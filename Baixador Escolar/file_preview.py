"""Preview local seguro, limitado e independente da interface gráfica."""

from __future__ import annotations

import math
import os
import tempfile
import warnings
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from io import BytesIO
from pathlib import Path
from threading import Event, Lock
from typing import Final

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pdfium_access import serialized_pdfium

from local_files import (
    LocalFileCategory,
    LocalFileEntry,
    LocalFilesError,
    revalidate_local_file,
)
from paths import InvalidLocalDataPath, LocalDataPathUnavailable


class PreviewStatus(str, Enum):
    """Estados públicos e estáveis de uma tentativa de preview."""

    SUCCESS = "success"
    LOADING = "loading"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    TOO_LARGE = "too_large"
    INVALID = "invalid"
    ERROR = "error"


class PreviewKind(str, Enum):
    """Tipos de conteúdo visual retornados pelo serviço."""

    IMAGE = "image"
    PDF_PAGE = "pdf_page"
    VIDEO_FRAME = "video_frame"
    WORD_TEXT = "word_text"


@dataclass(frozen=True, slots=True)
class FilePreviewResult:
    """Resultado imutável com pixels RGBA, sem dependência de toolkit visual."""

    status: PreviewStatus
    kind: PreviewKind | None = None
    width: int = 0
    height: int = 0
    rgba: bytes = b""
    message: str | None = None
    text: str = ""
    title: str = ""
    truncated: bool = False
    source_identity: tuple = ()


class PreviewCancelled(Exception):
    """Cancellation of a read-only preview owned by the Files page."""


