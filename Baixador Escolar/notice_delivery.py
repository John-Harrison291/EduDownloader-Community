"""Prepara, entrega e valida a árvore de notices do candidato Community.

``prepare`` usa somente evidências locais preservadas; ``stage`` copia a
allowlist D14A para um candidato novo. ``validate`` e ``validate-candidate``
operam offline e falham de forma fechada diante de qualquer divergência.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent
LICENSE_ROOT = PROJECT_ROOT / "Licencas"
INVENTORY_PATH = (
    PROJECT_ROOT / "docs" / "compliance" / "notices" / "NOTICE_DELIVERY_INVENTORY.json"
)
R2_COMPOSITION_PATH = (
    PROJECT_ROOT / "docs" / "compliance" / "notices" / "NOTICE_BASELINE.json"
)

R2_INVENTORY_SHA256 = "2977A447168A9E82B97A1691648DBB3DBEE434002BEDDFE3C86609FAFE755AF3"
HISTORICAL_INVENTORY_SHA256 = (
    "26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857"
)

GENERATED_TEXT_ARTIFACTS = (
    "CPYTHON_RUNTIME_NOTICES.txt",
    "CRYPTOGRAPHY_CFFI_THIRD_PARTY_NOTICES.txt",
    "CUSTOMTKINTER_THIRD_PARTY_NOTICES.txt",
    "FFMPEG_BTBN_NOTICE.txt",
    "MICROSOFT_RUNTIME_NOTICE.txt",
    "PACKAGING_LICENSES.txt",
    "TCL_LICENSES.txt",
    "THIRD_PARTY_NOTICES.txt",
    "THIRD_PARTY_SOURCE_INFORMATION.txt",
    "TK_LICENSE.txt",
)

GLOBAL_DELIVERY_ARTIFACTS = ("THIRD_PARTY_NOTICES.txt",)

PYPDFIUM2_ARTIFACTS = (
    "PYPDFIUM2_LICENSES/LICENSES/Apache-2.0.txt",
    "PYPDFIUM2_LICENSES/LICENSES/BSD-3-Clause.txt",
    "PYPDFIUM2_LICENSES/LICENSES/CC-BY-4.0.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/abseil.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/agg23.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/fast_float.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/freetype.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/icu.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/lcms.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/libjpeg_turbo.ijg",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/libjpeg_turbo.md",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/libopenjpeg.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/libpng.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/libtiff.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/llvm-libc.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/pdfium-binaries.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/pdfium.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/simdutf.txt",
    "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/zlib.txt",
)

SOURCE_ONLY_LICENSE_ARTIFACTS = (
    "yt-dlp/COMPOSITION.md",
    "yt-dlp/PROVENANCE.json",
    "yt-dlp/SHA2-256SUMS",
    "yt-dlp/SOURCE_CORRESPONDENCE.md",
    "yt-dlp/SOURCE_PROVENANCE.json",
)


def _family_specs() -> tuple[dict[str, Any], ...]:
    return (
        {
            "component": "Microsoft Visual C++ Runtime",
            "version": "Compatible x64 v14 runtime installed by the user/system",
            "runtime_components": ["Microsoft Visual C++ Runtime"],
            "distributed_material": [],
            "license_identity": "External system prerequisite; Microsoft terms apply to the user's installation",
            "notice_identity": "DIRECT_DLLS_NOT_DISTRIBUTED_TRANSITIVE_RISK_RECORDED",
            "delivery_artifacts": ["MICROSOFT_RUNTIME_NOTICE.txt"],
            "source_authority": "Microsoft official installation guidance; no installer redistributed",
            "delivery_status": "PREREQUISITE_INSTRUCTIONS",
            "review_status": "DIRECT_CLOSED_TRANSITIVE_RECORDED_RISK",
        },
        {
            "component": "CPython runtime",
            "version": "3.14.6",
            "runtime_components": ["CPython"],
            "distributed_material": [
                "python314.dll",
                "base_library.zip",
                "stdlib extensions",
            ],
            "license_identity": "Python-2.0 and exact bundled-component texts",
            "notice_identity": "RESOLVED",
            "delivery_artifacts": ["CPYTHON_RUNTIME_NOTICES.txt"],
            "source_authority": "CPython 3.14.6 source correspondence D3",
            "delivery_status": "PREPARED_NOT_DELIVERED",
            "review_status": "P3_REQUIRED",
        },
        {
            "component": "Tcl",
            "version": "8.6.15.0",
            "runtime_components": ["Tcl"],
            "distributed_material": ["tcl86t.dll", "_tcl_data"],
            "license_identity": "Tcl license terms and bundled zlib/libtommath texts",
            "notice_identity": "RESOLVED",
            "delivery_artifacts": ["TCL_LICENSES.txt"],
            "source_authority": "CPython/Tcl-Tk source correspondence D3",
            "delivery_status": "PREPARED_NOT_DELIVERED",
            "review_status": "P3_REQUIRED",
        },
        {
            "component": "Tk",
            "version": "8.6.15.0",
            "runtime_components": ["Tk"],
            "distributed_material": ["tk86t.dll", "_tk_data"],
            "license_identity": "Tk license terms",
            "notice_identity": "RESOLVED",
            "delivery_artifacts": ["TK_LICENSE.txt"],
            "source_authority": "CPython/Tcl-Tk source correspondence D3",
            "delivery_status": "PREPARED_NOT_DELIVERED",
            "review_status": "P3_REQUIRED",
        },
        {
            "component": "PyInstaller and hooks",
            "version": "6.21.0 / 2026.6",
            "runtime_components": ["pyinstaller", "pyinstaller-hooks-contrib"],
            "distributed_material": ["EduDownloader.exe bootloader", "runtime hooks"],
            "license_identity": "PyInstaller GPL-2.0-or-later; bootloader exception for frozen applications; bundled runtime hooks Apache-2.0 (analysis hooks are build-time)",
            "notice_identity": "RESOLVED",
            "delivery_artifacts": [
                "PyInstaller/COPYING.txt",
                "PyInstaller/ZLIB_LICENSE.txt",
                "pyinstaller-hooks-contrib/LICENSE",
            ],
            "source_authority": "PyInstaller/hooks source correspondence D4",
            "delivery_status": "DELIVERED_IN_R2_AND_RETAINED",
            "review_status": "P3_REQUIRED",
        },
        {
            "component": "cffi and cryptography closure",
            "version": "cffi 2.1.1 / cryptography 49.0.0 / OpenSSL 4.0.1 / Rust 1.96.0",
            "runtime_components": ["cffi", "cryptography"],
            "distributed_material": ["_cffi_backend.pyd", "cryptography _rust.pyd"],
            "license_identity": "cffi MIT-0; cryptography Apache-2.0 OR BSD-3-Clause; OpenSSL Apache-2.0; Rust/crates per exact closure notices (alternative licenses and exceptions retained)",
            "notice_identity": "RESOLVED",
            "delivery_artifacts": ["CRYPTOGRAPHY_CFFI_THIRD_PARTY_NOTICES.txt"],
            "source_authority": "cffi/cryptography source correspondence D6",
            "delivery_status": "PREPARED_NOT_DELIVERED",
            "review_status": "P3_REQUIRED",
        },
        {
            "component": "Deno",
            "version": "2.9.5 x86_64-pc-windows-msvc",
            "runtime_components": ["Deno"],
            "distributed_material": ["deno.exe"],
            "license_identity": "Resolved; 916 upstream texts and four canonical SPDX references",
            "notice_identity": "RESOLVED_WITH_15_UPSTREAM_TEXT_GAPS",
            "delivery_artifacts": [
                "DENO_LICENSE.txt",
                "deno/DENO_THIRD_PARTY_NOTICES.txt",
            ],
            "source_authority": "Deno 2.9.5 D11I review bundle and D11H SPDX policy",
            "delivery_status": "PARTIAL_PREPARED_NOT_DELIVERED",
            "review_status": "P3_REQUIRED",
        },
        {
            "component": "CustomTkinter",
            "version": "5.2.2",
            "runtime_components": ["customtkinter"],
            "distributed_material": [
                "Python package",
                "Roboto fonts",
                "shape font",
                "icon",
            ],
            "license_identity": "MIT evidence plus resolved Roboto/Digsby texts",
            "notice_identity": "PARTIAL_ROBOTO_PRODUCER_PENDING",
            "delivery_artifacts": [
                "CUSTOMTKINTER_LICENSE.txt",
                "CUSTOMTKINTER_THIRD_PARTY_NOTICES.txt",
            ],
            "source_authority": "CustomTkinter source correspondence D8",
            "delivery_status": "PARTIAL_PREPARED_NOT_DELIVERED",
            "review_status": "ROBOTO_PRODUCER_PENDING_AND_P3_REQUIRED",
        },
        {
            "component": "Pillow",
            "version": "13.0.0",
            "runtime_components": ["pillow"],
            "distributed_material": [
                "PIL Python modules and material native extensions"
            ],
            "license_identity": "MIT-CMU with wheel-provided component notices",
            "notice_identity": "RESOLVED",
            "delivery_artifacts": [
                "PILLOW_COMPOSITION.md",
                "PILLOW_LICENSE.txt",
                "PILLOW_SBOM.cdx.json",
            ],
            "source_authority": "Pillow 13.0.0 approved Windows x64 wheel",
            "delivery_status": "PREPARED_FOR_CURRENT_BUILDS",
            "review_status": "P3_REQUIRED",
        },
        {
            "component": "pypdfium2/PDFium",
            "version": "5.12.1",
            "runtime_components": ["pypdfium2"],
            "distributed_material": ["pypdfium2 Python modules", "pdfium.dll"],
            "license_identity": "Apache-2.0/BSD-3-Clause and exact PDFium build notices",
            "notice_identity": "RESOLVED",
            "delivery_artifacts": list(PYPDFIUM2_ARTIFACTS),
            "source_authority": "pypdfium2 wheel-provided LICENSES tree",
            "delivery_status": "PREPARED_AND_PRESENT_IN_R2",
            "review_status": "P3_REQUIRED",
        },
        {
            "component": "yt-dlp",
            "version": "2026.08.19",
            "runtime_components": ["yt-dlp"],
            "distributed_material": ["yt-dlp.exe"],
            "license_identity": "Unlicense plus exact embedded-runtime third-party texts",
            "notice_identity": "RESOLVED",
            "delivery_artifacts": [
                "yt-dlp/GPL-3.0.txt",
                "yt-dlp/RUNTIME_SOURCE_NOTICES.md",
                "yt-dlp/THIRD_PARTY_LICENSES.txt",
                "yt-dlp/YT-DLP-UNLICENSE.txt",
            ],
            "source_authority": "official yt-dlp 2026.08.19 release and P3 delta closure",
            "delivery_status": "PREPARED_FOR_NEXT_CANDIDATE",
            "review_status": "P3_REQUIRED",
        },
        {
            "component": "FFmpeg/FFprobe BtbN",
            "version": "n8.1.2-44-g7c533d0f86-20260825 win64-lgpl-8.1",
            "runtime_components": ["FFmpeg", "FFprobe"],
            "distributed_material": ["ffmpeg.exe", "ffprobe.exe"],
            "license_identity": "LGPL-3.0-or-later (BtbN LGPL static variant)",
            "notice_identity": "RESOLVED_FOR_ACTIVE_BTBN_BASELINE",
            "delivery_artifacts": [
                "FFMPEG_BTBN_LICENSE.txt",
                "FFMPEG_BTBN_NOTICE.txt",
                "THIRD_PARTY_SOURCE_INFORMATION.txt",
            ],
            "source_authority": "BtbN autobuild-2026-08-25-13-06 complete technical source bundle",
            "delivery_status": "PREPARED_NOT_PUBLISHED",
            "review_status": "P3_REQUIRED",
        },
        {
            "component": "Other Python runtime packages",
            "version": "darkdetect 0.8.0 / packaging 26.3 / pypdf 7.1.1",
            "runtime_components": ["darkdetect", "packaging", "pypdf"],
            "distributed_material": ["PYZ modules"],
            "license_identity": "darkdetect BSD-3-Clause; packaging Apache-2.0 OR BSD-2-Clause; pypdf BSD-3-Clause",
            "notice_identity": "RESOLVED",
            "delivery_artifacts": [
                "DARKDETECT_LICENSE.txt",
                "PACKAGING_LICENSES.txt",
                "PYPDF_LICENSE.txt",
            ],
            "source_authority": "approved exact wheels and package metadata",
            "delivery_status": "PREPARED_NOT_DELIVERED",
            "review_status": "P3_REQUIRED",
        },
    )


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_metadata(path: Path, relative: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": relative,
        "sha256": sha256_bytes(data),
        "size_bytes": len(data),
    }


def _delivery_paths(families: Iterable[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {path for family in families for path in family["delivery_artifacts"]},
        key=str.casefold,
    )


def _runtime_components(composition: Mapping[str, Any]) -> set[str]:
    packages = {
        item["package"]
        for item in composition["package_materiality"]
        if item["classification"] not in {"BUILD_ONLY", "BUILD_TOOL_ONLY"}
    }
    externals = {item["component"] for item in composition["external_binaries"]}
    return (
        packages
        | externals
        | {
            "CPython",
            "Microsoft Visual C++ Runtime",
            "Tcl",
            "Tk",
        }
    )


def build_inventory(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    license_root = project_root / "Licencas"
    composition = _read_json(
        project_root / "docs" / "compliance" / "notices" / "NOTICE_BASELINE.json"
    )
    families = list(_family_specs())
    paths = sorted(
        set(_delivery_paths(families)) | set(GLOBAL_DELIVERY_ARTIFACTS),
        key=str.casefold,
    )
    artifacts = [
        _artifact_metadata(license_root / relative, relative) for relative in paths
    ]
    inventory: dict[str, Any] = {
        "baseline": {
            "app_version": "0.9.5",
            "historical_candidate_inventory_sha256": HISTORICAL_INVENTORY_SHA256,
            "product_edition": "community",
            "r2_candidate_inventory_sha256": R2_INVENTORY_SHA256,
        },
        "delivery_artifacts": artifacts,
        "global_delivery_artifacts": list(GLOBAL_DELIVERY_ARTIFACTS),
        "families": families,
        "next_candidate_notice_set": "PARTIAL",
        "r2_notice_delivery": composition["notice_delivery"],
        "schema_version": 1,
        "separations": {
            "build_reproducibility": "P2_SEPARATE_PENDING",
            "legal_review": "P3_REQUIRED",
            "notice_delivery": "THIS_INVENTORY_ONLY",
            "source_correspondence": "SEPARATE_TRACKED_BUNDLES_AND_MANIFESTS",
        },
        "source_only_license_artifacts": list(SOURCE_ONLY_LICENSE_ARTIFACTS),
    }
    inventory["delivery_tree_sha256"] = sha256_bytes(canonical_json_bytes(artifacts))
    return inventory


def _actual_license_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }


def _composition_issues(composition: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if composition["application"] != {
        "activation_required_for_current_edition": False,
        "app_version": "0.9.5",
        "name": "EduDownloader",
        "product_edition": "community",
    }:
        issues.append("r2-application-identity-mismatch")
    if composition["pristine_inventory"]["inventory_sha256"] != R2_INVENTORY_SHA256:
        issues.append("r2-inventory-identity-mismatch")

    externals = {item["component"]: item for item in composition["external_binaries"]}
    expected_external = {
        "Deno": (
            "2.9.5 x86_64-pc-windows-msvc",
            "98F8C2A2D470E4CCB04C935C86FF8050817D877762AEC5EAEEB9E409CCB3B9FD",
        ),
        "FFmpeg": (
            "8.1.2 essentials",
            "1326DDE4C84FF1F96FE6B8916C5BED29E163E9B5DCCF995F6F3DB069D143EC5E",
        ),
        "FFprobe": (
            "8.1.2 essentials",
            "B49CCC7C6547B141AD5A2F6EC69CC04323D7133D7704D70B331B904C63EECB07",
        ),
        "yt-dlp": (
            "2026.07.04",
            "52FE3C26DCF71FBDC85B528589020BB0B8E383155CFA81B64DD447BBE35E24B8",
        ),
    }
    for component, (version, digest) in expected_external.items():
        record = externals.get(component)
        if not record or (record["version"], record["sha256"]) != (version, digest):
            issues.append(f"external-identity-mismatch:{component}")

    microsoft = composition["microsoft_runtime_packaging"]
    runtime_files = microsoft["runtime_files"]
    if microsoft["vc_runtime_authority"]["version"] != "14.51.36247.0":
        issues.append("microsoft-runtime-version-mismatch")
    if [item["filename"] for item in runtime_files] != [
        "VCRUNTIME140.dll",
        "VCRUNTIME140_1.dll",
    ]:
        issues.append("microsoft-runtime-file-set-mismatch")

    covered = {
        component
        for family in _family_specs()
        for component in family["runtime_components"]
    }
    expected = _runtime_components(composition)
    if covered != expected:
        missing = sorted(expected - covered, key=str.casefold)
        extra = sorted(covered - expected, key=str.casefold)
        issues.append(
            f"runtime-notice-coverage-mismatch:missing={missing}:extra={extra}"
        )
    return issues


def _deno_inventory_issues(project_root: Path) -> list[str]:
    issues: list[str] = []
    inventory_path = (
        project_root
        / "docs"
        / "compliance"
        / "deno"
        / "DENO_THIRD_PARTY_INVENTORY.json"
    )
    notice_path = inventory_path.with_name("DENO_THIRD_PARTY_NOTICES.txt")
    try:
        inventory = _read_json(inventory_path)
        notice_data = notice_path.read_bytes()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ["deno-tracked-notice-inventory-unavailable"]
    expected_counts = {
        "components": 931,
        "d11h_canonical_reference_available": 15,
        "d11h_canonical_reference_missing": 0,
        "d11h_upstream_license_text_absent": 13,
        "d11h_upstream_license_text_partial": 2,
        "license_expression_pending": 0,
        "license_text_pending": 15,
        "license_text_resolved": 916,
        "unknown": 0,
    }
    if inventory.get("authority") != (
        "PROJECT_GENERATED_FROM_EXACT_MATERIAL_CLOSURE_NOT_UPSTREAM_DENO_NOTICE"
    ):
        issues.append("deno-notice-authority-mismatch")
    if inventory.get("status") != "PARTIAL_GENERATED_INVENTORY":
        issues.append("deno-notice-status-mismatch")
    counts = inventory.get("counts", {})
    for key, value in expected_counts.items():
        if counts.get(key) != value:
            issues.append(f"deno-notice-count-mismatch:{key}")
    generated = inventory.get("generated_notice", {})
    if (
        generated.get("path") != "docs/compliance/deno/DENO_THIRD_PARTY_NOTICES.txt"
        or generated.get("sha256") != sha256_bytes(notice_data)
        or generated.get("size") != len(notice_data)
    ):
        issues.append("deno-generated-notice-identity-mismatch")
    spdx = inventory.get("spdx_canonical_reference_policy", {})
    if spdx.get("classification") != "SPDX_CANONICAL_REFERENCE_TEXT":
        issues.append("deno-spdx-reference-classification-mismatch")
    return issues


def find_issues(
    project_root: Path = PROJECT_ROOT,
    *,
    inventory_override: Mapping[str, Any] | None = None,
) -> list[str]:
    issues: list[str] = []
    inventory_path = (
        project_root
        / "docs"
        / "compliance"
        / "notices"
        / "NOTICE_DELIVERY_INVENTORY.json"
    )
    if inventory_override is None:
        try:
            raw_inventory = inventory_path.read_bytes()
            inventory = json.loads(raw_inventory.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ["notice-delivery-inventory-unavailable"]
        if raw_inventory != canonical_json_bytes(inventory):
            issues.append("notice-delivery-inventory-not-canonical")
    else:
        inventory = dict(inventory_override)

    composition_path = (
        project_root / "docs" / "compliance" / "notices" / "NOTICE_BASELINE.json"
    )
    try:
        composition = _read_json(composition_path)
        issues.extend(_composition_issues(composition))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        issues.append("r2-composition-unavailable-or-invalid")
        return sorted(set(issues))
    issues.extend(_deno_inventory_issues(project_root))

    try:
        expected = build_inventory(project_root)
    except OSError as exc:
        issues.append(f"delivery-artifact-unavailable:{exc.filename}")
        return sorted(set(issues))
    if inventory != expected:
        issues.append("notice-delivery-inventory-content-mismatch")

    license_root = project_root / "Licencas"
    classified = (
        set(_delivery_paths(inventory.get("families", [])))
        | set(inventory.get("global_delivery_artifacts", []))
        | set(inventory.get("source_only_license_artifacts", []))
    )
    actual = _actual_license_files(license_root)
    for path in sorted(actual - classified, key=str.casefold):
        issues.append(f"unexpected-license-artifact:{path}")
    for path in sorted(classified - actual, key=str.casefold):
        issues.append(f"classified-license-artifact-missing:{path}")

    for relative in GENERATED_TEXT_ARTIFACTS:
        path = license_root / relative
        try:
            data = path.read_bytes()
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            issues.append(f"generated-notice-unavailable-or-not-utf8:{relative}")
            continue
        if b"\r" in data or not data.endswith(b"\n"):
            issues.append(f"generated-notice-not-canonical-lf:{relative}")
        if re.search(r"(?i)\b[A-Z]:[\\/]", text) or re.search(
            r"(?i)\\Users\\|/home/|/Users/", text
        ):
            issues.append(f"local-path-leak:{relative}")
        if any(
            marker in text
            for marker in (
                "-----BEGIN PRIVATE KEY-----",
                "-----BEGIN ENCRYPTED PRIVATE KEY-----",
                "issuer-signing-key-v1.dpapi",
            )
        ):
            issues.append(f"private-material-marker:{relative}")

    microsoft_notice = (license_root / "MICROSOFT_RUNTIME_NOTICE.txt").read_text(
        encoding="utf-8"
    )
    for marker in (
        "EXTERNAL_PREREQUISITE",
        "NENHUMA DLL MICROSOFT DISTRIBUÍDA DIRETAMENTE",
        "COMMUNITY_1_4_RECORDED_RISK",
    ):
        if marker not in microsoft_notice:
            issues.append(f"microsoft-notice-marker-missing:{marker}")
    if re.search(r"(?i)ucrtbase|api-ms-win", microsoft_notice):
        issues.append("microsoft-notice-presents-system-runtime")

    ffmpeg_notice = (license_root / "FFMPEG_BTBN_NOTICE.txt").read_text(
        encoding="utf-8"
    )
    for marker in ("BtbN", "n8.1.2-44-g7c533d0f86-20260825", "LGPL-3.0-or-later"):
        if marker not in ffmpeg_notice:
            issues.append(f"ffmpeg-notice-marker-missing:{marker}")
    if "Gyan é a baseline ativa" in ffmpeg_notice:
        issues.append("gyan-presented-as-active")
    ffmpeg_license = license_root / "FFMPEG_BTBN_LICENSE.txt"
    try:
        license_hash = sha256_bytes(ffmpeg_license.read_bytes())
    except OSError:
        license_hash = None
    if (
        license_hash
        != "DA7EABB7BAFDF7D3AE5E9F223AA5BDC1EECE45AC569DC21B3B037520B4464768"
    ):
        issues.append("ffmpeg-btbn-license-diverges-from-upstream")
    try:
        source_information = (
            license_root / "THIRD_PARTY_SOURCE_INFORMATION.txt"
        ).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        source_information = ""
    for marker in (
        "38898AD6003147EF3EEC3BD4EA035F379549B17F2FF05262A9B983F2BFEAC3FC",
        "2F73720444FA6659A79393DCA0E97AFF4DC3304D34197A44D49711465EDC5700",
        "C0A2B121B96AF8E52DE6A01E31DBD5711948F19B3550E57DB4C27A5F558A54C8",
        "631B9722D989E073651B928AC79F42B02F4330941D3BBC668FEE8BD19F43ED6F",
        "DD7DBBE3BACA3B164D73CC6C09C2200967C77E7FA25FCBAA88A1E67EAF58870E",
        "7BD8141C14BBF777F97C3B6E219BA438045B7F8988DCCE0306316634B9C99D1E",
        "não afirma que o asset já foi publicado",
    ):
        if marker not in source_information:
            issues.append(f"ffmpeg-source-information-marker-missing:{marker}")

    deno_notice = license_root / "deno" / "DENO_THIRD_PARTY_NOTICES.txt"
    source_deno_notice = (
        project_root / "docs" / "compliance" / "deno" / "DENO_THIRD_PARTY_NOTICES.txt"
    )
    if deno_notice.read_bytes() != _render_deno_delivery(source_deno_notice):
        issues.append("deno-delivery-notice-diverges-from-tracked-inventory-render")
    deno_text = deno_notice.read_text(encoding="utf-8")
    if "SPDX_CANONICAL_REFERENCE_TEXT" not in deno_text:
        issues.append("deno-spdx-reference-distinction-missing")
    if not all(
        marker in deno_text
        for marker in (
            "upstream_license_text: ABSENT",
            "upstream_license_text: PARTIAL",
        )
    ):
        issues.append("deno-upstream-text-gap-distinction-missing")

    custom_notice = (license_root / "CUSTOMTKINTER_THIRD_PARTY_NOTICES.txt").read_text(
        encoding="utf-8"
    )
    if "ROBOTO_PRODUCER_PENDING" not in custom_notice:
        issues.append("customtkinter-roboto-pending-marker-missing")

    return sorted(set(issues))


def find_candidate_delivery_issues(
    candidate: Path,
    project_root: Path = PROJECT_ROOT,
) -> list[str]:
    """Validate the candidate's physical notice tree against the D14A allowlist."""

    issues = find_issues(project_root)
    inventory_path = (
        project_root
        / "docs"
        / "compliance"
        / "notices"
        / "NOTICE_DELIVERY_INVENTORY.json"
    )
    try:
        inventory = _read_json(inventory_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return sorted(set([*issues, "notice-delivery-inventory-unavailable"]))

    license_root = candidate.resolve() / "Licencas"
    if not license_root.is_dir():
        return sorted(set([*issues, "candidate-license-root-missing"]))
    expected = {item["path"]: item for item in inventory["delivery_artifacts"]}
    actual = _actual_license_files(license_root)
    for relative in sorted(actual - expected.keys(), key=str.casefold):
        issues.append(f"candidate-unexpected-license-artifact:{relative}")
    for relative in sorted(expected.keys() - actual, key=str.casefold):
        issues.append(f"candidate-delivery-artifact-missing:{relative}")
    for relative in sorted(actual & expected.keys(), key=str.casefold):
        path = license_root / PurePosixPath(relative)
        if path.is_symlink():
            issues.append(f"candidate-delivery-artifact-link:{relative}")
            continue
        record = _artifact_metadata(path, relative)
        if record != expected[relative]:
            issues.append(f"candidate-delivery-artifact-mismatch:{relative}")
    return sorted(set(issues))


def candidate_delivery_record(
    candidate: Path,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """Describe physical delivery separately from notice identity and review."""

    inventory_path = (
        project_root
        / "docs"
        / "compliance"
        / "notices"
        / "NOTICE_DELIVERY_INVENTORY.json"
    )
    inventory = _read_json(inventory_path)
    issues = find_candidate_delivery_issues(candidate, project_root)
    return {
        "artifact_count": len(inventory["delivery_artifacts"]),
        "delivery_tree_sha256": inventory["delivery_tree_sha256"],
        "families": [
            {
                "component": family["component"],
                "notice_delivery": "DELIVERED" if not issues else "FAIL",
                "notice_identity": family["notice_identity"],
                "review_status": family["review_status"],
            }
            for family in inventory["families"]
        ],
        "inventory": {
            "path": "docs/compliance/notices/NOTICE_DELIVERY_INVENTORY.json",
            "sha256": sha256_bytes(inventory_path.read_bytes()),
        },
        "notice_identity_set": inventory["next_candidate_notice_set"],
        "physical_delivery_status": (
            "COMPLETE_FOR_D14A_ALLOWLIST" if not issues else "FAIL"
        ),
        "validation_issues": issues,
    }


def stage_candidate_delivery(
    candidate: Path,
    project_root: Path = PROJECT_ROOT,
) -> None:
    """Copy only the exact D14A delivery allowlist into a fresh candidate."""

    source_issues = find_issues(project_root)
    if source_issues:
        raise ValueError("source notice delivery is invalid")
    inventory = _read_json(
        project_root
        / "docs"
        / "compliance"
        / "notices"
        / "NOTICE_DELIVERY_INVENTORY.json"
    )
    target_root = candidate.resolve() / "Licencas"
    if target_root.exists() and any(target_root.rglob("*")):
        raise ValueError("candidate license target is not empty")
    target_root.mkdir(parents=True, exist_ok=True)
    for artifact in inventory["delivery_artifacts"]:
        relative = PurePosixPath(artifact["path"])
        source = project_root / "Licencas" / relative
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    candidate_issues = find_candidate_delivery_issues(candidate, project_root)
    if candidate_issues:
        raise ValueError("staged candidate notice delivery is invalid")


def _normalized_text(path: Path) -> str:
    return _normalize_notice_text(path.read_text(encoding="utf-8"))


def _normalize_notice_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip(" \t") for line in normalized.split("\n")).rstrip("\n")


def render_consolidated_notice(
    title: str, sections: Sequence[tuple[str, str]]
) -> bytes:
    lines = [
        title,
        "",
        "Artifact de entrega gerado deterministicamente a partir de evidência local preservada.",
        "A inclusão técnica não constitui revisão jurídica nem autorização de publicação.",
    ]
    for heading, text in sections:
        normalized = _normalize_notice_text(text)
        lines.extend(("", "=" * 78, heading, "=" * 78, normalized))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_deno_delivery(source_notice: Path) -> bytes:
    source = _normalized_text(source_notice)
    preface = """DENO 2.9.5 — THIRD-PARTY NOTICE DELIVERY

Este artifact preserva o inventário técnico rastreado da composição material.
As marcações abaixo são distintas e não são intercambiáveis:

- UPSTREAM_LICENSE_TEXT: texto publicado pelo upstream exato;
- SPDX_CANONICAL_REFERENCE_TEXT: referência canônica complementar, nunca
  apresentada como texto upstream;
- P3_REQUIRED: revisão jurídica continua necessária.

Quinze componentes permanecem com upstream_license_text ABSENT ou PARTIAL.
Por isso, esta família e o conjunto do próximo candidato permanecem PARTIAL.

"""
    return (preface + source + "\n").encode("utf-8")


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _prepare_cpython(project_root: Path) -> None:
    evidence = (
        project_root / "build-compliance-python-runtime" / "evidence" / "licenses"
    )
    sections = []
    for relative in (
        "cpython/LICENSE",
        "cpython/Modules/expat/COPYING",
        "bzip2/LICENSE",
        "libffi/LICENSE",
        "mpdecimal/COPYRIGHT.txt",
        "openssl/ACKNOWLEDGEMENTS.md",
        "openssl/LICENSE.txt",
        "xz/COPYING",
        "xz/COPYING.GPLv2",
        "xz/COPYING.GPLv3",
        "xz/COPYING.LGPLv2.1",
        "zlib-ng/LICENSE.md",
        "zstandard/LICENSE",
        "zstandard/COPYING",
    ):
        sections.append((relative, _normalized_text(evidence / relative)))
    _write(
        project_root / "Licencas" / "CPYTHON_RUNTIME_NOTICES.txt",
        render_consolidated_notice(
            "CPYTHON 3.14.6 — RUNTIME LICENSES AND NOTICES", sections
        ),
    )
    tcl_sections = [
        (relative, _normalized_text(evidence / relative))
        for relative in (
            "tcl/license.terms",
            "tcl/compat/zlib/LICENSE",
            "tcl/libtommath/LICENSE",
        )
    ]
    _write(
        project_root / "Licencas" / "TCL_LICENSES.txt",
        render_consolidated_notice("TCL 8.6.15.0 — LICENSES", tcl_sections),
    )
    _write(
        project_root / "Licencas" / "TK_LICENSE.txt",
        render_consolidated_notice(
            "TK 8.6.15.0 — LICENSE",
            [("tk/license.terms", _normalized_text(evidence / "tk/license.terms"))],
        ),
    )


def _component_label(relative: str) -> str:
    parts = relative.split("/")
    if parts[0] == "metadata":
        return "cffi/libffi"
    return parts[1] if len(parts) > 1 else relative


def _prepare_cryptography(project_root: Path) -> None:
    provenance = _read_json(
        project_root
        / "docs"
        / "compliance"
        / "python"
        / "CRYPTOGRAPHY_CFFI_RUNTIME_SOURCE_PROVENANCE.json"
    )
    staging = project_root / "build-compliance-cryptography-cffi" / "staging"
    grouped: dict[str, list[str]] = defaultdict(list)
    contents: dict[str, str] = {}
    for relative, expected_hash in sorted(provenance["licenses"].items()):
        path = staging / Path(relative)
        data = path.read_bytes()
        if sha256_bytes(data) != expected_hash:
            raise ValueError(f"crypto license evidence hash mismatch: {relative}")
        grouped[expected_hash].append(_component_label(relative))
        contents[expected_hash] = _normalized_text(path)
    sections = []
    for digest in sorted(grouped):
        components = ", ".join(sorted(set(grouped[digest]), key=str.casefold))
        sections.append(
            (
                f"Aplica-se a: {components} | evidence SHA-256: {digest}",
                contents[digest],
            )
        )
    _write(
        project_root / "Licencas" / "CRYPTOGRAPHY_CFFI_THIRD_PARTY_NOTICES.txt",
        render_consolidated_notice(
            "CFFI 2.1.1 / CRYPTOGRAPHY 49.0.0 / OPENSSL 4.0.1 / RUST 1.96.0",
            sections,
        ),
    )


def _prepare_packaging(project_root: Path) -> None:
    wheel = (
        project_root
        / "build-compliance-wheels"
        / "wheelhouse"
        / "packaging-26.3-py3-none-any.whl"
    )
    with zipfile.ZipFile(wheel) as archive:
        members = (
            "packaging-26.3.dist-info/licenses/LICENSE",
            "packaging-26.3.dist-info/licenses/LICENSE.APACHE",
            "packaging-26.3.dist-info/licenses/LICENSE.BSD",
        )
        sections = [
            (member, archive.read(member).decode("utf-8").replace("\r\n", "\n"))
            for member in members
        ]
    _write(
        project_root / "Licencas" / "PACKAGING_LICENSES.txt",
        render_consolidated_notice("PACKAGING 26.3 — LICENSES", sections),
    )


def _prepare_customtkinter(project_root: Path) -> None:
    inputs = project_root / "build-compliance-customtkinter" / "inputs"
    preface = """CustomTkinter 5.2.2 é distribuído com sua licença MIT separada.

Os textos abaixo preservam a evidência técnica disponível para os assets
materialmente distribuídos. A correspondência do produtor exato dos dois TTF
Roboto permanece ROBOTO_PRODUCER_PENDING. Os TTF identificam Google Inc. e
Christian Robertson; o texto Apache-2.0 histórico acompanha este aviso. Isso
não prova o produtor exato dos blobs nem resolve interpretação jurídica.
Shapes OTF e ícone ICO acompanham o parent CustomTkinter MIT; sua autoria
histórica individual permanece risco registrado, sem conclusão adicional.

A linhagem do código de carregamento de fontes remonta a Digsby/Stack Overflow;
o texto Digsby preservado é entregue sem afirmar qual revisão jurídica rege a
adaptação atual. Origem: Digsby, arquivo gui/native/win/winfonts.py, commit
f5fe00244744aa131e07f09348d10563f3d8fa99. Intermediário: resposta de
Felipe, criada em 2015, em
https://stackoverflow.com/questions/11993290/truly-custom-font-in-tkinter/30631309.
As revisões conhecidas incluem CC BY-SA 3.0 e 4.0; a revisão copiada não foi
estabelecida. A adaptação altera nomes, estrutura de classe/método e suporte
a Python 3. REVISION_IDENTITY_PARTIAL permanece risco registrado; este aviso
não declara compatibilidade jurídica entre as licenças."""
    sections = [
        ("STATUS", preface),
        (
            "Roboto — evidência histórica Apache-2.0",
            _normalized_text(inputs / "roboto-historical-LICENSE.txt"),
        ),
        ("Digsby License v1", _normalized_text(inputs / "digsby-LICENSE")),
    ]
    _write(
        project_root / "Licencas" / "CUSTOMTKINTER_THIRD_PARTY_NOTICES.txt",
        render_consolidated_notice(
            "CUSTOMTKINTER 5.2.2 — THIRD-PARTY NOTICES", sections
        ),
    )


def _prepare_static_notices(project_root: Path) -> None:
    license_root = project_root / "Licencas"
    microsoft = """MICROSOFT VISUAL C++ RUNTIME — PRÉ-REQUISITO EXTERNO

Modelo: EXTERNAL_PREREQUISITE
NENHUMA DLL MICROSOFT DISTRIBUÍDA DIRETAMENTE pelo EduDownloader.
O Windows precisa ter Microsoft Visual C++ Runtime x64 compatível instalado
antes de iniciar o aplicativo. O EduDownloader não inclui nem hospeda o
instalador Microsoft. Se necessário, obtenha-o na fonte oficial:
https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170

Material Microsoft incorporado por binários upstream é assunto separado:
COMMUNITY_1_4_RECORDED_RISK. Este aviso não resolve sua cadeia transitiva.
Não há versão mínima comprovada para todos os binários atuais; a versão
14.51.36247.0 foi observada apenas no host de teste.

Este notice não declara LEGAL_APPROVED, autorização comercial, production_ready
ou public_release_allowed.
"""
    _write(license_root / "MICROSOFT_RUNTIME_NOTICE.txt", microsoft.encode("utf-8"))

    ffmpeg = """FFMPEG / FFPROBE — BASELINE ATIVA BTBN

Componente: FFmpeg e FFprobe
Versão: n8.1.2-44-g7c533d0f86-20260825 win64-lgpl-8.1
Provedor ativo: BtbN/FFmpeg-Builds
Arquivos distribuídos: ffmpeg.exe e ffprobe.exe
Licença declarada pela build ativa: LGPL-3.0-or-later
Texto da licença: FFMPEG_BTBN_LICENSE.txt
GPLv3 incorporada pela LGPLv3: yt-dlp/GPL-3.0.txt
libmp3lame: fonte SVN r6761 e textos LGPL preservados no bundle correspondente.

ffmpeg.exe SHA-256:
88F0453C46DBF83D3DA583A3ECECCBA6F2B82169C89A9B4254C481267E7135F8
ffprobe.exe SHA-256:
07A26215E0C482407412EEBA88FD169CAA97C8CBCD0C567CF9C6CFBA6F2843C7

Fonte correspondente e modo de entrega futuro: THIRD_PARTY_SOURCE_INFORMATION.txt.
O bundle foi preservado localmente; nenhum asset público foi criado nesta etapa.
"""
    _write(license_root / "FFMPEG_BTBN_NOTICE.txt", ffmpeg.encode("utf-8"))

    source_information = """INFORMAÇÃO DE FONTE DE TERCEIROS — COMMUNITY 1.4.0

Os três bundles abaixo foram verificados e preservados fora do aplicativo.
Na futura distribuição pública, cada asset de fonte deve acompanhar o pacote
binário da mesma release. Procure pelo nome exato na página dessa release e
confira seu SHA-256 antes de usar. Se algum asset não estiver acessível, a
entrega pública não está completa. Nenhum asset público existe por esta nota.

PACOTE BINÁRIO PREVISTO
EduDownloader-1.4.0-Community.zip

YT-DLP
Versão: 2026.08.19, win_exe
yt-dlp.exe SHA-256: 66674953FE251B89F4D08C5F0E35E0728679BD67AB3D7D05C0562AF101DD3E7A
Licença: executável combinado GPLv3+; código principal The Unlicense;
demais termos em yt-dlp/THIRD_PARTY_LICENSES.txt.
Asset de fonte previsto: EduDownloader-ThirdParty-Source-yt-dlp-2026.08.19.zip
Tamanho: 155871040 bytes
SHA-256: 38898AD6003147EF3EEC3BD4EA035F379549B17F2FF05262A9B983F2BFEAC3FC
Inventário SHA-256: 2F73720444FA6659A79393DCA0E97AFF4DC3304D34197A44D49711465EDC5700
Correspondência: SOURCE_PROVENANCE.json e inventário dentro do asset;
Licencas/yt-dlp/SOURCE_CORRESPONDENCE.md é evidência técnica do projeto.

DENO
Versão: 2.9.5, x86_64-pc-windows-msvc
deno.exe SHA-256: 98F8C2A2D470E4CCB04C935C86FF8050817D877762AEC5EAEEB9E409CCB3B9FD
Licenças: DENO_LICENSE.txt e deno/DENO_THIRD_PARTY_NOTICES.txt; componentes
MPL-2.0 identificados no inventário de fonte. Textos upstream ausentes ou
parciais continuam distintos das referências canônicas SPDX.
Asset de fonte previsto: EduDownloader-ThirdParty-Source-Deno-2.9.5-COMPLETE.zip
Tamanho: 268052753 bytes
SHA-256: C0A2B121B96AF8E52DE6A01E31DBD5711948F19B3550E57DB4C27A5F558A54C8
Inventário SHA-256: 631B9722D989E073651B928AC79F42B02F4330941D3BBC668FEE8BD19F43ED6F
Correspondência: BUNDLE_MANIFEST.json e SOURCE-BUNDLE-INVENTORY.json no asset;
o relatório DENO_RUNTIME_SOURCE_CORRESPONDENCE.md é evidência do projeto.
O bundle preserva a fonte identificada; não alega reconstrução bit a bit.

FFMPEG / FFPROBE

Componente: FFmpeg / FFprobe
Distribuidor/build: BtbN/FFmpeg-Builds, autobuild-2026-08-25-13-06
Versão: n8.1.2-44-g7c533d0f86-20260825, win64-lgpl-8.1 static x64
Licença declarada: LGPL-3.0-or-later
Commit FFmpeg: 7c533d0f86f13a06ec93968f6194349665b3536a

ffmpeg.exe SHA-256: 88F0453C46DBF83D3DA583A3ECECCBA6F2B82169C89A9B4254C481267E7135F8
ffprobe.exe SHA-256: 07A26215E0C482407412EEBA88FD169CAA97C8CBCD0C567CF9C6CFBA6F2843C7

Asset de fonte previsto:
EduDownloader-ThirdParty-Source-FFmpeg-BtbN-autobuild-2026-08-25-13-06-COMPLETE-CANDIDATE.zip
Tamanho do bundle: 646861654 bytes
SHA-256 do bundle: DD7DBBE3BACA3B164D73CC6C09C2200967C77E7FA25FCBAA88A1E67EAF58870E
SHA-256 do inventário interno: 7BD8141C14BBF777F97C3B6E219BA438045B7F8988DCCE0306316634B9C99D1E

O bundle de fonte correspondente está preservado e verificado localmente, fora
do aplicativo. A futura publicação deve entregar esse asset junto ao binário,
com o mesmo nome/hash e instrução de download na página da release. Esta nota
não afirma que o asset já foi publicado nem fornece URL fictícia.
"""
    _write(
        license_root / "THIRD_PARTY_SOURCE_INFORMATION.txt",
        source_information.encode("utf-8"),
    )

    index = """AVISOS E LICENÇAS DE COMPONENTES DE TERCEIROS

Este arquivo é o índice humano do conjunto preparado para o próximo candidato
Community. Ele não declara revisão jurídica concluída, produção pronta ou
publicação autorizada.

Microsoft Visual C++ Runtime x64 (pré-requisito externo)
  MICROSOFT_RUNTIME_NOTICE.txt — nenhuma DLL Microsoft app-local incluída;
  material transitivo upstream permanece risco registrado.

CPython 3.14.6, Tcl 8.6.15.0 e Tk 8.6.15.0
  CPYTHON_RUNTIME_NOTICES.txt, TCL_LICENSES.txt e TK_LICENSE.txt.

PyInstaller 6.21.0 e pyinstaller-hooks-contrib 2026.6
  PyInstaller/ e pyinstaller-hooks-contrib/. O conjunto preserva a associação
  da Bootloader Exception, zlib e hooks sem duplicar textos.

cffi 2.1.1, cryptography 49.0.0, OpenSSL 4.0.1 e Rust 1.96.0
  CRYPTOGRAPHY_CFFI_THIRD_PARTY_NOTICES.txt.

Deno 2.9.5
  DENO_LICENSE.txt e deno/DENO_THIRD_PARTY_NOTICES.txt. O notice mantém
  explicitamente a diferença entre texto upstream e referência canônica SPDX.
  Quinze componentes continuam com texto upstream ausente/parcial como risco
  registrado; a fonte preservada e seu asset previsto são identificados em
  THIRD_PARTY_SOURCE_INFORMATION.txt.

CustomTkinter 5.2.2
  CUSTOMTKINTER_LICENSE.txt e CUSTOMTKINTER_THIRD_PARTY_NOTICES.txt. A
  provenance do produtor exato dos TTF Roboto continua
  ROBOTO_PRODUCER_PENDING como risco registrado; créditos conhecidos constam
  do aviso entregue.

Pillow 13.0.0 e pypdfium2/PDFium 5.12.1
  PILLOW_LICENSE.txt, PILLOW_COMPOSITION.md, PILLOW_SBOM.cdx.json e
  PYPDFIUM2_LICENSES/.
  Este software utiliza FreeType por meio do Pillow e do PDFium.
  This software is based in part of the work of the FreeType Team.
  Os textos de licença correspondentes estão em PILLOW_LICENSE.txt e
  PYPDFIUM2_LICENSES/.

yt-dlp 2026.08.19
  yt-dlp/YT-DLP-UNLICENSE.txt, THIRD_PARTY_LICENSES.txt, GPL-3.0.txt e
  RUNTIME_SOURCE_NOTICES.md. O asset de fonte correspondente previsto consta
  de THIRD_PARTY_SOURCE_INFORMATION.txt.

FFmpeg/FFprobe BtbN n8.1.2-44-g7c533d0f86-20260825
  FFMPEG_BTBN_NOTICE.txt, FFMPEG_BTBN_LICENSE.txt e
  THIRD_PARTY_SOURCE_INFORMATION.txt. A fonte completa está preservada
  localmente; a publicação do asset está reservada à futura release.

Outros módulos runtime
  DARKDETECT_LICENSE.txt, PACKAGING_LICENSES.txt e PYPDF_LICENSE.txt.

Relatórios de provenance, bundles de source, wheelhouse, staging, inventários
internos, P2 e P3 não pertencem à árvore de notices entregue ao usuário. O R2
permanece historicamente inalterado com seus statuses anteriores.
"""
    _write(license_root / "THIRD_PARTY_NOTICES.txt", index.encode("utf-8"))


def prepare(project_root: Path = PROJECT_ROOT) -> None:
    _prepare_cpython(project_root)
    _prepare_cryptography(project_root)
    _prepare_packaging(project_root)
    _prepare_customtkinter(project_root)
    _prepare_static_notices(project_root)
    deno_target = project_root / "Licencas" / "deno" / "DENO_THIRD_PARTY_NOTICES.txt"
    deno_target.parent.mkdir(parents=True, exist_ok=True)
    _write(
        deno_target,
        _render_deno_delivery(
            project_root
            / "docs"
            / "compliance"
            / "deno"
            / "DENO_THIRD_PARTY_NOTICES.txt"
        ),
    )
    inventory_path = (
        project_root
        / "docs"
        / "compliance"
        / "notices"
        / "NOTICE_DELIVERY_INVENTORY.json"
    )
    _write(inventory_path, canonical_json_bytes(build_inventory(project_root)))


def _parse_args(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "stage", "validate", "validate-candidate")
    )
    parser.add_argument("--candidate", type=Path)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parse_args(arguments)
    if args.command == "prepare":
        prepare()
        print("Notice delivery tree and inventory prepared.")
    if args.command in {"stage", "validate-candidate"} and args.candidate is None:
        print("--candidate is required for this command")
        return 2
    if args.command == "stage":
        try:
            stage_candidate_delivery(args.candidate)
        except ValueError as error:
            print(f"Notice delivery staging rejected: {error}")
            return 1
        print("Candidate notice delivery staged from the exact D14A allowlist.")
    if args.command == "validate-candidate":
        issues = find_candidate_delivery_issues(args.candidate)
        if issues:
            print("Candidate notice delivery rejected:")
            for issue in issues:
                print(f"- {issue}")
            return 1
        print("Candidate notice delivery matches the exact D14A allowlist.")
        return 0
    issues = find_issues()
    if issues:
        print("Notice delivery rejected:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Notice delivery tree and inventory validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
