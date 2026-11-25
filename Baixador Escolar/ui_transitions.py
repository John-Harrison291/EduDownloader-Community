"""Abertura e restauração de foco sobre o shell persistente."""

from __future__ import annotations

import os
import tkinter as tk
from weakref import WeakKeyDictionary, ref

import customtkinter as ctk
from PIL import Image, ImageTk

from ui_design import SIDEBAR
from ui_motion import ease_out

STARTUP_MS = 1760
_HOLD = 0.16
_REVEAL = 0.76


def logo_position(viewport, destination, fraction):
    """Interpola o centro e o tamanho em pixels da área cliente."""
    width, height = viewport
    x, y, end_size = destination
    size = min(140, max(110, 3 * end_size), width // 4, height // 3)
    eased = ease_out(fraction)
    return (
        round(width / 2 + (x - width / 2) * eased),
        round(height / 2 + (y - height / 2) * eased),
        round(size + (end_size - size) * eased),
    )


def _cover_opacity(surface):
    """Ativa a composição em uma superfície filha, inicialmente opaca."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    try:
        user = ctypes.WinDLL("user32", use_last_error=True)
        read = user.GetWindowLongW
        read.argtypes = (wintypes.HWND, ctypes.c_int)
        read.restype = ctypes.c_long
        write = user.SetWindowLongW
        write.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
        write.restype = ctypes.c_long
        opacity = user.SetLayeredWindowAttributes
        opacity.argtypes = (
            wintypes.HWND,
            wintypes.DWORD,
            wintypes.BYTE,
            wintypes.DWORD,
        )
        opacity.restype = wintypes.BOOL
        handle = surface.winfo_id()
        style_index, layered, alpha = -20, 0x00080000, 2
        original = read(handle, style_index)
        write(handle, style_index, original | layered)
        if opacity(handle, 0, 255, alpha):
            return lambda value: bool(opacity(handle, 0, value, alpha))
        write(handle, style_index, original)
    except (OSError, AttributeError, tk.TclError):
        pass
    return None


class PageStack:
    """Uma única superfície mapeada, com instâncias persistentes."""

    def __init__(self, window, host, current, *, pages=()):
        self.host = host
        self.current = current
        tk.Misc.bind(window.sidebar, "<Map>", self._compose_rail, add="+")
        if os.name == "nt":
            # Cada página tem uma superfície opaca própria. A pintura de
            # seus HWNDs deixa de compartilhar os pixels da página anterior.
            for page in pages:
                _cover_opacity(page._parent_frame)

    @staticmethod
    def _compose_rail(event):
        _cover_opacity(event.widget)

    def show(self, page):
        previous = self.current
        if previous is page:
            return
        previous.grid_forget()
        try:
            page.grid(row=0, column=0, sticky="nsew")
        except Exception:
            previous.grid(row=0, column=0, sticky="nsew")
            raise
        self.current = page

    def widget_is_presented(self, widget):
        while widget is not None and widget.master is not self.host:
            widget = widget.master
        return widget is None or widget is self.current._parent_frame


class PagePresentation:
    def __init__(self, window, symbol, brand, motion) -> None:
        self.window = window
        self.symbol = symbol
        self.brand = brand
        self.motion = motion
        self._home = None
        self._startup_idle = None
        self._startup_size = None
        self._startup_label = None
        self._logo_item = None
        self._logo_size = 0
        self._source = None
        self._opacity = None
        self._symbol_image = None
        self._focus_idle = None
        self._focus = WeakKeyDictionary()
        if symbol is not None:
            tk.Misc.bind(symbol, "<Map>", self._symbol_mapped, add="+")

    @property
    def startup_active(self) -> bool:
        return self._startup_label is not None

    def arm_startup(self, home) -> None:
        if (
            self.symbol is None
            or self.brand is None
            or not self.motion.duration(STARTUP_MS, balanced_only=True)
        ):
            return
        try:
            self._source = self.brand.resize((140, 140), Image.Resampling.LANCZOS)
            background = SIDEBAR[int(ctk.get_appearance_mode() == "Dark")]
            cover = self._startup_label = tk.Canvas(
                self.window, bg=background, bd=0, highlightthickness=0, takefocus=False
            )
            self._home = home._parent_frame
            self._logo_item = cover.create_image(0, 0, anchor="center")
            self._symbol_image = self.symbol.cget("image")
            blank = ctk.CTkImage(light_image=Image.new("RGBA", (1, 1)), size=(40, 40))
            self.symbol.configure(image=blank)
            self._draw_logo(0, 0, 120)
            self._opacity = _cover_opacity(cover)
            cover.bind("<Configure>", self._cover_configured)
            cover.bind("<Map>", lambda _event: self.on_map())
            cover.place(x=0, y=0, relwidth=1, relheight=1)
            tk.Misc.lift(cover)
        except (OSError, ValueError, tk.TclError):
            self._clear_startup()

    def _cover_configured(self, event) -> None:
        if self._startup_size is None:
            self._startup_label.coords(
                self._logo_item, event.width / 2, event.height / 2
            )
            self.on_map()

    def on_map(self) -> None:
        if (
            self._startup_label is not None
            and self._startup_size is None
            and self._startup_idle is None
            and self.symbol.winfo_viewable()
            and self._startup_label.winfo_viewable()
        ):
            self._startup_idle = self.window.after_idle(self._start)

    def _symbol_mapped(self, event) -> None:
        if event.widget is self.symbol:
            self.on_map()

    def on_resize(self) -> None:
        if self._startup_size is not None and self._startup_size != self._window_size():
            self.cancel_startup()

    def cancel_startup(self) -> None:
        if self._startup_label is None:
            return
        self.motion.cancel("startup", settle=False)
        self._clear_startup()

    def _window_size(self) -> tuple[int, int]:
        return self.window.winfo_width(), self.window.winfo_height()

    def _start(self) -> None:
        self._startup_idle = None
        cover = self._startup_label
        if cover is None:
            return
        width, height = self._window_size()
        symbol_width, symbol_height = (
            self.symbol.winfo_width(),
            self.symbol.winfo_height(),
        )
        if (
            not self._home.winfo_viewable()
            or not self.symbol.winfo_viewable()
            or min(width, height, symbol_width, symbol_height) <= 1
            or not self.motion.duration(STARTUP_MS, balanced_only=True)
        ):
            self.cancel_startup()
            return
        self._startup_size = width, height
        destination = (
            self.symbol.winfo_rootx() - self.window.winfo_rootx() + symbol_width / 2,
            self.symbol.winfo_rooty() - self.window.winfo_rooty() + symbol_height / 2,
            min(symbol_width, symbol_height),
        )
        if self._opacity is None:
            # Mantém a cobertura inteira até o destino quando a composição não existe.
            self._animate(cover, destination, reveal=False)
        else:
            self._animate(cover, destination, reveal=True)

    def _animate(self, cover, destination, *, reveal):
        last = None
        last_opacity = 255
        travel_end = _REVEAL if reveal else 1.0

        def draw(progress):
            nonlocal last, last_opacity
            fraction = min(1.0, max(0.0, (progress - _HOLD) / (travel_end - _HOLD)))
            position = logo_position(self._startup_size, destination, fraction)
            if position != last:
                self._draw_logo(*position)
                last = position
            if reveal and progress >= travel_end:
                self._restore_symbol()
                value = round(
                    255 * (1 - ease_out((progress - travel_end) / (1 - travel_end)))
                )
                if value != last_opacity:
                    if not self._opacity(value):
                        raise tk.TclError("Composição da abertura indisponível.")
                    last_opacity = value

        self.motion.play(
            "startup",
            cover,
            STARTUP_MS if reveal else 1450,
            draw,
            done=self._clear_startup,
            curve=float,
            balanced_only=True,
        )

    def _draw_logo(self, x, y, size):
        cover = self._startup_label
        if self._logo_size != size:
            try:
                image = ImageTk.PhotoImage(
                    self._source.resize((size, size), Image.Resampling.LANCZOS),
                    master=cover,
                )
            except (OSError, ValueError) as error:
                raise tk.TclError("Não foi possível apresentar o símbolo.") from error
            cover.itemconfigure(self._logo_item, image=image)
            cover.image = image
            self._logo_size = size
        cover.coords(self._logo_item, x, y)

    def _restore_symbol(self):
        if self._symbol_image is not None:
            image, self._symbol_image = self._symbol_image, None
            self.symbol.configure(image=image)

    def _clear_startup(self) -> None:
        if self._startup_idle is not None:
            self.window.after_cancel(self._startup_idle)
            self._startup_idle = None
        self._startup_size = None
        self._home = None
        self._source = None
        self._opacity = None
        cover, self._startup_label = self._startup_label, None
        try:
            self._restore_symbol()
        finally:
            if cover is not None:
                cover.destroy()

    def before_swap(self, previous) -> None:
        self.cancel_startup()
        self._cancel_focus()
        focused = self.window.focus_get()
        widget = focused
        while widget is not None and widget is not previous:
            widget = widget.master
        if widget is previous and focused is not previous:
            self._focus[previous] = ref(focused)

    def present(self, page) -> None:
        saved = self._focus.get(page)
        widget = saved() if saved is not None else None
        if widget is None:
            return

        def restore():
            self._focus_idle = None
            if (
                page.winfo_viewable()
                and widget.winfo_exists()
                and widget.winfo_viewable()
            ):
                tk.Misc.focus_set(widget)

        self._focus_idle = self.window.after_idle(restore)

    def _cancel_focus(self) -> None:
        if self._focus_idle is not None:
            self.window.after_cancel(self._focus_idle)
            self._focus_idle = None

    def settle(self) -> None:
        self.cancel_startup()
        self.motion.cancel_all()
        self._cancel_focus()
