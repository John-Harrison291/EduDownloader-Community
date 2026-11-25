"""Validação determinística da pasta portátil produzida pelo build."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse

from constants import APP_VERSION, PRODUCT_EDITION


PORTABLE_DIR_NAME = "EduDownloader-Portable"
PROJECT_ROOT = Path(__file__).resolve().parent
NOTICE_DELIVERY_INVENTORY_PATH = (
    PROJECT_ROOT / "docs" / "compliance" / "notices" / "NOTICE_DELIVERY_INVENTORY.json"
)
MANIFEST_FILENAME = "release-manifest.json"
RELEASE_POLICY_FIELD = "release_policy"
PRODUCT_CANDIDATE_FIELD = "product_candidate"
COMMUNITY_CANDIDATE_CLASSIFICATION = "community-candidate"
COMMUNITY_DISTRIBUTION_CLASSIFICATION = "CANDIDATO COMMUNITY"
COMMUNITY_RELEASE_POLICY = MappingProxyType(
    {
        "app_version": APP_VERSION,
        "product_edition": PRODUCT_EDITION.value,
        "public_release_allowed": False,
    }
)
COMMUNITY_CANDIDATE_METADATA = MappingProxyType(
    {
        "edition": PRODUCT_EDITION.value,
        "app_version": APP_VERSION,
        "classification": COMMUNITY_CANDIDATE_CLASSIFICATION,
    }
)

REQUIRED_ROOT_FILES = (
    "EduDownloader.exe",
    "yt-dlp.exe",
    "deno.exe",
    "ffmpeg.exe",
    "ffprobe.exe",
    "README.txt",
    "LICENSE",
)
OWN_LICENSE_CANONICAL_SHA256 = (
    "854B1A044C05BA9B988FE222F2040E6743DCAE6F9DC28C292F75B733E647CA7A"
)
REQUIRED_DIRECTORIES = ("_internal", "Downloads", "Logs", "Licencas")
PYPDFIUM2_LICENSE_SHA256 = MappingProxyType(
    {
        "PYPDFIUM2_LICENSES/LICENSES/Apache-2.0.txt": "3DDF9BE5C28FE27DAD143A5DC76EEA25222AD1DD68934A047064E56ED2FA40C5",
        "PYPDFIUM2_LICENSES/LICENSES/BSD-3-Clause.txt": "AD9A9E823DF025F42389C1812EAE28019F657D1ED7B3A4EBFD5010B0736A0DA4",
        "PYPDFIUM2_LICENSES/LICENSES/CC-BY-4.0.txt": "F1B1748301CD4274F46733C218D510929661B4990855DE5FC645DACD69C4371C",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/abseil.txt": "F54FFF0B905DF5B3464527C652A30E903B172D6DCAB4D89B5E6F105D5E4A4603",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/agg23.txt": "C110D3EA2AD77467CE0DCFF7D3337E6C8BE8049A5103F4B9BD5FD911A77972E5",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/fast_float.txt": "BF1B57355FECA8FCE77EE95F48002F8D4789FB71B30EC7599C06CDA4901FBB2B",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/freetype.txt": "F4B133E25DF1F86AD3FFEA453AA0E613F0474F34778DBBB3E437E7B2724937D8",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/icu.txt": "93679F4389D53B6835D89843F251844FB9BC455B35BAB036D3C8E7ABE497A47A",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/lcms.txt": "7312B68C5B25E9BF2B828706FB4E29588F22705112F411FD42E1F7D84C3D139A",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/libjpeg_turbo.ijg": "DB16A04128171879C60708D171B88D97345A2DD20F9BFC173680A4497C73F704",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/libjpeg_turbo.md": "BE2B2B5AB168BCE87BC3E31F2A5C5ADBA4B7F6E9E51D618E958D1D46972EBD95",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/libopenjpeg.txt": "C5AB0890A737C2DFA7BA675036554F6D17741D98629B0C2A145354D00617E6B2",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/libpng.txt": "452390433BA0F88AA3E2B122C647741B72A0C117CD6ED7A329B49785AECB5511",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/libtiff.txt": "92B72BA97E6C2749C2A94BC0EF646B47080217F1E772A482B33CF5A5F98A6506",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/llvm-libc.txt": "3B6226C32E168C83B891D8D6F0D3C29C2116DC3EF93DC93C307B54F279ECF383",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/pdfium-binaries.txt": "8854F4388F1CA13B3AD9BAA42E95F5546B4C0B17109C159256D3ECA7BE39B09B",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/pdfium.txt": "961EACD9633FFF6D051DB7208B755E9210E30EFAC7ADEC3E6A6D52798F0CCF0E",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/simdutf.txt": "C172A0BA936FF31230FEBB5DAD869E25CB7C1A07480C7A381BE8CF011BB52719",
        "PYPDFIUM2_LICENSES/data/windows_x64/BUILD_LICENSES/zlib.txt": "33FD641C9F3B0E0BE64BC78FEA9E94807674CDD70C48477599226CB8956565FE",
    }
)
PILLOW_COMPLIANCE_SHA256 = MappingProxyType(
    {
        "PILLOW_LICENSE.txt": "988FFE8AB3480B0F4E9A0AB2702BFFD73D9FB6B47198043FB3BA101A62FAC236",
        "PILLOW_SBOM.cdx.json": "FE1CA6E3A4F73E7018A3805A75A19377453F342D203712F37387AD6EE853FD44",
    }
)
YTDLP_APPROVED_FILENAME = "yt-dlp.exe"
YTDLP_APPROVED_VERSION = "2026.08.19"
YTDLP_APPROVED_SIZE = 17_840_399
YTDLP_APPROVED_SHA256 = (
    "66674953FE251B89F4D08C5F0E35E0728679BD67AB3D7D05C0562AF101DD3E7A"
)
YTDLP_APPROVED_SOURCE_COMMIT = "594bd50c2c78ac432f81600d309fdc4e0a92d82c"
YTDLP_APPROVED_RELEASE_COMMIT = "3a08beaf031ab68f966401ead017ac81fe8486cf"
YTDLP_SOURCE_PROVENANCE_SHA256 = (
    "A7C6B6454CBDCE0A72C54AA83E3D8C056310B90EF6A898523E91E459EB5742FD"
)
YTDLP_OFFICIAL_DOCUMENT_SHA256 = MappingProxyType(
    {
        "yt-dlp/GPL-3.0.txt": (
            "27116FDF9E6118487959D5A9C5D7BFAB12E9AB131C235B2EF97469A5DC6C86A5"
        ),
        "yt-dlp/SHA2-256SUMS": (
            "A63701F30755CB4D9317950D69703E9D751D490CB1B7059E1BB501A353FE7DCB"
        ),
        "yt-dlp/THIRD_PARTY_LICENSES.txt": (
            "472AEFE951C7DB35E1657C1D13FD337140511ED6F2B329205105AD441C5A02B7"
        ),
        "yt-dlp/YT-DLP-UNLICENSE.txt": (
            "7E12E5DF4BAE12CB21581BA157CED20E1986A0508DD10D0E8A4AB9A4CF94E85C"
        ),
    }
)
YTDLP_PROVENANCE_EXPECTED = MappingProxyType(
    {
        "archive_type": "PyInstaller one-file / CArchive + PYZ",
        "channel": "stable",
        "component": "yt-dlp",
        "embedded_python": "3.10.11",
        "executable_filename": YTDLP_APPROVED_FILENAME,
        "executable_sha256": YTDLP_APPROVED_SHA256,
        "executable_size": YTDLP_APPROVED_SIZE,
        "executable_variant": "win_exe",
        "official_documents": {
            "GPL-3.0.txt": {
                "origin": (
                    "GPLv3 integral preservada da seção correspondente do "
                    "THIRD_PARTY_LICENSES.txt oficial da tag 2026.08.19"
                ),
                "sha256": YTDLP_OFFICIAL_DOCUMENT_SHA256["yt-dlp/GPL-3.0.txt"],
            },
            "SHA2-256SUMS": {
                "origin": "release oficial yt-dlp 2026.08.19",
                "sha256": YTDLP_OFFICIAL_DOCUMENT_SHA256["yt-dlp/SHA2-256SUMS"],
            },
            "THIRD_PARTY_LICENSES.txt": {
                "origin": "tag oficial yt-dlp 2026.08.19",
                "sha256": YTDLP_OFFICIAL_DOCUMENT_SHA256[
                    "yt-dlp/THIRD_PARTY_LICENSES.txt"
                ],
            },
            "YT-DLP-UNLICENSE.txt": {
                "origin": "LICENSE da tag oficial yt-dlp 2026.08.19",
                "sha256": YTDLP_OFFICIAL_DOCUMENT_SHA256["yt-dlp/YT-DLP-UNLICENSE.txt"],
            },
        },
        "release_commit": YTDLP_APPROVED_RELEASE_COMMIT,
        "release_tag": YTDLP_APPROVED_VERSION,
        "source_commit": YTDLP_APPROVED_SOURCE_COMMIT,
        "source_compliance_status": "staging-validated-technically-complete",
        "source_provenance_manifest": {
            "filename": "SOURCE_PROVENANCE.json",
            "sha256": YTDLP_SOURCE_PROVENANCE_SHA256,
        },
        "version": YTDLP_APPROVED_VERSION,
    }
)
YTDLP_COMPOSITION_REQUIRED_MARKERS = (
    "CArchive: 150 entradas",
    "PYZ: 1.584 módulos",
    "total auditado: 1.734 entradas",
    "CPython 3.10.11 AMD64",
    "OpenSSL 1.1.1t",
    "yt_dlp_ejs` 0.8.0",
    "sources externos dos lotes 1, 1B, 1C, 1D, 1E e",
    "source chain material tecnicamente completa (classe A)",
    "SOURCE_PROVENANCE.json",
)
YTDLP_RUNTIME_NOTICE_REQUIRED_MARKERS = (
    "OpenSSL | 1.1.1t",
    "SQLite | 3.40.1",
    "bzip2 | 1.0.8",
    "zlib | 1.2.13",
    "libffi | pin CPython 3.3.0",
    "XZ/liblzma | 5.2.5",
    "local_calculated_verified_revision",
    "não constitui conclusão jurídica",
)
YTDLP_DERIVED_COMPLIANCE_FILES = (
    "yt-dlp/COMPOSITION.md",
    "yt-dlp/PROVENANCE.json",
    "yt-dlp/RUNTIME_SOURCE_NOTICES.md",
    "yt-dlp/SOURCE_CORRESPONDENCE.md",
)
YTDLP_DELIVERY_FILES = (
    "yt-dlp/GPL-3.0.txt",
    "yt-dlp/RUNTIME_SOURCE_NOTICES.md",
    "yt-dlp/THIRD_PARTY_LICENSES.txt",
    "yt-dlp/YT-DLP-UNLICENSE.txt",
)


def _notice_delivery_hashes() -> dict[str, str]:
    inventory = json.loads(NOTICE_DELIVERY_INVENTORY_PATH.read_text(encoding="utf-8"))
    return {item["path"]: item["sha256"] for item in inventory["delivery_artifacts"]}


NOTICE_DELIVERY_SHA256 = MappingProxyType(_notice_delivery_hashes())
PINNED_LICENSE_SHA256 = MappingProxyType(
    {
        **PYPDFIUM2_LICENSE_SHA256,
        **PILLOW_COMPLIANCE_SHA256,
        **YTDLP_OFFICIAL_DOCUMENT_SHA256,
        **NOTICE_DELIVERY_SHA256,
    }
)
_PINNED_COMPONENT_ARTIFACT_SHA256 = {
    "_internal/installer/community-components-v1.json": (
        "DEC752FB55790F6705CB6256A4C60C45398DF68A7535DCF1578197CB30800E22"
    ),
    "_internal/installer/component-assets/DENO-2.9.8-DEPENDENCIAS.txt": (
        "B5F6A1E4841B26A4E3A92A094E6E52F0BC40DFEE18D946343B81B8172B69450F"
    ),
    "_internal/installer/component-assets/DENO-BASELINE-LICENSES.txt": (
        "5DCE768CB069D3CF0A73F4F2DC3308FE6B0786FD2A4DFF602ACA6E36E5532347"
    ),
    "_internal/installer/component-assets/FFMPEG_BTBN_LICENSE.txt": (
        "DA7EABB7BAFDF7D3AE5E9F223AA5BDC1EECE45AC569DC21B3B037520B4464768"
    ),
    "_internal/installer/component-assets/FFMPEG_BTBN_NOTICE.txt": (
        "B2610F994F7CADE5A3E70A9639B424F9F48C030806CADAE3E2D684C37035FB56"
    ),
}
REQUIRED_LICENSE_FILES = tuple(NOTICE_DELIVERY_SHA256)
REQUIRED_INTERNAL_FILES = (
    "_tkinter.pyd",
    "customtkinter/assets/fonts/CustomTkinter_shapes_font.otf",
    "customtkinter/assets/themes/blue.json",
    "pypdfium2_raw/pdfium.dll",
)
REQUIRED_INTERNAL_DIRECTORIES = ("_tcl_data", "_tk_data")
EMPTY_USER_DIRECTORIES = ("Downloads", "Logs")
FORBIDDEN_ROOT_ENTRIES = (
    "Componentes",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "build-tk-test",
    "build_antigo.bat",
    "dist",
    "dist-tk-test",
    "tests",
    "settings.json",
    "main.py",
    "app.py",
    "downloader.py",
)

_FORBIDDEN_PATH_PARTS = {
    "license_manager",
    "license-manager-private",
    ".staging",
    ".ds_store",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "activation_issuer",
    "backups",
    "build-tk-test",
    "dist-tk-test",
    "fakes",
    "fixtures",
    "probes",
    "spikes",
    "tests",
}
_FORBIDDEN_FILE_SUFFIXES = {
    ".bak",
    ".cookie",
    ".cookies",
    ".db",
    ".dpapi",
    ".dmp",
    ".edulic",
    ".edureq",
    ".key",
    ".lock",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".old",
    ".part",
    ".p12",
    ".pem",
    ".pfx",
    ".pk8",
    ".pkcs8",
    ".seed",
    ".sqlite",
    ".sqlite3",
    ".tmp",
    ".webm",
    ".ytdl",
}
_DOCUMENTS_COMPONENT_FORBIDDEN_FILENAMES = {
    ".lock",
    "component-manifest.json",
    "libreofficeportable.exe",
    "opens___.ttf",
    "portableapps.comlauncher.dll",
    "soffice.bin",
    "soffice.com",
    "soffice.exe",
}
_DOCUMENTS_COMPONENT_FORBIDDEN_PATH_PARTS = {
    "build-documents-poc",
    "libreoffice",
    "libreofficeportable",
    "profiles",
}
_DOCUMENTS_COMPONENT_ARCHIVE_SUFFIXES = (
    ".7z",
    ".gz",
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tar.xz",
    ".xz",
    ".zip",
)
_PRIVATE_ARTIFACT_NAMES = {
    "activation.dat",
    "issuer-signing-key-v1.dpapi",
    "issuance-register.json",
    "security_device_matrix_6b.md",
}
_PRIVATE_ARTIFACT_PATTERN = re.compile(
    r"(?:admin|issuance|licen[cs]e)[_-]?"
    r"(?:export|register|registry|runbook|backup)",
    re.IGNORECASE,
)
_PRIVATE_KEY_ARTIFACT_PATTERN = re.compile(
    r"(?:issuer|signing)[_-]?key|key[_-]?(?:backup|recovery)",
    re.IGNORECASE,
)
_SOURCE_SUFFIXES = {".py", ".pyc", ".pyo"}
_TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".ini",
    ".json",
    ".log",
    ".md",
    ".py",
    ".spec",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
_ALLOWED_URL_HOSTS = {
    "api.github.com",
    "apache.org",
    "codeload.github.com",
    "docs.python.org",
    "ffmpeg.org",
    "files.pythonhosted.org",
    "github.com",
    "gnu.org",
    "gyan.dev",
    "learn.microsoft.com",
    "opensource.org",
    "portableapps.com",
    "pyinstaller.org",
    "python-pillow.github.io",
    "python.org",
    "pypi.org",
    "raw.githubusercontent.com",
    "registry.npmjs.org",
    "stackoverflow.com",
    "tcl.tk",
    "www.apache.org",
    "www.ffmpeg.org",
    "www.gnu.org",
    "www.gyan.dev",
    "www.python.org",
    "www.tcl.tk",
}

_ABSOLUTE_WINDOWS_PATH_PATTERN = re.compile(r"\b[A-Za-z]:[\\/]")
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"-----BEGIN ENCRYPTED PRIVATE KEY-----|EncryptedPrivateKeyInfo"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(
        r"\b(?:api[_-]?key|client_secret|password|senha|authorization)\b"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{8,}",
        re.IGNORECASE,
    ),
)


def _relative(path: Path, root: Path) -> str:
    """Representa um caminho interno sempre com separadores portáteis."""
    return path.relative_to(root).as_posix()


def _read_text(path: Path) -> str | None:
    """Lê textos UTF-8 e ignora arquivos binários ou encodings desconhecidos."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def find_unexpected_urls(text: str) -> list[str]:
    """Retorna URLs cujo domínio não pertence à lista oficial aprovada."""
    unexpected: list[str] = []
    for match in _URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(".,);]")
        hostname = (urlparse(url).hostname or "").lower()
        if hostname not in _ALLOWED_URL_HOSTS:
            unexpected.append(url)
    return unexpected


