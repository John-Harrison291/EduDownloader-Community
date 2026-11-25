"""Pinned offline OCR component, bounded subprocesses and generated PNM input.

Never downloads, installs, changes PATH, or opens a source PDF. Only the
converter's own raster copies reach the engines. The optional Windows bridge
uses a fixed, noninteractive PowerShell command with no user data as code.
"""

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import hashlib
import math
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import time

from paths import get_app_dir, get_bundled_components_dir

COMMUNITY_ENGINE_SHA256 = (
    "95b889b9e5000d6f362348508b961a9be282c7f2facaf280b6ff8c9826188572"
)
MODEL_SHA256 = {
    ("fast", "por"): "c4932b937207a9514b7514d518b931a99938c02a28a5a5a553f8599ed58b7deb",
    ("best", "por"): "711de9dbb8052067bd42f16b9119967f30bada80d57e2ef24f65d09f531adb04",
    ("fast", "osd"): "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff",
}
MAX_BATCH_PIXELS = 20_000_000
MAX_BATCH_IMAGES = 96
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_OCR_WORDS = 50_000
PROCESS_MEMORY_BYTES = 512 * 1024 * 1024
DEFAULT_TIMEOUT = 90.0


class OcrUnavailable(RuntimeError):
    pass


class OcrFailure(RuntimeError):
    def __init__(self, code="failed"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OcrWord:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float | None
    block: int
    paragraph: int
    line: int


@dataclass(frozen=True)
class OcrBatch:
    pages: tuple[tuple[OcrWord, ...], ...]
    seconds: float
    peak_memory_bytes: int
    engine: str = "tesseract"


class _ProcessBudget:
    """Windows job: only our child, one process, hard memory ceiling, kill on close."""

    def __init__(self, process):
        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("min_working", ctypes.c_size_t),
                ("max_working", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Io(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "reads",
                    "writes",
                    "other",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", Io),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t),
            ]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        self.kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        self.info = Extended()
        self.info.basic.flags = 0x2000 | 0x100 | 0x8
        self.info.basic.active = 1
        self.info.process_memory = PROCESS_MEMORY_BYTES
        if not self.handle:
            raise OcrFailure("process-budget")
        if not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(self.info), ctypes.sizeof(self.info)
        ) or not self.kernel.AssignProcessToJobObject(
            self.handle, int(process._handle)
        ):
            self.close()
            raise OcrFailure("process-budget")

    def peak(self):
        if self.handle and self.kernel.QueryInformationJobObject(
            self.handle, 9, ctypes.byref(self.info), ctypes.sizeof(self.info), None
        ):
            return self.info.peak_process_memory
        return 0

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def bundled_ocr_directory(base_dir=None) -> Path:
    from_source = not getattr(sys, "frozen", False)
    return get_bundled_components_dir(base_dir) / (
        "OCR-Community" if from_source else "OCR"
    )


class OcrRuntime:
    def __init__(self, root=None, *, prefer_windows=True):
        self._managed_root = root is None
        self.root = Path(root) if root is not None else bundled_ocr_directory()
        self._engine_sha256 = COMMUNITY_ENGINE_SHA256
        self._verified = {}
        self._windows_available = None if prefer_windows else False

    def recognize_windows(self, image, digital_boxes, *, cancel=lambda: None):
        from pdf_ocr_windows import recognize

        try:
            return recognize(self, image, digital_boxes, cancel)
        except (OcrFailure, OSError, ValueError, TypeError, KeyError):
            self._windows_available = False
            return None

    def _verified_file(self, relative, expected):
        path = self.root / relative
        try:
            if (
                self.root.is_symlink()
                or self.root.is_junction()
                or any(p.is_symlink() or p.is_junction() for p in (path, path.parent))
            ):
                raise OcrUnavailable("component path")
            if not path.resolve(strict=True).is_relative_to(
                self.root.resolve(strict=True)
            ):
                raise OcrUnavailable("component containment")
            stat = path.stat()
            stamp = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
            if not path.is_file() or not 0 < stat.st_size <= 32 * 1024 * 1024:
                raise OcrUnavailable("component size")
            if self._verified.get(relative) != stamp:
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != expected:
                    raise OcrUnavailable("component integrity")
                self._verified[relative] = stamp
        except OSError as error:
            raise OcrUnavailable("component missing") from error
        return path

    def _component(self, family="fast", language="por"):
        if os.name != "nt" or (family, language) not in MODEL_SHA256:
            raise OcrUnavailable("unsupported component")
        if self._managed_root:
            from component_runtime import active_ocr

            managed = active_ocr(get_app_dir())
            if managed is not None:
                return managed[0] / "tesseract.exe", managed[0] / f"tessdata_{family}"
        executable = self._verified_file("tesseract.exe", self._engine_sha256)
        data = f"tessdata_{family}/{language}.traineddata"
        self._verified_file(data, MODEL_SHA256[family, language])
        return executable, self.root / f"tessdata_{family}"

    def available(self):
        try:
            self._component()
        except OcrUnavailable:
            return False
        return True

    def all_models_available(self) -> bool:
        try:
            for family, language in MODEL_SHA256:
                self._component(family, language)
        except OcrUnavailable:
            return False
        return True

    def _run(self, arguments, directory, cancel, timeout):
        if not math.isfinite(timeout) or not 0 < timeout <= 180:
            raise OcrFailure("timeout-limit")
        cancel()
        started = time.monotonic()
        process = budget = None
        try:
            process = subprocess.Popen(
                arguments,
                cwd=directory,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            )
            budget = _ProcessBudget(process)
            while process.poll() is None:
                cancel()
                if time.monotonic() - started > timeout:
                    raise OcrFailure("timeout")
                try:
                    process.wait(timeout=0.05)
                except subprocess.TimeoutExpired:
                    pass
            cancel()
            if process.returncode:
                raise OcrFailure("engine")
            return budget.peak()
        except OSError as error:
            raise OcrFailure("start") from error
        finally:
            try:
                if process is not None and process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        if process.poll() is None:
                            raise
                    process.wait(timeout=3)
            finally:
                if budget is not None:
                    budget.close()

    def orientation(self, image, *, cancel=lambda: None):
        """Clockwise correction and confidence, or None for insufficient evidence."""
        if not 0 < image.width * image.height <= MAX_BATCH_PIXELS:
            raise OcrFailure("input-limit")
        executable, data = self._component("fast", "osd")
        with tempfile.TemporaryDirectory(prefix="edudownloader-ocr-") as temp:
            directory = Path(temp)
            with image.convert("L") as gray:
                gray.save(directory / "orientation.pgm", format="PPM")
            try:
                self._run(
                    [
                        str(executable),
                        "orientation.pgm",
                        "direction",
                        "--tessdata-dir",
                        str(data),
                        "-l",
                        "osd",
                        "--psm",
                        "0",
                        "--dpi",
                        "300",
                    ],
                    directory,
                    cancel,
                    30,
                )
            except OcrFailure as error:
                if error.code == "engine":
                    return None
                raise
            path = directory / "direction.osd"
            if not path.is_file() or path.stat().st_size > 8192:
                return None
            values = dict(
                line.split(": ", 1)
                for line in path.read_text("utf-8").splitlines()
                if ": " in line
            )
            try:
                angle = int(values["Rotate"])
                confidence = float(values["Orientation confidence"])
            except (KeyError, ValueError):
                return None
            return (
                (angle, confidence)
                if angle in (0, 90, 180, 270) and math.isfinite(confidence)
                else None
            )

    def recognize(
        self,
        images,
        *,
        family="fast",
        psm=6,
        cancel=lambda: None,
        timeout=DEFAULT_TIMEOUT,
    ):
        if (
            psm not in (3, 6, 7, 11)
            or not 0 < len(images) <= MAX_BATCH_IMAGES
            or any(im.width <= 0 or im.height <= 0 for im in images)
            or sum(im.width * im.height for im in images) > MAX_BATCH_PIXELS
        ):
            raise OcrFailure("input-limit")
        executable, data = self._component(family)
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="edudownloader-ocr-") as temp:
            directory = Path(temp)
            paths = []
            for index, image in enumerate(images):
                cancel()
                path = directory / f"region-{index:03}.pgm"
                with image.convert("L") as gray:
                    gray.save(path, format="PPM")
                paths.append(Path(path.name))
            source = directory / "regions.txt"
            source.write_text("\n".join(map(str, paths)) + "\n", encoding="utf-8")
            target = directory / "recognized"
            arguments = [
                str(executable),
                str(source),
                str(target),
                "--tessdata-dir",
                str(data),
                "-l",
                "por",
                "--oem",
                "1",
                "--psm",
                str(psm),
                "--dpi",
                "300",
                "-c",
                "tessedit_create_tsv=1",
                "-c",
                "tessedit_create_txt=0",
            ]
            peak = self._run(arguments, directory, cancel, timeout)
            output = target.with_suffix(".tsv")
            if not output.exists() or not 0 < output.stat().st_size <= MAX_OUTPUT_BYTES:
                raise OcrFailure("output-limit")
            text = output.read_text(encoding="utf-8")
            pages = parse_tsv(text, tuple(image.size for image in images), cancel)
        return OcrBatch(pages, time.perf_counter() - started, peak)


