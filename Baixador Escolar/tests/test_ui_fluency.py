"""Regressões das otimizações locais de fluidez, sem fixtures Git."""

from pathlib import Path
from queue import Queue
from types import MethodType, SimpleNamespace
import threading
import unittest

from component_manager import ComponentId, ComponentState
from unittest.mock import Mock, patch

from app import (
    EduDownloaderApp,
    NAVIGATION_PAGES,
    PAGE_DOWNLOADS,
    PAGE_HOME,
    PAGE_PDF,
    PAGE_TOOLS,
)
from ui_design import NAV_HOVER, SIDEBAR_TEXT
from downloader import DownloadProgress
from tests.test_app import DownloadUiDouble
from ui_pages import (
    PdfToolsPage,
    SettingsPage,
    _ImagesPdfPreviewResult,
    _OrderedPathList,
    _PosterPreviewResult,
)
from paths import ManagedRootCheck, ManagedRootState
from yt_dlp_update import UpdateCheck, UpdateCheckStatus


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def widget(**properties):
    control = Mock()
    control.cget.side_effect = properties.__getitem__
    control.configure.side_effect = lambda **values: properties.update(values)
    return control


class RedundantUpdatesTests(unittest.TestCase):
    def test_progress_updates_metrics_without_reconfiguring_unchanged_controls(self):
        app = DownloadUiDouble()
        controls = []
        for name in (
            "link_entry",
            "paste_button",
            "clear_button",
            "change_destination_button",
            "quality_menu",
            "download_button",
            "cancel_button",
        ):
            control = widget(state="normal", text="Baixar")
            setattr(app, name, control)
            controls.append(control)
        app.content_type_buttons = [widget(state="normal") for _ in range(2)]
        controls.extend(app.content_type_buttons)
        app._show_progress(DownloadProgress(10, 100, 1000, 10, 90))
        for control in controls:
            control.configure.reset_mock()
        app._show_progress(DownloadProgress(20, 200, 1000, 10, 80))
        for control in controls:
            control.configure.assert_not_called()
        self.assertEqual(app.percentage.get(), "20%")
        app.progress_bar.set.assert_called_with(0.2)

    def test_navigation_only_recolors_buttons_whose_selection_changes(self):
        buttons = {
            name: widget(
                fg_color="transparent", text_color=SIDEBAR_TEXT, hover_color=NAV_HOVER
            )
            for name in NAVIGATION_PAGES
        }
        shell = SimpleNamespace(_navigation_buttons=buttons)
        EduDownloaderApp._select_navigation_page(shell, PAGE_HOME)
        for control in buttons.values():
            control.configure.reset_mock()
        EduDownloaderApp._select_navigation_page(shell, PAGE_PDF)
        self.assertEqual(buttons[PAGE_HOME].configure.call_count, 1)
        self.assertEqual(buttons[PAGE_TOOLS].configure.call_count, 1)
        for name in set(NAVIGATION_PAGES) - {PAGE_HOME, PAGE_TOOLS}:
            buttons[name].configure.assert_not_called()

    def test_word_resize_repositions_only_at_layout_breakpoint(self):
        page = SimpleNamespace(word_new_button=Mock())
        for name in (
            "word_hint_label",
            "word_source_label",
            "word_destination_label",
            "word_status_label",
        ):
            setattr(page, name, widget(wraplength=0))
        PdfToolsPage._resize_word_card(page, SimpleNamespace(width=800))
        page.word_new_button.grid.reset_mock()
        PdfToolsPage._resize_word_card(page, SimpleNamespace(width=800))
        page.word_new_button.grid.assert_not_called()
        self.assertEqual(page.word_hint_label.configure.call_count, 1)
        PdfToolsPage._resize_word_card(page, SimpleNamespace(width=400))
        page.word_new_button.grid.assert_called_once_with(
            row=1, column=0, columnspan=2, pady=(8, 0), sticky="w"
        )


