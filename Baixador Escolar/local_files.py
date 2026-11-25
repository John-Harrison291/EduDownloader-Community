"""Catálogo local não visual para arquivos escolhidos explicitamente."""

from __future__ import annotations

import ctypes
import ntpath
import os
import re
import stat
import subprocess
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final


class LocalFileCategory(str, Enum):
    """Categorias reconhecidas pelo catálogo local."""

    DOCUMENT = "document"
    PDF = "pdf"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class LocalFileSort(str, Enum):
    """Ordenações públicas e deliberadamente pequenas do catálogo local."""

    NAME = "name"
    RECENT = "recent"


@dataclass(frozen=True, slots=True)
class LocalFileEntry:
    """Snapshot imutável dos metadados básicos de um arquivo reconhecido."""

    path: Path
    category: LocalFileCategory
    size_bytes: int
    modified_timestamp: float

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def suffix(self) -> str:
        return self.path.suffix


@dataclass(frozen=True, slots=True)
class LocalFileProjection:
    """Resultado imutável de uma consulta, antes e depois do limite visual."""

    entries: tuple[LocalFileEntry, ...]
    total_count: int


class LocalFilesError(Exception):
    """Erro seguro que pode ser apresentado pela futura camada visual."""


_SUFFIX_CATEGORIES: Final = {
    ".docx": LocalFileCategory.DOCUMENT,
    ".doc": LocalFileCategory.DOCUMENT,
    ".odt": LocalFileCategory.DOCUMENT,
    ".txt": LocalFileCategory.DOCUMENT,
    ".pdf": LocalFileCategory.PDF,
    ".jpg": LocalFileCategory.IMAGE,
    ".jpeg": LocalFileCategory.IMAGE,
    ".png": LocalFileCategory.IMAGE,
    ".mp4": LocalFileCategory.VIDEO,
    ".mkv": LocalFileCategory.VIDEO,
    ".webm": LocalFileCategory.VIDEO,
    ".avi": LocalFileCategory.VIDEO,
    ".mov": LocalFileCategory.VIDEO,
    ".m4v": LocalFileCategory.VIDEO,
    ".mp3": LocalFileCategory.AUDIO,
    ".wav": LocalFileCategory.AUDIO,
    ".m4a": LocalFileCategory.AUDIO,
    ".aac": LocalFileCategory.AUDIO,
    ".flac": LocalFileCategory.AUDIO,
    ".ogg": LocalFileCategory.AUDIO,
    ".wma": LocalFileCategory.AUDIO,
}
_NATURAL_NUMBER = re.compile(r"([0-9]+)")
_FILE_ATTRIBUTE_REPARSE_POINT: Final = getattr(
    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400
)
_DRIVE_UNKNOWN: Final = 0
_DRIVE_NO_ROOT_DIR: Final = 1
_DRIVE_REMOVABLE: Final = 2
_DRIVE_FIXED: Final = 3
_DRIVE_REMOTE: Final = 4
_DRIVE_CDROM: Final = 5
_DRIVE_RAMDISK: Final = 6
_ALLOWED_DRIVE_TYPES: Final = frozenset(
    {_DRIVE_REMOVABLE, _DRIVE_FIXED, _DRIVE_CDROM, _DRIVE_RAMDISK}
)


def classify_local_file(path: Path | str) -> LocalFileCategory | None:
    """Classifica somente extensões reconhecidas, sem abrir o arquivo."""

    try:
        suffix = Path(path).suffix.casefold()
    except (OSError, TypeError, ValueError):
        return None
    return _SUFFIX_CATEGORIES.get(suffix)


