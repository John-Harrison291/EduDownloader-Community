"""Attachment Services para arquivos de mídia ainda no diretório da tarefa."""

from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
from enum import IntEnum
import os
from pathlib import Path
import stat
import sys
from uuid import UUID

from utils import split_media_url

ATTACHMENT_COMMAND = "--verify-download-attachment"
TASK_TEMP_ROOT_NAME = ".edudownloader-temporarios"


class AttachmentStatus(IntEnum):
    APPROVED = 0
    BLOCKED = 34
    UNAVAILABLE = 35
    FAILED = 36


def source_origin(url: str) -> str:
    parsed = split_media_url(url)
    host = parsed.hostname
    authority = f"[{host}]" if ":" in host else host.encode("idna").decode("ascii")
    if parsed.port is not None:
        authority += f":{parsed.port}"
    return f"{parsed.scheme}://{authority}/"


def _guid(value: str):
    return (c.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le)


def _check_staged_media(path: Path):
    if (
        not path.is_absolute()
        or path.suffix.casefold() not in {".mp4", ".mp3"}
        or not path.parent.name.startswith("tarefa-")
        or path.parent.parent.name != TASK_TEMP_ROOT_NAME
        or path.resolve(strict=True) != path
    ):
        raise ValueError("Arquivo fora da área de verificação")
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Arquivo redirecionado")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Arquivo de mídia inválido")


def save_attachment(path: Path, origin: str) -> AttachmentStatus:
    if os.name != "nt":
        return AttachmentStatus.UNAVAILABLE
    try:
        _check_staged_media(path)
        origin = source_origin(origin)
        ole = c.WinDLL("ole32.dll")
        initialize = ole.CoInitializeEx
        initialize.argtypes = (c.c_void_p, w.DWORD)
        initialize.restype = w.LONG
        if initialize(None, 0x2 | 0x4) < 0:
            return AttachmentStatus.UNAVAILABLE
    except (AttributeError, OSError, ValueError):
        return AttachmentStatus.UNAVAILABLE
    try:
        return _save_attachment(ole, path, origin)
    except (AttributeError, OSError, ValueError):
        return AttachmentStatus.FAILED
    finally:
        ole.CoUninitialize()


def _save_attachment(ole, path, origin):
    clsid = _guid("4125dd96-e03a-4103-8f70-e0597d803b9c")
    interface = _guid("73db1241-1e85-4581-8e4f-a81e1d0f8c57")
    instance = c.c_void_p()
    create = ole.CoCreateInstance
    create.argtypes = (
        c.c_void_p,
        c.c_void_p,
        w.DWORD,
        c.c_void_p,
        c.POINTER(c.c_void_p),
    )
    create.restype = w.LONG
    if (
        create(c.byref(clsid), None, 1, c.byref(interface), c.byref(instance)) != 0
        or not instance
    ):
        return AttachmentStatus.UNAVAILABLE
    table = c.cast(instance, c.POINTER(c.POINTER(c.c_void_p))).contents
    release = c.WINFUNCTYPE(w.ULONG, c.c_void_p)(table[2])
    invoke = c.WINFUNCTYPE(w.LONG, c.c_void_p)
    invoke_string = c.WINFUNCTYPE(w.LONG, c.c_void_p, w.LPCWSTR)
    try:
        if invoke_string(table[5])(instance, str(path)) != 0:
            return AttachmentStatus.FAILED
        if invoke_string(table[7])(instance, origin) != 0:
            return AttachmentStatus.FAILED
        # CheckPolicy controla a execução. Save ainda pode validar e marcar
        # um anexo que exige confirmação do Windows quando o usuário o abre.
        execution_policy = invoke(table[9])(instance)
        if execution_policy not in (0, 1):  # S_OK, S_FALSE
            return AttachmentStatus.BLOCKED
        result = invoke(table[11])(instance) & 0xFFFFFFFF
        if result == 0:
            return AttachmentStatus.APPROVED
        if result in {0x80070005, 0x800700E1, 0x800700E2, 0x800704EC, 0x800C000E}:
            return AttachmentStatus.BLOCKED
        return AttachmentStatus.FAILED
    finally:
        release(instance)


def attachment_exit(arguments: list[str]) -> int:
    if len(arguments) != 3 or arguments[0] != ATTACHMENT_COMMAND:
        return int(AttachmentStatus.FAILED)
    return int(save_attachment(Path(arguments[1]), arguments[2]))


if __name__ == "__main__":
    raise SystemExit(attachment_exit(sys.argv[1:]))
