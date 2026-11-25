"""Real Files selection, native preview ownership and cancellation in Tk."""

from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import customtkinter as ctk
from PIL import Image

from file_preview import (
    FilePreviewService,
    FilePreviewResult,
    PreviewStatus,
    PreviewKind,
)
from local_files import list_local_files
from tests.test_file_content_previews import APP, docx, video
from tests.test_file_preview import _write_odt
from tests.test_pdf_previews import make_pdf
from ui_pages import FilesPage, FilesPageActions


class FilesContentTkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = ctk.CTk()
        except tk.TclError as error:
            raise unittest.SkipTest(str(error)) from error
        cls.root.geometry("1000x750+20+20")
        cls.root.withdraw()
        cls.fixtures = tempfile.TemporaryDirectory(prefix="goal3-tk-source-")
        cls.movie = Path(cls.fixtures.name) / "own.mp4"
        if (APP / "ffmpeg.exe").is_file():
            video(cls.movie, duration="0.5")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        cls.fixtures.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="goal3-tk-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.document = self.directory / "Aula ação 你好.docx"
        docx(
            self.document,
            "<w:p><w:r><w:t>Plano de Ciências</w:t></w:r></w:p><w:p><w:r><w:t>Conteúdo para conferir</w:t></w:r></w:p>",
        )
        self.movie_path = self.directory / "Vídeo próprio.mp4"
        if self.movie.exists():
            self.movie_path.write_bytes(self.movie.read_bytes())
        self.image = self.directory / "Foto.png"
        with Image.new("RGB", (80, 40), "red") as image:
            image.save(self.image)
        make_pdf(self.directory / "PDF.pdf")
        (self.directory / "Legado.doc").write_bytes(b"legacy-fixture")
        self.opened = []
        self.service = FilePreviewService(media_dir=APP)
        self.page = FilesPage(
            self.root,
            actions=FilesPageActions(*(lambda *args: True for _ in range(6))),
            preview_service=self.service,
            get_favorites=lambda: (),
            is_favorite=lambda p: False,
            open_file=lambda selected, directory: (
                self.opened.append(selected.path) or selected.path
            ),
        )
        self.page.pack(fill="both", expand=True)
        self.page._directory = self.directory
        self.page._set_snapshot(list_local_files(self.directory))
        self.wait(
            lambda: len(self.page.file_tree.get_children()) == len(self.page.snapshot)
        )

    def tearDown(self):
        worker = self.page._preview_worker
        self.page.close()
        if worker:
            worker.join(5)
            self.assertFalse(worker.is_alive())
        self.page.destroy()

    def wait(self, predicate, seconds=10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Files preview did not reach expected state")

    def select(self, name):
        item = next(
            item for item, e in self.page._entry_by_item.items() if e.name == name
        )
        self.page.file_tree.selection_set(item)
        self.page._on_tree_selection()

    def available(self):
        return self.page._preview_state.value == "available"

    def text(self):
        return self.page.preview_document.get("1.0", "end-1c")

    def test_odt_selection_reaches_the_preview_worker_and_shows_its_format(self):
        odt = self.directory / "Aula sintética.odt"
        _write_odt(odt)
        self.page._set_snapshot(list_local_files(self.directory))
        self.wait(lambda: any(e.path == odt for e in self.page._entry_by_item.values()))
        self.select(odt.name)
        self.wait(self.available)
        self.assertEqual(self.text(), "Plano de aula")
        self.assertEqual(self.page._preview_caption.get(), "Amostra de texto do ODT")

    def test_real_video_word_pdf_image_and_legacy_keep_actions_and_panel_size(self):
        calls = []
        apply = self.page._apply_preview_result

        def applied(result):
            calls.append(threading.get_ident())
            return apply(result)

        before = (
            self.page.preview_frame.cget("width"),
            self.page.preview_frame.cget("height"),
        )
        with patch.object(self.page, "_apply_preview_result", side_effect=applied):
            self.select(self.document.name)
            self.wait(self.available)
            self.assertIn("Plano de Ciências", self.text())
            before_text = self.text()
            self.page.preview_document.insert("end", "must not edit")
            self.assertEqual(self.text(), before_text)
            self.assertIsNone(self.page._preview_pil_image)
            self.page._open_selected()
            self.assertEqual(self.opened, [self.document])
            if self.movie_path.exists():
                self.select(self.movie_path.name)
                self.wait(self.available)
                self.assertFalse(self.page.preview_document.winfo_manager())
                self.assertEqual(self.text(), "")
                self.assertGreater(
                    self.page._preview_pil_image.getpixel((20, 20))[2], 200
                )
            for name in ("PDF.pdf", "Foto.png"):
                self.select(name)
                self.wait(self.available)
                self.assertIsNotNone(self.page._preview_tk_image)
            self.select("Legado.doc")
            self.assertEqual(self.page._preview_state.value, "unsupported")
            self.assertEqual(self.page.preview_label._label.cget("image"), "")
        self.assertTrue(calls)
        self.assertEqual(set(calls), {threading.get_ident()})
        self.assertEqual(
            before,
            (
                self.page.preview_frame.cget("width"),
                self.page.preview_frame.cget("height"),
            ),
        )

    def test_selected_document_replacement_and_removal_update_without_ui_io(self):
        self.select(self.document.name)
        self.wait(self.available)
        docx(self.document, "<w:p><w:r><w:t>Documento substituído</w:t></w:r></w:p>")
        self.wait(lambda: "Documento substituído" in self.text())
        self.document.unlink()
        self.wait(lambda: self.page._preview_state.value == "unavailable")
        self.assertEqual(self.text(), "")
        self.assertIsNone(self.page._preview_tk_image)

    def test_rapid_selection_and_filtering_cancel_previous_work(self):
        started, ended = threading.Event(), threading.Event()
        original = self.service.create_cancellable_preview

        def slow(entry, directory, cancel):
            if entry.name == self.movie_path.name:
                started.set()
                cancel.wait(3)
                ended.set()
                return FilePreviewResult(
                    PreviewStatus.SUCCESS,
                    PreviewKind.VIDEO_FRAME,
                    1,
                    1,
                    b"\x00\x00\xff\xff",
                )
            return original(entry, directory, cancel)

        with patch.object(self.service, "create_cancellable_preview", side_effect=slow):
            if not self.movie_path.exists():
                self.skipTest("Native video fixture unavailable")
            self.select(self.movie_path.name)
            self.wait(started.is_set)
            worker = self.page._preview_worker
            for _ in range(30):
                self.select("Foto.png")
                self.select(self.document.name)
            self.wait(lambda: self.available() and "Plano de Ciências" in self.text())
            self.assertTrue(ended.is_set())
            self.assertIs(self.page._preview_worker, worker)
            self.assertLessEqual(self.page._preview_requests.qsize(), 1)
            self.assertLessEqual(self.page._preview_results.qsize(), 1)
            self.page._query.set("sem resultado")
            self.page._apply_search_now()
            self.wait(lambda: self.page._selected_entry is None)
            self.assertEqual(self.text(), "")
            self.assertIsNone(self.page._preview_pil_image)

    def test_closing_pending_preview_cancels_token_and_releases_cache(self):
        started, ended = threading.Event(), threading.Event()

        def slow(entry, directory, cancel):
            started.set()
            cancel.wait(3)
            ended.set()
            return FilePreviewResult(PreviewStatus.UNAVAILABLE)

        with patch.object(self.service, "create_cancellable_preview", side_effect=slow):
            self.select(self.document.name)
            self.wait(started.is_set)
            worker = self.page._preview_worker
            self.page.close()
            self.assertTrue(ended.wait(1))
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertFalse(self.service._cache)
            self.assertEqual(self.service._cache_bytes, 0)
            self.assertIsNone(self.page._preview_poll_after_id)
            self.assertIsNone(self.page._preview_tk_image)

    def test_optional_tools_can_be_missing_and_same_file_can_be_retried(self):
        if not self.movie_path.exists():
            self.skipTest("Native video fixture unavailable")
        self.service._media_dir = self.directory
        self.select(self.movie_path.name)
        self.wait(lambda: self.page._preview_state.value == "unavailable")
        self.assertIn("Componentes", self.page._preview_text.get())
        self.assertEqual(self.page.open_button.cget("state"), "normal")
        self.service._media_dir = APP
        self.select(self.movie_path.name)
        self.wait(self.available)
        self.assertIsNotNone(self.page._preview_tk_image)

    def test_word_scroll_does_not_move_the_files_page(self):
        self.root.deiconify()
        try:
            self.page._show_preview_document(
                FilePreviewResult(
                    PreviewStatus.SUCCESS,
                    kind=PreviewKind.WORD_TEXT,
                    text="\n".join(f"Parágrafo {i}" for i in range(200)),
                )
            )
            self.root.update()
            canvas = self.page._parent_canvas
            outer = canvas.yview()
            text_position = self.page.preview_document.yview()
            textbox = self.page.preview_document._textbox
            rootx, rooty = textbox.winfo_rootx() + 5, textbox.winfo_rooty() + 5
            # O hit-test do Windows depende das outras janelas do desktop.
            # Fixe somente esse resultado e envie o evento real ao Tk.
            with patch.object(
                self.root, "winfo_containing", return_value=textbox
            ) as hit:
                textbox.event_generate(
                    "<MouseWheel>", delta=-120, rootx=rootx, rooty=rooty
                )
            hit.assert_called_once_with(rootx, rooty)
            self.root.update()
            self.assertGreater(self.page.preview_document.yview()[0], text_position[0])
            self.assertEqual(canvas.yview(), outer)
        finally:
            self.root.withdraw()
