"""Real Tk regressions for cancellation by the callback's owner."""

import sys
import tkinter as tk
import unittest

import customtkinter as ctk

from ui_lifecycle import (
    AppRoot,
    AppearanceModeTracker,
    FormEntry,
    PreviewTextbox,
    ScalingTracker,
)


class UiLifecycleTests(unittest.TestCase):
    def make_root(self):
        root = AppRoot()
        root.withdraw()

        def close():
            try:
                if root.winfo_exists():
                    root.destroy()
            except tk.TclError:
                pass

        self.addCleanup(close)
        ctk.CTkLabel(root, text="QA")
        return root

    def test_destroying_the_timer_owner_keeps_another_root_running(self):
        first = self.make_root()
        second = self.make_root()
        trackers = {AppearanceModeTracker.update, ScalingTracker.check_dpi_scaling}
        self.assertTrue(trackers <= first._tracker_jobs.keys())
        own_job = second.after(5_000, lambda: None)
        self.addCleanup(second.after_cancel, own_job)

        first.destroy()

        self.assertTrue(trackers <= second._tracker_jobs.keys())
        self.assertTrue(second.tk.call("after", "info", own_job))
        self.assertNotIn(first, AppearanceModeTracker.app_list)
        self.assertNotIn(first, ScalingTracker.window_dpi_scaling_dict)

    def test_destroying_preview_cancels_its_owned_scrollbar_poll(self):
        root = self.make_root()
        preview = PreviewTextbox(root)
        pending = preview._scrollbar_job
        self.assertTrue(root.tk.call("after", "info", pending))

        preview.destroy()

        with self.assertRaises(tk.TclError):
            root.tk.call("after", "info", pending)
        self.assertTrue(root._tracker_jobs)

    def test_destroying_entry_releases_only_its_original_variable_trace(self):
        root = self.make_root()
        initial = tk.StringVar(root)
        replacement = tk.StringVar(root)
        observed = []
        caller_token = initial.trace_add(
            "write", lambda *_args: observed.append(initial.get())
        )
        entry = FormEntry(root, textvariable=initial)
        self.assertEqual(len(initial.trace_info()), 2)
        entry.configure(textvariable=replacement)

        entry.destroy()

        self.assertEqual(initial.trace_info(), [(("write",), caller_token)])
        self.assertEqual(replacement.trace_info(), [])
        initial.set("Preferência")
        self.assertEqual(observed, ["Preferência"])
        initial.trace_remove("write", caller_token)

    @unittest.skipUnless(sys.platform == "win32", "Janela nativa do Windows")
    def test_switching_appearance_does_not_unmap_the_window(self):
        appearance = ctk.get_appearance_mode()
        self.addCleanup(ctk.set_appearance_mode, appearance)
        ctk.set_appearance_mode("Light")
        root = self.make_root()
        root.state("zoomed")
        root.update()
        self.assertTrue(root.winfo_ismapped())
        unmaps = []
        tk.Misc.bind(
            root,
            "<Unmap>",
            lambda event: unmaps.append(event) if event.widget is root else None,
            add="+",
        )

        for mode in ("Dark", "Light", "Dark", "Light"):
            ctk.set_appearance_mode(mode)
            root.update()
            self.assertEqual(ctk.get_appearance_mode(), mode)
            self.assertEqual(root.state(), "zoomed")
            self.assertTrue(root.winfo_ismapped())

        self.assertEqual(unmaps, [])
