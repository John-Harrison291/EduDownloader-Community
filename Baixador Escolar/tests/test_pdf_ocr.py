"""Known, own fixtures for regional OCR, geometry and streamed DOCX assets."""

from contextlib import closing
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import tempfile
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    ArrayObject,
    NumberObject,
)
import pypdfium2 as pdfium

import docx_writer as w
import pdf_to_docx as service
import pdf_word_ocr as reconstruction
from pdf_ocr_runtime import OcrRuntime, OcrFailure, OcrWord, OcrBatch, parse_tsv
from pdf_ocr_vision import analyze, VisionLimit, TextRegion
import pdf_ocr_windows
from pdfium_access import PDFIUM_LOCK, page_matrix, page_objects
from tests.pdf_word_fixtures import make_pdf
from tests.test_pdf_to_docx_styles import make_styled_pdf


def text_image():
    image = Image.new("RGB", (1100, 700), "white")
    font = ImageFont.truetype("arial.ttf", 30)
    draw = ImageDraw.Draw(image)
    draw.text((70, 80), "Atividade com atenção e água", font=font, fill="black")
    draw.text((70, 140), "Questão 1. Quanto é 12 + 8?", font=font, fill="black")
    draw.text((70, 200), "Escreva uma explicação completa.", font=font, fill="black")
    return image


class VisionTests(unittest.TestCase):
    def test_text_candidates_and_existing_layer_coverage(self):
        with text_image() as image:
            result = analyze(image)
            self.assertGreater(len(result.regions), 0)
            covered = analyze(image, [(50, 50, 1050, 260)])
            self.assertEqual(covered.regions, ())
            self.assertGreater(covered.covered_components, 20)

    def test_own_illustration_does_not_justify_ocr(self):
        with Image.new("RGB", (600, 500), "white") as image:
            draw = ImageDraw.Draw(image)
            draw.ellipse((50, 50, 200, 200), fill="blue")
            draw.polygon(((300, 60), (540, 260), (290, 300)), fill="orange")
            self.assertEqual(analyze(image).regions, ())

    def test_analysis_bound_and_cancel(self):
        with Image.new("L", (5000, 5000)) as image:
            with self.assertRaises(VisionLimit):
                analyze(image)
        with text_image() as image:
            with self.assertRaisesRegex(RuntimeError, "cancel"):
                analyze(image, cancel=Mock(side_effect=RuntimeError("cancel")))

    def test_rotated_box_mapping(self):
        self.assertEqual(
            reconstruction._inverse_box((10, 20, 30, 40), 90, 200, 100),
            (160, 10, 180, 30),
        )
        self.assertEqual(
            reconstruction._inverse_box((10, 20, 30, 40), 270, 200, 100),
            (20, 70, 40, 90),
        )


