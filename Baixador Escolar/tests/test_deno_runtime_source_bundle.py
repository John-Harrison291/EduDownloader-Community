"""Testes offline da preservação da source closure do Deno 2.9.5."""

from __future__ import annotations

import copy
from contextlib import chdir
import io
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from collections import Counter
from pathlib import Path

from tests.compliance_inputs import evidence_path
import deno_runtime_source_bundle as source_bundle


class DenoRuntimeSourceBundleTests(unittest.TestCase):
    project_dir = Path(__file__).resolve().parents[1]

    def setUp(self):
        self.enterContext(
            patch.object(source_bundle, "_external_evidence_path", evidence_path)
        )

    @classmethod
    def official_evidence(cls) -> tuple[dict, dict]:
        return source_bundle.load_manifest(
            cls.project_dir / source_bundle.DEFAULT_MANIFEST
        )

    def test_official_manifests_are_canonical_pinned_and_portable(self) -> None:
        manifest_path = self.project_dir / source_bundle.DEFAULT_MANIFEST
        notice_path = self.project_dir / source_bundle.DEFAULT_NOTICE_MANIFEST
        notice_text_path = self.project_dir / source_bundle.DEFAULT_NOTICE_TEXT
        manifest, notice = self.official_evidence()

        self.assertEqual(
            source_bundle.sha256_file(manifest_path),
            source_bundle.OFFICIAL_MANIFEST_SHA256,
        )
        self.assertEqual(manifest_path.read_bytes(), source_bundle.formatted(manifest))
        self.assertEqual(
            source_bundle.sha256_file(notice_path),
            source_bundle.OFFICIAL_NOTICE_MANIFEST_SHA256,
        )
        self.assertEqual(notice_path.read_bytes(), source_bundle.formatted(notice))
        self.assertEqual(
            source_bundle.sha256_file(notice_text_path),
            source_bundle.OFFICIAL_NOTICE_TEXT_SHA256,
        )
        self.assertEqual(
            notice_text_path.read_bytes(), source_bundle.render_notice_text(notice)
        )
        evidence_hashes = {
            record["sha256"]
            for component in notice["components"]
            for record in component["license_files"] + component["notice_files"]
        }
        self.assertEqual(
            notice_text_path.read_text(encoding="utf-8").count("SHA-256: "),
            len(evidence_hashes),
        )
        self.assertNotRegex(
            manifest_path.read_text(encoding="utf-8"), r"\b[A-Za-z]:[\\/]"
        )
        self.assertNotRegex(
            notice_path.read_text(encoding="utf-8"), r"\b[A-Za-z]:[\\/]"
        )

    def test_release_authority_target_features_and_candidate_are_exact(self) -> None:
        manifest, _notice = self.official_evidence()

        self.assertEqual(
            manifest["candidate"]["deno_binary"]["version"],
            "2.9.5 x86_64-pc-windows-msvc",
        )
        self.assertEqual(
            manifest["candidate"]["deno_binary"]["sha256"],
            "98F8C2A2D470E4CCB04C935C86FF8050817D877762AEC5EAEEB9E409CCB3B9FD",
        )
        self.assertEqual(manifest["release_build"]["target"], source_bundle.TARGET)
        self.assertEqual(manifest["release_build"]["profile"], "release")
        self.assertEqual(
            manifest["release_build"]["packages"],
            ["deno", "denort", "test_server"],
        )
        self.assertEqual(
            manifest["release_build"]["explicit_features"], ["deno/panic-trace"]
        )
        self.assertTrue(manifest["release_build"]["default_features"])
        self.assertEqual(
            manifest["release_build"]["environment"],
            {"DENO_SNAPSHOT_MINIFY_SOURCES": "1"},
        )
        self.assertFalse(manifest["candidate"]["modified"])

    def test_cargo_target_predicates_and_semver_are_strict(self) -> None:
        for expression in (
            None,
            source_bundle.TARGET,
            "cfg(windows)",
            'cfg(target_os = "windows")',
            'cfg(all(target_arch = "x86_64", target_env = "msvc"))',
            "cfg(not(unix))",
        ):
            self.assertTrue(source_bundle.target_matches(expression))
        for expression in (
            "x86_64-unknown-linux-gnu",
            "cfg(unix)",
            'cfg(target_arch = "aarch64")',
            'cfg(any(target_os = "linux", target_os = "macos"))',
        ):
            self.assertFalse(source_bundle.target_matches(expression))
        with self.assertRaises(source_bundle.SourceBundleError):
            source_bundle.target_matches("cfg(unknown(value))")

        self.assertTrue(source_bundle.version_matches("^1.2", "1.9.0"))
        self.assertFalse(source_bundle.version_matches("^1.2", "2.0.0"))
        self.assertTrue(source_bundle.version_matches("=1.2", "1.2.9+build"))
        self.assertTrue(source_bundle.version_matches(">=0.5.0-rc.1", "0.5.0"))
        self.assertFalse(source_bundle.version_matches("~1.2.3", "1.3.0"))

    def test_feature_expansion_records_optional_and_codegen_requests(self) -> None:
        metadata = {
            "deps": [
                {"alias": "optional_dep", "optional": True},
                {"alias": "codegen_dep", "optional": False},
            ],
            "features": {
                "default": ["dep:optional_dep", "codegen_dep/derive"],
            },
        }

        features, optional, dependency_features = (
            source_bundle.CargoResolver._expand_features(metadata, {"default"})
        )

        self.assertEqual(features, {"default"})
        self.assertEqual(optional, {"optional_dep", "codegen_dep"})
        self.assertEqual(dependency_features, {"codegen_dep": {"derive"}})

    def test_exact_cargo_classification_and_minimum_parent_model(self) -> None:
        manifest, _notice = self.official_evidence()
        counts = manifest["counts"]
        packages = manifest["cargo_resolution"]["packages"]
        classifications = Counter(item["classification"] for item in packages)

        self.assertEqual(counts["lock_packages"], 1133)
        self.assertEqual(counts["workspace"], 82)
        self.assertEqual(counts["registry"], 1051)
        self.assertEqual(counts["material_runtime"], 765)
        self.assertEqual(counts["material_codegen"], 104)
        self.assertEqual(counts["build_only"], 29)
        self.assertEqual(counts["dev_only"], 17)
        self.assertEqual(counts["target_not_applicable"], 68)
        self.assertEqual(counts["optional_disabled"], 12)
        self.assertEqual(counts["unreachable"], 138)
        self.assertEqual(counts["unknown"], 0)
        self.assertEqual(classifications["MATERIAL_RUNTIME"], 765)
        self.assertEqual(classifications["MATERIAL_CODEGEN"], 104)
        self.assertEqual(manifest["minimum_source_parent_model"]["crate_parents"], 810)
        self.assertEqual(manifest["minimum_source_parent_model"]["reused_parents"], 19)

    def test_notice_inventory_is_project_generated_and_complete_as_an_inventory(
        self,
    ) -> None:
        manifest, notice = self.official_evidence()
        components = notice["components"]
        source_parents = Counter(item["source_parent"] for item in components)

        self.assertEqual(
            notice["authority"],
            "PROJECT_GENERATED_FROM_EXACT_MATERIAL_CLOSURE_NOT_UPSTREAM_DENO_NOTICE",
        )
        self.assertEqual(notice["status"], "PARTIAL_GENERATED_INVENTORY")
        self.assertEqual(notice["counts"]["components"], 931)
        self.assertEqual(notice["counts"]["cargo_components"], 869)
        self.assertEqual(notice["counts"]["native_components"], 62)
        self.assertEqual(notice["counts"]["runtime"], 765)
        self.assertEqual(notice["counts"]["codegen"], 104)
        self.assertEqual(notice["counts"]["d11b_initial_text_pending"], 88)
        self.assertEqual(notice["counts"]["d11b_text_resolved"], 73)
        self.assertEqual(notice["counts"]["d11c_initial_text_pending"], 44)
        self.assertEqual(notice["counts"]["d11c_text_resolved"], 28)
        self.assertEqual(notice["counts"]["d11d_initial_text_pending"], 16)
        self.assertEqual(notice["counts"]["d11d_text_resolved"], 1)
        self.assertEqual(notice["counts"]["license_text_resolved"], 916)
        self.assertEqual(notice["counts"]["license_text_pending"], 15)
        self.assertEqual(notice["counts"]["notice_resolved"], 29)
        self.assertEqual(notice["counts"]["notice_not_required"], 27)
        self.assertEqual(notice["counts"]["notice_pending"], 0)
        self.assertEqual(notice["counts"]["license_expression_resolved"], 931)
        self.assertEqual(notice["counts"]["license_expression_pending"], 0)
        self.assertEqual(notice["missing_license_expression"], [])
        self.assertEqual(
            notice["counts"]["license_text_resolved"]
            + notice["counts"]["license_text_pending"],
            len(components),
        )
        self.assertEqual(source_parents["DENO_SOURCE_PARENT"], 59)
        self.assertTrue(
            all(
                item["provenance_method"] == "COVERED_BY_DENO_PARENT"
                for item in components
                if item["source_parent"] == "DENO_SOURCE_PARENT"
            )
        )
        self.assertEqual(
            source_parents["CANONICAL_CRATE"]
            + source_parents["RUSTY_V8_AND_V8_SOURCE_PARENTS"],
            810,
        )
        self.assertEqual(
            len(notice["missing_license_text"]),
            manifest["counts"]["license_text_pending"],
        )
        self.assertEqual(
            len(
                {
                    (item["component"], item["version"], item["source"])
                    for item in components
                }
            ),
            len(components),
        )

    def test_d11h_spdx_snapshot_references_are_pinned_and_exact(self) -> None:
        manifest_path = self.project_dir / source_bundle.SPDX_REFERENCE_MANIFEST
        payload = source_bundle.load_spdx_reference_manifest()

        self.assertEqual(
            source_bundle.sha256_file(manifest_path),
            source_bundle.SPDX_REFERENCE_MANIFEST_SHA256,
        )
        self.assertEqual(manifest_path.read_bytes(), source_bundle.formatted(payload))
        self.assertEqual(payload["snapshot"]["version"], "3.28.0")
        self.assertEqual(payload["snapshot"]["tag"], "v3.28.0")
        self.assertEqual(
            payload["snapshot"]["commit"], source_bundle.SPDX_SNAPSHOT_COMMIT
        )
        self.assertEqual(
            {item["identifier"] for item in payload["references"]},
            {"MIT", "Apache-2.0", "CC0-1.0", "Zlib"},
        )
        self.assertTrue(
            all(
                item["classification"] == "SPDX_CANONICAL_REFERENCE_TEXT"
                and item["source_url"].startswith(
                    "https://raw.githubusercontent.com/spdx/license-list-data/"
                    + source_bundle.SPDX_SNAPSHOT_COMMIT
                    + "/text/"
                )
                for item in payload["references"]
            )
        )

    def test_d11h_spdx_reference_tampering_fails_closed(self) -> None:
        payload = source_bundle.load_spdx_reference_manifest()
        mutations = []

        wrong_identifier = copy.deepcopy(payload)
        wrong_identifier["references"][0]["identifier"] = "Apache-2.0-synthetic"
        mutations.append(("identifier", wrong_identifier))

        unpinned = copy.deepcopy(payload)
        unpinned["snapshot"]["commit"] = "latest"
        mutations.append(("snapshot", unpinned))

        wrong_hash = copy.deepcopy(payload)
        wrong_hash["references"][0]["sha256"] = "0" * 64
        mutations.append(("hash", wrong_hash))

        ambiguous = copy.deepcopy(payload)
        ambiguous["references"][0]["classification"] = "UPSTREAM_LICENSE_TEXT"
        mutations.append(("provenance", ambiguous))

        for name, mutated in mutations:
            with self.subTest(name=name):
                with self.assertRaises(source_bundle.SourceBundleError):
                    source_bundle.validate_spdx_reference_manifest(mutated)

    def test_d11h_expression_mapping_preserves_or_and_with(self) -> None:
        self.assertEqual(
            source_bundle.spdx_expression_identifiers("MIT OR Apache-2.0"),
            ["MIT", "Apache-2.0"],
        )
        self.assertEqual(
            source_bundle.spdx_expression_identifiers("MIT OR Apache-2.0 OR Zlib"),
            ["MIT", "Apache-2.0", "Zlib"],
        )
        self.assertEqual(
            source_bundle.spdx_expression_identifiers(
                "GPL-2.0-or-later WITH Bison-exception-2.2"
            ),
            ["GPL-2.0-or-later", "Bison-exception-2.2"],
        )
        for invalid in ("", "MIT OR", "WITH Bison-exception-2.2"):
            with self.subTest(expression=invalid):
                with self.assertRaises(source_bundle.SourceBundleError):
                    source_bundle.spdx_expression_identifiers(invalid)

    def test_d11h_component_policy_keeps_upstream_and_spdx_separate(self) -> None:
        manifest, notice = self.official_evidence()
        scoped = {
            (item["component"], item["version"]): item
            for item in notice["components"]
            if item.get("d11h_license_policy")
        }

        self.assertEqual(set(scoped), set(source_bundle.D11H_COMPONENT_EXPRESSIONS))
        self.assertEqual(len(scoped), 15)
        self.assertEqual(
            sum(
                item["d11h_license_policy"]["upstream_license_text"] == "ABSENT"
                for item in scoped.values()
            ),
            13,
        )
        self.assertEqual(
            sum(
                item["d11h_license_policy"]["upstream_license_text"] == "PARTIAL"
                for item in scoped.values()
            ),
            2,
        )
        for identity, item in scoped.items():
            with self.subTest(identity=identity):
                policy = item["d11h_license_policy"]
                self.assertEqual(item["license_text_status"], "TEXT_PENDING")
                self.assertEqual(
                    policy["canonical_reference_set"],
                    source_bundle.spdx_expression_identifiers(
                        item["license_expression"]
                    ),
                )
                self.assertEqual(policy["attribution_metadata"], "PARTIAL")
                self.assertEqual(
                    policy["d11f_category"],
                    "D" if " OR " in item["license_expression"] else "C",
                )
                self.assertEqual(policy["legal_review"], "P3_REQUIRED")
                self.assertNotIn("copyright_owner", policy)
                self.assertNotIn("copyright_year", policy)

        for identity in source_bundle.D11H_PARTIAL_UPSTREAM_TEXT:
            self.assertTrue(scoped[identity]["license_files"])
        self.assertEqual(
            manifest["status"]["source_correspondence"], "TECHNICALLY_COMPLETE"
        )
        self.assertEqual(
            manifest["status"]["canonical_reference_coverage"],
            "COMPLETE_FOR_D11H_SCOPE",
        )
        self.assertEqual(manifest["status"]["notice_delivery"], "PENDING_FIX")
        self.assertEqual(manifest["status"]["legal_review"], "P3_REQUIRED")

    def test_d11h_policy_invariants_fail_closed(self) -> None:
        manifest, notice = self.official_evidence()

        missing_or = copy.deepcopy(notice)
        derive = next(
            item
            for item in missing_or["components"]
            if item["component"] == "derive-io" and item["version"] == "0.4.1"
        )
        derive["d11h_license_policy"]["canonical_reference_set"] = ["MIT"]

        invented_attribution = copy.deepcopy(notice)
        attributed = next(
            item
            for item in invented_attribution["components"]
            if item.get("d11h_license_policy")
        )
        attributed["d11h_license_policy"]["copyright_owner"] = "synthetic"

        legal_approved = copy.deepcopy(notice)
        reviewed = next(
            item
            for item in legal_approved["components"]
            if item.get("d11h_license_policy")
        )
        reviewed["d11h_license_policy"]["legal_review"] = "COMPLETE"

        reopened_source = copy.deepcopy(manifest)
        reopened_source["status"]["source_correspondence"] = "PARTIAL"

        for name, mutated_manifest, mutated_notice in (
            ("OR missing", manifest, missing_or),
            ("invented attribution", manifest, invented_attribution),
            ("legal approved", manifest, legal_approved),
            ("source reopened", reopened_source, notice),
        ):
            with self.subTest(name=name):
                with self.assertRaises(source_bundle.SourceBundleError):
                    source_bundle.validate_manifest_structure(
                        mutated_manifest, mutated_notice
                    )

    def test_d11i_review_manifest_is_canonical_complete_and_path_free(self) -> None:
        path = self.project_dir / source_bundle.DEFAULT_REVIEW_MANIFEST
        manifest = source_bundle.load_review_manifest(path)
        roles = Counter(item["role"] for item in manifest["files"])

        self.assertEqual(
            source_bundle.sha256_file(path),
            source_bundle.OFFICIAL_REVIEW_MANIFEST_SHA256,
        )
        self.assertEqual(path.read_bytes(), source_bundle.formatted(manifest))
        self.assertEqual(
            manifest["bundle"]["classification"],
            "COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW",
        )
        self.assertEqual(manifest["payload_inventory"]["file_count"], 1710)
        self.assertEqual(manifest["payload_inventory"]["byte_count"], 338394544)
        self.assertEqual(
            manifest["payload_inventory"]["inventory_sha256"],
            "DCDC88E8E743436EE3B0EA1C6C9A682C5103F5E88C405B175619C787687195F5",
        )
        self.assertEqual(roles["cargo_material_source_archive"], 810)
        self.assertEqual(roles["source_parent_archive"], 4)
        self.assertEqual(roles["spdx_canonical_reference_text"], 4)
        self.assertEqual(roles["upstream_license_text_evidence"], 60)
        self.assertEqual(roles["attribution_or_notice_evidence"], 33)
        self.assertEqual(roles["source_provenance_metadata"], 34)
        self.assertEqual(len(manifest["excluded_evidence"]), 2)
        self.assertEqual(
            {item["reason"] for item in manifest["excluded_evidence"]},
            {"BINARY_ONLY_METADATA_CONTAINS_ABSOLUTE_UPSTREAM_BUILD_PATH"},
        )
        self.assertEqual(
            {item["component"] for item in manifest["source_parents"]},
            {"deno", "rust", "rusty_v8", "v8", "v8_rust"},
        )
        raw = path.read_bytes()
        self.assertNotIn(b"C:/Users/", raw)
        self.assertNotIn(b"C:\\Users\\", raw)
        self.assertNotIn(b"Baixador Escolar", raw)

    def test_d11i_review_policy_accepts_legacy_pending_and_fails_closed(self) -> None:
        manifest, notice = self.official_evidence()
        source_bundle.require_review_candidate(manifest, notice)

        mutations = []
        source_gap = copy.deepcopy(manifest)
        source_gap["counts"]["source_pending"] = 1
        mutations.append((source_gap, notice))
        missing_spdx = copy.deepcopy(manifest)
        missing_spdx["counts"]["canonical_reference_missing"] = 1
        mutations.append((missing_spdx, notice))
        legal_complete = copy.deepcopy(manifest)
        legal_complete["status"]["legal_review"] = "LEGAL_COMPLETE"
        mutations.append((legal_complete, notice))
        wrong_category = copy.deepcopy(notice)
        wrong_category["counts"]["d11h_category_d"] = 4
        mutations.append((manifest, wrong_category))

        for mutated_manifest, mutated_notice in mutations:
            with self.assertRaises(source_bundle.SourceBundleError):
                source_bundle.require_review_candidate(mutated_manifest, mutated_notice)

    def test_d11i_review_manifest_tampering_fails_closed(self) -> None:
        manifest = source_bundle.load_review_manifest()
        mutations = []
        incomplete_or = copy.deepcopy(manifest)
        incomplete_or["spdx"]["identifiers"].remove("Apache-2.0")
        mutations.append(incomplete_or)
        public_release = copy.deepcopy(manifest)
        public_release["bundle"]["classification"] = "PUBLIC_RELEASE_APPROVED"
        mutations.append(public_release)
        modified_frozen = copy.deepcopy(manifest)
        modified_frozen["frozen_candidate"]["modified"] = True
        mutations.append(modified_frozen)
        missing_parent = copy.deepcopy(manifest)
        missing_parent["source_parents"].pop()
        mutations.append(missing_parent)
        missing_crate = copy.deepcopy(manifest)
        crate = next(
            item
            for item in missing_crate["files"]
            if item["role"] == "cargo_material_source_archive"
        )
        missing_crate["files"].remove(crate)
        missing_crate["payload_inventory"] = source_bundle._review_payload_inventory(
            missing_crate["files"]
        )
        mutations.append(missing_crate)

        for mutated in mutations:
            with self.assertRaises(source_bundle.SourceBundleError):
                source_bundle.validate_review_manifest(mutated)

    def test_d11i_review_member_rejects_leakage(self) -> None:
        source_bundle.validate_review_member(
            "evidence/metadata/safe.json", b'{"status":"safe"}\n'
        )
        for path, data in (
            ("sources/deno.exe", b"not executable"),
            ("C:/review/file.txt", b"safe"),
            ("review/unexpected.tmp", b"safe"),
            ("evidence/metadata/local.json", b'{"path":"C:/Users/Operator"}'),
            ("evidence/metadata/drive.json", b'{"path":"D:/private/file"}'),
            ("review/key.txt", b"-----BEGIN PRIVATE KEY-----\nfixture"),
            ("review/activation_issuer/state.json", b"{}"),
        ):
            with self.subTest(path=path):
                with self.assertRaises(source_bundle.SourceBundleError):
                    source_bundle.validate_review_member(path, data)

    def test_d11i_staging_bundle_and_second_assembly_are_deterministic(self) -> None:
        payload = {
            "files": [
                {
                    "logical_path": "review/a.txt",
                    "sha256": source_bundle.sha256_bytes(b"alpha\n"),
                    "size": 6,
                },
                {
                    "logical_path": "review/unicode-ç.json",
                    "sha256": source_bundle.sha256_bytes(b'{"ok":true}\n'),
                    "size": 12,
                },
            ]
        }
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            staging = root / "staging"
            (staging / "review").mkdir(parents=True)
            (staging / "review/a.txt").write_bytes(b"alpha\n")
            (staging / "review/unicode-ç.json").write_bytes(b'{"ok":true}\n')
            (staging / source_bundle.REVIEW_BUNDLE_MANIFEST_NAME).write_bytes(
                source_bundle.formatted(payload)
            )

            inventory = source_bundle.verify_review_staging(
                payload, staging, validate_policy=False
            )
            first = root / "first.zip"
            second = root / "second.zip"
            first_result = source_bundle.assemble_review_bundle(
                payload, staging, first, validate_policy=False
            )
            second_result = source_bundle.assemble_review_bundle(
                payload, staging, second, validate_policy=False
            )
            comparison = source_bundle.compare_review_bundles(first, second)

            self.assertEqual(inventory["file_count"], 3)
            self.assertEqual(
                first_result["inventory_sha256"],
                second_result["inventory_sha256"],
            )
            self.assertEqual(
                first_result["bundle_sha256"], second_result["bundle_sha256"]
            )
            self.assertTrue(comparison["byte_equal"])

            (staging / "unexpected.tmp").write_bytes(b"unexpected")
            with self.assertRaises(source_bundle.SourceBundleError):
                source_bundle.verify_review_staging(
                    payload, staging, validate_policy=False
                )

    def test_d11b_license_reconciliation_is_exact_and_fail_closed(self) -> None:
        _manifest, notice = self.official_evidence()
        components = {
            (item["component"], item["version"]): item for item in notice["components"]
        }

        libuv = components[("libuv-sys-lite", "1.48.3")]
        self.assertIsNone(libuv["license_expression"])
        self.assertEqual(
            libuv["license_expression_status"], "RESOLVED_FROM_LICENSE_FILE"
        )
        self.assertEqual(libuv["license_text_status"], "TEXT_RESOLVED")

        for identity in (("plist", "1.9.0"), ("smartstring", "1.0.1")):
            with self.subTest(identity=identity):
                component = components[identity]
                self.assertEqual(component["license_text_status"], "TEXT_RESOLVED")
                self.assertTrue(
                    any(
                        "LICENCE" in record["path"].upper()
                        for record in component["license_files"]
                    )
                )

        wasmparser = components[("wasmparser", "0.244.0")]
        self.assertIn("LLVM-exception", wasmparser["license_expression"])
        self.assertTrue(
            any(record["role"] == "EXCEPTION" for record in wasmparser["license_files"])
        )
        self.assertEqual(wasmparser["license_text_status"], "TEXT_RESOLVED")

        for identity in (("zune-core", "0.4.12"), ("zune-jpeg", "0.4.13")):
            with self.subTest(identity=identity):
                self.assertEqual(
                    components[identity]["license_text_status"], "TEXT_PENDING"
                )
        self.assertEqual(len(notice["missing_license_text"]), 15)
        self.assertFalse(
            any(
                "CANONICAL_SPDX" in item["provenance_method"]
                for item in notice["components"]
            )
        )
        expected_pending_order = [
            f"{item['component']}@{item['version']}"
            for item in notice["components"]
            if item["license_text_status"] == "TEXT_PENDING"
        ]
        self.assertEqual(notice["missing_license_text"], expected_pending_order)

    def test_d11c_exact_family_workspace_and_partial_pair_evidence(self) -> None:
        _manifest, notice = self.official_evidence()
        components = {
            (item["component"], item["version"]): item for item in notice["components"]
        }
        mappings = [
            item["upstream_mapping"]
            for item in notice["components"]
            if item.get("upstream_mapping")
        ]
        swc = [
            item
            for item in mappings
            if item["repository"] == source_bundle.SWC_REPOSITORY
        ]

        self.assertEqual(len(mappings), 44)
        self.assertEqual(len(swc), 27)
        self.assertEqual(sum(item["component"].startswith("swc_") for item in swc), 23)
        self.assertTrue(
            all(
                item["exact_release_tag"] == "swc_core@v48.0.4"
                and item["evidence_commit"]
                == "b0ab736714f7574cd8e5f12eee224d666f01fccc"
                and item["workspace_license_inherited"]
                and item["resolution_status"] == "TEXT_RESOLVED"
                and item["package_manifest"]["sha256"]
                and item["workspace_manifest"]["sha256"]
                for item in swc
            )
        )
        swc_license_hashes = {
            record["sha256"]
            for item in components.values()
            if item.get("upstream_mapping") in swc
            for record in item["license_files"]
        }
        self.assertEqual(
            swc_license_hashes,
            {"D96EBA1F1881334D50FFC144276DFA98E147A415E7C591ECDFCB81680361DC91"},
        )

        dlopen = components[("dlopen2_derive", "0.4.0")]
        self.assertEqual(dlopen["license_text_status"], "TEXT_RESOLVED")
        self.assertEqual(
            dlopen["upstream_mapping"]["relation"],
            "EXACT_VCS_COMMIT_WORKSPACE_ROOT_LICENSE",
        )

        for identity in (("zune-core", "0.4.12"), ("zune-jpeg", "0.4.13")):
            with self.subTest(identity=identity):
                item = components[identity]
                self.assertEqual(item["license_text_status"], "TEXT_PENDING")
                self.assertEqual(
                    item["upstream_mapping"]["pending_reason"],
                    "EXACT_ROOT_SET_HAS_ZLIB_TEXT_BUT_ONLY_SHORT_APACHE_NOTICE_AND_NO_MIT_TEXT",
                )
                self.assertIn(
                    "7FA429541E55B1509909E058F2D21A37467E4958EC713B357F6E0CF9DC4EE352",
                    {record["sha256"] for record in item["license_files"]},
                )

        derive_pair = {
            components[(name, "0.4.1")]["upstream_mapping"]["crate_vcs_commit"]
            for name in ("derive-io", "derive-io-macros")
        }
        self.assertEqual(derive_pair, {"69a023098378b66e8f8852173b65ca5762b201e2"})
        self.assertEqual(
            components[("sys_traits", "0.1.28")]["upstream_mapping"][
                "crate_vcs_commit"
            ],
            "709e02e198721f81b485c078ccdf1835fa3e6a40",
        )
        self.assertEqual(
            components[("sys_traits_macros", "0.1.0")]["upstream_mapping"][
                "crate_vcs_commit"
            ],
            "75cbf3ea478624cc78275b0264e78e9ae13ce3f5",
        )
        self.assertEqual(notice["license_evidence_index"]["records"], 60)
        self.assertEqual(notice["license_evidence_index"]["mappings"], 44)

    def test_d11d_dlopen2_exact_version_commit_and_root_license(self) -> None:
        _manifest, notice = self.official_evidence()
        component = next(
            item
            for item in notice["components"]
            if item["component"] == "dlopen2" and item["version"] == "0.6.1"
        )
        mapping = component["upstream_mapping"]

        self.assertEqual(component["license_text_status"], "TEXT_RESOLVED")
        self.assertEqual(mapping["resolution_phase"], "D11D")
        self.assertEqual(
            mapping["notice_status"],
            "NOTICE_NOT_REQUIRED_BY_UPSTREAM_STRUCTURE",
        )
        self.assertIsNone(mapping["crate_vcs_commit"])
        self.assertEqual(
            mapping["evidence_commit"],
            "8580a7c1eafad6507b6c5fd37cb2e404af7e214d",
        )
        self.assertEqual(
            mapping["relation"],
            "EXACT_VERSION_COMMIT_CRATE_MANIFEST_MATCH_WORKSPACE_ROOT_LICENSE",
        )
        self.assertEqual(mapping["root_license_paths"], ["LICENSE"])
        self.assertEqual(
            {record["sha256"] for record in component["license_files"]},
            {"39FA265207450E77C62E90C5594A06C085B655D8374C7CED4BF7894B6BD95DD2"},
        )

        evidence_root = (
            evidence_path(source_bundle.WORK_ROOT)
            / "license-evidence/upstream/github/OpenByteDev/dlopen2"
            / mapping["evidence_commit"]
        )
        package_manifest = evidence_root / mapping["package_manifest"]["path"]
        workspace_manifest = evidence_root / mapping["workspace_manifest"]["path"]
        package = source_bundle.tomllib.loads(
            package_manifest.read_text(encoding="utf-8")
        )
        workspace = source_bundle.tomllib.loads(
            workspace_manifest.read_text(encoding="utf-8")
        )
        self.assertEqual(package["package"]["name"], "dlopen2")
        self.assertEqual(package["package"]["version"], "0.6.1")
        self.assertEqual(package["package"]["license"], "MIT")
        self.assertIn("dlopen2", workspace["workspace"]["members"])

        crate_path = evidence_path(source_bundle.CRATE_ROOT / "dlopen2-0.6.1.crate")
        with tarfile.open(crate_path, "r:gz") as archive:
            crate_manifest = archive.extractfile("dlopen2-0.6.1/Cargo.toml.orig").read()
        self.assertEqual(
            crate_manifest.decode("utf-8").splitlines(),
            package_manifest.read_text(encoding="utf-8").splitlines(),
        )

    def test_native_rust_sqlite_and_aws_lc_notice_identities_are_preserved(
        self,
    ) -> None:
        _manifest, notice = self.official_evidence()
        components = {
            (item["component"], item["version"]): item for item in notice["components"]
        }

        self.assertIn(("rust-std", "1.95.0"), components)
        self.assertEqual(
            components[("rust-std", "1.95.0")]["source_parent"],
            "RUST_1_95_SOURCE_PARENT",
        )
        self.assertTrue(
            any(name.startswith("v8-native:") for name, _version in components)
        )
        self.assertTrue(
            any(name.startswith("v8-rust:") for name, _version in components)
        )
        self.assertEqual(
            components[("libsqlite3-sys", "0.38.1")]["license_text_status"],
            "TEXT_RESOLVED",
        )
        self.assertEqual(
            components[("aws-lc-sys", "0.40.0")]["license_text_status"],
            "TEXT_RESOLVED",
        )

    def test_rust_rusty_v8_and_exact_v8_native_closure_are_resolved(self) -> None:
        manifest, _notice = self.official_evidence()
        parents = manifest["parents"]
        trace = manifest["v8_native_closure"]

        self.assertEqual(parents["deno"]["tree"], source_bundle.DENO_TREE)
        self.assertEqual(parents["deno"]["blob_count"], 14728)
        self.assertEqual(parents["rust"]["version"], "1.95.0")
        self.assertEqual(parents["rust"]["commit"], source_bundle.RUST_COMMIT)
        self.assertEqual(parents["rust"]["archive_file_count"], 2325)
        self.assertEqual(parents["rusty_v8"]["crate_version"], "150.4.0")
        self.assertEqual(
            parents["rusty_v8"]["crate_sha256"], source_bundle.V8_CRATE_SHA256
        )
        self.assertEqual(parents["v8"]["revision"], source_bundle.V8_COMMIT)
        self.assertEqual(parents["v8"]["tree"], source_bundle.V8_TREE)
        self.assertEqual(parents["v8"]["blob_count"], 19203)
        self.assertEqual(parents["v8_rust"]["commit"], source_bundle.V8_RUST_COMMIT)
        self.assertEqual(parents["v8_rust"]["tree"], source_bundle.V8_RUST_TREE)
        self.assertEqual(
            parents["v8_rust"]["archive_sha256"],
            source_bundle.V8_RUST_ARCHIVE_SHA256,
        )
        self.assertEqual(parents["v8_rust"]["archive_file_count"], 11275)
        self.assertEqual(manifest["status"]["v8_native_closure"], "RESOLVED")
        self.assertEqual(trace["status"], "RESOLVED_EXACT_GN_TRACE")
        self.assertEqual(manifest["counts"]["source_pending"], 0)
        self.assertEqual(manifest["counts"]["source_blocked"], 0)
        self.assertEqual(manifest["counts"]["open_source_unknown"], 0)

        self.assertEqual(trace["target"]["triple"], source_bundle.TARGET)
        self.assertEqual(
            trace["target"]["toolchain"], source_bundle.V8_GN_DEFAULT_TOOLCHAIN
        )
        self.assertEqual(trace["target"]["profile"], "release")
        self.assertTrue(trace["target"]["simdutf"])
        self.assertEqual(trace["root_target"]["label"], "//:rusty_v8")
        self.assertEqual(trace["root_target"]["type"], "static_library")
        self.assertEqual(trace["root_target"]["output"], "$BUILD_DIR/obj/rusty_v8.lib")
        self.assertEqual(
            trace["gn_args"]["explicit_from_rusty_v8_build_rs"],
            source_bundle.V8_GN_EXPLICIT_ARGS,
        )
        self.assertEqual(
            trace["gn_args"]["effective_source_selection"],
            source_bundle.V8_GN_EFFECTIVE_SOURCE_ARGS,
        )
        self.assertEqual(
            trace["authority"]["rusty_v8_workflow"]["artifact"],
            "rusty_v8_simdutf_release_x86_64-pc-windows-msvc.lib.gz",
        )

        expected_counts = {
            "generated_universe_targets": 731,
            "reached_targets": 356,
            "source_targets": 273,
            "generated_targets": 39,
            "build_only_targets": 44,
            "reached_edges": 1710,
            "declared_source_references": 6647,
            "unique_source_paths": 6576,
            "covered_by_rusty_v8_parent": 4456,
            "covered_by_separate_v8_rust_parent": 793,
            "generated_from_covered_source": 1327,
            "v8_candidates": 14,
            "v8_material_candidates": 10,
            "v8_excluded_candidates": 4,
            "v8_rust_license_components": 45,
            "other_material_v8_third_party": 7,
        }
        self.assertEqual(trace["counts"], expected_counts)
        self.assertEqual(
            trace["closure_targets_sha256"],
            source_bundle.V8_CLOSURE_TARGETS_SHA256,
        )
        self.assertEqual(
            trace["closure_edges_sha256"], source_bundle.V8_CLOSURE_EDGES_SHA256
        )
        self.assertEqual(
            trace["normalized_graph_sha256"],
            source_bundle.V8_NORMALIZED_GRAPH_SHA256,
        )
        self.assertEqual(
            trace["source_path_inventory_sha256"],
            source_bundle.V8_SOURCE_PATH_INVENTORY_SHA256,
        )

    def test_v8_candidates_codegen_and_notices_are_exact(self) -> None:
        manifest, _notice = self.official_evidence()
        trace = manifest["v8_native_closure"]
        candidates = {item["path"]: item for item in trace["candidates"]}

        self.assertEqual(
            {path: item["classification"] for path, item in candidates.items()},
            source_bundle.V8_NATIVE_CLASSIFICATIONS,
        )
        for path, item in candidates.items():
            with self.subTest(path=path):
                if item["material"]:
                    self.assertTrue(item["targets"])
                    self.assertTrue(item["consumer_edges"])
                    self.assertTrue(item["source_paths"])
                    self.assertEqual(item["source_status"], "RESOLVED")
                    self.assertTrue(
                        item["notice_identity_status"].startswith("VERIFIED")
                    )
                else:
                    self.assertFalse(item["targets"])
                    self.assertEqual(
                        item["selection_evidence"],
                        source_bundle.V8_EXCLUDED_CANDIDATE_EVIDENCE[path],
                    )

        icu = candidates["third_party/icu"]
        self.assertEqual(len(icu["targets"]), 8)
        self.assertEqual(len(icu["source_paths"]), 959)
        self.assertEqual(icu["license_expression"], "Unicode-3.0")
        self.assertEqual(len(icu["license_files"]), 1)
        simdutf = candidates["third_party/simdutf"]
        self.assertEqual(len(simdutf["targets"]), 2)
        self.assertEqual(len(simdutf["source_paths"]), 2)
        self.assertEqual(simdutf["source_coverage"], "COVERED_BY_RUSTY_V8_PARENT")
        llvm_libc = candidates["third_party/llvm-libc/src"]
        self.assertEqual(len(llvm_libc["targets"]), 2)
        self.assertEqual(len(llvm_libc["config_source_evidence"]), 1)
        self.assertEqual(len(candidates["third_party/rust"]["license_components"]), 45)
        self.assertTrue(
            all(
                component["license_files"]
                for component in candidates["third_party/rust"]["license_components"]
            )
        )

        self.assertEqual(trace["zlib"]["classification"], "TARGET_NOT_APPLICABLE")
        self.assertFalse(trace["zlib"]["evidence"]["v8_use_zlib"])
        self.assertFalse(trace["zlib"]["evidence"]["v8_enable_snapshot_compression"])
        self.assertEqual(
            candidates["third_party/partition_alloc"]["classification"],
            "FEATURE_DISABLED",
        )
        self.assertEqual(
            candidates["third_party/googletest/src"]["classification"],
            "TEST_ONLY",
        )
        self.assertEqual(len(trace["other_material_v8_third_party"]), 7)
        self.assertTrue(
            all(
                component["license_files"]
                and component["notice_identity_status"] == "VERIFIED"
                for component in trace["other_material_v8_third_party"]
            )
        )
        self.assertIn("//v8:run_torque", trace["codegen"]["targets"]["torque"])
        self.assertIn(
            "//v8:run_mksnapshot_default", trace["codegen"]["targets"]["snapshot"]
        )

    def test_v8_native_trace_tampering_fails_closed(self) -> None:
        manifest, _notice = self.official_evidence()
        official = manifest["v8_native_closure"]

        mutated_traces = []
        wrong_target = copy.deepcopy(official)
        wrong_target["target"]["triple"] = "x86_64-unknown-linux-gnu"
        mutated_traces.append(("target triple", wrong_target))
        wrong_root = copy.deepcopy(official)
        wrong_root["root_target"]["label"] = "//v8:v8"
        mutated_traces.append(("root", wrong_root))
        wrong_arg = copy.deepcopy(official)
        wrong_arg["gn_args"]["explicit_from_rusty_v8_build_rs"]["is_debug"] = True
        mutated_traces.append(("explicit args", wrong_arg))
        wrong_trace_input = copy.deepcopy(official)
        wrong_trace_input["authority"]["gn"]["sha256"] = "0" * 64
        mutated_traces.append(("GN authority", wrong_trace_input))
        wrong_revision = copy.deepcopy(official)
        wrong_revision["source_coverage"]["rusty_v8_parent"]["v8_revision"] = "0" * 40
        mutated_traces.append(("V8 revision", wrong_revision))
        missing_source = copy.deepcopy(official)
        missing_source["candidates"][0]["source_paths"] = []
        mutated_traces.append(("missing source", missing_source))
        unknown = copy.deepcopy(official)
        unknown["remaining_unknowns"] = ["synthetic-unknown"]
        mutated_traces.append(("UNKNOWN", unknown))
        wrong_classification = copy.deepcopy(official)
        wrong_classification["candidates"][0]["classification"] = "UNKNOWN"
        mutated_traces.append(("classification", wrong_classification))
        wrong_edges = copy.deepcopy(official)
        wrong_edges["closure_edges"][0]["to"] = "//synthetic:wrong"
        mutated_traces.append(("trace edge hash", wrong_edges))

        for name, trace in mutated_traces:
            with self.subTest(name=name):
                with self.assertRaises(source_bundle.SourceBundleError):
                    source_bundle.validate_v8_native_closure(trace)

    def test_material_native_sources_and_special_components_are_not_hidden(
        self,
    ) -> None:
        manifest, _notice = self.official_evidence()
        crates = {
            (item["name"], item["version"]): item
            for item in manifest["material_crates"]
        }

        for identity in (
            ("aws-lc-sys", "0.40.0"),
            ("ring", "0.17.14"),
            ("libsqlite3-sys", "0.38.1"),
            ("libz-sys", "1.1.20"),
            ("liblzma-sys", "0.4.6"),
            ("zstd-sys", "2.0.15+zstd.1.5.7"),
        ):
            self.assertGreater(crates[identity]["native_source_count"], 0)
            self.assertEqual(
                crates[identity]["native_source_coverage"], "COVERED_BY_CRATE_PARENT"
            )
        self.assertEqual(
            manifest["special_components"]["typescript_6_0_3"],
            "COVERED_BY_DENO_PARENT_CLI_TSC_00_TYPESCRIPT_JS",
        )
        self.assertEqual(
            manifest["special_components"]["js_snapshots"],
            "GENERATED_WITH_DENO_PARENT_AND_RESOLVED_CARGO_INPUTS",
        )

    def test_partial_closure_blocks_staging_and_complete_bundle(self) -> None:
        manifest, _notice = self.official_evidence()

        with self.assertRaisesRegex(
            source_bundle.SourceBundleError, "licenses pendentes"
        ):
            source_bundle.require_complete(manifest)

        no_text_gap = copy.deepcopy(manifest)
        no_text_gap["counts"]["license_text_pending"] = 0
        with self.assertRaisesRegex(
            source_bundle.SourceBundleError, "classe A ausente"
        ):
            source_bundle.require_complete(no_text_gap)

        class_a_without_notice = copy.deepcopy(no_text_gap)
        class_a_without_notice["status"]["open_source_correspondence"] = "A"
        with self.assertRaisesRegex(
            source_bundle.SourceBundleError, "notice inventory incompleto"
        ):
            source_bundle.require_complete(class_a_without_notice)

        complete = copy.deepcopy(class_a_without_notice)
        complete["status"]["notice_inventory"] = "COMPLETE_GENERATED_INVENTORY"
        source_bundle.require_complete(complete)

    def test_manifest_tampering_and_prohibited_payloads_fail_closed(self) -> None:
        manifest, notice = self.official_evidence()
        wrong_count = copy.deepcopy(manifest)
        wrong_count["counts"]["material_runtime"] -= 1
        with self.assertRaisesRegex(
            source_bundle.SourceBundleError, "manifest count diverge"
        ):
            source_bundle.validate_manifest_structure(wrong_count, notice)

        missing_text = copy.deepcopy(notice)
        resolved = next(
            item
            for item in missing_text["components"]
            if item.get("initial_d11b_text_pending")
            and item["license_text_status"] == "TEXT_RESOLVED"
        )
        resolved["license_files"] = []
        with self.assertRaisesRegex(
            source_bundle.SourceBundleError, "resolved component sem texto"
        ):
            source_bundle.validate_manifest_structure(manifest, missing_text)

        wrong_dlopen_commit = copy.deepcopy(notice)
        dlopen = next(
            item
            for item in wrong_dlopen_commit["components"]
            if item["component"] == "dlopen2" and item["version"] == "0.6.1"
        )
        dlopen["upstream_mapping"]["evidence_commit"] = "0" * 40
        with self.assertRaisesRegex(
            source_bundle.SourceBundleError, "D11D dlopen2 exact-version mapping"
        ):
            source_bundle.validate_manifest_structure(manifest, wrong_dlopen_commit)

        source_bundle.validate_source_member("sources/lib.rs", b"pub fn safe() {}\n")
        for name, data in (
            ("sources/tool.exe", b"not executable"),
            ("sources/native.bin", b"MZsynthetic"),
            ("sources/key.txt", b"-----BEGIN PRIVATE KEY-----\nfixture"),
            ("activation_issuer/module.rs", b"source"),
        ):
            with self.subTest(name=name):
                with self.assertRaises(source_bundle.SourceBundleError):
                    source_bundle.validate_source_member(name, data)

    def test_crate_identity_checksum_and_license_metadata_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            crate_path = Path(temporary_dir) / "fixture-1.0.0.crate"
            members = {
                "fixture-1.0.0/Cargo.toml": (
                    b'[package]\nname = "fixture"\nversion = "1.0.0"\nlicense = "MIT"\n'
                ),
                "fixture-1.0.0/src/lib.rs": b"pub fn fixture() {}\n",
                "fixture-1.0.0/LICENSE": b"synthetic license fixture\n",
            }
            with tarfile.open(crate_path, "w:gz") as archive:
                for name, data in members.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            package = {
                "name": "fixture",
                "version": "1.0.0",
                "checksum": source_bundle.sha256_file(crate_path),
                "license_expression": "Apache-2.0",
                "links": None,
            }

            with self.assertRaisesRegex(
                source_bundle.SourceBundleError,
                "crate/index license metadata diverge",
            ):
                source_bundle.inspect_crate(crate_path, package)

            package["license_expression"] = "MIT"
            package["checksum"] = "0" * 64
            with self.assertRaisesRegex(
                source_bundle.SourceBundleError, "crate checksum diverge"
            ):
                source_bundle.inspect_crate(crate_path, package)

    def test_preserved_local_evidence_matches_the_tracked_manifests(self) -> None:
        source_root = evidence_path("build-compliance-deno/work/deno/deno-2.9.5")
        if not source_root.is_dir():
            self.skipTest("evidência D10 local ignorada pelo Git não está disponível")
        manifest, notice = self.official_evidence()

        notice_text = self.project_dir / source_bundle.DEFAULT_NOTICE_TEXT
        external_root = evidence_path(source_bundle.WORK_ROOT).parent
        with (
            chdir(external_root),
            patch.object(source_bundle, "PROJECT_ROOT", external_root),
        ):
            source_bundle.verify_evidence(
                manifest, notice, source_root, notice_text_path=notice_text
            )


if __name__ == "__main__":
    unittest.main()
