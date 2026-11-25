"""Perfil de imagem administrativa baseado nos recursos de interface do MSI."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath


_CATALOG_NAME = "libreoffice-ui-resources.txt"
IMAGE_FILES = ("libreoffice-image.json", _CATALOG_NAME, "libreoffice-signatures.json")
_KEEP = {"common", "en_US", "pt_BR"}
_TRANSLATION = re.compile(
    r"program/resource/([A-Za-z0-9_@-]+)/LC_MESSAGES/[A-Za-z0-9_-]+\.mo"
)
OWNERSHIP_FILE = ".edudownloader-office.json"


def profile_directory() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "installer"


def is_redirected(path: Path) -> bool:
    try:
        status = path.lstat()
        return bool(
            stat.S_ISLNK(status.st_mode)
            or getattr(status, "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
    except FileNotFoundError:
        return False


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record_office_ownership(root: Path, installed_at: Path) -> None:
    """Registra o conteúdo produzido em um destino próprio recém-criado."""
    if any(is_redirected(path) for path in (root, *root.parents)):
        raise ValueError("Destino redirecionado")
    items = {}
    for path in sorted(root.rglob("*")):
        if is_redirected(path):
            raise ValueError("Arquivo redirecionado na imagem")
        if path.is_file():
            items[path.relative_to(root).as_posix()] = file_hash(path)
    if not items:
        raise ValueError("Imagem vazia")
    with (root / OWNERSHIP_FILE).open("x", encoding="utf-8") as output:
        json.dump(
            {"schema": 1, "installed_at": str(installed_at), "files": items}, output
        )


def read_removal_catalog(source: Path) -> tuple[dict, tuple[tuple[str, int], ...]]:
    profile = json.loads((source / "libreoffice-image.json").read_text("ascii"))
    content = (source / _CATALOG_NAME).read_text("ascii")
    if (
        hashlib.sha256(content.encode("ascii")).hexdigest()
        != profile["catalog_sha256_lf"]
    ):
        raise ValueError("O catálogo de recursos do LibreOffice foi alterado")
    rows: list[tuple[str, int]] = []
    paths: set[str] = set()
    for line in content.splitlines():
        path, size = line.split("|")
        entry = _TRANSLATION.fullmatch(path)
        size_bytes = int(size)
        if (
            entry is None
            or entry[1] in _KEEP
            or path.casefold() in paths
            or size_bytes <= 0
        ):
            raise ValueError("O catálogo contém recurso fora do perfil de interface")
        paths.add(path.casefold())
        rows.append((path, size_bytes))
    if (
        len(rows) != profile["catalog_removed_files"]
        or sum(size for _, size in rows) != profile["catalog_removed_bytes"]
    ):
        raise ValueError("O catálogo de recursos diverge do inventário")
    if (
        profile["administrative_image_bytes"]
        - profile["administrative_msi_copy_bytes"]
        - profile["catalog_removed_bytes"]
        != profile["installed_bytes"]
    ):
        raise ValueError("A dimensão do perfil LibreOffice diverge do inventário")
    return profile, tuple(rows)


def prune_ui_resources(root: Path, entries: Iterable[tuple[str, int]]) -> None:
    """Remove apenas traduções catalogadas de uma imagem temporária já autenticada."""
    root = root.absolute()
    if any(part.is_symlink() or part.is_junction() for part in (root, *root.parents)):
        raise ValueError("A imagem precisa estar em um diretório físico")
    for relative, size in entries:
        entry = _TRANSLATION.fullmatch(relative)
        if entry is None or entry[1] in _KEEP or size <= 0:
            raise ValueError("Recurso fora do perfil de interface")
        path = root.joinpath(*PurePosixPath(relative).parts)
        for item in (
            path,
            path.parent,
            path.parent.parent,
            root / "program/resource",
            root / "program",
        ):
            if item.is_symlink() or item.is_junction():
                raise ValueError("O recurso catalogado está redirecionado")
        if not path.is_file() or path.stat().st_size != size:
            raise ValueError("A imagem não corresponde ao catálogo")
        path.unlink()