def preview_checkpoint(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise PreviewCancelled


PREVIEW_MAX_DIMENSION: Final = 512
PREVIEW_MAX_FILE_BYTES: Final = 64 * 1024 * 1024
DOCUMENT_PREVIEW_SUFFIXES: Final = frozenset({".docx", ".odt"})
_OFFICE_PREVIEW_MAX_BYTES: Final = 16 * 1024 * 1024
PREVIEW_MAX_SOURCE_PIXELS: Final = 40_000_000
_MAX_PDF_PAGE_POINTS: Final = 14_400.0
_RGBA_CHANNELS: Final = 4

_RevalidateFile = Callable[[LocalFileEntry, Path | str], LocalFileEntry]


class FilePreviewService:
    """Read-only rendering; one caller worker owns a bounded, volatile cache."""

    def __init__(
        self,
        *,
        revalidate_file: _RevalidateFile = revalidate_local_file,
        media_dir: Path | None = None,
        document_component: Callable[[], Path | None] | None = None,
    ) -> None:
        self._revalidate_file = revalidate_file
        self._media_dir = media_dir
        self._document_component = document_component
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self._cache_lock = Lock()
        self._closed = False

    def close(self):
        with self._cache_lock:
            self._closed = True
            self._cache.clear()
            self._cache_bytes = 0

    def create_preview(
        self,
        entry: LocalFileEntry,
        directory: Path | str,
    ) -> FilePreviewResult:
        return self.create_cancellable_preview(entry, directory, None)

    def create_cancellable_preview(self, entry, directory, cancel_event):
        try:
            return self._create(entry, directory, cancel_event)
        except PreviewCancelled:
            return _result(PreviewStatus.UNAVAILABLE, "Prévia cancelada.")
        except (OSError, LocalFilesError):
            return _result(
                PreviewStatus.UNAVAILABLE, "O arquivo não está disponível para prévia."
            )
        except Exception:
            return _result(
                PreviewStatus.INVALID,
                "Não foi possível ler este arquivo para a prévia.",
            )

    def _create(self, entry, directory, cancel_event):
        preview_checkpoint(cancel_event)
        if self._closed:
            raise PreviewCancelled

        if not isinstance(entry, LocalFileEntry):
            return _result(
                PreviewStatus.INVALID,
                "O arquivo selecionado não é válido para preview.",
            )
        try:
            validated = self._revalidate_file(entry, directory)
        except LocalFilesError:
            return _result(
                PreviewStatus.UNAVAILABLE,
                "O arquivo selecionado não está disponível para preview.",
            )
        except (OSError, TypeError, ValueError):
            return _result(
                PreviewStatus.INVALID,
                "O arquivo selecionado não é válido para preview.",
            )

        if validated.category not in {
            LocalFileCategory.IMAGE,
            LocalFileCategory.PDF,
            LocalFileCategory.VIDEO,
            LocalFileCategory.DOCUMENT,
        }:
            return _result(
                PreviewStatus.UNSUPPORTED,
                "Este tipo de arquivo não possui preview local.",
            )
        if (
            validated.category is LocalFileCategory.DOCUMENT
            and validated.suffix.casefold() not in DOCUMENT_PREVIEW_SUFFIXES
        ):
            return _result(
                PreviewStatus.UNSUPPORTED,
                "Prévia visual indisponível para este formato. Use Abrir.",
            )
        limit = (
            1024 * 1024 * 1024
            if validated.category is LocalFileCategory.VIDEO
            else PREVIEW_MAX_FILE_BYTES
        )
        if validated.size_bytes > limit:
            return _result(
                PreviewStatus.TOO_LARGE,
                "O arquivo excede o limite seguro para preview.",
            )

        stamp = self._stamp(validated.path)
        key = (str(validated.path), validated.category, stamp)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
        if validated.category is LocalFileCategory.IMAGE:
            result = _preview_image(validated.path)
        elif validated.category is LocalFileCategory.PDF:
            result = _preview_pdf(validated.path)
        elif validated.category is LocalFileCategory.VIDEO:
            from video_preview import preview_video

            result = preview_video(validated.path, self._media_dir, cancel_event)
        else:
            result = self._preview_document(validated, cancel_event)
        preview_checkpoint(cancel_event)
        self._revalidate_file(validated, directory)
        if self._stamp(validated.path) != stamp:
            return _result(
                PreviewStatus.UNAVAILABLE,
                "O arquivo mudou durante a leitura. Selecione-o novamente.",
            )
        if result.status is PreviewStatus.SUCCESS:
            result = replace(result, source_identity=stamp)
        # Uma indisponibilidade temporária do LibreOffice pode mudar após a
        # instalação ou configuração do componente.
        if result.status is PreviewStatus.SUCCESS and not (
            result.kind is PreviewKind.WORD_TEXT
            and self._document_component is not None
        ):
            cost = (
                len(result.rgba)
                + len(result.text.encode("utf-8"))
                + len(result.title.encode("utf-8"))
            )
            with self._cache_lock:
                if not self._closed:
                    old = self._cache.pop(key, None)
                    if old is not None:
                        self._cache_bytes -= (
                            len(old.rgba)
                            + len(old.text.encode("utf-8"))
                            + len(old.title.encode("utf-8"))
                        )
                    self._cache[key] = result
                    self._cache_bytes += cost
                    while self._cache_bytes > 16 * 1024 * 1024 or len(self._cache) > 32:
                        _, old = self._cache.popitem(last=False)
                        self._cache_bytes -= (
                            len(old.rgba)
                            + len(old.text.encode("utf-8"))
                            + len(old.title.encode("utf-8"))
                        )
        return result

    def _preview_document(self, entry, cancel_event):
        from word_preview import preview_odt, preview_word

        suffix = entry.suffix.casefold()
        fallback = preview_odt if suffix == ".odt" else preview_word
        if entry.size_bytes > _OFFICE_PREVIEW_MAX_BYTES:
            return _result(
                PreviewStatus.TOO_LARGE,
                "O documento excede o limite seguro para prévia.",
            )
        if self._document_component is not None and os.name == "nt":
            from ctypes import WinDLL
            from documents_tools import (
                DocumentConversionRequest,
                DocumentConversionStatus,
                DocumentInputFormat,
                DocumentsConversionService,
            )
            from paths import documents_conversion_temp_parent

            try:
                if not WinDLL("shell32.dll").IsUserAnAdmin():
                    component = self._document_component()
                    preview_checkpoint(cancel_event)
                    if component is not None:
                        with tempfile.TemporaryDirectory(
                            prefix="EduDownloader-preview-",
                            dir=documents_conversion_temp_parent(),
                        ) as work:
                            pdf = Path(work) / "primeira-pagina.pdf"
                            conversion = DocumentsConversionService(
                                timeout_seconds=18, memory_limit=512 * 1024 * 1024
                            ).convert(
                                DocumentConversionRequest(
                                    entry.path,
                                    pdf,
                                    component_root=component,
                                    cancel_event=cancel_event,
                                    input_format=DocumentInputFormat.ODT
                                    if suffix == ".odt"
                                    else DocumentInputFormat.DOCX,
                                    preview=True,
                                )
                            )
                            preview_checkpoint(cancel_event)
                            if conversion.status is DocumentConversionStatus.COMPLETED:
                                visual = _preview_pdf(pdf)
                                if visual.status is PreviewStatus.SUCCESS:
                                    return visual
            except (
                OSError,
                RuntimeError,
                ValueError,
                InvalidLocalDataPath,
                LocalDataPathUnavailable,
            ):
                pass
        preview_checkpoint(cancel_event)
        return fallback(entry.path, cancel_event)

    @staticmethod
    def _stamp(path):
        info = path.stat()
        return info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino

    def source_identity(self, entry, directory):
        return self._stamp(self._revalidate_file(entry, directory).path)


def _preview_image(path: Path) -> FilePreviewResult:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path, formats=("JPEG", "PNG")) as source:
                if source.format not in {"JPEG", "PNG"}:
                    return _result(
                        PreviewStatus.INVALID,
                        "A imagem não é um JPG ou PNG válido.",
                    )
                if not _valid_source_dimensions(*source.size):
                    return _result(
                        PreviewStatus.TOO_LARGE,
                        "A imagem excede o limite seguro para preview.",
                    )
                source.load()
                oriented = ImageOps.exif_transpose(source)
                try:
                    return _rgba_preview(oriented, PreviewKind.IMAGE)
                finally:
                    if oriented is not source:
                        oriented.close()
    except (FileNotFoundError, PermissionError):
        return _result(
            PreviewStatus.UNAVAILABLE,
            "A imagem não está disponível para preview.",
        )
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ):
        return _result(
            PreviewStatus.INVALID,
            "A imagem não é um JPG ou PNG válido.",
        )
    except Exception:
        return _result(
            PreviewStatus.ERROR,
            "Não foi possível gerar o preview da imagem.",
        )


