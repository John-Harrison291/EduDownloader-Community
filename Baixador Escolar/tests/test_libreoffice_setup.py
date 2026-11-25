"""Resolução offline e setup 2.0: fixtures sintéticas, sem download/instalação real."""

from __future__ import annotations

import os
import json
import tempfile
import threading
import unittest
import subprocess
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from documents_component import (
    ENGINE_VERSION,
    DocumentsComponentService,
    DocumentsComponentStatus,
    windows_libreoffice_roots,
)
from libreoffice_managed import (
    AcquisitionError,
    AcquisitionStatus,
    LibreOfficeAcquisitionService,
    InstallerPending,
    OfficialGuidedInstaller,
    detected_component_path,
    documents_data_root,
    resolve_managed_component,
)
from tests.test_documents_component import SyntheticUserRuntime
from tests.test_libreoffice_managed import FakeInstaller, FakeTransport
from dataclasses import replace
import hashlib
from libreoffice_managed import APPROVED_BASELINE


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.service = DocumentsComponentService()
        self.enterContext(
            patch(
                "documents_component._windows_file_version", return_value=ENGINE_VERSION
            )
        )

    def test_valid_preference_precedes_system_and_managed(self):
        explicit = SyntheticUserRuntime(self.base, name="chosen").root
        other = SyntheticUserRuntime(self.base, name="other").root
        self.assertEqual(
            self.service.discover(
                explicit, system=(other,), managed=(other,)
            ).component.root,
            explicit,
        )

    def test_missing_preference_falls_back_to_system_before_managed(self):
        system = SyntheticUserRuntime(self.base, name="system").root
        managed = SyntheticUserRuntime(self.base, name="managed").root
        self.assertEqual(
            self.service.discover(
                self.base / "removed", system=(system,), managed=(managed,)
            ).component.root,
            system,
        )

    def test_invalid_system_falls_back_to_managed_offline(self):
        managed = SyntheticUserRuntime(self.base).root
        self.assertEqual(
            self.service.discover(
                system=(self.base / "bad",), managed=(managed,)
            ).component.root,
            managed,
        )

    def test_absence_is_not_ready_and_no_directories_are_created(self):
        self.assertEqual(
            self.service.discover(system=()).status,
            DocumentsComponentStatus.NOT_CONFIGURED,
        )
        self.assertEqual(list(self.base.iterdir()), [])

    def test_duplicate_candidates_checked_once(self):
        with patch.object(
            self.service, "fast_check", wraps=self.service.fast_check
        ) as checker:
            self.service.discover(self.base, system=(self.base,), managed=(self.base,))
        self.assertEqual(checker.call_count, 2)  # candidato + resultado NOT_CONFIGURED

    def native(self):
        return SyntheticUserRuntime(self.base, name="LibreOffice nativo João").root

    def test_native_known_engine_without_portable_launcher(self):
        root = self.native()
        result = self.service.fast_check(root)
        self.assertEqual(result.status, DocumentsComponentStatus.AVAILABLE)
        self.assertEqual(
            result.component.soffice_entrypoint, root / "program/soffice.com"
        )
        self.assertFalse((root / "LibreOfficePortable.exe").exists())

    def test_native_incomplete_rejected(self):
        root = self.native()
        (root / "program/mergedlo.dll").unlink()
        self.assertEqual(
            self.service.fast_check(root).status, DocumentsComponentStatus.CORRUPTED
        )

    def test_fake_executable_not_probed_or_executed(self):
        root = self.native()
        (root / "program/soffice.exe").write_bytes(b"fake")
        with patch("documents_component._windows_file_version") as probe:
            self.assertEqual(
                self.service.fast_check(root).status, DocumentsComponentStatus.CORRUPTED
            )
            probe.assert_not_called()

    def test_native_unapproved_engine_fail_closed(self):
        root = self.native()
        with patch(
            "documents_component._windows_file_version", return_value="99.0.0.0"
        ):
            self.assertEqual(
                self.service.fast_check(root).status,
                DocumentsComponentStatus.VERSION_MISMATCH,
            )

    def test_removed_installation_is_detected_again(self):
        root = SyntheticUserRuntime(self.base).root
        self.assertIsNotNone(self.service.discover(root, system=()).component)
        root.rename(self.base / "moved")
        self.assertIsNone(self.service.discover(root, system=()).component)

    def test_windows_discovery_is_bounded_and_ignores_command_strings(self):
        import winreg
        from unittest.mock import MagicMock

        key = MagicMock()
        native = self.base / "native/program/soffice.exe"
        with (
            patch("winreg.OpenKey", return_value=key) as opened,
            patch(
                "winreg.QueryValueEx",
                side_effect=[
                    (str(native), winreg.REG_SZ),
                    (str(native) + " --flag", winreg.REG_SZ),
                ],
            ),
            patch.dict(
                os.environ,
                {
                    "ProgramFiles": str(self.base / "programs"),
                    "ProgramFiles(x86)": str(self.base / "programs x86"),
                    "PATH": str(self.base / "untrusted"),
                },
            ),
        ):
            roots = windows_libreoffice_roots()
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(
            roots,
            (
                native.parent.parent,
                self.base / "programs/LibreOffice",
                self.base / "programs x86/LibreOffice",
            ),
        )

    def test_windows_registry_unavailable_keeps_standard_candidates(self):
        with (
            patch("winreg.OpenKey", side_effect=PermissionError),
            patch.dict(
                os.environ, {"ProgramFiles": str(self.base), "ProgramFiles(x86)": ""}
            ),
        ):
            self.assertEqual(windows_libreoffice_roots(), (self.base / "LibreOffice",))


class UserDataSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ,
            {
                "LOCALAPPDATA": str(self.base / "Dados João 你好"),
                "USERPROFILE": str(self.base / "perfil"),
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.length = patch("libreoffice_managed._MAX_COMPONENT_PATH_LENGTH", 1000)
        self.length.start()
        self.addCleanup(self.length.stop)
        payload = b"mock verified installer"
        self.baseline = replace(
            APPROVED_BASELINE,
            installer_size=len(payload),
            installer_sha256=hashlib.sha256(payload).hexdigest().upper(),
        )
        baseline_patch = patch("libreoffice_managed.APPROVED_BASELINE", self.baseline)
        baseline_patch.start()
        self.addCleanup(baseline_patch.stop)
        self.enterContext(
            patch(
                "documents_component._windows_file_version", return_value=ENGINE_VERSION
            )
        )
        self.transport = FakeTransport(payload)
        self.installer = FakeInstaller()
        # Esta suíte testa o contrato de instalação com um MSI e uma imagem
        # sintéticos. A homologação separada verifica MSI e conversões reais.
        self.signature = self.enterContext(
            patch("libreoffice_managed._verified_windows_msi", return_value=True)
        )
        self.enterContext(
            patch.object(
                LibreOfficeAcquisitionService, "_record_owned_image", autospec=True
            )
        )
        self.app = self.base / "app inexistente e sem escrita"
        self.service = LibreOfficeAcquisitionService(
            self.app,
            user_data=True,
            baseline=self.baseline,
            transport=self.transport,
            installer=self.installer,
        )

    def test_auto_creation_unicode_and_no_app_root_write(self):
        result = self.service.install(cancel=threading.Event())
        self.assertEqual(result.status, AcquisitionStatus.INSTALLED)
        self.signature.assert_called_once()
        self.assertFalse(self.app.exists())
        self.assertEqual(
            resolve_managed_component(documents_data_root()), result.component_root
        )
        self.assertEqual(
            list(
                (documents_data_root() / "Componentes/.staging/libreoffice").iterdir()
            ),
            [],
        )
        self.assertTrue(self.installer.arguments[0].name.endswith(".msi"))
        self.assertFalse(self.installer.arguments[0].exists())
        with patch("documents_component.windows_libreoffice_roots", return_value=()):
            self.assertEqual(
                detected_component_path({}, self.app, DocumentsComponentService()),
                result.component_root,
            )

    def test_manual_mode_rejects_unsigned_msi_without_activating_an_image(self):
        self.signature.return_value = False
        result = self.service.install(cancel=threading.Event())
        self.assertEqual(result.diagnostic_code, "installer_signature_mismatch")
        self.assertIsNone(resolve_managed_component(documents_data_root()))
        self.assertFalse((documents_data_root() / "Componentes/L").exists())

    def test_legacy_metadata_with_missing_image_can_be_replaced(self):
        managed = documents_data_root() / "Componentes"
        managed.mkdir(parents=True)
        metadata = managed / "active.json"
        metadata.write_text(
            json.dumps(
                {
                    "component_id": APPROVED_BASELINE.component_id,
                    "display_version": "26.2.4",
                    "installer_sha256": "0" * 64,
                    "relative_path": "L",
                }
            ),
            encoding="utf-8",
        )
        self.assertIsNone(resolve_managed_component(documents_data_root()))
        result = self.service.install(cancel=threading.Event())
        self.assertEqual(result.status, AcquisitionStatus.INSTALLED)
        self.assertEqual(result.component_root, managed / "L")
        self.assertEqual(
            resolve_managed_component(documents_data_root()), result.component_root
        )

    def test_data_permission_failure_no_download_or_app_fallback(self):
        with patch(
            "libreoffice_managed.documents_data_root",
            side_effect=AcquisitionError("managed_root_unavailable"),
        ):
            result = self.service.install(cancel=threading.Event())
        self.assertEqual(result.status, AcquisitionStatus.FAILED)
        self.assertEqual(self.transport.calls, 0)
        self.assertFalse(self.app.exists())

    def test_missing_environment_fail_closed(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": ""}):
            with self.assertRaises(AcquisitionError):
                documents_data_root()

    def test_retry_preserves_partial_installation(self):
        self.service.installer = FakeInstaller(create_runtime=False)
        first = self.service.install(cancel=threading.Event())
        self.assertEqual(first.status, AcquisitionStatus.FAILED)
        parent = documents_data_root() / "Componentes/L"
        (parent / "partial.txt").write_text("synthetic incomplete extraction")
        self.service.installer = self.installer
        second = self.service.install(cancel=threading.Event())
        self.assertEqual(second.status, AcquisitionStatus.INSTALLED)
        self.assertNotEqual(second.component_root, parent)
        self.assertTrue((parent / "partial.txt").exists())

    def test_network_failure_and_retry_preserve_state(self):
        with patch.object(
            self.transport, "download", side_effect=AcquisitionError("network_failure")
        ):
            failed = self.service.install(cancel=threading.Event())
        self.assertEqual(failed.diagnostic_code, "network_failure")
        self.assertIsNone(resolve_managed_component(documents_data_root()))
        self.assertEqual(self.installer.calls, 0)
        self.assertEqual(
            self.service.install(cancel=threading.Event()).status,
            AcquisitionStatus.INSTALLED,
        )

    def test_delayed_installer_preserves_stage_and_rechecks_without_worker(self):
        state = {"exit": None}
        process = SimpleNamespace(poll=lambda: state["exit"])

        class DelayedInstaller:
            def run(self, installer, parent, on_opened):
                SyntheticUserRuntime(parent.parent, name=parent.name)
                on_opened()
                raise InstallerPending(process)

        self.service.installer = DelayedInstaller()
        first = self.service.install(cancel=threading.Event())
        self.assertEqual(first.diagnostic_code, "installer_pending")
        self.assertTrue(self.service.has_pending_installer)
        stage_parent = documents_data_root() / "Componentes/.staging/libreoffice"
        self.assertEqual(len(list(stage_parent.iterdir())), 1)
        self.assertIsNone(resolve_managed_component(documents_data_root()))
        self.assertEqual(
            self.service.finish_pending_installation().status, AcquisitionStatus.BUSY
        )
        self.assertEqual(
            self.service.install(cancel=threading.Event()).status,
            AcquisitionStatus.BUSY,
        )
        state["exit"] = 0
        self.assertEqual(
            self.service.finish_pending_installation().status,
            AcquisitionStatus.INSTALLED,
        )
        self.assertFalse(self.service.has_pending_installer)
        self.assertEqual(list(stage_parent.iterdir()), [])

    def test_official_wait_is_bounded_without_killing_installer(self):
        from unittest.mock import Mock

        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired("official installer", 900)
        with patch("libreoffice_managed.subprocess.Popen", return_value=process):
            with self.assertRaises(InstallerPending):
                OfficialGuidedInstaller().run(
                    self.base / "verified.msi", self.base, lambda: None
                )
        process.wait.assert_called_once_with(timeout=900)
        process.kill.assert_not_called()
        process.terminate.assert_not_called()

    def test_recheck_never_waits_on_download_or_installer_worker(self):
        self.service._lock.acquire()
        try:
            self.assertIsNone(self.service.finish_pending_installation())
        finally:
            self.service._lock.release()
