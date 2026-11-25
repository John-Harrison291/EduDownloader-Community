"""Internal build composition, activation boundaries and negative artifact gates."""

from __future__ import annotations

import ast
import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
import zipfile

from constants import ProductEdition
from edition_profiles import select_build_profile
from edition_staging import (
    COMPONENT_SOURCES,
    SHARED_SOURCES,
    EXCLUDED_MODULES,
    stage_sources,
)
from validate_edition_distribution import (
    collected_toc_issues,
    embedded_zip_issues,
    matching_code,
    module_issues,
    payload_issues,
    UPSTREAM_PATH_BINARIES,
    zip_issues,
)


ROOT = Path(__file__).resolve().parents[1]


class EditionBuildTests(unittest.TestCase):
    def test_staged_specs_compile_with_one_version_and_complete_shared_imports(self):
        source = (ROOT / "EduDownloader.spec").read_text("utf-8")
        for edition in ProductEdition:
            staged = source
            compile(staged, "isolated-edition.spec", "exec")
            tree = ast.parse(staged)
            exe = next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "EXE"
            )
            self.assertEqual(sum(k.arg == "version" for k in exe.keywords), 1)
        # Follow local runtime imports, including modules added in Goals 2–5.5.
        pending = ["frozen_community"]
        seen = set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            tree = ast.parse((ROOT / (name + ".py")).read_text("utf-8-sig"))
            for node in ast.walk(tree):
                imports = (
                    [a.name.split(".")[0] for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module.split(".")[0]]
                    if isinstance(node, ast.ImportFrom)
                    and node.module
                    and node.level == 0
                    else []
                )
                pending.extend(
                    n
                    for n in imports
                    if (ROOT / (n + ".py")).is_file() and n not in seen
                )
        expected = seen - {"frozen_community"}
        self.assertLessEqual(expected, set(SHARED_SOURCES) | set(COMPONENT_SOURCES))

    def test_edition_metadata_has_no_certified_publisher_by_default(self):
        for edition in ProductEdition:
            with tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / "source"
                stage_sources(ROOT, target, select_build_profile(edition.value))
                metadata = (target / "version_info.txt").read_text("utf-8")
                profile = select_build_profile(edition.value)
                expected_name = "EduDownloader"
                self.assertIn(f"'FileDescription', '{expected_name}'", metadata)
                self.assertIn(profile.app_version, metadata)
                self.assertIn("CompanyName", metadata)
                self.assertNotIn(
                    "windows_signing.py", {p.name for p in target.iterdir()}
                )

    def test_upstream_path_exception_is_exact_bytes_and_path_only(self):
        import hashlib

        vendor = b"C:\\Users\\fixture-ci\\build"
        with patch.dict(
            UPSTREAM_PATH_BINARIES, {"vendor.dll": hashlib.sha256(vendor).hexdigest()}
        ):
            self.assertEqual(payload_issues("vendor.dll", vendor), [])
            self.assertTrue(payload_issues("other.dll", vendor))
            self.assertTrue(payload_issues("vendor.dll", vendor + b"changed"))
        secret = vendor + b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"A" * 64
        with patch.dict(
            UPSTREAM_PATH_BINARIES, {"vendor.dll": hashlib.sha256(secret).hexdigest()}
        ):
            self.assertIn(
                "private-key-payload:vendor.dll", payload_issues("vendor.dll", secret)
            )

    def test_toc_inspects_collected_files_not_exclusion_configuration(self):
        self.assertEqual(
            collected_toc_issues(
                (
                    ["license_manager", "activation_issuer"],
                    [("app", "source/app.py", "PYMODULE")],
                )
            ),
            [],
        )
        self.assertTrue(
            collected_toc_issues(
                [("innocent", "source/license_manager/keys.py", "DATA")]
            )
        )

    def test_embedded_zip_payload_inspection_finds_secret_under_innocent_name(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "innocent.txt", b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"A" * 64
            )
        self.assertTrue(embedded_zip_issues("base_library.zip", data.getvalue()))

    def test_staging_is_allowlisted_static_and_keeps_source_unchanged(self):
        original = (ROOT / "constants.py").read_bytes()
        for edition in ProductEdition:
            profile = select_build_profile(edition)
            with tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / "source"
                stage_sources(ROOT, target, profile)
                files = {
                    p.relative_to(target).as_posix()
                    for p in target.rglob("*")
                    if p.is_file()
                }
                self.assertNotIn("bootstrap.py", files)
                self.assertNotIn("main.py", files)
                self.assertNotIn("license_manager/v2_signing.py", files)
                self.assertNotIn("commercial_activation.py", files)
                self.assertFalse(any(name.startswith("licensing/") for name in files))
                self.assertNotIn("licensing/service.py", files)
                self.assertEqual(
                    (target / "ui_events.py").read_bytes(),
                    (ROOT / "ui_events.py").read_bytes(),
                )
                identity = target.joinpath("constants.py").read_text("utf-8")
                self.assertIn(
                    f"PRODUCT_EDITION: Final = ProductEdition.{edition.name}", identity
                )
                with self.assertRaises(FileExistsError):
                    stage_sources(ROOT, target, profile)
        self.assertEqual(original, (ROOT / "constants.py").read_bytes())

    def test_unknown_and_missing_profiles_fail_before_side_effects(self):
        for args in ([], ["COMMUNITY"], ["unknown"]):
            with tempfile.TemporaryDirectory() as temp:
                result = subprocess.run(
                    [sys.executable, str(ROOT / "build_editions.py"), *args],
                    cwd=temp,
                    capture_output=True,
                    timeout=15,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_spec_preserves_icon_datas_runtime_policy_and_private_exclusions(self):
        source = (ROOT / "EduDownloader.spec").read_text("utf-8")
        for edition in ProductEdition:
            profile = select_build_profile(edition)
            staged = source
            tree = ast.parse(staged)
            analysis = next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "Analysis"
            )
            self.assertEqual(ast.literal_eval(analysis.args[0]), [profile.entrypoint])
            keywords = {k.arg: k.value for k in analysis.keywords}
            self.assertTrue(
                set(EXCLUDED_MODULES) <= set(ast.literal_eval(keywords["excludes"]))
            )
            self.assertIn("edudownloader-symbol.ico", staged)
            self.assertIn("vcruntime140.dll", staged)
            self.assertIn("version_info.txt", staged)

    def test_code_comparison_accepts_only_exact_semantics_not_paths(self):
        source = (ROOT / "constants.py").read_text("utf-8")
        self.assertTrue(
            matching_code(
                compile(source, "other/constants.py", "exec", dont_inherit=True),
                source,
                "constants.py",
            )
        )
        changed = source.replace("3.0.0", "9.0.0")
        self.assertFalse(
            matching_code(
                compile(changed, "constants.py", "exec"), source, "constants.py"
            )
        )

    def test_community_entrypoint_has_no_activation_imports_even_fresh(self):
        code = "import sys; import frozen_community; print([m for m in sys.modules if m.startswith(('commercial_activation','licensing.v2','licensing.device','licensing.storage','activation_ui','license_manager'))])"
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "[]")

    def test_frozen_community_handles_maintenance_without_opening_ui(self):
        import frozen_community as entry

        with (
            patch.object(sys, "argv", ["EduDownloader.exe"]),
            patch.object(entry, "run_shared_shell") as shell,
            patch(
                "installed_maintenance.command_exit", return_value=None
            ) as maintenance,
        ):
            entry.main()
            shell.assert_called_once_with()
            maintenance.assert_called_once_with([])
        with (
            patch.object(sys, "argv", ["EduDownloader.exe", "--fixture"]),
            patch.object(entry, "run_shared_shell") as shell,
            patch("installed_maintenance.command_exit", return_value=7),
            self.assertRaises(SystemExit) as error,
        ):
            entry.main()
        self.assertEqual(error.exception.code, 7)
        shell.assert_not_called()

    def test_windowed_community_accepts_font_warning_without_stderr(self):
        import frozen_community as entry

        app_factory = ModuleType("app_factory")
        display = Mock(side_effect=lambda: self.assertIsNone(sys.stderr))

        def load(name):
            if name != "run_shared_shell":
                raise AttributeError(name)
            sys.stderr.write("Font fallback\n")
            return display

        app_factory.__getattr__ = load
        with (
            patch.dict(sys.modules, {"app_factory": app_factory}),
            patch.object(sys, "stderr", None),
            patch.object(sys, "frozen", True, create=True),
            patch.object(entry, "_restore_native_shapes") as restore,
        ):
            entry.run_shared_shell()
            self.assertIsNone(sys.stderr)
        display.assert_called_once_with()
        self.assertEqual(restore.call_count, int(sys.platform == "win32"))

    @unittest.skipUnless(sys.platform == "win32", "GDI disponível no Windows")
    def test_community_restores_native_shapes_only_after_private_font_load(self):
        import frozen_community as entry
        from customtkinter.windows.widgets.core_rendering import DrawEngine

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(sys, "_MEIPASS", tmp, create=True),
            patch.object(DrawEngine, "preferred_drawing_method", "circle_shapes"),
            patch("ctypes.WinDLL") as dll,
        ):
            font = (
                Path(tmp) / "customtkinter/assets/fonts/CustomTkinter_shapes_font.otf"
            )
            font.parent.mkdir(parents=True)
            data = b"synthetic font"
            font.write_bytes(data)
            add = dll.return_value.AddFontMemResourceEx
            add.return_value = None
            entry._restore_native_shapes()
            self.assertEqual(DrawEngine.preferred_drawing_method, "circle_shapes")

            def register(buffer, size, reserved, count):
                self.assertEqual(buffer.raw[:size], data)
                self.assertIsNone(reserved)
                count._obj.value = 1
                return 1

            add.side_effect = register
            entry._restore_native_shapes()
            self.assertEqual(DrawEngine.preferred_drawing_method, "font_shapes")
            self.assertEqual(add.call_count, 2)
            entry._restore_native_shapes()
            self.assertEqual(add.call_count, 2)

    def test_module_guard_rejects_private_activation_and_abandoned_stacks(self):
        base = set(SHARED_SOURCES) - {"pyi_rth_edudownloader_tk"}
        base |= {"pypdf", "PIL", "pypdfium2"}
        self.assertEqual(
            module_issues(
                base | set(COMPONENT_SOURCES), select_build_profile("community")
            ),
            [],
        )
        for name in (
            "license_manager.v2_signing",
            "activation_issuer.keys",
            "lxml.etree",
            "docx",
            "tests.fixture",
            "commercial_activation",
            "licensing.v2_client",
        ):
            self.assertTrue(
                any(
                    i.startswith("forbidden-module:")
                    for i in module_issues(
                        base | {name}, select_build_profile("community")
                    )
                )
            )
        self.assertIn(
            "missing-module:component_catalog",
            module_issues(base, select_build_profile("community")),
        )

    def test_nested_private_artifacts_paths_and_payloads_rejected(self):
        for name in (
            "nested/key.dpapi",
            "nested/activation.dat",
            "nested/test.edulic",
            "nested/customer.sqlite3",
            "nested/tessdata/por.traineddata",
        ):
            self.assertTrue(payload_issues(name, b"synthetic"))
        synthetic = b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"A" * 64
        self.assertTrue(payload_issues("nested/innocent.bin", synthetic))
        self.assertTrue(
            payload_issues("module", b"C:\\Users\\fixture-user\\Desktop\\build")
        )
        self.assertEqual(payload_issues("module", b"public verification key"), [])

    def test_zip_must_equal_validated_tree_exactly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / select_build_profile("community").output_directory
            root.mkdir()
            root.joinpath("data.txt").write_bytes(b"synthetic")
            archive = Path(temp) / "probe.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.write(root / "data.txt", root.name + "/data.txt")
            self.assertEqual(zip_issues(archive, root), [])
            with zipfile.ZipFile(archive, "a") as z:
                z.writestr("private/admin.db", json.dumps({"synthetic": True}))
            self.assertEqual(zip_issues(archive, root), ["zip-members-mismatch"])


if __name__ == "__main__":
    unittest.main()
