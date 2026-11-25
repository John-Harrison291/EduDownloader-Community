"""Captura e valida a baseline exata de wheels do build Community."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path
from typing import Any

from packaging.tags import Tag, compatible_tags, cpython_tags
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from validate_build_environment import canonicalize_distribution_name


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_LOCK_PATH = PROJECT_DIR / "requirements-build.lock"
DEFAULT_HASHED_LOCK_PATH = PROJECT_DIR / "requirements-build-hashes.lock"
DEFAULT_MANIFEST_PATH = (
    PROJECT_DIR / "docs" / "compliance" / "python" / "PYTHON_WHEEL_PROVENANCE.json"
)
SCHEMA_VERSION = 1
EXPECTED_PYTHON_VERSION = "3.14.6"
EXPECTED_IMPLEMENTATION = "CPython"
EXPECTED_ARCHITECTURE = "x86_64"
EXPECTED_PLATFORM_TAG = "win_amd64"
EXPECTED_PACKAGE_COUNT = 17
PYPI_INDEX_HOST = "pypi.org"
PYPI_INDEX_URL = f"https://{PYPI_INDEX_HOST}/simple"
CAPTURE_CLASSIFICATION = "A"
SDIST_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".zip")
NATIVE_SUFFIXES = (".dll", ".exe", ".pyd", ".so", ".dylib")
_LOCK_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")
_HASHED_LOCK_PATTERN = re.compile(
    r"^([A-Za-z0-9_.-]+)==([^\s;]+)\s+--hash=sha256:([0-9a-fA-F]{64})$"
)


RELATIONSHIPS = {
    "altgraph": "transitive: pyinstaller",
    "cffi": "transitive: cryptography",
    "cryptography": "direct runtime dependency",
    "customtkinter": "direct runtime dependency",
    "darkdetect": "transitive: customtkinter",
    "packaging": "build tooling dependency",
    "pefile": "transitive: pyinstaller on Windows",
    "pillow": "direct runtime dependency",
    "pip": "build environment bootstrap tooling",
    "pycparser": "transitive: cffi",
    "pyinstaller": "direct build dependency",
    "pyinstaller-hooks-contrib": "transitive: pyinstaller",
    "pypdf": "direct runtime dependency",
    "pypdfium2": "direct runtime dependency",
    "pywin32-ctypes": "transitive: pyinstaller on Windows",
    "ruff": "direct development/build validation dependency",
    "setuptools": "build environment bootstrap tooling",
}

IMPORT_SMOKE_MODULES = (
    "altgraph",
    "cffi",
    "cryptography",
    "customtkinter",
    "darkdetect",
    "packaging",
    "pefile",
    "PIL",
    "pip",
    "pycparser",
    "PyInstaller",
    "_pyinstaller_hooks_contrib",
    "pypdf",
    "pypdfium2",
    "win32ctypes",
    "setuptools",
)


@dataclass(frozen=True)
class LockedPackage:
    """Uma entrada exata do lock humano/canônico."""

    name: str
    normalized_name: str
    version: str
    marker: str | None
    relationship: str


def sha256_file(path: Path) -> str:
    """Calcula SHA-256 sem carregar o artefato inteiro na memória."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def canonical_json_bytes(value: Any) -> bytes:
    """Serializa JSON determinístico usado por manifesto e inventário."""
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def read_locked_packages(path: Path) -> tuple[dict[str, LockedPackage], list[str]]:
    """Lê pins exatos e registra a relação conhecida de cada dependência."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}, ["Lock do ambiente de build ausente ou ilegível"]

    packages: dict[str, LockedPackage] = {}
    issues: list[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_PATTERN.fullmatch(line)
        if match is None:
            issues.append(f"Entrada não exata no lock: linha {line_number}")
            continue
        name, version = match.groups()
        normalized_name = canonicalize_distribution_name(name)
        if normalized_name in packages:
            issues.append(f"Dependência duplicada no lock: {normalized_name}")
            continue
        packages[normalized_name] = LockedPackage(
            name=name,
            normalized_name=normalized_name,
            version=version,
            marker=None,
            relationship=RELATIONSHIPS.get(normalized_name, "relationship unknown"),
        )
    if not packages:
        issues.append("Lock do ambiente de build está vazio")
    return packages, issues


def read_hashed_lock(path: Path) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Lê o lock consumível pelo pip e exige um SHA-256 por pin."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}, ["Lock hash-pinned ausente ou ilegível"]

    packages: dict[str, tuple[str, str]] = {}
    issues: list[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _HASHED_LOCK_PATTERN.fullmatch(line)
        if match is None:
            issues.append(f"Entrada inválida no lock hash-pinned: linha {line_number}")
            continue
        name, version, digest = match.groups()
        normalized_name = canonicalize_distribution_name(name)
        if normalized_name in packages:
            issues.append(
                f"Dependência duplicada no lock hash-pinned: {normalized_name}"
            )
            continue
        packages[normalized_name] = (version, digest.upper())
    if not packages:
        issues.append("Lock hash-pinned está vazio")
    return packages, issues


def target_supported_tags() -> frozenset[Tag]:
    """Tags aceitas pela baseline CPython 3.14 / Windows x86-64."""
    tags = set(
        cpython_tags(
            python_version=(3, 14),
            abis=("cp314",),
            platforms=(EXPECTED_PLATFORM_TAG,),
        )
    )
    tags.update(
        compatible_tags(
            python_version=(3, 14),
            interpreter="cp314",
            platforms=(EXPECTED_PLATFORM_TAG,),
        )
    )
    return frozenset(tags)


def _wheel_license_files(names: list[str]) -> list[str]:
    prefixes = ("license", "copying", "notice", "authors")
    return sorted(
        name
        for name in names
        if any(part.casefold().startswith(prefixes) for part in Path(name).parts)
    )


def inspect_wheel(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Inspeciona identidade, metadata, licenças e payload nativo sem extrair."""
    issues: list[str] = []
    try:
        distribution, version, _build, tags = parse_wheel_filename(path.name)
    except InvalidWheelFilename:
        return None, [f"Nome de wheel inválido: {path.name}"]

    try:
        with zipfile.ZipFile(path) as archive:
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                return None, [f"Wheel corrompido em {corrupt_member}: {path.name}"]
            names = sorted(archive.namelist())
            metadata_paths = [
                name
                for name in names
                if name.endswith(".dist-info/METADATA") and name.count("/") == 1
            ]
            if len(metadata_paths) != 1:
                return None, [f"Wheel sem METADATA único: {path.name}"]
            metadata_path = metadata_paths[0]
            dist_info_dir = metadata_path.rsplit("/", maxsplit=1)[0]
            wheel_metadata_path = f"{dist_info_dir}/WHEEL"
            record_path = f"{dist_info_dir}/RECORD"
            for required_path in (wheel_metadata_path, record_path):
                if required_path not in names:
                    issues.append(f"Wheel sem {Path(required_path).name}: {path.name}")

            metadata = BytesParser(policy=compat32).parsebytes(
                archive.read(metadata_path)
            )
            wheel_metadata = archive.read(wheel_metadata_path).decode(
                "utf-8", errors="strict"
            )
    except (OSError, UnicodeError, zipfile.BadZipFile, KeyError) as error:
        return None, [f"Wheel ilegível {path.name}: {type(error).__name__}"]

    normalized_name = canonicalize_distribution_name(str(distribution))
    metadata_name = canonicalize_distribution_name(metadata.get("Name", ""))
    metadata_version = metadata.get("Version", "")
    if metadata_name != normalized_name:
        issues.append(f"Name do METADATA diverge do filename: {path.name}")
    if metadata_version != str(version):
        issues.append(f"Version do METADATA diverge do filename: {path.name}")

    wheel_declared_tags = sorted(
        line.removeprefix("Tag:").strip()
        for line in wheel_metadata.splitlines()
        if line.startswith("Tag:")
    )
    if not wheel_declared_tags:
        issues.append(f"WHEEL sem Tag: {path.name}")

    native_payloads = sorted(
        name for name in names if name.casefold().endswith(NATIVE_SUFFIXES)
    )
    license_files = _wheel_license_files(names)
    declared_license_files = sorted(metadata.get_all("License-File") or [])
    license_expression = (
        metadata.get("License-Expression") or metadata.get("License") or "UNKNOWN"
    ).strip()

    record = {
        "authority": PYPI_INDEX_URL,
        "declared_license": license_expression,
        "declared_license_files": declared_license_files,
        "dist_info": dist_info_dir,
        "distribution": normalized_name,
        "filename": path.name,
        "license_files": license_files,
        "marker": None,
        "native_payload_files": native_payloads,
        "native_payload_present": bool(native_payloads),
        "relationship": RELATIONSHIPS.get(normalized_name, "relationship unknown"),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "tags": sorted(str(tag) for tag in tags),
        "version": str(version),
        "wheel_metadata_tags": wheel_declared_tags,
    }
    return record, issues


