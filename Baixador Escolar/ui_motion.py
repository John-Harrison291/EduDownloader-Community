"""Quadros de UI por tempo decorrido, agendados exclusivamente pelo Tk."""

from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from time import monotonic
from weakref import ReferenceType, WeakSet, ref

from constants import MOTION_BALANCED, MOTION_OFF, MOTION_REDUCED

_FRAME_MS = 24
_MAX_ACTIVE = 12


def ease_out(progress: float) -> float:
    return 1 - (1 - progress) ** 3


def mix_color(start: str, end: str, progress: float) -> str:
    values = []
    for index in (1, 3, 5):
        low = int(start[index : index + 2], 16)
        high = int(end[index : index + 2], 16)
        values.append(round(low + (high - low) * progress))
    return "#{:02x}{:02x}{:02x}".format(*values)


def windows_reduces_motion() -> bool:
    """Read the Windows client-area animation preference, when available."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    enabled = wintypes.BOOL()
    try:
        read = ctypes.windll.user32.SystemParametersInfoW
        return bool(read(0x1042, 0, ctypes.byref(enabled), 0)) and not enabled.value
    except (OSError, AttributeError):
        return False


@dataclass(slots=True)
class _Effect:
    target: ReferenceType
    started: float
    seconds: float
    draw: Callable[[float], None]
    done: Callable[[], None] | None
    curve: Callable[[float], float]


class MotionClock:
    """Uma animação por chave e um timer compartilhado pela janela."""

    def __init__(
        self,
        window,
        preference: str = MOTION_BALANCED,
        *,
        clock: Callable[[], float] = monotonic,
        read_system: Callable[[], bool] = windows_reduces_motion,
    ) -> None:
        self._window = window
        self._clock = clock
        self._read_system = read_system
        self.preference = preference
        self.system_reduced = read_system()
        self._effects: dict[Hashable, _Effect] = {}
        self._activities = WeakSet()
        self.is_presented: Callable[[object], bool] = lambda _widget: True
        self._timer: str | None = None
        self._closed = False

    @property
    def mode(self) -> str:
        return MOTION_OFF if self.system_reduced else self.preference

    def configure(self, preference: str) -> None:
        previous = self.mode
        self.preference = preference
        self.system_reduced = self._read_system()
        if self.mode != previous:
            self.cancel_all()
            self.refresh_activity()

    def refresh_activity(self) -> None:
        for activity in tuple(self._activities):
            activity.motion_preference_changed()

    def watch_activity(self, widget) -> None:
        self._activities.add(widget)

    def active(self, key: Hashable) -> bool:
        return key in self._effects

    def duration(self, milliseconds: int, *, balanced_only: bool = False) -> int:
        if self.mode == MOTION_OFF:
            return 0
        if self.mode == MOTION_REDUCED:
            return 0 if balanced_only else round(milliseconds * 0.45)
        return milliseconds

    def play(
        self,
        key: Hashable,
        target,
        milliseconds: int,
        draw: Callable[[float], None],
        *,
        done: Callable[[], None] | None = None,
        curve: Callable[[float], float] = ease_out,
        balanced_only: bool = False,
    ) -> None:
        self.cancel(key)
        effect = _Effect(
            ref(target),
            self._clock(),
            max(0, self.duration(milliseconds, balanced_only=balanced_only)) / 1000,
            draw,
            done,
            curve,
        )
        if (
            self._closed
            or not effect.seconds
            or len(self._effects) >= _MAX_ACTIVE
            or not self._viewable(self._window)
            or not self.is_presented(target)
        ):
            self._finish(effect)
            return
        self._effects[key] = effect
        try:
            draw(0.0)
        except tk.TclError:
            self.cancel(key)
            return
        self._schedule()

    def cancel(self, key: Hashable, *, settle: bool = True) -> None:
        effect = self._effects.pop(key, None)
        if effect is not None and settle:
            self._finish(effect)
        if not self._effects:
            self._cancel_timer()

    def cancel_all(self) -> None:
        effects = tuple(self._effects.values())
        self._effects.clear()
        self._cancel_timer()
        for effect in effects:
            self._finish(effect)

    def forget_widget(self, widget) -> None:
        for key, effect in tuple(self._effects.items()):
            if effect.target() is widget:
                self.cancel(key, settle=False)

    def close(self) -> None:
        self._closed = True
        self.cancel_all()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            try:
                self._window.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None

    def _schedule(self) -> None:
        if self._timer is None and self._effects:

            def dispatch():
                if self._timer == timer:
                    self._tick()

            timer = self._window.after(_FRAME_MS, dispatch)
            self._timer = timer

    def _tick(self) -> None:
        self._timer = None
        if not self._viewable(self._window):
            self.cancel_all()
            return
        for key, effect in tuple(self._effects.items()):
            if self._effects.get(key) is not effect:
                continue
            target = effect.target()
            if not self._viewable(target) or not self.is_presented(target):
                self.cancel(key, settle=self._exists(target))
                continue
            progress = (self._clock() - effect.started) / effect.seconds
            if progress >= 1:
                self.cancel(key)
                continue
            try:
                effect.draw(effect.curve(max(0.0, progress)))
            except tk.TclError:
                self.cancel(key)
        self._schedule()

    @staticmethod
    def _exists(widget) -> bool:
        try:
            return widget is not None and bool(widget.winfo_exists())
        except tk.TclError:
            return False

    @classmethod
    def _viewable(cls, widget) -> bool:
        try:
            return cls._exists(widget) and bool(widget.winfo_viewable())
        except tk.TclError:
            return False

    @classmethod
    def _finish(cls, effect: _Effect) -> None:
        if cls._exists(effect.target()):
            try:
                try:
                    effect.draw(1.0)
                finally:
                    if effect.done is not None and cls._exists(effect.target()):
                        effect.done()
            except tk.TclError:
                pass
