"""Validated result metadata and Windows actions; invoked by a bounded worker."""

from dataclasses import dataclass

from local_files import (
    validate_local_regular_file,
    classify_local_file,
    LocalFileEntry,
    open_local_file,
    reveal_local_file,
)
from pdf_previews import checkpoint

ALLOWED_RESULT_SUFFIXES = frozenset({".pdf", ".docx", ".png", ".jpg", ".jpeg"})


def result_identity(path):
    info = path.stat()
    return info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino


def result_path(path):
    path = validate_local_regular_file(path)
    if path.suffix.casefold() not in ALLOWED_RESULT_SUFFIXES:
        raise ValueError("Unsupported result type")
    return path


def open_pdf_result_file(path):
    path = result_path(path)
    info = path.stat()
    open_local_file(
        LocalFileEntry(path, classify_local_file(path), info.st_size, info.st_mtime),
        path.parent,
    )
    return True


def open_pdf_result_folder(path):
    path = result_path(path)
    info = path.stat()
    reveal_local_file(
        LocalFileEntry(path, classify_local_file(path), info.st_size, info.st_mtime),
        path.parent,
    )
    return True


@dataclass(frozen=True)
class ResultRequest:
    paths: tuple
    action: object = None
    identity: tuple = ()


@dataclass(frozen=True)
class ResultInfo:
    size_bytes: int = 0
    identity: tuple = ()
    opened: bool = False
    error: str = ""


class PdfResultReader:
    def close(self):
        pass

    def bundle(self, request, _index, _bounds, cancel):
        try:
            size = 0
            for path in request.paths:
                checkpoint(cancel)
                size += result_path(path).stat().st_size
            identity = result_identity(request.paths[0])
            checkpoint(cancel)
            if request.action is not None:
                if identity != request.identity:
                    return ResultInfo(
                        error="O resultado foi alterado ou substituído. Gere ou selecione novamente o arquivo."
                    )
                if not request.action(request.paths[0]):
                    return ResultInfo(
                        error="Não foi possível abrir o resultado. Confira se ele ainda está disponível."
                    )
                return ResultInfo(size, identity, True)
            return ResultInfo(size, identity)
        except Exception:
            return ResultInfo(
                error="O resultado não está disponível ou não pôde ser aberto."
            )
