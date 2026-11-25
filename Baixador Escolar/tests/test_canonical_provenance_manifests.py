"""Regressões de materialização dos manifests canônicos de provenance."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.git_fixture import clone_with_autocrlf, commit, git, new_repository


PROJECT_DIR = Path(__file__).resolve().parents[1]
CANONICAL_MANIFESTS = {
    "docs/compliance/ffmpeg/BTBN_SOURCE_PROVENANCE.json": (
        "D7DB1D53B855484F5BDEE2F5DCA2360719CFAC1E338A1A073138C9D0A1D1F8FE"
    ),
    "docs/compliance/python/CPYTHON_RUNTIME_SOURCE_PROVENANCE.json": (
        "C091D37CB18D757282BE240A02370565A94673968A32C7AF4CAB66A974F2BC72"
    ),
    "docs/compliance/microsoft/MICROSOFT_RUNTIME_PACKAGING.json": (
        "A288A54243F2F9FDEBDF872159234A03B8786A2319FDAEAB6AD7529144DA8552"
    ),
    "docs/compliance/microsoft/MICROSOFT_EXTERNAL_RUNTIME_POLICY.json": (
        "DAD44F00F996EF3E836CE2CBE641E348FDC614BA4B5CD4EFC02AF0637050B290"
    ),
}
TEXT_NORMALIZED_NEIGHBORS = (
    "docs/compliance/ffmpeg/BTBN_CANDIDATE_PROVENANCE.json",
    "docs/compliance/python/CPYTHON_RUNTIME_SOURCE_CORRESPONDENCE.md",
    "docs/compliance/microsoft/MICROSOFT_RUNTIME_PACKAGING.md",
)
DIRECT_VALIDATION_TESTS = (
    "tests.test_btbn_source_bundle.BtbnSourceBundleTests."
    "test_official_manifest_has_fixed_core_identities_and_complete_status",
    "tests.test_python_runtime_source_bundle.PythonRuntimeSourceBundleTests."
    "test_official_manifest_is_canonical_and_pinned",
    "tests.test_microsoft_runtime_packaging.MicrosoftRuntimePackagingTests."
    "test_manifest_is_canonical_and_pins_official_x64_runtime",
    "tests.test_microsoft_runtime_packaging.MicrosoftRuntimePackagingTests."
    "test_external_policy_rejects_direct_runtime_files",
)


class CanonicalProvenanceManifestTests(unittest.TestCase):
    def test_git_attributes_are_limited_to_byte_canonical_manifests(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "source"
            new_repository(repo)
            shutil.copyfile(PROJECT_DIR / ".gitattributes", repo / ".gitattributes")
            output = git(
                repo,
                "check-attr",
                "text",
                "--",
                *CANONICAL_MANIFESTS,
                *TEXT_NORMALIZED_NEIGHBORS,
            )
        attributes = dict(
            line.split(": ", 2)[::2] for line in output.decode().splitlines()
        )
        for path in CANONICAL_MANIFESTS:
            self.assertEqual(attributes[path], "unset")
        for path in TEXT_NORMALIZED_NEIGHBORS:
            self.assertEqual(attributes[path], "unspecified")

    def test_worktree_preserves_pinned_manifest_bytes(self):
        for name, expected in CANONICAL_MANIFESTS.items():
            with self.subTest(path=name):
                self.assertEqual(
                    hashlib.sha256((PROJECT_DIR / name).read_bytes())
                    .hexdigest()
                    .upper(),
                    expected,
                )

    @unittest.skipUnless(sys.platform == "win32", "checkout autocrlf é Windows-only")
    def test_real_autocrlf_checkout_preserves_and_validates_manifests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Fonte canônica"
            checkout = root / "Teste Educação com Espaços"
            new_repository(source)
            shutil.copyfile(PROJECT_DIR / ".gitattributes", source / ".gitattributes")
            for name in CANONICAL_MANIFESTS:
                destination = source / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(PROJECT_DIR / name, destination)
            git(source, "add", "--", ".gitattributes", *CANONICAL_MANIFESTS)
            commit(source, root, "fixture de procedência")
            clone_with_autocrlf(source, checkout)
            for name, expected in CANONICAL_MANIFESTS.items():
                with self.subTest(path=name):
                    blob = git(checkout, "show", f"HEAD:{name}")
                    self.assertEqual((checkout / name).read_bytes(), blob)
                    self.assertEqual(hashlib.sha256(blob).hexdigest().upper(), expected)
            validation = subprocess.run(
                [sys.executable, "-m", "unittest", *DIRECT_VALIDATION_TESTS, "-v"],
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                validation.returncode, 0, validation.stdout + validation.stderr
            )


if __name__ == "__main__":
    unittest.main()