class SettingsWorkerTests(unittest.TestCase):
    def test_integrity_resolution_runs_off_tk_and_is_not_repeated_in_callback(self):
        thread_ids = []
        page = SimpleNamespace(
            _component_manager=SimpleNamespace(refresh_all=lambda: ()),
            _component_updater=SimpleNamespace(base_dir=Path("test-components")),
            _component_worker=None,
            _component_results=Queue(),
            _settings_closing=False,
            is_component_operation_active=False,
            component_state_labels={},
            _set_diagnostic_controls_busy=Mock(),
            _schedule_settings_poll=Mock(),
            after=Mock(),
            winfo_exists=lambda: True,
            components_refresh_button=Mock(),
            update_repair_button=Mock(),
            _poll_component_results=Mock(),
        )
        page._start_settings_worker = MethodType(
            SettingsPage._start_settings_worker, page
        )

        def resolve(_base):
            thread_ids.append(threading.get_ident())
            return SimpleNamespace(managed_issue="invalid_managed_hash")

        with patch("ui_pages.resolve_active_yt_dlp", side_effect=resolve):
            SettingsPage._refresh_components(page)
            page._component_worker.join(timeout=2)
        self.assertFalse(page._component_worker.is_alive())
        self.assertNotEqual(thread_ids, [threading.get_ident()])
        self.assertEqual(len(thread_ids), 1)
        with patch(
            "ui_pages.resolve_active_yt_dlp", side_effect=AssertionError("Tk IO")
        ):
            SettingsPage._poll_component_results(page)
        page.update_repair_button.grid.assert_called_once()

    def test_storage_check_runs_in_update_worker_before_presentation(self):
        thread_ids = []
        catalogue_thread_ids = []
        check = UpdateCheck(
            UpdateCheckStatus.UPDATE_AVAILABLE,
            "2026.08.19",
            SimpleNamespace(version="2026.09.01"),
        )
        storage = ManagedRootCheck(Path("test-components"), ManagedRootState.READ_ONLY)
        page = SimpleNamespace(
            _component_updater=SimpleNamespace(
                base_dir=Path("test-components"), check=lambda: check
            ),
            _available_release=None,
            _component_states={ComponentId.YT_DLP: ComponentState.READY},
            is_component_operation_active=False,
            _settings_closing=False,
            _set_diagnostic_controls_busy=Mock(),
            _schedule_settings_poll=Mock(),
            show_component_indicator=Mock(),
            _refresh_component_catalogue=lambda: catalogue_thread_ids.append(
                threading.get_ident()
            ),
            _update_events=Queue(),
            update_status=Mock(),
            update_check_button=Mock(),
            update_action_button=Mock(),
            after=Mock(),
            _poll_yt_dlp_update=Mock(),
        )
        page._start_settings_worker = MethodType(
            SettingsPage._start_settings_worker, page
        )
        page._invalidate_yt_dlp_offer = MethodType(
            SettingsPage._invalidate_yt_dlp_offer, page
        )

        def probe(_base):
            thread_ids.append(threading.get_ident())
            return storage

        with patch("ui_pages.probe_managed_root", side_effect=probe):
            SettingsPage._check_yt_dlp_update(page)
            page._update_worker.join(timeout=2)
        self.assertFalse(page._update_worker.is_alive())
        self.assertEqual(len(thread_ids), 1)
        self.assertNotEqual(thread_ids[0], threading.get_ident())
        self.assertEqual(catalogue_thread_ids, thread_ids)
        kind, result = page._update_events.get_nowait()
        self.assertEqual(kind, "check")
        with patch("ui_pages.probe_managed_root", side_effect=AssertionError("Tk IO")):
            SettingsPage._display_yt_dlp_check(
                page, result.check, storage=result.storage
            )
        page.update_action_button.grid.assert_not_called()
        self.assertIn(
            "não permite instalar",
            page.update_status.configure.call_args.kwargs["text"],
        )


