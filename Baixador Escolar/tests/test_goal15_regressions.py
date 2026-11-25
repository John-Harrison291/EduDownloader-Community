"""Regressões de downloads, documentos e mídia com insumos sintéticos."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
import logging
from pathlib import Path
from queue import Empty
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from constants import CONTENT_TYPE_VIDEO
from downloader import (
    DownloadCancelledError,
    DownloadEventKind,
    DownloadRequest,
    DownloadResult,
    DownloadService,
    DownloadServiceError,
    build_download_command,
    locate_tools,
    classify_download_error,
)
from local_files import LocalFilesError
import pdf_to_docx
from tests.download_network_fixtures import local_media_endpoint
from tests.pdf_word_fixtures import make_pdf
from tests.test_media_tools import (
    ControlledProcess,
    MediaOperationCancelled,
    MediaServiceTestCase,
    MediaToolsService,
)


class DownloadHttpErrorsTests(unittest.TestCase):
    def test_http_status_is_not_reported_as_connection_failure(self):
        for code, expected in (
            (404, "indisponível"),
            (410, "indisponível"),
            (403, "acesso"),
            (429, "solicitações"),
            (500, "servidor"),
            (503, "servidor"),
            (418, "HTTP"),
        ):
            with self.subTest(code=code):
                message = classify_download_error(
                    f"ERROR: Unable to download webpage: HTTP Error {code}: failure"
                )
                self.assertIn(expected, message)
                self.assertNotIn("acessar a internet", message)

    def test_connection_errors_keep_their_existing_message(self):
        for reason in ("timed out", "Failed to resolve", "connection refused"):
            self.assertIn("internet", classify_download_error(reason))


class VerifiedHeightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="goal15-staging-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.logger = logging.getLogger("goal15-staging")
        self.logger.addHandler(logging.NullHandler())
        self.service = DownloadService(self.root, self.logger)
        self.addCleanup(self.service.close)
        self.command = build_download_command(
            DownloadRequest(
                "https://example.invalid/own.mp4", CONTENT_TYPE_VIDEO, "720p"
            ),
            locate_tools(self.root),
            self.root,
        )

    def fake_download(self, command, existing, destination):
        self.assertIn("[height<=?720]", command[command.index("--format") + 1])
        self.assertEqual(command[-1], "https://example.invalid/own.mp4")
        file = destination / "video.mp4"
        file.write_bytes(b"synthetic-video")
        return DownloadResult(file, False)

    def verify(self, height):
        with (
            patch.object(self.service, "_execute", side_effect=self.fake_download),
            patch.object(self.service, "_probe_video_height", return_value=height),
        ):
            return self.service._download_verified_height(self.command, self.root, 720)

    def test_exact_height_limit_is_allowed_and_staging_removed(self):
        result = self.verify(720)
        self.assertEqual(result.file_path.read_bytes(), b"synthetic-video")
        self.assertEqual(list(self.root.iterdir()), [result.file_path])

    def test_existing_file_is_never_overwritten(self):
        target = self.root / "video.mp4"
        target.write_bytes(b"original-existing")
        with self.assertRaises(DownloadServiceError):
            self.verify(360)
        self.assertEqual(target.read_bytes(), b"original-existing")
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_oversized_video_is_not_published_and_staging_removed(self):
        with self.assertRaisesRegex(DownloadServiceError, "720p"):
            self.verify(1080)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unverifiable_video_is_not_published(self):
        with (
            patch.object(self.service, "_execute", side_effect=self.fake_download),
            patch.object(
                self.service,
                "_probe_video_height",
                side_effect=DownloadServiceError("resolução desconhecida"),
            ),
        ):
            with self.assertRaises(DownloadServiceError):
                self.service._download_verified_height(self.command, self.root, 720)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancel_after_probe_prevents_publication(self):
        def probe(path):
            self.service._cancel_event.set()
            return 360

        with (
            patch.object(self.service, "_execute", side_effect=self.fake_download),
            patch.object(self.service, "_probe_video_height", side_effect=probe),
        ):
            with self.assertRaises(DownloadCancelledError):
                self.service._download_verified_height(self.command, self.root, 720)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_or_malformed_resolution_fails_closed(self):
        for output in (
            {},
            {"streams": []},
            {"streams": [{"height": None}]},
            {"streams": [{"height": True}]},
            {"streams": ["not-a-stream"]},
        ):
            with self.subTest(output=output), self.assertRaises((ValueError, KeyError)):
                self.service._check_resolution_probe(0, json.dumps(output))

    def test_resolution_probe_timeout_stops_only_owned_process(self):
        process = ControlledProcess(["ffprobe"])
        process.stdout, process.stderr = StringIO(), StringIO()

        def stop(owned):
            self.assertIs(owned, process)
            process.force_finish(-1)

        with (
            patch("downloader.subprocess.Popen", return_value=process),
            patch("downloader.time.monotonic", side_effect=[0, 16]),
            patch.object(
                self.service, "_terminate_process_tree", side_effect=stop
            ) as terminate,
        ):
            with self.assertRaisesRegex(DownloadServiceError, "confirmar a resolução"):
                self.service._probe_video_height(self.root / "synthetic.mp4")
        terminate.assert_called_once_with(process)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_cancellation_interrupts_resolution_probe(self):
        process = ControlledProcess(["ffprobe"])
        process.stdout, process.stderr = StringIO(), StringIO()

        def communicate(**kwargs):
            self.service._cancel_event.set()
            raise subprocess.TimeoutExpired("ffprobe", 0.1)

        process.communicate = communicate
        with (
            patch("downloader.subprocess.Popen", return_value=process),
            patch.object(
                self.service,
                "_terminate_process_tree",
                side_effect=lambda owned: owned.force_finish(-1),
            ),
        ):
            with self.assertRaises(DownloadCancelledError):
                self.service._probe_video_height(self.root / "synthetic.mp4")
        self.assertIsNotNone(process.poll())


class WordOutputErrorsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="goal15-word-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "original.pdf"
        make_pdf(self.source)
        self.before = self.source.read_bytes()
        self.service = pdf_to_docx.PdfToDocxService()

    def assert_output_error(self, destination):
        with self.assertRaises(pdf_to_docx.PdfToDocxError) as caught:
            self.service.convert(self.source, destination)
        self.assertEqual(
            caught.exception.code, pdf_to_docx.DocxErrorCode.OUTPUT_INVALID
        )
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertFalse(list(self.root.glob(".edudownloader-word-*")))

    def test_missing_destination_directory(self):
        self.assert_output_error(self.root / "missing" / "output.docx")

    def test_directory_used_as_destination(self):
        directory = self.root / "directory.docx"
        directory.mkdir()
        self.assert_output_error(directory)

    def test_relative_destination(self):
        self.assert_output_error(Path("relative.docx"))

    def test_destination_permission_failure(self):
        with patch(
            "pdf_to_docx.validate_local_output_path",
            side_effect=LocalFilesError("Sem permissão"),
        ):
            self.assert_output_error(self.root / "output.docx")

    def test_write_permission_failure_preserves_existing_output(self):
        output = self.root / "output.docx"
        output.write_bytes(b"existing-result")
        with patch("pdf_to_docx.tempfile.mkstemp", side_effect=PermissionError):
            with self.assertRaises(pdf_to_docx.PdfToDocxError) as caught:
                self.service.convert(self.source, output, overwrite=True)
        self.assertEqual(
            caught.exception.code, pdf_to_docx.DocxErrorCode.OUTPUT_INVALID
        )
        self.assertEqual(output.read_bytes(), b"existing-result")
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_late_destination_revalidation_preserves_existing_output(self):
        output = self.root / "output.docx"
        output.write_bytes(b"previous")
        validate = pdf_to_docx.validate_local_output_path
        calls = []

        def check(*args, **kwargs):
            calls.append(args)
            if len(calls) > 1:
                raise LocalFilesError("Destination changed")
            return validate(*args, **kwargs)

        with patch("pdf_to_docx.validate_local_output_path", side_effect=check):
            with self.assertRaises(pdf_to_docx.PdfToDocxError) as caught:
                self.service.convert(self.source, output, overwrite=True)
        self.assertEqual(
            caught.exception.code, pdf_to_docx.DocxErrorCode.OUTPUT_INVALID
        )
        self.assertEqual(output.read_bytes(), b"previous")
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertFalse(list(self.root.glob(".edudownloader-word-*")))


class MediaExternalCancellationTests(MediaServiceTestCase):
    def test_token_after_initial_progress_prevents_conversion(self):
        token = threading.Event()
        calls = []
        with patch.object(
            self.service, "_run_command", side_effect=self._successful_runner(calls)
        ):
            with self.assertRaises(MediaOperationCancelled):
                self.service.video_to_mp3(
                    self.source,
                    self.output,
                    cancel_event=token,
                    on_progress=lambda progress: token.set(),
                )
        self.assertEqual(len(calls), 1)  # Input probe only; no encoding.
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_token_during_validation_preserves_previous_output(self):
        token = threading.Event()
        self.output.write_bytes(b"previous")

        def validate(path, tools):
            token.set()
            return 2.5

        with (
            patch.object(
                self.service, "_run_command", side_effect=self._successful_runner([])
            ),
            patch.object(self.service, "_validate_mp3", side_effect=validate),
        ):
            with self.assertRaises(MediaOperationCancelled):
                self.service.video_to_mp3(
                    self.source, self.output, overwrite=True, cancel_event=token
                )
        self.assertEqual(self.output.read_bytes(), b"previous")
        self.assertFalse(list(self.root.glob(".*.tmp.mp3")))

    def test_token_cancels_a_silent_owned_process(self):
        token = threading.Event()
        process = ControlledProcess(["ffprobe"], block=True)
        errors = []
        self.service._begin_operation(token)

        def run():
            try:
                self.service._run_command(["ffprobe"])
            except BaseException as error:
                errors.append(error)
            finally:
                self.service._finish_operation()

        with patch("media_tools.subprocess.Popen", return_value=process):
            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(process.communicate_started.wait(2))
            token.set()
            worker.join(2)
            ended = not worker.is_alive()
            if not ended:
                process.force_finish()  # Always release the test's synthetic process.
                worker.join(3)
        self.assertTrue(ended, "External cancellation did not stop a silent process")
        self.assertIsInstance(errors[0], MediaOperationCancelled)
        self.assertEqual(process.terminate_calls, 1)

    def test_cancelled_token_does_not_poison_next_operation(self):
        token = threading.Event()
        with patch.object(
            self.service, "_run_command", side_effect=self._successful_runner([])
        ):
            with self.assertRaises(MediaOperationCancelled):
                self.service.video_to_mp3(
                    self.source,
                    self.output,
                    cancel_event=token,
                    on_progress=lambda progress: token.set(),
                )
            self.assertIsNone(self.service._cancel_monitor)
            self.service.video_to_mp3(self.source, self.output)
        self.assertTrue(self.output.is_file())
        self.assertFalse(self.service.request_cancel())


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_head(self):
        location = getattr(self.server, "fixture_redirects", {}).get(self.path)
        if location is None:
            return super().send_head()
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return None


class NativeDirectVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Path(__file__).resolve().parents[1]
        if not all(
            (cls.app / name).is_file()
            for name in ("ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe", "deno.exe")
        ):
            raise unittest.SkipTest("Native download tools unavailable")
        cls.temp = tempfile.TemporaryDirectory(prefix="goal15-native-")
        cls.root = Path(cls.temp.name)
        for name, size in (("low", "640x360"), ("high", "1920x1080")):
            subprocess.run(
                [
                    str(cls.app / "ffmpeg.exe"),
                    "-v",
                    "error",
                    "-nostdin",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=blue:s={size}:r=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440",
                    "-t",
                    "1",
                    "-c:v",
                    "mpeg4",
                    "-c:a",
                    "aac",
                    str(cls.root / (name + ".mp4")),
                ],
                capture_output=True,
                check=True,
                timeout=30,
            )
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(QuietHandler, directory=str(cls.root))
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)
        cls.temp.cleanup()

    def download(self, name, quality, *, case_suffix=""):
        destination = self.root / (self._testMethodName + case_suffix)
        destination.mkdir()
        logger = logging.getLogger("goal15-native")
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        service = DownloadService(self.app, logger)
        source = self.root / (name + ".mp4")
        before = source.read_bytes()
        try:
            with local_media_endpoint(self.server):
                service.start(
                    DownloadRequest(
                        f"http://127.0.0.1:{self.server.server_port}/{name}.mp4",
                        CONTENT_TYPE_VIDEO,
                        quality,
                        destination,
                    )
                )
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        event = service.events.get_nowait()
                    except Empty:
                        time.sleep(0.025)
                        continue
                    if event.kind in (
                        DownloadEventKind.COMPLETED,
                        DownloadEventKind.ERROR,
                        DownloadEventKind.CANCELLED,
                    ):
                        return event, destination
                self.fail("Download did not finish")
        finally:
            service.close(timeout=8)
            self.assertFalse(service.is_running)
            self.assertEqual(source.read_bytes(), before)

    def test_360p_direct_video_with_missing_height_satisfies_720p_limit(self):
        event, destination = self.download("low", "720p")
        self.assertEqual(event.kind, DownloadEventKind.COMPLETED, str(event.payload))
        self.assertTrue(event.payload.file_path.is_file())
        self.assertFalse(list(destination.rglob("*.part")))

    def test_1080p_direct_video_cannot_bypass_720p_limit(self):
        event, destination = self.download("high", "720p")
        self.assertEqual(event.kind, DownloadEventKind.ERROR)
        self.assertFalse(list(destination.rglob("*.mp4")))

    def test_best_quality_preserves_direct_video_support(self):
        event, _ = self.download("high", "Melhor qualidade")
        self.assertEqual(event.kind, DownloadEventKind.COMPLETED, str(event.payload))

    def test_redirects_to_a_different_local_server_or_a_file_do_not_publish(self):
        from http.server import BaseHTTPRequestHandler

        hits = []

        class ForbiddenFixture(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_error(400)

            do_HEAD = do_GET

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), ForbiddenFixture) as forbidden:
            thread = threading.Thread(target=forbidden.serve_forever, daemon=True)
            thread.start()
            _copy = (self.root / "low.mp4").read_bytes()
            for name in ("second-server", "local-file"):
                (self.root / (name + ".mp4")).write_bytes(_copy)
            self.server.fixture_redirects = {
                "/second-server.mp4": f"http://127.0.0.1:{forbidden.server_port}/qa",
                "/local-file.mp4": (self.root / "low.mp4").as_uri(),
            }
            try:
                for name in ("second-server", "local-file"):
                    with self.subTest(name=name):
                        # Use distinct destination roots for both requests.
                        event, output = self.download(
                            name, "Melhor qualidade", case_suffix=name
                        )
                        self.assertEqual(event.kind, DownloadEventKind.ERROR)
                        self.assertEqual(list(output.rglob("*.mp4")), [])
                self.assertEqual(hits, [])
            finally:
                self.server.fixture_redirects.clear()
                forbidden.shutdown()
                thread.join(3)

    def test_native_media_token_at_final_progress_prevents_publication(self):
        token = threading.Event()
        source = self.root / "low.mp4"
        output = self.root / "cancelled-audio.mp3"
        original = source.read_bytes()
        output.write_bytes(b"previous-audio")
        service = MediaToolsService(self.app)

        def progress(sample):
            if sample.processed_seconds > 0:
                token.set()

        with self.assertRaises(MediaOperationCancelled):
            service.video_to_mp3(
                source, output, overwrite=True, cancel_event=token, on_progress=progress
            )
        self.assertTrue(token.is_set())
        self.assertEqual(output.read_bytes(), b"previous-audio")
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(list(self.root.glob(".*.tmp.mp3")))
        self.assertIsNone(service._active_process)
