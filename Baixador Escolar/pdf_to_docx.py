"""Local, bounded digital/regional OCR conversion into editable Word flow."""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
import ctypes
from enum import StrEnum
from io import BytesIO
from itertools import groupby
import math
import os
from pathlib import Path
import tempfile

import pypdfium2 as pdfium
import pypdfium2.raw as raw
import docx_writer as writer
import pdf_word_layout as layout
import pdf_word_ocr as ocr_layout
from pdf_ocr_runtime import OcrRuntime, OcrFailure, OcrUnavailable
from component_transactions import ComponentBusyError
from component_runtime import component_use
from paths import get_app_dir
from pdf_ocr_vision import VisionLimit, deskew_angle

from local_files import (
    LocalFilesError,
    validate_local_output_path,
    validate_local_regular_file,
)
from pdf_tools import PdfOperationCancelled, PdfOperationProgress, PdfToolsError
from pdfium_access import PDFIUM_LOCK, page_objects

MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_PAGES = 500
MAX_PAGE_POINTS = 1440
MAX_PAGE_OBJECTS = 10_000
MAX_TEXT_CHARS = 2_000_000
# Bound the OOXML tree before packaging even if every object changes style.
MAX_TEXT_RUNS = 50_000
MAX_IMAGE_PIXELS = 25_000_000
MAX_DECODED_IMAGE_BYTES = 256 * 1024 * 1024
MAX_DOCX_BYTES = 256 * 1024 * 1024


class DocxErrorCode(StrEnum):
    INVALID_PDF = "INVALID_PDF"
    PROTECTED_PDF = "PROTECTED_PDF"
    SCANNED_OR_IMAGE_ONLY = "SCANNED_OR_IMAGE_ONLY"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    CONVERSION_FAILED = "CONVERSION_FAILED"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    CANCELLED = "CANCELLED"
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"
    OCR_FAILED = "OCR_FAILED"


MESSAGES = {
    DocxErrorCode.INVALID_PDF: "Selecione um PDF válido e disponível neste computador.",
    DocxErrorCode.PROTECTED_PDF: "Este PDF está protegido e não pôde ser convertido.",
    DocxErrorCode.SCANNED_OR_IMAGE_ONLY: "Não foi possível recuperar texto editável deste PDF. Ele pode ser digitalizado, conter apenas ilustrações ou texto que exige uma imagem mais nítida.",
    DocxErrorCode.OCR_UNAVAILABLE: "Este PDF precisa de reconhecimento de texto em imagens. O componente OCR local está indisponível ou incompleto. Nenhum componente é instalado durante a conversão.",
    DocxErrorCode.OCR_FAILED: "Não foi possível reconhecer o texto em imagens com segurança. Tente um PDF menor ou com imagens mais nítidas. O arquivo anterior foi preservado.",
    DocxErrorCode.RESOURCE_LIMIT: "Este PDF excede os limites seguros para conversão. Tente um documento menor.",
    DocxErrorCode.CONVERSION_FAILED: "Não foi possível converter este PDF para Word.",
    DocxErrorCode.OUTPUT_INVALID: "Não foi possível salvar um documento Word válido. O arquivo anterior foi preservado.",
}


class PdfToDocxError(PdfToolsError):
    def __init__(self, code: DocxErrorCode):
        self.code = code
        super().__init__(MESSAGES[code])


class PdfToDocxCancelled(PdfOperationCancelled):
    code = DocxErrorCode.CANCELLED


@dataclass(frozen=True)
class PdfToDocxResult:
    output_path: Path
    page_count: int
    non_editable_pages: tuple[int, ...]
    ocr_pages: tuple[int, ...] = ()
    review_pages: tuple[int, ...] = ()
    ocr_unavailable_pages: tuple[int, ...] = ()
    page_analysis: tuple = ()


@dataclass(frozen=True)
class WordProgress:
    completed_items: int
    total_items: int
    phase: str


@dataclass(frozen=True)
class PageAnalysis:
    page: int
    kind: str
    ocr_words: int = 0
    regions: int = 0
    review: bool = False
    ocr_seconds: float = 0
    child_peak_bytes: int = 0
    engine: str = "digital"


@dataclass
class _Block:
    text: str
    left: float
    bottom: float
    right: float
    top: float
    size: float = 12
    image: bytes | None = None
    bold: bool = False
    italic: bool = False
    image_ratio: float = 1.0
    runs: tuple[writer.Run, ...] = ()
    font: str = "Arial"
    color: str = "000000"
    object_id: int | None = None


