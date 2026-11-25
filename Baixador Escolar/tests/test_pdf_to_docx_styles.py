"""Mixed styles from synthetic PDFs, checked at the generated OOXML run boundary."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import xml.etree.ElementTree as ET
import zipfile

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import pypdfium2 as pdfium

from docx_writer import NS, q, validate
import pdf_to_docx as service
from tests.pdf_word_fixtures import make_pdf


def make_styled_pdf(path, fragments, *, reverse=False, image=False):
    make_pdf(path, image=image)
    original = PdfReader(path)
    writer = PdfWriter(clone_from=original)
    page = writer.pages[0]
    fonts = page["/Resources"]["/Font"]
    for key, name in (
        ("R", "Helvetica"),
        ("B", "Helvetica-Bold"),
        ("I", "Helvetica-Oblique"),
        ("BI", "Helvetica-BoldOblique"),
    ):
        fonts[NameObject("/" + key)] = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/" + name),
                    NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
                }
            )
        )
    commands = [
        f"BT /{font} {size} Tf 1 0 0 1 {x} {y} Tm <{text.encode('cp1252').hex()}> Tj ET"
        for x, y, size, font, text in (reversed(fragments) if reverse else fragments)
    ]
    if image:
        commands.append("q 240 0 0 120 48 462 cm /Im1 Do Q")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    writer.close()


def run_content(run):
    return "".join(
        "\t" if node.tag == q("w:tab") else node.text or ""
        for node in run
        if node.tag in (q("w:t"), q("w:tab"))
    )


class MixedStyleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="word-styles-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "synthetic.pdf"
        self.output = self.root / "synthetic.docx"
        # Digital-only regressions must not depend on a maintainer's installed
        # OCR component. The OCR-enabled mixed-style case is in test_pdf_ocr.
        self.runtime = Mock(available=lambda: False)

    def convert(self, fragments, **options):
        make_styled_pdf(self.source, fragments, **options)
        before = self.source.read_bytes()
        service.PdfToDocxService(self.runtime).convert(self.source, self.output)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".edudownloader-word-*")))
        validate(self.output)
        with zipfile.ZipFile(self.output) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
        return document

    def assert_styles(self, paragraph, expected):
        actual = []
        for run in paragraph.findall("w:r", NS):
            bold = run.find("w:rPr/w:b", NS) is not None
            italic = run.find("w:rPr/w:i", NS) is not None
            actual.extend(
                (c, bold, italic) for c in run_content(run) if not c.isspace()
            )
        self.assertEqual(
            actual,
            [(c, b, i) for text, b, i in expected for c in text if not c.isspace()],
        )

    def test_bold_and_normal_same_line(self):
        document = self.convert(
            [(48, 720, 12, "B", "Leia o texto"), (120, 720, 12, "R", "e responda.")],
            reverse=True,
            image=True,
        )
        paragraph = document.find(".//w:body/w:p", NS)
        # PR #1 avoids adding a separator already extracted by PDFium.
        self.assertEqual("".join(paragraph.itertext()), "Leia o texto e responda.")
        self.assert_styles(
            paragraph, [("Leia o texto", True, False), ("e responda.", False, False)]
        )
        self.assertEqual(len(document.findall(".//wp:inline", NS)), 1)

    def test_italic_and_normal_same_line(self):
        document = self.convert(
            [(48, 720, 12, "I", "Leia o texto"), (120, 720, 12, "R", "e responda.")]
        )
        paragraph = document.find(".//w:body/w:p", NS)
        self.assertEqual("".join(paragraph.itertext()), "Leia o texto e responda.")
        self.assert_styles(
            paragraph, [("Leia o texto", False, True), ("e responda.", False, False)]
        )

    def test_mixed_styles_across_joined_lines_and_paragraph_order(self):
        document = self.convert(
            [
                (48, 720, 12, "R", "Normal"),
                (100, 720, 12, "B", "negrito"),
                (148, 720, 12, "I", "itálico"),
                (188, 720, 12, "R", "normal."),
                (48, 704, 12, "BI", "Ambos"),
                (100, 704, 12, "R", "fim."),
                (48, 650, 12, "R", "Outro parágrafo."),
            ],
            reverse=True,
        )
        paragraphs = document.findall(".//w:body/w:p", NS)
        self.assertEqual(
            ["".join(p.itertext()) for p in paragraphs],
            ["Normal negrito itálico normal. Ambos fim.", "Outro parágrafo."],
        )
        self.assert_styles(
            paragraphs[0],
            [
                ("Normal", False, False),
                ("negrito", True, False),
                ("itálico", False, True),
                ("normal.", False, False),
                ("Ambos", True, True),
                ("fim.", False, False),
            ],
        )
        self.assert_styles(paragraphs[1], [("Outro parágrafo.", False, False)])

    def test_large_regular_text_does_not_gain_bold(self):
        document = self.convert(
            [
                (48, 720, 24, "R", "Título normal"),
                (48, 650, 12, "R", "Corpo normal"),
                (48, 620, 12, "R", "Mais texto"),
            ]
        )
        self.assertIsNone(document.find(".//w:b", NS))
        self.assertIsNone(document.find(".//w:i", NS))

    def test_unknown_font_metadata_stays_normal(self):
        with (
            patch.object(pdfium.PdfFont, "get_base_name", return_value=""),
            patch.object(pdfium.PdfFont, "get_weight", return_value=0),
        ):
            document = self.convert(
                [(48, 720, 12, "B", "Indeterminado"), (148, 720, 12, "R", "normal")]
            )
        self.assertIsNone(document.find(".//w:b", NS))
        self.assertIsNone(document.find(".//w:i", NS))

    def test_unavailable_metadata_stays_normal(self):
        with (
            patch.object(
                pdfium.PdfFont, "get_base_name", side_effect=pdfium.PdfiumError("name")
            ),
            patch.object(
                pdfium.PdfFont, "get_weight", side_effect=pdfium.PdfiumError("weight")
            ),
        ):
            document = self.convert([(48, 720, 12, "BI", "Indeterminado")])
        self.assertEqual(validate(self.output)["text"], "Indeterminado")
        self.assertIsNone(document.find(".//w:b", NS))
        self.assertIsNone(document.find(".//w:i", NS))

    def test_weight_identifies_bold_when_name_is_unavailable(self):
        with (
            patch.object(
                pdfium.PdfFont, "get_base_name", side_effect=pdfium.PdfiumError("name")
            ),
            patch.object(pdfium.PdfFont, "get_weight", return_value=700),
        ):
            document = self.convert([(48, 720, 12, "B", "Negrito")])
        self.assert_styles(
            document.find(".//w:body/w:p", NS), [("Negrito", True, False)]
        )

    def test_missing_weight_keeps_identifiable_name_styles(self):
        with patch.object(
            pdfium.PdfFont,
            "get_weight",
            side_effect=pdfium.PdfiumError("weight unavailable"),
        ):
            document = self.convert(
                [(48, 720, 12, "BI", "Ambos"), (100, 720, 12, "R", "normal")]
            )
        self.assert_styles(
            document.find(".//w:body/w:p", NS),
            [("Ambos", True, True), ("normal", False, False)],
        )

    def test_fragment_sizes_and_wide_gap_tab_are_preserved(self):
        document = self.convert(
            [(48, 720, 12, "B", "Negrito"), (240, 720, 14, "I", "itálico")]
        )
        paragraph = document.find(".//w:body/w:p", NS)
        self.assertEqual(
            "".join(run_content(r) for r in paragraph.findall("w:r", NS)),
            "Negrito \titálico",
        )
        self.assert_styles(
            paragraph, [("Negrito", True, False), ("itálico", False, True)]
        )
        self.assertEqual(
            [s.get(q("w:val")) for s in paragraph.findall("w:r/w:rPr/w:sz", NS)],
            ["24", "28"],
        )

    def test_identical_adjacent_styles_share_one_run(self):
        blocks = [
            service._Block("x", 48 + i / 100, 720, 49 + i / 100, 732)
            for i in range(service.MAX_PAGE_OBJECTS)
        ]
        lines = service._reading_lines(blocks)
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(lines[0].runs), 1)
        self.assertEqual(lines[0].runs[0].text, " ".join("x" for _ in blocks))

    def test_run_budget_preserves_previous_output_and_cleans_temporary(self):
        make_styled_pdf(
            self.source,
            [(48, 720, 12, "B", "Negrito"), (100, 720, 12, "R", "normal")],
        )
        before = self.source.read_bytes()
        self.output.write_bytes(b"previous")
        with patch.object(service, "MAX_TEXT_RUNS", 1):
            with self.assertRaises(service.PdfToDocxError) as raised:
                service.PdfToDocxService().convert(
                    self.source, self.output, overwrite=True
                )
        self.assertEqual(raised.exception.code, service.DocxErrorCode.RESOURCE_LIMIT)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.output.read_bytes(), b"previous")
        self.assertFalse(list(self.root.glob(".edudownloader-word-*")))


if __name__ == "__main__":
    unittest.main()
