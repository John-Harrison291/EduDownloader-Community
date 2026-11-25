"""Real Tk checks: rendering stays off-thread, selection and resources persist."""

from pathlib import Path
import gc
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import ImageTk

from pdf_preview_ui import PagePreviewPane
from pdf_previews import PageRenderer, PreviewWorker, PreviewSpec
from pdf_tools import PdfToolsService
from tests.test_pdf_previews import make_pdf
from ui_lifecycle import AppRoot
from ui_pages import PdfToolsPage, PdfPageActions


class PreviewTkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = AppRoot()
        except tk.TclError as error:
            raise unittest.SkipTest(str(error)) from error
        cls.root.geometry("900x800+40+40")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        # Previous test cases leave destroyed widget/font reference cycles.
        # Collect them on their Tk owner before a renderer allocation can run
        # their Font.__del__ in its worker (which waits for a Tk mainloop).
        gc.collect()
        temporary = tempfile.TemporaryDirectory(prefix="goal2-tk-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "real.pdf"
        make_pdf(
            self.path,
            ((240, 360, (1, 0, 0)), (420, 180, (0, 1, 0)), (200, 280, (0, 0, 1))),
        )
        self.worker = PreviewWorker()
        self.pane = PagePreviewPane(self.root, self.worker)
        self.pane.pack(fill="both", expand=True)
        self.owner = threading.get_ident()

    def tearDown(self):
        self.pane.close()
        self.worker.close()
        self.pane.destroy()
        if self.worker.thread:
            self.worker.thread.join(3)
            self.assertFalse(self.worker.thread.is_alive())

    def wait(self, predicate, seconds=10):
        # Drive the same event loop as the app. Tk's update() drains a queue
        # that can be replenished indefinitely, so it can hide the deadline.
        poll_id = None
        matched = False
        error = None

        def poll():
            nonlocal poll_id, matched, error
            poll_id = None
            try:
                matched = bool(predicate())
            except Exception as exc:
                error = exc
            if matched or error is not None:
                self.root.quit()
            else:
                poll_id = self.root.after(5, poll)

        timeout_id = self.root.after(round(seconds * 1000), self.root.quit)
        poll_id = self.root.after(0, poll)
        try:
            self.root.mainloop()
        finally:
            self.root.after_cancel(timeout_id)
            if poll_id is not None:
                self.root.after_cancel(poll_id)
        if error is not None:
            raise error
        self.assertTrue(matched, "Preview did not reach expected state")

    def loaded(self, index=0):
        return (
            self.pane._bundle is not None
            and self.pane._bundle.index == index
            and self.pane._bundle.main is not None
            and self.pane._photo is not None
            and self.pane._poll_id is None
        )

    def test_actual_photo_images_are_created_only_on_tk_thread(self):
        original = ImageTk.PhotoImage
        callers = []

        def photo(*args, **kwargs):
            callers.append(threading.get_ident())
            return original(*args, **kwargs)

        with patch("pdf_preview_ui.ImageTk.PhotoImage", side_effect=photo):
            self.pane.set_context(PreviewSpec("pdf", (self.path,)))
            self.wait(lambda: self.loaded())
        self.assertTrue(callers)
        self.assertEqual(set(callers), {self.owner})
        self.assertIsNotNone(self.pane._photo)
        self.assertEqual(self.pane.total, 3)

    def test_failed_refresh_removes_previous_page_image(self):
        self.pane.set_context(PreviewSpec("pdf", (self.path,)))
        self.wait(lambda: self.loaded())
        self.path.unlink()
        self.pane.refresh()
        self.wait(lambda: self.pane._poll_id is None)
        self.assertIsNone(self.pane._photo)
        self.assertIsNone(self.pane._bundle.main)
        self.assertTrue(self.pane._bundle.error)
        self.assertEqual(self.pane.canvas.itemcget(self.pane._image_item, "image"), "")

    def test_selection_changes_reuse_pixels_and_tk_thumbnails(self):
        self.pane.set_context(PreviewSpec("pdf", (self.path,)))
        self.wait(lambda: self.loaded())
        rendered = self.worker.renderer.renders
        before = [button.cget("image") for button in self.pane.thumbs]
        self.pane.set_selection((3, 1, 3))
        self.assertEqual(self.worker.renderer.renders, rendered)
        self.assertEqual(before, [button.cget("image") for button in self.pane.thumbs])
        self.assertIn("✓", self.pane.thumbs[0].cget("text"))
        self.assertNotIn("✓", self.pane.thumbs[1].cget("text"))
        self.assertIn("✓", self.pane.thumbs[2].cget("text"))

    def test_zoom_navigation_fit_reset_and_latest_document(self):
        self.pane.set_context(PreviewSpec("pdf", (self.path,)))
        self.wait(lambda: self.loaded())
        self.pane.goto(1)
        self.wait(lambda: self.loaded(1))
        self.pane.change_zoom(1.25)
        generation = self.pane.generation
        self.wait(lambda: self.pane._poll_id is None)
        self.assertGreater(self.pane.zoom, 1)
        self.assertEqual(self.pane.generation, generation)
        self.pane.fit()
        self.assertEqual(self.pane.zoom, 1)
        self.pane.reset()
        self.assertEqual(self.pane.index, 0)
        other = self.path.with_name("other.pdf")
        make_pdf(other, ((200, 220, (0, 0, 1)),))
        for _ in range(20):
            self.pane.set_context(PreviewSpec("pdf", (self.path,)))
            self.pane.set_context(PreviewSpec("pdf", (other,)))
        self.wait(lambda: self.loaded() and self.pane.total == 1)
        self.assertIn("other.pdf", self.pane.caption.cget("text"))
        self.assertEqual(self.pane._bundle.main.rgb[2], 255)

    def test_clearing_and_closing_drops_images_callbacks_and_cache(self):
        self.pane.set_context(PreviewSpec("pdf", (self.path,)))
        self.pane.set_context(None)
        self.assertIsNone(self.pane._poll_id)
        self.assertIsNone(self.pane._photo)
        self.assertFalse(self.pane._thumb_sources)
        self.pane.close()
        self.worker.close()
        if self.worker.thread:
            self.worker.thread.join(3)
        self.assertEqual(self.worker.renderer.cache.bytes, 0)
        self.assertFalse(self.worker.results)

    def test_integrated_pdf_tools_keep_existing_order_and_extraction_contract(self):
        self.pane.pack_forget()
        actions = PdfPageActions(*(lambda *args: True for _ in range(5)))
        page = PdfToolsPage(self.root, actions=actions, service=PdfToolsService())
        page.pack(fill="both", expand=True)
        try:
            page.merge_files.set_paths([self.path])
            page._open_tool("Juntar PDFs")
            self.wait(lambda: page.merge_page_preview._bundle is not None)
            self.assertEqual(page.merge_files.paths, (self.path,))
            self.assertEqual(page.merge_page_preview.page_label.cget("text"), "PDF")
            self.assertIn("3 páginas", page._merge_detail_for_path(self.path))
            page._prepare_extract_source(self.path)
            page._extract_selection.set("3,1,3")
            self.assertEqual(page.extract_page_preview.selection, frozenset())
            self.wait(lambda: page._extract_page_count == 3)
            self.assertEqual(page.extract_page_preview.selection, frozenset({1, 3}))
            page._open_tool("PDF → Imagens")
            page._prepare_pdf_images_source(self.path)
            page._pdf_images_scope.set("Páginas específicas")
            page._pdf_images_selection.set("2")
            self.wait(lambda: page._pdf_images_page_count == 3)
            self.assertEqual(page.pdf_images_page_preview.selection, frozenset({2}))
        finally:
            page.close()
            page.destroy()
            if page._page_preview_worker.thread:
                page._page_preview_worker.thread.join(5)
                self.assertFalse(page._page_preview_worker.thread.is_alive())

    def test_tool_switch_while_worker_is_rendering_preserves_each_real_document(self):
        self.pane.pack_forget()
        started, release = threading.Event(), threading.Event()

        class ControlledRenderer(PageRenderer):
            def bundle(self, *args):
                if not started.is_set():
                    started.set()
                    if not release.wait(5):
                        raise TimeoutError("Fixture renderer was not released")
                return super().bundle(*args)

        actions = PdfPageActions(*(lambda *args: True for _ in range(5)))
        page = PdfToolsPage(self.root, actions=actions, service=PdfToolsService())
        page.pack(fill="both", expand=True)
        worker = page._page_preview_worker
        worker.renderer = ControlledRenderer()
        original = self.path.read_bytes()
        try:
            page.merge_files.set_paths([self.path])
            page._open_tool("Juntar PDFs")
            self.assertTrue(started.wait(2))
            thread = worker.thread
            page._open_tool("Extrair páginas")
            page._prepare_extract_source(self.path)
            self.wait(lambda: page._extract_page_count == 3)
            page._extract_selection.set("2")
            page._open_tool("PDF → Imagens")
            page._prepare_pdf_images_source(self.path)
            self.wait(lambda: page._pdf_images_page_count == 3)
            self.assertIs(worker.thread, thread)
            self.assertLessEqual(len(worker.pending), 3)
            release.set()
            panes = (
                page.merge_page_preview,
                page.extract_page_preview,
                page.pdf_images_page_preview,
            )
            self.wait(
                lambda: all(
                    p._bundle and p._photo and p._poll_id is None for p in panes
                )
            )
            self.assertEqual(page.tab_view.get(), "PDF → Imagens")
            self.assertEqual([p.total for p in panes], [1, 3, 3])
            self.assertTrue(all(p._bundle.main.rgb for p in panes))
            self.assertEqual(page.extract_page_preview.selection, frozenset({2}))
            self.assertEqual(self.path.read_bytes(), original)
        finally:
            release.set()
            page.close()
            page.destroy()
            if worker.thread:
                worker.thread.join(5)
                self.assertFalse(worker.thread.is_alive())
