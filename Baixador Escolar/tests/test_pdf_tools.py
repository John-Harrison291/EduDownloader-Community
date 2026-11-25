"""Testes das ferramentas PDF locais, sem abrir Tk ou acessar a rede."""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import tempfile
import unittest
from importlib.metadata import version
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import local_files
import pdf_tools
from packaging.version import Version
from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter

from pdf_tools import (
    _A4_MARGIN_PIXELS,
    _A4_PORTRAIT_PIXELS,
    _calculate_image_layout,
    _image_as_a4_page,
    _images_as_pdf_page,
    _load_normalized_image,
    _rect_to_pixels,
    _validate_images_to_pdf_output,
    PDF_TO_IMAGE_DPI,
    ImagesToPdfProgress,
    InvalidImageError,
    InvalidPageSelectionError,
    InvalidPdfError,
    PdfOperationCancelled,
    PdfOperationProgress,
    PdfToolsError,
    PdfToolsService,
    parse_page_selection,
)
from print_layout import (
    ImagePageLayout,
    MarginPreset,
    Orientation,
    PaperSize,
    PdfImageQuality,
    image_slots,
    page_dimensions,
    raster_dimensions,
)


def write_pdf(path: Path, widths: tuple[int, ...]) -> None:
    writer = PdfWriter()
    try:
        for width in widths:
            writer.add_blank_page(width=width, height=200)
        with path.open("wb") as stream:
            writer.write(stream)
    finally:
        writer.close()


def write_sized_pdf(path: Path, sizes: tuple[tuple[int, int], ...]) -> None:
    writer = PdfWriter()
    try:
        for width, height in sizes:
            writer.add_blank_page(width=width, height=height)
        with path.open("wb") as stream:
            writer.write(stream)
    finally:
        writer.close()


def write_protected_pdf(path: Path) -> None:
    writer = PdfWriter()
    try:
        writer.add_blank_page(width=72, height=72)
        writer.encrypt("senha-somente-para-fixture")
        with path.open("wb") as stream:
            writer.write(stream)
    finally:
        writer.close()


def page_widths(path: Path) -> tuple[int, ...]:
    reader = PdfReader(path)
    return tuple(round(float(page.mediabox.width)) for page in reader.pages)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PageSelectionTests(unittest.TestCase):
    def test_single_range_and_combinations_preserve_human_order(self) -> None:
        self.assertEqual(parse_page_selection("1", 10), (1,))
        self.assertEqual(parse_page_selection("1-3", 10), (1, 2, 3))
        self.assertEqual(parse_page_selection("1,3,5", 10), (1, 3, 5))
        self.assertEqual(
            parse_page_selection("1-3, 5, 8-10", 10),
            (1, 2, 3, 5, 8, 9, 10),
        )

    def test_duplicates_are_intentionally_preserved(self) -> None:
        self.assertEqual(parse_page_selection("2,1,2", 3), (2, 1, 2))

    def test_invalid_zero_missing_page_and_inverted_range_are_rejected(self) -> None:
        for selection in ("", "texto", "1,,2", "0", "0-2", "4", "3-2"):
            with self.subTest(selection=selection):
                with self.assertRaises(InvalidPageSelectionError):
                    parse_page_selection(selection, 3)


class PdfToolsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = PdfToolsService()

    def test_imported_pypdf_meets_both_xref_security_floors(self) -> None:
        installed = Version(version("pypdf"))
        self.assertGreaterEqual(installed, Version("6.21.4"))  # GHSA-5849-834g-hvw5
        self.assertGreaterEqual(installed, Version("7.0.0"))  # GHSA-59jv-x5x2-gg4c

    def test_extracts_pages_from_small_incremental_xref_stream(self) -> None:
        original = self.root / "base.pdf"
        incremental = self.root / "revisão.pdf"
        output = self.root / "extração.pdf"
        write_pdf(original, (80,))
        writer = PdfWriter(original, incremental=True)
        try:
            writer.add_blank_page(width=160, height=120)
            with incremental.open("wb") as stream:
                writer.write(stream)
        finally:
            writer.close()

        payload = incremental.read_bytes()
        self.assertLess(len(payload), 4096)
        self.assertIn(b"/Type /XRef", payload)
        self.service.extract_pages(incremental, "2,1", output)
        self.assertEqual(page_widths(output), (160, 80))
        self.assertEqual(incremental.read_bytes(), payload)

    def test_incomplete_pdf_is_rejected_in_bounded_process(self) -> None:
        source = self.root / "incompleto.pdf"
        write_pdf(source, (80,))
        source.write_bytes(source.read_bytes()[:48])
        probe = (
            "from pdf_tools import PdfToolsService, InvalidPdfError\n"
            "import sys\n"
            "try:\n"
            "    PdfToolsService().page_count(sys.argv[1])\n"
            "except InvalidPdfError:\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(1)\n"
        )

        result = subprocess.run(
            [sys.executable, "-B", "-c", probe, str(source)],
            cwd=Path(pdf_tools.__file__).resolve().parent,
            capture_output=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def write_colored_images(
        self,
        count: int,
        *,
        size: tuple[int, int] = (80, 60),
    ) -> tuple[Path, ...]:
        colors = (
            "red",
            "green",
            "blue",
            "yellow",
            "purple",
            "orange",
            "cyan",
            "magenta",
            "black",
        )
        paths = tuple(self.root / f"imagem-{index:02d}.png" for index in range(count))
        for path, color in zip(paths, colors[:count], strict=True):
            image = Image.new("RGB", size, color)
            try:
                image.save(path, "PNG")
            finally:
                image.close()
        return paths

    def test_pdf_workflows_reject_relative_and_unc_paths_consistently(self) -> None:
        for path in (Path("relativo.pdf"), Path(r"\\servidor\arquivo.pdf")):
            with self.subTest(source=path):
                with (
                    patch.object(Path, "is_file", return_value=True),
                    self.assertRaises(InvalidPdfError),
                ):
                    pdf_tools._validate_pdf_input(path)
        with self.assertRaises(PdfToolsError):
            pdf_tools._validate_output(Path("relativo.pdf"), (), False)
        with self.assertRaises(PdfToolsError):
            pdf_tools._validate_image_output_directory(Path("."))

    def test_merge_two_pdfs_preserves_order_and_originals(self) -> None:
        first = self.root / "primeiro.pdf"
        second = self.root / "segundo.pdf"
        output = self.root / "unido.pdf"
        write_pdf(first, (101, 102))
        write_pdf(second, (201,))
        before = (digest(first), digest(second))

        result = self.service.merge_pdfs((first, second), output)

        self.assertEqual(result.output_path, output)
        self.assertEqual(result.page_count, 3)
        self.assertEqual(page_widths(output), (101, 102, 201))
        self.assertEqual((digest(first), digest(second)), before)

    def test_merge_multiple_pdfs_supports_spaces_and_unicode_paths(self) -> None:
        directory = self.root / "Pasta com espaços e acentuação"
        directory.mkdir()
        inputs = tuple(
            directory / name for name in ("ação 1.pdf", "lição 2.pdf", "mês 3.pdf")
        )
        for index, path in enumerate(inputs, start=1):
            write_pdf(path, (index * 100,))
        output = directory / "resultado final.pdf"

        self.service.merge_pdfs(inputs, output)

        self.assertEqual(page_widths(output), (100, 200, 300))

    def test_merge_requires_two_inputs_and_rejects_invalid_pdf(self) -> None:
        valid = self.root / "válido.pdf"
        invalid = self.root / "inválido.pdf"
        write_pdf(valid, (100,))
        invalid.write_text("não é PDF", encoding="utf-8")

        with self.assertRaises(PdfToolsError):
            self.service.merge_pdfs((valid,), self.root / "poucos.pdf")
        with self.assertRaises(InvalidPdfError):
            self.service.merge_pdfs((valid, invalid), self.root / "falha.pdf")
        self.assertFalse((self.root / "falha.pdf").exists())

    def test_output_cannot_be_an_input_or_replace_without_permission(self) -> None:
        first = self.root / "um.pdf"
        second = self.root / "dois.pdf"
        existing = self.root / "existente.pdf"
        write_pdf(first, (100,))
        write_pdf(second, (200,))
        write_pdf(existing, (300,))
        existing_before = digest(existing)

        with self.assertRaises(PdfToolsError):
            self.service.merge_pdfs((first, second), first, overwrite=True)
        with self.assertRaises(PdfToolsError):
            self.service.merge_pdfs((first, second), existing)

        self.assertEqual(digest(existing), existing_before)

    def test_output_hard_link_to_input_cannot_replace_source(self) -> None:
        first = self.root / "primeiro.pdf"
        second = self.root / "segundo.pdf"
        alias = self.root / "alias.pdf"
        write_pdf(first, (100,))
        write_pdf(second, (200,))
        try:
            alias.hardlink_to(first)
        except OSError as error:
            self.skipTest(f"Hard link indisponível: {type(error).__name__}")
        original = digest(first)

        with self.assertRaises(PdfToolsError):
            self.service.merge_pdfs((first, second), alias, overwrite=True)

        self.assertEqual(digest(first), original)
        self.assertEqual(digest(alias), original)

    def test_explicit_overwrite_replaces_only_with_complete_result(self) -> None:
        first = self.root / "um.pdf"
        second = self.root / "dois.pdf"
        output = self.root / "existente.pdf"
        write_pdf(first, (100,))
        write_pdf(second, (200,))
        write_pdf(output, (300,))

        result = self.service.merge_pdfs((first, second), output, overwrite=True)

        self.assertEqual(result.page_count, 2)
        self.assertEqual(page_widths(output), (100, 200))
        self.assertEqual(list(self.root.glob(".*.tmp.pdf")), [])

    def test_extract_single_range_combination_and_duplicates(self) -> None:
        source = self.root / "origem.pdf"
        write_pdf(source, (100, 200, 300, 400, 500))
        cases = {
            "2": (200,),
            "2-4": (200, 300, 400),
            "1,3-4,2": (100, 300, 400, 200),
            "3,1,3": (300, 100, 300),
        }
        for index, (selection, expected) in enumerate(cases.items()):
            with self.subTest(selection=selection):
                output = self.root / f"extraído-{index}.pdf"
                result = self.service.extract_pages(source, selection, output)
                self.assertEqual(result.page_count, len(expected))
                self.assertEqual(page_widths(output), expected)

    def test_extract_rejects_invalid_selection_and_document(self) -> None:
        source = self.root / "origem.pdf"
        invalid = self.root / "corrompido.pdf"
        write_pdf(source, (100, 200))
        invalid.write_bytes(b"%PDF-incompleto")

        for selection in ("0", "3", "2-1", "1;x"):
            with self.subTest(selection=selection):
                with self.assertRaises(InvalidPageSelectionError):
                    self.service.extract_pages(
                        source,
                        selection,
                        self.root / f"erro-{selection.replace(';', '-')}.pdf",
                    )
        with self.assertRaises(InvalidPdfError):
            self.service.extract_pages(invalid, "1", self.root / "erro.pdf")

    def test_page_count_validates_the_document(self) -> None:
        source = self.root / "três páginas.pdf"
        write_pdf(source, (100, 200, 300))
        self.assertEqual(self.service.page_count(source), 3)

        invalid = self.root / "texto.pdf"
        invalid.write_text("inválido", encoding="utf-8")
        with self.assertRaises(InvalidPdfError):
            self.service.page_count(invalid)

    def test_invalid_pdf_does_not_log_document_content_or_path(self) -> None:
        marker = "CONTEUDO-PRIVADO-PDF-092"
        invalid = self.root / "perfil pessoal" / "documento.pdf"
        invalid.parent.mkdir()
        invalid.write_text(marker, encoding="utf-8")
        records: list[str] = []

        class Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record.getMessage())

        handler = Capture()
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            with self.assertRaises(InvalidPdfError):
                self.service.page_count(invalid)
        finally:
            root_logger.removeHandler(handler)

        rendered = "\n".join(records)
        self.assertNotIn(marker, rendered)
        self.assertNotIn(str(invalid), rendered)

    def test_images_to_pdf_supports_jpg_rgb_png_rgba_palette_and_order(self) -> None:
        landscape = self.root / "foto ampla.jpg"
        portrait = self.root / "imagem com transparência.png"
        palette = self.root / "paleta.png"
        Image.new("RGB", (400, 200), "red").save(landscape, "JPEG")
        Image.new("RGBA", (200, 400), (0, 0, 255, 80)).save(portrait, "PNG")
        palette_image = Image.new("P", (120, 240))
        palette_image.putpalette([0, 255, 0] * 256)
        palette_image.save(palette, "PNG")
        output = self.root / "imagens.pdf"
        before = tuple(digest(path) for path in (landscape, portrait, palette))

        result = self.service.images_to_pdf((landscape, portrait, palette), output)

        reader = PdfReader(output)
        self.assertEqual(result.page_count, 3)
        self.assertEqual(len(reader.pages), 3)
        self.assertGreater(
            float(reader.pages[0].mediabox.width),
            float(reader.pages[0].mediabox.height),
        )
        self.assertLess(
            float(reader.pages[1].mediabox.width),
            float(reader.pages[1].mediabox.height),
        )
        self.assertEqual(
            tuple(digest(path) for path in (landscape, portrait, palette)), before
        )

    def test_small_square_portrait_and_landscape_images_fill_useful_area(self) -> None:
        cases = (
            ((100, 100), _A4_PORTRAIT_PIXELS, (1062, 1062)),
            ((100, 200), _A4_PORTRAIT_PIXELS, (788, 1576)),
            ((200, 100), tuple(reversed(_A4_PORTRAIT_PIXELS)), (1576, 788)),
        )
        for image_size, page_size, expected_size in cases:
            with self.subTest(image_size=image_size):
                fitted_size, position = _calculate_image_layout(image_size, page_size)
                maximum = tuple(
                    dimension - 2 * _A4_MARGIN_PIXELS for dimension in page_size
                )

                self.assertEqual(fitted_size, expected_size)
                self.assertGreater(fitted_size[0], image_size[0])
                self.assertGreater(fitted_size[1], image_size[1])
                self.assertTrue(
                    fitted_size[0] == maximum[0] or fitted_size[1] == maximum[1]
                )
                self.assertLessEqual(fitted_size[0], maximum[0])
                self.assertLessEqual(fitted_size[1], maximum[1])
                self.assertEqual(position[0], (page_size[0] - fitted_size[0]) // 2)
                self.assertEqual(position[1], (page_size[1] - fitted_size[1]) // 2)
                self.assertEqual(
                    fitted_size[0] * image_size[1],
                    fitted_size[1] * image_size[0],
                )

    def test_large_image_is_reduced_proportionally_within_landscape_page(self) -> None:
        image_size = (4000, 2000)
        page_size = tuple(reversed(_A4_PORTRAIT_PIXELS))

        fitted_size, position = _calculate_image_layout(image_size, page_size)

        self.assertEqual(fitted_size, (1576, 788))
        self.assertLess(fitted_size[0], image_size[0])
        self.assertLess(fitted_size[1], image_size[1])
        self.assertEqual(fitted_size[0] * image_size[1], fitted_size[1] * image_size[0])
        self.assertEqual(position, (89, 226))

    def test_rendered_small_images_are_enlarged_centered_and_auto_oriented(
        self,
    ) -> None:
        cases = (
            ("retrato pequeno.png", (100, 200), _A4_PORTRAIT_PIXELS),
            (
                "paisagem pequena.png",
                (200, 100),
                tuple(reversed(_A4_PORTRAIT_PIXELS)),
            ),
        )
        for name, image_size, expected_page_size in cases:
            with self.subTest(name=name):
                source = self.root / name
                Image.new("RGB", image_size, "red").save(source, "PNG")
                before = digest(source)
                expected_size, expected_position = _calculate_image_layout(
                    image_size, expected_page_size
                )

                page = _image_as_a4_page(source)
                try:
                    white = Image.new("RGB", page.size, "white")
                    try:
                        content_box = ImageChops.difference(page, white).getbbox()
                    finally:
                        white.close()
                    self.assertEqual(page.size, expected_page_size)
                    self.assertEqual(
                        content_box,
                        (
                            expected_position[0],
                            expected_position[1],
                            expected_position[0] + expected_size[0],
                            expected_position[1] + expected_size[1],
                        ),
                    )
                finally:
                    page.close()
                self.assertEqual(digest(source), before)

    def test_images_to_pdf_supports_one_image_and_unicode_output(self) -> None:
        image = self.root / "ação única.png"
        output = self.root / "resultado com espaços.pdf"
        Image.new("RGB", (80, 60), "white").save(image, "PNG")
        before = digest(image)

        result = self.service.images_to_pdf((image,), output)

        self.assertEqual(result.page_count, 1)
        self.assertEqual(len(PdfReader(output).pages), 1)
        self.assertEqual(digest(image), before)

    def test_images_to_pdf_rejects_missing_or_invalid_image(self) -> None:
        with self.assertRaises(PdfToolsError):
            self.service.images_to_pdf((), self.root / "vazio.pdf")

        invalid = self.root / "quebrada.png"
        invalid.write_bytes(b"not-an-image")
        with self.assertRaises(InvalidImageError):
            self.service.images_to_pdf((invalid,), self.root / "falha.pdf")
        self.assertFalse((self.root / "falha.pdf").exists())

    def test_images_to_pdf_default_contract_preserves_historical_fundamentals(
        self,
    ) -> None:
        portrait, landscape = self.write_colored_images(2, size=(80, 120))
        landscape_image = Image.new("RGB", (120, 80), "blue")
        try:
            landscape_image.save(landscape, "PNG")
        finally:
            landscape_image.close()
        output = self.root / "default.pdf"

        result = self.service.images_to_pdf((portrait, landscape), output)

        reader = PdfReader(output)
        self.assertEqual(result.page_count, 2)
        self.assertEqual(len(reader.pages), 2)
        expected_portrait = page_dimensions(PaperSize.A4, Orientation.PORTRAIT)
        expected_landscape = page_dimensions(PaperSize.A4, Orientation.LANDSCAPE)
        self.assertAlmostEqual(
            float(reader.pages[0].mediabox.width), expected_portrait.width, delta=1
        )
        self.assertAlmostEqual(
            float(reader.pages[0].mediabox.height), expected_portrait.height, delta=1
        )
        self.assertAlmostEqual(
            float(reader.pages[1].mediabox.width), expected_landscape.width, delta=1
        )
        self.assertAlmostEqual(
            float(reader.pages[1].mediabox.height), expected_landscape.height, delta=1
        )

    def test_images_to_pdf_supports_paper_orientation_and_margin_contracts(
        self,
    ) -> None:
        (source,) = self.write_colored_images(1, size=(120, 80))
        for paper in (PaperSize.A4, PaperSize.LETTER):
            for orientation in (Orientation.PORTRAIT, Orientation.LANDSCAPE):
                for margin in MarginPreset:
                    with self.subTest(
                        paper=paper,
                        orientation=orientation,
                        margin=margin,
                    ):
                        layout = ImagePageLayout(
                            paper=paper,
                            orientation=orientation,
                            margin=margin,
                        )
                        page = _images_as_pdf_page((source,), layout)
                        try:
                            self.assertEqual(
                                page.size,
                                raster_dimensions(
                                    page_dimensions(paper, orientation),
                                    150,
                                ),
                            )
                            slot = _rect_to_pixels(
                                image_slots(paper, orientation, margin, 1)[0],
                                page.size,
                            )
                            white = Image.new("RGB", page.size, "white")
                            difference = ImageChops.difference(page, white)
                            try:
                                content_box = difference.getbbox()
                            finally:
                                difference.close()
                                white.close()
                            self.assertIsNotNone(content_box)
                            assert content_box is not None
                            self.assertGreaterEqual(content_box[0], round(slot.x))
                            self.assertGreaterEqual(content_box[1], round(slot.y))
                            self.assertLessEqual(
                                content_box[2], round(slot.x + slot.width)
                            )
                            self.assertLessEqual(
                                content_box[3], round(slot.y + slot.height)
                            )
                        finally:
                            page.close()

        output = self.root / "carta-paisagem.pdf"
        result = self.service.images_to_pdf(
            (source,),
            output,
            layout=ImagePageLayout(
                paper=PaperSize.LETTER,
                orientation=Orientation.LANDSCAPE,
                margin=MarginPreset.NONE,
            ),
        )
        generated = PdfReader(output).pages[0]
        self.assertEqual(result.page_count, 1)
        self.assertAlmostEqual(float(generated.mediabox.width), 792, delta=1)
        self.assertAlmostEqual(float(generated.mediabox.height), 612, delta=1)

    def test_two_and_four_per_page_preserve_counts_partial_pages_and_order(
        self,
    ) -> None:
        inputs = self.write_colored_images(9)
        varied_sizes = ((60, 120), (120, 60), (80, 80), (300, 50))
        varied_colors = ("red", "green", "blue", "yellow")
        for path, size, color in zip(
            inputs[:4], varied_sizes, varied_colors, strict=True
        ):
            image = Image.new("RGB", size, color)
            try:
                image.save(path, "PNG")
            finally:
                image.close()
        cases = (
            (2, (1, 2, 3, 5), (1, 1, 2, 3)),
            (4, (1, 4, 5, 8, 9), (1, 1, 2, 2, 3)),
        )
        for per_page, counts, expected_pages in cases:
            for count, expected in zip(counts, expected_pages, strict=True):
                with self.subTest(per_page=per_page, count=count):
                    output = self.root / f"grid-{per_page}-{count}.pdf"
                    result = self.service.images_to_pdf(
                        inputs[:count],
                        output,
                        layout=ImagePageLayout(
                            orientation=Orientation.PORTRAIT,
                            images_per_page=per_page,
                        ),
                    )
                    self.assertEqual(result.page_count, expected)
                    self.assertEqual(len(PdfReader(output).pages), expected)

        colors = ((255, 0, 0), (0, 128, 0), (0, 0, 255), (255, 255, 0))
        layout = ImagePageLayout(
            orientation=Orientation.PORTRAIT,
            images_per_page=4,
        )
        page = _images_as_pdf_page(inputs[:4], layout)
        try:
            slots = tuple(
                _rect_to_pixels(slot, page.size)
                for slot in image_slots(
                    PaperSize.A4,
                    Orientation.PORTRAIT,
                    MarginPreset.NORMAL,
                    4,
                )
            )
            for slot, expected_color in zip(slots, colors, strict=True):
                center = (
                    round(slot.x + slot.width / 2),
                    round(slot.y + slot.height / 2),
                )
                self.assertEqual(page.getpixel(center), expected_color)
        finally:
            page.close()

        partial = _images_as_pdf_page(inputs[4:5], layout)
        try:
            partial_slots = tuple(
                _rect_to_pixels(slot, partial.size)
                for slot in image_slots(
                    PaperSize.A4,
                    Orientation.PORTRAIT,
                    MarginPreset.NORMAL,
                    4,
                )
            )
            self.assertNotEqual(
                partial.getpixel(
                    (
                        round(partial_slots[0].x + partial_slots[0].width / 2),
                        round(partial_slots[0].y + partial_slots[0].height / 2),
                    )
                ),
                (255, 255, 255),
            )
            for slot in partial_slots[1:]:
                self.assertEqual(
                    partial.getpixel(
                        (
                            round(slot.x + slot.width / 2),
                            round(slot.y + slot.height / 2),
                        )
                    ),
                    (255, 255, 255),
                )
        finally:
            partial.close()

    def test_auto_orientation_uses_print_layout_result_per_group(self) -> None:
        inputs = self.write_colored_images(4, size=(60, 120))
        layout = ImagePageLayout(images_per_page=2)
        with patch(
            "pdf_tools.choose_image_page_orientation",
            side_effect=(Orientation.LANDSCAPE, Orientation.PORTRAIT),
        ) as chooser:
            output = self.root / "orientação por grupo.pdf"
            self.service.images_to_pdf(inputs, output, layout=layout)

        pages = PdfReader(output).pages
        self.assertEqual(chooser.call_count, 2)
        self.assertGreater(
            float(pages[0].mediabox.width), float(pages[0].mediabox.height)
        )
        self.assertLess(float(pages[1].mediabox.width), float(pages[1].mediabox.height))

    def test_exif_orientation_is_applied_before_auto_layout(self) -> None:
        source = self.root / "orientação exif.jpg"
        image = Image.new("RGB", (40, 80), "red")
        exif = image.getexif()
        exif[274] = 6
        image.save(source, "JPEG", exif=exif)
        image.close()
        output = self.root / "exif.pdf"

        normalized = _load_normalized_image(source)
        try:
            self.assertEqual(normalized.size, (80, 40))
        finally:
            normalized.close()
        self.service.images_to_pdf((source,), output)
        page = PdfReader(output).pages[0]
        self.assertGreater(float(page.mediabox.width), float(page.mediabox.height))

    def test_images_to_pdf_rejects_unsafe_paths_and_oversized_images_early(
        self,
    ) -> None:
        (source,) = self.write_colored_images(1)
        with self.assertRaises(InvalidImageError):
            self.service.images_to_pdf((Path("relativa.png"),), self.root / "a.pdf")
        with self.assertRaises(InvalidImageError):
            self.service.images_to_pdf(
                (r"\\servidor\materiais\imagem.png",),
                self.root / "b.pdf",
            )
        with self.assertRaises(PdfToolsError):
            self.service.images_to_pdf((source,), Path("relativo.pdf"))
        with self.assertRaises(PdfToolsError):
            self.service.images_to_pdf(
                (source,),
                r"\\servidor\materiais\resultado.pdf",
            )
        with self.assertRaises(PdfToolsError):
            self.service.images_to_pdf((source,), self.root / "resultado.txt")
        identity = self.root / "Mesmo.PDF"
        with self.assertRaises(PdfToolsError):
            _validate_images_to_pdf_output(identity, (identity,), True)
        with self.assertRaises(PdfToolsError):
            _validate_images_to_pdf_output(
                Path(str(identity).swapcase()),
                (identity,),
                True,
            )
        with self.assertRaises(PdfToolsError):
            self.service.images_to_pdf(
                (source,),
                self.root / "configuração.pdf",
                layout="inválido",  # type: ignore[arg-type]
            )

        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.__exit__.return_value = False
        fake.format = "PNG"
        fake.width = 10_001
        fake.height = 8_000
        with (
            patch("pdf_tools.Image.open", return_value=fake),
            self.assertRaises(InvalidImageError),
        ):
            _load_normalized_image(source)
        fake.load.assert_not_called()

        with self.assertRaisesRegex(PdfToolsError, "limite seguro de páginas"):
            self.service.images_to_pdf(
                (source,) * 501,
                self.root / "páginas-demais.pdf",
            )
        self.assertFalse((self.root / "páginas-demais.pdf").exists())

        invalid_event = MagicMock()
        invalid_event.is_set.side_effect = RuntimeError("falha interna")
        with self.assertRaisesRegex(PdfToolsError, "cancelamento"):
            self.service.images_to_pdf(
                (source,),
                self.root / "evento-inválido.pdf",
                cancel_event=invalid_event,
            )

    def test_images_to_pdf_rejects_reparse_access_denied_and_removed_input(
        self,
    ) -> None:
        (source,) = self.write_colored_images(1)
        actual = source.stat()
        reparse = SimpleNamespace(
            st_mode=actual.st_mode,
            st_file_attributes=local_files._FILE_ATTRIBUTE_REPARSE_POINT,
        )
        with (
            patch("local_files.os.stat", return_value=reparse),
            self.assertRaises(InvalidImageError),
        ):
            self.service.images_to_pdf((source,), self.root / "reparse.pdf")
        with (
            patch("local_files.os.stat", side_effect=PermissionError),
            self.assertRaises(InvalidImageError),
        ):
            self.service.images_to_pdf((source,), self.root / "negado.pdf")

        real_loader = pdf_tools._load_normalized_image

        def remove_then_load(path: Path) -> Image.Image:
            path.unlink()
            return real_loader(path)

        with (
            patch("pdf_tools._load_normalized_image", side_effect=remove_then_load),
            self.assertRaises(InvalidImageError),
        ):
            self.service.images_to_pdf((source,), self.root / "removido.pdf")
        self.assertFalse((self.root / "removido.pdf").exists())

    def test_images_to_pdf_cancellation_is_atomic_at_three_checkpoints(self) -> None:
        inputs = self.write_colored_images(5)
        layout = ImagePageLayout(images_per_page=2)
        for cancel_after in (0, 1, 3):
            with self.subTest(cancel_after=cancel_after):
                output = self.root / f"cancelado-{cancel_after}.pdf"
                write_pdf(output, (321,))
                before = digest(output)
                event = Event()
                if cancel_after == 0:
                    event.set()

                def update(progress: ImagesToPdfProgress) -> None:
                    if progress.completed_pages == cancel_after:
                        event.set()

                with self.assertRaises(PdfOperationCancelled):
                    self.service.images_to_pdf(
                        inputs,
                        output,
                        overwrite=True,
                        layout=layout,
                        cancel_event=event,
                        progress=update,
                    )
                self.assertEqual(digest(output), before)
                self.assertEqual(list(self.root.glob(".*.tmp.pdf")), [])

    def test_images_to_pdf_progress_is_monotonic_bounded_and_not_spammy(self) -> None:
        inputs = self.write_colored_images(5)
        updates: list[ImagesToPdfProgress] = []
        output = self.root / "progresso.pdf"

        result = self.service.images_to_pdf(
            inputs,
            output,
            layout=ImagePageLayout(images_per_page=2),
            progress=updates.append,
        )

        self.assertEqual(result.page_count, 3)
        self.assertEqual(
            updates,
            [ImagesToPdfProgress(index, 3) for index in range(4)],
        )
        self.assertTrue(
            all(current.completed_pages <= current.total_pages for current in updates)
        )

    def test_images_to_pdf_processes_groups_incrementally_and_closes_handles(
        self,
    ) -> None:
        inputs = self.write_colored_images(5)
        output = self.root / "incremental.pdf"
        real_loader = pdf_tools._load_normalized_image
        loaded: list[Image.Image] = []
        call_count = 0

        def tracked_loader(path: Path) -> Image.Image:
            nonlocal call_count
            if call_count and call_count % 2 == 0:
                for prior in loaded:
                    with self.assertRaises(ValueError):
                        prior.load()
                loaded.clear()
            image = real_loader(path)
            loaded.append(image)
            call_count += 1
            return image

        with patch("pdf_tools._load_normalized_image", side_effect=tracked_loader):
            result = self.service.images_to_pdf(
                inputs,
                output,
                layout=ImagePageLayout(images_per_page=2),
            )

        self.assertEqual(result.page_count, 3)
        for image in loaded:
            with self.assertRaises(ValueError):
                image.load()
        for source in inputs:
            renamed = source.with_name(f"renomeada-{source.name}")
            source.rename(renamed)
            renamed.unlink()
        self.assertEqual(list(self.root.glob(".*.tmp.pdf")), [])

    def test_images_to_pdf_failure_preserves_existing_output_and_cleans_temp(
        self,
    ) -> None:
        inputs = self.write_colored_images(3)
        output = self.root / "existente-imagens.pdf"
        write_pdf(output, (444,))
        before = digest(output)
        real_append = pdf_tools._append_image_page
        calls = 0

        def fail_second(writer: PdfWriter, page: Image.Image) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PdfToolsError("falha controlada")
            real_append(writer, page)

        with (
            patch("pdf_tools._append_image_page", side_effect=fail_second),
            self.assertRaises(PdfToolsError),
        ):
            self.service.images_to_pdf(
                inputs,
                output,
                overwrite=True,
                layout=ImagePageLayout(images_per_page=2),
            )
        self.assertEqual(digest(output), before)
        self.assertEqual(list(self.root.glob(".*.tmp.pdf")), [])

    def test_pdf_to_png_renders_one_page_at_fixed_150_dpi(self) -> None:
        source = self.root / "atividade.pdf"
        destination = self.root / "imagens"
        destination.mkdir()
        write_sized_pdf(source, ((72, 144),))
        before = digest(source)

        result = self.service.pdf_to_images(source, None, "PNG", destination)

        self.assertEqual(PDF_TO_IMAGE_DPI, 150.0)
        self.assertEqual(result.page_numbers, (1,))
        self.assertEqual(
            tuple(path.name for path in result.output_paths),
            ("atividade-pagina-001.png",),
        )
        with Image.open(result.output_paths[0]) as image:
            image.load()
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (150, 300))
        self.assertEqual(digest(source), before)

    def test_pdf_to_png_all_pages_preserves_order_sizes_and_original_names(
        self,
    ) -> None:
        directory = self.root / "Pasta com espaços e acentuação"
        destination = directory / "saída com espaços"
        destination.mkdir(parents=True)
        source = directory / "lição única.pdf"
        sizes = ((72, 144), (144, 72), (36, 72), (72, 36))
        write_sized_pdf(source, sizes)
        before = digest(source)

        result = self.service.pdf_to_images(source, None, "png", destination)

        self.assertEqual(result.page_numbers, (1, 2, 3, 4))
        self.assertEqual(
            tuple(path.name for path in result.output_paths),
            tuple(f"lição única-pagina-{page:03d}.png" for page in range(1, 5)),
        )
        expected_sizes = ((150, 300), (300, 150), (75, 150), (150, 75))
        for output, expected_size in zip(
            result.output_paths, expected_sizes, strict=True
        ):
            with Image.open(output) as image:
                image.load()
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, expected_size)
        self.assertEqual(digest(source), before)
        self.assertEqual(list(destination.glob(".*.tmp.*")), [])
        self.assertEqual(list(destination.glob(".*.bak.*")), [])

    def test_pdf_to_images_selection_uses_original_page_numbers_and_order(self) -> None:
        source = self.root / "caderno.pdf"
        destination = self.root / "selecionadas"
        destination.mkdir()
        write_sized_pdf(source, ((72, 72),) * 4)

        result = self.service.pdf_to_images(
            source,
            "1-2,4",
            "PNG",
            destination,
        )

        self.assertEqual(result.page_numbers, (1, 2, 4))
        self.assertEqual(
            tuple(path.name for path in result.output_paths),
            (
                "caderno-pagina-001.png",
                "caderno-pagina-002.png",
                "caderno-pagina-004.png",
            ),
        )

        reordered = self.root / "reordenadas"
        reordered.mkdir()
        reordered_result = self.service.pdf_to_images(
            source,
            "4,1,3",
            "PNG",
            reordered,
        )
        self.assertEqual(reordered_result.page_numbers, (4, 1, 3))
        self.assertEqual(
            tuple(path.name for path in reordered_result.output_paths),
            (
                "caderno-pagina-004.png",
                "caderno-pagina-001.png",
                "caderno-pagina-003.png",
            ),
        )

    def test_pdf_to_jpg_is_rgb_with_opaque_white_page_background(self) -> None:
        source = self.root / "folha paisagem.pdf"
        destination = self.root / "jpg"
        destination.mkdir()
        write_sized_pdf(source, ((144, 72),))

        result = self.service.pdf_to_images(source, "1", "JPG", destination)

        with Image.open(result.output_paths[0]) as image:
            image.load()
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (300, 150))
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_pdf_to_images_rejects_invalid_pages_format_document_and_password(
        self,
    ) -> None:
        source = self.root / "origem.pdf"
        corrupt = self.root / "corrompido.pdf"
        protected = self.root / "protegido.pdf"
        destination = self.root / "destino"
        destination.mkdir()
        write_sized_pdf(source, ((72, 72), (72, 72)))
        corrupt.write_bytes(b"%PDF-conteudo-incompleto")
        write_protected_pdf(protected)

        for selection in ("0", "3", "2-1", "1;x", "1,1"):
            with self.subTest(selection=selection):
                with self.assertRaises(InvalidPageSelectionError):
                    self.service.pdf_to_images(source, selection, "PNG", destination)
        with self.assertRaises(PdfToolsError):
            self.service.pdf_to_images(source, None, "WEBP", destination)
        with self.assertRaises(InvalidPdfError):
            self.service.pdf_to_images(corrupt, None, "PNG", destination)
        with self.assertRaisesRegex(InvalidPdfError, "protegido por senha"):
            self.service.pdf_to_images(protected, None, "PNG", destination)
        self.assertEqual(list(destination.iterdir()), [])

    def test_pdf_to_images_detects_conflicts_and_overwrites_only_when_allowed(
        self,
    ) -> None:
        source = self.root / "atividade.pdf"
        destination = self.root / "destino"
        destination.mkdir()
        write_sized_pdf(source, ((72, 72),))
        existing = destination / "atividade-pagina-001.png"
        existing.write_bytes(b"resultado anterior")
        before = existing.read_bytes()

        planned = self.service.pdf_to_image_output_paths(
            source,
            None,
            "PNG",
            destination,
        )
        self.assertEqual(planned, (existing,))
        with self.assertRaisesRegex(PdfToolsError, "já existem"):
            self.service.pdf_to_images(source, None, "PNG", destination)
        self.assertEqual(existing.read_bytes(), before)

        result = self.service.pdf_to_images(
            source,
            None,
            "PNG",
            destination,
            overwrite=True,
        )
        self.assertEqual(result.output_paths, (existing,))
        with Image.open(existing) as image:
            image.load()
            self.assertEqual(image.format, "PNG")
        self.assertEqual(list(destination.glob(".*.tmp.*")), [])
        self.assertEqual(list(destination.glob(".*.bak.*")), [])

    def test_pdf_to_images_does_not_overwrite_conflict_created_after_preflight(
        self,
    ) -> None:
        source = self.root / "atividade.pdf"
        destination = self.root / "destino"
        destination.mkdir()
        write_sized_pdf(source, ((72, 72),))
        output = destination / "atividade-pagina-001.png"
        validations = 0

        def create_conflict_on_publish(_paths, _overwrite):
            nonlocal validations
            validations += 1
            if validations == 2:
                output.write_bytes(b"arquivo criado depois da pre-validacao")

        with (
            patch(
                "pdf_tools._validate_image_output_conflicts",
                side_effect=create_conflict_on_publish,
            ),
            self.assertRaises(PdfToolsError),
        ):
            self.service.pdf_to_images(source, None, "PNG", destination)

        self.assertEqual(output.read_bytes(), b"arquivo criado depois da pre-validacao")
        self.assertEqual(list(destination.glob(".*.tmp.*")), [])
        self.assertEqual(list(destination.glob(".*.bak.*")), [])

    def test_pdf_to_images_failure_leaves_no_partial_outputs_or_temporaries(
        self,
    ) -> None:
        source = self.root / "material.pdf"
        destination = self.root / "destino"
        destination.mkdir()
        write_sized_pdf(source, ((72, 72), (72, 72)))
        real_render = pdf_tools._render_pdf_page

        def fail_second_page(
            document, page_number, temporary_path, image_format, quality
        ):
            if page_number == 2:
                raise PdfToolsError("falha controlada")
            return real_render(
                document, page_number, temporary_path, image_format, quality
            )

        with (
            patch("pdf_tools._render_pdf_page", side_effect=fail_second_page),
            self.assertRaises(PdfToolsError),
        ):
            self.service.pdf_to_images(source, None, "PNG", destination)

        self.assertEqual(list(destination.iterdir()), [])

    def test_merge_and_extract_report_bounded_progress_in_work_order(self) -> None:
        first = self.root / "primeiro.pdf"
        second = self.root / "segundo.pdf"
        source = self.root / "fonte.pdf"
        write_pdf(first, (100, 110))
        write_pdf(second, (120,))
        write_pdf(source, (100, 110, 120))
        merge_updates: list[PdfOperationProgress] = []
        extract_updates: list[PdfOperationProgress] = []

        self.service.merge_pdfs(
            (first, second),
            self.root / "unido.pdf",
            progress=merge_updates.append,
        )
        self.service.extract_pages(
            source,
            "3,1,2",
            self.root / "extraido.pdf",
            progress=extract_updates.append,
        )

        self.assertEqual(
            merge_updates,
            [
                PdfOperationProgress(0, 2),
                PdfOperationProgress(1, 2),
                PdfOperationProgress(2, 2),
            ],
        )
        self.assertEqual(
            extract_updates,
            [PdfOperationProgress(index, 3) for index in range(4)],
        )
        self.assertEqual(page_widths(self.root / "extraido.pdf"), (120, 100, 110))

    def test_merge_and_extract_cancellation_preserve_existing_outputs(self) -> None:
        first = self.root / "primeiro.pdf"
        second = self.root / "segundo.pdf"
        source = self.root / "fonte.pdf"
        merge_output = self.root / "unido.pdf"
        extract_output = self.root / "extraido.pdf"
        write_pdf(first, (100,))
        write_pdf(second, (200,))
        write_pdf(source, (100, 200, 300))
        write_pdf(merge_output, (777,))
        write_pdf(extract_output, (888,))
        merge_before = digest(merge_output)
        extract_before = digest(extract_output)

        for operation, output, before in (
            (
                lambda event, callback: self.service.merge_pdfs(
                    (first, second),
                    output,
                    overwrite=True,
                    cancel_event=event,
                    progress=callback,
                ),
                merge_output,
                merge_before,
            ),
            (
                lambda event, callback: self.service.extract_pages(
                    source,
                    "1-3",
                    output,
                    overwrite=True,
                    cancel_event=event,
                    progress=callback,
                ),
                extract_output,
                extract_before,
            ),
        ):
            with self.subTest(output=output.name):
                event = Event()

                def cancel_after_first(update: PdfOperationProgress) -> None:
                    if update.completed_items == 1:
                        event.set()

                with self.assertRaises(PdfOperationCancelled):
                    operation(event, cancel_after_first)
                self.assertEqual(digest(output), before)
                self.assertEqual(list(self.root.glob(".*.tmp.pdf")), [])

    def test_pdf_to_images_quality_progress_and_dimension_guard(self) -> None:
        source = self.root / "qualidade.pdf"
        destination = self.root / "alta"
        destination.mkdir()
        write_sized_pdf(source, ((72, 144), (144, 72)))
        updates: list[PdfOperationProgress] = []

        result = self.service.pdf_to_images(
            source,
            None,
            "PNG",
            destination,
            quality=PdfImageQuality.HIGH,
            progress=updates.append,
        )

        self.assertEqual(
            updates, [PdfOperationProgress(index, 2) for index in range(3)]
        )
        with Image.open(result.output_paths[0]) as image:
            self.assertEqual(image.size, (300, 600))
        with Image.open(result.output_paths[1]) as image:
            self.assertEqual(image.size, (600, 300))

        unsafe = self.root / "dimensao-insegura.pdf"
        write_sized_pdf(unsafe, ((14_401, 72),))
        with self.assertRaisesRegex(PdfToolsError, "limite seguro"):
            self.service.pdf_to_images(unsafe, None, "PNG", destination)

    def test_pdf_to_images_cancellation_rolls_back_new_and_existing_outputs(
        self,
    ) -> None:
        source = self.root / "cancelamento.pdf"
        destination = self.root / "destino-cancelamento"
        destination.mkdir()
        write_sized_pdf(source, ((72, 72), (72, 72)))
        existing = destination / "cancelamento-pagina-001.png"
        existing.write_bytes(b"resultado anterior")
        before = existing.read_bytes()
        event = Event()

        def cancel_after_first(update: PdfOperationProgress) -> None:
            if update.completed_items == 1:
                event.set()

        with self.assertRaises(PdfOperationCancelled):
            self.service.pdf_to_images(
                source,
                None,
                "PNG",
                destination,
                overwrite=True,
                cancel_event=event,
                progress=cancel_after_first,
            )

        self.assertEqual(existing.read_bytes(), before)
        self.assertFalse((destination / "cancelamento-pagina-002.png").exists())
        self.assertEqual(list(destination.glob(".*.tmp.*")), [])
        self.assertEqual(list(destination.glob(".*.bak.*")), [])

    def test_pdf_to_images_rejects_invalid_quality_and_more_than_500_pages(
        self,
    ) -> None:
        source = self.root / "limites.pdf"
        destination = self.root / "limites"
        destination.mkdir()
        write_sized_pdf(source, ((10, 10),) * 501)

        with self.assertRaisesRegex(PdfToolsError, "qualidade"):
            self.service.pdf_to_images(
                source,
                "1",
                "PNG",
                destination,
                quality="Alta",  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(PdfToolsError, "500 páginas"):
            self.service.pdf_to_images(source, None, "PNG", destination)
        self.assertEqual(list(destination.iterdir()), [])

    def test_write_failure_preserves_existing_output_and_cleans_temporary(self) -> None:
        first = self.root / "um.pdf"
        second = self.root / "dois.pdf"
        output = self.root / "resultado.pdf"
        write_pdf(first, (100,))
        write_pdf(second, (200,))
        output.write_bytes(b"resultado anterior")
        before = output.read_bytes()

        def fail_write(_writer: PdfWriter, stream: object) -> None:
            stream.write(b"parcial")
            raise OSError("falha simulada")

        with (
            patch("pdf_tools.PdfWriter.write", autospec=True, side_effect=fail_write),
            self.assertRaises(PdfToolsError),
        ):
            self.service.merge_pdfs((first, second), output, overwrite=True)

        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(list(self.root.glob(".*.tmp.pdf")), [])

    def test_write_failure_without_existing_output_leaves_no_result(self) -> None:
        first = self.root / "um.pdf"
        second = self.root / "dois.pdf"
        output = self.root / "não-deve-existir.pdf"
        write_pdf(first, (100,))
        write_pdf(second, (200,))

        with (
            patch("pdf_tools.PdfWriter.write", side_effect=OSError("falha simulada")),
            self.assertRaises(PdfToolsError),
        ):
            self.service.merge_pdfs((first, second), output)

        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.pdf")), [])


if __name__ == "__main__":
    unittest.main()
