"""Regressions for the local presentation paths revised in Goal 8.5."""

import sys
import tkinter as tk
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import customtkinter as ctk

from app import EduDownloaderApp
from pdf_tools import parse_page_selection
from ui_design import Design
from ui_pages import (
    DownloadsPage,
    FilesPage,
    PdfToolsPage,
    _PreviewVisualState,
    _shorten_cell,
)
from ui_resize_cover import (
    HTCLIENT,
    HTTRANSPARENT,
    WM_NCHITTEST,
    ContentPresentation,
    _NativeCover,
)
from ui_scroll import _WheelRouter


class WheelIsolationTests(unittest.TestCase):
    def setUp(self):
        self.window = Mock()
        self.outer, self.inner = Mock(), Mock()
        self.parent = Mock(master=self.window)
        self.parent._edu_scroll_region = (self.outer, 1, None)
        self.child = Mock(master=self.parent)
        self.child._edu_scroll_region = (self.inner, 1, None)
        self.child.winfo_toplevel.return_value = self.window
        self.parent.winfo_toplevel.return_value = self.window
        self.window.winfo_containing.return_value = self.child
        self.router = _WheelRouter.__new__(_WheelRouter)
        self.router.window = self.window
        self.router.active = None
        self.router.remainder = 0.0

    def wheel(self, delta, state=0):
        return self.router.route(
            SimpleNamespace(x_root=4, y_root=5, state=state, delta=delta, num="??")
        )

    def test_inner_owns_gestures_at_both_limits_then_outer_owns_its_surface(self):
        self.assertEqual(self.wheel(-120), "break")
        self.assertEqual(self.wheel(120), "break")
        self.assertEqual(self.inner.yview_scroll.call_count, 2)
        self.outer.yview_scroll.assert_not_called()
        self.window.winfo_containing.return_value = self.parent
        self.assertEqual(self.wheel(-120), "break")
        self.outer.yview_scroll.assert_called_once()

    def test_zoom_and_horizontal_wheel_never_move_parent_vertically(self):
        zoom = Mock(return_value="break")
        self.child._edu_scroll_region = (self.inner, 1, zoom)
        self.assertEqual(self.wheel(-120, state=4), "break")
        zoom.assert_called_once()
        self.inner.yview_scroll.assert_not_called()
        self.wheel(-120, state=1)
        self.inner.xview_scroll.assert_called_once()
        self.outer.yview_scroll.assert_not_called()


class AppearancePresentationTests(unittest.TestCase):
    def shell(self):
        return SimpleNamespace(
            _close_requested=False,
            settings={"text_scale": 100},
            _presentation=Mock(),
            _resize_presentation=Mock(),
            _design=Mock(),
            settings_page=Mock(),
            files_page=Mock(),
            _save_preferences=Mock(),
        )

    def test_cover_starts_before_the_font_change_and_finishes_after_layout(self):
        shell = self.shell()
        sequence = []
        shell._resize_presentation.begin_layout.side_effect = lambda: sequence.append(
            "show"
        )
        shell._design.set_text_scale.side_effect = lambda _: sequence.append("scale")
        shell._resize_presentation.finish_layout.side_effect = lambda: sequence.append(
            "ready"
        )
        for scale in (90, 90, 100, 110, 120, 120, 130, 100):
            EduDownloaderApp._change_text_scale(shell, scale)
        self.assertEqual(sequence, ["show", "scale", "ready"] * 5)
        self.assertEqual(shell.settings["text_scale"], 100)

    def test_failed_update_dismisses_the_cover_and_keeps_previous_preference(self):
        shell = self.shell()
        shell._design.set_text_scale.side_effect = tk.TclError("layout")
        with self.assertRaises(tk.TclError):
            EduDownloaderApp._change_text_scale(shell, 120)
        shell._resize_presentation.dismiss.assert_called_once_with()
        shell._resize_presentation.finish_layout.assert_not_called()
        shell._save_preferences.assert_not_called()
        self.assertEqual(shell.settings["text_scale"], 100)

    @unittest.skipUnless(sys.platform == "win32", "Windows canvas rendering behavior")
    def test_text_scale_preserves_mapped_canvas_and_recalculates_label_size(self):
        root = ctk.CTk()
        self.addCleanup(root.destroy)
        design = Design(root)
        label = design.label(root, "Configurações", font=design.title)
        label.pack()
        root.update()
        canvas = label._canvas
        size = label.winfo_reqheight()
        unmaps = []
        tk.Misc.bind(canvas, "<Unmap>", unmaps.append, add="+")
        design.set_text_scale(120)
        root.update()
        self.assertTrue(canvas.winfo_ismapped())
        self.assertGreater(label.winfo_reqheight(), size)
        self.assertEqual(unmaps, [])
        self.assertNotIn("grid_forget", vars(canvas))


