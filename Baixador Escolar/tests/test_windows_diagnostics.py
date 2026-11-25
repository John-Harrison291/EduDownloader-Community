"""Read-only diagnostics, honest unknown states and bounded native inventory."""

from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import windows_diagnostics as d
from windows_signing import SigningError


class DiagnosticsTests(unittest.TestCase):
    def test_read_only_probe_does_not_create_or_claim_write_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = d.probe_directory(root)
            self.assertEqual(result["writable"], "not-tested")
            self.assertEqual(list(root.iterdir()), [])
            result = d.probe_directory(root, write=True)
            self.assertEqual(result["writable"], True)
            self.assertEqual(list(root.iterdir()), [])
            with patch(
                "windows_diagnostics.tempfile.TemporaryFile",
                side_effect=PermissionError,
            ):
                self.assertEqual(
                    d.probe_directory(root, write=True)["status"], "requires-attention"
                )
            self.assertFalse((root / "missing").exists())
            self.assertEqual(
                d.probe_directory(root / "missing")["status"], "requires-attention"
            )

    def test_inventory_is_explicit_bounded_and_marks_unsigned_or_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "native.dll").write_bytes(b"invalid PE")
            (root / "ordinary.txt").write_text("synthetic", "utf-8")
            result = d.inventory(root)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["status"], "requires-attention")
            self.assertEqual(result[0]["signature"]["status"], "not-tested")
            with patch.object(d, "MAX_NATIVE_FILES", 0), self.assertRaises(ValueError):
                d.native_files(root)
            with patch.object(d, "inspect_pe", side_effect=PermissionError):
                self.assertEqual(
                    d.inventory(root)[0]["reason"], "native-file-unavailable-or-limit"
                )
            with patch.object(
                d, "inspect_signature", side_effect=SigningError("unavailable")
            ):
                self.assertEqual(
                    d.inventory(root, signatures=True)[0]["signature"]["status"],
                    "not-tested",
                )
            with self.assertRaises(ValueError):
                d.native_files(Path("relative"))

    def test_missing_ocr_and_absent_pe_reader_do_not_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = d.ocr_check(root / "absent")
            self.assertEqual(
                result["portable-portuguese"]["status"], "requires-attention"
            )
            self.assertEqual(result["windows-ocr"]["status"], "not-tested")
            with patch.dict("sys.modules", {"pefile": None}):
                self.assertEqual(
                    d.inspect_pe(root / "absent.dll")["status"], "not-tested"
                )
            self.assertEqual(list(root.iterdir()), [])

    def test_default_report_does_not_collect_personal_or_activation_data(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"LOCALAPPDATA": temp}),
        ):
            root = Path(temp)
            report = d.collect_report(root)
            text = json.dumps(report)
            self.assertNotIn(temp.replace("\\", "\\\\"), text)
            self.assertEqual(report["clean_machine"]["status"], "not-tested")
            self.assertEqual(
                report["publisher_signing"]["status"], "blocked-by-external-dependency"
            )
            self.assertEqual(list(root.iterdir()), [])
