"""Tests for the offline frozen-candidate composition contract."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from constants import APP_VERSION
from tests.git_fixture import commit, git, new_repository
from validate_frozen_candidate import (
    ALLOWED_PACKED_YTDLP_SMOKE_RESULTS,
    CANDIDATE_CLASSIFICATION,
    CONTROLLED_CANDIDATE_CLASSIFICATION,
    EXTERNAL_BINARY_BASELINE,
    V1_4_RC2_EXTERNAL_BINARY_BASELINE,
    NOTICE_COMPLETE_CANDIDATE_CLASSIFICATION,
    RELEASE_CANDIDATE_CLASSIFICATION,
    RELEASE_CANDIDATE_RC2_CLASSIFICATION,
    RELEASE_CANDIDATE_RC3_CLASSIFICATION,
    V1_2_RELEASE_CANDIDATE_CLASSIFICATION,
    V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
    V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
    V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
    V1_5_RELEASE_CANDIDATE_CLASSIFICATION,
    V1_6_PORTABILITY_PROBE_CLASSIFICATION,
    V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
    V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
    V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
    V1_3_PILLOW_IMAGINGFT_PATH,
    V1_3_PILLOW_IMAGINGFT_SHA256,
    V1_3_PILLOW_IMAGINGFT_SIZE,
    V1_0_RELEASE_CANDIDATE_CLASSIFICATION,
    _compliance_gap_report,
    _pillow_imagingft_issue,
    audit_notice_delivery,
    build_file_inventory,
    candidate_contract_environment,
    candidate_pipeline_contract,
    canonical_json_bytes,
    classify_package_materiality,
    compare_candidate_composition,
    compare_inventories,
    find_contamination_issues,
    find_v1_4_archive_issues,
    find_v1_5_archive_issues,
    inspect_external_binaries,
    prepare_candidate_root,
    validate_candidate_cleanup_target,
    validate_candidate_manifest,
    validate_inventory_against_manifest,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
TRACKED_FROZEN_MANIFEST_NAMES = (
    "FROZEN_CANDIDATE_1_0_RC1_COMPOSITION.json",
    "FROZEN_CANDIDATE_1_1_RC1_COMPOSITION.json",
    "FROZEN_CANDIDATE_1_5_RC1_COMPOSITION.json",
    "FROZEN_CANDIDATE_1_6_RC1_COMPOSITION.json",
    "FROZEN_CANDIDATE_COMPOSITION.json",
    "FROZEN_CANDIDATE_R2_COMPOSITION.json",
    "FROZEN_CANDIDATE_R3_COMPOSITION.json",
)
LOCAL_FROZEN_MANIFEST_NAMES = (
    "FROZEN_CANDIDATE_1_1_RC2_COMPOSITION.json",
    "FROZEN_CANDIDATE_1_1_RC3_COMPOSITION.json",
    "FROZEN_CANDIDATE_1_2_RC1_COMPOSITION.json",
    "FROZEN_CANDIDATE_1_3_RC1_COMPOSITION.json",
    "FROZEN_CANDIDATE_1_4_RC1_COMPOSITION.json",
    "FROZEN_CANDIDATE_1_4_RC2_COMPOSITION.json",
    "FROZEN_CANDIDATE_1_6_RC2_COMPOSITION.json",
    "FROZEN_CANDIDATE_1_7_RC1_COMPOSITION.json",
)
KNOWN_FROZEN_MANIFEST_NAMES = tuple(
    sorted((*TRACKED_FROZEN_MANIFEST_NAMES, *LOCAL_FROZEN_MANIFEST_NAMES))
)


def _frozen_manifest_set_issues(names: list[str]) -> list[str]:
    observed = set(names)
    required = set(TRACKED_FROZEN_MANIFEST_NAMES)
    known = set(KNOWN_FROZEN_MANIFEST_NAMES)
    return sorted(
        [f"missing:{name}" for name in required - observed]
        + [f"unexpected:{name}" for name in observed - known]
    )


class FrozenCandidateTests(unittest.TestCase):
    def test_microsoft_direct_runtime_gap_depends_on_physical_distribution(
        self,
    ) -> None:
        components = {"cffi": [], "cryptography": []}
        external = _compliance_gap_report(
            [], components, microsoft_runtime_distributed=False
        )
        historical = _compliance_gap_report(
            [], components, microsoft_runtime_distributed=True
        )
        self.assertNotIn(
            "Microsoft runtime DLLs physically redistributed",
            external["NEEDS_SOURCE_AUDIT"],
        )
        self.assertNotIn(
            "Microsoft runtime redistribution terms", external["NEEDS_NOTICE_REVIEW"]
        )
        self.assertIn(
            "Microsoft runtime DLLs physically redistributed",
            historical["NEEDS_SOURCE_AUDIT"],
        )
        self.assertIn(
            "Microsoft runtime redistribution terms", historical["NEEDS_NOTICE_REVIEW"]
        )

    @staticmethod
    def _run_git(
        arguments: list[str], *, cwd: Path, input_bytes: bytes | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
        )

    def test_frozen_manifest_attributes_cover_exact_canonical_set(self):
        paths = [
            f"docs/compliance/build/{name}" for name in KNOWN_FROZEN_MANIFEST_NAMES
        ]
        neighbor = "docs/compliance/build/FROZEN_CANDIDATE_COMPOSITION.md"
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            new_repository(source)
            shutil.copyfile(PROJECT_DIR / ".gitattributes", source / ".gitattributes")
            attributes = git(
                source, "check-attr", "text", "--", *paths, neighbor
            ).decode()
        for path in paths:
            self.assertIn(f"{path}: text: unset", attributes)
        self.assertIn(f"{neighbor}: text: unspecified", attributes)

    def test_frozen_manifest_authority_rejects_unknown_and_missing(self) -> None:
        tracked = list(TRACKED_FROZEN_MANIFEST_NAMES)
        self.assertEqual(_frozen_manifest_set_issues(tracked), [])
        self.assertEqual(
            _frozen_manifest_set_issues(
                [*tracked, "FROZEN_CANDIDATE_1_1_RC2_COMPOSITION.json"]
            ),
            [],
        )
        self.assertEqual(
            _frozen_manifest_set_issues(
                [*tracked, "FROZEN_CANDIDATE_1_1_RC3_COMPOSITION.json"]
            ),
            [],
        )
        self.assertEqual(
            _frozen_manifest_set_issues(
                [*tracked, "FROZEN_CANDIDATE_1_2_RC1_COMPOSITION.json"]
            ),
            [],
        )
        self.assertEqual(
            _frozen_manifest_set_issues(
                [*tracked, "FROZEN_CANDIDATE_1_3_RC1_COMPOSITION.json"]
            ),
            [],
        )
        self.assertEqual(
            _frozen_manifest_set_issues(
                [*tracked, "FROZEN_CANDIDATE_1_4_RC1_COMPOSITION.json"]
            ),
            [],
        )
        self.assertEqual(
            _frozen_manifest_set_issues(
                [
                    *tracked,
                    "FROZEN_CANDIDATE_1_1_RC2_COMPOSITION.json",
                    "FROZEN_CANDIDATE_1_1_RC3_COMPOSITION.json",
                    "FROZEN_CANDIDATE_1_2_RC1_COMPOSITION.json",
                    "FROZEN_CANDIDATE_1_3_RC1_COMPOSITION.json",
                    "FROZEN_CANDIDATE_1_4_RC1_COMPOSITION.json",
                ]
            ),
            [],
        )
        self.assertEqual(
            _frozen_manifest_set_issues(
                [*tracked, "FROZEN_CANDIDATE_FALSE_COMPOSITION.json"]
            ),
            ["unexpected:FROZEN_CANDIDATE_FALSE_COMPOSITION.json"],
        )
        self.assertEqual(
            _frozen_manifest_set_issues(tracked[1:]),
            ["missing:FROZEN_CANDIDATE_1_0_RC1_COMPOSITION.json"],
        )

    def test_frozen_manifest_authority_excludes_adjacent_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / "FROZEN_CANDIDATE_1_1_RC2_COMPOSITION.json").touch()
            (root / "FROZEN_CANDIDATE_1_1_RC3_COMPOSITION.json").touch()
            (root / "FROZEN_CANDIDATE_1_2_RC1_COMPOSITION.json").touch()
            (root / "FROZEN_CANDIDATE_1_3_RC1_COMPOSITION.json").touch()
            (root / "FROZEN_CANDIDATE_1_4_RC1_COMPOSITION.json").touch()
            (root / "FROZEN_CANDIDATE_1_1_RC2_COMPOSITION.md").touch()
            (root / "RC2_ADJACENT.json").touch()

            selected = sorted(
                path.name for path in root.glob("FROZEN_CANDIDATE*_COMPOSITION.json")
            )

        self.assertEqual(
            selected,
            [
                "FROZEN_CANDIDATE_1_1_RC2_COMPOSITION.json",
                "FROZEN_CANDIDATE_1_1_RC3_COMPOSITION.json",
                "FROZEN_CANDIDATE_1_2_RC1_COMPOSITION.json",
                "FROZEN_CANDIDATE_1_3_RC1_COMPOSITION.json",
                "FROZEN_CANDIDATE_1_4_RC1_COMPOSITION.json",
            ],
        )

    def test_missing_candidate_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            candidate = self._candidate_root(root)
            issues = validate_candidate_manifest(
                candidate,
                root / "FROZEN_CANDIDATE_1_1_RC3_COMPOSITION.json",
                expected_classification=RELEASE_CANDIDATE_RC3_CLASSIFICATION,
            )

        self.assertEqual(issues, ["candidate-manifest-unavailable"])

    def test_new_candidate_inventory_is_canonical_after_serialization(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "candidate"
            root.mkdir()
            (root / "fixture.txt").write_bytes(b"fixture")
            data = build_file_inventory(root)
            frozen = canonical_json_bytes(data)
            self.assertEqual(json.loads(frozen), data)
            self.assertEqual(canonical_json_bytes(json.loads(frozen)), frozen)

    @unittest.skipUnless(os.name == "nt", "autocrlf regression is Windows-specific")
    def test_autocrlf_checkout_preserves_and_validates_frozen_manifests(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git unavailable")

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "Repositório  Com  Espaços"
            checkout = root / "Checkout João — Educação"
            manifest_dir = source / "docs" / "compliance" / "build"
            candidate = source / "candidate"
            new_repository(source)
            manifest_dir.mkdir(parents=True)
            candidate.mkdir()
            shutil.copy2(PROJECT_DIR / ".gitattributes", source / ".gitattributes")

            (manifest_dir / "FROZEN_CANDIDATE_COMPOSITION.md").write_text(
                "Relatório não canônico\n",
                encoding="utf-8",
            )
            (candidate / "payload.bin").write_bytes(b"synthetic payload")
            synthetic_manifest = manifest_dir / "FROZEN_CANDIDATE_TEST_COMPOSITION.json"
            synthetic_manifest.write_bytes(
                canonical_json_bytes(
                    {"pristine_inventory": build_file_inventory(candidate)}
                )
            )

            self._run_git(["add", "."], cwd=source)
            commit(source, root, "frozen manifest fixture")

            self._run_git(
                ["clone", "--quiet", "--no-checkout", str(source), str(checkout)],
                cwd=root,
            )
            self._run_git(["config", "core.autocrlf", "true"], cwd=checkout)
            self._run_git(["checkout", "--quiet", "--force", "HEAD"], cwd=checkout)

            for name in (synthetic_manifest.name,):
                relative = f"docs/compliance/build/{name}"
                blob = self._run_git(["show", f"HEAD:{relative}"], cwd=checkout).stdout
                materialized = (checkout / relative).read_bytes()
                self.assertEqual(materialized, blob)
                self.assertEqual(
                    materialized,
                    canonical_json_bytes(json.loads(materialized)),
                )

            attributes = self._run_git(
                [
                    "check-attr",
                    "text",
                    "--",
                    "docs/compliance/build/FROZEN_CANDIDATE_TEST_COMPOSITION.json",
                    "docs/compliance/build/FROZEN_CANDIDATE_COMPOSITION.md",
                ],
                cwd=checkout,
            ).stdout.decode()
            self.assertIn(
                "FROZEN_CANDIDATE_TEST_COMPOSITION.json: text: unset",
                attributes,
            )
            self.assertIn(
                "FROZEN_CANDIDATE_COMPOSITION.md: text: unspecified",
                attributes,
            )
            self.assertEqual(
                validate_inventory_against_manifest(
                    checkout / "candidate",
                    checkout
                    / "docs"
                    / "compliance"
                    / "build"
                    / synthetic_manifest.name,
                ),
                [],
            )

    def test_active_ytdlp_external_baseline_is_current(self) -> None:
        self.assertEqual(
            EXTERNAL_BINARY_BASELINE["yt-dlp.exe"],
            {
                "component": "yt-dlp",
                "provider": "official yt-dlp release",
                "sha256": (
                    "66674953FE251B89F4D08C5F0E35E0728679BD67AB3D7D05C0562AF101DD3E7A"
                ),
                "version": "2026.08.19",
            },
        )

    def test_1_4_rc2_btbn_baseline_is_pinned_without_rewriting_rc1(self) -> None:
        self.assertEqual(EXTERNAL_BINARY_BASELINE["ffmpeg.exe"]["provider"], "Gyan")
        self.assertEqual(
            V1_4_RC2_EXTERNAL_BINARY_BASELINE["ffmpeg.exe"]["sha256"],
            "88F0453C46DBF83D3DA583A3ECECCBA6F2B82169C89A9B4254C481267E7135F8",
        )
        self.assertEqual(
            V1_4_RC2_EXTERNAL_BINARY_BASELINE["ffprobe.exe"]["sha256"],
            "07A26215E0C482407412EEBA88FD169CAA97C8CBCD0C567CF9C6CFBA6F2843C7",
        )

    def test_1_4_rc2_contract_preserves_rc1_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            rc1 = candidate_pipeline_contract(project, "v1.4-rc1")
            rc2 = candidate_pipeline_contract(project, "v1.4-rc2")
            self.assertEqual(rc2.root.name, "build-community-candidate-1.4.0-rc2")
            self.assertEqual(
                rc2.manifest.name, "FROZEN_CANDIDATE_1_4_RC2_COMPOSITION.json"
            )
            self.assertEqual(
                rc2.classification, V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION
            )
            self.assertTrue(rc2.cleanup_allowed)
            self.assertIn(
                "candidate-cleanup-target-mismatch",
                validate_candidate_cleanup_target(project, "v1.4-rc2", rc1.root),
            )

    def test_1_4_rc2_only_approves_exact_btbn_composition_delta(self) -> None:
        before = {
            "entries": [{"path": "ffmpeg.exe", "sha256": "historical"}],
            "inventory_sha256": "historical-inventory",
        }
        approved = {
            "entries": [
                {
                    "path": "ffmpeg.exe",
                    "sha256": V1_4_RC2_EXTERNAL_BINARY_BASELINE["ffmpeg.exe"]["sha256"],
                }
            ],
            "inventory_sha256": "approved-inventory",
        }
        tampered = {
            "entries": [{"path": "ffmpeg.exe", "sha256": "unapproved"}],
            "inventory_sha256": "tampered-inventory",
        }
        result = compare_candidate_composition(
            before,
            approved,
            candidate_classification=V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        )
        self.assertEqual(result["unexpected_count"], 0)
        self.assertEqual(
            result["classification_counts"], {"EXPECTED_EXTERNAL_BASELINE_UPDATE": 1}
        )
        rejected = compare_candidate_composition(
            before,
            tampered,
            candidate_classification=V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        )
        self.assertEqual(rejected["unexpected_count"], 1)

    def test_future_candidate_rejects_ds_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self._candidate_root(Path(tmp))
            for relative in (".DS_Store", "_internal/assets/.ds_store"):
                path = candidate / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic metadata")
            issues = find_contamination_issues(candidate)
        self.assertEqual(
            sum("non-runtime-metadata-present:" in issue for issue in issues), 2
        )

    def test_historical_inventory_check_does_not_rewrite_newer_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self._candidate_root(root)
            (candidate / ".DS_Store").write_bytes(b"historical metadata")
            manifest = {
                "pristine_inventory": build_file_inventory(candidate),
                "schema_version": 1,
            }
            manifest_path = root / "historical.json"
            manifest_path.write_bytes(canonical_json_bytes(manifest))

            inventory_issues = validate_inventory_against_manifest(
                candidate, manifest_path
            )
            policy_issues = find_contamination_issues(candidate)

        self.assertEqual(inventory_issues, [])
        self.assertTrue(any("non-runtime-metadata" in issue for issue in policy_issues))

    def _candidate_root(self, root: Path) -> Path:
        candidate = root / "EduDownloader-Portable"
        candidate.mkdir()
        (candidate / "Downloads").mkdir()
        (candidate / "Logs").mkdir()
        return candidate

    def test_inventory_is_canonical_complete_and_path_relative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = self._candidate_root(Path(temporary_dir))
            internal = candidate / "_internal"
            internal.mkdir()
            (candidate / "EduDownloader.exe").write_bytes(b"app")
            (internal / "base_library.zip").write_bytes(b"stdlib")

            first = build_file_inventory(candidate)
            second = build_file_inventory(candidate)

        self.assertEqual(first, second)
        self.assertEqual(first["file_count"], 2)
        self.assertTrue(all(":" not in entry["path"] for entry in first["entries"]))
        self.assertEqual(len(first["inventory_sha256"]), 64)

    def test_contamination_rejects_runtime_private_and_source_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = self._candidate_root(Path(temporary_dir))
            (candidate / "settings.json").write_text("{}", encoding="utf-8")
            (candidate / "private-key.txt").write_text(
                "-----BEGIN PRIVATE KEY-----\nsynthetic\n",
                encoding="utf-8",
            )
            (candidate / "Logs" / "old.log").write_text("old", encoding="utf-8")
            (candidate / "wheelhouse").mkdir()
            (candidate / "wheelhouse" / "sample.whl").write_bytes(b"wheel")

            issues = find_contamination_issues(candidate)

        self.assertTrue(any("runtime-settings" in issue for issue in issues))
        self.assertTrue(any("private-material-marker" in issue for issue in issues))
        self.assertTrue(any("runtime-generated" in issue for issue in issues))
        self.assertTrue(any("source-artifact" in issue for issue in issues))

    def test_contamination_scan_accepts_non_utf8_notice_and_still_finds_marker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = self._candidate_root(Path(temporary_dir))
            licenses = candidate / "Licencas"
            licenses.mkdir()
            (licenses / "legacy-notice.txt").write_bytes(b"Copyright \xa9 upstream")

            clean_issues = find_contamination_issues(candidate)
            (licenses / "bad-notice.txt").write_bytes(
                b"Copyright \xa9\n-----BEGIN PRIVATE KEY-----\nsynthetic"
            )
            private_issues = find_contamination_issues(candidate)

        self.assertEqual(clean_issues, [])
        self.assertTrue(
            any("private-material-marker" in issue for issue in private_issues)
        )

    def test_external_hash_mismatch_fails_closed(self) -> None:
        expected = {
            "tool.exe": {
                "component": "Synthetic tool",
                "provider": "synthetic",
                "sha256": "0" * 64,
                "version": "1",
            }
        }
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / "tool.exe").write_bytes(b"different")

            records, issues = inspect_external_binaries(root, expected)

        self.assertEqual(len(records), 1)
        self.assertEqual(issues, ["external-binary-hash-mismatch:tool.exe"])

    def test_after_smoke_allows_only_expected_runtime_files(self) -> None:
        before = {"entries": []}
        allowed_after = {
            "entries": [
                {
                    "path": "settings.json",
                    "sha256": "1",
                    "size_bytes": 1,
                },
                {
                    "path": "Logs/edudownloader.log",
                    "sha256": "2",
                    "size_bytes": 2,
                },
            ]
        }
        unexpected_after = {
            "entries": [
                {
                    "path": "Downloads/unexpected.mp4",
                    "sha256": "3",
                    "size_bytes": 3,
                }
            ]
        }

        allowed = compare_inventories(before, allowed_after)
        unexpected = compare_inventories(before, unexpected_after)

        self.assertEqual(allowed["runtime_changes_status"], "PASS")
        self.assertEqual(unexpected["runtime_changes_status"], "FAIL")

    def test_r2_delta_classifies_known_packaging_fixes_and_unknowns(self) -> None:
        historical = {
            "entries": [
                {"path": "_internal/ucrtbase.dll", "sha256": "1", "size_bytes": 1},
                {"path": "_internal/assets/.DS_Store", "sha256": "2", "size_bytes": 1},
                {"path": "unchanged.bin", "sha256": "3", "size_bytes": 1},
            ],
            "inventory_sha256": "A" * 64,
        }
        current = {
            "entries": [
                {"path": "unchanged.bin", "sha256": "3", "size_bytes": 1},
                {"path": "unexpected.bin", "sha256": "4", "size_bytes": 1},
            ],
            "inventory_sha256": "B" * 64,
        }

        comparison = compare_candidate_composition(historical, current)
        by_path = {item["path"]: item for item in comparison["differences"]}

        self.assertEqual(
            by_path["_internal/ucrtbase.dll"]["classification"], "PACKAGING_FIX"
        )
        self.assertEqual(
            by_path["_internal/assets/.DS_Store"]["classification"], "PACKAGING_FIX"
        )
        self.assertEqual(by_path["unexpected.bin"]["classification"], "UNEXPECTED")
        self.assertEqual(comparison["unexpected_count"], 1)

    def test_r3_delta_classifies_license_changes_as_notice_delivery_fixes(self) -> None:
        before = {
            "entries": [],
            "inventory_sha256": "A" * 64,
        }
        after = {
            "entries": [
                {
                    "path": "Licencas/MICROSOFT_RUNTIME_NOTICE.txt",
                    "sha256": "1",
                    "size_bytes": 1,
                }
            ],
            "inventory_sha256": "B" * 64,
        }

        comparison = compare_candidate_composition(before, after)

        self.assertEqual(
            comparison["classification_counts"], {"NOTICE_DELIVERY_FIX": 1}
        )
        self.assertEqual(comparison["unexpected_count"], 0)

    def test_own_mit_license_delivery_is_classified(self) -> None:
        before = {"entries": [], "inventory_sha256": "A" * 64}
        after = {
            "entries": [{"path": "LICENSE", "sha256": "1", "size_bytes": 1}],
            "inventory_sha256": "B" * 64,
        }

        comparison = compare_candidate_composition(before, after)

        self.assertEqual(
            comparison["classification_counts"], {"NOTICE_DELIVERY_FIX": 1}
        )
        self.assertEqual(comparison["unexpected_count"], 0)

    def test_1_3_pillow_freetype_delta_is_exact_and_candidate_scoped(self) -> None:
        before = {"entries": [], "inventory_sha256": "A" * 64}
        approved = {
            "path": V1_3_PILLOW_IMAGINGFT_PATH,
            "sha256": V1_3_PILLOW_IMAGINGFT_SHA256,
            "size_bytes": V1_3_PILLOW_IMAGINGFT_SIZE,
        }
        current = {"entries": [approved], "inventory_sha256": "B" * 64}

        historical = compare_candidate_composition(before, current)
        scoped = compare_candidate_composition(
            before,
            current,
            candidate_classification=V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
        )

        self.assertEqual(historical["unexpected_count"], 1)
        self.assertEqual(scoped["unexpected_count"], 0)
        self.assertEqual(
            scoped["differences"][0]["classification"], "EXPECTED_EXPLAINED"
        )
        self.assertEqual(
            _pillow_imagingft_issue(current, V1_3_RELEASE_CANDIDATE_CLASSIFICATION),
            None,
        )

    def test_1_3_pillow_freetype_rejects_other_payloads_and_missing_file(self) -> None:
        before = {"entries": [], "inventory_sha256": "A" * 64}
        approved = {
            "path": V1_3_PILLOW_IMAGINGFT_PATH,
            "sha256": V1_3_PILLOW_IMAGINGFT_SHA256,
            "size_bytes": V1_3_PILLOW_IMAGINGFT_SIZE,
        }
        variants = (
            {**approved, "path": "_internal/PIL/_imagingmorph.cp314-win_amd64.pyd"},
            {**approved, "path": "_internal/PIL/extra.dat"},
            {**approved, "path": "_internal/PIL/_imagingft.cp315-win_amd64.pyd"},
            {**approved, "path": "extra.bin"},
            {**approved, "sha256": "0" * 64},
            {**approved, "size_bytes": 1},
        )
        for variant in variants:
            with self.subTest(variant=variant):
                current = {"entries": [variant], "inventory_sha256": "B" * 64}
                comparison = compare_candidate_composition(
                    before,
                    current,
                    candidate_classification=V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
                )
                self.assertEqual(comparison["unexpected_count"], 1)
                self.assertIsNotNone(
                    _pillow_imagingft_issue(
                        current, V1_3_RELEASE_CANDIDATE_CLASSIFICATION
                    )
                )
        approved_plus_extra = {
            "entries": [approved, {**approved, "path": "_internal/PIL/extra.dat"}],
            "inventory_sha256": "C" * 64,
        }
        comparison = compare_candidate_composition(
            before,
            approved_plus_extra,
            candidate_classification=V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
        )
        self.assertEqual(comparison["unexpected_count"], 1)
        removed = compare_candidate_composition(
            {"entries": [approved], "inventory_sha256": "D" * 64},
            before,
            candidate_classification=V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
        )
        self.assertEqual(removed["unexpected_count"], 1)
        self.assertEqual(
            _pillow_imagingft_issue(before, V1_3_RELEASE_CANDIDATE_CLASSIFICATION),
            "expected-pillow-imagingft-missing",
        )

    def test_r2_delta_accepts_only_logically_equivalent_base_library_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historical_root = root / "historical"
            current_root = root / "current"
            relative = Path("_internal/base_library.zip")
            historical_zip = historical_root / relative
            current_zip = current_root / relative
            historical_zip.parent.mkdir(parents=True)
            current_zip.parent.mkdir(parents=True)
            members = (("alpha.pyc", b"alpha"), ("beta.pyc", b"beta"))
            with zipfile.ZipFile(historical_zip, "w") as archive:
                for name, content in members:
                    archive.writestr(name, content)
            with zipfile.ZipFile(current_zip, "w") as archive:
                for name, content in reversed(members):
                    archive.writestr(name, content)

            equivalent = compare_candidate_composition(
                build_file_inventory(historical_root),
                build_file_inventory(current_root),
                historical_candidate=historical_root,
                current_candidate=current_root,
            )
            difference = equivalent["differences"][0]
            self.assertEqual(difference["classification"], "EXPECTED_EXPLAINED")
            self.assertEqual(difference["reason"], "equivalent-zip-members-reordered")
            self.assertEqual(equivalent["unexpected_count"], 0)

            with zipfile.ZipFile(current_zip, "w") as archive:
                archive.writestr("alpha.pyc", b"changed")
                archive.writestr("beta.pyc", b"beta")
            changed = compare_candidate_composition(
                build_file_inventory(historical_root),
                build_file_inventory(current_root),
                historical_candidate=historical_root,
                current_candidate=current_root,
            )
            self.assertEqual(changed["differences"][0]["classification"], "UNEXPECTED")
            self.assertEqual(changed["unexpected_count"], 1)

    def test_notice_delivery_is_conservative_and_physical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self._candidate_root(Path(tmp))
            licenses = candidate / "Licencas"
            (licenses / "PyInstaller").mkdir(parents=True)
            (licenses / "pyinstaller-hooks-contrib").mkdir()
            for relative in (
                "DENO_LICENSE.txt",
                "CUSTOMTKINTER_LICENSE.txt",
                "PyInstaller/COPYING.txt",
                "PyInstaller/ZLIB_LICENSE.txt",
                "pyinstaller-hooks-contrib/LICENSE",
            ):
                (licenses / relative).write_text("fixture", encoding="utf-8")

            delivery = audit_notice_delivery(candidate)

        self.assertEqual(delivery["pyinstaller"]["status"], "DELIVERED")
        self.assertEqual(delivery["deno"]["status"], "PARTIAL")
        self.assertEqual(delivery["microsoft"]["status"], "PENDING_FIX")
        self.assertEqual(delivery["cpython_tcl_tk"]["status"], "PENDING_FIX")

    def test_build_only_packages_are_not_inferred_from_wheelhouse(self) -> None:
        records = classify_package_materiality(
            pyz_modules=("customtkinter", "PIL.Image", "pypdf"),
            file_paths=("_internal/PIL/_imaging.pyd",),
            runtime_hooks=({"name": "pyi_rth_inspect", "provenance": "PyInstaller"},),
        )
        by_package = {record["package"]: record for record in records}

        self.assertEqual(by_package["pip"]["classification"], "BUILD_TOOL_ONLY")
        self.assertEqual(by_package["ruff"]["classification"], "BUILD_TOOL_ONLY")
        self.assertEqual(by_package["setuptools"]["classification"], "BUILD_TOOL_ONLY")
        self.assertEqual(by_package["altgraph"]["classification"], "BUILD_ONLY")
        self.assertEqual(
            by_package["pyinstaller"]["classification"],
            "PARTIAL_COMPONENT_PRESENT",
        )
        self.assertEqual(by_package["pillow"]["classification"], "DISTRIBUTED_NATIVE")

    def test_noncanonical_candidate_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            candidate = self._candidate_root(root)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "application": {
                            "app_version": APP_VERSION,
                            "product_edition": "community",
                        },
                        "candidate_classification": CANDIDATE_CLASSIFICATION,
                        "gates": {
                            "production_ready": False,
                            "public_release_allowed": False,
                        },
                        "pristine_inventory": build_file_inventory(candidate),
                        "schema_version": 1,
                    }
                ),
                encoding="utf-8",
            )

            issues = validate_candidate_manifest(candidate, manifest_path)

        self.assertIn("candidate-manifest-not-canonical", issues)

    def test_controlled_candidate_classification_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            candidate = self._candidate_root(root)
            manifest_path = root / "manifest.json"
            manifest_path.write_bytes(
                canonical_json_bytes(
                    {
                        "application": {
                            "app_version": APP_VERSION,
                            "product_edition": "community",
                        },
                        "candidate_classification": CONTROLLED_CANDIDATE_CLASSIFICATION,
                        "gates": {
                            "production_ready": False,
                            "public_release_allowed": False,
                        },
                        "pristine_inventory": build_file_inventory(candidate),
                        "schema_version": 1,
                    }
                )
            )

            issues = validate_candidate_manifest(
                candidate,
                manifest_path,
                expected_classification=CONTROLLED_CANDIDATE_CLASSIFICATION,
            )

        self.assertNotIn("candidate-classification-mismatch", issues)
        self.assertNotIn("candidate-classification-expectation-invalid", issues)

    def test_1_6_probe_manifest_requires_non_rc_and_closed_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            candidate = self._candidate_root(root)
            manifest_path = root / "manifest.json"
            payload = {
                "application": {
                    "app_version": "1.6.0",
                    "product_edition": "community",
                    "activation_required_for_current_edition": False,
                },
                "candidate_classification": V1_6_PORTABILITY_PROBE_CLASSIFICATION,
                "controlled_packaging": {
                    "microsoft_dynamic_runtime_file_count": 0,
                },
                "gates": {
                    "production_ready": False,
                    "public_release_allowed": False,
                },
                "pristine_inventory": build_file_inventory(candidate),
                "probe_contract": {
                    "is_release_candidate": False,
                    "rc_number": "NONE",
                    "purpose": "PORTABILITY_AND_VC_RUNTIME",
                },
                "schema_version": 1,
            }
            manifest_path.write_bytes(canonical_json_bytes(payload))
            valid = validate_candidate_manifest(
                candidate,
                manifest_path,
                expected_classification=V1_6_PORTABILITY_PROBE_CLASSIFICATION,
            )
            self.assertNotIn("probe-contract-mismatch", valid)
            self.assertNotIn("probe-application-contract-mismatch", valid)
            self.assertNotIn("probe-direct-microsoft-runtime-present", valid)
            payload["probe_contract"]["is_release_candidate"] = True
            payload["gates"]["public_release_allowed"] = True
            payload["controlled_packaging"]["microsoft_dynamic_runtime_file_count"] = 1
            manifest_path.write_bytes(canonical_json_bytes(payload))
            invalid = validate_candidate_manifest(
                candidate,
                manifest_path,
                expected_classification=V1_6_PORTABILITY_PROBE_CLASSIFICATION,
            )
            self.assertIn("probe-contract-mismatch", invalid)
            self.assertIn("public-release-gate-open", invalid)
            self.assertIn("probe-direct-microsoft-runtime-present", invalid)

    def test_1_6_rc1_manifest_requires_rc1_and_closed_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            candidate = self._candidate_root(root)
            manifest_path = root / "manifest.json"
            payload = {
                "application": {
                    "app_version": "1.6.0",
                    "product_edition": "community",
                    "activation_required_for_current_edition": False,
                },
                "candidate_classification": V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
                "controlled_packaging": {"microsoft_dynamic_runtime_file_count": 0},
                "gates": {"production_ready": False, "public_release_allowed": False},
                "pristine_inventory": build_file_inventory(candidate),
                "rc_contract": {"is_release_candidate": True, "rc_number": 1},
                "schema_version": 1,
            }
            manifest_path.write_bytes(canonical_json_bytes(payload))
            valid = validate_candidate_manifest(
                candidate,
                manifest_path,
                expected_classification=V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
            )
            self.assertNotIn("v1.6-rc-contract-mismatch", valid)
            self.assertNotIn("v1.6-rc-application-contract-mismatch", valid)
            self.assertNotIn("v1.6-rc-direct-microsoft-runtime-present", valid)
            payload["rc_contract"]["rc_number"] = 2
            payload["gates"]["public_release_allowed"] = True
            payload["controlled_packaging"]["microsoft_dynamic_runtime_file_count"] = 1
            manifest_path.write_bytes(canonical_json_bytes(payload))
            invalid = validate_candidate_manifest(
                candidate,
                manifest_path,
                expected_classification=V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
            )
            self.assertIn("v1.6-rc-contract-mismatch", invalid)
            self.assertIn("public-release-gate-open", invalid)
            self.assertIn("v1.6-rc-direct-microsoft-runtime-present", invalid)

    def test_1_6_rc2_manifest_requires_rc2_and_closed_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            candidate = self._candidate_root(root)
            manifest_path = root / "manifest.json"
            payload = {
                "application": {
                    "app_version": "1.6.0",
                    "product_edition": "community",
                    "activation_required_for_current_edition": False,
                },
                "candidate_classification": V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
                "controlled_packaging": {"microsoft_dynamic_runtime_file_count": 0},
                "gates": {"production_ready": False, "public_release_allowed": False},
                "pristine_inventory": build_file_inventory(candidate),
                "rc_contract": {"is_release_candidate": True, "rc_number": 2},
                "schema_version": 1,
            }
            manifest_path.write_bytes(canonical_json_bytes(payload))
            valid = validate_candidate_manifest(
                candidate,
                manifest_path,
                expected_classification=V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
            )
            self.assertNotIn("v1.6-rc-contract-mismatch", valid)
            self.assertNotIn("v1.6-rc-application-contract-mismatch", valid)
            self.assertNotIn("v1.6-rc-direct-microsoft-runtime-present", valid)
            payload["rc_contract"]["rc_number"] = 1
            payload["gates"]["public_release_allowed"] = True
            payload["controlled_packaging"]["microsoft_dynamic_runtime_file_count"] = 1
            manifest_path.write_bytes(canonical_json_bytes(payload))
            invalid = validate_candidate_manifest(
                candidate,
                manifest_path,
                expected_classification=V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
            )
            self.assertIn("v1.6-rc-contract-mismatch", invalid)
            self.assertIn("public-release-gate-open", invalid)
            self.assertIn("v1.6-rc-direct-microsoft-runtime-present", invalid)

    def test_1_7_rc1_manifest_requires_version_contract_and_closed_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            candidate = self._candidate_root(root)
            manifest_path = root / "manifest.json"
            payload = {
                "application": {
                    "app_version": "1.7.0",
                    "product_edition": "community",
                    "activation_required_for_current_edition": False,
                },
                "candidate_classification": V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
                "controlled_packaging": {"microsoft_dynamic_runtime_file_count": 0},
                "gates": {"production_ready": False, "public_release_allowed": False},
                "pristine_inventory": build_file_inventory(candidate),
                "rc_contract": {"is_release_candidate": True, "rc_number": 1},
                "schema_version": 1,
            }
            manifest_path.write_bytes(canonical_json_bytes(payload))
            valid = validate_candidate_manifest(
                candidate,
                manifest_path,
                expected_classification=V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
            )
            for issue in (
                "v1.7-rc-contract-mismatch",
                "v1.7-rc-application-contract-mismatch",
                "v1.7-rc-direct-microsoft-runtime-present",
                "public-release-gate-open",
            ):
                self.assertNotIn(issue, valid)
            payload["rc_contract"]["rc_number"] = 2
            payload["application"]["app_version"] = "1.6.0"
            payload["controlled_packaging"]["microsoft_dynamic_runtime_file_count"] = 1
            payload["gates"]["public_release_allowed"] = True
            manifest_path.write_bytes(canonical_json_bytes(payload))
            invalid = validate_candidate_manifest(
                candidate,
                manifest_path,
                expected_classification=V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
            )
            for issue in (
                "v1.7-rc-contract-mismatch",
                "v1.7-rc-application-contract-mismatch",
                "v1.7-rc-direct-microsoft-runtime-present",
                "public-release-gate-open",
            ):
                self.assertIn(issue, invalid)

    def test_r3_candidate_classification_is_explicit(self) -> None:
        self.assertEqual(
            NOTICE_COMPLETE_CANDIDATE_CLASSIFICATION,
            "INTERNAL_CONTROLLED_CANDIDATE_R3",
        )

    def test_1_0_rc1_candidate_classification_is_explicit(self) -> None:
        self.assertEqual(
            V1_0_RELEASE_CANDIDATE_CLASSIFICATION,
            "INTERNAL_1_0_RELEASE_CANDIDATE_RC1",
        )

    def test_1_1_rc1_candidate_classification_is_explicit(self) -> None:
        self.assertEqual(
            RELEASE_CANDIDATE_CLASSIFICATION,
            "INTERNAL_1_1_RELEASE_CANDIDATE_RC1",
        )

    def test_1_1_rc2_candidate_classification_is_explicit(self) -> None:
        self.assertEqual(
            RELEASE_CANDIDATE_RC2_CLASSIFICATION,
            "INTERNAL_1_1_RELEASE_CANDIDATE_RC2",
        )

    def test_1_1_rc3_candidate_classification_is_explicit(self) -> None:
        self.assertEqual(
            RELEASE_CANDIDATE_RC3_CLASSIFICATION,
            "INTERNAL_1_1_RELEASE_CANDIDATE_RC3",
        )

    def test_1_2_rc1_candidate_classification_is_explicit(self) -> None:
        self.assertEqual(
            V1_2_RELEASE_CANDIDATE_CLASSIFICATION,
            "INTERNAL_1_2_RELEASE_CANDIDATE_RC1",
        )

    def test_1_3_rc1_candidate_classification_is_explicit(self) -> None:
        self.assertEqual(
            V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
            "INTERNAL_1_3_RELEASE_CANDIDATE_RC1",
        )

    def test_1_4_rc1_candidate_classification_is_explicit(self) -> None:
        self.assertEqual(
            V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
            "INTERNAL_1_4_RELEASE_CANDIDATE_RC1",
        )

    def test_1_4_archive_contract_requires_documents_without_pdf_to_docx_stack(
        self,
    ) -> None:
        valid = {"pyz_modules": ["app", "documents_component", "documents_tools"]}
        self.assertEqual(
            find_v1_4_archive_issues(valid, V1_4_RELEASE_CANDIDATE_CLASSIFICATION),
            [],
        )
        missing = find_v1_4_archive_issues(
            {"pyz_modules": ["app", "documents_tools"]},
            V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
        )
        self.assertIn("v1.4-required-pyz-module-missing:documents_component", missing)
        for namespace in ("pdf2docx", "fitz", "pymupdf", "cv2", "numpy"):
            with self.subTest(namespace=namespace):
                issues = find_v1_4_archive_issues(
                    {
                        "pyz_modules": [
                            "documents_component",
                            "documents_tools",
                            namespace,
                        ]
                    },
                    V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
                )
                self.assertIn(f"v1.4-pdf-to-docx-module-forbidden:{namespace}", issues)

    def test_rc3_manifest_rejects_wrong_candidate_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            candidate = self._candidate_root(root)
            manifest_path = root / "FROZEN_CANDIDATE_1_1_RC3_COMPOSITION.json"
            manifest_path.write_bytes(
                canonical_json_bytes(
                    {
                        "application": {
                            "app_version": APP_VERSION,
                            "product_edition": "community",
                        },
                        "candidate_classification": (
                            RELEASE_CANDIDATE_RC2_CLASSIFICATION
                        ),
                        "gates": {
                            "production_ready": False,
                            "public_release_allowed": False,
                        },
                        "pristine_inventory": build_file_inventory(candidate),
                        "schema_version": 1,
                    }
                )
            )

            issues = validate_candidate_manifest(
                candidate,
                manifest_path,
                expected_classification=RELEASE_CANDIDATE_RC3_CLASSIFICATION,
            )

        self.assertIn("candidate-classification-mismatch", issues)

    def test_candidate_contracts_use_separate_exact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            rc1 = candidate_pipeline_contract(project, "rc1")
            rc2 = candidate_pipeline_contract(project, "rc2")
            rc3 = candidate_pipeline_contract(project, "rc3")
            v1_2_rc1 = candidate_pipeline_contract(project, "v1.2-rc1")
            v1_3_rc1 = candidate_pipeline_contract(project, "v1.3-rc1")
            v1_4_rc1 = candidate_pipeline_contract(project, "v1.4-rc1")

        self.assertEqual(rc1.root.name, "build-community-candidate-1.1.0-rc1")
        self.assertEqual(
            rc1.manifest.name,
            "FROZEN_CANDIDATE_1_1_RC1_COMPOSITION.json",
        )
        self.assertEqual(rc1.classification, RELEASE_CANDIDATE_CLASSIFICATION)
        self.assertFalse(rc1.cleanup_allowed)
        self.assertEqual(rc2.root.name, "build-community-candidate-1.1.0-rc2")
        self.assertEqual(
            rc2.manifest.name,
            "FROZEN_CANDIDATE_1_1_RC2_COMPOSITION.json",
        )
        self.assertEqual(rc2.classification, RELEASE_CANDIDATE_RC2_CLASSIFICATION)
        self.assertFalse(rc2.cleanup_allowed)
        self.assertEqual(rc3.root.name, "build-community-candidate-1.1.0-rc3")
        self.assertEqual(
            rc3.manifest.name,
            "FROZEN_CANDIDATE_1_1_RC3_COMPOSITION.json",
        )
        self.assertEqual(rc3.classification, RELEASE_CANDIDATE_RC3_CLASSIFICATION)
        self.assertFalse(rc3.cleanup_allowed)
        self.assertEqual(v1_2_rc1.root.name, "build-community-candidate-1.2.0-rc1")
        self.assertEqual(
            v1_2_rc1.manifest.name,
            "FROZEN_CANDIDATE_1_2_RC1_COMPOSITION.json",
        )
        self.assertEqual(
            v1_2_rc1.classification,
            V1_2_RELEASE_CANDIDATE_CLASSIFICATION,
        )
        self.assertFalse(v1_2_rc1.cleanup_allowed)
        self.assertEqual(v1_3_rc1.root.name, "build-community-candidate-1.3.0-rc1")
        self.assertEqual(
            v1_3_rc1.manifest.name,
            "FROZEN_CANDIDATE_1_3_RC1_COMPOSITION.json",
        )
        self.assertEqual(v1_3_rc1.classification, V1_3_RELEASE_CANDIDATE_CLASSIFICATION)
        self.assertFalse(v1_3_rc1.cleanup_allowed)
        self.assertEqual(v1_4_rc1.root.name, "build-community-candidate-1.4.0-rc1")
        self.assertEqual(
            v1_4_rc1.manifest.name,
            "FROZEN_CANDIDATE_1_4_RC1_COMPOSITION.json",
        )
        self.assertEqual(v1_4_rc1.classification, V1_4_RELEASE_CANDIDATE_CLASSIFICATION)
        self.assertTrue(v1_4_rc1.cleanup_allowed)
        self.assertEqual(
            len(
                {
                    rc1.root,
                    rc2.root,
                    rc3.root,
                    v1_2_rc1.root,
                    v1_3_rc1.root,
                    v1_4_rc1.root,
                }
            ),
            6,
        )
        self.assertEqual(
            len(
                {
                    rc1.manifest,
                    rc2.manifest,
                    rc3.manifest,
                    v1_2_rc1.manifest,
                    v1_3_rc1.manifest,
                    v1_4_rc1.manifest,
                }
            ),
            6,
        )

    def test_1_5_candidate_contract_is_isolated_and_preserves_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            selected = candidate_pipeline_contract(project, "v1.5-rc1")
            previous = candidate_pipeline_contract(project, "v1.4-rc2")

            self.assertEqual(selected.root.name, "build-community-candidate-1.5.0-rc1")
            self.assertEqual(
                selected.manifest.name,
                "FROZEN_CANDIDATE_1_5_RC1_COMPOSITION.json",
            )
            self.assertEqual(
                selected.classification, V1_5_RELEASE_CANDIDATE_CLASSIFICATION
            )
            self.assertTrue(selected.cleanup_allowed)
            self.assertEqual(
                validate_candidate_cleanup_target(project, "v1.5-rc1", selected.root),
                [],
            )
            self.assertIn(
                "candidate-cleanup-target-mismatch",
                validate_candidate_cleanup_target(project, "v1.5-rc1", previous.root),
            )
            self.assertIn(
                "candidate-cleanup-protected-v1.4-rc2",
                validate_candidate_cleanup_target(project, "v1.5-rc1", previous.root),
            )
            self.assertEqual(
                find_v1_5_archive_issues(
                    {
                        "pyz_modules": [
                            "documents_component",
                            "documents_tools",
                            "media_tools",
                            "mp3_quality",
                        ]
                    },
                    selected.classification,
                ),
                [],
            )
            self.assertIn(
                "v1.5-required-pyz-module-missing:media_tools",
                find_v1_5_archive_issues(
                    {"pyz_modules": ["mp3_quality"]}, selected.classification
                ),
            )

    def test_1_6_probe_contract_is_not_an_rc_and_preserves_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            selected = candidate_pipeline_contract(project, "v1.6-probe")
            previous = candidate_pipeline_contract(project, "v1.5-rc1")
            self.assertEqual(selected.root.name, "build-community-probe-1.6.0")
            self.assertEqual(
                selected.manifest,
                selected.root / "evidence" / "FROZEN_PROBE_1_6_COMPOSITION.json",
            )
            self.assertEqual(
                selected.classification, V1_6_PORTABILITY_PROBE_CLASSIFICATION
            )
            self.assertNotIn("RELEASE_CANDIDATE", selected.classification)
            self.assertTrue(selected.cleanup_allowed)
            self.assertEqual(
                validate_candidate_cleanup_target(project, "v1.6-probe", selected.root),
                [],
            )
            self.assertIn(
                "candidate-cleanup-protected-v1.5-rc1",
                validate_candidate_cleanup_target(project, "v1.6-probe", previous.root),
            )
            self.assertIn(
                "v1.5-required-pyz-module-missing:media_tools",
                find_v1_5_archive_issues(
                    {"pyz_modules": ["mp3_quality"]}, selected.classification
                ),
            )

    def test_1_6_rc1_contract_preserves_probe_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            selected = candidate_pipeline_contract(project, "v1.6-rc1")
            probe = candidate_pipeline_contract(project, "v1.6-probe")
            previous = candidate_pipeline_contract(project, "v1.5-rc1")
            self.assertEqual(selected.root.name, "build-community-candidate-1.6.0-rc1")
            self.assertEqual(
                selected.manifest,
                project
                / "docs/compliance/build/FROZEN_CANDIDATE_1_6_RC1_COMPOSITION.json",
            )
            self.assertEqual(
                selected.classification, V1_6_RELEASE_CANDIDATE_CLASSIFICATION
            )
            self.assertTrue(selected.cleanup_allowed)
            self.assertEqual(
                validate_candidate_cleanup_target(project, "v1.6-rc1", selected.root),
                [],
            )
            self.assertIn(
                "candidate-cleanup-protected-v1.6-probe",
                validate_candidate_cleanup_target(project, "v1.6-rc1", probe.root),
            )
            self.assertIn(
                "candidate-cleanup-protected-v1.5-rc1",
                validate_candidate_cleanup_target(project, "v1.6-rc1", previous.root),
            )

    def test_1_6_rc2_contract_preserves_rc1_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            selected = candidate_pipeline_contract(project, "v1.6-rc2")
            rc1 = candidate_pipeline_contract(project, "v1.6-rc1")
            probe = candidate_pipeline_contract(project, "v1.6-probe")
            previous = candidate_pipeline_contract(project, "v1.5-rc1")
            self.assertEqual(selected.root.name, "build-community-candidate-1.6.0-rc2")
            self.assertEqual(
                selected.manifest,
                project
                / "docs/compliance/build/FROZEN_CANDIDATE_1_6_RC2_COMPOSITION.json",
            )
            self.assertEqual(
                selected.classification, V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION
            )
            self.assertTrue(selected.cleanup_allowed)
            self.assertEqual(
                validate_candidate_cleanup_target(project, "v1.6-rc2", selected.root),
                [],
            )
            for historical_id, historical in (
                ("v1.6-rc1", rc1),
                ("v1.6-probe", probe),
                ("v1.5-rc1", previous),
            ):
                self.assertIn(
                    f"candidate-cleanup-protected-{historical_id}",
                    validate_candidate_cleanup_target(
                        project, "v1.6-rc2", historical.root
                    ),
                )
            self.assertIn(
                "v1.5-required-pyz-module-missing:media_tools",
                find_v1_5_archive_issues(
                    {"pyz_modules": ["mp3_quality"]}, selected.classification
                ),
            )

    def test_1_7_rc1_contract_preserves_visual_probe_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            selected = candidate_pipeline_contract(project, "v1.7-rc1")
            self.assertEqual(selected.root.name, "build-community-candidate-1.7.0-rc1")
            self.assertEqual(
                selected.manifest,
                project
                / "docs/compliance/build/FROZEN_CANDIDATE_1_7_RC1_COMPOSITION.json",
            )
            self.assertEqual(
                selected.classification, V1_7_RELEASE_CANDIDATE_CLASSIFICATION
            )
            self.assertTrue(selected.cleanup_allowed)
            self.assertEqual(
                validate_candidate_cleanup_target(project, "v1.7-rc1", selected.root),
                [],
            )
            for historical_id in (
                "v1.7-visual-probe",
                "v1.6-rc2",
                "v1.6-rc1",
                "v1.5-rc1",
            ):
                historical = candidate_pipeline_contract(project, historical_id)
                self.assertIn(
                    f"candidate-cleanup-protected-{historical_id}",
                    validate_candidate_cleanup_target(
                        project, "v1.7-rc1", historical.root
                    ),
                )

    def test_probe_rejects_managed_components_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = Path(temporary_dir)
            (candidate / "Downloads").mkdir()
            (candidate / "Logs").mkdir()
            (candidate / "Componentes").mkdir()
            self.assertIn(
                "managed-components-bundled", find_contamination_issues(candidate)
            )

    def test_candidate_contract_environment_keeps_1_1_through_1_3_as_history(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            environment = candidate_contract_environment(project, "v1.4-rc1")

        self.assertTrue(environment["CANDIDATE_ROOT"].endswith("1.4.0-rc1"))
        self.assertTrue(environment["RC1_CANDIDATE_ROOT"].endswith("1.1.0-rc1"))
        self.assertTrue(
            environment["RC1_PORTABLE_DIR"].endswith(
                "1.1.0-rc1\\dist\\EduDownloader-Portable"
            )
        )
        self.assertTrue(environment["RC2_CANDIDATE_ROOT"].endswith("1.1.0-rc2"))
        self.assertTrue(
            environment["RC2_PORTABLE_DIR"].endswith(
                "1.1.0-rc2\\dist\\EduDownloader-Portable"
            )
        )
        self.assertTrue(environment["RC3_CANDIDATE_ROOT"].endswith("1.1.0-rc3"))
        self.assertTrue(
            environment["RC3_PORTABLE_DIR"].endswith(
                "1.1.0-rc3\\dist\\EduDownloader-Portable"
            )
        )
        self.assertTrue(environment["V1_2_RC1_CANDIDATE_ROOT"].endswith("1.2.0-rc1"))
        self.assertTrue(
            environment["V1_2_RC1_PORTABLE_DIR"].endswith(
                "1.2.0-rc1\\dist\\EduDownloader-Portable"
            )
        )
        self.assertTrue(environment["V1_3_RC1_CANDIDATE_ROOT"].endswith("1.3.0-rc1"))
        self.assertTrue(
            environment["V1_3_RC1_PORTABLE_DIR"].endswith(
                "1.3.0-rc1\\dist\\EduDownloader-Portable"
            )
        )
        self.assertEqual(
            environment["CANDIDATE_CLASSIFICATION"],
            V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
        )
        self.assertEqual(environment["CANDIDATE_CLEANUP_ALLOWED"], "1")
        self.assertEqual(environment["RESOLVED_CANDIDATE_ID"], "v1.4-rc1")

    def test_invalid_candidate_identifier_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            with self.assertRaisesRegex(ValueError, "unsupported-candidate-id"):
                candidate_pipeline_contract(Path(temporary_dir), "v1.2-rc2")
            for candidate_id in ("v1.4-rc3", "v1.4-rc10", "unknown"):
                with self.subTest(candidate_id=candidate_id):
                    with self.assertRaisesRegex(ValueError, "unsupported-candidate-id"):
                        candidate_pipeline_contract(Path(temporary_dir), candidate_id)

    def test_cleanup_rejects_history_outside_parent_and_similar_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            rc1 = candidate_pipeline_contract(project, "rc1")
            rc2 = candidate_pipeline_contract(project, "rc2")
            rc3 = candidate_pipeline_contract(project, "rc3")
            v1_2_rc1 = candidate_pipeline_contract(project, "v1.2-rc1")
            v1_3_rc1 = candidate_pipeline_contract(project, "v1.3-rc1")
            selected = candidate_pipeline_contract(project, "v1.4-rc1")
            parent = project
            outside = project / "nested" / "build-community-candidate-1.4.0-rc1"
            external = project.parent / "outside-v1.4-rc1"
            similar = project / "build-community-candidate-1.4.0-rc1-other"
            future = project / "build-community-candidate-1.4.0-rc2"
            rc10 = project / "build-community-candidate-1.4.0-rc10"
            poc = project / "build-documents-poc"
            component = project / "components" / "documents"

            rc1_issues = validate_candidate_cleanup_target(project, "rc1", rc1.root)
            rc2_issues = validate_candidate_cleanup_target(project, "rc2", rc2.root)
            rc3_issues = validate_candidate_cleanup_target(project, "rc3", rc3.root)
            v1_2_issues = validate_candidate_cleanup_target(
                project, "v1.2-rc1", v1_2_rc1.root
            )
            v1_3_issues = validate_candidate_cleanup_target(
                project, "v1.3-rc1", v1_3_rc1.root
            )
            parent_issues = validate_candidate_cleanup_target(
                project, "v1.4-rc1", parent
            )
            outside_issues = validate_candidate_cleanup_target(
                project, "v1.4-rc1", outside
            )
            external_issues = validate_candidate_cleanup_target(
                project, "v1.4-rc1", external
            )
            similar_issues = validate_candidate_cleanup_target(
                project, "v1.4-rc1", similar
            )
            future_issues = validate_candidate_cleanup_target(
                project, "v1.4-rc1", future
            )
            rc10_issues = validate_candidate_cleanup_target(project, "v1.4-rc1", rc10)
            historical_issues = validate_candidate_cleanup_target(
                project, "v1.4-rc1", v1_3_rc1.root
            )
            poc_issues = validate_candidate_cleanup_target(project, "v1.4-rc1", poc)
            component_issues = validate_candidate_cleanup_target(
                project, "v1.4-rc1", component
            )

            rc1.root.mkdir()
            rc2.root.mkdir()
            rc3.root.mkdir()
            v1_2_rc1.root.mkdir()
            v1_3_rc1.root.mkdir()
            rc1_marker = rc1.root / "pristine.txt"
            rc2_marker = rc2.root / "pristine.txt"
            rc3_marker = rc3.root / "pristine.txt"
            v1_2_marker = v1_2_rc1.root / "pristine.txt"
            v1_3_marker = v1_3_rc1.root / "pristine.txt"
            rc1_marker.write_text("preserve", encoding="utf-8")
            rc2_marker.write_text("preserve", encoding="utf-8")
            rc3_marker.write_text("preserve", encoding="utf-8")
            v1_2_marker.write_text("preserve", encoding="utf-8")
            v1_3_marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "candidate-cleanup-read-only"):
                prepare_candidate_root(project, "rc1", rc1.root)
            with self.assertRaisesRegex(ValueError, "candidate-cleanup-read-only"):
                prepare_candidate_root(project, "rc2", rc2.root)
            with self.assertRaisesRegex(ValueError, "candidate-cleanup-read-only"):
                prepare_candidate_root(project, "rc3", rc3.root)
            with self.assertRaisesRegex(ValueError, "candidate-cleanup-read-only"):
                prepare_candidate_root(project, "v1.2-rc1", v1_2_rc1.root)
            with self.assertRaisesRegex(ValueError, "candidate-cleanup-read-only"):
                prepare_candidate_root(project, "v1.3-rc1", v1_3_rc1.root)

            self.assertIn("candidate-cleanup-read-only", rc1_issues)
            self.assertIn("candidate-cleanup-protected-rc1", rc1_issues)
            self.assertIn("candidate-cleanup-read-only", rc2_issues)
            self.assertIn("candidate-cleanup-protected-rc2", rc2_issues)
            self.assertIn("candidate-cleanup-read-only", rc3_issues)
            self.assertIn("candidate-cleanup-protected-rc3", rc3_issues)
            self.assertIn("candidate-cleanup-read-only", v1_2_issues)
            self.assertIn("candidate-cleanup-protected-v1.2-rc1", v1_2_issues)
            self.assertIn("candidate-cleanup-read-only", v1_3_issues)
            self.assertIn("candidate-cleanup-protected-v1.3-rc1", v1_3_issues)
            self.assertIn("candidate-cleanup-target-mismatch", parent_issues)
            self.assertIn("candidate-cleanup-outside-project", parent_issues)
            self.assertIn("candidate-cleanup-target-mismatch", outside_issues)
            self.assertIn("candidate-cleanup-outside-project", outside_issues)
            self.assertIn("candidate-cleanup-outside-project", external_issues)
            self.assertIn("candidate-cleanup-target-mismatch", similar_issues)
            self.assertIn("candidate-cleanup-target-mismatch", future_issues)
            self.assertIn("candidate-cleanup-target-mismatch", rc10_issues)
            self.assertIn("candidate-cleanup-target-mismatch", historical_issues)
            self.assertIn("candidate-cleanup-protected-v1.3-rc1", historical_issues)
            self.assertIn("candidate-cleanup-target-mismatch", poc_issues)
            self.assertIn("candidate-cleanup-target-mismatch", component_issues)
            self.assertEqual(rc1_marker.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(rc2_marker.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(rc3_marker.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(v1_2_marker.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(v1_3_marker.read_text(encoding="utf-8"), "preserve")
            self.assertTrue(selected.cleanup_allowed)

    def test_1_4_rc1_cleanup_removes_only_synthetic_selected_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            rc1 = candidate_pipeline_contract(project, "rc1")
            rc2 = candidate_pipeline_contract(project, "rc2")
            rc3 = candidate_pipeline_contract(project, "rc3")
            v1_2_rc1 = candidate_pipeline_contract(project, "v1.2-rc1")
            v1_3_rc1 = candidate_pipeline_contract(project, "v1.3-rc1")
            selected = candidate_pipeline_contract(project, "v1.4-rc1")
            rc1.root.mkdir()
            rc2.root.mkdir()
            rc3.root.mkdir()
            v1_2_rc1.root.mkdir()
            v1_3_rc1.root.mkdir()
            selected.root.mkdir()
            markers = [
                candidate.root / "pristine.txt"
                for candidate in (rc1, rc2, rc3, v1_2_rc1, v1_3_rc1)
            ]
            for marker in markers:
                marker.write_text("preserve", encoding="utf-8")
            (selected.root / "temporary.txt").write_text("remove", encoding="utf-8")

            prepare_candidate_root(project, "v1.4-rc1", selected.root)

            self.assertFalse(selected.root.exists())
            for marker in markers:
                self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_1_1_through_1_3_inventories_remain_valid_after_1_4_configuration(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            historical = [
                candidate_pipeline_contract(project, candidate_id)
                for candidate_id in ("rc1", "rc2", "rc3", "v1.2-rc1", "v1.3-rc1")
            ]
            manifests = []
            for candidate in historical:
                candidate.root.mkdir()
                (candidate.root / "pristine.txt").write_text(
                    "preserve", encoding="utf-8"
                )
                manifest = project / f"{candidate.candidate_id}.json"
                manifest.write_bytes(
                    canonical_json_bytes(
                        {"pristine_inventory": build_file_inventory(candidate.root)}
                    )
                )
                manifests.append(manifest)

            candidate_pipeline_contract(project, "v1.4-rc1")
            issues = [
                validate_inventory_against_manifest(candidate.root, manifest)
                for candidate, manifest in zip(historical, manifests, strict=True)
            ]

        self.assertEqual(issues, [[], [], [], [], []])

    def test_packed_ytdlp_smoke_results_are_fail_closed(self) -> None:
        self.assertEqual(ALLOWED_PACKED_YTDLP_SMOKE_RESULTS, {"NOT_RUN", "PASS"})

    def test_approved_ytdlp_and_readme_deltas_are_expected(self) -> None:
        historical = {
            "entries": [],
            "inventory_sha256": "before",
        }
        current = {
            "entries": [
                {"path": "yt-dlp.exe"},
                {"path": "README.txt"},
            ],
            "inventory_sha256": "after",
        }

        result = compare_candidate_composition(historical, current)

        self.assertEqual(result["unexpected_count"], 0)
        self.assertEqual(
            {item["classification"] for item in result["differences"]},
            {"EXPECTED_EXTERNAL_BASELINE_UPDATE", "EXPECTED_SOURCE_EVOLUTION"},
        )

    def test_canonical_json_has_trailing_newline_and_sorted_keys(self) -> None:
        serialized = canonical_json_bytes({"z": 1, "a": 2})

        self.assertEqual(serialized, b'{\n  "a": 2,\n  "z": 1\n}\n')


if __name__ == "__main__":
    unittest.main()
