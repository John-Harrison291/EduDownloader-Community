import base64
from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from component_catalog import (
    CATALOGUE_DOMAIN,
    CatalogueCache,
    CatalogueError,
    canonical_catalogue,
    parse_catalogue,
    verify_signed_catalogue,
)


def catalogue(revision=1, *, revoked=(), assets=()):
    return {
        "schema": 1,
        "edition": "community",
        "revision": revision,
        "issued": "2026-11-24T00:00:00Z",
        "expires": "2026-12-01T00:00:00Z",
        "approvals": list(assets),
        "revoked": list(revoked),
    }


class ComponentCatalogueTests(unittest.TestCase):
    NOW = datetime(2026, 11, 28, tzinfo=UTC)

    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.keys = {"fixture-only": self.key.public_key().public_bytes_raw()}

    def envelope(self, document):
        signature = self.key.sign(CATALOGUE_DOMAIN + canonical_catalogue(document))
        return {
            "key_id": "fixture-only",
            "payload": document,
            "signature": base64.b64encode(signature).decode(),
        }

    def signed(self, document):
        return canonical_catalogue(self.envelope(document))

    def test_signature_and_edition_are_checked_before_an_approval(self):
        good = self.signed(catalogue(2))
        self.assertEqual(verify_signed_catalogue(good, self.keys).revision, 2)
        bad = self.envelope(catalogue(3))
        bad["payload"]["revision"] = 2
        with self.assertRaisesRegex(CatalogueError, "invalid_catalogue_signature"):
            verify_signed_catalogue(canonical_catalogue(bad), self.keys)
        with self.assertRaisesRegex(CatalogueError, "untrusted_catalogue_key"):
            verify_signed_catalogue(good, {})
        with self.assertRaises(CatalogueError):
            verify_signed_catalogue(
                self.signed({**catalogue(2), "edition": "commercial"}), self.keys
            )

    def test_cache_rejects_expiry_rollback_and_revocation_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = CatalogueCache(
                Path(temporary), parse_catalogue(catalogue()), keys=self.keys
            )
            blocked = [{"component": "deno", "version": "2.9.8"}]
            saved = self.signed(catalogue(4, revoked=blocked))
            self.assertTrue(
                cache.accept(saved, now=self.NOW).is_revoked("deno", "2.9.8.0")
            )
            for rejected in (catalogue(3, revoked=blocked), catalogue(5)):
                with self.assertRaises(CatalogueError):
                    cache.accept(self.signed(rejected), now=self.NOW)
            self.assertEqual(cache.path.read_bytes(), saved)
            later = datetime(2026, 12, 3, tzinfo=UTC)
            self.assertTrue(cache.effective(now=later).is_revoked("deno", "2.9.8"))
            with self.assertRaisesRegex(CatalogueError, "outside_validity"):
                cache.accept(self.signed(catalogue(9, revoked=blocked)), now=later)