def parse_tsv(text, sizes, cancel=lambda: None):
    pages = [[] for _ in sizes]
    for number, line in enumerate(text.splitlines()[1:]):
        if number % 64 == 0:
            cancel()
        if number > MAX_OCR_WORDS * 3:
            raise OcrFailure("word-limit")
        fields = line.split("\t", 11)
        if len(fields) != 12 or fields[0] != "5" or not fields[11].strip():
            continue
        try:
            page, block, paragraph, row, _word, left, top, width, height = map(
                int, fields[1:10]
            )
            confidence = float(fields[10])
            image_width, image_height = sizes[page - 1]
            valid = (
                1 <= page <= len(pages)
                and 0 <= left < left + width <= image_width
                and 0 <= top < top + height <= image_height
                and math.isfinite(confidence)
                and 0 <= confidence <= 100
                and len(fields[11]) <= 512
            )
        except (ValueError, IndexError) as error:
            raise OcrFailure("invalid-output") from error
        if not valid:
            raise OcrFailure("invalid-output")
        pages[page - 1].append(
            OcrWord(
                fields[11], left, top, width, height, confidence, block, paragraph, row
            )
        )
    if sum(map(len, pages)) > MAX_OCR_WORDS:
        raise OcrFailure("word-limit")
    return tuple(tuple(page) for page in pages)
