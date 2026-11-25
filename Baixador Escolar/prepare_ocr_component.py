"""Explicit maintainer preparation of the offline Windows x64 OCR component.

Not imported or launched by conversion. Uses pinned sources/tools, never a
global installation. No application executable or installer is rebuilt here.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

MANIFEST = Path(__file__).with_name("ocr_community_sources.json")
UTF8_MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="EduDownloader.OfflineOCR" version="1.0.0.0" processorArchitecture="amd64"/>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo>
  <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>
    <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
  </windowsSettings></application>
</assembly>
"""


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def obtain(entry, cache, download):
    target = cache / entry["name"]
    if not target.exists():
        if not download:
            raise RuntimeError(
                f"Missing verified cache file: {entry['name']}; explicit --download required"
            )
        temporary = target.with_suffix(target.suffix + ".part")
        if temporary.exists():
            raise RuntimeError("Existing partial download preserved")
        try:
            request = urllib.request.Request(
                entry["url"], headers={"User-Agent": "EduDownloader-OCR-maintainer"}
            )
            with (
                urllib.request.urlopen(request, timeout=180) as response,
                temporary.open("xb") as stream,
            ):
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > entry["bytes"]:
                        raise RuntimeError("Download size limit")
                    stream.write(chunk)
            if digest(temporary) != entry["sha256"]:
                raise RuntimeError("Download integrity mismatch")
            temporary.rename(target)
        finally:
            temporary.unlink(missing_ok=True)
    if target.stat().st_size != entry["bytes"] or digest(target) != entry["sha256"]:
        raise RuntimeError(f"Cache integrity mismatch: {entry['name']}")
    return target


def extract(source, destination):
    if destination.exists():
        raise RuntimeError("Build workspace must be new")
    destination.mkdir()
    with zipfile.ZipFile(source) as archive:
        if sum(item.file_size for item in archive.infolist()) > 2_000_000_000:
            raise RuntimeError("Archive size limit")
        for item in archive.infolist():
            if (
                not (destination / item.filename)
                .resolve()
                .is_relative_to(destination.resolve())
                or ((item.external_attr >> 16) & 0o170000) == 0o120000
            ):
                raise RuntimeError("Archive path")
        archive.extractall(destination)


