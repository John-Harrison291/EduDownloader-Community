"""Fail-closed edition, archive and private-material gates for internal 2.5 outputs."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import marshal
from pathlib import Path
import re
from types import CodeType
import zipfile

from constants import APP_VERSION, ProductEdition
from edition_profiles import EditionBuildProfile, select_build_profile
from edition_staging import (
    COMPONENT_SOURCES,
    SHARED_SOURCES,
    EXCLUDED_MODULES,
)
from ocr_component_delivery import approved_ocr_file, approved_ocr_tree
from validate_distribution import find_distribution_issues, sha256_file


ROOT = Path(__file__).resolve().parent


def edition_classification(profile: EditionBuildProfile) -> str:
    series = profile.app_version.rsplit(".", 1)[0].replace(".", "_")
    return f"INTERNAL_{series}_EDITION_VALIDATION"


PERSONAL_PATH = re.compile(rb"[a-z]:[\\/]Users[\\/][^\\/\s\x00]+[\\/]", re.I)
PRIVATE_PAYLOAD = re.compile(
    rb"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=\r\n]{32,}",
    re.I,
)
FORBIDDEN_NAMES = re.compile(
    r"(?:^|[./_\\-])(?:license_manager|activation_issuer|tesseract|tessdata|pytesseract)(?:$|[./_\\-])|\.(?:edulic|edureq|dpapi|pk8|p8|p12|pfx|key|sqlite3?|db|traineddata)$|(?:^|/)activation\.dat$",
    re.I,
)
# Exact approved upstream bytes contain CI build paths, not EduDownloader user data.
# Deno: existing pinned external provenance; cryptography: pinned 49.0.0 Windows
# wheel (PYTHON_WHEEL_PROVENANCE.json), member cryptography/hazmat/bindings/_rust.pyd.
# This exception applies ONLY to the path finding, never to secrets or filenames.
UPSTREAM_PATH_BINARIES = {
    "deno.exe": "98f8c2a2d470e4ccb04c935c86ff8050817d877762aec5eaeeb9e409ccb3b9fd",
    "_internal/cryptography/hazmat/bindings/_rust.pyd": "813b101f70efb79c388239ce82ac891e195a1e19eeaeb43c32d9bf425e7b51b8",
}


def _code_signature(code: CodeType):
    def constant(value):
        if isinstance(value, CodeType):
            return _code_signature(value)
        if isinstance(value, (tuple, frozenset)):
            items = [constant(v) for v in value]
            return sorted(items, key=repr) if isinstance(value, frozenset) else items
        return repr(value)

    return [
        code.co_code.hex(),
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_exceptiontable.hex(),
        code.co_stacksize,
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
        code.co_flags,
        [constant(c) for c in code.co_consts],
    ]


def matching_code(actual: CodeType, source: str, filename: str) -> bool:
    expected = compile(source, filename, "exec", dont_inherit=True, optimize=0)
    return _code_signature(actual) == _code_signature(expected)


def archive_contents(
    executable: Path,
) -> tuple[dict[str, CodeType], dict[str, CodeType]]:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    pyzs = [name for name, entry in archive.toc.items() if entry[-1] == "z"]
    if len(pyzs) != 1:
        raise ValueError("Expected exactly one PYZ")
    pyz = archive.open_embedded_archive(pyzs[0])
    modules = {name: pyz.extract(name) for name in pyz.toc}
    scripts = {
        name: marshal.loads(archive.extract(name))
        for name, entry in archive.toc.items()
        if entry[-1] == "s"
    }
    return modules, scripts


def module_issues(names: set[str], profile: EditionBuildProfile) -> list[str]:
    issues = []
    for name in sorted(names):
        if FORBIDDEN_NAMES.search(name) or any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in (
                *EXCLUDED_MODULES,
                "licensing",
                "activation_controller",
                "activation_ui",
                "commercial_activation",
            )
        ):
            issues.append(f"forbidden-module:{name}")
    required = set(SHARED_SOURCES) - {"pyi_rth_edudownloader_tk"}
    required |= {"pypdf", "PIL", "pypdfium2", "pdf_to_docx", "docx_writer"}
    required.update(COMPONENT_SOURCES)
    issues.extend(f"missing-module:{name}" for name in sorted(required - names))
    return issues


def payload_issues(name: str, data: bytes) -> list[str]:
    result = []
    if FORBIDDEN_NAMES.search(name) and not approved_ocr_file(name, data):
        result.append(f"private-or-ocr-artifact:{name}")
    if PRIVATE_PAYLOAD.search(data):
        result.append(f"private-key-payload:{name}")
    upstream_bytes = (
        name in UPSTREAM_PATH_BINARIES
        and hashlib.sha256(data).hexdigest() == UPSTREAM_PATH_BINARIES[name]
    )
    if not upstream_bytes and (
        PERSONAL_PATH.search(data) or PERSONAL_PATH.search(data.replace(b"\x00", b""))
    ):
        result.append(f"personal-absolute-path:{name}")
    return result


def collected_toc_issues(toc: object) -> list[str]:
    """Inspect collected entries, not the spec's list of excluded private modules."""
    issues = []
    collected_types = {
        "PYMODULE",
        "PYMODULE-1",
        "PYMODULE-2",
        "PYSOURCE",
        "EXTENSION",
        "BINARY",
        "DATA",
        "ZIPFILE",
        "EXECUTABLE",
    }

    def walk(value):
        if isinstance(value, (tuple, list)):
            if (
                len(value) == 3
                and all(isinstance(v, str) for v in value)
                and value[2] in collected_types
            ):
                yield value
            else:
                for item in value:
                    yield from walk(item)

    for name, source, _kind in walk(toc):
        if any(FORBIDDEN_NAMES.search(v.replace("\\", "/")) for v in (name, source)):
            issues.append("forbidden-collected-toc-entry")
    return issues


