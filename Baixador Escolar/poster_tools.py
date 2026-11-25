"""Motor local e independente de interface para pôsteres PDF paginados."""

from __future__ import annotations

import math
import os
import tempfile
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import Event
from typing import Final

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter

from local_files import (
    LocalFilesError,
    validate_local_output_path,
    validate_local_regular_file,
)
from print_layout import (
    EffectivePpi,
    MarginPreset,
    Orientation,
    OverlapPreset,
    PaperSize,
    PdfImageQuality,
    PosterGrid,
    PosterLayout,
    PrintLayoutError,
    Rect,
    Size,
    choose_poster_orientation,
    contain_image,
    effective_poster_ppi,
    page_content_rect,
    page_dimensions,
    poster_page_position,
    poster_panel_size,
    raster_dimensions,
    validate_conversion_image_dimensions,
    validate_pdf_page_dimensions,
)


SUPPORTED_POSTER_IMAGE_SUFFIXES: Final = frozenset({".jpg", ".jpeg", ".png"})
POSTER_RENDER_DPI: Final = PdfImageQuality.STANDARD.dpi
POSTER_MARGIN: Final = MarginPreset.NORMAL
_POINTS_PER_INCH: Final = 72.0
_PDF_DIMENSION_TOLERANCE_POINTS: Final = 1.0
_CROP_MARK_LENGTH_POINTS: Final = 9.0
_CROP_MARK_GAP_POINTS: Final = 3.0


class PosterToolsError(Exception):
    """Erro seguro do motor de pôster que pode ser apresentado pela interface."""


class InvalidPosterImageError(PosterToolsError):
    """A imagem de entrada não pôde ser usada com segurança."""


class PosterOperationCancelled(PosterToolsError):
    """A criação do pôster foi cancelada cooperativamente."""


@dataclass(frozen=True, slots=True)
class PosterProgress:
    """Progresso imutável em páginas concluídas."""

    completed_pages: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class NormalizedCrop:
    """Recorte normalizado da imagem original, no intervalo de zero a um."""

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        values = (self.left, self.top, self.right, self.bottom)
        if not all(math.isfinite(value) for value in values):
            raise PosterToolsError("O recorte calculado para o pôster é inválido.")
        if not (0 <= self.left < self.right <= 1):
            raise PosterToolsError("O recorte horizontal do pôster é inválido.")
        if not (0 <= self.top < self.bottom <= 1):
            raise PosterToolsError("O recorte vertical do pôster é inválido.")

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class PosterTilePlan:
    """Plano puro de uma folha, em ordem de leitura."""

    page_index: int
    row: int
    column: int
    panel_viewport: Rect
    source_crop: NormalizedCrop | None
    destination: Rect | None


@dataclass(frozen=True, slots=True)
class PosterPlan:
    """Geometria completa e determinística de um pôster."""

    orientation: Orientation
    page_size: Size
    content_rect: Rect
    panel_size: Size
    image_placement: Rect
    effective_ppi: EffectivePpi
    tiles: tuple[PosterTilePlan, ...]

    @property
    def page_count(self) -> int:
        return len(self.tiles)


@dataclass(frozen=True, slots=True)
class PosterRequest:
    """Pedido imutável para gerar um único PDF de pôster."""

    input_path: Path
    output_path: Path
    paper: PaperSize = PaperSize.A4
    orientation: Orientation = Orientation.AUTO
    grid: PosterGrid = PosterGrid.TWO_BY_TWO
    overlap: OverlapPreset = OverlapPreset.SMALL
    show_crop_marks: bool = False
    overwrite: bool = False
    cancel_event: Event | None = None
    progress: Callable[[PosterProgress], None] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.input_path, Path) or not isinstance(
            self.output_path, Path
        ):
            raise PosterToolsError("Os caminhos do pôster são inválidos.")
        try:
            PosterLayout(
                paper=self.paper,
                orientation=self.orientation,
                margin=POSTER_MARGIN,
                grid=self.grid,
                overlap=self.overlap,
                show_crop_marks=self.show_crop_marks,
            )
        except PrintLayoutError as error:
            raise PosterToolsError("A configuração do pôster é inválida.") from error
        if not isinstance(self.overwrite, bool):
            raise PosterToolsError("A política de substituição é inválida.")
        _validate_operation_hooks(self.cancel_event, self.progress)


@dataclass(frozen=True, slots=True)
class PosterResult:
    """Resultado validado de uma criação de pôster."""

    output_path: Path
    page_count: int
    orientation: Orientation
    effective_ppi: EffectivePpi


