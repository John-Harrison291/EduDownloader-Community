"""Real local video pixels and hostile/normal DOCX packages for Files previews."""

import json
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event, Timer
import time
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from file_preview import (
    FilePreviewService,
    FilePreviewResult,
    PreviewKind,
    PreviewStatus,
    PreviewCancelled,
)
from local_files import classify_local_file, LocalFileEntry
import video_preview
import word_preview

APP = Path(__file__).resolve().parents[1]
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def entry(path):
    info = path.stat()
    return LocalFileEntry(path, classify_local_file(path), info.st_size, info.st_mtime)


def docx(path, body="", *, xml=None, extra=None):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="'
            + word_preview.MAIN_TYPE
            + '"/></Types>',
        )
        archive.writestr(
            "word/document.xml",
            xml or f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>',
        )
        for name, data in (extra or {}).items():
            archive.writestr(name, data)


def video(path, *, size="320x180", duration="2", codec="mpeg4", intro=False, sar=False):
    source = f"color=c=blue:s={size}:r=20:d={duration}"
    if intro:
        source += ",drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='lt(t,0.3)'"
    if sar:
        source += ",setsar=2"
    command = [
        str(APP / "ffmpeg.exe"),
        "-v",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        source,
        "-c:v",
        codec,
        "-threads",
        "1",
        "-y",
        str(path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))


class WordPreviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="goal3-word-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "Aula ação 你好.docx"
        self.service = FilePreviewService()
        self.addCleanup(self.service.close)

    def preview(self):
        return self.service.create_preview(entry(self.path), self.root)

    def test_paragraphs_titles_breaks_tables_and_external_links_are_text_only(self):
        docx(
            self.path,
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Ciências</w:t></w:r></w:p>'
            "<w:p><w:r><w:t>Primeiro</w:t><w:br/><w:t>Segundo</w:t><w:tab/><w:t>Fim</w:t></w:r></w:p>"
            "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
            "<w:p><w:hyperlink><w:r><w:t>Link apenas textual</w:t></w:r></w:hyperlink></w:p>",
            extra={
                "docProps/core.xml": '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Plano da semana</dc:title></cp:coreProperties>',
                "word/_rels/document.xml.rels": '<Relationships><Relationship Target="https://example.invalid/never-request" TargetMode="External"/></Relationships>',
                "word/embeddings/ignored.bin": b"never executed",
            },
        )
        original = self.path.read_bytes()
        names = set(self.root.iterdir())
        result = self.preview()
        self.assertEqual(result.status, PreviewStatus.SUCCESS)
        self.assertEqual(result.kind, PreviewKind.WORD_TEXT)
        self.assertEqual(
            result.text, "Ciências\nPrimeiro\nSegundo\tFim\nA\tB\nLink apenas textual"
        )
        self.assertEqual(result.title, "Plano da semana")
        self.assertEqual(original, self.path.read_bytes())
        self.assertEqual(names, set(self.root.iterdir()))

    def test_empty_and_long_documents_are_explicit_and_bounded(self):
        for body in (
            "",
            "<w:p/>",
            '<w:p><w:r><w:t xml:space="preserve">   </w:t><w:br/><w:tab/></w:r></w:p>',
            "<w:p><w:r><w:drawing/></w:r></w:p>",
        ):
            docx(self.path, body)
            result = self.preview()
            self.assertEqual(result.text, "")
            self.assertIn("sem texto", result.message)
        docx(
            self.path,
            "".join(
                f"<w:p><w:r><w:t>Parágrafo número {i} conteúdo da aula</w:t></w:r></w:p>"
                for i in range(2000)
            ),
        )
        result = self.preview()
        self.assertEqual(result.status, PreviewStatus.SUCCESS)
        self.assertEqual(len(result.text), word_preview.MAX_TEXT)
        self.assertTrue(result.truncated)

    def test_malformed_truncated_legacy_and_unsupported_packages(self):
        cases = [b"broken", b"PK\x03\x04broken"]
        for data in cases:
            self.path.write_bytes(data)
            self.assertEqual(self.preview().status, PreviewStatus.INVALID)
        for xml in ("<broken>", "<document/>", f'<w:document xmlns:w="{W}"/>'):
            docx(self.path, xml=xml)
            self.assertEqual(self.preview().status, PreviewStatus.INVALID)
        legacy = self.root / "legado.doc"
        legacy.write_bytes(b"synthetic-old-document")
        result = self.service.create_preview(entry(legacy), self.root)
        self.assertEqual(result.status, PreviewStatus.UNSUPPORTED)
        self.assertIn("Abrir", result.message)

    def test_entities_traversal_duplicates_zip_bombs_and_deep_xml_are_refused(self):
        docx(
            self.path,
            xml=f'<!DOCTYPE x [<!ENTITY x "expanded">]><w:document xmlns:w="{W}"><w:body><w:p>&x;</w:p></w:body></w:document>',
        )
        self.assertEqual(self.preview().status, PreviewStatus.INVALID)
        docx(self.path, extra={"../outside.txt": "unsafe"})
        self.assertEqual(self.preview().status, PreviewStatus.INVALID)
        docx(self.path, extra={"word/bomb.bin": "0" * 100_000})
        self.assertEqual(self.preview().status, PreviewStatus.TOO_LARGE)
        docx(self.path, "<w:sdt>" * 70 + "<w:p/>" + "</w:sdt>" * 70)
        self.assertEqual(self.preview().status, PreviewStatus.TOO_LARGE)
        docx(self.path)
        with zipfile.ZipFile(self.path, "a") as archive:
            with self.assertWarns(UserWarning):
                archive.writestr("word/document.xml", "duplicate")
        self.assertEqual(self.preview().status, PreviewStatus.INVALID)

    def test_limits_cancellation_removed_and_changed_during_read(self):
        docx(self.path, "<w:p><w:r><w:t>Original</w:t></w:r></w:p>")
        token = Event()
        token.set()
        self.assertEqual(
            self.service.create_cancellable_preview(
                entry(self.path), self.root, token
            ).status,
            PreviewStatus.UNAVAILABLE,
        )
        with patch("word_preview.MAX_MEMBERS", 1):
            self.assertEqual(self.preview().status, PreviewStatus.TOO_LARGE)
        self.service.close()
        self.service = FilePreviewService()
        original = word_preview.preview_word

        def removed(path, cancel):
            result = original(path, cancel)
            path.unlink()
            return result

        with patch("word_preview.preview_word", side_effect=removed):
            self.assertEqual(self.preview().status, PreviewStatus.UNAVAILABLE)
        docx(self.path, "<w:p><w:r><w:t>Restored</w:t></w:r></w:p>")

        def changed(path, cancel):
            result = original(path, cancel)
            docx(path, "<w:p/>")
            return result

        with patch("word_preview.preview_word", side_effect=changed):
            self.assertEqual(self.preview().status, PreviewStatus.UNAVAILABLE)

    def test_cache_reuses_text_but_file_replacement_invalidates_it(self):
        docx(self.path, "<w:p><w:r><w:t>Primeiro</w:t></w:r></w:p>")
        with patch(
            "word_preview.preview_word", wraps=word_preview.preview_word
        ) as render:
            first = self.preview()
            self.assertIs(first, self.preview())
            docx(self.path, "<w:p><w:r><w:t>Outro documento</w:t></w:r></w:p>")
            self.assertEqual(self.preview().text, "Outro documento")
            self.assertEqual(render.call_count, 2)

    def test_word_byte_element_and_encoding_guards(self):
        docx(self.path, "<w:p><w:r><w:t>Conteúdo</w:t></w:r></w:p>")
        for constant in ("MAX_DOCX_BYTES", "MAX_XML_BYTES", "MAX_ELEMENTS"):
            with self.subTest(limit=constant), patch("word_preview." + constant, 1):
                self.assertEqual(self.preview().status, PreviewStatus.TOO_LARGE)
        xml = f'<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY x "unsafe">]><w:document xmlns:w="{W}"><w:body/></w:document>'
        docx(self.path, xml=xml.encode("utf-16"))
        self.assertEqual(self.preview().status, PreviewStatus.INVALID)


