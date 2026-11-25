"""Signing gates with synthetic identities; never use a real private key."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import windows_signing as w

THUMBPRINT = "A" * 40
PUBLISHER = "CN=TEST ONLY Goal 6"


def certificate(**changes):
    now = datetime.now(timezone.utc)
    return {
        "publisher": PUBLISHER,
        "thumbprint": THUMBPRINT,
        "private_key_present": True,
        "trusted": True,
        "code_signing": True,
        "not_before": (now - timedelta(days=1)).isoformat(),
        "not_after": (now + timedelta(days=1)).isoformat(),
        **changes,
    }


def signature(**changes):
    return {
        "status": "Valid",
        "type": "Authenticode",
        "publisher": PUBLISHER,
        "thumbprint": THUMBPRINT,
        "timestamp_present": True,
        **changes,
    }


class SigningTests(unittest.TestCase):
    def test_timestamp_credentials_or_malformed_urls_never_launch_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.exe"
            source.write_bytes(b"own synthetic input")
            for url in (
                "https://user:secret@timestamp.example.test",
                "https://timestamp.example.test?token=synthetic",
                "https://[broken",
                "file:///server",
                None,
            ):
                with (
                    self.subTest(url=url),
                    patch.object(w, "validate_signtool") as tool,
                    self.assertRaises(w.SigningError),
                ):
                    w.sign_copy(
                        source,
                        root / "target.exe",
                        signtool=root / "signtool.exe",
                        thumbprint=THUMBPRINT,
                        expected_publisher=PUBLISHER,
                        timestamp_url=url,
                    )
                tool.assert_not_called()
                self.assertFalse((root / "target.exe").exists())

    def test_explicit_cert_preflight_rejects_missing_mismatch_expired_or_untrusted(
        self,
    ):
        for change in (
            {"publisher": "CN=Another"},
            {"thumbprint": "B" * 40},
            {"trusted": False},
            {"private_key_present": False},
            {"code_signing": False},
            {"not_after": "2020-01-01T00:00:00+00:00"},
            {"not_before": "malformed"},
        ):
            with (
                self.subTest(change=change),
                patch.object(w, "_powershell_json", return_value=certificate(**change)),
                self.assertRaises(w.SigningError),
            ):
                w.certificate_preflight(THUMBPRINT, PUBLISHER)
        with patch.object(w, "_powershell_json", return_value=certificate()) as query:
            w.certificate_preflight(THUMBPRINT, PUBLISHER)
            self.assertEqual(query.call_args.args[1]["EDU_CERT_THUMBPRINT"], THUMBPRINT)
            self.assertEqual(query.call_args.args[1]["EDU_CERT_STORE"], "CurrentUser")

    def test_signature_integrity_identity_timestamp_and_catalog_gates(self):
        for change in (
            {"status": "HashMismatch"},
            {"status": "NotTrusted"},
            {"status": "NotSigned"},
            {"publisher": "CN=Another"},
            {"timestamp_present": False},
            {"thumbprint": "B" * 40},
            {"type": "Catalog"},
        ):
            with (
                self.subTest(change=change),
                patch.object(w, "inspect_signature", return_value=signature(**change)),
                self.assertRaises(w.SigningError),
            ):
                w.verify_signature(
                    Path("synthetic.exe"),
                    expected_publisher=PUBLISHER,
                    expected_thumbprint=THUMBPRINT,
                )
        with patch.object(
            w, "inspect_signature", return_value=signature(certificate_expired_now=True)
        ):
            # Windows may validate an expired signer through a trusted timestamp.
            self.assertEqual(
                w.verify_signature(Path("synthetic.exe"), expected_publisher=PUBLISHER)[
                    "status"
                ],
                "Valid",
            )

    def test_signs_only_copy_and_verifies_before_exclusive_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, target, tool = (
                root / "original.exe",
                root / "signed.exe",
                root / "signtool.exe",
            )
            source.write_bytes(b"synthetic unsigned PE stand-in")
            calls = []

            def run(_tool, args):
                calls.append(args)
                staged = Path(args[-1])
                self.assertNotEqual(staged, source)
                self.assertTrue(staged.exists())
                staged.write_bytes(staged.read_bytes() + b" signature")

            with (
                patch.object(w, "validate_signtool", return_value=tool),
                patch.object(w, "certificate_preflight", return_value=certificate()),
                patch.object(
                    w, "inspect_signature", return_value={"status": "NotSigned"}
                ),
                patch.object(w, "_run_tool", side_effect=run),
                patch.object(w, "verify_signature", return_value=signature()) as verify,
            ):
                w.sign_copy(
                    source,
                    target,
                    signtool=tool,
                    thumbprint=THUMBPRINT,
                    expected_publisher=PUBLISHER,
                    timestamp_url="https://timestamp.example.test",
                )
            self.assertEqual(source.read_bytes(), b"synthetic unsigned PE stand-in")
            self.assertTrue(target.read_bytes().endswith(b" signature"))
            self.assertTrue(verify.called)
            self.assertNotIn("/a", calls[0])
            self.assertIn("/sha1", calls[0])
            self.assertEqual(calls[0][calls[0].index("/fd") + 1], "SHA256")
            self.assertEqual(calls[0][calls[0].index("/td") + 1], "SHA256")
            self.assertIn("/tr", calls[0])
            self.assertFalse(list(root.glob(".edu-signing-*")))

    def test_failed_post_sign_verification_never_publishes_or_changes_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, target = root / "source.exe", root / "target.exe"
            source.write_bytes(b"original")
            with (
                patch.object(
                    w, "validate_signtool", return_value=root / "signtool.exe"
                ),
                patch.object(w, "certificate_preflight", return_value=certificate()),
                patch.object(
                    w, "inspect_signature", return_value={"status": "NotSigned"}
                ),
                patch.object(w, "_run_tool"),
                patch.object(
                    w, "verify_signature", side_effect=w.SigningError("untrusted")
                ),
                self.assertRaises(w.SigningError),
            ):
                w.sign_copy(
                    source,
                    target,
                    signtool=root / "signtool.exe",
                    thumbprint=THUMBPRINT,
                    expected_publisher=PUBLISHER,
                    timestamp_url="https://timestamp.example.test",
                )
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), b"original")
            self.assertFalse(list(root.glob(".edu-signing-*")))

    def test_existing_output_and_existing_third_party_signature_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, target = root / "source.exe", root / "target.exe"
            source.write_bytes(b"vendor")
            target.write_bytes(b"keep")
            with self.assertRaises(w.SigningError):
                w.sign_copy(
                    source,
                    target,
                    signtool=root / "signtool.exe",
                    thumbprint=THUMBPRINT,
                    expected_publisher=PUBLISHER,
                    timestamp_url="https://timestamp.example.test",
                )
            self.assertEqual(target.read_bytes(), b"keep")
            target.unlink()
            with (
                patch.object(
                    w, "validate_signtool", return_value=root / "signtool.exe"
                ),
                patch.object(w, "certificate_preflight", return_value=certificate()),
                patch.object(w, "inspect_signature", return_value=signature()),
                self.assertRaises(w.SigningError),
            ):
                w.sign_copy(
                    source,
                    target,
                    signtool=root / "signtool.exe",
                    thumbprint=THUMBPRINT,
                    expected_publisher=PUBLISHER,
                    timestamp_url="https://timestamp.example.test",
                )
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), b"vendor")
