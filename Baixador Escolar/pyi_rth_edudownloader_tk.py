"""Prepara Tcl/Tk antes da importação da interface no executável congelado."""

import atexit
import ctypes
import os
import sys
from pathlib import Path


def _prepare_tcl_environment() -> None:
    internal_dir = Path(sys._MEIPASS)
    tcl_data_dir = internal_dir / "_tcl_data"
    tk_data_dir = internal_dir / "_tk_data"
    tcl_libraries = sorted(internal_dir.glob("tcl*.dll"))

    if not tcl_data_dir.is_dir() or not tk_data_dir.is_dir():
        raise FileNotFoundError("Os dados Tcl/Tk não foram incluídos na distribuição")
    if not tcl_libraries:
        raise FileNotFoundError("A DLL do Tcl não foi incluída na distribuição")

    os.chdir(internal_dir)
    os.environ["TCL_LIBRARY"] = "_tcl_data"
    os.environ["TK_LIBRARY"] = "_tk_data"
    tcl_path = b"_tcl_data"
    tk_path = b"_tk_data"

    tcl = ctypes.WinDLL(str(tcl_libraries[0]))
    tcl.Tcl_FindExecutable.argtypes = [ctypes.c_char_p]
    tcl.Tcl_FindExecutable(os.fsencode(sys.executable))
    tcl.Tcl_CreateInterp.restype = ctypes.c_void_p
    interpreter = tcl.Tcl_CreateInterp()
    if not interpreter:
        raise RuntimeError("O interpretador Tcl temporário não pôde ser criado")

    tcl.Tcl_SetVar2.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    tcl.Tcl_SetVar2.restype = ctypes.c_char_p
    for name, value in (
        (b"TCL_LIBRARY", tcl_path),
        (b"TK_LIBRARY", tk_path),
    ):
        if not tcl.Tcl_SetVar2(interpreter, b"env", name, value, 1):
            raise RuntimeError(f"A variável Tcl {name.decode()} não pôde ser definida")

    tcl.Tcl_SetVar.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    tcl.Tcl_SetVar.restype = ctypes.c_char_p
    if not tcl.Tcl_SetVar(
        interpreter,
        b"tcl_library",
        tcl_path,
        1,
    ):
        raise RuntimeError("A biblioteca global do Tcl não pôde ser definida")

    tcl.Tcl_EvalFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    if tcl.Tcl_EvalFile(interpreter, b"_tcl_data/init.tcl") != 0:
        tcl.Tcl_GetStringResult.argtypes = [ctypes.c_void_p]
        tcl.Tcl_GetStringResult.restype = ctypes.c_char_p
        detail = tcl.Tcl_GetStringResult(interpreter).decode("utf-8", "replace")
        raise RuntimeError(f"O init.tcl não pôde ser carregado: {detail}")

    tcl.Tcl_DeleteInterp.argtypes = [ctypes.c_void_p]
    atexit.register(tcl.Tcl_DeleteInterp, interpreter)


_prepare_tcl_environment()
del _prepare_tcl_environment