def wheel_inventory_sha256(records: list[dict[str, Any]]) -> str:
    """Hash do inventário material, independente de timestamp e caminho local."""
    material = [
        {
            "distribution": record["distribution"],
            "filename": record["filename"],
            "sha256": record["sha256"],
            "size": record["size"],
            "tags": record["tags"],
            "version": record["version"],
        }
        for record in sorted(records, key=lambda item: item["distribution"])
    ]
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest().upper()


def inspect_wheelhouse(
    wheelhouse: Path,
    locked: dict[str, LockedPackage],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Exige conjunto wheel-only exato, versões pinadas e tags compatíveis."""
    issues: list[str] = []
    if not wheelhouse.is_dir():
        return [], ["Wheelhouse ausente ou não é diretório"]

    files = sorted(path for path in wheelhouse.rglob("*") if path.is_file())
    records: list[dict[str, Any]] = []
    for path in files:
        if path.parent != wheelhouse:
            issues.append(
                f"Artefato aninhado inesperado: {path.relative_to(wheelhouse)}"
            )
            continue
        lowercase_name = path.name.casefold()
        if lowercase_name.endswith(SDIST_SUFFIXES):
            issues.append(f"Source distribution proibida: {path.name}")
            continue
        if path.suffix.casefold() != ".whl":
            issues.append(f"Artefato não-wheel inesperado: {path.name}")
            continue
        record, wheel_issues = inspect_wheel(path)
        issues.extend(wheel_issues)
        if record is not None:
            records.append(record)

    actual_by_name: dict[str, dict[str, Any]] = {}
    for record in records:
        name = record["distribution"]
        if name in actual_by_name:
            issues.append(f"Wheel duplicado para package/version: {name}")
        else:
            actual_by_name[name] = record

    for name in sorted(locked.keys() - actual_by_name.keys()):
        issues.append(f"Wheel esperado ausente: {name}")
    for name in sorted(actual_by_name.keys() - locked.keys()):
        issues.append(f"Wheel inesperado: {name}")
    supported_tags = target_supported_tags()
    for name in sorted(locked.keys() & actual_by_name.keys()):
        locked_package = locked[name]
        record = actual_by_name[name]
        if record["version"] != locked_package.version:
            issues.append(f"Versão divergente do wheel: {name}")
        parsed_tags = {Tag(*tag.split("-")) for tag in record["tags"]}
        if not parsed_tags & supported_tags:
            issues.append(f"Tags incompatíveis com CPython 3.14 win_amd64: {name}")

    return sorted(records, key=lambda item: item["distribution"]), issues


def generate_hashed_lock_text(records: list[dict[str, Any]]) -> str:
    """Gera um artifact identity por package/version para --require-hashes."""
    header = (
        "# Baseline Windows x86-64 / CPython 3.14.6.\n"
        "# Gerado a partir de PYTHON_WHEEL_PROVENANCE.json; não editar manualmente.\n"
    )
    entries = "\n".join(
        f"{record['distribution']}=={record['version']} "
        f"--hash=sha256:{record['sha256'].lower()}"
        for record in sorted(records, key=lambda item: item["distribution"])
    )
    return f"{header}{entries}\n"


def offline_install_command(
    python_executable: Path,
    wheelhouse: Path,
    hashed_lock: Path,
) -> list[str]:
    """Monta a instalação offline sem fallback de índice ou hash opcional."""
    return [
        str(python_executable),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "--require-hashes",
        "-r",
        str(hashed_lock),
    ]


def build_manifest(
    lock_path: Path,
    records: list[dict[str, Any]],
    hashed_lock_text: str,
    *,
    proof_complete: bool,
    recorded_on: str,
) -> dict[str, Any]:
    """Constrói o manifesto rastreado sem timestamp ou caminho pessoal."""
    proof_status = "PASS" if proof_complete else "PENDING"
    total_size = sum(record["size"] for record in records)
    return {
        "capture_classification": (
            CAPTURE_CLASSIFICATION if proof_complete else "B_PARTIAL"
        ),
        "capture_policy": {
            "artifact_identity_per_package": 1,
            "index_url": PYPI_INDEX_URL,
            "no_dependencies_during_download": True,
            "only_binary_all": True,
            "sdists_allowed": False,
        },
        "lock": {
            "all_versions_exact": True,
            "package_count": len(records),
            "path": lock_path.name,
            "sha256": sha256_file(lock_path),
        },
        "offline_proof": {
            "environment_exactness": proof_status,
            "import_smoke": proof_status,
            "missing_wheel_fail_closed": proof_status,
            "no_index": proof_complete,
            "pip_check": proof_status,
            "require_hashes": proof_complete,
        },
        "packages": records,
        "recorded_on": recorded_on,
        "schema_version": SCHEMA_VERSION,
        "target": {
            "architecture": EXPECTED_ARCHITECTURE,
            "implementation": EXPECTED_IMPLEMENTATION,
            "platform_tag": EXPECTED_PLATFORM_TAG,
            "python_version": EXPECTED_PYTHON_VERSION,
        },
        "wheelhouse": {
            "file_count": len(records),
            "inventory_sha256": wheel_inventory_sha256(records),
            "total_size": total_size,
            "tracked_in_git": False,
        },
        "hashed_lock": {
            "path": DEFAULT_HASHED_LOCK_PATH.name,
            "sha256": hashlib.sha256(hashed_lock_text.encode("utf-8"))
            .hexdigest()
            .upper(),
        },
    }


def validate_manifest(
    lock_path: Path,
    hashed_lock_path: Path,
    manifest_path: Path,
    *,
    wheelhouse: Path | None = None,
) -> list[str]:
    """Valida metadata rastreada e, opcionalmente, a wheelhouse preservada."""
    locked, issues = read_locked_packages(lock_path)
    hashed, hashed_issues = read_hashed_lock(hashed_lock_path)
    issues.extend(hashed_issues)
    try:
        raw_manifest = manifest_path.read_bytes()
        manifest = json.loads(raw_manifest)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return issues + ["Manifesto de wheels ausente, ilegível ou inválido"]

    if raw_manifest != canonical_json_bytes(manifest):
        issues.append("Manifesto de wheels não está em JSON canônico")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        issues.append("Schema do manifesto de wheels não suportado")
    if manifest.get("capture_classification") != CAPTURE_CLASSIFICATION:
        issues.append("Wheel Integrity Capture ainda não está em classe A")
    expected_capture_policy = {
        "artifact_identity_per_package": 1,
        "index_url": PYPI_INDEX_URL,
        "no_dependencies_during_download": True,
        "only_binary_all": True,
        "sdists_allowed": False,
    }
    if manifest.get("capture_policy") != expected_capture_policy:
        issues.append("Política de captura do manifesto diverge da baseline")
    target = manifest.get("target", {})
    expected_target = {
        "architecture": EXPECTED_ARCHITECTURE,
        "implementation": EXPECTED_IMPLEMENTATION,
        "platform_tag": EXPECTED_PLATFORM_TAG,
        "python_version": EXPECTED_PYTHON_VERSION,
    }
    if target != expected_target:
        issues.append("Target do manifesto diverge da baseline aprovada")

    manifest_packages = manifest.get("packages")
    if not isinstance(manifest_packages, list):
        return issues + ["Lista packages ausente no manifesto"]
    manifest_by_name = {
        package.get("distribution"): package
        for package in manifest_packages
        if isinstance(package, dict)
    }
    if len(manifest_by_name) != len(manifest_packages):
        issues.append("Packages duplicados ou inválidos no manifesto")
    if set(manifest_by_name) != set(locked):
        issues.append("Conjunto de packages do manifesto diverge do lock")
    if len(manifest_packages) != EXPECTED_PACKAGE_COUNT:
        issues.append("Quantidade de packages do manifesto diverge da baseline")
    if set(hashed) != set(locked):
        issues.append("Conjunto do lock hash-pinned diverge do lock canônico")
    if manifest.get("lock", {}).get("package_count") != len(locked):
        issues.append("Contagem do lock no manifesto diverge da baseline")
    if manifest.get("wheelhouse", {}).get("file_count") != len(manifest_packages):
        issues.append("Contagem da wheelhouse no manifesto diverge das entries")
    if manifest.get("wheelhouse", {}).get("tracked_in_git") is not False:
        issues.append("Manifesto não preserva a política de wheelhouse ignorada")

    manifest_records_valid = True
    supported_tags = target_supported_tags()
    for package in manifest_packages:
        try:
            distribution, version, _build, filename_tags = parse_wheel_filename(
                package["filename"]
            )
            recorded_tags = {Tag(*tag.split("-")) for tag in package["tags"]}
            digest = package["sha256"]
            native_payload_files = package["native_payload_files"]
        except (InvalidWheelFilename, KeyError, TypeError, ValueError):
            issues.append("Entry de package inválida no manifesto")
            manifest_records_valid = False
            continue
        if canonicalize_distribution_name(str(distribution)) != package.get(
            "distribution"
        ):
            issues.append(f"Filename diverge do package: {package.get('distribution')}")
        if str(version) != package.get("version"):
            issues.append(f"Filename diverge da versão: {package.get('distribution')}")
        if recorded_tags != filename_tags or not recorded_tags & supported_tags:
            issues.append(f"Tags inválidas no manifesto: {package.get('distribution')}")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9A-F]{64}", digest) is None:
            issues.append(
                f"SHA-256 inválido no manifesto: {package.get('distribution')}"
            )
        if not isinstance(package.get("size"), int) or package["size"] <= 0:
            issues.append(
                f"Tamanho inválido no manifesto: {package.get('distribution')}"
            )
        if package.get("native_payload_present") is not bool(native_payload_files):
            issues.append(
                f"Inventário nativo incoerente: {package.get('distribution')}"
            )

    if manifest_records_valid:
        if manifest.get("wheelhouse", {}).get("inventory_sha256") != (
            wheel_inventory_sha256(manifest_packages)
        ):
            issues.append("Inventário derivado das entries diverge do manifesto")
        if manifest.get("wheelhouse", {}).get("total_size") != sum(
            package["size"] for package in manifest_packages
        ):
            issues.append("Tamanho derivado das entries diverge do manifesto")

    for name in sorted(set(locked) & set(manifest_by_name)):
        package = manifest_by_name[name]
        if package.get("version") != locked[name].version:
            issues.append(f"Versão do manifesto diverge do lock: {name}")
        if package.get("relationship") != locked[name].relationship:
            issues.append(f"Relação direta/transitiva divergente: {name}")
        hashed_entry = hashed.get(name)
        if hashed_entry != (locked[name].version, package.get("sha256")):
            issues.append(f"Hash lock diverge do manifesto: {name}")

    expected_hashed_lock_sha = (
        hashlib.sha256(
            hashed_lock_path.read_bytes() if hashed_lock_path.is_file() else b""
        )
        .hexdigest()
        .upper()
    )
    if manifest.get("hashed_lock", {}).get("sha256") != expected_hashed_lock_sha:
        issues.append("SHA-256 do lock hash-pinned diverge do manifesto")
    if manifest.get("lock", {}).get("sha256") != sha256_file(lock_path):
        issues.append("SHA-256 do lock canônico diverge do manifesto")

    proof = manifest.get("offline_proof", {})
    for key in (
        "environment_exactness",
        "import_smoke",
        "missing_wheel_fail_closed",
        "pip_check",
    ):
        if proof.get(key) != "PASS":
            issues.append(f"Prova offline pendente ou inválida: {key}")
    for key in ("no_index", "require_hashes"):
        if proof.get(key) is not True:
            issues.append(f"Política offline não comprovada: {key}")

    if wheelhouse is not None:
        actual_records, wheelhouse_issues = inspect_wheelhouse(wheelhouse, locked)
        issues.extend(wheelhouse_issues)
        if actual_records != manifest_packages:
            issues.append("Conteúdo da wheelhouse diverge do manifesto")
        actual_inventory = wheel_inventory_sha256(actual_records)
        if manifest.get("wheelhouse", {}).get("inventory_sha256") != actual_inventory:
            issues.append("Inventário da wheelhouse diverge do manifesto")
        if manifest.get("wheelhouse", {}).get("total_size") != sum(
            record["size"] for record in actual_records
        ):
            issues.append("Tamanho total da wheelhouse diverge do manifesto")
    return issues


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Captura ou valida a baseline exata de wheels do build."
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--hashed-lock", type=Path, default=DEFAULT_HASHED_LOCK_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--proof-complete", action="store_true")
    parser.add_argument("--recorded-on", default="2026-09-01")
    parser.add_argument("--evidence", type=Path)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    args = _parse_arguments(arguments)
    if args.capture:
        if args.wheelhouse is None:
            print("--capture exige --wheelhouse")
            return 1
        locked, issues = read_locked_packages(args.lock)
        records, wheelhouse_issues = inspect_wheelhouse(args.wheelhouse, locked)
        issues.extend(wheelhouse_issues)
        if issues:
            print("Wheelhouse rejeitada:")
            for issue in issues:
                print(f"- {issue}")
            return 1
        hashed_lock_text = generate_hashed_lock_text(records)
        manifest = build_manifest(
            args.lock,
            records,
            hashed_lock_text,
            proof_complete=args.proof_complete,
            recorded_on=args.recorded_on,
        )
        args.hashed_lock.write_bytes(hashed_lock_text.encode("utf-8"))
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_bytes(canonical_json_bytes(manifest))
        if args.evidence is not None:
            evidence = {
                "captured_at_utc": datetime.now(UTC).isoformat(),
                "download_command_policy": ["--only-binary=:all:", "--no-deps"],
                "index_url": PYPI_INDEX_URL,
                "wheelhouse_inventory_sha256": manifest["wheelhouse"][
                    "inventory_sha256"
                ],
            }
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_bytes(canonical_json_bytes(evidence))
        print(
            "Wheelhouse capturada: "
            f"{len(records)} wheels; "
            f"inventory_sha256={manifest['wheelhouse']['inventory_sha256']}"
        )
        return 0

    issues = validate_manifest(
        args.lock,
        args.hashed_lock,
        args.manifest,
        wheelhouse=args.wheelhouse,
    )
    if issues:
        print("Wheel Integrity inválida:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Wheel Integrity classe A validada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
