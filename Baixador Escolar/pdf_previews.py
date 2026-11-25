"""Bounded, read-only page rendering. No Tk objects or output files here."""

from collections import OrderedDict
from contextlib import closing
from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path
from threading import Condition, Event, Thread
import warnings

from PIL import Image, ImageOps
import pypdfium2 as pdfium
from pypdf import PdfReader

from local_files import validate_local_regular_file
from pdfium_access import PDFIUM_LOCK
from pdf_tools import _images_as_pdf_page
from poster_tools import _render_poster_page, plan_poster
from print_layout import (
    Size,
    choose_image_page_orientation,
    page_dimensions,
    image_rotations,
    rotated_image_size,
)

MAX_PREVIEW_FILE_BYTES = 128 * 1024 * 1024
MAX_PREVIEW_PAGES = 10_000
MAX_RENDER_DIMENSION = 2048
MAX_CACHE_BYTES = 48 * 1024 * 1024
MAX_CACHE_ITEMS = 96
MAX_DECODE_PIXELS = 16_000_000


class PreviewError(ValueError):
    pass


class PreviewCancelled(Exception):
    pass


def checkpoint(cancel):
    if cancel is not None and cancel.is_set():
        raise PreviewCancelled


@dataclass(frozen=True)
class PreviewSpec:
    kind: str
    paths: tuple[Path, ...]
    layout: object = None
    crop_marks: bool = False
    rotations: tuple[int, ...] = ()


@dataclass(frozen=True)
class Raster:
    width: int
    height: int
    rgb: bytes
    count: int = 1
    caption: str = ""
    error: str = ""
    source_bytes: int = 0

    def image(self):
        return Image.frombytes("RGB", (self.width, self.height), self.rgb)


@dataclass(frozen=True)
class PreviewBundle:
    index: int
    total: int
    main: Raster | None
    thumbs: tuple[tuple[int, Raster], ...] = ()
    error: str = ""


class RasterCache:
    def __init__(self, max_bytes=MAX_CACHE_BYTES, max_items=MAX_CACHE_ITEMS):
        self.max_bytes, self.max_items = max_bytes, max_items
        self.items = OrderedDict()
        self.bytes = 0
        self.hits = 0

    def get(self, key):
        value = self.items.get(key)
        if value is not None:
            self.items.move_to_end(key)
            self.hits += 1
        return value

    def put(self, key, value):
        size = len(value.rgb)
        if size > self.max_bytes:
            return
        previous = self.items.pop(key, None)
        if previous is not None:
            self.bytes -= len(previous.rgb)
        self.items[key] = value
        self.bytes += size
        while self.bytes > self.max_bytes or len(self.items) > self.max_items:
            _, old = self.items.popitem(last=False)
            self.bytes -= len(old.rgb)

    def clear(self):
        self.items.clear()
        self.bytes = 0


def fingerprint(path):
    path = validate_local_regular_file(path)
    info = path.stat()
    if not 0 < info.st_size <= MAX_PREVIEW_FILE_BYTES:
        raise PreviewError(
            "Arquivo vazio ou grande demais para a prévia (limite de 128 MB)."
        )
    return str(path), info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino


def pixel_bounds(bounds):
    return tuple(max(32, min(MAX_RENDER_DIMENSION, int(value))) for value in bounds)


def preview_dpi(size, bounds):
    return max(1, int(min(bounds[0] / size.width, bounds[1] / size.height) * 72))


