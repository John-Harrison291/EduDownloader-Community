"""Ferramentas PDF locais com validação conservadora e escrita atômica."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import warnings
from io import BytesIO
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Final

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter

from local_files import (
    LocalFilesError,
    validate_local_output_path,
    validate_local_regular_file,
)
from pdfium_access import serialized_pdfium
from print_layout import (
    ImagePageLayout,
    MarginPreset,
    Orientation,
    PaperSize,
    PdfImageQuality,
    PrintLayoutError,
    Rect,
    Size,
    choose_image_page_orientation,
    contain_image,
    image_slots,
    image_rotations,
    rotated_image_size,
    page_dimensions,
    paginate_images,
    pdf_export_requires_warning,
    pdfium_scale,
    raster_dimensions,
    validate_conversion_image_dimensions,
    validate_pdf_page_dimensions,
)


SUPPORTED_IMAGE_SUFFIXES: Final = frozenset({".jpg", ".jpeg", ".png"})
_PAGE_TOKEN = re.compile(r"(?P<start>\d+)(?:\s*-\s*(?P<end>\d+))?")
_PDF_RESOLUTION_DPI: Final = 150
_A4_PORTRAIT_PIXELS: Final = raster_dimensions(
    page_dimensions(PaperSize.A4, Orientation.PORTRAIT),
    _PDF_RESOLUTION_DPI,
)
_A4_MARGIN_PIXELS: Final = round(
    MarginPreset.NORMAL.points * _PDF_RESOLUTION_DPI / 72.0
)
PDF_TO_IMAGE_DPI: Final = float(PdfImageQuality.STANDARD.dpi)
_PDF_TO_IMAGE_FORMATS: Final = frozenset({"PNG", "JPG"})
_PDF_TO_IMAGE_JPEG_QUALITY: Final = 90
_UNSAFE_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES: Final = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)

# O pypdf inclui trechos do cabeçalho inválido em mensagens próprias. O cliente
# apresenta erros controlados e não propaga esse conteúdo para os logs.
_PYPDF_LOGGER = logging.getLogger("pypdf")
_PYPDF_LOGGER.addHandler(logging.NullHandler())
_PYPDF_LOGGER.propagate = False


class PdfToolsError(Exception):
    """Erro seguro que pode ser apresentado diretamente à pessoa usuária."""


class InvalidPdfError(PdfToolsError):
    """Um PDF de entrada não pôde ser lido de forma confiável."""


class InvalidImageError(PdfToolsError):
    """Uma imagem de entrada não é suportada ou não pôde ser lida."""


class InvalidPageSelectionError(PdfToolsError):
    """A expressão de páginas não representa uma seleção válida."""


class PdfOperationCancelled(PdfToolsError):
    """Uma operação PDF longa foi cancelada cooperativamente."""


@dataclass(frozen=True)
class PdfOperationResult:
    """Resultado mínimo de uma operação local concluída."""

    output_path: Path
    page_count: int


@dataclass(frozen=True)
class PdfImageExportResult:
    """Resultado da renderização local de páginas inteiras do PDF."""

    output_directory: Path
    output_paths: tuple[Path, ...]
    page_numbers: tuple[int, ...]

    @property
    def page_count(self) -> int:
        return len(self.page_numbers)


@dataclass(frozen=True, slots=True)
class ImagesToPdfProgress:
    """Progresso pequeno e imutável de uma conversão Imagens → PDF."""

    completed_pages: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class PdfOperationProgress:
    """Progresso pequeno e imutável de uma operação PDF."""

    completed_items: int
    total_items: int


def parse_page_selection(selection: str, total_pages: int) -> tuple[int, ...]:
    """Converte seleção humana em páginas baseadas em 1, mantendo ordem e duplicatas."""
    if total_pages < 1:
        raise InvalidPageSelectionError("O PDF não contém páginas disponíveis.")
    if not isinstance(selection, str) or not selection.strip():
        raise InvalidPageSelectionError("Informe ao menos uma página.")

    pages: list[int] = []
    for raw_token in selection.split(","):
        token = raw_token.strip()
        match = _PAGE_TOKEN.fullmatch(token)
        if match is None:
            raise InvalidPageSelectionError("Use páginas como 1, 1-3 ou 1-3,5,8-10.")
        start = int(match.group("start"))
        end_text = match.group("end")
        end = int(end_text) if end_text is not None else start
        if start == 0 or end == 0:
            raise InvalidPageSelectionError("A numeração das páginas começa em 1.")
        if end < start:
            raise InvalidPageSelectionError("Uma faixa de páginas está invertida.")
        if start > total_pages or end > total_pages:
            raise InvalidPageSelectionError(
                f"O PDF possui somente {total_pages} página(s)."
            )
        pages.extend(range(start, end + 1))

    if not pages:
        raise InvalidPageSelectionError("Informe ao menos uma página.")
    return tuple(pages)


class PdfToolsService:
    """Executa operações PDF locais sem depender da interface gráfica."""

    def page_count(self, source: Path | str) -> int:
        """Lê e valida um PDF, retornando sua quantidade de páginas."""
        source_path = _validate_pdf_input(source)
        with source_path.open("rb") as stream:
            reader = _read_pdf(stream, source_path.name)
            return len(reader.pages)

    def merge_pdfs(
        self,
        inputs: Sequence[Path | str],
        output: Path | str,
        *,
        overwrite: bool = False,
        cancel_event: Event | None = None,
        progress: Callable[[PdfOperationProgress], None] | None = None,
    ) -> PdfOperationResult:
        """Junta dois ou mais PDFs na ordem recebida, sem modificar as entradas."""
        _validate_operation_hooks(cancel_event, progress)
        input_paths = tuple(_validate_pdf_input(path) for path in inputs)
        if len(input_paths) < 2:
            raise PdfToolsError("Selecione pelo menos dois arquivos PDF.")
        output_path = _validate_output(output, input_paths, overwrite)

        def produce(temporary_path: Path) -> int:
            writer = PdfWriter()
            page_total = 0
            try:
                _report_operation_progress(progress, 0, len(input_paths))
                for completed_documents, source_path in enumerate(input_paths, start=1):
                    _raise_if_cancelled(cancel_event)
                    try:
                        with source_path.open("rb") as stream:
                            reader = _read_pdf(stream, source_path.name)
                            for page in reader.pages:
                                writer.add_page(page)
                                page_total += 1
                    except PdfToolsError:
                        raise
                    except Exception as error:
                        raise InvalidPdfError(
                            _invalid_pdf_message(source_path.name)
                        ) from error
                    _report_operation_progress(
                        progress,
                        completed_documents,
                        len(input_paths),
                    )
                    _raise_if_cancelled(cancel_event)
                with temporary_path.open("wb") as destination:
                    writer.write(destination)
                _raise_if_cancelled(cancel_event)
            finally:
                writer.close()
            return page_total

        return _write_atomically(
            output_path, overwrite, produce, cancel_event=cancel_event
        )

    def extract_pages(
        self,
        source: Path | str,
        selection: str,
        output: Path | str,
        *,
        overwrite: bool = False,
        cancel_event: Event | None = None,
        progress: Callable[[PdfOperationProgress], None] | None = None,
    ) -> PdfOperationResult:
        """Extrai páginas na ordem informada; páginas repetidas são mantidas."""
        _validate_operation_hooks(cancel_event, progress)
        source_path = _validate_pdf_input(source)
        output_path = _validate_output(output, (source_path,), overwrite)

        try:
            source_stream = source_path.open("rb")
        except OSError as error:
            raise InvalidPdfError(_invalid_pdf_message(source_path.name)) from error
        with source_stream:
            reader = _read_pdf(source_stream, source_path.name)
            pages = parse_page_selection(selection, len(reader.pages))

            def produce(temporary_path: Path) -> int:
                writer = PdfWriter()
                try:
                    _report_operation_progress(progress, 0, len(pages))
                    for completed_pages, page_number in enumerate(pages, start=1):
                        _raise_if_cancelled(cancel_event)
                        writer.add_page(reader.pages[page_number - 1])
                        _report_operation_progress(
                            progress,
                            completed_pages,
                            len(pages),
                        )
                        _raise_if_cancelled(cancel_event)
                    with temporary_path.open("wb") as destination:
                        writer.write(destination)
                    _raise_if_cancelled(cancel_event)
                except PdfToolsError:
                    raise
                except Exception as error:
                    raise InvalidPdfError(
                        _invalid_pdf_message(source_path.name)
                    ) from error
                finally:
                    writer.close()
                return len(pages)

            return _write_atomically(
                output_path, overwrite, produce, cancel_event=cancel_event
            )

    def images_to_pdf(
        self,
        inputs: Sequence[Path | str],
        output: Path | str,
        *,
        overwrite: bool = False,
        layout: ImagePageLayout | None = None,
        rotations: Sequence[int] | None = None,
        cancel_event: Event | None = None,
        progress: Callable[[ImagesToPdfProgress], None] | None = None,
    ) -> PdfOperationResult:
        """Cria PDF paginado com imagens inteiras, layout físico e ordem estável."""
        resolved_layout = _validate_images_to_pdf_layout(layout)
        _validate_images_to_pdf_hooks(cancel_event, progress)
        input_paths = tuple(_validate_image_input(path) for path in inputs)
        try:
            angles = image_rotations(rotations, len(input_paths))
        except PrintLayoutError as error:
            raise PdfToolsError(str(error)) from error
        if not input_paths:
            raise PdfToolsError("Selecione pelo menos uma imagem JPG ou PNG.")
        output_path = _validate_images_to_pdf_output(
            output,
            input_paths,
            overwrite,
        )
        groups = paginate_images(input_paths, resolved_layout.images_per_page)
        total_pages = len(groups)
        try:
            pdf_export_requires_warning(total_pages)
        except PrintLayoutError as error:
            raise PdfToolsError(
                "A seleção excede o limite seguro de páginas."
            ) from error
        _raise_if_cancelled(cancel_event)

        def produce(temporary_path: Path) -> int:
            writer = PdfWriter()
            try:
                _report_images_to_pdf_progress(progress, 0, total_pages)
                for completed_pages, group in enumerate(groups, start=1):
                    _raise_if_cancelled(cancel_event)
                    offset = (completed_pages - 1) * resolved_layout.images_per_page
                    group_angles = angles[offset : offset + len(group)]
                    options = {"rotations": group_angles} if any(group_angles) else {}
                    page = _images_as_pdf_page(group, resolved_layout, **options)
                    try:
                        _append_image_page(writer, page)
                    finally:
                        page.close()
                    _report_images_to_pdf_progress(
                        progress,
                        completed_pages,
                        total_pages,
                    )
                    _raise_if_cancelled(cancel_event)
                with temporary_path.open("wb") as destination:
                    writer.write(destination)
                _raise_if_cancelled(cancel_event)
            except PdfToolsError:
                raise
            except Exception as error:
                raise PdfToolsError(
                    "Não foi possível criar o PDF com as imagens selecionadas."
                ) from error
            finally:
                writer.close()
            return total_pages

        return _write_atomically(
            output_path, overwrite, produce, cancel_event=cancel_event
        )

    def pdf_to_image_output_paths(
        self,
        source: Path | str,
        selection: str | None,
        image_format: str,
        output_directory: Path | str,
        *,
        total_pages: int | None = None,
    ) -> tuple[Path, ...]:
        """Planeja nomes previsíveis sem renderizar ou modificar arquivos."""
        source_path = _validate_pdf_input(source)
        destination = _validate_image_output_directory(output_directory)
        page_total = total_pages if total_pages is not None else self.page_count(source)
        pages = _selected_pages(selection, page_total)
        normalized_format = _normalize_image_format(image_format)
        return _pdf_image_output_paths(
            source_path,
            destination,
            pages,
            page_total,
            normalized_format,
        )

    @serialized_pdfium
    def pdf_to_images(
        self,
        source: Path | str,
        selection: str | None,
        image_format: str,
        output_directory: Path | str,
        *,
        overwrite: bool = False,
        quality: PdfImageQuality = PdfImageQuality.STANDARD,
        cancel_event: Event | None = None,
        progress: Callable[[PdfOperationProgress], None] | None = None,
    ) -> PdfImageExportResult:
        """Renderiza páginas inteiras em PNG/JPG com qualidade limitada e local."""
        _validate_pdf_image_quality(quality)
        _validate_operation_hooks(cancel_event, progress)
        source_path = _validate_pdf_input(source)
        destination = _validate_image_output_directory(output_directory)
        normalized_format = _normalize_image_format(image_format)
        document = _open_pdfium_document(source_path)
        temporary_paths: list[Path] = []
        try:
            total_pages = len(document)
            if total_pages < 1:
                raise InvalidPdfError(
                    f'O arquivo "{source_path.name}" não contém páginas.'
                )
            pages = _selected_pages(selection, total_pages)
            try:
                pdf_export_requires_warning(len(pages))
            except PrintLayoutError as error:
                raise PdfToolsError(
                    "A seleção excede o limite seguro de 500 páginas."
                ) from error
            output_paths = _pdf_image_output_paths(
                source_path,
                destination,
                pages,
                total_pages,
                normalized_format,
            )
            _validate_image_output_conflicts(output_paths, overwrite)
            _raise_if_cancelled(cancel_event)

            prepared: list[tuple[Path, Path]] = []
            _report_operation_progress(progress, 0, len(pages))
            for completed_pages, (page_number, output_path) in enumerate(
                zip(pages, output_paths, strict=True),
                start=1,
            ):
                _raise_if_cancelled(cancel_event)
                temporary_path = _new_image_temporary(output_path)
                temporary_paths.append(temporary_path)
                _render_pdf_page(
                    document,
                    page_number,
                    temporary_path,
                    normalized_format,
                    quality,
                )
                prepared.append((temporary_path, output_path))
                _report_operation_progress(progress, completed_pages, len(pages))
                _raise_if_cancelled(cancel_event)

            _publish_image_outputs(prepared, overwrite, cancel_event=cancel_event)
            temporary_paths.clear()
            return PdfImageExportResult(destination, output_paths, pages)
        except PdfToolsError:
            raise
        except Exception as error:
            raise PdfToolsError(
                "Não foi possível converter as páginas do PDF em imagens."
            ) from error
        finally:
            document.close()
            for temporary_path in temporary_paths:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _validate_pdf_input(value: Path | str) -> Path:
    try:
        path = validate_local_regular_file(value)
    except LocalFilesError as error:
        try:
            display_name = Path(value).name or "arquivo"
        except (OSError, TypeError, ValueError):
            display_name = "arquivo"
        raise InvalidPdfError(_invalid_pdf_message(display_name)) from error
    if path.suffix.casefold() != ".pdf":
        raise InvalidPdfError(_invalid_pdf_message(path.name or "arquivo"))
    return path


def _validate_image_input(value: Path | str) -> Path:
    try:
        path = validate_local_regular_file(value)
    except LocalFilesError as error:
        try:
            display_name = Path(value).name or "arquivo"
        except (OSError, TypeError, ValueError):
            display_name = "arquivo"
        raise InvalidImageError(_invalid_image_message(display_name)) from error
    if path.suffix.casefold() not in SUPPORTED_IMAGE_SUFFIXES:
        raise InvalidImageError(_invalid_image_message(path.name or "arquivo"))
    return path


def _validate_images_to_pdf_layout(
    layout: ImagePageLayout | None,
) -> ImagePageLayout:
    if layout is None:
        return ImagePageLayout()
    if not isinstance(layout, ImagePageLayout):
        raise PdfToolsError("A configuração de página não é válida.")
    return layout


def _validate_images_to_pdf_hooks(
    cancel_event: Event | None,
    progress: Callable[[ImagesToPdfProgress], None] | None,
) -> None:
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise PdfToolsError("O controle de cancelamento não é válido.")
    if progress is not None and not callable(progress):
        raise PdfToolsError("O callback de progresso não é válido.")


def _validate_operation_hooks(
    cancel_event: Event | None,
    progress: Callable[[PdfOperationProgress], None] | None,
) -> None:
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise PdfToolsError("O controle de cancelamento não é válido.")
    if progress is not None and not callable(progress):
        raise PdfToolsError("O callback de progresso não é válido.")


def _validate_pdf_image_quality(quality: PdfImageQuality) -> None:
    if not isinstance(quality, PdfImageQuality):
        raise PdfToolsError("Escolha a qualidade Padrão ou Alta.")


def _validate_images_to_pdf_output(
    value: Path | str,
    inputs: Sequence[Path],
    overwrite: bool,
) -> Path:
    try:
        output = validate_local_output_path(value, inputs=inputs)
    except LocalFilesError as error:
        raise PdfToolsError("O arquivo de saída não é válido ou local.") from error
    if output.suffix.casefold() != ".pdf":
        raise PdfToolsError("O arquivo de saída deve usar a extensão .pdf.")
    if output.exists() and not overwrite:
        raise PdfToolsError("O arquivo de saída já existe e não foi substituído.")
    return output


def _validate_image_output_directory(value: Path | str) -> Path:
    try:
        directory = Path(value)
        return validate_local_output_path(
            directory / ".edudownloader-directory-validation"
        ).parent
    except (LocalFilesError, OSError, TypeError, ValueError) as error:
        raise PdfToolsError("A pasta de destino não está disponível.") from error


def _validate_output(
    value: Path | str,
    inputs: Sequence[Path],
    overwrite: bool,
) -> Path:
    try:
        output = validate_local_output_path(value, inputs=inputs)
    except LocalFilesError as error:
        raise PdfToolsError("O arquivo de saída não é válido ou local.") from error
    if output.suffix.casefold() != ".pdf":
        raise PdfToolsError("O arquivo de saída deve usar a extensão .pdf.")
    if any(_same_path(output, source) for source in inputs):
        raise PdfToolsError("O arquivo de saída não pode ser um arquivo de entrada.")
    if output.exists() and not overwrite:
        raise PdfToolsError("O arquivo de saída já existe e não foi substituído.")
    return output


def _same_path(first: Path, second: Path) -> bool:
    try:
        return first.samefile(second)
    except (FileNotFoundError, OSError):
        return os.path.normcase(os.path.abspath(first)) == os.path.normcase(
            os.path.abspath(second)
        )


def _read_pdf(stream: object, display_name: str) -> PdfReader:
    try:
        reader = PdfReader(stream, strict=False)
        if reader.is_encrypted:
            raise InvalidPdfError(
                f'O arquivo "{display_name}" é protegido por senha e não é suportado.'
            )
        if len(reader.pages) < 1:
            raise InvalidPdfError(f'O arquivo "{display_name}" não contém páginas.')
        return reader
    except PdfToolsError:
        raise
    except Exception as error:
        raise InvalidPdfError(_invalid_pdf_message(display_name)) from error


def _write_atomically(
    output: Path,
    overwrite: bool,
    producer: Callable[[Path], int],
    *,
    cancel_event: Event | None = None,
) -> PdfOperationResult:
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.stem}-",
            suffix=".tmp.pdf",
            dir=output.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        expected_pages = producer(temporary_path)
        if expected_pages < 1:
            raise PdfToolsError("A operação não produziu páginas.")
        with temporary_path.open("rb") as stream:
            result_reader = _read_pdf(stream, "resultado temporário")
            if len(result_reader.pages) != expected_pages:
                raise PdfToolsError("O PDF gerado não pôde ser validado.")
            _validate_generated_pdf_pages(result_reader)
        _raise_if_cancelled(cancel_event)
        if output.exists() and not overwrite:
            raise PdfToolsError("O arquivo de saída já existe e não foi substituído.")
        if overwrite:
            os.replace(temporary_path, output)
        else:
            os.rename(temporary_path, output)
        temporary_path = None
        return PdfOperationResult(output, expected_pages)
    except PdfToolsError:
        raise
    except (OSError, PermissionError) as error:
        raise PdfToolsError(
            "Não foi possível gravar o resultado. Verifique a pasta e o arquivo."
        ) from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _validate_generated_pdf_pages(reader: PdfReader) -> None:
    try:
        for page in reader.pages:
            if float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0:
                raise PdfToolsError("O PDF gerado contém uma página inválida.")
    except PdfToolsError:
        raise
    except Exception as error:
        raise PdfToolsError("O PDF gerado não pôde ser validado.") from error


def _image_as_a4_page(path: Path) -> Image.Image:
    """Adaptador histórico para o layout default A4/AUTO/NORMAL/1."""

    return _images_as_pdf_page((path,), ImagePageLayout())


def _images_as_pdf_page(
    paths: Sequence[Path],
    layout: ImagePageLayout,
    *,
    resolution_dpi: int = _PDF_RESOLUTION_DPI,
    image_loader=None,
    source_sizes: Sequence[Size] | None = None,
    rotations: Sequence[int] | None = None,
) -> Image.Image:
    """Renderiza um grupo em uma página, mantendo somente o grupo atual aberto."""

    images: list[Image.Image] = []
    page: Image.Image | None = None
    try:
        angles = image_rotations(rotations, len(paths))
        for path, angle in zip(paths, angles):
            image = (image_loader or _load_normalized_image)(path)
            if angle:
                try:
                    rotated = image.transpose(
                        {
                            90: Image.Transpose.ROTATE_270,
                            180: Image.Transpose.ROTATE_180,
                            270: Image.Transpose.ROTATE_90,
                        }[angle]
                    )
                finally:
                    image.close()
                image = rotated
            images.append(image)
        if source_sizes is not None:
            source_sizes = tuple(
                rotated_image_size(size, angle)
                for size, angle in zip(source_sizes, angles, strict=True)
            )
        orientation = choose_image_page_orientation(
            source_sizes or tuple(Size(*image.size) for image in images),
            layout,
        )
        page_size = raster_dimensions(
            page_dimensions(layout.paper, orientation),
            resolution_dpi,
        )
        slots = image_slots(
            layout.paper,
            orientation,
            layout.margin,
            layout.images_per_page,
        )
        page = Image.new("RGB", page_size, "white")
        for index, (image, slot) in enumerate(zip(images, slots, strict=False)):
            pixel_slot = _rect_to_pixels(slot, page_size, resolution_dpi)
            size = (
                (source_sizes[index].width, source_sizes[index].height)
                if source_sizes
                else image.size
            )
            fitted_size, position = _fit_image_to_slot(size, pixel_slot)
            fitted = (
                image.copy()
                if fitted_size == image.size
                else image.resize(fitted_size, Image.Resampling.LANCZOS)
            )
            try:
                page.paste(fitted, position)
            finally:
                fitted.close()
        result = page
        page = None
        return result
    finally:
        if page is not None:
            page.close()
        for image in images:
            image.close()


def _load_normalized_image(path: Path) -> Image.Image:
    """Revalida, orienta por EXIF e normaliza uma imagem sem manter handles."""

    path = _validate_image_input(path)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path, formats=("JPEG", "PNG")) as source:
                if source.format not in {"JPEG", "PNG"}:
                    raise InvalidImageError(_invalid_image_message(path.name))
                validate_conversion_image_dimensions(source.width, source.height)
                source.load()
                oriented = ImageOps.exif_transpose(source)
                try:
                    return _flatten_to_rgb(oriented)
                finally:
                    if oriented is not source:
                        oriented.close()
    except InvalidImageError:
        raise
    except PrintLayoutError as error:
        raise InvalidImageError(
            f'A imagem "{path.name}" excede o limite seguro de conversão.'
        ) from error
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise InvalidImageError(_invalid_image_message(path.name)) from error


def _calculate_image_layout(
    image_size: tuple[int, int],
    page_size: tuple[int, int],
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Compatibilidade histórica implementada pelo mesmo contain da 1.3-A."""

    slot = Rect(
        _A4_MARGIN_PIXELS,
        _A4_MARGIN_PIXELS,
        page_size[0] - 2 * _A4_MARGIN_PIXELS,
        page_size[1] - 2 * _A4_MARGIN_PIXELS,
    )
    return _fit_image_to_slot(image_size, slot)