class FileSelectionPresentationTests(unittest.TestCase):
    def test_details_and_actions_reflow_within_the_same_presentation(self):
        events = []

        @contextmanager
        def viewport_change(*, pointer):
            self.assertIs(pointer, page.file_tree)
            events.append("cover")
            yield
            events.append("schedule paint")

        entry = SimpleNamespace(
            name="Aula.odt", suffix=".odt", size_bytes=400, modified_timestamp=0
        )
        page = Mock(_selected_entry=None, _entry_by_item={"odt": entry})
        page.file_tree.selection.return_value = ("odt",)
        page._viewport_change = viewport_change
        page._selection_presentation.side_effect = lambda: (
            FilesPage._selection_presentation(page)
        )
        page._detail_type.set.side_effect = lambda _text: events.append("details")
        page._refresh_context_actions.side_effect = lambda: events.append("actions")
        page._clear_selection.side_effect = lambda: FilesPage._clear_selection(page)
        page._schedule_preview.side_effect = lambda _entry: setattr(
            page, "_preview_state", _PreviewVisualState.LOADING
        )
        page._type_label.return_value = "Documento OpenDocument"
        page._format_timestamp.return_value = "25/11/2026"

        FilesPage._on_tree_selection(page)
        FilesPage._on_tree_selection(page)
        self.assertIs(page._selected_entry, entry)
        page._schedule_preview.assert_called_once_with(entry)
        self.assertEqual(events, ["cover", "details", "actions", "schedule paint"])

        events.clear()
        page.file_tree.selection.return_value = ()
        FilesPage._on_tree_selection(page)
        self.assertIsNone(page._selected_entry)
        self.assertEqual(events, ["cover", "details", "actions", "schedule paint"])

    def test_native_cover_allows_a_second_click_only_inside_the_file_list(self):
        def translate(handle, point):
            self.assertEqual(handle, 2)
            point._obj.x -= 25
            point._obj.y -= 40
            return True

        def client_rect(_handle, rect):
            rect._obj.right = 100
            rect._obj.bottom = 80
            return True

        native = Mock(
            callback=lambda callback: callback,
            set_subclass=Mock(return_value=False),
            screen_to_client=translate,
            get_client=client_rect,
        )
        cover = _NativeCover(native, 1, lambda: True, 0)
        cover.deadline = 1
        cover.block_sidebar = True
        cover.input_hwnd = 2

        def hit(x, y):
            return cover._child_message(3, WM_NCHITTEST, 0, x | (y << 16), 0, 0)

        self.assertEqual(hit(75, 55), HTTRANSPARENT)
        self.assertEqual(hit(126, 55), HTCLIENT)
        self.assertEqual(hit(75, 39), HTCLIENT)
        cover.input_hwnd = None
        self.assertEqual(hit(75, 55), HTCLIENT)


