"""Provas funcionais locais antes de disponibilizar binários adquiridos."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from component_catalog import version_key
from yt_dlp_update import UpdateCancelled, UpdateError


def run_probe(
    command: list[str],
    scratch: Path,
    cancel: threading.Event,
    timeout: float = 20,
    *,
    stderr=False,
) -> bytes:
    if cancel.is_set():
        raise UpdateCancelled
    environment = {
        **os.environ,
        "DENO_DIR": str(scratch / "deno-cache"),
        "NO_COLOR": "1",
    }
    with subprocess.Popen(
        command,
        cwd=scratch,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if stderr else subprocess.DEVNULL,
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as process:
        end = time.monotonic() + timeout
        while True:
            try:
                if cancel.is_set():
                    raise UpdateCancelled
                if time.monotonic() >= end:
                    raise UpdateError("component_probe_timed_out")
                output, _ = process.communicate(timeout=0.2)
                if process.returncode or len(output) > 1024 * 1024:
                    raise UpdateError("component_probe_failed")
                return output
            except subprocess.TimeoutExpired:
                continue
            finally:
                if (
                    cancel.is_set() or time.monotonic() >= end
                ) and process.poll() is None:
                    process.kill()
                    process.wait()


def _version(binary: Path, command: str, scratch: Path, cancel: threading.Event):
    lines = run_probe([str(binary), command], scratch, cancel).splitlines()
    first = lines[0] if lines else b""
    match = re.search(rb"\bv?n?(\d+(?:\.\d+){1,3})(?!\d)", first)
    if match is None:
        raise UpdateError("component_version_unreadable")
    return first, version_key(match[1].decode())


def _ffmpeg_version_stamp(banner: bytes) -> bytes:
    tokens = banner.split()
    if len(tokens) < 3 or tokens[1] != b"version":
        raise UpdateError("media_pair_version_unreadable")
    return tokens[2]


def _media(root: Path, scratch: Path, version: str, cancel: threading.Event) -> None:
    ffmpeg, ffprobe = str(root / "ffmpeg.exe"), str(root / "ffprobe.exe")
    first, first_version = _version(Path(ffmpeg), "-version", scratch, cancel)
    second, second_version = _version(Path(ffprobe), "-version", scratch, cancel)
    if (
        first_version != version_key(version)
        or second_version != first_version
        or (_ffmpeg_version_stamp(first) != _ffmpeg_version_stamp(second))
    ):
        raise UpdateError("media_pair_version_mismatch")
    config = [
        tuple(
            line.strip()
            for line in run_probe(
                [path, "-buildconf"], scratch, cancel, stderr=True
            ).splitlines()
            if line.strip().startswith(b"--")
        )
        for path in (ffmpeg, ffprobe)
    ]
    if not config[0] or config[0] != config[1]:
        raise UpdateError("media_pair_configuration_mismatch")
    mp4, mp3, png = (
        str(scratch / name) for name in ("sample.mp4", "sample.mp3", "sample.png")
    )
    common = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
    run_probe(
        [
            *common,
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=160x120:r=8",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            "2",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            mp4,
        ],
        scratch,
        cancel,
    )
    run_probe([*common, "-i", mp4, "-vn", "-c:a", "libmp3lame", mp3], scratch, cancel)
    run_probe(
        [
            *common,
            "-ss",
            "0.25",
            "-i",
            mp4,
            "-t",
            "0.75",
            "-vn",
            "-c:a",
            "libmp3lame",
            str(scratch / "clip.mp3"),
        ],
        scratch,
        cancel,
    )
    run_probe([*common, "-i", mp4, "-frames:v", "1", png], scratch, cancel)
    detail = json.loads(
        run_probe(
            [ffprobe, "-v", "error", "-show_streams", "-of", "json", mp4],
            scratch,
            cancel,
        )
    )
    if {item.get("codec_name") for item in detail.get("streams", [])} != {
        "mpeg4",
        "aac",
    } or (not Path(png).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")):
        raise UpdateError("media_outputs_invalid")


def _ocr(root: Path, scratch: Path, version: str, cancel: threading.Event) -> None:
    from PIL import Image, ImageDraw, ImageFont

    binary = root / "tesseract.exe"
    _, found = _version(binary, "--version", scratch, cancel)
    if found != version_key(version):
        raise UpdateError("component_version_mismatch")
    data = str(root / "tessdata_fast")
    languages = run_probe(
        [str(binary), "--list-langs", "--tessdata-dir", data], scratch, cancel
    )
    if not {b"por", b"osd"}.issubset(set(languages.splitlines())):
        raise UpdateError("ocr_models_missing")
    font = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts/arial.ttf"), 48)
    photo = scratch / "sample.pgm"
    with Image.new("L", (800, 160), "white") as picture:
        ImageDraw.Draw(picture).text(
            (20, 35), "Ciências e educação", fill="black", font=font
        )
        picture.save(photo, format="PPM")
    for model in (data, str(root / "tessdata_best")):
        text = (
            run_probe(
                [
                    str(binary),
                    str(photo),
                    "stdout",
                    "--tessdata-dir",
                    model,
                    "-l",
                    "por",
                    "--psm",
                    "7",
                ],
                scratch,
                cancel,
            )
            .decode("utf-8")
            .strip()
            .casefold()
        )
        if "ciências" not in text or "educação" not in text:
            raise UpdateError("ocr_probe_incompatible")


def verify_component(
    component: str, root: Path, scratch: Path, version: str, cancel: threading.Event
) -> None:
    scratch.mkdir()
    if component == "deno":
        binary = root / "deno.exe"
        _, found = _version(binary, "--version", scratch, cancel)
        if found != version_key(version):
            raise UpdateError("component_version_mismatch")
        if (
            run_probe(
                [str(binary), "eval", "console.log(20 + 22)"], scratch, cancel
            ).strip()
            != b"42"
        ):
            raise UpdateError("deno_javascript_probe_failed")
    elif component == "ffmpeg-ffprobe":
        _media(root, scratch, version, cancel)
    elif component == "ocr":
        _ocr(root, scratch, version, cancel)
    else:
        raise UpdateError("component_probe_unsupported")
