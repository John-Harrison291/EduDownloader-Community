"""Fail-closed policy for Microsoft runtime inputs in frozen builds."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final


PROJECT_DIR: Final = Path(__file__).resolve().parent
DEFAULT_MANIFEST: Final = (
    PROJECT_DIR
    / "docs"
    / "compliance"
    / "microsoft"
    / "MICROSOFT_RUNTIME_PACKAGING.json"
)
EXTERNAL_POLICY_MANIFEST: Final = (
    PROJECT_DIR
    / "docs"
    / "compliance"
    / "microsoft"
    / "MICROSOFT_EXTERNAL_RUNTIME_POLICY.json"
)
EXTERNAL_DISTRIBUTION_MODEL: Final = "EXTERNAL_PREREQUISITE"
SUPPORTED_BASELINE: Final = "WINDOWS_10_OR_NEWER_X64"
EXPECTED_RUNTIME_FILES: Final = frozenset({"vcruntime140.dll", "vcruntime140_1.dll"})
FORBIDDEN_APPLICATION_LOCAL_NAMES: Final = frozenset({"ucrtbase.dll"})
MICROSOFT_RUNTIME_NAME = re.compile(
    r"(?i)^(?:vcruntime|msvcp|concrt|vcomp|mfc|mfcm|vcamp|vccorlib)\d.*\.dll$"
)
API_SET_NAME = re.compile(r"(?i)^api-ms-win-(?:core|crt)-.+\.dll$")
X64_MACHINE: Final = 0x8664

SignatureProbe = Callable[[Path], Mapping[str, str]]


def canonical_json_bytes(value: object) -> bytes:
    """Serialize tracked evidence deterministically."""
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    """Return the uppercase SHA-256 for a local file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Load the pinned Microsoft runtime policy."""
    return json.loads(path.read_text(encoding="utf-8"))


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()


def validate_manifest(manifest: Mapping[str, Any]) -> list[str]:
    """Validate the tracked policy without consulting local state."""
    if manifest.get("distribution_model") == EXTERNAL_DISTRIBUTION_MODEL:
        return validate_external_policy(manifest)
    issues: list[str] = []
    if manifest.get("schema_version") != 1:
        issues.append("microsoft-runtime-manifest-schema-mismatch")
    if manifest.get("scope") != "NEXT_CONTROLLED_CANDIDATE":
        issues.append("microsoft-runtime-manifest-scope-mismatch")

    baseline = manifest.get("baseline", {})
    if baseline.get("supported_windows") != SUPPORTED_BASELINE:
        issues.append("microsoft-runtime-windows-baseline-mismatch")
    if baseline.get("architecture") != "x64":
        issues.append("microsoft-runtime-baseline-architecture-mismatch")

    authority = manifest.get("vc_runtime_authority", {})
    minimum = authority.get("minimum_version")
    version = authority.get("version")
    if not isinstance(minimum, str) or not _version_tuple(minimum):
        issues.append("microsoft-runtime-minimum-version-invalid")
    if not isinstance(version, str) or not _version_tuple(version):
        issues.append("microsoft-runtime-version-invalid")
    elif isinstance(minimum, str) and _version_tuple(version) < _version_tuple(minimum):
        issues.append("microsoft-runtime-version-below-minimum")
    if authority.get("architecture") != "x64":
        issues.append("microsoft-runtime-authority-architecture-mismatch")
    if authority.get("publisher") != "Microsoft Corporation":
        issues.append("microsoft-runtime-authority-publisher-mismatch")
    package = authority.get("package", {})
    if not re.fullmatch(r"[0-9A-F]{64}", str(package.get("sha256", ""))):
        issues.append("microsoft-runtime-package-hash-invalid")
    if package.get("authenticode", {}).get("status") != "VALID":
        issues.append("microsoft-runtime-package-signature-not-valid")

    records = manifest.get("runtime_files", [])
    filenames = {
        str(record.get("filename", "")).casefold()
        for record in records
        if isinstance(record, Mapping)
    }
    if filenames != EXPECTED_RUNTIME_FILES or len(records) != len(filenames):
        issues.append("microsoft-runtime-file-set-mismatch")
    for record in records:
        if not isinstance(record, Mapping):
            issues.append("microsoft-runtime-file-record-invalid")
            continue
        if record.get("architecture") != "x64":
            issues.append("microsoft-runtime-file-architecture-mismatch")
        if record.get("version") != version:
            issues.append("microsoft-runtime-file-version-mismatch")
        if not re.fullmatch(r"[0-9A-F]{64}", str(record.get("sha256", ""))):
            issues.append("microsoft-runtime-file-hash-invalid")
        signature = record.get("authenticode", {})
        if signature.get("status") != "VALID":
            issues.append("microsoft-runtime-file-signature-not-valid")
        if "Microsoft Corporation" not in str(signature.get("publisher", "")):
            issues.append("microsoft-runtime-file-publisher-mismatch")

    policies = manifest.get("policies", {})
    if policies.get("api_set") != "SYSTEM_RUNTIME_NOT_TO_BE_BUNDLED":
        issues.append("microsoft-runtime-api-set-policy-mismatch")
    if policies.get("ucrt") != "SYSTEM_RUNTIME_NOT_TO_BE_BUNDLED":
        issues.append("microsoft-runtime-ucrt-policy-mismatch")
    if policies.get("unexpected_origin") != "FAIL_CLOSED":
        issues.append("microsoft-runtime-origin-policy-not-fail-closed")
    if manifest.get("status", {}).get("p3") != "P3_PENDING_REVIEW":
        issues.append("microsoft-runtime-p3-status-mismatch")
    return sorted(set(issues))


def validate_external_policy(manifest: Mapping[str, Any]) -> list[str]:
    """Check the fail-closed contract for a system-provided VC runtime."""
    issues: list[str] = []
    if manifest.get("schema_version") != 1:
        issues.append("microsoft-external-policy-schema-mismatch")
    if manifest.get("distribution_model") != EXTERNAL_DISTRIBUTION_MODEL:
        issues.append("microsoft-external-policy-model-mismatch")
    if manifest.get("runtime_files") != []:
        issues.append("microsoft-external-policy-direct-files-present")
    baseline = manifest.get("baseline", {})
    if baseline != {"architecture": "x64", "supported_windows": SUPPORTED_BASELINE}:
        issues.append("microsoft-external-policy-baseline-mismatch")
    policies = manifest.get("policies", {})
    if policies.get("direct_vc_runtime") != "FORBIDDEN_IN_CLIENT_PACKAGE":
        issues.append("microsoft-external-policy-direct-guard-missing")
    if policies.get("upstream_embedded_material") != "SEPARATE_RECORDED_RISK":
        issues.append("microsoft-external-policy-upstream-scope-mismatch")
    if manifest.get("vc_runtime_authority") != {
        "source": "WINDOWS_INSTALLED_PREREQUISITE"
    }:
        issues.append("microsoft-external-policy-authority-mismatch")
    return sorted(set(issues))


def pe_architecture(path: Path) -> str:
    """Read PE machine type without importing third-party inspection code."""
    try:
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                return "UNKNOWN"
            stream.seek(0x3C)
            offset_bytes = stream.read(4)
            if len(offset_bytes) != 4:
                return "UNKNOWN"
            stream.seek(struct.unpack("<I", offset_bytes)[0])
            if stream.read(4) != b"PE\0\0":
                return "UNKNOWN"
            machine_bytes = stream.read(2)
            if len(machine_bytes) != 2:
                return "UNKNOWN"
    except OSError:
        return "UNKNOWN"
    return "x64" if struct.unpack("<H", machine_bytes)[0] == X64_MACHINE else "OTHER"


def _powershell_executable() -> str | None:
    modern = shutil.which("pwsh.exe")
    if modern is not None:
        return modern
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    explicit = (
        system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    if explicit.is_file():
        return str(explicit)
    return shutil.which("powershell.exe")


def inspect_authenticode(path: Path) -> dict[str, str]:
    """Read Authenticode and version metadata without changing trust stores."""
    powershell = _powershell_executable()
    if powershell is None:
        return {"status": "UNAVAILABLE"}
    script = (
        "$ErrorActionPreference='Stop';"
        "Import-Module Microsoft.PowerShell.Security -ErrorAction Stop;"
        "$p=$env:EDUDOWNLOADER_SIGNATURE_INPUT;"
        "$s=Get-AuthenticodeSignature -LiteralPath $p;"
        "$v=(Get-Item -LiteralPath $p).VersionInfo;"
        "[pscustomobject]@{status=[string]$s.Status;"
        "publisher=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{''};"
        "thumbprint=if($s.SignerCertificate){$s.SignerCertificate.Thumbprint}else{''};"
        "version=[string]$v.FileVersion;product=[string]$v.ProductName;"
        "description=[string]$v.FileDescription;company=[string]$v.CompanyName}"
        "|ConvertTo-Json -Compress"
    )
    encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    environment = os.environ.copy()
    environment["EDUDOWNLOADER_SIGNATURE_INPUT"] = str(path.resolve())
    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded_script,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        shell=False,
    )
    if completed.returncode != 0:
        return {"status": "UNAVAILABLE"}
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "UNAVAILABLE"}


def _validate_runtime_file(
    path: Path,
    record: Mapping[str, Any],
    signature_probe: SignatureProbe,
) -> list[str]:
    name = str(record["filename"])
    prefix = f"microsoft-runtime-file:{name}:"
    if not path.is_file():
        return [prefix + "missing"]
    issues: list[str] = []
    if path.stat().st_size != record.get("size_bytes"):
        issues.append(prefix + "size-mismatch")
    if sha256_file(path) != record.get("sha256"):
        issues.append(prefix + "hash-mismatch")
    if pe_architecture(path) != "x64":
        issues.append(prefix + "architecture-mismatch")
    observed = signature_probe(path)
    if str(observed.get("status", "")).casefold() != "valid":
        issues.append(prefix + "signature-not-valid")
    expected_signature = record.get("authenticode", {})
    if observed.get("thumbprint") != expected_signature.get("thumbprint"):
        issues.append(prefix + "signer-thumbprint-mismatch")
    if "Microsoft Corporation" not in str(observed.get("publisher", "")):
        issues.append(prefix + "publisher-mismatch")
    if observed.get("version") != record.get("version"):
        issues.append(prefix + "version-mismatch")
    return issues


def validate_runtime_authority(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    signature_probe: SignatureProbe = inspect_authenticode,
) -> list[str]:
    """Validate the ignored, pinned runtime input directory."""
    issues = validate_manifest(manifest)
    if not root.is_dir():
        return sorted(set(issues + ["microsoft-runtime-authority-root-missing"]))
    actual = {path.name.casefold(): path for path in root.iterdir() if path.is_file()}
    if set(actual) != EXPECTED_RUNTIME_FILES:
        issues.append("microsoft-runtime-authority-file-set-mismatch")
    for record in manifest.get("runtime_files", []):
        if not isinstance(record, Mapping) or "filename" not in record:
            continue
        path = actual.get(
            str(record["filename"]).casefold(), root / str(record["filename"])
        )
        issues.extend(_validate_runtime_file(path, record, signature_probe))
    return sorted(set(issues))


def isolated_search_path(
    project_root: Path,
    runtime_root: Path | None = None,
    *,
    system_root: Path | None = None,
) -> str:
    """Build a deterministic DLL search path independent of the user PATH."""
    windows = (
        system_root or Path(os.environ.get("SystemRoot", r"C:\Windows"))
    ).resolve()
    roots = (
        *((runtime_root.resolve(),) if runtime_root is not None else ()),
        project_root.resolve(),
        windows / "System32",
        windows / "System32" / "WindowsPowerShell" / "v1.0",
        windows,
    )
    return os.pathsep.join(str(root) for root in roots)


def _is_relative_to(path: Path, roots: Iterable[Path]) -> bool:
    resolved = path.resolve()
    return any(
        resolved == root.resolve() or resolved.is_relative_to(root.resolve())
        for root in roots
    )


def _toc_entries(value: object) -> Iterable[tuple[str, str, str]]:
    if (
        isinstance(value, tuple)
        and len(value) == 3
        and all(isinstance(item, str) for item in value)
        and value[2] in {"BINARY", "EXTENSION"}
    ):
        yield value
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _toc_entries(item)


def validate_analysis_toc(
    toc_path: Path,
    manifest: Mapping[str, Any],
    *,
    runtime_root: Path | None = None,
    allowed_roots: Iterable[Path],
) -> list[str]:
    """Reject PyInstaller dependency resolution outside explicit authorities."""
    try:
        parsed = ast.literal_eval(toc_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return ["microsoft-runtime-analysis-toc-unreadable"]
    issues: list[str] = []
    external = manifest.get("distribution_model") == EXTERNAL_DISTRIBUTION_MODEL
    records = {
        str(record["filename"]).casefold(): record
        for record in manifest.get("runtime_files", [])
    }
    seen_runtime: dict[str, int] = {}
    seen_toc_entries: set[tuple[str, str, str]] = set()
    roots = tuple(Path(root).resolve() for root in allowed_roots)
    for destination, source, _typecode in _toc_entries(parsed):
        toc_entry = (destination, source, _typecode)
        if toc_entry in seen_toc_entries:
            continue
        seen_toc_entries.add(toc_entry)
        source_path = Path(source)
        name = Path(destination).name.casefold()
        if source_path.suffix.casefold() == ".dll" and not _is_relative_to(
            source_path, roots
        ):
            issues.append(f"microsoft-runtime-analysis-unallowed-dll-origin:{name}")
        if "libheif" in {part.casefold() for part in source_path.parts}:
            issues.append(f"microsoft-runtime-analysis-libheif-contamination:{name}")
        if name in FORBIDDEN_APPLICATION_LOCAL_NAMES or API_SET_NAME.fullmatch(name):
            issues.append(f"microsoft-runtime-analysis-system-runtime-bundled:{name}")
        if not MICROSOFT_RUNTIME_NAME.fullmatch(name):
            continue
        if external:
            if name not in EXPECTED_RUNTIME_FILES:
                issues.append(f"microsoft-runtime-analysis-unplanned-family:{name}")
            continue
        seen_runtime[name] = seen_runtime.get(name, 0) + 1
        if name not in records:
            issues.append(f"microsoft-runtime-analysis-unplanned-family:{name}")
            continue
        if runtime_root is None or not _is_relative_to(source_path, (runtime_root,)):
            issues.append(f"microsoft-runtime-analysis-unpinned-origin:{name}")
        elif not source_path.is_file():
            issues.append(f"microsoft-runtime-analysis-source-missing:{name}")
        elif sha256_file(source_path) != records[name]["sha256"]:
            issues.append(f"microsoft-runtime-analysis-hash-mismatch:{name}")
    for name in records:
        if seen_runtime.get(name) != 1:
            issues.append(f"microsoft-runtime-analysis-required-count:{name}")
    return sorted(set(issues))


def validate_candidate_runtime(
    candidate: Path,
    manifest: Mapping[str, Any],
    *,
    signature_probe: SignatureProbe = inspect_authenticode,
) -> list[str]:
    """Validate the selected runtime bytes in a produced onedir candidate."""
    issues = validate_manifest(manifest)
    if manifest.get("distribution_model") == EXTERNAL_DISTRIBUTION_MODEL:
        if not candidate.is_dir():
            return sorted(set(issues + ["microsoft-external-candidate-missing"]))
        for path in candidate.rglob("*"):
            if path.is_file() and path.name.casefold() in EXPECTED_RUNTIME_FILES:
                issues.append(
                    "microsoft-external-candidate-direct-file-forbidden:"
                    + path.relative_to(candidate).as_posix()
                )
        return sorted(set(issues))
    records = {
        str(record["filename"]).casefold(): record
        for record in manifest.get("runtime_files", [])
    }
    found: dict[str, list[Path]] = {}
    for path in candidate.rglob("*.dll"):
        name = path.name.casefold()
        if name in FORBIDDEN_APPLICATION_LOCAL_NAMES or API_SET_NAME.fullmatch(name):
            issues.append(f"microsoft-runtime-candidate-system-runtime-bundled:{name}")
        if MICROSOFT_RUNTIME_NAME.fullmatch(name):
            found.setdefault(name, []).append(path)
    if set(found) != set(records):
        issues.append("microsoft-runtime-candidate-file-set-mismatch")
    for name, paths in found.items():
        if len(paths) != 1:
            issues.append(f"microsoft-runtime-candidate-duplicate:{name}")
        if name in records:
            for path in paths:
                issues.extend(
                    _validate_runtime_file(path, records[name], signature_probe)
                )
    return sorted(set(issues))


def _print_issues(label: str, issues: Sequence[str]) -> int:
    if issues:
        print(f"{label} rejected:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print(f"{label} validated.")
    return 0


def _parse_arguments(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Microsoft runtime packaging inputs."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    authority = commands.add_parser("validate-authority")
    authority.add_argument("--root", type=Path, required=True)
    authority.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    analysis = commands.add_parser("validate-analysis")
    analysis.add_argument("--analysis-toc", type=Path, required=True)
    analysis.add_argument("--runtime-root", type=Path, required=True)
    analysis.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    analysis.add_argument("--project-root", type=Path, default=PROJECT_DIR)
    candidate = commands.add_parser("validate-candidate")
    candidate.add_argument("--candidate", type=Path, required=True)
    candidate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    external = commands.add_parser("validate-external-policy")
    external.add_argument("--manifest", type=Path, default=EXTERNAL_POLICY_MANIFEST)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parse_arguments(arguments)
    manifest = load_manifest(args.manifest)
    if args.command == "validate-external-policy":
        return _print_issues(
            "Microsoft external runtime policy", validate_manifest(manifest)
        )
    if args.command == "validate-authority":
        return _print_issues(
            "Microsoft runtime authority",
            validate_runtime_authority(args.root, manifest),
        )
    if args.command == "validate-analysis":
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        allowed = (
            args.project_root,
            args.runtime_root,
            Path(sys.base_prefix),
            system_root,
        )
        return _print_issues(
            "Microsoft runtime PyInstaller analysis",
            validate_analysis_toc(
                args.analysis_toc,
                manifest,
                runtime_root=args.runtime_root,
                allowed_roots=allowed,
            ),
        )
    return _print_issues(
        "Microsoft runtime candidate",
        validate_candidate_runtime(args.candidate, manifest),
    )


if __name__ == "__main__":
    raise SystemExit(main())
