from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from documents_component import (
    COMPONENT_VERSION,
    ENGINE_VERSION,
    DocumentsComponentService,
    DocumentsComponentStatus,
)


class SyntheticUserRuntime:
    def __init__(self, parent: Path, *, name: str = "LibreOffice João 你好") -> None:
        self.root = parent / name
        self.program = self.root / "program"
        self.python_home = self.program / "python-core-3.12.13"
        (self.python_home / "bin").mkdir(parents=True)
        (self.root / "share" / "registry").mkdir(parents=True)
        (self.program / "version.ini").write_text(
            "[Version]\nVendor=The Document Foundation\n", encoding="utf-8"
        )
        for path in (
            self.program / "soffice.exe",
            self.program / "soffice.com",
            self.program / "soffice.bin",
            self.program / "mergedlo.dll",
            self.python_home / "bin" / "python.exe",
        ):
            path.write_bytes(
                b"MZ" + bytes(58) + (64).to_bytes(4, "little") + b"PE\0\0\x64\x86"
            )


class DocumentsComponentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.runtime = SyntheticUserRuntime(self.base)
        self.service = DocumentsComponentService(app_root=self.base / "app")
        self.enterContext(
            patch(
                "documents_component._windows_file_version", return_value=ENGINE_VERSION
            )
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_no_implicit_runtime_is_not_configured(self) -> None:
        result = self.service.fast_check()
        self.assertEqual(result.status, DocumentsComponentStatus.NOT_CONFIGURED)
        self.assertIsNone(result.component)

    def test_runtime_below_app_root_is_never_implicitly_selected(self) -> None:
        implicit = self.base / "app" / "components" / "documents"
        implicit.parent.mkdir(parents=True)
        self.runtime.root.rename(implicit)
        result = self.service.fast_check()
        self.assertEqual(result.status, DocumentsComponentStatus.NOT_CONFIGURED)

    def test_relative_path_is_invalid(self) -> None:
        result = self.service.fast_check(Path("LibreOfficePortable"))
        self.assertEqual(result.status, DocumentsComponentStatus.INVALID)

    def test_missing_path_is_invalid(self) -> None:
        result = self.service.fast_check(self.base / "ausente")
        self.assertEqual(result.status, DocumentsComponentStatus.INVALID)

    def test_official_msi_layout_is_available(self) -> None:
        result = self.service.fast_check(self.runtime.root)
        self.assertEqual(result.status, DocumentsComponentStatus.AVAILABLE)
        assert result.component is not None
        self.assertEqual(result.component.root, self.runtime.root)
        self.assertEqual(result.component.engine_root, self.runtime.root)
        self.assertEqual(result.component.engine_version, ENGINE_VERSION)
        self.assertEqual(result.component.component_version, COMPONENT_VERSION)
        self.assertEqual(
            result.component.soffice_entrypoint, self.runtime.program / "soffice.com"
        )

    def test_official_cp1252_metadata_is_accepted(self) -> None:
        (self.runtime.program / "version.ini").write_bytes(
            "[Version]\nVendor=The Document Foundation\nDescription=LibreOffice™\n".encode(
                "cp1252"
            )
        )
        result = self.service.fast_check(self.runtime.root)
        self.assertEqual(result.status, DocumentsComponentStatus.AVAILABLE)

    def test_full_verify_repeats_structural_validation(self) -> None:
        result = self.service.full_verify(self.runtime.root)
        self.assertEqual(result.status, DocumentsComponentStatus.AVAILABLE)
        self.assertEqual(
            result.diagnostic_code, "documents_runtime_full_verify_available"
        )

    def test_unrecognized_vendor_is_invalid(self) -> None:
        (self.runtime.program / "version.ini").write_text(
            "[Version]\nVendor=Example\n",
            encoding="utf-8",
        )
        result = self.service.fast_check(self.runtime.root)
        self.assertEqual(result.status, DocumentsComponentStatus.INVALID)

    def test_unsupported_version_is_version_mismatch(self) -> None:
        with patch(
            "documents_component._windows_file_version", return_value="26.2.4.2"
        ):
            result = self.service.fast_check(self.runtime.root)
        self.assertEqual(result.status, DocumentsComponentStatus.VERSION_MISMATCH)

    def test_legacy_portable_installation_is_never_used(self) -> None:
        portable = self.base / "Legacy"
        manifest = portable / "App" / "AppInfo" / "appinfo.ini"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("[Version]\nDisplayVersion=26.2.4\n", encoding="utf-8")
        result = self.service.fast_check(portable)
        self.assertEqual(result.status, DocumentsComponentStatus.VERSION_MISMATCH)
        self.assertIsNone(result.component)

    def test_missing_soffice_is_incomplete(self) -> None:
        (self.runtime.program / "soffice.com").unlink()
        result = self.service.fast_check(self.runtime.root)
        self.assertEqual(result.status, DocumentsComponentStatus.CORRUPTED)

    def test_mixed_engine_versions_are_rejected(self) -> None:
        with patch(
            "documents_component._windows_file_version",
            side_effect=[ENGINE_VERSION, ENGINE_VERSION, "26.2.4.2"],
        ):
            result = self.service.fast_check(self.runtime.root)
        self.assertEqual(result.status, DocumentsComponentStatus.VERSION_MISMATCH)

    def test_missing_python_runtime_is_incomplete(self) -> None:
        (self.runtime.python_home / "bin" / "python.exe").unlink()
        result = self.service.fast_check(self.runtime.root)
        self.assertEqual(result.status, DocumentsComponentStatus.CORRUPTED)

    def test_old_wrapper_is_not_accepted_as_runtime_root(self) -> None:
        wrapper = self.base / "legacy-component"
        nested = wrapper / "engine"
        nested.mkdir(parents=True)
        self.runtime.root.rename(nested / "LibreOfficePortable")
        (wrapper / "component-manifest.json").write_text("{}", encoding="utf-8")
        result = self.service.fast_check(wrapper)
        self.assertEqual(result.status, DocumentsComponentStatus.CORRUPTED)


if __name__ == "__main__":
    unittest.main()
