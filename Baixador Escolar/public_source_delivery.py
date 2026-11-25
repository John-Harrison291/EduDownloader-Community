"""Pinned source assets for a future Community 1.4 public package.

This module validates local evidence only. It never publishes or downloads it.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_INFORMATION = PROJECT_ROOT / "Licencas" / "THIRD_PARTY_SOURCE_INFORMATION.txt"
SOURCE_ASSETS = (
    (
        "yt-dlp",
        "compliance_artifacts/yt-dlp/2026.08.19/bundles/"
        "EduDownloader-ThirdParty-Source-yt-dlp-2026.08.19.zip",
        155_871_040,
        "38898AD6003147EF3EEC3BD4EA035F379549B17F2FF05262A9B983F2BFEAC3FC",
        "2F73720444FA6659A79393DCA0E97AFF4DC3304D34197A44D49711465EDC5700",
    ),
    (
        "Deno",
        "build-compliance-deno/EduDownloader-ThirdParty-Source-Deno-2.9.5-COMPLETE.zip",
        268_052_753,
        "C0A2B121B96AF8E52DE6A01E31DBD5711948F19B3550E57DB4C27A5F558A54C8",
        "631B9722D989E073651B928AC79F42B02F4330941D3BBC668FEE8BD19F43ED6F",
    ),
    (
        "FFmpeg/FFprobe BtbN",
        "build-compliance-ffmpeg-btbn/autobuild-2026-08-25-13-06/bundles/"
        "EduDownloader-ThirdParty-Source-FFmpeg-BtbN-"
        "autobuild-2026-08-25-13-06-COMPLETE-CANDIDATE.zip",
        646_861_654,
        "DD7DBBE3BACA3B164D73CC6C09C2200967C77E7FA25FCBAA88A1E67EAF58870E",
        "7BD8141C14BBF777F97C3B6E219BA438045B7F8988DCCE0306316634B9C99D1E",
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def find_source_delivery_issues(root: Path = PROJECT_ROOT) -> list[str]:
    """Reject missing, changed, or undocumented separate source assets."""
    issues: list[str] = []
    try:
        notice = (root / "Licencas" / SOURCE_INFORMATION.name).read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError):
        return ["Informação de fontes entregue no pacote ausente ou ilegível"]
    for component, relative, size, digest, inventory in SOURCE_ASSETS:
        source = root / relative
        if source.name not in notice or digest not in notice or inventory not in notice:
            issues.append(f"Asset de fonte sem instrução/identidade: {component}")
        if not source.is_file():
            issues.append(f"Asset de fonte ausente: {component}")
            continue
        if source.stat().st_size != size or _sha256(source) != digest:
            issues.append(f"Asset de fonte divergente: {component}")
    return issues


def stage_source_assets(
    release_dir: Path, *, root: Path = PROJECT_ROOT, replace: bool = False
) -> tuple[Path, ...]:
    """Copy pinned bundles beside a future public ZIP, never silently replacing."""
    issues = find_source_delivery_issues(root)
    if issues:
        raise ValueError("; ".join(issues))
    release_dir.mkdir(parents=True, exist_ok=True)
    targets: list[Path] = []
    for _, relative, size, digest, _ in SOURCE_ASSETS:
        source = root / relative
        target = release_dir / source.name
        if target.exists():
            if target.stat().st_size == size and _sha256(target) == digest:
                targets.append(target)
                continue
            if not replace:
                raise ValueError(f"Asset de fonte existente diverge: {target.name}")
        temporary = release_dir / f"{source.name}.tmp"
        if temporary.exists():
            raise ValueError(f"Cópia parcial de fonte encontrada: {temporary.name}")
        try:
            shutil.copyfile(source, temporary)
            if temporary.stat().st_size != size or _sha256(temporary) != digest:
                raise ValueError(f"Cópia de fonte divergente: {source.name}")
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
        targets.append(target)
    return tuple(targets)


def find_staged_source_issues(release_dir: Path) -> list[str]:
    """Validate the three separate files beside a public release ZIP."""
    issues: list[str] = []
    for component, relative, size, digest, _ in SOURCE_ASSETS:
        path = release_dir / Path(relative).name
        if not path.is_file():
            issues.append(f"Asset de fonte não entregue: {component}")
        elif path.stat().st_size != size or _sha256(path) != digest:
            issues.append(f"Asset de fonte entregue diverge: {component}")
    return issues


def main() -> int:
    issues = find_source_delivery_issues()
    if issues:
        for issue in issues:
            print(f"ERRO: {issue}", file=sys.stderr)
        return 1
    print("Três source assets verificados localmente; publicação não executada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
