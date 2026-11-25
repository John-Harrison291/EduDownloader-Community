"""Testes offline do staging e bundle de source correspondente do yt-dlp."""

from __future__ import annotations

import json
import hashlib
import io
import tarfile
import tempfile
import unittest
from base64 import b64encode
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePath

from tests.compliance_inputs import evidence_path
from yt_dlp_source_bundle import (
    OFFICIAL_EXECUTABLE_SHA256,
    OFFICIAL_MANIFEST_SHA256,
    OFFICIAL_SOURCE_ARCHIVE_SHA256,
    SourceBundleError,
    assemble_bundle,
    canonical_json_bytes,
    git_blob_sha1,
    load_manifest,
    pem_certificate_hashes,
    sha256_bytes,
    trusted_certdata_certificate_hashes,
    validate_manifest_structure,
    validate_official_identity,
    verify_bundle,
    verify_commit_snapshot_archive,
    verify_cpython_external_archive,
    verify_cpython_runtime_correspondence,
    verify_python_p2_correspondence,
    verify_sfparse_coverage,
    verify_staging,
)


class YtDlpSourceBundleTests(unittest.TestCase):
    """Exercita falha fechada sem rede ou artefatos grandes reais."""

    @staticmethod
    def make_file_entry(path: str, content: bytes) -> dict[str, object]:
        return {
            "origin": "https://github.com/yt-dlp/yt-dlp",
            "purpose": "fixture sintética de teste",
            "sha256": sha256_bytes(content),
            "size": len(content),
            "staging_path": path,
        }

    @classmethod
    def make_source_entry(cls, path: str, content: bytes) -> dict[str, object]:
        return {
            **cls.make_file_entry(path, content),
            "component": "dependency",
            "coverage": "source sintético",
            "filename": PurePath(path).name,
            "integrity_authority": "fixture sintética",
            "official_upstream": "https://github.com/example/dependency",
            "status": "verified",
            "version": "1.0",
        }

    def make_manifest(
        self, source_content: bytes = b"source", input_content: bytes = b"input"
    ) -> dict[str, object]:
        return {
            "build_inputs": [
                self.make_file_entry("build-inputs/workflow.yml", input_content)
            ],
            "component": "yt-dlp",
            "correspondence": {
                "certifi": {"status": "conditional"},
                "cpython_runtime": {"status": "conditional"},
                "ejs": {"status": "conditional"},
                "native_curl": {"status": "conditional"},
                "python_p2": {"status": "conditional"},
            },
            "dependencies": [],
            "executable": {
                "embedded_python": "3.10.11 AMD64",
                "filename": "yt-dlp.exe",
                "sha256": OFFICIAL_EXECUTABLE_SHA256,
                "size": 17_840_399,
                "variant": "win_exe",
            },
            "metadata_collections": [],
            "missing_sources": [],
            "provenance_metadata": [
                self.make_file_entry("source-metadata/dependency.json", b"metadata")
            ],
            "release_commit": "f" * 40,
            "release_tag": "2026.08.19",
            "requirements_locks": [],
            "schema_version": 2,
            "source_archive": self.make_file_entry(
                "upstream/yt-dlp.tar.gz", source_content
            ),
            "source_archives": [
                self.make_source_entry("sources/dependency.tar.gz", b"dependency")
            ],
            "source_bundle": {
                "bundle_filename": "bundles/test.zip",
                "checksum_authority": "fixture",
                "completeness_class": "B",
                "scope": "third-party source only",
                "status": "partial-missing-identified-sources",
            },
            "source_commit": "a" * 40,
            "toolchain": {
                "pyinstaller": {"version": "6.21.0"},
                "python": {"embedded_version": "3.10.11"},
            },
            "version": "2026.08.19",
        }

    @staticmethod
    def write_manifest(path: Path, manifest: dict[str, object]) -> None:
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def write_staging(staging: Path) -> None:
        source = staging / "upstream" / "yt-dlp.tar.gz"
        build_input = staging / "build-inputs" / "workflow.yml"
        source_archive = staging / "sources" / "dependency.tar.gz"
        source_metadata = staging / "source-metadata" / "dependency.json"
        source.parent.mkdir(parents=True)
        build_input.parent.mkdir(parents=True)
        source_archive.parent.mkdir(parents=True)
        source_metadata.parent.mkdir(parents=True)
        source.write_bytes(b"source")
        build_input.write_bytes(b"input")
        source_archive.write_bytes(b"dependency")
        source_metadata.write_bytes(b"metadata")

    @staticmethod
    def write_tar_gz(path: Path, members: dict[str, bytes]) -> None:
        with tarfile.open(path, "w:gz") as archive:
            for name, content in members.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))

    def make_python_p2_fixture(
        self, staging: Path
    ) -> tuple[dict[str, object], Path, Path]:
        source_path = staging / "sources" / "setuptools-1.0.tar.gz"
        metadata_path = staging / "metadata" / "setuptools.json"
        lock_path = staging / "locks" / "requirements.txt"
        source_path.parent.mkdir(parents=True)
        metadata_path.parent.mkdir(parents=True)
        lock_path.parent.mkdir(parents=True)
        members = {
            "setuptools-1.0/LICENSE": b"parent license",
            "setuptools-1.0/setuptools/__init__.py": b"__version__ = '1.0'",
            "setuptools-1.0/setuptools/_vendor/demo/__init__.py": b"demo",
            "setuptools-1.0/setuptools/_vendor/demo-1.0.dist-info/LICENSE": b"MIT",
        }
        self.write_tar_gz(source_path, members)
        source_content = source_path.read_bytes()
        source_hash = sha256_bytes(source_content)
        source_url = "https://files.pythonhosted.org/setuptools-1.0.tar.gz"
        metadata = {
            "info": {"name": "setuptools", "version": "1.0"},
            "urls": [
                {
                    "digests": {"sha256": source_hash.casefold()},
                    "filename": "setuptools-1.0.tar.gz",
                    "packagetype": "sdist",
                    "size": len(source_content),
                    "url": source_url,
                }
            ],
        }
        metadata_content = json.dumps(metadata).encode()
        lock_content = (
            f"setuptools==1.0 \\\n    --hash=sha256:{source_hash.casefold()}\n"
        ).encode()
        metadata_path.write_bytes(metadata_content)
        lock_path.write_bytes(lock_content)
        source_entry = self.make_source_entry(
            "sources/setuptools-1.0.tar.gz", source_content
        )
        source_entry.update(
            {
                "component": "setuptools",
                "filename": "setuptools-1.0.tar.gz",
                "origin": source_url,
                "version": "1.0",
            }
        )
        manifest = {
            "build_inputs": [
                self.make_file_entry("locks/requirements.txt", lock_content)
            ],
            "correspondence": {
                "python_p2": {
                    "packages": [
                        {
                            "archive_root": "setuptools-1.0",
                            "build_only_dependencies": [],
                            "component": "setuptools",
                            "coverage": "synthetic source fixture",
                            "dist_info_status": "synthetic",
                            "integrity_authority": "synthetic metadata and lock",
                            "license_files": ["LICENSE"],
                            "lock_hash": source_hash,
                            "lock_path": "locks/requirements.txt",
                            "material_name": "setuptools",
                            "metadata_staging_path": "metadata/setuptools.json",
                            "native_status": "pure Python",
                            "observed_native_extensions": 0,
                            "observed_python_modules": 1,
                            "package": "setuptools",
                            "required_archive_members": ["setuptools/__init__.py"],
                            "source_filename": "setuptools-1.0.tar.gz",
                            "source_sha256": source_hash,
                            "source_size": len(source_content),
                            "source_staging_path": "sources/setuptools-1.0.tar.gz",
                            "technical_status": "resolved",
                            "upstream": "https://github.com/pypa/setuptools",
                            "vendor_status": "synthetic vendor mapped",
                            "version": "1.0",
                        }
                    ],
                    "status": "verified",
                    "vendors": [
                        {
                            "license_paths": [
                                "setuptools/_vendor/demo-1.0.dist-info/LICENSE"
                            ],
                            "material_name": "demo",
                            "source_path_prefix": "setuptools/_vendor/demo/",
                        }
                    ],
                }
            },
            "provenance_metadata": [
                self.make_file_entry("metadata/setuptools.json", metadata_content)
            ],
            "source_archive": self.make_file_entry("upstream/source.tar.gz", b""),
            "source_archives": [source_entry],
        }
        return manifest, metadata_path, lock_path

    def test_official_manifest_is_pinned_and_has_required_provenance(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        path = project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"
        manifest = load_manifest(path)
        text = path.read_text(encoding="utf-8")

        self.assertEqual(sha256_bytes(path.read_bytes()), OFFICIAL_MANIFEST_SHA256)
        self.assertEqual(
            text,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        self.assertEqual(
            manifest["source_archive"]["sha256"], OFFICIAL_SOURCE_ARCHIVE_SHA256
        )
        self.assertEqual(manifest["toolchain"]["python"]["embedded_version"], "3.10.11")
        self.assertEqual(manifest["toolchain"]["pyinstaller"]["version"], "6.22.0")
        self.assertEqual(manifest["source_bundle"]["completeness_class"], "A")
        self.assertEqual(len(manifest["build_inputs"]), 18)
        self.assertEqual(len(manifest["source_archives"]), 36)
        self.assertEqual(len(manifest["provenance_metadata"]), 74)
        self.assertEqual(manifest["metadata_collections"][0]["file_count"], 50)
        self.assertEqual(manifest["metadata_collections"][1]["file_count"], 6)
        self.assertNotRegex(text, r"\b[A-Za-z]:[\\/](?!/)")
        checksum_file = project_dir / "Licencas" / "yt-dlp" / "SHA2-256SUMS"
        self.assertIn(
            f"{OFFICIAL_SOURCE_ARCHIVE_SHA256.lower()}  yt-dlp.tar.gz",
            checksum_file.read_text(encoding="utf-8"),
        )

    def test_official_toolchain_requirements_and_missing_sources_are_explicit(
        self,
    ) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = load_manifest(
            project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"
        )
        pyinstaller = manifest["toolchain"]["pyinstaller"]

        self.assertEqual(pyinstaller["builds_release_tag"], "2026.08.19.215425")
        self.assertEqual(
            pyinstaller["upstream_commit"],
            "70fc17210920bce17f4ab09bbf8104b0dbd45338",
        )
        self.assertEqual(
            pyinstaller["wheel_sha256"],
            "294099ECB5FDD2A13AE4C29006D4E335B697A63B6A16CF052B90EC2B40BEF05A",
        )
        self.assertEqual(pyinstaller["source_asset_status"], "verified-preserved")
        self.assertEqual(
            {item["path"] for item in manifest["requirements_locks"]},
            {
                "build-inputs/yt-dlp-tag/bundle/requirements/curl-cffi.txt",
                "build-inputs/yt-dlp-tag/bundle/requirements/pip.txt",
                "build-inputs/yt-dlp-tag/bundle/requirements/win-x64-pyinstaller.txt",
            },
        )
        self.assertEqual(manifest["missing_sources"], [])
        self.assertEqual(
            manifest["source_bundle"]["status"],
            "technically-complete-pending-legal-review",
        )

    def test_official_cpython_source_and_runtime_metadata_are_closed(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = load_manifest(
            project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"
        )
        cpython = manifest["correspondence"]["cpython_runtime"]

        self.assertEqual(cpython["status"], "verified")
        self.assertEqual(cpython["technical_status"], "resolved")
        self.assertEqual(cpython["archive"]["tag"], "v3.10.11")
        self.assertEqual(
            cpython["archive"]["commit"],
            "7d4cc5aa854fdea4d01a5b9c59e37c6e62f1103d",
        )
        self.assertEqual(
            cpython["archive"]["tree"],
            "70d149737111f058b90938480d20b2a9cb038480",
        )
        self.assertEqual(cpython["setup_python"]["patch_provenance"], "B")
        self.assertFalse(cpython["setup_python"]["runtime_package_downloaded"])
        self.assertFalse(cpython["setup_python"]["exact_job_consumption_proven"])
        verify_cpython_runtime_correspondence(
            manifest,
            evidence_path("compliance_artifacts/yt-dlp/2026.08.19"),
        )

    def test_official_cpython_external_pins_are_exact_and_verified(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        path = project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        cpython = manifest["correspondence"]["cpython_runtime"]

        self.assertEqual(
            {item["component"]: item["version"] for item in cpython["external_pins"]},
            {
                "OpenSSL": "1.1.1t",
                "SQLite": "3.40.1",
                "XZ/liblzma": "5.2.5",
                "bzip2": "1.0.8",
                "libffi runtime": "3.3.0",
                "zlib runtime": "1.2.13",
            },
        )
        self.assertTrue(
            all(
                item["status"] == "verified"
                and item["technical_status"] == "resolved"
                and len(item["source_sha256"]) == 64
                for item in cpython["external_pins"]
            )
        )

        missing = deepcopy(manifest)
        missing["correspondence"]["cpython_runtime"]["external_pins"].pop()
        with self.assertRaisesRegex(SourceBundleError, "Pins externos CPython"):
            validate_manifest_structure(missing)

        wrong_revision = deepcopy(manifest)
        wrong_revision["correspondence"]["cpython_runtime"]["external_pins"][0][
            "source_commit"
        ] = "0" * 40
        with self.assertRaisesRegex(SourceBundleError, "Pins PCbuild CPython"):
            validate_official_identity(wrong_revision)

        wrong_openssl = deepcopy(manifest)
        wrong_openssl["correspondence"]["cpython_runtime"]["external_pins"][0][
            "version"
        ] = "3.0"
        with self.assertRaisesRegex(SourceBundleError, "Archive externo CPython"):
            validate_official_identity(wrong_openssl)

    def test_each_cpython_external_fails_closed_when_absent_or_divergent(
        self,
    ) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )
        staging = evidence_path("compliance_artifacts/yt-dlp/2026.08.19")
        pins = manifest["correspondence"]["cpython_runtime"]["external_pins"]

        for pin in pins:
            with self.subTest(component=pin["component"], case="correct"):
                verify_cpython_external_archive(pin, staging)

            absent = deepcopy(pin)
            absent["source_staging_path"] = (
                f"sources/lot-1f/absent-{pin['source_filename']}"
            )
            with (
                self.subTest(component=pin["component"], case="absent"),
                self.assertRaisesRegex(SourceBundleError, pin["component"]),
            ):
                verify_cpython_external_archive(absent, staging)

            wrong_hash = deepcopy(pin)
            wrong_hash["source_sha256"] = "0" * 64
            with (
                self.subTest(component=pin["component"], case="hash"),
                self.assertRaisesRegex(SourceBundleError, pin["component"]),
            ):
                verify_cpython_external_archive(wrong_hash, staging)

            wrong_tree = deepcopy(pin)
            wrong_tree["source_tree"] = "0" * 40
            with (
                self.subTest(component=pin["component"], case="revision"),
                self.assertRaisesRegex(SourceBundleError, pin["component"]),
            ):
                verify_cpython_external_archive(wrong_tree, staging)

    def test_cpython_runtime_closures_remain_distinct_and_scope_is_material(
        self,
    ) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )
        sources = {item["component"]: item for item in manifest["source_archives"]}
        cpython = manifest["correspondence"]["cpython_runtime"]
        pins = {item["component"]: item for item in cpython["external_pins"]}
        curl_parents = {
            item["component"]: item
            for item in manifest["correspondence"]["native_curl"]["parents"]
        }

        self.assertNotEqual(
            pins["zlib runtime"]["source_commit"],
            curl_parents["zlib"]["revision"],
        )
        self.assertIn("CPython zlib runtime", sources)
        self.assertIn("zlib", sources)
        self.assertIn("CPython libffi runtime", sources)
        self.assertIn("cffi", sources)
        self.assertIn(
            "distinct from curl closure zlib",
            sources["CPython zlib runtime"]["coverage"],
        )
        self.assertIn("libffi-7.dll", sources["CPython libffi runtime"]["coverage"])
        self.assertEqual(
            {item["component"] for item in cpython["bundled_sources"]},
            {"Expat", "mpdecimal"},
        )
        self.assertNotIn("Tcl/Tk/Tix", sources)

    def test_expat_mpdecimal_and_tcltk_scope_is_fail_closed(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )
        cpython = manifest["correspondence"]["cpython_runtime"]
        self.assertEqual(
            {item["component"]: item["version"] for item in cpython["bundled_sources"]},
            {"Expat": "2.5.0", "mpdecimal": "2.5.1"},
        )
        self.assertTrue(
            all(
                item["status"] == "covered-by-parent"
                and item["separate_source_required"] is False
                for item in cpython["bundled_sources"]
            )
        )
        tcltk = next(
            item
            for item in cpython["non_material_externals"]
            if item["component"] == "Tcl/Tk/Tix"
        )
        self.assertEqual(tcltk["status"], "not-required")
        self.assertFalse(tcltk["source_required"])

        opened_parent = deepcopy(manifest)
        opened_parent["correspondence"]["cpython_runtime"]["bundled_sources"][0][
            "separate_source_required"
        ] = True
        with self.assertRaisesRegex(SourceBundleError, "vendorizado CPython"):
            validate_manifest_structure(opened_parent)

    def test_cpython_tag_commit_and_metadata_collection_fail_closed(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )

        wrong_tag = deepcopy(manifest)
        wrong_tag["correspondence"]["cpython_runtime"]["archive"]["commit"] = "0" * 40
        with self.assertRaisesRegex(SourceBundleError, "source CPython"):
            validate_official_identity(wrong_tag)

        wrong_collection = deepcopy(manifest)
        wrong_collection["metadata_collections"][0]["inventory_sha256"] = "0" * 64
        with self.assertRaisesRegex(SourceBundleError, "metadata CPython"):
            validate_official_identity(wrong_collection)

        proprietary = self.make_manifest()
        proprietary["metadata_collections"] = [
            {
                "file_count": 1,
                "inventory_sha256": "A" * 64,
                "origin_authorities": ["https://www.python.org"],
                "purpose": "fixture",
                "staging_root": "licensing/private-runtime-metadata",
            }
        ]
        with self.assertRaisesRegex(SourceBundleError, "proprietário ou privado"):
            validate_manifest_structure(proprietary)

    def test_official_ejs_certdata_and_curl_sources_are_closed(
        self,
    ) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = load_manifest(
            project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"
        )

        ejs = manifest["correspondence"]["ejs"]
        certifi = manifest["correspondence"]["certifi"]
        native_curl = manifest["correspondence"]["native_curl"]
        self.assertEqual(ejs["status"], "verified")
        self.assertEqual(certifi["status"], "verified")
        self.assertEqual(certifi["trusted_certificate_count"], 121)
        self.assertEqual(
            certifi["certdata_commit"],
            "4e9426ae522c67de47ff3e060774328b42df0134",
        )
        self.assertEqual(native_curl["status"], "verified")
        self.assertEqual(
            native_curl["closure_status"], "resolved-source-correspondence"
        )
        self.assertEqual(native_curl["build_reproducibility_status"], "partial")
        self.assertEqual(native_curl["sfparse"]["status"], "covered-by-parent")
        self.assertEqual(
            {item["component"] for item in ejs["bundled_dependencies"]},
            {"Meriyah", "Astring"},
        )
        self.assertTrue(
            all(
                item["source_status"] == "verified"
                for item in ejs["bundled_dependencies"]
            )
        )
        self.assertIn(
            "BoringSSL",
            {item["component"] for item in native_curl["closure"]},
        )
        self.assertTrue(
            all(
                item["status"] in {"verified", "not-required"}
                for item in native_curl["closure"]
            )
        )
        self.assertEqual(
            {item["component"] for item in native_curl["parents"]},
            {
                "BoringSSL",
                "Brotli native",
                "nghttp2",
                "nghttp3",
                "ngtcp2",
                "zlib",
                "zstd",
            },
        )

    def test_official_python_p2_sources_and_vendors_are_closed(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = load_manifest(
            project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"
        )
        python_p2 = manifest["correspondence"]["python_p2"]

        self.assertEqual(python_p2["status"], "verified")
        self.assertEqual(python_p2["technical_status"], "resolved")
        self.assertEqual(
            {item["package"]: item["version"] for item in python_p2["packages"]},
            {
                "brotli": "1.2.0",
                "cffi": "2.1.1",
                "charset-normalizer": "3.5.0",
                "idna": "3.18",
                "pycparser": "3.0",
                "pycryptodomex": "3.23.0",
                "requests": "2.34.2",
                "typing-extensions": "4.16.0",
                "urllib3": "2.7.0",
                "websockets": "16.1.1",
            },
        )
        self.assertEqual(python_p2["vendors"], [])
        self.assertTrue(
            all(
                dependency["material_in_executable"] is False
                and dependency["source_required"] is False
                for dependency in python_p2["build_only_dependencies"]
            )
        )
        self.assertEqual(
            {item["component"] for item in python_p2["build_only_dependencies"]},
            {"Cython", "mypy/mypyc", "packaging", "setuptools"},
        )
        self.assertTrue(
            all(
                closure["status"] == "covered-by-parent"
                and closure["separate_source_required"] is False
                for closure in python_p2["native_closures"]
            )
        )

    def test_python_p2_metadata_lock_and_vendor_map_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            staging = Path(temporary_dir)
            manifest, metadata_path, lock_path = self.make_python_p2_fixture(staging)
            verify_python_p2_correspondence(manifest, staging)

            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["urls"][0]["filename"] = "other.tar.gz"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(SourceBundleError, "sdist PyPI"):
                verify_python_p2_correspondence(manifest, staging)

            metadata["urls"][0]["filename"] = "setuptools-1.0.tar.gz"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            lock_path.write_text("setuptools==1.0\n", encoding="utf-8")
            with self.assertRaisesRegex(SourceBundleError, "Lock Python P2"):
                verify_python_p2_correspondence(manifest, staging)

            source_hash = manifest["correspondence"]["python_p2"]["packages"][0][
                "source_sha256"
            ]
            lock_path.write_text(
                f"setuptools==1.0 --hash=sha256:{source_hash.casefold()}\n",
                encoding="utf-8",
            )
            manifest["correspondence"]["python_p2"]["vendors"][0]["license_paths"] = [
                "setuptools/_vendor/demo-1.0.dist-info/MISSING"
            ]
            with self.assertRaisesRegex(SourceBundleError, "Licença de vendor"):
                verify_python_p2_correspondence(manifest, staging)

            (staging / "sources" / "setuptools-1.0.tar.gz").unlink()
            with self.assertRaisesRegex(SourceBundleError, "sdist Python P2"):
                verify_python_p2_correspondence(manifest, staging)

    def test_official_python_p2_package_vendor_and_native_closure_are_pinned(
        self,
    ) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        path = project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"

        missing_package = json.loads(path.read_text(encoding="utf-8"))
        missing_package["correspondence"]["python_p2"]["packages"].pop()
        with self.assertRaisesRegex(SourceBundleError, "Packages Python P2"):
            validate_official_identity(missing_package)

        wrong_version = json.loads(path.read_text(encoding="utf-8"))
        wrong_version["correspondence"]["python_p2"]["packages"][0]["version"] = "0.0.0"
        with self.assertRaisesRegex(SourceBundleError, "Packages Python P2"):
            validate_official_identity(wrong_version)

        external_vendor = json.loads(path.read_text(encoding="utf-8"))
        external_vendor["correspondence"]["python_p2"]["vendors"] = [
            {
                "license_paths": ["LICENSE"],
                "material_in_executable": True,
                "material_name": "unexpected-external-vendor",
                "parent_package": "setuptools",
                "source_additional_required": False,
                "source_path_prefix": "setuptools/_vendor/unexpected/",
                "technical_status": "covered-by-parent",
                "version": "1.0",
            }
        ]
        with self.assertRaisesRegex(SourceBundleError, "Vendors não materiais"):
            validate_official_identity(external_vendor)

        partial_native = json.loads(path.read_text(encoding="utf-8"))
        partial_native["correspondence"]["python_p2"]["native_closures"][0][
            "status"
        ] = "partial"
        with self.assertRaisesRegex(SourceBundleError, "Closure nativa Python P2"):
            validate_manifest_structure(partial_native)

    def test_commit_snapshot_matches_exact_git_tree(self) -> None:
        content = b"native source\n"
        tree = {
            "sha": "a" * 40,
            "tree": [
                {
                    "path": "src/native.c",
                    "sha": git_blob_sha1(content),
                    "type": "blob",
                }
            ],
            "truncated": False,
        }
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive = Path(temporary_dir) / "component-deadbeef.tar.gz"
            self.write_tar_gz(archive, {"component-deadbeef/src/native.c": content})

            verify_commit_snapshot_archive(
                archive,
                tree,
                expected_root="component-deadbeef",
                strategy="git_archive_exact",
                expected_file_count=1,
            )

    def test_commit_snapshot_revision_divergence_fails_closed(self) -> None:
        expected = b"expected source\n"
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive = Path(temporary_dir) / "component-deadbeef.tar.gz"
            self.write_tar_gz(
                archive, {"component-deadbeef/src/native.c": b"wrong source\n"}
            )
            tree = {
                "tree": [
                    {
                        "path": "src/native.c",
                        "sha": git_blob_sha1(expected),
                        "type": "blob",
                    }
                ],
                "truncated": False,
            }

            with self.assertRaisesRegex(SourceBundleError, "árvore Git"):
                verify_commit_snapshot_archive(
                    archive,
                    tree,
                    expected_root="component-deadbeef",
                    strategy="git_archive_exact",
                    expected_file_count=1,
                )

    def test_sfparse_material_is_accepted_when_covered_by_parent(self) -> None:
        files = {
            "lib/sfparse/sfparse.c": b"sfparse C source\n",
            "lib/sfparse/sfparse.h": b"sfparse header\n",
            "lib/sfparse/COPYING": b"sfparse license\n",
        }
        specification = {
            "material_files": [
                {
                    "git_blob_sha1": git_blob_sha1(content),
                    "path": name,
                    "sha256": sha256_bytes(content),
                    "size": len(content),
                }
                for name, content in files.items()
            ]
        }
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive = Path(temporary_dir) / "nghttp3.tar.gz"
            self.write_tar_gz(
                archive,
                {f"nghttp3-1.0/{name}": content for name, content in files.items()},
            )

            verify_sfparse_coverage(archive, specification)

    def test_sfparse_absent_from_parent_requires_separate_source(self) -> None:
        specification = {
            "material_files": [
                {
                    "git_blob_sha1": git_blob_sha1(b"expected"),
                    "path": "lib/sfparse/sfparse.c",
                    "sha256": sha256_bytes(b"expected"),
                    "size": len(b"expected"),
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive = Path(temporary_dir) / "nghttp3.tar.gz"
            self.write_tar_gz(archive, {"nghttp3-1.0/lib/nghttp3.c": b"nghttp3 source"})

            with self.assertRaisesRegex(SourceBundleError, "sfparse ausente"):
                verify_sfparse_coverage(archive, specification)

    def test_official_parent_revision_cannot_be_changed(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )
        manifest["correspondence"]["native_curl"]["parents"][0]["revision"] = "0" * 40

        with self.assertRaisesRegex(SourceBundleError, "Revisions"):
            validate_official_identity(manifest)

    def test_official_native_parent_cannot_be_removed(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )
        manifest["correspondence"]["native_curl"]["parents"].pop()

        with self.assertRaisesRegex(SourceBundleError, "Parents"):
            validate_official_identity(manifest)

    def test_non_material_submodule_cannot_be_promoted(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )
        submodule = next(
            item
            for item in manifest["correspondence"]["native_curl"]["submodules"]
            if item["path"] == "tests/munit"
        )
        submodule["material"] = True

        with self.assertRaisesRegex(SourceBundleError, "submodules"):
            validate_official_identity(manifest)

    def test_zstd_remains_material_in_windows_native_closure(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = load_manifest(
            project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"
        )
        zstd = next(
            item
            for item in manifest["correspondence"]["native_curl"]["parents"]
            if item["component"] == "zstd"
        )

        self.assertEqual(zstd["technical_status"], "resolved")
        self.assertEqual(zstd["archive_strategy"], "official_recipe_hash")
        self.assertIn("official source archive", zstd["coverage"])

    def test_certdata_fixture_matches_equivalent_pem_set(self) -> None:
        der = b"synthetic DER certificate"
        sha1 = hashlib.sha1(der).digest()

        def octal(value: bytes) -> str:
            return "".join(f"\\{byte:03o}" for byte in value)

        certdata = (
            "# This Source Code Form is subject to test terms.\n\n"
            "BEGINDATA\n"
            "CKA_CLASS CK_OBJECT_CLASS CKO_CERTIFICATE\n"
            "CKA_VALUE MULTILINE_OCTAL\n"
            f"{octal(der)}\nEND\n"
            "CKA_CLASS CK_OBJECT_CLASS CKO_NSS_TRUST\n"
            "CKA_CERT_SHA1_HASH MULTILINE_OCTAL\n"
            f"{octal(sha1)}\nEND\n"
            "CKA_TRUST_SERVER_AUTH CK_TRUST CKT_NSS_TRUSTED_DELEGATOR\n"
        ).encode()
        pem = (
            b"-----BEGIN CERTIFICATE-----\n"
            + b64encode(der)
            + b"\n-----END CERTIFICATE-----\n"
        )

        self.assertEqual(
            trusted_certdata_certificate_hashes(
                certdata, as_of=datetime(2026, 6, 17, tzinfo=timezone.utc)
            ),
            pem_certificate_hashes(pem),
        )

    def test_official_certdata_status_cannot_be_weakened(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )
        manifest["correspondence"]["certifi"]["status"] = "conditional"

        with self.assertRaisesRegex(SourceBundleError, "Certifi/EJS/curl"):
            validate_official_identity(manifest)

    def test_official_astring_source_status_cannot_be_weakened(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )
        next(
            item
            for item in manifest["source_archives"]
            if item["component"] == "Astring"
        )["status"] = "conditional"

        with self.assertRaisesRegex(SourceBundleError, "sources externos"):
            validate_official_identity(manifest)

    def assert_source_fixture_rejects_mutation(
        self, component: str, filename: str
    ) -> None:
        content = f"official {component} source".encode()
        manifest = self.make_manifest()
        entry = self.make_source_entry(f"sources/{filename}", content)
        entry["component"] = component
        manifest["source_archives"].append(entry)
        manifest["source_archives"].sort(key=lambda item: item["staging_path"])
        with tempfile.TemporaryDirectory() as temporary_dir:
            staging = Path(temporary_dir)
            self.write_staging(staging)
            path = staging / "sources" / filename
            path.write_bytes(content)

            verify_staging(manifest, staging)
            path.write_bytes(b"X" * len(content))

            with self.assertRaisesRegex(SourceBundleError, "SHA-256 divergente"):
                verify_staging(manifest, staging)

    def test_astring_source_is_accepted_and_wrong_bytes_fail_closed(self) -> None:
        self.assert_source_fixture_rejects_mutation(
            "Astring", "astring-v1.9.0-source.tar.gz"
        )

    def test_meriyah_source_is_accepted_and_wrong_bytes_fail_closed(self) -> None:
        self.assert_source_fixture_rejects_mutation(
            "Meriyah", "meriyah-v6.1.4-source.tar.gz"
        )

    def test_certdata_is_accepted_and_wrong_bytes_fail_closed(self) -> None:
        self.assert_source_fixture_rejects_mutation(
            "Mozilla certdata", "mozilla-certdata.txt"
        )

    def test_official_native_parent_hash_divergence_fails_closed(self) -> None:
        self.assert_source_fixture_rejects_mutation("nghttp2", "nghttp2-1.63.0.tar.bz2")

    def test_local_native_parent_hash_divergence_fails_closed(self) -> None:
        self.assert_source_fixture_rejects_mutation(
            "zstd", "zstd-794ea1b0-source.tar.gz"
        )

    def test_cpython_source_hash_divergence_fails_closed(self) -> None:
        self.assert_source_fixture_rejects_mutation("CPython", "Python-3.10.11.tar.xz")

    def test_declared_cpython_source_missing_from_staging_fails_closed(self) -> None:
        manifest = self.make_manifest()
        entry = self.make_source_entry(
            "sources/Python-3.10.11.tar.xz", b"synthetic CPython source"
        )
        entry.update(
            {
                "component": "CPython",
                "filename": "Python-3.10.11.tar.xz",
                "version": "3.10.11",
            }
        )
        manifest["source_archives"].append(entry)
        manifest["source_archives"].sort(key=lambda item: item["staging_path"])
        with tempfile.TemporaryDirectory() as temporary_dir:
            staging = Path(temporary_dir)
            self.write_staging(staging)

            with self.assertRaisesRegex(SourceBundleError, "ausente"):
                verify_staging(manifest, staging)

    def test_metadata_collection_inventory_is_deterministic_and_fail_closed(
        self,
    ) -> None:
        manifest = self.make_manifest()
        content = b"official metadata fixture"
        relative = "source-metadata/cpython/metadata.json"
        entry = {
            "relative_path": relative,
            "sha256": sha256_bytes(content),
            "size": len(content),
        }
        manifest["metadata_collections"] = [
            {
                "file_count": 1,
                "inventory_sha256": sha256_bytes(canonical_json_bytes([entry])),
                "origin_authorities": ["https://www.python.org"],
                "purpose": "fixture sintética",
                "staging_root": "source-metadata/cpython",
            }
        ]
        with tempfile.TemporaryDirectory() as temporary_dir:
            staging = Path(temporary_dir)
            self.write_staging(staging)
            path = staging / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(content)

            first = verify_staging(manifest, staging)
            second = verify_staging(manifest, staging)
            self.assertEqual(first, second)

            path.write_bytes(b"tampered metadata fixture")
            with self.assertRaisesRegex(SourceBundleError, "coleção de metadata"):
                verify_staging(manifest, staging)

    def test_declared_certdata_missing_from_staging_fails_closed(self) -> None:
        manifest = self.make_manifest()
        entry = self.make_source_entry(
            "sources/mozilla-certdata.txt", b"synthetic certdata"
        )
        entry["component"] = "Mozilla certdata"
        manifest["source_archives"].append(entry)
        manifest["source_archives"].sort(key=lambda item: item["staging_path"])
        with tempfile.TemporaryDirectory() as temporary_dir:
            staging = Path(temporary_dir)
            self.write_staging(staging)

            with self.assertRaisesRegex(SourceBundleError, "ausente"):
                verify_staging(manifest, staging)

    def test_correct_staging_is_verified_in_deterministic_order(self) -> None:
        manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as temporary_dir:
            staging = Path(temporary_dir)
            self.write_staging(staging)

            inventory = verify_staging(manifest, staging)

        self.assertEqual(
            [entry["relative_path"] for entry in inventory],
            [
                "build-inputs/workflow.yml",
                "source-metadata/dependency.json",
                "sources/dependency.tar.gz",
                "upstream/yt-dlp.tar.gz",
            ],
        )

    def test_missing_file_fails_closed(self) -> None:
        manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as temporary_dir:
            staging = Path(temporary_dir)
            source = staging / "upstream" / "yt-dlp.tar.gz"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"source")

            with self.assertRaisesRegex(SourceBundleError, "ausente"):
                verify_staging(manifest, staging)

    def test_hash_divergence_fails_closed(self) -> None:
        manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as temporary_dir:
            staging = Path(temporary_dir)
            self.write_staging(staging)
            (staging / "build-inputs" / "workflow.yml").write_bytes(b"altered")

            with self.assertRaisesRegex(SourceBundleError, "Tamanho divergente"):
                verify_staging(manifest, staging)

    def test_same_size_hash_divergence_fails_closed(self) -> None:
        manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as temporary_dir:
            staging = Path(temporary_dir)
            self.write_staging(staging)
            (staging / "build-inputs" / "workflow.yml").write_bytes(b"other")

            with self.assertRaisesRegex(SourceBundleError, "SHA-256 divergente"):
                verify_staging(manifest, staging)

    def test_unexpected_file_fails_closed(self) -> None:
        manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as temporary_dir:
            staging = Path(temporary_dir)
            self.write_staging(staging)
            (staging / "extra.txt").write_text("extra", encoding="utf-8")

            with self.assertRaisesRegex(SourceBundleError, "inesperado"):
                verify_staging(manifest, staging)

    def test_absolute_path_in_manifest_is_rejected(self) -> None:
        manifest = self.make_manifest()
        manifest["source_archive"]["staging_path"] = "C:/Users/Test/source.tar.gz"
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "manifest.json"
            self.write_manifest(path, manifest)

            with self.assertRaisesRegex(SourceBundleError, "caminho local|absoluto"):
                load_manifest(path, enforce_official_baseline=False)

    def test_proprietary_source_path_is_rejected(self) -> None:
        manifest = self.make_manifest()
        manifest["build_inputs"][0]["staging_path"] = "app.py"
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "manifest.json"
            self.write_manifest(path, manifest)

            with self.assertRaisesRegex(SourceBundleError, "proprietário"):
                load_manifest(path, enforce_official_baseline=False)

    def test_official_manifest_tampering_is_rejected(self) -> None:
        project_dir = Path(__file__).resolve().parents[1]
        original = project_dir / "Licencas" / "yt-dlp" / "SOURCE_PROVENANCE.json"
        manifest = json.loads(original.read_text(encoding="utf-8"))
        manifest["version"] = "2026.07.05"
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "SOURCE_PROVENANCE.json"
            self.write_manifest(path, manifest)

            with self.assertRaisesRegex(SourceBundleError, "adulterado"):
                load_manifest(path)

    def test_bundle_is_deterministic_and_reopens_against_inventory(self) -> None:
        manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            staging = root / "staging"
            manifest_path = root / "manifest.json"
            first = root / "first.zip"
            second = root / "second.zip"
            self.write_staging(staging)
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
            reopened = verify_bundle(
                manifest_path,
                first,
                enforce_official_baseline=False,
            )
            first_bytes = first.read_bytes()

        self.assertEqual(first_result, second_result)
        self.assertEqual(first_result, reopened)
        self.assertEqual(first_result["bundle_sha256"], sha256_bytes(first_bytes))
        self.assertEqual(first_result["file_count"], 6)

    def test_manifest_build_inputs_must_be_sorted(self) -> None:
        manifest = self.make_manifest()
        second = deepcopy(manifest["build_inputs"][0])
        second["staging_path"] = "build-inputs/a.txt"
        manifest["build_inputs"].append(second)
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "manifest.json"
            self.write_manifest(path, manifest)

            with self.assertRaisesRegex(SourceBundleError, "ordem determinística"):
                load_manifest(path, enforce_official_baseline=False)

    def test_unknown_source_status_is_rejected(self) -> None:
        manifest = self.make_manifest()
        manifest["source_archives"][0]["status"] = "complete"
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "manifest.json"
            self.write_manifest(path, manifest)

            with self.assertRaisesRegex(SourceBundleError, "status inválido"):
                load_manifest(path, enforce_official_baseline=False)


if __name__ == "__main__":
    unittest.main()
