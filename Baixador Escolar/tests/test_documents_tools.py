from __future__ import annotations

import ctypes
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from dataclasses import FrozenInstanceError
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
    DOCX_MAX_COMPRESSION_RATIO,
    DocumentConversionRequest,
    DocumentConversionStatus,
    DocumentsConversionService,
    _ProcessOutcome,
    _WindowsJobProcess,
    build_libreoffice_command,
    build_libreoffice_environment,
    validate_docx_input,
)


def _write_docx(
    path: Path,
    *,
    extra_entries: dict[str, bytes] | None = None,
    required: bool = True,
) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        if required:
            archive.writestr(
                "[Content_Types].xml",
                b"<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>",
            )
            archive.writestr(
                "word/document.xml",
                b"<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>",
            )
        for name, content in (extra_entries or {}).items():
            archive.writestr(name, content)


def _write_pdf(path: Path, *, pages: int = 1) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)


def _mark_zip_encrypted(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        cursor = 0
        while (index := payload.find(signature, cursor)) >= 0:
            offset = index + flag_offset
            flags = int.from_bytes(payload[offset : offset + 2], "little") | 0x1
            payload[offset : offset + 2] = flags.to_bytes(2, "little")
            cursor = index + len(signature)
    path.write_bytes(payload)


class _FakeComponentService:
    def __init__(
        self,
        component: DocumentsComponent | None,
        status: DocumentsComponentStatus = DocumentsComponentStatus.AVAILABLE,
    ) -> None:
        self.component = component
        self.status = status
        self.calls: list[Path | None] = []

    def fast_check(self, root: Path | None) -> DocumentsComponentCheck:
        self.calls.append(root)
        return DocumentsComponentCheck(
            self.status,
            self.component
            if self.status is DocumentsComponentStatus.AVAILABLE
            else None,
            f"component_{self.status.value.casefold()}",
        )


class _FakeRunner:
    def __init__(self, behavior: str = "success") -> None:
        self.behavior = behavior
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        command: list[str],
        environment: dict[str, str],
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
        cancel_event: threading.Event,
        timeout_seconds: float,
    ) -> _ProcessOutcome:
        self.calls.append(
            {
                "command": command,
                "environment": environment,
                "cwd": cwd,
                "timeout": timeout_seconds,
                "policy": (
                    Path(environment["TEMP"]).parent
                    / "profile/user/registrymodifications.xcu"
                ).read_text(encoding="utf-8"),
            }
        )
        stdout_path.write_text("ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        staging = Path(command[command.index("--outdir") + 1])
        if self.behavior in ("success", "writer_lock"):
            _write_pdf(staging / "document.pdf")
            if self.behavior == "writer_lock":
                (staging / ".~lock.document.pdf#").write_text("lock", encoding="utf-8")
            return _ProcessOutcome(0)
        if self.behavior == "cancelled_late":
            _write_pdf(staging / "document.pdf")
            cancel_event.set()
            return _ProcessOutcome(0)
        if self.behavior == "timeout":
            return _ProcessOutcome(None, timed_out=True)
        if self.behavior == "failure":
            return _ProcessOutcome(1, stderr="engine details must stay internal")
        if self.behavior == "no_output":
            return _ProcessOutcome(0)
        if self.behavior == "invalid_pdf":
            (staging / "document.pdf").write_bytes(b"not a pdf")
            return _ProcessOutcome(0)
        if self.behavior == "extra_output":
            _write_pdf(staging / "document.pdf")
            (staging / "extra.txt").write_text("extra", encoding="utf-8")
            return _ProcessOutcome(0)
        if self.behavior == "pythonhome_warning":
            _write_pdf(staging / "document.pdf")
            return _ProcessOutcome(
                0, stderr="Could not find platform independent libraries <prefix>"
            )
        raise AssertionError(self.behavior)


class DocumentsToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source = self.base / "Aula João.docx"
        _write_docx(self.source)
        component_root = self.base / "component"
        engine = component_root / "engine"
        program = engine / "App/libreoffice/program"
        python_home = program / "python-core-3.12.13"
        python_home.mkdir(parents=True)
        self.component = DocumentsComponent(
            root=component_root,
            engine_root=engine,
            soffice_entrypoint=program / "soffice.com",
            soffice_bin=program / "soffice.bin",
            launcher=engine / "LibreOfficePortable.exe",
            python_home=python_home,
            python_runtime=python_home / "bin/python.exe",
            component_version=COMPONENT_VERSION,
            engine_version=ENGINE_VERSION,
        )
        self.component_service = _FakeComponentService(self.component)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _convert(
        self,
        behavior: str = "success",
        *,
        output: Path | None = None,
        overwrite: bool = False,
        cancel_event: threading.Event | None = None,
        preview: bool = False,
    ) -> tuple[object, _FakeRunner]:
        runner = _FakeRunner(behavior)
        operations = self.base / "operations"
        operations.mkdir(exist_ok=True)
        service = DocumentsConversionService(
            component_service=self.component_service,
            temporary_parent=operations,
            process_runner=runner,
        )
        result = service.convert(
            DocumentConversionRequest(
                self.source,
                output or self.base / "Saída João.pdf",
                component_root=self.component.root,
                overwrite=overwrite,
                cancel_event=cancel_event,
                preview=preview,
            )
        )
        self.assertEqual(list(operations.iterdir()), [])
        return result, runner

    def test_request_and_result_contracts_are_immutable(self) -> None:
        request = DocumentConversionRequest(self.source, self.base / "out.pdf")
        with self.assertRaises(FrozenInstanceError):
            request.overwrite = True

    def test_valid_docx_is_accepted_without_extracting_it(self) -> None:
        self.assertEqual(validate_docx_input(self.source), self.source)
        self.assertFalse((self.base / "word").exists())

    def test_preview_exports_only_first_page_in_an_isolated_profile(self) -> None:
        with mock.patch.dict(
            os.environ, {"NO_PROXY": "*", "SC_FORCE_CALCULATION": "opencl"}
        ):
            result, runner = self._convert(preview=True)
        self.assertEqual(result.status, DocumentConversionStatus.COMPLETED)
        self.assertEqual(len(runner.calls), 1)
        call = runner.calls[0]
        self.assertIn(
            'pdf:writer_pdf_Export:{"PageRange":{"type":"string","value":"1"}}',
            call["command"],
        )
        environment = call["environment"]
        self.assertEqual(environment["HTTP_PROXY"], environment["HTTPS_PROXY"])
        self.assertTrue(environment["HTTP_PROXY"].startswith("http://127.0.0.1:"))
        self.assertNotIn("NO_PROXY", environment)
        self.assertNotIn("SC_FORCE_CALCULATION", environment)
        self.assertEqual(environment["SAL_DISABLE_OPENCL"], "1")
        self.assertIn('oor:name="DisableMacrosExecution"', call["policy"])
        self.assertIn('oor:name="Link" oor:op="fuse"><value>0', call["policy"])

    def test_preview_rejects_external_relationship_before_starting_the_engine(
        self,
    ) -> None:
        _write_docx(
            self.source,
            extra_entries={
                "word/_rels/document.xml.rels": (
                    b'<Relationships><Relationship TargetMode="External" '
                    b'Target="https://example.invalid/public"/></Relationships>'
                )
            },
        )
        before = self.source.read_bytes()
        result, runner = self._convert(preview=True)
        self.assertEqual(
            result.diagnostic_code, "documents_preview_requires_local_content"
        )
        self.assertFalse(runner.calls)
        self.assertEqual(before, self.source.read_bytes())

    def test_plain_text_renamed_docx_is_rejected(self) -> None:
        path = self.base / "renamed.docx"
        path.write_text("not zip", encoding="utf-8")
        with self.assertRaises(ValueError):
            validate_docx_input(path)

    def test_truncated_zip_is_rejected(self) -> None:
        path = self.base / "truncated.docx"
        _write_docx(path)
        path.write_bytes(path.read_bytes()[:20])
        with self.assertRaises(ValueError):
            validate_docx_input(path)

    def test_encrypted_zip_flag_is_rejected_before_engine(self) -> None:
        path = self.base / "encrypted.docx"
        _write_docx(path)
        _mark_zip_encrypted(path)
        with self.assertRaises(ValueError):
            validate_docx_input(path)

    def test_zip_without_word_structure_is_rejected(self) -> None:
        path = self.base / "not-word.docx"
        _write_docx(path, required=False, extra_entries={"data.txt": b"x"})
        with self.assertRaises(ValueError):
            validate_docx_input(path)

    def test_zip_traversal_is_rejected(self) -> None:
        path = self.base / "traversal.docx"
        _write_docx(path, extra_entries={"../escape.txt": b"x"})
        with self.assertRaises(ValueError):
            validate_docx_input(path)

    def test_zip_absolute_or_drive_entry_is_rejected(self) -> None:
        for name in ("/absolute.txt", "C:/drive.txt"):
            with self.subTest(name=name):
                path = self.base / f"unsafe-{len(name)}.docx"
                _write_docx(path, extra_entries={name: b"x"})
                with self.assertRaises(ValueError):
                    validate_docx_input(path)

        # O próprio zipfile normaliza a barra invertida no Windows antes de
        # gravá-la. A política pura ainda precisa rejeitar o nome bruto caso
        # um archive produzido por outra implementação o preserve.
        self.assertFalse(documents_tools._safe_zip_entry("word\\unsafe.xml"))

    def test_zip_symlink_entry_is_rejected(self) -> None:
        path = self.base / "symlink.docx"
        _write_docx(path)
        with zipfile.ZipFile(path, "a") as archive:
            link = zipfile.ZipInfo("word/link")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            archive.writestr(link, "target")
        with self.assertRaises(ValueError):
            validate_docx_input(path)

    def test_compression_ratio_limit_is_rejected(self) -> None:
        path = self.base / "ratio.docx"
        _write_docx(path, extra_entries={"word/repeated.bin": b"A" * 200_000})
        with self.assertRaises(ValueError):
            validate_docx_input(path)

    def test_entry_count_limit_is_rejected(self) -> None:
        path = self.base / "entries.docx"
        _write_docx(path, extra_entries={"word/a.txt": b"a"})
        with mock.patch.object(documents_tools, "DOCX_MAX_ENTRIES", 2):
            with self.assertRaises(ValueError):
                validate_docx_input(path)

    def test_expanded_size_and_entry_size_limits_are_rejected(self) -> None:
        path = self.base / "limits.docx"
        _write_docx(path, extra_entries={"word/a.bin": b"abcdefghij"})
        with mock.patch.object(documents_tools, "DOCX_MAX_ENTRY_BYTES", 9):
            with self.assertRaises(ValueError):
                validate_docx_input(path)
        with mock.patch.object(documents_tools, "DOCX_MAX_EXPANDED_BYTES", 10):
            with self.assertRaises(ValueError):
                validate_docx_input(path)

    def test_archive_file_size_limit_is_rejected(self) -> None:
        with mock.patch.object(
            documents_tools, "DOCX_MAX_FILE_BYTES", self.source.stat().st_size - 1
        ):
            with self.assertRaises(ValueError):
                validate_docx_input(self.source)

    def test_relative_removed_unc_and_wrong_extension_are_rejected(self) -> None:
        wrong = self.base / "document.zip"
        _write_docx(wrong)
        removed = self.base / "removed.docx"
        _write_docx(removed)
        removed.unlink()
        for value in (
            Path("relative.docx"),
            removed,
            wrong,
            Path(r"\\server\share\document.docx"),
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_docx_input(value)

    def test_reparse_input_is_rejected_when_supported(self) -> None:
        link = self.base / "link.docx"
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest("O host não permite criar symlink sem elevação.")
        with self.assertRaises(ValueError):
            validate_docx_input(link)

    def test_command_and_environment_are_explicit_and_hardened(self) -> None:
        profile = self.base / "Perfil João"
        staging = self.base / "Saída com espaços"
        command = build_libreoffice_command(
            self.component, self.source, staging, profile
        )
        self.assertEqual(command[0], str(self.component.soffice_entrypoint))
        self.assertIn("--headless", command)
        self.assertEqual(command[command.index("--outdir") + 1], str(staging))
        self.assertTrue(command[1].startswith("-env:UserInstallation=file:"))
        environment = build_libreoffice_environment(self.component, self.base / "tmp")
        self.assertEqual(environment["PYTHONHOME"], str(self.component.python_home))
        self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(environment["TEMP"], str(self.base / "tmp"))
        self.assertNotIn(
            str(self.component.soffice_entrypoint), environment.get("PATH", "")
        )

    def test_success_uses_security_policy_validates_and_publishes_pdf(self) -> None:
        result, runner = self._convert()
        self.assertEqual(result.status, DocumentConversionStatus.COMPLETED)
        self.assertEqual(result.output_path, self.base / "Saída João.pdf")
        self.assertEqual(len(PdfReader(result.output_path).pages), 1)
        call = runner.calls[0]
        policy = call["policy"]
        self.assertIn("DisableMacrosExecution", policy)
        self.assertIn("DisableActiveContent", policy)
        self.assertIn("MacroSecurityLevel", policy)
        self.assertIn("BlockUntrustedRefererLinks", policy)
        self.assertNotIn("Trusted", policy)
        self.assertEqual(call["cwd"], self.component.soffice_entrypoint.parent)
        self.assertEqual(
            call["timeout"], documents_tools.DOCUMENT_CONVERSION_TIMEOUT_SECONDS
        )

    def test_component_absent_and_corrupted_are_controlled(self) -> None:
        for status in (
            DocumentsComponentStatus.NOT_CONFIGURED,
            DocumentsComponentStatus.CORRUPTED,
        ):
            with self.subTest(status=status):
                service = DocumentsConversionService(
                    component_service=_FakeComponentService(None, status)
                )
                result = service.convert(
                    DocumentConversionRequest(self.source, self.base / "out.pdf")
                )
                self.assertEqual(
                    result.status, DocumentConversionStatus.COMPONENT_UNAVAILABLE
                )
                self.assertIsNone(result.output_path)

    def test_existing_output_requires_overwrite(self) -> None:
        output = self.base / "existing.pdf"
        output.write_bytes(b"old")
        result, runner = self._convert(output=output)
        self.assertEqual(result.status, DocumentConversionStatus.OUTPUT_EXISTS)
        self.assertEqual(output.read_bytes(), b"old")
        self.assertEqual(runner.calls, [])

    def test_output_must_be_absolute_pdf_and_distinct(self) -> None:
        for output in (Path("relative.pdf"), self.base / "out.txt", self.source):
            with self.subTest(output=output):
                runner = _FakeRunner()
                service = DocumentsConversionService(
                    component_service=self.component_service,
                    process_runner=runner,
                )
                result = service.convert(DocumentConversionRequest(self.source, output))
                self.assertEqual(result.status, DocumentConversionStatus.INVALID_INPUT)
                self.assertEqual(runner.calls, [])

    def test_cancelled_late_never_publishes_and_preserves_previous_output(self) -> None:
        output = self.base / "previous.pdf"
        output.write_bytes(b"previous")
        event = threading.Event()
        result, _runner = self._convert(
            "cancelled_late",
            output=output,
            overwrite=True,
            cancel_event=event,
        )
        self.assertEqual(result.status, DocumentConversionStatus.CANCELLED)
        self.assertEqual(output.read_bytes(), b"previous")

    def test_timeout_and_failure_preserve_previous_output(self) -> None:
        for behavior, code in (
            ("timeout", "documents_conversion_timeout"),
            ("failure", "documents_engine_failed"),
        ):
            with self.subTest(behavior=behavior):
                output = self.base / f"{behavior}.pdf"
                output.write_bytes(b"previous")
                result, _runner = self._convert(behavior, output=output, overwrite=True)
                self.assertEqual(result.status, DocumentConversionStatus.ERROR)
                self.assertEqual(result.diagnostic_code, code)
                self.assertEqual(output.read_bytes(), b"previous")

    def test_missing_engine_output_is_rejected_and_preserves_previous_output(
        self,
    ) -> None:
        output = self.base / "no-output.pdf"
        output.write_bytes(b"previous")
        result, _runner = self._convert("no_output", output=output, overwrite=True)
        self.assertEqual(result.status, DocumentConversionStatus.ERROR)
        self.assertEqual(result.diagnostic_code, "documents_unexpected_engine_output")
        self.assertEqual(output.read_bytes(), b"previous")

    def test_invalid_or_unexpected_engine_output_is_rejected(self) -> None:
        for behavior in ("invalid_pdf", "extra_output"):
            with self.subTest(behavior=behavior):
                output = self.base / f"{behavior}.pdf"
                output.write_bytes(b"previous")
                result, _runner = self._convert(behavior, output=output, overwrite=True)
                self.assertEqual(result.status, DocumentConversionStatus.ERROR)
                self.assertEqual(output.read_bytes(), b"previous")

    def test_writer_lock_is_not_published_and_operation_is_cleaned(self) -> None:
        result, _runner = self._convert("writer_lock")
        self.assertEqual(result.status, DocumentConversionStatus.COMPLETED)
        self.assertTrue(result.output_path.is_file())
        self.assertEqual(list((self.base / "operations").iterdir()), [])

    def test_known_pythonhome_warning_is_internal_diagnostic(self) -> None:
        result, _runner = self._convert("pythonhome_warning")
        self.assertEqual(result.status, DocumentConversionStatus.ERROR)
        self.assertEqual(result.diagnostic_code, "documents_pythonhome_warning")
        self.assertNotIn("prefix", result.public_message)

    def test_replace_failure_restores_previous_output(self) -> None:
        output = self.base / "replace.pdf"
        output.write_bytes(b"previous")
        real_replace = os.replace

        def fail_candidate(source: object, destination: object) -> None:
            source_path = Path(source)
            destination_path = Path(destination)
            if destination_path == output and source_path.name.endswith(".pending.pdf"):
                raise OSError("simulated replacement failure")
            real_replace(source, destination)

        with mock.patch.object(
            documents_tools.os, "replace", side_effect=fail_candidate
        ):
            result, _runner = self._convert(output=output, overwrite=True)
        self.assertEqual(result.status, DocumentConversionStatus.ERROR)
        self.assertEqual(output.read_bytes(), b"previous")
        self.assertEqual(list(self.base.glob("*.backup.pdf")), [])
        self.assertEqual(list(self.base.glob("*.pending.pdf")), [])

    def test_backup_cleanup_failure_restores_previous_output(self) -> None:
        output = self.base / "backup-cleanup.pdf"
        previous = b"previous"
        output.write_bytes(previous)
        real_unlink = Path.unlink

        def fail_populated_backup(path: Path, *args: object, **kwargs: object) -> None:
            if (
                path.name.endswith(".backup.pdf")
                and path.exists()
                and path.stat().st_size == len(previous)
            ):
                raise OSError("simulated backup cleanup failure")
            real_unlink(path, *args, **kwargs)

        with mock.patch.object(
            Path, "unlink", autospec=True, side_effect=fail_populated_backup
        ):
            result, _runner = self._convert(output=output, overwrite=True)
        self.assertEqual(result.status, DocumentConversionStatus.ERROR)
        self.assertEqual(output.read_bytes(), previous)
        self.assertEqual(list(self.base.glob("*.backup.pdf")), [])

    def test_input_original_is_not_modified(self) -> None:
        before = self.source.read_bytes()
        self._convert()
        self.assertEqual(self.source.read_bytes(), before)

    def test_temporary_cleanup_handles_read_only_profile_files(self) -> None:
        root = self.base / "owned-operation"
        root.mkdir()
        readonly = root / "profile-template.txt"
        readonly.write_text("profile", encoding="utf-8")
        readonly.chmod(stat.S_IREAD)
        self.assertTrue(documents_tools._remove_operation_root(root))
        self.assertFalse(root.exists())

    def test_ratio_constant_is_exactly_defensive_contract(self) -> None:
        self.assertEqual(DOCX_MAX_COMPRESSION_RATIO, 100.0)


@unittest.skipUnless(os.name == "nt", "Windows Job Object test")
class WindowsJobObjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _start(self, command: list[str], stem: str) -> _WindowsJobProcess:
        return _WindowsJobProcess.start(
            command,
            dict(os.environ),
            self.base,
            self.base / f"{stem}.stdout",
            self.base / f"{stem}.stderr",
        )

    def test_cancelling_job_terminates_child_tree(self) -> None:
        pid_file = self.base / "child.pid"
        child_code = "import time; time.sleep(30)"
        parent_code = (
            "import pathlib,subprocess,sys,time;"
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
            f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid));"
            "time.sleep(30)"
        )
        with self._start([sys.executable, "-c", parent_code], "tree") as job:
            deadline = time.monotonic() + 5
            child_pid = None
            while time.monotonic() < deadline:
                if pid_file.exists():
                    pid_text = pid_file.read_text(encoding="utf-8").strip()
                    if pid_text.isdecimal():
                        child_pid = int(pid_text)
                        break
                time.sleep(0.02)
            self.assertIsNotNone(child_pid)
            event = threading.Event()
            event.set()
            outcome = job.wait(event, 10)
            self.assertTrue(outcome.cancelled)
            self.assertTrue(outcome.tree_stopped)
        deadline = time.monotonic() + 2
        while _pid_running(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(_pid_running(child_pid))

    def test_two_jobs_are_isolated(self) -> None:
        command = [sys.executable, "-c", "import time; time.sleep(30)"]
        with (
            self._start(command, "a") as first,
            self._start(command, "b") as second,
        ):
            cancel = threading.Event()
            cancel.set()
            first_outcome = first.wait(cancel, 10)
            self.assertTrue(first_outcome.tree_stopped)
            self.assertTrue(_process_handle_running(second.process_handle))
            self.assertTrue(second.terminate())

    def test_wait_tracks_child_after_launcher_exits(self) -> None:
        parent_code = (
            "import subprocess,sys;"
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(0.4)'])"
        )
        started = time.monotonic()
        with self._start([sys.executable, "-c", parent_code], "launcher") as job:
            outcome = job.wait(threading.Event(), 5)
        self.assertEqual(outcome.returncode, 0)
        self.assertTrue(outcome.tree_stopped)
        self.assertGreaterEqual(time.monotonic() - started, 0.25)


def _process_handle_running(handle: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    result = kernel32.WaitForSingleObject(handle, 0)
    return result == documents_tools.WAIT_TIMEOUT


def _pid_running(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        return _process_handle_running(handle)
    finally:
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    unittest.main()
