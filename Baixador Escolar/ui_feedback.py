"""Apresentação de botões, cartões e medições de progresso."""

import tkinter as tk

import customtkinter as ctk

from constants import MOTION_BALANCED
from ui_motion import mix_color


class MotionButton(ctk.CTkButton):
    """Mantém as cores semânticas e ajusta somente o desenho momentâneo."""

    def __init__(self, master, *, motion, disabled_surface=None, **options):
        self._disabled_surface = disabled_surface
        self._motion = motion
        self._effect_key = ("button", id(self))
        self._pointed = False
        self._painted = None
        super().__init__(master, **options)

    def configure(self, **options):
        if self._motion is not None and options.keys() & {
            "state",
            "fg_color",
            "hover_color",
            "bg_color",
        }:
            self._motion.cancel(self._effect_key, settle=False)
            self._painted = None
        if options.get("state") == tk.DISABLED:
            self._pointed = False
        super().configure(**options)

    def _draw(self, no_color_updates=False):
        if self._disabled_surface is None or self._state != tk.DISABLED:
            return super()._draw(no_color_updates)
        normal_color = self._fg_color
        self._fg_color = self._disabled_surface
        try:
            return super()._draw(no_color_updates)
        finally:
            self._fg_color = normal_color

    def _base_color(self):
        color = self._bg_color if self._fg_color == "transparent" else self._fg_color
        return self._apply_appearance_mode(color)

    def _hover_fill(self):
        return (
            self._apply_appearance_mode(self._hover_color)
            if self._hover_color is not None and self._hover
            else self._base_color()
        )

    def _paint(self, color):
        if self._painted == color or self._state == tk.DISABLED:
            return
        self._canvas.itemconfig("inner_parts", outline=color, fill=color)
        for label in (self._text_label, self._image_label):
            if label is not None:
                label.configure(bg=color)
        self._painted = color

    def _transition(self, start, end, milliseconds):
        self._motion.cancel(self._effect_key, settle=False)
        if start.casefold() == end.casefold() or any(
            not value.startswith("#") or len(value) != 7 for value in (start, end)
        ):
            self._paint(end)
            return
        self._motion.play(
            self._effect_key,
            self,
            milliseconds,
            lambda fraction: self._paint(mix_color(start, end, fraction)),
        )

    def _on_enter(self, event=None):
        if self._motion is None:
            return super()._on_enter(event)
        if self._state == tk.NORMAL and self._hover and not self._pointed:
            self._pointed = True
            self._transition(
                self._painted or self._base_color(), self._hover_fill(), 110
            )

    def _on_leave(self, event=None):
        if self._motion is None:
            return super()._on_leave(event)
        if self._pointed:
            self._pointed = False
            self._transition(
                self._painted or self._hover_fill(), self._base_color(), 100
            )

    def _clicked(self, event=None):
        if self._motion is None:
            return super()._clicked(event)
        self.invoke()

    def invoke(self):
        if self._motion is not None and self._state == tk.NORMAL:
            base, hover = self._base_color(), self._hover_fill()
            self._transition(
                base if self._pointed else hover, hover if self._pointed else base, 110
            )
        return super().invoke()

    def highlight_selection(self):
        if self._motion is not None and self._state == tk.NORMAL:
            normal = self._hover_fill() if self._pointed else self._base_color()
            self._transition(self._hover_fill(), normal, 110)


def card_feedback(card, action, motion, resting, highlighted):
    """Aplica uma borda ao cartão que contém uma ação real."""
    if motion is None:
        return
    card.configure(border_width=1, border_color=resting)
    key = ("card", id(card))
    current = resting
    pointed = False

    def set_pointed(event):
        nonlocal pointed, current
        if event.type == tk.EventType.Leave:
            x, y = event.x_root, event.y_root
            if (
                card.winfo_rootx() <= x < card.winfo_rootx() + card.winfo_width()
                and card.winfo_rooty() <= y < card.winfo_rooty() + card.winfo_height()
            ):
                return
        inside = event.type == tk.EventType.Enter and action.cget("state") != "disabled"
        if inside == pointed:
            return
        pointed = inside
        start = current
        end = highlighted if inside else resting
        motion.cancel(key, settle=False)

        def draw(fraction):
            nonlocal current
            colors = tuple(mix_color(a, b, fraction) for a, b in zip(start, end))
            if colors != current:
                card.configure(border_color=colors)
                current = colors

        motion.play(key, card, 130, draw)

    widgets = [card]
    while widgets:
        widget = widgets.pop()
        tk.Misc.bind(widget, "<Enter>", set_pointed, add="+")
        tk.Misc.bind(widget, "<Leave>", set_pointed, add="+")
        widgets.extend(widget.winfo_children())


