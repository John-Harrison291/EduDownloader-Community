"""Leitura e gravação das preferências locais em JSON."""

from __future__ import annotations

import json
import ntpath
import os
import tempfile
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Any
from collections.abc import Callable

from constants import (
    CONTENT_TYPES,
    DEFAULT_SETTINGS,
    TEXT_SCALE_LEVELS,
    THEMES,
    VIDEO_QUALITIES,
)
from paths import get_settings_path

MAX_FAVORITE_FOLDERS = 10
_MAX_WINDOWS_PATH_LENGTH = 32_767
_INVALID_WINDOWS_PATH_CHARACTERS = frozenset('<>"|?*')
DIALOG_FOLDER_KEYS = frozenset(
    {
        "downloads.output",
        "pdf.input",
        "pdf.output",
        "pdf_word.input",
        "pdf_word.output",
        "documents.input",
        "documents.output",
        "media.input",
        "media.output",
    }
)

PDF_PREFERENCE_CHOICES = {
    "images_paper": ("A4", "Carta"),
    "images_orientation": ("Automática", "Retrato", "Paisagem"),
    "images_margin": ("Normal", "Pequena", "Sem margem"),
    "images_per_page": ("1 por página", "2 por página", "4 por página"),
    "pdf_images_format": ("PNG", "JPG"),
    "pdf_images_quality": ("Padrão", "Alta"),
    "poster_paper": ("A4", "Carta"),
    "poster_orientation": ("Automática", "Retrato", "Paisagem"),
    "poster_grid": ("2 × 2", "3 × 3", "4 × 4"),
    "poster_overlap": ("Pequena", "Nenhuma"),
}


def normalize_pdf_preferences(value):
    if not isinstance(value, dict):
        return {}
    result = {
        key: item
        for key, item in value.items()
        if key in PDF_PREFERENCE_CHOICES
        and isinstance(item, str)
        and item in PDF_PREFERENCE_CHOICES[key]
    }
    if type(value.get("poster_crop_marks")) is bool:
        result["poster_crop_marks"] = value["poster_crop_marks"]
    return result


class FavoriteFolderResult(StrEnum):
    """Resultados controlados das mutações explícitas de favoritos."""

    ADDED = "added"
    ALREADY_EXISTS = "already_exists"
    LIMIT_REACHED = "limit_reached"
    INVALID_PATH = "invalid_path"
    REMOVED = "removed"
    NOT_FOUND = "not_found"


def default_settings() -> dict[str, Any]:
    """Retorna uma cópia dos padrões para evitar alterações globais."""

    defaults = DEFAULT_SETTINGS.copy()
    defaults["favorite_folders"] = []
    return defaults


def normalize_settings(data: object) -> dict[str, Any]:
    """Mantém somente valores reconhecidos e completa itens ausentes."""
    normalized = default_settings()
    if not isinstance(data, dict):
        return normalized

    validators = {
        "tema": THEMES,
        "ultimo_tipo": CONTENT_TYPES,
        "ultima_qualidade": VIDEO_QUALITIES,
    }
    for key, valid_values in validators.items():
        value = data.get(key)
        if isinstance(value, str) and value in valid_values:
            normalized[key] = value
    text_scale = data.get("text_scale")
    if type(text_scale) is int and text_scale in TEXT_SCALE_LEVELS:
        normalized["text_scale"] = text_scale
    normalized["favorite_folders"] = _normalize_favorite_folders(
        data.get("favorite_folders")
    )
    component_path = data.get("documents_component_path")
    if (
        isinstance(component_path, str)
        and favorite_folder_comparison_key(component_path) is not None
    ):
        normalized["documents_component_path"] = component_path
    if data.get("documents_component_origin") == "MANAGED":
        normalized["documents_component_origin"] = "MANAGED"
    folders = normalize_dialog_folders(data.get("dialog_folders"))
    if folders:
        normalized["dialog_folders"] = folders
    pdf = normalize_pdf_preferences(data.get("pdf_preferences"))
    if pdf:
        normalized["pdf_preferences"] = pdf
    return normalized


def normalize_dialog_folders(value: object) -> dict[str, str]:
    """Allow only bounded local folder preferences; never inspect them on load."""
    if not isinstance(value, dict):
        return {}
    return {
        key: folder
        for key, folder in value.items()
        if key in DIALOG_FOLDER_KEYS
        and isinstance(folder, str)
        and favorite_folder_comparison_key(folder) is not None
    }


class DialogFolderPreferences:
    """Small shared dialog memory; persistence is injected only by the shell."""

    def __init__(
        self, folders=None, persist: Callable[[dict[str, str]], None] | None = None
    ):
        self._folders = normalize_dialog_folders(folders)
        self._persist = persist

    def available(self, key: str) -> Path | None:
        folder = self._folders.get(key)
        if folder:
            try:
                path = Path(folder)
                if path.is_dir():
                    return path
            except OSError:
                pass
        return None

    def remember(self, key: str, folder: Path) -> None:
        value = str(folder)
        if (
            not normalize_dialog_folders({key: value})
            or self._folders.get(key) == value
        ):
            return
        self._folders[key] = value
        if self._persist is not None:
            self._persist(dict(self._folders))

    def choose(self, dialog, key: str, *, directory: bool = False, **options):
        initial = self.available(key)
        if initial is not None:
            options["initialdir"] = str(initial)
        selected = dialog(**options)
        if selected:
            first = selected[0] if isinstance(selected, (tuple, list)) else selected
            path = Path(first)
            self.remember(key, path if directory else path.parent)
        return selected


