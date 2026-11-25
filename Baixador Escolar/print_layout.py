"""Contratos puros de impressão e layout para as ferramentas locais."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, TypeVar


POINTS_PER_INCH: Final = 72.0
MILLIMETRES_PER_INCH: Final = 25.4

SUPPORTED_IMAGES_PER_PAGE: Final = frozenset({1, 2, 4})
MAX_CONVERSION_IMAGE_PIXELS: Final = 80_000_000
PDF_EXPORT_PAGE_WARNING_THRESHOLD: Final = 100
MAX_PDF_EXPORT_PAGES: Final = 500
MAX_POSTER_GRID_DIMENSION: Final = 4
MAX_POSTER_PAGES: Final = 16
MAX_PDF_PAGE_POINTS: Final = 14_400.0
PPI_LOW_THRESHOLD: Final = 100.0
PPI_VERY_LOW_THRESHOLD: Final = 72.0

_CELL_SPACING_MILLIMETRES: Final = {
    "none": 3.0,
    "small": 4.0,
    "normal": 5.0,
}

_Item = TypeVar("_Item")


class PrintLayoutError(ValueError):
    """Indica uma configuração física ou geométrica inválida."""


def millimetres_to_points(value: float) -> float:
    """Converte milímetros para PDF points."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PrintLayoutError("A medida física deve ser numérica.")
    if not math.isfinite(value) or value < 0:
        raise PrintLayoutError("A medida física deve ser finita e não negativa.")
    return value * POINTS_PER_INCH / MILLIMETRES_PER_INCH


