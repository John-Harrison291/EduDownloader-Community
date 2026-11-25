"""Known geometry and editable structures, using only existing test dependencies."""

from pathlib import Path
from io import BytesIO
import tempfile
from threading import Event
import unittest
from unittest.mock import patch, Mock
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import docx_writer as w
import pdf_to_docx as service
from tests.test_pdf_to_docx_styles import make_styled_pdf


def advanced_pdf(path, *, lines=None, paths=(), image=False, times=False):
    make_styled_pdf(
        path, lines or [(48, 770, 20, "B", "Atividade de estudo")], image=image
    )
    writer = PdfWriter(clone_from=PdfReader(path))
    page = writer.pages[0]
    stream = page.get_contents().get_data()
    if times:
        page["/Resources"]["/Font"][NameObject("/T")] = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Times-Roman"),
                    NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
                }
            )
        )
        stream += b"\nBT /T 12 Tf 0.2 0.4 0.7 rg 1 0 0 1 48 700 Tm (Fonte em cor) Tj ET"
    for command in paths:
        stream += b"\n" + command.encode("ascii")
    content = DecodedStreamObject()
    content.set_data(stream)
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(path)
    writer.close()


def grid_pdf(path, *, merged=False, heading=True):
    xs, ys = (48, 178, 308), (720, 685, 650, 615)
    lines = [(48, 770, 20, "B", "Tabela editável")] if heading else []
    for r in range(3):
        for c in range(2):
            if merged and ((r == 0 and c == 1) or (r == 2 and c == 0)):
                continue
            lines.append((xs[c] + 6, ys[r] - 22, 11, "R", f"L{r + 1}C{c + 1}"))
    commands = [f"{xs[0]} {y} m {xs[-1]} {y} l S" for y in ys]
    if merged:
        commands[2] = f"{xs[1]} {ys[2]} m {xs[-1]} {ys[2]} l S"
    commands += [
        f"{x} {ys[-1]} m {x} {ys[1] if merged and x == xs[1] else ys[0]} l S"
        for x in xs
    ]
    advanced_pdf(path, lines=lines, paths=commands)


class AdvancedConversionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="goal5-advanced-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.source = self.directory / "Atividade ação.pdf"
        self.output = self.directory / "Editável 你好.docx"
        self.runtime = Mock(available=lambda: False)

    def convert(self):
        before = self.source.read_bytes()
        service.PdfToDocxService(self.runtime).convert(self.source, self.output)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(list(self.directory.glob(".edudownloader-word-*")))
        w.validate(self.output)
        with zipfile.ZipFile(self.output) as archive:
            return ET.fromstring(archive.read("word/document.xml"))

    def test_ruled_table_cells_are_native_and_in_reading_order(self):
        grid_pdf(self.source)
        root = self.convert()
        rows = root.findall(".//w:tbl/w:tr", w.NS)
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [
                ["".join(c.itertext()) for c in row.findall("w:tc", w.NS)]
                for row in rows
            ],
            [["L1C1", "L1C2"], ["L2C1", "L2C2"], ["L3C1", "L3C2"]],
        )
        self.assertEqual(len(root.findall(".//wp:inline", w.NS)), 0)

    def test_horizontal_and_vertical_merges_keep_text_once(self):
        grid_pdf(self.source, merged=True)
        root = self.convert()
        self.assertEqual(root.find(".//w:gridSpan", w.NS).get(w.q("w:val")), "2")
        self.assertEqual(
            [node.get(w.q("w:val")) for node in root.findall(".//w:vMerge", w.NS)],
            ["restart", "continue"],
        )
        for value in ("L1C1", "L2C1", "L2C2", "L3C2"):
            self.assertEqual("".join(root.itertext()).count(value), 1)

    def test_columns_use_sections_and_left_column_precedes_right(self):
        lines = [(48, 780, 20, "B", "Título das duas colunas")]
        lines += [
            (x, 730 - r * 24, 11, "R", f"{label} conteúdo {r + 1}.")
            for x, label in ((48, "ESQUERDA"), (320, "DIREITA"))
            for r in range(5)
        ]
        advanced_pdf(self.source, lines=lines)
        root = self.convert()
        self.assertIsNotNone(root.find(".//w:cols[@w:num='2']", w.NS))
        text = "".join(root.itertext())
        self.assertLess(
            text.index("ESQUERDA conteúdo 5"), text.index("DIREITA conteúdo 1")
        )
        self.assertEqual(
            root.find("w:body/w:sectPr/w:type", w.NS).get(w.q("w:val")), "continuous"
        )

    def test_paragraphs_join_hyphenated_lines_and_preserve_independent_indent(self):
        advanced_pdf(
            self.source,
            lines=[
                (48, 750, 12, "R", "Uma explica-"),
                (48, 734, 12, "R", "ção natural para a atividade."),
                (68, 680, 12, "R", "Outro parágrafo independente."),
            ],
        )
        root = self.convert()
        paragraphs = root.findall("w:body/w:p", w.NS)
        self.assertEqual(len(paragraphs), 2)
        self.assertIn("explicação natural", "".join(paragraphs[0].itertext()))
        self.assertGreater(
            int(paragraphs[1].find("w:pPr/w:ind", w.NS).get(w.q("w:left"))), 0
        )

    def test_font_color_and_underlining_remain_run_properties(self):
        advanced_pdf(self.source, times=True, paths=["48 697 m 110 697 l S"])
        root = self.convert()
        self.assertIn(
            "Times New Roman",
            {n.get(w.q("w:ascii")) for n in root.findall(".//w:rFonts", w.NS)},
        )
        self.assertIsNotNone(root.find(".//w:color", w.NS))
        self.assertIsNotNone(root.find(".//w:u", w.NS))

    def test_transformed_text_uses_page_font_size_instead_of_unscaled_tf(self):
        advanced_pdf(
            self.source, lines=[(64, 900, 16, "R", "Texto com escala de navegador.")]
        )
        writer = PdfWriter(clone_from=PdfReader(self.source))
        page = writer.pages[0]
        stream = DecodedStreamObject()
        stream.set_data(
            b"q 0.75 0 0 0.75 0 0 cm\n" + page.get_contents().get_data() + b"\nQ"
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.write(self.source)
        writer.close()
        root = self.convert()
        sizes = {
            int(n.get(w.q("w:val"))) for n in root.findall(".//w:r/w:rPr/w:sz", w.NS)
        }
        self.assertEqual(sizes, {24})
        self.assertIn("Texto com escala de navegador.", "".join(root.itertext()))

    def test_picture_above_text_controls_top_margin_and_keeps_aspect_ratio(self):
        advanced_pdf(
            self.source,
            lines=[(48, 100, 12, "R", "Texto depois da figura.")],
            image=True,
        )
        writer = PdfWriter(clone_from=PdfReader(self.source))
        page = writer.pages[0]
        stream = DecodedStreamObject()
        stream.set_data(
            page.get_contents().get_data().replace(b"48 462 cm", b"48 700 cm")
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.write(self.source)
        writer.close()
        root = self.convert()
        self.assertLessEqual(
            int(root.find(".//w:pgMar", w.NS).get(w.q("w:top"))), 24 * 20
        )
        image = root.find(".//wp:extent", w.NS)
        self.assertAlmostEqual(int(image.get("cx")) / int(image.get("cy")), 2)
        self.assertIn("Texto depois da figura.", "".join(root.itertext()))

    def test_plain_paragraphs_never_become_a_table(self):
        advanced_pdf(
            self.source,
            lines=[
                (48, 750 - r * 30, 12, "R", "Texto contínuo de um parágrafo comum.")
                for r in range(8)
            ],
        )
        root = self.convert()
        self.assertEqual(root.findall(".//w:tbl", w.NS), [])
        self.assertEqual(root.findall(".//w:cols", w.NS), [])

    def test_vector_illustration_is_cropped_without_rasterizing_text(self):
        advanced_pdf(
            self.source,
            lines=[
                (48, 760, 18, "B", "Compare o gráfico"),
                (48, 440, 12, "R", "O texto continua editável."),
            ],
            paths=["0.2 0.4 0.8 rg 60 500 45 100 re f", "130 500 45 160 re f"],
        )
        root = self.convert()
        self.assertEqual(len(root.findall(".//wp:inline", w.NS)), 1)
        extent = root.find(".//wp:extent", w.NS)
        self.assertLess(int(extent.get("cx")), 595 * 12700 / 2)
        self.assertIn("O texto continua editável.", "".join(root.itertext()))

    def test_footer_is_native_and_does_not_add_a_large_body_gap(self):
        advanced_pdf(
            self.source,
            lines=[
                (48, 770, 20, "B", "Conteúdo da página"),
                (48, 700, 12, "R", "Um parágrafo editável."),
                (48, 25, 9, "R", "Rodapé controlado"),
            ],
        )
        root = self.convert()
        self.assertIsNotNone(root.find(".//w:footerReference", w.NS))
        with zipfile.ZipFile(self.output) as archive:
            footer = ET.fromstring(archive.read("word/footer1.xml"))
        self.assertIn("Rodapé controlado", "".join(footer.itertext()))
        self.assertNotIn("Rodapé controlado", "".join(root.itertext()))
        # Removing all ordinary body lines must not turn a table's footer back
        # into body content with a page-sized gap.
        grid_pdf(self.source, heading=False)
        writer = PdfWriter(clone_from=PdfReader(self.source))
        page = writer.pages[0]
        stream = DecodedStreamObject()
        stream.set_data(
            page.get_contents().get_data()
            + b"\nBT /R 9 Tf 1 0 0 1 48 25 Tm (Rodape da tabela) Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.write(self.source)
        writer.close()
        self.output = self.output.with_stem("Tabela com rodape")
        root = self.convert()
        self.assertEqual(len(root.findall(".//w:tbl", w.NS)), 1)
        self.assertIsNotNone(root.find(".//w:footerReference", w.NS))
        self.assertNotIn("Rodape da tabela", "".join(root.itertext()))

    def test_footer_can_be_larger_than_dense_table_body_text(self):
        advanced_pdf(
            self.source,
            lines=[
                (
                    48,
                    770 - i * 18,
                    8,
                    "R",
                    "Conteúdo pequeno com muitos caracteres para leitura.",
                )
                for i in range(8)
            ]
            + [(48, 50, 8.5, "R", "Rodapé pequeno"), (48, 25, 11, "R", "Página 1")],
        )
        root = self.convert()
        self.assertIsNotNone(root.find(".//w:footerReference", w.NS))
        self.assertNotIn("Página 1", "".join(root.itertext()))
        self.assertNotIn("Rodapé pequeno", "".join(root.itertext()))

    def test_geometry_and_grid_limits_preserve_previous_output(self):
        grid_pdf(self.source)
        self.output.write_bytes(b"previous")
        for field in ("MAX_GEOMETRY_CHARS", "MAX_GRID_CELLS"):
            with (
                patch("pdf_word_layout." + field, 1),
                self.assertRaises(service.PdfToDocxError) as raised,
            ):
                service.PdfToDocxService().convert(
                    self.source, self.output, overwrite=True
                )
            self.assertEqual(
                raised.exception.code, service.DocxErrorCode.RESOURCE_LIMIT
            )
            self.assertEqual(self.output.read_bytes(), b"previous")

    def test_cancel_during_new_geometry_preserves_output_and_cleans_temporaries(self):
        grid_pdf(self.source)
        self.output.write_bytes(b"previous")
        token = Event()
        from pdf_word_layout import path_segments

        def stop(*args, **kwargs):
            result = path_segments(*args, **kwargs)
            token.set()
            return result

        with (
            patch("pdf_word_layout.path_segments", side_effect=stop),
            self.assertRaises(service.PdfToDocxCancelled),
        ):
            service.PdfToDocxService().convert(
                self.source, self.output, overwrite=True, cancel_event=token
            )
        self.assertEqual(self.output.read_bytes(), b"previous")
        self.assertFalse(list(self.directory.glob(".edudownloader-word-*")))


class AdvancedWriterTests(unittest.TestCase):
    def test_missing_second_page_header_gets_own_empty_story(self):
        parts, _ = w.package_parts(
            [
                w.Page(
                    595,
                    842,
                    (w.Paragraph((w.Run("Página um"),)),),
                    header=(w.Paragraph((w.Run("Cabeçalho exclusivo"),)),),
                ),
                w.Page(842, 595, (w.Paragraph((w.Run("Página dois"),)),)),
            ]
        )
        first = ET.fromstring(parts["word/header1.xml"])
        second = ET.fromstring(parts["word/header2.xml"])
        self.assertIn("Cabeçalho exclusivo", "".join(first.itertext()))
        self.assertEqual("".join(second.itertext()), "")
        root = ET.fromstring(parts["word/document.xml"])
        self.assertEqual(len(root.findall(".//w:headerReference", w.NS)), 2)
        self.assertEqual(
            [n.get(w.q("w:orient")) for n in root.findall(".//w:pgSz", w.NS)],
            ["portrait", "landscape"],
        )

    def test_active_field_in_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "active.docx"
            parts, _ = w.package_parts(
                [
                    w.Page(
                        595,
                        842,
                        (w.Paragraph((w.Run("Corpo"),)),),
                        header=(w.Paragraph((w.Run("Cabeçalho"),)),),
                    )
                ]
            )
            root = ET.fromstring(parts["word/header1.xml"])
            ET.SubElement(
                root[0], w.q("w:fldSimple"), {w.q("w:instr"): "INCLUDETEXT remote"}
            )
            parts["word/header1.xml"] = ET.tostring(
                root, encoding="utf-8", xml_declaration=True
            )
            with output.open("wb") as stream:
                w.save_parts(parts, stream)
            with self.assertRaises(ValueError):
                w.validate(output)

    def test_repeated_picture_reuses_media_but_keeps_unique_drawing_ids(self):
        with tempfile.TemporaryDirectory() as directory, BytesIO() as buffer:
            with Image.new("RGB", (40, 20), "blue") as image:
                image.save(buffer, format="PNG")
            picture = w.Picture(buffer.getvalue(), 80, 40)
            parts, text = w.package_parts(
                [
                    w.Page(
                        595,
                        842,
                        (w.Paragraph((w.Run("Texto editável"),)), picture, picture),
                    )
                ]
            )
            self.assertEqual(
                len([name for name in parts if name.startswith("word/media/")]), 1
            )
            output = Path(directory) / "repeated.docx"
            with output.open("wb") as stream:
                w.save_parts(parts, stream)
            report = w.validate(output, text)
            self.assertEqual(report["images"], 2)
            self.assertEqual(report["unique_images"], 1)
            root = ET.fromstring(parts["word/document.xml"])
            self.assertEqual(
                [n.get("id") for n in root.findall(".//wp:docPr", w.NS)], ["1", "2"]
            )

    def test_header_footer_validation_blocks_external_relationships(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "test.docx"
            parts, text = w.package_parts(
                [
                    w.Page(
                        595,
                        842,
                        (w.Paragraph((w.Run("Corpo"),)),),
                        footer=(w.Paragraph((w.Run("Rodapé"),)),),
                    )
                ]
            )
            with output.open("wb") as stream:
                w.save_parts(parts, stream)
            self.assertEqual(w.validate(output, text)["text"], "CorpoRodapé")
            rel = ET.fromstring(parts["word/_rels/document.xml.rels"])
            rel[0].set("TargetMode", "External")
            parts["word/_rels/document.xml.rels"] = ET.tostring(
                rel, encoding="utf-8", xml_declaration=True
            )
            with output.open("wb") as stream:
                w.save_parts(parts, stream)
            with self.assertRaises(ValueError):
                w.validate(output)

    def test_invalid_table_spans_and_font_geometry_are_rejected(self):
        for block in (
            w.Table((100, 100), ((w.Cell(0, (), colspan=3),),)),
            w.Paragraph((w.Run("texto", font="Unknown remote font"),)),
            w.Paragraph((w.Run("texto"),), before=float("inf")),
        ):
            with self.subTest(block=type(block)), self.assertRaises(ValueError):
                w.package_parts([w.Page(595, 842, (block,))])
