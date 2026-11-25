"""Compila o instalador Community a partir de um onedir já validado."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit

from PIL import Image, ImageDraw

from constants import APP_VERSION
from documents_component import ENGINE_VERSION
from libreoffice_image import read_removal_catalog
from ocr_component_delivery import approved_ocr_tree
from validate_distribution import find_distribution_issues, sha256_file
from validate_edition_distribution import (
    archive_contents,
    executable_version_issues,
    module_issues,
)
from edition_profiles import select_build_profile
from windows_prerequisites import MINIMUM_VC_VERSION
from windows_signing import SigningError, inspect_signature


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "installer"
FILENAME = f"EduDownloader-{APP_VERSION}-Setup-Windows-x64.exe"
COMPILER_VERSION = "7.1.1"


def _json(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def _hex(value: str, digits: int) -> str:
    if re.fullmatch(f"[0-9A-Fa-f]{{{digits}}}", value) is None:
        raise ValueError("Hash ou impressão digital inválida")
    return value.upper()


def _https(value: str, host: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != host
        or not parsed.path
        or parsed.query
        or parsed.fragment
        or '"' in value
    ):
        raise ValueError("Origem da dependência difere da autoridade aprovada")
    return value


def prerequisites() -> dict[str, str]:
    office = _json(ROOT / "docs/compliance/documents/LIBREOFFICE_MANAGED_BASELINE.json")
    signatures = _json(SOURCE / "libreoffice-signatures.json")
    image, _ = read_removal_catalog(SOURCE)
    runtime = _json(
        ROOT / "docs/compliance/microsoft/MICROSOFT_RUNTIME_PACKAGING.json"
    )["vc_runtime_authority"]
    vc_minimum = ".".join(map(str, MINIMUM_VC_VERSION))
    if (
        runtime["minimum_version"] != vc_minimum
        or runtime["architecture"] != "x64"
        or office["engine_version"] != ENGINE_VERSION
        or signatures["version"] != ENGINE_VERSION
        or office["installer_mode"] != "administrative-image"
        or office["architecture"] != "windows-x64"
        or image["engine_version"] != ENGINE_VERSION
        or image["source_msi_sha256"].casefold()
        != office["installer_sha256"].casefold()
        or image["administrative_image_bytes"] != office["installed_image_size_bytes"]
    ):
        raise ValueError("A baseline do instalador diverge do aplicativo")
    package = runtime["package"]
    if package["authenticode"]["status"] != "VALID" or not package["authenticode"][
        "publisher"
    ].startswith("CN=Microsoft Corporation,"):
        raise ValueError("Autoridade Microsoft inesperada")
    if (
        re.fullmatch(
            r"LibreOffice_[0-9.]+_Win_x86-64\.msi", office["installer_filename"]
        )
        is None
    ):
        raise ValueError("Nome de MSI inválido")
    return {
        "AppVersion": APP_VERSION,
        "VCMinimum": vc_minimum,
        "VCURL": _https(
            package["official_resolved_url"], "download.visualstudio.microsoft.com"
        ),
        "VCSHA": _hex(package["sha256"], 64),
        "VCSigner": _hex(package["authenticode"]["thumbprint"], 40),
        "VCSize": str(int(package["size_bytes"])),
        "OfficeURL": _https(office["download_url"], "tdf.c3sl.ufpr.br"),
        "OfficeMSI": office["installer_filename"],
        "OfficeEngine": ENGINE_VERSION,
        "OfficeSHA": _hex(office["installer_sha256"], 64),
        "OfficeSigner": _hex(signatures["thumbprint"], 40),
        "OfficeMSISize": str(int(office["installer_size_bytes"])),
        "OfficeImageSize": str(int(office["installed_image_size_bytes"])),
        "OfficeInstallSize": str(int(image["installed_bytes"])),
        "OfficeRemoveCount": str(int(image["catalog_removed_files"])),
        "OfficeSOFFICECOM": _hex(signatures["sha256"]["soffice.com"], 64),
        "OfficeSOFFICEEXE": _hex(signatures["sha256"]["soffice.exe"], 64),
        "OfficeSOFFICEBIN": _hex(signatures["sha256"]["soffice.bin"], 64),
    }


def payload_identity(payload: Path) -> tuple[str, int]:
    """Identifica o conjunto instalado sem incluir estado mutável e sem seguir links."""
    identity = hashlib.sha256()
    size = 0
    for path in sorted(payload.rglob("*")):
        relative = path.relative_to(payload)
        if path.is_symlink() or path.is_junction():
            raise ValueError("O onedir contém um link")
        if relative.parts[0] in ("Downloads", "Logs"):
            if path.is_file():
                raise ValueError("O onedir contém arquivos do usuário")
            continue
        if path.is_file():
            length = path.stat().st_size
            data = f"{relative.as_posix()}\0{length}\0{sha256_file(path)}\n"
            identity.update(data.encode("utf-8"))
            size += length
    if size <= 0:
        raise ValueError("O onedir está vazio")
    return identity.hexdigest(), size


def _safe_path(path: Path) -> Path:
    raw = path.absolute()
    if any(item.is_symlink() or item.is_junction() for item in (raw, *raw.parents)):
        raise ValueError("Os caminhos do compilador e do pacote precisam ser físicos")
    return raw.resolve()


def verify_payload(payload: Path) -> tuple[str, int]:
    identity = payload_identity(payload)
    issues = find_distribution_issues(payload)
    if not approved_ocr_tree(payload / "Componentes"):
        issues.append("OCR empacotado difere do manifesto aprovado")
    modules, _ = archive_contents(payload / "EduDownloader.exe")
    issues += module_issues(set(modules), select_build_profile("community"))
    if issues:
        raise ValueError(
            f"Falha nos validadores do onedir Community: {', '.join(issues)}"
        )
    return identity


def _wizard_brand(small: Path, large: Path) -> None:
    with Image.open(ROOT / "branding/edudownloader-logo-original.png") as source:
        original = source.convert("RGBA")
        logo = original.crop((300, 185, 950, 835))
        for destination, dimensions, size in (
            (small, (55, 55), 49),
            (large, (328, 628), 224),
        ):
            background = Image.new("RGB", dimensions, "white")
            if destination == large:
                gradient = ImageDraw.Draw(background)
                for y in range(background.height):
                    fraction = y / (background.height - 1)
                    color = tuple(
                        round(start + (end - start) * fraction)
                        for start, end in zip((242, 249, 255), (192, 220, 246))
                    )
                    gradient.line((0, y, background.width, y), fill=color)
            icon = logo.resize((size, size), Image.Resampling.LANCZOS)
            background.paste(
                icon,
                ((background.width - size) // 2, (background.height - size) // 2),
                icon,
            )
            background.save(destination)


def run(iscc: Path, payload: Path, output: Path) -> Path:
    if os.name != "nt" or APP_VERSION != select_build_profile("community").app_version:
        raise ValueError("Compile no Windows a versão atual da Community")
    iscc, payload, output = map(_safe_path, (iscc, payload, output))
    if (
        payload == output
        or output.is_relative_to(payload)
        or payload.is_relative_to(output)
    ):
        raise ValueError("Separe o diretório do instalador do onedir validado")
    if not payload.is_dir() or not iscc.is_file():
        raise ValueError("O compilador e o onedir validado precisam existir")
    result = output / FILENAME
    if output.exists():
        raise FileExistsError("Escolha uma nova pasta de saída")
    signature = inspect_signature(iscc)
    if signature["status"] != "Valid" or signature["simple_publisher"] != "Pyrsys B.V.":
        raise ValueError("Assinatura do compilador Inno Setup não reconhecida")
    version = subprocess.check_output([iscc, "--version"], text=True).strip()
    if version != COMPILER_VERSION:
        raise ValueError(f"Use a versão Inno Setup {COMPILER_VERSION}")
    identity, size = verify_payload(payload)
    if executable_version_issues(payload / "EduDownloader.exe"):
        raise ValueError("Os metadados do executável divergem da versão do instalador")
    definitions = prerequisites()
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="inno-entrada-", dir=output) as temporary:
        logo = Path(temporary) / "wizard.bmp"
        panel = Path(temporary) / "wizard-panel.bmp"
        _wizard_brand(logo, panel)
        definitions.update(
            Payload=str(payload),
            PayloadID=identity[:24],
            PayloadSize=str(size),
            LogoFile=str(logo),
            WizardPanel=str(panel),
            InstallMarkerSHA=sha256_file(SOURCE / "EduDownloader.Community.installed"),
            AppExecutableSHA=sha256_file(payload / "EduDownloader.exe"),
        )
        subprocess.run(
            [
                iscc,
                "-ni",
                "-qp",
                f"--output-dir={output}",
                *(f"--define={key}={value}" for key, value in definitions.items()),
                SOURCE / "community.iss",
            ],
            cwd=SOURCE,
            check=True,
        )
    if payload_identity(payload) != (identity, size):
        raise ValueError("O onedir mudou enquanto o instalador era compilado")
    receipt = {
        "edition": "community",
        "version": APP_VERSION,
        "compiler": version,
        "payload_sha256": identity,
        "payload_bytes": size,
        "installer_sha256": sha256_file(result),
        "installer_bytes": result.stat().st_size,
        "classification": "QA_LOCAL",
    }
    (output / "instalador-qa.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", required=True, type=Path)
    parser.add_argument("--portable", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(run(args.iscc, args.portable, args.output))
    except (
        OSError,
        ValueError,
        RuntimeError,
        SigningError,
        subprocess.SubprocessError,
    ) as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
