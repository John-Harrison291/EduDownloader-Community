"""Build and validate evidence for a clean frozen analysis candidate.

The module intentionally keeps the product runtime independent from the local
wheelhouse.  It is used only by the controlled build pipeline and records no
absolute local paths in tracked evidence.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Mapping, Sequence

from constants import (
    APP_NAME,
    APP_VERSION,
    PRODUCT_EDITION,
)
from notice_delivery import (
    candidate_delivery_record,
    find_candidate_delivery_issues,
)
from validate_distribution import find_distribution_issues
from validate_pyinstaller_warnings import (
    parse_warning_entries,
    read_explained_warnings,
    read_warning_baseline,
)
from validate_python_wheels import canonical_json_bytes, sha256_file


SCHEMA_VERSION: Final = 1
CANDIDATE_CLASSIFICATION: Final = "INTERNAL_ANALYSIS_CANDIDATE"
CONTROLLED_CANDIDATE_CLASSIFICATION: Final = "INTERNAL_CONTROLLED_CANDIDATE_R2"
NOTICE_COMPLETE_CANDIDATE_CLASSIFICATION: Final = "INTERNAL_CONTROLLED_CANDIDATE_R3"
V1_0_RELEASE_CANDIDATE_CLASSIFICATION: Final = "INTERNAL_1_0_RELEASE_CANDIDATE_RC1"
RELEASE_CANDIDATE_CLASSIFICATION: Final = "INTERNAL_1_1_RELEASE_CANDIDATE_RC1"
RELEASE_CANDIDATE_RC2_CLASSIFICATION: Final = "INTERNAL_1_1_RELEASE_CANDIDATE_RC2"
RELEASE_CANDIDATE_RC3_CLASSIFICATION: Final = "INTERNAL_1_1_RELEASE_CANDIDATE_RC3"
V1_2_RELEASE_CANDIDATE_CLASSIFICATION: Final = "INTERNAL_1_2_RELEASE_CANDIDATE_RC1"
V1_3_RELEASE_CANDIDATE_CLASSIFICATION: Final = "INTERNAL_1_3_RELEASE_CANDIDATE_RC1"
V1_4_RELEASE_CANDIDATE_CLASSIFICATION: Final = "INTERNAL_1_4_RELEASE_CANDIDATE_RC1"
V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION: Final = "INTERNAL_1_4_RELEASE_CANDIDATE_RC2"
V1_5_RELEASE_CANDIDATE_CLASSIFICATION: Final = "INTERNAL_1_5_RELEASE_CANDIDATE_RC1"
V1_6_PORTABILITY_PROBE_CLASSIFICATION: Final = "INTERNAL_1_6_PORTABILITY_PROBE"
V1_6_RELEASE_CANDIDATE_CLASSIFICATION: Final = "INTERNAL_1_6_RELEASE_CANDIDATE_RC1"
V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION: Final = "INTERNAL_1_6_RELEASE_CANDIDATE_RC2"
V1_7_VISUAL_PROBE_CLASSIFICATION: Final = "INTERNAL_1_7_VISUAL_PROBE"
V1_7_RELEASE_CANDIDATE_CLASSIFICATION: Final = "INTERNAL_1_7_RELEASE_CANDIDATE_RC1"
V1_7_BRANDING_PATH: Final = "_internal/branding/edudownloader-logo-original.png"
V1_7_BRANDING_SHA256: Final = (
    "FE0321DBFF7338B322CD458A5D40EA8D07B0FF31DFF142C5D803B7B3FF0BAE56"
)
V1_7_BRANDING_SIZE: Final = 452_529
# The 1.3 poster imports ImageDraw -> ImageFont -> optional _imagingft.
# These are the exact extension bytes in the approved Pillow 12.3.0 wheel.
V1_3_PILLOW_IMAGINGFT_PATH: Final = "_internal/PIL/_imagingft.cp314-win_amd64.pyd"
V1_3_PILLOW_IMAGINGFT_SHA256: Final = (
    "93C3CA5A3E7119897BE9825A0A4228D485410FC8F1E42257EDF7E89052C79BCE"
)
V1_3_PILLOW_IMAGINGFT_SIZE: Final = 2_171_392
ALLOWED_CANDIDATE_CLASSIFICATIONS: Final = frozenset(
    {
        CANDIDATE_CLASSIFICATION,
        CONTROLLED_CANDIDATE_CLASSIFICATION,
        NOTICE_COMPLETE_CANDIDATE_CLASSIFICATION,
        V1_0_RELEASE_CANDIDATE_CLASSIFICATION,
        RELEASE_CANDIDATE_CLASSIFICATION,
        RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        RELEASE_CANDIDATE_RC3_CLASSIFICATION,
        V1_2_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_5_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_PORTABILITY_PROBE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_7_VISUAL_PROBE_CLASSIFICATION,
        V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
    }
)
ALLOWED_SMOKE_RESULTS: Final = frozenset(
    {"NOT_RUN", "PASS", "PASS_WITH_AUTOMATION_LIMITATION"}
)
ALLOWED_PACKED_YTDLP_SMOKE_RESULTS: Final = frozenset({"NOT_RUN", "PASS"})
PIPELINE_VERSION: Final = 2
EXPECTED_SOURCE_COMMIT_PATTERN: Final = re.compile(r"[0-9a-f]{40}")
ABSOLUTE_WINDOWS_PATH_PATTERN: Final = re.compile(
    r"(?i)(?:^|[\s\"'])(?:[a-z]:[\\/]|\\\\[^\\/\s]+[\\/])"
)


@dataclass(frozen=True)
class CandidatePipelineContract:
    """Explicit paths and classification for one known release candidate."""

    candidate_id: str
    root: Path
    manifest: Path
    classification: str
    cleanup_allowed: bool


_CANDIDATE_SPECS: Final = {
    "rc1": (
        "build-community-candidate-1.1.0-rc1",
        "FROZEN_CANDIDATE_1_1_RC1_COMPOSITION.json",
        RELEASE_CANDIDATE_CLASSIFICATION,
        False,
    ),
    "rc2": (
        "build-community-candidate-1.1.0-rc2",
        "FROZEN_CANDIDATE_1_1_RC2_COMPOSITION.json",
        RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        False,
    ),
    "rc3": (
        "build-community-candidate-1.1.0-rc3",
        "FROZEN_CANDIDATE_1_1_RC3_COMPOSITION.json",
        RELEASE_CANDIDATE_RC3_CLASSIFICATION,
        False,
    ),
    "v1.2-rc1": (
        "build-community-candidate-1.2.0-rc1",
        "FROZEN_CANDIDATE_1_2_RC1_COMPOSITION.json",
        V1_2_RELEASE_CANDIDATE_CLASSIFICATION,
        False,
    ),
    "v1.3-rc1": (
        "build-community-candidate-1.3.0-rc1",
        "FROZEN_CANDIDATE_1_3_RC1_COMPOSITION.json",
        V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
        False,
    ),
    "v1.4-rc1": (
        "build-community-candidate-1.4.0-rc1",
        "FROZEN_CANDIDATE_1_4_RC1_COMPOSITION.json",
        V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
        True,
    ),
    "v1.4-rc2": (
        "build-community-candidate-1.4.0-rc2",
        "FROZEN_CANDIDATE_1_4_RC2_COMPOSITION.json",
        V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        True,
    ),
    "v1.5-rc1": (
        "build-community-candidate-1.5.0-rc1",
        "FROZEN_CANDIDATE_1_5_RC1_COMPOSITION.json",
        V1_5_RELEASE_CANDIDATE_CLASSIFICATION,
        True,
    ),
    "v1.6-probe": (
        "build-community-probe-1.6.0",
        "FROZEN_PROBE_1_6_COMPOSITION.json",
        V1_6_PORTABILITY_PROBE_CLASSIFICATION,
        True,
    ),
    "v1.6-rc1": (
        "build-community-candidate-1.6.0-rc1",
        "FROZEN_CANDIDATE_1_6_RC1_COMPOSITION.json",
        V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
        True,
    ),
    "v1.6-rc2": (
        "build-community-candidate-1.6.0-rc2",
        "FROZEN_CANDIDATE_1_6_RC2_COMPOSITION.json",
        V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        True,
    ),
    "v1.7-visual-probe": (
        "build-community-probe-1.7.0-visual",
        "FROZEN_PROBE_1_7_VISUAL_COMPOSITION.json",
        V1_7_VISUAL_PROBE_CLASSIFICATION,
        True,
    ),
    "v1.7-rc1": (
        "build-community-candidate-1.7.0-rc1",
        "FROZEN_CANDIDATE_1_7_RC1_COMPOSITION.json",
        V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
        True,
    ),
}


def candidate_pipeline_contract(
    project_root: Path, candidate_id: str
) -> CandidatePipelineContract:
    """Return the explicit, fail-closed contract for a known candidate."""

    try:
        root_name, manifest_name, classification, cleanup_allowed = _CANDIDATE_SPECS[
            candidate_id
        ]
    except KeyError as exc:
        raise ValueError(f"unsupported-candidate-id:{candidate_id}") from exc
    project = project_root.resolve()
    return CandidatePipelineContract(
        candidate_id=candidate_id,
        root=project / root_name,
        manifest=(
            project / root_name / "evidence" / manifest_name
            if candidate_id in {"v1.6-probe", "v1.7-visual-probe"}
            else project / "docs" / "compliance" / "build" / manifest_name
        ),
        classification=classification,
        cleanup_allowed=cleanup_allowed,
    )


def candidate_contract_environment(
    project_root: Path, candidate_id: str
) -> dict[str, str]:
    """Build the small environment contract consumed by ``build.bat``."""

    selected = candidate_pipeline_contract(project_root, candidate_id)
    rc1 = candidate_pipeline_contract(project_root, "rc1")
    rc2 = candidate_pipeline_contract(project_root, "rc2")
    rc3 = candidate_pipeline_contract(project_root, "rc3")
    v1_2_rc1 = candidate_pipeline_contract(project_root, "v1.2-rc1")
    v1_3_rc1 = candidate_pipeline_contract(project_root, "v1.3-rc1")
    return {
        "CANDIDATE_CLEANUP_ALLOWED": "1" if selected.cleanup_allowed else "0",
        "CANDIDATE_CLASSIFICATION": selected.classification,
        "CANDIDATE_ROOT": str(selected.root),
        "EXPECTED_CANDIDATE_ROOT": str(selected.root),
        "FROZEN_MANIFEST": str(selected.manifest),
        "RESOLVED_PROJECT_ROOT": str(project_root.resolve()),
        "RESOLVED_CANDIDATE_ID": selected.candidate_id,
        "RC1_CANDIDATE_ROOT": str(rc1.root),
        "RC1_FROZEN_MANIFEST": str(rc1.manifest),
        "RC1_PORTABLE_DIR": str(rc1.root / "dist" / "EduDownloader-Portable"),
        "RC2_CANDIDATE_ROOT": str(rc2.root),
        "RC2_FROZEN_MANIFEST": str(rc2.manifest),
        "RC2_PORTABLE_DIR": str(rc2.root / "dist" / "EduDownloader-Portable"),
        "RC3_CANDIDATE_ROOT": str(rc3.root),
        "RC3_FROZEN_MANIFEST": str(rc3.manifest),
        "RC3_PORTABLE_DIR": str(rc3.root / "dist" / "EduDownloader-Portable"),
        "V1_2_RC1_CANDIDATE_ROOT": str(v1_2_rc1.root),
        "V1_2_RC1_FROZEN_MANIFEST": str(v1_2_rc1.manifest),
        "V1_2_RC1_PORTABLE_DIR": str(v1_2_rc1.root / "dist" / "EduDownloader-Portable"),
        "V1_3_RC1_CANDIDATE_ROOT": str(v1_3_rc1.root),
        "V1_3_RC1_FROZEN_MANIFEST": str(v1_3_rc1.manifest),
        "V1_3_RC1_PORTABLE_DIR": str(v1_3_rc1.root / "dist" / "EduDownloader-Portable"),
    }


def _same_resolved_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(
        str(right.resolve())
    )


def validate_candidate_cleanup_target(
    project_root: Path, candidate_id: str, target: Path
) -> list[str]:
    """Approve only the exact mutable candidate root as a cleanup target."""

    try:
        selected = candidate_pipeline_contract(project_root, candidate_id)
        protected = {
            historical_id: candidate_pipeline_contract(project_root, historical_id)
            for historical_id in ("rc1", "rc2", "rc3", "v1.2-rc1", "v1.3-rc1")
        }
        if candidate_id in {
            "v1.4-rc2",
            "v1.5-rc1",
            "v1.6-probe",
            "v1.6-rc1",
            "v1.6-rc2",
            "v1.7-visual-probe",
            "v1.7-rc1",
        }:
            protected["v1.4-rc1"] = candidate_pipeline_contract(
                project_root, "v1.4-rc1"
            )
        if candidate_id in {
            "v1.5-rc1",
            "v1.6-probe",
            "v1.6-rc1",
            "v1.6-rc2",
            "v1.7-visual-probe",
            "v1.7-rc1",
        }:
            protected["v1.4-rc2"] = candidate_pipeline_contract(
                project_root, "v1.4-rc2"
            )
        if candidate_id in {
            "v1.6-probe",
            "v1.6-rc1",
            "v1.6-rc2",
            "v1.7-visual-probe",
            "v1.7-rc1",
        }:
            protected["v1.5-rc1"] = candidate_pipeline_contract(
                project_root, "v1.5-rc1"
            )
        if candidate_id in {"v1.6-rc1", "v1.6-rc2", "v1.7-visual-probe", "v1.7-rc1"}:
            protected["v1.6-probe"] = candidate_pipeline_contract(
                project_root, "v1.6-probe"
            )
        if candidate_id in {"v1.6-rc2", "v1.7-visual-probe", "v1.7-rc1"}:
            protected["v1.6-rc1"] = candidate_pipeline_contract(
                project_root, "v1.6-rc1"
            )
        if candidate_id in {"v1.7-visual-probe", "v1.7-rc1"}:
            protected["v1.6-rc2"] = candidate_pipeline_contract(
                project_root, "v1.6-rc2"
            )
        if candidate_id == "v1.7-rc1":
            protected["v1.7-visual-probe"] = candidate_pipeline_contract(
                project_root, "v1.7-visual-probe"
            )
    except ValueError:
        return ["candidate-id-invalid"]
    project = project_root.resolve()
    resolved_target = target.resolve()
    issues: list[str] = []
    if not selected.cleanup_allowed:
        issues.append("candidate-cleanup-read-only")
    if not _same_resolved_path(resolved_target, selected.root):
        issues.append("candidate-cleanup-target-mismatch")
    if not _same_resolved_path(resolved_target.parent, project):
        issues.append("candidate-cleanup-outside-project")
    for historical_id, historical in protected.items():
        if _same_resolved_path(resolved_target, historical.root):
            issues.append(f"candidate-cleanup-protected-{historical_id}")
    return sorted(set(issues))


def prepare_candidate_root(project_root: Path, candidate_id: str, target: Path) -> None:
    """Remove an existing mutable candidate only after validating its exact path."""

    issues = validate_candidate_cleanup_target(project_root, candidate_id, target)
    if issues:
        raise ValueError(",".join(issues))
    if target.exists():
        if not target.is_dir():
            raise ValueError("candidate-cleanup-target-not-directory")
        shutil.rmtree(target)


EXTERNAL_BINARY_BASELINE: Final = {
    "yt-dlp.exe": {
        "component": "yt-dlp",
        "provider": "official yt-dlp release",
        "sha256": ("66674953FE251B89F4D08C5F0E35E0728679BD67AB3D7D05C0562AF101DD3E7A"),
        "version": "2026.08.19",
    },
    "ffmpeg.exe": {
        "component": "FFmpeg",
        "provider": "Gyan",
        "sha256": ("1326DDE4C84FF1F96FE6B8916C5BED29E163E9B5DCCF995F6F3DB069D143EC5E"),
        "version": "8.1.2 essentials",
    },
    "ffprobe.exe": {
        "component": "FFprobe",
        "provider": "Gyan",
        "sha256": ("B49CCC7C6547B141AD5A2F6EC69CC04323D7133D7704D70B331B904C63EECB07"),
        "version": "8.1.2 essentials",
    },
    "deno.exe": {
        "component": "Deno",
        "provider": "official Deno release",
        "sha256": ("98F8C2A2D470E4CCB04C935C86FF8050817D877762AEC5EAEEB9E409CCB3B9FD"),
        "version": "2.9.5 x86_64-pc-windows-msvc",
    },
}
V1_4_RC2_EXTERNAL_BINARY_BASELINE: Final = {
    **EXTERNAL_BINARY_BASELINE,
    "ffmpeg.exe": {
        "component": "FFmpeg",
        "provider": "BtbN",
        "sha256": "88F0453C46DBF83D3DA583A3ECECCBA6F2B82169C89A9B4254C481267E7135F8",
        "version": "n8.1.2-44-g7c533d0f86-20260825 win64-lgpl-8.1",
    },
    "ffprobe.exe": {
        "component": "FFprobe",
        "provider": "BtbN",
        "sha256": "07A26215E0C482407412EEBA88FD169CAA97C8CBCD0C567CF9C6CFBA6F2843C7",
        "version": "n8.1.2-44-g7c533d0f86-20260825 win64-lgpl-8.1",
    },
}


def _external_baseline_for_classification(
    candidate_classification: str,
) -> Mapping[str, Mapping[str, str]]:
    if candidate_classification in {
        V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_5_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_PORTABILITY_PROBE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_7_VISUAL_PROBE_CLASSIFICATION,
        V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
    }:
        return V1_4_RC2_EXTERNAL_BINARY_BASELINE
    return EXTERNAL_BINARY_BASELINE


PACKAGE_NAMESPACES: Final = {
    "altgraph": ("altgraph",),
    "cffi": ("cffi",),
    "cryptography": ("cryptography",),
    "customtkinter": ("customtkinter",),
    "darkdetect": ("darkdetect",),
    "packaging": ("packaging",),
    "pefile": ("pefile",),
    "pillow": ("PIL",),
    "pip": ("pip",),
    "pycparser": ("pycparser",),
    "pyinstaller": ("PyInstaller",),
    "pyinstaller-hooks-contrib": ("_pyinstaller_hooks_contrib",),
    "pypdf": ("pypdf",),
    "pypdfium2": ("pypdfium2", "pypdfium2_raw"),
    "pywin32-ctypes": ("win32ctypes",),
    "ruff": ("ruff",),
    "setuptools": ("setuptools", "pkg_resources"),
}
BUILD_TOOL_ONLY_PACKAGES: Final = frozenset({"pip", "ruff", "setuptools"})
BUILD_ONLY_PACKAGES: Final = frozenset(
    {"altgraph", "packaging", "pefile", "pycparser", "pywin32-ctypes"}
)

PRIVATE_FILENAMES: Final = frozenset(
    {
        "activation.dat",
        "issuer-signing-key-v1.dpapi",
        "issuance-register.json",
        "private-key.pem",
        "private-signing-key.pem",
    }
)
PRIVATE_SUFFIXES: Final = frozenset(
    {".dpapi", ".key", ".p12", ".p8", ".pem", ".pk8", ".pkcs8", ".seed"}
)
PRIVATE_TEXT_MARKERS: Final = (
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN ENCRYPTED PRIVATE KEY-----",
    "edudownloader.private-signing-key",
    "protected_private_key",
    "issuer-signing-key-v1.dpapi",
)
FORBIDDEN_ARCHIVE_PREFIXES: Final = ("activation_issuer", "tests")
V1_4_REQUIRED_PYZ_MODULES: Final = frozenset({"documents_component", "documents_tools"})
V1_5_REQUIRED_PYZ_MODULES: Final = V1_4_REQUIRED_PYZ_MODULES | frozenset(
    {"media_tools", "mp3_quality"}
)
V1_4_FORBIDDEN_PDF_TO_DOCX_NAMESPACES: Final = frozenset(
    {"cv2", "fitz", "numpy", "pdf2docx", "pymupdf"}
)
TEXT_SCAN_SUFFIXES: Final = frozenset(
    {".cfg", ".ini", ".json", ".log", ".md", ".txt", ".xml", ".yaml", ".yml"}
)
RUNTIME_ALLOWED_PATHS: Final = frozenset({"settings.json", "Logs/edudownloader.log"})


def _relative(path: Path, root: Path) -> str:
    return PurePosixPath(*path.relative_to(root).parts).as_posix()


def _canonical_inventory_bytes(entries: list[dict[str, Any]]) -> bytes:
    return json.dumps(
        entries,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _file_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    return suffix.removeprefix(".") if suffix else "no_extension"


def classify_file(relative_path: str) -> tuple[str, str]:
    """Classify one real onedir payload without inferring from build wheels."""

    normalized = relative_path.replace("\\", "/")
    lowered = normalized.casefold()
    name = PurePosixPath(normalized).name.casefold()
    top_level = "/" not in normalized

    if top_level and name in EXTERNAL_BINARY_BASELINE:
        baseline = EXTERNAL_BINARY_BASELINE[name]
        return "external_executables", str(baseline["component"])
    if lowered == "edudownloader.exe":
        return "frozen_application", "EduDownloader + PyInstaller bootloader"
    if lowered.startswith("licencas/"):
        return "notices_licenses", "tracked compliance material"
    if lowered == "readme.txt":
        return "assets_data", "EduDownloader"
    if lowered.startswith("_internal/_tcl_data/") or lowered.startswith(
        "_internal/_tk_data/"
    ):
        return "python_tcl_tk_runtime", "Tcl/Tk from CPython 3.14.6"
    if any(
        marker in lowered
        for marker in ("/tcl8", "/tcl9", "/tk8", "/tk9", "tcl86", "tk86")
    ):
        return "python_tcl_tk_runtime", "Tcl/Tk from CPython 3.14.6"
    if lowered.startswith("_internal/pil/"):
        return "third_party_python_native", "Pillow 12.3.0"
    if lowered.startswith("_internal/cryptography/"):
        return "third_party_python_native", "cryptography 49.0.0"
    if name.startswith("_cffi_backend"):
        return "third_party_python_native", "cffi 2.1.1"
    if lowered.startswith("_internal/pypdfium2") or name == "pdfium.dll":
        return "third_party_python_native", "pypdfium2 5.12.1 / PDFium"
    if lowered.startswith("_internal/customtkinter/"):
        return "assets_data", "CustomTkinter 5.2.2"
    if lowered == V1_7_BRANDING_PATH.casefold():
        return "assets_data", "EduDownloader branding"
    if name.startswith("python3") and name.endswith(".dll"):
        return "python_runtime", "CPython 3.14.6"
    if name == "base_library.zip":
        return "python_runtime", "CPython 3.14.6 standard library"
    if name.startswith(("vcruntime", "msvcp", "ucrtbase", "api-ms-win-")):
        return "microsoft_runtime", "Microsoft runtime"
    if lowered.startswith("_internal/") and path_suffix(lowered) == ".pyd":
        return "python_runtime", "CPython 3.14.6 extension module"
    if lowered.startswith("_internal/") and path_suffix(lowered) == ".dll":
        return "python_pyinstaller_runtime", "CPython/PyInstaller runtime"
    if lowered.startswith("_internal/"):
        return "python_pyinstaller_runtime", "PyInstaller onedir payload"
    return "assets_data", "EduDownloader"


def path_suffix(path: str) -> str:
    return PurePosixPath(path).suffix.casefold()


def build_file_inventory(root: Path) -> dict[str, Any]:
    """Inventory every shipped file and attach conservative provenance."""

    resolved = root.resolve()
    entries: list[dict[str, Any]] = []
    for path in sorted(
        (item for item in resolved.rglob("*") if item.is_file()),
        key=lambda item: (
            _relative(item, resolved).casefold(),
            _relative(item, resolved),
        ),
    ):
        relative = _relative(path, resolved)
        group, provenance = classify_file(relative)
        entries.append(
            {
                "group": group,
                "path": relative,
                "provenance": provenance,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                "type": _file_type(path),
            }
        )
    return {
        "algorithm": "sha256",
        "entries": entries,
        "file_count": len(entries),
        "inventory_sha256": hashlib.sha256(_canonical_inventory_bytes(entries))
        .hexdigest()
        .upper(),
        "scope": "all-files-in-pristine-candidate",
        "total_size_bytes": sum(entry["size_bytes"] for entry in entries),
    }


def summarize_groups(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, int]] = {}
    for entry in entries:
        group = str(entry["group"])
        summary = totals.setdefault(group, {"file_count": 0, "total_size_bytes": 0})
        summary["file_count"] += 1
        summary["total_size_bytes"] += int(entry["size_bytes"])
    return [
        {"group": group, **totals[group]} for group in sorted(totals, key=str.casefold)
    ]


def find_contamination_issues(root: Path) -> list[str]:
    """Reject runtime residue, private artifacts and administrative material."""

    resolved = root.resolve()
    if not resolved.is_dir():
        return ["candidate-root-missing"]
    issues: list[str] = []
    if (resolved / "Componentes").exists():
        issues.append("managed-components-bundled")
    for directory_name in ("Downloads", "Logs"):
        directory = resolved / directory_name
        if not directory.is_dir():
            issues.append(f"required-empty-directory-missing:{directory_name}")
        elif any(directory.iterdir()):
            issues.append(f"runtime-generated-file-present:{directory_name}")

    for path in resolved.rglob("*"):
        if not path.is_file():
            continue
        relative = _relative(path, resolved)
        lowered = relative.casefold()
        name = path.name.casefold()
        suffix = path.suffix.casefold()
        if ".ds_store" in lowered.split("/"):
            issues.append(f"non-runtime-metadata-present:{relative}")
        if name == "settings.json":
            issues.append(f"runtime-settings-present:{relative}")
        if name in PRIVATE_FILENAMES or suffix in PRIVATE_SUFFIXES:
            issues.append(f"private-artifact-present:{relative}")
        if any(
            marker in lowered
            for marker in (
                "activation_issuer",
                "issuance-register",
                "private-signing-key",
                "source-bundle",
                "wheelhouse",
            )
        ):
            issues.append(f"administrative-or-source-artifact-present:{relative}")
        if suffix not in TEXT_SCAN_SUFFIXES or path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            issues.append(f"text-scan-failed:{relative}")
            continue
        if any(marker.encode("ascii") in data for marker in PRIVATE_TEXT_MARKERS):
            issues.append(f"private-material-marker-present:{relative}")
    return sorted(set(issues))


def inspect_external_binaries(
    root: Path,
    expected: Mapping[str, Mapping[str, str]] = EXTERNAL_BINARY_BASELINE,
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    for filename in sorted(expected, key=str.casefold):
        path = root / filename
        baseline = expected[filename]
        if not path.is_file():
            issues.append(f"external-binary-missing:{filename}")
            continue
        digest = sha256_file(path)
        if digest != baseline["sha256"]:
            issues.append(f"external-binary-hash-mismatch:{filename}")
        records.append(
            {
                "component": baseline["component"],
                "filename": filename,
                "provider": baseline["provider"],
                "sha256": digest,
                "size_bytes": path.stat().st_size,
                "version": baseline["version"],
            }
        )
    return records, issues


def _analysis_runtime_hook_provenance(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    try:
        parsed = ast.literal_eval(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return {}

    provenance: dict[str, str] = {}

    def visit(value: object) -> None:
        if isinstance(value, tuple) and len(value) >= 2:
            destination, source = value[0], value[1]
            if isinstance(destination, str) and isinstance(source, str):
                name = PurePosixPath(destination.replace("\\", "/")).name
                if name.startswith("pyi_rth_"):
                    lowered_source = source.casefold().replace("\\", "/")
                    if "_pyinstaller_hooks_contrib" in lowered_source:
                        provenance[name] = "pyinstaller-hooks-contrib"
                    elif "/pyinstaller/" in lowered_source:
                        provenance[name] = "PyInstaller"
                    else:
                        provenance[name] = "EduDownloader project runtime hook"
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(parsed)
    return provenance


def inspect_frozen_archives(
    executable: Path,
    analysis_toc: Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Read CArchive/PYZ from the real executable without extracting source."""

    issues: list[str] = []
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError:
        return {}, ["pyinstaller-reader-unavailable"]

    try:
        archive = CArchiveReader(str(executable))
    except (OSError, TypeError, ValueError) as error:
        return {}, [f"carchive-unreadable:{type(error).__name__}"]

    carchive_entries = [
        {"name": name, "typecode": values[-1]}
        for name, values in sorted(archive.toc.items(), key=lambda item: item[0])
    ]
    pyz_modules: list[str] = []
    for name, values in archive.toc.items():
        if values[-1] != "z":
            continue
        try:
            embedded = archive.open_embedded_archive(name)
            pyz_modules.extend(str(module) for module in embedded.toc)
        except (KeyError, OSError, TypeError, ValueError) as error:
            issues.append(f"pyz-unreadable:{name}:{type(error).__name__}")

    hook_origins = _analysis_runtime_hook_provenance(analysis_toc)
    runtime_hooks: list[dict[str, str]] = []
    for entry in carchive_entries:
        name = PurePosixPath(entry["name"].replace("\\", "/")).name
        if not name.startswith("pyi_rth_"):
            continue
        runtime_hooks.append(
            {
                "name": name,
                "provenance": hook_origins.get(name, "UNKNOWN"),
            }
        )

    all_names = [entry["name"] for entry in carchive_entries] + pyz_modules
    for name in all_names:
        lowered = name.casefold()
        if any(
            lowered == prefix or lowered.startswith(f"{prefix}.")
            for prefix in FORBIDDEN_ARCHIVE_PREFIXES
        ):
            issues.append(f"forbidden-archive-entry:{name}")

    return (
        {
            "carchive_entries": carchive_entries,
            "carchive_entry_count": len(carchive_entries),
            "pyz_module_count": len(set(pyz_modules)),
            "pyz_modules": sorted(set(pyz_modules), key=str.casefold),
            "runtime_hooks": sorted(runtime_hooks, key=lambda item: item["name"]),
        },
        sorted(set(issues)),
    )