def _rect_to_pixels(
    rect: Rect, page_size: tuple[int, int], dpi: int = _PDF_RESOLUTION_DPI
) -> Rect:
    scale = dpi / 72.0
    left = max(0, round(rect.x * scale))
    top = max(0, round(rect.y * scale))
    right = min(page_size[0], round((rect.x + rect.width) * scale))
    bottom = min(page_size[1], round((rect.y + rect.height) * scale))
    return Rect(left, top, right - left, bottom - top)


def _fit_image_to_slot(
    image_size: tuple[int, int],
    slot: Rect,
) -> tuple[tuple[int, int], tuple[int, int]]:
    placement = contain_image(Size(*image_size), slot)
    fitted_size = (
        min(round(slot.width), max(1, round(placement.width))),
        min(round(slot.height), max(1, round(placement.height))),
    )
    position = (
        round(slot.x) + (round(slot.width) - fitted_size[0]) // 2,
        round(slot.y) + (round(slot.height) - fitted_size[1]) // 2,
    )
    return fitted_size, position


def _append_image_page(writer: PdfWriter, page: Image.Image) -> None:
    """Converte uma página raster em PDF e libera o buffer após cloná-la."""

    with BytesIO() as buffer:
        page.save(buffer, "PDF", resolution=_PDF_RESOLUTION_DPI)
        buffer.seek(0)
        reader = _read_pdf(buffer, "página de imagens temporária")
        if len(reader.pages) != 1:
            raise PdfToolsError("Uma página de imagens não pôde ser validada.")
        writer.add_page(reader.pages[0])


