"""Offline checks for the future public source-asset contract."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import public_source_delivery


class PublicSourceDeliveryTests(unittest.TestCase):
    def test_exact_asset_and_notice_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "sources" / "source.zip"
            asset.parent.mkdir()
            asset.write_bytes(b"fixture")
            digest = hashlib.sha256(b"fixture").hexdigest().upper()
            inventory = "A" * 64
            notice = root / "Licencas" / "THIRD_PARTY_SOURCE_INFORMATION.txt"
            notice.parent.mkdir()
            notice.write_text(f"source.zip {digest} {inventory}", encoding="utf-8")
            specs = (("sample", "sources/source.zip", 7, digest, inventory),)
            with patch.object(public_source_delivery, "SOURCE_ASSETS", specs):
                self.assertEqual(
                    public_source_delivery.find_source_delivery_issues(root), []
                )
                asset.write_bytes(b"changed")
                self.assertIn(
                    "Asset de fonte divergente: sample",
                    public_source_delivery.find_source_delivery_issues(root),
                )
                asset.unlink()
                self.assertIn(
                    "Asset de fonte ausente: sample",
                    public_source_delivery.find_source_delivery_issues(root),
                )

    def test_undocumented_source_asset_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "asset.zip"
            asset.write_bytes(b"x")
            license_root = root / "Licencas"
            license_root.mkdir()
            (license_root / "THIRD_PARTY_SOURCE_INFORMATION.txt").write_text(
                "no matching source", encoding="utf-8"
            )
            specs = (("sample", "asset.zip", 1, "A" * 64, "B" * 64),)
            with patch.object(public_source_delivery, "SOURCE_ASSETS", specs):
                self.assertIn(
                    "Asset de fonte sem instrução/identidade: sample",
                    public_source_delivery.find_source_delivery_issues(root),
                )

    def test_staging_requires_exact_assets_and_explicit_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            output = Path(temporary) / "release"
            root.mkdir()
            asset = root / "source.zip"
            asset.write_bytes(b"source")
            digest = hashlib.sha256(b"source").hexdigest().upper()
            inventory = "B" * 64
            license_root = root / "Licencas"
            license_root.mkdir()
            (license_root / "THIRD_PARTY_SOURCE_INFORMATION.txt").write_text(
                f"source.zip {digest} {inventory}", encoding="utf-8"
            )
            specs = (("sample", "source.zip", 6, digest, inventory),)
            with patch.object(public_source_delivery, "SOURCE_ASSETS", specs):
                staged = public_source_delivery.stage_source_assets(output, root=root)
                self.assertEqual(staged, (output / "source.zip",))
                self.assertEqual(
                    public_source_delivery.find_staged_source_issues(output), []
                )
                staged[0].write_bytes(b"tampered")
                self.assertTrue(
                    public_source_delivery.find_staged_source_issues(output)
                )
                with self.assertRaisesRegex(ValueError, "existente diverge"):
                    public_source_delivery.stage_source_assets(output, root=root)
                public_source_delivery.stage_source_assets(
                    output, root=root, replace=True
                )
                self.assertEqual(
                    public_source_delivery.find_staged_source_issues(output), []
                )


if __name__ == "__main__":
    unittest.main()
