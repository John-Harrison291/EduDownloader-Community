"""Build-only delivery of the unchanged, pinned portable OCR component.

No download, rebuild, signing, component discovery or runtime installation.
Only allowlisted files are copied into a fresh candidate's component directory.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from pdf_ocr_runtime import COMMUNITY_ENGINE_SHA256, MODEL_SHA256


REQUIRED_LICENSES = (
    "COPYING.MinGW-w64-runtime.txt",
    "COPYING.MinGW-w64.txt",
    "COPYING.winpthreads.txt",
    "Leptonica-BSD.txt",
    "LLVM-MinGW-runtime.txt",
    "tessdata-best-LICENSE.txt",
    "tessdata-fast-LICENSE.txt",
    "Tesseract-Apache-2.0.txt",
)


def _ordinary_directory(path):
    path = Path(path)
    if (
        not path.is_absolute()
        or not path.is_dir()
        or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))
    ):
        raise RuntimeError("OCR delivery requires ordinary absolute directories")
    return path


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _policy(project_root):
    root = _ordinary_directory(project_root)
    policy_path = root / "docs/windows/OCR_COMMUNITY_DELIVERY_MANIFEST.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    source_manifest = root / "ocr_community_sources.json"
    source_hash = hashlib.sha256(
        source_manifest.read_text("utf-8").encode("utf-8")
    ).hexdigest()
    if policy.get("schema") != 1 or policy.get("source_manifest_sha256") != source_hash:
        raise RuntimeError("OCR delivery policy/source manifest mismatch")
    files = policy.get("files")
    if not isinstance(files, dict) or not 5 <= len(files) <= 64:
        raise RuntimeError("Invalid OCR delivery allowlist")
    required = {"tesseract.exe": COMMUNITY_ENGINE_SHA256}
    required.update(
        (f"tessdata_{family}/{language}.traineddata", digest)
        for (family, language), digest in MODEL_SHA256.items()
    )
    expected_names = (
        set(required)
        | {"component.json"}
        | {"Licenses/" + name for name in REQUIRED_LICENSES}
    )
    if set(files) != expected_names or any(
        not isinstance(v, dict) for v in files.values()
    ):
        raise RuntimeError("OCR delivery requires the full component and its licenses")
    if any(
        files.get(name, {}).get("sha256") != digest for name, digest in required.items()
    ):
        raise RuntimeError("OCR delivery must retain the runtime integrity pins")
    return files


def approved_ocr_file(name, data):
    """Narrow build-validator exception: canonical path AND trusted pinned bytes."""
    if not name.startswith("Componentes/OCR/"):
        return False
    root = Path(__file__).resolve().parent
    relative = name.removeprefix("Componentes/OCR/")
    try:
        expected = _policy(root).get(relative)
        return (
            expected is not None
            and len(data) == expected["bytes"]
            and hashlib.sha256(data).hexdigest() == expected["sha256"]
        )
    except (OSError, ValueError, TypeError, RuntimeError, KeyError):
        return False


def approved_ocr_tree(components):
    """Only the full approved OCR tree may occupy Componentes in a new bundle."""
    try:
        components = _ordinary_directory(components)
        project = Path(__file__).resolve().parent
        policy = _policy(project)
        expected = {"OCR/" + relative: item for relative, item in policy.items()}
        directories = {
            p.as_posix()
            for name in expected
            for p in PurePosixPath(name).parents
            if p != PurePosixPath(".")
        }
        seen = set()
        for parent, subdirectories, files in os.walk(components, followlinks=False):
            parent = Path(parent)
            for name in subdirectories:
                path = parent / name
                _ordinary_directory(path)
                if path.relative_to(components).as_posix() not in directories:
                    return False
            for name in files:
                path = parent / name
                relative = path.relative_to(components).as_posix()
                item = expected.get(relative)
                if (
                    item is None
                    or path.is_symlink()
                    or path.is_junction()
                    or not path.is_file()
                    or path.stat().st_size != item["bytes"]
                    or _digest(path) != item["sha256"]
                ):
                    return False
                seen.add(relative)
        return seen == set(expected)
    except (OSError, ValueError, TypeError, RuntimeError, KeyError):
        return False


def validate_ocr_component(project_root, *, source=None):
    root = _ordinary_directory(project_root)
    files = _policy(root)
    source = _ordinary_directory(source or root / "Componentes/OCR-Community")
    for relative, expected in files.items():
        part = PurePosixPath(relative)
        if (
            part.is_absolute()
            or ".." in part.parts
            or "\\" in relative
            or ":" in relative
        ):
            raise RuntimeError("Unsafe OCR delivery filename")
        path = source / relative
        _ordinary_directory(path.parent)
        if (
            path.is_symlink()
            or path.is_junction()
            or not path.is_file()
            or not 0 < path.stat().st_size <= 32 * 1024 * 1024
            or path.stat().st_size != expected.get("bytes")
            or _digest(path) != expected.get("sha256")
        ):
            raise RuntimeError(
                f"Missing, corrupt or unsafe OCR delivery file: {relative}"
            )
    return files


def stage_ocr_component(project_root, candidate, *, source=None):
    """Validate source and copied bytes before an exclusive Windows publication."""
    if os.name != "nt":
        raise RuntimeError("OCR delivery targets Windows bundles")
    source = source or Path(project_root) / "Componentes/OCR-Community"
    files = validate_ocr_component(project_root, source=source)
    candidate = _ordinary_directory(candidate)
    components = candidate / "Componentes"
    if components.exists():
        _ordinary_directory(components)
    destination = components / "OCR"
    if destination.exists() or destination.is_symlink() or destination.is_junction():
        raise FileExistsError("OCR delivery never replaces an existing component")
    # Staging is local to the fresh candidate, never in the source component.
    with tempfile.TemporaryDirectory(prefix=".ocr-delivery-", dir=candidate) as temp:
        staged = Path(temp) / "OCR"
        staged.mkdir()
        for relative, expected in files.items():
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
            if (
                target.stat().st_size != expected["bytes"]
                or _digest(target) != expected["sha256"]
            ):
                raise RuntimeError("OCR input changed while copying; candidate refused")
        components.mkdir(exist_ok=True)
        _ordinary_directory(components)
        os.rename(staged, destination)  # Windows rename refuses a raced destination.
    return destination
