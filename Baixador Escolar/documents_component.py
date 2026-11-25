"""Validação local e descoberta limitada de LibreOffice externo, sem execução."""

from __future__ import annotations

import configparser
import os
import re
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from paths import get_app_dir


COMPONENT_ID: Final = "edudownloader.documents.user-provided-libreoffice"
COMPONENT_VERSION: Final = "user-provided-runtime-v1"
ENGINE_NAME: Final = "LibreOffice"
ENGINE_VERSION: Final = "26.8.3.1"
MAX_METADATA_BYTES: Final = 256 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT: Final = getattr(
    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400
)
_PYTHON_HOME_PATTERN: Final = re.compile(r"^python-core-[0-9]+(?:\.[0-9]+){2}$")


class DocumentsComponentStatus(str, Enum):
    """Estados públicos e estáveis da instalação local opcional."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    AVAILABLE = "AVAILABLE"
    INVALID = "INVALID"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    CORRUPTED = "CORRUPTED"


@dataclass(frozen=True, slots=True)
class DocumentsComponent:
    """Caminhos validados do runtime nativo externo."""

    root: Path
    engine_root: Path
    soffice_entrypoint: Path
    soffice_bin: Path
    launcher: Path
    python_home: Path
    python_runtime: Path
    component_version: str
    engine_version: str


@dataclass(frozen=True, slots=True)
class DocumentsComponentCheck:
    """Resultado seguro da validação da instalação local."""

    status: DocumentsComponentStatus
    component: DocumentsComponent | None
    diagnostic_code: str


class _RuntimeInvalid(ValueError):
    pass


class _VersionMismatch(ValueError):
    pass


class _RuntimeCorrupted(ValueError):
    pass


class DocumentsComponentService:
    """Valida uma raiz ou descobre candidatos locais conhecidos, sem rede."""

    def __init__(
        self, app_root: Path | None = None, *, expected_engine: str | None = None
    ) -> None:
        # Mantido para compatibilidade de construção/injeção. O diretório do
        # aplicativo nunca é sondado nem tratado como local implícito do motor.
        self._app_root = Path(app_root) if app_root is not None else get_app_dir()
        self._expected_engine = expected_engine

    def fast_check(
        self, component_root: Path | str | None = None
    ) -> DocumentsComponentCheck:
        """Valida identidade oficial e arquivos operacionais essenciais."""

        if component_root is None:
            return DocumentsComponentCheck(
                DocumentsComponentStatus.NOT_CONFIGURED,
                None,
                "documents_runtime_not_configured",
            )
        try:
            root = _validate_root(component_root)
            if (root / "App" / "AppInfo" / "appinfo.ini").is_file():
                raise _VersionMismatch
            component = (
                _load_system_runtime(root)
                if self._expected_engine is None
                else _load_system_runtime(root, expected_engine=self._expected_engine)
            )
        except _VersionMismatch:
            return DocumentsComponentCheck(
                DocumentsComponentStatus.VERSION_MISMATCH,
                None,
                "documents_runtime_version_mismatch",
            )
        except _RuntimeCorrupted:
            return DocumentsComponentCheck(
                DocumentsComponentStatus.CORRUPTED,
                None,
                "documents_runtime_incomplete",
            )
        except (
            _RuntimeInvalid,
            configparser.Error,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
        ):
            return DocumentsComponentCheck(
                DocumentsComponentStatus.INVALID,
                None,
                "documents_runtime_invalid",
            )
        return DocumentsComponentCheck(
            DocumentsComponentStatus.AVAILABLE,
            component,
            "documents_runtime_available",
        )

    def full_verify(
        self, component_root: Path | str | None = None
    ) -> DocumentsComponentCheck:
        """Repete a validação estrutural sem reivindicar hashes do usuário."""

        result = self.fast_check(component_root)
        if result.status is DocumentsComponentStatus.AVAILABLE:
            return DocumentsComponentCheck(
                result.status,
                result.component,
                "documents_runtime_full_verify_available",
            )
        return result

    def discover(
        self,
        preferred: Path | str | None = None,
        *,
        managed: tuple[Path, ...] = (),
        system: tuple[Path, ...] | None = None,
    ) -> DocumentsComponentCheck:
        """Sondagem limitada, offline; nunca executa candidatos para identificá-los."""
        candidates = (
            preferred,
            *(windows_libreoffice_roots() if system is None else system),
            *managed,
        )
        seen: set[str] = set()
        for candidate in candidates:
            if candidate is None:
                continue
            key = os.path.normcase(os.path.abspath(candidate))
            if key in seen:
                continue
            seen.add(key)
            result = self.fast_check(candidate)
            if result.status is DocumentsComponentStatus.AVAILABLE:
                return result
        return self.fast_check(None)


def windows_libreoffice_roots() -> tuple[Path, ...]:
    """App Paths oficial (ambas as views) e duas pastas padrão; não usa PATH."""
    if os.name != "nt":
        return ()
    import winreg

    roots: list[Path] = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe",
                0,
                winreg.KEY_READ | view,
            ) as key:
                value, kind = winreg.QueryValueEx(key, "")
            if kind == winreg.REG_SZ and isinstance(value, str):
                executable = Path(value.strip('"'))
                if (
                    executable.is_absolute()
                    and executable.name.lower() == "soffice.exe"
                    and executable.parent.name.lower() == "program"
                ):
                    roots.append(executable.parent.parent)
        except OSError:
            pass
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(variable)
        if value and Path(value).is_absolute():
            roots.append(Path(value) / "LibreOffice")
    return tuple(roots)


def _windows_file_version(path: Path) -> str:
    """Lê recurso VERSIONINFO sem carregar/executar o binário candidato."""
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("version", use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    api.VerQueryValueW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not 0 < size <= MAX_METADATA_BYTES:
        raise _RuntimeCorrupted
    buffer = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.GetFileVersionInfoW(
        str(path), 0, size, buffer
    ) or not api.VerQueryValueW(
        buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)
    ):
        raise _RuntimeCorrupted
    if length.value < 52:
        raise _RuntimeCorrupted
    values = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    if values[0] != 0xFEEF04BD:
        raise _RuntimeCorrupted
    return ".".join(
        str(part)
        for part in (
            values[2] >> 16,
            values[2] & 65535,
            values[3] >> 16,
            values[3] & 65535,
        )
    )


def _required_pe(root: Path, relative: str) -> Path:
    path = _required_file(root, relative)
    with path.open("rb") as source:
        header = source.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise _RuntimeCorrupted
        offset = int.from_bytes(header[60:64], "little")
        if not 64 <= offset <= 1024 * 1024:
            raise _RuntimeCorrupted
        source.seek(offset)
        if source.read(6) != b"PE\0\0\x64\x86":
            raise _RuntimeCorrupted
    return path


def _load_system_runtime(
    root: Path, *, expected_engine: str | None = None
) -> DocumentsComponent:
    """Valida o layout nativo e a versão do motor aprovado."""
    program = _required_directory(root, "program")
    version = _read_ini(root, program / "version.ini")
    if version.get("Version", "Vendor", fallback="") != "The Document Foundation":
        raise _RuntimeInvalid
    executable = _required_pe(root, "program/soffice.exe")
    engine_version = _windows_file_version(executable)
    entrypoint = _required_pe(root, "program/soffice.com")
    binary = _required_pe(root, "program/soffice.bin")
    if expected_engine is None and engine_version != ENGINE_VERSION:
        from constants import PRODUCT_EDITION, ProductEdition

        if PRODUCT_EDITION is ProductEdition.COMMUNITY:
            from libreoffice_managed import AcquisitionError, documents_data_root
            from component_updates import signed_office_root

            try:
                if signed_office_root(documents_data_root()) == root:
                    expected_engine = engine_version
            except AcquisitionError:
                pass
    expected = expected_engine or ENGINE_VERSION
    if engine_version != expected or any(
        _windows_file_version(path) != expected for path in (entrypoint, binary)
    ):
        raise _VersionMismatch
    _required_pe(root, "program/mergedlo.dll")
    _required_directory(root, "share/registry")
    homes = [
        item for item in program.iterdir() if _PYTHON_HOME_PATTERN.fullmatch(item.name)
    ]
    if len(homes) != 1:
        raise _RuntimeCorrupted
    home = _required_existing_path(root, homes[0], directory=True)
    python = _required_pe(root, (home / "bin/python.exe").relative_to(root).as_posix())
    return DocumentsComponent(
        root,
        root,
        entrypoint,
        binary,
        executable,
        home,
        python,
        COMPONENT_VERSION,
        engine_version,
    )


def _validate_root(value: Path | str) -> Path:
    try:
        candidate = Path(value)
    except (OSError, TypeError, ValueError) as error:
        raise _RuntimeInvalid from error
    if not candidate.is_absolute():
        raise _RuntimeInvalid
    root = Path(os.path.abspath(candidate))
    try:
        metadata = os.stat(root, follow_symlinks=False)
    except OSError as error:
        raise _RuntimeInvalid from error
    if not stat.S_ISDIR(metadata.st_mode) or _is_link_or_reparse(metadata):
        raise _RuntimeInvalid
    return root


def _read_ini(root: Path, path: Path) -> configparser.ConfigParser:
    _required_existing_path(root, path, directory=False)
    metadata = os.stat(path, follow_symlinks=False)
    if metadata.st_size <= 0 or metadata.st_size > MAX_METADATA_BYTES:
        raise _RuntimeInvalid
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return parser


def _required_directory(root: Path, relative: str) -> Path:
    return _required_existing_path(
        root, root.joinpath(*relative.split("/")), directory=True
    )


def _required_file(root: Path, relative: str) -> Path:
    return _required_existing_path(
        root, root.joinpath(*relative.split("/")), directory=False
    )


def _required_existing_path(root: Path, path: Path, *, directory: bool) -> Path:
    root = Path(os.path.abspath(root))
    candidate = Path(os.path.abspath(path))
    try:
        if os.path.commonpath((root, candidate)) != str(root):
            raise _RuntimeInvalid
    except ValueError as error:
        raise _RuntimeInvalid from error
    try:
        metadata = os.stat(candidate, follow_symlinks=False)
    except OSError as error:
        raise _RuntimeCorrupted from error
    expected = (
        stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    )
    if not expected or _is_link_or_reparse(metadata):
        raise _RuntimeCorrupted
    current = candidate if directory else candidate.parent
    while current != root:
        metadata = os.stat(current, follow_symlinks=False)
        if not stat.S_ISDIR(metadata.st_mode) or _is_link_or_reparse(metadata):
            raise _RuntimeCorrupted
        current = current.parent
    return candidate


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        attributes & _FILE_ATTRIBUTE_REPARSE_POINT
    )