class ContentPresentationTests(unittest.TestCase):
    def setUp(self):
        self.host = Mock()
        self.host.winfo_width.return_value = 900
        self.host.winfo_height.return_value = 600
        self.first = Mock(_parent_frame=self.surface(1))
        self.second = Mock(_parent_frame=self.surface(2))
        self.app = Mock(
            _page_stack=SimpleNamespace(host=self.host, current=self.first),
            _pages={"Arquivos": self.first, "PDF": self.second},
        )
        with patch("ui_resize_cover.tk.Misc.bind"):
            self.presentation = ContentPresentation(self.app)
        self.native = Mock(
            enum=lambda callback: callback,
            update_pending=Mock(return_value=False),
            redraw=Mock(return_value=True),
            flush=Mock(return_value=0),
        )
        self.cover = Mock(active=True, native=self.native)
        self.presentation._cover = self.cover

    def surface(self, handle):
        return Mock(
            master=self.host,
            winfo_id=Mock(return_value=handle),
            winfo_viewable=Mock(return_value=True),
            winfo_width=Mock(return_value=900),
            winfo_height=Mock(return_value=600),
            winfo_children=Mock(return_value=[]),
        )

    def test_waits_for_pending_native_paint_and_new_expose(self):
        self.native.update_pending.return_value = True
        self.presentation._present()
        self.native.redraw.assert_not_called()
        self.app.after.assert_called_once()
        self.cover.hide.assert_not_called()

        self.native.update_pending.return_value = False
        self.presentation._present()
        self.native.redraw.assert_called_once()
        self.presentation._observe(SimpleNamespace(widget=self.first._parent_frame))
        self.presentation._present()
        self.cover.hide.assert_not_called()
        self.native.redraw.assert_called_once()
        self.presentation._present()
        self.cover.hide.assert_called_once_with("ready")
        self.assertNotIn(self.first, self.presentation._unpainted)

    def test_navigation_clears_the_file_list_pointer_region_while_still_covered(self):
        self.app._close_requested = False
        self.app._modal_open = False
        self.app._presentation.startup_active = False
        self.app._resize_presentation = None
        tree = Mock(winfo_id=Mock(return_value=103))
        with self.presentation.change(self.first, layout=True, pointer=tree):
            self.assertEqual(self.cover.input_hwnd, 103)

        with self.presentation.change(self.second):
            self.app._page_stack.current = self.second
            self.assertIsNone(self.cover.input_hwnd)

    def test_hidden_layout_marks_only_its_page_and_latest_navigation_wins(self):
        self.presentation._unpainted.clear()
        with self.presentation.change(self.second, layout=True):
            pass
        self.assertEqual(self.presentation._unpainted, {self.second})
        self.app.after_idle.assert_not_called()
        with self.presentation.change(self.second):
            self.app._page_stack.current = self.second
        with self.presentation.change(self.first):
            self.app._page_stack.current = self.first
        self.app.after_idle.assert_called_once()
        self.presentation._present()
        self.assertEqual(self.native.redraw.call_args.args[0], 1)
        self.presentation._present()
        self.assertIn(self.second, self.presentation._unpainted)

    def test_failed_mutation_dismisses_and_keeps_pages_pending(self):
        self.presentation._unpainted.clear()
        with self.assertRaises(ValueError):
            with self.presentation.change(self.first, dark=True):
                raise ValueError("palette")
        self.cover.hide.assert_called_once_with("dismissed")
        self.assertEqual(self.presentation._unpainted, {self.first, self.second})
        self.app.after_idle.assert_not_called()

    def test_navigation_during_native_redraw_keeps_new_destination_pending(self):
        def redirect(*_args):
            with self.presentation.change(self.second):
                self.app._page_stack.current = self.second
            return True

        self.native.redraw.side_effect = redirect
        self.presentation._present()
        self.app.after_idle.assert_called_once()
        self.cover.hide.assert_not_called()
        self.native.redraw.side_effect = None
        self.presentation._present()
        self.assertEqual(self.native.redraw.call_args.args[0], 2)
        self.presentation._present()
        self.cover.hide.assert_called_once_with("ready")
        self.assertEqual(self.presentation._unpainted, {self.first})

    def test_close_cancels_queued_presentation_and_releases_native_surface(self):
        self.presentation._pending = "after#11"
        self.presentation.close()
        self.app.after_cancel.assert_called_once_with("after#11")
        self.cover.hide.assert_called_once_with("dismissed")
        self.cover.close.assert_called_once_with()


class PdfThumbnailSelectionTests(unittest.TestCase):
    def test_visual_toggle_preserves_manual_order_and_untouched_duplicates(self):
        selection = Mock()
        selection.get.return_value = "3,1-2,3,2"
        page = SimpleNamespace(
            _extract_page_count=5, _extract_selection=selection, is_busy=False
        )
        PdfToolsPage._toggle_extract_page(page, 3)
        selection.set.assert_called_once_with("1,2,2")
        self.assertEqual(
            parse_page_selection(selection.set.call_args.args[0], 5), (1, 2, 2)
        )
        selection.reset_mock()
        selection.get.return_value = "3,1-2,3,2"
        PdfToolsPage._toggle_extract_page(page, 5)
        selection.set.assert_called_once_with("3,1,2,3,2,5")

    def test_invalid_busy_and_empty_inputs_do_not_change_navigation(self):
        selection = Mock()
        selection.get.return_value = "9-3"
        page = SimpleNamespace(
            _extract_page_count=5, _extract_selection=selection, is_busy=False, index=3
        )
        PdfToolsPage._toggle_extract_page(page, 1)
        selection.set.assert_not_called()
        page.is_busy = True
        selection.get.return_value = "1"
        PdfToolsPage._toggle_extract_page(page, 1)
        selection.set.assert_not_called()
        page.is_busy = False
        PdfToolsPage._toggle_extract_page(page, 1)
        selection.set.assert_called_once_with("")
        self.assertEqual(page.index, 3)


class DownloadAndFilesPresentationTests(unittest.TestCase):
    def test_recent_shortcut_stays_visible_only_when_its_file_has_no_card(self):
        result = Path("a.mp4")
        view = SimpleNamespace(
            open_result_file_button=Mock(),
            open_result_folder_button=Mock(),
            _result_shortcuts=Mock(),
            _queue_actions=Mock(recent_result_path=lambda: result),
            _queue_result_paths={result},
            _display=Mock(),
        )
        DownloadsPage.set_result_actions_enabled(view, True)
        view._display.assert_called_once_with(view._result_shortcuts, False)
        view._queue_result_paths = {Path("b.mp4")}
        DownloadsPage.set_result_actions_enabled(view, True)
        view._display.assert_called_with(view._result_shortcuts, True)

    def test_file_table_shortening_keeps_the_string_readable(self):
        self.assertEqual(_shorten_cell("Documento do Word", 10, len), "Documento…")
        self.assertEqual(_shorten_cell("PDF", 10, len), "PDF")