@dataclass(frozen=True, slots=True)
class Size:
    """Dimensão positiva em uma unidade comum."""

    width: float
    height: float

    def __post_init__(self) -> None:
        _require_positive_finite(self.width, "largura")
        _require_positive_finite(self.height, "altura")

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class Rect:
    """Retângulo positivo em coordenadas físicas da página."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for value, label in ((self.x, "x"), (self.y, "y")):
            if not math.isfinite(value) or value < 0:
                raise PrintLayoutError(f"A coordenada {label} deve ser válida.")
        _require_positive_finite(self.width, "largura")
        _require_positive_finite(self.height, "altura")

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class ContainPlacement:
    """Posição e escala de uma imagem integralmente contida em uma célula."""

    x: float
    y: float
    width: float
    height: float
    scale: float


@dataclass(frozen=True, slots=True)
class EffectivePpi:
    """Resolução física aproximada da imagem já ajustada ao painel."""

    horizontal: float
    vertical: float
    conservative: float
    quality: PpiQuality


class PaperSize(Enum):
    """Papéis suportados pelo contrato físico inicial."""

    A4 = (millimetres_to_points(210.0), millimetres_to_points(297.0))
    LETTER = (8.5 * POINTS_PER_INCH, 11.0 * POINTS_PER_INCH)

    @property
    def portrait_size(self) -> Size:
        return Size(*self.value)


class Orientation(str, Enum):
    """Orientação solicitada ou resolvida de uma página."""

    AUTO = "auto"
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class MarginPreset(Enum):
    """Margens simples; NONE não promete impressão física sem bordas."""

    NONE = 0.0
    SMALL = millimetres_to_points(7.5)
    NORMAL = millimetres_to_points(15.0)

    @property
    def points(self) -> float:
        return float(self.value)


class PdfImageQuality(Enum):
    """Presets deliberadamente pequenos de rasterização PDF."""

    STANDARD = 150
    HIGH = 300

    @property
    def dpi(self) -> int:
        return int(self.value)


class PosterGrid(Enum):
    """Grades de pôster aceitas, sem dimensões arbitrárias."""

    TWO_BY_TWO = (2, 2)
    THREE_BY_THREE = (3, 3)
    FOUR_BY_FOUR = (4, 4)

    @property
    def rows(self) -> int:
        return self.value[0]

    @property
    def columns(self) -> int:
        return self.value[1]

    @property
    def page_count(self) -> int:
        return self.rows * self.columns


class OverlapPreset(Enum):
    """Sobreposição física a aplicar somente nas bordas internas do grid."""

    NONE = 0.0
    SMALL = millimetres_to_points(5.0)

    @property
    def points(self) -> float:
        return float(self.value)


class PpiQuality(str, Enum):
    """Classificação conservadora para o aviso futuro de qualidade."""

    OK = "ok"
    LOW = "low"
    VERY_LOW = "very_low"


@dataclass(frozen=True, slots=True)
class ImagePageLayout:
    """Pedido imutável para uma página de imagens."""

    paper: PaperSize = PaperSize.A4
    orientation: Orientation = Orientation.AUTO
    margin: MarginPreset = MarginPreset.NORMAL
    images_per_page: int = 1

    def __post_init__(self) -> None:
        _require_enum(self.paper, PaperSize, "papel")
        _require_enum(self.orientation, Orientation, "orientação")
        _require_enum(self.margin, MarginPreset, "margem")
        _validate_images_per_page(self.images_per_page)


@dataclass(frozen=True, slots=True)
class PosterLayout:
    """Configuração imutável para o futuro motor de pôster."""

    paper: PaperSize = PaperSize.A4
    orientation: Orientation = Orientation.AUTO
    margin: MarginPreset = MarginPreset.NORMAL
    grid: PosterGrid = PosterGrid.TWO_BY_TWO
    overlap: OverlapPreset = OverlapPreset.SMALL
    show_crop_marks: bool = False

    def __post_init__(self) -> None:
        _require_enum(self.paper, PaperSize, "papel")
        _require_enum(self.orientation, Orientation, "orientação")
        _require_enum(self.margin, MarginPreset, "margem")
        _require_enum(self.grid, PosterGrid, "grid")
        _require_enum(self.overlap, OverlapPreset, "sobreposição")
        if not isinstance(self.show_crop_marks, bool):
            raise PrintLayoutError("A configuração de marcas de corte é inválida.")


def page_dimensions(paper: PaperSize, orientation: Orientation) -> Size:
    """Retorna dimensões físicas de uma orientação já resolvida."""

    _require_enum(paper, PaperSize, "papel")
    _require_resolved_orientation(orientation)
    portrait = paper.portrait_size
    if orientation is Orientation.PORTRAIT:
        return Size(
            min(portrait.width, portrait.height), max(portrait.width, portrait.height)
        )
    return Size(
        max(portrait.width, portrait.height), min(portrait.width, portrait.height)
    )


def page_content_rect(
    paper: PaperSize,
    orientation: Orientation,
    margin: MarginPreset,
) -> Rect:
    """Calcula a área útil simétrica de uma página em PDF points."""

    _require_enum(margin, MarginPreset, "margem")
    page = page_dimensions(paper, orientation)
    width = page.width - 2 * margin.points
    height = page.height - 2 * margin.points
    if width <= 0 or height <= 0:
        raise PrintLayoutError("A margem não deixa área útil positiva na página.")
    return Rect(margin.points, margin.points, width, height)


def image_slots(
    paper: PaperSize,
    orientation: Orientation,
    margin: MarginPreset,
    images_per_page: int,
) -> tuple[Rect, ...]:
    """Distribui 1, 2 ou 4 células em ordem de leitura."""

    _validate_images_per_page(images_per_page)
    _require_resolved_orientation(orientation)
    content = page_content_rect(paper, orientation, margin)
    rows, columns = _image_grid_shape(images_per_page, orientation)
    spacing = cell_spacing(margin)
    cell_width = (content.width - spacing * (columns - 1)) / columns
    cell_height = (content.height - spacing * (rows - 1)) / rows
    if cell_width <= 0 or cell_height <= 0:
        raise PrintLayoutError("O espaçamento não deixa células positivas na página.")
    return tuple(
        Rect(
            content.x + column * (cell_width + spacing),
            content.y + row * (cell_height + spacing),
            cell_width,
            cell_height,
        )
        for row in range(rows)
        for column in range(columns)
    )


def cell_spacing(margin: MarginPreset) -> float:
    """Retorna espaçamento interno fixo e pequeno para cada preset."""

    _require_enum(margin, MarginPreset, "margem")
    return millimetres_to_points(_CELL_SPACING_MILLIMETRES[margin.name.casefold()])


def contain_image(
    image_size: Size | tuple[float, float],
    cell: Rect,
    *,
    allow_upscale: bool = True,
) -> ContainPlacement:
    """Centraliza a imagem sem corte, deformação ou extrapolação da célula."""

    image = _coerce_size(image_size)
    if not isinstance(cell, Rect):
        raise PrintLayoutError("A célula de destino é inválida.")
    if not isinstance(allow_upscale, bool):
        raise PrintLayoutError("A política de ampliação é inválida.")
    scale = min(cell.width / image.width, cell.height / image.height)
    if not allow_upscale:
        scale = min(1.0, scale)
    width = min(cell.width, image.width * scale)
    height = min(cell.height, image.height * scale)
    return ContainPlacement(
        x=cell.x + (cell.width - width) / 2,
        y=cell.y + (cell.height - height) / 2,
        width=width,
        height=height,
        scale=scale,
    )


def choose_image_page_orientation(
    image_sizes: Sequence[Size | tuple[float, float]],
    layout: ImagePageLayout,
) -> Orientation:
    """Resolve AUTO pelo maior aproveitamento de área; empate favorece portrait."""

    if not isinstance(layout, ImagePageLayout):
        raise PrintLayoutError("A configuração da página é inválida.")
    if layout.orientation is not Orientation.AUTO:
        return layout.orientation
    images = tuple(_coerce_size(size) for size in image_sizes)
    if not images or len(images) > layout.images_per_page:
        raise PrintLayoutError(
            "O grupo de imagens não corresponde ao layout da página."
        )
    portrait_score = _image_page_score(images, layout, Orientation.PORTRAIT)
    landscape_score = _image_page_score(images, layout, Orientation.LANDSCAPE)
    if landscape_score > portrait_score + 1e-12:
        return Orientation.LANDSCAPE
    return Orientation.PORTRAIT


def paginate_images(
    items: Sequence[_Item], images_per_page: int
) -> tuple[tuple[_Item, ...], ...]:
    """Agrupa itens sem alterar sua ordem, duplicar ou descartar entradas."""

    _validate_images_per_page(images_per_page)
    return tuple(
        tuple(items[start : start + images_per_page])
        for start in range(0, len(items), images_per_page)
    )


def image_rotations(values, count: int) -> tuple[int, ...]:
    """Clockwise composition angles, applied after EXIF normalization."""
    if values is None or values == ():
        return (0,) * count
    try:
        result = tuple(values)
    except TypeError as error:
        raise PrintLayoutError("A rotação das imagens é inválida.") from error
    if len(result) != count or any(
        type(value) is not int or value not in (0, 90, 180, 270) for value in result
    ):
        raise PrintLayoutError(
            "Informe uma rotação de 0°, 90°, 180° ou 270° para cada imagem."
        )
    return result


def rotated_image_size(size: Size, angle: int) -> Size:
    image_rotations((angle,), 1)
    return Size(size.height, size.width) if angle in (90, 270) else size


def pdfium_scale(quality: PdfImageQuality) -> float:
    """Converte o preset de qualidade na escala física usada pelo PDFium."""

    _require_enum(quality, PdfImageQuality, "qualidade")
    return quality.dpi / POINTS_PER_INCH


def raster_dimensions(size_points: Size, dpi: int) -> tuple[int, int]:
    """Estima dimensões inteiras de um raster para uma página física."""

    if not isinstance(size_points, Size):
        raise PrintLayoutError("A dimensão física é inválida.")
    _require_positive_integer(dpi, "DPI")
    return (
        max(1, round(size_points.width * dpi / POINTS_PER_INCH)),
        max(1, round(size_points.height * dpi / POINTS_PER_INCH)),
    )


def estimate_raster_bytes(width: int, height: int, channels: int = 4) -> int:
    """Estima bytes de pixels crus, sem prometer equivalência ao RSS real."""

    _require_positive_integer(width, "largura")
    _require_positive_integer(height, "altura")
    _require_positive_integer(channels, "canais")
    return width * height * channels


def validate_conversion_image_dimensions(width: int, height: int) -> int:
    """Valida o limite inicial de pixels de uma imagem de conversão."""

    _require_positive_integer(width, "largura")
    _require_positive_integer(height, "altura")
    pixels = width * height
    if pixels > MAX_CONVERSION_IMAGE_PIXELS:
        raise PrintLayoutError("A imagem excede o limite seguro de conversão.")
    return pixels


def pdf_export_requires_warning(page_count: int) -> bool:
    """Valida a exportação e indica quando a quantidade merece aviso."""

    _require_positive_integer(page_count, "quantidade de páginas")
    if page_count > MAX_PDF_EXPORT_PAGES:
        raise PrintLayoutError("A seleção excede o limite seguro de páginas.")
    return page_count > PDF_EXPORT_PAGE_WARNING_THRESHOLD


def validate_pdf_page_dimensions(width: float, height: float) -> Size:
    """Rejeita dimensões PDF não finitas, vazias ou absurdas."""

    size = Size(width, height)
    if size.width > MAX_PDF_PAGE_POINTS or size.height > MAX_PDF_PAGE_POINTS:
        raise PrintLayoutError("A página PDF excede o limite físico seguro.")
    return size


def poster_panel_size(
    paper: PaperSize,
    orientation: Orientation,
    margin: MarginPreset,
    grid: PosterGrid,
    overlap: OverlapPreset,
) -> Size:
    """Calcula o painel físico descontando overlap somente entre folhas."""

    _require_enum(grid, PosterGrid, "grid")
    _require_enum(overlap, OverlapPreset, "sobreposição")
    content = page_content_rect(paper, orientation, margin)
    width = content.width * grid.columns - overlap.points * (grid.columns - 1)
    height = content.height * grid.rows - overlap.points * (grid.rows - 1)
    if width <= 0 or height <= 0:
        raise PrintLayoutError("A sobreposição não deixa um painel positivo.")
    return Size(width, height)


def choose_poster_orientation(
    image_size: Size | tuple[float, float], layout: PosterLayout
) -> Orientation:
    """Resolve AUTO comparando o aproveitamento físico do painel completo."""

    if not isinstance(layout, PosterLayout):
        raise PrintLayoutError("A configuração do pôster é inválida.")
    if layout.orientation is not Orientation.AUTO:
        return layout.orientation
    image = _coerce_size(image_size)
    portrait_score = _poster_score(image, layout, Orientation.PORTRAIT)
    landscape_score = _poster_score(image, layout, Orientation.LANDSCAPE)
    if landscape_score > portrait_score + 1e-12:
        return Orientation.LANDSCAPE
    return Orientation.PORTRAIT


def effective_poster_ppi(
    image_size: Size | tuple[float, float], panel_size_points: Size
) -> EffectivePpi:
    """Calcula PPI conservador após contain da imagem no painel físico."""

    image = _coerce_size(image_size)
    if not isinstance(panel_size_points, Size):
        raise PrintLayoutError("A dimensão física do painel é inválida.")
    placed = contain_image(
        image,
        Rect(0.0, 0.0, panel_size_points.width, panel_size_points.height),
    )
    horizontal = image.width / (placed.width / POINTS_PER_INCH)
    vertical = image.height / (placed.height / POINTS_PER_INCH)
    conservative = min(horizontal, vertical)
    return EffectivePpi(
        horizontal=horizontal,
        vertical=vertical,
        conservative=conservative,
        quality=classify_ppi(conservative),
    )


def classify_ppi(value: float) -> PpiQuality:
    """Classifica a resolução efetiva nos dois níveis de aviso aprovados."""

    _require_positive_finite(value, "PPI")
    if value < PPI_VERY_LOW_THRESHOLD:
        return PpiQuality.VERY_LOW
    if value < PPI_LOW_THRESHOLD:
        return PpiQuality.LOW
    return PpiQuality.OK


def poster_page_position(grid: PosterGrid, page_index: int) -> tuple[int, int]:
    """Converte índice zero-based em linha/coluna, em ordem de leitura."""

    _require_enum(grid, PosterGrid, "grid")
    _require_non_negative_integer(page_index, "índice da página")
    if page_index >= grid.page_count:
        raise PrintLayoutError("O índice da página está fora do grid.")
    return divmod(page_index, grid.columns)


def poster_page_index(grid: PosterGrid, row: int, column: int) -> int:
    """Converte linha/coluna zero-based no índice em ordem de leitura."""

    _require_enum(grid, PosterGrid, "grid")
    _require_non_negative_integer(row, "linha")
    _require_non_negative_integer(column, "coluna")
    if row >= grid.rows or column >= grid.columns:
        raise PrintLayoutError("A posição está fora do grid.")
    return row * grid.columns + column


def _image_grid_shape(
    images_per_page: int, orientation: Orientation
) -> tuple[int, int]:
    if images_per_page == 1:
        return (1, 1)
    if images_per_page == 2:
        return (2, 1) if orientation is Orientation.PORTRAIT else (1, 2)
    return (2, 2)


def _image_page_score(
    images: Sequence[Size], layout: ImagePageLayout, orientation: Orientation
) -> float:
    slots = image_slots(
        layout.paper,
        orientation,
        layout.margin,
        layout.images_per_page,
    )
    rendered_area = 0.0
    for image, slot in zip(images, slots, strict=False):
        placed = contain_image(image, slot)
        rendered_area += placed.width * placed.height
    return (
        rendered_area / page_content_rect(layout.paper, orientation, layout.margin).area
    )


def _poster_score(image: Size, layout: PosterLayout, orientation: Orientation) -> float:
    panel = poster_panel_size(
        layout.paper,
        orientation,
        layout.margin,
        layout.grid,
        layout.overlap,
    )
    placed = contain_image(image, Rect(0.0, 0.0, panel.width, panel.height))
    return placed.width * placed.height / panel.area


def _coerce_size(value: Size | tuple[float, float]) -> Size:
    if isinstance(value, Size):
        return value
    try:
        width, height = value
    except (TypeError, ValueError) as error:
        raise PrintLayoutError("A dimensão informada é inválida.") from error
    return Size(width, height)


def _validate_images_per_page(value: int) -> None:
    if isinstance(value, bool) or value not in SUPPORTED_IMAGES_PER_PAGE:
        raise PrintLayoutError("Use exatamente 1, 2 ou 4 imagens por página.")


def _require_resolved_orientation(value: Orientation) -> None:
    _require_enum(value, Orientation, "orientação")
    if value is Orientation.AUTO:
        raise PrintLayoutError(
            "A orientação automática precisa ser resolvida primeiro."
        )


def _require_enum(value: object, expected: type[Enum], label: str) -> None:
    if not isinstance(value, expected):
        raise PrintLayoutError(f"A configuração de {label} é inválida.")


def _require_positive_finite(value: float, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PrintLayoutError(f"A {label} deve ser numérica.")
    if not math.isfinite(value) or value <= 0:
        raise PrintLayoutError(f"A {label} deve ser finita e positiva.")


def _require_positive_integer(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PrintLayoutError(f"A {label} deve ser um inteiro positivo.")


def _require_non_negative_integer(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PrintLayoutError(f"O valor de {label} deve ser um inteiro não negativo.")
