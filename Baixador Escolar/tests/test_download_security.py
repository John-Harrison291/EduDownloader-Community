"""Defensive download checks with synthetic requests, media and policy results."""

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import json
import logging
import os
import socket
import threading
import unittest

from constants import CONTENT_TYPE_AUDIO, CONTENT_TYPE_VIDEO
from download_network import (
    DestinationBlocked,
    DownloadNetwork,
    _public_endpoints,
    check_media_destination,
)
from downloader import (
    DownloadCancelledError,
    DownloadRequest,
    DownloadResult,
    DownloadService,
    DownloadServiceError,
    ToolPaths,
    build_download_command,
)
from tests.download_network_fixtures import local_media_endpoint
from windows_attachment import AttachmentStatus, source_origin


class DownloadDestinationPolicyTests(unittest.TestCase):
    def test_requires_unambiguous_http_without_credentials_or_local_targets(self):
        for url in (
            "https://cdn.example.org:443/a?revision=2",
            "http://public.example.org/",
            "https://[2606:4700:4700::1111]/",
        ):
            with self.subTest(url=url):
                check_media_destination(url)
        for url in (
            "file:///qa/synthetic",
            "ftp://example.org/media",
            "https://user@example.org/media",
            "https://example.org:0/media",
            "http://[fe80::1]/",
            "https://example.org:8080/media",
            "http://localhost/media",
            "http://device.home.arpa/media",
            "http://[::ffff:127.0.0.1]/",
            "http://[64:ff9b::7f00:1]/",
            "https://192.0.2.1/media",
            "https://127.000.0.1/media",
            "https://2130706433/media",
            "https://public.example.org\\media",
            "https://public.example.org/\nmedia",
            "https://public.example.org/\u200bmedia",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                check_media_destination(url)

    def test_dns_resolution_rejects_mixed_public_and_private_answers(self):
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, 443))
            for host in ("1.1.1.1", "10.0.0.9")
        ]
        with (
            patch("download_network.socket.getaddrinfo", return_value=answers),
            self.assertRaises(DestinationBlocked),
        ):
            _public_endpoints("cdn.example.org", 443)

    def test_origin_for_native_services_drops_path_query_and_fragment(self):
        self.assertEqual(
            source_origin("https://example.org/private-name?secret=fixture#here"),
            "https://example.org/",
        )


class DownloadProxyTests(unittest.TestCase):
    def test_authenticated_http_fixture_and_denial_of_another_loopback_target(self):
        seen = []

        class SyntheticHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get("Proxy-Authorization")))
                self.send_response(200)
                self.send_header("Content-Length", "8")
                self.end_headers()
                self.wfile.write(b"fixture!")

            def log_message(self, *_args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), SyntheticHandler) as origin:
            server = threading.Thread(target=origin.serve_forever, daemon=True)
            server.start()
            try:
                url = f"http://127.0.0.1:{origin.server_port}/synthetic"
                with local_media_endpoint(origin), DownloadNetwork() as proxy:

                    def request(target, authenticate):
                        conn = HTTPConnection(
                            "127.0.0.1", proxy.server.server_port, timeout=3
                        )
                        try:
                            headers = {}
                            if authenticate:
                                headers["Proxy-Authorization"] = (
                                    proxy.server.authorization.decode()
                                )
                            conn.request("GET", target, headers=headers)
                            with conn.getresponse() as response:
                                return response.status, response.read()
                        finally:
                            conn.close()

                    self.assertEqual(request(url, False), (407, b""))
                    self.assertEqual(seen, [])
                    self.assertEqual(request(url, True), (200, b"fixture!"))
                    self.assertEqual(seen, [("/synthetic", None)])
                    port = 81 if origin.server_port != 81 else 82
                    self.assertEqual(
                        request(f"http://127.0.0.1:{port}/not-the-fixture", True),
                        (403, b""),
                    )
                    self.assertTrue(proxy.blocked)
                    encoded = proxy.server.authorization[6:].decode()
                    self.assertNotIn(proxy.token, proxy.redact(proxy.token))
                    self.assertNotIn(encoded, proxy.redact(encoded))
            finally:
                origin.shutdown()
                server.join(3)
            with self.assertRaises(DestinationBlocked):
                check_media_destination(url)


class SafePublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        logger = logging.getLogger("test-safe-publication")
        logger.handlers = [logging.NullHandler()]
        self.service = DownloadService(self.root, logger)
        self.request = DownloadRequest(
            "https://cdn.example.org/synthetic", CONTENT_TYPE_VIDEO, "720p", self.root
        )
        tools = ToolPaths(
            *(self.root / name for name in ("yt-dlp", "ffmpeg", "ffprobe", "deno"))
        )
        self.command = build_download_command(self.request, tools, self.root)
        self.final = self.root / "fixture.mp4"
        self.staged = None

    def download(self, command, *, destination_dir):
        self.assertIn("--", command)
        self.assertEqual(command[command.index("--paths") + 1], str(destination_dir))
        self.staged = destination_dir / self.final.name
        self.staged.write_bytes(b"fixture mantida na area temporaria")
        return DownloadResult(self.staged, False)

    def assert_no_staging(self):
        self.assertFalse(self.final.exists())
        self.assertIsNotNone(self.staged)
        self.assertFalse(self.staged.exists())

    def run_pipeline(self):
        return self.service._secure_execute(self.request, self.command, self.root)

    def test_explicit_block_and_unavailable_security_keep_file_unpublished(self):
        for status in (
            AttachmentStatus.BLOCKED,
            AttachmentStatus.UNAVAILABLE,
            AttachmentStatus.FAILED,
        ):
            with (
                self.subTest(status=status),
                patch.object(self.service, "_execute", side_effect=self.download),
                patch.object(self.service, "_verify_media") as format_check,
                patch.object(
                    self.service,
                    "_run_verification_process",
                    return_value=(status, None),
                ),
                self.assertRaisesRegex(DownloadServiceError, "segurança|bloqueado"),
            ):
                try:
                    self.run_pipeline()
                finally:
                    format_check.assert_called_once()
                    self.assert_no_staging()

    def test_cancel_during_validation_keeps_file_unpublished(self):
        def cancel(_path, _url):
            self.service._cancel_event.set()

        with (
            patch.object(self.service, "_execute", side_effect=self.download),
            patch.object(self.service, "_verify_media"),
            patch.object(self.service, "_verify_attachment", side_effect=cancel),
            self.assertRaises(DownloadCancelledError),
        ):
            self.run_pipeline()
        self.assert_no_staging()

    def test_marking_that_changes_mtime_requires_revalidating_final_media(self):
        def mark(path, _url):
            meta = path.stat()
            os.utime(path, ns=(meta.st_atime_ns, meta.st_mtime_ns + 1_000_000_000))

        with (
            patch.object(self.service, "_execute", side_effect=self.download),
            patch.object(self.service, "_verify_media") as verify,
            patch.object(self.service, "_verify_attachment", side_effect=mark),
        ):
            result = self.run_pipeline()
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(result.file_path, self.final)
        self.assertTrue(result.file_path.is_file())
        self.assertFalse(self.staged.exists())

    def test_personal_file_is_not_overwritten(self):
        self.final.write_bytes(b"existing fixture")
        with (
            patch.object(self.service, "_execute", side_effect=self.download),
            patch.object(self.service, "_verify_media"),
            patch.object(self.service, "_verify_attachment"),
            self.assertRaisesRegex(DownloadServiceError, "já existe"),
        ):
            self.run_pipeline()
        self.assertEqual(self.final.read_bytes(), b"existing fixture")
        self.assertFalse(self.staged.exists())

    def test_incomplete_or_external_output_fails_before_system_services(self):
        for use_external in (True, False):

            def output(_command, *, destination_dir):
                self.staged = (
                    self.final if use_external else destination_dir / self.final.name
                )
                self.staged.write_bytes(b"partial")
                return DownloadResult(self.staged, False)

            with (
                self.subTest(external_output=use_external),
                patch.object(self.service, "_execute", side_effect=output),
                patch.object(self.service, "_verify_media") as probe,
                patch.object(self.service, "_verify_attachment") as attachment,
                self.assertRaisesRegex(DownloadServiceError, "formato"),
            ):
                self.run_pipeline()
            probe.assert_not_called()
            attachment.assert_not_called()
            if use_external:
                self.assertEqual(self.final.read_bytes(), b"partial")
                self.final.unlink()
            else:
                self.assert_no_staging()

    def test_fake_mp4_and_audio_without_mp3_are_rejected(self):
        runner = Mock()
        fixture = self.root / "untrusted.mp4"
        fixture.write_bytes(b"arquivo de teste simples")
        with patch.object(self.service, "_run_verification_process", runner):
            with self.assertRaisesRegex(DownloadServiceError, "formato"):
                self.service._verify_media(fixture, CONTENT_TYPE_VIDEO)
        runner.assert_not_called()
        code = json.dumps(
            {
                "format": {"format_name": "mp3"},
                "streams": [{"codec_type": "audio", "codec_name": "aac"}],
            }
        )
        runner.return_value = (0, code)
        with patch.object(self.service, "_run_verification_process", runner):
            with self.assertRaisesRegex(DownloadServiceError, "formato"):
                self.service._verify_media(fixture, CONTENT_TYPE_AUDIO)
