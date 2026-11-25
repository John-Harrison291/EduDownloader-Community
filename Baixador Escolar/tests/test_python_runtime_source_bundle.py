"""Testes offline da closure de source do runtime CPython/Tcl-Tk congelado."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from python_runtime_source_bundle import (
    DEFAULT_FROZEN_CANDIDATE,
    DEFAULT_FROZEN_MANIFEST,
    DEFAULT_MANIFEST,
    DEFAULT_STAGING,
    OFFICIAL_MANIFEST_SHA256,
    SourceBundleError,
    assemble_bundle,
    canonical_json_bytes,
    load_manifest,
    sha256_bytes,
    validate_manifest_structure,
    validate_official_identity,
    verify_bundle,
    verify_candidate_notices,
    verify_frozen_consistency,
    verify_staging,
)


class PythonRuntimeSourceBundleTests(unittest.TestCase):
    """Exercita identidade, escopo e montagem determinística sem rede."""

    project_dir = Path(__file__).resolve().parents[1]

    @classmethod
    def official_manifest_path(cls) -> Path:
        return cls.project_dir / DEFAULT_MANIFEST

    @classmethod
    def official_manifest(cls) -> dict[str, object]:
        return load_manifest(cls.official_manifest_path())

    @staticmethod
    def write_manifest(path: Path, manifest: dict[str, object]) -> None:
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def make_fixture(cls, root: Path) -> tuple[dict[str, object], Path]:
        manifest = deepcopy(cls.official_manifest())
        source_content = b"source fixture"
        license_content = b"license fixture\n"
        parent = deepcopy(manifest["parents"][0])
        parent.update(
            {
                "id": "fixture",
                "version": "1.0",
                "preservation_status": "PRESERVED_NEW",
                "consumers": ["fixture consumer"],
                "source_archive": {
                    "origin": "https://example.invalid/source.tar.gz",
                    "sha256": sha256_bytes(source_content),
                    "size_bytes": len(source_content),
                    "staging_path": "sources/source.tar.gz",
                },
                "git": {
                    "commit": "1" * 40,
                    "tree": "2" * 40,
                },
                "licenses": [
                    {
                        "archive_path": "LICENSE",
                        "sha256": sha256_bytes(license_content),
                        "size_bytes": len(license_content),
                        "staging_path": "licenses/fixture/LICENSE",
                    }
                ],
            }
        )
        license_entry = {
            "relative_path": "licenses/fixture/LICENSE",
            "sha256": sha256_bytes(license_content),
            "size": len(license_content),
        }
        manifest.update(
            {
                "bin_deps_evidence": [],
                "classification": {
                    "legal_review": "PENDING",
                    "notice_review": "PENDING",
                    "source_correspondence": "A",
                    "technical_status": "technically-complete-pending-legal-review",
                },
                "component": "synthetic runtime source fixture",
                "counts": {
                    "blocked": 0,
                    "logical_source_parents": 1,
                    "new_acquisitions": 1,
                    "pending": 0,
                    "preserved": 1,
                    "reused_existing": 0,
                    "unknown_material": 0,
                },
                "covered_by_parent": [],
                "distribution_notice": {},
                "metadata_collections": [
                    {
                        "file_count": 1,
                        "inventory_sha256": sha256_bytes(
                            canonical_json_bytes([license_entry])
                        ),
                        "root": "licenses",
                        "total_size_bytes": len(license_content),
                    }
                ],
                "non_material": [],
                "parents": [parent],
            }
        )
        staging = root / "staging"
        source = staging / "sources/source.tar.gz"
        license_path = staging / "licenses/fixture/LICENSE"
        source.parent.mkdir(parents=True)
        license_path.parent.mkdir(parents=True)
        source.write_bytes(source_content)
        license_path.write_bytes(license_content)
        return manifest, staging

    def test_official_manifest_is_canonical_and_pinned(self) -> None:
        path = self.official_manifest_path()
        manifest = self.official_manifest()

        self.assertEqual(sha256_bytes(path.read_bytes()), OFFICIAL_MANIFEST_SHA256)
        self.assertEqual(
            path.read_bytes(),
            (
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8"),
        )
        self.assertNotRegex(path.read_text(encoding="utf-8"), r"\b[A-Za-z]:[\\/]")

    def test_exact_parent_counts_and_preservation_model(self) -> None:
        manifest = self.official_manifest()
        parents = {item["id"]: item for item in manifest["parents"]}

        self.assertEqual(manifest["counts"]["logical_source_parents"], 10)
        self.assertEqual(manifest["counts"]["new_acquisitions"], 8)
        self.assertEqual(manifest["counts"]["reused_existing"], 2)
        self.assertEqual(
            set(parents),
            {
                "bzip2",
                "cpython",
                "libffi",
                "mpdecimal",
                "openssl",
                "tcl",
                "tk",
                "xz",
                "zlib-ng",
                "zstandard",
            },
        )
        self.assertEqual(
            {
                parent_id
                for parent_id, parent in parents.items()
                if parent["preservation_status"] == "PRESERVED_NEW"
            },
            set(parents) - {"bzip2", "xz"},
        )
        self.assertEqual(
            {
                parent_id
                for parent_id, parent in parents.items()
                if parent["preservation_status"] == "REUSED_EXISTING_SOURCE"
            },
            {"bzip2", "xz"},
        )

    def test_exact_runtime_versions_and_dynamic_consumers(self) -> None:
        parents = {item["id"]: item for item in self.official_manifest()["parents"]}

        self.assertEqual(parents["cpython"]["version"], "3.14.6")
        self.assertEqual(parents["tcl"]["version"], "8.6.15.0")
        self.assertEqual(parents["tk"]["version"], "8.6.15.0")
        self.assertIn("_internal/_ctypes.pyd", parents["libffi"]["consumers"])
        self.assertIn("_internal/libffi-8.dll", parents["libffi"]["consumers"])
        self.assertIn("_internal/_decimal.pyd", parents["mpdecimal"]["consumers"])
        self.assertIn("_internal/_ssl.pyd", parents["openssl"]["consumers"])
        self.assertIn("_internal/libcrypto-3.dll", parents["openssl"]["consumers"])
        self.assertIn(
            "_internal/python314.dll (zlib compatibility 1.3.1.zlib-ng)",
            parents["zlib-ng"]["consumers"],
        )
        self.assertIn("_internal/_zstd.pyd", parents["zstandard"]["consumers"])

    def test_internal_components_are_covered_without_extra_parents(self) -> None:
        manifest = self.official_manifest()
        covered = {item["id"]: item for item in manifest["covered_by_parent"]}

        self.assertEqual(covered["expat"]["version"], "2.8.1")
        self.assertEqual(
            covered["hacl"]["version"],
            "8ba599b2f6c9701b3dc961db895b0856a2210f76",
        )
        self.assertEqual(covered["tcl-zlib"]["version"], "1.3.1")
        self.assertEqual(covered["libtommath"]["parent"], "tcl")
        self.assertTrue(
            all(item["status"] == "PRESERVED_WITH_PARENT" for item in covered.values())
        )

    def test_sqlite_is_explicitly_not_required(self) -> None:
        manifest = self.official_manifest()

        self.assertNotIn("sqlite", {item["id"] for item in manifest["parents"]})
        self.assertEqual(
            manifest["non_material"],
            [
                {
                    "component": "SQLite",
                    "reason": (
                        "_sqlite3.pyd e sqlite3.dll não existem no frozen candidate; "
                        "o pin PCbuild não participa da composição distribuída"
                    ),
                    "source_required": False,
                    "status": "NOT_REQUIRED",
                    "version": "3.50.4.0",
                }
            ],
        )

    def test_bin_deps_evidence_is_exact(self) -> None:
        evidence = {
            item["tag"]: (item["commit"], item["tree"])
            for item in self.official_manifest()["bin_deps_evidence"]
        }

        self.assertEqual(
            evidence,
            {
                "libffi-3.4.4": (
                    "94cb9a1c7feb608adf2b9f8fe2dbd6925ffbf90d",
                    "bf8087b61bea675a2d4ab393e25e017a9eea9734",
                ),
                "openssl-bin-3.5.7": (
                    "3217be5a2a7e20dbc5f5b5160ef21a9c84de7138",
                    "489fe20520999c58ed7f39d43bea3c482ec46cee",
                ),
                "tcltk-8.6.15.0": (
                    "5a51bb7b87efa119332c52b04a84c49d3042279c",
                    "d30680904f4152fa2fd06bda1f332b7041c8728c",
                ),
            },
        )

    def test_wrong_official_source_hash_or_revision_fails_closed(self) -> None:
        manifest = self.official_manifest()
        wrong_hash = deepcopy(manifest)
        wrong_hash["parents"][0]["source_archive"]["sha256"] = "0" * 64
        wrong_revision = deepcopy(manifest)
        wrong_revision["parents"][0]["git"]["commit"] = "0" * 40

        with self.assertRaisesRegex(SourceBundleError, "Source hash diverge"):
            validate_official_identity(wrong_hash)
        with self.assertRaisesRegex(SourceBundleError, "Commit diverge"):
            validate_official_identity(wrong_revision)

    def test_class_a_rejects_pending_material_and_missing_license(self) -> None:
        manifest = self.official_manifest()
        pending = deepcopy(manifest)
        pending["counts"]["pending"] = 1
        missing_license = deepcopy(manifest)
        missing_license["parents"][0]["licenses"] = []

        with self.assertRaisesRegex(SourceBundleError, "Classe A"):
            validate_manifest_structure(pending)
        with self.assertRaisesRegex(SourceBundleError, "Licença ausente"):
            validate_manifest_structure(missing_license)

    def test_missing_or_changed_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            manifest, staging = self.make_fixture(root)

            (staging / "sources/source.tar.gz").unlink()
            with self.assertRaisesRegex(SourceBundleError, "Source ausente"):
                verify_staging(manifest, staging)

            (staging / "sources/source.tar.gz").write_bytes(b"source fixturE")
            with self.assertRaisesRegex(SourceBundleError, "Source hash diverge"):
                verify_staging(manifest, staging)

    def test_executable_leakage_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            manifest, staging = self.make_fixture(root)
            (staging / "candidate.exe").write_bytes(b"MZ")

            with self.assertRaisesRegex(SourceBundleError, "proibido"):
                verify_staging(manifest, staging)

    def test_synthetic_bundle_is_byte_deterministic_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            manifest, staging = self.make_fixture(root)
            manifest_path = root / "manifest.json"
            first = root / "first.zip"
            second = root / "second.zip"
            self.write_manifest(manifest_path, manifest)

            first_result = assemble_bundle(
                manifest_path,
                staging,
                first,
                enforce_official_baseline=False,
            )
            second_result = assemble_bundle(
                manifest_path,
                staging,
                second,
                enforce_official_baseline=False,
            )
            verified = verify_bundle(
                manifest_path,
                first,
                enforce_official_baseline=False,
            )

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_result, second_result)
            self.assertEqual(first_result, verified)

    def test_official_staging_and_candidate_are_fully_verifiable(self) -> None:
        staging = self.project_dir / DEFAULT_STAGING
        candidate = self.project_dir / DEFAULT_FROZEN_CANDIDATE
        if not staging.is_dir() or not candidate.is_dir():
            self.skipTest("artefatos locais ignorados de compliance não disponíveis")
        manifest = self.official_manifest()

        inventory = verify_staging(manifest, staging)
        frozen = verify_frozen_consistency(
            manifest,
            self.project_dir / DEFAULT_FROZEN_MANIFEST,
        )
        notices = verify_candidate_notices(manifest, staging, candidate)

        self.assertEqual(len(inventory), 104)
        self.assertEqual(sum(item["size"] for item in inventory), 112_285_992)
        self.assertEqual(frozen["status"], "verified")
        self.assertTrue(notices["normalized_equal"])
        self.assertEqual(notices["tcl_license_status"], "NOTICE_GAP_TO_FIX_LATER")


if __name__ == "__main__":
    unittest.main()
