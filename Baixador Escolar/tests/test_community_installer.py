import tempfile
import unittest
from pathlib import Path

from build_community_installer import SOURCE, payload_identity, prerequisites
from documents_component import ENGINE_VERSION
from libreoffice_image import prune_ui_resources, read_removal_catalog
from windows_prerequisites import MINIMUM_VC_VERSION


class CommunityInstallerTests(unittest.TestCase):
    def test_prerequisite_pins_use_existing_baselines_and_official_hosts(self):
        pins = prerequisites()
        self.assertEqual(pins["VCMinimum"], ".".join(map(str, MINIMUM_VC_VERSION)))
        self.assertEqual(pins["OfficeEngine"], ENGINE_VERSION)
        self.assertTrue(
            pins["VCURL"].startswith("https://download.visualstudio.microsoft.com/")
        )
        self.assertTrue(pins["OfficeURL"].startswith("https://tdf.c3sl.ufpr.br/"))
        for field in (
            "VCSHA",
            "OfficeSHA",
            "OfficeSOFFICECOM",
            "OfficeSOFFICEEXE",
            "OfficeSOFFICEBIN",
        ):
            self.assertRegex(pins[field], r"^[0-9A-F]{64}$")
        for field in ("VCSigner", "OfficeSigner"):
            self.assertRegex(pins[field], r"^[0-9A-F]{40}$")

    def test_reinstallation_identity_is_stable_and_changes_with_program_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            program = root / "EduDownloader.exe"
            program.write_bytes(b"previous")
            first, size = payload_identity(root)
            (root / "Logs").mkdir()
            (root / "Downloads").mkdir()
            self.assertEqual(payload_identity(root), (first, size))
            program.write_bytes(b"new")
            self.assertNotEqual(payload_identity(root)[0], first)

    def test_mutable_user_files_are_rejected_even_in_ignored_portable_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            downloads = root / "Downloads"
            downloads.mkdir()
            (downloads / "particular.pdf").write_bytes(b"file must not be packaged")
            with self.assertRaisesRegex(ValueError, "arquivos do usuário"):
                payload_identity(root)

    def test_office_cleanup_covers_both_owned_short_and_long_paths(self):
        script = (SOURCE / "community.iss").read_text(encoding="utf-8")
        cleanup = script.split("procedure CleanOfficeScratch", 1)[1].split(
            "function CopyPreparedOffice", 1
        )[0]
        self.assertIn("SafeLocalDirectory(PathName)", cleanup)
        self.assertIn(r"DelTree('\\?\' + PathName", cleanup)
        for owner, folder in (
            ("OfficeProbeOwned", "lo-test"),
            ("OfficeImageOwned", "lo-image"),
        ):
            self.assertIn(f"{owner} := True;", script)
            self.assertIn(
                f"if {owner} then\n    "
                rf"CleanOfficeScratch(ExpandConstant('{{tmp}}\{folder}'));",
                cleanup,
            )

    def test_office_profile_restricts_pruning_to_reviewed_user_interface_translations(
        self,
    ):
        profile, catalog = read_removal_catalog(SOURCE)
        self.assertEqual(profile["engine_version"], ENGINE_VERSION)
        self.assertEqual(
            int(prerequisites()["OfficeInstallSize"]), profile["installed_bytes"]
        )
        self.assertGreater(
            int(prerequisites()["OfficeImageSize"]), profile["installed_bytes"]
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            names = (
                "program/resource/de/LC_MESSAGES/ui.mo",
                "program/resource/pt_BR/LC_MESSAGES/ui.mo",
                "share/extensions/dict-de/hyphen.txt",
                "license.txt",
            )
            for name in names:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_bytes(b"content")
            prune_ui_resources(root, ((names[0], 7),))
            self.assertFalse((root / names[0]).exists())
            for name in names[1:]:
                with self.assertRaises(ValueError):
                    prune_ui_resources(root, ((name, 7),))
                self.assertEqual((root / name).read_bytes(), b"content")
        self.assertFalse(
            any("/pt_BR/" in path or "/common/" in path for path, _ in catalog)
        )
