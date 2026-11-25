"""Compila e valida um candidato local do EduDownloader Community."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

from constants import APP_VERSION, ProductEdition, REQUIRED_EXECUTABLES
from edition_profiles import select_build_profile
from edition_staging import stage_sources
from ocr_component_delivery import stage_ocr_component, validate_ocr_component


ROOT = Path(__file__).resolve().parent
SOURCE_DIRECTORIES = ("Licencas", "branding", "docs", "installer", "tests")


def source_inventory(root: Path) -> dict[str, str]:
    """Hash the local source and build configuration before validation."""
    paths = [
        p
        for p in root.iterdir()
        if p.is_file()
        and p.name != "settings.json"
        and (
            p.suffix in {".py", ".json", ".txt", ".lock", ".spec"}
            or p.name in {".gitattributes", ".gitignore"}
        )
    ]
    for directory in SOURCE_DIRECTORIES:
        paths.extend(
            p
            for p in (root / directory).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
    inventory = {}
    for path in paths:
        if path.is_symlink() or path.is_junction():
            raise RuntimeError(f"Unexpected linked source: {path.relative_to(root)}")
        inventory[path.relative_to(root).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    inventory["../LICENSE"] = hashlib.sha256(
        (root.parent / "LICENSE").read_bytes()
    ).hexdigest()
    return inventory


def run_build(
    edition: str,
    *,
    expected_version: str | None = None,
    inputs_root: Path = ROOT,
    output_root: Path | None = None,
) -> Path:
    profile = select_build_profile(edition)
    version = profile.app_version
    expected_version = version if expected_version is None else expected_version
    if (
        APP_VERSION != select_build_profile("community").app_version
        or expected_version != version
        or platform.python_version() != "3.14.6"
        or os.name != "nt"
        or sys.maxsize <= 2**32
    ):
        raise RuntimeError(
            f"Requires Windows x64 CPython 3.14.6 and requested version {version}"
        )
    inputs_root = inputs_root.resolve(strict=True)
    ocr_source = inputs_root / "Componentes/OCR-Community"
    validate_ocr_component(ROOT, source=ocr_source)
    inputs = source_inventory(ROOT)
    parent = output_root or ROOT / ("build-editions-" + version.rsplit(".", 1)[0])
    parent.mkdir(exist_ok=True)
    if parent.is_symlink() or parent.is_junction():
        raise RuntimeError("Unsafe build parent")
    run_root = Path(tempfile.mkdtemp(prefix=edition + "-", dir=parent))
    print(f"INTERNAL_BUILD_ROOT={run_root}", flush=True)
    evidence = run_root / "evidence"
    evidence.mkdir()
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PIP_NO_INDEX": "1",
        "EDUDOWNLOADER_WHEELHOUSE": str(
            inputs_root / "build-compliance-wheels/wheelhouse"
        ),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    steps = []

    def run(label, command, cwd=ROOT):
        print(f"STEP {label}", flush=True)
        with (evidence / f"{label}.log").open("wb") as log:
            completed = subprocess.run(
                [str(v) for v in command],
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        steps.append({"step": label, "exit_code": completed.returncode})
        (evidence / "steps.json").write_text(
            json.dumps(steps, indent=2) + "\n", encoding="utf-8"
        )
        if completed.returncode:
            raise RuntimeError(f"Gate failed: {label}; see isolated evidence log")

    run("create-environment", [sys.executable, "-m", "venv", run_root / "venv"])
    python = run_root / "venv/Scripts/python.exe"
    run(
        "offline-install",
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            inputs_root / "build-compliance-wheels/wheelhouse",
            "--require-hashes",
            "-r",
            ROOT / "requirements-build-hashes.lock",
        ],
    )
    run(
        "wheel-integrity",
        [
            python,
            "validate_python_wheels.py",
            "--lock",
            "requirements-build.lock",
            "--hashed-lock",
            "requirements-build-hashes.lock",
            "--manifest",
            "docs/compliance/python/PYTHON_WHEEL_PROVENANCE.json",
            "--wheelhouse",
            inputs_root / "build-compliance-wheels/wheelhouse",
        ],
    )
    run("pip-check", [python, "-m", "pip", "check"])
    run(
        "environment",
        [python, "validate_build_environment.py", "--lock", "requirements-build.lock"],
    )
    run(
        "externals",
        [
            python,
            "validate_frozen_candidate.py",
            "validate-externals",
            "--root",
            inputs_root,
        ],
    )
    run("notices-source", [python, "notice_delivery.py", "validate"])
    run("full-suite", [python, "run_test_suite.py"])
    # The checks run from ROOT. Relative paths keep the Windows command line
    # within its length limit when the checkout is nested in a QA directory.
    python_paths = [p for p in inputs if p.endswith(".py")]
    run("ruff", [python, "-m", "ruff", "check", *python_paths])
    run("format", [python, "-m", "ruff", "format", "--check", *python_paths])
    run("compileall", [python, "-m", "compileall", "-q", *python_paths])
    if inputs != source_inventory(ROOT):
        raise RuntimeError(
            "Source inputs changed during validation; refusing to freeze"
        )
    stage = run_root / "source"
    stage_sources(ROOT, stage, profile)
    # Hash every staged input, including immutable edition composition. Not shipped.
    (evidence / "staging.json").write_text(
        json.dumps(
            {
                p.relative_to(stage).as_posix(): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in sorted(stage.rglob("*"))
                if p.is_file()
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run(
        "pyinstaller",
        [
            python,
            ROOT / "build_pyinstaller.py",
            "--project-root",
            ROOT,
            "--workpath",
            run_root / "work",
            "--distpath",
            run_root / "dist",
            "--microsoft-runtime-manifest",
            ROOT / "docs/compliance/microsoft/MICROSOFT_EXTERNAL_RUNTIME_POLICY.json",
            stage / "EduDownloader.spec",
        ],
        cwd=stage,
    )
    run(
        "warnings",
        [
            python,
            "validate_pyinstaller_warnings.py",
            "--warnings",
            run_root / "work/EduDownloader/warn-EduDownloader.txt",
            "--baseline",
            "pyinstaller-warnings-baseline.txt",
            "--explained",
            "pyinstaller-warnings-explained.txt",
        ],
    )
    portable = run_root / "dist/EduDownloader-Portable"
    output = run_root / "dist" / profile.output_directory
    # Only rename this freshly-created output, never historical candidates.
    portable.rename(output)
    for filename in REQUIRED_EXECUTABLES:
        shutil.copyfile(inputs_root / filename, output / filename)
    stage_ocr_component(ROOT, output, source=ocr_source)
    (output / "README.txt").write_text(
        f"EduDownloader {version} — {profile.edition.value.title()}\n"
        "INTERNAL VALIDATION ONLY — não autorizado para publicação.\n\n"
        "Downloads, Arquivos, PDF, Documentos, Mídia, Configurações e Início.\n"
        "PDF para Word: PDFium + writer OOXML próprio e OCR local quando o componente está presente.\n"
        "Componentes/OCR inclui motor, modelos e licenças verificados para homologação offline.\n"
        "LibreOffice é um componente separado, obtido pelo fluxo oficial; não está neste pacote.\n"
        "Notices e informações de fonte de terceiros: pasta Licencas.\n"
        "Windows 11: alvo validado; Windows 10 e máquina sem VC Runtime: pendentes.\n"
        "VC Runtime é pré-requisito externo; não há DLL app-local adicionada.\n",
        encoding="utf-8",
        newline="\n",
    )
    shutil.copyfile(ROOT.parent / "LICENSE", output / "LICENSE")
    for directory in ("Downloads", "Logs"):
        (output / directory).mkdir()
    run(
        "notices-delivery",
        [python, "notice_delivery.py", "stage", "--candidate", output],
    )
    run(
        "microsoft-runtime",
        [
            python,
            "microsoft_runtime_packaging.py",
            "validate-candidate",
            "--candidate",
            output,
            "--manifest",
            ROOT / "docs/compliance/microsoft/MICROSOFT_EXTERNAL_RUNTIME_POLICY.json",
        ],
    )
    run(
        "frozen-externals",
        [
            python,
            "validate_frozen_candidate.py",
            "validate-externals",
            "--root",
            output,
        ],
    )
    run("distribution", [python, "validate_distribution.py", output])
    guard = [
        python,
        "validate_edition_distribution.py",
        "--edition",
        edition,
        "--dist",
        output,
        "--analysis-toc",
        run_root / "work/EduDownloader/Analysis-00.toc",
    ]
    run("edition-guard", guard)
    archive_path = run_root / (profile.output_directory + ".zip")
    with zipfile.ZipFile(
        archive_path, "x", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(
                    path, output.name + "/" + path.relative_to(output).as_posix()
                )
    run("zip-guard", [*guard, "--zip", archive_path])
    if inputs != source_inventory(ROOT):
        raise RuntimeError("Source inputs changed during build; output is not approved")
    from validate_edition_distribution import edition_classification, inventory

    manifest = {
        "classification": edition_classification(profile),
        "profile": profile.as_contract(),
        "source_inputs": inputs,
        "distribution": inventory(output),
        "zip_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest().upper(),
        "zip_size": archive_path.stat().st_size,
        "steps": steps,
        "frozen_smoke": "PENDING",
        "visual_check": "PENDING",
    }
    (evidence / "composition.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(f"INTERNAL_BUILD_COMPLETE={output}", flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edition", choices=list(ProductEdition))
    parser.add_argument("--expected-version")
    parser.add_argument("--inputs", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    try:
        run_build(
            args.edition,
            expected_version=args.expected_version,
            inputs_root=args.inputs,
            output_root=args.output_root,
        )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