def prepare(cache, workspace, destination, download=False, *, manifest_path=MANIFEST):
    if os.name != "nt":
        raise RuntimeError("Windows x64 build required")
    cache, workspace, destination = (
        Path(p).resolve() for p in (cache, workspace, destination)
    )
    if (
        destination.exists()
        or workspace.exists()
        or workspace == destination
        or workspace.is_relative_to(destination)
        or destination.is_relative_to(workspace)
    ):
        raise RuntimeError("Use distinct, new workspace and destination directories")
    cache.mkdir(parents=True, exist_ok=True)
    manifest_bytes = manifest_path.read_text("utf-8").encode("utf-8")
    manifest = json.loads(manifest_bytes)
    archives = {
        item["name"]: obtain(item, cache, download) for item in manifest["archives"]
    }
    models = {
        item["name"]: obtain(item, cache, download) for item in manifest["models"]
    }
    workspace.mkdir(parents=True)
    for name in ("llvm", "cmake", "ninja", "leptonica", "tesseract"):
        extract(
            archives[name + (".whl" if name in ("cmake", "ninja") else ".zip")],
            workspace / name,
        )
    llvm = next((workspace / "llvm").glob("llvm-mingw-*")) / "bin"
    cmake = workspace / "cmake/cmake/data/bin/cmake.exe"
    ninja = next((workspace / "ninja").rglob("ninja.exe"))
    prefix = workspace / "prefix"
    env = {
        **os.environ,
        "SOURCE_DATE_EPOCH": "1735689600",
        "PATH": str(llvm) + ";" + os.environ["PATH"],
    }

    def run(label, arguments):
        with (workspace / (label + ".log")).open("w", encoding="utf-8") as log:
            subprocess.run(
                [str(arg) for arg in arguments],
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=1800,
                check=True,
            )
        print(label, flush=True)

    (workspace / "utf8.manifest").write_text(UTF8_MANIFEST, "utf-8")
    (workspace / "utf8.rc").write_text('1 24 "utf8.manifest"\n', "utf-8")
    resource = workspace / "utf8.o"
    run(
        "utf8-resource",
        [
            llvm / "x86_64-w64-mingw32-windres.exe",
            "utf8.rc",
            "-O",
            "coff",
            "-o",
            resource,
        ],
    )
    flags = f'-D_USE_MATH_DEFINES -ffile-prefix-map="{workspace.as_posix()}=/ocr-build"'
    common = [
        "-G",
        "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={ninja}",
        f"-DCMAKE_C_COMPILER={llvm / 'x86_64-w64-mingw32-clang.exe'}",
        f"-DCMAKE_CXX_COMPILER={llvm / 'x86_64-w64-mingw32-clang++.exe'}",
        f"-DCMAKE_INSTALL_PREFIX={prefix}",
        f"-DCMAKE_PREFIX_PATH={prefix}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
        f"-DCMAKE_C_FLAGS={flags}",
        f"-DCMAKE_CXX_FLAGS={flags}",
        f'-DCMAKE_EXE_LINKER_FLAGS=-static -Wl,--no-insert-timestamp -s "{resource.as_posix()}"',
    ]
    lept = next((workspace / "leptonica").glob("leptonica-*"))
    tess = next((workspace / "tesseract").glob("tesseract-*"))
    run(
        "leptonica-configure",
        [
            cmake,
            "-S",
            lept,
            "-B",
            workspace / "build-lept",
            *common,
            "-DSW_BUILD=OFF",
            "-DBUILD_PROG=OFF",
            *[
                f"-DENABLE_{codec}=OFF"
                for codec in ("ZLIB", "PNG", "JPEG", "TIFF", "GIF", "WEBP", "OPENJPEG")
            ],
        ],
    )
    run(
        "leptonica-build",
        [cmake, "--build", workspace / "build-lept", "--parallel", "4"],
    )
    run("leptonica-install", [cmake, "--install", workspace / "build-lept"])
    run(
        "tesseract-configure",
        [
            cmake,
            "-S",
            tess,
            "-B",
            workspace / "build-tess",
            *common,
            "-DBUILD_TRAINING_TOOLS=OFF",
            "-DBUILD_TESTS=OFF",
            "-DGRAPHICS_DISABLED=ON",
            "-DOPENMP_BUILD=OFF",
            "-DDISABLE_TIFF=ON",
            "-DDISABLE_ARCHIVE=ON",
            "-DDISABLE_CURL=ON",
            "-DENABLE_NATIVE=OFF",
            "-DENABLE_LTO=OFF",
            "-DENABLE_UNITY_BUILD=ON",
            "-DENABLE_CCACHE=OFF",
        ],
    )
    run(
        "tesseract-build",
        [
            cmake,
            "--build",
            workspace / "build-tess",
            "--target",
            "tesseract",
            "--parallel",
            "4",
        ],
    )
    executable = workspace / "build-tess/bin/tesseract.exe"
    if digest(executable) != manifest["engine_sha256"]:
        raise RuntimeError("Reproduced engine does not match the reviewed build")
    destination.mkdir(parents=True)
    shutil.copyfile(executable, destination / "tesseract.exe")
    for item in manifest["models"]:
        output = destination / item["target"]
        output.parent.mkdir(exist_ok=True)
        shutil.copyfile(models[item["name"]], output)
    licenses = destination / "Licenses"
    licenses.mkdir(exist_ok=True)
    for name, source in (
        ("Tesseract-Apache-2.0.txt", tess / "LICENSE"),
        ("Leptonica-BSD.txt", lept / "leptonica-license.txt"),
    ):
        shutil.copyfile(source, licenses / name)
    runtime_licenses = llvm.parent / "x86_64-w64-mingw32/share/mingw32"
    shutil.copyfile(llvm.parent / "LICENSE.TXT", licenses / "LLVM-MinGW-runtime.txt")
    for name in (
        "COPYING.MinGW-w64-runtime.txt",
        "COPYING.MinGW-w64.txt",
        "COPYING.winpthreads.txt",
    ):
        shutil.copyfile(runtime_licenses / name, licenses / name)
    record = {
        "engine_sha256": digest(executable),
        "engine_bytes": executable.stat().st_size,
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "runtime": "Windows 10 1903+ x64 UCRT; UTF-8 process manifest; static PNM-only",
    }
    (destination / "component.json").write_text(json.dumps(record, indent=2), "utf-8")
    print(json.dumps(record), flush=True)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Explicitly permit pinned maintainer downloads",
    )
    args = parser.parse_args()
    prepare(
        args.cache,
        args.workspace,
        args.destination,
        args.download,
    )
