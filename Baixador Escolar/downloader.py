"""Serviço de download portátil baseado em yt-dlp e FFmpeg."""

from __future__ import annotations

import errno
import ctypes
import json
import logging
import math
import os
import queue
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO
from urllib.parse import parse_qsl, unquote, urlsplit

from constants import (
    CONTENT_TYPE_AUDIO,
    CONTENT_TYPE_VIDEO,
    DENO_FILENAME,
    FFMPEG_FILENAME,
    FFPROBE_FILENAME,
    VIDEO_QUALITIES,
    PRODUCT_EDITION,
    ProductEdition,
)
from paths import (
    ensure_downloads_dir,
    get_app_dir,
    get_log_path,
    get_tool_path,
)
from yt_dlp_update import resolve_active_yt_dlp
from component_transactions import ComponentBusyError
from component_runtime import active_component, component_use
from mp3_quality import DEFAULT_MP3_QUALITY, Mp3Quality
from utils import is_valid_url


PROGRESS_PREFIX = "BAIXADOR_PROGRESSO|"
FILE_PREFIX = "BAIXADOR_ARQUIVO|"
VIDEO_OUTPUT_TEMPLATE = "%(title)s [%(id)s] [%(height)sp].%(ext)s"
AUDIO_OUTPUT_TEMPLATE = "%(title)s [%(id)s] [audio].%(ext)s"
TASK_TEMP_ROOT_NAME = ".edudownloader-temporarios"
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUP_COUNT = 2
PROGRESS_TEMPLATE = (
    PROGRESS_PREFIX
    + "%(progress._percent_str)s|%(progress.downloaded_bytes)s|"
    + "%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|"
    + "%(progress.speed)s|%(progress.eta)s"
)

QUALITY_HEIGHTS: dict[str, int | None] = {
    "Melhor qualidade": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}

_HTTP_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_WINDOWS_USER_PROFILE_PATTERN = re.compile(
    r"\b[A-Z]:[\\/]+Users[\\/]+[^\\/\r\n\"]+(?=[\\/])",
    re.IGNORECASE,
)

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004
_JOB_FINISH_GRACE_SECONDS = 0.5
_JOB_FINISH_POLL_SECONDS = 0.01


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("thread_id", wintypes.DWORD),
        ("owner_pid", wintypes.DWORD),
        ("base_priority", wintypes.LONG),
        ("delta_priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
    ]


class _JobBasicLimits(ctypes.Structure):
    _fields_ = [
        ("per_process_time", ctypes.c_int64),
        ("per_job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD),
        ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t),
        ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class _JobIoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_operations",
            "write_operations",
            "other_operations",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _JobExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _JobBasicLimits),
        ("io", _JobIoCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class _JobAccounting(ctypes.Structure):
    _fields_ = [
        ("total_user_time", ctypes.c_int64),
        ("total_kernel_time", ctypes.c_int64),
        ("period_user_time", ctypes.c_int64),
        ("period_kernel_time", ctypes.c_int64),
        ("page_faults", wintypes.DWORD),
        ("total_processes", wintypes.DWORD),
        ("active_processes", wintypes.DWORD),
        ("terminated_processes", wintypes.DWORD),
    ]


class _WindowsDownloadJob:
    """Mantém os filhos do yt-dlp sob a posse de uma única tarefa."""

    def __init__(self, handle: int) -> None:
        self._handle = handle
        self._lock = threading.Lock()
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._kernel32.TerminateJobObject.restype = wintypes.BOOL
        self._kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    @classmethod
    def attach(cls, process_handle: int) -> _WindowsDownloadJob:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = _JobExtendedLimits()
            limits.basic.flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ) or not kernel32.AssignProcessToJobObject(handle, process_handle):
                raise ctypes.WinError(ctypes.get_last_error())
            return cls(int(handle))
        except Exception:
            kernel32.CloseHandle(handle)
            raise

    def _active_processes(self) -> int:
        accounting = _JobAccounting()
        returned = wintypes.DWORD()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            ctypes.byref(returned),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(accounting.active_processes)

    @staticmethod
    def resume(process_id: int) -> None:
        """Libera a thread principal somente após vincular o processo ao Job."""
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ThreadEntry),
        ]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            if not kernel32.Thread32First(snapshot, ctypes.byref(entry)):
                raise ctypes.WinError(ctypes.get_last_error())
            while True:
                if entry.owner_pid == process_id:
                    thread = kernel32.OpenThread(
                        _THREAD_SUSPEND_RESUME, False, entry.thread_id
                    )
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if kernel32.ResumeThread(thread) != 1:
                            raise ctypes.WinError(ctypes.get_last_error())
                    finally:
                        kernel32.CloseHandle(thread)
                    return
                if not kernel32.Thread32Next(snapshot, ctypes.byref(entry)):
                    raise OSError("A thread inicial do download não foi encontrada.")
        finally:
            kernel32.CloseHandle(snapshot)

    def terminate(self) -> bool:
        with self._lock:
            if not self._handle:
                return False
            if self._active_processes() and not self._kernel32.TerminateJobObject(
                self._handle, 1
            ):
                return False
            deadline = time.monotonic() + 5.0
            while self._active_processes():
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)
            return True

    def finish(self) -> tuple[bool, bool]:
        """Distingue término natural e confirma o fim da árvore da tarefa."""
        # O wait do lançador não aguarda descendentes como o conhost. Dê à
        # árvore owned uma janela limitada de término natural, fora da UI.
        deadline = time.monotonic() + _JOB_FINISH_GRACE_SECONDS
        while True:
            with self._lock:
                if not self._handle:
                    return False, False
                if not self._active_processes():
                    return True, True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, self.terminate()
            # Não reter o lock: cancelamento pode terminar o Job nesse intervalo.
            time.sleep(min(_JOB_FINISH_POLL_SECONDS, remaining))

    def close(self) -> None:
        with self._lock:
            if self._handle:
                self._kernel32.CloseHandle(self._handle)
                self._handle = 0


@dataclass(frozen=True)
class ToolPaths:
    """Caminhos dos quatro executáveis externos obrigatórios."""

    yt_dlp: Path
    ffmpeg: Path
    ffprobe: Path
    deno: Path


@dataclass(frozen=True)
class DownloadRequest:
    """Dados imutáveis escolhidos para um download."""

    url: str
    content_type: str
    quality: str
    destination_dir: Path | None = None
    mp3_quality: Mp3Quality = DEFAULT_MP3_QUALITY


@dataclass(frozen=True)
class DownloadProgress:
    """Medições reais fornecidas pelo yt-dlp durante o download."""

    percent: float | None
    downloaded_bytes: float | None
    total_bytes: float | None
    speed: float | None
    eta: float | None


@dataclass(frozen=True)
class DownloadResult:
    """Resultado confirmado da execução do yt-dlp."""

    final_output_path: Path
    already_existed: bool

    @property
    def file_path(self) -> Path:
        """Alias temporário para consumidores anteriores ao contrato 1.1."""
        return self.final_output_path


class DownloadPhase(str, Enum):
    """Fases internas observáveis sem texto de apresentação da interface."""

    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    VERIFYING = "verifying"


