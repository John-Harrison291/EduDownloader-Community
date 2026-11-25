"""Permanent service regressions promoted from the approved minimal OOXML experiment."""

from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch, Mock
import zipfile

import xml.etree.ElementTree as ET
from docx_writer import NS, q, validate
from pypdf import PdfReader, PdfWriter
import pypdfium2 as pdfium

import pdf_to_docx as service
from tests.pdf_word_fixtures import make_pdf


class PdfToDocxTests(unittest.TestCase):
    def test_waiting_for_pdfium_lock_remains_cancellable(self):
        make_pdf(self.source)
        event, attempting, ended = Event(), Event(), Event()
        errors = []
        lock = service.PDFIUM_LOCK

        class ObservedLock:
            def acquire(self, *, timeout):
                attempting.set()
                return lock.acquire(timeout=timeout)

            def release(self):
                lock.release()

        def convert():
            try:
                self.service.convert(self.source, self.output, cancel_event=event)
            except Exception as error:
                errors.append(error)
            finally:
                ended.set()

        with lock, patch.object(service, "PDFIUM_LOCK", ObservedLock()):
            worker = Thread(target=convert)
            worker.start()
            self.assertTrue(attempting.wait(2))
            event.set()
            self.assertTrue(ended.wait(3))
        worker.join(3)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], service.PdfToDocxCancelled)
        self.assertFalse(self.output.exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Word ação ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "Atividade Matemática.pdf"
        self.output = self.root / "Atividade Matemática.docx"
        self.service = service.PdfToDocxService(Mock(available=lambda: False))

    def convert(self, **fixture):
        expected = make_pdf(self.source, **fixture)
        before = self.source.read_bytes()
        result = self.service.convert(self.source, self.output)
        self.assertEqual(before, self.source.read_bytes())
        self.assertFalse(list(self.root.glob(".edudownloader-word-*")))
        with zipfile.ZipFile(self.output) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        validate(self.output)
        return result, document, expected

    def assert_code(self, code, call):
        with self.assertRaises(service.PdfToDocxError) as raised:
            call()
        self.assertEqual(raised.exception.code, code)

    def test_text_nodes_accents_order_and_paragraphs_no_raster(self):
        with patch.object(
            pdfium.PdfPage, "render", side_effect=AssertionError("no screenshots")
        ):
            _, document, expected = self.convert(reverse=True)
        text = "\n".join("".join(p.itertext()) for p in document.findall(".//w:p", NS))
        for line in expected:
            self.assertIn(line, text)
        self.assertIn("Primeiro parágrafo com atenção e acentuação. Continuação", text)
        self.assertEqual(len(document.findall(".//w:p", NS)), 5)
        # The fixture uses regular Helvetica, including its larger headings.
        self.assertIsNone(document.find(".//w:p/w:r/w:rPr/w:b", NS))
        sizes = [int(s.get(q("w:val"))) for s in document.findall(".//w:sz", NS)]
        self.assertGreater(sizes[0], sizes[-1])
        with zipfile.ZipFile(self.output) as archive:
            self.assertIn(b"<w:t ", archive.read("word/document.xml"))
            self.assertFalse(
                any(n.startswith("word/media/") for n in archive.namelist())
            )

    def test_image_preserved_and_aspect_ratio(self):
        _, document, _ = self.convert(image=True)
        self.assertEqual(len(document.findall(".//wp:inline", NS)), 1)
        shape = document.find(".//wp:extent", NS)
        self.assertAlmostEqual(int(shape.get("cx")) / int(shape.get("cy")), 2)

    def test_fragmented_line_preserves_existing_word_spacing(self):
        for first, second, second_x, expected in (
            ("Atividade ", "escolar.", 100, "Atividade escolar."),
            ("Atividade", "escolar.", 100, "Atividade escolar."),
            ("Atividade ", "escolar.", 240, "Atividade \tescolar."),
        ):
            with self.subTest(first=first, second=second, second_x=second_x):
                self.output.unlink(missing_ok=True)
                _, document, _ = self.convert(
                    text_lines=[
                        (48, 720, 12, first),
                        (second_x, 720, 12, second),
                        (48, 680, 12, "Segundo parágrafo independente."),
                    ],
                    reverse=True,
                )
                paragraphs = document.findall(".//w:body/w:p", NS)
                self.assertEqual(len(paragraphs), 2)
                self.assertEqual(
                    validate(self.output)["text"],
                    expected + "Segundo parágrafo independente.",
                )
                self.assertEqual(
                    "".join(paragraphs[0].itertext()), expected.replace("\t", "")
                )
                self.assertEqual(
                    "".join(paragraphs[1].itertext()), "Segundo parágrafo independente."
                )

    def test_line_separator_preserves_extracted_whitespace_and_wide_gaps(self):
        for first, second, second_x, expected in (
            ("Atividade", " escolar.", 100, "Atividade escolar."),
            ("Atividade  ", "escolar.", 100, "Atividade  escolar."),
            ("Atividade  escolar ", "simples.", 100, "Atividade  escolar simples."),
            ("Atividade ", " escolar.", 100, "Atividade  escolar."),
            ("Atividade", "escolar.", 100, "Atividade escolar."),
            ("Atividade", "escolar.", 240, "Atividade\tescolar."),
        ):
            with self.subTest(first=first, second=second, second_x=second_x):
                lines = service._reading_lines(
                    [
                        service._Block(first, 48, 720, 97, 732),
                        service._Block(second, second_x, 720, second_x + 40, 732),
                    ]
                )
                self.assertEqual([line.text for line in lines], [expected])

    def test_multipage_progress(self):
        make_pdf(self.source, count=3)
        progress = []
        result = self.service.convert(
            self.source, self.output, progress=progress.append
        )
        self.assertEqual(result.page_count, 3)
        self.assertEqual([p.completed_items for p in progress], [0, 1, 2, 3])
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("word/document.xml").count(b"<w:sectPr>"), 3)

    def test_landscape_sections(self):
        _, document, _ = self.convert(count=3, landscape=(1,))
        sizes = document.findall(".//w:pgSz", NS)
        self.assertEqual(len(sizes), 3)
        self.assertEqual(
            [s.get(q("w:orient")) for s in sizes], ["portrait", "landscape", "portrait"]
        )
        self.assertLess(int(sizes[0].get(q("w:w"))), int(sizes[0].get(q("w:h"))))
        self.assertGreater(int(sizes[1].get(q("w:w"))), int(sizes[1].get(q("w:h"))))

    def test_image_text_requires_local_ocr_component(self):
        make_pdf(self.source, scanned=(0,))
        self.assert_code(
            service.DocxErrorCode.OCR_UNAVAILABLE,
            lambda: self.service.convert(self.source, self.output),
        )
        self.assertFalse(self.output.exists())

    def test_mixed_retains_noneditable_page(self):
        result, document, _ = self.convert(count=3, scanned=(0, 2))
        self.assertEqual(result.non_editable_pages, (1, 3))
        self.assertEqual(len(document.findall(".//wp:inline", NS)), 2)
        self.assertIn(
            "Ciências página 2",
            "\n".join("".join(p.itertext()) for p in document.findall(".//w:p", NS)),
        )

    def test_aligned_table_reconstruction_preserves_each_editable_cell(self):
        _, document, expected = self.convert(table=True)
        text = "\n".join("".join(p.itertext()) for p in document.findall(".//w:p", NS))
        self.assertEqual(len(document.findall(".//w:tbl", NS)), 1)
        self.assertEqual(len(document.findall(".//w:tbl/w:tr", NS)), 4)
        self.assertEqual(len(document.findall(".//w:tbl/w:tr/w:tc", NS)), 12)
        for cell in expected:
            self.assertIn(cell, text)

    def test_invalid_corrupt_and_renamed(self):
        for data in (b"plain text", b"%PDF-1.7 broken"):
            self.source.write_bytes(data)
            self.assert_code(
                service.DocxErrorCode.INVALID_PDF,
                lambda: self.service.convert(self.source, self.output),
            )

    def test_protected_including_empty_user_password(self):
        for password in ("secret", ""):
            make_pdf(self.source)
            writer = PdfWriter(clone_from=PdfReader(self.source))
            writer.encrypt(password, owner_password="owner")
            with self.source.open("wb") as stream:
                writer.write(stream)
            writer.close()
            self.assert_code(
                service.DocxErrorCode.PROTECTED_PDF,
                lambda: self.service.convert(self.source, self.output),
            )

    def test_collision_preserves_previous(self):
        make_pdf(self.source)
        self.output.write_bytes(b"previous")
        self.assert_code(
            service.DocxErrorCode.OUTPUT_INVALID,
            lambda: self.service.convert(self.source, self.output),
        )
        self.assertEqual(self.output.read_bytes(), b"previous")

    def test_failed_validation_atomic_and_no_temporary(self):
        make_pdf(self.source)
        self.output.write_bytes(b"previous")
        with patch.object(
            service,
            "validate_docx",
            side_effect=service.PdfToDocxError(service.DocxErrorCode.OUTPUT_INVALID),
        ):
            self.assert_code(
                service.DocxErrorCode.OUTPUT_INVALID,
                lambda: self.service.convert(self.source, self.output, overwrite=True),
            )
        self.assertEqual(self.output.read_bytes(), b"previous")
        self.assertFalse(list(self.root.glob(".edudownloader-word-*")))

    def test_cancel_after_page(self):
        make_pdf(self.source, count=3)
        event = Event()

        def progress(item):
            if item.completed_items == 1:
                event.set()

        with self.assertRaises(service.PdfToDocxCancelled):
            self.service.convert(
                self.source, self.output, cancel_event=event, progress=progress
            )
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob(".edudownloader-word-*")))

    def test_cancel_before_publish_preserves_previous(self):
        make_pdf(self.source)
        self.output.write_bytes(b"previous")
        event = Event()
        with patch.object(service, "validate_docx", side_effect=lambda *_: event.set()):
            with self.assertRaises(service.PdfToDocxCancelled):
                self.service.convert(
                    self.source, self.output, overwrite=True, cancel_event=event
                )
        self.assertEqual(self.output.read_bytes(), b"previous")
        self.assertFalse(list(self.root.glob(".edudownloader-word-*")))

    def test_limits(self):
        make_pdf(self.source, count=2, image=True)
        for name, limit in (
            ("MAX_INPUT_BYTES", 10),
            ("MAX_PAGES", 1),
            ("MAX_PAGE_POINTS", 100),
            ("MAX_TEXT_CHARS", 5),
            ("MAX_IMAGE_PIXELS", 10),
            ("MAX_PAGE_OBJECTS", 1),
            ("MAX_DECODED_IMAGE_BYTES", 100),
        ):
            with self.subTest(name=name), patch.object(service, name, limit):
                self.assert_code(
                    service.DocxErrorCode.RESOURCE_LIMIT,
                    lambda: self.service.convert(self.source, self.output),
                )
        self.assertFalse(self.output.exists())

    def test_docx_validation_crc_structure_text_and_external_links(self):
        self.output.write_bytes(b"not a zip")
        self.assert_code(
            service.DocxErrorCode.OUTPUT_INVALID,
            lambda: service.validate_docx(self.output, "expected"),
        )
        self.output.unlink()
        self.convert()
        self.assert_code(
            service.DocxErrorCode.OUTPUT_INVALID,
            lambda: service.validate_docx(self.output, "wrong text"),
        )
        with zipfile.ZipFile(self.output, "a") as archive:
            archive.writestr(
                "word/_rels/bad.rels",
                '<Relationships><Relationship TargetMode="External" Target="https://invalid.test" /></Relationships>',
            )
        self.assert_code(
            service.DocxErrorCode.OUTPUT_INVALID,
            lambda: service.validate_docx(self.output, "text"),
        )


if __name__ == "__main__":
    unittest.main()