def embedded_zip_issues(name: str, data: bytes, depth: int = 0) -> list[str]:
    """Bounded inspection includes compressed payloads, not only archive filenames."""
    if depth > 2:
        return [f"nested-archive-limit:{name}"]
    issues = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 4096 or sum(i.file_size for i in infos) > 128 * 1024 * 1024:
                return [f"archive-limits:{name}"]
            for info in infos:
                member = name + "/" + info.filename
                if info.flag_bits & 1 or info.file_size > 32 * 1024 * 1024:
                    issues.append(f"archive-member-limit-or-encrypted:{member}")
                    continue
                content = archive.read(info)
                issues.extend(payload_issues(member, content))
                if info.filename.casefold().endswith(".zip"):
                    issues.extend(embedded_zip_issues(member, content, depth + 1))
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
        issues.append(f"embedded-archive-unreadable:{name}")
    return issues


def executable_version_issues(
    executable: Path, version: str = APP_VERSION
) -> list[str]:
    """Read PE resources as data; reject missing or mismatched product identity."""
    try:
        import pefile
    except ImportError:
        return ["windows-version-unreadable"]
    expected = tuple(int(part) for part in version.split(".")) + (0,)
    issues = []
    try:
        with pefile.PE(str(executable), fast_load=True) as pe:
            pe.parse_data_directories(
                directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
            )
            fixed = pe.VS_FIXEDFILEINFO
            if len(fixed) != 1:
                return ["windows-version-unreadable"]
            for label, high, low in (
                ("file", fixed[0].FileVersionMS, fixed[0].FileVersionLS),
                ("product", fixed[0].ProductVersionMS, fixed[0].ProductVersionLS),
            ):
                if (high >> 16, high & 65535, low >> 16, low & 65535) != expected:
                    issues.append(f"windows-{label}-version-mismatch")
            tables = [
                table.entries
                for group in pe.FileInfo
                for entry in group
                if entry.Key == b"StringFileInfo"
                for table in entry.StringTable
            ]
            if not tables or any(
                table.get(key) != version.encode("ascii")
                for table in tables
                for key in (b"FileVersion", b"ProductVersion")
            ):
                issues.append("windows-string-version-mismatch")
    except (OSError, ValueError, AttributeError, TypeError, pefile.PEFormatError):
        return ["windows-version-unreadable"]
    return issues


