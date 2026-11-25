"""Reproduced Goal 6.5 regressions; all input and output paths are synthetic."""

import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_editions
import ocr_component_delivery as delivery
from validate_edition_distribution import payload_issues
from settings import default_settings, load_settings, save_settings


class PreferencePreservationTests(unittest.TestCase):
    def test_failed_read_never_replaces_existing_preferences_or_allows_session_save(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = json.dumps({**default_settings(), "tema": "escuro"}).encode()
            path.write_bytes(original)
            normal_open = Path.open

            def denied_read(target, mode="r", *args, **kwargs):
                if target == path and "r" in mode:
                    raise PermissionError("synthetic read failure")
                return normal_open(target, mode, *args, **kwargs)

            with patch.object(Path, "open", denied_read):
                loaded = load_settings(path)
            self.assertEqual(loaded, default_settings())
            self.assertEqual(path.read_bytes(), original)
            loaded["tema"] = "claro"
            with self.assertRaises(OSError):
                save_settings(loaded, path)
            with self.assertRaises(OSError):
                save_settings(loaded.copy(), path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])
            # A successful reload starts a normal writable session.
            reloaded = load_settings(path)
            reloaded["ultima_qualidade"] = "720p"
            self.assertEqual(save_settings(reloaded, path)["ultima_qualidade"], "720p")

    def test_malformed_json_and_encoding_preserve_original_on_load_and_later_save(self):
        for original in (b'{"tema":"escuro",', b"\xff\xfe\x00", b"[]"):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "settings.json"
                path.write_bytes(original)
                loaded = load_settings(path)
                self.assertEqual(loaded, default_settings())
                self.assertEqual(path.read_bytes(), original)
                with self.assertRaises(OSError):
                    save_settings(loaded, path)
                self.assertEqual(path.read_bytes(), original)


