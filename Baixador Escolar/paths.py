"""Caminhos portáteis usados pelo aplicativo."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from constants import LOG_FILENAME

COMMUNITY_INSTALL_MARKER = "EduDownloader.Community.installed"


class InvalidLocalDataPath(RuntimeError):
    """LOCALAPPDATA indica um caminho inválido."""


class LocalDataPathUnavailable(RuntimeError):
    """O perfil local do Windows não está disponível."""


def get_app_dir() -> Path:
    """Retorna a pasta do projeto ou, futuramente, do executável empacotado."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_downloads_dir(base_dir: Path | None = None) -> Path:
    """Frozen defaults use the Windows user folder; explicit QA roots stay local.

    Custom destinations are resolved by the downloader before this default.
    Legacy files/preferences are neither moved nor rewritten here.
    """
    if getattr(sys, "frozen", False) and (
        base_dir is None or base_dir.resolve() == get_app_dir()
    ):
        known = _known_downloads_folder()
        if known is not None:
            return known / "EduDownloader"
        try:
            return get_runtime_state_dir() / "Downloads"
        except (
            InvalidLocalDataPath,
            LocalDataPathUnavailable,
        ):
            raise OSError("A pasta de dados do usuário não está disponível.") from None
    return (base_dir or get_app_dir()) / "Downloads"


def _known_downloads_folder() -> Path | None:
    """Resolve redirected Downloads without creating or probing the directory."""
    if os.name != "nt":
        return None
    import ctypes
    import uuid

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    identifier = (ctypes.c_byte * 16).from_buffer_copy(
        uuid.UUID("374de290-123f-4565-9164-39c4925e467b").bytes_le
    )
    pointer = ctypes.c_void_p()
    try:
        if (
            shell.SHGetKnownFolderPath(
                ctypes.byref(identifier), 0x4000, None, ctypes.byref(pointer)
            )
            != 0
            or not pointer.value
        ):
            return None
        value = ctypes.wstring_at(pointer)
        path = Path(value)
        if (
            not value
            or any(c in value for c in "\0\r\n")
            or not path.is_absolute()
            or path.parent == path
            or ".." in path.parts
        ):
            return None
        return path
    finally:
        if pointer.value:
            ole.CoTaskMemFree(pointer)


def get_settings_path(base_dir: Path | None = None) -> Path:
    """Frozen preferences are per user, outside the program directory."""
    return get_runtime_state_dir(base_dir) / "settings.json"


def get_runtime_state_dir(base_dir: Path | None = None) -> Path:
    """Keep development/explicit test roots; frozen runtime never writes app root.

    A missing/invalid user profile fails closed, without an app-root fallback.
    """
    if getattr(sys, "frozen", False) and (
        base_dir is None or base_dir.resolve() == get_app_dir()
    ):
        return (
            _validated_local_app_data(None) / "EduDownloader" / "Community2" / "Runtime"
        )
    return base_dir or get_app_dir()


def get_tool_path(filename: str, base_dir: Path | None = None) -> Path:
    """Retorna o caminho de um executável localizado junto ao aplicativo."""
    return (base_dir or get_app_dir()) / filename


def get_managed_components_dir(base_dir: Path | None = None) -> Path:
    """Em instalação convencional, mantém atualizações na área do usuário."""
    if get_community_install_root(base_dir) is not None:
        return get_runtime_state_dir(base_dir) / "Componentes"
    return get_bundled_components_dir(base_dir)


def get_bundled_components_dir(base_dir: Path | None = None) -> Path:
    """Componentes entregues junto com o executável, como o OCR."""
    return (base_dir or get_app_dir()) / "Componentes"


def get_community_install_root(base_dir: Path | None = None) -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    app_dir = get_app_dir()
    if (
        base_dir is not None and base_dir.resolve() != app_dir
    ) or app_dir.parent.name != "Programa":
        return None
    marker = app_dir / COMMUNITY_INSTALL_MARKER
    if marker.is_symlink() or not marker.is_file():
        return None
    return app_dir.parent.parent


