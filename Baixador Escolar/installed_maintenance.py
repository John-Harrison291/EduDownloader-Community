"""Manutenção da instalação convencional executada no perfil do usuário."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path, PurePosixPath

from component_transactions import component_lock, recover_staging
from component_release_policy import YTDLP_NOTICE_NAMES
from constants import LOG_FILENAME
from libreoffice_image import OWNERSHIP_FILE, file_hash, is_redirected
from libreoffice_managed import AcquisitionError, documents_data_root
from paths import get_app_dir, get_community_install_root, get_runtime_state_dir


_YTDLP_VERSION = re.compile(r"20[0-9]{2}\.[0-9]{2}\.[0-9]{2}(?:\.[0-9]+)?")
_OFFICE_VERSION = re.compile(r"L(?:-repair-[0-9a-f]{8})?")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def command_exit(arguments: list[str]) -> int | None:
    if arguments[:1] == ["--verify-download-attachment"]:
        from windows_attachment import attachment_exit

        return attachment_exit(arguments)
    if arguments == ["--setup-component-updates"]:
        return update_installed_components()
    if arguments == ["--uninstall-user-components"]:
        return uninstall_current_user(False)
    if arguments == ["--uninstall-user-data"]:
        return uninstall_current_user(True)
    return None


def _ordinary(path: Path) -> bool:
    return not any(is_redirected(item) for item in (path, *path.parents))


def _json(path: Path, limit: int = 16 * 1024) -> dict:
    if not _ordinary(path) or path.stat().st_size > limit:
        raise ValueError("Inventário fora do perfil")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Inventário inválido")
    return value


def _remove_empty(directory: Path, boundary: Path) -> None:
    while directory != boundary and directory.is_relative_to(boundary):
        try:
            directory.rmdir()
        except OSError:
            break
        directory = directory.parent


def _owned_binary(path: Path, digest: object) -> bool:
    return (
        isinstance(digest, str)
        and _SHA256.fullmatch(digest) is not None
        and _ordinary(path)
        and path.is_file()
        and file_hash(path) == digest
    )


def _remove_yt_dlp(root: Path) -> None:
    directory = root / "yt-dlp"
    if not directory.is_dir() or not _ordinary(directory):
        return
    removed = set()
    for version in directory.iterdir():
        if not version.is_dir() or not _YTDLP_VERSION.fullmatch(version.name):
            continue
        try:
            marker = version / "metadata.json"
            info = _json(marker)
            binary = version / "yt-dlp.exe"
            if (
                info.get("component") != "yt-dlp"
                or info.get("version") != version.name
                or info.get("relative_path") != f"{version.name}/yt-dlp.exe"
                or not _owned_binary(binary, info.get("sha256"))
            ):
                continue
            binary.unlink()
            notices = info.get("notices", {})
            if isinstance(notices, dict):
                for name in YTDLP_NOTICE_NAMES:
                    notice = version / name
                    if _owned_binary(notice, notices.get(name)):
                        notice.unlink()
            marker.unlink()
            removed.add(version.name)
            _remove_empty(version, directory)
        except (OSError, ValueError):
            continue
    pointer = directory / "active.json"
    if pointer.exists():
        info = _json(pointer)
        if info.get("component") == "yt-dlp" and info.get("version") in removed:
            pointer.unlink()


def _relative_office_path(relative: str) -> PurePosixPath:
    path = PurePosixPath(relative)
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != relative
        or any(char in relative for char in "\\:\0")
    ):
        raise ValueError("Entrada do inventário inválida")
    return path


def _remove_office(root: Path, installation: Path) -> None:
    if not root.is_dir() or not _ordinary(root):
        return
    removed = set()
    for version in root.iterdir():
        if (
            not _OFFICE_VERSION.fullmatch(version.name)
            or not version.is_dir()
            or not _ordinary(version)
        ):
            continue
        marker = version / OWNERSHIP_FILE
        if not marker.is_file():
            continue
        inventory = _json(marker, limit=8 * 1024 * 1024)
        if inventory.get("schema") != 1 or inventory.get("installed_at") != str(
            installation
        ):
            continue
        files = inventory.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("Inventário do motor inválido")
        to_check = [
            (version.joinpath(*_relative_office_path(relative).parts), digest)
            for relative, digest in files.items()
        ]
        for path, digest in to_check:
            if path == marker:
                continue
            if _owned_binary(path, digest):
                path.unlink()
                _remove_empty(path.parent, version)
        marker.unlink()
        removed.add(version.name)
        _remove_empty(version, root)
    pointer = root / "active.json"
    if pointer.is_file():
        info = _json(pointer)
        signed_pointer = (
            set(info) == {"schema", "version", "identity", "relative_path"}
            and info["schema"] == 2
            and isinstance(info["identity"], str)
            and re.fullmatch(r"[0-9a-f]{24}", info["identity"]) is not None
        )
        if (
            (
                info.get("component_id") == "edudownloader.documents.libreoffice"
                or signed_pointer
            )
            and isinstance(info.get("relative_path"), str)
            and info["relative_path"] in removed
        ):
            pointer.unlink()


def cleanup_user_installation(
    installation: Path, runtime: Path, documents: Path, *, remove_preferences: bool
) -> None:
    managed = runtime / "Componentes"
    office = documents / "Componentes"
    for root, component, remove in (
        (managed, "yt-dlp", lambda: _remove_yt_dlp(managed)),
        (office, "libreoffice", lambda: _remove_office(office, installation)),
    ):
        if root.is_dir() and _ordinary(root):
            recover_staging(root, component)
            with component_lock(root, component):
                remove()
            _remove_empty(root / component, root)
    if remove_preferences and runtime.is_dir() and _ordinary(runtime):
        for file in (runtime / "settings.json", runtime / "Logs" / LOG_FILENAME):
            if _ordinary(file) and file.is_file():
                file.unlink()
        _remove_empty(runtime / "Logs", runtime)


def uninstall_current_user(remove_preferences: bool) -> int:
    installation = get_community_install_root()
    if installation is None or os.name != "nt" or not _ordinary(installation):
        return 2
    try:
        from component_updates import remove_owned_components
        from paths import get_app_dir

        remove_owned_components(get_app_dir())
        cleanup_user_installation(
            installation,
            get_runtime_state_dir(),
            documents_data_root(),
            remove_preferences=remove_preferences,
        )
    except (AcquisitionError, OSError, RuntimeError, ValueError):
        return 2
    return 0


def update_installed_components() -> int:
    """Consulta durante o Setup, no perfil do usuário, com o mesmo caminho da UI."""
    if os.name != "nt" or get_community_install_root() is None:
        return 2
    import ctypes

    if ctypes.windll.shell32.IsUserAnAdmin():
        return 2
    from component_manager import ComponentId, ComponentManager
    from component_updates import ComponentUpdateService
    from downloader import DownloadService
    from yt_dlp_update import UpdateCheckStatus, UpdateStatus, YtDlpUpdateService

    base = get_app_dir()
    manager = ComponentManager(base_dir=base)
    packages = ComponentUpdateService(base)
    cancel = threading.Event()
    updated = False
    try:
        packages.refresh_catalogue()
    except (OSError, ValueError, RuntimeError):
        pass
    for component in (ComponentId.DENO, ComponentId.FFMPEG_FFPROBE, ComponentId.OCR):
        try:
            candidate = packages.available(
                component, manager.refresh(component).version
            )
            if candidate is not None:
                result, _ = packages.update(candidate, cancel=cancel)
                updated |= result is UpdateStatus.UPDATED
        except (OSError, ValueError, RuntimeError):
            continue
    gate = DownloadService(base)
    try:
        service = YtDlpUpdateService(
            base,
            usage_gate=gate,
            approval=packages.approve_yt_dlp,
            notices_provider=packages.yt_dlp_notices,
        )
        check = service.check()
        if check.status is UpdateCheckStatus.UP_TO_DATE:
            return 3 if updated else 0
        if check.status is UpdateCheckStatus.NOT_APPROVED:
            return 3 if updated else 4
        if check.status is UpdateCheckStatus.CHECK_FAILED or check.release is None:
            return (
                3
                if updated
                else (5 if check.diagnostic_code == "connection_unavailable" else 6)
            )
        result = service.update(check.release, cancel=cancel)
        return 3 if updated or result.status is UpdateStatus.UPDATED else 7
    finally:
        gate.close()
