"""Read-only technical Windows diagnostics; no activation or device collection.

PE inspection is an explicit maintainer operation using pefile from the existing
build environment. Its absence is reported as not tested, never as success.
No executable being inventoried is launched. Signatures use Windows APIs only.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from paths import get_app_dir, get_runtime_state_dir
from pdf_ocr_runtime import OcrRuntime, OcrUnavailable, bundled_ocr_directory
from windows_prerequisites import check_vc_runtime, native_architecture
from windows_signing import inspect_signature, SigningError


MAX_NATIVE_FILES = 4096
MAX_FILE_BYTES = 512 * 1024 * 1024


def native_files(root):
    root = Path(root)
    if (
        not root.is_absolute()
        or not root.is_dir()
        or any(p.is_symlink() or p.is_junction() for p in (root, *root.parents))
    ):
        raise ValueError("An ordinary absolute inventory root is required")
    result, visited = [], 0
    for parent, directories, files in os.walk(root, followlinks=False):
        parent = Path(parent)
        directories[:] = [
            name
            for name in directories
            if not (parent / name).is_symlink() and not (parent / name).is_junction()
        ]
        visited += len(files) + len(directories)
        if visited > 100_000:
            raise ValueError("Inventory traversal limit")
        for name in files:
            path = parent / name
            if path.suffix.casefold() in (".exe", ".dll", ".pyd"):
                if path.is_symlink() or path.is_junction():
                    raise ValueError("Native reparse input")
                result.append(path)
                if len(result) > MAX_NATIVE_FILES:
                    raise ValueError("Native inventory limit")
    return sorted(result)


def inspect_pe(path):
    try:
        import pefile
    except ImportError:
        return {"status": "not-tested", "reason": "pefile-build-dependency-unavailable"}
    path = Path(path)
    if (
        not 0 < path.stat().st_size <= MAX_FILE_BYTES
        or path.is_symlink()
        or path.is_junction()
    ):
        raise ValueError("Native file size/path limit")
    try:
        with pefile.PE(str(path), fast_load=True) as pe:
            pe.parse_data_directories(directories=[1, 13])
            imports = sorted(
                {
                    entry.dll.decode("ascii", "replace").lower()
                    for field in (
                        "DIRECTORY_ENTRY_IMPORT",
                        "DIRECTORY_ENTRY_DELAY_IMPORT",
                    )
                    for entry in getattr(pe, field, ())
                }
            )
            result = {
                "status": "ready",
                "architecture": {0x8664: "x64", 0x14C: "x86", 0xAA64: "arm64"}.get(
                    pe.FILE_HEADER.Machine, "unknown"
                ),
                "linker": f"{pe.OPTIONAL_HEADER.MajorLinkerVersion}.{pe.OPTIONAL_HEADER.MinorLinkerVersion}",
                "imports": imports,
                "vc_runtime_imports": [
                    name
                    for name in imports
                    if name.startswith(("vcruntime", "msvcp", "concrt", "vcomp", "mfc"))
                ],
                "ucrt_imports": [
                    name
                    for name in imports
                    if name == "ucrtbase.dll" or name.startswith("api-ms-win-crt-")
                ],
            }
        with path.open("rb") as binary:
            result["sha256"] = hashlib.file_digest(binary, "sha256").hexdigest()
        result["bytes"] = path.stat().st_size
        if result["architecture"] != "x64":
            result.update(status="requires-attention", reason="component-not-x64")
        return result
    except pefile.PEFormatError:
        return {"status": "requires-attention", "reason": "invalid-pe"}


def inventory(root, *, signatures=False):
    root = Path(root)
    records = []
    for path in native_files(root):
        try:
            pe_result = inspect_pe(path)
        except (OSError, ValueError):
            pe_result = {
                "status": "requires-attention",
                "reason": "native-file-unavailable-or-limit",
            }
        record = {"path": path.relative_to(root).as_posix(), **pe_result}
        if signatures:
            try:
                record["signature"] = inspect_signature(path)
            except SigningError:
                record["signature"] = {
                    "status": "not-tested",
                    "reason": "windows-signature-query-unavailable",
                }
        else:
            record["signature"] = {
                "status": "not-tested",
                "reason": "signature-query-not-requested",
            }
        records.append(record)
    return records


def ocr_check(root):
    runtime = OcrRuntime(Path(root), prefer_windows=False)
    result = {}
    for family, language, key in (
        ("fast", "por", "portable-portuguese"),
        ("fast", "osd", "orientation"),
        ("best", "por", "optional-best"),
    ):
        try:
            runtime._component(family, language)
            result[key] = {"status": "ready", "integrity": "pinned-sha256"}
        except OcrUnavailable:
            result[key] = {
                "status": "requires-attention",
                "reason": "component-missing-corrupt-or-unsupported",
            }
    result["windows-ocr"] = {
        "status": "not-tested",
        "reason": "optional-api-requires-separate-functional-test-and-package-support-review",
    }
    return result


def smart_app_control_state():
    if os.name != "nt":
        return {"status": "not-tested", "reason": "windows-only"}
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\CI\Policy",
            0,
            winreg.KEY_READ,
        ) as key:
            value = winreg.QueryValueEx(key, "VerifiedAndReputablePolicyState")[0]
        return {
            "status": "not-tested",
            "configured_state": {0: "off", 1: "enforced", 2: "evaluation"}.get(
                value, "unknown"
            ),
            "reason": "configuration-is-not-an-application-acceptance-test",
        }
    except OSError:
        return {"status": "not-tested", "reason": "policy-query-unavailable"}


def probe_directory(path, *, write=False):
    """Optional explicit QA probe; default diagnostics never create directories."""
    path = Path(path)
    if not path.is_absolute() or any(
        p.is_symlink() or p.is_junction() for p in (path, *path.parents)
    ):
        return {"status": "requires-attention", "reason": "invalid-directory-probe"}
    try:
        with os.scandir(path):
            pass
        if write:
            with tempfile.TemporaryFile(dir=path) as own:
                own.write(b"QA")
                own.flush()
                os.fsync(own.fileno())
            return {
                "status": "ready",
                "readable": True,
                "writable": True,
                "reason": "explicit-temporary-write-probe",
            }
        return {"status": "ready", "readable": True, "writable": "not-tested"}
    except OSError:
        return {
            "status": "requires-attention",
            "reason": "directory-access-unavailable",
        }


def collect_report(app_dir=None):
    app_dir = Path(app_dir) if app_dir is not None else get_app_dir()
    try:
        runtime = get_runtime_state_dir(app_dir)
        paths = {
            "status": "ready",
            "application_data_separate": runtime != app_dir,
            "mode": "frozen-per-user"
            if getattr(sys, "frozen", False)
            else "source-development",
            "write_permission": "not-tested: read-only check does not create files",
        }
    except Exception:
        paths = {"status": "requires-attention", "reason": "invalid-user-profile"}
    return {
        "schema": 1,
        "windows": {
            "status": "ready" if os.name == "nt" else "not-tested",
            "build": sys.getwindowsversion().build if os.name == "nt" else None,
            "architecture": native_architecture(),
        },
        "vc_runtime": asdict(check_vc_runtime()),
        "data_paths": paths,
        "ocr": ocr_check(bundled_ocr_directory(app_dir)),
        "smart_app_control": smart_app_control_state(),
        "publisher_signing": {
            "status": "blocked-by-external-dependency",
            "reason": "no-explicit-authorized-certificate-or-provider-configured",
        },
        "clean_machine": {
            "status": "not-tested",
            "reason": "requires-independent-windows-environment",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path)
    parser.add_argument("--inventory-root", type=Path)
    parser.add_argument("--signatures", action="store_true")
    parser.add_argument("--probe-directory", type=Path)
    parser.add_argument("--probe-write", action="store_true")
    args = parser.parse_args()
    report = collect_report(args.app_dir)
    if args.probe_write and args.probe_directory is None:
        parser.error("--probe-write requires an explicit --probe-directory")
    if args.probe_directory:
        report["directory_probe"] = probe_directory(
            args.probe_directory, write=args.probe_write
        )
    if args.inventory_root:
        try:
            report["native_inventory"] = inventory(
                args.inventory_root, signatures=args.signatures
            )
        except (ValueError, OSError):
            report["native_inventory"] = {
                "status": "requires-attention",
                "reason": "inventory-root-unavailable-or-limit",
            }
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