def _cancel(event):
    if event is not None and event.is_set():
        raise PdfToDocxCancelled("Conversão cancelada.")


def _limit(condition):
    if not condition:
        raise PdfToDocxError(DocxErrorCode.RESOURCE_LIMIT)


def _reading_lines(blocks):
    """Baseline proximity and coordinate order; intentionally not a table engine."""
    rows = []
    for block in sorted(
        (b for b in blocks if b.image is None), key=lambda b: -b.bottom
    ):
        if rows and abs(rows[-1][0].bottom - block.bottom) <= block.size * 0.4:
            rows[-1].append(block)
        else:
            rows.append([block])
    lines = []
    for row in rows:
        row.sort(key=lambda b: b.left)
        runs = [writer.Run(row[0].text, row[0].size, row[0].bold, row[0].italic)]
        for previous, current in zip(row, row[1:]):
            separator = " "
            if current.left - previous.right > current.size * 2:
                separator = "\t"
            elif previous.text[-1:].isspace() or current.text[:1].isspace():
                # PDFium may already include the word separator in either object.
                separator = ""
            runs.append(
                writer.Run(
                    separator + current.text, current.size, current.bold, current.italic
                )
            )
        runs = tuple(
            writer.Run("".join(run.text for run in group), *style)
            for style, group in groupby(
                runs, key=lambda run: (run.size, run.bold, run.italic)
            )
        )
        lines.append(
            _Block(
                "".join(run.text for run in runs),
                min(b.left for b in row),
                min(b.bottom for b in row),
                max(b.right for b in row),
                max(b.top for b in row),
                max(b.size for b in row),
                runs=runs,
            )
        )
    return sorted(
        lines + [b for b in blocks if b.image], key=lambda b: (-b.top, b.left)
    )


def _page_blocks(page, budget, event):
    blocks = []
    with (
        closing(page.get_textpage()) as textpage,
        page_objects(
            page, textpage=textpage, cancel=lambda: _cancel(event), limit=_limit
        ) as objects,
    ):
        _limit(textpage.count_chars() + budget[0] <= MAX_TEXT_CHARS)
        for number, entry in enumerate(objects):
            obj = entry.object
            _cancel(event)
            _limit(number < MAX_PAGE_OBJECTS)
            bounds = entry.bounds
            _limit(
                all(math.isfinite(x) and abs(x) <= MAX_PAGE_POINTS * 4 for x in bounds)
            )
            if isinstance(obj, pdfium.PdfTextObj):
                text = writer.safe_text(obj.extract())
                budget[0] += len(text)
                _limit(budget[0] <= MAX_TEXT_CHARS)
                if text.strip():
                    size = obj.get_font_size()
                    _limit(math.isfinite(size) and 0 < size <= 500)
                    matrix = entry.matrix
                    size *= math.hypot(matrix.c, matrix.d)
                    _limit(math.isfinite(size) and size > 0)
                    with closing(obj.get_font()) as font:
                        # Missing metadata must not prevent text extraction or
                        # manufacture emphasis. Keep each available signal.
                        try:
                            name = font.get_base_name().casefold()
                        except pdfium.PdfiumError:
                            name = ""
                        try:
                            weight = font.get_weight()
                        except pdfium.PdfiumError:
                            weight = 0
                        bold = weight >= 600 or "bold" in name
                        italic = "italic" in name or "oblique" in name
                    blocks.append(
                        _Block(
                            text,
                            *bounds,
                            # Tf is in text space; browser PDFs commonly
                            # scale it by 0.75 in the object matrix.
                            min(96, max(6, size)),
                            bold=bold,
                            italic=italic,
                            font=layout.font_family(name),
                            color=_text_color(obj),
                            object_id=ctypes.cast(obj.raw, ctypes.c_void_p).value,
                        )
                    )
            elif isinstance(obj, pdfium.PdfImage):
                metadata = obj.get_metadata()
                pixels = metadata.width * metadata.height
                _limit(0 < pixels <= MAX_IMAGE_PIXELS)
                budget[1] += pixels * 4
                _limit(budget[1] <= MAX_DECODED_IMAGE_BYTES)
                # Normalize only the embedded image, never a textual page.
                with closing(obj.get_bitmap()) as bitmap:
                    with bitmap.to_pil() as image, image.convert("RGBA") as rgb:
                        stream = BytesIO()
                        rgb.save(stream, format="PNG")
                if bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                    blocks.append(
                        _Block(
                            "",
                            *bounds,
                            image=stream.getvalue(),
                            image_ratio=metadata.height / metadata.width,
                        )
                    )
    return blocks


