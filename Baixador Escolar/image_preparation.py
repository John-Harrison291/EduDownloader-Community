"""Read-only preparation using the same geometry and renderer as image PDF export."""

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from math import ceil

from PIL import Image
from pdf_tools import _PDF_RESOLUTION_DPI

from pdf_previews import (
    PageRenderer,
    RasterCache,
    checkpoint,
    fingerprint,
    PreviewCancelled,
)
from print_layout import (
    Size,
    image_rotations,
    rotated_image_size,
    image_slots,
    choose_image_page_orientation,
    contain_image,
    validate_conversion_image_dimensions,
    page_dimensions,
    raster_dimensions,
)

MAX_ANALYSIS_IMAGES = 2000
MAX_ESTIMATE_PAGES = 50
PRINT_WARNING_PPI = 150


@dataclass(frozen=True)
class ImageQuality:
    path: object
    dpi: float


@dataclass(frozen=True)
class ImagePreparation:
    qualities: tuple = ()
    estimated_bytes: tuple[int, int] | None = None
    message: str = ""


class ImagePreparationReader:
    def __init__(self):
        self.dimensions = OrderedDict()
        self.renderer = PageRenderer(
            RasterCache(max_bytes=8 * 1024 * 1024, max_items=16)
        )

    def close(self):
        self.dimensions.clear()
        self.renderer.close()

    def size(self, path, stamp):
        if stamp not in self.dimensions:
            with Image.open(path, formats=("JPEG", "PNG")) as source:
                if source.format not in {"JPEG", "PNG"}:
                    raise ValueError("Unsupported image")
                width, height = source.size
                validate_conversion_image_dimensions(width, height)
                if source.getexif().get(274) in (5, 6, 7, 8):
                    width, height = height, width
                self.dimensions[stamp] = Size(width, height)
            while len(self.dimensions) > 2048:
                self.dimensions.popitem(last=False)
        self.dimensions.move_to_end(stamp)
        return self.dimensions[stamp]

    def bundle(self, spec, _index, _bounds, cancel):
        try:
            checkpoint(cancel)
            if not spec.paths or len(spec.paths) > MAX_ANALYSIS_IMAGES:
                return ImagePreparation(
                    message="Avaliação indisponível para esta quantidade de imagens."
                )
            angles = image_rotations(spec.rotations, len(spec.paths))
            sizes = []
            stamps = []
            for path, angle in zip(spec.paths, angles):
                checkpoint(cancel)
                stamp = fingerprint(path)
                stamps.append(stamp)
                sizes.append(rotated_image_size(self.size(path, stamp), angle))
            qualities = []
            n = spec.layout.images_per_page
            for start in range(0, len(sizes), n):
                checkpoint(cancel)
                group = sizes[start : start + n]
                orientation = choose_image_page_orientation(group, spec.layout)
                slots = image_slots(
                    spec.layout.paper, orientation, spec.layout.margin, n
                )
                for offset, (size, slot) in enumerate(zip(group, slots)):
                    placed = contain_image(size, slot)
                    dpi = min(
                        _PDF_RESOLUTION_DPI,
                        size.width * 72 / placed.width,
                        size.height * 72 / placed.height,
                    )
                    qualities.append(ImageQuality(spec.paths[start + offset], dpi))
            pages = ceil(len(sizes) / n)
            estimate = None
            message = ""
            if pages <= MAX_ESTIMATE_PAGES:
                try:
                    estimate = self.estimate(spec, sizes, pages, cancel)
                except PreviewCancelled:
                    raise
                except Exception:
                    message = "Estimativa indisponível para estas imagens."
            else:
                message = "Estimativa indisponível acima de 50 páginas."
            for path, stamp in zip(spec.paths, stamps):
                checkpoint(cancel)
                if fingerprint(path) != stamp:
                    raise ValueError("Source changed")
            return ImagePreparation(tuple(qualities), estimate, message)
        except PreviewCancelled:
            raise
        except Exception:
            return ImagePreparation(
                message="Não foi possível avaliar todas as imagens. Confira os arquivos."
            )

    def estimate(self, spec, sizes, pages, cancel):
        samples = []
        n = spec.layout.images_per_page
        for page in sorted({0, pages // 2, pages - 1}):
            checkpoint(cancel)
            raster = self.renderer.render(spec, page, (800, 800), cancel)
            orientation = choose_image_page_orientation(
                sizes[page * n : (page + 1) * n], spec.layout
            )
            export_pixels = raster_dimensions(
                page_dimensions(spec.layout.paper, orientation), _PDF_RESOLUTION_DPI
            )
            with raster.image() as image, BytesIO() as stream:
                image.save(stream, format="JPEG", quality=75)
                samples.append(
                    len(stream.getbuffer())
                    * export_pixels[0]
                    * export_pixels[1]
                    / (raster.width * raster.height)
                )
        # JPEG scaling is approximate; widen the interval for unsampled pages.
        low, high = (0.35, 2.0) if pages <= 3 else (0.25, 3.0)
        return round(min(samples) * low * pages) + 2048 * pages, round(
            max(samples) * high * pages
        ) + 8192 * pages