def find_edition_issues(
    root: Path,
    profile: EditionBuildProfile,
    *,
    project: Path = ROOT,
    analysis_toc: Path | None = None,
) -> list[str]:
    issues = find_distribution_issues(root)
    if not approved_ocr_tree(root / "Componentes"):
        issues.append("portable-ocr-missing-or-unverified")
    issues.extend(
        executable_version_issues(root / "EduDownloader.exe", profile.app_version)
    )
    if root.name != profile.output_directory:
        issues.append("edition-output-name-mismatch")
    try:
        modules, scripts = archive_contents(root / "EduDownloader.exe")
        issues.extend(module_issues(set(modules), profile))
        expected_constants = (project / "constants.py").read_text("utf-8")
        if not matching_code(modules["constants"], expected_constants, "constants.py"):
            issues.append("frozen-edition-constants-mismatch")
        entrypoint = Path(profile.entrypoint).stem
        if entrypoint not in scripts or not matching_code(
            scripts[entrypoint],
            (project / profile.entrypoint).read_text("utf-8"),
            profile.entrypoint,
        ):
            issues.append("frozen-entrypoint-mismatch")
        expected_sources = set(SHARED_SOURCES) - {
            "constants",
            "pyi_rth_edudownloader_tk",
        }
        expected_sources.update(COMPONENT_SOURCES)
        for name in expected_sources:
            if not matching_code(
                modules[name],
                (project / (name + ".py")).read_text("utf-8"),
                name + ".py",
            ):
                issues.append(f"frozen-shared-source-mismatch:{name}")
        for name, code in {**modules, **scripts}.items():
            if isinstance(code, CodeType):
                issues.extend(payload_issues(name, marshal.dumps(code)))
    except (OSError, ValueError, KeyError, ImportError, TypeError, EOFError):
        issues.append("frozen-archive-unreadable-or-incomplete")
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            issues.append("distribution-link-forbidden")
        elif path.is_file():
            relative = path.relative_to(root).as_posix()
            data = path.read_bytes()
            issues.extend(payload_issues(relative, data))
            if path.suffix.casefold() == ".zip":
                issues.extend(embedded_zip_issues(relative, data))
    if analysis_toc is not None:
        try:
            toc = ast.literal_eval(analysis_toc.read_text("utf-8"))

            issues.extend(collected_toc_issues(toc))
        except (OSError, ValueError, SyntaxError):
            issues.append("analysis-toc-unreadable")
    return sorted(set(issues))


def inventory(root: Path) -> dict:
    files = [
        {
            "path": p.relative_to(root).as_posix(),
            "size": p.stat().st_size,
            "sha256": sha256_file(p).upper(),
        }
        for p in sorted(root.rglob("*"))
        if p.is_file()
    ]
    canonical = json.dumps(
        files, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return {
        "files": files,
        "file_count": len(files),
        "total_bytes": sum(f["size"] for f in files),
        "inventory_sha256": hashlib.sha256(canonical).hexdigest().upper(),
    }


def zip_issues(path: Path, root: Path) -> list[str]:
    """ZIP must match the validated directory exactly, including every byte."""
    expected = {
        root.name + "/" + p.relative_to(root).as_posix(): p
        for p in root.rglob("*")
        if p.is_file()
    }
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != set(expected):
                return ["zip-members-mismatch"]
            for info in archive.infolist():
                source = expected[info.filename]
                if info.file_size != source.stat().st_size:
                    return ["zip-size-mismatch"]
                digest = hashlib.sha256()
                with archive.open(info) as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                if digest.hexdigest() != sha256_file(source):
                    return ["zip-content-mismatch"]
    except (OSError, ValueError, zipfile.BadZipFile):
        return ["zip-unreadable"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", required=True, choices=list(ProductEdition))
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--analysis-toc", type=Path)
    parser.add_argument("--zip", type=Path)
    args = parser.parse_args()
    profile = select_build_profile(args.edition)
    issues = find_edition_issues(args.dist, profile, analysis_toc=args.analysis_toc)
    if args.zip:
        issues.extend(zip_issues(args.zip, args.dist))
    print(
        json.dumps(
            {
                "edition": args.edition,
                "app_version": profile.app_version,
                "classification": edition_classification(profile),
                "issues": issues,
            },
            ensure_ascii=False,
        )
    )
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