class ManagedRootState(StrEnum):
    AVAILABLE = "available"
    READ_ONLY = "read-only"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ManagedRootCheck:
    path: Path
    state: ManagedRootState


def probe_managed_root(base_dir: Path | None = None) -> ManagedRootCheck:
    """Sonda escrita temporária, sem criar Componentes ou escolher fallback."""
    base = base_dir if base_dir is not None else get_app_dir()
    root = get_managed_components_dir(base)
    try:
        boundary = (
            _validated_local_app_data(None)
            if get_community_install_root(base) is not None
            else base
        )
        probe_dir = root
        while not probe_dir.exists() and probe_dir != boundary:
            if probe_dir.is_symlink() or probe_dir.is_junction():
                return ManagedRootCheck(root, ManagedRootState.UNAVAILABLE)
            probe_dir = probe_dir.parent
        if not probe_dir.is_dir() or any(
            path.is_symlink() or path.is_junction()
            for path in (probe_dir, *probe_dir.parents)
        ):
            return ManagedRootCheck(root, ManagedRootState.UNAVAILABLE)
        with tempfile.TemporaryFile(dir=probe_dir):
            pass
    except PermissionError:
        return ManagedRootCheck(root, ManagedRootState.READ_ONLY)
    except OSError:
        return ManagedRootCheck(root, ManagedRootState.UNAVAILABLE)
    return ManagedRootCheck(root, ManagedRootState.AVAILABLE)


def documents_conversion_temp_parent() -> Path:
    """Mantém o perfil e os arquivos do LibreOffice fora da instalação e do TEMP externo."""
    local = _validated_local_app_data(None)
    if (
        not local.is_dir()
        or str(local).startswith(("\\\\", "//"))
        or len(str(local)) > 120
        or any(
            path.is_symlink() or path.is_junction() for path in (local, *local.parents)
        )
    ):
        raise OSError("Área temporária curta do LibreOffice indisponível")
    return local


def get_logs_dir(base_dir: Path | None = None) -> Path:
    """Frozen logs are per user; explicit development roots stay portable."""
    return get_runtime_state_dir(base_dir) / "Logs"


def get_log_path(base_dir: Path | None = None) -> Path:
    """Retorna o caminho do arquivo principal de log."""
    return get_logs_dir(base_dir) / LOG_FILENAME


def ensure_downloads_dir(base_dir: Path | None = None) -> Path:
    """Cria a pasta Downloads, quando necessário, e retorna seu caminho."""
    downloads_dir = get_downloads_dir(base_dir)
    downloads_dir.mkdir(parents=True, exist_ok=True)
    return downloads_dir


def open_downloads_dir(base_dir: Path | None = None) -> Path:
    """Cria e abre a pasta Downloads no Explorador de Arquivos do Windows."""
    downloads_dir = ensure_downloads_dir(base_dir)
    if os.name != "nt":
        raise OSError("A abertura da pasta está disponível apenas no Windows.")
    os.startfile(downloads_dir)  # type: ignore[attr-defined]
    return downloads_dir


def _validated_local_app_data(value: str | Path | None) -> Path:
    raw_value: object = os.environ.get("LOCALAPPDATA") if value is None else value
    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        raise LocalDataPathUnavailable
    if not isinstance(raw_value, (str, Path)) or isinstance(raw_value, bool):
        raise InvalidLocalDataPath

    raw_text = str(raw_value)
    if (
        not raw_text
        or "\x00" in raw_text
        or any(character in raw_text for character in ("\r", "\n"))
    ):
        raise InvalidLocalDataPath
    try:
        base_dir = Path(raw_text)
    except (OSError, TypeError, ValueError):
        raise InvalidLocalDataPath from None
    if (
        not base_dir.is_absolute()
        or base_dir.parent == base_dir
        or any(part in {".", ".."} for part in base_dir.parts)
    ):
        raise InvalidLocalDataPath
    return base_dir