def find_v1_4_archive_issues(
    archive: Mapping[str, Any], candidate_classification: str
) -> list[str]:
    """Enforce the closed 1.4 PYZ contract without inspecting source heuristically."""

    if candidate_classification not in {
        V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
    }:
        return []
    modules = {str(module).casefold() for module in archive.get("pyz_modules", ())}
    issues = [
        f"v1.4-required-pyz-module-missing:{module}"
        for module in sorted(V1_4_REQUIRED_PYZ_MODULES)
        if module.casefold() not in modules
    ]
    for module in sorted(modules):
        namespace = module.partition(".")[0]
        if namespace in V1_4_FORBIDDEN_PDF_TO_DOCX_NAMESPACES:
            issues.append(f"v1.4-pdf-to-docx-module-forbidden:{module}")
    return issues


def find_v1_5_archive_issues(
    archive: Mapping[str, Any], candidate_classification: str
) -> list[str]:
    """Require the frozen 1.5 media modules without relaxing prior exclusions."""

    if candidate_classification not in {
        V1_5_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_PORTABILITY_PROBE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_7_VISUAL_PROBE_CLASSIFICATION,
        V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
    }:
        return []
    modules = {str(module).casefold() for module in archive.get("pyz_modules", ())}
    issues = [
        f"v1.5-required-pyz-module-missing:{module}"
        for module in sorted(V1_5_REQUIRED_PYZ_MODULES)
        if module.casefold() not in modules
    ]
    for module in sorted(modules):
        if module.partition(".")[0] in V1_4_FORBIDDEN_PDF_TO_DOCX_NAMESPACES:
            issues.append(f"v1.5-pdf-to-docx-module-forbidden:{module}")
    return issues


