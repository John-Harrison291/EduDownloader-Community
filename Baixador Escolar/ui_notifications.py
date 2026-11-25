"""Notificações breves que complementam o estado persistente da operação."""

import tkinter as tk
from collections import deque
from dataclasses import dataclass

import customtkinter as ctk

from ui_design import CANVAS, ERROR_TEXT, LINK, SURFACE, TEXT
from ui_transitions import _cover_opacity

_STYLES = {
    "success": ("Concluído", ("#18794E", "#55CC91")),
    "error": ("Erro", ERROR_TEXT),
    "warning": ("Atenção", ("#845000", "#F0B35A")),
    "info": ("Informação", LINK),
}
_SUCCESS_MS = 3000
_WAIT_MS = 4200


@dataclass(frozen=True, slots=True)
class Notice:
    kind: str
    message: str


class NotificationCenter:
    """Um cartão, até três mensagens em espera e um timer de visibilidade."""

    def __init__(self, parent, design, *, motion=None):
        self.motion = motion
        self.slot = None
        if motion is not None:
            self.slot = ctk.CTkFrame(
                parent, corner_radius=0, fg_color=CANVAS, height=88
            )
            self.slot.grid(row=1, column=0, sticky="ew")
            self.slot.grid_remove()
        compact = self.slot is None
        self._card = ctk.CTkFrame(
            parent if compact else self.slot,
            corner_radius=10 if compact else 14,
            fg_color=SURFACE,
            border_width=1,
        )
        padding = 12 if compact else 14
        self._title = design.label(self._card, "", font=design.control)
        self._title.pack(fill="x", padx=padding, pady=(5 if compact else 7, 0))
        self._message = design.label(
            self._card,
            "",
            color=TEXT,
            font=design.small,
            width=244 if compact else 326,
            wraplength=244 if compact else 314,
        )
        self._message.pack(fill="x", padx=padding, pady=(0, 6 if compact else 8))
        if compact:
            _cover_opacity(self._card)
            for widget in (self._card, self._title, self._message):
                tk.Misc.bind(widget, "<Enter>", self._yield_to_pointer, add="+")
        else:
            tk.Misc.bind(self._card, "<Configure>", self._fit_slot, add="+")
        self._timer = None
        self._pending = deque(maxlen=3)
        self.current = None

    def post(self, kind, message):
        notice = Notice(kind, message)
        if notice == self.current or notice in self._pending:
            return
        if self.current is not None:
            self._pending.append(notice)
        else:
            self._show(notice)

    def _show(self, notice):
        self.current = notice
        title, color = _STYLES[notice.kind]
        self._title.configure(text=title, text_color=color)
        self._message.configure(text=notice.message)
        self._card.configure(border_color=color)
        if self.slot is not None:
            self.slot.grid()
            self._animate(entering=True)
            self._timer = self.slot.after(_WAIT_MS, self._expire)
            return
        self._card.place(relx=1, rely=1, x=-22, y=-16, anchor="se")
        tk.Misc.lift(self._card)
        self._timer = self._card.after(
            _SUCCESS_MS if notice.kind == "success" else _WAIT_MS, self._expire
        )

    def _yield_to_pointer(self, _event):
        if (
            self._timer is not None
            and self.current is not None
            and self.current.kind == "success"
        ):
            self._card.after_cancel(self._timer)
            self._expire()

    def _expire(self):
        self._timer = None
        if self.slot is None:
            self._hide()
        else:
            self._animate(entering=False)

    def _fit_slot(self, event):
        height = max(88, round(self.slot._reverse_widget_scaling(event.height)) + 12)
        if height != self.slot.cget("height"):
            self.slot.configure(height=height)

    def _animate(self, *, entering):
        distance = 12 if self.motion.duration(170, balanced_only=True) else 0
        previous = None

        def draw(fraction):
            nonlocal previous
            offset = round(distance * (1 - fraction if entering else fraction))
            if previous != offset:
                self._card.place(relx=1, x=-22 + offset, y=4, anchor="ne")
                previous = offset

        self.motion.play(
            "toast",
            self.slot,
            170 if entering else 145,
            draw,
            done=None if entering else self._hide,
            balanced_only=True,
        )

    def _hide(self):
        self.current = None
        if self._pending:
            self._show(self._pending.popleft())
        else:
            self._card.place_forget()
            if self.slot is not None:
                self.slot.grid_remove()

    def clear(self):
        if self._timer is not None:
            self._card.after_cancel(self._timer)
            self._timer = None
        if self.motion is not None:
            self.motion.cancel("toast", settle=False)
        self._pending.clear()
        self._hide()
