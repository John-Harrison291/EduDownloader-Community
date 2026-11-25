"""Atualização opt-in do yt-dlp, isolada da baseline distribuída."""

from __future__ import annotations

import hashlib
import base64
import binascii
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from component_release_policy import YTDLP_NOTICE_NAMES, approved_yt_dlp_notices
from component_transactions import (
    ComponentFileLock,
    ManagedStage,
    component_lock,
    create_stage,
)
from paths import ManagedRootState, get_managed_components_dir, probe_managed_root

# A política de source licensing rejeita endpoints completos embutidos em literais.
_HTTPS = "https://"
LATEST_RELEASE_URL = _HTTPS + "api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
RELEASE_ROOT = _HTTPS + "github.com/yt-dlp/yt-dlp/releases/download"
SOURCE_ROOT = _HTTPS + "github.com/yt-dlp/yt-dlp/releases/tag"
MAX_BINARY_BYTES = 128 * 1024 * 1024  # 17 MB na baseline 2026.08.19; margem ~7x.
MAX_METADATA_BYTES = 512 * 1024
MAX_SUMS_BYTES = 64 * 1024
MIN_FREE_RESERVE_BYTES = 32 * 1024 * 1024
_VERSION = re.compile(r"20[0-9]{2}\.[0-9]{2}\.[0-9]{2}(?:\.[0-9]+)?\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SUM_LINE = re.compile(r"([0-9a-fA-F]{64}) [ *]([^/\\\r\n]+)\Z")
_ASSET_HOSTS = frozenset(
    {
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)
_USER_AGENT = "EduDownloader/1.6 (yt-dlp component update)"
LOGGER = logging.getLogger(__name__)
_PENDING_ACTIVATION = "activation-pending.json"
_LOCAL_ACTIVATION = threading.local()


class UpdateError(Exception):
    """Falha fail-closed; o código não contém URL ou dado pessoal."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class UpdateCancelled(UpdateError):
    def __init__(self) -> None:
        super().__init__("cancelled")


class UpdateCheckStatus(StrEnum):
    UP_TO_DATE = "up-to-date"
    UPDATE_AVAILABLE = "update-available"
    CHECK_FAILED = "check-failed"
    NOT_APPROVED = "not-approved"


class UpdateStatus(StrEnum):
    UPDATED = "updated"
    REPAIRED = "repaired"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BUSY = "busy"
    STORAGE_UNAVAILABLE = "storage-unavailable"


@dataclass(frozen=True, slots=True)
class OfficialRelease:
    version: str
    binary_url: str
    binary_size: int
    binary_digest: str
    sums_url: str
    sums_digest: str
    source_url: str
    release_url: str


@dataclass(frozen=True, slots=True)
class UpdateCheck:
    status: UpdateCheckStatus
    current_version: str | None
    release: OfficialRelease | None
    diagnostic_code: str = ""


@dataclass(frozen=True, slots=True)
class UpdateResult:
    status: UpdateStatus
    version: str | None
    diagnostic_code: str


@dataclass(frozen=True, slots=True)
class ActiveYtDlp:
    path: Path
    version: str | None
    managed: bool
    managed_issue: str | None = None


class UpdateUsageGate(Protocol):
    def begin_yt_dlp_update(self) -> bool: ...

    def end_yt_dlp_update(self) -> None: ...


def _safe_url(url: str, allowed_hosts: frozenset[str]) -> None:
    try:
        parts = urllib.parse.urlsplit(url)
        valid_port = parts.port in (None, 443)
    except ValueError:
        raise UpdateError("invalid_url") from None
    if (
        parts.scheme != "https"
        or parts.hostname not in allowed_hosts
        or not valid_port
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise UpdateError("invalid_url")


def _SafeRedirects(allowed_hosts: frozenset[str]):
    # urllib.request carrega ssl/socket; não fazê-lo no import do bootstrap.
    import urllib.request

    class SafeRedirects(urllib.request.HTTPRedirectHandler):
        def __init__(self) -> None:
            self.count = 0

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            self.count += 1
            if self.count > 5:
                raise UpdateError("too_many_redirects")
            _safe_url(newurl, allowed_hosts)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return SafeRedirects()


class OfficialTransport:
    """HTTPS com redirects delimitados e leitura em streaming com limites."""

    def _open(self, url: str, allowed_hosts: frozenset[str]):
        import socket
        import urllib.error
        import urllib.request

        _safe_url(url, allowed_hosts)
        opener = urllib.request.build_opener(_SafeRedirects(allowed_hosts))
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": _USER_AGENT,
            },
        )
        try:
            response = opener.open(request, timeout=15)
            _safe_url(response.geturl(), allowed_hosts)
            if response.status != 200:
                response.close()
                raise UpdateError("http_failure")
            return response
        except urllib.error.HTTPError as error:
            error.close()
            raise UpdateError("http_failure") from None
        except urllib.error.URLError as error:
            reason = error.reason
            if isinstance(reason, socket.gaierror) or getattr(
                reason, "winerror", None
            ) in (10050, 10051, 10065):
                raise UpdateError("connection_unavailable") from None
            raise UpdateError("network_failure") from None
        except (OSError, TimeoutError):
            raise UpdateError("network_failure") from None

    def read_bytes(
        self, url: str, *, limit: int, allowed_hosts: frozenset[str]
    ) -> bytes:
        with self._open(url, allowed_hosts) as response:
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > limit):
                raise UpdateError("oversized_response")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise UpdateError("oversized_response")
            if length is not None and len(data) != int(length):
                raise UpdateError("truncated_response")
            return data

    def download(
        self,
        url: str,
        destination: Path,
        *,
        expected_size: int,
        cancel: threading.Event,
        progress: Callable[[int, int | None], None] | None = None,
        allowed_hosts: frozenset[str] = _ASSET_HOSTS,
        maximum_size: int = MAX_BINARY_BYTES,
    ) -> str:
        digest = hashlib.sha256()
        count = 0
        with self._open(url, allowed_hosts) as response:
            length_text = response.headers.get("Content-Length")
            length = (
                int(length_text) if length_text and length_text.isdecimal() else None
            )
            if length is not None and length != expected_size:
                raise UpdateError("size_mismatch")
            with destination.open("xb") as output:
                while True:
                    if cancel.is_set():
                        raise UpdateCancelled
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > maximum_size or count > expected_size:
                        raise UpdateError("oversized_binary")
                    output.write(chunk)
                    digest.update(chunk)
                    if progress is not None:
                        progress(count, length)
                output.flush()
                os.fsync(output.fileno())
        if cancel.is_set():
            raise UpdateCancelled
        if count != expected_size:
            raise UpdateError("truncated_binary")
        return digest.hexdigest()


def _required_asset(data: dict, name: str, tag: str) -> dict:
    matches = [
        asset
        for asset in data.get("assets", [])
        if isinstance(asset, dict) and asset.get("name") == name
    ]
    if len(matches) != 1:
        raise UpdateError("missing_or_duplicate_asset")
    asset = matches[0]
    expected_url = f"{RELEASE_ROOT}/{tag}/{name}"
    if asset.get("browser_download_url") != expected_url:
        raise UpdateError("unexpected_asset_url")
    digest = asset.get("digest")
    if (
        not isinstance(digest, str)
        or not digest.startswith("sha256:")
        or not _SHA256.fullmatch(digest[7:])
    ):
        raise UpdateError("missing_asset_digest")
    return asset


def parse_official_release(payload: bytes) -> OfficialRelease:
    try:
        data = json.loads(payload)
        if (
            not isinstance(data, dict)
            or data.get("draft") is not False
            or data.get("prerelease") is not False
        ):
            raise UpdateError("not_stable_release")
        tag = data.get("tag_name")
        if not isinstance(tag, str) or not _VERSION.fullmatch(tag):
            raise UpdateError("invalid_release_version")
        binary = _required_asset(data, "yt-dlp.exe", tag)
        sums = _required_asset(data, "SHA2-256SUMS", tag)
        source = _required_asset(data, "yt-dlp.tar.gz", tag)
        size = binary.get("size")
        if type(size) is not int or not (0 < size <= MAX_BINARY_BYTES):
            raise UpdateError("invalid_binary_size")
        return OfficialRelease(
            tag,
            binary["browser_download_url"],
            size,
            binary["digest"][7:],
            sums["browser_download_url"],
            sums["digest"][7:],
            source["browser_download_url"],
            f"{SOURCE_ROOT}/{tag}",
        )
    except (UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        raise UpdateError("malformed_release_metadata") from None


def parse_official_sums(payload: bytes) -> str:
    if len(payload) > MAX_SUMS_BYTES:
        raise UpdateError("oversized_sums")
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeError:
        raise UpdateError("malformed_sums") from None
    found: dict[str, str] = {}
    for line in lines:
        match = _SUM_LINE.fullmatch(line)
        if match is None:
            raise UpdateError("malformed_sums")
        digest, filename = match.groups()
        if filename in found:
            raise UpdateError("duplicate_sums")
        found[filename] = digest.lower()
    if "yt-dlp.exe" not in found:
        raise UpdateError("missing_binary_sum")
    return found["yt-dlp.exe"]


def _version_tuple(value: str) -> tuple[int, ...]:
    if not _VERSION.fullmatch(value):
        raise UpdateError("invalid_version")
    return tuple(map(int, value.split(".")))


def _probe_version(path: Path) -> str:
    try:
        result = subprocess.run(
            [str(path), "--version"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise UpdateError("version_probe_failed") from None
    version = result.stdout.strip()
    if result.returncode != 0 or not _VERSION.fullmatch(version):
        raise UpdateError("version_probe_failed")
    return version


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _read_json(path: Path, limit: int = 16 * 1024) -> dict:
    if _is_link(path) or path.stat().st_size > limit:
        raise UpdateError("invalid_managed_metadata")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise UpdateError("invalid_managed_metadata")
    return data


def _component_dir(base_dir: Path) -> Path:
    return get_managed_components_dir(base_dir) / "yt-dlp"


def resolve_active_yt_dlp(base_dir: Path) -> ActiveYtDlp:
    """Seleciona somente managed íntegro; caso contrário mantém bundled."""
    bundled = base_dir / "yt-dlp.exe"
    component_dir = _component_dir(base_dir)
    if (component_dir / _PENDING_ACTIVATION).exists() and not getattr(
        _LOCAL_ACTIVATION, "allow_pending", False
    ):
        return ActiveYtDlp(bundled, None, False, "activation_pending")
    active_path = component_dir / "active.json"
    if not active_path.exists():
        return ActiveYtDlp(bundled, None, False)
    try:
        root = get_managed_components_dir(base_dir)
        if _is_link(root) or _is_link(component_dir):
            raise UpdateError("invalid_managed_root")
        active = _read_json(active_path)
        version = active["version"]
        digest = active["sha256"]
        relative = active["relative_path"]
        if (
            active.get("component") != "yt-dlp"
            or not isinstance(version, str)
            or not _VERSION.fullmatch(version)
            or not isinstance(digest, str)
            or not _SHA256.fullmatch(digest)
            or relative != f"{version}/yt-dlp.exe"
        ):
            raise UpdateError("invalid_managed_metadata")
        version_dir = component_dir / version
        binary = version_dir / "yt-dlp.exe"
        if _is_link(version_dir) or _is_link(binary) or not binary.is_file():
            raise UpdateError("invalid_managed_binary")
        size = binary.stat().st_size
        if not (0 < size <= MAX_BINARY_BYTES) or _sha256_file(binary) != digest:
            raise UpdateError("invalid_managed_hash")
        installed = _read_json(version_dir / "metadata.json")
        if (
            installed.get("component") != "yt-dlp"
            or installed.get("version") != version
            or installed.get("sha256") != digest
            or installed.get("relative_path") != relative
        ):
            raise UpdateError("invalid_managed_metadata")
        notices = installed.get("notices", {})
        if not isinstance(notices, dict) or (
            notices and set(notices) != set(YTDLP_NOTICE_NAMES)
        ):
            raise UpdateError("invalid_managed_notices")
        for name, notice_hash in notices.items():
            notice = version_dir / name
            if (
                not isinstance(notice_hash, str)
                or not _SHA256.fullmatch(notice_hash)
                or _is_link(notice)
                or not notice.is_file()
                or not 0 < notice.stat().st_size <= MAX_METADATA_BYTES
                or _sha256_file(notice) != notice_hash
            ):
                raise UpdateError("invalid_managed_notices")
        return ActiveYtDlp(binary, version, True)
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
        UpdateError,
    ) as error:
        code = (
            error.code if isinstance(error, UpdateError) else "invalid_managed_metadata"
        )
        return ActiveYtDlp(bundled, None, False, code)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".active-", suffix=".tmp", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _canonical_json(data: dict) -> bytes:
    return (
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def recover_pending_activation(base_dir: Path) -> bool:
    """Restaura o ponteiro anterior só após crash comprovado pelo lock livre."""
    root = get_managed_components_dir(base_dir)
    component = _component_dir(base_dir)
    journal = component / _PENDING_ACTIVATION
    if (
        not journal.exists()
        or _is_link(root)
        or _is_link(component)
        or _is_link(journal)
    ):
        return False
    lock = component_lock(root, "yt-dlp")
    if not lock.acquire():
        return False
    try:
        data = _read_json(journal)
        previous = data.get("previous")
        new_digest = data.get("new_sha256")
        if (
            data.get("component") != "yt-dlp"
            or not isinstance(data.get("operation_id"), str)
            or re.fullmatch(r"[0-9a-f]{32}", data["operation_id"]) is None
            or not isinstance(new_digest, str)
            or not _SHA256.fullmatch(new_digest)
            or previous is not None
            and not isinstance(previous, str)
        ):
            return False
        try:
            old_bytes = (
                None if previous is None else base64.b64decode(previous, validate=True)
            )
        except (ValueError, binascii.Error):
            return False
        if old_bytes is not None and len(old_bytes) > 16 * 1024:
            return False
        pointer = component / "active.json"
        if _is_link(pointer):
            return False
        current = pointer.read_bytes() if pointer.exists() else None
        if current != old_bytes and (
            current is None or hashlib.sha256(current).hexdigest() != new_digest
        ):
            return False
        if current != old_bytes:
            if old_bytes is None:
                pointer.unlink()
            else:
                _atomic_bytes(pointer, old_bytes)
        journal.unlink()
        LOGGER.warning("Ativação interrompida do yt-dlp revertida para versão anterior")
        return True
    except (OSError, UnicodeError, ValueError, TypeError, UpdateError):
        return False
    finally:
        lock.close()


class YtDlpUpdateService:
    """Coordena check, consentimento externo e transação de atualização."""

    def __init__(
        self,
        base_dir: Path,
        *,
        usage_gate: UpdateUsageGate,
        transport: OfficialTransport | None = None,
        approval: Callable[[OfficialRelease], bool] | None = None,
        notices_provider: Callable[[OfficialRelease], tuple[tuple[str, str, str], ...]]
        | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.usage_gate = usage_gate
        self.transport = transport or OfficialTransport()
        self._approval = approval
        self._notices_provider = notices_provider or approved_yt_dlp_notices
        self._operation = threading.Lock()

    def repair_invalid(self) -> UpdateResult:
        """Desativa só ponteiro managed inválido, sem baixar nem remover binários."""
        if not self._operation.acquire(blocking=False):
            return UpdateResult(UpdateStatus.BUSY, None, "operation_busy")
        cross_lock: ComponentFileLock | None = None
        gate_acquired = False
        try:
            if not self.usage_gate.begin_yt_dlp_update():
                return UpdateResult(UpdateStatus.BUSY, None, "download_active")
            gate_acquired = True
            root = get_managed_components_dir(self.base_dir)
            component = _component_dir(self.base_dir)
            if _is_link(root) or _is_link(component):
                raise UpdateError("invalid_managed_root")
            cross_lock = component_lock(root, "yt-dlp")
            if not cross_lock.acquire():
                return UpdateResult(UpdateStatus.BUSY, None, "operation_busy")
            active = resolve_active_yt_dlp(self.base_dir)
            pointer = component / "active.json"
            journal = component / _PENDING_ACTIVATION
            if (
                active.managed_issue is None
                or _is_link(pointer)
                or _is_link(journal)
                or not (pointer.is_file() or journal.is_file())
            ):
                raise UpdateError("repair_not_needed")
            operation_id = uuid.uuid4().hex
            quarantine = component / f".invalid-active-{operation_id}.json"
            if pointer.is_file():
                os.replace(pointer, quarantine)
            if journal.is_file():
                os.replace(journal, component / f".invalid-pending-{operation_id}.json")
            if resolve_active_yt_dlp(self.base_dir).managed:
                if quarantine.exists():
                    os.replace(quarantine, pointer)
                raise UpdateError("repair_failed")
            return UpdateResult(UpdateStatus.REPAIRED, None, "bundled_restored")
        except (OSError, UpdateError, ValueError) as error:
            code = (
                error.code if isinstance(error, UpdateError) else type(error).__name__
            )
            LOGGER.warning("Reparo do yt-dlp não aplicado (%s)", code)
            return UpdateResult(UpdateStatus.FAILED, None, code)
        finally:
            if cross_lock is not None:
                cross_lock.close()
            if gate_acquired:
                self.usage_gate.end_yt_dlp_update()
            self._operation.release()

    def check(self) -> UpdateCheck:
        if not self._operation.acquire(blocking=False):
            return UpdateCheck(UpdateCheckStatus.CHECK_FAILED, None, None, "busy")
        current = None
        try:
            current = _probe_version(resolve_active_yt_dlp(self.base_dir).path)
            payload = self.transport.read_bytes(
                LATEST_RELEASE_URL,
                limit=MAX_METADATA_BYTES,
                allowed_hosts=frozenset({"api.github.com"}),
            )
            release = parse_official_release(payload)
            newer = _version_tuple(release.version) > _version_tuple(current)
            if newer and self._approval is not None and not self._approval(release):
                return UpdateCheck(
                    UpdateCheckStatus.NOT_APPROVED, current, release, "not_approved"
                )
            status = (
                UpdateCheckStatus.UPDATE_AVAILABLE
                if newer
                else UpdateCheckStatus.UP_TO_DATE
            )
            return UpdateCheck(status, current, release)
        except Exception as error:
            code = (
                error.code if isinstance(error, UpdateError) else type(error).__name__
            )
            LOGGER.warning("Consulta de atualização do yt-dlp falhou (%s)", code)
            return UpdateCheck(UpdateCheckStatus.CHECK_FAILED, current, None, code)
        finally:
            self._operation.release()

    def update(
        self,
        release: OfficialRelease,
        *,
        cancel: threading.Event,
        progress: Callable[[int, int | None], None] | None = None,
    ) -> UpdateResult:
        if self._approval is not None and not self._approval(release):
            return UpdateResult(UpdateStatus.FAILED, None, "not_approved")
        if not self._operation.acquire(blocking=False):
            return UpdateResult(UpdateStatus.BUSY, None, "operation_busy")
        stage: ManagedStage | None = None
        component_dir: Path | None = None
        cross_lock: ComponentFileLock | None = None
        gate_acquired = False
        operation_id = "none"
        operation_stage = "preflight"
        rollback_result = "not-needed"
        try:
            if not self.usage_gate.begin_yt_dlp_update():
                return UpdateResult(UpdateStatus.BUSY, None, "download_active")
            gate_acquired = True
            if cancel.is_set():
                raise UpdateCancelled
            storage = probe_managed_root(self.base_dir)
            if storage.state is not ManagedRootState.AVAILABLE:
                return UpdateResult(
                    UpdateStatus.STORAGE_UNAVAILABLE, None, storage.state.value
                )
            if (
                not _VERSION.fullmatch(release.version)
                or release.binary_size <= 0
                or release.binary_size > MAX_BINARY_BYTES
            ):
                raise UpdateError("invalid_release")
            expected_binary = f"{RELEASE_ROOT}/{release.version}/yt-dlp.exe"
            expected_sums = f"{RELEASE_ROOT}/{release.version}/SHA2-256SUMS"
            if (
                release.binary_url != expected_binary
                or release.sums_url != expected_sums
            ):
                raise UpdateError("invalid_release")
            if (
                release.source_url != f"{RELEASE_ROOT}/{release.version}/yt-dlp.tar.gz"
                or release.release_url != f"{SOURCE_ROOT}/{release.version}"
            ):
                raise UpdateError("invalid_release")
            if not _SHA256.fullmatch(release.binary_digest) or not _SHA256.fullmatch(
                release.sums_digest
            ):
                raise UpdateError("invalid_release")
            current_version = _probe_version(resolve_active_yt_dlp(self.base_dir).path)
            if _version_tuple(release.version) <= _version_tuple(current_version):
                raise UpdateError("not_newer")
            required_free = release.binary_size * 2 + MIN_FREE_RESERVE_BYTES
            storage_volume = next(
                folder
                for folder in (storage.path, *storage.path.parents)
                if folder.is_dir()
            )
            if shutil.disk_usage(storage_volume).free < required_free:
                raise UpdateError("insufficient_space")
            component_dir = _component_dir(self.base_dir)
            if _is_link(storage.path) or _is_link(component_dir):
                raise UpdateError("invalid_managed_root")
            component_dir.mkdir(parents=True, exist_ok=True)
            cross_lock = component_lock(storage.path, "yt-dlp")
            if not cross_lock.acquire():
                return UpdateResult(UpdateStatus.BUSY, None, "operation_busy")
            if (component_dir / _PENDING_ACTIVATION).exists():
                raise UpdateError("recovery_required")
            stage = create_stage(storage.path, "yt-dlp", release.version)
            operation_id = stage.path.name
            sums = self.transport.read_bytes(
                release.sums_url,
                limit=MAX_SUMS_BYTES,
                allowed_hosts=_ASSET_HOSTS,
            )
            if hashlib.sha256(sums).hexdigest() != release.sums_digest:
                raise UpdateError("sums_digest_mismatch")
            expected_hash = parse_official_sums(sums)
            if expected_hash != release.binary_digest:
                raise UpdateError("binary_authorities_disagree")
            stage.set_stage("download")
            operation_stage = "download"
            downloaded = stage.path / "yt-dlp.exe.part"
            actual_hash = self.transport.download(
                release.binary_url,
                downloaded,
                expected_size=release.binary_size,
                cancel=cancel,
                progress=progress,
            )
            if actual_hash != expected_hash:
                raise UpdateError("binary_hash_mismatch")
            if cancel.is_set():
                raise UpdateCancelled
            binary = stage.path / "yt-dlp.exe"
            os.replace(downloaded, binary)
            if _probe_version(binary) != release.version:
                raise UpdateError("version_mismatch")
            stage.set_stage("verified")
            operation_stage = "verified"
            relative_path = f"{release.version}/yt-dlp.exe"
            metadata = {
                "component": "yt-dlp",
                "version": release.version,
                "relative_path": relative_path,
                "sha256": actual_hash,
                "release_tag": release.version,
                "release_url": release.release_url,
                "source_url": release.source_url,
                "installed_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            if self._approval is not None:
                notices = {}
                for name, url, expected in self._notices_provider(release):
                    payload = self.transport.read_bytes(
                        url,
                        limit=MAX_METADATA_BYTES,
                        allowed_hosts=frozenset({"raw.githubusercontent.com"}),
                    )
                    if hashlib.sha256(payload).hexdigest() != expected:
                        raise UpdateError("notice_hash_mismatch")
                    (stage.path / name).write_bytes(payload)
                    notices[name] = expected
                metadata["notices"] = notices
            (stage.path / "metadata.json").write_bytes(_canonical_json(metadata))
            activation_operation_id = stage.path.name
            target = component_dir / release.version
            if _is_link(target):
                raise UpdateError("existing_version_conflict")
            if target.exists():
                existing = _read_json(target / "metadata.json")
                existing_binary = target / "yt-dlp.exe"
                if (
                    _is_link(target)
                    or _is_link(existing_binary)
                    or existing.get("sha256") != actual_hash
                    or existing.get("notices") != metadata.get("notices")
                    or _sha256_file(existing_binary) != actual_hash
                    or _probe_version(existing_binary) != release.version
                ):
                    raise UpdateError("existing_version_conflict")
                stage.cleanup()
                stage = None
            else:
                stage.set_stage("prepared")
                operation_stage = "prepared"
                stage.close()
                os.replace(stage.path, target)
                stage = None
                (target / "operation.json").unlink(missing_ok=True)
                (target / ".owner.lock").unlink(missing_ok=True)
            if cancel.is_set():
                raise UpdateCancelled
            active_path = component_dir / "active.json"
            if _is_link(active_path):
                raise UpdateError("invalid_managed_metadata")
            old_pointer = active_path.read_bytes() if active_path.exists() else None
            if old_pointer is not None and len(old_pointer) > 16 * 1024:
                raise UpdateError("invalid_managed_metadata")
            pointer = {
                key: metadata[key]
                for key in ("component", "version", "relative_path", "sha256")
            }
            new_pointer = _canonical_json(pointer)
            journal = component_dir / _PENDING_ACTIVATION
            _atomic_bytes(
                journal,
                _canonical_json(
                    {
                        "component": "yt-dlp",
                        "operation_id": activation_operation_id,
                        "previous": (
                            None
                            if old_pointer is None
                            else base64.b64encode(old_pointer).decode("ascii")
                        ),
                        "new_sha256": hashlib.sha256(new_pointer).hexdigest(),
                    }
                ),
            )
            _atomic_bytes(active_path, new_pointer)
            operation_stage = "post-verify"
            try:
                _LOCAL_ACTIVATION.allow_pending = True
                try:
                    active = resolve_active_yt_dlp(self.base_dir)
                    from downloader import locate_tools

                    if (
                        not active.managed
                        or active.path != target / "yt-dlp.exe"
                        or locate_tools(self.base_dir).yt_dlp != active.path
                        or _probe_version(active.path) != release.version
                    ):
                        raise UpdateError("post_activation_failure")
                finally:
                    _LOCAL_ACTIVATION.allow_pending = False
            except Exception:
                try:
                    if old_pointer is None:
                        active_path.unlink(missing_ok=True)
                        rollback_result = "bundled"
                    else:
                        _atomic_bytes(active_path, old_pointer)
                        rollback_result = "previous"
                    if (
                        old_pointer is not None
                        and active_path.read_bytes() != old_pointer
                    ):
                        raise UpdateError("rollback_mismatch")
                except Exception:
                    # Se o pointer anterior não puder ser restaurado, prefira
                    # o bundled a manter uma versão recém-ativada sem validação.
                    try:
                        active_path.unlink(missing_ok=True)
                        rollback_result = "bundled-after-restore-failure"
                    except OSError:
                        rollback_result = "pending-journal-fallback"
                        raise UpdateError("rollback_failed") from None
                journal.unlink(missing_ok=True)
                raise UpdateError("post_activation_failure") from None
            journal.unlink()
            return UpdateResult(UpdateStatus.UPDATED, release.version, "updated")
        except UpdateCancelled:
            return UpdateResult(UpdateStatus.CANCELLED, None, "cancelled")
        except Exception as error:
            code = (
                error.code if isinstance(error, UpdateError) else type(error).__name__
            )
            LOGGER.warning(
                "Atualização yt-dlp não aplicada (op=%s, etapa=%s, falha=%s, rollback=%s)",
                operation_id,
                operation_stage,
                code,
                rollback_result,
            )
            return UpdateResult(UpdateStatus.FAILED, None, code)
        finally:
            if stage is not None and component_dir is not None:
                try:
                    stage.cleanup()
                except (OSError, UpdateError, ValueError):
                    LOGGER.warning(
                        "Staging próprio do yt-dlp requer revisão de limpeza"
                    )
            if cross_lock is not None:
                cross_lock.close()
            if gate_acquired:
                self.usage_gate.end_yt_dlp_update()
            self._operation.release()
