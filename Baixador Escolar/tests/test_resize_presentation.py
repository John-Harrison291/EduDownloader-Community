"""Contratos de composição, expiração e entrada da janela principal."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import ANY, Mock, patch
import tkinter as tk

import ui_resize_cover as resize


class NativeCoverTests(TestCase):
    def setUp(self):
        self.api = Mock()
        self.api.callback.side_effect = lambda callback: callback
        self.api.default_proc.return_value = 49
        self.api.is_minimized.return_value = False
        self.api.is_maximized.return_value = False
        self.api.flush.return_value = 0
        self.api.get_client.side_effect = self.client_rect
        self.api.select.return_value = 7
        self.api.remove_subclass.return_value = True
        self.allowed = Mock(return_value=True)
        self.clock = self.enterContext(
            patch.object(resize, "monotonic", return_value=10)
        )
        self.timers = self.enterContext(patch.object(resize, "Timer"))
        self.cover = resize._NativeCover(self.api, 42, self.allowed, 0x513615)
        self.addCleanup(self.cover.close)

    @staticmethod
    def client_rect(_hwnd, pointer):
        pointer._obj.right = 1280
        pointer._obj.bottom = 820
        return True

    def send(self, message, wp=0, lp=0):
        return self.cover.proc(42, message, wp, lp, self.cover.cookie, 0)

    def maximize(self):
        self.assertEqual(self.send(resize.WM_SYSCOMMAND, resize.SC_MAXIMIZE), 49)

    def test_install_and_forward_unhandled_messages(self):
        self.api.set_subclass.assert_called_once_with(
            42, self.cover.proc, self.cover.cookie, 0
        )
        self.assertIn(self.cover.cookie, resize._SUBCLASSES)
        self.assertEqual(self.send(0x0048, 5, 3), 49)
        self.api.default_proc.assert_called_once_with(42, 0x0048, 5, 3)
        self.assertFalse(self.cover.active)
        self.api.window.assert_not_called()

    def test_destroy_active_releases_surface_window_and_subclass(self):
        self.maximize()
        self.assertTrue(self.cover.active)
        self.assertEqual(self.send(resize.WM_NCDESTROY), 49)
        self.assertFalse(self.cover.active)
        self.assertFalse(self.cover.attached)
        self.assertNotIn(self.cover.cookie, resize._SUBCLASSES)
        self.assertNotIn(self.cover.child_cookie, resize._SUBCLASSES)
        self.assertIsNone(self.cover.child)
        self.assertIsNone(self.cover.dc)
        self.assertIsNone(self.cover.bitmap)
        self.timers.return_value.cancel.assert_called_once()
        self.api.delete_dc.assert_called_once()
        self.api.destroy_window.assert_called_once()
        self.api.remove_subclass.assert_called_once_with(
            42, self.cover.proc, self.cover.cookie
        )
        self.api.default_proc.assert_called_with(42, resize.WM_NCDESTROY, 0, 0)

    def test_native_cover_blocks_content_and_passes_only_sidebar_hit_tests(self):
        self.cover.sidebar = 43

        def rail_rect(hwnd, pointer):
            if hwnd == 43:
                pointer._obj.right = 232
                pointer._obj.bottom = 820
                return True
            return self.client_rect(hwnd, pointer)

        self.api.get_client.side_effect = rail_rect
        self.api.screen_to_client.return_value = True
        self.maximize()
        child = self.cover.child
        self.api.set_subclass.assert_called_with(
            child, self.cover.child_proc, self.cover.child_cookie, 0
        )

        def hit(x, y):
            point = (x & 0xFFFF) | ((y & 0xFFFF) << 16)
            return self.cover.child_proc(
                child, resize.WM_NCHITTEST, 0, point, self.cover.child_cookie, 0
            )

        self.assertEqual(hit(231, 100), resize.HTTRANSPARENT)
        self.assertEqual(hit(232, 100), resize.HTCLIENT)
        self.assertEqual(hit(-1, 100), resize.HTCLIENT)
        self.api.screen_to_client.return_value = False
        self.assertEqual(hit(20, 100), resize.HTCLIENT)
        self.cover.hide("ready")
        self.assertEqual(hit(232, 100), resize.HTTRANSPARENT)

    def test_font_cover_is_owned_and_leaves_native_maximize_as_a_child_surface(self):
        def screen_point(_hwnd, pointer):
            pointer._obj.x, pointer._obj.y = 142, 85
            return True

        self.api.client_to_screen.side_effect = screen_point
        self.cover.block_sidebar = True
        self.cover._begin()
        self.api.window.assert_called_once_with(
            resize.WS_EX_LAYERED | resize.WS_EX_NOACTIVATE | resize.WS_EX_TOOLWINDOW,
            "STATIC",
            "",
            resize.WS_POPUP,
            142,
            85,
            1,
            1,
            42,
            None,
            None,
            None,
        )
        self.assertTrue(self.cover.active)
        self.assertTrue(self.cover.popup)
        self.assertAlmostEqual(self.cover.deadline - self.clock.return_value, 2.5)
        self.cover.hide("ready")
        self.maximize()
        self.assertFalse(self.cover.popup)
        self.assertAlmostEqual(self.cover.deadline - self.clock.return_value, 0.450)
        self.assertEqual(
            self.api.window.call_args.args[3], resize.WS_CHILD | resize.WS_CLIPSIBLINGS
        )

    def test_failed_removal_retains_native_callback_until_destroy_message(self):
        self.api.remove_subclass.return_value = False
        self.cover.close()
        self.assertIn(self.cover.cookie, resize._SUBCLASSES)
        self.maximize()
        self.assertFalse(self.cover.active)
        self.send(resize.WM_NCDESTROY)
        self.assertNotIn(self.cover.cookie, resize._SUBCLASSES)
        self.assertFalse(self.cover.attached)

    def test_delayed_timer_is_backed_by_monotonic_deadline(self):
        self.maximize()
        self.clock.return_value = 10.3
        self.send(0x0048)
        self.assertTrue(self.cover.active)
        self.clock.return_value = 10.9
        self.send(0x0048)
        self.assertFalse(self.cover.active)
        self.timers.return_value.cancel.assert_called_once()

    def test_restart_and_stale_expiration_do_not_hide_new_operation(self):
        self.maximize()
        first = self.cover.operation
        self.api.is_maximized.return_value = True
        self.clock.return_value = 10.2
        self.send(resize.WM_SYSCOMMAND, resize.SC_RESTORE)
        self.assertEqual(self.cover.operation, first + 1)
        self.assertIsNotNone(self.cover.child)
        self.assertEqual(
            self.send(resize.WM_COVER_DEADLINE, self.cover.cookie, first), 0
        )
        self.assertTrue(self.cover.active)
        self.assertEqual(
            self.send(resize.WM_COVER_DEADLINE, self.cover.cookie, first + 1), 0
        )
        self.assertFalse(self.cover.active)

    def test_expiration_from_other_window_instance_is_forwarded(self):
        self.maximize()
        self.assertEqual(
            self.send(
                resize.WM_COVER_DEADLINE, self.cover.cookie + 1, self.cover.operation
            ),
            49,
        )
        self.assertTrue(self.cover.active)

    def test_parent_client_area_is_recomposed_after_real_geometry_change(self):
        self.maximize()
        self.assertEqual(self.cover.dimensions, (1280, 820))

        def updated_rect(_hwnd, pointer):
            pointer._obj.right = 1920
            pointer._obj.bottom = 1009
            return True

        self.api.get_client.side_effect = updated_rect
        self.send(resize.WM_WINDOWPOSCHANGED)
        self.assertEqual(self.cover.dimensions, (1920, 1009))
        self.assertEqual(self.api.dib.call_count, 2)
        self.send(resize.WM_SIZE)
        self.assertEqual(self.api.dib.call_count, 2)

    def test_minimize_focus_loss_and_caption_close_release_the_cover(self):
        for msg, wp in (
            (resize.WM_SYSCOMMAND, resize.SC_MINIMIZE),
            (resize.WM_ACTIVATE, 0),
            (resize.WM_CLOSE, 0),
            (resize.WM_ENTERSIZEMOVE, 0),
        ):
            with self.subTest(message=msg):
                self.maximize()
                self.assertTrue(self.cover.active)
                self.send(msg, wp)
                self.assertFalse(self.cover.active)
                self.api.default_proc.assert_called_with(42, msg, wp, 0)

    def test_composition_failure_falls_back_to_the_original_window(self):
        self.api.update_layer.return_value = False
        self.maximize()
        self.assertFalse(self.cover.active)
        self.api.delete_dc.assert_called_once()
        self.timers.assert_not_called()

    def test_failed_hide_destroys_the_child(self):
        self.maximize()
        self.api.position.return_value = False
        self.cover.hide("ready")
        self.api.destroy_window.assert_called_once()
        self.assertIsNone(self.cover.child)

    def test_no_coverage_at_startup_or_when_native_minimized(self):
        self.allowed.return_value = False
        self.maximize()
        self.assertFalse(self.cover.active)
        self.allowed.return_value = True
        self.api.is_minimized.return_value = True
        self.maximize()
        self.assertFalse(self.cover.active)
        self.api.window.assert_not_called()


class ResizePresentationTests(TestCase):
    def setUp(self):
        self.app = Mock()
        self.rail = self.app.sidebar
        self.rail.master = None
        self.content = SimpleNamespace(master=None)
        self.arrow = SimpleNamespace(master=self.rail)
        with patch.object(tk.Misc, "bind"):
            self.presentation = resize.ResizePresentation(self.app)
        self.cover = Mock(active=True, operation=2, block_sidebar=False)
        self.presentation.cover = self.cover

    def guard(self, event_type, key="", widget=None):
        return self.presentation._guard_input(
            SimpleNamespace(type=event_type, keysym=key, widget=widget or self.content)
        )

    def test_mouse_and_keyboard_allow_safe_navigation_and_block_hidden_actions(self):
        for event_type in (
            tk.EventType.ButtonPress,
            tk.EventType.ButtonRelease,
            tk.EventType.MouseWheel,
            tk.EventType.KeyPress,
            tk.EventType.KeyRelease,
        ):
            self.assertEqual(self.guard(event_type, "Return"), "break")
            self.assertIsNone(self.guard(event_type, "Return", self.arrow))
        self.assertIsNone(self.guard(tk.EventType.KeyPress, "Tab"))
        self.assertIsNone(self.guard(tk.EventType.KeyPress, "ISO_Left_Tab"))
        self.assertEqual(
            self.guard(tk.EventType.KeyPress, "Escape", self.arrow), "break"
        )
        self.cover.hide.assert_called_once()
        self.cover.active = False
        self.assertIsNone(self.guard(tk.EventType.ButtonPress))

    def test_input_arriving_on_expiration_is_not_replayed(self):
        def expire():
            self.cover.active = False

        self.cover.expire.side_effect = expire
        self.assertEqual(self.guard(tk.EventType.ButtonPress), "break")
        self.assertIsNone(self.guard(tk.EventType.ButtonPress))

    def test_layout_blocks_sidebar_click_even_if_cover_expires_during_delivery(self):
        self.cover.block_sidebar = True

        def expire():
            self.cover.active = False
            self.cover.block_sidebar = False

        self.cover.expire.side_effect = expire
        self.assertEqual(
            self.guard(tk.EventType.ButtonPress, widget=self.arrow), "break"
        )
        self.assertIsNone(self.guard(tk.EventType.ButtonPress, widget=self.arrow))

    def test_font_layout_schedules_one_paint_before_checking_readiness(self):
        self.app.winfo_children.return_value = []
        self.app.after_idle.side_effect = ("paint-1", "paint-2", "inspect")
        self.presentation.finish_layout()
        self.presentation.finish_layout()
        self.app.after_cancel.assert_called_once_with("paint-1")
        self.assertTrue(self.presentation.layout_pending)
        self.cover.hide.assert_not_called()
        self.presentation._paint_layout()
        self.assertFalse(self.presentation.layout_pending)
        self.app.after_idle.assert_called_with(self.presentation._inspect, 2)

    def test_sidebar_handle_is_captured_when_the_sidebar_maps(self):
        self.cover.sidebar = None
        self.rail.winfo_id.return_value = 43
        self.presentation._mapped(
            SimpleNamespace(type=tk.EventType.FocusIn, widget=self.rail)
        )
        self.rail.winfo_id.assert_not_called()

        self.presentation._mapped(
            SimpleNamespace(type=tk.EventType.Map, widget=self.rail)
        )
        self.assertEqual(self.cover.sidebar, 43)

    def test_window_identity_and_api_unavailable_keep_the_shell_functional(self):
        self.presentation.cover = None
        with patch.object(resize, "_Win32", side_effect=OSError):
            self.presentation._attach()
        self.assertIsNone(self.presentation.cover)
        api = Mock()
        api.ancestor.return_value = 0
        with patch.object(resize, "_Win32", return_value=api):
            self.presentation._attach()
        api.set_subclass.assert_not_called()

    def test_only_two_matching_layout_observations_reveal_the_window(self):
        ready = (object(), (1920, 1009))
        with patch.object(self.presentation, "_ready", return_value=ready):
            self.presentation._inspect(2)
            self.cover.hide.assert_not_called()
            self.app.after.assert_called_once_with(ANY, self.presentation._inspect, 2)
            self.presentation._inspect(2)
            self.cover.hide.assert_called_once_with("ready")

    def test_old_layout_callback_cannot_reveal_newer_presentation(self):
        self.presentation._inspect(1)
        self.cover.hide.assert_not_called()
        self.app.after_idle.assert_called_once_with(self.presentation._inspect, 2)

    def test_close_cancels_tk_callback_before_releasing_the_window(self):
        self.presentation.pending = "after9"
        self.presentation.close()
        self.app.after_cancel.assert_called_once_with("after9")
        self.cover.close.assert_called_once_with()
        self.assertIsNone(self.presentation.cover)
        self.assertTrue(self.presentation.stopped)
