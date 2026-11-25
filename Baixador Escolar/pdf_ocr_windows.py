"""Optional Windows inbox Portuguese OCR; no downloads or policy changes.

The verified portable Tesseract component remains the prerequisite/fallback.
Only a generated, digitally masked PNG and fixed script enter the OS process.
Microsoft formally supports this desktop API with package identity. This
opportunistic adapter may be unavailable in a portable distribution; failure
is cached and the verified Tesseract path remains fully independent.
"""

import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import tempfile
import time

from PIL import ImageDraw

SCRIPT = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$ocrType=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
$awaitMethod=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
 $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
 $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and
 $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function AwaitResult($operation,[Type]$type){
 $task=$awaitMethod.MakeGenericMethod($type).Invoke($null,@($operation))
 if(-not $task.Wait(25000)){throw 'OCR timeout'}
 return $task.Result
}
$engine=$ocrType::TryCreateFromLanguage([Windows.Globalization.Language]::new('pt-BR'))
if($null -eq $engine){
 [IO.File]::WriteAllText((Join-Path $pwd 'recognized.json'),'{}')
 exit 0
}
$stream=$bitmap=$null
try {
 $file=AwaitResult ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Join-Path $pwd 'page.png'))) ([Windows.Storage.StorageFile])
 $stream=AwaitResult ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
 $decoder=AwaitResult ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
 $bitmap=AwaitResult ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,[Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)) ([Windows.Graphics.Imaging.SoftwareBitmap])
 if($bitmap.PixelWidth -gt $ocrType::MaxImageDimension -or $bitmap.PixelHeight -gt $ocrType::MaxImageDimension){throw 'OCR dimensions'}
 $result=AwaitResult ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
 $lines=@($result.Lines | ForEach-Object {
  ,@($_.Words | ForEach-Object {
    [ordered]@{text=$_.Text;x=$_.BoundingRect.X;y=$_.BoundingRect.Y;width=$_.BoundingRect.Width;height=$_.BoundingRect.Height}
  })
 })
 [IO.File]::WriteAllText((Join-Path $pwd 'recognized.json'),([ordered]@{lines=$lines} | ConvertTo-Json -Depth 7))
} finally {
 if($null -ne $bitmap){$bitmap.Dispose()}
 if($null -ne $stream){$stream.Dispose()}
}
"""


def system_powershell():
    if os.name != "nt":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetWindowsDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel.GetWindowsDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    count = kernel.GetWindowsDirectoryW(buffer, len(buffer))
    if not 0 < count < len(buffer):
        return None
    path = Path(buffer.value) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return path if path.is_file() else None


def recognize(runtime, image, digital_boxes, cancel):
    from pdf_ocr_runtime import OcrBatch, OcrWord, OcrFailure

    if runtime._windows_available is False:
        return None
    executable = system_powershell()
    if executable is None:
        runtime._windows_available = False
        return None
    started = time.perf_counter()
    if not 0 < image.width * image.height <= 20_000_000:
        raise OcrFailure("input-limit")
    with tempfile.TemporaryDirectory(prefix="edudownloader-ocr-windows-") as temp:
        directory = Path(temp)
        with image.convert("L") as gray:
            draw = ImageDraw.Draw(gray)
            for left, top, right, bottom in digital_boxes:
                cancel()
                draw.rectangle((left - 2, top - 2, right + 2, bottom + 2), fill=255)
            gray.thumbnail((2500, 2500))
            width, height = gray.size
            gray.save(directory / "page.png", "PNG")
        # Fixed literal command; neither user text nor paths become script code.
        peak = runtime._run(
            [str(executable), "-NoProfile", "-NonInteractive", "-Command", SCRIPT],
            directory,
            cancel,
            40,
        )
        output = directory / "recognized.json"
        if not output.is_file() or not 0 < output.stat().st_size <= 8 * 1024 * 1024:
            raise OcrFailure("output-limit")
        data = json.loads(output.read_text("utf-8-sig"))
        if not isinstance(data, dict):
            raise OcrFailure("invalid-output")
        if data == {}:
            runtime._windows_available = False
            return None
        lines = data.get("lines")
        if not isinstance(lines, list) or len(lines) > 10_000:
            raise OcrFailure("invalid-output")
        words = []
        sx, sy = image.width / width, image.height / height
        for index, line in enumerate(lines):
            cancel()
            if not isinstance(line, list):
                raise OcrFailure("invalid-output")
            for word in line:
                if not isinstance(word, dict):
                    raise OcrFailure("invalid-output")
                text = word.get("text")
                values = [word.get(key) for key in ("x", "y", "width", "height")]
                if (
                    not isinstance(text, str)
                    or len(text) > 512
                    or not all(
                        isinstance(v, (int, float)) and math.isfinite(v) for v in values
                    )
                ):
                    raise OcrFailure("invalid-output")
                x, y, ww, hh = values
                if not (0 <= x < x + ww <= width + 1 and 0 <= y < y + hh <= height + 1):
                    raise OcrFailure("invalid-output")
                words.append(
                    OcrWord(
                        text, x * sx, y * sy, ww * sx, hh * sy, None, 1, 1, index + 1
                    )
                )
                if len(words) > 50_000:
                    raise OcrFailure("word-limit")
        runtime._windows_available = True
    return OcrBatch((tuple(words),), time.perf_counter() - started, peak, "windows-ocr")