def find_ytdlp_compliance_issues(licenses_dir: Path) -> list[str]:
    """Valida documentos oficiais e metadados da baseline yt-dlp aprovada."""

    issues: list[str] = []
    for filename, expected_hash in YTDLP_OFFICIAL_DOCUMENT_SHA256.items():
        document = licenses_dir / filename
        if document.is_file() and sha256_file(document).upper() != expected_hash:
            issues.append(
                "Documento yt-dlp divergente da release 2026.08.19 auditada: "
                f"{filename}"
            )

    provenance_path = licenses_dir / "yt-dlp" / "PROVENANCE.json"
    if provenance_path.is_file():
        try:
            provenance: Any = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            issues.append("Manifesto de proveniência yt-dlp ilegível ou inválido")
        else:
            if provenance != dict(YTDLP_PROVENANCE_EXPECTED):
                issues.append(
                    "Manifesto de proveniência yt-dlp diverge da baseline auditada"
                )

    source_provenance_path = licenses_dir / "yt-dlp" / "SOURCE_PROVENANCE.json"
    if (
        source_provenance_path.is_file()
        and sha256_file(source_provenance_path).upper()
        != YTDLP_SOURCE_PROVENANCE_SHA256
    ):
        issues.append("Manifesto de source provenance yt-dlp foi adulterado")

    composition_path = licenses_dir / "yt-dlp" / "COMPOSITION.md"
    if composition_path.is_file():
        composition = _read_text(composition_path)
        if composition is None or any(
            marker not in composition for marker in YTDLP_COMPOSITION_REQUIRED_MARKERS
        ):
            issues.append("Documento de composição yt-dlp está incompleto")
    source_document_path = licenses_dir / "yt-dlp" / "SOURCE_CORRESPONDENCE.md"
    if source_document_path.is_file():
        source_document = _read_text(source_document_path)
        required_markers = (
            "A — TECNICAMENTE COMPLETA PARA REVISÃO JURÍDICA",
            "072AAD4F2A7604E92155F61A275A4752DC64046C8F6D90DF3710525D94CD37C1",
            "PyInstaller 6.22.0",
            "source do PyInstaller/bootloader está preservado",
            "curl-impersonate `v2.0.0`",
            "Astring 1.9.0",
            "Meriyah 6.1.4",
            "4e9426ae522c67de47ff3e060774328b42df0134",
            "121 certificados",
            "Python P2 geral: **RESOLVIDO TECNICAMENTE**",
            "CPython 3.10.11",
            "OpenSSL, SQLite, bzip2, zlib runtime, libffi e XZ",
            "RUNTIME_SOURCE_NOTICES.md",
            "Não há source gap material conhecido",
            "não autoriza publicação",
        )
        if source_document is None or any(
            marker not in source_document for marker in required_markers
        ):
            issues.append("Documento de source correspondence yt-dlp está incompleto")
    runtime_notice_path = licenses_dir / "yt-dlp" / "RUNTIME_SOURCE_NOTICES.md"
    if runtime_notice_path.is_file():
        runtime_notice = _read_text(runtime_notice_path)
        if runtime_notice is None or any(
            marker not in runtime_notice
            for marker in YTDLP_RUNTIME_NOTICE_REQUIRED_MARKERS
        ):
            issues.append("Suplemento de notices do runtime yt-dlp está incompleto")
    return issues


