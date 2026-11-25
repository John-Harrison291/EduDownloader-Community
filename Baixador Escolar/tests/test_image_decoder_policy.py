"""Exercise the image input policy with small, benign fixtures."""

from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch

from PIL import Image, UnidentifiedImageError
from PIL.PngImagePlugin import PngInfo
from pypdf import PdfReader

from file_preview import PreviewStatus, _preview_image
from image_preparation import ImagePreparationReader
from pdf_previews import PageRenderer, fingerprint
from pdf_tools import InvalidImageError, PdfOperationCancelled, PdfToolsService
from poster_tools import InvalidPosterImageError, PosterRequest, PosterService
from print_layout import Size
from ui_pages import _preview_image_size


class ImageDecoderPolicyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.reader = ImagePreparationReader()
        self.renderer = PageRenderer()
        self.addCleanup(self.reader.close)
        self.addCleanup(self.renderer.close)
        self.pdf = PdfToolsService()
        self.poster = PosterService()

    def test_renamed_images_are_rejected_before_other_decoders_are_considered(self):
        Image.init()
        for image_format in ("GIF", "TIFF", "XBM"):
            with self.subTest(image_format=image_format):
                path = self.root / f"{image_format}.png"
                with Image.new("1", (8, 8), 1) as image:
                    image.save(path, format=image_format)
                pdf_output = self.root / "images.pdf"
                poster_output = self.root / "poster.pdf"

                unexpected_probe = Mock(
                    side_effect=AssertionError(
                        f"Unexpected identification attempt for {image_format}"
                    )
                )
                original_factory = Image.OPEN[image_format][0]
                with patch.dict(
                    Image.OPEN, {image_format: (original_factory, unexpected_probe)}
                ):
                    self.assertEqual(_preview_image(path).status, PreviewStatus.INVALID)
                    with self.assertRaises(UnidentifiedImageError):
                        self.reader.size(path, fingerprint(path))
                    with self.assertRaises(UnidentifiedImageError):
                        self.renderer.image_thumbnail(path, (64, 64))
                    self.assertEqual(_preview_image_size(path), (Size(1.0, 1.0), True))
                    with self.assertRaises(InvalidImageError):
                        self.pdf.images_to_pdf([path], pdf_output)
                    with self.assertRaises(InvalidPosterImageError):
                        self.poster.create(PosterRequest(path, poster_output))
                unexpected_probe.assert_not_called()
                self.assertFalse(pdf_output.exists())
                self.assertFalse(poster_output.exists())

    def test_exif_orientation_and_rgba_survive_the_real_image_paths(self):
        photo = self.root / "photo.jpg"
        alpha = self.root / "transparente.png"
        with Image.new("RGB", (36, 18), (12, 50, 220)) as image:
            exif = image.getexif()
            exif[274] = 6
            image.save(photo, exif=exif)
        with Image.new("RGBA", (24, 12), (255, 0, 0, 128)) as image:
            image.save(alpha)
        originals = {path: path.read_bytes() for path in (photo, alpha)}

        preview = _preview_image(photo)
        self.assertEqual(preview.status, PreviewStatus.SUCCESS)
        self.assertEqual((preview.width, preview.height), (18, 36))
        self.assertEqual(self.reader.size(photo, fingerprint(photo)), Size(18, 36))
        small, reported_size = self.renderer.image_thumbnail(photo, (12, 12))
        self.assertEqual(reported_size, Size(18, 36))
        self.assertLess(small.width, small.height)

        png_preview = _preview_image(alpha)
        self.assertEqual(png_preview.status, PreviewStatus.SUCCESS)
        self.assertEqual(tuple(png_preview.rgba[:4]), (255, 0, 0, 128))
        flattened, _ = self.renderer.image_thumbnail(alpha, (64, 64))
        with flattened.image() as image:
            red, green, blue = image.getpixel((0, 0))
        self.assertEqual(red, 255)
        self.assertTrue(126 <= green <= 128 and green == blue)

        pdf = self.root / "output.pdf"
        self.pdf.images_to_pdf([photo, alpha], pdf)
        self.assertEqual(len(PdfReader(pdf).pages), 2)
        poster = self.root / "poster.pdf"
        self.poster.create(PosterRequest(alpha, poster))
        self.assertEqual(len(PdfReader(poster).pages), 4)
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_invalid_image_and_cancellation_leave_no_output(self):
        bad = self.root / "invalid.jpg"
        bad.write_bytes(b"Invalid JPEG fixture")
        png = self.root / "valid.png"
        with Image.new("RGB", (12, 16), "red") as image:
            image.save(png)
        original = png.read_bytes()
        output = self.root / "output.pdf"
        with self.assertRaises(InvalidImageError):
            self.pdf.images_to_pdf([png, bad], output)
        self.assertFalse(output.exists())
        cancel = Event()
        cancel.set()
        with self.assertRaises(PdfOperationCancelled):
            self.pdf.images_to_pdf([png], output, cancel_event=cancel)
        self.assertFalse(output.exists())
        self.assertEqual(png.read_bytes(), original)

    def test_small_png_metadata_and_truncated_input(self):
        png = self.root / "metadata.png"
        metadata = PngInfo()
        metadata.add_text("Description", "Synthetic classroom image")
        with Image.new("RGB", (30, 20), "green") as image:
            image.save(png, pnginfo=metadata)
        self.assertEqual(_preview_image(png).status, PreviewStatus.SUCCESS)
        with Image.open(png, formats=("PNG",)) as image:
            self.assertEqual(image.info["Description"], "Synthetic classroom image")

        short = self.root / "truncada.png"
        original = png.read_bytes()
        short.write_bytes(original[: len(original) // 2])
        self.assertEqual(_preview_image(short).status, PreviewStatus.INVALID)
        output = self.root / "partial.pdf"
        with self.assertRaises(InvalidImageError):
            self.pdf.images_to_pdf([short], output)
        self.assertFalse(output.exists())
        self.assertEqual(png.read_bytes(), original)
