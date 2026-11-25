"""Ponto de entrada do portátil Community no Windows."""

import sys
from contextlib import nullcontext, redirect_stderr
from io import StringIO
from pathlib import Path


def _restore_native_shapes() -> None:
    from ctypes import POINTER, WinDLL, byref, c_void_p, create_string_buffer
    from ctypes.wintypes import DWORD, HANDLE
    from customtkinter.windows.widgets.core_rendering import DrawEngine

    if DrawEngine.preferred_drawing_method != "circle_shapes":
        return

    # GDI can reject a bundled font by path even when Python can read it.
    font = (
        Path(sys._MEIPASS) / "customtkinter/assets/fonts/CustomTkinter_shapes_font.otf"
    )
    try:
        data = font.read_bytes()
        add_font = WinDLL("gdi32.dll").AddFontMemResourceEx
        add_font.argtypes = (c_void_p, DWORD, c_void_p, POINTER(DWORD))
        add_font.restype = HANDLE
        count = DWORD()
        handle = add_font(create_string_buffer(data), len(data), None, byref(count))
    except OSError:
        return
    if handle and count.value:
        DrawEngine.preferred_drawing_method = "font_shapes"


def run_shared_shell() -> None:
    # CustomTkinter reports font fallback to stderr, which a windowed build lacks.
    with redirect_stderr(StringIO()) if sys.stderr is None else nullcontext():
        from app_factory import run_shared_shell as display_shell

    if sys.platform == "win32" and getattr(sys, "frozen", False):
        _restore_native_shapes()
    display_shell()


def main() -> None:
    from installed_maintenance import command_exit

    if (code := command_exit(sys.argv[1:])) is not None:
        raise SystemExit(code)
    run_shared_shell()


if __name__ == "__main__":
    main()
