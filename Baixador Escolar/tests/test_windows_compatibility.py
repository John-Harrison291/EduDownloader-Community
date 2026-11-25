"""Windows preparation contracts; synthetic roots, no system configuration writes."""

from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import paths
from file_publication import publish_new_file
from windows_prerequisites import check_vc_runtime
from windows_metadata import metadata


def record(version=(14, 51, 36247, 0)):
    return {
        "Installed": 1,
        "Version": "v" + ".".join(map(str, version)),
        **dict(zip(("Major", "Minor", "Bld", "Rbld"), version)),
    }


class RuntimeTests(unittest.TestCase):
    def check(self, records):
        return check_vc_runtime(architecture="AMD64", reader=lambda: records)

    def test_absent_lower_equal_and_newer(self):
        self.assertEqual(self.check([]).reason, "runtime-absent")
        self.assertEqual(
            self.check([record((14, 44, 35211, 0))]).reason, "runtime-below-minimum"
        )
        self.assertEqual(self.check([record((14, 51, 0, 0))]).status, "ready")
        self.assertEqual(self.check([record((14, 60, 1, 0))]).status, "ready")

    def test_inconsistent_records_are_never_reported_sufficient(self):
        for records in (
            [record(), record((14, 52, 1, 0))],
            [record(), {"Installed": 0}],
            [{**record(), "Bld": 5}],
            [{"Installed": 1, "Version": "14.51.0.0"}],
            [{**record(), "Version": "unknown"}],
        ):
            with self.subTest(records=records):
                self.assertEqual(
                    self.check(records).reason, "runtime-records-inconsistent"
                )

    def test_wrong_architecture_and_denied_query(self):
        self.assertEqual(
            check_vc_runtime(architecture="ARM64", reader=lambda: [record()]).reason,
            "architecture-not-x64",
        )
        with patch(
            "windows_prerequisites.read_runtime_records", side_effect=PermissionError
        ):
            self.assertEqual(check_vc_runtime(architecture="x64").status, "not-tested")


class UserPathTests(unittest.TestCase):
    def test_frozen_downloads_respects_redirected_known_folder_without_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            redirected = root / "Perfil Árvore" / "Materiais redirecionados"
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(
                    sys, "executable", str(root / "Program Files/EduDownloader.exe")
                ),
                patch.object(paths, "_known_downloads_folder", return_value=redirected),
            ):
                self.assertEqual(
                    paths.get_downloads_dir(paths.get_app_dir()),
                    redirected / "EduDownloader",
                )
                self.assertFalse(redirected.exists())
                self.assertFalse(paths.get_app_dir().exists())

    def test_missing_known_folder_uses_profile_and_invalid_profile_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "perfil"
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(paths, "_known_downloads_folder", return_value=None),
                patch.dict(os.environ, {"LOCALAPPDATA": str(profile)}),
            ):
                self.assertTrue(paths.get_downloads_dir().is_relative_to(profile))
                self.assertFalse(profile.exists())
                with (
                    patch.dict(os.environ, {"LOCALAPPDATA": ""}),
                    self.assertRaises(OSError),
                ):
                    paths.get_downloads_dir()


class PublicationTests(unittest.TestCase):
    def test_parent_local_publication_does_not_need_hardlinks_on_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / "staged.tmp", Path(temp) / "receipt.edulic"
            source.write_bytes(b"synthetic signed bytes")
            with patch(
                "file_publication.os.link",
                side_effect=OSError("hard links unavailable"),
            ):
                if os.name == "nt":
                    publish_new_file(source, target)
                    self.assertEqual(target.read_bytes(), b"synthetic signed bytes")
            source.write_bytes(b"replacement")
            with self.assertRaises(FileExistsError):
                publish_new_file(source, target)
            self.assertEqual(target.read_bytes(), b"synthetic signed bytes")
            self.assertEqual(source.read_bytes(), b"replacement")

    def test_cross_parent_and_cancellation_never_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "other").mkdir()
            source, target = root / "staged.tmp", root / "other/target.edureq"
            source.write_bytes(b"safe")
            with self.assertRaises(OSError):
                publish_new_file(source, target)
            target = root / "target.edureq"
            with self.assertRaisesRegex(RuntimeError, "cancel"):
                publish_new_file(
                    source,
                    target,
                    check_cancel=lambda: (_ for _ in ()).throw(RuntimeError("cancel")),
                )
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), b"safe")

    def test_metadata_has_current_version_without_invented_publisher(self):
        self.assertEqual(metadata()["ProductVersion"], "3.0.0")
        self.assertEqual(metadata()["CompanyName"], "")
        with self.assertRaises(ValueError):
            metadata(publisher="name\ncommand")
