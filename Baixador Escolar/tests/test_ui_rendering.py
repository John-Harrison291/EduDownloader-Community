"""Regressões de listas incrementais, consultas, prévias e filas da Etapa 2."""

from dataclasses import replace
from pathlib import Path
from queue import Empty, Queue
from types import SimpleNamespace
import random
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk
from PIL import Image

from local_files import LocalFileCategory, LocalFileEntry, LocalFileProjection
from media_tools import MediaConversionProgress
from pdf_tools import PdfOperationProgress, PdfToolsService
from print_layout import Size
from poster_tools import plan_poster
from ui_events import CoalescingQueue
from ui_pages import (
    FilesPage,
    FilesPageActions,
    MediaToolsPage,
    PdfPageActions,
    PdfToolsPage,
    SettingsPage,
    _OrderedPathList,
    _PdfOperationUiState,
    _PosterPreview,
)


def noop(*_args):
    return None


class CoalescingQueueTests(unittest.TestCase):
    def test_burst_uses_one_slot_and_preserves_terminal_order(self):
        events = CoalescingQueue(
            lambda event: "progress" if event[0] == "progress" else None
        )
        for index in range(100_000):
            events.put(("progress", index))
        self.assertEqual(events.qsize(), 1)
        events.put(("phase", "install"))
        events.put(("progress", 100_000))
        events.put(("result", "failed"))
        self.assertEqual(
            [events.get_nowait() for _ in range(4)],
            [
                ("progress", 99_999),
                ("phase", "install"),
                ("progress", 100_000),
                ("result", "failed"),
            ],
        )
        self.assertTrue(events.empty())
        with self.assertRaises(Empty):
            events.get_nowait()

    def test_generations_and_cancellation_are_not_collapsed_together(self):
        events = CoalescingQueue(lambda event: event[0])
        events.put((1, "old"))
        events.put((2, "current"))
        events.put((1, "late"))
        self.assertEqual(
            [events.get_nowait() for _ in range(3)],
            [(1, "old"), (2, "current"), (1, "late")],
        )
        events = CoalescingQueue(lambda event: None if event[0] == "cancelled" else 1)
        events.put(("progress", 1))
        events.put(("cancelled", None))
        self.assertEqual(events.get_nowait(), ("progress", 1))
        self.assertEqual(events.get_nowait(), ("cancelled", None))

    def test_producer_and_consumer_preserve_all_structural_events(self):
        events = CoalescingQueue(
            lambda event: "progress" if event[0] == "progress" else None
        )
        done = threading.Event()

        def produce():
            for index in range(1000):
                events.put(("progress", index))
                events.put(("result", index))
            done.set()

        worker = threading.Thread(target=produce)
        worker.start()
        received = []
        while not done.is_set() or not events.empty():
            try:
                received.append(events.get_nowait())
            except Empty:
                done.wait(0.001)
        worker.join(timeout=2)
        self.assertEqual(
            [value for kind, value in received if kind == "result"], list(range(1000))
        )

    def test_consumers_have_a_budget_even_with_uncoalesced_input(self):
        progress = MediaConversionProgress(1, 2)
        page = SimpleNamespace(
            _progress_results=Queue(),
            _operation_generation=1,
            _cancel_requested=False,
            _busy=True,
            progress_bar=Mock(),
            _status=Mock(),
        )
        for _ in range(1000):
            page._progress_results.put((1, progress))
        MediaToolsPage._consume_progress(page)
        self.assertEqual(page._progress_results.qsize(), 936)
        page.progress_bar.set.assert_called_once_with(0.5)

    def test_pdf_does_not_lose_current_progress_to_a_late_old_generation(self):
        queue = CoalescingQueue(lambda event: event[0])
        queue.put((2, PdfOperationProgress(2, 4)))
        queue.put((1, PdfOperationProgress(1, 4)))
        status = Mock()
        page = SimpleNamespace(
            _operation_progress_results=queue,
            _operation_generation=2,
            _operation_name="merge",
            _operation_state=_PdfOperationUiState.PROCESSING,
            progress_bar=Mock(),
            _operation_progress_text=lambda _: status,
        )
        PdfToolsPage._apply_latest_operation_progress(page)
        page.progress_bar.set.assert_called_once_with(0.5)

    def test_settings_bursts_render_once_before_terminal_result(self):
        for kind in ("update", "install"):
            with self.subTest(kind=kind):
                events = CoalescingQueue(
                    lambda event: "progress" if event[0] == "progress" else None
                )
                for index in range(10000):
                    events.put(("progress", (index, 10000)))
                events.put(
                    ("result", ("result", "snapshot") if kind == "update" else "result")
                )
                calls = []
                progress = Mock()
                progress.set.side_effect = lambda value: calls.append(
                    ("progress", value)
                )
                page = SimpleNamespace(winfo_exists=lambda: True, after=Mock())
                if kind == "update":
                    page._update_events = events
                    page._update_worker = None
                    page.update_progress = progress
                    page.update_status = Mock()
                    page._display_yt_dlp_result = lambda *args: calls.append(
                        ("terminal", args)
                    )
                    SettingsPage._poll_yt_dlp_update(page)
                else:
                    page._install_events = events
                    page._install_worker = None
                    page.libreoffice_progress = progress
                    page.libreoffice_status = Mock()
                    page._display_libreoffice_result = lambda *args: calls.append(
                        ("terminal", args)
                    )
                    SettingsPage._poll_libreoffice_install(page)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0][0], "progress")
                self.assertEqual(calls[1][0], "terminal")