def validate_local_regular_file(path: Path | str) -> Path:
    """Valida um arquivo local absoluto sem seguir links ou reparse points."""

    try:
        raw_path = os.fspath(path)
    except (OSError, TypeError, ValueError) as error:
        raise LocalFilesError("Selecione um arquivo local válido.") from error

    if _looks_like_unc_path(raw_path):
        raise LocalFilesError("Arquivos de rede não são suportados.")

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        raise LocalFilesError("Selecione um arquivo local com caminho absoluto.")

    candidate = Path(os.path.abspath(raw_path))
    if os.name == "nt":
        drive_type = _windows_drive_type(candidate)
        if drive_type == _DRIVE_REMOTE:
            raise LocalFilesError("Arquivos de rede não são suportados.")
        if drive_type not in _ALLOWED_DRIVE_TYPES:
            raise LocalFilesError("O arquivo selecionado não está disponível.")
    try:
        metadata = os.stat(candidate, follow_symlinks=False)
    except FileNotFoundError as error:
        raise LocalFilesError("O arquivo selecionado não está disponível.") from error
    except PermissionError as error:
        raise LocalFilesError(
            "Sem permissão para acessar o arquivo selecionado."
        ) from error
    except OSError as error:
        raise LocalFilesError(
            "Não foi possível acessar o arquivo selecionado."
        ) from error
    if not stat.S_ISREG(metadata.st_mode) or _is_link_or_reparse(metadata):
        raise LocalFilesError(
            "O arquivo selecionado não está disponível como arquivo regular."
        )
    return candidate


def validate_local_output_path(
    path: Path | str,
    *,
    inputs: Iterable[Path | str] = (),
) -> Path:
    """Valida um output local absoluto e distinto dos inputs informados."""

    try:
        raw_path = os.fspath(path)
    except (OSError, TypeError, ValueError) as error:
        raise LocalFilesError("O arquivo de saída não é válido.") from error
    if _looks_like_unc_path(raw_path):
        raise LocalFilesError("Arquivos de rede não são suportados.")

    candidate = Path(raw_path)
    if not candidate.is_absolute() or not candidate.name:
        raise LocalFilesError("Escolha um arquivo de saída com caminho absoluto.")
    candidate = Path(os.path.abspath(raw_path))
    parent = _validate_local_directory(candidate.parent)
    candidate = parent / candidate.name
    require_distinct_output_path(candidate, inputs)

    try:
        metadata = os.stat(candidate, follow_symlinks=False)
    except FileNotFoundError:
        return candidate
    except PermissionError as error:
        raise LocalFilesError(
            "Sem permissão para acessar o arquivo de saída."
        ) from error
    except OSError as error:
        raise LocalFilesError("Não foi possível acessar o arquivo de saída.") from error
    if not stat.S_ISREG(metadata.st_mode) or _is_link_or_reparse(metadata):
        raise LocalFilesError("O arquivo de saída não é um arquivo regular válido.")
    return candidate


def windows_paths_equivalent(first: Path | str, second: Path | str) -> bool:
    """Compara caminhos pela identidade textual case-insensitive do Windows."""

    try:
        first_key = ntpath.normcase(ntpath.abspath(os.fspath(first)))
        second_key = ntpath.normcase(ntpath.abspath(os.fspath(second)))
    except (OSError, TypeError, ValueError) as error:
        raise LocalFilesError("Não foi possível comparar os caminhos.") from error
    return first_key == second_key


def require_distinct_output_path(
    output: Path | str, inputs: Iterable[Path | str]
) -> Path:
    """Rejeita um output textualmente equivalente a qualquer input no Windows."""

    try:
        output_path = Path(output)
    except (OSError, TypeError, ValueError) as error:
        raise LocalFilesError("O arquivo de saída não é válido.") from error
    if any(windows_paths_equivalent(output_path, source) for source in inputs):
        raise LocalFilesError("O arquivo de saída não pode ser um arquivo de entrada.")
    return output_path