class PosterService:
    """Gera pôsteres locais sem importar ou conhecer a interface gráfica."""

    def create(self, request: PosterRequest) -> PosterResult:
        if not isinstance(request, PosterRequest):
            raise PosterToolsError("O pedido de pôster é inválido.")
        source_path = _validate_image_input(request.input_path)
        output_path = _validate_output(
            request.output_path, source_path, request.overwrite
        )
        _raise_if_cancelled(request.cancel_event)

        image = _load_normalized_image(source_path)
        try:
            layout = PosterLayout(
                paper=request.paper,
                orientation=request.orientation,
                margin=POSTER_MARGIN,
                grid=request.grid,
                overlap=request.overlap,
                show_crop_marks=request.show_crop_marks,
            )
            plan = plan_poster(Size(*image.size), layout)
            _write_poster_atomically(request, output_path, image, plan)
        finally:
            image.close()
        return PosterResult(
            output_path=output_path,
            page_count=plan.page_count,
            orientation=plan.orientation,
            effective_ppi=plan.effective_ppi,
        )


def plan_poster(
    image_size: Size | tuple[float, float], layout: PosterLayout
) -> PosterPlan:
    """Planeja folhas e recortes sem abrir arquivos nem alocar um painel raster."""

    if not isinstance(layout, PosterLayout):
        raise PosterToolsError("A configuração do pôster é inválida.")
    image = image_size if isinstance(image_size, Size) else Size(*image_size)
    orientation = choose_poster_orientation(image, layout)
    page_size = page_dimensions(layout.paper, orientation)
    content = page_content_rect(layout.paper, orientation, layout.margin)
    panel = poster_panel_size(
        layout.paper,
        orientation,
        layout.margin,
        layout.grid,
        layout.overlap,
    )
    placement = contain_image(image, Rect(0.0, 0.0, panel.width, panel.height))
    placement_rect = Rect(
        placement.x,
        placement.y,
        placement.width,
        placement.height,
    )
    step_x = content.width - layout.overlap.points
    step_y = content.height - layout.overlap.points
    tiles = tuple(
        _plan_tile(
            page_index,
            layout.grid,
            content,
            placement_rect,
            step_x,
            step_y,
        )
        for page_index in range(layout.grid.page_count)
    )
    return PosterPlan(
        orientation=orientation,
        page_size=page_size,
        content_rect=content,
        panel_size=panel,
        image_placement=placement_rect,
        effective_ppi=effective_poster_ppi(image, panel),
        tiles=tiles,
    )


def _plan_tile(
    page_index: int,
    grid: PosterGrid,
    content: Rect,
    placement: Rect,
    step_x: float,
    step_y: float,
) -> PosterTilePlan:
    row, column = poster_page_position(grid, page_index)
    viewport = Rect(
        column * step_x,
        row * step_y,
        content.width,
        content.height,
    )
    intersection = _intersect_rectangles(viewport, placement)
    if intersection is None:
        return PosterTilePlan(page_index, row, column, viewport, None, None)
    crop = NormalizedCrop(
        left=_unit_interval((intersection.x - placement.x) / placement.width),
        top=_unit_interval((intersection.y - placement.y) / placement.height),
        right=_unit_interval(
            (intersection.x + intersection.width - placement.x) / placement.width
        ),
        bottom=_unit_interval(
            (intersection.y + intersection.height - placement.y) / placement.height
        ),
    )
    destination = Rect(
        content.x + intersection.x - viewport.x,
        content.y + intersection.y - viewport.y,
        intersection.width,
        intersection.height,
    )
    return PosterTilePlan(
        page_index,
        row,
        column,
        viewport,
        crop,
        destination,
    )


def _intersect_rectangles(first: Rect, second: Rect) -> Rect | None:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    if right <= left or bottom <= top:
        return None
    return Rect(left, top, right - left, bottom - top)


def _unit_interval(value: float) -> float:
    return min(1.0, max(0.0, value))