class NativeVideoTests(unittest.TestCase):
    def setUp(self):
        if not (APP / "ffmpeg.exe").is_file() or not (APP / "ffprobe.exe").is_file():
            self.skipTest("Local media tools unavailable")
        temporary = tempfile.TemporaryDirectory(prefix="goal3-video-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = FilePreviewService(media_dir=APP)
        self.addCleanup(self.service.close)

    def test_frame_skips_black_intro_preserves_source_and_cache(self):
        path = self.root / "Vídeo ação 你好.mp4"
        video(path, intro=True)
        original = path.read_bytes()
        names = set(self.root.iterdir())
        with patch(
            "video_preview.preview_video", wraps=video_preview.preview_video
        ) as render:
            result = self.service.create_preview(entry(path), self.root)
            self.assertIs(result, self.service.create_preview(entry(path), self.root))
            self.assertEqual(render.call_count, 1)
        self.assertEqual(result.status, PreviewStatus.SUCCESS, result.message)
        self.assertEqual(result.kind, PreviewKind.VIDEO_FRAME)
        with Image.frombytes(
            "RGBA", (result.width, result.height), result.rgba
        ) as image:
            r, g, b, a = image.getpixel((result.width // 2, result.height // 2))
            self.assertGreater(b, 200)
            self.assertLess(r, 20)
        self.assertAlmostEqual(result.width / result.height, 320 / 180, delta=0.02)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(names, set(self.root.iterdir()))

    def test_recognized_formats_short_portrait_and_sample_aspect(self):
        for suffix, codec in (
            (".mp4", "mpeg4"),
            (".mkv", "ffv1"),
            (".webm", "libvpx-vp9"),
            (".avi", "mpeg4"),
            (".mov", "mpeg4"),
            (".m4v", "mpeg4"),
        ):
            with self.subTest(suffix=suffix):
                path = self.root / ("curto" + suffix)
                video(path, size="64x96", duration="0.05", codec=codec)
                result = self.service.create_preview(entry(path), self.root)
                self.assertEqual(result.status, PreviewStatus.SUCCESS, result.message)
                self.assertAlmostEqual(result.width / result.height, 2 / 3, delta=0.02)
        path = self.root / "anamorphic.mp4"
        video(path, size="96x64", duration="0.2", sar=True)
        result = self.service.create_preview(entry(path), self.root)
        self.assertEqual(result.status, PreviewStatus.SUCCESS, result.message)
        self.assertAlmostEqual(result.width / result.height, 3, delta=0.03)

    def test_corrupt_no_stream_missing_tools_timeout_and_unsupported_dimensions(self):
        path = self.root / "broken.mp4"
        path.write_bytes(b"not a movie")
        self.assertEqual(
            self.service.create_preview(entry(path), self.root).status,
            PreviewStatus.INVALID,
        )
        missing = FilePreviewService(media_dir=self.root)
        self.assertEqual(
            missing.create_preview(entry(path), self.root).status,
            PreviewStatus.UNAVAILABLE,
        )
        for data in (
            {"streams": []},
            {"streams": [{"width": 99999, "height": 200}]},
            {"streams": [{"width": 10, "height": 10}], "format": {"duration": "NaN"}},
        ):
            with patch("video_preview._run", return_value=json.dumps(data).encode()):
                self.assertEqual(
                    video_preview.preview_video(path, APP).status, PreviewStatus.INVALID
                )
        with patch("video_preview._run", side_effect=TimeoutError):
            result = video_preview.preview_video(path, APP)
            self.assertEqual(result.status, PreviewStatus.UNAVAILABLE)
            self.assertIn("demorou", result.message)

    def test_video_replacement_invalidates_frame_and_empty_decode_is_controlled(self):
        path = self.root / "replace.mp4"
        video(path, size="320x180", duration="0.2")
        first = self.service.create_preview(entry(path), self.root)
        video(path, size="64x96", duration="0.2")
        second = self.service.create_preview(entry(path), self.root)
        self.assertGreater(first.width, first.height)
        self.assertLess(second.width, second.height)
        with patch(
            "video_preview._run",
            side_effect=[b'{"streams":[{"width":10,"height":10}]}', b"", b""],
        ):
            self.assertEqual(
                video_preview.preview_video(path, APP).status, PreviewStatus.INVALID
            )


class PreviewResourceTests(unittest.TestCase):
    def test_unresponsive_termination_uses_kill_only_for_owned_process(self):
        class Process:
            def __init__(self):
                self.stdout = BytesIO()
                self.returncode = None
                self.terminated = False
                self.killed = False

            def communicate(self, timeout):
                raise subprocess.TimeoutExpired("owned", timeout)

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True

            def wait(self, timeout):
                if self.returncode is None:
                    raise subprocess.TimeoutExpired("owned", timeout)
                return self.returncode

            def kill(self):
                self.killed = True
                self.returncode = -9

        process = Process()
        with patch("video_preview.subprocess.Popen", return_value=process):
            with self.assertRaises(TimeoutError):
                video_preview._run(
                    ["owned-fixture"], None, time.monotonic() + 0.01, max_bytes=16
                )
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertTrue(process.stdout.closed)

    def test_native_silent_process_timeout_and_cancel_are_reaped(self):
        popen = subprocess.Popen
        owned = []

        def start(*args, **kwargs):
            process = popen(*args, **kwargs)
            owned.append(process)
            return process

        for cancel in (False, True):
            token = Event()
            timer = Timer(0.1, token.set)
            if cancel:
                timer.start()
            try:
                with patch("video_preview.subprocess.Popen", side_effect=start):
                    with self.assertRaises(
                        PreviewCancelled if cancel else TimeoutError
                    ):
                        video_preview._run(
                            [sys.executable, "-c", "import time;time.sleep(30)"],
                            token,
                            time.monotonic() + 0.2,
                            max_bytes=128,
                        )
            finally:
                timer.cancel()
            self.assertIsNotNone(owned[-1].poll())
            self.assertTrue(owned[-1].stdout.closed)

    def test_cache_is_bounded_and_close_releases_pixels(self):
        with tempfile.TemporaryDirectory(prefix="goal3-cache-") as temporary:
            root = Path(temporary)
            service = FilePreviewService()
            raster = FilePreviewResult(
                PreviewStatus.SUCCESS,
                PreviewKind.VIDEO_FRAME,
                512,
                512,
                b"\xff" * (512 * 512 * 4),
            )
            with patch("video_preview.preview_video", return_value=raster):
                for i in range(80):
                    path = root / f"{i}.mp4"
                    path.write_bytes(b"own-fixture")
                    self.assertEqual(
                        service.create_preview(entry(path), root).status,
                        PreviewStatus.SUCCESS,
                    )
                    self.assertLessEqual(service._cache_bytes, 16 * 1024 * 1024)
                    self.assertLessEqual(len(service._cache), 32)
            service.close()
            self.assertFalse(service._cache)
            self.assertEqual(service._cache_bytes, 0)
