"""Real pixels, bounded scheduling and printing parity for Goal 2 previews."""

from contextlib import closing
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch
import hashlib
import tempfile
import time
import unittest

from PIL import Image, ImageChops, ImageStat
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
import pypdfium2 as pdfium

from pdf_previews import (
    MAX_CACHE_BYTES,
    PageRenderer,
    PreviewSpec,
    Raster,
    RasterCache,
    PreviewWorker,
    PreviewBundle,
    PreviewCancelled,
)
from pdfium_access import PDFIUM_LOCK
from pdf_tools import PdfToolsService
from poster_tools import PosterService, PosterRequest
from print_layout import (
    ImagePageLayout,
    PaperSize,
    Orientation,
    MarginPreset,
    PosterLayout,
    PosterGrid,
    OverlapPreset,
)


def make_pdf(path, pages=((240, 360, (1, 0, 0)),), *, password=None):
    writer = PdfWriter()
    for width, height, color in pages:
        page = writer.add_blank_page(width, height)
        stream = DecodedStreamObject()
        r, g, b = color
        stream.set_data(
            f"{r} {g} {b} rg 0 0 {width} {height} re f 0 0 0 rg 12 18 20 16 re f".encode()
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    writer.write(path)
    writer.close()


def native_image(path, index, bounds):
    with (
        PDFIUM_LOCK,
        pdfium.PdfDocument(str(path)) as document,
        closing(document[index]) as page,
    ):
        scale = min(bounds[0] / page.get_width(), bounds[1] / page.get_height())
        bitmap = page.render(scale=scale, fill_color=(255, 255, 255, 255))
        try:
            return bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()


class PreviewPixelsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="goal2-pixels-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.renderer = PageRenderer()
        self.addCleanup(self.renderer.close)
        self.pdf = self.root / "mixed.pdf"
        make_pdf(
            self.pdf,
            ((240, 360, (1, 0, 0)), (420, 180, (0, 1, 0)), (200, 280, (0, 0, 1))),
        )
        self.images = []
        for i, (size, color) in enumerate(
            [
                ((480, 160), "red"),
                ((120, 360), "green"),
                ((260, 260), "blue"),
                ((280, 120), "yellow"),
                ((100, 220), "purple"),
            ]
        ):
            p = self.root / f"photo-{i}.png"
            with Image.new("RGB", size, color) as im:
                im.save(p)
            self.images.append(p)

    def assert_pixels_close(self, raster, path, page):
        with (
            closing(raster.image()) as preview,
            closing(native_image(path, page, preview.size)) as exported,
        ):
            exported = exported.resize(preview.size, Image.Resampling.LANCZOS)
            try:
                with closing(ImageChops.difference(preview, exported)) as difference:
                    self.assertLess(max(ImageStat.Stat(difference).mean), 8.0)
            finally:
                exported.close()

    def test_pdf_real_pages_orientation_count_and_cache(self):
        original = self.pdf.read_bytes()
        files = set(self.root.iterdir())
        spec = PreviewSpec("pdf", (self.pdf,))
        for index, channel in enumerate((0, 1, 2)):
            raster = self.renderer.render(spec, index, (500, 500))
            self.assertEqual(raster.count, 3)
            with closing(raster.image()) as image:
                pixel = image.getpixel((image.width // 2, image.height // 2))
            self.assertGreater(pixel[channel], 245)
            self.assert_pixels_close(raster, self.pdf, index)
        self.assertGreater(
            self.renderer.render(spec, 1, (500, 500)).width,
            self.renderer.render(spec, 1, (500, 500)).height,
        )
        before = self.renderer.renders
        self.renderer.render(spec, 1, (500, 500))
        self.assertEqual(self.renderer.renders, before)
        self.assertGreater(self.renderer.cache.hits, 0)
        self.assertEqual(self.pdf.read_bytes(), original)
        self.assertEqual(set(self.root.iterdir()), files)

    def test_merge_thumbnails_follow_order_and_skip_bad_document(self):
        bad = self.root / "broken.pdf"
        bad.write_bytes(b"broken")
        second = self.root / "second.pdf"
        make_pdf(second, ((300, 200, (0, 0, 1)),))
        bundle = self.renderer.bundle(
            PreviewSpec("merge", (bad, second, self.pdf)), 0, (500, 500)
        )
        self.assertIsNone(bundle.main)
        self.assertEqual(bundle.total, 3)
        self.assertTrue(bundle.thumbs[0][1].error)
        self.assertTrue(bundle.thumbs[1][1].rgb)
        self.assertIn("1 página", bundle.thumbs[1][1].caption)
        reordered = self.renderer.bundle(
            PreviewSpec("merge", (self.pdf, second)), 0, (500, 500)
        )
        self.assertIn("mixed.pdf", reordered.main.caption)
        self.assertEqual(reordered.main.count, 3)

    def test_images_real_photographs_all_layouts_match_generated_pdf(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.images}
        for n, paper, margin, orientation in (
            (1, PaperSize.A4, MarginPreset.NORMAL, Orientation.AUTO),
            (2, PaperSize.LETTER, MarginPreset.SMALL, Orientation.LANDSCAPE),
            (4, PaperSize.A4, MarginPreset.NONE, Orientation.PORTRAIT),
        ):
            with self.subTest(n=n):
                layout = ImagePageLayout(
                    paper=paper,
                    orientation=orientation,
                    margin=margin,
                    images_per_page=n,
                )
                output = self.root / f"photos-{n}.pdf"
                result = PdfToolsService().images_to_pdf(
                    self.images, output, layout=layout
                )
                spec = PreviewSpec("images", tuple(self.images), layout)
                for page in range(result.page_count):
                    raster = self.renderer.render(spec, page, (450, 480))
                    self.assertEqual(raster.count, result.page_count)
                    self.assert_pixels_close(raster, output, page)
        self.assertEqual(
            before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.images}
        )

    def test_add_remove_and_reorder_images_updates_pixels_and_page_count(self):
        layout = ImagePageLayout()
        first = self.renderer.render(
            PreviewSpec("images", tuple(self.images[:2]), layout), 0, (300, 400)
        )
        changed = self.renderer.render(
            PreviewSpec("images", (self.images[2],), layout), 0, (300, 400)
        )
        self.assertEqual((first.count, changed.count), (2, 1))
        self.assertNotEqual(first.rgb, changed.rgb)
        with closing(changed.image()) as im:
            r, g, b = im.getpixel((im.width // 2, im.height // 2))
            self.assertGreater(b, 245)
            self.assertLess(r, 10)

    def test_cached_first_page_updates_count_when_later_images_are_added_or_removed(
        self,
    ):
        layout = ImagePageLayout(images_per_page=2)
        first = self.renderer.render(
            PreviewSpec("images", tuple(self.images[:2]), layout), 0, (300, 400)
        )
        rendered = self.renderer.renders
        added = self.renderer.render(
            PreviewSpec("images", tuple(self.images[:3]), layout), 0, (300, 400)
        )
        removed = self.renderer.render(
            PreviewSpec("images", tuple(self.images[:2]), layout), 0, (300, 400)
        )
        self.assertEqual((first.count, added.count, removed.count), (1, 2, 1))
        self.assertIs(first.rgb, added.rgb)
        self.assertEqual(self.renderer.renders, rendered)

    def test_exif_orientation_and_transparency_match_final_pdf(self):
        jpeg = self.root / "rotated.jpg"
        exif = Image.Exif()
        exif[274] = 6
        with Image.new("RGB", (180, 80), "red") as im:
            im.save(jpeg, exif=exif)
        png = self.root / "alpha.png"
        with Image.new("RGBA", (120, 240), (0, 0, 255, 120)) as im:
            im.save(png)
        paths = (jpeg, png)
        layout = ImagePageLayout(images_per_page=2)
        output = self.root / "orientation.pdf"
        PdfToolsService().images_to_pdf(paths, output, layout=layout)
        raster = self.renderer.render(
            PreviewSpec("images", paths, layout), 0, (500, 500)
        )
        self.assert_pixels_close(raster, output, 0)

    def test_poster_real_pages_keep_margins_overlap_crop_and_number_order(self):
        image = self.images[0]
        before = image.read_bytes()
        layout = PosterLayout(grid=PosterGrid.TWO_BY_TWO, overlap=OverlapPreset.SMALL)
        output = self.root / "poster.pdf"
        PosterService().create(
            PosterRequest(
                image,
                output,
                grid=layout.grid,
                overlap=layout.overlap,
                show_crop_marks=True,
            )
        )
        spec = PreviewSpec("poster", (image,), layout, True)
        for index in range(4):
            raster = self.renderer.render(spec, index, (420, 480))
            self.assertEqual(raster.count, 4)
            self.assert_pixels_close(raster, output, index)
        self.assertEqual(image.read_bytes(), before)

    def test_large_poster_last_page_and_layout_changes(self):
        for grid in PosterGrid:
            spec = PreviewSpec(
                "poster", (self.images[2],), PosterLayout(grid=grid), True
            )
            raster = self.renderer.render(spec, grid.page_count - 1, (300, 400))
            self.assertEqual(raster.count, grid.page_count)

    def test_invalid_protected_missing_and_large_inputs_return_useful_errors(self):
        encrypted = self.root / "protected.pdf"
        make_pdf(encrypted, password="test-only")
        corrupt = self.root / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-1.7\ninvalid")
        for path in (encrypted, corrupt, self.root / "missing.pdf"):
            bundle = self.renderer.bundle(PreviewSpec("pdf", (path,)), 0, (300, 400))
            self.assertIsNone(bundle.main)
            self.assertTrue(bundle.error)
        self.assertIn(
            "protegido",
            self.renderer.bundle(PreviewSpec("pdf", (encrypted,)), 0, (300, 400)).error,
        )
        with patch("pdf_previews.MAX_PREVIEW_FILE_BYTES", 1):
            self.assertIn(
                "grande",
                self.renderer.bundle(
                    PreviewSpec("pdf", (self.pdf,)), 0, (300, 400)
                ).error,
            )
        with patch("pdf_previews.MAX_DECODE_PIXELS", 1):
            self.assertIn(
                "grande",
                self.renderer.bundle(
                    PreviewSpec("images", (self.images[0],), ImagePageLayout()),
                    0,
                    (300, 400),
                ).error,
            )

    def test_changed_document_invalidates_cached_count_and_pixels(self):
        spec = PreviewSpec("pdf", (self.pdf,))
        first = self.renderer.render(spec, 0, (300, 400))
        make_pdf(self.pdf, ((200, 200, (0, 0, 1)),))
        second = self.renderer.render(spec, 0, (300, 400))
        self.assertEqual((first.count, second.count), (3, 1))
        self.assertNotEqual(first.rgb, second.rgb)

    def test_large_document_loads_only_a_window_of_pages(self):
        path = self.root / "large.pdf"
        make_pdf(path, [(120, 160, (0, 1, 0))] * 1001)
        result = self.renderer.bundle(PreviewSpec("pdf", (path,)), 999, (250, 300))
        self.assertEqual(result.total, 1001)
        self.assertLessEqual(len(result.thumbs), 4)
        self.assertLessEqual(self.renderer.renders, 5)
        self.assertLessEqual(self.renderer.cache.bytes, MAX_CACHE_BYTES)
        self.assertIsNotNone(result.main)

    def test_large_jpeg_decoder_reduces_before_loading(self):
        path = self.root / "camera.jpg"
        with Image.new("RGB", (3000, 2000), "red") as im:
            im.save(path)
        with patch("pdf_previews.MAX_DECODE_PIXELS", 2_000_000):
            bundle = self.renderer.bundle(
                PreviewSpec("images", (path,), ImagePageLayout()), 0, (350, 450)
            )
        self.assertIsNotNone(bundle.main, bundle.error)

    def test_cancellation_while_waiting_for_pdfium_does_not_render(self):
        token = Event()
        ended = Event()
        errors = []

        def run():
            try:
                self.renderer.render(
                    PreviewSpec("pdf", (self.pdf,)), 0, (300, 400), token
                )
            except PreviewCancelled:
                errors.append("cancelled")
            finally:
                ended.set()

        with PDFIUM_LOCK:
            thread = Thread(target=run)
            thread.start()
            token.set()
            self.assertTrue(ended.wait(2))
        thread.join(2)
        self.assertEqual(errors, ["cancelled"])


class PreviewSchedulingTests(unittest.TestCase):
    def test_cache_is_bounded_in_bytes_and_entries(self):
        cache = RasterCache(max_bytes=90, max_items=2)
        for number in range(100):
            cache.put(number, Raster(3, 3, b"x" * 27))
        self.assertLessEqual(cache.bytes, 90)
        self.assertEqual(len(cache.items), 2)
        cache.clear()
        self.assertEqual(cache.bytes, 0)

    def test_rapid_selection_discards_old_results_and_keeps_one_worker(self):
        started = Event()
        release = Event()

        class Renderer:
            def bundle(self, spec, index, bounds, cancel):
                if index == 0:
                    started.set()
                    release.wait(3)
                return PreviewBundle(
                    index, 1001, Raster(1, 1, bytes((index % 255, 0, 0)))
                )

            def close(self):
                pass

        worker = PreviewWorker(Renderer())
        try:
            worker.submit("view", 0, None, 0, (100, 100))
            self.assertTrue(started.wait(1))
            thread = worker.thread
            for number in range(1, 1001):
                worker.submit("view", number, None, number, (100, 100))
            self.assertLessEqual(len(worker.pending), 1)
            self.assertIs(worker.thread, thread)
            release.set()
            deadline = time.monotonic() + 3
            result = None
            while result is None and time.monotonic() < deadline:
                result = worker.take("view")
                time.sleep(0.005)
            self.assertEqual(result[0], 1000)
            self.assertEqual(result[1].index, 1000)
        finally:
            release.set()
            worker.close()
            worker.thread.join(3)
        self.assertFalse(worker.thread.is_alive())
        self.assertFalse(worker.results)

    def test_closing_cancels_waiting_work_and_clears_cache(self):
        worker = PreviewWorker()
        worker.renderer.cache.put("own", Raster(1, 1, b"abc"))
        worker.close()
        self.assertEqual(worker.renderer.cache.bytes, 0)
        worker.submit("closed", 1, None, 0, (100, 100))
        self.assertFalse(worker.pending)

    def test_switching_tools_preserves_other_owners_without_stale_updates(self):
        class Renderer:
            def bundle(self, spec, index, bounds, cancel):
                return PreviewBundle(index, 2, Raster(1, 1, b"abc"))

            def close(self):
                pass

        worker = PreviewWorker(Renderer())
        try:
            worker.submit("merge", 1, None, 0, (100, 100))
            worker.submit("extract", 2, None, 1, (100, 100))
            deadline = time.monotonic() + 2
            while len(worker.results) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(worker.take("merge")[0], 1)
            self.assertEqual(worker.take("extract")[0], 2)
            worker.invalidate("merge")
            self.assertIsNone(worker.take("merge"))
        finally:
            worker.close()
            worker.thread.join(2)