def _text_color(obj):
    values = [ctypes.c_ulong() for _ in range(4)]
    if raw.FPDFPageObj_GetFillColor(obj, *(ctypes.byref(v) for v in values)):
        return "".join(f"{min(255, v.value):02X}" for v in values[:3])
    return "000000"


def _make_page(page, dimensions, blocks, budget, event):
    width, height = dimensions
    content = []
    has_text = any(b.text.strip() for b in blocks)
    if has_text:
        converted = layout.make_page(
            page, dimensions, blocks, budget, lambda: _cancel(event), _limit
        )
        _limit(budget[2] <= MAX_TEXT_RUNS)
        return converted, True
    if not has_text:
        pixels = math.ceil(width) * math.ceil(height)
        budget[1] += pixels * 4
        _limit(pixels <= MAX_IMAGE_PIXELS and budget[1] <= MAX_DECODED_IMAGE_BYTES)
        _cancel(event)
        with closing(page.render(scale=1)) as bitmap:
            with bitmap.to_pil() as image:
                stream = BytesIO()
                image.save(stream, format="PNG")
        content.append(writer.Picture(stream.getvalue(), width, height))
    return writer.Page(width, height, tuple(content)), has_text


def validate_docx(path: Path, expected_text: str, check_cancel=lambda: None) -> None:
    try:
        _limit(0 < path.stat().st_size <= MAX_DOCX_BYTES)
        writer.validate(path, expected_text, check_cancel)
    except PdfToDocxCancelled:
        raise
    except Exception as error:
        raise PdfToDocxError(DocxErrorCode.OUTPUT_INVALID) from error


