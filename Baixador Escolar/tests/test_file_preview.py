"""Testes do preview local puro, sem Tk, subprocessos ou arquivos pessoais."""

from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from threading import Event
from typing import cast
from zipfile import ZipFile

from PIL import Image
from pypdf import PdfWriter

import file_preview
from file_preview import (
    PREVIEW_MAX_DIMENSION,
    PREVIEW_MAX_FILE_BYTES,
    FilePreviewResult,
    FilePreviewService,
    PreviewKind,
    PreviewStatus,
)
from local_files import LocalFileCategory, LocalFileEntry, LocalFilesError
from word_preview import require_offline_document


def _entry(path: Path, category: LocalFileCategory) -> LocalFileEntry:
    metadata = path.stat()
    return LocalFileEntry(path, category, metadata.st_size, metadata.st_mtime)


def _write_image(
    path: Path,
    size: tuple[int, int],
    *,
    mode: str = "RGB",
    color: tuple[int, ...] = (20, 40, 60),
) -> None:
    image = Image.new(mode, size, color)
    try:
        image.save(path)
    finally:
        image.close()


def _write_pdf(path: Path, sizes: tuple[tuple[float, float], ...]) -> None:
    writer = PdfWriter()
    try:
        for width, height in sizes:
            writer.add_blank_page(width=width, height=height)
        with path.open("wb") as stream:
            writer.write(stream)
    finally:
        writer.close()


def _write_protected_pdf(path: Path) -> None:
    writer = PdfWriter()
    try:
        writer.add_blank_page(width=200, height=300)
        writer.encrypt("senha-somente-para-fixture")
        with path.open("wb") as stream:
            writer.write(stream)
    finally:
        writer.close()


def _write_odt(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr(
            "content.xml",
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            "<office:body><office:text><text:p>Plano de aula</text:p>"
            "</office:text></office:body></office:document-content>",
        )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def _write_header_only_png(path: Path, width: int, height: int) -> None:
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IEND", b"")
    )


class FilePreviewContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = FilePreviewService()

    def test_result_contract_is_immutable(self) -> None:
        result = FilePreviewResult(PreviewStatus.UNSUPPORTED)

        with self.assertRaises(FrozenInstanceError):
            result.width = 1  # type: ignore[misc]

    def test_legacy_documents_audio_and_unknown_categories_are_unsupported(
        self,
    ) -> None:
        paths = (
            (self.root / "aula.doc", LocalFileCategory.DOCUMENT),
            (self.root / "notas.txt", LocalFileCategory.DOCUMENT),
            (self.root / "audio.mp3", LocalFileCategory.AUDIO),
        )
        for path, category in paths:
            path.write_bytes(b"fixture")
            with self.subTest(category=category):
                result = self.service.create_preview(_entry(path, category), self.root)
                self.assertEqual(result.status, PreviewStatus.UNSUPPORTED)
                self.assertEqual(result.rgba, b"")

        unknown = LocalFileEntry(
            self.root / "desconhecido.bin",
            cast(LocalFileCategory, "unknown"),
            0,
            0,
        )
        result = FilePreviewService(
            revalidate_file=lambda entry, _directory: entry
        ).create_preview(unknown, self.root)
        self.assertEqual(result.status, PreviewStatus.UNSUPPORTED)

    def test_odt_has_bounded_text_fallback_without_office(self) -> None:
        document = self.root / "aula.odt"
        _write_odt(document)
        entry = _entry(document, LocalFileCategory.DOCUMENT)
        result = self.service.create_preview(entry, self.root)
        self.assertEqual(result.status, PreviewStatus.SUCCESS)
        self.assertEqual(result.kind, PreviewKind.WORD_TEXT)
        self.assertEqual(result.text, "Plano de aula")
        self.assertEqual(result.rgba, b"")

        document.write_bytes(b"fixture invalida")
        result = self.service.create_preview(
            _entry(document, LocalFileCategory.DOCUMENT), self.root
        )
        self.assertEqual(result.status, PreviewStatus.INVALID)

    def test_office_preflight_accepts_only_relationships_inside_package(self) -> None:
        document = self.root / "relacoes.docx"
        for target, mode, valid in (
            ("../media/imagem.png", "", True),
            ("/media/imagem.png", "", True),
            ("../../fora.png", "", False),
            ("https://example.invalid/aula", ' TargetMode="External"', False),
            ("%2e%2e/%2e%2e/fora.png", "", False),
        ):
            with self.subTest(target=target):
                with ZipFile(document, "w") as archive:
                    archive.writestr("media/imagem.png", b"fixture")
                    archive.writestr(
                        "word/_rels/document.xml.rels",
                        f'<Relationships><Relationship Target="{target}"{mode}/></Relationships>',
                    )
                if valid:
                    require_offline_document(document, Event())
                else:
                    with self.assertRaises(ValueError):
                        require_offline_document(document, Event())

    def test_invalid_contract_and_revalidation_failure_are_safe(self) -> None:
        invalid = self.service.create_preview(cast(LocalFileEntry, object()), self.root)
        self.assertEqual(invalid.status, PreviewStatus.INVALID)

        path = self.root / "imagem.png"
        _write_image(path, (10, 10))

        def reject(_entry: LocalFileEntry, _directory: Path | str) -> LocalFileEntry:
            raise LocalFilesError("detalhe privado")

        unavailable = FilePreviewService(revalidate_file=reject).create_preview(
            _entry(path, LocalFileCategory.IMAGE), self.root
        )
        self.assertEqual(unavailable.status, PreviewStatus.UNAVAILABLE)
        self.assertNotIn("detalhe privado", unavailable.message or "")

    def test_relative_unc_directory_removed_and_reparse_are_rejected(self) -> None:
        image = self.root / "imagem.png"
        _write_image(image, (10, 10))
        entry = _entry(image, LocalFileCategory.IMAGE)

        relative = replace(entry, path=Path("imagem.png"))
        self.assertNotEqual(
            self.service.create_preview(relative, self.root).status,
            PreviewStatus.SUCCESS,
        )
        self.assertNotEqual(
            self.service.create_preview(entry, r"\\servidor\compartilhamento").status,
            PreviewStatus.SUCCESS,
        )

        directory_entry_path = self.root / "diretorio.png"
        directory_entry_path.mkdir()
        directory_entry = LocalFileEntry(
            directory_entry_path,
            LocalFileCategory.IMAGE,
            0,
            0,
        )
        self.assertEqual(
            self.service.create_preview(directory_entry, self.root).status,
            PreviewStatus.UNAVAILABLE,
        )

        removed = entry
        image.unlink()
        self.assertEqual(
            self.service.create_preview(removed, self.root).status,
            PreviewStatus.UNAVAILABLE,
        )

        def reject_reparse(
            _entry: LocalFileEntry, _directory: Path | str
        ) -> LocalFileEntry:
            raise LocalFilesError("reparse point")

        self.assertEqual(
            FilePreviewService(revalidate_file=reject_reparse)
            .create_preview(entry, self.root)
            .status,
            PreviewStatus.UNAVAILABLE,
        )

    def test_file_size_limit_is_enforced_before_decoding(self) -> None:
        path = self.root / "pequena.png"
        _write_image(path, (2, 2))
        entry = _entry(path, LocalFileCategory.IMAGE)

        service = FilePreviewService(
            revalidate_file=lambda current, _directory: replace(
                current, size_bytes=PREVIEW_MAX_FILE_BYTES + 1
            )
        )
        result = service.create_preview(entry, self.root)

        self.assertEqual(result.status, PreviewStatus.TOO_LARGE)
        self.assertEqual(result.rgba, b"")

    def test_module_has_no_ui_subprocess_network_or_persistence_imports(self) -> None:
        source = Path(file_preview.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "tkinter",
            "customtkinter",
            "subprocess",
            "urllib",
            "requests",
            "logging",
            "ui_pages",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class ImagePreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = FilePreviewService()

    def preview(self, path: Path):
        return self.service.create_preview(
            _entry(path, LocalFileCategory.IMAGE), path.parent
        )

    def assert_success(self, result, size: tuple[int, int]) -> None:
        self.assertEqual(result.status, PreviewStatus.SUCCESS)
        self.assertEqual(result.kind, PreviewKind.IMAGE)
        self.assertEqual((result.width, result.height), size)
        self.assertEqual(len(result.rgba), result.width * result.height * 4)
        self.assertIsNone(result.message)

    def test_small_jpg_is_not_upscaled_and_large_landscape_is_limited(self) -> None:
        small = self.root / "pequena.jpg"
        large = self.root / "grande.jpg"
        _write_image(small, (120, 80))
        _write_image(large, (2048, 1024))

        self.assert_success(self.preview(small), (120, 80))
        self.assert_success(self.preview(large), (512, 256))

    def test_portrait_and_landscape_preserve_ratio(self) -> None:
        portrait = self.root / "retrato.png"
        landscape = self.root / "paisagem.png"
        _write_image(portrait, (400, 800))
        _write_image(landscape, (900, 300))

        self.assert_success(self.preview(portrait), (256, 512))
        self.assert_success(self.preview(landscape), (512, 171))

    def test_rgba_transparency_and_payload_are_preserved(self) -> None:
        path = self.root / "transparente.png"
        _write_image(path, (2, 1), mode="RGBA", color=(10, 20, 30, 40))

        result = self.preview(path)

        self.assert_success(result, (2, 1))
        self.assertEqual(result.rgba, bytes((10, 20, 30, 40)) * 2)

    def test_exif_orientation_is_applied(self) -> None:
        path = self.root / "orientada.jpg"
        image = Image.new("RGB", (40, 20), "red")
        try:
            exif = Image.Exif()
            exif[274] = 6
            image.save(path, exif=exif)
        finally:
            image.close()

        self.assert_success(self.preview(path), (20, 40))

    def test_spaces_and_unicode_paths_work_without_modifying_source(self) -> None:
        directory = self.root / "Pasta João — Educação 你好"
        directory.mkdir()
        path = directory / "imagem com espaços çã.png"
        _write_image(path, (33, 21))
        before = path.read_bytes()

        self.assert_success(self.preview(path), (33, 21))
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_truncated_and_excessive_pixel_images_are_rejected(self) -> None:
        invalid = self.root / "invalida.png"
        invalid.write_bytes(b"nao-e-imagem")
        self.assertEqual(self.preview(invalid).status, PreviewStatus.INVALID)

        truncated = self.root / "truncada.jpg"
        _write_image(truncated, (20, 20))
        truncated.write_bytes(truncated.read_bytes()[:24])
        self.assertEqual(self.preview(truncated).status, PreviewStatus.INVALID)

        huge = self.root / "dimensoes-excessivas.png"
        _write_header_only_png(huge, 8_000, 5_001)
        previous_limit = Image.MAX_IMAGE_PIXELS
        result = self.preview(huge)
        self.assertEqual(result.status, PreviewStatus.TOO_LARGE)
        self.assertIs(Image.MAX_IMAGE_PIXELS, previous_limit)

    def test_handles_are_closed_after_preview(self) -> None:
        path = self.root / "renomeavel.png"
        renamed = self.root / "renomeada.png"
        _write_image(path, (20, 20))
        self.assertEqual(self.preview(path).status, PreviewStatus.SUCCESS)

        path.rename(renamed)
        renamed.unlink()
        self.assertFalse(renamed.exists())


class PdfPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = FilePreviewService()

    def preview(self, path: Path):
        return self.service.create_preview(
            _entry(path, LocalFileCategory.PDF), path.parent
        )

    def assert_success(self, result, size: tuple[int, int]) -> None:
        self.assertEqual(result.status, PreviewStatus.SUCCESS)
        self.assertEqual(result.kind, PreviewKind.PDF_PAGE)
        self.assertEqual((result.width, result.height), size)
        self.assertEqual(len(result.rgba), result.width * result.height * 4)

    def test_one_page_portrait_and_landscape_are_rendered_at_bounded_size(self) -> None:
        portrait = self.root / "retrato.pdf"
        landscape = self.root / "paisagem.pdf"
        _write_pdf(portrait, ((256, 512),))
        _write_pdf(landscape, ((1024, 512),))

        self.assert_success(self.preview(portrait), (256, 512))
        self.assert_success(self.preview(landscape), (512, 256))

    def test_small_pdf_is_not_upscaled_and_only_first_page_is_rendered(self) -> None:
        path = self.root / "duas-paginas.pdf"
        _write_pdf(path, ((120, 240), (900, 300)))

        self.assert_success(self.preview(path), (120, 240))

    def test_zero_page_invalid_password_and_absurd_pdf_are_rejected(self) -> None:
        empty = self.root / "sem-paginas.pdf"
        _write_pdf(empty, ())
        self.assertEqual(self.preview(empty).status, PreviewStatus.UNAVAILABLE)

        invalid = self.root / "invalido.pdf"
        invalid.write_bytes(b"nao-e-pdf")
        self.assertEqual(self.preview(invalid).status, PreviewStatus.INVALID)

        truncated = self.root / "truncado.pdf"
        _write_pdf(truncated, ((200, 200),))
        truncated.write_bytes(truncated.read_bytes()[:40])
        self.assertEqual(self.preview(truncated).status, PreviewStatus.INVALID)

        protected = self.root / "protegido.pdf"
        _write_protected_pdf(protected)
        self.assertEqual(self.preview(protected).status, PreviewStatus.INVALID)

        absurd = self.root / "pagina-absurda.pdf"
        _write_pdf(absurd, ((14_401, 100),))
        self.assertEqual(self.preview(absurd).status, PreviewStatus.TOO_LARGE)

    def test_unicode_spaces_original_integrity_and_closed_handles(self) -> None:
        directory = self.root / "Pasta João — Educação 你好"
        directory.mkdir()
        path = directory / "arquivo com espaços çã.pdf"
        renamed = directory / "renomeado.pdf"
        _write_pdf(path, ((200, 300),))
        before = path.read_bytes()

        self.assert_success(self.preview(path), (200, 300))
        self.assertEqual(path.read_bytes(), before)
        path.rename(renamed)
        renamed.unlink()
        self.assertFalse(renamed.exists())

    def test_independent_concurrent_calls_return_complete_payloads(self) -> None:
        image = self.root / "imagem.png"
        pdf = self.root / "documento.pdf"
        _write_image(image, (64, 32))
        _write_pdf(pdf, ((200, 100),))
        image_entry = _entry(image, LocalFileCategory.IMAGE)
        pdf_entry = _entry(pdf, LocalFileCategory.PDF)
        requests = (
            (image_entry, PreviewKind.IMAGE),
            (pdf_entry, PreviewKind.PDF_PAGE),
            (image_entry, PreviewKind.IMAGE),
            (pdf_entry, PreviewKind.PDF_PAGE),
        )

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = tuple(
                executor.map(
                    lambda request: (
                        self.service.create_preview(request[0], self.root),
                        request[1],
                    ),
                    requests,
                )
            )

        for result, expected_kind in results:
            self.assertEqual(result.status, PreviewStatus.SUCCESS)
            self.assertEqual(result.kind, expected_kind)
            self.assertEqual(len(result.rgba), result.width * result.height * 4)
            self.assertLessEqual(result.width, PREVIEW_MAX_DIMENSION)
            self.assertLessEqual(result.height, PREVIEW_MAX_DIMENSION)


if __name__ == "__main__":
    unittest.main()
