"""Contratos da abertura e do layout na janela Windows."""

import json
import logging
import os
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import PAGE_DOWNLOADS, PAGE_HOME, NAVIGATION_PAGES, EduDownloaderApp
from constants import MOTION_BALANCED, MOTION_OFF
from downloader import DownloadService
from settings import default_settings, save_settings
from ui_motion import MotionClock
from ui_transitions import STARTUP_MS


def isolated_window(test):
    """Cada caso nativo possui seu próprio interpretador Tcl."""

    @wraps(test)
    def run(self):
        marker = "EDUDOWNLOADER_STARTUP_TEST_CASE"
        if os.environ.get(marker) == test.__name__:
            test(self)
            return
        process = subprocess.run(
            [sys.executable, "-m", "unittest", self.id(), "-v"],
            env={**os.environ, marker: test.__name__},
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        output = process.stdout + process.stderr
        self.assertEqual(process.returncode, 0, output)
        if "OK (skipped=1)" in output:
            self.skipTest(output.strip())
        self.assertIn("Ran 1 test", output)

    return run


class PageStackLayoutTests(unittest.TestCase):
    def test_hidden_widgets_do_not_influence_native_resize_readiness(self):
        from ui_resize_cover import ResizePresentation

        shell = Mock()
        cover = Mock(operation=4)
        setup = SimpleNamespace(
            app=shell, cover=cover, layout_pending=False, changed=Mock()
        )
        shell._page_stack.widget_is_presented.return_value = False
        widget = Mock()
        ResizePresentation._configured(setup, SimpleNamespace(widget=widget))
        setup.changed.assert_not_called()
        shell._page_stack.widget_is_presented.return_value = True
        ResizePresentation._configured(setup, SimpleNamespace(widget=widget))
        setup.changed.assert_called_once_with()


@unittest.skipUnless(os.name == "nt", "Maximização nativa do Tk no Windows")
class StartupPresentationTests(unittest.TestCase):
    def open_window(self, *, windows_reduced=False, legacy_motion=None):
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="edu-start-"))
        logger = logging.Logger("edu-start")
        logger.addHandler(logging.NullHandler())
        service = DownloadService(Path(directory), logger)
        self.addCleanup(service.close)
        self.now = 0.0
        settings = default_settings()
        settings_path = Path(directory) / "settings.json"
        self.enterContext(
            patch("settings.get_settings_path", return_value=settings_path)
        )
        save_settings(settings, settings_path)
        if legacy_motion is not None:
            settings_path.write_text(
                json.dumps({**settings, "motion": legacy_motion}), encoding="utf-8"
            )
        with patch(
            "app.MotionClock",
            side_effect=lambda window: MotionClock(
                window, read_system=lambda: windows_reduced, clock=lambda: self.now
            ),
        ):
            try:
                window = EduDownloaderApp(service)
            except tk.TclError as error:
                if "display" in str(error).lower():
                    self.skipTest(str(error))
                raise
        self.addCleanup(lambda: window.close() if not window._close_finalized else None)
        self.errors = []
        window.report_callback_exception = lambda *args: self.errors.append(args)
        return window

    @isolated_window
    def test_first_mapping_is_maximized_and_restoration_keeps_persistent_cards(self):
        window = self.open_window(windows_reduced=True)
        states = []
        tk.Misc.bind(
            window,
            "<Map>",
            lambda event: (
                states.append(window.state()) if event.widget is window else None
            ),
            add="+",
        )
        window.update()
        settled = tk.BooleanVar(master=window)
        window.after(350, settled.set, True)
        window.wait_variable(settled)
        self.assertEqual(states, ["zoomed"])
        self.assertFalse(self.errors)
        self.assertEqual(
            [
                name
                for name, page in window._pages.items()
                if page._parent_frame.winfo_ismapped()
            ],
            [PAGE_HOME],
        )
        window.state("normal")
        cards = [
            window.home_page.module_buttons[name].master
            for name in ("PDF", "Documentos", "Mídia")
        ]
        pages = tuple(window._pages.values())
        window.home_page.link_entry.insert(0, "https://example.invalid/qa")
        for size, rows in (
            ("1280x820", 1),
            ("1024x768", 2),
            ("860x600", 3),
            ("1280x820", 1),
        ):
            window.geometry(size)
            window.update()
            self.assertEqual(window.state(), "normal")
            self.assertEqual(len({card.grid_info()["row"] for card in cards}), rows)
            self.assertEqual(tuple(window._pages.values()), pages)
            self.assertEqual(
                window.home_page.link_entry.get(), "https://example.invalid/qa"
            )
        window.state("zoomed")
        window.update()
        self.assertEqual(window.state(), "zoomed")
        self.assertIsNone(window._presentation._startup_label)
        self.assertFalse(self.errors)

    @isolated_window
    def test_cover_is_client_sized_and_released_on_completion(self):
        window = self.open_window(legacy_motion=MOTION_OFF)
        window.update()
        self.assertEqual(window._motion.preference, MOTION_BALANCED)
        presentation = window._presentation
        cover = presentation._startup_label
        self.assertIsNotNone(cover)
        self.assertEqual(
            (cover.winfo_width(), cover.winfo_height()),
            (window.winfo_width(), window.winfo_height()),
        )
        self.assertTrue(window.home_page._parent_frame.winfo_viewable())
        self.assertTrue(window._motion.active("startup"))
        self.now = STARTUP_MS / 1000 + 1
        window._motion._cancel_timer()
        window._motion._tick()
        self.assertFalse(cover.winfo_exists())
        self.assertIsNone(presentation._startup_label)
        self.assertIsNone(presentation._startup_idle)
        self.assertIsNotNone(window.sidebar.brand_symbol.cget("image"))
        self.assertFalse(window._motion.active("startup") or self.errors)

    @isolated_window
    def test_navigation_cancels_cover_without_moving_host_and_close_clears_timers(self):
        window = self.open_window()
        window.update()
        presentation = window._presentation
        cover = presentation._startup_label
        self.assertIsNotNone(cover)
        window._navigation_buttons[PAGE_DOWNLOADS].invoke()
        self.assertFalse(cover.winfo_exists())
        for name in (*NAVIGATION_PAGES, PAGE_HOME) * 5:
            window._navigation_buttons[name].invoke()
        window.update()
        self.assertEqual(window._current_page, PAGE_HOME)
        self.assertEqual(window._page_host.winfo_y(), 0)
        self.assertFalse(window._motion.active("page"))
        pages = {page._parent_frame for page in window._pages.values()}
        mapped = [
            frame
            for frame in window._page_host.winfo_children()
            if frame in pages and frame.winfo_ismapped()
        ]
        self.assertIs(mapped[-1], window.home_page._parent_frame)
        window.close()
        self.assertFalse(
            window._motion._effects or window._motion._timer or self.errors
        )

    @isolated_window
    def test_reduced_motion_from_windows_opens_the_shell_without_a_cover(self):
        window = self.open_window(windows_reduced=True, legacy_motion=MOTION_BALANCED)
        window.update()
        self.assertEqual(window.state(), "zoomed")
        self.assertEqual(window._current_page, PAGE_HOME)
        self.assertIsNone(window._presentation._startup_label)
        self.assertFalse(window._motion.active("startup") or self.errors)

    @isolated_window
    def test_mainloop_maps_the_window_after_customtkinter_prepares_it(self):
        window = self.open_window()
        mapped = []

        def close_from_first_map(event):
            if event.widget is window:
                mapped.append((window.state(), window._window_exists))
                window.after_idle(window.close)

        tk.Misc.bind(window, "<Map>", close_from_first_map, add="+")
        window.mainloop()
        self.assertEqual(mapped, [("zoomed", True)])
        self.assertTrue(window._close_finalized)
        self.assertFalse(
            window._motion._effects or window._motion._timer or self.errors
        )