class PdfToDocxService:
    def __init__(self, ocr_runtime=None):
        self._ocr = ocr_runtime if ocr_runtime is not None else OcrRuntime()

    def convert(
        self, source, destination, *, overwrite=False, cancel_event=None, progress=None
    ):
        temporary = None
        store = writer.ImageStore()
        stage = "input"
        try:
            _cancel(cancel_event)
            source = validate_local_regular_file(source)
            if source.suffix.casefold() != ".pdf":
                raise PdfToDocxError(DocxErrorCode.INVALID_PDF)
            _limit(0 < source.stat().st_size <= MAX_INPUT_BYTES)
            with source.open("rb") as stream:
                data = stream.read(MAX_INPUT_BYTES + 1)
            _limit(len(data) <= MAX_INPUT_BYTES)
            if not data.startswith(b"%PDF-"):
                raise PdfToDocxError(DocxErrorCode.INVALID_PDF)
            stage = "output"
            destination = validate_local_output_path(destination, inputs=(source,))
            if destination.suffix.casefold() != ".docx":
                raise PdfToDocxError(DocxErrorCode.OUTPUT_INVALID)
            if destination.exists() and not overwrite:
                raise PdfToDocxError(DocxErrorCode.OUTPUT_INVALID)
            stage = "conversion"
            with component_use(get_app_dir(), "ocr"):
                document, count, warnings, analyses, missing = self._convert(
                    data, cancel_event, progress, store
                )
            _cancel(cancel_event)
            parts, expected_text = writer.package_parts(
                document, lambda: _cancel(cancel_event)
            )
            stage = "output"
            descriptor, name = tempfile.mkstemp(
                prefix=".edudownloader-word-", suffix=".docx", dir=destination.parent
            )
            temporary = Path(name)
            with os.fdopen(descriptor, "wb") as stream:
                writer.save_parts(parts, stream, lambda: _cancel(cancel_event))
            validate_docx(temporary, expected_text, lambda: _cancel(cancel_event))
            _cancel(cancel_event)
            validate_local_output_path(destination, inputs=(source,))
            if overwrite:
                os.replace(temporary, destination)
            elif os.name == "nt":
                os.rename(temporary, destination)  # Windows refuses a raced-in target.
            else:
                os.link(temporary, destination)  # Exclusive publication on POSIX.
                temporary.unlink()
            return PdfToDocxResult(
                destination,
                count,
                tuple(warnings),
                tuple(a.page for a in analyses if a.ocr_words),
                tuple(a.page for a in analyses if a.review),
                tuple(missing),
                tuple(analyses),
            )
        except (PdfToDocxError, PdfToDocxCancelled):
            raise
        except ComponentBusyError as error:
            raise PdfToDocxError(DocxErrorCode.OCR_UNAVAILABLE) from error
        except LocalFilesError as error:
            code = (
                DocxErrorCode.OUTPUT_INVALID
                if stage == "output"
                else DocxErrorCode.INVALID_PDF
            )
            raise PdfToDocxError(code) from error
        except OSError as error:
            code = {
                "input": DocxErrorCode.INVALID_PDF,
                "output": DocxErrorCode.OUTPUT_INVALID,
            }.get(stage, DocxErrorCode.CONVERSION_FAILED)
            raise PdfToDocxError(code) from error
        except Exception as error:
            raise PdfToDocxError(DocxErrorCode.CONVERSION_FAILED) from error
        finally:
            store.close()
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # Preserve the original, controlled operation error.

    def _convert(self, data, event, progress, store):
        try:
            with _native_access(event):
                pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as error:
            code = (
                DocxErrorCode.PROTECTED_PDF
                if error.err_code == raw.FPDF_ERR_PASSWORD
                else DocxErrorCode.INVALID_PDF
            )
            raise PdfToDocxError(code) from error
        raster = None
        try:
            with _native_access(event):
                if raw.FPDF_GetSecurityHandlerRevision(pdf) != -1:
                    raise PdfToDocxError(DocxErrorCode.PROTECTED_PDF)
                count = len(pdf)
            _limit(0 < count <= MAX_PAGES)
            document = []
            warnings = []
            analyses, missing = [], []
            budget = [0, 0, 0]
            if progress:
                progress(PdfOperationProgress(0, count))
            for index in range(count):
                _cancel(event)
                raster = None
                with _native_access(event), closing(pdf[index]) as page:
                    dimensions = page.get_size()
                    _limit(
                        all(
                            math.isfinite(d) and 144 <= d <= MAX_PAGE_POINTS
                            for d in dimensions
                        )
                    )
                    # Decoded pixels are a per-page working set, not retained
                    # across a long document. Compressed assets have a separate
                    # bounded temporary store and package limit.
                    budget[1] = 0
                    blocks = _page_blocks(page, budget, event)
                    segments = layout.path_segments(
                        page, lambda: _cancel(event), _limit
                    )
                    chars = layout.glyphs(
                        page, blocks, segments, lambda: _cancel(event), _limit
                    )
                    if any(b.image for b in blocks):
                        if progress:
                            progress(WordProgress(index, count, "Analisando a página"))
                        scale = min(
                            300 / 72,
                            (18_000_000 / (dimensions[0] * dimensions[1])) ** 0.5,
                        )
                        _limit(
                            math.ceil(dimensions[0] * scale)
                            * math.ceil(dimensions[1] * scale)
                            <= MAX_IMAGE_PIXELS
                        )
                        with (
                            closing(page.render(scale=scale)) as bitmap,
                            bitmap.to_pil() as image,
                        ):
                            raster = image.copy()
                    graphics = (
                        layout.isolated_graphics(
                            page,
                            chars,
                            [b for b in blocks if b.image],
                            dimensions,
                            budget,
                            lambda: _cancel(event),
                            _limit,
                        )
                        if chars
                        else []
                    )
                    # No native handles leave this section or survive OCR waits.
                    if raster is None:
                        converted_page, has_text = _make_page(
                            page, dimensions, blocks, budget, event
                        )
                try:
                    analysis_record = PageAnalysis(
                        index + 1, "digital" if chars else "graphic"
                    )
                    if raster is not None:
                        available = self._ocr.available()
                        analysis = ocr_layout.analyze_page(
                            raster, dimensions, chars, lambda: _cancel(event)
                        )
                        changed = False
                        if not chars and available and analysis.regions:
                            try:
                                orientation = self._ocr.orientation(
                                    raster, cancel=lambda: _cancel(event)
                                )
                            except (OcrFailure, OcrUnavailable):
                                orientation = None
                            if orientation and orientation[0] and orientation[1] >= 3:
                                angle = orientation[0]
                                replacement = raster.rotate(
                                    -angle, expand=True, fillcolor="white"
                                )
                                raster.close()
                                raster = replacement
                                changed = True
                                if angle in (90, 270):
                                    dimensions = dimensions[::-1]
                            skew = deskew_angle(raster, lambda: _cancel(event))
                            if skew:
                                replacement = raster.rotate(
                                    skew, expand=True, fillcolor="white"
                                )
                                dimensions = (
                                    dimensions[0] * replacement.width / raster.width,
                                    dimensions[1] * replacement.height / raster.height,
                                )
                                raster.close()
                                raster = replacement
                                changed = True
                        if changed:
                            analysis = ocr_layout.analyze_page(
                                raster, dimensions, chars, lambda: _cancel(event)
                            )
                        has_text = bool(chars)
                        if analysis.regions and available:
                            if progress:
                                progress(
                                    WordProgress(
                                        index, count, "Reconhecendo texto em imagens"
                                    )
                                )
                            try:
                                recognized = ocr_layout.recognize_page(
                                    raster,
                                    dimensions,
                                    chars,
                                    analysis,
                                    self._ocr,
                                    store,
                                    lambda: _cancel(event),
                                )
                            except (OcrUnavailable, OcrFailure) as error:
                                raise PdfToDocxError(
                                    DocxErrorCode.OCR_FAILED
                                ) from error
                            if recognized.glyphs:
                                has_text = True
                                budget[0] += sum(len(g.text) for g in recognized.glyphs)
                                _limit(budget[0] <= MAX_TEXT_CHARS)
                                converted_page = layout.compose_page(
                                    dimensions,
                                    [],
                                    chars + list(recognized.glyphs),
                                    segments + list(recognized.segments),
                                    list(recognized.graphics),
                                    budget,
                                    lambda: _cancel(event),
                                    _limit,
                                )
                            else:
                                converted_page = _detached_page(
                                    raster,
                                    dimensions,
                                    chars,
                                    blocks,
                                    segments,
                                    graphics,
                                    budget,
                                    store,
                                    event,
                                )
                            analysis_record = PageAnalysis(
                                index + 1,
                                "mixed" if chars else "scanned",
                                recognized.words,
                                recognized.regions,
                                recognized.review,
                                recognized.seconds,
                                recognized.peak_memory_bytes,
                                recognized.engine,
                            )
                        else:
                            if analysis.regions and not available:
                                missing.append(index + 1)
                                analysis_record = PageAnalysis(
                                    index + 1,
                                    "mixed" if chars else "scanned",
                                    regions=len(analysis.regions),
                                    review=True,
                                )
                            converted_page = _detached_page(
                                raster,
                                dimensions,
                                chars,
                                blocks,
                                segments,
                                graphics,
                                budget,
                                store,
                                event,
                            )
                    document.append(_spool_page(converted_page, store))
                    analyses.append(analysis_record)
                    if not has_text:
                        warnings.append(index + 1)
                except VisionLimit as error:
                    raise PdfToDocxError(DocxErrorCode.RESOURCE_LIMIT) from error
                finally:
                    if raster is not None:
                        raster.close()
                        raster = None
                if progress:
                    progress(PdfOperationProgress(index + 1, count))
            if len(warnings) == count:
                raise PdfToDocxError(
                    DocxErrorCode.OCR_UNAVAILABLE
                    if missing
                    else DocxErrorCode.SCANNED_OR_IMAGE_ONLY
                )
            return document, count, warnings, analyses, missing
        finally:
            # A native extraction error can occur after rendering and before
            # entering the detached OCR phase's cleanup section.
            if raster is not None:
                raster.close()
            with PDFIUM_LOCK:
                pdf.close()


