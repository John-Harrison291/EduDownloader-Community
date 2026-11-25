"""Contratos do branding aprovado no checkout e no probe congelado 1.7."""

from __future__ import annotations

import ast
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import app
from validate_frozen_candidate import (
    V1_7_BRANDING_PATH,
    V1_7_BRANDING_SHA256,
    V1_7_BRANDING_SIZE,
    V1_7_VISUAL_PROBE_CLASSIFICATION,
    V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
    _visual_branding_issue,
    candidate_pipeline_contract,
    compare_candidate_composition,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = PROJECT_ROOT / "branding" / "edudownloader-logo-original.png"
ICON = PROJECT_ROOT / "branding" / "edudownloader-symbol.ico"


class BrandingTests(unittest.TestCase):
    def test_original_asset_is_approved_and_unchanged(self) -> None:
        self.assertTrue(ORIGINAL.is_file())
        self.assertEqual(ORIGINAL.stat().st_size, V1_7_BRANDING_SIZE)
        self.assertEqual(
            hashlib.sha256(ORIGINAL.read_bytes()).hexdigest().upper(),
            V1_7_BRANDING_SHA256,
        )
        with Image.open(ORIGINAL) as image:
            self.assertEqual(image.size, (1254, 1254))

    def test_branding_path_resolves_in_checkout_and_frozen_layout(self) -> None:
        self.assertEqual(app.EduDownloaderApp._load_brand_image().size, (650, 650))
        with tempfile.TemporaryDirectory() as temporary:
            internal = Path(temporary) / "portable with spaces" / "_internal"
            asset = internal / "branding" / ORIGINAL.name
            asset.parent.mkdir(parents=True)
            shutil.copy2(ORIGINAL, asset)
            with patch.object(app, "__file__", str(internal / "app.py")):
                frozen_image = app.EduDownloaderApp._load_brand_image()
            self.assertIsNotNone(frozen_image)
            self.assertEqual(frozen_image.size, (650, 650))

    def test_spec_collects_relative_runtime_asset_and_embeds_derived_icon(self) -> None:
        spec = (PROJECT_ROOT / "EduDownloader.spec").read_text(encoding="utf-8")
        tree = ast.parse(spec)
        analysis = next(
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "analysis"
                for target in node.targets
            )
        )
        executable = next(
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "executable"
                for target in node.targets
            )
        )
        analysis_kwargs = {keyword.arg: keyword.value for keyword in analysis.keywords}
        exe_kwargs = {keyword.arg: keyword.value for keyword in executable.keywords}
        assets = dict(ast.literal_eval(analysis_kwargs["datas"]))
        self.assertEqual(assets["branding/edudownloader-logo-original.png"], "branding")
        self.assertEqual(
            ast.literal_eval(exe_kwargs["icon"]),
            "branding/edudownloader-symbol.ico",
        )
        self.assertNotIn("C:/Users/", spec)
        self.assertNotIn("C:\\Users\\", spec)
        with Image.open(ICON) as image:
            self.assertTrue(
                {(16, 16), (32, 32), (48, 48), (256, 256)} <= image.ico.sizes()
            )

    def test_visual_probe_is_isolated_and_branding_delta_is_exact(self) -> None:
        contract = candidate_pipeline_contract(PROJECT_ROOT, "v1.7-visual-probe")
        self.assertEqual(contract.classification, V1_7_VISUAL_PROBE_CLASSIFICATION)
        self.assertEqual(contract.manifest.parent, contract.root / "evidence")
        self.assertNotIn("candidate", contract.root.name)
        approved = {
            "path": V1_7_BRANDING_PATH,
            "sha256": V1_7_BRANDING_SHA256,
            "size_bytes": V1_7_BRANDING_SIZE,
        }
        before = {"entries": [], "inventory_sha256": "A" * 64}
        after = {"entries": [approved], "inventory_sha256": "B" * 64}
        scoped = compare_candidate_composition(
            before,
            after,
            candidate_classification=V1_7_VISUAL_PROBE_CLASSIFICATION,
        )
        historical = compare_candidate_composition(before, after)
        self.assertEqual(scoped["unexpected_count"], 0)
        self.assertEqual(historical["unexpected_count"], 1)
        self.assertIsNone(
            _visual_branding_issue(after, V1_7_VISUAL_PROBE_CLASSIFICATION)
        )
        changed = {"entries": [{**approved, "sha256": "0" * 64}]}
        self.assertEqual(
            _visual_branding_issue(changed, V1_7_VISUAL_PROBE_CLASSIFICATION),
            "v1.7-branding-asset-mismatch",
        )
        self.assertIsNone(
            _visual_branding_issue(after, V1_7_RELEASE_CANDIDATE_CLASSIFICATION)
        )
        self.assertEqual(
            _visual_branding_issue(changed, V1_7_RELEASE_CANDIDATE_CLASSIFICATION),
            "v1.7-branding-asset-mismatch",
        )


if __name__ == "__main__":
    unittest.main()
