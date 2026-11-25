"""Valida warnings do PyInstaller contra uma baseline textual controlada."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_WARNINGS_PATH = (
    PROJECT_DIR / "build" / "EduDownloader" / "warn-EduDownloader.txt"
)
DEFAULT_BASELINE_PATH = PROJECT_DIR / "pyinstaller-warnings-baseline.txt"
_WARNING_PATTERN = re.compile(r"^(missing|excluded) module named (?:'([^']+)'|([^ ]+))")
_BASELINE_PATTERN = re.compile(r"^(missing|excluded)\|([^|\s]+)$")
_EXPLAINED_PATTERN = re.compile(r"^(missing|excluded)\|([^|\s]+)\|(.+\S)$")
_FORBIDDEN_MODULE_PREFIXES = ("activation_issuer", "tests")


def parse_warning_entries(text: str) -> set[str]:
    """Extrai somente tipo e módulo, sem caminhos nem detalhes ambientais."""
    entries: set[str] = set()
    for line in text.splitlines():
        match = _WARNING_PATTERN.match(line)
        if match is None:
            continue
        kind, quoted_name, plain_name = match.groups()
        entries.add(f"{kind}|{quoted_name or plain_name}")
    return entries


def read_warning_baseline(path: Path) -> tuple[set[str], list[str]]:
    """Lê a allowlist explícita e rejeita entradas ambíguas ou duplicadas."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return set(), ["Baseline de warnings ausente ou ilegível"]

    entries: set[str] = set()
    issues: list[str] = []
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if _BASELINE_PATTERN.fullmatch(line) is None:
            issues.append(f"Entrada inválida na baseline de warnings: linha {number}")
            continue
        if line in entries:
            issues.append(f"Entrada duplicada na baseline de warnings: linha {number}")
            continue
        entries.add(line)
    if not entries:
        issues.append("Baseline de warnings está vazia")
    return entries, issues


def read_explained_warnings(path: Path) -> tuple[dict[str, str], list[str]]:
    """Read candidate-specific warnings without rewriting historical baseline."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}, ["Lista de warnings explicados ausente ou ilegível"]

    entries: dict[str, str] = {}
    issues: list[str] = []
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _EXPLAINED_PATTERN.fullmatch(line)
        if match is None:
            issues.append(f"Warning explicado inválido: linha {number}")
            continue
        kind, module, reason = match.groups()
        entry = f"{kind}|{module}"
        if entry in entries:
            issues.append(f"Warning explicado duplicado: linha {number}")
            continue
        entries[entry] = reason
    if not entries:
        issues.append("Lista de warnings explicados está vazia")
    return entries, issues


def find_pyinstaller_warning_issues(
    warnings_path: Path,
    baseline_path: Path,
    explained_path: Path | None = None,
) -> list[str]:
    """Falha em warning novo, ausente da execução ou módulo proibido."""
    baseline, issues = read_warning_baseline(baseline_path)
    explained: dict[str, str] = {}
    if explained_path is not None:
        explained, explained_issues = read_explained_warnings(explained_path)
        issues.extend(explained_issues)
        for entry in sorted(baseline & explained.keys()):
            issues.append(f"Warning explicado já pertence à baseline: {entry}")
    if issues:
        return issues
    try:
        warning_text = warnings_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ["Relatório de warnings do PyInstaller ausente ou ilegível"]

    actual = parse_warning_entries(warning_text)
    for entry in sorted(actual):
        module_name = entry.partition("|")[2].casefold()
        if any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in _FORBIDDEN_MODULE_PREFIXES
        ):
            issues.append(f"Módulo proibido apareceu nos warnings: {entry}")
    allowed = baseline | explained.keys()
    for entry in sorted(actual - allowed):
        issues.append(f"Warning novo não auditado: {entry}")
    for entry in sorted(allowed - actual):
        issues.append(f"Warning conhecido ausente; baseline requer revisão: {entry}")
    return issues


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compara os warnings do PyInstaller com a baseline auditada."
    )
    parser.add_argument("--warnings", type=Path, default=DEFAULT_WARNINGS_PATH)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--explained", type=Path)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    args = _parse_arguments(arguments)
    issues = find_pyinstaller_warning_issues(
        args.warnings,
        args.baseline,
        args.explained,
    )
    if issues:
        print("Validação dos warnings do PyInstaller reprovada:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Warnings correspondem à baseline histórica e às explicações auditadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
