"""Offline D8 source/provenance tests; no network, app or source execution."""

from __future__ import annotations

import copy
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import customtkinter_runtime_source as d
from pyinstaller_runtime_source_bundle import (
    SourceBundleError,
    canonical,
    formatted,
    inventory,
)


class CustomTkinterSourceTests(unittest.TestCase):
    def test_sdist_setup_reformatting_preserves_fields_and_only_adds_egg_info(self):
        upstream = b"[metadata]\nlicense = CC0\nclassifiers =\n    MIT\n"
        generated = b"[metadata]\nlicense = CC0\nclassifiers = \n\tMIT\n[egg_info]\ntag_build =\ntag_date = 0\n"
        d.check_setup_cfg(generated, upstream)
        for bad in (
            generated.replace(b"CC0", b"MIT"),
            generated.replace(b"tag_date = 0", b"tag_date = 1"),
        ):
            with self.assertRaises(SourceBundleError):
                d.check_setup_cfg(bad, upstream)

    def setUp(self):
        self.manifest = json.loads(d.MANIFEST.read_bytes())

    def package(self):
        files = {f"customtkinter/m{i}.py": b"value = 1\n" for i in range(43)}
        assets = (
            "themes/blue.json",
            "themes/dark-blue.json",
            "themes/green.json",
            "fonts/CustomTkinter_shapes_font.otf",
            "icons/CustomTkinter_icon_Windows.ico",
            "fonts/Roboto/Roboto-Regular.ttf",
            "fonts/Roboto/Roboto-Medium.ttf",
            ".DS_Store",
            "icons/.DS_Store",
        )
        files.update(
            {"customtkinter/assets/" + name: b"synthetic asset" for name in assets}
        )
        source = {
            **files,
            "LICENSE": b"license",
            "setup.cfg": b"metadata",
            "MANIFEST.in": b"include",
        }
        tree = {
            "truncated": False,
            "tree": [
                {"path": name, "type": "blob", "sha": d.git_blob(data)}
                for name, data in source.items()
                if not name.endswith(".DS_Store")
            ],
        }
        return source, files, tree

    def test_official_manifest_is_pinned_and_canonical(self):
        self.assertEqual(d.load_manifest(), self.manifest)
        self.assertEqual(formatted(self.manifest), d.MANIFEST.read_bytes())

    def test_manifest_mutation_is_rejected_even_with_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_bytes(formatted({**self.manifest, "classification": "COMPLETE"}))
            with self.assertRaisesRegex(SourceBundleError, "unapproved"):
                d.load_manifest(path)

    def test_wrong_identities_and_false_completion_fail_closed(self):
        mutations = (
            ("classification", None, "COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW"),
            ("customtkinter", "sdist_sha256", "0" * 64),
            ("customtkinter", "commit", "0" * 40),
            ("customtkinter", "tree", "0" * 40),
            ("customtkinter", "wheel_sha256", "0" * 64),
            ("digsby", "commit", "0" * 40),
            ("digsby", "tree", "0" * 40),
            ("digsby", "source_sha256", "0" * 64),
            ("digsby", "license_sha256", "0" * 64),
            ("modules", None, []),
            ("license_signals", "license_lf_sha256", "0" * 64),
            ("license_signals", "metadata_license", "MIT"),
            ("license_discrepancy", None, "RESOLVED"),
            ("roboto", "hashes", {"Regular": "0" * 64}),
            ("roboto", "producer_status", "RESOLVED"),
            ("roboto", "producing_parent", "Roboto 2.137"),
            ("source_pending", None, 0),
            ("unknown_material_files", None, 0),
            ("stack_overflow", "answer_id", 0),
            ("stack_overflow", "author", ""),
            ("stack_overflow", "revisions", []),
            ("notice_delivery", None, "COMPLETE"),
        )
        for parent, key, value in mutations:
            with self.subTest(parent=parent, key=key):
                manifest = copy.deepcopy(self.manifest)
                if key is None:
                    manifest[parent] = value
                else:
                    manifest[parent][key] = value
                with self.assertRaises(SourceBundleError):
                    d.validate_manifest(manifest)

    def test_missing_license_and_lineage_evidence_fails(self):
        for name in (
            "roboto-historical-LICENSE.txt",
            "digsby-LICENSE",
            "so-revisions.json",
        ):
            with self.subTest(name=name):
                manifest = copy.deepcopy(self.manifest)
                del manifest["acquisitions"][name]
                with self.assertRaises(SourceBundleError):
                    d.validate_manifest(manifest)

    def test_all_43_sources_and_9_data_match_tag_sdist_wheel(self):
        source, wheel, tree = self.package()
        d.check_package(source, wheel, tree)

    def test_missing_source_and_each_kind_of_modified_runtime_member_fails(self):
        source, wheel, tree = self.package()
        for name in wheel:
            with self.subTest(name=name):
                changed = {**source, name: b"wrong"}
                with self.assertRaisesRegex(SourceBundleError, "mismatch"):
                    d.check_package(changed, wheel, tree)
                missing = dict(source)
                del missing[name]
                with self.assertRaises(SourceBundleError):
                    d.check_package(missing, wheel, tree)

    def test_wrong_git_blob_and_truncated_tree_fail(self):
        source, wheel, tree = self.package()
        tree["tree"][0]["sha"] = "0" * 40
        with self.assertRaisesRegex(SourceBundleError, "tag mismatch"):
            d.check_package(source, wheel, tree)
        tree["truncated"] = True
        with self.assertRaisesRegex(SourceBundleError, "truncated"):
            d.check_package(source, wheel, tree)

    def test_unexplained_wheel_member_or_missing_python_module_fails(self):
        source, wheel, tree = self.package()
        wheel["customtkinter/extra.py"] = b"extra"
        with self.assertRaises(SourceBundleError):
            d.check_package(source, wheel, tree)
        del wheel["customtkinter/extra.py"]
        del wheel["customtkinter/m0.py"]
        with self.assertRaises(SourceBundleError):
            d.check_package(source, wheel, tree)

    def test_mit_line_endings_and_discrepant_metadata_are_preserved(self):
        license_data = Path("Licencas/CUSTOMTKINTER_LICENSE.txt").read_bytes()
        metadata = b"Creative Commons Zero v1.0 Universal\nLicense :: OSI Approved :: MIT License"
        source = {
            "LICENSE": license_data.replace(b"\r\n", b"\n"),
            "setup.cfg": metadata,
        }
        d.check_license(source, metadata, license_data)
        with self.assertRaisesRegex(SourceBundleError, "CC0"):
            d.check_license(source, b"MIT", license_data)
        with self.assertRaisesRegex(SourceBundleError, "MIT LICENSE"):
            d.check_license({**source, "LICENSE": b""}, metadata, license_data)
        with self.assertRaisesRegex(SourceBundleError, "normalization"):
            d.check_license(source, metadata, license_data + b"changed")

    def test_invalid_preserved_artifact_fails_before_using_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "inputs").mkdir()
            name = next(iter(self.manifest["acquisitions"]))
            (work / "inputs" / name).write_bytes(b"wrong")
            with self.assertRaisesRegex(SourceBundleError, "hash mismatch"):
                d.verify_inputs(self.manifest, work)

    def test_partial_parent_blocks_all_bundle_commands_without_writing(self):
        for command in ("verify-staging", "assemble", "verify-bundle"):
            with self.subTest(command=command), patch("sys.argv", ["d8", command]):
                with patch.object(d, "verify_inputs") as verify:
                    self.assertEqual(d.main(), 1)
                    verify.assert_not_called()
        with self.assertRaisesRegex(SourceBundleError, "unresolved"):
            d.require_complete(self.manifest)

    def test_version_only_parent_cannot_unlock_bundle(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["roboto"]["producer_status"] = "RESOLVED"
        with self.assertRaisesRegex(SourceBundleError, "version-only"):
            d.require_complete(manifest)

    def test_archive_inventory_is_deterministic_without_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                for name in ("source/b.py", "source/a.py"):
                    member = tarfile.TarInfo(name)
                    member.size = 4
                    archive.addfile(member, io.BytesIO(b"data"))
            files = d.read_archive(path, "source")
            first = inventory(files)
            second = inventory(dict(reversed(list(files.items()))))
            self.assertEqual(canonical(first), canonical(second))
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_archive_traversal_and_duplicates_are_rejected(self):
        for names in (("source/../escape",), ("source/a", "source/a")):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "bad.tar.gz"
                with tarfile.open(path, "w:gz") as archive:
                    for name in names:
                        member = tarfile.TarInfo(name)
                        member.size = 1
                        archive.addfile(member, io.BytesIO(b"x"))
                with self.assertRaises(SourceBundleError):
                    d.read_archive(path, "source")

    def test_frozen_authority_and_lineage_are_not_rewritten(self):
        baseline = d.load_manifest()
        self.assertEqual(d.formatted(self.manifest), d.formatted(baseline))
        self.assertRegex(
            self.manifest["frozen_authority"]["inventory_sha256"], r"^[a-fA-F0-9]{64}$"
        )
        revisions = self.manifest["stack_overflow"]["revisions"]
        self.assertEqual(len({r["code_sha256"] for r in revisions[:3]}), 1)
        self.assertIsNone(self.manifest["stack_overflow"]["revision_used"])
        self.assertEqual(self.manifest["notice_delivery"], "PENDING_FIX")


if __name__ == "__main__":
    unittest.main()