def _module_present(modules: Iterable[str], namespaces: Iterable[str]) -> bool:
    lowered_modules = {module.casefold() for module in modules}
    for namespace in namespaces:
        lowered_namespace = namespace.casefold()
        if any(
            module == lowered_namespace or module.startswith(f"{lowered_namespace}.")
            for module in lowered_modules
        ):
            return True
    return False


def classify_package_materiality(
    pyz_modules: Iterable[str],
    file_paths: Iterable[str],
    runtime_hooks: Iterable[Mapping[str, str]],
) -> list[dict[str, Any]]:
    """Classify the 17 locked packages from material found in the real output."""

    modules = tuple(pyz_modules)
    paths = tuple(path.replace("\\", "/") for path in file_paths)
    lowered_paths = tuple(path.casefold() for path in paths)
    hook_records = tuple(runtime_hooks)
    records: list[dict[str, Any]] = []
    native_markers = {
        "cffi": ("_cffi_backend",),
        "cryptography": ("/cryptography/", "cryptography/hazmat/bindings/_rust"),
        "pillow": ("/pil/",),
        "pypdfium2": ("/pypdfium2", "pdfium.dll"),
    }
    data_markers = {
        "customtkinter": ("/customtkinter/",),
        "pillow": ("/pil/",),
        "pypdfium2": ("/pypdfium2",),
    }

    for package, namespaces in PACKAGE_NAMESPACES.items():
        module_present = _module_present(modules, namespaces)
        native_evidence = sorted(
            path
            for path, lowered in zip(paths, lowered_paths, strict=True)
            if any(marker in lowered for marker in native_markers.get(package, ()))
            and path_suffix(lowered) in {".dll", ".pyd"}
        )
        data_evidence = sorted(
            path
            for path, lowered in zip(paths, lowered_paths, strict=True)
            if any(marker in lowered for marker in data_markers.get(package, ()))
        )
        evidence: list[str] = []

        if package == "pyinstaller":
            hook_names = sorted(
                hook["name"]
                for hook in hook_records
                if hook.get("provenance") == "PyInstaller"
            )
            evidence = ["EduDownloader.exe bootloader", *hook_names]
            category = "PARTIAL_COMPONENT_PRESENT"
        elif package == "pyinstaller-hooks-contrib":
            evidence = sorted(
                hook["name"]
                for hook in hook_records
                if hook.get("provenance") == "pyinstaller-hooks-contrib"
            )
            category = "PARTIAL_COMPONENT_PRESENT" if evidence else "BUILD_ONLY"
        elif native_evidence:
            evidence = native_evidence
            category = "DISTRIBUTED_NATIVE"
        elif module_present:
            evidence = [f"PYZ namespace: {namespace}" for namespace in namespaces]
            category = "DISTRIBUTED_RUNTIME"
        elif data_evidence:
            evidence = data_evidence
            category = "DISTRIBUTED_DATA"
        elif package in BUILD_TOOL_ONLY_PACKAGES:
            category = "BUILD_TOOL_ONLY"
        elif package in BUILD_ONLY_PACKAGES:
            category = "BUILD_ONLY"
        else:
            category = "NOT_PRESENT_IN_FROZEN_OUTPUT"

        records.append(
            {
                "classification": category,
                "evidence": evidence,
                "package": package,
            }
        )
    return records