def _write_poster_atomically(
    request: PosterRequest,
    output_path: Path,
    image: Image.Image,
    plan: PosterPlan,
) -> None:
    temporary_path: Path | None = None
    writer = PdfWriter()
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.stem}-",
            suffix=".tmp.pdf",
            dir=output_path.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        _report_progress(request.progress, 0, plan.page_count)
        for completed_pages, tile in enumerate(plan.tiles, start=1):
            _raise_if_cancelled(request.cancel_event)
            page = _render_poster_page(
                image,
                plan,
                tile,
                show_crop_marks=request.show_crop_marks,
            )
            try:
                _append_image_page(writer, page)
            finally:
                page.close()
            _report_progress(request.progress, completed_pages, plan.page_count)
            _raise_if_cancelled(request.cancel_event)
        with temporary_path.open("wb") as destination:
            writer.write(destination)
        _raise_if_cancelled(request.cancel_event)
        _validate_generated_poster(temporary_path, plan)
        _raise_if_cancelled(request.cancel_event)
        _publish_output(temporary_path, output_path, request.overwrite)
        temporary_path = None
    except PosterToolsError:
        raise
    except (OSError, PermissionError) as error:
        raise PosterToolsError(
            "Não foi possível gravar o pôster. Verifique a pasta e o arquivo."
        ) from error
    except Exception as error:
        raise PosterToolsError("Não foi possível criar o pôster PDF.") from error
    finally:
        writer.close()
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _render_poster_page(
    image: Image.Image,
    plan: PosterPlan,
    tile: PosterTilePlan,
    *,
    show_crop_marks: bool,
    render_dpi: int = POSTER_RENDER_DPI,
) -> Image.Image:
    page_pixels = raster_dimensions(plan.page_size, render_dpi)
    page = Image.new("RGB", page_pixels, "white")
    if tile.source_crop is not None and tile.destination is not None:
        source_box = _normalized_crop_to_pixels(tile.source_crop, image.size)
        destination_box = _rect_to_pixel_box(tile.destination, page_pixels, render_dpi)
        cropped = image.crop(source_box)
        fitted: Image.Image | None = None
        try:
            destination_size = (
                destination_box[2] - destination_box[0],
                destination_box[3] - destination_box[1],
            )
            fitted = cropped.resize(destination_size, Image.Resampling.LANCZOS)
            page.paste(fitted, destination_box[:2])
        finally:
            if fitted is not None:
                fitted.close()
            cropped.close()
    if show_crop_marks:
        _draw_crop_marks(page, plan.content_rect, render_dpi)
    return page


def _normalized_crop_to_pixels(
    crop: NormalizedCrop, image_size: tuple[int, int]
) -> tuple[int, int, int, int]:
    width, height = image_size
    left = max(0, min(width - 1, math.floor(crop.left * width)))
    top = max(0, min(height - 1, math.floor(crop.top * height)))
    right = max(left + 1, min(width, math.ceil(crop.right * width)))
    bottom = max(top + 1, min(height, math.ceil(crop.bottom * height)))
    return left, top, right, bottom


def _rect_to_pixel_box(
    rect: Rect, page_size: tuple[int, int], dpi: int = POSTER_RENDER_DPI
) -> tuple[int, int, int, int]:
    scale = dpi / _POINTS_PER_INCH
    left = max(0, min(page_size[0] - 1, math.floor(rect.x * scale)))
    top = max(0, min(page_size[1] - 1, math.floor(rect.y * scale)))
    right = max(
        left + 1,
        min(page_size[0], math.ceil((rect.x + rect.width) * scale)),
    )
    bottom = max(
        top + 1,
        min(page_size[1], math.ceil((rect.y + rect.height) * scale)),
    )
    return left, top, right, bottom


def _draw_crop_marks(
    page: Image.Image, content: Rect, dpi: int = POSTER_RENDER_DPI
) -> None:
    segments = _crop_mark_segments(content, page.size, dpi)
    draw = ImageDraw.Draw(page)
    width = max(1, round(0.5 * dpi / _POINTS_PER_INCH))
    for start, end in segments:
        draw.line((start, end), fill="black", width=width)


def _crop_mark_segments(
    content: Rect, page_size: tuple[int, int], dpi: int = POSTER_RENDER_DPI
) -> tuple[tuple[tuple[int, int], tuple[int, int]], ...]:
    scale = dpi / _POINTS_PER_INCH
    left, top, right, bottom = _rect_to_pixel_box(content, page_size, dpi)
    gap = max(1, round(_CROP_MARK_GAP_POINTS * scale))
    length = max(1, round(_CROP_MARK_LENGTH_POINTS * scale))
    return (
        ((max(0, left - gap - length), top), (left - gap, top)),
        ((left, max(0, top - gap - length)), (left, top - gap)),
        ((right + gap, top), (min(page_size[0] - 1, right + gap + length), top)),
        ((right - 1, max(0, top - gap - length)), (right - 1, top - gap)),
        ((max(0, left - gap - length), bottom - 1), (left - gap, bottom - 1)),
        ((left, bottom + gap), (left, min(page_size[1] - 1, bottom + gap + length))),
        (
            (right + gap, bottom - 1),
            (min(page_size[0] - 1, right + gap + length), bottom - 1),
        ),
        (
            (right - 1, bottom + gap),
            (right - 1, min(page_size[1] - 1, bottom + gap + length)),
        ),
    )


