"""Entrega a roda somente à região rolável mais interna sob o cursor."""

import sys
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk


class _WheelRouter:
    def __init__(self, window):
        self.window = window
        self.tag = f"EduWheel{id(self)}"
        self.active = None
        self.remainder = 0.0
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            window.bind_class(self.tag, sequence, self.route)
        tk.Misc.bind(window, "<Map>", self._mapped, add="+")
        tk.Misc.bind(window, "<Destroy>", self._destroyed, add="+")

    def _mapped(self, event):
        widget = event.widget
        if widget.winfo_toplevel() is self.window and self.tag not in widget.bindtags():
            widget.bindtags((self.tag, *widget.bindtags()))

    def _destroyed(self, event):
        if event.widget is self.window:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.window.unbind_class(self.tag, sequence)

    def route(self, event):
        widget = self.window.winfo_containing(event.x_root, event.y_root)
        if widget is None or widget.winfo_toplevel() is not self.window:
            return "break"
        region = None
        while widget is not None and widget is not self.window:
            region = getattr(widget, "_edu_scroll_region", None)
            if region is not None:
                break
            if isinstance(widget, (tk.Text, ttk.Treeview)):
                region = (widget, 1, None)
                break
            widget = widget.master
        if region is None:
            return None
        view, step, zoom = region
        if event.state & 4:
            return zoom(event) if zoom is not None else "break"
        horizontal = bool(event.state & 1)
        direction = -1 if event.num == 4 else 1
        delta = direction if event.num in (4, 5) else -event.delta
        if sys.platform == "win32" and event.num not in (4, 5):
            delta /= 120
        identity = str(view), horizontal
        if identity != self.active:
            self.active, self.remainder = identity, 0.0
        self.remainder += delta * step
        units = int(self.remainder)
        self.remainder -= units
        scroll = getattr(view, "xview_scroll" if horizontal else "yview_scroll", None)
        if units and scroll is not None:
            scroll(units, "units")
        # A própria região consome o gesto mesmo quando já está no limite.
        return "break"


def wheel_region(container, viewport, *, step=1, zoom=None):
    window = container.winfo_toplevel()
    if not hasattr(window, "_edu_wheel_router"):
        window._edu_wheel_router = _WheelRouter(window)
    container._edu_scroll_region = viewport, step, zoom


class ScrollableFrame(ctk.CTkScrollableFrame):
    """Conserva geometria e temas do CTk; a roda pertence à janela."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        step = 20 if sys.platform == "win32" else 1
        wheel_region(self._parent_frame, self._parent_canvas, step=step)

    def bind_all(self, sequence=None, func=None, add=None):
        # São os cinco bindings que CTk registra por frame a cada criação.
        if func in (
            self._mouse_wheel_all,
            self._keyboard_shift_press_all,
            self._keyboard_shift_release_all,
        ):
            return None
        return super().bind_all(sequence, func, add)
