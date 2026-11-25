"""Respostas semânticas, duração e limites de apresentação."""

import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import customtkinter as ctk

from app import EduDownloaderApp
from constants import MOTION_OFF, MOTION_REDUCED
from download_queue import QueueState
from downloader import DownloadResult
from ui_design import Design
from ui_feedback import ProgressBar
from ui_motion import MotionClock
from ui_notifications import NotificationCenter


class TerminalNotificationTests(unittest.TestCase):
    def test_queue_emits_only_new_real_terminals_and_keeps_details_private(self):
        app = SimpleNamespace(_notify=Mock())
        result = DownloadResult(Path("materiais-privados.mp4"), False)
        existing = DownloadResult(Path("outro-material.mp4"), True)
        snapshot = (
            SimpleNamespace(id="a", state=QueueState.DOWNLOADING, result=None),
            SimpleNamespace(id="b", state=QueueState.CANCELLED, result=None),
            SimpleNamespace(id="c", state=QueueState.COMPLETED, result=None),
            SimpleNamespace(id="d", state=QueueState.COMPLETED, result=result),
            SimpleNamespace(id="e", state=QueueState.ERROR, result=None),
            SimpleNamespace(id="f", state=QueueState.COMPLETED, result=existing),
        )
        EduDownloaderApp._notify_download_terminals(app, (), snapshot)
        self.assertEqual(
            [call.args[0] for call in app._notify.call_args_list],
            ["success", "error", "info"],
        )
        self.assertNotIn(".mp4", repr(app._notify.call_args_list))
        EduDownloaderApp._notify_download_terminals(app, snapshot, snapshot)
        self.assertEqual(app._notify.call_count, 3)


class FeedbackTkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = ctk.CTk()
        except tk.TclError as error:
            raise unittest.SkipTest(str(error)) from error

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.time = 0.0
        self.motion = MotionClock(
            self.root, clock=lambda: self.time, read_system=lambda: False
        )
        self.root._motion = self.motion
        self.host = ctk.CTkFrame(self.root)
        self.host.pack(fill="both", expand=True)
        self.host.grid_columnconfigure(0, weight=1)
        self.design = Design(self.root, motion=self.motion)
        self.addCleanup(self.host.destroy)
        self.addCleanup(self.motion.close)

    def tick(self, seconds):
        self.time += seconds
        self.motion._cancel_timer()
        self.motion._tick()

    def test_button_hover_click_and_disabled_use_the_real_command_once(self):
        action = Mock()
        button = self.design.button(self.host, "Testar", action, keyboard=True)
        button.grid()
        self.root.update()
        button._on_leave()
        self.tick(0.15)
        button._on_enter()
        self.tick(0.05)
        color = button._canvas.itemcget("inner_parts", "fill")
        self.assertNotIn(color, (button._base_color(), button._hover_fill()))
        button.invoke()
        action.assert_called_once_with()
        button.configure(state="disabled")
        button._on_enter()
        button.invoke()
        action.assert_called_once_with()
        self.assertFalse(self.motion.active(button._effect_key))

    def test_progress_stays_under_the_measurement_and_resets_at_terminal(self):
        bar = ProgressBar(self.host, mode="determinate")
        bar.grid()
        bar.set(0)
        self.root.update()
        bar.set(0.73)
        self.assertEqual(bar.get(), 0.73)
        self.tick(0.04)
        self.assertGreater(bar._determinate_value, 0)
        self.assertLess(bar._determinate_value, 0.73)
        bar.set(0)
        self.assertEqual(bar._determinate_value, 0)
        self.assertFalse(self.motion.active(bar._effect_key))
        bar.configure(mode="indeterminate")
        bar.start()
        self.assertTrue(bar._loop_running)
        self.motion.configure(MOTION_REDUCED)
        self.assertFalse(bar._loop_running)
        bar.stop()

    def test_notifications_are_bounded_non_focusable_and_clear_timers(self):
        self.motion.configure(MOTION_OFF)
        center = NotificationCenter(self.host, self.design)
        self.addCleanup(center.clear)
        focus = tk.Entry(self.host)
        focus.grid()
        self.design.set_text_scale(120)
        self.root.update()
        focus.focus_force()
        previous_geometry = self.host.grid_size(), focus.winfo_geometry()
        message = "Não foi possível concluir o download. Confira a fila."
        center.post("success", message)
        center.post("success", message)
        self.assertFalse(center._pending)
        for i in range(12):
            center.post("error", f"Falha {i}")
        self.root.update()
        self.assertEqual(len(center._pending), 3)
        self.assertIs(self.root.focus_get(), focus)
        self.assertTrue(center._card.place_info())
        self.assertEqual(
            (self.host.grid_size(), focus.winfo_geometry()), previous_geometry
        )
        self.assertGreaterEqual(
            center._message.winfo_height(), center._message.winfo_reqheight()
        )
        self.assertLessEqual(
            center._card.winfo_y() + center._card.winfo_height(),
            self.host.winfo_height(),
        )
        center.clear()
        self.assertFalse(center._card.place_info())
        self.assertIsNone(center._timer)
        self.assertIsNone(center.current)