class IdleCallbacksTests(unittest.TestCase):
    def test_late_focus_is_revalidated_and_only_presentation_timers_are_cancelled(self):
        page = SimpleNamespace(
            _download_active=False,
            _close_requested=False,
            _current_page=PAGE_DOWNLOADS,
            after_idle=Mock(return_value="focus-timer"),
            after_cancel=Mock(),
            link_entry=Mock(),
            _settings_scroll_after_id="scroll-timer",
            _close_poll_after_id="functional-poll",
        )
        EduDownloaderApp._focus_link_entry(page)
        callback = page.after_idle.call_args.args[0]
        EduDownloaderApp._focus_link_entry(page)
        page.after_cancel.assert_called_with("focus-timer")
        page._current_page = PAGE_HOME
        EduDownloaderApp._cancel_page_idle_callbacks(page)
        callback()
        page.link_entry.focus_set.assert_not_called()
        self.assertIsNone(page._focus_link_after_id)
        self.assertIsNone(page._settings_scroll_after_id)
        self.assertEqual(page._close_poll_after_id, "functional-poll")

    def test_theme_redraw_is_coalesced_cancelled_on_close_and_guarded(self):
        page = PreviewLoadingTests().make_page()
        page._preview_theme_after_id = None
        page._tool_height_after_id = "tool-height-idle"
        page._merge_metadata_generation = 0
        page._merge_metadata_after_id = None
        variable = Mock()
        page._form_write_traces.append((variable, "preview-write"))
        page._render_images_preview = Mock()
        page._render_poster_preview = Mock()
        page.after_idle = Mock(return_value="theme-idle")
        with patch("ui_pages.ctk.CTkScrollableFrame._set_appearance_mode"):
            page._set_appearance_mode("Dark")
            page._set_appearance_mode("Light")
        page.after_cancel.assert_called_with("theme-idle")
        callback = page.after_idle.call_args.args[0]
        page.close()
        variable.trace_remove.assert_called_once_with("write", "preview-write")
        self.assertFalse(page._form_write_traces)
        self.assertIsNone(page._preview_theme_after_id)
        self.assertIsNone(page._tool_height_after_id)
        page.after_cancel.assert_any_call("tool-height-idle")
        callback()
        page._render_images_preview.assert_not_called()
        page._render_poster_preview.assert_not_called()


class OrderedPathListTests(unittest.TestCase):
    def make_list(self):
        paths = _OrderedPathList.__new__(_OrderedPathList)
        paths._paths = []
        paths._selected = Value(-1)
        paths._enabled = True
        paths._rows = Mock()
        paths._design = Mock()
        paths._rows.winfo_children.return_value = []
        paths._row_controls = {}
        paths._inline_order = False
        paths._empty_label = Mock()
        paths._empty_text = "Vazio"
        paths._detail_for_path = None
        paths._on_change = Mock()
        paths._on_selection_change = Mock()
        paths._drag = None
        return paths

    def test_selection_does_not_report_content_change_or_recreate_rows(self):
        paths = self.make_list()
        with patch.object(paths._design, "form_radio") as radio:
            radio.return_value.winfo_manager.return_value = ""
            paths.set_paths([Path("a.pdf"), Path("b.pdf")])
            paths._on_change.reset_mock()
            command = radio.call_args.kwargs["command"]
            paths._selected.set(1)
            command()
            paths._on_selection_change.assert_called_once_with()
            paths._on_change.assert_not_called()
            self.assertEqual(radio.call_count, 2)
            self.assertEqual(paths.selected_index, 1)
            self.assertEqual(paths.paths, (Path("a.pdf"), Path("b.pdf")))

    def test_move_remove_and_add_preserve_order_selection_and_notifications(self):
        paths = self.make_list()
        with patch.object(paths._design, "form_radio") as radio:
            radio.return_value.winfo_manager.return_value = ""
            paths.set_paths([Path("a.pdf"), Path("b.pdf")])
            paths._selected.set(1)
            paths.move_selected(-1)
            self.assertEqual(paths.paths, (Path("b.pdf"), Path("a.pdf")))
            self.assertEqual(paths.selected_index, 0)
            paths.remove_selected()
            self.assertEqual(paths.paths, (Path("a.pdf"),))
            self.assertEqual(paths.selected_index, 0)
            self.assertEqual(paths.add_paths([Path("a.pdf"), Path("c.pdf")]), 1)
            self.assertEqual(paths.paths, (Path("a.pdf"), Path("c.pdf")))
            self.assertEqual(paths.selected_index, 1)
            self.assertEqual(paths._on_change.call_count, 4)
            paths._on_selection_change.assert_not_called()

    def test_duplicate_names_keep_parent_labels_and_metadata(self):
        paths = self.make_list()
        paths._detail_for_path = lambda _: "2 páginas"
        with patch.object(paths._design, "form_radio") as radio:
            radio.return_value.winfo_manager.return_value = ""
            paths.set_paths(
                [Path("primeiro/a.pdf"), Path("segundo/a.pdf"), Path("b.pdf")]
            )
        self.assertEqual(
            [call.kwargs["text"] for call in radio.call_args_list],
            [
                "1. a.pdf — primeiro\n2 páginas",
                "2. a.pdf — segundo\n2 páginas",
                "3. b.pdf\n2 páginas",
            ],
        )


