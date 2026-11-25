"""Own the CustomTkinter timers used by the application shell and file preview."""

import tkinter as tk
from functools import wraps

import customtkinter as ctk
from customtkinter.windows.widgets.appearance_mode.appearance_mode_tracker import (
    AppearanceModeTracker,
)
from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker


class AppRoot(ctk.CTk):
    """Cancel only toolkit loops scheduled on this root, then hand off live loops."""

    def __init__(self, *args, **kwargs):
        self._tracker_jobs = {}
        super().__init__(*args, **kwargs)

    def _windows_set_titlebar_color(self, color_mode):
        if not self._window_exists:
            super()._windows_set_titlebar_color(color_mode)
            return
        if self._deactivate_windows_window_header_manipulation:
            return

        # O CustomTkinter retira a janela do mapa para ajustar o tema nativo.
        # Com as páginas compostas do shell isso expõe o fundo e remonta o cache.
        # Use os mesmos atributos DWM, mantendo a janela e o foco no lugar.
        import ctypes as c
        from ctypes import wintypes as w

        try:
            get_parent = c.windll.user32.GetParent
            get_parent.argtypes = (w.HWND,)
            get_parent.restype = w.HWND
            set_attribute = c.windll.dwmapi.DwmSetWindowAttribute
            set_attribute.argtypes = (w.HWND, w.DWORD, c.c_void_p, w.DWORD)
            set_attribute.restype = c.c_long
            hwnd = get_parent(self.winfo_id())
            if hwnd:
                value = w.BOOL(color_mode.lower() == "dark")
                if set_attribute(hwnd, 20, c.byref(value), c.sizeof(value)) != 0:
                    set_attribute(hwnd, 19, c.byref(value), c.sizeof(value))
        except (AttributeError, OSError, tk.TclError):
            pass

    def after(self, ms, func=None, *args, **kwargs):
        if func not in (
            AppearanceModeTracker.update,
            ScalingTracker.check_dpi_scaling,
            self._windows_set_titlebar_icon,
        ):
            return super().after(ms, func, *args, **kwargs)

        @wraps(func)
        def run():
            self._tracker_jobs.pop(func, None)
            return func(*args, **kwargs)

        job = super().after(ms, run)
        self._tracker_jobs[func] = job
        return job

    def destroy(self):
        appearance = AppearanceModeTracker
        scaling = ScalingTracker
        pending = self._tracker_jobs
        self._tracker_jobs = {}
        for job in pending.values():
            self.after_cancel(job)
        if self in appearance.app_list:
            appearance.app_list.remove(self)
        super().destroy()
        scaling.window_dpi_scaling_dict.pop(self, None)
        if appearance.update in pending:
            appearance.update_loop_running = self._resume_tracker(
                appearance.app_list, appearance.update_loop_interval, appearance.update
            )
        if scaling.check_dpi_scaling in pending:
            scaling.update_loop_running = self._resume_tracker(
                scaling.window_widgets_dict,
                scaling.update_loop_interval,
                scaling.check_dpi_scaling,
            )

    @staticmethod
    def _resume_tracker(windows, interval, callback):
        for window in windows:
            try:
                if window.winfo_exists():
                    window.after(interval, callback)
                    return True
            except tk.TclError:
                continue
        return False


class FormEntry(ctk.CTkEntry):
    """Own the textvariable trace left registered by CustomTkinter 5.2.2."""

    def __init__(self, *args, textvariable=None, **kwargs):
        self._traced_variable = textvariable
        super().__init__(*args, textvariable=textvariable, **kwargs)

    def destroy(self):
        if getattr(self, "_textvariable_callback_name", ""):
            self._traced_variable.trace_remove(
                "write", self._textvariable_callback_name
            )
            self._textvariable_callback_name = ""
        super().destroy()


class PreviewTextbox(ctk.CTkTextbox):
    """Keep the scrollbar refresh token for the lifetime of this text widget."""

    _scrollbar_job = None

    def after(self, ms, func=None, *args, **kwargs):
        job = super().after(ms, func, *args, **kwargs)
        if func == self._check_if_scrollbars_needed and args == (None, True):
            self._scrollbar_job = job
        return job

    def _check_if_scrollbars_needed(self, event=None, continue_loop=False):
        if continue_loop:
            self._scrollbar_job = None
        super()._check_if_scrollbars_needed(event)
        if continue_loop and self.winfo_exists():
            self.after(
                self._scrollbar_update_time,
                self._check_if_scrollbars_needed,
                None,
                True,
            )

    def destroy(self):
        if self._scrollbar_job is not None:
            self.after_cancel(self._scrollbar_job)
            self._scrollbar_job = None
        super().destroy()
