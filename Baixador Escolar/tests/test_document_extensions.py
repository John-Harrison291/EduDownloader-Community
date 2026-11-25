from __future__ import annotations

import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pypdf import PdfReader, PdfWriter

import documents_tools
from documents_component import (
    COMPONENT_VERSION,
    ENGINE_VERSION,
    DocumentsComponent,
    DocumentsComponentCheck,
    DocumentsComponentStatus,
)
from documents_tools import (
    DocumentConversionRequest,
    DocumentConversionStatus,
    DocumentInputFormat,
    DocumentsConversionService,
    _ProcessOutcome,
    validate_odt_input,
    validate_txt_input,
)


def _write_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)


def _write_odt(
    path: Path,
    *,
    content: bytes = b"<office:document-content/>",
    extra_entries: dict[str, bytes] | None = None,
    include_content: bool = True,
    mimetype: bytes = b"application/vnd.oasis.opendocument.text",
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        if include_content:
            archive.writestr("content.xml", content, compress_type=zipfile.ZIP_DEFLATED)
        for name, payload in (extra_entries or {}).items():
            archive.writestr(name, payload, compress_type=zipfile.ZIP_DEFLATED)


class _ComponentService:
    def __init__(
        self,
        component: DocumentsComponent | None,
        status: DocumentsComponentStatus = DocumentsComponentStatus.AVAILABLE,
    ) -> None:
        self.component = component
        self.status = status
        self.calls: list[Path | None] = []

    def fast_check(self, root: Path | None = None) -> DocumentsComponentCheck:
        self.calls.append(root)
        return DocumentsComponentCheck(
            self.status,
            self.component
            if self.status is DocumentsComponentStatus.AVAILABLE
            else None,
            "test",
        )


class _Runner:
    def __init__(self, *, cancel: bool = False) -> None:
        self.cancel = cancel
        self.calls: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        _environment: dict[str, str],
        _cwd: Path,
        _stdout_path: Path,
        _stderr_path: Path,
        cancel_event: threading.Event,
        _timeout_seconds: float,
    ) -> _ProcessOutcome:
        self.calls.append(command)
        staging = Path(command[command.index("--outdir") + 1])
        _write_pdf(staging / "document.pdf")
        if self.cancel:
            cancel_event.set()
        return _ProcessOutcome(0)


class DocumentExtensionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        component_root = self.base / "component"
        program = component_root / "engine/App/libreoffice/program"
        python_home = program / "python-core-3.12.13"
        python_home.mkdir(parents=True)
        self.component = DocumentsComponent(
            root=component_root,
            engine_root=component_root / "engine",
            soffice_entrypoint=program / "soffice.com",
            soffice_bin=program / "soffice.bin",
            launcher=component_root / "engine/LibreOfficePortable.exe",
            python_home=python_home,
            python_runtime=python_home / "bin/python.exe",
            component_version=COMPONENT_VERSION,
            engine_version=ENGINE_VERSION,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _text_service(self) -> tuple[DocumentsConversionService, _ComponentService]:
        missing = _ComponentService(None, DocumentsComponentStatus.NOT_CONFIGURED)
        operations = self.base / "operations"
        operations.mkdir(exist_ok=True)
        return (
            DocumentsConversionService(
                component_service=missing,
                temporary_parent=operations,
            ),
            missing,
        )

    def _convert_text(
        self,
        content: bytes,
        *,
        name: str = "Anotações 你好.txt",
        overwrite: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> tuple[object, Path, Path, _ComponentService]:
        source = self.base / name
        source.write_bytes(content)
        output = self.base / f"{source.stem}.pdf"
        service, component = self._text_service()
        result = service.convert(
            DocumentConversionRequest(
                source,
                output,
                overwrite=overwrite,
                cancel_event=cancel_event,
                input_format=DocumentInputFormat.TXT,
            )
        )
        return result, source, output, component

    def test_txt_utf8_bom_unicode_blank_lines_tabs_and_no_final_newline(self) -> None:
        content = "Título\n\nAção\tEducação 你好\nsem newline".encode("utf-8-sig")
        result, source, output, component = self._convert_text(content)
        self.assertEqual(result.status, DocumentConversionStatus.COMPLETED)
        self.assertEqual(len(PdfReader(output, strict=True).pages), 1)
        self.assertEqual(source.read_bytes(), content)
        self.assertEqual(component.calls, [])
        self.assertEqual(list((self.base / "operations").iterdir()), [])

    def test_empty_txt_creates_one_valid_blank_page(self) -> None:
        result, _source, output, _component = self._convert_text(b"")
        self.assertEqual(result.status, DocumentConversionStatus.COMPLETED)
        pages = PdfReader(output, strict=True).pages
        self.assertEqual(len(pages), 1)
        width = float(pages[0].mediabox.width)
        height = float(pages[0].mediabox.height)
        self.assertAlmostEqual(width, 595.2, delta=1.0)
        self.assertAlmostEqual(height, 841.92, delta=1.0)
        self.assertLess(width, height)

    def test_long_lines_wrap_and_many_lines_paginate(self) -> None:
        content = (("palavra " * 400) + "\n" + ("linha\n" * 180)).encode()
        result, _source, output, _component = self._convert_text(content)
        self.assertEqual(result.status, DocumentConversionStatus.COMPLETED)
        self.assertGreater(len(PdfReader(output, strict=True).pages), 1)

    def test_invalid_utf8_and_defensive_limits_are_friendly_invalid_input(self) -> None:
        result, _source, output, component = self._convert_text(b"inv\xfflido")
        self.assertEqual(result.status, DocumentConversionStatus.INVALID_INPUT)
        self.assertEqual(
            result.public_message, "Não foi possível ler este arquivo de texto."
        )
        self.assertFalse(output.exists())
        self.assertEqual(component.calls, [])

        with mock.patch.object(documents_tools, "TXT_MAX_LINE_CHARACTERS", 4):
            result, _source, output, _component = self._convert_text(
                b"12345", name="limite.txt"
            )
        self.assertEqual(result.status, DocumentConversionStatus.INVALID_INPUT)
        self.assertFalse(output.exists())

    def test_txt_removed_relative_unc_wrong_extension_and_size_are_rejected(
        self,
    ) -> None:
        valid = self.base / "texto.txt"
        valid.write_text("ok", encoding="utf-8")
        self.assertEqual(validate_txt_input(valid), valid)
        removed = self.base / "removido.txt"
        removed.write_text("x", encoding="utf-8")
        removed.unlink()
        wrong = self.base / "texto.md"
        wrong.write_text("x", encoding="utf-8")
        for value in (
            Path("relativo.txt"),
            removed,
            wrong,
            Path(r"\\host\share\a.txt"),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_txt_input(value)
        with mock.patch.object(documents_tools, "TXT_MAX_FILE_BYTES", 1):
            with self.assertRaises(ValueError):
                validate_txt_input(valid)

    def test_unknown_input_format_fails_closed(self) -> None:
        source = self.base / "texto.txt"
        source.write_text("ok", encoding="utf-8")
        service, component = self._text_service()
        result = service.convert(
            DocumentConversionRequest(
                source,
                self.base / "texto.pdf",
                input_format="TXT",  # type: ignore[arg-type]
            )
        )
        self.assertEqual(result.status, DocumentConversionStatus.INVALID_INPUT)
        self.assertEqual(result.diagnostic_code, "documents_invalid_input_format")
        self.assertEqual(component.calls, [])

    def test_txt_output_exists_cancel_and_atomic_failure_preserve_previous(
        self,
    ) -> None:
        source = self.base / "texto.txt"
        source.write_text("conteúdo", encoding="utf-8")
        output = self.base / "texto.pdf"
        output.write_bytes(b"previous")
        service, component = self._text_service()
        request = DocumentConversionRequest(
            source, output, input_format=DocumentInputFormat.TXT
        )
        result = service.convert(request)
        self.assertEqual(result.status, DocumentConversionStatus.OUTPUT_EXISTS)
        self.assertEqual(output.read_bytes(), b"previous")
        self.assertEqual(component.calls, [])

        event = threading.Event()
        event.set()
        cancelled = service.convert(
            DocumentConversionRequest(
                source,
                output,
                overwrite=True,
                cancel_event=event,
                input_format=DocumentInputFormat.TXT,
            )
        )
        self.assertEqual(cancelled.status, DocumentConversionStatus.CANCELLED)
        self.assertEqual(output.read_bytes(), b"previous")

        real_replace = documents_tools.os.replace

        def fail_publication(source_path: object, destination_path: object) -> None:
            if Path(destination_path) == output and Path(source_path).name.endswith(
                ".pending.pdf"
            ):
                raise OSError("simulated publication failure")
            real_replace(source_path, destination_path)

        with mock.patch.object(
            documents_tools.os, "replace", side_effect=fail_publication
        ):
            failed = service.convert(
                DocumentConversionRequest(
                    source,
                    output,
                    overwrite=True,
                    input_format=DocumentInputFormat.TXT,
                )
            )
        self.assertEqual(failed.status, DocumentConversionStatus.ERROR)
        self.assertEqual(output.read_bytes(), b"previous")
        self.assertEqual(list(self.base.glob("*.pending.pdf")), [])
        self.assertEqual(list(self.base.glob("*.backup.pdf")), [])

    def test_txt_page_limit_and_mid_render_cancellation_are_enforced(self) -> None:
        source = self.base / "muitas-linhas.txt"
        source.write_text("linha\n" * 200, encoding="utf-8")
        output = self.base / "muitas-linhas.pdf"
        service, component = self._text_service()
        with mock.patch.object(documents_tools, "TXT_MAX_PAGES", 1):
            limited = service.convert(
                DocumentConversionRequest(
                    source, output, input_format=DocumentInputFormat.TXT
                )
            )
        self.assertEqual(limited.status, DocumentConversionStatus.INVALID_INPUT)
        self.assertFalse(output.exists())
        self.assertEqual(component.calls, [])

        previous = b"previous"
        output.write_bytes(previous)
        event = threading.Event()
        real_wrap = documents_tools._wrap_text_line
        calls = 0

        def cancel_after_first(*args: object, **kwargs: object) -> tuple[str, ...]:
            nonlocal calls
            calls += 1
            result = real_wrap(*args, **kwargs)
            if calls == 1:
                event.set()
            return result

        with mock.patch.object(
            documents_tools, "_wrap_text_line", side_effect=cancel_after_first
        ):
            cancelled = service.convert(
                DocumentConversionRequest(
                    source,
                    output,
                    overwrite=True,
                    cancel_event=event,
                    input_format=DocumentInputFormat.TXT,
                )
            )
        self.assertEqual(cancelled.status, DocumentConversionStatus.CANCELLED)
        self.assertEqual(output.read_bytes(), previous)

    def test_valid_odt_uses_shared_hardened_runtime(self) -> None:
        source = self.base / "Plano 你好.odt"
        _write_odt(
            source,
            content=(
                '<office:document-content xmlns:office="urn:oasis:names:tc:'
                'opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:'
                'tc:opendocument:xmlns:table:1.0" xmlns:draw="urn:oasis:names:'
                'tc:opendocument:xmlns:drawing:1.0" xmlns:xlink="http://www.'
                'w3.org/1999/xlink">Educação 你好'
                "<table:table><table:table-row/></table:table>"
                '<draw:image xlink:href="Pictures/a.png"/>'
                "</office:document-content>"
            ).encode("utf-8"),
            extra_entries={"Pictures/a.png": b"synthetic-image"},
        )
        output = self.base / "Plano 你好.pdf"
        runner = _Runner()
        component_service = _ComponentService(self.component)
        operations = self.base / "odt-operations"
        operations.mkdir()
        service = DocumentsConversionService(
            component_service=component_service,
            temporary_parent=operations,
            process_runner=runner,
        )
        result = service.convert(
            DocumentConversionRequest(
                source,
                output,
                component_root=self.component.root,
                input_format=DocumentInputFormat.ODT,
            )
        )
        self.assertEqual(result.status, DocumentConversionStatus.COMPLETED)
        self.assertEqual(len(PdfReader(output, strict=True).pages), 1)
        self.assertTrue(runner.calls[0][-1].endswith("document.odt"))
        self.assertEqual(list(operations.iterdir()), [])

    def test_odt_structure_mimetype_traversal_and_ratio_are_rejected(self) -> None:
        cases: list[Path] = []
        plain = self.base / "plain.odt"
        plain.write_text("not zip", encoding="utf-8")
        cases.append(plain)
        missing = self.base / "missing.odt"
        _write_odt(missing, include_content=False)
        cases.append(missing)
        bad_mime = self.base / "mime.odt"
        _write_odt(bad_mime, mimetype=b"text/plain")
        cases.append(bad_mime)
        traversal = self.base / "traversal.odt"
        _write_odt(traversal, extra_entries={"../escape": b"x"})
        cases.append(traversal)
        ratio = self.base / "ratio.odt"
        _write_odt(ratio, extra_entries={"Pictures/a.bin": b"A" * 200_000})
        cases.append(ratio)
        for path in cases:
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_odt_input(path)

    def test_odt_removed_relative_unc_and_wrong_extension_are_rejected(self) -> None:
        valid = self.base / "valid.odt"
        _write_odt(valid)
        self.assertEqual(validate_odt_input(valid), valid)
        removed = self.base / "removed.odt"
        _write_odt(removed)
        removed.unlink()
        wrong = self.base / "wrong.zip"
        _write_odt(wrong)
        for value in (
            Path("relative.odt"),
            removed,
            wrong,
            Path(r"\\host\share\document.odt"),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_odt_input(value)

    def test_invalid_odt_never_reaches_component_runner(self) -> None:
        source = self.base / "invalid.odt"
        source.write_text("not an odt", encoding="utf-8")
        runner = _Runner()
        service = DocumentsConversionService(
            component_service=_ComponentService(self.component),
            process_runner=runner,
        )
        result = service.convert(
            DocumentConversionRequest(
                source,
                self.base / "invalid.pdf",
                input_format=DocumentInputFormat.ODT,
            )
        )
        self.assertEqual(result.status, DocumentConversionStatus.INVALID_INPUT)
        self.assertEqual(runner.calls, [])

    def test_odt_cancel_never_publishes_partial_output(self) -> None:
        source = self.base / "cancel.odt"
        _write_odt(source)
        output = self.base / "cancel.pdf"
        output.write_bytes(b"previous")
        runner = _Runner(cancel=True)
        service = DocumentsConversionService(
            component_service=_ComponentService(self.component),
            process_runner=runner,
        )
        result = service.convert(
            DocumentConversionRequest(
                source,
                output,
                overwrite=True,
                input_format=DocumentInputFormat.ODT,
            )
        )
        self.assertEqual(result.status, DocumentConversionStatus.CANCELLED)
        self.assertEqual(output.read_bytes(), b"previous")

    def test_odt_missing_component_is_controlled(self) -> None:
        source = self.base / "valid.odt"
        _write_odt(source)
        service = DocumentsConversionService(
            component_service=_ComponentService(
                None, DocumentsComponentStatus.NOT_CONFIGURED
            )
        )
        result = service.convert(
            DocumentConversionRequest(
                source,
                self.base / "valid.pdf",
                input_format=DocumentInputFormat.ODT,
            )
        )
        self.assertEqual(result.status, DocumentConversionStatus.COMPONENT_UNAVAILABLE)

    def test_odt_corrupted_component_is_controlled(self) -> None:
        source = self.base / "valid-corrupted.odt"
        _write_odt(source)
        service = DocumentsConversionService(
            component_service=_ComponentService(
                None, DocumentsComponentStatus.CORRUPTED
            )
        )
        result = service.convert(
            DocumentConversionRequest(
                source,
                self.base / "valid-corrupted.pdf",
                input_format=DocumentInputFormat.ODT,
            )
        )
        self.assertEqual(result.status, DocumentConversionStatus.COMPONENT_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