class _UnreadableSettings(dict):
    """Session defaults cannot replace an existing file that was not read.

    Keep the guard with the values until a successful reload. The shell already
    handles OSError while saving, so tools remain usable without losing data.
    """

    def copy(self):
        return type(self)(self)


def save_settings(
    data: dict[str, Any], settings_path: Path | None = None
) -> dict[str, Any]:
    """Normaliza e grava as configurações; retorna o conteúdo salvo."""
    if isinstance(data, _UnreadableSettings):
        raise OSError(
            "As preferências originais não foram lidas; reabra após verificar o arquivo."
        )
    path = settings_path or get_settings_path()
    normalized = normalize_settings(data)
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.stem}-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(normalized, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return normalized


def load_settings(settings_path: Path | None = None) -> dict[str, Any]:
    """Recover session defaults without overwriting unreadable existing data."""
    path = settings_path or get_settings_path()
    needs_repair = False

    try:
        with path.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
        if not isinstance(raw_data, dict):
            return _UnreadableSettings(default_settings())
        settings = normalize_settings(raw_data)
        needs_repair = settings != raw_data
    except FileNotFoundError:
        settings = default_settings()
        needs_repair = True
    except (json.JSONDecodeError, UnicodeError, OSError, TypeError):
        return _UnreadableSettings(default_settings())

    if needs_repair:
        try:
            save_settings(settings, path)
        except OSError:
            # Um pendrive protegido contra escrita não deve impedir a abertura.
            pass
    return settings


def favorite_folder_comparison_key(folder: Path | str) -> str | None:
    """Produz chave Windows equivalente sem consultar ou resolver o caminho."""

    raw = str(folder)
    if (
        not raw
        or len(raw) > _MAX_WINDOWS_PATH_LENGTH
        or raw != raw.strip()
        or "\0" in raw
        or raw.startswith(("\\\\", "//"))
    ):
        return None
    drive, _tail = ntpath.splitdrive(raw)
    if len(drive) != 2 or drive[1] != ":" or not drive[0].isalpha():
        return None
    if not ntpath.isabs(raw):
        return None
    if any(
        ord(character) < 32
        or character in _INVALID_WINDOWS_PATH_CHARACTERS
        or character == ":"
        for character in _tail
    ):
        return None
    normalized = ntpath.normpath(raw)
    return unicodedata.normalize("NFC", normalized).casefold()


def get_favorite_folders(settings_path: Path | None = None) -> tuple[str, ...]:
    """Retorna favoritos persistidos sem acessar as pastas apontadas."""

    settings = load_settings(settings_path)
    return tuple(settings["favorite_folders"])


def add_favorite_folder(
    folder: Path | str, settings_path: Path | None = None
) -> FavoriteFolderResult:
    """Persiste uma pasta favorita somente após esta chamada explícita."""

    comparison_key = favorite_folder_comparison_key(folder)
    if comparison_key is None:
        return FavoriteFolderResult.INVALID_PATH

    settings = load_settings(settings_path)
    favorites = list(settings["favorite_folders"])
    if any(
        favorite_folder_comparison_key(current) == comparison_key
        for current in favorites
    ):
        return FavoriteFolderResult.ALREADY_EXISTS
    if len(favorites) >= MAX_FAVORITE_FOLDERS:
        return FavoriteFolderResult.LIMIT_REACHED

    favorites.append(str(folder))
    settings["favorite_folders"] = favorites
    save_settings(settings, settings_path)
    return FavoriteFolderResult.ADDED


def remove_favorite_folder(
    folder: Path | str, settings_path: Path | None = None
) -> FavoriteFolderResult:
    """Remove apenas a entrada equivalente; nunca toca na pasta física."""

    comparison_key = favorite_folder_comparison_key(folder)
    if comparison_key is None:
        return FavoriteFolderResult.INVALID_PATH

    settings = load_settings(settings_path)
    favorites = list(settings["favorite_folders"])
    remaining = [
        current
        for current in favorites
        if favorite_folder_comparison_key(current) != comparison_key
    ]
    if len(remaining) == len(favorites):
        return FavoriteFolderResult.NOT_FOUND

    settings["favorite_folders"] = remaining
    save_settings(settings, settings_path)
    return FavoriteFolderResult.REMOVED


def is_favorite_folder(folder: Path | str, settings_path: Path | None = None) -> bool:
    """Consulta equivalência sem exigir que a pasta exista."""

    comparison_key = favorite_folder_comparison_key(folder)
    if comparison_key is None:
        return False
    return any(
        favorite_folder_comparison_key(current) == comparison_key
        for current in get_favorite_folders(settings_path)
    )


def _normalize_favorite_folders(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in value:
        if not isinstance(candidate, str):
            continue
        comparison_key = favorite_folder_comparison_key(candidate)
        if comparison_key is None or comparison_key in seen:
            continue
        normalized.append(candidate)
        seen.add(comparison_key)
        if len(normalized) == MAX_FAVORITE_FOLDERS:
            break
    return normalized