def _raise_if_cancelled(cancel_event: Event | None) -> None:
    if cancel_event is None:
        return
    try:
        cancelled = cancel_event.is_set()
    except Exception as error:
        raise PdfToolsError(
            "O controle de cancelamento não pôde ser consultado."
        ) from error
    if cancelled:
        raise PdfOperationCancelled("A operação PDF foi cancelada.")


def _report_images_to_pdf_progress(
    callback: Callable[[ImagesToPdfProgress], None] | None,
    completed_pages: int,
    total_pages: int,
) -> None:
    if callback is None:
        return
    try:
        callback(ImagesToPdfProgress(completed_pages, total_pages))
    except PdfToolsError:
        raise
    except Exception as error:
        raise PdfToolsError(
            "Não foi possível comunicar o progresso da operação."
        ) from error


def _report_operation_progress(
    callback: Callable[[PdfOperationProgress], None] | None,
    completed_items: int,
    total_items: int,
) -> None:
    if callback is None:
        return
    try:
        callback(PdfOperationProgress(completed_items, total_items))
    except PdfToolsError:
        raise
    except Exception as error:
        raise PdfToolsError(
            "Não foi possível comunicar o progresso da operação."
        ) from error


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        try:
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        finally:
            rgba.close()
    return image.convert("RGB")