class ProgressBar(ctk.CTkProgressBar):
    """Retarda somente a pintura, mantendo a medição como valor público."""

    def __init__(self, master, **options):
        self._motion = getattr(master.winfo_toplevel(), "_motion", None)
        self._effect_key = ("progress", id(self))
        self._spinning = False
        self._reading = 0.0
        super().__init__(master, **options)
        self._reading = super().get()
        if self._motion is not None:
            self._motion.watch_activity(self)
            tk.Misc.bind(self, "<Map>", self._sync_spin, add="+")
            tk.Misc.bind(self, "<Unmap>", self._sync_spin, add="+")

    def set(self, value, from_variable_callback=False):
        exact = max(0.0, min(1.0, value))
        previous = self._reading
        self._reading = exact
        write = super().set
        if self._motion is None:
            write(exact, from_variable_callback)
            return
        if exact == previous and self._motion.active(self._effect_key):
            return
        self._motion.cancel(self._effect_key, settle=False)
        current = super().get()
        if (
            not self.winfo_viewable()
            or self.cget("mode") != "determinate"
            or not current < exact < 1
        ):
            if current != exact:
                write(exact, from_variable_callback)
            return
        self._motion.play(
            self._effect_key,
            self,
            115,
            lambda fraction: write(
                min(exact, current + (exact - current) * fraction),
                from_variable_callback,
            ),
        )

    def get(self):
        return self._reading

    def start(self):
        self._spinning = True
        self._sync_spin()

    def stop(self):
        self._spinning = False
        if self._motion is not None:
            self._motion.cancel(self._effect_key)
        super().stop()

    def _sync_spin(self, _event=None):
        if (
            self._spinning
            and self.cget("mode") == "indeterminate"
            and (
                self._motion is None
                or (
                    self._motion.mode == MOTION_BALANCED
                    and self.winfo_viewable()
                    and self._motion.is_presented(self)
                )
            )
        ):
            super().start()
        elif self._loop_running:
            super().stop()

    def motion_preference_changed(self):
        self._sync_spin()

    def destroy(self):
        self.stop()
        super().destroy()


class PanelReveal:
    """Revela um painel persistente, recortando só o excesso de altura."""

    def __init__(self, frame, body, disclosure, motion):
        self.frame = frame
        self.body = body
        self.disclosure = disclosure
        self.motion = motion
        self.key = ("panel", id(frame))
        self.expanded = False
        tk.Misc.bind(body, "<Configure>", self._fit_contents, add="+")

    def set_expanded(self, expanded):
        if expanded == self.expanded:
            return
        self.motion.cancel(self.key, settle=False)
        self.expanded = expanded
        start = self.frame.cget("height") if self.frame.grid_info() else 1
        if expanded:
            self.frame.grid()
            self.body.place(x=0, y=0, relwidth=1)
        else:
            focused = self.frame.winfo_toplevel().focus_get()
            if self._contains_focus(focused):
                tk.Misc.focus_set(self.disclosure)
            self.body.place_forget()

        def draw(fraction):
            destination = self._body_height() if expanded else 1
            self._set_height(round(start + (destination - start) * fraction))

        def done():
            if expanded:
                self._set_height(self._body_height())
            else:
                self.frame.grid_remove()

        self.motion.play(self.key, self.frame, 190, draw, done=done, balanced_only=True)

    def reveal_focus(self, focused):
        if self.expanded and self._contains_focus(focused):
            self.motion.cancel(self.key)

    def _contains_focus(self, widget):
        while widget is not None:
            if widget is self.body:
                return True
            widget = widget.master
        return False

    def _body_height(self):
        return max(
            1, round(self.frame._reverse_widget_scaling(self.body.winfo_reqheight()))
        )

    def _set_height(self, height):
        if self.frame.cget("height") != height:
            self.frame.configure(height=height)

    def _fit_contents(self, _event):
        if self.expanded and not self.motion.active(self.key):
            self._set_height(self._body_height())
