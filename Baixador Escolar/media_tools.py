"""Conversões locais de mídia com FFmpeg e publicação segura."""

from __future__ import annotations

import errno
import json
import math
import os
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from downloader import locate_tools
from component_transactions import ComponentBusyError
from component_runtime import component_use
from paths import get_app_dir
from mp3_quality import DEFAULT_MP3_QUALITY, Mp3Quality


SUPPORTED_VIDEO_SUFFIXES: Final = frozenset(
    {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
)
FFPROBE_TIMEOUT_SECONDS: Final = 30.0
PROCESS_SHUTDOWN_TIMEOUT_SECONDS: Final = 1.0
# MP3 pode acrescentar frames de padding/atraso, inclusive em sample rates baixos.
# Tolerância absoluta, sem crescer com o vídeo e sem relaxar os limites de entrada.
MP3_SEGMENT_DURATION_TOLERANCE_SECONDS: Final = 0.25


class MediaToolsError(Exception):
    """Erro seguro que pode ser apresentado diretamente à pessoa usuária."""


class MediaOperationCancelled(MediaToolsError):
    """Indica que a operação de mídia foi cancelada de forma controlada."""


@dataclass(frozen=True)
class MediaToolPaths:
    """Executáveis necessários para as conversões locais de mídia."""

    ffmpeg: Path
    ffprobe: Path


@dataclass(frozen=True)
class MediaConversionResult:
    """Resultado validado de uma conversão local concluída."""

    output_path: Path
    duration_seconds: float


@dataclass(frozen=True)
class MediaConversionProgress:
    """Tempo realmente processado pelo FFmpeg e duração sondada, se disponível."""

    processed_seconds: float
    total_seconds: float | None

    @property
    def fraction(self) -> float | None:
        if self.total_seconds is None:
            return None
        return min(self.processed_seconds / self.total_seconds, 0.99)


def locate_media_tools(base_dir: Path | None = None) -> MediaToolPaths:
    """Reutiliza a descoberta portátil já usada pelo downloader."""

    tools = locate_tools(base_dir)
    return MediaToolPaths(ffmpeg=tools.ffmpeg, ffprobe=tools.ffprobe)


def build_video_to_mp3_command(
    tools: MediaToolPaths,
    source: Path,
    temporary_output: Path,
    quality: Mp3Quality = DEFAULT_MP3_QUALITY,
    *,
    report_progress: bool = False,
) -> list[str]:
    """Monta um argv previsível para extrair somente o primeiro áudio em MP3."""

    if not isinstance(quality, Mp3Quality):
        raise ValueError("Perfil MP3 desconhecido")

    command = [
        str(tools.ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
    ]
    if report_progress:
        command.extend(["-nostats", "-stats_period", "0.2", "-progress", "pipe:1"])
    command.extend(
        [
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            quality.bitrate_argument,
            str(temporary_output),
        ]
    )
    return command


def build_video_probe_command(tools: MediaToolPaths, source: Path) -> list[str]:
    """Sonda áudio e duração da origem sem depender do stderr humano."""

    return [
        str(tools.ffprobe),
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,duration:format=duration",
        "-of",
        "json",
        str(source),
    ]


def build_mp3_probe_command(tools: MediaToolPaths, output: Path) -> list[str]:
    """Monta um argv JSON para validar streams e duração do MP3 gerado."""

    return [
        str(tools.ffprobe),
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,duration:format=duration",
        "-of",
        "json",
        str(output),
    ]


class MediaToolsService:
    """Executa conversões locais sem depender da interface gráfica."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir
        self._process_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._external_cancel_event: threading.Event | None = None
        self._cancel_monitor: threading.Thread | None = None
        self._cancel_monitor_stop = threading.Event()
        self._cancel_monitor_error: MediaToolsError | None = None
        self._active_process: subprocess.Popen[str] | None = None
        self._operation_active = False
        self._operation_worker_finished = True
        self._output_published = False

    def request_cancel(self) -> bool:
        """Solicita cancelamento da operação e encerra somente seu processo ativo."""

        with self._process_lock:
            if not self._operation_active or self._output_published:
                return False
            self._cancel_event.set()
            process = self._active_process

        if process is not None:
            try:
                self._stop_owned_process(process)
            finally:
                self._release_finished_process(process)
        return True

    def video_to_mp3(
        self,
        source: Path | str,
        output: Path | str,
        *,
        overwrite: bool = False,
        quality: Mp3Quality = DEFAULT_MP3_QUALITY,
        on_progress: Callable[[MediaConversionProgress], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> MediaConversionResult:
        """Extrai áudio MP3 no perfil escolhido e publica só uma saída validada."""

        return self._video_to_mp3(
            source,
            output,
            overwrite=overwrite,
            quality=quality,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )

    def video_segment_to_mp3(
        self,
        source: Path | str,
        output: Path | str,
        *,
        start_seconds: float,
        end_seconds: float,
        overwrite: bool = False,
        quality: Mp3Quality = DEFAULT_MP3_QUALITY,
        on_progress: Callable[[MediaConversionProgress], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> MediaConversionResult:
        """Extrai [início, fim) em segundos int/float finitos, relativos à origem.

        Exige 0 <= início < fim <= duração sondada pelo FFprobe. Strings e bool
        não são aceitos. A duração do MP3 pode diferir em até 0,25 s por frames
        e atraso do codificador; esta tolerância não se aplica à entrada.
        """

        return self._video_to_mp3(
            source,
            output,
            overwrite=overwrite,
            quality=quality,
            on_progress=on_progress,
            cancel_event=cancel_event,
            segment=(start_seconds, end_seconds),
        )

    def _video_to_mp3(
        self,
        source: Path | str,
        output: Path | str,
        *,
        overwrite: bool,
        quality: Mp3Quality,
        on_progress: Callable[[MediaConversionProgress], None] | None,
        cancel_event: threading.Event | None,
        segment: tuple[float, float] | None = None,
    ) -> MediaConversionResult:
        self._begin_operation(cancel_event)
        temporary_path: Path | None = None
        lease = component_use(self._base_dir or get_app_dir(), "ffmpeg-ffprobe")
        holding_lease = False
        try:
            lease.__enter__()
            holding_lease = True
            if segment is not None:
                segment = _validate_segment_times(*segment)
            if not isinstance(quality, Mp3Quality):
                raise MediaToolsError("Selecione uma qualidade MP3 válida.")
            source_path = _validate_video_input(source)
            output_path = _validate_mp3_output(output, source_path, overwrite)
            tools = _validate_media_tools(self._base_dir)
            self._raise_if_cancelled()

            source_duration: float | None = None
            if on_progress is not None or segment is not None:
                probe = self._run_command(
                    build_video_probe_command(tools, source_path),
                    timeout=FFPROBE_TIMEOUT_SECONDS,
                )
                self._raise_if_cancelled()
                source_duration = _validate_video_probe(probe)
                if segment is not None:
                    if source_duration is None:
                        raise MediaToolsError(
                            "Não foi possível determinar uma duração válida do vídeo."
                        )
                    if segment[1] > source_duration:
                        raise MediaToolsError(
                            "O fim do trecho não pode ultrapassar a duração do vídeo."
                        )
                    source_duration = segment[1] - segment[0]
                if on_progress is not None:
                    on_progress(MediaConversionProgress(0.0, source_duration))

            self._raise_if_cancelled()

            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{output_path.stem}-",
                suffix=".tmp.mp3",
                dir=output_path.parent,
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)

            command = build_video_to_mp3_command(
                tools,
                source_path,
                temporary_path,
                quality,
                report_progress=on_progress is not None,
            )
            if segment is not None:
                # Seek de entrada: FFmpeg faz accurate_seek ao transcodificar,
                # decodificando só desde o ponto de busca anterior ao início.
                # -t é de saída e limita a duração, sem confundir fim com duração.
                input_index = command.index("-i")
                command[input_index:input_index] = ["-ss", f"{segment[0]:.9f}"]
                command[-1:-1] = ["-t", f"{source_duration:.9f}"]
            conversion = (
                self._run_command(command)
                if on_progress is None
                else self._run_command(
                    command,
                    on_progress=on_progress,
                    total_duration=source_duration,
                )
            )
            self._raise_if_cancelled()
            if conversion.returncode != 0:
                raise MediaToolsError(_classify_ffmpeg_failure(conversion.stderr))

            duration = self._validate_mp3(temporary_path, tools)
            if segment is not None and abs(duration - source_duration) > (
                MP3_SEGMENT_DURATION_TOLERANCE_SECONDS
            ):
                raise MediaToolsError(
                    "A duração do MP3 gerado não corresponde ao trecho solicitado."
                )
            self._publish_output(temporary_path, output_path, overwrite=overwrite)
            return MediaConversionResult(output_path, duration)
        except MediaToolsError:
            raise
        except ComponentBusyError as error:
            raise MediaToolsError(
                "Aguarde a atualização das ferramentas de vídeo."
            ) from error
        except OSError as error:
            raise MediaToolsError(_classify_os_error(error)) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            if holding_lease:
                lease.__exit__(None, None, None)
            self._finish_operation()

    def _begin_operation(self, cancel_event: threading.Event | None = None) -> None:
        with self._process_lock:
            if self._operation_active:
                raise MediaToolsError("Já existe uma operação de mídia em andamento.")
            self._cancel_event.clear()
            self._external_cancel_event = cancel_event
            self._cancel_monitor_error = None
            self._cancel_monitor_stop = threading.Event()
            if cancel_event is not None and cancel_event.is_set():
                self._cancel_event.set()
            self._active_process = None
            self._operation_active = True
            self._operation_worker_finished = False
            self._output_published = False
        if cancel_event is not None:
            # communicate()/pipe reads may block without producing progress. A
            # per-operation watcher uses the same owned-process cancellation as UI.
            def watch():
                while not self._cancel_monitor_stop.wait(0.05):
                    if cancel_event.is_set():
                        try:
                            self.request_cancel()
                        except MediaToolsError as error:
                            self._cancel_monitor_error = error
                        return

            self._cancel_monitor = threading.Thread(
                target=watch, name="edudownloader-media-token", daemon=True
            )
            try:
                self._cancel_monitor.start()
            except (OSError, RuntimeError) as error:
                self._cancel_monitor = None
                self._finish_operation()
                raise MediaToolsError(
                    "Não foi possível preparar o cancelamento da mídia."
                ) from error

    def _finish_operation(self) -> None:
        self._cancel_monitor_stop.set()
        monitor = self._cancel_monitor
        if monitor is not None:
            monitor.join()
        self._cancel_monitor = None
        self._external_cancel_event = None
        with self._process_lock:
            self._operation_worker_finished = True
            process = self._active_process
            if process is None or process.poll() is not None:
                self._active_process = None
                self._operation_active = False

    def _raise_if_cancelled(self) -> None:
        if self._cancel_monitor_error is not None:
            raise self._cancel_monitor_error
        if self._cancellation_requested():
            raise MediaOperationCancelled("A operação de mídia foi cancelada.")

    def _cancellation_requested(self) -> bool:
        if (
            self._external_cancel_event is not None
            and self._external_cancel_event.is_set()
        ):
            self._cancel_event.set()
        return self._cancel_event.is_set()

    def _run_command(
        self,
        command: list[str],
        *,
        timeout: float | None = None,
        on_progress: Callable[[MediaConversionProgress], None] | None = None,
        total_duration: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self._raise_if_cancelled()
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        )
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=creation_flags,
            )
            with self._process_lock:
                self._active_process = process
                cancelled = self._cancellation_requested()
            if cancelled:
                self._stop_owned_process(process)
                self._raise_if_cancelled()

            try:
                if on_progress is None:
                    stdout, stderr = process.communicate(timeout=timeout)
                else:
                    stdout, stderr = self._collect_progress(
                        process, on_progress, total_duration
                    )
            except subprocess.TimeoutExpired as error:
                self._stop_owned_process(process)
                raise MediaToolsError(
                    "FFmpeg ou ffprobe não concluiu a operação no tempo esperado."
                ) from error

            self._raise_if_cancelled()
            return subprocess.CompletedProcess(
                command,
                process.returncode,
                stdout or "",
                stderr or "",
            )
        except MediaToolsError:
            raise
        except OSError as error:
            raise MediaToolsError(
                _classify_os_error(error, executable=Path(command[0]).name)
            ) from error
        finally:
            if process is not None:
                self._release_finished_process(process)

    def _collect_progress(
        self,
        process: subprocess.Popen[str],
        on_progress: Callable[[MediaConversionProgress], None],
        total_duration: float | None,
    ) -> tuple[str, str]:
        """Drena stderr em paralelo e lê o protocolo estável de -progress."""

        if process.stdout is None or process.stderr is None:
            raise MediaToolsError("Não foi possível acompanhar a conversão de mídia.")
        errors: list[str] = []
        error_reader = threading.Thread(
            target=lambda: errors.append(process.stderr.read()),
            name="edudownloader-media-stderr",
            daemon=True,
        )
        reader_started = False
        fields: dict[str, str] = {}
        try:
            try:
                error_reader.start()
            except (OSError, RuntimeError) as error:
                raise MediaToolsError(
                    "Não foi possível acompanhar a conversão de mídia."
                ) from error
            reader_started = True
            for line in process.stdout:
                key, separator, value = line.strip().partition("=")
                if not separator:
                    continue
                fields[key] = value
                if key == "progress":
                    elapsed = _progress_seconds(fields)
                    if elapsed is not None and not self._cancellation_requested():
                        on_progress(MediaConversionProgress(elapsed, total_duration))
                    fields.clear()
            process.wait()
        except Exception:
            self._stop_owned_process(process)
            raise
        finally:
            if reader_started:
                error_reader.join(timeout=PROCESS_SHUTDOWN_TIMEOUT_SECONDS)
            process.stdout.close()
            process.stderr.close()
        if error_reader.is_alive():
            raise MediaToolsError("Não foi possível ler o resultado da conversão.")
        return "", "".join(errors)

    def _stop_owned_process(self, process: subprocess.Popen[str]) -> None:
        with self._process_lock:
            if process.poll() is not None:
                return
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=PROCESS_SHUTDOWN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=PROCESS_SHUTDOWN_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired as error:
                    raise MediaToolsError(
                        "Não foi possível confirmar o encerramento do processo de mídia."
                    ) from error
            if process.poll() is None:
                raise MediaToolsError(
                    "Não foi possível confirmar o encerramento do processo de mídia."
                )

    def _release_finished_process(self, process: subprocess.Popen[str]) -> None:
        with self._process_lock:
            if self._active_process is process and process.poll() is not None:
                self._active_process = None
                if self._operation_worker_finished:
                    self._operation_active = False

    def _validate_mp3(self, path: Path, tools: MediaToolPaths) -> float:
        self._raise_if_cancelled()
        if not path.is_file() or path.stat().st_size < 1:
            raise MediaToolsError("O MP3 gerado está vazio ou não pôde ser validado.")

        probe = self._run_command(
            build_mp3_probe_command(tools, path),
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
        self._raise_if_cancelled()
        return _validate_mp3_probe(probe)

    def _publish_output(
        self,
        temporary_path: Path,
        output_path: Path,
        *,
        overwrite: bool,
    ) -> None:
        with self._process_lock:
            self._raise_if_cancelled()
            if output_path.exists() and not overwrite:
                raise MediaToolsError(
                    "O arquivo MP3 de destino já existe e não foi substituído."
                )
            if overwrite:
                os.replace(temporary_path, output_path)
            elif os.name != "nt":
                # rename substitui destinos no POSIX: link publica sem sobrescrever
                # um arquivo criado por outra operação depois da checagem acima.
                # O finally da conversão remove o nome temporário após publicar.
                os.link(temporary_path, output_path)
            else:
                os.rename(temporary_path, output_path)
            self._output_published = True


def _validate_video_input(value: Path | str) -> Path:
    path = Path(value)
    if path.suffix.casefold() not in SUPPORTED_VIDEO_SUFFIXES or not path.is_file():
        raise MediaToolsError("Selecione um arquivo de vídeo compatível e disponível.")
    return path


def _validate_segment_times(start: object, end: object) -> tuple[float, float]:
    values: list[float] = []
    for value in (start, end):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MediaToolsError(
                "Informe início e fim como segundos numéricos válidos."
            )
        try:
            number = float(value)
        except OverflowError:
            raise MediaToolsError(
                "Informe início e fim como segundos numéricos válidos."
            ) from None
        if not math.isfinite(number):
            raise MediaToolsError(
                "Informe início e fim como segundos numéricos válidos."
            )
        values.append(number)
    start_seconds, end_seconds = values
    if start_seconds < 0 or end_seconds <= start_seconds:
        raise MediaToolsError(
            "O início deve ser zero ou positivo e o fim deve ser maior que o início."
        )
    return start_seconds, end_seconds


def _validate_mp3_output(value: Path | str, source: Path, overwrite: bool) -> Path:
    output = Path(value)
    if output.suffix.casefold() != ".mp3":
        raise MediaToolsError("O arquivo de saída deve usar a extensão .mp3.")
    if _same_path(output, source):
        raise MediaToolsError("O destino não pode substituir o vídeo original.")
    if not output.parent.is_dir():
        raise MediaToolsError("A pasta de destino não está disponível.")
    if output.exists() and not overwrite:
        raise MediaToolsError(
            "O arquivo MP3 de destino já existe e não foi substituído."
        )
    return output


def _validate_media_tools(base_dir: Path | None) -> MediaToolPaths:
    tools = locate_media_tools(base_dir)
    if not tools.ffmpeg.is_file():
        raise MediaToolsError("ffmpeg.exe não foi encontrado na pasta do aplicativo.")
    if not tools.ffprobe.is_file():
        raise MediaToolsError("ffprobe.exe não foi encontrado na pasta do aplicativo.")
    return tools


def _validate_mp3_probe(probe: subprocess.CompletedProcess[str]) -> float:
    if probe.returncode != 0:
        raise MediaToolsError("O MP3 gerado não pôde ser validado pelo ffprobe.")
    try:
        payload = json.loads(probe.stdout)
        streams = payload.get("streams", [])
        stream_types = [stream.get("codec_type") for stream in streams]
        duration_values = [payload.get("format", {}).get("duration")]
        duration_values.extend(stream.get("duration") for stream in streams)
        duration = next(
            (
                value
                for raw_value in duration_values
                if (value := _positive_float(raw_value)) is not None
            ),
            None,
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        raise MediaToolsError("O MP3 gerado possui informações inválidas.") from None
    if "audio" not in stream_types:
        raise MediaToolsError("O resultado não contém uma faixa de áudio válida.")
    if "video" in stream_types:
        raise MediaToolsError("O resultado contém vídeo e foi rejeitado.")
    if duration is None:
        raise MediaToolsError("O MP3 gerado não possui duração válida.")
    return duration


def _validate_video_probe(probe: subprocess.CompletedProcess[str]) -> float | None:
    if probe.returncode != 0:
        raise MediaToolsError("O vídeo selecionado não pôde ser analisado.")
    try:
        payload = json.loads(probe.stdout)
        streams = payload.get("streams", [])
        audio_streams = [
            stream for stream in streams if stream.get("codec_type") == "audio"
        ]
        if not audio_streams:
            raise MediaToolsError(
                "Este vídeo não possui uma faixa de áudio que possa ser convertida."
            )
        values = [payload.get("format", {}).get("duration")]
        values.extend(stream.get("duration") for stream in audio_streams)
        return next(
            (duration for value in values if (duration := _positive_float(value))),
            None,
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        raise MediaToolsError(
            "O vídeo selecionado possui informações inválidas."
        ) from None


def _progress_seconds(fields: dict[str, str]) -> float | None:
    """FFmpeg informa out_time_us em microssegundos no protocolo -progress."""

    microseconds = _positive_float(fields.get("out_time_us"))
    if microseconds is not None:
        return microseconds / 1_000_000
    timestamp = fields.get("out_time")
    if not timestamp:
        return None
    try:
        hours, minutes, seconds = timestamp.split(":", 2)
        return _positive_float(int(hours) * 3600 + int(minutes) * 60 + float(seconds))
    except (ValueError, TypeError):
        return None


def _classify_ffmpeg_failure(stderr: str) -> str:
    lowered = stderr.casefold()
    no_audio_markers = (
        "matches no streams",
        "does not contain any stream",
        "stream map '0:a:0'",
    )
    if any(marker in lowered for marker in no_audio_markers):
        return "O vídeo selecionado não possui uma faixa de áudio utilizável."
    return "O vídeo é incompatível ou a conversão para MP3 falhou."


def _classify_os_error(error: OSError, *, executable: str | None = None) -> str:
    if error.errno == errno.ENOEXEC or getattr(error, "winerror", None) == 193:
        name = (
            executable
            if executable in {"ffmpeg.exe", "ffprobe.exe"}
            else "A ferramenta"
        )
        return f"{name} não pôde ser executado e pode estar corrompido."
    if error.errno == errno.ENOSPC:
        return "Não há espaço suficiente para criar o arquivo MP3."
    if error.errno in {errno.EACCES, errno.EPERM}:
        return "Sem permissão para ler o vídeo ou gravar o arquivo MP3."
    if error.errno == errno.ENOENT:
        return "FFmpeg ou ffprobe não está disponível para executar a conversão."
    return "Não foi possível acessar o vídeo ou gravar o arquivo MP3."


def _positive_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _same_path(first: Path, second: Path) -> bool:
    try:
        return first.samefile(second)
    except (FileNotFoundError, OSError):
        return os.path.normcase(os.path.abspath(first)) == os.path.normcase(
            os.path.abspath(second)
        )