def _open_pdfium_document(source: Path) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(source)
    except pdfium.PdfiumError as error:
        if error.err_code == pdfium_raw.FPDF_ERR_PASSWORD:
            raise InvalidPdfError(
                f'O arquivo "{source.name}" é protegido por senha e não é suportado.'
            ) from error
        raise InvalidPdfError(_invalid_pdf_message(source.name)) from error
    except (OSError, ValueError) as error:
        raise InvalidPdfError(_invalid_pdf_message(source.name)) from error


def _selected_pages(selection: str | None, total_pages: int) -> tuple[int, ...]:
    if total_pages < 1:
        raise InvalidPageSelectionError("O PDF não contém páginas disponíveis.")
    pages = (
        tuple(range(1, total_pages + 1))
        if selection is None
        else parse_page_selection(selection, total_pages)
    )
    if len(set(pages)) != len(pages):
        raise InvalidPageSelectionError(
            "Não repita páginas ao exportar imagens do PDF."
        )
    return pages


def _normalize_image_format(value: str) -> str:
    normalized = str(value).strip().upper()
    if normalized == "JPEG":
        normalized = "JPG"
    if normalized not in _PDF_TO_IMAGE_FORMATS:
        raise PdfToolsError("Escolha o formato PNG ou JPG.")
    return normalized


