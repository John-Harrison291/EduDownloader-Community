"""Testes offline do contrato fail-closed de integridade de wheels."""

from __future__ import annotations

import hashlib
import os
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.git_fixture import clone_with_autocrlf, commit, git, new_repository

from validate_python_wheels import (
    RELATIONSHIPS,
    build_manifest,
    canonical_json_bytes,
    generate_hashed_lock_text,
    inspect_wheelhouse,
    offline_install_command,
    read_hashed_lock,
    read_locked_packages,
    validate_manifest,
    wheel_inventory_sha256,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_DIR.parent
CANONICAL_ARTIFACTS = {
    "requirements-build.lock": (
        "2DAC755598C2F0810897EB701884D46064B6513C4D0B86FA5EC14289986F06B5"
    ),
    "requirements-build-hashes.lock": (
        "196D8A0743AC96CFB805D316A6836F9B4BCC3A5C7AF977DF5C6F8B2509E59669"
    ),
    "docs/compliance/python/PYTHON_WHEEL_PROVENANCE.json": (
        "2423ED1A3CC6F20CD7C70B93A9774DE61F59F9933D2D6E7CD1E7B04065447834"
    ),
}
ADJACENT_TEXT_ARTIFACTS = (
    "requirements-dev.txt",
    "requirements.txt",
    "docs/compliance/python/WHEEL_INTEGRITY_CAPTURE.md",
)


class PythonWheelIntegrityTests(unittest.TestCase):
    def _write_lock(
        self,
        root: Path,
        packages: dict[str, str],
    ) -> Path:
        path = root / "requirements-build.lock"
        path.write_text(
            "".join(f"{name}=={version}\n" for name, version in packages.items()),
            encoding="utf-8",
        )
        return path

    def _write_wheel(
        self,
        wheelhouse: Path,
        distribution: str,
        version: str,
        tag: str = "py3-none-any",
        *,
        metadata_name: str | None = None,
        native_file: str | None = None,
    ) -> Path:
        filename_distribution = distribution.replace("-", "_")
        filename = f"{filename_distribution}-{version}-{tag}.whl"
        path = wheelhouse / filename
        dist_info = f"{filename_distribution}-{version}.dist-info"
        metadata = (
            "Metadata-Version: 2.4\n"
            f"Name: {metadata_name or distribution}\n"
            f"Version: {version}\n"
            "License-Expression: MIT\n"
            "License-File: LICENSE.txt\n\n"
        )
        wheel_metadata = (
            "Wheel-Version: 1.0\n"
            "Generator: synthetic-test\n"
            "Root-Is-Purelib: true\n"
            f"Tag: {tag}\n"
        )
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"{dist_info}/METADATA", metadata)
            archive.writestr(f"{dist_info}/WHEEL", wheel_metadata)
            archive.writestr(f"{dist_info}/RECORD", "")
            archive.writestr(f"{dist_info}/LICENSE.txt", "Synthetic MIT text\n")
            archive.writestr(f"{distribution}/__init__.py", "")
            archive.writestr(
                f"{distribution}/licenses/THIRD_PARTY.txt",
                "Synthetic third-party notice\n",
            )
            archive.writestr(
                f"{distribution}/_vendor/sample-1.0.dist-info/METADATA",
                "Name: sample\nVersion: 1.0\n\n",
            )
            if native_file is not None:
                archive.writestr(native_file, b"synthetic-native-payload")
        return path

    def _two_package_fixture(
        self,
        root: Path,
    ) -> tuple[Path, Path, dict[str, object]]:
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir()
        lock_path = self._write_lock(
            root,
            {"Package_A": "1.0", "package-b": "2.0"},
        )
        self._write_wheel(wheelhouse, "Package_A", "1.0")
        self._write_wheel(
            wheelhouse,
            "package_b",
            "2.0",
            "cp314-cp314-win_amd64",
            native_file="package_b/native.pyd",
        )
        locked, issues = read_locked_packages(lock_path)
        self.assertEqual(issues, [])
        return lock_path, wheelhouse, locked

    def _complete_fixture(
        self,
        root: Path,
    ) -> tuple[Path, Path, Path, Path]:
        packages = {name: "1.0" for name in RELATIONSHIPS}
        lock_path = self._write_lock(root, packages)
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir()
        for name in packages:
            self._write_wheel(wheelhouse, name, "1.0")
        locked, lock_issues = read_locked_packages(lock_path)
        records, wheel_issues = inspect_wheelhouse(wheelhouse, locked)
        self.assertEqual(lock_issues + wheel_issues, [])

        hashed_lock_text = generate_hashed_lock_text(records)
        hashed_lock_path = root / "requirements-build-hashes.lock"
        hashed_lock_path.write_bytes(hashed_lock_text.encode("utf-8"))
        manifest = build_manifest(
            lock_path,
            records,
            hashed_lock_text,
            proof_complete=True,
            recorded_on="2026-09-01",
        )
        manifest_path = root / "PYTHON_WHEEL_PROVENANCE.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        return lock_path, hashed_lock_path, manifest_path, wheelhouse

    def test_exact_wheel_set_normalization_metadata_and_native_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _lock_path, wheelhouse, locked = self._two_package_fixture(root)

            records, issues = inspect_wheelhouse(wheelhouse, locked)

        self.assertEqual(issues, [])
        self.assertEqual(
            [record["distribution"] for record in records],
            ["package-a", "package-b"],
        )
        self.assertFalse(records[0]["native_payload_present"])
        self.assertTrue(records[1]["native_payload_present"])
        self.assertEqual(records[1]["native_payload_files"], ["package_b/native.pyd"])
        self.assertEqual(records[0]["declared_license"], "MIT")
        self.assertEqual(len(records[0]["license_files"]), 2)

    def test_lock_rejects_unpinned_and_duplicate_normalized_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            lock_path = Path(temporary_dir) / "requirements-build.lock"
            lock_path.write_text(
                "Package_A==1.0\npackage-a==1.0\nunpinned>=2\n",
                encoding="utf-8",
            )

            _locked, issues = read_locked_packages(lock_path)

        self.assertTrue(any("duplicada" in issue for issue in issues))
        self.assertTrue(any("não exata" in issue for issue in issues))

    def test_missing_and_extra_wheels_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            lock_path = self._write_lock(root, {"package-a": "1.0"})
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            locked, _issues = read_locked_packages(lock_path)

            _records, missing_issues = inspect_wheelhouse(wheelhouse, locked)
            self._write_wheel(wheelhouse, "package_a", "1.0")
            self._write_wheel(wheelhouse, "unexpected", "1.0")
            _records, extra_issues = inspect_wheelhouse(wheelhouse, locked)

        self.assertTrue(any("esperado ausente" in issue for issue in missing_issues))
        self.assertTrue(any("inesperado" in issue for issue in extra_issues))

    def test_wrong_version_and_duplicate_version_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            lock_path = self._write_lock(root, {"package-a": "1.0"})
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            self._write_wheel(wheelhouse, "package_a", "9.0")
            self._write_wheel(wheelhouse, "package_a", "8.0")
            locked, _issues = read_locked_packages(lock_path)

            _records, issues = inspect_wheelhouse(wheelhouse, locked)

        self.assertTrue(any("duplicado" in issue for issue in issues))
        self.assertTrue(any("Versão divergente" in issue for issue in issues))

    def test_sdist_and_other_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            lock_path = self._write_lock(root, {"package-a": "1.0"})
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            (wheelhouse / "package-a-1.0.tar.gz").write_bytes(b"sdist")
            (wheelhouse / "README.txt").write_text("unexpected", encoding="utf-8")
            locked, _issues = read_locked_packages(lock_path)

            _records, issues = inspect_wheelhouse(wheelhouse, locked)

        self.assertTrue(
            any("Source distribution proibida" in issue for issue in issues)
        )
        self.assertTrue(any("não-wheel" in issue for issue in issues))

    def test_python_and_platform_tag_mismatch_are_rejected(self) -> None:
        for tag in ("cp313-cp313-win_amd64", "cp314-cp314-manylinux_2_39_x86_64"):
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir)
                lock_path = self._write_lock(root, {"package-a": "1.0"})
                wheelhouse = root / "wheelhouse"
                wheelhouse.mkdir()
                self._write_wheel(wheelhouse, "package_a", "1.0", tag)
                locked, _issues = read_locked_packages(lock_path)

                _records, issues = inspect_wheelhouse(wheelhouse, locked)

            self.assertTrue(any("Tags incompatíveis" in issue for issue in issues))

    def test_hash_lock_and_inventory_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _lock_path, wheelhouse, locked = self._two_package_fixture(root)
            records, issues = inspect_wheelhouse(wheelhouse, locked)
            self.assertEqual(issues, [])

            first_inventory = wheel_inventory_sha256(records)
            second_inventory = wheel_inventory_sha256(list(reversed(records)))
            first_lock = generate_hashed_lock_text(records)
            second_lock = generate_hashed_lock_text(list(reversed(records)))

        self.assertEqual(first_inventory, second_inventory)
        self.assertEqual(first_lock, second_lock)

    def test_hashed_lock_rejects_bad_hash_and_missing_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "requirements-build-hashes.lock"
            path.write_text(
                "package-a==1.0 --hash=sha256:not-a-hash\npackage-b==2.0\n",
                encoding="utf-8",
            )

            _packages, issues = read_hashed_lock(path)

        self.assertEqual(len(issues), 3)
        self.assertTrue(all("hash-pinned" in issue for issue in issues))

    def test_manifest_and_wheel_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            lock_path, hashed_lock, manifest, wheelhouse = self._complete_fixture(root)
            self.assertEqual(
                validate_manifest(
                    lock_path,
                    hashed_lock,
                    manifest,
                    wheelhouse=wheelhouse,
                ),
                [],
            )

            wheel = next(wheelhouse.glob("*.whl"))
            with wheel.open("ab") as stream:
                stream.write(b"tamper")
            issues = validate_manifest(
                lock_path,
                hashed_lock,
                manifest,
                wheelhouse=wheelhouse,
            )

        self.assertTrue(any("wheelhouse diverge" in issue for issue in issues))

    def test_manifest_hash_tampering_fails_without_local_wheelhouse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            lock_path, hashed_lock, manifest_path, _wheelhouse = self._complete_fixture(
                root
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["packages"][0]["sha256"] = "0" * 64
            manifest_path.write_bytes(canonical_json_bytes(manifest))

            issues = validate_manifest(lock_path, hashed_lock, manifest_path)

        self.assertTrue(any("Hash lock diverge" in issue for issue in issues))
        self.assertTrue(any("Inventário derivado" in issue for issue in issues))

    def test_noncanonical_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            lock_path, hashed_lock, manifest_path, _wheelhouse = self._complete_fixture(
                root
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            issues = validate_manifest(lock_path, hashed_lock, manifest_path)

        self.assertTrue(any("JSON canônico" in issue for issue in issues))

    def test_offline_install_command_requires_no_index_and_hashes(self) -> None:
        command = offline_install_command(
            Path("offline-python.exe"),
            Path("wheelhouse"),
            Path("requirements-build-hashes.lock"),
        )

        self.assertIn("--no-index", command)
        self.assertIn("--find-links", command)
        self.assertIn("--require-hashes", command)
        self.assertNotIn("--index-url", command)

    def test_canonical_wheel_metadata_has_narrow_git_attributes(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "source"
            new_repository(repo)
            shutil.copyfile(PROJECT_DIR / ".gitattributes", repo / ".gitattributes")
            result = git(
                repo,
                "check-attr",
                "text",
                "--",
                *CANONICAL_ARTIFACTS,
                *ADJACENT_TEXT_ARTIFACTS,
            )
        attributes = dict(
            line.split(": ", 2)[::2] for line in result.decode().splitlines()
        )
        for name in CANONICAL_ARTIFACTS:
            self.assertEqual(attributes[name], "unset")
        for name in ADJACENT_TEXT_ARTIFACTS:
            self.assertEqual(attributes[name], "unspecified")

    def test_canonical_wheel_metadata_matches_pinned_hashes(self):
        for name, expected in CANONICAL_ARTIFACTS.items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((PROJECT_DIR / name).read_bytes())
                    .hexdigest()
                    .upper(),
                    expected,
                )

    @unittest.skipUnless(sys.platform == "win32", "checkout autocrlf é Windows-only")
    def test_real_autocrlf_checkout_preserves_wheel_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            temporary_root = Path(temporary_dir)
            source = temporary_root / "Fonte canônica"
            checkout = temporary_root / "Teste Educação com espaços"
            new_repository(source)
            project = source / PROJECT_DIR.name
            project.mkdir()
            names = [
                ".gitattributes",
                "requirements-build.lock",
                "requirements-build-hashes.lock",
                "docs/compliance/python/PYTHON_WHEEL_PROVENANCE.json",
                "validate_python_wheels.py",
                "validate_build_environment.py",
            ]
            for name in names:
                target = project / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(PROJECT_DIR / name, target)
            git(source, "add", "--", *[f"{PROJECT_DIR.name}/{name}" for name in names])
            commit(source, temporary_root, "wheel metadata fixture")
            clone_with_autocrlf(source, checkout)
            checkout_project = checkout / PROJECT_DIR.name

            for relative_path, expected_sha256 in CANONICAL_ARTIFACTS.items():
                with self.subTest(path=relative_path):
                    blob_bytes = git(
                        checkout, "show", f"HEAD:{PROJECT_DIR.name}/{relative_path}"
                    )
                    worktree_bytes = (checkout_project / relative_path).read_bytes()
                    self.assertEqual(worktree_bytes, blob_bytes)
                    self.assertEqual(
                        hashlib.sha256(worktree_bytes).hexdigest().upper(),
                        expected_sha256,
                    )

            attribute_result = git(
                checkout_project,
                "check-attr",
                "text",
                "--",
                *CANONICAL_ARTIFACTS,
                *ADJACENT_TEXT_ARTIFACTS,
            )
            attributes = dict(
                line.split(": ", 2)[::2]
                for line in attribute_result.decode().splitlines()
            )
            for path in CANONICAL_ARTIFACTS:
                self.assertEqual(attributes[path], "unset")
            for path in ADJACENT_TEXT_ARTIFACTS:
                self.assertEqual(attributes[path], "unspecified")

            command = [
                sys.executable,
                "validate_python_wheels.py",
                "--lock",
                "requirements-build.lock",
                "--hashed-lock",
                "requirements-build-hashes.lock",
                "--manifest",
                "docs/compliance/python/PYTHON_WHEEL_PROVENANCE.json",
            ]
            if wheelhouse := os.environ.get("EDUDOWNLOADER_WHEELHOUSE"):
                command.extend(("--wheelhouse", wheelhouse))
            validator_result = subprocess.run(
                command,
                cwd=checkout_project,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                validator_result.returncode,
                0,
                validator_result.stdout + validator_result.stderr,
            )
            self.assertIn("Wheel Integrity classe A validada.", validator_result.stdout)


if __name__ == "__main__":
    unittest.main()