def _append_image_page(writer: PdfWriter, page: Image.Image) -> None:
    with BytesIO() as buffer:
        page.save(buffer, "PDF", resolution=POSTER_RENDER_DPI)
        buffer.seek(0)
        reader = PdfReader(buffer, strict=False)
        if reader.is_encrypted or len(reader.pages) != 1:
            raise PosterToolsError("Uma folha do pôster não pôde ser validada.")
        writer.add_page(reader.pages[0])


def _validate_generated_poster(path: Path, plan: PosterPlan) -> None:
    try:
        with path.open("rb") as stream:
            reader = PdfReader(stream, strict=False)
            if reader.is_encrypted or len(reader.pages) != plan.page_count:
                raise PosterToolsError("O PDF de pôster gerado não pôde ser validado.")
            for page in reader.pages:
                actual = validate_pdf_page_dimensions(
                    float(page.mediabox.width), float(page.mediabox.height)
                )
                if (
                    abs(actual.width - plan.page_size.width)
                    > _PDF_DIMENSION_TOLERANCE_POINTS
                    or abs(actual.height - plan.page_size.height)
                    > _PDF_DIMENSION_TOLERANCE_POINTS
                ):
                    raise PosterToolsError(
                        "O PDF de pôster gerado possui dimensões inesperadas."
                    )
    except PosterToolsError:
        raise
    except (OSError, ValueError, PrintLayoutError) as error:
        raise PosterToolsError(
            "O PDF de pôster gerado não pôde ser validado."
        ) from error


def _publish_output(temporary: Path, output: Path, overwrite: bool) -> None:
    validated = _validate_output(output, None, overwrite)
    if validated != output:
        raise PosterToolsError("O arquivo de saída mudou durante a operação.")
    if overwrite:
        os.replace(temporary, output)
    else:
        os.rename(temporary, output)


def _validate_image_input(value: Path) -> Path:
    if value.suffix.casefold() not in SUPPORTED_POSTER_IMAGE_SUFFIXES:
        raise InvalidPosterImageError("Selecione uma imagem JPG, JPEG ou PNG.")
    try:
        return validate_local_regular_file(value)
    except LocalFilesError as error:
        raise InvalidPosterImageError(str(error)) from error


def _validate_output(value: Path, source: Path | None, overwrite: bool) -> Path:
    if value.suffix.casefold() != ".pdf":
        raise PosterToolsError("O arquivo de saída deve usar a extensão .pdf.")
    try:
        output = validate_local_output_path(
            value,
            inputs=() if source is None else (source,),
        )
    except LocalFilesError as error:
        raise PosterToolsError(str(error)) from error
    if output.exists() and not overwrite:
        raise PosterToolsError("O arquivo de saída já existe e não foi substituído.")
    return output


def _load_normalized_image(path: Path) -> Image.Image:
    path = _validate_image_input(path)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path, formats=("JPEG", "PNG")) as source:
                if source.format not in {"JPEG", "PNG"}:
                    raise InvalidPosterImageError(
                        "A imagem selecionada não é um JPG ou PNG válido."
                    )
                validate_conversion_image_dimensions(source.width, source.height)
                source.load()
                oriented = ImageOps.exif_transpose(source)
                try:
                    return _flatten_to_rgb(oriented)
                finally:
                    if oriented is not source:
                        oriented.close()
    except InvalidPosterImageError:
        raise
    except PrintLayoutError as error:
        raise InvalidPosterImageError(
            "A imagem excede o limite seguro de conversão."
        ) from error
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise InvalidPosterImageError(
            "A imagem selecionada não pôde ser lida com segurança."
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


def _validate_operation_hooks(
    cancel_event: Event | None,
    progress: Callable[[PosterProgress], None] | None,
) -> None:
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise PosterToolsError("O controle de cancelamento é inválido.")
    if progress is not None and not callable(progress):
        raise PosterToolsError("O callback de progresso é inválido.")


def _raise_if_cancelled(cancel_event: Event | None) -> None:
    if cancel_event is None:
        return
    try:
        cancelled = cancel_event.is_set()
    except Exception as error:
        raise PosterToolsError(
            "O controle de cancelamento não pôde ser consultado."
        ) from error
    if cancelled:
        raise PosterOperationCancelled("A criação do pôster foi cancelada.")


def _report_progress(
    callback: Callable[[PosterProgress], None] | None,
    completed_pages: int,
    total_pages: int,
) -> None:
    if callback is None:
        return
    try:
        callback(PosterProgress(completed_pages, total_pages))
    except PosterToolsError:
        raise
    except Exception as error:
        raise PosterToolsError(
            "Não foi possível comunicar o progresso do pôster."
        ) from error
