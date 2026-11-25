"""Testes estruturais do pipeline de candidato Community, sem gerar build."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from validate_build_environment import (
    PILLOW_AUDITED_VERSION,
    PILLOW_AUDITED_WHEEL_TAG,
    PillowBuildEvidence,
    find_build_environment_issues,
    find_pillow_baseline_issues,
    read_exact_dependency_lock,
)
from validate_pyinstaller_warnings import (
    find_pyinstaller_warning_issues,
    read_explained_warnings,
    read_warning_baseline,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


class BuildPipelineTests(unittest.TestCase):
    def test_spec_excludes_only_packaging_residue_without_running_pyinstaller(self):
        tree = ast.parse(
            (PROJECT_DIR / "EduDownloader.spec").read_text(encoding="utf-8")
        )
        assignments = [
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute) and target.attr == "datas"
                for target in node.targets
            )
        ]
        self.assertEqual(len(assignments), 1)
        kept = [
            (name, "source", "DATA")
            for name in (
                "customtkinter/assets/themes/blue.json",
                "customtkinter/assets/fonts/Roboto/Roboto-Regular.ttf",
                "cryptography-1.dist-info/licenses/LICENSE",
            )
        ]
        removed = [
            (name, "source", "DATA")
            for name in (
                ".DS_Store",
                "customtkinter\\assets\\.ds_store",
                "cryptography-1.dist-info/sboms/sbom.json",
            )
        ]
        analysis = SimpleNamespace(datas=kept + removed)
        exec(
            compile(
                ast.Module(body=assignments, type_ignores=[]), "spec-filter", "exec"
            ),
            {"analysis": analysis},
        )
        self.assertEqual(analysis.datas, kept)

    def _pillow_evidence(
        self,
        *,
        version: str = PILLOW_AUDITED_VERSION,
        wheel_tags: frozenset[str] = frozenset({PILLOW_AUDITED_WHEEL_TAG}),
        libimagequant: bool | None = False,
    ) -> PillowBuildEvidence:
        return PillowBuildEvidence(
            version=version,
            wheel_tags=wheel_tags,
            feature_support={
                "libimagequant": libimagequant,
                "raqm": False,
                "xcb": False,
            },
        )

    def _write_warning_fixture(self, path: Path, entries: set[str]) -> None:
        lines: list[str] = []
        for entry in sorted(entries):
            kind, module = entry.split("|", maxsplit=1)
            lines.append(f"{kind} module named '{module}' - imported by exemplo")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_build_runs_pip_check_after_offline_install_and_before_pyinstaller(self):
        build = (Path(__file__).resolve().parents[1] / "build_editions.py").read_text(
            "utf-8"
        )
        self.assertLess(build.index('"offline-install"'), build.index('"pip-check"'))
        self.assertLess(build.index('"pip-check"'), build.index('"pyinstaller"'))

    def test_build_runs_fresh_process_suite_with_canonical_text_checkout(self):
        build = (Path(__file__).resolve().parents[1] / "build_editions.py").read_text(
            "utf-8"
        )
        self.assertLess(build.index('"full-suite"'), build.index('"pyinstaller"'))
        self.assertIn('"run_test_suite.py"', build)

    def test_official_build_uses_complete_exact_dependency_lock(self):
        build = (Path(__file__).resolve().parents[1] / "build_editions.py").read_text(
            "utf-8"
        )
        self.assertIn('"requirements-build-hashes.lock"', build)
        self.assertIn('"--require-hashes"', build)
        self.assertIn('"--no-index"', build)

    def test_build_validates_tracked_wheel_integrity_baseline(self):
        build = (Path(__file__).resolve().parents[1] / "build_editions.py").read_text(
            "utf-8"
        )
        self.assertIn('"validate_python_wheels.py"', build)
        self.assertIn('"docs/compliance/python/PYTHON_WHEEL_PROVENANCE.json"', build)
        self.assertLess(build.index('"wheel-integrity"'), build.index('"pyinstaller"'))

    def test_candidate_build_uses_fresh_isolated_paths_without_old_dist(self):
        build = (Path(__file__).resolve().parents[1] / "build_editions.py").read_text(
            "utf-8"
        )
        self.assertIn("tempfile.mkdtemp(", build)
        self.assertIn('run_root / "dist"', build)
        self.assertNotIn("rmtree(", build)

    def test_candidate_build_blocks_network_fallback_and_requires_wheelhouse(self):
        build = (Path(__file__).resolve().parents[1] / "build_editions.py").read_text(
            "utf-8"
        )
        self.assertIn('inputs_root / "build-compliance-wheels/wheelhouse"', build)
        self.assertIn('"PIP_NO_INDEX": "1"', build)

    def test_candidate_build_records_pristine_composition_without_release(self):
        build = (Path(__file__).resolve().parents[1] / "build_editions.py").read_text(
            "utf-8"
        )
        self.assertIn('"composition.json"', build)
        self.assertIn('"source_inputs": inputs', build)
        self.assertIn("if inputs != source_inventory(ROOT):", build)
        self.assertNotIn("gh release", build)

    def test_r3_pipeline_stages_only_the_notice_delivery_allowlist(self):
        build = (Path(__file__).resolve().parents[1] / "build_editions.py").read_text(
            "utf-8"
        )
        self.assertIn(
            '[python, "notice_delivery.py", "stage", "--candidate", output]', build
        )
        self.assertLess(
            build.index('"notices-delivery"'), build.index('"edition-guard"')
        )

    def test_spec_excludes_ds_store_from_future_candidate(self) -> None:
        specification = (PROJECT_DIR / "EduDownloader.spec").read_text(encoding="utf-8")

        self.assertIn('".ds_store"', specification.casefold())
        self.assertIn("analysis.datas =", specification)

    def test_current_environment_lock_is_exact_and_complete(self) -> None:
        lock_path = PROJECT_DIR / "requirements-build.lock"
        locked, issues = read_exact_dependency_lock(lock_path)

        self.assertEqual(issues, [])
        self.assertEqual(
            find_build_environment_issues(lock_path, installed=locked),
            [],
        )

    def test_environment_validator_rejects_missing_changed_and_extra_packages(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lock_path = Path(temporary_dir) / "requirements-build.lock"
            lock_path.write_text(
                "Package_A==1.0\npackage-b==2.0\n",
                encoding="utf-8",
            )
            installed = {
                "package-a": "9.0",
                "unexpected_package": "3.0",
            }

            issues = find_build_environment_issues(
                lock_path,
                installed=installed,
            )

        self.assertTrue(any("package-a" in issue for issue in issues))
        self.assertTrue(any("package-b" in issue for issue in issues))
        self.assertTrue(any("unexpected-package" in issue for issue in issues))

    def test_pillow_audited_baseline_is_accepted(self) -> None:
        self.assertEqual(
            find_pillow_baseline_issues(self._pillow_evidence()),
            [],
        )

    def test_pillow_libimagequant_enabled_is_rejected(self) -> None:
        issues = find_pillow_baseline_issues(self._pillow_evidence(libimagequant=True))

        self.assertIn(
            "Pillow libimagequant support differs from the audited baseline; "
            "third-party compliance review required.",
            issues,
        )

    def test_pillow_libimagequant_unknown_fails_closed(self) -> None:
        issues = find_pillow_baseline_issues(self._pillow_evidence(libimagequant=None))

        self.assertTrue(
            any(
                "Não foi possível verificar a feature Pillow libimagequant" in issue
                for issue in issues
            )
        )

    def test_pillow_version_and_wheel_tag_are_part_of_the_baseline(self) -> None:
        issues = find_pillow_baseline_issues(
            self._pillow_evidence(version="12.3.0", wheel_tags=frozenset())
        )

        self.assertTrue(any("Versão do Pillow" in issue for issue in issues))
        self.assertTrue(any("Wheel do Pillow" in issue for issue in issues))

    def test_warning_baseline_matches_known_entries(self) -> None:
        baseline_path = PROJECT_DIR / "pyinstaller-warnings-baseline.txt"
        baseline, baseline_issues = read_warning_baseline(baseline_path)
        with tempfile.TemporaryDirectory() as temporary_dir:
            warnings_path = Path(temporary_dir) / "warnings.txt"
            self._write_warning_fixture(warnings_path, baseline)
            issues = find_pyinstaller_warning_issues(warnings_path, baseline_path)

        self.assertEqual(baseline_issues, [])
        self.assertIn("missing|collections.abc", baseline)
        self.assertEqual(issues, [])

    def test_warning_validator_rejects_new_and_missing_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            baseline_path = root / "baseline.txt"
            warnings_path = root / "warnings.txt"
            baseline_path.write_text(
                "missing|known_module\nmissing|resolved_module\n",
                encoding="utf-8",
            )
            self._write_warning_fixture(
                warnings_path,
                {"missing|known_module", "missing|new_module"},
            )

            issues = find_pyinstaller_warning_issues(warnings_path, baseline_path)

        self.assertTrue(any("new_module" in issue for issue in issues))
        self.assertTrue(any("resolved_module" in issue for issue in issues))

    def test_explained_warnings_are_separate_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            baseline_path = root / "baseline.txt"
            explained_path = root / "explained.txt"
            warnings_path = root / "warnings.txt"
            baseline_path.write_text("missing|known_module\n", encoding="utf-8")
            explained_path.write_text(
                "missing|optional_module|delayed optional import\n",
                encoding="utf-8",
            )
            self._write_warning_fixture(
                warnings_path,
                {"missing|known_module", "missing|optional_module"},
            )

            explained, explained_issues = read_explained_warnings(explained_path)
            issues = find_pyinstaller_warning_issues(
                warnings_path,
                baseline_path,
                explained_path,
            )

        self.assertEqual(explained_issues, [])
        self.assertEqual(
            explained["missing|optional_module"], "delayed optional import"
        )
        self.assertEqual(issues, [])

    def test_missing_explained_warning_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            baseline_path = root / "baseline.txt"
            explained_path = root / "explained.txt"
            warnings_path = root / "warnings.txt"
            baseline_path.write_text("missing|known_module\n", encoding="utf-8")
            explained_path.write_text(
                "missing|optional_module|delayed optional import\n",
                encoding="utf-8",
            )
            self._write_warning_fixture(warnings_path, {"missing|known_module"})

            issues = find_pyinstaller_warning_issues(
                warnings_path,
                baseline_path,
                explained_path,
            )

        self.assertTrue(any("optional_module" in issue for issue in issues))

    def test_warning_validator_rejects_forbidden_private_or_test_modules(self) -> None:
        for module in ("activation_issuer.keys", "tests.fixtures"):
            with (
                self.subTest(module=module),
                tempfile.TemporaryDirectory() as temporary_dir,
            ):
                root = Path(temporary_dir)
                baseline_path = root / "baseline.txt"
                warnings_path = root / "warnings.txt"
                entry = f"missing|{module}"
                baseline_path.write_text(f"{entry}\n", encoding="utf-8")
                self._write_warning_fixture(warnings_path, {entry})

                issues = find_pyinstaller_warning_issues(
                    warnings_path,
                    baseline_path,
                )

            self.assertTrue(any("Módulo proibido" in issue for issue in issues))

    def test_build_validates_pyinstaller_warnings_before_inventory(self):
        build = (Path(__file__).resolve().parents[1] / "build_editions.py").read_text(
            "utf-8"
        )
        self.assertLess(
            build.index('"warnings"'), build.index('"distribution": inventory(')
        )
        self.assertIn('"pyinstaller-warnings-baseline.txt"', build)


if __name__ == "__main__":
    unittest.main()
