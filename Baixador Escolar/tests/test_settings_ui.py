"""Integração das preferências e do diagnóstico com a janela persistente."""

import json
import logging
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont, ttk
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk

from app import PAGE_DOWNLOADS, PAGE_FILES, PAGE_SETTINGS, EduDownloaderApp
from component_manager import ComponentId
from constants import LEGAL_NOTICE, MOTION_BALANCED, MOTION_OFF
from downloader import DownloadService
from libreoffice_managed import AcquisitionResult, AcquisitionStatus
from settings import load_settings, save_settings
from ui_design import PRIMARY, SOFT


class SettingsShellTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="edu-settings-ui-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings_path = self.root / "settings.json"
        self.enterContext(
            patch(
                "app.load_settings",
                side_effect=lambda: load_settings(self.settings_path),
            )
        )
        self.enterContext(
            patch(
                "app.save_settings",
                side_effect=lambda values: save_settings(values, self.settings_path),
            )
        )

    def create_window(self):
        logger = logging.Logger("settings-ui-fixture")
        logger.addHandler(logging.NullHandler())
        service = DownloadService(self.root, logger)
        self.addCleanup(service.close)
        try:
            window = EduDownloaderApp(service)
        except tk.TclError as error:
            if "display" in str(error).lower():
                self.skipTest(str(error))
            raise
        self.addCleanup(self.close_window, window)
        self.callback_errors = []
        window.report_callback_exception = lambda *error: self.callback_errors.append(
            error
        )
        window._show_page(PAGE_SETTINGS)
        window.update()
        self.assertFalse(self.callback_errors)
        return window

    def close_window(self, window):
        if window._close_finalized:
            return
        try:
            window.winfo_exists()
        except tk.TclError:
            return
        with patch.object(window, "_ask_confirmation", return_value=True):
            window.close()
        self.pump_until(window, lambda: window._close_finalized)

    def pump_until(self, window, predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            window.update()
            self.assertFalse(self.callback_errors)
            time.sleep(0.01)
        self.assertTrue(predicate())

    def test_theme_and_font_scale_apply_to_hidden_pages_and_restore_on_restart(self):
        window = self.create_window()
        page = window.settings_page
        entry_font = window.link_entry.cget("font")
        nav_size = entry_font.cget("size")
        native = tkfont.nametofont("TkHeadingFont", root=window)
        native_size = native.cget("size")
        self.assertEqual(page.text_scale_status.get(), "Padrão (100%)")
        self.assertEqual(page.theme_buttons["Claro"].cget("fg_color"), PRIMARY)
        page.theme_buttons["Escuro"].invoke()
        self.assertEqual(ctk.get_appearance_mode(), "Dark")
        self.assertEqual(page.theme_buttons["Claro"].cget("fg_color"), SOFT)
        self.assertEqual(page.theme_buttons["Escuro"].cget("fg_color"), PRIMARY)

        page.text_scale_decrease.invoke()
        self.assertEqual(page.text_scale_status.get(), "90%")
        self.assertEqual(page.text_scale_decrease.cget("state"), "disabled")
        self.assertEqual(entry_font.cget("size"), round(nav_size * 0.9))
        page.text_scale_reset.invoke()
        self.assertEqual(entry_font.cget("size"), nav_size)
        for _ in range(3):
            page.text_scale_increase.invoke()
        self.assertEqual(page.text_scale_increase.cget("state"), "disabled")
        self.assertEqual(page.text_scale_status.get(), "120%")
        self.assertEqual(entry_font.cget("size"), round(nav_size * 1.2))
        self.assertEqual(native.cget("size"), round(native_size * 1.2))

        window._show_page(PAGE_FILES)
        tree = window.files_page.file_tree
        font_name = ttk.Style(window).lookup(tree.cget("style"), "font")
        tree_font = tkfont.nametofont(font_name, root=window)
        self.assertEqual(abs(tree_font.cget("size")), entry_font.cget("size"))
        window.update()
        self.assertFalse(self.callback_errors)
        self.close_window(window)
        restarted = self.create_window()
        self.assertEqual(restarted.settings_page.text_scale_status.get(), "120%")
        self.assertEqual(
            restarted.link_entry.cget("font").cget("size"), round(nav_size * 1.2)
        )
        self.assertEqual(ctk.get_appearance_mode(), "Dark")

    def test_changing_folder_updates_both_pages_and_keeps_existing_requests(self):
        window = self.create_window()
        self.assertIn("(padrão)", window.settings_page.download_folder_path.get())
        self.assertFalse((self.root / "Downloads").exists())
        first = self.root / "Aula João"
        second = self.root / "Pasta com espaço e conteúdo autorizado"
        first.mkdir()
        second.mkdir()
        window.download_queue.add = enqueue = Mock()
        for destination in (first, second):
            window._show_page(PAGE_SETTINGS)
            with patch("app.filedialog.askdirectory", return_value=str(destination)):
                window.settings_page.download_folder_button.invoke()
            self.assertEqual(
                window.settings_page.download_folder_path.get(), str(destination)
            )
            self.assertEqual(
                window.downloads_page.destination_text.get(), str(destination)
            )
            window._show_page(PAGE_DOWNLOADS)
            window.link_entry.insert(0, "https://example.com/aula")
            window.download_button.invoke()
        self.assertEqual(
            [call.args[0].destination_dir for call in enqueue.call_args_list],
            [first, second],
        )
        self.assertEqual(
            load_settings(self.settings_path)["dialog_folders"]["downloads.output"],
            str(second),
        )
        with (
            patch("app.filedialog.askdirectory", return_value=str(first / "ausente")),
            patch.object(window, "_show_warning") as warning,
        ):
            window._choose_download_destination()
        warning.assert_called_once()
        self.assertEqual(window.downloads_page.destination_text.get(), str(second))

    def test_long_download_path_remains_readable_and_unchanged_at_120_percent(self):
        window = self.create_window()
        page = window.settings_page
        page.theme_buttons["Escuro"].invoke()
        window._change_text_scale(120)
        destination = self.root / ("SegmentoComprido" * 7) / ("subpasta" * 15)
        page.show_download_destination(destination)
        entry = page.download_folder_entry

        for size in ("860x600", "1024x768"):
            with self.subTest(size=size):
                window.state("normal")
                window.geometry(size)
                window.update()
                entry.xview_moveto(1)
                self.assertEqual(entry._entry.xview()[1], 1)
                self.assertEqual(entry.get(), str(destination))
                self.assertEqual(entry.cget("state"), "readonly")
                self.assertLess(entry.winfo_width(), window.winfo_width())

        self.assertEqual(page.download_folder_path.get(), str(destination))

    def test_unreadable_preferences_keep_original_when_text_scale_is_applied(self):
        original = b'{"tema":"escuro",'
        self.settings_path.write_bytes(original)
        page = self.create_window().settings_page
        page.text_scale_increase.invoke()
        self.assertEqual(page.text_scale_status.get(), "110%")
        self.assertIn("não foi salva", page._persistence_status.get())
        self.assertEqual(self.settings_path.read_bytes(), original)

    def test_settings_only_show_remaining_controls_in_a_small_window(self):
        window = self.create_window()
        page = window.settings_page
        if window.state() == "zoomed":
            window.state("normal")
        window.geometry("860x600")
        window._change_text_scale(120)
        window.update()
        self.assertEqual(
            sorted(int(item.grid_info()["row"]) for item in page.grid_slaves()),
            [0, 1, 2, 3],
        )
        diagnostics = page.diagnostics_button.master
        self.assertEqual(int(diagnostics.grid_info()["row"]), 3)
        self.assertGreater(int(diagnostics.grid_info()["pady"][1]), 0)
        pending = list(page.winfo_children())
        labels = []
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, (ctk.CTkLabel, ctk.CTkButton)):
                labels.append(widget.cget("text"))
        for removed in (
            "EduDownloader",
            "Versão 2.5.0",
            "Sobre o EduDownloader",
            "Movimento da interface",
        ):
            self.assertNotIn(removed, labels)
        self.assertFalse(hasattr(page, "motion_menu") or hasattr(page, "about_button"))
        self.assertIn("Tamanho do texto", labels)
        self.assertIn("Ver diagnóstico", labels)
        self.assertIn(
            LEGAL_NOTICE,
            [
                child.cget("text")
                for child in window._pages[PAGE_DOWNLOADS].winfo_children()
                if isinstance(child, ctk.CTkLabel)
            ],
        )

    def test_windows_motion_change_still_settles_effect_after_legacy_migration(self):
        self.settings_path.write_text(
            json.dumps({"motion": "desativado"}), encoding="utf-8"
        )
        window = self.create_window()
        frames = []
        event = tk.Event()
        event.widget, event.type = window, tk.EventType.FocusIn
        self.assertEqual(window._motion.preference, MOTION_BALANCED)
        with patch.object(window._motion, "_read_system", return_value=False):
            window._sync_window_motion(event)
            window._motion.play("fixture", window.settings_page, 1000, frames.append)
        self.assertTrue(window._motion.active("fixture"))
        with patch.object(window._motion, "_read_system", return_value=True):
            window._sync_window_motion(event)
        self.assertEqual(frames, [0, 1])
        self.assertEqual(window._motion.mode, MOTION_OFF)
        self.assertFalse(window._motion.active("fixture"))
        self.assertNotIn("motion", window.settings)

    def test_keyboard_reaches_diagnosis_and_skips_its_closed_panel(self):
        window = self.create_window()
        page = window.settings_page
        if window.state() == "zoomed":
            window.state("normal")
        window.geometry("860x600")
        page.text_scale_increase.invoke()
        page.text_scale_increase.invoke()
        window.update()
        self.assertEqual(window.settings["text_scale"], 120)
        presentation = window._resize_presentation
        if presentation is not None:
            self.pump_until(
                window,
                lambda: (
                    not presentation.layout_pending
                    and (presentation.cover is None or not presentation.cover.active)
                ),
                seconds=5,
            )
        entry = page.download_folder_entry._entry
        tk.Misc.focus_force(entry)
        window.update()
        self.assertIs(entry.tk_focusNext(), page.diagnostics_button)
        tk.Misc.event_generate(entry, "<Tab>")
        window.update()
        self.assertIs(window.focus_get(), page.diagnostics_button)
        self.assertIsNot(
            page.diagnostics_button.tk_focusNext(), page.components_refresh_button
        )
        canvas = page._parent_canvas
        self.assertLessEqual(
            page.diagnostics_button.winfo_rooty()
            + page.diagnostics_button.winfo_height(),
            canvas.winfo_rooty() + canvas.winfo_height() + 2,
        )
        page.diagnostics_button.invoke()
        window.update()
        self.assertIs(
            page.diagnostics_button.tk_focusNext(), page.components_refresh_button
        )

    def test_diagnosis_survives_theme_panel_and_page_changes_and_safe_close(self):
        window = self.create_window()
        page = window.settings_page
        entered, finish = threading.Event(), threading.Event()
        self.addCleanup(finish.set)

        def diagnosis():
            entered.set()
            if not finish.wait(5):
                raise TimeoutError
            raise OSError("erro de teste")

        page._component_manager.refresh_all = Mock(side_effect=diagnosis)
        self.assertFalse(page.diagnostics_panel.grid_info())
        page.diagnostics_button.invoke()
        page.components_refresh_button.invoke()
        self.assertTrue(entered.wait(1))
        state = page.component_state_labels[ComponentId.YT_DLP]
        self.assertEqual(state.cget("text"), "Verificando…")
        self.assertEqual(page.update_check_button.cget("state"), "disabled")
        page.theme_buttons["Escuro"].invoke()
        page.diagnostics_button.invoke()
        window._show_page(PAGE_DOWNLOADS)
        self.assertTrue(page.is_component_operation_active)
        window._show_page(PAGE_SETTINGS)
        page.diagnostics_button.invoke()
        finish.set()
        self.pump_until(window, lambda: not page.is_component_operation_active)
        self.assertEqual(state.cget("text"), "Erro de verificação")
        self.assertEqual(page.update_check_button.cget("state"), "normal")
        entered.clear()
        finish.clear()
        page.components_refresh_button.invoke()
        self.assertTrue(entered.wait(1))
        with patch.object(window, "_ask_confirmation", return_value=True):
            window.close()
        self.assertFalse(window._close_finalized)
        finish.set()
        self.pump_until(window, lambda: window._close_finalized)
        self.assertFalse(page._component_poll_ids)

    def test_worker_start_failures_allow_diagnosis_retry_and_close(self):
        window = self.create_window()
        page = window.settings_page
        state = page.component_state_labels[ComponentId.YT_DLP]
        refresh = Mock(return_value=())
        page._component_manager.refresh_all = refresh

        with patch.object(threading.Thread, "start", side_effect=RuntimeError):
            page.components_refresh_button.invoke()
        self.pump_until(window, lambda: not page.is_component_operation_active)
        refresh.assert_not_called()
        self.assertEqual(state.cget("text"), "Erro de verificação")
        self.assertEqual(page.components_refresh_button.cget("state"), "normal")
        self.assertFalse(page._component_poll_ids)

        with patch.object(threading.Thread, "start", side_effect=OSError):
            page.update_check_button.invoke()
        self.pump_until(window, lambda: not page.is_component_operation_active)
        self.assertIn("Não foi possível verificar", page.update_status.cget("text"))
        self.assertEqual(page.update_check_button.cget("state"), "normal")

        page.components_refresh_button.invoke()
        self.pump_until(window, lambda: not page.is_component_operation_active)
        refresh.assert_called_once_with()
        self.close_window(window)
        self.assertFalse(page._component_poll_ids)

    def test_closing_shell_removes_tcl_traces_owned_by_each_page(self):
        window = self.create_window()
        pdf = window.pdf_page
        variables = (
            window.files_page._query,
            pdf._extract_selection,
            pdf._pdf_images_selection,
            pdf._pdf_images_scope,
            *pdf._pdf_preference_vars().values(),
            pdf.merge_page_preview.number,
            window.media_page._extraction_mode,
            window.media_page._segment_start,
        )
        for variable in variables:
            self.assertTrue(variable.trace_info())

        self.close_window(window)

        for variable in variables:
            self.assertEqual(variable.trace_info(), [])

    def test_close_waits_for_a_pending_installer_with_settings_hidden(self):
        window = self.create_window()
        page = window.settings_page
        can_finish = threading.Event()
        self.addCleanup(can_finish.set)
        recorded_threads = []

        class PendingInstall:
            has_pending_installer = True

            def finish_pending_installation(self):
                recorded_threads.append(threading.get_ident())
                if can_finish.is_set():
                    self.has_pending_installer = False
                    return AcquisitionResult(
                        AcquisitionStatus.CANCELLED, None, "cancelled"
                    )
                return AcquisitionResult(
                    AcquisitionStatus.BUSY, None, "installer_pending"
                )

        page._component_installer = PendingInstall()
        window._show_page(PAGE_DOWNLOADS)
        with patch.object(window, "_ask_confirmation", return_value=True):
            window.close()
        self.pump_until(window, lambda: bool(recorded_threads))
        self.assertFalse(window._close_finalized)
        self.assertNotIn(threading.get_ident(), recorded_threads)
        can_finish.set()
        self.pump_until(window, lambda: window._close_finalized)