@contextmanager
def _native_access(event):
    while not PDFIUM_LOCK.acquire(timeout=0.1):
        _cancel(event)
    try:
        _cancel(event)
        yield
    finally:
        PDFIUM_LOCK.release()


def _detached_page(
    raster, dimensions, chars, blocks, segments, graphics, budget, store, event
):
    if chars:
        if any(
            (b.right - b.left) * (b.top - b.bottom)
            > dimensions[0] * dimensions[1] * 0.4
            for b in blocks
            if b.image
        ):
            graphics = list(
                ocr_layout.digital_graphics(
                    raster, dimensions, chars, store, lambda: _cancel(event)
                )
            )
            blocks = [b for b in blocks if b.text]
        return layout.compose_page(
            dimensions,
            blocks,
            chars,
            segments,
            graphics,
            budget,
            lambda: _cancel(event),
            _limit,
        )
    with raster.copy() as small:
        small.thumbnail((1600, 1600))
        stream = BytesIO()
        small.save(stream, "PNG")
    return writer.Page(
        *dimensions, (writer.Picture(store.add(stream.getvalue()), *dimensions),)
    )


def _spool_page(page, store):
    def block(item):
        if isinstance(item, writer.Picture) and isinstance(item.png, bytes):
            return replace(item, png=store.add(item.png))
        if isinstance(item, writer.Columns):
            return replace(
                item,
                columns=tuple(
                    tuple(block(b) for b in column) for column in item.columns
                ),
            )
        if isinstance(item, writer.Table):
            return replace(
                item,
                rows=tuple(
                    tuple(
                        replace(c, blocks=tuple(block(b) for b in c.blocks))
                        for c in row
                    )
                    for row in item.rows
                ),
            )
        return item

    return replace(page, blocks=tuple(block(b) for b in page.blocks))
