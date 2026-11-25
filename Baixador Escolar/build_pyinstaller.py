"""Executa o PyInstaller com metadados Tcl/Tk validados no Windows."""

from __future__ import annotations

import argparse
import os
import sys
from sysconfig import get_path
from pathlib import Path

from microsoft_runtime_packaging import (
    EXTERNAL_DISTRIBUTION_MODEL,
    EXTERNAL_POLICY_MANIFEST,
    isolated_search_path,
    load_manifest,
    validate_analysis_toc,
    validate_manifest,
    validate_candidate_runtime,
)


def configure_tcl_tk(base_prefix: Path | None = None) -> None:
    """Configura a coleta quando a detecção automática do Tcl/Tk falhar."""
    import _tkinter
    from PyInstaller.utils.hooks.tcl_tk import tcltk_info

    base = (base_prefix or Path(sys.base_prefix)).resolve()
    version = _tkinter.TCL_VERSION
    dlls_dir = base / "DLLs"
    tcl_root = base / "tcl"
    tcl_data_dir = tcl_root / f"tcl{version}"
    tk_data_dir = tcl_root / f"tk{_tkinter.TK_VERSION}"
    tcl_module_dir = tcl_root / f"tcl{version.split('.')[0]}"
    tkinter_extension = Path(_tkinter.__file__).resolve()

    required_paths = (
        tkinter_extension,
        tcl_data_dir / "init.tcl",
        tk_data_dir / "tk.tcl",
    )
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        names = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Recursos Tcl/Tk ausentes: {names}")

    tcl_library, tk_library = tcltk_info._find_tcl_tk_shared_libraries(
        str(tkinter_extension)
    )
    if not tcl_library or not tk_library:
        raise FileNotFoundError(
            f"DLLs Tcl/Tk não foram localizadas a partir de {dlls_dir}"
        )

    tcltk_info.available = True
    tcltk_info.tkinter_extension_file = str(tkinter_extension)
    tcltk_info.tcl_version = tuple(int(part) for part in version.split("."))
    tcltk_info.tk_version = tuple(int(part) for part in _tkinter.TK_VERSION.split("."))
    tcltk_info.tcl_threaded = True
    tcltk_info.tcl_data_dir = str(tcl_data_dir)
    tcltk_info.tk_data_dir = str(tk_data_dir)
    tcltk_info.tcl_module_dir = str(tcl_module_dir)
    tcltk_info.is_macos_system_framework = False
    tcltk_info.tcl_shared_library = tcl_library
    tcltk_info.tk_shared_library = tk_library
    tcltk_info.data_files = tcltk_info._collect_files_from_directory(
        str(tcl_data_dir),
        prefix="_tcl_data",
        excludes=["demos", "*.lib", "tclConfig.sh"],
    )
    tcltk_info.data_files += tcltk_info._collect_files_from_directory(
        str(tk_data_dir),
        prefix="_tk_data",
        excludes=["demos", "*.lib", "tkConfig.sh"],
    )
    if tcl_module_dir.is_dir():
        tcltk_info.data_files += tcltk_info._collect_files_from_directory(
            str(tcl_module_dir), prefix=tcl_module_dir.name
        )


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa o PyInstaller com Tcl/Tk validado."
    )
    parser.add_argument("spec", type=Path)
    parser.add_argument("--workpath", type=Path)
    parser.add_argument("--distpath", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument(
        "--microsoft-runtime-manifest",
        type=Path,
        default=EXTERNAL_POLICY_MANIFEST,
    )
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    """Valida os argumentos, prepara Tcl/Tk e inicia a compilação."""
    args = _parse_arguments(arguments)
    spec_path = args.spec.resolve()
    if not spec_path.is_file():
        print(f"Arquivo .spec não encontrado: {spec_path}")
        return 2
    if args.workpath is None:
        print("O workpath isolado é obrigatório para validar o Analysis TOC.")
        return 2

    project_root = (args.project_root or spec_path.parent).resolve()
    manifest_path = args.microsoft_runtime_manifest.resolve()
    try:
        manifest = load_manifest(manifest_path)
    except (OSError, UnicodeError, ValueError):
        print("Manifest do Microsoft runtime ausente ou inválido.")
        return 2
    policy_issues = validate_manifest(manifest)
    if manifest.get("distribution_model") != EXTERNAL_DISTRIBUTION_MODEL:
        policy_issues.append("microsoft-external-policy-model-mismatch")
    if policy_issues:
        print("Microsoft external runtime policy rejected:")
        for issue in policy_issues:
            print(f"- {issue}")
        return 2

    os.environ["PATH"] = isolated_search_path(project_root)

    configure_tcl_tk()
    from PyInstaller.__main__ import run as run_pyinstaller

    pyinstaller_arguments = ["--noconfirm", "--clean"]
    if args.workpath is not None:
        pyinstaller_arguments.extend(["--workpath", str(args.workpath.resolve())])
    if args.distpath is not None:
        pyinstaller_arguments.extend(["--distpath", str(args.distpath.resolve())])
    pyinstaller_arguments.append(str(spec_path))
    run_pyinstaller(pyinstaller_arguments)

    analysis_toc = args.workpath.resolve() / spec_path.stem / "Analysis-00.toc"
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    analysis_issues = validate_analysis_toc(
        analysis_toc,
        manifest,
        allowed_roots=(
            project_root,
            Path(sys.base_prefix),
            Path(get_path("platlib")),
            system_root,
        ),
    )
    if analysis_issues:
        print("Microsoft runtime PyInstaller analysis rejected:")
        for issue in analysis_issues:
            print(f"- {issue}")
        return 2
    candidate = (args.distpath or spec_path.parent / "dist") / "EduDownloader-Portable"
    candidate_issues = validate_candidate_runtime(candidate, manifest)
    if candidate_issues:
        print("Microsoft external runtime candidate rejected:")
        for issue in candidate_issues:
            print(f"- {issue}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