class PreviewLoadingTests(unittest.TestCase):
    def make_page(self):
        page = PdfToolsPage.__new__(PdfToolsPage)
        page._closed = False
        page._form_write_traces = []
        page._preview_resize_after_id = None
        page.after = Mock(return_value="preview-timer")
        page.after_cancel = Mock()
        page._refresh_controls = Mock()
        page.image_files = SimpleNamespace(paths=(Path("image.png"),), _drag=None)
        page._analysis_worker = Mock()
        page._result_worker = Mock()
        page._analysis_after_id = None
        page._result_after_id = None
        page._poster_source = Path("image.png")
        page._poster_quality = Value("")
        for prefix in ("images", "poster"):
            canvas = Mock()
            canvas.winfo_width.return_value = 400
            canvas.winfo_height.return_value = 300
            canvas.cget.return_value = "300"
            setattr(page, prefix + "_preview_canvas", canvas)
            for name, value in (
                ("generation", 0),
                ("after_id", None),
                ("pending", False),
                ("worker_active", False),
                ("failed", False),
                ("loading", False),
                ("results", Queue()),
            ):
                setattr(page, "_" + prefix + "_preview_" + name, value)
            setattr(page, "_" + prefix + "_preview", Mock())
        return page

    def test_resize_keeps_loading_and_invalidates_old_previews(self):
        for prefix in ("images", "poster"):
            with self.subTest(prefix=prefix):
                page = self.make_page()
                getattr(page, "_invalidate_" + prefix + "_preview")()
                self.assertIsNone(getattr(page, "_" + prefix + "_preview"))
                getattr(page, "_render_" + prefix + "_preview")()
                canvas = getattr(page, prefix + "_preview_canvas")
                self.assertEqual(
                    canvas.create_text.call_args.kwargs["text"],
                    "Atualizando pré-visualização...",
                )
                self.assertTrue(getattr(page, "_" + prefix + "_preview_loading"))

    def test_stale_results_do_not_end_current_loading(self):
        for prefix, result_type in (
            ("images", _ImagesPdfPreviewResult),
            ("poster", _PosterPreviewResult),
        ):
            with self.subTest(prefix=prefix):
                page = self.make_page()
                getattr(page, "_invalidate_" + prefix + "_preview")()
                getattr(page, "_" + prefix + "_preview_results").put(
                    result_type(0, failed=True)
                )
                getattr(page, "_poll_" + prefix + "_preview")()
                self.assertTrue(getattr(page, "_" + prefix + "_preview_loading"))
                self.assertIsNone(getattr(page, "_" + prefix + "_preview"))

    def test_current_failure_ends_loading_and_closed_page_does_not_draw(self):
        for prefix, result_type in (
            ("images", _ImagesPdfPreviewResult),
            ("poster", _PosterPreviewResult),
        ):
            with self.subTest(prefix=prefix):
                page = self.make_page()
                getattr(page, "_invalidate_" + prefix + "_preview")()
                getattr(page, "_" + prefix + "_preview_results").put(
                    result_type(1, failed=True)
                )
                getattr(page, "_poll_" + prefix + "_preview")()
                self.assertFalse(getattr(page, "_" + prefix + "_preview_loading"))
                canvas = getattr(page, prefix + "_preview_canvas")
                canvas.reset_mock()
                page._closed = True
                getattr(page, "_render_" + prefix + "_preview")()
                canvas.delete.assert_not_called()

    def test_worker_start_failure_does_not_leave_loading_stuck(self):
        for prefix in ("images", "poster"):
            with self.subTest(prefix=prefix):
                page = self.make_page()
                page._current_images_layout = Mock()
                page._current_poster_layout = Mock()
                page._thread_factory = Mock()
                page._thread_factory.return_value.start.side_effect = RuntimeError(
                    "thread"
                )
                getattr(page, "_invalidate_" + prefix + "_preview")()
                getattr(page, "_request_" + prefix + "_preview")()
                self.assertFalse(getattr(page, "_" + prefix + "_preview_loading"))
                self.assertTrue(getattr(page, "_" + prefix + "_preview_failed"))


if __name__ == "__main__":
    unittest.main()