class RealTkStage2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = ctk.CTk()
        except tk.TclError as error:
            raise unittest.SkipTest(str(error)) from error
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def files_page(self, **options):
        page = FilesPage(
            self.root,
            actions=FilesPageActions(noop, noop, noop, noop, noop, noop),
            get_favorites=lambda: (),
            **options,
        )
        self.addCleanup(page.destroy)
        self.addCleanup(page.close)
        return page

    def pdf_page(self):
        page = PdfToolsPage(
            self.root,
            service=PdfToolsService(),
            actions=PdfPageActions(noop, noop, noop, lambda *_: False),
        )
        self.addCleanup(page.destroy)
        self.addCleanup(page.close)
        return page

    def entries(self, count):
        return tuple(
            LocalFileEntry(
                Path(f"C:/fixtures/file-{index:05d}.txt"),
                LocalFileCategory.DOCUMENT,
                index,
                1700000000,
            )
            for index in range(count)
        )

    def render(self, page, entries):
        page._visible_entries = entries
        page._projection_total_count = len(entries)
        page._start_render(entries)
        while page._render_after_id is not None:
            page.after_cancel(page._render_after_id)
            page._render_batch(page._render_generation)

    def test_pdf_rows_reused_with_duplicates_metadata_and_selection(self):
        details = {}
        listing = _OrderedPathList(
            self.root,
            empty_text="empty",
            on_change=Mock(),
            detail_for_path=lambda path: details.get(path),
        )
        self.addCleanup(listing.destroy)
        a = Path("C:/one/a.pdf")
        b = Path("C:/two/a.pdf")
        listing.set_paths([a, b, a])
        controls = dict(listing._row_controls)
        listing._selected.set(1)
        listing.move_selected(-1)
        self.assertEqual(listing.paths, (b, a, a))
        self.assertEqual(listing.selected_index, 0)
        self.assertEqual(listing._row_controls, controls)
        details[b] = "3 páginas"
        listing.refresh()
        self.assertIn("two\n3 páginas", controls[0].cget("text"))
        listing.set_enabled(False)
        self.assertTrue(
            all(control.cget("state") == "disabled" for control in controls.values())
        )
        listing.remove_selected()
        self.assertEqual(listing.paths, (a, a))
        self.assertEqual(listing._row_controls[0], controls[0])
        self.assertFalse(controls[2].winfo_exists())
        self.assertEqual(listing.add_paths([a, Path("C:/three/c.pdf")]), 1)
        self.assertEqual(listing.selected_index, 2)

    def test_pdf_refresh_does_not_create_destroy_or_regrid_rows_and_keeps_scroll(self):
        listing = _OrderedPathList(self.root, empty_text="empty", on_change=noop)
        self.addCleanup(listing.destroy)
        listing.pack()
        listing.set_paths([entry.path for entry in self.entries(100)])
        self.root.update_idletasks()
        listing._rows._parent_canvas.yview_moveto(0.5)
        scroll = listing._rows._parent_canvas.yview()
        controls = tuple(listing._row_controls.values())
        with (
            patch("ui_pages.ctk.CTkRadioButton") as constructor,
            patch.object(controls[0], "grid", wraps=controls[0].grid) as grid,
        ):
            listing.refresh()
        constructor.assert_not_called()
        grid.assert_not_called()
        self.root.update_idletasks()
        self.assertEqual(listing._rows._parent_canvas.yview(), scroll)
        self.assertEqual(tuple(listing._row_controls.values()), controls)

    def test_inline_pdf_order_reuses_rows_and_preserves_focus_and_limits(self):
        changed = Mock()
        listing = _OrderedPathList(
            self.root,
            empty_text="empty",
            on_change=changed,
            inline_order=True,
            detail_for_path=lambda _path: "2 páginas · 10 kB",
        )
        self.addCleanup(listing.destroy)
        listing.pack(fill="x")
        self.root.deiconify()
        a, b, c = map(Path, ("a.pdf", "b.pdf", "c.pdf"))
        listing.set_paths([a, b, c])
        self.root.update()
        controls = dict(listing._row_controls)
        first, middle, last = (controls[index].master for index in range(3))
        geometry = middle.grid_bbox()
        self.assertEqual(first.buttons[-1].cget("state"), "disabled")
        self.assertEqual(last.buttons[1].cget("state"), "disabled")
        changed.reset_mock()
        first.buttons[-1].invoke()
        last.buttons[1].invoke()
        changed.assert_not_called()

        tk.Misc.focus_force(controls[1])
        self.root.update()
        self.assertTrue(middle.buttons[-1].winfo_ismapped())
        self.assertEqual(middle.grid_bbox(), geometry)
        for button in middle.buttons.values():
            self.assertLessEqual(
                button.winfo_y() + button.winfo_height(), button.master.winfo_height()
            )
            gap = button.winfo_rootx() - (
                controls[1].winfo_rootx() + controls[1].winfo_width()
            )
            self.assertIn(gap, range(1, 10))
        self.assertIs(controls[1].tk_focusNext(), middle.buttons[-1])
        tk.Misc.focus_force(middle.buttons[-1])
        self.root.update()
        tk.Misc.event_generate(middle.buttons[-1], "<space>")
        self.root.update()
        self.assertEqual(listing.paths, (b, a, c))
        self.assertEqual(listing.selected_index, 0)
        self.assertIs(listing.focus_get(), controls[0])
        self.assertEqual(listing._row_controls, controls)
        tk.Misc.event_generate(controls[0], "<Control-Down>")
        self.root.update()
        self.assertEqual(listing.paths, (a, b, c))
        self.assertIs(listing.focus_get(), controls[1])
        self.assertEqual(changed.call_count, 2)
        listing.set_enabled(False)
        middle.buttons[-1].invoke()
        self.assertEqual(listing.paths, (a, b, c))
        self.assertEqual(changed.call_count, 2)
        listing.set_enabled(True)

        original_geometry = self.root.geometry()
        self.addCleanup(self.root.geometry, original_geometry)
        for theme in ("Light", "Dark"):
            with self.subTest(theme=theme):
                self.addCleanup(ctk.set_appearance_mode, ctk.get_appearance_mode())
                ctk.set_appearance_mode(theme)
                listing._design.set_text_scale(120)
                self.root.geometry("420x390")
                listing.set_paths([a, Path("Nome prolongado " * 16 + ".pdf"), c])
                self.root.update()
                rail = middle.buttons[-1].master
                canvas = listing._rows._parent_canvas
                self.assertLessEqual(
                    rail.winfo_rootx() + rail.winfo_width(),
                    canvas.winfo_rootx() + canvas.winfo_width(),
                )
                self.assertTrue(middle.buttons[1].winfo_ismapped())
                self.assertIn("2 páginas · 10 kB", controls[1].cget("text"))

    def test_files_refresh_and_append_retain_selection_focus_scroll_and_ids(self):
        page = self.files_page()
        entries = self.entries(500)
        self.render(page, entries)
        items = page.file_tree.get_children()
        chosen = items[200]
        page.file_tree.selection_set(chosen)
        page.file_tree.focus(chosen)
        page._on_tree_selection()
        page.file_tree.yview_moveto(0.4)
        scroll = page.file_tree.yview()
        with (
            patch.object(
                page.file_tree, "delete", wraps=page.file_tree.delete
            ) as delete,
            patch.object(
                page.file_tree, "insert", wraps=page.file_tree.insert
            ) as insert,
            patch.object(page.file_tree, "move", wraps=page.file_tree.move) as move,
        ):
            self.render(page, entries)
            self.assertEqual(
                (delete.call_count, insert.call_count, move.call_count), (0, 0, 0)
            )
            self.render(page, entries + self.entries(501)[-1:])
            self.assertEqual(
                (delete.call_count, insert.call_count, move.call_count), (0, 1, 0)
            )
        self.assertEqual(page.file_tree.get_children()[:500], items)
        self.assertEqual(page.file_tree.selection(), (chosen,))
        self.assertEqual(page.file_tree.focus(), chosen)
        self.assertAlmostEqual(page.file_tree.yview()[0], scroll[0], delta=0.003)

    def test_files_metadata_removal_order_and_interrupted_batches(self):
        page = self.files_page()
        entries = self.entries(300)
        self.render(page, entries)
        chosen = page.file_tree.get_children()[5]
        page.file_tree.selection_set(chosen)
        page._on_tree_selection()
        changed = replace(entries[5], size_bytes=1024)
        update = entries[:5] + (changed,) + entries[6:]
        self.render(page, update)
        self.assertEqual(page._selected_entry, changed)
        self.assertIn("KB", page._detail_size.get())
        self.render(page, update[:5] + update[6:])
        self.assertIsNone(page._selected_entry)
        rng = random.Random(19)
        for _ in range(20):
            reordered = list(entries[:8])
            rng.shuffle(reordered)
            self.render(page, tuple(reordered))
            self.assertEqual(
                tuple(
                    page._entry_by_item[item] for item in page.file_tree.get_children()
                ),
                tuple(reordered),
            )
        self.render(page, entries)
        page._start_render(())
        old_generation = page._render_generation
        self.render(page, entries)
        before = page.file_tree.get_children()
        page._render_batch(old_generation)
        self.assertEqual(page.file_tree.get_children(), before)
        self.assertEqual(len(before), 300)

    def test_projection_worker_coalesces_queries_and_rejects_stale_results(self):
        workers = []

        class Worker(threading.Thread):
            def start(self):
                workers.append(self)
                super().start()

        page = self.files_page(thread_factory=Worker)
        page._PROJECTION_WORKER_THRESHOLD = 1
        page._snapshot = self.entries(20)
        release = threading.Event()
        started = threading.Event()
        calls = []
        original = page._project_files

        def project(request):
            calls.append((request.query, threading.get_ident()))
            if len(calls) == 1:
                started.set()
                release.wait(3)
            return original(request)

        page._project_files = project
        page._apply_filters()
        self.assertTrue(started.wait(2))
        page._query.set("file-00001")
        page._apply_search_now()
        page._query.set("file-00002")
        page._apply_search_now()
        self.assertEqual(len(workers), 1)
        release.set()
        workers[0].join(timeout=3)
        page.after_cancel(page._projection_after_id)
        page._poll_projection()
        workers[1].join(timeout=3)
        page.after_cancel(page._projection_after_id)
        page._poll_projection()
        self.assertEqual([query for query, _ in calls], ["", "file-00002"])
        self.assertTrue(all(thread != threading.get_ident() for _, thread in calls))
        self.assertEqual(page._visible_entries, (page._snapshot[2],))
        self.assertEqual(len(page.file_tree.get_children()), 1)

    def test_refresh_keeps_selection_and_preview_while_scan_is_pending(self):
        class DeferredWorker:
            def __init__(self, **_options):
                pass

            def start(self):
                pass

        page = self.files_page(thread_factory=DeferredWorker)
        entries = self.entries(3)
        self.render(page, entries)
        page._directory = entries[0].path.parent
        item = page.file_tree.get_children()[1]
        page.file_tree.selection_set(item)
        page._on_tree_selection()
        generation = page._preview_generation
        preview_state = page._preview_state
        page._refresh_directory()
        self.assertTrue(page._loading)
        self.assertEqual(page._selected_entry, entries[1])
        self.assertEqual(page._preview_generation, generation)
        self.assertEqual(page._preview_state, preview_state)
        self.assertEqual(page.file_tree.selection(), (item,))

    def test_projection_failure_and_close_leave_existing_rows_intact(self):
        page = self.files_page()
        entries = self.entries(5)
        self.render(page, entries)
        page._snapshot = entries
        page._PROJECTION_WORKER_THRESHOLD = 1
        page._thread_factory = Mock()
        page._thread_factory.return_value.start.side_effect = RuntimeError("no thread")
        before = page.file_tree.get_children()
        page._apply_filters()
        self.assertEqual(page.file_tree.get_children(), before)
        self.assertFalse(page._projection_worker_active)
        page._projection_results.put(
            (page._projection_generation, LocalFileProjection((), 0))
        )
        page.close()
        page._poll_projection()
        self.assertEqual(page.file_tree.get_children(), before)

    def test_preview_retains_items_scaled_image_and_invalidates_for_theme_size_generation(
        self,
    ):
        page = self.pdf_page()
        page._poster_source = Path("fixture.png")
        thumbnail = Image.new("RGB", (240, 180), "blue")
        page._poster_preview = _PosterPreview(
            plan_poster(Size(240, 180), page._current_poster_layout()), thumbnail
        )
        page._render_poster_preview()
        canvas = page.poster_preview_canvas
        items = canvas.find_all()
        photo = page._poster_preview_tk_image
        with patch.object(thumbnail, "resize", wraps=thumbnail.resize) as resize:
            for _ in range(100):
                page._render_poster_preview()
            resize.assert_not_called()
            self.assertEqual(canvas.find_all(), items)
            with patch(
                "ui_pages.ctk.get_appearance_mode",
                return_value="Light" if ctk.get_appearance_mode() == "Dark" else "Dark",
            ):
                page._render_poster_preview()
            resize.assert_not_called()
            self.assertIs(page._poster_preview_tk_image, photo)
            self.assertEqual(canvas.find_all(), items)
            canvas.configure(width=700)
            page._render_poster_preview()
            self.assertEqual(resize.call_count, 1)
        page._invalidate_poster_preview()
        self.assertTrue(page._poster_preview_loading)
        self.assertEqual(len(canvas.find_all()), 1)
        self.assertIsNone(page._poster_preview_tk_image)

    def test_resize_is_coalesced_and_skips_hidden_canvases(self):
        page = self.pdf_page()
        with (
            patch.object(page, "after_idle", return_value="idle") as after,
            patch.object(page, "_render_images_preview") as images,
            patch.object(page, "_render_poster_preview") as poster,
        ):
            for _ in range(20):
                page._schedule_preview_redraw()
            self.assertEqual(after.call_count, 1)
            after.call_args.args[0]()
            images.assert_not_called()
            poster.assert_not_called()
        self.assertIsNone(page._preview_resize_after_id)

    def test_images_canvas_cache_invalidates_and_keeps_correct_stacking(self):
        page = self.pdf_page()
        temporary = tempfile.TemporaryDirectory(prefix="goal2-canvas-")
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "fixture.png"
        with Image.new("RGB", (240, 180), "blue") as image:
            image.save(path)
        original = path.read_bytes()
        page.image_files.add_paths([path])
        pane = page.images_page_preview

        def loaded():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                self.root.update()
                if pane._photo and pane._poll_id is None:
                    return
                time.sleep(0.005)
            self.fail("Real image preview did not finish")

        loaded()
        pixels = pane._bundle.main.rgb
        canvas = page.images_preview_canvas
        items = canvas.find_all()
        renders = page._page_preview_worker.renderer.renders
        for _ in range(100):
            page._render_images_preview()
        self.assertEqual(page._page_preview_worker.renderer.renders, renders)
        self.assertEqual(canvas.find_all(), items)
        self.assertEqual(len(items), 2)
        page._images_per_page.set("4 por página")
        page._render_images_preview()
        loaded()
        self.assertNotEqual(pane._bundle.main.rgb, pixels)
        self.assertEqual(canvas.find_all(), items)
        for width in range(400, 500, 5):
            canvas.configure(width=width)
            page._render_images_preview()
        loaded()
        self.assertEqual(canvas.find_all(), items)
        self.assertEqual(canvas.type(items[0]), "image")
        self.assertEqual(canvas.type(items[1]), "text")
        self.assertEqual(canvas.itemcget(items[1], "text"), "")
        page.image_files._paths.clear()
        page._invalidate_images_preview()
        self.assertIsNone(pane._photo)
        self.assertEqual(canvas.itemcget(items[0], "image"), "")
        self.assertEqual(
            canvas.itemcget(items[1], "text"),
            "Adicione imagens para visualizar o resultado.",
        )
        self.assertEqual(canvas.find_all(), items)
        self.assertEqual(path.read_bytes(), original)

    def test_poster_resizes_keep_only_one_tk_image(self):
        page = self.pdf_page()
        page._poster_source = Path("fixture.png")
        page._poster_preview = _PosterPreview(
            plan_poster(Size(240, 180), page._current_poster_layout()),
            Image.new("RGB", (240, 180), "blue"),
        )
        page._render_poster_preview()
        canvas = page.poster_preview_canvas
        count = len(self.root.tk.call("image", "names"))
        for height in range(300, 400, 5):
            canvas.configure(height=height)
            page._render_poster_preview()
        self.assertEqual(len(self.root.tk.call("image", "names")), count)


if __name__ == "__main__":
    unittest.main()
