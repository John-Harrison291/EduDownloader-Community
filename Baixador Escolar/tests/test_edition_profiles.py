"""Contratos de compilação do candidato Community."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from constants import APP_VERSION, PRODUCT_EDITION, ProductEdition
from edition_profiles import EditionBuildProfile, select_build_profile


ROOT = Path(__file__).resolve().parents[1]


class EditionProfileTests(unittest.TestCase):
    def test_version_and_default_identity(self) -> None:
        self.assertEqual(APP_VERSION, "3.0.0")
        self.assertIs(PRODUCT_EDITION, ProductEdition.COMMUNITY)

    def test_community_output_entrypoint_and_packaging_contract_are_fixed(self):
        profile = select_build_profile("community")
        self.assertEqual(profile.output_directory, "EduDownloader-3.0.0-Community")
        contract = profile.as_contract()
        self.assertEqual(contract["entrypoint"], "frozen_community.py")
        self.assertEqual(contract["spec"], "EduDownloader.spec")
        self.assertTrue(contract["candidate_pipeline_ready"])
        self.assertIs(contract["production_ready"], False)
        self.assertIs(contract["public_release_allowed"], False)

    def test_unknown_or_untyped_edition_cannot_default_to_community(self) -> None:
        for edition in ("", "unknown", "COMMERCIAL"):
            with self.subTest(edition=edition), self.assertRaises(ValueError):
                select_build_profile(edition)
        with self.assertRaises(ValueError):
            EditionBuildProfile("commercial")

    def test_profile_cannot_be_promoted_by_mutating_flags(self) -> None:
        profile = select_build_profile("community")
        with self.assertRaises(FrozenInstanceError):
            profile.edition = ProductEdition.COMMUNITY
        document = profile.as_contract()
        document["production_ready"] = True
        self.assertFalse(profile.production_ready)

    def test_explicit_cli_selection_is_read_only_and_never_activates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            for edition in ProductEdition:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "edition_profiles.py"),
                        "--edition",
                        edition.value,
                    ],
                    cwd=temporary_dir,
                    env={**os.environ, "LOCALAPPDATA": temporary_dir},
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["edition"], edition.value)
            self.assertEqual(list(Path(temporary_dir).iterdir()), [])

    def test_local_build_profile_does_not_authorize_release(self):
        self.assertIs(select_build_profile("community").public_release_allowed, False)


if __name__ == "__main__":
    unittest.main()
