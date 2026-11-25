"""Relógio determinístico e efeitos descartáveis da interface."""

import unittest
from unittest.mock import Mock, call, patch

from constants import MOTION_BALANCED, MOTION_OFF, MOTION_REDUCED
from ui_motion import MotionClock, ease_out
from ui_transitions import PageStack, logo_position


class LogoTrajectoryTests(unittest.TestCase):
    def test_starts_centred_and_finishes_at_actual_sidebar_coordinates(self):
        destination = (32, 46, 40)
        for width, height in ((860, 600), (1280, 820), (1920, 1009)):
            first = logo_position((width, height), destination, 0)
            middle = logo_position((width, height), destination, 0.5)
            final = logo_position((width, height), destination, 1)
            self.assertEqual(first, (round(width / 2), round(height / 2), 120))
            self.assertTrue(
                all(start > mid > end for start, mid, end in zip(first, middle, final))
            )
            self.assertEqual(final, destination)

    def test_larger_sidebar_symbol_does_not_make_the_centre_icon_oversized(self):
        self.assertEqual(logo_position((1920, 1000), (48, 60, 60), 0)[2], 140)
        self.assertEqual(logo_position((1920, 1000), (48, 60, 60), 1), (48, 60, 60))


class Loop:
    def __init__(self):
        self.exists = True
        self.visible = True
        self.now = 0.0
        self.callbacks = {}
        self.sequence = 0

    def winfo_exists(self):
        return self.exists

    def winfo_viewable(self):
        return self.visible

    def after(self, milliseconds, callback):
        self.sequence += 1
        self.callbacks[self.sequence] = callback
        return self.sequence

    def after_cancel(self, job):
        self.callbacks.pop(job, None)

    def advance(self, seconds):
        self.now += seconds
        pending = tuple(self.callbacks.values())
        self.callbacks.clear()
        for callback in pending:
            callback()


class MotionClockTests(unittest.TestCase):
    def setUp(self):
        self.root = Loop()
        self.widget = Loop()
        self.system = False
        self.motion = MotionClock(
            self.root, clock=lambda: self.root.now, read_system=lambda: self.system
        )

    def test_uses_elapsed_time_and_finishes_at_exact_endpoint(self):
        frames, done = [], []
        self.motion.play(
            "page", self.widget, 180, frames.append, done=lambda: done.append(True)
        )
        self.root.advance(0.09)
        self.assertEqual(frames, [0, ease_out(0.5)])
        self.assertEqual(len(self.root.callbacks), 1)
        self.root.advance(1.0)
        self.assertEqual(frames[-1], 1)
        self.assertEqual(done, [True])
        self.assertFalse(self.motion.active("page") or self.root.callbacks)

    def test_rapid_replacement_settles_old_key_and_ignores_stale_callback(self):
        first, second = [], []
        self.motion.play("page", self.widget, 180, first.append)
        stale = next(iter(self.root.callbacks.values()))
        self.motion.play("page", self.widget, 180, second.append)
        stale()
        self.assertEqual(first, [0, 1])
        self.assertEqual(second, [0])
        self.assertEqual(len(self.root.callbacks), 1)
        self.motion.close()
        self.assertEqual(second, [0, 1])
        self.assertFalse(self.root.callbacks)

    def test_destroyed_targets_receive_no_more_frames_or_completion(self):
        frames, done = [], []
        self.motion.play(
            "card", self.widget, 200, frames.append, done=lambda: done.append(True)
        )
        self.widget.exists = False
        self.motion.forget_widget(self.widget)
        self.root.advance(1)
        self.assertEqual(frames, [0])
        self.assertEqual(done, [])
        self.assertFalse(self.root.callbacks)

    def test_minimize_settles_each_effect_and_stops_the_timer(self):
        frames = []
        self.motion.play("card", self.widget, 200, frames.append)
        self.root.visible = False
        self.root.advance(0.02)
        self.assertEqual(frames, [0, 1])
        self.assertFalse(self.root.callbacks)

    def test_reduced_off_and_windows_preference_settle_safely(self):
        self.motion.configure(MOTION_REDUCED)
        self.assertEqual(self.motion.duration(180), 81)
        self.assertEqual(self.motion.duration(180, balanced_only=True), 0)
        frames = []
        self.motion.play("card", self.widget, 180, frames.append)
        self.motion.configure(MOTION_OFF)
        self.assertEqual(frames, [0, 1])
        self.motion.play("card", self.widget, 180, frames.append)
        self.assertEqual(frames, [0, 1, 1])
        self.system = True
        self.motion.configure(MOTION_BALANCED)
        self.assertEqual(self.motion.mode, MOTION_OFF)
        self.assertEqual(self.motion.preference, MOTION_BALANCED)
        self.assertFalse(self.root.callbacks)

    def test_active_effects_share_one_bounded_timer(self):
        for index in range(40):
            self.motion.play(index, self.widget, 200, lambda _: None)
        self.assertLessEqual(sum(self.motion.active(i) for i in range(40)), 12)
        self.assertEqual(len(self.root.callbacks), 1)
        self.motion.cancel_all()
        self.assertFalse(self.root.callbacks)


class PageStackMotionTests(unittest.TestCase):
    def setUp(self):
        self.root = Loop()
        self.root.sidebar = Mock()
        self.host = Mock()
        self.pages = [Mock() for _ in range(4)]
        for page in self.pages:
            page._parent_frame.master = self.host
        with patch("ui_transitions.tk.Misc.bind"):
            self.stack = PageStack(self.root, self.host, self.pages[0])

    def test_windows_uses_independent_opaque_surfaces_without_queueing_transitions(
        self,
    ):
        with (
            patch("ui_transitions.os.name", "nt"),
            patch("ui_transitions.tk.Misc.bind"),
            patch("ui_transitions._cover_opacity") as compose,
        ):
            stack = PageStack(self.root, self.host, self.pages[0], pages=self.pages)
            for page in self.pages[1:]:
                stack.show(page)
        self.assertEqual(
            compose.call_args_list, [call(page._parent_frame) for page in self.pages]
        )
        self.assertIs(stack.current, self.pages[-1])
        self.assertFalse(self.root.callbacks)

    def test_rapid_swaps_unmap_the_old_surface_before_showing_the_next(self):
        visible = self.pages[:1]
        for page in self.pages:
            page.grid_forget.side_effect = lambda p=page: visible.remove(p)
            page.grid.side_effect = lambda p=page, **_: visible.append(p)
        for page in self.pages[1:] + self.pages[::-1]:
            self.stack.show(page)
            self.assertEqual(visible, [page])
            self.assertTrue(self.stack.widget_is_presented(page._parent_frame))
        self.assertFalse(self.root.callbacks)

    def test_reslecting_active_surface_does_not_remap_it(self):
        active = self.pages[0]
        self.stack.show(active)
        active.grid_forget.assert_not_called()
        active.grid.assert_not_called()

    def test_failure_to_map_a_destination_restores_previous_surface(self):
        active, target = self.pages[:2]
        target.grid.side_effect = RuntimeError("failed")
        with self.assertRaises(RuntimeError):
            self.stack.show(target)
        active.grid_forget.assert_called_once_with()
        active.grid.assert_called_once_with(row=0, column=0, sticky="nsew")
        self.assertIs(self.stack.current, active)

    def test_presentation_membership_checks_the_external_scrollable_frame(self):
        active, hidden = self.pages[:2]
        child = Mock(master=hidden._parent_frame)
        self.assertFalse(self.stack.widget_is_presented(child))
        child.master = active._parent_frame
        self.assertTrue(self.stack.widget_is_presented(child))
        self.assertFalse(self.root.callbacks)
