"""Testes offline da consolidação de notices do próximo candidato."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import notice_delivery
from tests.git_fixture import clone_with_autocrlf, commit, git, new_repository


PROJECT_DIR = Path(__file__).resolve().parents[1]
TEXT_NORMALIZED_DELIVERY_PATHS = ()
BYTE_CANONICAL_AUTHORITY_PATHS = (
    "docs/compliance/deno/DENO_THIRD_PARTY_INVENTORY.json",
    "docs/compliance/deno/DENO_THIRD_PARTY_NOTICES.txt",
    "docs/compliance/notices/NOTICE_DELIVERY_INVENTORY.json",
)


class NoticeDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = PROJECT_DIR
        cls.inventory = json.loads(
            notice_delivery.INVENTORY_PATH.read_text(encoding="utf-8")
        )

    @classmethod
    def _byte_canonical_notice_paths(cls) -> tuple[str, ...]:
        text_normalized = set(TEXT_NORMALIZED_DELIVERY_PATHS)
        delivered = {
            f"Licencas/{item['path']}" for item in cls.inventory["delivery_artifacts"]
        }
        return tuple(
            sorted(
                (delivered - text_normalized) | set(BYTE_CANONICAL_AUTHORITY_PATHS),
                key=str.casefold,
            )
        )

    def test_notice_attributes_cover_exact_byte_canonical_set(self):
        paths = self._byte_canonical_notice_paths()
        optional = (
            *TEXT_NORMALIZED_DELIVERY_PATHS,
            "docs/compliance/notices/NOTICE_DELIVERY_CONSOLIDATION.md",
        )
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "source"
            new_repository(repo)
            shutil.copyfile(PROJECT_DIR / ".gitattributes", repo / ".gitattributes")
            output = git(repo, "check-attr", "text", "--", *paths, *optional)
        attrs = dict(line.split(": ", 2)[::2] for line in output.decode().splitlines())
        self.assertTrue(all(attrs[path] == "unset" for path in paths))
        self.assertTrue(all(attrs[path] == "unspecified" for path in optional))

    def test_byte_canonical_notice_worktree_matches_inventory(self):
        for item in self.inventory["delivery_artifacts"]:
            with self.subTest(path=item["path"]):
                data = (PROJECT_DIR / "Licencas" / item["path"]).read_bytes()
                self.assertEqual(len(data), item["size_bytes"])
                self.assertEqual(notice_delivery.sha256_bytes(data), item["sha256"])

    @unittest.skipUnless(os.name == "nt", "autocrlf regression is Windows-specific")
    def test_autocrlf_checkout_preserves_and_validates_canonical_notices(self):
        if shutil.which("git") is None:
            self.skipTest("Git indisponível")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Fonte de avisos"
            checkout = root / "Checkout Educação com espaços"
            new_repository(source)
            # Keep the whole legal source layout used by find_issues, with no
            # repository metadata or personal files from the host.
            from build_editions import source_inventory

            paths = tuple(
                name
                for name in source_inventory(PROJECT_DIR)
                if name.startswith(("docs/", "Licencas/")) or name == ".gitattributes"
            )
            for name in paths:
                destination = source / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(PROJECT_DIR / name, destination)

            index = source / "Licencas/THIRD_PARTY_NOTICES.txt"
            preserved = index.read_bytes()
            index.write_bytes(b"Legacy notice fixture.\n")
            git(source, "add", "--", *paths)
            commit(source, root, "legacy notice fixture")
            self.assertTrue(notice_delivery.find_issues(source))

            index.write_bytes(preserved)
            git(source, "add", "--", "Licencas/THIRD_PARTY_NOTICES.txt")
            commit(source, root, "canonical notice fixture")
            clone_with_autocrlf(source, checkout)
            for name in self._byte_canonical_notice_paths():
                data = (checkout / name).read_bytes()
                self.assertEqual(data, (PROJECT_DIR / name).read_bytes(), name)
                self.assertEqual(data, git(checkout, "show", f"HEAD:{name}"), name)
            self.assertEqual(notice_delivery.find_issues(checkout), [])

    def _temporary_project(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        shutil.copytree(self.project_root / "Licencas", root / "Licencas")
        composition_dir = root / "docs" / "compliance" / "notices"
        composition_dir.mkdir(parents=True)
        shutil.copyfile(
            notice_delivery.R2_COMPOSITION_PATH,
            composition_dir / "NOTICE_BASELINE.json",
        )
        inventory_dir = root / "docs" / "compliance" / "notices"
        inventory_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            notice_delivery.INVENTORY_PATH,
            inventory_dir / "NOTICE_DELIVERY_INVENTORY.json",
        )
        deno_dir = root / "docs" / "compliance" / "deno"
        deno_dir.mkdir(parents=True)
        shutil.copyfile(
            self.project_root
            / "docs"
            / "compliance"
            / "deno"
            / "DENO_THIRD_PARTY_NOTICES.txt",
            deno_dir / "DENO_THIRD_PARTY_NOTICES.txt",
        )
        return temporary, root

    def test_current_delivery_tree_is_valid(self) -> None:
        self.assertEqual(notice_delivery.find_issues(), [])

    def test_candidate_staging_copies_only_the_exact_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = Path(temporary_dir) / "EduDownloader-Portable"
            candidate.mkdir()
            notice_delivery.stage_candidate_delivery(candidate)

            issues = notice_delivery.find_candidate_delivery_issues(candidate)
            actual = {
                path.relative_to(candidate / "Licencas").as_posix()
                for path in (candidate / "Licencas").rglob("*")
                if path.is_file()
            }

        self.assertEqual(issues, [])
        self.assertEqual(
            actual, {item["path"] for item in self.inventory["delivery_artifacts"]}
        )

    def test_candidate_delivery_fails_closed_for_missing_extra_or_changed_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = Path(temporary_dir) / "EduDownloader-Portable"
            candidate.mkdir()
            notice_delivery.stage_candidate_delivery(candidate)
            (candidate / "Licencas" / "TCL_LICENSES.txt").unlink()
            (candidate / "Licencas" / "MICROSOFT_RUNTIME_NOTICE.txt").write_text(
                "alterado", encoding="utf-8"
            )
            (candidate / "Licencas" / "INTERNAL_PROVENANCE.json").write_text(
                "{}\n", encoding="utf-8"
            )
            issues = notice_delivery.find_candidate_delivery_issues(candidate)

        self.assertIn("candidate-delivery-artifact-missing:TCL_LICENSES.txt", issues)
        self.assertIn(
            "candidate-delivery-artifact-mismatch:MICROSOFT_RUNTIME_NOTICE.txt",
            issues,
        )
        self.assertIn(
            "candidate-unexpected-license-artifact:INTERNAL_PROVENANCE.json", issues
        )

    def test_physical_delivery_does_not_erase_partial_identity_or_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = Path(temporary_dir) / "EduDownloader-Portable"
            candidate.mkdir()
            notice_delivery.stage_candidate_delivery(candidate)
            record = notice_delivery.candidate_delivery_record(candidate)

        families = {item["component"]: item for item in record["families"]}
        self.assertEqual(
            record["physical_delivery_status"], "COMPLETE_FOR_D14A_ALLOWLIST"
        )
        self.assertEqual(record["notice_identity_set"], "PARTIAL")
        self.assertEqual(families["Deno"]["notice_delivery"], "DELIVERED")
        self.assertIn("15_UPSTREAM_TEXT_GAPS", families["Deno"]["notice_identity"])
        self.assertIn(
            "ROBOTO_PRODUCER_PENDING",
            families["CustomTkinter"]["notice_identity"],
        )

    def test_corrected_license_metadata_and_freetype_credit_are_delivered(self) -> None:
        families = {item["component"]: item for item in self.inventory["families"]}
        self.assertIn(
            "runtime hooks Apache-2.0",
            families["PyInstaller and hooks"]["license_identity"],
        )
        self.assertIn(
            "cryptography Apache-2.0 OR BSD-3-Clause",
            families["cffi and cryptography closure"]["license_identity"],
        )
        self.assertIn(
            "darkdetect BSD-3-Clause",
            families["Other Python runtime packages"]["license_identity"],
        )
        index = (self.project_root / "Licencas" / "THIRD_PARTY_NOTICES.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "This software is based in part of the work of the FreeType Team.",
            index,
        )

    def test_runtime_to_notice_coverage_is_exact(self) -> None:
        composition = json.loads(
            notice_delivery.R2_COMPOSITION_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(notice_delivery._composition_issues(composition), [])
        families = {item["component"]: item for item in self.inventory["families"]}
        self.assertEqual(
            families["Microsoft Visual C++ Runtime"]["distributed_material"], []
        )
        self.assertEqual(families["Tcl"]["version"], "8.6.15.0")
        self.assertEqual(families["Tk"]["version"], "8.6.15.0")
        self.assertIn(
            "pyinstaller-hooks-contrib",
            families["PyInstaller and hooks"]["runtime_components"],
        )
        self.assertEqual(
            families["cffi and cryptography closure"]["runtime_components"],
            ["cffi", "cryptography"],
        )
        self.assertEqual(families["Pillow"]["version"], "13.0.0")
        self.assertIn("PILLOW_SBOM.cdx.json", families["Pillow"]["delivery_artifacts"])
        self.assertEqual(families["pypdfium2/PDFium"]["version"], "5.12.1")
        self.assertEqual(families["yt-dlp"]["version"], "2026.08.19")

    def test_missing_notice_fails_closed(self) -> None:
        temporary, root = self._temporary_project()
        self.addCleanup(temporary.cleanup)
        (root / "Licencas" / "TCL_LICENSES.txt").unlink()
        issues = notice_delivery.find_issues(root)
        self.assertTrue(
            any("delivery-artifact-unavailable" in issue for issue in issues), issues
        )

    def test_wrong_version_fails_closed(self) -> None:
        mutated = copy.deepcopy(self.inventory)
        microsoft = next(
            item
            for item in mutated["families"]
            if item["component"] == "Microsoft Visual C++ Runtime"
        )
        microsoft["version"] = "0.0.0.0"
        self.assertIn(
            "notice-delivery-inventory-content-mismatch",
            notice_delivery.find_issues(inventory_override=mutated),
        )

    def test_unexpected_compliance_artifact_fails_closed(self) -> None:
        temporary, root = self._temporary_project()
        self.addCleanup(temporary.cleanup)
        (root / "Licencas" / "INTERNAL_PROVENANCE.json").write_text(
            "{}\n", encoding="utf-8", newline="\n"
        )
        self.assertIn(
            "unexpected-license-artifact:INTERNAL_PROVENANCE.json",
            notice_delivery.find_issues(root),
        )

    def test_deno_spdx_and_upstream_texts_remain_distinct(self) -> None:
        self.assertEqual(notice_delivery._deno_inventory_issues(self.project_root), [])
        deno = (
            self.project_root / "Licencas" / "deno" / "DENO_THIRD_PARTY_NOTICES.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("SPDX_CANONICAL_REFERENCE_TEXT", deno)
        self.assertIn("upstream_license_text: ABSENT", deno)
        self.assertIn("upstream_license_text: PARTIAL", deno)
        family = next(
            item for item in self.inventory["families"] if item["component"] == "Deno"
        )
        self.assertEqual(family["delivery_status"], "PARTIAL_PREPARED_NOT_DELIVERED")

    def test_customtkinter_partial_is_preserved(self) -> None:
        family = next(
            item
            for item in self.inventory["families"]
            if item["component"] == "CustomTkinter"
        )
        self.assertIn("ROBOTO_PRODUCER_PENDING", family["notice_identity"])
        notice = (
            self.project_root / "Licencas" / "CUSTOMTKINTER_THIRD_PARTY_NOTICES.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("ROBOTO_PRODUCER_PENDING", notice)
        self.assertIn("Christian Robertson", notice)
        self.assertIn("https://stackoverflow.com/questions/11993290", notice)
        self.assertIn("A adaptação altera nomes", notice)

    def test_btbn_is_active_and_source_delivery_is_pending(self) -> None:
        notice = (self.project_root / "Licencas" / "FFMPEG_BTBN_NOTICE.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("Provedor ativo: BtbN/FFmpeg-Builds", notice)
        self.assertIn("LGPL-3.0-or-later", notice)
        source = (
            self.project_root / "Licencas" / "THIRD_PARTY_SOURCE_INFORMATION.txt"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "DD7DBBE3BACA3B164D73CC6C09C2200967C77E7FA25FCBAA88A1E67EAF58870E", source
        )
        self.assertIn("não afirma que o asset já foi publicado", source)
        for expected in (
            "EduDownloader-ThirdParty-Source-yt-dlp-2026.08.19.zip",
            "EduDownloader-ThirdParty-Source-Deno-2.9.5-COMPLETE.zip",
            "EduDownloader-ThirdParty-Source-FFmpeg-BtbN-autobuild-2026-08-25-13-06-COMPLETE-CANDIDATE.zip",
        ):
            self.assertIn(expected, source)

    def test_rendering_and_inventory_are_deterministic(self) -> None:
        sections = (("B", "dois  \r\n"), ("A", "um\n"))
        first = notice_delivery.render_consolidated_notice("T", sections)
        self.assertEqual(
            first, notice_delivery.render_consolidated_notice("T", sections)
        )
        self.assertNotIn(b"\r", first)
        self.assertNotIn(b"dois  \n", first)
        self.assertEqual(
            notice_delivery.canonical_json_bytes(notice_delivery.build_inventory()),
            notice_delivery.INVENTORY_PATH.read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
