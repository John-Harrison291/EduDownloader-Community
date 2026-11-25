"""Posse e recuperação conservadora de staging de componentes gerenciados."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_COMPONENTS = frozenset(
    {"yt-dlp", "libreoffice", "deno", "ffmpeg-ffprobe", "ocr", "catalogue"}
)
_MARKER = "operation.json"
_OWNER_LOCK = ".owner.lock"
_MAX_MARKER_BYTES = 4096
_OPERATION_ID = re.compile(r"[0-9a-f]{32}\Z")
_STAGES = frozenset(
    {"created", "download", "verified", "prepared", "installer", "verify"}
)


def _unsafe(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def ordinary_component_path(path: Path) -> bool:
    return not any(_unsafe(part) for part in (path, *path.parents))


def _windows_lock(handle, *, shared: bool) -> bool:
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    lock = ctypes.WinDLL("kernel32", use_last_error=True).LockFileEx
    lock.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(Overlapped),
    ]
    lock.restype = wintypes.BOOL
    flags = 1 if shared else 3
    return bool(
        lock(
            msvcrt.get_osfhandle(handle.fileno()),
            flags,
            0,
            1,
            0,
            ctypes.byref(Overlapped()),
        )
    )


class ComponentBusyError(RuntimeError):
    """Outra instância está alterando este componente."""


class ComponentFileLock:
    """Lock interprocesso por componente; o arquivo estável nunca é apagado."""

    def __init__(self, path: Path, *, shared: bool = False) -> None:
        self.path = path
        self.shared = shared
        self._file = None

    def acquire(self) -> bool:
        if not ordinary_component_path(self.path):
            raise OSError("unsafe_component_lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                if not _windows_lock(handle, shared=self.shared):
                    handle.close()
                    return False
            else:
                import fcntl

                mode = fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX
                fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            handle.close()
            return False
        self._file = handle
        return True

    def close(self) -> None:
        if self._file is None:
            return
        self._file.close()
        self._file = None

    def __enter__(self) -> ComponentFileLock:
        if not self.acquire():
            raise ComponentBusyError
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def component_lock(
    root: Path, component: str, *, shared: bool = False
) -> ComponentFileLock:
    if component not in _COMPONENTS or not ordinary_component_path(root):
        raise ValueError("invalid_component_root")
    return ComponentFileLock(root / ".locks" / f"{component}.lock", shared=shared)


def _stage_parent(root: Path, component: str) -> Path:
    if component not in _COMPONENTS or _unsafe(root):
        raise ValueError("invalid_component_root")
    parent = root / ".staging" / component
    if any(_unsafe(item) for item in (parent.parent, parent)):
        raise ValueError("unsafe_staging_root")
    return parent


def _marker_data(stage: Path, component: str) -> dict | None:
    try:
        marker = stage / _MARKER
        if (
            _unsafe(stage)
            or _unsafe(marker)
            or marker.stat().st_size > _MAX_MARKER_BYTES
        ):
            return None
        data = json.loads(marker.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or data.get("schema") != 1
            or data.get("component_id") != component
            or data.get("operation_id") != stage.name
            or _OPERATION_ID.fullmatch(stage.name) is None
            or not isinstance(data.get("started_at"), (int, float))
            or not math.isfinite(data["started_at"])
            or not isinstance(data.get("process_id"), int)
            or data["process_id"] <= 0
            or data.get("owned_paths") != ["."]
            or not isinstance(data.get("target_version"), str)
            or not 0 < len(data["target_version"]) <= 64
            or any(char in data["target_version"] for char in "/\\\0")
            or data.get("stage") not in _STAGES
            or not (stage / _OWNER_LOCK).is_file()
            or _unsafe(stage / _OWNER_LOCK)
        ):
            return None
        return data
    except (OSError, UnicodeError, ValueError):
        return None


def _safe_tree(stage: Path) -> bool:
    try:
        return all(not _unsafe(path) for path in (stage, *stage.rglob("*")))
    except OSError:
        return False


def cleanup_owned_stage(stage: Path, root: Path, component: str) -> bool:
    """Remove só árvore sob .staging com marker exato e sem reparse points."""
    parent = _stage_parent(root, component)
    if stage.parent != parent or _marker_data(stage, component) is None:
        return False
    if not _safe_tree(stage):
        return False
    owner = ComponentFileLock(stage / _OWNER_LOCK)
    if not owner.acquire():
        return False
    owner.close()
    shutil.rmtree(stage)
    return True


@dataclass
class ManagedStage:
    path: Path
    root: Path
    component: str
    owner: ComponentFileLock

    def set_stage(self, value: str) -> None:
        if value not in _STAGES:
            raise ValueError("invalid_operation_stage")
        data = _marker_data(self.path, self.component)
        if data is None:
            raise ValueError("invalid_operation_marker")
        data["stage"] = value
        _atomic_marker(self.path / _MARKER, data)

    def close(self) -> None:
        self.owner.close()

    def cleanup(self) -> bool:
        self.close()
        return cleanup_owned_stage(self.path, self.root, self.component)


def atomic_component_bytes(path: Path, data: bytes) -> None:
    if not ordinary_component_path(path):
        raise OSError("unsafe_component_metadata")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".metadata-", suffix=".tmp", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _atomic_marker(path: Path, data: dict) -> None:
    atomic_component_bytes(
        path,
        (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        ),
    )


def create_stage(root: Path, component: str, target_version: str) -> ManagedStage:
    parent = _stage_parent(root, component)
    parent.mkdir(parents=True, exist_ok=True)
    operation_id = uuid.uuid4().hex
    path = parent / operation_id
    path.mkdir()
    owner = ComponentFileLock(path / _OWNER_LOCK)
    if not owner.acquire():
        raise ComponentBusyError
    stage = ManagedStage(path, root, component, owner)
    try:
        _atomic_marker(
            path / _MARKER,
            {
                "schema": 1,
                "operation_id": operation_id,
                "component_id": component,
                "started_at": time.time(),
                "process_id": os.getpid(),
                "stage": "created",
                "owned_paths": ["."],
                "target_version": target_version,
            },
        )
    except Exception:
        owner.close()
        raise
    return stage


@dataclass(frozen=True)
class RecoveryReport:
    cleaned: int = 0
    active: int = 0
    unknown: int = 0


def recover_staging(
    root: Path, component: str, *, now: float | None = None
) -> RecoveryReport:
    """Limpa só operações inequivocamente órfãs; nunca toca diretório desconhecido."""
    parent = _stage_parent(root, component)
    if not parent.is_dir():
        return RecoveryReport()
    lock = component_lock(root, component)
    if not lock.acquire():
        return RecoveryReport(active=1)
    cleaned = active = unknown = 0
    try:
        current = time.time() if now is None else now
        for stage in parent.iterdir():
            if not stage.is_dir() or _unsafe(stage):
                unknown += 1
                continue
            data = _marker_data(stage, component)
            if data is None or current - data["started_at"] < 2:
                unknown += 1
                continue
            try:
                if cleanup_owned_stage(stage, root, component):
                    cleaned += 1
                else:
                    active += 1
            except OSError:
                unknown += 1
    finally:
        lock.close()
    return RecoveryReport(cleaned, active, unknown)
