"""D6 offline regressions: materiality, exact sources, closure and leakage."""

from __future__ import annotations

import copy
import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import cryptography_cffi_source_bundle as s


class CryptographyCffiSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = s.load_manifest()

    def test_canonical_pinned_manifest_and_complete_scope(self):
        s.validate_structure(self.manifest)
        self.assertEqual(self.manifest["counts"]["logical_parents"], 26)
        self.assertEqual(len(s.RUNTIME), 15)
        self.assertEqual(len(s.CODEGEN), 4)
        self.assertEqual(len(s.BUILD_ONLY), 12)
        self.assertEqual(self.manifest["status"]["microsoft"], "P3_PENDING_REVIEW")

    def test_each_material_parent_required(self):
        for name in self.manifest["parents"]:
            with self.subTest(parent=name):
                m = copy.deepcopy(self.manifest)
                del m["parents"][name]
                with self.assertRaises(s.SourceBundleError):
                    s.validate_structure(m)

    def test_required_libffi_generator_rust_and_local_crate_files(self):
        paths = {
            f"sources/{key}/{p}" for key, members in s.REQUIRED.items() for p in members
        }
        paths |= {"metadata/cffi/libffi-LICENSE"}
        paths |= {
            "sources/cryptography/" + p for p in self.manifest["local_crates"].values()
        }
        for name in sorted(paths):
            with self.subTest(path=name):
                m = copy.deepcopy(self.manifest)
                m["staging"]["files"] = [
                    e for e in m["staging"]["files"] if e["path"] != name
                ]
                with self.assertRaises(s.SourceBundleError):
                    s.validate_structure(m)

    def test_no_build_only_or_target_crate_promoted(self):
        for name in [*s.BUILD_ONLY, "portable-atomic"]:
            m = copy.deepcopy(self.manifest)
            m["parents"][name] = copy.deepcopy(m["parents"]["asn1"])
            with self.subTest(name=name), self.assertRaises(s.SourceBundleError):
                s.validate_structure(m)

    def test_runtime_and_codegen_roles_are_exact(self):
        for name in s.RUNTIME | s.CODEGEN:
            m = copy.deepcopy(self.manifest)
            m["parents"][name]["role"] = "BUILD_ONLY"
            with self.subTest(name=name), self.assertRaises(s.SourceBundleError):
                s.validate_structure(m)

    def test_no_gap_can_be_labeled_a(self):
        for field in ("pending", "blocked", "open_source_unknown"):
            m = copy.deepcopy(self.manifest)
            m["counts"][field] = 1
            with self.subTest(field=field), self.assertRaises(s.SourceBundleError):
                s.validate_structure(m)

    def test_generated_source_relation_and_reuse_required(self):
        for key in ("generated_source_inputs", "local_crates"):
            m = copy.deepcopy(self.manifest)
            m[key] = {}
            with self.subTest(key=key), self.assertRaises(s.SourceBundleError):
                s.validate_structure(m)
        m = copy.deepcopy(self.manifest)
        m["parents"]["cffi-generator"]["preservation"] = "PRESERVED_NEW"
        with self.assertRaises(s.SourceBundleError):
            s.validate_structure(m)

    def test_manifest_pin_rejects_version_hash_lock_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            for parent, field, value in (
                ("cffi", "archive_sha256", "0" * 64),
                ("cryptography", "archive_sha256", "0" * 64),
                ("openssl-source", "version", "3.5.7"),
                ("rust", "version", "1.97.1"),
                ("cfg-if", "crate_checksum", "0" * 64),
            ):
                m = copy.deepcopy(self.manifest)
                m["parents"][parent][field] = value
                path.write_bytes(s.formatted(m))
                with (
                    self.subTest(parent=parent),
                    self.assertRaises(s.SourceBundleError),
                ):
                    s.load_manifest(path)

    @staticmethod
    def crate_fixture():
        files = {
            "Cargo.toml": b'[package]\nname="demo"\nversion="1.0.0"\nlicense="MIT"\n',
            "src/lib.rs": b"// synthetic source\n",
            "LICENSE": b"synthetic notice",
        }
        parent = {
            "name": "demo",
            "version": "1.0.0",
            "license_expression": "MIT",
            "crate_checksum": "1" * 64,
        }
        return files, parent

    def test_crate_name_version_license_sources_verified(self):
        files, parent = self.crate_fixture()
        s.verify_crate(files, parent)
        for path in files:
            altered = dict(files)
            del altered[path]
            with self.subTest(path=path), self.assertRaises(s.SourceBundleError):
                s.verify_crate(altered, parent)
        for field in ("name", "version", "license_expression"):
            altered = dict(parent, **{field: "wrong"})
            with self.subTest(field=field), self.assertRaises(s.SourceBundleError):
                s.verify_crate(files, altered)

    def test_vendored_reuse_all_files_and_package_checksum(self):
        files, parent = self.crate_fixture()
        parent["vendored_reuse"] = True
        checks = {
            "package": parent["crate_checksum"],
            "files": {n: s.sha256(b).lower() for n, b in files.items()},
        }
        files[".cargo-checksum.json"] = s.formatted(checks)
        s.verify_crate(files, parent)
        for kind in ("checksum", "content", "extra"):
            changed = dict(files)
            if kind == "checksum":
                changed[".cargo-checksum.json"] = s.formatted(
                    dict(checks, package="0" * 64)
                )
            elif kind == "content":
                changed["src/lib.rs"] += b"changed"
            else:
                changed["extra.rs"] = b"unapproved"
            with self.subTest(kind=kind), self.assertRaises(s.SourceBundleError):
                s.verify_crate(changed, parent)

    @staticmethod
    def make_archive(path, files):
        with tarfile.open(path, "w:gz") as archive:
            for name, data in files.items():
                info = tarfile.TarInfo("fixture/" + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return {
            "name": "fixture",
            "prefix": "fixture",
            "archive_size": path.stat().st_size,
            "archive_sha256": s.sha256(path.read_bytes()),
        }

    def test_projection_keeps_sources_excludes_prebuilt_and_loose_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.tar.gz"
            parent = self.make_archive(
                path,
                {
                    "src/lib.rs": b"source",
                    "win64.asm": b"assembly source",
                    "win64.obj": b"prebuilt",
                    "test.key": b"synthetic fixture",
                    "run.exe": b"MZfixture",
                },
            )
            before = path.read_bytes()
            files, excluded = s.project_archive(path, parent)
            self.assertEqual(set(files), {"src/lib.rs", "win64.asm"})
            self.assertEqual(len(excluded), 3)
            self.assertEqual(before, path.read_bytes())

    def test_bad_archive_hash_and_missing_input_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crate.tar.gz"
            parent = self.make_archive(path, {"source.rs": b"source"})
            parent["archive_sha256"] = "0" * 64
            with self.assertRaises(s.SourceBundleError):
                s.archive_files(path, parent)
            with self.assertRaises(s.SourceBundleError):
                s.archive_files(path.with_name("missing"), parent)

    def test_archive_traversal_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.tar.gz"
            parent = self.make_archive(path, {"../escape": b"source"})
            with self.assertRaises(s.SourceBundleError):
                s.archive_files(path, parent)
            with tarfile.open(path, "w:gz") as archive:
                info = tarfile.TarInfo("fixture/link")
                info.type = tarfile.SYMTYPE
                info.linkname = "../../outside"
                archive.addfile(info)
            parent.update(
                archive_size=path.stat().st_size,
                archive_sha256=s.sha256(path.read_bytes()),
            )
            with self.assertRaises(s.SourceBundleError):
                s.archive_files(path, parent)

    def test_secret_executable_and_administrative_payload_rejected(self):
        for name, data in (
            ("run", b"MZfixture"),
            ("foreign.whl", b"x"),
            ("foreign.pyd", b"x"),
            ("issuer.dpapi", b"x"),
            ("activation.dat", b"x"),
            ("activation_issuer/source.py", b"x"),
            (
                "source.txt",
                b"-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----",
            ),
        ):
            with self.subTest(name=name), self.assertRaises(s.SourceBundleError):
                s.check_payload(name, data)

    def test_public_upstream_exception_never_accepts_changed_content(self):
        for name in s.PUBLIC_UPSTREAM_SOURCE:
            with self.subTest(name=name), self.assertRaises(s.SourceBundleError):
                s.check_payload(name, b"-----BEGIN PRIVATE KEY-----\nnot upstream")

    def test_small_bundle_determinism_inventory_and_no_overwrite(self):
        # ZIP layer is tested independently of the 26-parent closure; closure
        # structure, exact graph, source projections and hashes have own tests.
        files = {"sources/demo/source.rs": b"synthetic source"}
        manifest = {"staging": s.inventory(files)}

        def verify(m, actual):
            if s.inventory(actual) != m["staging"]:
                raise s.SourceBundleError("unexpected content")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(s, "verify_payload", side_effect=verify),
        ):
            root = Path(directory)
            stage = root / "stage"
            p = stage / "sources/demo/source.rs"
            p.parent.mkdir(parents=True)
            p.write_bytes(files["sources/demo/source.rs"])
            first, second = root / "one.zip", root / "two.zip"
            self.assertEqual(
                s.assemble(manifest, stage, first), s.assemble(manifest, stage, second)
            )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with self.assertRaises(s.SourceBundleError):
                s.assemble(manifest, stage, first)
            # A self-consistent forged ZIP cannot redefine expected authority.
            forged = root / "forged.zip"
            altered = dict(files, **{"sources/proprietary.py": b"not upstream"})
            with zipfile.ZipFile(forged, "w") as z:
                for name, data in sorted(s.bundle_files(manifest, altered).items()):
                    z.writestr(s._zip_info(name), data)
            with self.assertRaises(s.SourceBundleError):
                s.verify_bundle(manifest, forged)

    def test_graph_wrong_lock_rejected_before_parsing(self):
        with self.assertRaises(s.SourceBundleError):
            s.verify_graph(
                self.manifest, {"sources/cryptography/Cargo.lock": b"wrong lock"}
            )

    def test_exact_std_reuse_and_compiler_builtins_backtrace_evidence(self):
        parents = self.manifest["parents"]
        self.assertEqual(parents["rust"]["version"], "1.96.0")
        self.assertEqual(parents["hashbrown"]["version"], "0.16.1")
        self.assertTrue(parents["cfg-if"]["vendored_reuse"])
        self.assertTrue(parents["rustc-demangle"]["vendored_reuse"])
        self.assertFalse(self.manifest["rust_std_vendor_in_archive"])
        self.assertEqual(
            len(self.manifest["source_comparison"]["rust"]["backtrace"]["matched"]), 79
        )
        self.assertTrue(
            any(
                "compiler-builtins/compiler-builtins/src/lib.rs" in e["path"]
                for e in self.manifest["staging"]["files"]
            )
        )


if __name__ == "__main__":
    unittest.main()