class DownloadEventKind(str, Enum):
    """Tipos de mensagens enviadas da thread de trabalho à interface."""

    PHASE = "phase"
    PROGRESS = "progress"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class DownloadEvent:
    """Mensagem segura colocada na fila do serviço."""

    kind: DownloadEventKind
    payload: object = None


class DownloadEventBuffer:
    """Preserva eventos estruturais e limita telemetria de progresso redundante."""

    def __init__(self) -> None:
        self._events: deque[DownloadEvent] = deque()
        self._latest_progress: DownloadEvent | None = None
        self._lock = threading.Lock()

    def put(self, event: DownloadEvent) -> None:
        """Mantém somente a amostra mais nova entre eventos estruturais."""
        with self._lock:
            if event.kind == DownloadEventKind.PROGRESS:
                self._latest_progress = event
                return
            self._flush_progress_locked()
            self._events.append(event)

    def get_nowait(self) -> DownloadEvent:
        """Retorna o próximo evento na ordem sem bloquear a thread gráfica."""
        with self._lock:
            if self._events:
                return self._events.popleft()
            if self._latest_progress is not None:
                event = self._latest_progress
                self._latest_progress = None
                return event
        raise queue.Empty

    def empty(self) -> bool:
        """Informa se não há eventos estruturais nem progresso pendente."""
        with self._lock:
            return not self._events and self._latest_progress is None

    def qsize(self) -> int:
        """Expõe o backlog efetivo para diagnóstico e testes determinísticos."""
        with self._lock:
            return len(self._events) + int(self._latest_progress is not None)

    def has_structural_event(self) -> bool:
        """Permite priorizar fases e términos já ordenados no buffer."""
        with self._lock:
            return any(
                event.kind != DownloadEventKind.PROGRESS for event in self._events
            )

    def _flush_progress_locked(self) -> None:
        if self._latest_progress is not None:
            self._events.append(self._latest_progress)
            self._latest_progress = None


class DownloadServiceError(Exception):
    """Erro conhecido que contém uma mensagem segura para o usuário."""

    def __init__(self, user_message: str, details: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.details = details


class MissingToolsError(DownloadServiceError):
    """Indica que um ou mais executáveis externos não foram encontrados."""


class DownloadBusyError(DownloadServiceError):
    """Indica tentativa de iniciar um segundo download simultâneo."""


class DownloadCancelledError(DownloadServiceError):
    """Controle interno usado quando o usuário cancela o download."""


def locate_tools(base_dir: Path | None = None) -> ToolPaths:
    """Localiza os executáveis ao lado do programa, sem caminhos fixos."""
    base = base_dir or get_app_dir()
    media = active_component(base, "ffmpeg-ffprobe")
    deno = active_component(base, "deno")
    return ToolPaths(
        yt_dlp=resolve_active_yt_dlp(base).path,
        ffmpeg=(
            media[0] / FFMPEG_FILENAME
            if media
            else get_tool_path(FFMPEG_FILENAME, base)
        ),
        ffprobe=(
            media[0] / FFPROBE_FILENAME
            if media
            else get_tool_path(FFPROBE_FILENAME, base)
        ),
        deno=(deno[0] / DENO_FILENAME if deno else get_tool_path(DENO_FILENAME, base)),
    )


def validate_external_tools(base_dir: Path | None = None) -> ToolPaths:
    """Valida os quatro executáveis e informa cada ausência em português."""
    tools = locate_tools(base_dir)
    tool_paths = (tools.yt_dlp, tools.ffmpeg, tools.ffprobe, tools.deno)
    missing = [path.name for path in tool_paths if not path.is_file()]
    if missing:
        messages = [
            f"{filename} não foi encontrado na pasta do aplicativo."
            for filename in missing
        ]
        raise MissingToolsError("\n".join(messages), ", ".join(missing))
    return tools


def _probe_destination_writable(destination_dir: Path) -> None:
    """Confirma escrita real sem deixar um arquivo persistente no destino."""
    with tempfile.TemporaryFile(dir=destination_dir):
        pass


def _resolve_download_destination(
    requested_destination: Path | None,
    base_dir: Path,
) -> Path:
    """Resolve e valida uma única vez o destino efetivo da tarefa."""
    explicit_destination = requested_destination is not None
    try:
        if explicit_destination:
            candidate = Path(requested_destination)
            if not candidate.is_absolute():
                raise ValueError("o destino explícito deve ser absoluto")
        else:
            candidate = ensure_downloads_dir(base_dir)

        destination_dir = candidate.resolve(strict=True)
        if not destination_dir.is_dir():
            raise NotADirectoryError(
                errno.ENOTDIR,
                "o destino informado não é um diretório",
                str(candidate),
            )
        with os.scandir(destination_dir):
            pass
        _probe_destination_writable(destination_dir)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        if explicit_destination:
            user_message = (
                "Não foi possível usar a pasta de destino selecionada. "
                "Verifique se ela existe e permite gravação."
            )
        elif isinstance(error, OSError):
            user_message = classify_os_error(error)
        else:
            user_message = (
                "Não foi possível preparar a pasta de downloads. "
                "Consulte o arquivo de log."
            )
        raise DownloadServiceError(user_message, str(error)) from error
    return destination_dir


def _validate_final_output_path(
    reported_path: Path,
    destination_dir: Path,
    details: str,
) -> Path:
    """Aceita somente um arquivo final regular contido no destino da tarefa."""
    candidate = (
        reported_path
        if reported_path.is_absolute()
        else destination_dir / reported_path
    )
    try:
        final_path = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise DownloadServiceError(
            "O yt-dlp terminou, mas o arquivo final não foi encontrado. "
            "Consulte o arquivo de log.",
            details,
        ) from error

    try:
        final_path.relative_to(destination_dir)
    except ValueError as error:
        raise DownloadServiceError(
            "O yt-dlp informou um arquivo final fora da pasta de destino autorizada.",
            details,
        ) from error

    try:
        reported_stat = os.lstat(candidate)
    except OSError as error:
        raise DownloadServiceError(
            "O yt-dlp terminou, mas o arquivo final não foi encontrado. "
            "Consulte o arquivo de log.",
            details,
        ) from error
    if (
        stat.S_ISLNK(reported_stat.st_mode)
        or _is_reparse_point(reported_stat)
        or not stat.S_ISREG(reported_stat.st_mode)
    ):
        raise DownloadServiceError(
            "O yt-dlp informou um arquivo final inválido. Consulte o arquivo de log.",
            details,
        )
    return final_path


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    """Reconhece junctions e outros reparse points expostos pelo Windows."""
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(path_stat, "st_file_attributes", 0) & reparse_attribute)


def build_video_format(quality: str) -> str:
    """Prioriza H.264/AAC e usa outros codecs somente como alternativa."""
    if quality not in QUALITY_HEIGHTS:
        raise ValueError(f"Qualidade de vídeo desconhecida: {quality}")

    height = QUALITY_HEIGHTS[quality]
    height_filter = "" if height is None else f"[height<={height}]"
    return "/".join(
        (
            f"bv{height_filter}[vcodec^=avc1]+ba[acodec^=mp4a]",
            f"b{height_filter}[vcodec^=avc1][acodec^=mp4a]",
            f"bv{height_filter}[vcodec^=avc1]+ba",
            f"b{height_filter}[vcodec^=avc1]",
            f"bv*{height_filter}+ba[acodec^=mp4a]",
            f"b{height_filter}[acodec^=mp4a]",
            f"bv*{height_filter}+ba/b{height_filter}",
        )
    )


