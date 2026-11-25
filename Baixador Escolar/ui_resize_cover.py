"""Proteção da composição nativa durante mudanças no layout da janela."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
from itertools import count
import os
from threading import Timer, get_native_id
from time import monotonic
import tkinter as tk

import customtkinter as ctk

from ui_design import CANVAS, SIDEBAR


# Os callbacks precisam sobreviver a uma falha de remoção até WM_NCDESTROY.
_SUBCLASSES = {}
_IDS = count(1)

WM_SIZE = 0x0005
WM_ACTIVATE = 0x0006
WM_CLOSE = 0x0010
WM_SHOWWINDOW = 0x0018
WM_WINDOWPOSCHANGED = 0x0047
WM_NCDESTROY = 0x0082
WM_NCHITTEST = 0x0084
WM_SYSCOMMAND = 0x0112
WM_ENTERSIZEMOVE = 0x0231
WM_COVER_DEADLINE = 0x8753

SC_SIZE = 0xF000
SC_MOVE = 0xF010
SC_MINIMIZE = 0xF020
SC_MAXIMIZE = 0xF030
SC_CLOSE = 0xF060
SC_RESTORE = 0xF120

WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CLIPSIBLINGS = 0x04000000
WS_EX_LAYERED = 0x80000
WS_EX_NOPARENTNOTIFY = 0x04
WS_EX_TOOLWINDOW = 0x80
WS_EX_NOACTIVATE = 0x08000000
SWP_NOACTIVATE = 0x10
SWP_NOMOVE = 0x02
SWP_NOSIZE = 0x01
SWP_NOZORDER = 0x04
SWP_SHOWWINDOW = 0x40
SWP_HIDEWINDOW = 0x80
HTTRANSPARENT = -1
HTCLIENT = 1

_COVER_SECONDS = 0.450
_TEXT_LAYOUT_TIMEOUT_SECONDS = 2.5
_PAINT_POLL_MS = 12
_REDRAW_SUBTREE = 0x0001 | 0x0004 | 0x0080 | 0x0100


class Blend(c.Structure):
    _fields_ = [
        ("operation", w.BYTE),
        ("flags", w.BYTE),
        ("alpha", w.BYTE),
        ("format", w.BYTE),
    ]


class BitmapHeader(c.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("width", w.LONG),
        ("height", w.LONG),
        ("planes", w.WORD),
        ("bits", w.WORD),
        ("compression", w.DWORD),
        ("image", w.DWORD),
        ("x", w.LONG),
        ("y", w.LONG),
        ("colors", w.DWORD),
        ("important", w.DWORD),
    ]


def _api(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = args
    return function


class _Win32:
    """Carrega as APIs só quando o shell Windows tem um HWND real."""

    def __init__(self):
        USER = c.WinDLL("user32", use_last_error=True)
        GDI = c.WinDLL("gdi32", use_last_error=True)
        COMMON = c.WinDLL("comctl32", use_last_error=True)
        DWM = c.WinDLL("dwmapi", use_last_error=True)
        self.callback = c.WINFUNCTYPE(
            w.LPARAM, w.HWND, w.UINT, w.WPARAM, w.LPARAM, c.c_size_t, c.c_size_t
        )
        self.enum = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        self.set_subclass = _api(
            COMMON,
            "SetWindowSubclass",
            w.BOOL,
            w.HWND,
            self.callback,
            c.c_size_t,
            c.c_size_t,
        )
        self.remove_subclass = _api(
            COMMON, "RemoveWindowSubclass", w.BOOL, w.HWND, self.callback, c.c_size_t
        )
        self.default_proc = _api(
            COMMON, "DefSubclassProc", w.LPARAM, w.HWND, w.UINT, w.WPARAM, w.LPARAM
        )
        self.ancestor = _api(USER, "GetAncestor", w.HWND, w.HWND, w.UINT)
        self.window = _api(
            USER,
            "CreateWindowExW",
            w.HWND,
            w.DWORD,
            w.LPCWSTR,
            w.LPCWSTR,
            w.DWORD,
            c.c_int,
            c.c_int,
            c.c_int,
            c.c_int,
            w.HWND,
            w.HMENU,
            w.HINSTANCE,
            c.c_void_p,
        )
        self.position = _api(
            USER,
            "SetWindowPos",
            w.BOOL,
            w.HWND,
            w.HWND,
            c.c_int,
            c.c_int,
            c.c_int,
            c.c_int,
            w.UINT,
        )
        self.update_layer = _api(
            USER,
            "UpdateLayeredWindow",
            w.BOOL,
            w.HWND,
            w.HDC,
            c.POINTER(w.POINT),
            c.POINTER(w.SIZE),
            w.HDC,
            c.POINTER(w.POINT),
            w.COLORREF,
            c.POINTER(Blend),
            w.DWORD,
        )
        self.get_client = _api(USER, "GetClientRect", w.BOOL, w.HWND, c.POINTER(w.RECT))
        self.screen_to_client = _api(
            USER, "ScreenToClient", w.BOOL, w.HWND, c.POINTER(w.POINT)
        )
        self.client_to_screen = _api(
            USER, "ClientToScreen", w.BOOL, w.HWND, c.POINTER(w.POINT)
        )
        self.post = _api(
            USER, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM
        )
        self.is_maximized = _api(USER, "IsZoomed", w.BOOL, w.HWND)
        self.is_minimized = _api(USER, "IsIconic", w.BOOL, w.HWND)
        self.destroy_window = _api(USER, "DestroyWindow", w.BOOL, w.HWND)
        self.visible = _api(USER, "IsWindowVisible", w.BOOL, w.HWND)
        self.update_pending = _api(
            USER, "GetUpdateRect", w.BOOL, w.HWND, c.c_void_p, w.BOOL
        )
        self.enum_children = _api(
            USER, "EnumChildWindows", w.BOOL, w.HWND, self.enum, w.LPARAM
        )
        self.redraw = _api(
            USER, "RedrawWindow", w.BOOL, w.HWND, c.c_void_p, c.c_void_p, w.UINT
        )
        self.create_dc = _api(GDI, "CreateCompatibleDC", w.HDC, w.HDC)
        self.delete_dc = _api(GDI, "DeleteDC", w.BOOL, w.HDC)
        self.dib = _api(
            GDI,
            "CreateDIBSection",
            w.HANDLE,
            w.HDC,
            c.c_void_p,
            w.UINT,
            c.POINTER(c.c_void_p),
            w.HANDLE,
            w.DWORD,
        )
        self.select = _api(GDI, "SelectObject", w.HANDLE, w.HDC, w.HANDLE)
        self.delete_object = _api(GDI, "DeleteObject", w.BOOL, w.HANDLE)
        self.brush = _api(GDI, "CreateSolidBrush", w.HBRUSH, w.COLORREF)
        self.fill = _api(USER, "FillRect", c.c_int, w.HDC, c.POINTER(w.RECT), w.HBRUSH)
        self.flush = _api(DWM, "DwmFlush", c.c_long)
        self.owner = _api(
            USER, "GetWindowThreadProcessId", w.DWORD, w.HWND, c.POINTER(w.DWORD)
        )
        self.is_window = _api(USER, "IsWindow", w.BOOL, w.HWND)


class _NativeCover:
    """Possui somente recursos Win32. O procedimento nunca chama o Tcl."""

    def __init__(self, native, hwnd, allowed, color, sidebar=None):
        self.native = native
        self.hwnd = hwnd
        self.allowed = allowed
        self.color = color
        self.sidebar = sidebar
        self.block_sidebar = False
        self.input_hwnd = None
        self.popup = False
        self.cookie = next(_IDS)
        self.child_cookie = next(_IDS)
        self.operation = 0
        self.deadline = None
        self.watchdog = None
        self.child = self.dc = self.bitmap = self.selected = None
        self.dimensions = None
        self.surface_color = None
        self.proc = native.callback(self._message)
        self.child_proc = native.callback(self._child_message)
        self.attached = bool(native.set_subclass(hwnd, self.proc, self.cookie, 0))
        if self.attached:
            _SUBCLASSES[self.cookie] = self.proc

    @property
    def active(self):
        return self.deadline is not None

    def _message(self, hwnd, message, wp, lp, _cookie, _data):
        native = self.native
        if message == WM_NCDESTROY and hwnd == self.hwnd:
            try:
                self.close()
                return native.default_proc(hwnd, message, wp, lp)
            finally:
                # HWND em destruição: a cadeia não voltará a chamar este callback.
                self.attached = False
                _SUBCLASSES.pop(self.cookie, None)

        if hwnd == self.hwnd and self.attached:
            try:
                if message == WM_COVER_DEADLINE and wp == self.cookie:
                    if lp == self.operation:
                        self.hide("deadline")
                    return 0
                self.expire()
                self._observe(message, wp)
            except (OSError, RuntimeError, ValueError, c.ArgumentError):
                self.hide("native-error")
        return native.default_proc(hwnd, message, wp, lp)

    def _child_message(self, hwnd, message, wp, lp, _cookie, _data):
        native = self.native
        if message == WM_NCDESTROY:
            try:
                return native.default_proc(hwnd, message, wp, lp)
            finally:
                _SUBCLASSES.pop(self.child_cookie, None)
                if self.child == hwnd:
                    self.child = None
        if message == WM_NCHITTEST:
            if not self.active:
                return HTTRANSPARENT
            # Só encaminha entrada às regiões que continuam válidas sob a capa.
            target = self.input_hwnd if self.block_sidebar else self.sidebar
            point = w.POINT(c.c_short(lp).value, c.c_short(lp >> 16).value)
            rect = w.RECT()
            if (
                target
                and native.screen_to_client(target, c.byref(point))
                and native.get_client(target, c.byref(rect))
                and rect.left <= point.x < rect.right
                and rect.top <= point.y < rect.bottom
            ):
                return HTTRANSPARENT
            return HTCLIENT
        return native.default_proc(hwnd, message, wp, lp)

    def _observe(self, message, wp):
        if message == WM_SYSCOMMAND:
            command = wp & 0xFFF0
            if command in (SC_CLOSE, SC_MINIMIZE, SC_MOVE, SC_SIZE):
                self.hide("system-command")
            elif self.allowed() and (
                (
                    command == SC_MAXIMIZE
                    and not self.native.is_maximized(self.hwnd)
                    and not self.native.is_minimized(self.hwnd)
                )
                or (command == SC_RESTORE and self.native.is_maximized(self.hwnd))
            ):
                self._begin()
        elif self.active:
            if (
                message in (WM_CLOSE, WM_ENTERSIZEMOVE)
                or (message == WM_ACTIVATE and not wp & 0xFFFF)
                or (message == WM_SHOWWINDOW and not wp)
            ):
                self.hide("interrupted")
            elif message in (WM_SIZE, WM_WINDOWPOSCHANGED):
                if self.native.is_minimized(self.hwnd):
                    self.hide("minimized")
                elif (
                    self.popup or self._client_size() != self.dimensions
                ) and not self._present():
                    self.hide("resize-failed")

    def _begin(self):
        self.operation += 1
        self._cancel_watchdog()
        # A escala renova a pintura de toda a página visível. O limite aqui
        # só encerra um layout sem resposta. O caminho normal usa _ready.
        timeout = _TEXT_LAYOUT_TIMEOUT_SECONDS if self.block_sidebar else _COVER_SECONDS
        self.deadline = monotonic() + timeout
        if not self._present():
            self.hide("show-failed")
            return
        # Apenas publica uma mensagem. O HWND e o Tk pertencem à thread da UI.
        self.watchdog = Timer(
            max(0, self.deadline - monotonic()),
            self.native.post,
            (self.hwnd, WM_COVER_DEADLINE, self.cookie, self.operation),
        )
        self.watchdog.daemon = True
        self.watchdog.start()
        # Preserva a ordem do protótipo antes de encaminhar o comando do sistema.
        if self.native.flush() < 0:
            self.hide("composition-unavailable")

    def _cancel_watchdog(self):
        if self.watchdog is not None:
            self.watchdog.cancel()
            self.watchdog = None

    def _client_size(self):
        area = w.RECT()
        if self.native.get_client(self.hwnd, c.byref(area)):
            return area.right, area.bottom
        return 0, 0

    def _present(self):
        native = self.native
        # A escala altera muitos HWNDs sob a mesma janela. Uma superfície
        # independente deixa o Windows compor esses filhos enquanto estão cobertos.
        popup = self.block_sidebar
        if self.child and self.popup != popup:
            self._destroy_child()
            if self.child:
                return False
        point = w.POINT()
        if popup and not native.client_to_screen(self.hwnd, c.byref(point)):
            return False
        if not self.child:
            extended = WS_EX_LAYERED | WS_EX_NOPARENTNOTIFY
            style = WS_CHILD | WS_CLIPSIBLINGS
            if popup:
                extended = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                style = WS_POPUP
            self.child = native.window(
                extended,
                "STATIC",
                "",
                style,
                point.x,
                point.y,
                1,
                1,
                self.hwnd,
                None,
                None,
                None,
            )
            if not self.child or not native.set_subclass(
                self.child, self.child_proc, self.child_cookie, 0
            ):
                self._destroy_child()
                return False
            self.popup = popup
            _SUBCLASSES[self.child_cookie] = self.child_proc
        width, height = self._client_size()
        if not self.child or min(width, height) <= 0 or width * height > 32 * 1024**2:
            return False
        if (width, height) != self.dimensions or self.color != self.surface_color:
            if not self._create_surface(width, height):
                return False
        if popup and not native.position(
            self.child,
            None,
            point.x,
            point.y,
            0,
            0,
            SWP_NOACTIVATE | SWP_NOSIZE | SWP_NOZORDER,
        ):
            return False
        return self._transfer(255) and native.position(
            self.child,
            None,
            0,
            0,
            0,
            0,
            SWP_NOACTIVATE
            | SWP_NOMOVE
            | SWP_NOSIZE
            | SWP_SHOWWINDOW
            | (SWP_NOZORDER if popup else 0),
        )

    def _create_surface(self, width, height):
        self._free_surface()
        native = self.native
        self.dc = native.create_dc(None)
        if not self.dc:
            return False
        raw = c.c_void_p()
        header = BitmapHeader(c.sizeof(BitmapHeader), width, -height, 1, 32)
        self.bitmap = native.dib(self.dc, c.byref(header), 0, c.byref(raw), None, 0)
        if not self.bitmap:
            return False
        self.selected = native.select(self.dc, self.bitmap)
        if self.selected in (None, 0, c.c_void_p(-1).value):
            self.selected = None
            return False
        brush = native.brush(self.color)
        if not brush:
            return False
        try:
            if not native.fill(self.dc, c.byref(w.RECT(0, 0, width, height)), brush):
                return False
        finally:
            native.delete_object(brush)
        self.dimensions = (width, height)
        self.surface_color = self.color
        return True

    def _transfer(self, alpha):
        size = w.SIZE(*self.dimensions)
        origin = w.POINT()
        blend = Blend(0, 0, alpha, 0)
        return bool(
            self.native.update_layer(
                self.child,
                None,
                None,
                c.byref(size),
                self.dc,
                c.byref(origin),
                0,
                c.byref(blend),
                2,
            )
        )

    def _free_surface(self):
        if self.dc:
            if self.selected:
                self.native.select(self.dc, self.selected)
            if self.bitmap:
                self.native.delete_object(self.bitmap)
            self.native.delete_dc(self.dc)
        self.dc = self.bitmap = self.selected = self.dimensions = None

    def expire(self):
        if self.active and monotonic() >= self.deadline:
            self.hide("deadline")

    def hide(self, _reason):
        if not self.active:
            return
        self.deadline = None
        self.block_sidebar = False
        self._cancel_watchdog()
        try:
            if self.child:
                if self.dimensions is not None:
                    self._transfer(0)
                if not self.native.position(
                    self.child,
                    None,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOACTIVATE
                    | SWP_NOZORDER
                    | SWP_NOMOVE
                    | SWP_NOSIZE
                    | SWP_HIDEWINDOW,
                ):
                    self._destroy_child()
        finally:
            self._free_surface()

    def _destroy_child(self):
        if self.child and (
            not self.native.is_window(self.child)
            or self.native.destroy_window(self.child)
        ):
            self.child = None
            _SUBCLASSES.pop(self.child_cookie, None)

    def close(self):
        self.hide("closed")
        self._destroy_child()
        self.allowed = lambda: False
        if self.attached and self.native.remove_subclass(
            self.hwnd, self.proc, self.cookie
        ):
            self.attached = False
            _SUBCLASSES.pop(self.cookie, None)


class ResizePresentation:
    """Une a composição nativa, os sinais do layout e a entrada do shell Tk."""

    _POINTER_EVENTS = frozenset(
        (tk.EventType.ButtonPress, tk.EventType.ButtonRelease, tk.EventType.MouseWheel)
    )

    def __init__(self, app):
        self.app = app
        self.cover = None
        self.stopped = False
        self.pending = None
        self.witness = None
        self.layout_pending = False
        self.tag = f"EduResizePresentation{id(self)}"
        tk.Misc.bind(app, "<Map>", self._mapped, add="+")
        tk.Misc.bind(app, "<FocusIn>", self._mapped, add="+")
        tk.Misc.bind(app, "<Configure>", self._configured, add="+")
        tk.Misc.bind(app, "<Unmap>", self._unmapped, add="+")
        for event in (
            "<KeyPress>",
            "<KeyRelease>",
            "<ButtonPress>",
            "<ButtonRelease>",
            "<MouseWheel>",
        ):
            app.bind_class(self.tag, event, self._guard_input)

    def _allowed(self):
        return (
            not self.stopped
            and not self.app._close_requested
            and not self.app._modal_open
            and not self.app._presentation.startup_active
        )

    def _mapped(self, event):
        if self.stopped:
            return
        if event.widget is self.app:
            self._attach()
        if self.cover is not None:
            if event.widget is self.app.sidebar and event.type == tk.EventType.Map:
                self.cover.sidebar = event.widget.winfo_id()
            self._guard_widget(event.widget)

    def _attach(self):
        try:
            native = self.cover.native if self.cover else _Win32()
            hwnd = native.ancestor(self.app.winfo_id(), 2)
            if self.cover and self.cover.attached and self.cover.hwnd == hwnd:
                return
            if self.cover:
                self.cover.close()
                self.cover = None
            pid = w.DWORD()
            if (
                not hwnd
                or native.owner(hwnd, c.byref(pid)) != get_native_id()
                or pid.value != os.getpid()
            ):
                return
            sidebar = self.app.sidebar
            cover = _NativeCover(
                native,
                hwnd,
                self._allowed,
                self._theme_color(),
                sidebar.winfo_id() if sidebar.winfo_ismapped() else None,
            )
            if cover.attached:
                self.cover = cover
                stack = [self.app]
                while stack:
                    widget = stack.pop()
                    if widget.winfo_toplevel() is self.app:
                        self._guard_widget(widget)
                        stack.extend(widget.winfo_children())
        except (OSError, AttributeError, tk.TclError):
            if self.cover:
                self.cover.close()
                self.cover = None

    def _guard_widget(self, widget):
        if widget.winfo_toplevel() is self.app:
            tags = widget.bindtags()
            if tags[0] != self.tag:
                widget.bindtags((self.tag, *(tag for tag in tags if tag != self.tag)))

    @staticmethod
    def _theme_color():
        color = SIDEBAR[int(ctk.get_appearance_mode() == "Dark")]
        red, green, blue = bytes.fromhex(color[1:])
        return red | green << 8 | blue << 16

    def _guard_input(self, event):
        cover = self.cover
        if not cover or not cover.active:
            return None
        # Um clique já entregue sob a cobertura nunca é reenviado depois de expirar.
        block_sidebar = cover.block_sidebar
        cover.expire()
        if block_sidebar:
            return "break"
        if event.type == tk.EventType.KeyPress and event.keysym == "Escape":
            self.dismiss()
            return "break"
        widget = event.widget
        while widget is not None:
            if widget is self.app.sidebar:
                return None
            widget = widget.master
        if event.type in self._POINTER_EVENTS:
            return "break"
        if event.keysym in ("Tab", "ISO_Left_Tab", "Shift_L", "Shift_R"):
            return None
        return "break"

    def begin_layout(self):
        if not self._allowed() or not self.app.winfo_viewable():
            return
        if self.cover is None:
            self._attach()
        if self.cover is None:
            return
        self.layout_pending = True
        self.cover.block_sidebar = True
        self.cover._begin()

    def finish_layout(self):
        if self.pending is not None:
            self.app.after_cancel(self.pending)
        self.layout_pending = True
        self.pending = self.app.after_idle(self._paint_layout)

    def _paint_layout(self):
        self.pending = None
        # A grade já mudou de tamanho. Renove o fundo dos canvases visíveis
        # para que o Tk descarte os pixels copiados das posições anteriores.
        try:
            widgets = [self.app]
            while widgets:
                widget = widgets.pop()
                if isinstance(widget, tk.Toplevel) or not widget.winfo_viewable():
                    continue
                if isinstance(widget, tk.Canvas):
                    tk.Canvas.configure(widget, background=widget.cget("background"))
                widgets.extend(widget.winfo_children())
        except tk.TclError:
            self.dismiss()
            return
        self.layout_pending = False
        self.changed()

    def refresh_theme(self):
        if self.cover is not None:
            self.cover.color = self._theme_color()

    def _configured(self, event):
        cover = self.cover
        if not cover:
            return
        if event.widget is self.app:
            self.refresh_theme()
        if cover.active and self.app._page_stack.widget_is_presented(event.widget):
            self.changed()

    def changed(self):
        cover = self.cover
        if cover and cover.active and not self.layout_pending:
            self.witness = None
            if self.pending is None:
                self.pending = self.app.after_idle(self._inspect, cover.operation)

    def _ready(self, cover):
        stack = self.app._page_stack
        page = stack.current._parent_frame
        host = stack.host
        rail = self.app.sidebar
        if (
            not page.winfo_viewable()
            or (page.winfo_width(), page.winfo_height())
            != (host.winfo_width(), host.winfo_height())
            or rail.winfo_height() != self.app.winfo_height()
            or cover.dimensions != (self.app.winfo_width(), self.app.winfo_height())
        ):
            return None
        native = cover.native
        dirty = False

        @native.enum
        def observe(child, _unused):
            nonlocal dirty
            dirty = bool(
                native.visible(child) and native.update_pending(child, None, False)
            )
            return not dirty

        for widget in (page, rail):
            target = widget.winfo_id()
            if native.update_pending(target, None, False):
                return None
            native.enum_children(target, observe, 0)
            if dirty:
                return None
        return page, cover.dimensions

    def _inspect(self, operation):
        self.pending = None
        cover = self.cover
        if not cover or not cover.active or self.layout_pending:
            return
        cover.expire()
        if not cover.active:
            return
        if operation != cover.operation:
            self.changed()
            return
        try:
            ready = self._ready(cover)
        except (OSError, tk.TclError):
            cover.hide("layout-unavailable")
            return
        if ready is not None and self.witness == (operation, ready):
            cover.hide("ready")
        else:
            self.witness = operation, ready
            self.pending = self.app.after(_PAINT_POLL_MS, self._inspect, operation)

    def _unmapped(self, event):
        if event.widget is self.app:
            self.dismiss()

    def dismiss(self):
        self.layout_pending = False
        if self.cover:
            self.cover.hide("dismissed")
        if self.pending is not None:
            self.app.after_cancel(self.pending)
            self.pending = None

    def close(self):
        self.stopped = True
        self.dismiss()
        if self.cover is not None:
            self.cover.close()
            self.cover = None


class ContentPresentation:
    """Mantém o viewport coberto até a composição da página persistente."""

    def __init__(self, app):
        self.app = app
        self.stack = app._page_stack
        self._unpainted = set(app._pages.values())
        self._cover = None
        self._pending = None
        self._generation = 0
        self._request = 0
        self._witness = None
        self._repaint_requested = False
        for signal in ("<Map>", "<Configure>", "<Expose>"):
            tk.Misc.bind(app, signal, self._observe, add="+")
        tk.Misc.bind(app, "<Unmap>", self._unmapped, add="+")

    @contextmanager
    def change(self, page, *, dark=None, layout=False, pointer=None):
        if dark is not None:
            self._unpainted.update(self.app._pages.values())
        if layout:
            self._unpainted.add(page)
            if page is not self.stack.current:
                yield
                return
        if page not in self._unpainted and not self._active:
            yield
            return
        self._begin(dark, pointer)
        try:
            yield
        except BaseException:
            self.dismiss()
            raise
        else:
            self._schedule()

    @property
    def _active(self):
        return self._cover is not None and self._cover.active

    def _begin(self, dark, pointer):
        self._request += 1
        self._witness = None
        self._repaint_requested = False
        if (
            self.app._close_requested
            or self.app._modal_open
            or self.app._presentation.startup_active
            or not self.stack.host.winfo_viewable()
        ):
            return
        resize = self.app._resize_presentation
        if resize and resize.cover and resize.cover.active:
            return
        try:
            if self._cover is None:
                native = resize.cover.native if resize and resize.cover else _Win32()
                hwnd = self.stack.host.winfo_id()
                pid = w.DWORD()
                if (
                    native.owner(hwnd, c.byref(pid)) != get_native_id()
                    or pid.value != os.getpid()
                ):
                    return
                self._cover = _NativeCover(native, hwnd, lambda: False, 0)
            if not self._cover.attached:
                return
            self._cover.input_hwnd = (
                pointer.winfo_id()
                if pointer is not None and pointer.winfo_viewable()
                else None
            )
            if self._active and dark is None:
                return
            if dark is None:
                dark = ctk.get_appearance_mode() == "Dark"
            red, green, blue = self.app.winfo_rgb(CANVAS[dark])
            self._cover.color = (
                (red // 257) | ((green // 257) << 8) | ((blue // 257) << 16)
            )
            self._cover.block_sidebar = True
            self._cover._begin()
        except (OSError, tk.TclError, c.ArgumentError):
            self.dismiss()

    def _observe(self, event):
        if not self._active:
            return
        widget = event.widget
        surface = self.stack.current._parent_frame
        while widget is not None and widget not in (self.stack.host, surface):
            widget = widget.master
        if widget is surface or event.widget is self.stack.host:
            self._generation += 1

    def _schedule(self, *, paint_pending=False):
        if not self._active or self._pending is not None:
            return
        if paint_pending:
            self._pending = self.app.after(_PAINT_POLL_MS, self._present)
        else:
            self._pending = self.app.after_idle(self._present)

    def _present(self):
        self._pending = None
        if not self._active:
            return
        cover = self._cover
        cover.expire()
        if not cover.active:
            return
        try:
            self._inspect(cover)
        except (OSError, tk.TclError, c.ArgumentError):
            self.dismiss()

    def _inspect(self, cover):
        request = self._request
        page = self.stack.current
        surface = page._parent_frame
        host = self.stack.host
        native = cover.native
        dirty = False

        @native.enum
        def inspect(child, _unused):
            nonlocal dirty
            dirty = bool(
                native.visible(child) and native.update_pending(child, None, False)
            )
            return not dirty

        hwnd = surface.winfo_id()
        native.enum_children(hwnd, inspect, 0)
        if (
            dirty
            or native.update_pending(hwnd, None, False)
            or not surface.winfo_viewable()
            or (surface.winfo_width(), surface.winfo_height())
            != (host.winfo_width(), host.winfo_height())
        ):
            self._witness = None
            self._schedule(paint_pending=True)
            return
        # O Windows pode validar WM_PAINT antes de o Tk entregar Expose e
        # redesenhar os canvases. Solicite a pintura e confira o ciclo seguinte.
        if self._witness != self._generation:
            if not self._repaint_requested:
                self._repaint_requested = True
                widgets = [surface]
                while widgets:
                    widget = widgets.pop()
                    if isinstance(widget, tk.Toplevel) or not widget.winfo_viewable():
                        continue
                    if isinstance(widget, tk.Canvas):
                        tk.Misc.configure(
                            widget, background=tk.Misc.cget(widget, "background")
                        )
                    widgets.extend(widget.winfo_children())
                painted = native.redraw(hwnd, None, None, _REDRAW_SUBTREE)
                if request != self._request:
                    self._schedule()
                    return
                if not painted:
                    self.dismiss()
                    return
            self._witness = self._generation
            self._schedule()
            return
        result = native.flush()
        if request != self._request:
            self._schedule()
        elif result < 0:
            self.dismiss()
        elif self._witness != self._generation:
            self._schedule()
        else:
            self._unpainted.discard(page)
            cover.hide("ready")

    def _unmapped(self, event):
        if event.widget is self.app:
            self.dismiss()

    def dismiss(self):
        self._request += 1
        if self._pending is not None:
            self.app.after_cancel(self._pending)
            self._pending = None
        if self._cover is not None:
            self._cover.hide("dismissed")

    def close(self):
        self.dismiss()
        if self._cover is not None:
            self._cover.close()
            self._cover = None