@serialized_pdfium
def _preview_pdf(path: Path) -> FilePreviewResult:
    document = None
    page = None
    bitmap = None
    rendered = None
    try:
        with path.open("rb") as stream:
            source = stream.read(PREVIEW_MAX_FILE_BYTES + 1)
        if len(source) > PREVIEW_MAX_FILE_BYTES:
            return _result(
                PreviewStatus.TOO_LARGE,
                "O arquivo excede o limite seguro para preview.",
            )
        with BytesIO(source) as stream:
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted:
                return _result(
                    PreviewStatus.INVALID,
                    "O arquivo não é um PDF válido ou legível.",
                )
            page_count = len(reader.pages)
        if page_count < 1:
            return _result(
                PreviewStatus.UNAVAILABLE,
                "O PDF não contém páginas disponíveis para preview.",
            )
        document = pdfium.PdfDocument(source)
        page = document[0]
        source_width, source_height = page.get_size()
        if not _valid_pdf_dimensions(source_width, source_height):
            return _result(
                PreviewStatus.TOO_LARGE,
                "A página do PDF excede o limite seguro para preview.",
            )
        scale = min(
            1.0,
            PREVIEW_MAX_DIMENSION / source_width,
            PREVIEW_MAX_DIMENSION / source_height,
        )
        bitmap = page.render(
            scale=scale,
            fill_color=(255, 255, 255, 255),
        )
        rendered = bitmap.to_pil()
        return _rgba_preview(rendered, PreviewKind.PDF_PAGE)
    except (FileNotFoundError, PermissionError):
        return _result(
            PreviewStatus.UNAVAILABLE,
            "O PDF não está disponível para preview.",
        )
    except (pdfium.PdfiumError, PdfReadError, OSError, TypeError, ValueError):
        return _result(
            PreviewStatus.INVALID,
            "O arquivo não é um PDF válido ou legível.",
        )
    except Exception:
        return _result(
            PreviewStatus.ERROR,
            "Não foi possível gerar o preview do PDF.",
        )
    finally:
        if rendered is not None:
            rendered.close()
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        if document is not None:
            document.close()


def _rgba_preview(image: Image.Image, kind: PreviewKind) -> FilePreviewResult:
    limited = image.copy()
    rgba = None
    try:
        limited.thumbnail(
            (PREVIEW_MAX_DIMENSION, PREVIEW_MAX_DIMENSION),
            Image.Resampling.LANCZOS,
        )
        rgba = limited.convert("RGBA")
        width, height = rgba.size
        payload = rgba.tobytes()
        if len(payload) != width * height * _RGBA_CHANNELS:
            return _result(
                PreviewStatus.ERROR,
                "Não foi possível validar os pixels do preview.",
            )
        return FilePreviewResult(
            status=PreviewStatus.SUCCESS,
            kind=kind,
            width=width,
            height=height,
            rgba=payload,
        )
    finally:
        if rgba is not None:
            rgba.close()
        limited.close()


def _valid_source_dimensions(width: int, height: int) -> bool:
    return width > 0 and height > 0 and width * height <= PREVIEW_MAX_SOURCE_PIXELS


def _valid_pdf_dimensions(width: float, height: float) -> bool:
    return (
        math.isfinite(width)
        and math.isfinite(height)
        and 0 < width <= _MAX_PDF_PAGE_POINTS
        and 0 < height <= _MAX_PDF_PAGE_POINTS
    )


def _result(status: PreviewStatus, message: str) -> FilePreviewResult:
    return FilePreviewResult(status=status, message=message)
