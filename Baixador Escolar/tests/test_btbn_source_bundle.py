"""Testes offline dos bundles de source do candidato FFmpeg BtbN."""

from __future__ import annotations

import io
import hashlib
import json
import tarfile
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tests.compliance_inputs import evidence_path as compliance_input
from btbn_source_bundle import (
    C4D_PACKAGES,
    DEFAULT_MANIFEST,
    OFFICIAL_BTBN_COMMIT,
    OFFICIAL_BUNDLE_CLASSIFICATION,
    OFFICIAL_FFMPEG_COMMIT,
    PARTIAL_BUNDLE_CLASSIFICATION,
    SourceBundleError,
    _validate_c7_runtime_closure,
    _validate_c5_hardware_closure,
    _verify_cargo_closure,
    _validate_manifest,
    assemble_bundle,
    formatted_json_bytes,
    load_manifest,
    sha256_bytes,
    verify_bundle,
    verify_staging,
)


class BtbnSourceBundleTests(unittest.TestCase):
    """Exercita as invariantes fail-closed sem rede ou sources reais."""

    @staticmethod
    def _git_blob_sha(content: bytes) -> str:
        header = f"blob {len(content)}\0".encode("ascii")
        return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()

    @staticmethod
    def _git_tree_sha(entries: dict[str, tuple[str, str]]) -> str:
        content = b"".join(
            f"{mode} {name}\0".encode("utf-8") + bytes.fromhex(sha)
            for name, (mode, sha) in sorted(entries.items())
        )
        header = f"tree {len(content)}\0".encode("ascii")
        return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()

    @staticmethod
    def _write_tar(path: Path, members: dict[str, bytes]) -> None:
        with tarfile.open(path, "w:gz") as archive:
            for name, content in sorted(members.items()):
                member = tarfile.TarInfo(name)
                member.mtime = 0
                member.mode = 0o644
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))

    @staticmethod
    def _entry(relative: str, content: bytes) -> dict[str, object]:
        return {
            "relative_path": relative,
            "sha256": sha256_bytes(content),
            "size": len(content),
        }

    @staticmethod
    def _source(
        relative: str,
        content: bytes,
        *,
        root: str,
        tree: str,
        tree_metadata: str,
        count: int,
        required: list[str],
    ) -> dict[str, object]:
        return {
            "acquisition_url": "https://example.invalid/source.tar.gz",
            "authority": "local_calculated_verified_revision",
            "license_declared_upstream": "fixture terms",
            "license_files": ["LICENSE"],
            "relative_path": relative,
            "required_files": required,
            "sha256": sha256_bytes(content),
            "size": len(content),
            "tree_verification": {
                "allowed_missing": [],
                "archive_blob_count": count,
                "archive_root": root,
                "eol_normalized_paths": [],
                "expected_blob_count": count,
                "strategy": "git_tree_blob_comparison",
                "tree": tree,
                "tree_metadata": tree_metadata,
                "tree_truncated": False,
            },
        }

    def _fixture(self, root: Path) -> tuple[dict[str, object], Path, Path]:
        staging = root / "staging"
        sources = staging / "sources"
        metadata = staging / "metadata"
        sources.mkdir(parents=True)
        metadata.mkdir(parents=True)

        btbn_commit = "a" * 40
        btbn_tree = "b" * 40
        btbn_members = {
            "fixture-btbn/LICENSE": b"MIT fixture\n",
            "fixture-btbn/build.sh": b"#!/bin/sh\n",
            "fixture-btbn/patches/demo.patch": b"patch fixture\n",
        }
        btbn_path = sources / "btbn.tar.gz"
        self._write_tar(btbn_path, btbn_members)
        btbn_blobs = {
            name.removeprefix("fixture-btbn/"): content
            for name, content in btbn_members.items()
        }
        btbn_commit_json = json.dumps(
            {"sha": btbn_commit, "tree": {"sha": btbn_tree}}
        ).encode()
        btbn_tree_json = json.dumps(
            {
                "sha": btbn_tree,
                "tree": [
                    {
                        "path": name,
                        "sha": self._git_blob_sha(content),
                        "type": "blob",
                    }
                    for name, content in sorted(btbn_blobs.items())
                ],
                "truncated": False,
            }
        ).encode()
        (metadata / "btbn-commit.json").write_bytes(btbn_commit_json)
        (metadata / "btbn-tree.json").write_bytes(btbn_tree_json)

        component_commit = "c" * 40
        component_tree = "d" * 40
        component_members = {
            "fixture-component/LICENSE": b"BSD fixture\n",
            "fixture-component/configure": b"configure fixture\n",
        }
        component_path = sources / "component.tar.gz"
        self._write_tar(component_path, component_members)
        component_blobs = {
            name.removeprefix("fixture-component/"): content
            for name, content in component_members.items()
        }
        commit_json = json.dumps(
            {"sha": component_commit, "tree": {"sha": component_tree}}
        ).encode()
        tree_json = json.dumps(
            {
                "sha": component_tree,
                "tree": [
                    {
                        "path": name,
                        "sha": self._git_blob_sha(content),
                        "type": "blob",
                    }
                    for name, content in sorted(component_blobs.items())
                ],
                "truncated": False,
            }
        ).encode()
        tag_json = json.dumps(
            {
                "object": {"sha": component_commit, "type": "commit"},
                "sha": "e" * 40,
                "tag": "v1.0",
            }
        ).encode()
        (metadata / "component-commit.json").write_bytes(commit_json)
        (metadata / "component-tree.json").write_bytes(tree_json)
        (metadata / "component-tag.json").write_bytes(tag_json)

        btbn_source = self._source(
            "sources/btbn.tar.gz",
            btbn_path.read_bytes(),
            root="fixture-btbn",
            tree=btbn_tree,
            tree_metadata="metadata/btbn-tree.json",
            count=len(btbn_blobs),
            required=["build.sh"],
        )
        component_source = self._source(
            "sources/component.tar.gz",
            component_path.read_bytes(),
            root="fixture-component",
            tree=component_tree,
            tree_metadata="metadata/component-tree.json",
            count=len(component_blobs),
            required=["configure"],
        )
        manifest: dict[str, object] = {
            "authoritative_note": "fixture parcial",
            "batch": {
                "external_parent_limit": 16,
                "id": "C1",
                "preserved_parent_count": 1,
                "selection": ["component"],
                "status": "SOURCE_CLOSURE_PRESERVATION_STARTED",
            },
            "btbn_snapshot": {
                "commit": btbn_commit,
                "metadata": [
                    self._entry("metadata/btbn-commit.json", btbn_commit_json),
                    self._entry("metadata/btbn-tree.json", btbn_tree_json),
                ],
                "preservation_status": "PRESERVED",
                "source": btbn_source,
                "tree": btbn_tree,
            },
            "bundle": {
                "bundle_filename": "fixture-PARTIAL.zip",
                "classification": PARTIAL_BUNDLE_CLASSIFICATION,
                "deterministic_zip": True,
                "root": "fixture-source-partial",
            },
            "candidate": {
                "btbn_commit": btbn_commit,
                "ffmpeg_commit": component_commit,
                "release": "fixture",
                "variant": "fixture",
            },
            "parent_status": {
                "baseline_parent_count": 2,
                "counts_for_baseline_81": {
                    "BLOCKED": 0,
                    "BUILD_ONLY": 0,
                    "CONDITIONAL": 0,
                    "NOT_REQUIRED": 0,
                    "PENDING": 1,
                    "PRESERVED": 1,
                },
                "source_closure": "PARTIAL",
            },
            "parents": [
                {
                    "batch": "C1",
                    "class": "A",
                    "component": "component",
                    "dedupe_key": "https://example.invalid/component|v1.0",
                    "full_revision": component_commit,
                    "metadata": [
                        self._entry("metadata/component-commit.json", commit_json),
                        self._entry("metadata/component-tree.json", tree_json),
                        self._entry("metadata/component-tag.json", tag_json),
                    ],
                    "pin_kind": "git_tag_or_ref",
                    "preservation_status": "PRESERVED",
                    "recipe_pin": "v1.0",
                    "ref": "v1.0",
                    "source": component_source,
                    "source_type": "Git",
                    "tag_object": "e" * 40,
                    "tree": component_tree,
                },
                {
                    "batch": None,
                    "class": "B",
                    "component": "pending",
                    "dedupe_key": "https://example.invalid/pending|1",
                    "full_revision": None,
                    "metadata": [],
                    "pin_kind": "release_archive",
                    "preservation_status": "PENDING",
                    "recipe_pin": "1",
                    "ref": None,
                    "source": None,
                    "source_type": "release archive",
                    "tag_object": None,
                    "tree": None,
                },
            ],
            "patches": [
                {
                    "application_status": "BLOCKED",
                    "applies_to": "pending",
                    "path_in_btbn_snapshot": "patches/demo.patch",
                    "preimage_status": "BLOCKED_UNTIL_PARENT_SOURCE_BATCH",
                    "sha256": sha256_bytes(b"patch fixture\n"),
                    "size": len(b"patch fixture\n"),
                }
            ],
            "proprietary_source_policy": {
                "allowed_roots": ["metadata", "sources"],
                "forbidden_markers": [
                    "activation_issuer",
                    "activation.dat",
                    ".edulic",
                    ".edureq",
                    "dpapi",
                ],
            },
            "recorded_on": "2026-08-28",
            "schema_version": 1,
            "source_correspondence": "PARTIAL",
            "transitives_discovered": [],
            "windows": {
                "current_windows": "PROVEN_COMPATIBLE",
                "windows_10_before_22h2": "NOT_PROVEN_OWNER_DECISION_REQUIRED",
            },
        }
        manifest_path = root / "manifest.json"
        self._write_manifest(manifest_path, manifest)
        return manifest, manifest_path, staging

    def _patch_fixture(
        self,
        root: Path,
        *,
        component: str,
        transitions: list[tuple[bytes, bytes]],
        mismatch_index: int | None = None,
    ) -> tuple[dict[str, object], Path, Path]:
        manifest, manifest_path, staging = self._fixture(root)
        sources = staging / "sources"
        metadata = staging / "metadata"
        parent = manifest["parents"][0]
        parent["component"] = component

        license_content = b"BSD fixture\n"
        initial = transitions[0][0]
        final = transitions[-1][1]
        component_members = {
            "fixture-component/LICENSE": license_content,
            "fixture-component/hello.txt": initial,
        }
        component_path = sources / "component.tar.gz"
        self._write_tar(component_path, component_members)
        component_tree_entries = {
            "LICENSE": ("100644", self._git_blob_sha(license_content)),
            "hello.txt": ("100644", self._git_blob_sha(initial)),
        }
        component_tree = self._git_tree_sha(component_tree_entries)
        component_commit = parent["full_revision"]
        component_commit_json = json.dumps(
            {"sha": component_commit, "tree": {"sha": component_tree}}
        ).encode()
        component_tree_json = json.dumps(
            {
                "sha": component_tree,
                "tree": [
                    {"mode": mode, "path": name, "sha": sha, "type": "blob"}
                    for name, (mode, sha) in sorted(component_tree_entries.items())
                ],
                "truncated": False,
            }
        ).encode()
        (metadata / "component-commit.json").write_bytes(component_commit_json)
        (metadata / "component-tree.json").write_bytes(component_tree_json)
        parent["tree"] = component_tree
        parent["source"] = self._source(
            "sources/component.tar.gz",
            component_path.read_bytes(),
            root="fixture-component",
            tree=component_tree,
            tree_metadata="metadata/component-tree.json",
            count=2,
            required=["hello.txt"],
        )
        parent["metadata"] = [
            self._entry("metadata/component-commit.json", component_commit_json),
            self._entry("metadata/component-tree.json", component_tree_json),
            parent["metadata"][2],
        ]

        patches: list[dict[str, object]] = []
        replay_patches: list[dict[str, object]] = []
        btbn_members = {
            "fixture-btbn/LICENSE": b"MIT fixture\n",
            "fixture-btbn/build.sh": b"#!/bin/sh\n",
        }
        for index, (before, after) in enumerate(transitions, start=1):
            expected_before = (
                b"not-the-preimage\n" if mismatch_index == index else before
            )
            relative = f"patches/{component}/{index:02d}.patch"
            content = (
                b"From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\n"
                b"From: Fixture <fixture@example.invalid>\n"
                b"Date: Thu, 1 Jan 1970 00:00:00 +0000\n"
                + f"Subject: [PATCH] fixture {index}\n\n".encode()
                + b"---\n hello.txt | 2 +-\n 1 file changed, 1 insertion(+), 1 deletion(-)\n\n"
                + b"diff --git a/hello.txt b/hello.txt\n"
                + f"index {self._git_blob_sha(expected_before)[:7]}..{self._git_blob_sha(after)[:7]} 100644\n".encode()
                + b"--- a/hello.txt\n+++ b/hello.txt\n@@ -1 +1 @@\n-"
                + expected_before.rstrip(b"\n")
                + b"\n+"
                + after.rstrip(b"\n")
                + b"\n-- \n2.39.0\n"
            )
            btbn_members[f"fixture-btbn/{relative}"] = content
            patch_entry = {
                "application_order": index,
                "application_status": "APPLIES_CLEANLY",
                "applies_to": component,
                "full_recipe_replay_claimed": False,
                "path_in_btbn_snapshot": relative,
                "preimage_status": "EXACT_UPSTREAM_TREE_VERIFIED",
                "replay_metadata": f"metadata/{component}-patch-replay.json",
                "sha256": sha256_bytes(content),
                "size": len(content),
                "target_files": ["hello.txt"],
            }
            patches.append(patch_entry)
            replay_patches.append(
                {
                    "application_order": index,
                    "path_in_btbn_snapshot": relative,
                    "sha256": sha256_bytes(content),
                    "size": len(content),
                    "target_files": ["hello.txt"],
                }
            )

        btbn_path = sources / "btbn.tar.gz"
        self._write_tar(btbn_path, btbn_members)
        btbn_blobs = {
            name.removeprefix("fixture-btbn/"): content
            for name, content in btbn_members.items()
        }
        btbn_tree_entries = {
            name: ("100644", self._git_blob_sha(content))
            for name, content in btbn_blobs.items()
        }
        btbn_tree = self._git_tree_sha(btbn_tree_entries)
        btbn_commit = manifest["btbn_snapshot"]["commit"]
        btbn_commit_json = json.dumps(
            {"sha": btbn_commit, "tree": {"sha": btbn_tree}}
        ).encode()
        btbn_tree_json = json.dumps(
            {
                "sha": btbn_tree,
                "tree": [
                    {"mode": mode, "path": name, "sha": sha, "type": "blob"}
                    for name, (mode, sha) in sorted(btbn_tree_entries.items())
                ],
                "truncated": False,
            }
        ).encode()
        (metadata / "btbn-commit.json").write_bytes(btbn_commit_json)
        (metadata / "btbn-tree.json").write_bytes(btbn_tree_json)
        manifest["btbn_snapshot"].update(
            {
                "metadata": [
                    self._entry("metadata/btbn-commit.json", btbn_commit_json),
                    self._entry("metadata/btbn-tree.json", btbn_tree_json),
                ],
                "source": self._source(
                    "sources/btbn.tar.gz",
                    btbn_path.read_bytes(),
                    root="fixture-btbn",
                    tree=btbn_tree,
                    tree_metadata="metadata/btbn-tree.json",
                    count=len(btbn_blobs),
                    required=["build.sh"],
                ),
                "tree": btbn_tree,
            }
        )

        final_tree = self._git_tree_sha(
            {
                "LICENSE": ("100644", self._git_blob_sha(license_content)),
                "hello.txt": ("100644", self._git_blob_sha(final)),
            }
        )
        replay = {
            "application_status": "APPLIES_CLEANLY",
            "baseline_tree": component_tree,
            "component": component,
            "final_tree_after_patch_sequence": final_tree,
            "full_recipe_replay_claimed": False,
            "patch_count": len(patches),
            "patches": replay_patches,
            "preimage_verification": "ALL_GIT_BLOBS_MATCH_EXACT_UPSTREAM_TREE",
            "schema_version": 1,
        }
        replay_content = formatted_json_bytes(replay)
        replay_path = metadata / f"{component}-patch-replay.json"
        replay_path.write_bytes(replay_content)
        parent["metadata"].append(
            self._entry(f"metadata/{component}-patch-replay.json", replay_content)
        )
        parent["patch_application"] = "APPLIES_CLEANLY"
        parent["patches"] = [item["path_in_btbn_snapshot"] for item in patches]
        manifest["patches"] = patches
        self._write_manifest(manifest_path, manifest)
        return manifest, manifest_path, staging

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
        path.write_bytes(formatted_json_bytes(manifest))

    @staticmethod
    def _validate_c5(manifest: dict[str, object]) -> None:
        transitives = {
            item["component"]: item for item in manifest["transitives_discovered"]
        }
        _validate_c5_hardware_closure(
            manifest,
            manifest["parents"],
            manifest["dependency_parents"],
            transitives,
        )

    @staticmethod
    def _validate_c7(manifest: dict[str, object]) -> None:
        transitives = {
            item["component"]: item for item in manifest["transitives_discovered"]
        }
        _validate_c7_runtime_closure(manifest, manifest["parents"], transitives)

    def _cargo_closure_fixture(
        self, root: Path
    ) -> tuple[dict[str, object], dict[str, object], Path, Path]:
        source_path = compliance_input(
            "build-compliance-ffmpeg-btbn/autobuild-2026-08-25-13-06/"
            "source-staging/metadata/rav1e-cargo-closure-c4d.json"
        )
        document = json.loads(source_path.read_text(encoding="utf-8"))
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        staging = root / "staging"
        evidence_path = staging / "metadata/rav1e-cargo-closure-c4d.json"
        evidence_path.parent.mkdir(parents=True)
        evidence_path.write_bytes(formatted_json_bytes(document))
        return manifest, document, staging, evidence_path

    def test_official_manifest_has_fixed_core_identities_and_complete_status(
        self,
    ) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        self.assertEqual(manifest["candidate"]["btbn_commit"], OFFICIAL_BTBN_COMMIT)
        self.assertEqual(manifest["candidate"]["ffmpeg_commit"], OFFICIAL_FFMPEG_COMMIT)
        lame = next(
            item for item in manifest["parents"] if item["component"] == "libmp3lame"
        )
        self.assertEqual(lame["full_revision"], "6761")
        self.assertEqual(
            manifest["source_correspondence"],
            "A_TECHNICALLY_COMPLETE_FOR_LEGAL_REVIEW",
        )
        self.assertEqual(
            manifest["bundle"]["classification"],
            OFFICIAL_BUNDLE_CLASSIFICATION,
        )

    def test_official_tags_resolve_to_full_commit_tree_and_tag_object(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        for component in ("mbedtls", "openssl", "Vulkan-Headers"):
            parent = next(
                item for item in manifest["parents"] if item["component"] == component
            )
            self.assertRegex(parent["full_revision"], r"^[0-9a-f]{40}$")
            self.assertRegex(parent["tree"], r"^[0-9a-f]{40}$")
            self.assertRegex(parent["tag_object"], r"^[0-9a-f]{40}$")

    def test_official_mbedtls_transitives_are_fully_preserved(
        self,
    ) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        dependencies = {
            item["component"]: item for item in manifest["dependency_parents"]
        }
        self.assertEqual(
            dependencies["mbedtls-framework"]["preservation_status"],
            "PRESERVED",
        )
        self.assertEqual(
            dependencies["TF-PSA-Crypto"]["preservation_status"],
            "PRESERVED",
        )
        self.assertEqual(
            dependencies["mldsa-native"]["preservation_status"], "PRESERVED"
        )
        mbedtls = next(
            item for item in manifest["parents"] if item["component"] == "mbedtls"
        )
        self.assertEqual(mbedtls["component_result"], "RESOLVED")

    def test_missing_mbedtls_child_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        manifest["dependency_parents"] = [
            item
            for item in manifest["dependency_parents"]
            if item["component"] != "mldsa-native"
        ]
        with self.assertRaisesRegex(SourceBundleError, "dependency parents"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_openssl_conditional_submodule_is_rejected_after_resolution(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        submodule = next(
            item
            for item in manifest["transitives_discovered"]
            if str(item["component"]).startswith("openssl/")
        )
        submodule["status"] = "CONDITIONAL"
        counts = manifest["parent_status"]["transitive_classification_counts"]
        counts["NOT_REQUIRED"] -= 1
        counts["CONDITIONAL"] = 1
        with self.assertRaisesRegex(SourceBundleError, "OpenSSL"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_material_parent_total_closes_runtime_sources_after_c7(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        status = manifest["parent_status"]
        self.assertEqual(status["source_parent_record_count"], 142)
        self.assertEqual(status["adjusted_material_parent_count"], 138)
        counts = status["counts_for_material_parents_138"]
        self.assertEqual(counts["PRESERVED"], 138)
        self.assertEqual(counts["PENDING"], 0)
        self.assertEqual(counts["BLOCKED"], 0)
        dependencies = manifest["dependency_parents"]
        self.assertEqual(len(dependencies), 58)
        self.assertTrue(
            {
                "TF-PSA-Crypto",
                "fast_float",
                "graphengine",
                "highway",
                "mbedtls-framework",
                "mldsa-native",
            }.issubset(
                {
                    item["component"]
                    for item in dependencies
                    if item["preservation_status"] == "PRESERVED"
                }
            )
        )

    def test_official_graphengine_is_preserved_and_zimg_is_resolved(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        graphengine = next(
            item
            for item in manifest["dependency_parents"]
            if item["component"] == "graphengine"
        )
        self.assertEqual(graphengine["preservation_status"], "PRESERVED")
        self.assertEqual(graphengine["component_result"], "RESOLVED")
        zimg = next(item for item in manifest["parents"] if item["component"] == "zimg")
        self.assertEqual(zimg["component_result"], "RESOLVED")

    def test_new_c3_submodules_are_explicitly_not_required(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        transitives = {
            item["component"]: item for item in manifest["transitives_discovered"]
        }
        self.assertEqual(
            transitives["graphengine/test/googletest"]["status"], "NOT_REQUIRED"
        )
        self.assertEqual(
            transitives["srt/submodules/abi-compliance-checker"]["status"],
            "NOT_REQUIRED",
        )

    def test_c3_submodule_materiality_regression_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        submodule = next(
            item
            for item in manifest["transitives_discovered"]
            if item["component"] == "graphengine/test/googletest"
        )
        submodule["status"] = "PENDING"
        counts = manifest["parent_status"]["transitive_classification_counts"]
        counts["NOT_REQUIRED"] -= 1
        counts["PENDING"] = counts.get("PENDING", 0) + 1
        with self.assertRaisesRegex(SourceBundleError, "Submódulo C3"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c7_toolchain_parents_have_no_material_blocker(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        blocked = {
            item["component"]: item
            for item in manifest["parents"]
            if item["preservation_status"] == "BLOCKED"
        }
        self.assertEqual(blocked, {})
        self.assertEqual(manifest["runtime_toolchain_closure"]["status"], "RESOLVED")

    def test_c4_network_compression_and_text_islands_are_resolved(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        islands = manifest["closure_islands"]
        self.assertEqual(islands["network_tls"]["status"], "RESOLVED")
        self.assertEqual(islands["compression"]["status"], "RESOLVED")
        self.assertEqual(islands["text_rendering"]["status"], "RESOLVED")
        for island in ("network_tls", "compression", "text_rendering"):
            self.assertEqual(
                {item["status"] for item in islands[island]["members"]},
                {"PRESERVED"},
            )

    def test_c4_network_incomplete_status_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        manifest["closure_islands"]["network_tls"]["status"] = "PARTIAL"
        with self.assertRaisesRegex(SourceBundleError, "Status agregado"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c4_librist_and_libzmq_are_exact_and_resolved(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        parents = {item["component"]: item for item in manifest["parents"]}
        expected = {
            "librist": "4f45ef8f78983892d52ccd52d9f675435b23738f",
            "libzmq": "46493370217ac135246617fa2f6ac819d8b61bfc",
        }
        for component, revision in expected.items():
            parent = parents[component]
            self.assertEqual(parent["full_revision"], revision)
            self.assertEqual(parent["batch"], "C4")
            self.assertEqual(parent["component_result"], "RESOLVED")
            self.assertEqual(parent["preservation_status"], "PRESERVED")

    def test_c4_bad_git_tree_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        parent = next(
            item for item in manifest["parents"] if item["component"] == "librist"
        )
        parent["tree"] = "0" * 39
        with self.assertRaisesRegex(SourceBundleError, "Tree Git"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c4d_processing_and_codec_cargo_are_resolved(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        islands = manifest["closure_islands"]
        self.assertEqual(islands["processing"]["status"], "RESOLVED")
        self.assertEqual(
            {
                item["component"]
                for item in islands["processing"]["members"]
                if item["status"] == "PENDING"
            },
            set(),
        )
        self.assertEqual(islands["codec_audio_video"]["status"], "RESOLVED")
        pending_codec = {
            item["component"]
            for item in islands["codec_audio_video"]["members"]
            if item["status"] == "PENDING"
        }
        self.assertEqual(pending_codec, set())

    def test_c4b_ffplay_only_sdl_is_not_a_distributed_pair_gap(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        sdl = next(item for item in manifest["parents"] if item["component"] == "SDL")
        self.assertEqual(sdl["source_scope"], "BTBN_BUILD_PARENT")
        self.assertEqual(
            sdl["distributed_pair_status"], "NOT_REQUIRED_FOR_DISTRIBUTED_PAIR"
        )
        self.assertEqual(sdl["preservation_status"], "NOT_REQUIRED")
        self.assertIsNone(sdl["source"])
        self.assertIn("ffplay", sdl["distributed_pair_evidence"])

    def test_c4b_distributed_parent_cannot_be_excluded_without_evidence(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        parent = next(
            item for item in manifest["parents"] if item["component"] == "libjxl"
        )
        parent["preservation_status"] = "NOT_REQUIRED"
        parent["source"] = None
        parent["distributed_pair_status"] = "NOT_REQUIRED_FOR_DISTRIBUTED_PAIR"
        with self.assertRaisesRegex(SourceBundleError, "excluído.*sem evidência"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c4b_distributed_pair_scope_is_exact(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        scope = manifest["distributed_pair_scope"]
        self.assertEqual(scope["distributed_programs"], ["ffmpeg.exe", "ffprobe.exe"])
        self.assertEqual(scope["excluded_programs"], ["ffplay.exe"])
        self.assertEqual(
            scope["evidence"][0]["relative_path"],
            "metadata/c4b-distributed-pair-materiality.json",
        )

    def test_c4b_material_parents_are_evidenced_in_both_programs(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        parents = {item["component"]: item for item in manifest["parents"]}
        for component in (
            "libplacebo",
            "openal-soft",
            "game-music-emu",
            "libjxl",
            "LCEVCdec",
            "rav1e",
        ):
            parent = parents[component]
            self.assertEqual(
                parent["distributed_pair_status"], "MATERIAL_TO_DISTRIBUTED_PAIR"
            )
            self.assertEqual(
                parent["distributed_pair_materiality"], "BOTH_DISTRIBUTED_PROGRAMS"
            )
            self.assertTrue(parent["distributed_pair_evidence"])

    def test_c4b_libjxl_material_dependencies_are_deduplicated(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        transitives = {
            item["component"]: item for item in manifest["transitives_discovered"]
        }
        for component in (
            "libjxl/third_party/highway",
            "libjxl/third_party/brotli",
            "libjxl/third_party/lcms",
            "libjxl/third_party/zlib",
            "libjxl/third_party/libpng",
        ):
            self.assertEqual(transitives[component]["status"], "PRESERVED")
            self.assertIn("dependency_dedupe_key", transitives[component])

    def test_c4b_missing_material_parent_fails_closed(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        manifest["dependency_parents"] = [
            item
            for item in manifest["dependency_parents"]
            if item["component"] != "highway"
        ]
        with self.assertRaisesRegex(SourceBundleError, "dependency parents"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c4d_rav1e_cargo_inventory_classifies_entire_lock(self) -> None:
        inventory = json.loads(
            compliance_input(
                "build-compliance-ffmpeg-btbn/autobuild-2026-08-25-13-06/"
                "source-staging/metadata/rav1e-cargo-closure-c4d.json"
            ).read_text(encoding="utf-8")
        )
        packages = inventory["all_package_classification"]
        material = inventory["material_packages"]
        excluded = {
            item["classification"]
            for item in packages
            if item["classification"]
            in {
                "BUILD_ONLY",
                "DEV_ONLY",
                "OPTIONAL_DISABLED",
                "TARGET_NOT_APPLICABLE",
                "UNREACHABLE",
            }
        }
        self.assertEqual(len(packages), 272)
        self.assertEqual(len(material), 48)
        self.assertEqual(
            len(
                [
                    item
                    for item in material
                    if item["preservation_status"] == "PRESERVED"
                ]
            ),
            48,
        )
        self.assertEqual(
            len(
                [item for item in material if item["preservation_status"] == "PENDING"]
            ),
            0,
        )
        self.assertEqual(inventory["unknown_packages"], [])
        self.assertEqual(
            excluded,
            {
                "BUILD_ONLY",
                "DEV_ONLY",
                "OPTIONAL_DISABLED",
                "TARGET_NOT_APPLICABLE",
                "UNREACHABLE",
            },
        )
        self.assertTrue(
            all(
                item["status"] == "NOT_REQUIRED"
                for item in packages
                if item["classification"] in excluded
            )
        )
        self.assertEqual(
            inventory["cargo_update_cc"]["status"], "REPRODUCIBILITY_PENDING"
        )
        self.assertEqual(
            inventory["rust_runtime_materiality"]["status"], "NEEDS_REVIEW"
        )

    def test_c4d_contains_exactly_the_eight_authorized_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, document, _, _ = self._cargo_closure_fixture(Path(directory))
            packages = document["c4d"]["packages"]
            self.assertEqual(
                {(item["name"], item["version"]) for item in packages},
                C4D_PACKAGES,
            )
            material = {item["name"]: item for item in document["material_packages"]}
            self.assertEqual(
                {
                    (item["name"], item["version"])
                    for item in document["material_packages"]
                    if item["preservation_batch"] == "C4d"
                },
                C4D_PACKAGES,
            )
            self.assertTrue(
                all(
                    material[name]["preservation_status"] == "PRESERVED"
                    for name, _ in C4D_PACKAGES
                )
            )

    def test_c4d_runtime_and_codegen_roles_are_exact(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        c4d = {
            item["cargo_package"]: item
            for item in manifest["dependency_parents"]
            if item.get("batch") == "C4d"
        }
        self.assertEqual(
            {
                name
                for name, item in c4d.items()
                if item["cargo_dependency_type"] == "RUNTIME_MATERIAL"
            },
            {"av1-grain", "minimal-lexical", "nom", "profiling"},
        )
        self.assertEqual(
            {
                name
                for name, item in c4d.items()
                if item["cargo_dependency_type"] == "CODEGEN_MATERIAL"
            },
            {"built", "num-derive", "profiling-procmacros", "simd_helpers"},
        )
        self.assertTrue(
            all(
                item["cargo_codegen_role"]
                for item in c4d.values()
                if item["cargo_dependency_type"] == "CODEGEN_MATERIAL"
            )
        )

    def test_c4d_missing_authorized_crate_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        manifest["dependency_parents"] = [
            item
            for item in manifest["dependency_parents"]
            if item.get("cargo_package") != "av1-grain"
        ]
        with self.assertRaisesRegex(SourceBundleError, "dependency parents"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c4d_material_crate_cannot_be_marked_build_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging, _ = self._cargo_closure_fixture(Path(directory))
            parent = next(
                item
                for item in manifest["dependency_parents"]
                if item.get("cargo_package") == "built"
            )
            parent["cargo_dependency_type"] = "BUILD_ONLY"
            with self.assertRaisesRegex(SourceBundleError, "Parent Cargo"):
                _verify_cargo_closure(manifest, staging)

    def test_c4d_normal_library_is_resolved_with_zero_pending(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        self.assertEqual(
            manifest["remaining_pending_classification"]["NORMAL_LIBRARY_PENDING"], []
        )
        self.assertEqual(manifest["normal_library_closure"]["status"], "RESOLVED")
        self.assertEqual(
            manifest["normal_library_closure"]["pending_material_source_count"], 0
        )
        self.assertEqual(manifest["rav1e_cargo_closure"]["status"], "RESOLVED")

    def test_c4d_pending_normal_library_regression_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        manifest["remaining_pending_classification"]["NORMAL_LIBRARY_PENDING"] = [
            "unexpected"
        ]
        with self.assertRaisesRegex(SourceBundleError, "Closure normal"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c4d_missing_upstream_license_files_are_explicit(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        cargo = {
            item["cargo_package"]: item
            for item in manifest["dependency_parents"]
            if item.get("source_type") == "Cargo Registry"
        }
        for name in ("profiling", "profiling-procmacros", "simd_helpers"):
            source = cargo[name]["source"]
            self.assertEqual(source["license_files"], [])
            self.assertTrue(source["license_files_absent_from_published_crate"])
            self.assertTrue(source["license_files_note"])
            self.assertTrue(source["license_declared_upstream"])

    def test_c4d_undocumented_license_file_absence_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        parent = next(
            item
            for item in manifest["dependency_parents"]
            if item.get("cargo_package") == "profiling"
        )
        parent["source"]["license_files_note"] = None
        with self.assertRaisesRegex(SourceBundleError, "Ausência.*licença"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c4c_registry_checksums_and_material_roles_are_explicit(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        cargo = [
            item
            for item in manifest["dependency_parents"]
            if item["source_type"] == "Cargo Registry"
        ]
        self.assertTrue(
            all(
                item["cargo_dependency_type"]
                in {"RUNTIME_MATERIAL", "CODEGEN_MATERIAL"}
                and item["cargo_target_applicability"] == "x86_64-pc-windows-gnu"
                for item in cargo
            )
        )
        preserved = [
            item for item in cargo if item["preservation_status"] == "PRESERVED"
        ]
        self.assertTrue(
            all(
                item["source"]["sha256"].lower() == item["cargo_lock_checksum"]
                and item["source"]["authority"]
                == "cargo_lock_and_crates_io_index_checksum"
                for item in preserved
            )
        )

    def test_c4c_closure_evidence_matches_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging, _ = self._cargo_closure_fixture(Path(directory))
            _verify_cargo_closure(manifest, staging)

    def test_c4c_build_dev_optional_target_and_codegen_roles_are_explicit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, document, _, _ = self._cargo_closure_fixture(Path(directory))
            packages = document["all_package_classification"]
            for classification in (
                "BUILD_ONLY",
                "DEV_ONLY",
                "OPTIONAL_DISABLED",
                "TARGET_NOT_APPLICABLE",
            ):
                matching = [
                    item
                    for item in packages
                    if item["classification"] == classification
                ]
                self.assertTrue(matching)
                self.assertTrue(
                    all(item["status"] == "NOT_REQUIRED" for item in matching)
                )
            codegen = [
                item
                for item in document["material_packages"]
                if item["classification"] == "CODEGEN_MATERIAL"
            ]
            self.assertEqual(len(codegen), 13)
            self.assertTrue(
                {
                    "arg_enum_proc_macro",
                    "equator-macro",
                    "noop_proc_macro",
                    "thiserror-impl",
                }.issubset({item["name"] for item in codegen})
            )

    def test_c4c_material_transitive_dependency_is_in_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, document, _, _ = self._cargo_closure_fixture(Path(directory))
            material = {item["name"]: item for item in document["material_packages"]}
            dependency_names = {
                dependency["package"]
                for dependency in material["aligned"]["dependencies"]
            }
            self.assertIn("as-slice", dependency_names)
            self.assertIn("as-slice", material)

    def test_c4c_duplicate_crate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, document, staging, evidence = self._cargo_closure_fixture(
                Path(directory)
            )
            document["all_package_classification"][1] = deepcopy(
                document["all_package_classification"][0]
            )
            evidence.write_bytes(formatted_json_bytes(document))
            with self.assertRaisesRegex(SourceBundleError, "duplicado"):
                _verify_cargo_closure(manifest, staging)

    def test_c4c_wrong_registry_checksum_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, document, staging, evidence = self._cargo_closure_fixture(
                Path(directory)
            )
            document["material_packages"][0]["cargo_lock_checksum"] = "0" * 64
            evidence.write_bytes(formatted_json_bytes(document))
            with self.assertRaisesRegex(SourceBundleError, "Cargo.lock"):
                _verify_cargo_closure(manifest, staging)

    def test_c4c_wrong_material_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, document, staging, evidence = self._cargo_closure_fixture(
                Path(directory)
            )
            document["material_packages"][0]["version"] = "0.0.0"
            evidence.write_bytes(formatted_json_bytes(document))
            with self.assertRaisesRegex(SourceBundleError, "Cargo.lock"):
                _verify_cargo_closure(manifest, staging)

    def test_c4c_material_dependency_graph_inconsistency_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, document, staging, evidence = self._cargo_closure_fixture(
                Path(directory)
            )
            package = next(
                item for item in document["material_packages"] if item["dependencies"]
            )
            package["dependencies"][0]["version"] = "0.0.0"
            evidence.write_bytes(formatted_json_bytes(document))
            with self.assertRaisesRegex(SourceBundleError, "Dependency material"):
                _verify_cargo_closure(manifest, staging)

    def test_c4c_missing_material_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, document, staging, evidence = self._cargo_closure_fixture(
                Path(directory)
            )
            preserved = next(
                item
                for item in document["material_packages"]
                if item["preservation_status"] == "PRESERVED"
            )
            preserved["source"] = None
            evidence.write_bytes(formatted_json_bytes(document))
            with self.assertRaisesRegex(SourceBundleError, "Source material"):
                _verify_cargo_closure(manifest, staging)

    def test_c4c_unknown_classification_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, document, staging, evidence = self._cargo_closure_fixture(
                Path(directory)
            )
            document["all_package_classification"][0]["classification"] = "UNKNOWN"
            evidence.write_bytes(formatted_json_bytes(document))
            with self.assertRaisesRegex(SourceBundleError, "UNKNOWN"):
                _verify_cargo_closure(manifest, staging)

    def test_c4c_git_vs_registry_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, document, staging, evidence = self._cargo_closure_fixture(
                Path(directory)
            )
            document["material_packages"][0]["registry_source"] = (
                "git+https://example.invalid/not-the-registry"
            )
            evidence.write_bytes(formatted_json_bytes(document))
            with self.assertRaisesRegex(SourceBundleError, "Registry"):
                _verify_cargo_closure(manifest, staging)

    def test_c4c_disabled_package_in_source_parent_graph_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, document, staging, evidence = self._cargo_closure_fixture(
                Path(directory)
            )
            disabled = next(
                item
                for item in document["all_package_classification"]
                if item["classification"] == "OPTIONAL_DISABLED"
                and item["source"] is not None
            )
            material = document["material_packages"][0]
            parent = next(
                item
                for item in manifest["dependency_parents"]
                if item.get("source_type") == "Cargo Registry"
                and item["cargo_package"] == material["name"]
            )
            for item in (material, parent):
                key_name = "name" if item is material else "cargo_package"
                key_version = "version" if item is material else "cargo_version"
                item[key_name] = disabled["name"]
                item[key_version] = disabled["version"]
            material["cargo_lock_checksum"] = disabled["checksum"]
            parent["cargo_lock_checksum"] = disabled["checksum"]
            material["source"]["sha256"] = disabled["checksum"].upper()
            parent["source"]["sha256"] = disabled["checksum"].upper()
            evidence.write_bytes(formatted_json_bytes(document))
            with self.assertRaisesRegex(
                SourceBundleError, "Cargo.lock classificado|não material"
            ):
                _verify_cargo_closure(manifest, staging)

    def test_new_material_dependency_discovery_fails_closed(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        dependency = next(
            item
            for item in manifest["transitives_discovered"]
            if item["component"] == "mldsa-native"
        )
        dependency["status"] = "PENDING"
        counts = manifest["parent_status"]["transitive_classification_counts"]
        counts["PRESERVED"] -= 1
        counts["PENDING"] = counts.get("PENDING", 0) + 1
        with self.assertRaisesRegex(SourceBundleError, "Nova dependency material"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_gpl_components_excluded_from_lgpl_variant_remain_not_required(
        self,
    ) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        parent_names = {item["component"].lower() for item in manifest["parents"]}
        excluded = {
            item["component"]: item
            for item in manifest["excluded_non_material_components"]
        }
        self.assertEqual(excluded["x264"]["status"], "NOT_REQUIRED")
        self.assertEqual(excluded["x264"]["class"], "E")
        self.assertTrue(
            {
                "avisynth",
                "davs2",
                "dvdread",
                "dvdnav",
                "frei0r",
                "rubberband",
                "vidstab",
                "x264",
                "x265",
                "xavs2",
                "xvid",
            }.isdisjoint(parent_names)
        )

    def test_c7_hardware_and_runtime_are_resolved_separately(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        remaining = manifest["remaining_pending_classification"]
        self.assertEqual(remaining["HARDWARE_HEADER_PENDING"], [])
        self.assertEqual(
            manifest["closure_islands"]["hardware_headers"]["status"], "RESOLVED"
        )
        self.assertEqual(remaining["RUNTIME_TOOLCHAIN_BLOCKED"], [])
        self.assertEqual(remaining["RUNTIME_TOOLCHAIN_PENDING"], [])
        self.assertEqual(remaining["RUNTIME_TOOLCHAIN_UNKNOWN_COUNT"], 0)
        self.assertEqual(
            manifest["closure_islands"]["runtime_toolchain"]["status"],
            "RESOLVED",
        )

    def test_c7_gcc_parent_covers_all_material_runtimes(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        transitives = {
            item["component"]: item for item in manifest["transitives_discovered"]
        }
        for component in (
            "GCC/libgcc",
            "GCC/libgcc_eh",
            "GCC/libstdc++-v3",
            "GCC/libgomp",
        ):
            self.assertEqual(transitives[component]["status"], "PRESERVED_WITH_PARENT")
            self.assertEqual(
                transitives[component]["materiality"], "MATERIAL_COVERED_BY_PARENT"
            )

    def test_c7_gcc_checksum_regression_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        gcc = next(
            item for item in manifest["parents"] if item["component"] == "GCC 15.2.0"
        )
        gcc["source"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(SourceBundleError, "GCC 15.2.0"):
            self._validate_c7(manifest)

    def test_c7_patchsets_are_target_classified_and_complete(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        patches = [
            item
            for item in manifest["patches"]
            if item.get("producer") == "crosstool-NG"
        ]
        gcc = [item for item in patches if item["source_parent"] == "GCC 15.2.0"]
        mingw = [
            item for item in patches if item["source_parent"] == "mingw-w64 v13.0.0"
        ]
        self.assertEqual((len(gcc), len(mingw)), (19, 7))
        self.assertEqual(
            sum(item["application_status"] == "APPLIES_CLEANLY" for item in gcc),
            8,
        )
        self.assertEqual(
            sum(item["application_status"] == "APPLIES_CLEANLY" for item in mingw),
            2,
        )
        self.assertTrue(
            all(
                item["application_status"] in {"APPLIES_CLEANLY", "NOT_APPLICABLE"}
                for item in patches
            )
        )

    def test_c7_material_patch_cannot_be_blocked(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        patch = next(
            item
            for item in manifest["patches"]
            if item.get("target_applicability") == "MATERIAL_FOR_WIN64_X86_64"
        )
        patch["application_status"] = "BLOCKED"
        with self.assertRaisesRegex(SourceBundleError, "Patch material C7"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c7_dual_mingw_revisions_and_runtime_coverage_are_preserved(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        parents = {item["component"]: item for item in manifest["parents"]}
        self.assertEqual(
            parents["mingw-w64 v13.0.0"]["revision_role"],
            "MINGW_BASE_TOOLCHAIN_SOURCE",
        )
        self.assertEqual(
            parents["mingw-w64"]["revision_role"], "MINGW_FINAL_OVERLAY_SOURCE"
        )
        self.assertNotEqual(
            parents["mingw-w64 v13.0.0"]["full_revision"],
            parents["mingw-w64"]["full_revision"],
        )
        coverage = set(manifest["runtime_toolchain_closure"]["coverage"])
        self.assertTrue(
            {
                "mingw-w64 final/CRT",
                "mingw-w64 final/startup",
                "mingw-w64 final/winpthreads",
            }.issubset(coverage)
        )

    def test_c7_mingw_std_threads_remains_not_required(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        parent = next(
            item
            for item in manifest["parents"]
            if item["component"] == "mingw-std-threads"
        )
        self.assertEqual(parent["preservation_status"], "NOT_REQUIRED")
        self.assertEqual(parent["materiality"], "BUILD_REPRODUCIBILITY_INPUT")
        parent["preservation_status"] = "BLOCKED"
        with self.assertRaisesRegex(SourceBundleError, "mingw-std-threads"):
            self._validate_c7(manifest)

    def test_c7_rust_parent_covers_runtime_builtins_and_backtrace(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        coverage = set(manifest["runtime_toolchain_closure"]["coverage"])
        self.assertTrue(
            {
                "rust-src/core",
                "rust-src/alloc",
                "rust-src/std",
                "rust-src/panic_abort",
                "rust-src/panic_unwind",
                "rust-src/compiler_builtins",
                "rust-src/backtrace",
                "rust-src/windows-gnu-pal",
            }.issubset(coverage)
        )

    def test_c7_missing_backtrace_coverage_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        item = next(
            item
            for item in manifest["transitives_discovered"]
            if item["component"] == "rust-src/backtrace"
        )
        item["status"] = "PENDING"
        with self.assertRaisesRegex(SourceBundleError, "Cobertura runtime C7"):
            self._validate_c7(manifest)

    def test_c7_build_only_and_system_runtime_boundaries_remain_separate(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        closure = manifest["runtime_toolchain_closure"]
        self.assertEqual(closure["build_reproducibility"]["status"], "PARTIAL")
        self.assertIn("binutils 2.46.0", closure["build_reproducibility"]["build_only"])
        self.assertIn("rustc", closure["build_reproducibility"]["build_only"])
        self.assertIn("Cargo", closure["build_reproducibility"]["build_only"])
        self.assertIn(
            "cc crate post-update", closure["build_reproducibility"]["build_only"]
        )
        self.assertEqual(
            set(closure["system_runtime"]),
            {"UCRT/API sets", "Windows system DLLs"},
        )

    def test_c5_hardware_pending_classification_mismatch_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        manifest["remaining_pending_classification"]["HARDWARE_HEADER_PENDING"] = [
            "https://example.invalid/not-authorized|" + "0" * 40
        ]
        with self.assertRaisesRegex(SourceBundleError, "Hardware/Headers"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c5_header_only_material_without_source_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        amf = next(item for item in manifest["parents"] if item["component"] == "AMF")
        amf["source"] = None
        with self.assertRaisesRegex(SourceBundleError, "preservado sem source"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_c5_external_driver_cannot_be_promoted_to_distributed_material(
        self,
    ) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        manifest["hardware_header_closure"]["external_interfaces"][0]["distributed"] = (
            True
        )
        with self.assertRaisesRegex(SourceBundleError, "Runtime/driver externo"):
            self._validate_c5(manifest)

    def test_c5_target_not_applicable_cannot_be_required(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        amf = next(item for item in manifest["parents"] if item["component"] == "AMF")
        amf["target_applicability"] = "TARGET_NOT_APPLICABLE"
        with self.assertRaisesRegex(SourceBundleError, "Materialidade/source C5"):
            self._validate_c5(manifest)

    def test_c5_nv_revisions_distinguish_effective_and_superseded_inputs(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        records = {
            item["full_revision"]: item
            for item in manifest["parents"]
            if item["component"] == "nv-codec-headers"
        }
        self.assertEqual(
            {
                revision
                for revision, item in records.items()
                if item["preservation_status"] == "NOT_REQUIRED"
            },
            {
                "833faee5f7b8d3f56444347c587f4aed11ee213f",
                "ced4f8eba3ba5dd431932cba17928f0dffdaeb2b",
            },
        )
        self.assertEqual(
            records["eddcea9e27f6b772057c9b3f87de2cc1737faffc"]["preservation_status"],
            "PRESERVED",
        )

    def test_c5_superseded_nv_revision_cannot_be_promoted(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        old = next(
            item
            for item in manifest["parents"]
            if item.get("full_revision") == "833faee5f7b8d3f56444347c587f4aed11ee213f"
        )
        old["revision_role"] = "MATERIAL_FINAL"
        with self.assertRaisesRegex(SourceBundleError, "superseded"):
            self._validate_c5(manifest)

    def test_c5_vulkan_header_revisions_must_not_be_falsely_deduplicated(
        self,
    ) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        standalone = next(
            item
            for item in manifest["parents"]
            if item["component"] == "Vulkan-Headers"
        )
        submodule = next(
            item
            for item in manifest["dependency_parents"]
            if item["component"] == "Vulkan-Headers (libplacebo submodule)"
        )
        submodule["tree"] = standalone["tree"]
        with self.assertRaisesRegex(SourceBundleError, "deduplicados"):
            self._validate_c5(manifest)

    def test_c5_shaderc_material_and_test_only_dependencies_are_exact(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        transitives = {
            item["component"]: item for item in manifest["transitives_discovered"]
        }
        for component in (
            "shaderc/glslang",
            "shaderc/SPIRV-Tools",
            "shaderc/SPIRV-Headers",
        ):
            self.assertEqual(transitives[component]["status"], "PRESERVED")
            self.assertEqual(transitives[component]["materiality"], "MATERIAL_SOURCE")
        for component in (
            "shaderc/abseil_cpp",
            "shaderc/effcee",
            "shaderc/googletest",
            "shaderc/re2",
        ):
            self.assertEqual(transitives[component]["status"], "NOT_REQUIRED")
            self.assertEqual(transitives[component]["materiality"], "TEST_ONLY")

    def test_c5_shaderc_test_only_dependency_cannot_be_promoted(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        dependency = next(
            item
            for item in manifest["transitives_discovered"]
            if item["component"] == "shaderc/googletest"
        )
        dependency["status"] = "PRESERVED"
        dependency["materiality"] = "MATERIAL_SOURCE"
        with self.assertRaisesRegex(SourceBundleError, "test-only"):
            self._validate_c5(manifest)

    def test_c5_libva_windows_target_and_libvpl_runtime_boundary_are_explicit(
        self,
    ) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        parents = {item["component"]: item for item in manifest["parents"]}
        self.assertIn("WIN64_LGPL_8_1_STATIC", parents["libva"]["target_applicability"])
        self.assertTrue(parents["libva"]["static_code"])
        self.assertIn("libmfx64-gen.dll", parents["libvpl"]["external_runtime"])
        self.assertTrue(parents["libvpl"]["static_code"])

    def test_c5_libvpl_external_runtime_cannot_be_folded_into_source(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        libvpl = next(
            item for item in manifest["parents"] if item["component"] == "libvpl"
        )
        libvpl["external_runtime"] = []
        with self.assertRaisesRegex(SourceBundleError, "oneVPL"):
            self._validate_c5(manifest)

    def test_c5_material_tree_drift_is_rejected_by_staging_evidence(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        amf = next(item for item in manifest["parents"] if item["component"] == "AMF")
        amf["tree"] = "0" * 40
        with self.assertRaisesRegex(SourceBundleError, "Source/evidência C5"):
            verify_staging(
                manifest,
                compliance_input(
                    "build-compliance-ffmpeg-btbn/autobuild-2026-08-25-13-06/"
                    "source-staging"
                ),
            )

    def test_island_member_status_drift_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        manifest["closure_islands"]["text_rendering"]["members"][0]["status"] = (
            "PENDING"
        )
        with self.assertRaisesRegex(SourceBundleError, "Status de ilha"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_island_missing_parent_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        manifest["closure_islands"]["network_tls"]["members"].pop()
        with self.assertRaisesRegex(
            SourceBundleError, "Contagens da ilha|não cobre todos"
        ):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_duplicate_dependency_revision_is_rejected(self) -> None:
        manifest = deepcopy(load_manifest(DEFAULT_MANIFEST))
        manifest["dependency_parents"][1]["dedupe_key"] = manifest[
            "dependency_parents"
        ][0]["dedupe_key"]
        with self.assertRaisesRegex(SourceBundleError, "duplicado"):
            _validate_manifest(manifest, enforce_official_baseline=True)

    def test_aom_patch_applies_to_exact_synthetic_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging = self._patch_fixture(
                Path(directory),
                component="aom",
                transitions=[(b"old\n", b"new\n")],
            )
            inventory = verify_staging(manifest, staging)
            self.assertTrue(
                any("aom-patch-replay" in item["relative_path"] for item in inventory)
            )

    def test_aom_patch_preimage_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging = self._patch_fixture(
                Path(directory),
                component="aom",
                transitions=[(b"old\n", b"new\n")],
                mismatch_index=1,
            )
            with self.assertRaisesRegex(SourceBundleError, "Replay Git falhou"):
                verify_staging(manifest, staging)

    def test_aribb24_patch_order_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging = self._patch_fixture(
                Path(directory),
                component="aribb24",
                transitions=[(b"old\n", b"middle\n"), (b"middle\n", b"new\n")],
            )
            verify_staging(manifest, staging)
            manifest["patches"][0]["application_order"] = 2
            manifest["patches"][1]["application_order"] = 1
            with self.assertRaisesRegex(SourceBundleError, "Evidência por patch"):
                verify_staging(manifest, staging)

    def test_aribb24_patch_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging = self._patch_fixture(
                Path(directory),
                component="aribb24",
                transitions=[(b"old\n", b"middle\n"), (b"middle\n", b"new\n")],
                mismatch_index=2,
            )
            with self.assertRaisesRegex(SourceBundleError, "Replay Git falhou"):
                verify_staging(manifest, staging)

    def test_valid_staging_and_pending_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging = self._fixture(Path(directory))
            inventory = verify_staging(manifest, staging)
            self.assertEqual(len(inventory), 7)
            self.assertFalse(
                any("pending" in item["relative_path"] for item in inventory)
            )

    def test_wrong_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging = self._fixture(Path(directory))
            manifest["parents"][0]["source"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(SourceBundleError, "SHA-256 divergente"):
                verify_staging(manifest, staging)

    def test_missing_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging = self._fixture(Path(directory))
            (staging / "sources/component.tar.gz").unlink()
            with self.assertRaisesRegex(SourceBundleError, "ausente"):
                verify_staging(manifest, staging)

    def test_archive_blob_divergence_is_rejected_after_archive_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging = self._fixture(Path(directory))
            source_path = staging / "sources/component.tar.gz"
            self._write_tar(
                source_path,
                {
                    "fixture-component/LICENSE": b"BSD fixture\n",
                    "fixture-component/configure": b"changed\n",
                },
            )
            source = manifest["parents"][0]["source"]
            source["size"] = source_path.stat().st_size
            source["sha256"] = sha256_bytes(source_path.read_bytes())
            with self.assertRaisesRegex(SourceBundleError, "Blob Git divergente"):
                verify_staging(manifest, staging)

    def test_patch_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging = self._fixture(Path(directory))
            manifest["patches"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(SourceBundleError, "Patch diverge"):
                verify_staging(manifest, staging)

    def test_duplicate_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, path, _ = self._fixture(Path(directory))
            duplicate = deepcopy(manifest["parents"][1])
            manifest["parents"].append(duplicate)
            manifest["parent_status"]["counts_for_baseline_81"]["PENDING"] = 2
            self._write_manifest(path, manifest)
            with self.assertRaisesRegex(SourceBundleError, "duplicado"):
                load_manifest(path, enforce_official_baseline=False)

    def test_proprietary_source_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _, staging = self._fixture(Path(directory))
            (staging / "sources/activation_issuer.py").write_text("private")
            with self.assertRaisesRegex(SourceBundleError, "source proprietário"):
                verify_staging(manifest, staging)

    def test_non_partial_bundle_classification_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, path, _ = self._fixture(Path(directory))
            manifest["bundle"]["classification"] = "COMPLETE"
            self._write_manifest(path, manifest)
            with self.assertRaisesRegex(SourceBundleError, "Classificação"):
                load_manifest(path, enforce_official_baseline=False)

    def test_bundle_is_partial_verifiable_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest_path, staging = self._fixture(root)
            first = root / "first.zip"
            second = root / "second.zip"
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
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                first_result["classification"], PARTIAL_BUNDLE_CLASSIFICATION
            )
            self.assertEqual(first_result, second_result)
            self.assertEqual(
                verify_bundle(
                    manifest_path,
                    first,
                    enforce_official_baseline=False,
                ),
                first_result,
            )

    def test_complete_candidate_bundle_is_verifiable_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, manifest_path, staging = self._fixture(root)
            manifest["parents"] = [manifest["parents"][0]]
            manifest["parent_status"]["counts_for_baseline_81"] = {
                "BLOCKED": 0,
                "BUILD_ONLY": 0,
                "CONDITIONAL": 0,
                "NOT_REQUIRED": 0,
                "PENDING": 0,
                "PRESERVED": 1,
            }
            manifest["source_correspondence"] = (
                "A_TECHNICALLY_COMPLETE_FOR_LEGAL_REVIEW"
            )
            manifest["bundle"].update(
                {
                    "bundle_filename": "fixture-COMPLETE-CANDIDATE.zip",
                    "classification": OFFICIAL_BUNDLE_CLASSIFICATION,
                    "root": "fixture-source-complete-candidate",
                }
            )
            self._write_manifest(manifest_path, manifest)
            first = root / "first-complete.zip"
            second = root / "second-complete.zip"
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
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                first_result["classification"], OFFICIAL_BUNDLE_CLASSIFICATION
            )
            self.assertEqual(first_result, second_result)
            self.assertEqual(
                verify_bundle(
                    manifest_path,
                    first,
                    enforce_official_baseline=False,
                ),
                first_result,
            )


if __name__ == "__main__":
    unittest.main()
