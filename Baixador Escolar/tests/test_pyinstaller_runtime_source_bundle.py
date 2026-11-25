"""Regressões offline de identidade, source-only e bundle PyInstaller D4."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import marshal
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pyinstaller_runtime_source_bundle as s


class PyInstallerRuntimeSourceTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = s.load_manifest(cls.root / s.DEFAULT_MANIFEST)

    def fixture(self):
        manifest = copy.deepcopy(self.manifest)
        required = {
            "sources/" + p for p in [*s.RUNTIME_SOURCES.values(), *s.LICENSES, s.ICON]
        }
        required |= {
            f"sources/pyinstaller/bootloader/{p}"
            for p in (
                "wscript",
                "src/main.c",
                "src/pyi_archive.c",
                "zlib/inflate.c",
                "zlib/inftrees.c",
                "zlib/crc32.c",
                "zlib/crc32.h",
                "zlib/inffixed.h",
                "zlib/README",
            )
        }
        files = {name: b"# synthetic source\n" for name in required}
        license_paths = {
            "pyinstaller/COPYING.txt": "Licencas/PyInstaller/COPYING.txt",
            "pyinstaller/bootloader/zlib/LICENSE": "Licencas/PyInstaller/ZLIB_LICENSE.txt",
            "hooks-contrib/LICENSE": "Licencas/pyinstaller-hooks-contrib/LICENSE",
        }
        for name, path in license_paths.items():
            files["sources/" + name] = (self.root / path).read_bytes()
        files["sources/" + s.ICON] = b"synthetic image resource"
        for parent_id, parent in s.PARENTS.items():
            source = next(
                p
                for p in files
                if p.startswith(f"sources/{parent_id}/") and p.endswith(".py")
            )
            rel = source.removeprefix(f"sources/{parent_id}/")
            data = files[source]
            blob = hashlib.sha1(
                b"blob " + str(len(data)).encode() + b"\0" + data
            ).hexdigest()
            manifest["source_comparison"][parent_id] = [
                {"path": rel, "git_blob": blob, "normalize_lf": True}
            ]
            files[f"metadata/{parent_id}/tree.json"] = s.formatted(
                {
                    "sha": parent["tree"],
                    "truncated": False,
                    "tree": [{"path": rel, "sha": blob}],
                }
            )
            files[f"metadata/{parent_id}/commit.json"] = s.formatted(
                {"sha": parent["commit"], "tree": {"sha": parent["tree"]}}
            )
        manifest["staging"] = s.inventory(files)
        return manifest, files

    def test_canonical_manifest_and_exact_parents(self):
        self.assertEqual(
            set(self.manifest["parents"]), {"pyinstaller", "hooks-contrib"}
        )
        self.assertEqual(
            self.manifest["parents"]["pyinstaller"]["preservation"],
            "REUSED_EXISTING_SOURCE",
        )
        self.assertEqual(self.manifest["counts"]["new_acquisitions"], 1)
        self.assertEqual(self.manifest["counts"]["transitive_parents"], 0)

    def test_source_files_licenses_and_generated_tables_are_covered(self):
        names = {e["path"] for e in self.manifest["staging"]["files"]}
        for path in [*s.RUNTIME_SOURCES.values(), *s.LICENSES, s.ICON]:
            self.assertIn("sources/" + path, names)
        self.assertIn("sources/pyinstaller/bootloader/zlib/crc32.c", names)
        self.assertIn("sources/pyinstaller/bootloader/zlib/inflate.c", names)
        self.assertEqual(
            self.manifest["materiality"]["zlib_1.3.2"], "COVERED_BY_PARENT"
        )
        self.assertEqual(
            len(self.manifest["excluded_input_members"]["pyinstaller"]), 21
        )

    def test_source_and_pypi_archives_are_not_claimed_identical(self):
        self.assertNotEqual(
            self.manifest["parents"]["pyinstaller"]["archive_sha256"],
            self.manifest["pypi_sdist_identities"]["pyinstaller"]["sha256"],
        )

    def test_runtime_hook_is_not_build_only(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["materiality"]["hooks-contrib"] = "BUILD_ONLY_NOT_DISTRIBUTED"
        with self.assertRaises(s.SourceBundleError):
            s.validate_structure(manifest)
        self.assertEqual(
            self.manifest["materiality"]["analysis_hooks"], "BUILD_ONLY_NOT_DISTRIBUTED"
        )

    def test_wrong_commit_tree_hash_reuse_or_parent_rejected(self):
        for field in ("commit", "tree", "archive_sha256", "preservation"):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                manifest["parents"]["pyinstaller"][field] = "wrong"
                with self.assertRaises(s.SourceBundleError):
                    s.validate_structure(manifest)

    def test_complete_with_gap_or_missing_runtime_source_rejected(self):
        for field in ("pending", "blocked", "unknown"):
            manifest = copy.deepcopy(self.manifest)
            manifest["counts"][field] = 1
            with self.assertRaises(s.SourceBundleError):
                s.validate_structure(manifest)
        manifest = copy.deepcopy(self.manifest)
        del manifest["runtime_sources"]["pyi_rth_inspect"]
        with self.assertRaises(s.SourceBundleError):
            s.validate_structure(manifest)

    def test_missing_each_material_source_is_rejected(self):
        for part in (
            "bootloader/src/main.c",
            "pyimod02_importers.py",
            "pyi_rth_inspect.py",
            "pyi_rth__tkinter.py",
            "pyi_rth_cryptography_openssl.py",
            "zlib/inflate.c",
            "zlib/LICENSE",
            "icon-windowed.ico",
            "COPYING.txt",
            "hooks-contrib/LICENSE",
        ):
            with self.subTest(part=part):
                manifest, files = self.fixture()
                path = next(p for p in files if p.endswith(part))
                del files[path]
                manifest["staging"] = s.inventory(files)
                with self.assertRaises(s.SourceBundleError):
                    s.validate_structure(manifest)

    def test_content_mismatch_and_proprietary_extra_rejected(self):
        manifest, files = self.fixture()
        for name, data in (
            ("sources/pyinstaller/bootloader/src/main.c", b"changed"),
            ("sources/app.py", b"proprietary source"),
        ):
            changed = dict(files)
            changed[name] = data
            with self.assertRaises(s.SourceBundleError):
                s.verify_payload(manifest, changed)

    def test_license_hash_mismatch_rejected_even_with_updated_inventory(self):
        manifest, files = self.fixture()
        files["sources/pyinstaller/COPYING.txt"] = b"wrong license"
        manifest["staging"] = s.inventory(files)
        with self.assertRaises(s.SourceBundleError):
            s.verify_payload(manifest, files)

    def test_source_blob_comparison_rejects_wrong_tree(self):
        manifest, files = self.fixture()
        path = "metadata/hooks-contrib/tree.json"
        tree = json.loads(files[path])
        tree["sha"] = "0" * 40
        files[path] = s.formatted(tree)
        manifest["staging"] = s.inventory(files)
        with patch.object(s, "ICON_SHA256", s.sha256(files["sources/" + s.ICON])):
            with self.assertRaises(s.SourceBundleError):
                s.verify_payload(manifest, files)

    def test_prohibited_executable_paths_and_magic(self):
        for path, data in (
            ("sources/run.exe", b"x"),
            ("sources/run", b"MZpayload"),
            ("sources/run", b"\x7fELFpayload"),
            ("sources/key.pem", b"x"),
            ("sources/activation_issuer/keys.py", b"x"),
        ):
            with self.subTest(path=path, data=data):
                with self.assertRaises(s.SourceBundleError):
                    s.check_payload(path, data)

    def test_paths_fail_closed(self):
        for path in (
            "../outside",
            "/absolute",
            "C:/local",
            "a\\b",
            "a/../b",
            "a//b",
            "a./b",
        ):
            with self.subTest(path=path):
                with self.assertRaises(s.SourceBundleError):
                    s.safe_name(path)

    @staticmethod
    def make_archive(path, entries):
        with tarfile.open(path, "w:gz") as archive:
            for name, data in entries.items():
                member = tarfile.TarInfo("fixture/" + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return {
            "prefix": "fixture",
            "archive_size": path.stat().st_size,
            "archive_sha256": s.sha256(path.read_bytes()),
        }

    def test_projection_excludes_prebuilt_and_test_key_without_modifying_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.tar.gz"
            parent = self.make_archive(
                path,
                {
                    "bootloader/src/main.c": b"source",
                    "PyInstaller/bootloader/Windows-64bit-intel/runw.exe": b"MZfixture",
                    "tests/server.pem": b"synthetic excluded fixture",
                },
            )
            before = path.read_bytes()
            files, excluded = s.project_archive(path, parent)
            self.assertEqual(files, {"bootloader/src/main.c": b"source"})
            self.assertEqual(len(excluded), 2)
            self.assertEqual(path.read_bytes(), before)

    def test_missing_source_and_wrong_archive_hash_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.tar.gz"
            with self.assertRaises(s.SourceBundleError):
                s.project_archive(path, s.PARENTS["pyinstaller"])
            parent = self.make_archive(path, {"source.c": b"source"})
            parent["archive_sha256"] = "0" * 64
            with self.assertRaises(s.SourceBundleError):
                s.project_archive(path, parent)

    def test_bundle_determinism_and_standalone_verification(self):
        manifest, files = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / "stage"
            for name, data in files.items():
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            first = Path(directory) / "one.zip"
            second = Path(directory) / "two.zip"
            with patch.object(s, "ICON_SHA256", s.sha256(files["sources/" + s.ICON])):
                self.assertEqual(
                    s.assemble(manifest, stage, first),
                    s.assemble(manifest, stage, second),
                )
                self.assertEqual(first.read_bytes(), second.read_bytes())
                s.verify_bundle(manifest, first)
                with self.assertRaises(s.SourceBundleError):
                    s.assemble(manifest, stage, first)

    def test_forged_self_consistent_bundle_cannot_replace_expected_inventory(self):
        manifest, files = self.fixture()
        files["sources/proprietary.py"] = b"not upstream"
        payload = s.bundle_files(manifest, files)
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "forged.zip"
            with zipfile.ZipFile(bundle, "w") as archive:
                for name, data in payload.items():
                    archive.writestr(s._zip_info(name), data)
            with self.assertRaises(s.SourceBundleError):
                s.verify_bundle(manifest, bundle)

    def test_cli_manifest_pin_rejects_modified_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            manifest = copy.deepcopy(self.manifest)
            manifest["candidate"]["source_commit"] = "0" * 40
            path.write_bytes(s.formatted(manifest))
            with self.assertRaises(s.SourceBundleError):
                s.load_manifest(path)

    def test_frozen_comparison_does_not_inherit_validator_future_flags_or_execute(self):
        manifest = copy.deepcopy(self.manifest)
        source = b"raise RuntimeError('must not execute')\n"
        entries = {
            name: marshal.dumps(
                compile(source, name + ".py", "exec", dont_inherit=True)
            )
            for name in s.RUNTIME_SOURCES
        }
        manifest["candidate"]["carchive_entries"] = sorted(entries)
        frozen_manifest = b"synthetic frozen authority"
        manifest["candidate"]["manifest_sha256"] = s.sha256(frozen_manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            for rel in s.RUNTIME_SOURCES.values():
                path = stage / "sources" / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(source)
            authority = root / s.FROZEN_MANIFEST
            authority.parent.mkdir(parents=True, exist_ok=True)
            authority.write_bytes(frozen_manifest)
            exe = root / s.FROZEN_ROOT / "EduDownloader.exe"
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b"synthetic CArchive")
            with (
                patch.object(s, "EXE_SHA256", s.sha256(exe.read_bytes())),
                patch.object(s, "archive_entries", return_value=entries),
            ):
                s.verify_frozen(manifest, stage, root)
                path.write_bytes(b"CHANGED = True\n")
                with self.assertRaises(s.SourceBundleError):
                    s.verify_frozen(manifest, stage, root)


if __name__ == "__main__":
    unittest.main()
