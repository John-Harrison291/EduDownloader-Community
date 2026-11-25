"""Six preparation features integrated in actual persistent PDF widgets."""

from pathlib import Path
import gc
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk
from PIL import Image

from pdf_tools import PdfToolsService, PdfOperationResult, PdfImageExportResult
from pdf_previews import PreviewSpec, PreviewWorker
from image_preparation import ImagePreparation
from pdf_results import ResultInfo
from settings import save_settings, load_settings
from tests.test_pdf_previews import make_pdf
from ui_pages import PdfToolsPage, PdfPageActions


class PreparationTkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = ctk.CTk()
        except tk.TclError as error:
            raise unittest.SkipTest(str(error)) from error
        cls.root.geometry("1100x950+30+30")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="goal4-tk-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.paths = []
        for i, size in enumerate(
            ((100, 200), (240, 80), (150, 150), (300, 120), (90, 260))
        ):
            path = self.directory / f"{i} Foto ação.png"
            with Image.new(
                "RGB", size, ("red", "blue", "green", "yellow", "cyan")[i]
            ) as image:
                image.save(path)
            self.paths.append(path)
        self.owner = threading.get_ident()
        self.open_calls = []
        self.errors = []
        self.actions = PdfPageActions(
            lambda m: None,
            lambda m: None,
            lambda m: self.errors.append((m, threading.get_ident())),
            lambda m: False,
            lambda path: (
                self.open_calls.append(("file", path, threading.get_ident())) or True
            ),
            lambda path: (
                self.open_calls.append(("folder", path, threading.get_ident())) or True
            ),
        )
        self.page = self.new_page()

    def new_page(self, **kwargs):
        page = PdfToolsPage(
            self.root, service=PdfToolsService(), actions=self.actions, **kwargs
        )
        page.pack(fill="both", expand=True)
        return page

    def close_page(self, page):
        workers = [
            page._page_preview_worker,
            page._analysis_worker,
            page._result_worker,
        ]
        page.close()
        for worker in workers:
            if worker.thread:
                worker.thread.join(5)
                self.assertFalse(worker.thread.is_alive())
        page.destroy()
        if getattr(self, "page", None) is page:
            self.page = None
        # Repeated page recreation is a test fixture. Collect its Tk font cycles
        # on the Tk thread before a new worker can trigger cyclic collection.
        del page
        gc.collect()

    def tearDown(self):
        self.close_page(self.page)
        self.root.withdraw()

    def wait(self, predicate, seconds=10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("PDF preparation did not reach expected state")

    def ready(self):
        pane = self.page.images_page_preview
        return (
            pane._bundle
            and pane._photo
            and pane._poll_id is None
            and self.page._image_analysis is not None
        )

    def test_rotation_identity_reorder_remove_readd_and_zoom_navigation(self):
        self.page.image_files.set_paths(self.paths)
        self.wait(self.ready)
        original = {p: p.read_bytes() for p in self.paths}
        for angle in (90, 180, 270, 0):
            self.page._rotate_image(90)
            self.wait(self.ready)
            self.assertEqual(self.page._image_angles(), (angle, 0, 0, 0, 0))
        self.page.images_page_preview.change_zoom(1.25)
        self.page.images_page_preview.goto(3)
        self.page._images_margin.set("Sem margem")
        self.page._on_images_layout_changed()
        self.wait(self.ready)
        self.assertEqual(self.page.images_page_preview.zoom, 1.25)
        self.assertEqual(self.page.images_page_preview.index, 3)
        self.page._rotate_image(90)
        self.page.image_files.move_to_insertion(0, 5)
        self.wait(self.ready)
        self.assertEqual(
            self.page.image_files.paths, tuple(self.paths[1:] + self.paths[:1])
        )
        self.assertEqual(self.page._image_angles(), (0, 0, 0, 0, 90))
        self.page.image_files.remove_selected()
        self.page.image_files.add_paths([self.paths[0]])
        self.assertEqual(self.page._image_angles(), (0, 0, 0, 0, 0))
        self.assertEqual(original, {p: p.read_bytes() for p in self.paths})
        self.assertEqual(set(self.directory.iterdir()), set(self.paths))

    def test_rotated_order_exports_actual_pdf_and_shows_estimate_quality_real_size(
        self,
    ):
        self.page._open_tool("Imagens → PDF")
        self.page.image_files.set_paths(self.paths)
        self.page._images_per_page.set("2 por página")
        self.page._on_images_layout_changed()
        self.page._rotate_image(90)
        self.page.image_files.move_to_insertion(0, 5)
        self.wait(self.ready)
        self.assertIn("aproximado", self.page._images_estimate.get())
        self.assertIn("perder nitidez", self.page._images_quality.get())
        self.assertEqual(self.page.images_run_button.cget("state"), "normal")
        output = self.directory / "Resultado ação.pdf"
        self.page._start_images_worker(
            self.page.image_files.paths,
            output,
            overwrite=False,
            layout=self.page._current_images_layout(),
            rotations=self.page._image_angles(),
        )
        self.wait(
            lambda: not self.page.is_busy and self.page._feedback_for().info is not None
        )
        self.assertEqual(PdfToolsService().page_count(output), 3)
        self.assertEqual(
            self.page._feedback_for().info.size_bytes, output.stat().st_size
        )
        self.assertIn("Tamanho real", self.page._feedback_for().result_text.get())
        self.assertIn(str(output.parent), self.page._feedback_for().result_text.get())

    def test_preferences_restart_invalid_values_and_no_writes_for_rotation_drag_zoom(
        self,
    ):
        self.close_page(self.page)
        setting = self.directory / "preferences.json"
        saved = []

        def persist(values):
            saved.append(values)
            save_settings({"pdf_preferences": values}, setting)
            return True

        self.page = self.new_page(persist_preferences=persist)
        self.page._images_paper.set("Carta")
        self.page._images_orientation.set("Paisagem")
        self.page._images_margin.set("Pequena")
        self.page._images_per_page.set("4 por página")
        self.page._poster_grid.set("3 × 3")
        self.page._poster_crop_marks.set(True)
        self.page._pdf_images_format.set("JPG")
        self.page._pdf_images_quality.set("Alta")
        count = len(saved)
        self.page.image_files.set_paths(self.paths)
        self.page._rotate_image(90)
        self.page.image_files.move_to_insertion(0, 5)
        self.page.images_page_preview.change_zoom(1.25)
        self.assertEqual(len(saved), count)
        restored = load_settings(setting)["pdf_preferences"]
        self.close_page(self.page)
        self.page = self.new_page(preferences=restored)
        self.assertEqual(self.page._images_paper.get(), "Carta")
        self.assertEqual(self.page._images_per_page.get(), "4 por página")
        self.assertEqual(self.page._poster_grid.get(), "3 × 3")
        self.assertTrue(self.page._poster_crop_marks.get())
        self.assertEqual(self.page._pdf_images_format.get(), "JPG")
        self.assertEqual(self.page._image_rotations, {})
        self.close_page(self.page)
        self.page = self.new_page(
            preferences={"images_paper": "BAD"},
            persist_preferences=Mock(side_effect=PermissionError),
        )
        self.assertEqual(self.page._images_paper.get(), "A4")
        self.page._images_paper.set("Carta")
        self.assertIn("só nesta sessão", self.page._pdf_preference_message.get())

    def test_real_drag_marker_auto_scroll_escape_invalid_drop_and_preserved_rotation(
        self,
    ):
        self.root.deiconify()
        self.page._open_tool("Imagens → PDF")
        extra = []
        for i in range(50):
            path = self.directory / f"Item {i:02}.png"
            with Image.new("RGB", (20, 30), "blue") as image:
                image.save(path)
            extra.append(path)
        self.page.image_files.set_paths(extra)
        self.page._rotate_image(90)
        self.root.update()
        listing = self.page.image_files
        drag = listing._drag
        canvas = drag.canvas

        def event(x, y):
            return SimpleNamespace(x_root=x, y_root=y)

        row = listing._row_controls[0]
        press = event(row.winfo_rootx() + 20, row.winfo_rooty() + 10)
        bottom = event(
            canvas.winfo_rootx() + 35, canvas.winfo_rooty() + canvas.winfo_height() - 3
        )
        drag.press(0, press)
        drag.motion(bottom)
        self.assertTrue(drag.marker.winfo_manager())
        before = canvas.yview()[0]
        self.wait(lambda: canvas.yview()[0] > before)
        drag.release(bottom)
        self.assertEqual(len(set(listing.paths)), 50)
        self.assertGreater(listing.selected_index, 0)
        self.assertEqual(
            self.page._image_rotations[listing._comparison_key(extra[0])], 90
        )
        order = listing.paths
        drag.press(0, press)
        drag.motion(bottom)
        self.root.focus_force()
        self.root.event_generate("<Escape>")
        self.root.update()
        self.assertIsNone(drag.source)
        self.assertEqual(listing.paths, order)
        drag.press(0, press)
        outside = event(canvas.winfo_rootx() - 50, canvas.winfo_rooty() - 50)
        drag.motion(outside)
        drag.release(outside)
        self.assertEqual(listing.paths, order)
        listing.set_enabled(False)
        drag.press(0, press)
        self.assertIsNone(drag.source)
        listing.set_enabled(True)
        listing.set_paths(self.paths)
        listing.move_to_insertion(4, 0)
        self.assertEqual(listing.paths, tuple(self.paths[4:] + self.paths[:4]))
        listing.move_to_insertion(0, 3)
        self.assertEqual(
            listing.paths, tuple(self.paths[:2] + self.paths[4:] + self.paths[2:4])
        )
        listing.move_to_insertion(2, 5)
        self.assertEqual(listing.paths, tuple(self.paths))
        drag.press(0, press)
        listing.set_paths(self.paths[:2])
        drag.motion(bottom)
        self.assertIsNone(drag.source)
        self.assertIsNone(drag.after_id)

    def test_latest_analysis_and_result_win_and_close_cancels_pending_work(self):
        class HeldReader:
            def __init__(self, result):
                self.started = threading.Event()
                self.release = threading.Event()
                self.closed = threading.Event()
                self.result = result
                self.calls = []

            def bundle(self, spec, _index, _bounds, _cancel):
                self.calls.append(spec)
                self.started.set()
                if not self.release.wait(5):
                    raise TimeoutError("Controlled reader was not released")
                return self.result(spec)

            def close(self):
                self.closed.set()

        analysis = HeldReader(
            lambda spec: ImagePreparation(message=str(spec.rotations))
        )
        results = HeldReader(lambda spec: ResultInfo(spec.paths[0].stat().st_size))
        for field, reader in (
            ("_analysis_worker", analysis),
            ("_result_worker", results),
        ):
            worker = getattr(self.page, field)
            worker.close()
            setattr(self.page, field, PreviewWorker(reader))
            self.addCleanup(reader.release.set)
        self.page.image_files.set_paths(self.paths)
        spec = PreviewSpec(
            "images", tuple(self.paths), self.page._current_images_layout()
        )
        self.page._request_image_analysis(spec)
        self.assertTrue(analysis.started.wait(2))
        self.page._set_result(self.paths[0])
        self.assertTrue(results.started.wait(2))
        for i in range(100):
            latest = PreviewSpec(
                "images", tuple(self.paths), spec.layout, rotations=((i % 4) * 90,) * 5
            )
            self.page._request_image_analysis(latest)
            self.page._set_result(self.paths[i % 5])
            self.assertLessEqual(len(self.page._analysis_worker.pending), 1)
            self.assertLessEqual(len(self.page._result_worker.pending), 1)
        analysis.release.set()
        results.release.set()
        self.page._image_rotations = {
            self.page.image_files._comparison_key(path): 270 for path in self.paths
        }
        self.wait(
            lambda: (
                self.page._image_analysis is not None
                and self.page._feedback_for().info is not None
            )
        )
        self.assertEqual(self.page._image_analysis.message, str(latest.rotations))
        self.assertEqual(self.page._feedback_for().path, self.paths[4])
        self.assertEqual(
            self.page._feedback_for().info.size_bytes, self.paths[4].stat().st_size
        )
        self.assertLessEqual(len(analysis.calls), 2)
        self.assertLessEqual(len(results.calls), 2)
        for reader in (analysis, results):
            reader.release.clear()
            reader.started.clear()
        self.page._request_image_analysis(spec)
        self.page._set_result(self.paths[0])
        self.assertTrue(analysis.started.wait(2))
        self.assertTrue(results.started.wait(2))
        self.page._request_image_analysis(latest)
        self.page._set_result(self.paths[1])
        self.page.close()
        analysis.release.set()
        results.release.set()
        for worker in (self.page._analysis_worker, self.page._result_worker):
            worker.thread.join(3)
            self.assertFalse(worker.thread.is_alive())
            self.assertFalse(worker.pending)
            self.assertFalse(worker.results)
        self.assertTrue(analysis.closed.is_set())
        self.assertTrue(results.closed.is_set())
        self.assertIsNone(self.page._analysis_after_id)
        self.assertIsNone(self.page._result_after_id)

    def test_worker_start_failure_keeps_export_available_and_result_disabled(self):
        with patch.object(
            self.page._analysis_worker, "submit", side_effect=RuntimeError
        ):
            self.page.image_files.set_paths(self.paths)
            self.page._render_images_preview()
        self.assertIn("indisponível", self.page._images_estimate.get())
        self.assertEqual(self.page.images_run_button.cget("state"), "normal")
        with patch.object(self.page._result_worker, "submit", side_effect=OSError):
            self.page._set_result(self.paths[0])
        self.assertIsNone(self.page._feedback_for().path)
        self.assertEqual(self.page.open_file_button.cget("state"), "disabled")
        self.assertIn(
            "Não foi possível conferir", self.page._feedback_for().result_text.get()
        )

    def test_compact_layout_preserves_buttons_and_thumbnail_bounds_after_resize(self):
        self.root.deiconify()
        self.page._open_tool("Imagens → PDF")
        self.page.image_files.set_paths(self.paths)
        self.page._rotate_image(90)
        self.wait(self.ready)
        for width in (860, 1100, 860):
            self.root.geometry(f"{width}x700+30+30")
            self.wait(
                lambda: (
                    self.ready() and self.page.images_page_preview._resize_id is None
                )
            )
            listing = self.page.image_files
            self.assertLessEqual(
                self.page.images_remove_button.winfo_rootx()
                + self.page.images_remove_button.winfo_width(),
                listing.winfo_rootx() + listing.winfo_width(),
            )
            pane = self.page.images_page_preview
            for button in pane.thumbs:
                if button.winfo_manager():
                    self.assertLessEqual(
                        button.winfo_rootx() + button.winfo_width(),
                        pane.winfo_rootx() + pane.winfo_width(),
                    )
        self.root.geometry("1100x950+30+30")

    def test_open_actions_are_validated_async_multiple_outputs_and_errors_return_to_tk(
        self,
    ):
        self.page._open_tool("Juntar PDFs")
        output = self.directory / "PDF ação 你好.pdf"
        make_pdf(output)
        self.page._complete_operation("PDF criado", PdfOperationResult(output, 1))
        self.assertEqual(self.page.open_file_button.cget("state"), "disabled")
        self.wait(lambda: self.page._feedback_for().info is not None)
        self.page.open_file_button.invoke()
        self.wait(lambda: not self.page._feedback_for().pending)
        self.assertEqual(self.open_calls[0][:2], ("file", output))
        self.assertNotEqual(self.open_calls[0][2], self.owner)
        output.unlink()
        self.page.open_folder_button.invoke()
        self.wait(lambda: self.page._feedback_for().path is None)
        self.assertEqual(self.errors[-1][1], self.owner)
        first = self.paths[0]
        second = self.paths[1]
        self.page._open_tool("PDF → Imagens")
        self.page._complete_pdf_images_export(
            PdfImageExportResult(self.directory, (first, second), (1, 2))
        )
        self.wait(lambda: self.page._feedback_for().info is not None)
        self.assertEqual(self.page.open_file_button.cget("state"), "disabled")
        self.page.open_folder_button.invoke()
        self.wait(lambda: not self.page._feedback_for().pending)
        self.assertEqual(self.open_calls[-1][:2], ("folder", first))
        self.assertIn("2 arquivos", self.page._feedback_for().result_text.get())