def build_download_command(
    request: DownloadRequest,
    tools: ToolPaths,
    downloads_dir: Path,
) -> list[str]:
    """Monta o comando como lista segura, inclusive para caminhos com espaços."""
    if not is_valid_url(request.url):
        raise ValueError("URL inválida")
    if request.content_type not in {CONTENT_TYPE_VIDEO, CONTENT_TYPE_AUDIO}:
        raise ValueError(f"Tipo de conteúdo desconhecido: {request.content_type}")
    if (
        request.content_type == CONTENT_TYPE_VIDEO
        and request.quality not in VIDEO_QUALITIES
    ):
        raise ValueError(f"Qualidade desconhecida: {request.quality}")
    if request.content_type == CONTENT_TYPE_AUDIO and not isinstance(
        request.mp3_quality, Mp3Quality
    ):
        raise ValueError("Perfil MP3 desconhecido")

    command = [
        str(tools.yt_dlp),
        "--ignore-config",
        "--no-js-runtimes",
        "--js-runtimes",
        f"deno:{tools.deno.resolve()}",
        "--no-remote-components",
        "--no-playlist",
        "--newline",
        "--no-color",
        "--encoding",
        "utf-8",
        "--progress",
        "--progress-template",
        f"download:{PROGRESS_TEMPLATE}",
        "--print",
        f"after_move:{FILE_PREFIX}%(filepath)s",
        "--no-simulate",
        "--windows-filenames",
        "--trim-filenames",
        "180",
        "--no-overwrites",
        "--paths",
        str(downloads_dir),
        "--output",
        (
            AUDIO_OUTPUT_TEMPLATE
            if request.content_type == CONTENT_TYPE_AUDIO
            else VIDEO_OUTPUT_TEMPLATE
        ),
        "--ffmpeg-location",
        str(tools.ffmpeg.parent),
    ]

    if request.content_type == CONTENT_TYPE_AUDIO:
        command.extend(
            [
                "--format",
                "bestaudio/best",
                "--extract-audio",
                "--audio-format",
                "mp3",
                "--audio-quality",
                request.mp3_quality.bitrate_argument.upper(),
            ]
        )
    else:
        command.extend(
            [
                "--format",
                build_video_format(request.quality),
                "--merge-output-format",
                "mp4",
                "--remux-video",
                "mp4",
            ]
        )

    command.append(request.url)
    return command


def parse_progress_line(line: str) -> DownloadProgress | None:
    """Transforma a linha especial do yt-dlp em dados de progresso."""
    if not line.startswith(PROGRESS_PREFIX):
        return None

    fields = line.strip().split("|")
    if len(fields) != 7:
        return None

    percent = _parse_number(fields[1].replace("%", ""))
    downloaded = _parse_number(fields[2])
    total = _parse_number(fields[3]) or _parse_number(fields[4])
    speed = _parse_number(fields[5])
    eta = _parse_number(fields[6])

    if percent is None and downloaded is not None and total:
        percent = downloaded / total * 100
    if percent is not None:
        percent = max(0.0, min(100.0, percent))

    return DownloadProgress(percent, downloaded, total, speed, eta)


def classify_download_error(output: str) -> str:
    """Converte detalhes técnicos frequentes em uma mensagem amigável."""
    lowered = output.lower()
    http_error = re.search(r"\bhttp(?:\s+error|/[\d.]+)?[\s:]+([45]\d\d)\b", lowered)
    if http_error:
        status = int(http_error.group(1))
        if status in {404, 410}:
            return "O recurso está indisponível ou foi removido. Verifique o link informado."
        if status in {401, 403}:
            return "A origem recusou o acesso ao conteúdo. Verifique se o link é público e autorizado."
        if status == 429:
            return "A origem recebeu muitas solicitações. Aguarde e tente novamente."
        if status >= 500:
            return (
                "O servidor de origem apresentou uma falha. Tente novamente mais tarde."
            )
        return f"A origem retornou um erro HTTP {status}. Verifique o link e tente novamente."
    network_markers = (
        "unable to download webpage",
        "failed to resolve",
        "network is unreachable",
        "connection refused",
        "connection reset",
        "timed out",
        "temporary failure in name resolution",
    )
    unavailable_markers = (
        "video unavailable",
        "content is not available",
        "private video",
        "login required",
        "sign in to confirm",
        "this video is unavailable",
        "drm protected",
    )
    permission_markers = (
        "permission denied",
        "access is denied",
        "winerror 5",
    )
    disk_space_markers = (
        "no space left on device",
        "not enough space on the disk",
        "disk full",
        "winerror 112",
    )

    if any(marker in lowered for marker in network_markers):
        return "Não foi possível acessar a internet. Verifique sua conexão e tente novamente."
    if any(marker in lowered for marker in disk_space_markers):
        return "Não há espaço livre suficiente. Libere espaço no dispositivo e tente novamente."
    if any(marker in lowered for marker in permission_markers):
        return (
            "Não foi possível gravar na pasta de destino. Verifique a permissão "
            "da pasta e tente novamente."
        )
    if "unsupported url" in lowered:
        return "O link informado não é compatível ou não está disponível para download."
    if any(marker in lowered for marker in unavailable_markers):
        return (
            "O conteúdo está indisponível ou exige uma forma de acesso não suportada."
        )
    if "ffmpeg" in lowered and "not found" in lowered:
        return (
            "O FFmpeg não pôde ser utilizado. Verifique os executáveis do aplicativo."
        )
    if "requested format is not available" in lowered:
        return (
            "O conteúdo não oferece um formato compatível com a qualidade escolhida. "
            "Tente outra qualidade."
        )
    return (
        "Não foi possível concluir o download. Verifique sua conexão e se o "
        "conteúdo está disponível. Consulte o arquivo de log para mais detalhes."
    )


def classify_os_error(error: OSError) -> str:
    """Traduz falhas locais comuns sem exibir detalhes técnicos ou pessoais."""
    error_number = getattr(error, "errno", None)
    winerror = getattr(error, "winerror", None)
    if isinstance(error, PermissionError) or error_number in {
        errno.EACCES,
        errno.EPERM,
    }:
        return (
            "Não foi possível gravar na pasta de destino. Verifique a permissão "
            "da pasta e tente novamente."
        )
    if error_number == errno.ENOSPC or winerror == 112:
        return "Não há espaço livre suficiente. Libere espaço no dispositivo e tente novamente."
    return "Não foi possível preparar o download. Consulte o arquivo de log."


