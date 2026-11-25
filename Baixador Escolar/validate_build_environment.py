"""Compara o ambiente Python do build com o lock completo versionado."""

from __future__ import annotations

import argparse
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution, distributions
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_LOCK_PATH = PROJECT_DIR / "requirements-build.lock"
_LOCK_ENTRY_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")
PILLOW_AUDITED_VERSION = "13.0.0"
PILLOW_AUDITED_WHEEL_TAG = "cp314-cp314-win_amd64"
PILLOW_AUDITED_OPTIONAL_FEATURES = ("libimagequant", "raqm", "xcb")


@dataclass(frozen=True)
class PillowBuildEvidence:
    """Metadata and feature flags that define the audited Pillow baseline."""

    version: str | None
    wheel_tags: frozenset[str]
    feature_support: Mapping[str, bool | None]


def canonicalize_distribution_name(name: str) -> str:
    """Aplica a normalização de nomes usada pelo ecossistema Python."""
    return re.sub(r"[-_.]+", "-", name).casefold()


def read_exact_dependency_lock(path: Path) -> tuple[dict[str, str], list[str]]:
    """Lê somente entradas exatas e rejeita duplicatas ou opções implícitas."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}, ["Lock do ambiente de build ausente ou ilegível"]

    locked: dict[str, str] = {}
    issues: list[str] = []
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_ENTRY_PATTERN.fullmatch(line)
        if match is None:
            issues.append(f"Entrada não exata no lock de build: linha {number}")
            continue
        name, version = match.groups()
        canonical_name = canonicalize_distribution_name(name)
        if canonical_name in locked:
            issues.append(f"Dependência duplicada no lock de build: linha {number}")
            continue
        locked[canonical_name] = version
    if not locked:
        issues.append("Lock do ambiente de build está vazio")
    return locked, issues


def installed_distributions() -> dict[str, str]:
    """Obtém somente nome e versão, sem caminhos ou identidade da máquina."""
    result: dict[str, str] = {}
    for installed_distribution in distributions():
        name = installed_distribution.metadata.get("Name")
        if name:
            result[canonicalize_distribution_name(name)] = (
                installed_distribution.version
            )
    return result


def collect_pillow_build_evidence() -> PillowBuildEvidence:
    """Read stable Pillow metadata and feature APIs without parsing human output."""

    try:
        installed_pillow = distribution("Pillow")
    except PackageNotFoundError:
        return PillowBuildEvidence(
            version=None,
            wheel_tags=frozenset(),
            feature_support={
                feature: None for feature in PILLOW_AUDITED_OPTIONAL_FEATURES
            },
        )

    wheel_metadata = installed_pillow.read_text("WHEEL") or ""
    wheel_tags = frozenset(
        line.removeprefix("Tag:").strip()
        for line in wheel_metadata.splitlines()
        if line.startswith("Tag:")
    )
    feature_support: dict[str, bool | None] = {}
    try:
        from PIL import features as pillow_features
    except ImportError:
        feature_support.update(
            {feature: None for feature in PILLOW_AUDITED_OPTIONAL_FEATURES}
        )
    else:
        for feature in PILLOW_AUDITED_OPTIONAL_FEATURES:
            try:
                feature_support[feature] = pillow_features.check_feature(feature)
            except (AttributeError, ValueError):
                feature_support[feature] = None
    return PillowBuildEvidence(
        version=installed_pillow.version,
        wheel_tags=wheel_tags,
        feature_support=feature_support,
    )


def find_pillow_baseline_issues(evidence: PillowBuildEvidence) -> list[str]:
    """Fail closed when Pillow differs from the audited Windows wheel baseline."""

    issues: list[str] = []
    if evidence.version != PILLOW_AUDITED_VERSION:
        issues.append("Versão do Pillow difere da baseline auditada")
    if PILLOW_AUDITED_WHEEL_TAG not in evidence.wheel_tags:
        issues.append("Wheel do Pillow difere da baseline cp314-win_amd64 auditada")

    for feature in PILLOW_AUDITED_OPTIONAL_FEATURES:
        support = evidence.feature_support.get(feature)
        if support is None:
            issues.append(
                f"Não foi possível verificar a feature Pillow {feature}; "
                "revisão de compliance de terceiros obrigatória"
            )
        elif support:
            issues.append(
                f"Pillow {feature} support differs from the audited baseline; "
                "third-party compliance review required."
            )
    return issues


def find_build_environment_issues(
    lock_path: Path,
    *,
    installed: Mapping[str, str] | None = None,
    pillow_evidence: PillowBuildEvidence | None = None,
) -> list[str]:
    """Rejeita pacote ausente, versão divergente e dependência inesperada."""
    locked, issues = read_exact_dependency_lock(lock_path)
    if issues:
        return issues
    actual_source = installed if installed is not None else installed_distributions()
    actual = {
        canonicalize_distribution_name(name): version
        for name, version in actual_source.items()
    }
    for name in sorted(locked.keys() - actual.keys()):
        issues.append(f"Dependência bloqueada ausente: {name}")
    for name in sorted(actual.keys() - locked.keys()):
        issues.append(f"Dependência inesperada no ambiente de build: {name}")
    for name in sorted(locked.keys() & actual.keys()):
        if locked[name] != actual[name]:
            issues.append(f"Versão divergente no ambiente de build: {name}")
    issues.extend(
        find_pillow_baseline_issues(
            pillow_evidence
            if pillow_evidence is not None
            else collect_pillow_build_evidence()
        )
    )
    return issues


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida o ambiente Python contra o lock completo do build."
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    args = _parse_arguments(arguments)
    issues = find_build_environment_issues(args.lock)
    if issues:
        print("Ambiente Python do build diverge do lock:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Ambiente Python corresponde exatamente ao lock do build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