def list_local_files(directory: Path | str) -> tuple[LocalFileEntry, ...]:
    """Lista um snapshot não recursivo dos arquivos reconhecidos da pasta."""

    directory_path = _validate_local_directory(directory)
    entries: list[LocalFileEntry] = []
    try:
        with os.scandir(directory_path) as scanned:
            for candidate in scanned:
                category = classify_local_file(candidate.name)
                if category is None:
                    continue
                try:
                    if not candidate.is_file(follow_symlinks=False):
                        continue
                    metadata = candidate.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except PermissionError as error:
                    raise LocalFilesError(
                        "Sem permissão para ler a pasta selecionada."
                    ) from error
                except OSError as error:
                    raise LocalFilesError(
                        "Não foi possível ler a pasta selecionada."
                    ) from error
                if _is_link_or_reparse(metadata):
                    continue
                entries.append(
                    LocalFileEntry(
                        path=directory_path / candidate.name,
                        category=category,
                        size_bytes=metadata.st_size,
                        modified_timestamp=metadata.st_mtime,
                    )
                )
    except LocalFilesError:
        raise
    except FileNotFoundError as error:
        raise LocalFilesError(
            "A pasta selecionada não está mais disponível."
        ) from error
    except PermissionError as error:
        raise LocalFilesError("Sem permissão para ler a pasta selecionada.") from error
    except OSError as error:
        raise LocalFilesError("Não foi possível ler a pasta selecionada.") from error
    return tuple(sorted(entries, key=_entry_sort_key))


def filter_local_files(
    entries: Iterable[LocalFileEntry],
    category: LocalFileCategory | None = None,
    query: str = "",
) -> tuple[LocalFileEntry, ...]:
    """Filtra um snapshot existente por categoria e substring normalizada."""

    if category is not None and not isinstance(category, LocalFileCategory):
        raise TypeError("category deve ser LocalFileCategory ou None")
    if not isinstance(query, str):
        raise TypeError("query deve ser texto")
    normalized_query = _normalized_text(query)
    return tuple(
        entry
        for entry in entries
        if (category is None or entry.category is category)
        and (not normalized_query or normalized_query in _normalized_text(entry.name))
    )


def project_local_files(
    entries: Iterable[LocalFileEntry],
    *,
    category: LocalFileCategory | None = None,
    query: str = "",
    sort: LocalFileSort = LocalFileSort.NAME,
    limit: int | None = None,
) -> LocalFileProjection:
    """Compõe busca, categoria, ordenação e limite sem acessar o filesystem."""

    if not isinstance(sort, LocalFileSort):
        raise TypeError("sort deve ser LocalFileSort")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
        raise TypeError("limit deve ser inteiro ou None")
    if limit is not None and limit < 1:
        raise ValueError("limit deve ser positivo")

    filtered = filter_local_files(entries, category=category, query=query)
    if sort is LocalFileSort.RECENT:
        ordered = tuple(
            sorted(
                filtered,
                key=lambda entry: (-entry.modified_timestamp, _entry_sort_key(entry)),
            )
        )
    else:
        ordered = tuple(sorted(filtered, key=_entry_sort_key))
    projected = ordered if limit is None else ordered[:limit]
    return LocalFileProjection(projected, len(ordered))


def revalidate_local_file(
    entry: LocalFileEntry, directory: Path | str
) -> LocalFileEntry:
    """Revalida um item antes de uma ação explícita e atualiza seu snapshot."""

    if not isinstance(entry, LocalFileEntry):
        raise LocalFilesError("O arquivo selecionado não é válido.")
    directory_path = _validate_local_directory(directory)
    try:
        entry_path = Path(os.path.abspath(os.fspath(entry.path)))
    except (OSError, TypeError, ValueError) as error:
        raise LocalFilesError("O arquivo selecionado não é válido.") from error
    if _windows_path_key(entry_path.parent) != _windows_path_key(directory_path):
        raise LocalFilesError(
            "O arquivo selecionado não pertence diretamente à pasta escolhida."
        )
    category = classify_local_file(entry_path)
    if category is None or category is not entry.category:
        raise LocalFilesError("O arquivo selecionado não é compatível.")
    try:
        metadata = os.stat(entry_path, follow_symlinks=False)
    except FileNotFoundError as error:
        raise LocalFilesError(
            "O arquivo selecionado não está mais disponível."
        ) from error
    except PermissionError as error:
        raise LocalFilesError(
            "Sem permissão para acessar o arquivo selecionado."
        ) from error
    except OSError as error:
        raise LocalFilesError(
            "Não foi possível acessar o arquivo selecionado."
        ) from error
    if not stat.S_ISREG(metadata.st_mode) or _is_link_or_reparse(metadata):
        raise LocalFilesError(
            "O arquivo selecionado não está mais disponível como arquivo regular."
        )
    return LocalFileEntry(
        path=entry_path,
        category=category,
        size_bytes=metadata.st_size,
        modified_timestamp=metadata.st_mtime,
    )


