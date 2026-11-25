"""Local video frames, bounded native work, no exports or persistent files."""

from io import BytesIO
import json
import math
from pathlib import Path
import subprocess
import time

from PIL import Image, ImageStat

from constants import FFMPEG_FILENAME, FFPROBE_FILENAME
from component_transactions import ComponentBusyError
from component_runtime import active_component, component_use
from paths import get_app_dir, get_tool_path
from file_preview import (
    FilePreviewResult,
    PreviewKind,
    PreviewStatus,
    PreviewCancelled,
    preview_checkpoint,
    _rgba_preview,
)

VIDEO_TIMEOUT = 10.0
DEMUXERS = {
    ".mp4": "mov",
    ".m4v": "mov",
    ".mov": "mov",
    ".mkv": "matroska",
    ".webm": "matroska",
    ".avi": "avi",
}


def _run(command, cancel, deadline, *, max_bytes):
    preview_checkpoint(cancel)
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        while True:
            preview_checkpoint(cancel)
            if time.monotonic() >= deadline:
                raise TimeoutError
            try:
                output, _ = process.communicate(
                    timeout=min(0.05, max(0.001, deadline - time.monotonic()))
                )
                if process.returncode or len(output) > max_bytes:
                    raise ValueError("Invalid local frame")
                return output
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=0.2)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=2)
        if process.stdout is not None:
            process.stdout.close()


def preview_video(path: Path, media_dir=None, cancel=None):
    demuxer = DEMUXERS.get(path.suffix.casefold())
    if not demuxer:
        return FilePreviewResult(
            PreviewStatus.UNSUPPORTED, message="Formato de vídeo sem prévia local."
        )
    try:
        with component_use(media_dir or get_app_dir(), "ffmpeg-ffprobe"):
            return _preview_video(path, demuxer, media_dir, cancel)
    except (ComponentBusyError, OSError, ValueError):
        return FilePreviewResult(
            PreviewStatus.UNAVAILABLE,
            message="Ferramentas de vídeo indisponíveis. Tente novamente ou use Abrir.",
        )


def _preview_video(path, demuxer, media_dir, cancel):
    managed = active_component(media_dir or get_app_dir(), "ffmpeg-ffprobe")
    ffmpeg, ffprobe = (
        (managed[0] / FFMPEG_FILENAME, managed[0] / FFPROBE_FILENAME)
        if managed
        else (
            get_tool_path(FFMPEG_FILENAME, media_dir),
            get_tool_path(FFPROBE_FILENAME, media_dir),
        )
    )
    if not ffmpeg.is_file() or not ffprobe.is_file():
        return FilePreviewResult(
            PreviewStatus.UNAVAILABLE,
            message="Componentes de vídeo indisponíveis. Use Abrir.",
        )
    deadline = time.monotonic() + VIDEO_TIMEOUT
    # Explicit demuxer prevents a renamed network playlist being interpreted.
    source = [
        "-protocol_whitelist",
        "file,pipe",
        "-f",
        demuxer,
        "-max_alloc",
        "33554432",
        "-probesize",
        "4194304",
        "-analyzeduration",
        "2000000",
    ]
    if demuxer == "mov":
        source += ["-enable_drefs", "0", "-use_absolute_path", "0"]
    best = None
    try:
        info = json.loads(
            _run(
                [
                    str(ffprobe),
                    "-v",
                    "error",
                    *source,
                    "-select_streams",
                    "V:0",
                    "-show_entries",
                    "stream=width,height,duration:format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                cancel,
                deadline,
                max_bytes=8192,
            )
        )
        stream = info.get("streams", [])[0]
        width, height = int(stream["width"]), int(stream["height"])
        if (
            min(width, height) < 1
            or max(width, height) > 16384
            or width * height > 40_000_000
        ):
            raise ValueError("Frame dimensions exceed preview limit")
        raw_duration = info.get("format", {}).get("duration", stream.get("duration", 0))
        duration = 0.0 if raw_duration in (None, "N/A", "") else float(raw_duration)
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("Invalid duration")
        positions = (
            (min(duration * 0.1, 30), min(duration * 0.5, 90), 0)
            if duration
            else (1, 0)
        )
        best_score = -1
        for position in dict.fromkeys(positions):
            preview_checkpoint(cancel)
            try:
                payload = _run(
                    [
                        str(ffmpeg),
                        "-v",
                        "error",
                        "-nostdin",
                        "-threads",
                        "1",
                        "-filter_threads",
                        "1",
                        *source,
                        "-ss",
                        f"{position:.3f}",
                        "-i",
                        str(path),
                        "-map",
                        "0:V:0",
                        "-an",
                        "-sn",
                        "-dn",
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=w='max(1,min(512,512*dar))':h='max(1,min(512,512/dar))',setsar=1",
                        "-threads",
                        "1",
                        "-f",
                        "image2pipe",
                        "-vcodec",
                        "ppm",
                        "pipe:1",
                    ],
                    cancel,
                    deadline,
                    max_bytes=1024 * 1024,
                )
                with (
                    BytesIO(payload) as data,
                    Image.open(data, formats=("PPM",)) as frame,
                ):
                    if frame.width > 512 or frame.height > 512:
                        raise ValueError("Unexpected raster")
                    frame.load()
                    # Prefer a visible frame; try alternatives for black intros.
                    with frame.convert("L") as gray:
                        stats = ImageStat.Stat(gray)
                        score = stats.mean[0] + stats.stddev[0]
                    candidate = _rgba_preview(frame, PreviewKind.VIDEO_FRAME)
                if score > best_score:
                    best, best_score = candidate, score
                if score >= 12:
                    break
            except TimeoutError:
                raise
            except (ValueError, OSError):
                continue
        return best or FilePreviewResult(
            PreviewStatus.INVALID,
            message="Nenhum quadro legível neste vídeo. Use Abrir.",
        )
    except PreviewCancelled:
        raise
    except TimeoutError:
        return FilePreviewResult(
            PreviewStatus.UNAVAILABLE,
            message="O vídeo demorou demais para a prévia. Use Abrir.",
        )
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return FilePreviewResult(
            PreviewStatus.INVALID,
            message="Não foi possível ler um quadro deste vídeo. Use Abrir.",
        )