class PageRenderer:
    """The worker alone owns this cache; all native handles close per render."""

    def __init__(self, cache=None):
        self.cache = cache if cache is not None else RasterCache()
        self.metadata = OrderedDict()
        self.renders = 0

    def close(self):
        self.cache.clear()
        self.metadata.clear()

    def _metadata(self, key, factory):
        if key not in self.metadata:
            self.metadata[key] = factory()
            while len(self.metadata) > 96:
                self.metadata.popitem(last=False)
        self.metadata.move_to_end(key)
        return self.metadata[key]

    def image_thumbnail(self, path, bounds, cancel=None):
        stamp = fingerprint(path)
        key = ("image", stamp, bounds)
        raster = self.cache.get(key)

        def dimensions():
            with Image.open(path, formats=("JPEG", "PNG")) as source:
                if source.format not in {"PNG", "JPEG"}:
                    raise PreviewError("A prévia aceita imagens PNG e JPEG.")
                width, height = source.size
                if source.getexif().get(274) in {5, 6, 7, 8}:
                    width, height = height, width
                return Size(width, height)

        size = self._metadata(("dimensions", stamp), dimensions)
        if raster is None:
            checkpoint(cancel)
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path, formats=("JPEG", "PNG")) as source:
                    # JPEG decoder reduction happens before decoding the bitmap.
                    reduction = 1
                    while (
                        source.width * source.height / (reduction * reduction)
                        > MAX_DECODE_PIXELS
                        and reduction < 8
                    ):
                        reduction *= 2
                    source.draft(
                        "RGB",
                        (
                            min(bounds[0], max(1, source.width // reduction)),
                            min(bounds[1], max(1, source.height // reduction)),
                        ),
                    )
                    if source.width * source.height > MAX_DECODE_PIXELS:
                        raise PreviewError(
                            "Imagem grande demais para a prévia. Use uma cópia menor."
                        )
                    source.thumbnail(bounds, Image.Resampling.LANCZOS)
                    oriented = ImageOps.exif_transpose(source)
                    try:
                        oriented.thumbnail(bounds, Image.Resampling.LANCZOS)
                        rgba = oriented.convert("RGBA")
                        image = Image.new("RGB", rgba.size, "white")
                        try:
                            image.paste(rgba, mask=rgba.getchannel("A"))
                            raster = Raster(*image.size, image.tobytes())
                        finally:
                            image.close()
                            rgba.close()
                    finally:
                        if oriented is not source:
                            oriented.close()
            checkpoint(cancel)
            if fingerprint(path) != stamp:
                raise PreviewError(
                    "O arquivo mudou durante a leitura. Atualize a prévia."
                )
            self.cache.put(key, raster)
        return raster, size

    def _pdf(self, path, page, bounds, cancel):
        stamp = fingerprint(path)

        def inspect():
            with Path(path).open("rb") as stream:
                reader = PdfReader(stream, strict=False)
                if reader.is_encrypted:
                    raise PreviewError("PDF protegido por senha: prévia indisponível.")
                count = len(reader.pages)
            if not 0 < count <= MAX_PREVIEW_PAGES:
                raise PreviewError(
                    "O PDF não tem páginas ou excede o limite de 10.000 páginas da prévia."
                )
            return count

        count = self._metadata(("pdf", stamp), inspect)
        if not 0 <= page < count:
            raise PreviewError("Página indisponível.")
        key = ("pdf", stamp, page, bounds)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        # Waiting for another PDF tool never prevents changing selection/closing.
        while not PDFIUM_LOCK.acquire(timeout=0.05):
            checkpoint(cancel)
        try:
            checkpoint(cancel)
            with pdfium.PdfDocument(str(path)) as document:
                with closing(document[page]) as native_page:
                    width, height = native_page.get_size()
                    if not all(0 < value <= 14_400 for value in (width, height)):
                        raise PreviewError(
                            "Dimensões de página não suportadas pela prévia."
                        )
                    scale = min(bounds[0] / width, bounds[1] / height)
                    bitmap = native_page.render(
                        scale=scale, fill_color=(255, 255, 255, 255)
                    )
                    try:
                        image = bitmap.to_pil().convert("RGB")
                        try:
                            raster = Raster(
                                *image.size,
                                image.tobytes(),
                                count,
                                f"{Path(path).name} · {count} página(s)",
                                source_bytes=stamp[1],
                            )
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
        finally:
            PDFIUM_LOCK.release()
        checkpoint(cancel)
        if fingerprint(path) != stamp:
            raise PreviewError("O PDF mudou durante a leitura. Atualize a prévia.")
        self.renders += 1
        self.cache.put(key, raster)
        return raster

    def render(self, spec, index, bounds, cancel=None):
        checkpoint(cancel)
        bounds = pixel_bounds(bounds)
        if spec.kind in {"pdf", "merge"}:
            path = spec.paths[index] if spec.kind == "merge" else spec.paths[0]
            return self._pdf(path, 0 if spec.kind == "merge" else index, bounds, cancel)
        if spec.kind == "images":
            n = spec.layout.images_per_page
            total = ceil(len(spec.paths) / n)
            group = spec.paths[index * n : (index + 1) * n]
            angles = image_rotations(spec.rotations, len(spec.paths))[
                index * n : (index + 1) * n
            ]
            if not group:
                raise PreviewError("Página sem imagens.")
            stamps = tuple(fingerprint(path) for path in group)
            key = ("images", stamps, angles, spec.layout, bounds)
            cached = self.cache.get(key)
            if cached is not None:
                return replace(cached, count=total) if cached.count != total else cached
            sizes = tuple(
                self.image_thumbnail(path, (1024, 1024), cancel)[1] for path in group
            )
            orientation = choose_image_page_orientation(
                tuple(
                    rotated_image_size(size, angle)
                    for size, angle in zip(sizes, angles)
                ),
                spec.layout,
            )
            size = page_dimensions(spec.layout.paper, orientation)

            def load(path):
                checkpoint(cancel)
                return self.image_thumbnail(path, (1024, 1024), cancel)[0].image()

            image = _images_as_pdf_page(
                group,
                spec.layout,
                resolution_dpi=preview_dpi(size, bounds),
                image_loader=load,
                source_sizes=sizes,
                rotations=angles,
            )
        elif spec.kind == "poster":
            stamp = fingerprint(spec.paths[0])
            key = ("poster", stamp, spec.layout, spec.crop_marks, index, bounds)
            cached = self.cache.get(key)
            if cached is not None:
                return cached
            thumb, size = self.image_thumbnail(spec.paths[0], (1536, 1536), cancel)
            plan = plan_poster(size, spec.layout)
            source = thumb.image()
            try:
                image = _render_poster_page(
                    source,
                    plan,
                    plan.tiles[index],
                    show_crop_marks=spec.crop_marks,
                    render_dpi=preview_dpi(plan.page_size, bounds),
                )
            finally:
                source.close()
            total = plan.page_count
        else:
            raise PreviewError("Tipo de prévia inválido.")
        try:
            checkpoint(cancel)
            raster = Raster(*image.size, image.tobytes(), total)
        finally:
            image.close()
        self.renders += 1
        self.cache.put(key, raster)
        return raster

    def bundle(self, spec, index, bounds, cancel=None):
        main = None
        error_message = ""
        try:
            main = self.render(spec, index, bounds, cancel)
            total = len(spec.paths) if spec.kind == "merge" else main.count
        except PreviewCancelled:
            raise
        except Exception as error:
            total = len(spec.paths) if spec.kind == "merge" else 0
            error_message = public_preview_error(error)
        try:
            start = max(0, min(index - 1, total - 4))
            thumbs = []
            for number in range(start, min(total, start + 4)):
                checkpoint(cancel)
                try:
                    thumb = self.render(spec, number, (128, 100), cancel)
                except PreviewCancelled:
                    raise
                except Exception as error:
                    thumb = Raster(0, 0, b"", error=public_preview_error(error))
                thumbs.append((number, thumb))
            return PreviewBundle(index, total, main, tuple(thumbs), error_message)
        except PreviewCancelled:
            raise
        except Exception as error:
            # Merge still allows moving to the next valid document.
            total = len(spec.paths) if spec.kind == "merge" else 0
            return PreviewBundle(index, total, None, error=public_preview_error(error))


def public_preview_error(error):
    if isinstance(error, PreviewError):
        return str(error)
    return "Não foi possível visualizar o arquivo. Ele pode estar inválido, protegido ou inacessível."


class PreviewWorker:
    """One worker for every PDF view, one latest pending/result slot per owner."""

    def __init__(self, renderer=None):
        self.renderer = renderer or PageRenderer()
        self.condition = Condition()
        self.pending = OrderedDict()
        self.results = {}
        self.tokens = {}
        self.closed = False
        self.thread = None

    def submit(self, owner, generation, spec, index, bounds):
        with self.condition:
            if self.closed:
                return
            self._invalidate(owner)
            if owner not in self.tokens and len(self.tokens) >= 8:
                self._invalidate(next(iter(self.tokens)))
            token = Event()
            self.tokens[owner] = token
            self.pending[owner] = (generation, spec, index, bounds, token)
            self.pending.move_to_end(owner)
            if self.thread is None:
                self.thread = Thread(
                    target=self._run, name="edudownloader-pdf-preview", daemon=True
                )
                try:
                    self.thread.start()
                except (OSError, RuntimeError):
                    self.thread = None
                    self._invalidate(owner)
                    raise
            self.condition.notify()

    def _invalidate(self, owner):
        previous = self.tokens.pop(owner, None)
        if previous is not None:
            previous.set()
        self.pending.pop(owner, None)
        self.results.pop(owner, None)

    def invalidate(self, owner):
        with self.condition:
            self._invalidate(owner)

    def take(self, owner):
        with self.condition:
            return self.results.pop(owner, None)

    def _run(self):
        try:
            while True:
                with self.condition:
                    while not self.pending and not self.closed:
                        self.condition.wait()
                    if self.closed:
                        return
                    owner, (generation, spec, index, bounds, token) = (
                        self.pending.popitem(last=False)
                    )
                try:
                    result = self.renderer.bundle(spec, index, bounds, token)
                except PreviewCancelled:
                    continue
                except Exception:
                    result = PreviewBundle(
                        index, 0, None, error="Não foi possível renderizar a prévia."
                    )
                with self.condition:
                    if not self.closed and not token.is_set():
                        self.results[owner] = (generation, result)
        finally:
            self.renderer.close()

    def close(self):
        with self.condition:
            self.closed = True
            for owner in tuple(self.tokens):
                self._invalidate(owner)
            self.condition.notify_all()
        if self.thread is None:
            self.renderer.close()