def _safe_output_stem(stem: str) -> str:
    sanitized = _UNSAFE_FILENAME_CHARACTERS.sub("_", stem).strip(" .")
    sanitized = sanitized or "documento"
    if sanitized.upper() in _WINDOWS_RESERVED_NAMES:
        sanitized = f"_{sanitized}"
    return sanitized


def _pdf_image_output_paths(
    source: Path,
    output_directory: Path,
    pages: tuple[int, ...],
    total_pages: int,
    image_format: str,
) -> tuple[Path, ...]:
    padding = max(3, len(str(total_pages)))
    extension = image_format.casefold()
    stem = _safe_output_stem(source.stem)
    return tuple(
        output_directory / f"{stem}-pagina-{page_number:0{padding}d}.{extension}"
        for page_number in pages
    )


def _validate_image_output_conflicts(
    output_paths: Sequence[Path], overwrite: bool
) -> None:
    for output_path in output_paths:
        if output_path.exists() and not output_path.is_file():
            raise PdfToolsError(
                "Um item na pasta de destino impede a criação das imagens."
            )
    conflicts = tuple(path for path in output_paths if path.exists())
    if conflicts and not overwrite:
        raise PdfToolsError(
            f"{len(conflicts)} imagem(ns) de saída já existem e não foram substituídas."
        )