def find_distribution_issues(
    portable_dir: Path,
    *,
    require_manifest: bool = False,
) -> list[str]:
    """Retorna problemas estruturais, resíduos e possíveis dados sensíveis."""
    root = portable_dir.resolve()
    if not root.is_dir():
        return [f"A pasta portátil não existe: {root}"]

    issues: list[str] = []
    for filename in REQUIRED_ROOT_FILES:
        if not (root / filename).is_file():
            issues.append(f"Arquivo obrigatório ausente: {filename}")
    own_license = root / "LICENSE"
    if own_license.is_file():
        canonical_license = own_license.read_bytes().replace(b"\r\n", b"\n")
        if (
            hashlib.sha256(canonical_license).hexdigest().upper()
            != OWN_LICENSE_CANONICAL_SHA256
        ):
            issues.append("LICENSE próprio divergente do MIT aprovado")
    if require_manifest and not (root / MANIFEST_FILENAME).is_file():
        issues.append(f"Arquivo obrigatório ausente: {MANIFEST_FILENAME}")
    elif require_manifest:
        issues.extend(_manifest_policy_issues(root / MANIFEST_FILENAME))

    for dirname in REQUIRED_DIRECTORIES:
        if not (root / dirname).is_dir():
            issues.append(f"Pasta obrigatória ausente: {dirname}")
    for filename in REQUIRED_LICENSE_FILES:
        if not (root / "Licencas" / filename).is_file():
            issues.append(f"Documento de terceiros ausente: Licencas/{filename}")
    for filename, expected_hash in NOTICE_DELIVERY_SHA256.items():
        notice_path = root / "Licencas" / filename
        if not notice_path.is_file():
            continue
        if sha256_file(notice_path).upper() != expected_hash:
            issues.append(f"Notice D14A divergente do inventário: {filename}")
    for filename, expected_hash in PYPDFIUM2_LICENSE_SHA256.items():
        license_path = root / "Licencas" / filename
        if (
            license_path.is_file()
            and sha256_file(license_path).upper() != expected_hash
        ):
            issues.append(f"Documento pypdfium2 divergente do wheel 5.12.1: {filename}")
    for filename, expected_hash in PILLOW_COMPLIANCE_SHA256.items():
        compliance_path = root / "Licencas" / filename
        if (
            compliance_path.is_file()
            and sha256_file(compliance_path).upper() != expected_hash
        ):
            issues.append(
                f"Documento Pillow divergente da wheel 13.0.0 auditada: {filename}"
            )
    issues.extend(find_ytdlp_compliance_issues(root / "Licencas"))
    for filename in REQUIRED_INTERNAL_FILES:
        if not (root / "_internal" / filename).is_file():
            issues.append(f"Recurso interno obrigatório ausente: {filename}")
    for dirname in REQUIRED_INTERNAL_DIRECTORIES:
        if not (root / "_internal" / dirname).is_dir():
            issues.append(f"Pasta interna obrigatória ausente: {dirname}")

    from ocr_component_delivery import approved_ocr_file, approved_ocr_tree

    for entry_name in FORBIDDEN_ROOT_ENTRIES:
        if (root / entry_name).exists():
            if entry_name == "Componentes" and approved_ocr_tree(root / entry_name):
                continue
            issues.append(f"Item de desenvolvimento ou pessoal incluído: {entry_name}")

    for dirname in EMPTY_USER_DIRECTORIES:
        directory = root / dirname
        if directory.is_dir() and any(directory.iterdir()):
            issues.append(f"A pasta {dirname} deveria estar vazia")

    for path in root.rglob("*"):
        relative = _relative(path, root)
        ordered_relative_parts = tuple(
            part.casefold() for part in path.relative_to(root).parts
        )
        relative_parts = set(ordered_relative_parts)
        if any(
            part in {"docx", "lxml", "docx.py", "lxml.py"}
            or part.startswith(("python_docx-", "lxml-"))
            for part in relative_parts
        ):
            issues.append(f"Stack PDF/Word abandonada incluída: {relative}")
        forbidden_parts = relative_parts & _FORBIDDEN_PATH_PARTS
        if forbidden_parts:
            issues.append(f"Cache ou artefato proibido incluído: {relative}")
            continue
        if not path.is_file():
            continue

        suffix = path.suffix.lower()
        name = path.name.casefold()
        if name in {"vcruntime140.dll", "vcruntime140_1.dll"}:
            issues.append(f"Microsoft VC runtime app-local proibido: {relative}")
        normalized_stem = path.stem.casefold().replace("-", "_")
        contains_documents_component_root = any(
            ordered_relative_parts[index : index + 2] == ("components", "documents")
            for index in range(max(0, len(ordered_relative_parts) - 1))
        )
        is_libreoffice_source_archive = "libreoffice" in name and name.endswith(
            _DOCUMENTS_COMPONENT_ARCHIVE_SUFFIXES
        )
        if (
            relative_parts & _DOCUMENTS_COMPONENT_FORBIDDEN_PATH_PARTS
            or contains_documents_component_root
            or name in _DOCUMENTS_COMPONENT_FORBIDDEN_FILENAMES
            or is_libreoffice_source_archive
        ):
            issues.append(f"Motor ou evidencia PoC de documentos incluído: {relative}")
        if name == "activation.dat":
            issues.append(f"Dados locais de ativação incluídos: {relative}")
        if (
            name in _PRIVATE_ARTIFACT_NAMES
            or normalized_stem == "activation_issuer"
            or "license_manager" in normalized_stem
            or _PRIVATE_ARTIFACT_PATTERN.search(name)
            or _PRIVATE_KEY_ARTIFACT_PATTERN.search(name)
            or "runbook" in path.stem.casefold()
            or (
                suffix == ".sha256"
                and any(
                    marker in name
                    for marker in ("admin", "issuance", "licen", "register", "export")
                )
            )
        ):
            issues.append(f"Artefato administrativo privado incluído: {relative}")
        if suffix in _FORBIDDEN_FILE_SUFFIXES or path.name.endswith("~"):
            issues.append(
                f"Arquivo pessoal, temporário ou sensível incluído: {relative}"
            )
        if suffix in _SOURCE_SUFFIXES and "_internal" not in relative_parts:
            issues.append(f"Código-fonte desnecessário incluído: {relative}")
        if suffix not in _TEXT_SUFFIXES:
            continue

        expected_component_hash = _PINNED_COMPONENT_ARTIFACT_SHA256.get(relative)
        pinned_component = False
        if expected_component_hash is not None:
            pinned_component = sha256_file(path).upper() == expected_component_hash
            if not pinned_component:
                issues.append(
                    f"Artefato de componente homologado divergente: {relative}"
                )

        text = _read_text(path)
        if text is None:
            continue
        if _ABSOLUTE_WINDOWS_PATH_PATTERN.search(text):
            issues.append(f"Possível caminho absoluto encontrado em: {relative}")
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            issues.append(f"Possível segredo ou chave encontrado em: {relative}")
        pinned_notice = False
        if relative.startswith("Licencas/"):
            license_relative = relative.removeprefix("Licencas/")
            expected_hash = PINNED_LICENSE_SHA256.get(license_relative)
            if expected_hash is not None:
                pinned_notice = sha256_file(path).upper() == expected_hash
        pinned_ocr_notice = (
            approved_ocr_file(relative, path.read_bytes())
            if relative.startswith("Componentes/OCR/Licenses/")
            else False
        )
        if find_unexpected_urls(text) and not (
            pinned_notice or pinned_ocr_notice or pinned_component
        ):
            issues.append(f"URL de domínio não aprovado encontrada em: {relative}")
    return issues