class DownloadService:
    """Executa um download por vez fora da thread gráfica."""

    def __init__(
        self,
        base_dir: Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.base_dir = (base_dir or get_app_dir()).resolve()
        self.events = DownloadEventBuffer()
        self._owns_logger = logger is None
        self._logger = logger or _create_logger(get_log_path(self.base_dir))
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._process_tree_stopped = threading.Event()
        self._process_tree_stopped.set()
        self._termination_thread: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._job: _WindowsDownloadJob | None = None
        self._running = False
        self._yt_dlp_update_active = False

    @property
    def is_running(self) -> bool:
        """Informa de forma segura se existe uma operação em andamento."""
        with self._lock:
            return self._running

    def start(self, request: DownloadRequest) -> None:
        """Valida, prepara e inicia a thread de download."""
        with self._lock:
            if self._running:
                raise DownloadBusyError("Já existe um download em andamento.")
            if self._yt_dlp_update_active:
                raise DownloadBusyError("Aguarde a atualização do componente terminar.")
            self._cancel_event.clear()
            self._process_tree_stopped.set()
            self._termination_thread = None
            self._running = True

        try:
            tools = validate_external_tools(self.base_dir)
            destination_dir = _resolve_download_destination(
                request.destination_dir,
                self.base_dir,
            )
            protected = PRODUCT_EDITION is ProductEdition.COMMUNITY
            if protected:
                from download_network import check_media_destination

                try:
                    check_media_destination(request.url)
                except ValueError:
                    raise DownloadServiceError(
                        "O endereço do download é inválido ou aponta para um destino não permitido."
                    ) from None
            existing_files = (
                frozenset()
                if protected
                else frozenset(
                    path.resolve()
                    for path in destination_dir.iterdir()
                    if path.is_file()
                )
            )
            command = build_download_command(request, tools, destination_dir)
        except DownloadServiceError as error:
            with self._lock:
                self._running = False
            self._logger.error(
                "Falha ao preparar download | %s | detalhes=%s",
                error.user_message,
                _redact_sensitive_text(
                    error.details,
                    self.base_dir,
                    request.url,
                    request.destination_dir,
                ),
            )
            raise
        except (OSError, ValueError) as error:
            with self._lock:
                self._running = False
            safe_details = _redact_sensitive_text(
                str(error),
                self.base_dir,
                request.url,
                request.destination_dir,
            )
            self._logger.error(
                "Falha ao preparar download | tipo=%s | detalhes=%s",
                type(error).__name__,
                safe_details,
            )
            user_message = (
                classify_os_error(error)
                if isinstance(error, OSError)
                else "Não foi possível preparar o download. Consulte o arquivo de log."
            )
            raise DownloadServiceError(user_message, safe_details) from error

        try:
            worker = threading.Thread(
                target=self._worker_main,
                args=(request, command, existing_files, destination_dir),
                kwargs={"protected": protected},
                name="download-worker",
                daemon=True,
            )
            with self._lock:
                self._worker = worker
            worker.start()
        except Exception as error:
            safe_details = _redact_sensitive_text(
                str(error),
                self.base_dir,
                request.url,
                destination_dir,
            )
            self._logger.error(
                "Falha ao iniciar thread | tipo=%s | detalhes=%s",
                type(error).__name__,
                safe_details,
            )
            with self._lock:
                self._running = False
                self._worker = None
            raise DownloadServiceError(
                "Não foi possível iniciar o processamento do download.",
                safe_details,
            ) from error

    def begin_yt_dlp_update(self) -> bool:
        """Reserva o componente sem interromper um download em andamento."""
        with self._lock:
            if self._running or self._yt_dlp_update_active:
                return False
            self._yt_dlp_update_active = True
            return True

    def end_yt_dlp_update(self) -> None:
        """Libera a reserva após update, falha ou cancelamento."""
        with self._lock:
            self._yt_dlp_update_active = False

    def cancel(self) -> bool:
        """Solicita cancelamento e encerra a árvore de processos sem bloquear a UI."""
        with self._lock:
            if not self._running:
                return False
            already_requested = self._cancel_event.is_set()
            self._cancel_event.set()
            process = self._process
            if process is not None and not already_requested:
                self._process_tree_stopped.clear()
                termination_thread = threading.Thread(
                    target=self._terminate_process_tree_and_signal,
                    args=(process,),
                    name="download-canceller",
                    daemon=True,
                )
                self._termination_thread = termination_thread
                try:
                    termination_thread.start()
                except Exception:
                    # shutdown() ainda pode terminar a árvore sincronamente se
                    # não houver recursos para criar o worker de cancelamento.
                    self._termination_thread = None
                    raise
        return True

    def shutdown(self, timeout: float = 5.0) -> None:
        """Cancela e aguarda brevemente, evitando processos órfãos ao fechar."""
        with self._lock:
            running = self._running
            worker = self._worker
            process = self._process
            termination_thread = self._termination_thread
            if running:
                self._cancel_event.set()

        if process is not None:
            if termination_thread is not None:
                termination_thread.join()
            else:
                self._process_tree_stopped.clear()
                self._terminate_process_tree_and_signal(process)
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=timeout)

    def close(self, timeout: float = 5.0) -> None:
        """Encerra a operação e libera explicitamente o arquivo de log."""
        self.shutdown(timeout)
        if self._owns_logger:
            for handler in list(self._logger.handlers):
                try:
                    handler.flush()
                except OSError:
                    pass
                try:
                    handler.close()
                except OSError:
                    pass
                finally:
                    self._logger.removeHandler(handler)

    def _worker_main(
        self,
        request: DownloadRequest,
        command: list[str],
        existing_files: frozenset[Path] = frozenset(),
        destination_dir: Path | None = None,
        *,
        protected: bool = False,
    ) -> None:
        """Controla resultado e erros da execução feita na thread secundária."""
        started_at = time.monotonic()
        logged_quality = (
            f"MP3 {request.mp3_quality.display_label}"
            if request.content_type == CONTENT_TYPE_AUDIO
            else request.quality
        )
        self._logger.info(
            "Início do download | tipo=%s | qualidade=%s",
            request.content_type,
            logged_quality,
        )
        self.events.put(DownloadEvent(DownloadEventKind.PHASE, DownloadPhase.PREPARING))

        try:
            try:
                with component_use(self.base_dir, "yt-dlp", "deno", "ffmpeg-ffprobe"):
                    if protected:
                        assert destination_dir is not None
                        result = self._secure_execute(request, command, destination_dir)
                    else:
                        result = self._execute(command, existing_files, destination_dir)
            except ComponentBusyError as error:
                raise DownloadBusyError(
                    "Aguarde a atualização dos componentes terminar."
                ) from error
            outcome = (
                "Arquivo já existente"
                if result.already_existed
                else "Download concluído"
            )
            self._logger.info(
                "Término do download | resultado=%s | arquivo=%s | duração=%.2fs",
                outcome,
                result.final_output_path.name,
                max(0.0, time.monotonic() - started_at),
            )
            self.events.put(DownloadEvent(DownloadEventKind.COMPLETED, result))
        except DownloadCancelledError:
            self._logger.info(
                "Término do download | resultado=cancelado | duração=%.2fs",
                max(0.0, time.monotonic() - started_at),
            )
            self.events.put(DownloadEvent(DownloadEventKind.CANCELLED))
        except DownloadServiceError as error:
            details = _redact_sensitive_text(
                error.details,
                self.base_dir,
                request.url,
                destination_dir,
            )
            self._logger.error(
                "Término do download | resultado=erro | duração=%.2fs | %s | detalhes=%s",
                max(0.0, time.monotonic() - started_at),
                error.user_message,
                details,
            )
            self.events.put(DownloadEvent(DownloadEventKind.ERROR, error))
        except Exception as error:
            safe_details = _redact_sensitive_text(
                str(error),
                self.base_dir,
                request.url,
                destination_dir,
            )
            self._logger.error(
                "Término do download | resultado=erro inesperado | duração=%.2fs | tipo=%s | detalhes=%s",
                max(0.0, time.monotonic() - started_at),
                type(error).__name__,
                safe_details,
            )
            friendly_error = DownloadServiceError(
                "Ocorreu um erro desconhecido. Consulte o arquivo de log.",
                safe_details,
            )
            self.events.put(DownloadEvent(DownloadEventKind.ERROR, friendly_error))
        finally:
            # Um sucesso pode ganhar da solicitação de cancelamento. Mesmo
            # assim, o canceller antigo precisa sair antes de liberar o serviço:
            # ele consulta self._job e não pode enxergar o Job de outra tarefa.
            while True:
                with self._lock:
                    termination_thread = self._termination_thread
                    if termination_thread is None or not termination_thread.is_alive():
                        self._process = None
                        self._job = None
                        self._termination_thread = None
                        self._worker = None
                        self._running = False
                        break
                termination_thread.join()

    def _secure_execute(
        self, request: DownloadRequest, command: list[str], destination: Path
    ) -> DownloadResult:
        from download_network import DownloadNetwork

        staging = self._create_task_temp_dir(destination)
        try:
            with DownloadNetwork() as route:
                guarded = list(command)
                guarded[guarded.index("--paths") + 1] = str(staging)
                selector = guarded.index("--format") + 1
                guarded[selector] = re.sub(
                    r"(^|[+/])(?:bestaudio|best|bv\*?|ba|b)(?=\[|[+/]|$)",
                    lambda match: (
                        match[0]
                        + "[protocol~='^(?:https?|m3u8(?:_native)?|http_dash_segments)$']"
                    ),
                    guarded[selector],
                )
                guarded[-1:-1] = [
                    "--proxy",
                    route.url,
                    "--socket-timeout",
                    "18",
                    "--no-plugin-dirs",
                    "--downloader",
                    "m3u8:native",
                    "--downloader-args",
                    "ffmpeg_i:-protocol_whitelist pipe",
                    "--postprocessor-args",
                    "ffmpeg_i:-protocol_whitelist file,pipe "
                    "-format_whitelist mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,mp3,aac,ogg,mpegts,flac,wav,avi,flv",
                    "--",
                ]
                try:
                    result = self._execute(guarded, destination_dir=staging)
                except DownloadServiceError as error:
                    if route.blocked:
                        raise DownloadServiceError(
                            "O download foi interrompido porque um endereço de rede não é permitido."
                        ) from None
                    # A credencial do proxy existe só durante a tarefa e não
                    # deve sobreviver em diagnósticos, mesmo se o motor a ecoar.
                    error.details = route.redact(error.details)
                    raise
            if self._cancel_event.is_set():
                raise DownloadCancelledError("Download cancelado.")
            self.events.put(
                DownloadEvent(DownloadEventKind.PHASE, DownloadPhase.VERIFYING)
            )
            path = result.file_path
            identity = self._staged_identity(path, staging, request.content_type)
            self._verify_media(path, request.content_type)
            if self._staged_identity(path, staging, request.content_type) != identity:
                raise DownloadServiceError(
                    "O arquivo mudou durante a verificação de segurança."
                )
            self._verify_attachment(path, request.url)
            saved = self._staged_identity(path, staging, request.content_type)
            if saved[:3] != identity[:3]:
                raise DownloadServiceError(
                    "O arquivo mudou durante a verificação de segurança."
                )
            if saved != identity:
                # Gravar Zone.Identifier também pode alterar a data do arquivo
                # no NTFS. Valida o conteúdo efetivo após o retorno do Windows.
                self._verify_media(path, request.content_type)
            target = destination / path.name
            with self._lock:
                if self._cancel_event.is_set():
                    raise DownloadCancelledError("Download cancelado.")
                if self._staged_identity(path, staging, request.content_type) != saved:
                    raise DownloadServiceError(
                        "O arquivo mudou durante a verificação de segurança."
                    )
                if destination.resolve(strict=True) != destination or _is_reparse_point(
                    destination.lstat()
                ):
                    raise DownloadServiceError(
                        "A pasta de destino mudou durante a verificação."
                    )
                try:
                    if os.name == "nt":
                        # Renomear no mesmo volume preserva os fluxos NTFS,
                        # inclusive informações de zona que o Windows gravou.
                        os.rename(path, target)
                    else:
                        os.link(path, target)
                except FileExistsError:
                    raise DownloadServiceError(
                        "O arquivo de destino já existe e não foi substituído."
                    ) from None
            return DownloadResult(target, False)
        except OSError as error:
            raise DownloadServiceError(classify_os_error(error), str(error)) from error
        finally:
            if self._process_tree_stopped.is_set():
                self._cleanup_cancelled_task_temp(staging, destination)

    @staticmethod
    def _staged_identity(path: Path, staging: Path, content_type: str):
        extension = ".mp4" if content_type == CONTENT_TYPE_VIDEO else ".mp3"
        try:
            if path.parent != staging or path.suffix.casefold() != extension:
                raise ValueError
            if _validate_final_output_path(path, staging, "") != path:
                raise ValueError
            info = path.lstat()
            if (
                info.st_nlink != 1
                or info.st_size < 16
                or staging.resolve(strict=True) != staging
                or _is_reparse_point(staging.lstat())
            ):
                raise ValueError
        except (ValueError, OSError, DownloadServiceError):
            raise DownloadServiceError(
                "O conteúdo recebido não corresponde ao formato de mídia esperado."
            ) from None
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    def _run_verification_process(self, command, *, timeout, capture=False):
        if self._cancel_event.is_set():
            raise DownloadCancelledError("Download cancelado.")
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parent
            if not getattr(sys, "frozen", False)
            else self.base_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with self._lock:
            self._process = process
        deadline = time.monotonic() + timeout
        try:
            while True:
                if self._cancel_event.is_set():
                    raise DownloadCancelledError("Download cancelado.")
                if time.monotonic() >= deadline:
                    raise TimeoutError
                try:
                    output, _ = process.communicate(timeout=0.1)
                    if self._cancel_event.is_set():
                        raise DownloadCancelledError("Download cancelado.")
                    return process.returncode, output
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                self._terminate_process_tree(process)
            if process.poll() is None:
                self._process_tree_stopped.clear()
            if process.stdout is not None:
                process.stdout.close()
            with self._lock:
                if self._process is process and process.poll() is not None:
                    self._process = None

    def _verify_media(self, path, content_type):
        video = content_type == CONTENT_TYPE_VIDEO
        formats = "mov,mp4,m4a,3gp,3g2,mj2" if video else "mp3"
        try:
            with path.open("rb") as stream:
                head = stream.read(12)
            if video and head[4:8] != b"ftyp":
                raise ValueError
            code, output = self._run_verification_process(
                [
                    str(locate_tools(self.base_dir).ffprobe),
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file",
                    "-max_alloc",
                    "67108864",
                    "-format_whitelist",
                    formats,
                    "-probesize",
                    "4194304",
                    "-analyzeduration",
                    "4000000",
                    "-max_streams",
                    "16",
                    "-show_entries",
                    "format=format_name:stream=codec_type,codec_name:stream_disposition=attached_pic",
                    "-of",
                    "json",
                    str(path),
                ],
                timeout=18,
                capture=True,
            )
            if code != 0 or not output or len(output) > 64 * 1024:
                raise ValueError
            info = json.loads(output)
            streams = info["streams"]
            name = info["format"]["format_name"]
            if video:
                matches = (
                    "mp4" in name.split(",")
                    and any(
                        stream["codec_type"] == "video"
                        and stream.get("codec_name")
                        and not stream.get("disposition", {}).get("attached_pic")
                        for stream in streams
                    )
                    and any(
                        stream["codec_type"] == "audio" and stream.get("codec_name")
                        for stream in streams
                    )
                )
            else:
                matches = name == "mp3" and any(
                    stream["codec_type"] == "audio"
                    and stream.get("codec_name") == "mp3"
                    for stream in streams
                )
            if not matches:
                raise ValueError
        except TimeoutError:
            raise DownloadServiceError(
                "Não foi possível concluir a verificação do formato."
            ) from None
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise DownloadServiceError(
                "O conteúdo recebido não corresponde ao formato de mídia esperado."
            ) from None

    def _verify_attachment(self, path, url):
        from windows_attachment import (
            ATTACHMENT_COMMAND,
            AttachmentStatus,
            source_origin,
        )

        if os.name != "nt":
            raise DownloadServiceError(
                "A verificação de segurança do Windows está indisponível."
            )
        command = [sys.executable]
        if not getattr(sys, "frozen", False):
            command.extend(("-B", "-m", "windows_attachment"))
        command.extend((ATTACHMENT_COMMAND, str(path), source_origin(url)))
        try:
            code, _ = self._run_verification_process(command, timeout=60)
        except OSError:
            raise DownloadServiceError(
                "Não foi possível concluir a verificação de segurança."
            ) from None
        if code == AttachmentStatus.BLOCKED:
            raise DownloadServiceError(
                "O arquivo foi bloqueado pela segurança do Windows."
            )
        if code == AttachmentStatus.UNAVAILABLE:
            raise DownloadServiceError(
                "A verificação de segurança do Windows está indisponível."
            )
        if code != AttachmentStatus.APPROVED:
            raise DownloadServiceError(
                "Não foi possível concluir a verificação de segurança."
            )

    def _create_task_temp_dir(self, destination_dir: Path | None = None) -> Path:
        """Cria uma área exclusiva para os temporários desta execução."""
        effective_destination = destination_dir or ensure_downloads_dir(self.base_dir)
        temp_root = effective_destination / TASK_TEMP_ROOT_NAME
        temp_root.mkdir(parents=True, exist_ok=True)
        if temp_root.resolve(strict=True) != temp_root or _is_reparse_point(
            temp_root.lstat()
        ):
            raise OSError(errno.EACCES, "Área de trabalho redirecionada")
        return Path(tempfile.mkdtemp(prefix="tarefa-", dir=temp_root))

    @staticmethod
    def _command_with_task_temp(command: list[str], task_temp_dir: Path) -> list[str]:
        """Acrescenta o caminho temporário antes da única URL do comando."""
        if len(command) < 2:
            raise DownloadServiceError("O comando de download está incompleto.")
        execution_command = list(command)
        end = -2 if execution_command[-2] == "--" else -1
        execution_command[end:end] = ["--paths", f"temp:{task_temp_dir}"]
        return execution_command

    def _remove_empty_task_temp(self, task_temp_dir: Path) -> None:
        """Remove somente diretórios temporários que já estejam vazios."""
        try:
            task_temp_dir.rmdir()
        except OSError:
            return
        try:
            task_temp_dir.parent.rmdir()
        except OSError:
            pass

    def _cleanup_cancelled_task_temp(
        self,
        task_temp_dir: Path,
        destination_dir: Path | None = None,
    ) -> tuple[int, int]:
        """Remove apenas os arquivos pertencentes à tarefa cancelada."""
        effective_destination = destination_dir or ensure_downloads_dir(self.base_dir)
        expected_root = effective_destination / TASK_TEMP_ROOT_NAME
        removed = 0
        failures = 0

        try:
            task_parent = task_temp_dir.parent.resolve(strict=True)
            task_stat = os.lstat(task_temp_dir)
            resolved_task_dir = task_temp_dir.resolve(strict=True)
        except (OSError, RuntimeError):
            self._logger.warning(
                "Limpeza após cancelamento | resultado=ignorada | motivo=caminho inválido"
            )
            return 0, 1
        if (
            task_parent != expected_root
            or resolved_task_dir.parent != expected_root
            or stat.S_ISLNK(task_stat.st_mode)
            or _is_reparse_point(task_stat)
            or not stat.S_ISDIR(task_stat.st_mode)
        ):
            self._logger.warning(
                "Limpeza após cancelamento | resultado=ignorada | motivo=caminho inválido"
            )
            return 0, 1

        entries = []
        directories = [resolved_task_dir]
        while directories:
            directory = directories.pop()
            try:
                if directory.resolve(strict=True) != directory or _is_reparse_point(
                    directory.lstat()
                ):
                    raise OSError("Diretório de tarefa redirecionado")
                for entry in directory.iterdir():
                    info = entry.lstat()
                    entries.append((entry, info))
                    if stat.S_ISDIR(info.st_mode) and not _is_reparse_point(info):
                        directories.append(entry)
            except (OSError, RuntimeError):
                failures += 1

        for entry, info in reversed(entries):
            try:
                if entry.parent.resolve(strict=True) != entry.parent:
                    raise OSError("Diretório de tarefa redirecionado")
                if stat.S_ISDIR(info.st_mode):
                    entry.rmdir()
                else:
                    entry.unlink()
                    removed += 1
            except OSError:
                failures += 1

        try:
            resolved_task_dir.rmdir()
        except OSError:
            if resolved_task_dir.exists():
                failures += 1
        try:
            expected_root.rmdir()
        except OSError:
            pass

        self._logger.info(
            "Limpeza após cancelamento | temporários removidos=%d | falhas=%d",
            removed,
            failures,
        )
        return removed, failures

    def _terminate_process_tree_and_signal(
        self, process: subprocess.Popen[str]
    ) -> None:
        """Encerra a árvore e sinaliza que a limpeza já pode começar."""
        try:
            with self._lock:
                job = self._job
            if job is not None:
                stopped = job.terminate()
            else:
                self._terminate_process_tree(process)
                stopped = process.poll() is not None
        except OSError:
            stopped = False
        if stopped:
            self._process_tree_stopped.set()

    def _wait_for_process_tree_shutdown(self) -> bool:
        """Aguarda a rotina limitada de encerramento fora da thread gráfica."""
        with self._lock:
            termination_thread = self._termination_thread
        if (
            termination_thread is not None
            and termination_thread is not threading.current_thread()
        ):
            termination_thread.join()
        else:
            self._process_tree_stopped.wait(timeout=15)
        return self._process_tree_stopped.is_set()

    def _execute(
        self,
        command: list[str],
        existing_files: frozenset[Path] = frozenset(),
        destination_dir: Path | None = None,
    ) -> DownloadResult:
        """Executa o yt-dlp e só confirma sucesso se o arquivo final existir."""
        if self._cancel_event.is_set():
            raise DownloadCancelledError("Download cancelado.")

        try:
            effective_destination = (
                destination_dir
                if destination_dir is not None
                else ensure_downloads_dir(self.base_dir).resolve()
            )
            task_temp_dir = self._create_task_temp_dir(effective_destination)
            execution_command = self._command_with_task_temp(command, task_temp_dir)
        except OSError as error:
            raise DownloadServiceError(classify_os_error(error), str(error)) from error

        creation_flags = 0
        if os.name == "nt":
            creation_flags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
            )

        try:
            process = subprocess.Popen(
                execution_command,
                cwd=self.base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
                creationflags=creation_flags,
            )
        except OSError as error:
            self._remove_empty_task_temp(task_temp_dir)
            raise DownloadServiceError(classify_os_error(error), str(error)) from error

        job: _WindowsDownloadJob | None = None
        if os.name == "nt" and isinstance(getattr(process, "_handle", None), int):
            try:
                job = _WindowsDownloadJob.attach(int(process._handle))
                job.resume(process.pid)
            except OSError as error:
                if job is not None:
                    job.close()
                else:
                    self._terminate_process_tree(process)
                if process.stdout is not None:
                    process.stdout.close()
                self._remove_empty_task_temp(task_temp_dir)
                raise DownloadServiceError(
                    "Não foi possível controlar os processos do download.", str(error)
                ) from error
        with self._lock:
            self._process = process
            self._job = job

        if self._cancel_event.is_set():
            with self._lock:
                termination_thread = self._termination_thread
            if termination_thread is None:
                self._process_tree_stopped.clear()
                self._terminate_process_tree_and_signal(process)

        output_lines: deque[str] = deque(maxlen=40)
        file_path: Path | None = None
        stdout: TextIO | None = process.stdout
        owned_tree_finished = True

        try:
            if stdout is None:
                raise DownloadServiceError("Não foi possível acompanhar o download.")

            for raw_line in stdout:
                line = raw_line.strip()
                if not line:
                    continue
                output_lines.append(line)

                progress = parse_progress_line(line)
                if progress is not None:
                    self.events.put(DownloadEvent(DownloadEventKind.PROGRESS, progress))
                    continue
                if line.startswith(FILE_PREFIX):
                    file_path = Path(line[len(FILE_PREFIX) :])
                    continue

                phase = _phase_from_output(line)
                if phase is not None:
                    self.events.put(DownloadEvent(DownloadEventKind.PHASE, phase))

            return_code = process.wait()
        except Exception:
            self._terminate_process_tree_and_signal(process)
            raise
        finally:
            try:
                if stdout is not None:
                    stdout.close()
            finally:
                if job is not None:
                    try:
                        owned_tree_finished, tree_stopped = job.finish()
                        if tree_stopped:
                            self._process_tree_stopped.set()
                    except OSError:
                        owned_tree_finished = False
                    finally:
                        job.close()
                        with self._lock:
                            if self._job is job:
                                self._job = None

        # Erros sem fragmentos também não devem deixar uma pasta vazia. Se houver
        # conteúdo, preserve-o: a posse/atividade de descendentes não foi provada.
        self._remove_empty_task_temp(task_temp_dir)
        if not owned_tree_finished and not self._cancel_event.is_set():
            raise DownloadServiceError(
                "O download terminou com processos auxiliares ainda ativos."
            )
        if return_code == 0:
            details = "\n".join(output_lines)
            if file_path is None:
                raise DownloadServiceError(
                    "O yt-dlp terminou sem informar o arquivo final. Consulte o arquivo de log.",
                    details,
                )
            final_path = _validate_final_output_path(
                file_path,
                effective_destination,
                details,
            )
            self._remove_empty_task_temp(task_temp_dir)
            return DownloadResult(final_path, final_path in existing_files)
        if self._cancel_event.is_set():
            if self._wait_for_process_tree_shutdown():
                self._cleanup_cancelled_task_temp(
                    task_temp_dir,
                    effective_destination,
                )
            else:
                self._logger.warning(
                    "Limpeza após cancelamento | resultado=adiada | "
                    "motivo=árvore de processos ainda ativa"
                )
            raise DownloadCancelledError("Download cancelado.")
        details = "\n".join(output_lines)
        # Ordinary downloads retain strict format selection. Only an unavailable
        # limited MP4 format may retry unknown heights, entirely in owned staging.
        if (
            "requested format is not available" in details.lower()
            and "--remux-video" in command
        ):
            heights = set(
                re.findall(r"\[height<=(\d+)\]", command[command.index("--format") + 1])
            )
            if len(heights) == 1:
                return self._download_verified_height(
                    command, effective_destination, int(heights.pop())
                )
        raise DownloadServiceError(classify_download_error(details), details)

    def _download_verified_height(
        self, command: list[str], destination: Path, limit: int
    ) -> DownloadResult:
        staging = self._create_task_temp_dir(destination)
        try:
            fallback = list(command)
            index = fallback.index("--format") + 1
            fallback[index] = fallback[index].replace(
                f"[height<={limit}]", f"[height<=?{limit}]"
            )
            end = -2 if fallback[-2] == "--" else -1
            fallback[end:end] = ["--paths", f"home:{staging}"]
            result = self._execute(fallback, frozenset(), staging)
            height = self._probe_video_height(result.file_path)
            if height > limit:
                raise DownloadServiceError(
                    f"O vídeo excede o limite de {limit}p e não foi salvo. Escolha outra qualidade.",
                )
            target = destination / result.file_path.name
            # Validate the target again and publish exclusively. Never replace a
            # user file that existed before the download or appeared meanwhile.
            with self._lock:
                if self._cancel_event.is_set():
                    raise DownloadCancelledError("Download cancelado.")
                if target.exists():
                    raise DownloadServiceError(
                        "O arquivo de destino já existe e não foi substituído."
                    )
                if os.name == "nt":
                    os.rename(result.file_path, target)
                else:
                    os.link(result.file_path, target)
            return DownloadResult(target, False)
        except OSError as error:
            raise DownloadServiceError(classify_os_error(error), str(error)) from error
        finally:
            if self._process_tree_stopped.is_set():
                self._cleanup_cancelled_task_temp(staging, destination)

    def _probe_video_height(self, path: Path) -> int:
        """Read actual stream dimensions; never infer them from a URL/filename."""
        if self._cancel_event.is_set():
            raise DownloadCancelledError("Download cancelado.")
        security_options = []
        if PRODUCT_EDITION is ProductEdition.COMMUNITY:
            security_options = [
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                "mov,mp4,m4a,3gp,3g2,mj2",
                "-max_alloc",
                "67108864",
                "-max_streams",
                "16",
            ]
        process = subprocess.Popen(
            [
                str(locate_tools(self.base_dir).ffprobe),
                "-v",
                "error",
                *security_options,
                "-select_streams",
                "v",
                "-show_entries",
                "stream=height",
                "-of",
                "json",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with self._lock:
            self._process = process
        deadline = time.monotonic() + 15
        try:
            while True:
                if self._cancel_event.is_set():
                    raise DownloadCancelledError("Download cancelado.")
                if time.monotonic() >= deadline:
                    raise ValueError("Resolution probe timed out")
                try:
                    stdout, _stderr = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            self._check_resolution_probe(process.returncode, stdout)
            streams = json.loads(stdout)["streams"]
            return max(stream["height"] for stream in streams)
        except DownloadCancelledError:
            raise
        except (ValueError, KeyError, TypeError) as error:
            raise DownloadServiceError(
                "Não foi possível confirmar a resolução do vídeo. O limite escolhido não foi ignorado."
            ) from error
        finally:
            if process.poll() is None:
                self._terminate_process_tree(process)
            if process.poll() is None:
                self._process_tree_stopped.clear()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    @staticmethod
    def _check_resolution_probe(returncode: int, output: str) -> None:
        if returncode != 0 or len(output) > 100_000:
            raise ValueError("Invalid resolution probe")
        streams = json.loads(output)["streams"]
        if (
            not isinstance(streams, list)
            or not streams
            or not all(
                isinstance(stream, dict)
                and type(stream.get("height")) is int
                and stream["height"] > 0
                for stream in streams
            )
        ):
            raise ValueError("Unknown video resolution")

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
        """Encerra yt-dlp e processos filhos como FFmpeg/ffprobe."""
        if process.poll() is not None:
            return

        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            try:
                process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass

        try:
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass

        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass


def _parse_number(value: str) -> float | None:
    """Converte campos numéricos do yt-dlp, aceitando valores ausentes."""
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"na", "n/a", "none", "null"}:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _phase_from_output(line: str) -> DownloadPhase | None:
    """Reconhece fases internas sem acoplar o serviço ao texto da interface."""
    lowered = line.lower()
    information_markers = (
        "extracting url",
        "downloading webpage",
        "downloading api json",
        "downloading initial data",
        "downloading player",
    )
    if any(marker in lowered for marker in information_markers):
        return DownloadPhase.PREPARING
    if line.startswith("[download]"):
        return DownloadPhase.DOWNLOADING
    if line.startswith(
        (
            "[Merger]",
            "[ExtractAudio]",
            "[VideoRemuxer]",
            "[RemuxVideo]",
            "[MoveFiles]",
        )
    ):
        return DownloadPhase.PROCESSING
    return None


def _redact_sensitive_text(
    text: str,
    base_dir: Path | None = None,
    source_url: str | None = None,
    destination_dir: Path | None = None,
) -> str:
    """Remove URL, destino da tarefa e caminhos pessoais dos detalhes do log."""
    # Recognize complete paths before URL fragments can change their spelling.
    # All overlapping spans are removed together; markers are never reprocessed.
    patterns = [(_HTTP_URL_PATTERN.pattern, "[URL removida]")]
    paths = [
        (path, marker)
        for path, marker in (
            (destination_dir, "[PASTA DE DESTINO]"),
            (base_dir, "[PASTA DO APLICATIVO]"),
        )
        if path is not None
    ]
    for path, marker in sorted(paths, key=lambda item: len(str(item[0])), reverse=True):
        # Accept native, forward, mixed and escaped Windows separators.
        pattern = r"[\\/]+".join(
            re.escape(part) for part in re.split(r"[\\/]+", str(path))
        )
        patterns.append((pattern, marker))
    patterns.append((_WINDOWS_USER_PROFILE_PATTERN.pattern, "[PERFIL DO USUÁRIO]"))
    if source_url:
        patterns.extend(_source_url_redaction_patterns(source_url))
    return _replace_sensitive_patterns(text, patterns)


def _source_url_redaction_patterns(source_url: str) -> list[tuple[str, str]]:
    """Recognize secondary representations of the submitted URL."""
    try:
        parsed = urlsplit(source_url)
    except ValueError:
        return []

    endpoint_variants = _decoded_variants(parsed.netloc)
    if parsed.hostname:
        endpoint_variants.update(_decoded_variants(parsed.hostname))

    path = parsed.path
    query = parsed.query
    path_and_query = path + (f"?{query}" if query else "")
    url_data_variants = _decoded_variants(path_and_query)
    url_data_variants.update(_decoded_variants(query))
    for raw_parameter in query.split("&"):
        url_data_variants.update(_decoded_variants(raw_parameter))
        raw_name, _, raw_value = raw_parameter.partition("=")
        for part in (raw_name, raw_value):
            url_data_variants.update(
                variant for variant in _decoded_variants(part) if len(variant) >= 4
            )
    for name, value in parse_qsl(query, keep_blank_values=True):
        if name:
            url_data_variants.update(_decoded_variants(f"{name}={value}"))
            if len(name) >= 4:
                url_data_variants.update(_decoded_variants(name))
        if len(value) >= 4:
            url_data_variants.update(_decoded_variants(value))
    if parsed.fragment:
        url_data_variants.update(_decoded_variants(parsed.fragment))
    if path not in {"", "/"}:
        url_data_variants.update(_decoded_variants(path))
        bare_path = path.lstrip("/")
        bare_path_and_query = path_and_query.lstrip("/")
        if len(bare_path) >= 3:
            url_data_variants.update(_decoded_variants(bare_path))
        if len(bare_path_and_query) >= 3:
            url_data_variants.update(_decoded_variants(bare_path_and_query))

    # Userinfo may also be echoed separately by an external diagnostic.
    url_data_variants.update(_decoded_variants(parsed.username or ""))
    url_data_variants.update(_decoded_variants(parsed.password or ""))
    patterns = []
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        patterns.append(
            (rf"\bport\s*=\s*['\"]?{port}['\"]?(?!\d)", "port=[PORTA removida]")
        )
    for variant in sorted(endpoint_variants | url_data_variants, key=len, reverse=True):
        marker = (
            "[ENDPOINT DA URL removido]"
            if variant in endpoint_variants
            else "[DADOS DA URL removidos]"
        )
        patterns.append((re.escape(variant), marker))
    return patterns


def _decoded_variants(value: str) -> set[str]:
    if not value:
        return set()
    return {value, unquote(value)} - {""}


def _replace_sensitive_patterns(text: str, patterns: list[tuple[str, str]]) -> str:
    """Merge all original sensitive spans before emitting any replacements."""
    spans = []
    for priority, (expression, _) in enumerate(patterns):
        # Lookahead also finds a match beginning inside another match.
        for match in re.finditer(f"(?=({expression}))", text, re.IGNORECASE):
            start, end = match.span(1)
            if end > start:
                spans.append((start, end, priority))
    if not spans:
        return text
    spans.sort()
    chunks = []
    position = 0
    start, end, priority = spans[0]
    for next_start, next_end, next_priority in spans[1:]:
        if next_start < end:
            end = max(end, next_end)
            priority = min(priority, next_priority)
        else:
            chunks.extend((text[position:start], patterns[priority][1]))
            position = end
            start, end, priority = next_start, next_end, next_priority
    chunks.extend((text[position:start], patterns[priority][1], text[end:]))
    return "".join(chunks)


def _create_logger(log_path: Path) -> logging.Logger:
    """Cria um logger UTF-8 rotativo ou usa descarte seguro sem escrita."""
    logger = logging.getLogger(f"edudownloader.download.{log_path.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handler: logging.Handler = RotatingFileHandler(
                log_path,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
            )
        except OSError:
            handler = logging.NullHandler()
        logger.addHandler(handler)
    return logger