class RuntimeParsingTests(unittest.TestCase):
    def test_windows_failure_is_cached_without_disabling_portable_engine(self):
        runtime = OcrRuntime()
        with (
            Image.new("L", (100, 100)) as image,
            patch.object(
                pdf_ocr_windows,
                "system_powershell",
                return_value=Path("system-powershell.exe"),
            ),
            patch.object(runtime, "_run", side_effect=OcrFailure("timeout")) as child,
        ):
            self.assertIsNone(runtime.recognize_windows(image, ()))
            self.assertIsNone(runtime.recognize_windows(image, ()))
            self.assertEqual(child.call_count, 1)
        self.assertFalse(runtime._windows_available)
        # A Windows API failure must not change Tesseract's component lookup.
        with patch.object(runtime, "_verified_file", return_value=Path("verified")):
            self.assertTrue(runtime.available())

    def test_windows_adapter_masks_digital_and_does_not_fabricate_confidence(self):
        runtime = OcrRuntime(prefer_windows=True)

        def run(arguments, directory, cancel, timeout):
            self.assertNotIn("-ExecutionPolicy", arguments)
            self.assertIn("-NoProfile", arguments)
            with Image.open(directory / "page.png") as raster:
                self.assertEqual(raster.getpixel((5, 5)), 255)
            (directory / "recognized.json").write_text(
                json.dumps(
                    {
                        "lines": [
                            [
                                {
                                    "text": "água",
                                    "x": 15,
                                    "y": 15,
                                    "width": 20,
                                    "height": 10,
                                }
                            ]
                        ]
                    }
                ),
                "utf-8",
            )
            return 1234

        with (
            Image.new("L", (100, 100), 0) as image,
            patch.object(
                pdf_ocr_windows,
                "system_powershell",
                return_value=Path("system-powershell.exe"),
            ),
            patch.object(runtime, "_run", side_effect=run),
        ):
            result = pdf_ocr_windows.recognize(
                runtime, image, [(0, 0, 10, 10)], lambda: None
            )
        self.assertEqual(result.pages[0][0].text, "água")
        self.assertIsNone(result.pages[0][0].confidence)
        self.assertEqual(result.engine, "windows-ocr")

    def test_windows_missing_language_is_cached_without_installing(self):
        runtime = OcrRuntime()

        def run(arguments, directory, cancel, timeout):
            (directory / "recognized.json").write_text("{}", "utf-8")
            return 1000

        with (
            Image.new("L", (100, 100)) as image,
            patch.object(
                pdf_ocr_windows,
                "system_powershell",
                return_value=Path("system-powershell.exe"),
            ),
            patch.object(runtime, "_run", side_effect=run) as child,
        ):
            self.assertIsNone(runtime.recognize_windows(image, ()))
            self.assertIsNone(runtime.recognize_windows(image, ()))
            self.assertEqual(child.call_count, 1)

    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"

    def test_quotes_accents_numbers_preserved(self):
        text = self.header + '5\t1\t1\t1\t1\t1\t10\t20\t90\t30\t95.2\t"água"\n'
        result = parse_tsv(text, [(200, 200)])
        self.assertEqual(result[0][0].text, '"água"')
        self.assertAlmostEqual(result[0][0].confidence, 95.2)

    def test_invalid_coordinates_confidence_and_page(self):
        for page, left, confidence in (
            (0, 10, "95"),
            (2, 10, "95"),
            (1, -10, "95"),
            (1, 10, "nan"),
        ):
            with (
                self.subTest(page=page, left=left, confidence=confidence),
                self.assertRaises(OcrFailure),
            ):
                parse_tsv(
                    self.header
                    + f"5\t{page}\t1\t1\t1\t1\t{left}\t20\t90\t30\t{confidence}\tágua\n",
                    [(200, 200)],
                )

    def test_missing_component_has_no_download_or_process(self):
        with tempfile.TemporaryDirectory() as root, patch("subprocess.Popen") as child:
            self.assertFalse(OcrRuntime(root).available())
            child.assert_not_called()

    def test_batch_and_timeout_limits_before_launch(self):
        runtime = OcrRuntime()
        with self.assertRaises(OcrFailure):
            runtime.recognize([])
        with self.assertRaises(OcrFailure):
            runtime._run([], ".", lambda: None, float("nan"))