def _new_image_temporary(output_path: Path) -> Path:
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.stem}-",
            suffix=f".tmp{output_path.suffix}",
            dir=output_path.parent,
        )
        os.close(descriptor)
        return Path(temporary_name)
    except OSError as error:
        raise PdfToolsError(
            "Não foi possível preparar os arquivos na pasta de destino."
        ) from error


def _render_pdf_page(
    document: pdfium.PdfDocument,
    page_number: int,
    temporary_path: Path,
    image_format: str,
    quality: PdfImageQuality,
) -> None:
    page = None
    bitmap = None
    rendered = None
    normalized = None
    try:
        page = document[page_number - 1]
        source_width, source_height = page.get_size()
        try:
            validate_pdf_page_dimensions(source_width, source_height)
            scale = pdfium_scale(quality)
            validate_conversion_image_dimensions(
                max(1, round(source_width * scale)),
                max(1, round(source_height * scale)),
            )
        except PrintLayoutError as error:
            raise PdfToolsError(
                f"A página {page_number} excede o limite seguro de conversão."
            ) from error
        bitmap = page.render(
            scale=scale,
            fill_color=(255, 255, 255, 255),
        )
        rendered = bitmap.to_pil()
        normalized = rendered.convert("RGB")
        if image_format == "PNG":
            normalized.save(temporary_path, "PNG")
        else:
            normalized.save(
                temporary_path,
                "JPEG",
                quality=_PDF_TO_IMAGE_JPEG_QUALITY,
            )
        _validate_rendered_image(temporary_path, image_format, normalized.size)
    except PdfToolsError:
        raise
    except (OSError, ValueError, pdfium.PdfiumError) as error:
        raise PdfToolsError(
            f"Não foi possível renderizar a página {page_number} do PDF."
        ) from error
    finally:
        if normalized is not None:
            normalized.close()
        if rendered is not None:
            rendered.close()
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()