def open_local_file(entry: LocalFileEntry, directory: Path | str) -> Path:
    """Abre um arquivo reconhecido no aplicativo padrão do Windows."""

    validated = revalidate_local_file(entry, directory)
    if os.name != "nt":
        raise LocalFilesError(
            "A abertura de arquivos está disponível apenas no Windows."
        )
    try:
        os.startfile(str(validated.path))  # type: ignore[attr-defined]
    except OSError as error:
        raise LocalFilesError(
            "Não foi possível abrir o arquivo selecionado."
        ) from error
    return validated.path


def reveal_local_file(entry: LocalFileEntry, directory: Path | str) -> Path:
    """Mostra um arquivo reconhecido e selecionado no Windows Explorer."""

    validated = revalidate_local_file(entry, directory)
    if os.name != "nt":
        raise LocalFilesError(
            "A localização de arquivos está disponível apenas no Windows."
        )
    try:
        subprocess.Popen(
            ["explorer.exe", "/select,", str(validated.path)],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as error:
        raise LocalFilesError(
            "Não foi possível mostrar o arquivo selecionado no Explorer."
        ) from error
    return validated.path


def _validate_local_directory(value: Path | str) -> Path:
    try:
        raw_path = os.fspath(value)
    except (OSError, TypeError, ValueError) as error:
        raise LocalFilesError("Selecione uma pasta local válida.") from error

    if _looks_like_unc_path(raw_path):
        raise LocalFilesError("Pastas de rede não são suportadas.")

    directory = Path(raw_path)
    if not directory.is_absolute():
        raise LocalFilesError("Selecione uma pasta local com caminho absoluto.")

    directory = Path(os.path.abspath(raw_path))
    if os.name == "nt":
        drive_type = _windows_drive_type(directory)
        if drive_type == _DRIVE_REMOTE:
            raise LocalFilesError("Pastas de rede não são suportadas.")
        if drive_type not in _ALLOWED_DRIVE_TYPES:
            raise LocalFilesError("A pasta selecionada não está disponível.")
    try:
        metadata = os.stat(directory, follow_symlinks=False)
    except FileNotFoundError as error:
        raise LocalFilesError("A pasta selecionada não está disponível.") from error
    except PermissionError as error:
        raise LocalFilesError("Sem permissão para ler a pasta selecionada.") from error
    except OSError as error:
        raise LocalFilesError(
            "Não foi possível acessar a pasta selecionada."
        ) from error
    if _is_link_or_reparse(metadata):
        raise LocalFilesError(
            "Links e pontos de nova análise não são aceitos como pasta."
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise LocalFilesError("O caminho selecionado não é uma pasta.")
    return directory


def _windows_drive_type(path: Path) -> int:
    if os.name != "nt":
        return _DRIVE_FIXED
    root = path.anchor
    if not root:
        return _DRIVE_UNKNOWN
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_drive_type = kernel32.GetDriveTypeW
        get_drive_type.argtypes = [ctypes.c_wchar_p]
        get_drive_type.restype = ctypes.c_uint
        return int(get_drive_type(root))
    except (AttributeError, OSError):
        return _DRIVE_UNKNOWN


def _looks_like_unc_path(value: object) -> bool:
    try:
        raw = os.fspath(value)
    except TypeError:
        return False
    if isinstance(raw, bytes):
        return raw.replace(b"/", b"\\").startswith(b"\\\\")
    return raw.replace("/", "\\").startswith("\\\\")


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        attributes & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _windows_path_key(path: Path) -> str:
    return ntpath.normcase(ntpath.abspath(os.fspath(path)))


def _normalized_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _entry_sort_key(
    entry: LocalFileEntry,
) -> tuple[tuple[tuple[int, int | str], ...], str, str]:
    name = entry.name
    normalized = _normalized_text(name)
    natural = tuple(
        (0, int(part)) if part.isascii() and part.isdigit() else (1, part)
        for part in _NATURAL_NUMBER.split(normalized)
        if part
    )
    return natural, normalized, name
