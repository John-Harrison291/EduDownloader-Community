"""Contratos offline da aquisição assistida do MSI do LibreOffice."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from component_transactions import component_lock
from libreoffice_managed import (
    APPROVED_BASELINE,
    AcquisitionCancelled,
    AcquisitionError,
    AcquisitionStatus,
    LibreOfficeAcquisitionService,
    LibreOfficeTransport,
    OfficialGuidedInstaller,
    _check_url,
    configured_component_path,
    managed_component_root,
    resolve_managed_component,
)
from settings import load_settings, save_settings
from tests.test_documents_component import SyntheticUserRuntime


class FakeTransport:
    def __init__(self, content: bytes, *, cancel_during: bool = False) -> None:
        self.content = content
        self.cancel_during = cancel_during
        self.calls = 0

    def download(self, baseline, destination, cancel, progress):
        self.calls += 1
        destination.write_bytes(self.content)
        if progress is not None:
            progress(len(self.content), len(self.content))
        if self.cancel_during:
            cancel.set()
            raise AcquisitionCancelled
        return hashlib.sha256(self.content).hexdigest().upper()


class FakeInstaller:
    def __init__(self, *, exit_code: int = 0, create_runtime: bool = True) -> None:
        self.exit_code = exit_code
        self.create_runtime = create_runtime
        self.calls = 0
        self.arguments = None

    def run(self, installer, destination_parent, on_opened):
        self.calls += 1
        self.arguments = (installer, destination_parent)
        on_opened()
        if self.create_runtime:
            SyntheticUserRuntime(
                destination_parent.parent, name=destination_parent.name
            )
        return self.exit_code


class ManagedLibreOfficeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name) / "portable app"
        self.base.mkdir()
        self.payload = b"synthetic official installer"
        self.baseline = replace(
            APPROVED_BASELINE,
            installer_size=len(self.payload),
            installer_sha256=hashlib.sha256(self.payload).hexdigest().upper(),
        )
        self.transport = FakeTransport(self.payload)
        self.installer = FakeInstaller()
        self.service = LibreOfficeAcquisitionService(
            self.base,
            baseline=self.baseline,
            transport=self.transport,
            installer=self.installer,
        )
        self.length_patch = patch(
            "libreoffice_managed._MAX_COMPONENT_PATH_LENGTH", 1000
        )
        self.length_patch.start()
        self.baseline_patch = patch(
            "libreoffice_managed.APPROVED_BASELINE", self.baseline
        )
        self.baseline_patch.start()
        self.enterContext(
            patch(
                "documents_component._windows_file_version",
                return_value=APPROVED_BASELINE.engine_version,
            )
        )

    def tearDown(self) -> None:
        self.baseline_patch.stop()
        self.length_patch.stop()
        self.temporary.cleanup()

    def test_baseline_exact_identity_and_https_host_policy(self) -> None:
        manifest = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "docs"
                / "compliance"
                / "documents"
                / "LIBREOFFICE_MANAGED_BASELINE.json"
            ).read_text(encoding="utf-8")
        )
        for key in (
            "component_id",
            "publisher",
            "display_version",
            "package_version",
            "engine_version",
            "variant",
            "architecture",
            "installer_filename",
            "installer_sha256",
            "authority_url",
            "compatibility",
        ):
            self.assertEqual(manifest[key], getattr(APPROVED_BASELINE, key))
        self.assertEqual(
            manifest["installer_size_bytes"], APPROVED_BASELINE.installer_size
        )
        self.assertEqual(APPROVED_BASELINE.display_version, "26.8.3")
        self.assertEqual(APPROVED_BASELINE.package_version, "26.8.3.1")
        self.assertEqual(APPROVED_BASELINE.variant, "MSI")
        self.assertEqual(APPROVED_BASELINE.installer_size, 376_311_808)
        self.assertEqual(manifest["download_url"], APPROVED_BASELINE.download_url)
        self.assertEqual(len(APPROVED_BASELINE.installer_sha256), 64)
        _check_url(APPROVED_BASELINE.download_url)
        for url in (
            "http://tdf.c3sl.ufpr.br/file",
            "https://tdf.c3sl.ufpr.br.evil.invalid/file",
            "https://evil.invalid/file",
            "https://tdf.c3sl.ufpr.br:444/file",
            "https://user@tdf.c3sl.ufpr.br/file",
        ):
            with self.subTest(url=url), self.assertRaises(AcquisitionError):
                _check_url(url)

    def test_verified_guided_install_activates_relative_path(self) -> None:
        phases = []
        progress = []
        result = self.service.install(
            cancel=threading.Event(),
            phase=phases.append,
            progress=lambda done, total: progress.append((done, total)),
            await_launch=lambda parent: parent,
        )
        self.assertIs(result.status, AcquisitionStatus.INSTALLED)
        self.assertEqual(result.component_root, managed_component_root(self.base))
        self.assertEqual(
            phases, ["download", "installer", "installer_opened", "verify"]
        )
        self.assertEqual(progress, [(len(self.payload), len(self.payload))])
        self.assertEqual(self.installer.calls, 1)
        self.assertEqual(resolve_managed_component(self.base), result.component_root)
        active = json.loads(
            (self.base / "Componentes" / "active.json").read_text(encoding="utf-8")
        )
        self.assertEqual(active["relative_path"], "L")
        self.assertEqual(active["installer_sha256"], self.baseline.installer_sha256)
        self.assertEqual(
            {item.name for item in (self.base / "Componentes").iterdir()},
            {"L", "active.json", ".locks", ".staging"},
        )

    def test_hash_mismatch_never_executes_installer(self) -> None:
        self.transport.content = b"different same-size content"[: len(self.payload)]
        result = self.service.install(cancel=threading.Event())
        self.assertIs(result.status, AcquisitionStatus.FAILED)
        self.assertEqual(result.diagnostic_code, "hash_mismatch")
        self.assertEqual(self.installer.calls, 0)
        self.assertFalse((self.base / "Componentes" / "active.json").exists())
        self.assertFalse(
            list((self.base / "Componentes" / ".staging" / "libreoffice").iterdir())
        )

    def test_download_cancel_keeps_no_stage_or_component(self) -> None:
        self.transport.cancel_during = True
        result = self.service.install(cancel=threading.Event())
        self.assertIs(result.status, AcquisitionStatus.CANCELLED)
        self.assertEqual(self.installer.calls, 0)
        self.assertFalse((self.base / "Componentes" / "active.json").exists())
        self.assertFalse(
            list((self.base / "Componentes" / ".staging" / "libreoffice").iterdir())
        )

    def test_installer_cancel_or_destination_change_never_activates(self) -> None:
        for exit_code, create_runtime in ((0, False), (1, True)):
            with self.subTest(exit_code=exit_code, create_runtime=create_runtime):
                self.installer = FakeInstaller(
                    exit_code=exit_code, create_runtime=create_runtime
                )
                self.service.installer = self.installer
                result = self.service.install(cancel=threading.Event())
                self.assertIs(result.status, AcquisitionStatus.FAILED)
                self.assertIsNone(resolve_managed_component(self.base))
                self.assertFalse((self.base / "Componentes" / "active.json").exists())

    def test_existing_managed_is_not_reinstalled(self) -> None:
        first = self.service.install(cancel=threading.Event())
        self.assertIs(first.status, AcquisitionStatus.INSTALLED)
        second = self.service.install(cancel=threading.Event())
        self.assertIs(second.status, AcquisitionStatus.FAILED)
        self.assertEqual(second.diagnostic_code, "already_installed_or_needs_repair")
        self.assertEqual(self.transport.calls, 1)

    def test_guided_repair_keeps_previous_until_verified_and_uses_relative_root(
        self,
    ) -> None:
        first = self.service.install(cancel=threading.Event())
        self.assertIs(first.status, AcquisitionStatus.INSTALLED)
        original = first.component_root
        pointer = self.base / "Componentes" / "active.json"
        previous_metadata = pointer.read_bytes()
        failing = FakeInstaller(exit_code=1, create_runtime=False)
        self.service.installer = failing
        failed = self.service.install(cancel=threading.Event(), repair=True)
        self.assertIs(failed.status, AcquisitionStatus.FAILED)
        self.assertEqual(pointer.read_bytes(), previous_metadata)
        self.assertTrue(original.is_dir())
        self.service.installer = FakeInstaller()
        repaired = self.service.install(cancel=threading.Event(), repair=True)
        self.assertIs(repaired.status, AcquisitionStatus.INSTALLED)
        self.assertNotEqual(repaired.component_root, original)
        self.assertTrue(original.is_dir())
        self.assertEqual(resolve_managed_component(self.base), repaired.component_root)
        metadata = json.loads(pointer.read_text(encoding="utf-8"))
        self.assertTrue(metadata["relative_path"].startswith("L-repair-"))

    def test_corrupted_managed_pointer_never_resolves_traversal(self) -> None:
        self.assertIs(
            self.service.install(cancel=threading.Event()).status,
            AcquisitionStatus.INSTALLED,
        )
        pointer = self.base / "Componentes" / "active.json"
        metadata = json.loads(pointer.read_text(encoding="utf-8"))
        # Caminho absoluto local é intencionalmente permitido para MANAGED_EXTERNAL_ROOT.
        for bad in ("../outside", "\\\\server\\share", ""):
            with self.subTest(path=bad):
                metadata.pop("relative_path", None)
                metadata["external_path"] = bad
                pointer.write_text(json.dumps(metadata), encoding="utf-8")
                self.assertIsNone(resolve_managed_component(self.base))

    def test_repair_metadata_write_failure_preserves_previous_pointer(self) -> None:
        first = self.service.install(cancel=threading.Event())
        self.assertIs(first.status, AcquisitionStatus.INSTALLED)
        pointer = self.base / "Componentes" / "active.json"
        previous = pointer.read_bytes()
        replacement = self.base / "Componentes" / "L-repair-12345678"
        SyntheticUserRuntime(replacement.parent, name=replacement.name)
        with patch("libreoffice_managed.os.replace", side_effect=PermissionError):
            failed = self.service.verify_installation(replacement, repair=True)
        self.assertIs(failed.status, AcquisitionStatus.FAILED)
        self.assertEqual(pointer.read_bytes(), previous)
        self.assertEqual(resolve_managed_component(self.base), first.component_root)

    def test_other_instance_lock_blocks_guided_install(self) -> None:
        with component_lock(self.base / "Componentes", "libreoffice"):
            result = self.service.install(cancel=threading.Event())
        self.assertIs(result.status, AcquisitionStatus.BUSY)
        self.assertEqual(self.transport.calls, 0)
        self.assertFalse((self.base / "Componentes" / "active.json").exists())

    def test_read_only_and_low_space_fail_before_download(self) -> None:
        with patch(
            "libreoffice_managed.probe_managed_root",
            return_value=SimpleNamespace(state="read-only"),
        ):
            self.assertEqual(
                self.service.install(cancel=threading.Event()).diagnostic_code,
                "managed_root_unavailable",
            )
        with patch(
            "libreoffice_managed.shutil.disk_usage",
            return_value=SimpleNamespace(free=0),
        ):
            self.assertEqual(
                self.service.install(cancel=threading.Event()).diagnostic_code,
                "insufficient_disk_space",
            )
        self.assertEqual(self.transport.calls, 0)

    def test_legacy_manual_settings_are_not_rewritten_and_survive_managed_choice(
        self,
    ) -> None:
        settings_path = self.base / "settings.json"
        manual = str(self.base / "manual LO")
        settings = save_settings(
            {
                "tema": "claro",
                "ultimo_tipo": "Vídeo MP4",
                "ultima_qualidade": "720p",
                "favorite_folders": [],
                "documents_component_path": manual,
            },
            settings_path,
        )
        before = settings_path.read_bytes()
        self.assertEqual(load_settings(settings_path), settings)
        self.assertEqual(settings_path.read_bytes(), before)
        self.assertEqual(configured_component_path(settings, self.base), manual)
        self.assertIs(
            self.service.install(cancel=threading.Event()).status,
            AcquisitionStatus.INSTALLED,
        )
        settings["documents_component_origin"] = "MANAGED"
        save_settings(settings, settings_path)
        self.assertEqual(
            configured_component_path(load_settings(settings_path), self.base),
            managed_component_root(self.base),
        )
        self.assertEqual(
            load_settings(settings_path)["documents_component_path"], manual
        )

    def test_managed_resolution_moves_with_portable_root(self) -> None:
        first = self.service.install(cancel=threading.Event())
        self.assertIs(first.status, AcquisitionStatus.INSTALLED)
        second = self.base.parent / "second portable app"
        self.base.rename(second)
        settings = {"documents_component_origin": "MANAGED"}
        self.assertEqual(
            configured_component_path(settings, second), managed_component_root(second)
        )
        self.assertFalse(
            str(configured_component_path(settings, second)).startswith(str(self.base))
        )

    def test_installer_runner_prefills_destination_without_silent_switch(self) -> None:
        fake = SimpleNamespace(wait=lambda **kwargs: 0)
        msiexec = Path(os.environ["SystemRoot"]) / "System32" / "msiexec.exe"
        payload = self.base / "installer.msi"
        with patch("libreoffice_managed.subprocess.Popen", return_value=fake) as popen:
            opened = []
            outcome = OfficialGuidedInstaller().run(
                payload,
                self.base,
                lambda: opened.append(True),
            )
        self.assertEqual(outcome, 0)
        self.assertEqual(opened, [True])
        prefix = subprocess.list2cmdline([str(msiexec), "/a", str(payload)])
        popen.assert_called_once_with(
            f'{prefix} TARGETDIR="{self.base}" /norestart',
            executable=str(msiexec),
            cwd=self.base,
            shell=False,
        )

    def test_ready_gate_cancel_and_external_explicit_destination(self) -> None:
        cancelled = self.service.install(
            cancel=threading.Event(), await_launch=lambda _parent: None
        )
        self.assertIs(cancelled.status, AcquisitionStatus.CANCELLED)
        self.assertEqual(self.installer.calls, 0)
        external = self.base.parent / "short managed location"
        external.mkdir()
        ready = []
        result = self.service.install(
            cancel=threading.Event(),
            await_launch=lambda parent: ready.append(parent) or external,
        )
        self.assertIs(result.status, AcquisitionStatus.INSTALLED)
        self.assertEqual(ready, [self.base / "Componentes" / "L"])
        self.assertEqual(result.component_root, external)
        self.assertEqual(resolve_managed_component(self.base), result.component_root)
        self.assertEqual(
            self.service.verify_installation(external).status,
            AcquisitionStatus.INSTALLED,
        )

    def test_manual_verify_only_expected_destination(self) -> None:
        parent = self.service.destination_parent()
        self.assertEqual(
            self.service.verify_installation(parent).diagnostic_code,
            "installed_structure_invalid",
        )
        SyntheticUserRuntime(parent.parent, name=parent.name)
        self.assertIs(
            self.service.verify_installation(parent).status,
            AcquisitionStatus.INSTALLED,
        )

    def test_default_path_policy_rejects_long_but_accepts_unicode(self) -> None:
        with patch("libreoffice_managed._MAX_COMPONENT_PATH_LENGTH", 1):
            with self.assertRaisesRegex(AcquisitionError, "managed_path_too_long"):
                self.service.destination_parent()
        self.assertEqual(
            self.service.destination_parent(self.base / "João 你好"),
            self.base / "João 你好",
        )

    def test_transport_streams_and_rejects_incomplete_or_bad_final_host(self) -> None:
        class Response:
            status = 200

            def __init__(self, content, url):
                self.content = content
                self.url = url
                self.headers = {"Content-Length": str(len(content))}
                self.offset = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def close(self):
                return None

            def geturl(self):
                return self.url

            def read(self, size):
                chunk = self.content[self.offset : self.offset + size]
                self.offset += len(chunk)
                return chunk

        class Opener:
            def __init__(self, response):
                self.response = response

            def open(self, *_args, **_kwargs):
                return self.response

        destination = self.base / "download.bin"
        with patch(
            "urllib.request.build_opener",
            return_value=Opener(Response(self.payload, self.baseline.download_url)),
        ):
            digest = LibreOfficeTransport().download(
                self.baseline, destination, threading.Event()
            )
        self.assertEqual(digest, self.baseline.installer_sha256)
        self.assertEqual(destination.read_bytes(), self.payload)
        destination.unlink()
        with patch(
            "urllib.request.build_opener",
            return_value=Opener(
                Response(self.payload[:-1], self.baseline.download_url)
            ),
        ):
            with self.assertRaisesRegex(AcquisitionError, "size_mismatch"):
                LibreOfficeTransport().download(
                    self.baseline, destination, threading.Event()
                )
        with patch(
            "urllib.request.build_opener",
            return_value=Opener(Response(self.payload, "https://evil.invalid/payload")),
        ):
            with self.assertRaisesRegex(AcquisitionError, "invalid_download_url"):
                LibreOfficeTransport().download(
                    self.baseline, destination, threading.Event()
                )
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