def _validate_rendered_image(
    path: Path, image_format: str, expected_size: tuple[int, int]
) -> None:
    expected_format = "JPEG" if image_format == "JPG" else "PNG"
    try:
        with Image.open(path, formats=(expected_format,)) as image:
            image.load()
            if image.format != expected_format or image.size != expected_size:
                raise PdfToolsError("Uma imagem temporária não pôde ser validada.")
    except PdfToolsError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as error:
        raise PdfToolsError("Uma imagem temporária não pôde ser validada.") from error


def _publish_image_outputs(
    prepared: Sequence[tuple[Path, Path]],
    overwrite: bool,
    *,
    cancel_event: Event | None = None,
) -> None:
    backups: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        _raise_if_cancelled(cancel_event)
        _validate_image_output_conflicts(
            tuple(output_path for _temporary, output_path in prepared), overwrite
        )
        if overwrite:
            for _temporary_path, output_path in prepared:
                _raise_if_cancelled(cancel_event)
                if not output_path.exists():
                    continue
                descriptor, backup_name = tempfile.mkstemp(
                    prefix=f".{output_path.stem}-",
                    suffix=f".bak{output_path.suffix}",
                    dir=output_path.parent,
                )
                os.close(descriptor)
                backup_path = Path(backup_name)
                backup_path.unlink()
                os.replace(output_path, backup_path)
                backups[output_path] = backup_path

        for temporary_path, output_path in prepared:
            _raise_if_cancelled(cancel_event)
            if overwrite:
                os.replace(temporary_path, output_path)
            else:
                os.rename(temporary_path, output_path)
            published.append(output_path)
        _raise_if_cancelled(cancel_event)
    except (PdfToolsError, OSError, PermissionError) as error:
        for output_path in reversed(published):
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
        for output_path, backup_path in backups.items():
            try:
                os.replace(backup_path, output_path)
            except OSError:
                pass
        if isinstance(error, PdfToolsError):
            raise
        raise PdfToolsError(
            "Não foi possível publicar todas as imagens na pasta de destino."
        ) from error
    else:
        for backup_path in backups.values():
            try:
                backup_path.unlink(missing_ok=True)
            except OSError:
                pass


def _invalid_pdf_message(name: str) -> str:
    return f'O arquivo "{name}" não é um PDF válido ou legível.'


def _invalid_image_message(name: str) -> str:
    return f'A imagem "{name}" não é um JPG ou PNG válido.'