class BuildOcrDeliveryTests(unittest.TestCase):
    def fixture(self, root):
        project, candidate = root / "project", root / "candidate"
        component = project / "Componentes/OCR-Community"
        candidate.mkdir()
        policy = json.loads(
            (
                Path(build_editions.__file__).parent
                / "docs/windows/OCR_COMMUNITY_DELIVERY_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        for name, item in policy["files"].items():
            data = ("synthetic: " + name).encode()
            path = component / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            item.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        source_manifest = project / "ocr_community_sources.json"
        source_manifest.write_bytes(b"synthetic source manifest")
        policy["source_manifest_sha256"] = hashlib.sha256(
            source_manifest.read_bytes()
        ).hexdigest()
        manifest = project / "docs/windows/OCR_COMMUNITY_DELIVERY_MANIFEST.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(policy), encoding="utf-8")
        engine = policy["files"]["tesseract.exe"]["sha256"]
        models = {
            key: policy["files"][f"tessdata_{key[0]}/{key[1]}.traineddata"]["sha256"]
            for key in delivery.MODEL_SHA256
        }
        self.enterContext(patch.object(delivery, "COMMUNITY_ENGINE_SHA256", engine))
        self.enterContext(patch.object(delivery, "MODEL_SHA256", models))
        return project, candidate, policy

    def test_delivers_only_verified_allowlist_and_never_replaces_existing_component(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            project, candidate, policy = self.fixture(Path(directory))
            (project / "Componentes/OCR-Community/not-for-delivery.txt").write_bytes(
                b"synthetic unrelated state"
            )
            target = delivery.stage_ocr_component(project, candidate)
            self.assertEqual(
                {
                    p.relative_to(target).as_posix()
                    for p in target.rglob("*")
                    if p.is_file()
                },
                set(policy["files"]),
            )
            for name, expected in policy["files"].items():
                self.assertEqual(
                    hashlib.sha256((target / name).read_bytes()).hexdigest(),
                    expected["sha256"],
                )
            with self.assertRaises(FileExistsError):
                delivery.stage_ocr_component(project, candidate)

    def test_missing_or_corrupt_engine_model_and_license_fail_before_delivery(self):
        for name in (
            "tesseract.exe",
            "tessdata_fast/por.traineddata",
            "Licenses/Tesseract-Apache-2.0.txt",
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                project, candidate, _ = self.fixture(Path(directory))
                path = project / "Componentes/OCR-Community" / name
                path.write_bytes(b"corrupt")
                with self.assertRaises(RuntimeError):
                    delivery.stage_ocr_component(project, candidate)
                self.assertEqual(list(candidate.iterdir()), [])

    def test_copy_mutation_never_publishes_partial_or_unverified_component(self):
        with tempfile.TemporaryDirectory() as directory:
            project, candidate, _ = self.fixture(Path(directory))
            original = delivery.shutil.copyfile

            def changed(source, target):
                result = original(source, target)
                if Path(target).name == "tesseract.exe":
                    Path(target).write_bytes(b"changed during copy")
                return result

            with (
                patch.object(delivery.shutil, "copyfile", changed),
                self.assertRaises(RuntimeError),
            ):
                delivery.stage_ocr_component(project, candidate)
            self.assertEqual(list(candidate.iterdir()), [])

    def test_publication_race_preserves_competing_component(self):
        with tempfile.TemporaryDirectory() as directory:
            project, candidate, _ = self.fixture(Path(directory))
            original = delivery.os.rename

            def competing(source, target):
                Path(target).mkdir()
                (Path(target) / "previous.txt").write_bytes(b"concurrent owned fixture")
                return original(source, target)

            with (
                patch.object(delivery.os, "rename", competing),
                self.assertRaises(FileExistsError),
            ):
                delivery.stage_ocr_component(project, candidate)
            self.assertEqual(
                (candidate / "Componentes/OCR/previous.txt").read_bytes(),
                b"concurrent owned fixture",
            )
            self.assertFalse(list(candidate.glob(".ocr-delivery-*")))

    def test_ocr_gate_requires_exact_bytes_path_and_complete_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            project, candidate, policy = self.fixture(Path(directory))
            target = delivery.stage_ocr_component(project, candidate)
            with patch.object(delivery, "_policy", return_value=policy["files"]):
                self.assertTrue(delivery.approved_ocr_tree(candidate / "Componentes"))
                data = (target / "tesseract.exe").read_bytes()
                name = "Componentes/OCR/tesseract.exe"
                self.assertEqual(payload_issues(name, data), [])
                self.assertTrue(payload_issues(name, data + b"changed"))
                self.assertTrue(payload_issues("other/tesseract.exe", data))
                (target / "unexpected.dat").write_bytes(b"unrelated synthetic state")
                self.assertFalse(delivery.approved_ocr_tree(candidate / "Componentes"))
                (target / "unexpected.dat").unlink()
                (target / "tessdata_fast/por.traineddata").unlink()
                self.assertFalse(delivery.approved_ocr_tree(candidate / "Componentes"))

    def test_ocr_exception_never_suppresses_private_key_payload_checks(self):
        name = "Componentes/OCR/tesseract.exe"
        data = b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"A" * 64
        with patch(
            "validate_edition_distribution.approved_ocr_file", return_value=True
        ):
            self.assertIn("private-key-payload:" + name, payload_issues(name, data))

    def test_missing_license_in_policy_is_not_a_valid_component(self):
        with tempfile.TemporaryDirectory() as directory:
            project, candidate, policy = self.fixture(Path(directory))
            del policy["files"]["Licenses/Leptonica-BSD.txt"]
            path = project / "docs/windows/OCR_COMMUNITY_DELIVERY_MANIFEST.json"
            path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                delivery.stage_ocr_component(project, candidate)
            self.assertEqual(list(candidate.iterdir()), [])

    def test_edition_pipeline_delivers_verified_ocr_before_distribution_gates(self):
        source = Path(build_editions.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "stage_ocr_component"
        ]
        self.assertEqual(len(calls), 1, "Both edition builds must deliver pinned OCR")
        self.assertTrue(callable(getattr(build_editions, "stage_ocr_component", None)))


if __name__ == "__main__":
    unittest.main()
