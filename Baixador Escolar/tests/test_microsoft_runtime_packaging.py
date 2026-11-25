"""Offline regression tests for controlled Microsoft runtime packaging."""

from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path

import microsoft_runtime_packaging as runtime


PROJECT_DIR = Path(__file__).resolve().parents[1]


class MicrosoftRuntimePackagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = runtime.load_manifest()

    def _signature(self, path: Path) -> dict[str, str]:
        record = next(
            item
            for item in self.manifest["runtime_files"]
            if item["filename"].casefold() == path.name.casefold()
        )
        return {
            "status": "Valid",
            "publisher": record["authenticode"]["publisher"],
            "thumbprint": record["authenticode"]["thumbprint"],
            "version": record["version"],
        }

    def test_manifest_is_canonical_and_pins_official_x64_runtime(self) -> None:
        path = runtime.DEFAULT_MANIFEST
        self.assertEqual(path.read_bytes(), runtime.canonical_json_bytes(self.manifest))
        self.assertEqual(runtime.validate_manifest(self.manifest), [])
        self.assertEqual(
            {item["filename"].casefold() for item in self.manifest["runtime_files"]},
            runtime.EXPECTED_RUNTIME_FILES,
        )
        self.assertEqual(
            self.manifest["baseline"]["supported_windows"],
            "WINDOWS_10_OR_NEWER_X64",
        )

    def test_manifest_rejects_version_below_minimum(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["vc_runtime_authority"]["version"] = "14.42.34438.0"
        for item in manifest["runtime_files"]:
            item["version"] = "14.42.34438.0"
        self.assertIn(
            "microsoft-runtime-version-below-minimum",
            runtime.validate_manifest(manifest),
        )

    def test_manifest_rejects_non_x64_and_invalid_signature_metadata(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["runtime_files"][0]["architecture"] = "x86"
        manifest["runtime_files"][0]["authenticode"]["status"] = "INVALID"
        issues = runtime.validate_manifest(manifest)
        self.assertIn("microsoft-runtime-file-architecture-mismatch", issues)
        self.assertIn("microsoft-runtime-file-signature-not-valid", issues)

    def test_isolated_path_does_not_inherit_unrelated_global_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            old_path = os.environ.get("PATH")
            os.environ["PATH"] = os.pathsep.join(
                (str(root / "libheif" / "bin"), str(root / "unrelated"))
            )
            try:
                result = runtime.isolated_search_path(
                    root / "project", root / "runtime", system_root=root / "Windows"
                )
            finally:
                if old_path is None:
                    os.environ.pop("PATH", None)
                else:
                    os.environ["PATH"] = old_path
        self.assertNotIn("libheif", result.casefold())
        self.assertNotIn("unrelated", result.casefold())
        self.assertIn(str(root / "runtime"), result)

    def test_analysis_rejects_libheif_ucrt_and_unrelated_dll_origins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            project = root / "project"
            runtime_root = project / "runtime"
            unrelated = root / "libheif" / "bin"
            runtime_root.mkdir(parents=True)
            unrelated.mkdir(parents=True)
            toc = root / "Analysis-00.toc"
            toc.write_text(
                repr(
                    (
                        [],
                        [
                            (
                                "api-ms-win-crt-runtime-l1-1-0.dll",
                                str(unrelated / "api-ms-win-crt-runtime-l1-1-0.dll"),
                                "BINARY",
                            ),
                            ("ucrtbase.dll", str(unrelated / "ucrtbase.dll"), "BINARY"),
                        ],
                    )
                ),
                encoding="utf-8",
            )
            issues = runtime.validate_analysis_toc(
                toc,
                self.manifest,
                runtime_root=runtime_root,
                allowed_roots=(project,),
            )
        self.assertTrue(any("libheif-contamination" in item for item in issues))
        self.assertTrue(any("system-runtime-bundled" in item for item in issues))
        self.assertTrue(any("unallowed-dll-origin" in item for item in issues))

    def test_analysis_rejects_vcruntime_from_cpython_or_wrong_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            project = root / "project"
            runtime_root = project / "runtime"
            python_root = root / "python"
            runtime_root.mkdir(parents=True)
            python_root.mkdir()
            toc = root / "Analysis-00.toc"
            entries = []
            for record in self.manifest["runtime_files"]:
                source = python_root / record["filename"]
                source.write_bytes(b"wrong")
                entries.append((record["filename"], str(source), "BINARY"))
            toc.write_text(repr(([], entries)), encoding="utf-8")
            issues = runtime.validate_analysis_toc(
                toc,
                self.manifest,
                runtime_root=runtime_root,
                allowed_roots=(project, python_root),
            )
        self.assertTrue(any("unpinned-origin" in item for item in issues))

    def test_analysis_rejects_duplicate_or_unplanned_runtime_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            runtime_root = root / "runtime"
            runtime_root.mkdir()
            entries = []
            for record in self.manifest["runtime_files"]:
                path = runtime_root / record["filename"]
                path.write_bytes(b"fixture")
                entries.append((record["filename"], str(path), "BINARY"))
            entries.append(
                ("msvcp140.dll", str(runtime_root / "msvcp140.dll"), "BINARY")
            )
            entries.append(
                ("VCRUNTIME140.dll", str(runtime_root / "copy.dll"), "BINARY")
            )
            toc = root / "Analysis-00.toc"
            toc.write_text(repr((entries,)), encoding="utf-8")
            issues = runtime.validate_analysis_toc(
                toc,
                self.manifest,
                runtime_root=runtime_root,
                allowed_roots=(runtime_root,),
            )
        self.assertTrue(any("unplanned-family:msvcp140.dll" in item for item in issues))
        self.assertTrue(
            any("required-count:vcruntime140.dll" in item for item in issues)
        )

    def test_analysis_deduplicates_identical_serialized_toc_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            runtime_root = root / "runtime"
            runtime_root.mkdir()
            manifest = copy.deepcopy(self.manifest)
            entries = []
            for record in manifest["runtime_files"]:
                path = runtime_root / record["filename"]
                path.write_bytes(b"fixture")
                record["sha256"] = runtime.sha256_file(path)
                entries.append((record["filename"], str(path), "BINARY"))
            toc = root / "Analysis-00.toc"
            toc.write_text(repr((entries, entries)), encoding="utf-8")

            issues = runtime.validate_analysis_toc(
                toc,
                manifest,
                runtime_root=runtime_root,
                allowed_roots=(runtime_root,),
            )

        self.assertEqual(issues, [])

    def test_candidate_rejects_application_local_ucrt_and_api_sets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = Path(temporary_dir)
            internal = candidate / "_internal"
            internal.mkdir()
            (internal / "ucrtbase.dll").write_bytes(b"fixture")
            (internal / "api-ms-win-core-file-l1-1-0.dll").write_bytes(b"fixture")
            issues = runtime.validate_candidate_runtime(
                candidate,
                self.manifest,
                signature_probe=self._signature,
            )
        self.assertTrue(
            any("system-runtime-bundled:ucrtbase.dll" in item for item in issues)
        )
        self.assertTrue(any("api-ms-win-core" in item for item in issues))

    def test_runtime_file_signature_probe_fails_closed(self) -> None:
        record = self.manifest["runtime_files"][0]
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / record["filename"]
            path.write_bytes(b"not-a-pe")
            issues = runtime._validate_runtime_file(
                path,
                record,
                lambda _path: {
                    "status": "HashMismatch",
                    "publisher": "Unknown",
                    "thumbprint": "0" * 40,
                    "version": record["version"],
                },
            )
        self.assertTrue(any("signature-not-valid" in item for item in issues))
        self.assertTrue(any("signer-thumbprint-mismatch" in item for item in issues))
        self.assertTrue(any("architecture-mismatch" in item for item in issues))

    def test_external_policy_rejects_direct_runtime_files(self) -> None:
        policy = runtime.load_manifest(runtime.EXTERNAL_POLICY_MANIFEST)
        self.assertEqual(runtime.validate_manifest(policy), [])
        self.assertEqual(
            runtime.canonical_json_bytes(policy),
            runtime.EXTERNAL_POLICY_MANIFEST.read_bytes(),
        )
        changed = copy.deepcopy(policy)
        changed["runtime_files"] = [{"filename": "VCRUNTIME140.dll"}]
        self.assertIn(
            "microsoft-external-policy-direct-files-present",
            runtime.validate_manifest(changed),
        )

    def test_external_candidate_rejects_direct_files_but_not_embedded_names(
        self,
    ) -> None:
        policy = runtime.load_manifest(runtime.EXTERNAL_POLICY_MANIFEST)
        with tempfile.TemporaryDirectory() as temporary_dir:
            candidate = Path(temporary_dir)
            internal = candidate / "_internal"
            internal.mkdir()
            (candidate / "yt-dlp.exe").write_bytes(b"VCRUNTIME140.dll")
            self.assertEqual(runtime.validate_candidate_runtime(candidate, policy), [])
            direct = internal / "vCrUnTiMe140_1.DLL"
            direct.write_bytes(b"fixture")
            self.assertIn(
                "microsoft-external-candidate-direct-file-forbidden:_internal/"
                "vCrUnTiMe140_1.DLL",
                runtime.validate_candidate_runtime(candidate, policy),
            )

    def test_external_analysis_allows_auto_dependency_but_rejects_other_family(
        self,
    ) -> None:
        policy = runtime.load_manifest(runtime.EXTERNAL_POLICY_MANIFEST)
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            toc = root / "Analysis-00.toc"
            toc.write_text(
                repr(
                    (
                        [
                            (
                                "VCRUNTIME140.dll",
                                str(root / "VCRUNTIME140.dll"),
                                "BINARY",
                            ),
                            ("msvcp140.dll", str(root / "msvcp140.dll"), "BINARY"),
                        ],
                    )
                ),
                encoding="utf-8",
            )
            issues = runtime.validate_analysis_toc(toc, policy, allowed_roots=(root,))
        self.assertIn(
            "microsoft-runtime-analysis-unplanned-family:msvcp140.dll",
            issues,
        )
        self.assertNotIn(
            "microsoft-runtime-analysis-unplanned-family:vcruntime140.dll", issues
        )

    def test_build_pipeline_checks_external_policy_for_build_and_candidate(self):
        build = (PROJECT_DIR / "build_editions.py").read_text("utf-8")
        pyinstaller = (PROJECT_DIR / "build_pyinstaller.py").read_text("utf-8")
        self.assertIn('"--microsoft-runtime-manifest"', build)
        self.assertIn(
            '"docs/compliance/microsoft/MICROSOFT_EXTERNAL_RUNTIME_POLICY.json"', build
        )
        self.assertLess(
            build.index('"pyinstaller",'), build.index('"validate-candidate",')
        )
        self.assertLess(
            pyinstaller.index("validate_manifest(manifest)"),
            pyinstaller.index("run_pyinstaller(pyinstaller_arguments)"),
        )

    def test_spec_does_not_inject_microsoft_runtime(self) -> None:
        specification = (PROJECT_DIR / "EduDownloader.spec").read_text(encoding="utf-8")
        self.assertIn("binaries=[]", specification)
        self.assertNotIn("microsoft_runtime_binaries", specification)
        self.assertIn("analysis.binaries = [", specification)
        self.assertIn("external_runtime_names", specification)
        self.assertNotIn("ucrtbase.dll", specification.casefold())

    def test_notice_model_remains_pending_p3(self) -> None:
        notice = (
            PROJECT_DIR
            / "docs"
            / "compliance"
            / "microsoft"
            / "MICROSOFT_RUNTIME_NOTICE_TEMPLATE.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("P3_PENDING_REVIEW", notice)
        self.assertIn("não declara LEGAL_APPROVED", notice)


if __name__ == "__main__":
    unittest.main()