def pe_imports(path: Path) -> tuple[list[str], str | None]:
    """Return redacted PE import names for native composition evidence."""

    try:
        import pefile
    except ImportError:
        return [], "pefile-unavailable"
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        imports = sorted(
            {
                entry.dll.decode("ascii", errors="replace")
                for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", ())
            },
            key=str.casefold,
        )
        pe.close()
        return imports, None
    except (OSError, ValueError, pefile.PEFormatError) as error:
        return [], f"{type(error).__name__}"


def _component_records(
    root: Path,
    entries: Iterable[Mapping[str, Any]],
    markers: Iterable[str],
    *,
    include_pe_imports: bool = False,
) -> list[dict[str, Any]]:
    marker_values = tuple(marker.casefold() for marker in markers)
    records: list[dict[str, Any]] = []
    for entry in entries:
        path = str(entry["path"])
        if not any(marker in path.casefold() for marker in marker_values):
            continue
        record: dict[str, Any] = {
            "path": path,
            "sha256": entry["sha256"],
            "size_bytes": entry["size_bytes"],
        }
        if include_pe_imports and path_suffix(path) in {".dll", ".exe", ".pyd"}:
            imports, error = pe_imports(root / PurePosixPath(path))
            record["pe_imports"] = imports
            if error is not None:
                record["pe_inspection_error"] = error
        records.append(record)
    return records


def build_component_evidence(
    root: Path,
    inventory: Mapping[str, Any],
    archive: Mapping[str, Any],
) -> dict[str, Any]:
    entries = inventory["entries"]
    return {
        "cffi": _component_records(
            root, entries, ("_cffi_backend",), include_pe_imports=True
        ),
        "cpython": _component_records(
            root, entries, ("python314.dll", "base_library.zip")
        ),
        "cryptography": _component_records(
            root, entries, ("_internal/cryptography/",), include_pe_imports=True
        ),
        "customtkinter": {
            "license_in_distribution": any(
                entry["path"] == "Licencas/CUSTOMTKINTER_LICENSE.txt"
                for entry in entries
            ),
            "payload": _component_records(root, entries, ("_internal/customtkinter/",)),
            "review_status": "NEEDS_NOTICE_REVIEW",
        },
        "hooks_contrib": [
            hook
            for hook in archive.get("runtime_hooks", [])
            if hook.get("provenance") == "pyinstaller-hooks-contrib"
        ],
        "microsoft_runtime": _component_records(
            root,
            entries,
            ("vcruntime", "msvcp", "ucrtbase", "api-ms-win-"),
            include_pe_imports=True,
        ),
        "pillow": {
            "native_extensions": _component_records(
                root, entries, ("_internal/PIL/",), include_pe_imports=False
            ),
            "review_status": "RESOLVED_ALREADY",
            "version": "12.3.0",
        },
        "pyinstaller": {
            "bootloader": "EduDownloader.exe",
            "runtime_hooks": archive.get("runtime_hooks", []),
            "version": "6.21.0",
        },
        "pypdfium2": {
            "payload": _component_records(
                root,
                entries,
                ("_internal/pypdfium2", "pdfium.dll"),
                include_pe_imports=True,
            ),
            "review_status": "RESOLVED_ALREADY",
            "version": "5.12.1",
        },
        "tcl_tk": _component_records(
            root,
            entries,
            ("_tcl_data/", "_tk_data/", "tcl86", "tk86", "tcl9", "tk9"),
        ),
    }