class StreamedMediaTests(unittest.TestCase):
    def test_bounded_page_anchor_and_unsupported_attributes(self):
        store = w.ImageStore()
        self.addCleanup(store.close)
        with Image.new("RGB", (24, 18), "blue") as image:
            stream = BytesIO()
            image.save(stream, "PNG")
        picture = w.Picture(store.add(stream.getvalue()), 24, 18, position=(48, 100))
        page = w.Page(595, 842, (picture, w.Paragraph((w.Run("Texto editável"),))))
        parts, expected = w.package_parts([page])
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "test.docx"
            with output.open("wb") as target:
                w.save_parts(parts, target)
            self.assertEqual(w.validate(output, expected)["images"], 1)
        with self.assertRaises(ValueError):
            w.package_parts(
                [replace(page, blocks=(replace(picture, position=(590, 100)),))]
            )

    def test_asset_stream_tamper_detection_and_cleanup(self):
        store = w.ImageStore()
        self.addCleanup(store.close)
        with Image.new("RGB", (24, 18), "blue") as image:
            stream = BytesIO()
            image.save(stream, "PNG")
        asset = store.add(stream.getvalue())
        parts, expected = w.package_parts(
            [
                w.Page(
                    595,
                    842,
                    (w.Paragraph((w.Run("Editável"),)), w.Picture(asset, 24, 18)),
                )
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "output.docx"
            with target.open("wb") as output:
                w.save_parts(parts, output)
            self.assertEqual(w.validate(target, expected)["images"], 1)
            changed = bytearray(asset.path.read_bytes())
            changed[-1] ^= 1
            asset.path.write_bytes(changed)
            with self.assertRaises(OSError):
                w.save_parts(parts, BytesIO())
        directory = asset.path.parent
        store.close()
        self.assertFalse(directory.exists())


class NativeGeometryTests(unittest.TestCase):
    def test_decorative_digital_overprint_is_single_text_with_repeated_letters_kept(
        self,
    ):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.pdf", Path(root) / "output.docx"
            make_styled_pdf(
                source,
                [
                    (48, 720, 24, "R", "Escola 111"),
                    (49, 719, 24, "R", "Escola 111"),
                    (48, 721, 24, "R", "Escola 111"),
                    (48, 650, 12, "R", "Letras ll e numeros 111 permanecem."),
                ],
            )
            result = service.PdfToDocxService(Mock(available=lambda: False)).convert(
                source, output
            )
            text = w.validate(output)["text"]
            self.assertEqual(text.count("Escola 111"), 1)
            self.assertIn("Letras ll e numeros 111 permanecem.", text)
            self.assertEqual(result.ocr_pages, ())

    def test_nested_form_lifetime_transform_and_conversion(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.pdf", Path(root) / "output.docx"
            make_pdf(source)
            pdf = PdfWriter(clone_from=PdfReader(source))
            page = pdf.pages[0]
            form = DecodedStreamObject()
            form.set_data(page.get_contents().get_data())
            form.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Form"),
                    NameObject("/BBox"): ArrayObject(
                        [
                            NumberObject(0),
                            NumberObject(0),
                            NumberObject(595),
                            NumberObject(842),
                        ]
                    ),
                    NameObject("/Resources"): page["/Resources"],
                }
            )
            reference = pdf._add_object(form)
            page[NameObject("/Resources")] = DictionaryObject(
                {
                    NameObject("/XObject"): DictionaryObject(
                        {NameObject("/Fm"): reference}
                    )
                }
            )
            stream = DecodedStreamObject()
            stream.set_data(b"q .75 0 0 .75 30 40 cm /Fm Do Q")
            page[NameObject("/Contents")] = pdf._add_object(stream)
            pdf.write(source)
            pdf.close()
            with (
                PDFIUM_LOCK,
                pdfium.PdfDocument(source) as doc,
                closing(doc[0]) as native,
                page_objects(native) as objects,
            ):
                children = [
                    entry
                    for entry in objects
                    if isinstance(entry.object, pdfium.PdfTextObj)
                ]
                self.assertGreater(len(children), 4)
                self.assertAlmostEqual(children[0].matrix.a, 0.75)
                self.assertGreater(children[0].bounds[0], 30)
            service.PdfToDocxService().convert(source, output)
            self.assertIn("Ciências página 1", w.validate(output)["text"])

    def test_crop_and_rotation_match_pdfium_device_frame(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.pdf"
            for rotation in (0, 90, 180, 270):
                make_pdf(source)
                pdf = PdfWriter(clone_from=PdfReader(source))
                page = pdf.pages[0]
                page.cropbox.lower_left = (20, 30)
                page.cropbox.upper_right = (560, 800)
                page.rotate(rotation)
                pdf.write(source)
                pdf.close()
                with (
                    PDFIUM_LOCK,
                    pdfium.PdfDocument(source) as doc,
                    closing(doc[0]) as native,
                ):
                    matrix = page_matrix(native)
                    width, height = native.get_size()
                    with closing(native.render(scale=1)) as bitmap:
                        converter = bitmap.get_posconv(native)
                        for x, y in ((20, 30), (560, 800), (100, 200)):
                            expected = converter.to_bitmap(x, y)
                            xx, yy = matrix.on_point(x, y)
                            self.assertAlmostEqual(xx, expected[0], delta=1)
                            self.assertAlmostEqual(height - yy, expected[1], delta=1)


class RegionalIntegrationTests(unittest.TestCase):
    def test_isolated_printed_numbers_remain_recoverable_in_cells(self):
        for text in ("1", "12", "2002"):
            for confidence in (98, None):
                with self.subTest(text=text, confidence=confidence):
                    self.assertTrue(
                        reconstruction._accepted(
                            (OcrWord(text, 0, 0, 12, 20, confidence, 1, 1, 1),)
                        )
                    )

    def test_horizontal_shape_noise_is_not_rescued_by_rotating_until_words_appear(self):
        with text_image() as image, closing(w.ImageStore()) as store:
            analysis = analyze(image)
            analysis = replace(analysis, regions=(analysis.regions[0],))
            batch = OcrBatch(
                (
                    tuple(
                        OcrWord("E", 10 + i * 20, 5, 10, 20, 98, 1, 1, 1)
                        for i in range(6)
                    ),
                ),
                0.01,
                1000,
            )
            runtime = Mock(recognize=Mock(return_value=batch))
            result = reconstruction.recognize_page(
                image, (550, 350), [], analysis, runtime, store, lambda: None
            )
            self.assertEqual(result.glyphs, ())
            self.assertTrue(result.review)
            self.assertEqual(runtime.recognize.call_count, 1)

    def test_native_failure_after_render_closes_detached_raster(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.pdf", Path(root) / "output.docx"
            make_pdf(source, image=True)
            image, raster = Image.new("RGB", (32, 32)), Image.new("RGB", (32, 32))
            image.copy = Mock(return_value=raster)
            bitmap = Mock(to_pil=lambda: image)
            with (
                patch.object(pdfium.PdfPage, "render", return_value=bitmap),
                patch.object(
                    service.layout,
                    "isolated_graphics",
                    side_effect=RuntimeError("native failure"),
                ),
                self.assertRaises(service.PdfToDocxError),
            ):
                service.PdfToDocxService().convert(source, output)
            with self.assertRaises(ValueError):
                raster.getpixel((0, 0))
            self.assertFalse(output.exists())

    def test_mixed_ocr_preserves_digital_bold_and_normal_styles(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.pdf", Path(root) / "output.docx"
            make_styled_pdf(
                source,
                [
                    (48, 720, 12, "B", "Leia o texto"),
                    (120, 720, 12, "R", "e responda."),
                ],
                image=True,
            )

            def recognize(images, **kwargs):
                return OcrBatch(
                    tuple(
                        (OcrWord("FIGURA", 10, 10, 100, 25, 95, 1, 1, 1),)
                        for _ in images
                    ),
                    0.01,
                    1000,
                )

            runtime = Mock(available=lambda: True, recognize=recognize)
            result = service.PdfToDocxService(runtime).convert(source, output)
            self.assertEqual(result.ocr_pages, (1,))
            info = w.validate(output)
            self.assertIn("Leia o texto e responda.", info["text"])
            self.assertIn("FIGURA", info["text"])
            self.assertGreaterEqual(info["images"], 1)
            with zipfile.ZipFile(output) as archive:
                tree = ET.fromstring(archive.read("word/document.xml"))
            paragraph = next(
                p
                for p in tree.findall(".//w:p", w.NS)
                if "Leia" in "".join(t.text or "" for t in p.findall(".//w:t", w.NS))
            )
            runs = paragraph.findall("w:r", w.NS)
            self.assertIsNotNone(runs[0].find("w:rPr/w:b", w.NS))
            self.assertIsNone(runs[-1].find("w:rPr/w:b", w.NS))

    def test_graphic_only_page_never_starts_recognition_or_orientation(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.pdf", Path(root) / "output.docx"
            make_pdf(source, scanned=(0,))
            pdf = PdfWriter(clone_from=PdfReader(source))
            with Image.new("RGB", (240, 120), "white") as image:
                ImageDraw.Draw(image).ellipse((40, 20, 120, 100), fill="blue")
                pdf.pages[0]["/Resources"]["/XObject"]["/Im1"].set_data(image.tobytes())
            pdf.write(source)
            pdf.close()
            runtime = Mock(available=lambda: True)
            with self.assertRaises(service.PdfToDocxError) as raised:
                service.PdfToDocxService(runtime).convert(source, output)
            self.assertEqual(
                raised.exception.code, service.DocxErrorCode.SCANNED_OR_IMAGE_ONLY
            )
            runtime.recognize.assert_not_called()
            runtime.orientation.assert_not_called()

    def test_overlapping_candidate_rasters_are_bounded_before_allocation(self):
        with text_image() as image, closing(w.ImageStore()) as store:
            analysis = replace(
                analyze(image), regions=(TextRegion((0, 0, 5000, 5000), 3),) * 2
            )
            with patch.object(image, "crop") as crop, self.assertRaises(VisionLimit):
                reconstruction.recognize_page(
                    image, (550, 350), [], analysis, Mock(), store, lambda: None
                )
            crop.assert_not_called()

    def test_shared_editable_flow_deduplicates_overlapping_regions(self):
        # The engine is deterministic here; native-engine quality is measured
        # separately against the retained known-transcription corpus.
        with text_image() as image, closing(w.ImageStore()) as store:
            analysis = analyze(image)
            analysis = replace(
                analysis, regions=(analysis.regions[0], analysis.regions[0])
            )

            def recognize(images, **kwargs):
                pages = tuple(
                    (
                        OcrWord("Questão", 5, 5, 100, 25, 95, 1, 1, 1),
                        OcrWord("12", 110, 5, 35, 25, 98, 1, 1, 1),
                        OcrWord("água", 155, 5, 80, 25, 96, 1, 1, 1),
                    )
                    for _ in images
                )
                return OcrBatch(pages, 0.01, 1000)

            runtime = Mock(recognize=recognize)
            result = reconstruction.recognize_page(
                image, (550, 350), [], analysis, runtime, store, lambda: None
            )
            self.assertEqual(result.words, 3)
            budget = [0, 0, 0]
            page = service.layout.compose_page(
                (550, 350),
                [],
                list(result.glyphs),
                [],
                list(result.graphics),
                budget,
                lambda: None,
                lambda valid: self.assertTrue(valid),
            )
            text = " ".join(
                r.text
                for p in service.layout.walk_paragraphs(page.blocks)
                for r in p.runs
            )
            self.assertIn("Questão 12 água", text)

    def test_recognition_cancel_releases_crops_and_does_not_publish(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.pdf", Path(root) / "output.docx"
            make_pdf(source, scanned=(0,))
            output.write_bytes(b"previous")
            runtime = Mock(
                available=lambda: True,
                orientation=lambda *a, **kw: None,
                recognize=Mock(side_effect=service.PdfToDocxCancelled("cancel")),
            )
            with self.assertRaises(service.PdfToDocxCancelled):
                service.PdfToDocxService(runtime).convert(
                    source, output, overwrite=True
                )
            self.assertEqual(output.read_bytes(), b"previous")
            self.assertFalse(list(Path(root).glob(".edudownloader-word-*")))

    def test_ocr_shares_global_text_budget_and_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.pdf", Path(root) / "output.docx"
            make_pdf(source, scanned=(0,))
            output.write_bytes(b"previous")
            runtime = Mock(available=lambda: True, orientation=lambda *a, **kw: None)
            recognized = Mock(glyphs=(Mock(text="Questão"),))
            with (
                patch.object(service, "MAX_TEXT_CHARS", 3),
                patch.object(reconstruction, "recognize_page", return_value=recognized),
                self.assertRaises(service.PdfToDocxError) as raised,
            ):
                service.PdfToDocxService(runtime).convert(
                    source, output, overwrite=True
                )
            self.assertEqual(
                raised.exception.code, service.DocxErrorCode.RESOURCE_LIMIT
            )
            self.assertEqual(output.read_bytes(), b"previous")
            self.assertFalse(list(Path(root).glob(".edudownloader-word-*")))