def _manifest_policy_issues(path: Path) -> list[str]:
    """Validate a fail-closed Community package policy and identity."""

    try:
        manifest: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ["Manifesto interno ilegível ou inválido"]
    if not isinstance(manifest, dict):
        return ["Manifesto interno não é um objeto JSON"]
    identity = (
        manifest.get(RELEASE_POLICY_FIELD),
        manifest.get(PRODUCT_CANDIDATE_FIELD),
        manifest.get("distribution", {}).get("classification"),
    )
    if identity != (
        dict(COMMUNITY_RELEASE_POLICY),
        dict(COMMUNITY_CANDIDATE_METADATA),
        COMMUNITY_DISTRIBUTION_CLASSIFICATION,
    ):
        return ["Política ou identidade do pacote Community ausente ou inválida"]
    return find_inventory_issues(path.parent, manifest)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash one distribution file without loading it fully into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_distribution_inventory(root: Path) -> dict[str, Any]:
    """Build a deterministic inventory that excludes its own manifest."""

    entries: list[dict[str, Any]] = []
    for path in sorted(
        root.rglob("*"),
        key=lambda item: (item.as_posix().casefold(), item.as_posix()),
    ):
        if not path.is_file() or path.name == MANIFEST_FILENAME:
            continue
        entries.append(
            {
                "path": _relative(path, root),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    canonical = json.dumps(
        entries, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return {
        "algorithm": "sha256",
        "entries": entries,
        "entry_count": len(entries),
        "root_sha256": hashlib.sha256(canonical).hexdigest(),
        "scope": "all-files-except-release-manifest",
        "total_size_bytes": sum(entry["size_bytes"] for entry in entries),
    }


def find_inventory_issues(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Compare the declared file inventory with the real onedir contents."""

    inventory = manifest.get("file_inventory")
    if not isinstance(inventory, dict):
        return ["Inventário da distribuição ausente ou inválido"]
    try:
        actual = build_distribution_inventory(root)
    except OSError:
        return ["Inventário da distribuição não pôde ser calculado"]
    if inventory != actual:
        return ["Inventário da distribuição diverge dos arquivos reais"]
    return []


def main(arguments: list[str] | None = None) -> int:
    """Valida o argumento recebido e produz uma saída adequada ao build.bat."""
    args = arguments if arguments is not None else sys.argv[1:]
    require_manifest = False
    if args and args[0] == "--release":
        require_manifest = True
        args = args[1:]
    if len(args) != 1:
        print("Uso: python validate_distribution.py [--release] <pasta-portatil>")
        return 2

    portable_dir = Path(args[0])
    issues = find_distribution_issues(portable_dir, require_manifest=require_manifest)
    if issues:
        print("A distribuição portátil possui problemas:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print(f"Distribuição validada: {portable_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