def warning_classification(
    warnings_path: Path,
    baseline_path: Path,
    explained_path: Path,
) -> dict[str, Any]:
    baseline, baseline_issues = read_warning_baseline(baseline_path)
    explained, explained_issues = read_explained_warnings(explained_path)
    baseline_issues.extend(explained_issues)
    overlap = baseline & explained.keys()
    if overlap:
        baseline_issues.append("explained-warning-overlaps-historical-baseline")
    try:
        actual = parse_warning_entries(warnings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        actual = set()
        baseline_issues.append("warnings-report-unavailable")
    forbidden = sorted(
        entry
        for entry in actual
        if entry.partition("|")[2].casefold().startswith(FORBIDDEN_ARCHIVE_PREFIXES)
    )
    allowed = baseline | explained.keys()
    new = sorted(actual - allowed)
    missing = sorted(allowed - actual)
    return {
        "actual_count": len(actual),
        "baseline_count": len(baseline),
        "baseline_issues": sorted(baseline_issues),
        "expected": sorted(actual & baseline),
        "forbidden": forbidden,
        "missing_expected": missing,
        "new_blocking": sorted(set(new + forbidden)),
        "new_explained": [
            {"entry": entry, "reason": explained[entry]}
            for entry in sorted(actual & explained.keys())
        ],
        "status": (
            "PASS"
            if not baseline_issues and not new and not missing and not forbidden
            else "FAIL"
        ),
    }


def compare_inventories(
    pristine: Mapping[str, Any],
    after_smoke: Mapping[str, Any],
) -> dict[str, Any]:
    before_by_path = {entry["path"]: entry for entry in pristine["entries"]}
    after_by_path = {entry["path"]: entry for entry in after_smoke["entries"]}
    created = sorted(after_by_path.keys() - before_by_path.keys(), key=str.casefold)
    deleted = sorted(before_by_path.keys() - after_by_path.keys(), key=str.casefold)
    modified = sorted(
        path
        for path in before_by_path.keys() & after_by_path.keys()
        if before_by_path[path]["sha256"] != after_by_path[path]["sha256"]
        or before_by_path[path]["size_bytes"] != after_by_path[path]["size_bytes"]
    )
    unexpected = sorted(
        path for path in [*created, *modified] if path not in RUNTIME_ALLOWED_PATHS
    )
    return {
        "created": created,
        "deleted": deleted,
        "modified": modified,
        "runtime_changes_status": (
            "PASS" if not unexpected and not deleted else "FAIL"
        ),
        "unexpected": unexpected,
    }


def validate_inventory_against_manifest(
    candidate: Path,
    manifest_path: Path,
) -> list[str]:
    """Compare historical bytes without applying policy introduced later."""
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ["candidate-manifest-unavailable"]
    issues: list[str] = []
    if raw != canonical_json_bytes(manifest):
        issues.append("candidate-manifest-not-canonical")
    if manifest.get("pristine_inventory") != build_file_inventory(candidate):
        issues.append("candidate-pristine-inventory-mismatch")
    return sorted(set(issues))


def _delta_classification(path: str) -> tuple[str, str]:
    lowered = path.casefold()
    name = PurePosixPath(path).name.casefold()
    if (
        name == ".ds_store"
        or name == "ucrtbase.dll"
        or name.startswith("api-ms-win-core-")
        or name.startswith("api-ms-win-crt-")
        or name in {"vcruntime140.dll", "vcruntime140_1.dll"}
    ):
        return "PACKAGING_FIX", "controlled-runtime-composition"
    if lowered.startswith("licencas/"):
        return "NOTICE_DELIVERY_FIX", "d14a-notice-delivery"
    if path == "LICENSE":
        return "NOTICE_DELIVERY_FIX", "community-own-code-mit-license-delivery"
    if path in {"EduDownloader.exe", "README.txt"}:
        return "EXPECTED_SOURCE_EVOLUTION", "tracked-source-evolution"
    if path == "yt-dlp.exe":
        return "EXPECTED_EXTERNAL_BASELINE_UPDATE", "approved-yt-dlp-update"
    return "UNEXPECTED", "unclassified-composition-delta"


def _pillow_imagingft_issue(
    inventory: Mapping[str, Any], candidate_classification: str
) -> str | None:
    if candidate_classification not in {
        V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_5_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_PORTABILITY_PROBE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_7_VISUAL_PROBE_CLASSIFICATION,
        V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
    }:
        return None
    entry = next(
        (
            item
            for item in inventory["entries"]
            if item["path"] == V1_3_PILLOW_IMAGINGFT_PATH
        ),
        None,
    )
    if entry is None:
        return "expected-pillow-imagingft-missing"
    if (
        entry.get("sha256") != V1_3_PILLOW_IMAGINGFT_SHA256
        or entry.get("size_bytes") != V1_3_PILLOW_IMAGINGFT_SIZE
    ):
        return "expected-pillow-imagingft-provenance-mismatch"
    return None


def _visual_branding_issue(
    inventory: Mapping[str, Any], candidate_classification: str
) -> str | None:
    if candidate_classification not in {
        V1_7_VISUAL_PROBE_CLASSIFICATION,
        V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
    }:
        return None
    entry = next(
        (item for item in inventory["entries"] if item["path"] == V1_7_BRANDING_PATH),
        None,
    )
    if entry is None:
        return "v1.7-branding-asset-missing"
    if (
        entry.get("sha256") != V1_7_BRANDING_SHA256
        or entry.get("size_bytes") != V1_7_BRANDING_SIZE
    ):
        return "v1.7-branding-asset-mismatch"
    return None


def _zip_members_equal_ignoring_order(first: Path, second: Path) -> bool:
    """Compare ZIP members and stable metadata without trusting archive order."""

    def member_records(archive: zipfile.ZipFile) -> dict[str, tuple[Any, ...]]:
        records: dict[str, tuple[Any, ...]] = {}
        for info in archive.infolist():
            if info.filename in records:
                raise ValueError("duplicate ZIP member")
            records[info.filename] = (
                info.date_time,
                info.compress_type,
                info.comment,
                info.extra,
                info.create_system,
                info.external_attr,
                info.internal_attr,
                info.flag_bits,
                info.CRC,
                info.file_size,
                info.compress_size,
                hashlib.sha256(archive.read(info)).digest(),
            )
        return records

    try:
        with (
            zipfile.ZipFile(first) as first_archive,
            zipfile.ZipFile(second) as second_archive,
        ):
            return member_records(first_archive) == member_records(second_archive)
    except (OSError, ValueError, zipfile.BadZipFile):
        return False


def compare_candidate_composition(
    historical_inventory: Mapping[str, Any],
    current_inventory: Mapping[str, Any],
    *,
    historical_candidate: Path | None = None,
    current_candidate: Path | None = None,
    candidate_classification: str | None = None,
) -> dict[str, Any]:
    """Classify every byte-level difference from the historical candidate."""
    historical = {entry["path"]: entry for entry in historical_inventory["entries"]}
    current = {entry["path"]: entry for entry in current_inventory["entries"]}
    differences: list[dict[str, Any]] = []
    for path in sorted(set(historical) | set(current), key=str.casefold):
        before = historical.get(path)
        after = current.get(path)
        if before == after:
            continue
        classification, reason = _delta_classification(path)
        if (
            candidate_classification
            in {
                V1_7_VISUAL_PROBE_CLASSIFICATION,
                V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
            }
            and classification == "UNEXPECTED"
            and path == V1_7_BRANDING_PATH
            and before is None
            and after is not None
            and after.get("sha256") == V1_7_BRANDING_SHA256
            and after.get("size_bytes") == V1_7_BRANDING_SIZE
        ):
            classification = "EXPECTED_EXPLAINED"
            reason = "v1.7-approved-branding-asset"
        if (
            candidate_classification
            in {
                V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
                V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
                V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
                V1_5_RELEASE_CANDIDATE_CLASSIFICATION,
                V1_6_PORTABILITY_PROBE_CLASSIFICATION,
                V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
                V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
                V1_7_VISUAL_PROBE_CLASSIFICATION,
                V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
            }
            and path == V1_3_PILLOW_IMAGINGFT_PATH
            and before is None
            and after is not None
            and after.get("sha256") == V1_3_PILLOW_IMAGINGFT_SHA256
            and after.get("size_bytes") == V1_3_PILLOW_IMAGINGFT_SIZE
        ):
            classification = "EXPECTED_EXPLAINED"
            reason = "v1.3-poster-imagedraw-pillow-imagefont-optional-freetype"
        if (
            classification == "UNEXPECTED"
            and candidate_classification
            in {
                V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
                V1_5_RELEASE_CANDIDATE_CLASSIFICATION,
                V1_6_PORTABILITY_PROBE_CLASSIFICATION,
                V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
                V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
                V1_7_VISUAL_PROBE_CLASSIFICATION,
                V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
            }
            and path in {"ffmpeg.exe", "ffprobe.exe"}
            and after is not None
            and after.get("sha256") == V1_4_RC2_EXTERNAL_BINARY_BASELINE[path]["sha256"]
        ):
            classification = "EXPECTED_EXTERNAL_BASELINE_UPDATE"
            reason = "approved-btbn-ffmpeg-ffprobe-baseline"
        if (
            classification == "UNEXPECTED"
            and path == "_internal/base_library.zip"
            and historical_candidate is not None
            and current_candidate is not None
            and _zip_members_equal_ignoring_order(
                historical_candidate / PurePosixPath(path),
                current_candidate / PurePosixPath(path),
            )
        ):
            classification = "EXPECTED_EXPLAINED"
            reason = "equivalent-zip-members-reordered"
        change = "modified"
        if before is None:
            change = "added"
        elif after is None:
            change = "removed"
        differences.append(
            {
                "after": after,
                "before": before,
                "change": change,
                "classification": classification,
                "path": path,
                "reason": reason,
            }
        )
    counts: dict[str, int] = {}
    for item in differences:
        classification = item["classification"]
        counts[classification] = counts.get(classification, 0) + 1
    return {
        "classification_counts": dict(sorted(counts.items())),
        "differences": differences,
        "historical_inventory_sha256": historical_inventory["inventory_sha256"],
        "unexpected_count": counts.get("UNEXPECTED", 0),
    }


def audit_notice_delivery(candidate: Path) -> dict[str, Any]:
    """Record conservative physical delivery without legal conclusions."""
    licenses = candidate / "Licencas"

    def present(*paths: str) -> bool:
        return all((licenses / path).is_file() for path in paths)

    return {
        "cffi_cryptography": {
            "reason": "component-specific runtime notices are not delivered",
            "status": "PENDING_FIX",
        },
        "cpython_tcl_tk": {
            "reason": "component-specific runtime notices are not delivered",
            "status": "PENDING_FIX",
        },
        "customtkinter": {
            "reason": "component license is present; bundled font review remains separate",
            "status": (
                "PARTIAL" if present("CUSTOMTKINTER_LICENSE.txt") else "PENDING_FIX"
            ),
        },
        "deno": {
            "reason": "Deno license is present; third-party notice closure remains separate",
            "status": "PARTIAL" if present("DENO_LICENSE.txt") else "PENDING_FIX",
        },
        "microsoft": {
            "reason": "D13A notice template is not delivered pending P3 review",
            "status": "PENDING_FIX",
        },
        "other": {
            "reason": "delivered notices exist; remaining review is tracked separately",
            "status": "PARTIAL",
        },
        "pyinstaller": {
            "reason": "physical license files checked in the candidate",
            "status": (
                "DELIVERED"
                if present(
                    "PyInstaller/COPYING.txt",
                    "PyInstaller/ZLIB_LICENSE.txt",
                    "pyinstaller-hooks-contrib/LICENSE",
                )
                else "PENDING_FIX"
            ),
        },
    }


def record_build_environment(output: Path, initial_pip_file: Path) -> dict[str, Any]:
    """Capture the fresh environment without recording its personal path."""

    try:
        initial_pip = initial_pip_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        initial_pip = "UNKNOWN"
    packages = sorted(
        (
            {
                "name": distribution.metadata["Name"],
                "version": distribution.version,
            }
            for distribution in importlib.metadata.distributions()
        ),
        key=lambda item: item["name"].casefold(),
    )
    evidence = {
        "architecture": platform.machine(),
        "implementation": platform.python_implementation(),
        "packages": packages,
        "pip_final_version": importlib.metadata.version("pip"),
        "pip_initial_version": initial_pip,
        "python_executable": "build-env/Scripts/python.exe",
        "python_version": platform.python_version(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json_bytes(evidence))
    return evidence


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return value


def _compliance_gap_report(
    package_materiality: Iterable[Mapping[str, Any]],
    components: Mapping[str, Any],
    *,
    microsoft_runtime_distributed: bool,
) -> dict[str, list[str]]:
    build_only = sorted(
        str(record["package"])
        for record in package_materiality
        if record["classification"] in {"BUILD_ONLY", "BUILD_TOOL_ONLY"}
    )
    needs_source = [
        "CPython 3.14.6 frozen runtime and standard library",
        "PyInstaller 6.21.0 bootloader/runtime material",
        "Tcl/Tk runtime shipped with CPython",
    ]
    if microsoft_runtime_distributed:
        needs_source.append("Microsoft runtime DLLs physically redistributed")
    if components["cffi"]:
        needs_source.append("cffi 2.1.1 native _cffi_backend")
    if components["cryptography"]:
        needs_source.append("cryptography 49.0.0 Rust/native extension")
    needs_notice = [
        "CPython 3.14.6 and Tcl/Tk notices",
        "CustomTkinter installed metadata versus local license discrepancy",
        "Deno third-party notices",
        "PyInstaller bootloader and runtime-hook notices",
        "pyinstaller-hooks-contrib runtime material if listed",
    ]
    if microsoft_runtime_distributed:
        needs_notice.append("Microsoft runtime redistribution terms")
    return {
        "BUILD_ONLY_NOT_DISTRIBUTED": build_only,
        "EXTERNAL_COMPONENT_ALREADY_TRACKED": [
            "FFmpeg/FFprobe Gyan active baseline",
            "yt-dlp 2026.08.19",
            "Deno 2.9.5 (notice closure remains separate)",
        ],
        "NEEDS_NOTICE_REVIEW": needs_notice,
        "NEEDS_SOURCE_AUDIT": needs_source,
        "RESOLVED_ALREADY": [
            "Pillow 12.3.0 composition baseline",
            "pypdfium2 5.12.1 / PDFium source and license baseline",
            "yt-dlp 2026.08.19 source correspondence",
        ],
        "SYSTEM_RUNTIME": [
            "Windows system imports referenced by PE files",
            "Microsoft DLLs listed separately only when physically shipped",
        ],
    }


def build_candidate_manifest(
    candidate: Path,
    *,
    source_commit: str,
    warnings_path: Path,
    warning_baseline_path: Path,
    warning_explained_path: Path,
    analysis_toc: Path,
    build_environment_path: Path,
    wheel_manifest_path: Path,
    hash_lock_path: Path,
    microsoft_runtime_manifest_path: Path,
    historical_manifest_path: Path,
    historical_candidate_path: Path,
    comparison_manifest_path: Path,
    comparison_candidate_path: Path,
    notice_inventory_path: Path,
    candidate_classification: str,
    smoke_result: str,
    packed_ytdlp_smoke_result: str,
    spec_path: Path,
    pipeline_path: Path,
    after_smoke: Path | None = None,
    packed_ytdlp_smoke_output: Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    resolved = candidate.resolve()
    issues: list[str] = []
    inventory = build_file_inventory(resolved)
    pillow_imagingft_issue = _pillow_imagingft_issue(
        inventory, candidate_classification
    )
    if pillow_imagingft_issue is not None:
        issues.append(pillow_imagingft_issue)
    branding_issue = _visual_branding_issue(inventory, candidate_classification)
    if branding_issue is not None:
        issues.append(branding_issue)
    external, external_issues = inspect_external_binaries(
        resolved, _external_baseline_for_classification(candidate_classification)
    )
    issues.extend(external_issues)
    contamination = find_contamination_issues(resolved)
    issues.extend(contamination)
    distribution_issues = find_distribution_issues(resolved)
    issues.extend(f"distribution:{issue}" for issue in distribution_issues)
    archive, archive_issues = inspect_frozen_archives(
        resolved / "EduDownloader.exe", analysis_toc
    )
    issues.extend(archive_issues)
    issues.extend(find_v1_4_archive_issues(archive, candidate_classification))
    issues.extend(find_v1_5_archive_issues(archive, candidate_classification))
    warning_report = warning_classification(
        warnings_path,
        warning_baseline_path,
        warning_explained_path,
    )
    if warning_report["status"] != "PASS":
        issues.append("pyinstaller-warning-baseline-mismatch")

    package_materiality = classify_package_materiality(
        archive.get("pyz_modules", []),
        (entry["path"] for entry in inventory["entries"]),
        archive.get("runtime_hooks", []),
    )
    components = build_component_evidence(resolved, inventory, archive)
    wheel_manifest = _load_json(wheel_manifest_path)
    microsoft_runtime_manifest = _load_json(microsoft_runtime_manifest_path)
    historical_manifest = _load_json(historical_manifest_path)
    comparison_manifest = _load_json(comparison_manifest_path)
    build_environment = _load_json(build_environment_path)
    if len(build_environment.get("packages", [])) != 17:
        issues.append("offline-build-environment-package-count-mismatch")
    if (
        source_commit != source_commit.casefold()
        or not EXPECTED_SOURCE_COMMIT_PATTERN.fullmatch(source_commit)
    ):
        issues.append("source-commit-invalid")
    if candidate_classification not in ALLOWED_CANDIDATE_CLASSIFICATIONS:
        issues.append("candidate-classification-invalid")
    if candidate_classification in {
        V1_6_PORTABILITY_PROBE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_7_VISUAL_PROBE_CLASSIFICATION,
    } and (APP_VERSION != "1.6.0" or PRODUCT_EDITION.value != "community"):
        issues.append(
            "probe-application-contract-mismatch"
            if candidate_classification
            in {
                V1_6_PORTABILITY_PROBE_CLASSIFICATION,
                V1_7_VISUAL_PROBE_CLASSIFICATION,
            }
            else "v1.6-rc-application-contract-mismatch"
        )
    if candidate_classification == V1_7_RELEASE_CANDIDATE_CLASSIFICATION and (
        APP_VERSION != "1.7.0" or PRODUCT_EDITION.value != "community"
    ):
        issues.append("v1.7-rc-application-contract-mismatch")
    if smoke_result not in ALLOWED_SMOKE_RESULTS:
        issues.append("controlled-smoke-result-invalid")
    if packed_ytdlp_smoke_result not in ALLOWED_PACKED_YTDLP_SMOKE_RESULTS:
        issues.append("packed-ytdlp-smoke-result-invalid")

    packed_ytdlp_smoke: dict[str, Any] = {
        "case": "PUBLIC_BASIC_CASE",
        "cookies_or_login": False,
        "remote_components": False,
        "result": packed_ytdlp_smoke_result,
        "section": "1s-9s",
        "video_id": "YE7VzlLtp-4",
    }
    if packed_ytdlp_smoke_result == "PASS":
        if packed_ytdlp_smoke_output is None or not packed_ytdlp_smoke_output.is_file():
            issues.append("packed-ytdlp-smoke-output-missing")
        else:
            packed_ytdlp_smoke["output"] = {
                "sha256": sha256_file(packed_ytdlp_smoke_output),
                "size_bytes": packed_ytdlp_smoke_output.stat().st_size,
            }
    elif packed_ytdlp_smoke_output is not None:
        issues.append("packed-ytdlp-smoke-output-unexpected")

    historical_comparison = compare_candidate_composition(
        historical_manifest["pristine_inventory"],
        inventory,
        historical_candidate=historical_candidate_path.resolve(),
        current_candidate=resolved,
        candidate_classification=candidate_classification,
    )
    if historical_comparison["unexpected_count"]:
        issues.append("unexpected-historical-composition-delta")
    r2_comparison = compare_candidate_composition(
        comparison_manifest["pristine_inventory"],
        inventory,
        historical_candidate=comparison_candidate_path.resolve(),
        current_candidate=resolved,
        candidate_classification=candidate_classification,
    )
    if r2_comparison["unexpected_count"]:
        issues.append("unexpected-r2-composition-delta")
    notice_delivery_issues = find_candidate_delivery_issues(resolved)
    issues.extend(f"notice-delivery:{issue}" for issue in notice_delivery_issues)
    notice_record = candidate_delivery_record(resolved)
    if sha256_file(notice_inventory_path) != notice_record["inventory"]["sha256"]:
        issues.append("notice-delivery-inventory-authority-mismatch")

    microsoft_entries = [
        entry for entry in inventory["entries"] if entry["group"] == "microsoft_runtime"
    ]
    microsoft_names = {
        PurePosixPath(entry["path"]).name.casefold() for entry in microsoft_entries
    }
    api_set_count = sum(
        name.startswith("api-ms-win-core-") or name.startswith("api-ms-win-crt-")
        for name in microsoft_names
    )
    ucrt_count = sum(name == "ucrtbase.dll" for name in microsoft_names)
    ds_store_count = sum(
        PurePosixPath(entry["path"]).name.casefold() == ".ds_store"
        for entry in inventory["entries"]
    )

    after_smoke_record: dict[str, Any] | None = None
    if after_smoke is not None:
        after_inventory = build_file_inventory(after_smoke.resolve())
        comparison = compare_inventories(inventory, after_inventory)
        if comparison["runtime_changes_status"] != "PASS":
            issues.append("after-smoke-runtime-changes-unexpected")
        after_smoke_record = {
            "comparison": comparison,
            "file_count": after_inventory["file_count"],
            "inventory_sha256": after_inventory["inventory_sha256"],
            "total_size_bytes": after_inventory["total_size_bytes"],
        }

    manifest = {
        "after_smoke": after_smoke_record,
        "application": {
            "activation_required_for_current_edition": False,
            "app_version": APP_VERSION,
            "name": APP_NAME,
            "product_edition": PRODUCT_EDITION.value,
        },
        "archive_composition": archive,
        "build_provenance": {
            "build_environment": build_environment,
            "build_timestamp_utc": datetime.now(UTC).isoformat(),
            "configuration": {
                "pipeline": {
                    "path": pipeline_path.name,
                    "sha256": sha256_file(pipeline_path),
                },
                "microsoft_runtime": {
                    "manifest_path": "docs/compliance/microsoft/"
                    + microsoft_runtime_manifest_path.name,
                    "manifest_sha256": sha256_file(microsoft_runtime_manifest_path),
                },
                "notice_delivery_inventory": {
                    "path": "docs/compliance/notices/NOTICE_DELIVERY_INVENTORY.json",
                    "sha256": sha256_file(notice_inventory_path),
                },
                "pyinstaller_spec": {
                    "path": spec_path.name,
                    "sha256": sha256_file(spec_path),
                },
                "warning_baseline": {
                    "path": warning_baseline_path.name,
                    "sha256": sha256_file(warning_baseline_path),
                },
                "warning_explained": {
                    "path": warning_explained_path.name,
                    "sha256": sha256_file(warning_explained_path),
                },
            },
            "offline_install_policy": {
                "find_links_wheelhouse_only": True,
                "no_index": True,
                "require_hashes": True,
            },
            "operating_system": {
                "machine": platform.machine(),
                "release": platform.release(),
                "system": platform.system(),
                "version": platform.version(),
            },
            "pipeline_version": PIPELINE_VERSION,
            "source_commit": source_commit,
            "wheel_provenance": {
                "capture_classification": wheel_manifest["capture_classification"],
                "file_count": wheel_manifest["wheelhouse"]["file_count"],
                "hash_lock_sha256": sha256_file(hash_lock_path),
                "inventory_sha256": wheel_manifest["wheelhouse"]["inventory_sha256"],
                "manifest_path": "docs/compliance/python/PYTHON_WHEEL_PROVENANCE.json",
                "manifest_sha256": sha256_file(wheel_manifest_path),
                "total_size_bytes": wheel_manifest["wheelhouse"]["total_size"],
            },
        },
        "candidate_classification": candidate_classification,
        "controlled_smoke": {
            "packed_ytdlp": packed_ytdlp_smoke,
            "result": smoke_result,
        },
        "compliance_gaps": _compliance_gap_report(
            package_materiality,
            components,
            microsoft_runtime_distributed=bool(microsoft_entries),
        ),
        "components": components,
        "contamination": {
            "issues": contamination,
            "private_material_status": "PASS" if not contamination else "FAIL",
            "status": "PASS" if not contamination else "FAIL",
        },
        "controlled_packaging": {
            "api_set_distributed_count": api_set_count,
            "ds_store_count": ds_store_count,
            "microsoft_dynamic_runtime_file_count": len(microsoft_entries),
            "microsoft_dynamic_runtime_files": sorted(microsoft_names),
            "microsoft_dynamic_runtime_total_size_bytes": sum(
                entry["size_bytes"] for entry in microsoft_entries
            ),
            "ucrt_distributed_count": ucrt_count,
            "windows_baseline": microsoft_runtime_manifest["baseline"][
                "supported_windows"
            ],
        },
        "external_binaries": external,
        "gates": {
            "activation_operational": True,
            "default_trust_store_key_count": 1,
            "operational_private_key_configured": False,
            "operational_public_key_configured": True,
            "production_crypto_configured": True,
            "production_ready": False,
            "public_release_allowed": False,
        },
        "group_summaries": summarize_groups(inventory["entries"]),
        "package_materiality": package_materiality,
        "microsoft_runtime_packaging": {
            "baseline": microsoft_runtime_manifest["baseline"],
            "distribution_model": microsoft_runtime_manifest.get(
                "distribution_model", "DIRECT_DISTRIBUTION_HISTORICAL"
            ),
            "policies": microsoft_runtime_manifest["policies"],
            "runtime_files": microsoft_runtime_manifest["runtime_files"],
            "status": microsoft_runtime_manifest["status"],
            "vc_runtime_authority": microsoft_runtime_manifest["vc_runtime_authority"],
        },
        "notice_delivery": notice_record,
        "historical_comparison": historical_comparison,
        "r2_comparison": r2_comparison,
        "pristine_inventory": inventory,
        "schema_version": SCHEMA_VERSION,
        "warning_classification": warning_report,
    }
    if candidate_classification == V1_6_PORTABILITY_PROBE_CLASSIFICATION:
        manifest["probe_contract"] = {
            "is_release_candidate": False,
            "rc_number": "NONE",
            "purpose": "PORTABILITY_AND_VC_RUNTIME",
        }
    elif candidate_classification == V1_7_VISUAL_PROBE_CLASSIFICATION:
        manifest["probe_contract"] = {
            "is_release_candidate": False,
            "rc_number": "NONE",
            "purpose": "V1_7_VISUAL_BRANDING",
        }
    elif candidate_classification == V1_7_RELEASE_CANDIDATE_CLASSIFICATION:
        manifest["rc_contract"] = {"is_release_candidate": True, "rc_number": 1}
    elif candidate_classification in {
        V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
    }:
        manifest["rc_contract"] = {
            "is_release_candidate": True,
            "rc_number": (
                1
                if candidate_classification == V1_6_RELEASE_CANDIDATE_CLASSIFICATION
                else 2
            ),
        }
    serialized = canonical_json_bytes(manifest).decode("utf-8")
    if ABSOLUTE_WINDOWS_PATH_PATTERN.search(serialized):
        issues.append("absolute-local-path-in-manifest")
    return manifest, sorted(set(issues))


def validate_candidate_manifest(
    candidate: Path,
    manifest_path: Path,
    *,
    expected_classification: str = CANDIDATE_CLASSIFICATION,
) -> list[str]:
    issues: list[str] = []
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ["candidate-manifest-unavailable"]
    if raw != canonical_json_bytes(manifest):
        issues.append("candidate-manifest-not-canonical")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        issues.append("candidate-manifest-schema-mismatch")
    if expected_classification not in ALLOWED_CANDIDATE_CLASSIFICATIONS:
        issues.append("candidate-classification-expectation-invalid")
    if manifest.get("candidate_classification") != expected_classification:
        issues.append("candidate-classification-mismatch")
    if expected_classification == V1_6_PORTABILITY_PROBE_CLASSIFICATION and (
        manifest.get("probe_contract")
        != {
            "is_release_candidate": False,
            "rc_number": "NONE",
            "purpose": "PORTABILITY_AND_VC_RUNTIME",
        }
    ):
        issues.append("probe-contract-mismatch")
    if expected_classification == V1_7_VISUAL_PROBE_CLASSIFICATION and (
        manifest.get("probe_contract")
        != {
            "is_release_candidate": False,
            "rc_number": "NONE",
            "purpose": "V1_7_VISUAL_BRANDING",
        }
        or "rc_contract" in manifest
    ):
        issues.append("v1.7-probe-contract-mismatch")
    if expected_classification == V1_7_RELEASE_CANDIDATE_CLASSIFICATION and (
        manifest.get("rc_contract") != {"is_release_candidate": True, "rc_number": 1}
        or "probe_contract" in manifest
    ):
        issues.append("v1.7-rc-contract-mismatch")
    if expected_classification in {
        V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
    }:
        expected_rc_number = (
            1 if expected_classification == V1_6_RELEASE_CANDIDATE_CLASSIFICATION else 2
        )
        if (
            manifest.get("rc_contract")
            != {
                "is_release_candidate": True,
                "rc_number": expected_rc_number,
            }
            or "probe_contract" in manifest
        ):
            issues.append("v1.6-rc-contract-mismatch")
    if manifest.get("application", {}).get("app_version") != APP_VERSION:
        issues.append("candidate-app-version-mismatch")
    if manifest.get("application", {}).get("product_edition") != PRODUCT_EDITION.value:
        issues.append("candidate-edition-mismatch")
    if expected_classification == V1_7_RELEASE_CANDIDATE_CLASSIFICATION:
        application = manifest.get("application", {})
        if (
            application.get("app_version") != "1.7.0"
            or application.get("product_edition") != "community"
            or application.get("activation_required_for_current_edition") is not False
        ):
            issues.append("v1.7-rc-application-contract-mismatch")
        if (
            manifest.get("controlled_packaging", {}).get(
                "microsoft_dynamic_runtime_file_count"
            )
            != 0
        ):
            issues.append("v1.7-rc-direct-microsoft-runtime-present")
    if expected_classification in {
        V1_6_PORTABILITY_PROBE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_7_VISUAL_PROBE_CLASSIFICATION,
    }:
        application = manifest.get("application", {})
        if (
            application.get("app_version") != "1.6.0"
            or application.get("product_edition") != "community"
            or application.get("activation_required_for_current_edition") is not False
        ):
            issues.append(
                "probe-application-contract-mismatch"
                if expected_classification
                in {
                    V1_6_PORTABILITY_PROBE_CLASSIFICATION,
                    V1_7_VISUAL_PROBE_CLASSIFICATION,
                }
                else "v1.6-rc-application-contract-mismatch"
            )
        if (
            manifest.get("controlled_packaging", {}).get(
                "microsoft_dynamic_runtime_file_count"
            )
            != 0
        ):
            issues.append(
                "probe-direct-microsoft-runtime-present"
                if expected_classification == V1_6_PORTABILITY_PROBE_CLASSIFICATION
                else "v1.6-rc-direct-microsoft-runtime-present"
            )
    if manifest.get("gates", {}).get("production_ready") is not False:
        issues.append("production-gate-open")
    if manifest.get("gates", {}).get("public_release_allowed") is not False:
        issues.append("public-release-gate-open")
    actual_inventory = build_file_inventory(candidate)
    if manifest.get("pristine_inventory") != actual_inventory:
        issues.append("candidate-pristine-inventory-mismatch")
    pillow_imagingft_issue = _pillow_imagingft_issue(
        actual_inventory, expected_classification
    )
    if pillow_imagingft_issue is not None:
        issues.append(pillow_imagingft_issue)
    branding_issue = _visual_branding_issue(actual_inventory, expected_classification)
    if branding_issue is not None:
        issues.append(branding_issue)
    if expected_classification in {
        NOTICE_COMPLETE_CANDIDATE_CLASSIFICATION,
        V1_0_RELEASE_CANDIDATE_CLASSIFICATION,
        RELEASE_CANDIDATE_CLASSIFICATION,
        RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        RELEASE_CANDIDATE_RC3_CLASSIFICATION,
        V1_2_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_3_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_4_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_4_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_5_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_PORTABILITY_PROBE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_CLASSIFICATION,
        V1_6_RELEASE_CANDIDATE_RC2_CLASSIFICATION,
        V1_7_VISUAL_PROBE_CLASSIFICATION,
        V1_7_RELEASE_CANDIDATE_CLASSIFICATION,
    }:
        issues.extend(find_candidate_delivery_issues(candidate))
        if (
            manifest.get("notice_delivery", {}).get("physical_delivery_status")
            != "COMPLETE_FOR_D14A_ALLOWLIST"
        ):
            issues.append("candidate-notice-delivery-not-complete")
    issues.extend(
        find_v1_4_archive_issues(
            manifest.get("archive_composition", {}), expected_classification
        )
    )
    issues.extend(
        find_v1_5_archive_issues(
            manifest.get("archive_composition", {}), expected_classification
        )
    )
    _external, external_issues = inspect_external_binaries(
        candidate, _external_baseline_for_classification(expected_classification)
    )
    issues.extend(external_issues)
    issues.extend(find_contamination_issues(candidate))
    serialized = raw.decode("utf-8", errors="replace")
    if ABSOLUTE_WINDOWS_PATH_PATTERN.search(serialized):
        issues.append("absolute-local-path-in-manifest")
    return sorted(set(issues))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _parse_arguments(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida e inventaria o frozen analysis candidate."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    contract = commands.add_parser("candidate-contract")
    contract.add_argument("--project-root", type=Path, required=True)
    contract.add_argument("--candidate-id", required=True)

    prepare = commands.add_parser("prepare-candidate-root")
    prepare.add_argument("--project-root", type=Path, required=True)
    prepare.add_argument("--candidate-id", required=True)
    prepare.add_argument("--target", type=Path, required=True)

    externals = commands.add_parser("validate-externals")
    externals.add_argument("--root", type=Path, required=True)

    environment = commands.add_parser("record-environment")
    environment.add_argument("--output", type=Path, required=True)
    environment.add_argument("--initial-pip-file", type=Path, required=True)

    write = commands.add_parser("write-manifest")
    write.add_argument("--candidate", type=Path, required=True)
    write.add_argument("--manifest", type=Path, required=True)
    write.add_argument("--source-commit", required=True)
    write.add_argument("--warnings", type=Path, required=True)
    write.add_argument("--warning-baseline", type=Path, required=True)
    write.add_argument("--warning-explained", type=Path, required=True)
    write.add_argument("--analysis-toc", type=Path, required=True)
    write.add_argument("--build-environment", type=Path, required=True)
    write.add_argument("--wheel-manifest", type=Path, required=True)
    write.add_argument("--hash-lock", type=Path, required=True)
    write.add_argument("--microsoft-runtime-manifest", type=Path, required=True)
    write.add_argument("--historical-manifest", type=Path, required=True)
    write.add_argument("--historical-candidate", type=Path, required=True)
    write.add_argument("--comparison-manifest", type=Path, required=True)
    write.add_argument("--comparison-candidate", type=Path, required=True)
    write.add_argument("--notice-inventory", type=Path, required=True)
    write.add_argument(
        "--classification",
        choices=sorted(ALLOWED_CANDIDATE_CLASSIFICATIONS),
        required=True,
    )
    write.add_argument(
        "--smoke-result", choices=sorted(ALLOWED_SMOKE_RESULTS), required=True
    )
    write.add_argument(
        "--packed-ytdlp-smoke-result",
        choices=sorted(ALLOWED_PACKED_YTDLP_SMOKE_RESULTS),
        default="NOT_RUN",
    )
    write.add_argument("--packed-ytdlp-smoke-output", type=Path)
    write.add_argument("--spec", type=Path, required=True)
    write.add_argument("--pipeline", type=Path, required=True)
    write.add_argument("--pristine-snapshot", type=Path)
    write.add_argument("--after-smoke", type=Path)
    write.add_argument("--after-smoke-snapshot", type=Path)

    validate = commands.add_parser("validate-manifest")
    validate.add_argument("--candidate", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument(
        "--classification",
        choices=sorted(ALLOWED_CANDIDATE_CLASSIFICATIONS),
        default=CANDIDATE_CLASSIFICATION,
    )
    inventory = commands.add_parser("validate-inventory")
    inventory.add_argument("--candidate", type=Path, required=True)
    inventory.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parse_arguments(arguments)
    if args.command == "candidate-contract":
        try:
            environment = candidate_contract_environment(
                args.project_root, args.candidate_id
            )
        except ValueError as exc:
            print(exc)
            return 1
        for name, value in sorted(environment.items()):
            print(f"{name}={value}")
        return 0
    if args.command == "prepare-candidate-root":
        try:
            prepare_candidate_root(args.project_root, args.candidate_id, args.target)
        except (OSError, ValueError) as exc:
            print(f"Candidate cleanup rejected: {exc}")
            return 1
        print("Candidate cleanup target validated and prepared.")
        return 0
    if args.command == "validate-externals":
        records, issues = inspect_external_binaries(
            args.root, V1_4_RC2_EXTERNAL_BINARY_BASELINE
        )
        if issues:
            for issue in issues:
                print(issue)
            return 1
        print(f"External binaries validated: {len(records)}")
        return 0
    if args.command == "record-environment":
        evidence = record_build_environment(args.output, args.initial_pip_file)
        print(
            f"Offline build environment recorded: {len(evidence['packages'])} packages"
        )
        return 0
    if args.command == "validate-inventory":
        issues = validate_inventory_against_manifest(args.candidate, args.manifest)
        if issues:
            print("Candidate inventory rejected:")
            for issue in issues:
                print(f"- {issue}")
            return 1
        print("Candidate inventory matches its immutable manifest.")
        return 0
    if args.command == "write-manifest":
        manifest, issues = build_candidate_manifest(
            args.candidate,
            source_commit=args.source_commit,
            warnings_path=args.warnings,
            warning_baseline_path=args.warning_baseline,
            warning_explained_path=args.warning_explained,
            analysis_toc=args.analysis_toc,
            build_environment_path=args.build_environment,
            wheel_manifest_path=args.wheel_manifest,
            hash_lock_path=args.hash_lock,
            microsoft_runtime_manifest_path=args.microsoft_runtime_manifest,
            historical_manifest_path=args.historical_manifest,
            historical_candidate_path=args.historical_candidate,
            comparison_manifest_path=args.comparison_manifest,
            comparison_candidate_path=args.comparison_candidate,
            notice_inventory_path=args.notice_inventory,
            candidate_classification=args.classification,
            smoke_result=args.smoke_result,
            packed_ytdlp_smoke_result=args.packed_ytdlp_smoke_result,
            spec_path=args.spec,
            pipeline_path=args.pipeline,
            after_smoke=args.after_smoke,
            packed_ytdlp_smoke_output=args.packed_ytdlp_smoke_output,
        )
        if issues:
            print("Frozen candidate rejected:")
            for issue in issues:
                print(f"- {issue}")
            return 1
        _write_json(args.manifest, manifest)
        if args.pristine_snapshot is not None:
            _write_json(args.pristine_snapshot, manifest["pristine_inventory"])
        if args.after_smoke is not None and args.after_smoke_snapshot is not None:
            _write_json(
                args.after_smoke_snapshot,
                build_file_inventory(args.after_smoke.resolve()),
            )
        print(
            "Frozen candidate inventory recorded: "
            f"{manifest['pristine_inventory']['file_count']} files; "
            f"inventory_sha256={manifest['pristine_inventory']['inventory_sha256']}"
        )
        return 0

    issues = validate_candidate_manifest(
        args.candidate,
        args.manifest,
        expected_classification=args.classification,
    )
    if issues:
        print("Frozen candidate manifest rejected:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Frozen candidate manifest validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
