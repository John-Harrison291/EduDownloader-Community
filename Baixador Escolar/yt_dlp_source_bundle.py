"""Verifica e monta o bundle separado de source do yt-dlp auditado."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_MANIFEST = Path("Licencas/yt-dlp/SOURCE_PROVENANCE.json")
DEFAULT_STAGING = Path("compliance_artifacts/yt-dlp/2026.08.19")
DEFAULT_BUNDLE = DEFAULT_STAGING / (
    "bundles/EduDownloader-ThirdParty-Source-yt-dlp-2026.08.19.zip"
)
OFFICIAL_MANIFEST_SHA256 = (
    "A7C6B6454CBDCE0A72C54AA83E3D8C056310B90EF6A898523E91E459EB5742FD"
)
OFFICIAL_COMPONENT = "yt-dlp"
OFFICIAL_VERSION = "2026.08.19"
OFFICIAL_SOURCE_COMMIT = "594bd50c2c78ac432f81600d309fdc4e0a92d82c"
OFFICIAL_RELEASE_COMMIT = "3a08beaf031ab68f966401ead017ac81fe8486cf"
OFFICIAL_EXECUTABLE_SHA256 = (
    "66674953FE251B89F4D08C5F0E35E0728679BD67AB3D7D05C0562AF101DD3E7A"
)
OFFICIAL_SOURCE_ARCHIVE_SHA256 = (
    "072AAD4F2A7604E92155F61A275A4752DC64046C8F6D90DF3710525D94CD37C1"
)
OFFICIAL_CPYTHON_SOURCE_SHA256 = (
    "3C3BC3048303721C904A03EB8326B631E921F11CC3BE2988456A42F115DAF04C"
)
OFFICIAL_CPYTHON_COMMIT = "7d4cc5aa854fdea4d01a5b9c59e37c6e62f1103d"
OFFICIAL_CPYTHON_TREE = "70d149737111f058b90938480d20b2a9cb038480"
OFFICIAL_CPYTHON_TAG_OBJECT = "67e163167580c6867f6c735bc143e601a3318561"
OFFICIAL_CPYTHON_METADATA_FILE_COUNT = 50
OFFICIAL_CPYTHON_METADATA_INVENTORY_SHA256 = (
    "A5AC9D91D07C80B488D26C5A38B1857B42BFF20433B799F8EDF6DBDE10FDC54C"
)
OFFICIAL_CPYTHON_METADATA_AUTHORITY_HOSTS = (
    "api.github.com",
    "github.com",
    "raw.githubusercontent.com",
    "www.python.org",
)
OFFICIAL_CPYTHON_EXTERNAL_PINS = {
    "OpenSSL": (
        "openssl-1.1.1t",
        "82bfdc9e019e4892c5bd8f90b71c42fbf79f29d0",
        "bc4df93cec8153bb83968daa11aa7f0727b2ca20",
    ),
    "SQLite": (
        "sqlite-3.40.1.0",
        "db4ca556b25787c263ee72a4b764c4be474c322f",
        "e8bf88c536ad863a1481e88e0742ba5690fc853b",
    ),
    "XZ/liblzma": (
        "xz-5.2.5",
        "c6bc0c612605622aaef101a33a751f9de2ecc193",
        "2b8fb6a3c0b111c2175bec896b2a22448fd0ac4b",
    ),
    "bzip2": (
        "bzip2-1.0.8",
        "05301997b2f9590f49c672cf3dfd3d3dfa7ad521",
        "933e65e88f0a28f9bcbc8abe5a4c12e3f618c043",
    ),
    "libffi runtime": (
        "libffi-3.3.0",
        "35a5081d073058159e8db96c43029f88c1da501a",
        "b4583c058b78268d2349dc17f4597d59733a6f43",
    ),
    "zlib runtime": (
        "zlib-1.2.13",
        "9071e5ae1bd90c30518404b95ec0be0d4cf6cf84",
        "a686f8a2cdec1ce5183781d167531e927284188c",
    ),
}
OFFICIAL_CPYTHON_EXTERNAL_METADATA_FILE_COUNT = 6
OFFICIAL_CPYTHON_EXTERNAL_METADATA_INVENTORY_SHA256 = (
    "B0F77408F4E9455CA754D46694A5F3F00CE942718789A1EF2188FEAB77CA8629"
)
OFFICIAL_CPYTHON_EXTERNAL_METADATA_AUTHORITY_HOSTS = ("api.github.com",)
OFFICIAL_CPYTHON_EXTERNAL_ARCHIVES = {
    "OpenSSL": {
        "archive_blob_count": 3099,
        "archive_direct_matches": 3099,
        "archive_eol_normalized_matches": 0,
        "archive_root": "cpython-source-deps-openssl-1.1.1t",
        "filename": "openssl-1.1.1t.zip",
        "license_references": (
            "LICENSE",
            "external/perl/Text-Template-1.46/COPYING",
        ),
        "required_fragments": {
            "include/openssl/opensslv.h": (b"OpenSSL 1.1.1t  7 Feb 2023",),
            "LICENSE": (b"OpenSSL License", b"Original SSLeay License"),
        },
        "sha256": ("DCB3F0726184F0924249F1FFB2322794FBC0C99C2AB581DBE5A3E9D88B9C837C"),
        "size": 11_952_076,
        "tree_metadata_path": (
            "source-metadata/lot-1f/"
            "cpython-source-deps-openssl-1.1.1t.tree-recursive.json"
        ),
        "version": "1.1.1t",
    },
    "SQLite": {
        "archive_blob_count": 5,
        "archive_direct_matches": 5,
        "archive_eol_normalized_matches": 0,
        "archive_root": "cpython-source-deps-sqlite-3.40.1.0",
        "filename": "sqlite-3.40.1.0.zip",
        "license_references": ("sqlite3.c", "sqlite3.h"),
        "required_fragments": {
            "sqlite3.h": (
                b'#define SQLITE_VERSION        "3.40.1"',
                b"The author disclaims copyright to this source code",
            ),
        },
        "sha256": ("39ADCF18B275197E819F3997F96B9D4C28563739EDBCFDA5305199004B627D01"),
        "size": 2_597_565,
        "tree_metadata_path": (
            "source-metadata/lot-1f/"
            "cpython-source-deps-sqlite-3.40.1.0.tree-recursive.json"
        ),
        "version": "3.40.1",
    },
    "XZ/liblzma": {
        "archive_blob_count": 480,
        "archive_direct_matches": 480,
        "archive_eol_normalized_matches": 0,
        "archive_root": "cpython-source-deps-xz-5.2.5",
        "filename": "xz-5.2.5.zip",
        "license_references": (
            "COPYING",
            "COPYING.GPLv2",
            "COPYING.GPLv3",
            "COPYING.LGPLv2.1",
        ),
        "required_fragments": {
            "src/liblzma/api/lzma/version.h": (
                b"LZMA_VERSION_MAJOR 5",
                b"LZMA_VERSION_MINOR 2",
                b"LZMA_VERSION_PATCH 5",
            ),
        },
        "sha256": ("6A4389CC05143BEB2679B1299CECEE71B02BAA55E70F68A88B44DC01AD495424"),
        "size": 2_054_244,
        "tree_metadata_path": (
            "source-metadata/lot-1f/cpython-source-deps-xz-5.2.5.tree-recursive.json"
        ),
        "version": "5.2.5",
    },
    "bzip2": {
        "archive_blob_count": 56,
        "archive_direct_matches": 56,
        "archive_eol_normalized_matches": 0,
        "archive_root": "cpython-source-deps-bzip2-1.0.8",
        "filename": "bzip2-1.0.8.zip",
        "license_references": ("LICENSE",),
        "required_fragments": {
            "LICENSE": (b"bzip2/libbzip2 version 1.0.8 of 13 July 2019",),
        },
        "sha256": ("12C17D15F99E27235529574A722FB484A4E8FDF2427CEF53B1B68BDF07E404A9"),
        "size": 831_543,
        "tree_metadata_path": (
            "source-metadata/lot-1f/cpython-source-deps-bzip2-1.0.8.tree-recursive.json"
        ),
        "version": "1.0.8",
    },
    "libffi runtime": {
        "archive_blob_count": 397,
        "archive_direct_matches": 393,
        "archive_eol_normalized_matches": 4,
        "archive_root": "cpython-source-deps-libffi-3.3.0",
        "filename": "libffi-3.3.0.zip",
        "license_references": ("LICENSE", "LICENSE-BUILDTOOLS"),
        "required_fragments": {
            "configure.ac": (b"AC_INIT([libffi], [3.3-rc0]",),
            "LICENSE": (b"Permission is hereby granted, free of charge",),
        },
        "sha256": ("AD6F4DDFD00591CC6E6A7F1FD82FDBD4CC41CF2D117E861A24235A7CF126D779"),
        "size": 828_438,
        "tree_metadata_path": (
            "source-metadata/lot-1f/"
            "cpython-source-deps-libffi-3.3.0.tree-recursive.json"
        ),
        "version": "3.3.0",
    },
    "zlib runtime": {
        "archive_blob_count": 243,
        "archive_direct_matches": 243,
        "archive_eol_normalized_matches": 0,
        "archive_root": "cpython-source-deps-zlib-1.2.13",
        "filename": "zlib-1.2.13.zip",
        "license_references": ("LICENSE",),
        "required_fragments": {
            "zlib.h": (b'#define ZLIB_VERSION "1.2.13"',),
        },
        "sha256": ("93F286FEFC44D971DBE865C59D6C61BB9CF429CA6607EB0604B0A5DAE33D9486"),
        "size": 1_692_041,
        "tree_metadata_path": (
            "source-metadata/lot-1f/cpython-source-deps-zlib-1.2.13.tree-recursive.json"
        ),
        "version": "1.2.13",
    },
}
BUNDLE_ROOT = "yt-dlp-2026.08.19-source"
_HEX_64 = re.compile(r"[0-9A-F]{64}\Z")
_SOURCE_STATUSES = {"conditional", "not-required", "pending", "verified"}
_NATIVE_INTEGRITY_AUTHORITIES = {
    "local_calculated_verified_revision",
    "official_published",
}
_NATIVE_ARCHIVE_STRATEGIES = {
    "git_archive_eol_normalized",
    "git_archive_exact",
    "git_archive_export_ignore",
    "official_release_asset",
    "official_recipe_hash",
}
_NATIVE_TECHNICAL_STATUSES = {"blocked", "partial", "resolved"}
_WINDOWS_ABSOLUTE_PATH = re.compile(r"\b[A-Za-z]:[\\/]")
_PROHIBITED_NAMES = {
    "activation.dat",
    "app.py",
    "downloader.py",
    "issuer-signing-key-v1.dpapi",
    "issuance-register.json",
}
_PROHIBITED_PARTS = {
    ".git",
    "activation_issuer",
    "backups",
    "licensing",
    "tests",
}
_PEM_CERTIFICATE = re.compile(
    rb"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----",
    re.DOTALL,
)


class SourceBundleError(ValueError):
    """Indica que o staging, manifesto ou bundle falhou fechado."""


def sha256_bytes(content: bytes) -> str:
    """Calcula SHA-256 em formato hexadecimal maiúsculo."""
    return hashlib.sha256(content).hexdigest().upper()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calcula SHA-256 sem carregar um arquivo grande inteiro em memória."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def canonical_json_bytes(value: Any) -> bytes:
    """Serializa JSON canônico usado como identidade do inventário."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def formatted_json_bytes(value: Any) -> bytes:
    """Serializa documentos JSON legíveis e determinísticos."""
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _parse_certdata_objects(content: bytes) -> list[dict[str, tuple[str, bytes]]]:
    """Lê os objetos CKBI necessários sem instalar uma toolchain externa."""
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise SourceBundleError("certdata Mozilla não está em UTF-8") from error
    objects: list[dict[str, tuple[str, bytes]]] = []
    current: dict[str, tuple[str, bytes]] | None = None
    index = 0
    began = False
    while index < len(lines):
        line = lines[index]
        index += 1
        if not began:
            began = line == "BEGINDATA"
            continue
        if not line or line.startswith("#") or line.startswith("CVS_ID "):
            continue
        words = line.split()
        if len(words) < 2:
            raise SourceBundleError("certdata Mozilla contém atributo inválido")
        if len(words) == 2 and words[1] == "MULTILINE_OCTAL":
            value = bytearray()
            ended = False
            while index < len(lines):
                octal_line = lines[index]
                index += 1
                if octal_line == "END":
                    ended = True
                    break
                try:
                    value.extend(
                        int(token, 8) for token in octal_line.split("\\") if token
                    )
                except ValueError as error:
                    raise SourceBundleError(
                        "certdata Mozilla contém octal inválido"
                    ) from error
            if not ended:
                raise SourceBundleError("certdata Mozilla contém bloco incompleto")
            parsed_value = bytes(value)
        else:
            if len(words) < 3:
                raise SourceBundleError("certdata Mozilla contém valor ausente")
            parsed_value = " ".join(words[2:]).encode("utf-8")
        if words[0] == "CKA_CLASS":
            if current is not None:
                objects.append(current)
            current = {}
        if current is None:
            raise SourceBundleError("certdata Mozilla contém atributo fora de objeto")
        current[words[0]] = (words[1], parsed_value)
    if not began:
        raise SourceBundleError("certdata Mozilla não contém BEGINDATA")
    if current is not None:
        objects.append(current)
    return objects


def trusted_certdata_certificate_hashes(
    content: bytes, *, as_of: datetime
) -> tuple[str, ...]:
    """Reproduz a seleção TLS do gerador oficial e retorna hashes dos DERs."""
    if as_of.tzinfo is None:
        raise SourceBundleError("Data de geração do certdata deve conter fuso")
    objects = _parse_certdata_objects(content)
    certificates = [
        item
        for item in objects
        if item.get("CKA_CLASS", ("", b""))[1] == b"CKO_CERTIFICATE"
    ]
    trusts = [
        item
        for item in objects
        if item.get("CKA_CLASS", ("", b""))[1] == b"CKO_NSS_TRUST"
    ]
    trust_by_sha1: dict[bytes, dict[str, tuple[str, bytes]]] = {}
    for trust in trusts:
        digest = trust.get("CKA_CERT_SHA1_HASH")
        if digest is None:
            raise SourceBundleError("certdata Mozilla contém trust sem SHA-1")
        trust_by_sha1[digest[1]] = trust
    selected: list[str] = []
    for certificate in certificates:
        value = certificate.get("CKA_VALUE")
        if value is None:
            raise SourceBundleError("certdata Mozilla contém certificado sem DER")
        der = value[1]
        trust = trust_by_sha1.get(hashlib.sha1(der).digest(), {})
        server_auth = trust.get("CKA_TRUST_SERVER_AUTH")
        if server_auth is None:
            raise SourceBundleError("certdata Mozilla contém certificado sem trust")
        allowed_trust = {
            b"CKT_NSS_MUST_VERIFY_TRUST",
            b"CKT_NSS_NOT_TRUSTED",
            b"CKT_NSS_TRUST_UNKNOWN",
            b"CKT_NSS_TRUSTED_DELEGATOR",
        }
        if server_auth[1] not in allowed_trust:
            raise SourceBundleError("certdata Mozilla contém trust desconhecido")
        if server_auth[1] != b"CKT_NSS_TRUSTED_DELEGATOR":
            continue
        distrust_after = certificate.get("CKA_NSS_SERVER_DISTRUST_AFTER")
        if distrust_after and distrust_after[0] == "CK_BBOOL":
            if distrust_after[1] != b"CK_FALSE":
                raise SourceBundleError(
                    "certdata Mozilla contém distrust-after booleano inválido"
                )
        elif distrust_after and distrust_after[0] == "MULTILINE_OCTAL":
            try:
                cutoff = datetime.strptime(
                    distrust_after[1].decode("ascii"), "%y%m%d%H%M%SZ"
                ).replace(tzinfo=timezone.utc) + timedelta(days=398)
            except (UnicodeDecodeError, ValueError) as error:
                raise SourceBundleError(
                    "certdata Mozilla contém distrust-after inválido"
                ) from error
            if as_of > cutoff:
                continue
        elif distrust_after:
            raise SourceBundleError(
                "certdata Mozilla contém tipo distrust-after desconhecido"
            )
        selected.append(sha256_bytes(der))
    if not selected or len(selected) != len(set(selected)):
        raise SourceBundleError("certdata Mozilla produziu conjunto DER inválido")
    return tuple(sorted(selected))


def pem_certificate_hashes(content: bytes) -> tuple[str, ...]:
    """Extrai o conjunto de certificados DER de um bundle PEM."""
    try:
        hashes = [
            sha256_bytes(base64.b64decode(re.sub(rb"\s+", b"", match), validate=True))
            for match in _PEM_CERTIFICATE.findall(content)
        ]
    except ValueError as error:
        raise SourceBundleError("cacert.pem contém base64 inválido") from error
    if not hashes or len(hashes) != len(set(hashes)):
        raise SourceBundleError("cacert.pem contém conjunto DER inválido")
    return tuple(sorted(hashes))


def git_blob_sha1(content: bytes) -> str:
    """Calcula a identidade Git SHA-1 de um blob sem invocar Git."""
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def archive_git_blobs(path: Path) -> tuple[str, dict[str, str]]:
    """Lê um tar sem extrair e retorna root e blobs relativos observados."""
    blobs: dict[str, str] = {}
    roots: set[str] = set()
    try:
        with tarfile.open(path, "r:*") as archive:
            for member in archive.getmembers():
                pure = PurePosixPath(member.name)
                if pure.is_absolute() or ".." in pure.parts:
                    raise SourceBundleError("Source archive contém caminho inseguro")
                if not pure.parts:
                    continue
                roots.add(pure.parts[0])
                if len(pure.parts) == 1:
                    continue
                relative = PurePosixPath(*pure.parts[1:]).as_posix()
                if member.isfile():
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise SourceBundleError(
                            "Source archive contém arquivo regular ilegível"
                        )
                    content = stream.read()
                elif member.issym():
                    content = member.linkname.encode("utf-8")
                else:
                    continue
                if relative in blobs:
                    raise SourceBundleError("Source archive contém path duplicado")
                blobs[relative] = git_blob_sha1(content)
    except (OSError, tarfile.TarError, UnicodeError) as error:
        raise SourceBundleError("Source archive inválido ou ilegível") from error
    if len(roots) != 1 or not blobs:
        raise SourceBundleError("Source archive não possui root único e conteúdo")
    return next(iter(roots)), blobs


def verify_commit_snapshot_archive(
    archive_path: Path,
    tree_document: dict[str, Any],
    *,
    expected_root: str,
    strategy: str,
    expected_file_count: int,
) -> None:
    """Compara snapshot oficial por commit com a árvore Git preservada."""
    if strategy not in _NATIVE_ARCHIVE_STRATEGIES - {"official_release_asset"}:
        raise SourceBundleError("Estratégia de snapshot Git inválida")
    if tree_document.get("truncated") is not False:
        raise SourceBundleError("Árvore Git ausente, truncada ou inválida")
    entries = tree_document.get("tree")
    if not isinstance(entries, list):
        raise SourceBundleError("Árvore Git não contém entradas")
    expected = {
        entry.get("path"): entry.get("sha")
        for entry in entries
        if isinstance(entry, dict) and entry.get("type") == "blob"
    }
    if not expected or not all(
        isinstance(path, str) and isinstance(blob, str)
        for path, blob in expected.items()
    ):
        raise SourceBundleError("Árvore Git contém blobs inválidos")
    root, actual = archive_git_blobs(archive_path)
    if root != expected_root:
        raise SourceBundleError("Root do source snapshot diverge da revisão")
    if len(actual) != expected_file_count:
        raise SourceBundleError("Contagem de arquivos do source snapshot diverge")
    extra = set(actual) - set(expected)
    missing = set(expected) - set(actual)
    if extra:
        raise SourceBundleError("Source snapshot contém blob fora da árvore Git")
    if strategy != "git_archive_export_ignore" and missing:
        raise SourceBundleError("Source snapshot omite blob da árvore Git")
    mismatches: list[str] = []
    for relative, archive_blob in actual.items():
        if archive_blob == expected[relative]:
            continue
        if strategy != "git_archive_eol_normalized":
            mismatches.append(relative)
            continue
        suffix = PurePosixPath(relative).suffix.casefold()
        if suffix not in {
            ".bat",
            ".cmd",
            ".rc",
            ".sln",
            ".vcproj",
            ".vcxproj",
        }:
            mismatches.append(relative)
            continue
        try:
            with tarfile.open(archive_path, "r:*") as archive:
                member = next(
                    item
                    for item in archive.getmembers()
                    if item.name.endswith(f"/{relative}") and item.isfile()
                )
                stream = archive.extractfile(member)
                if stream is None:
                    raise SourceBundleError("Arquivo CRLF do snapshot está ilegível")
                normalized = stream.read().replace(b"\r\n", b"\n")
        except (OSError, StopIteration, tarfile.TarError) as error:
            raise SourceBundleError("Arquivo CRLF do snapshot está ausente") from error
        if git_blob_sha1(normalized) != expected[relative]:
            mismatches.append(relative)
    if mismatches:
        raise SourceBundleError(
            f"Source snapshot diverge da árvore Git: {mismatches[0]}"
        )


def verify_sfparse_coverage(archive_path: Path, specification: dict[str, Any]) -> None:
    """Confirma que o nghttp3 incorpora os blobs materiais exatos do sfparse."""
    material_files = specification.get("material_files")
    if not isinstance(material_files, list) or not material_files:
        raise SourceBundleError("Mapa material do sfparse está ausente")
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            members = {member.name: member for member in archive.getmembers()}
            for expected in material_files:
                suffix = expected.get("path")
                if not isinstance(suffix, str):
                    raise SourceBundleError("Path material do sfparse é inválido")
                matches = [
                    member
                    for name, member in members.items()
                    if name.endswith(f"/{suffix}") and member.isfile()
                ]
                if len(matches) != 1:
                    raise SourceBundleError(f"Material sfparse ausente: {suffix}")
                stream = archive.extractfile(matches[0])
                if stream is None:
                    raise SourceBundleError(f"Material sfparse ilegível: {suffix}")
                content = stream.read()
                if len(content) != expected.get("size"):
                    raise SourceBundleError(f"Tamanho sfparse divergente: {suffix}")
                if git_blob_sha1(content) != expected.get("git_blob_sha1"):
                    raise SourceBundleError(f"Revisão sfparse divergente: {suffix}")
                if sha256_bytes(content) != expected.get("sha256"):
                    raise SourceBundleError(f"SHA-256 sfparse divergente: {suffix}")
    except (OSError, tarfile.TarError) as error:
        raise SourceBundleError("Archive nghttp3 inválido para sfparse") from error


def _validate_relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceBundleError(f"{field} deve ser um caminho relativo não vazio")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or "\\" in value
        or _WINDOWS_ABSOLUTE_PATH.search(value)
    ):
        raise SourceBundleError(f"{field} contém caminho absoluto ou inseguro")
    folded_parts = {part.casefold() for part in pure.parts}
    if pure.name.casefold() in _PROHIBITED_NAMES or folded_parts & _PROHIBITED_PARTS:
        raise SourceBundleError(f"{field} inclui source proprietário ou privado")
    return value


def _validate_file_entry(entry: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise SourceBundleError(f"{field} deve ser um objeto")
    required = {"origin", "purpose", "sha256", "size", "staging_path"}
    if set(entry) != required:
        raise SourceBundleError(f"{field} possui campos ausentes ou inesperados")
    _validate_relative_path(entry["staging_path"], field=f"{field}.staging_path")
    if not isinstance(entry["origin"], str) or not entry["origin"]:
        raise SourceBundleError(f"{field}.origin deve identificar o upstream")
    if _WINDOWS_ABSOLUTE_PATH.search(entry["origin"]):
        raise SourceBundleError(f"{field}.origin contém caminho local")
    if not isinstance(entry["purpose"], str) or not entry["purpose"]:
        raise SourceBundleError(f"{field}.purpose deve explicar o uso")
    if not isinstance(entry["size"], int) or entry["size"] < 0:
        raise SourceBundleError(f"{field}.size deve ser inteiro não negativo")
    if not isinstance(entry["sha256"], str) or not _HEX_64.fullmatch(entry["sha256"]):
        raise SourceBundleError(f"{field}.sha256 deve ser hexadecimal maiúsculo")
    return entry


def _validate_source_entry(entry: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise SourceBundleError(f"{field} deve ser um objeto")
    required = {
        "component",
        "coverage",
        "filename",
        "integrity_authority",
        "official_upstream",
        "origin",
        "purpose",
        "sha256",
        "size",
        "staging_path",
        "status",
        "version",
    }
    if set(entry) != required:
        raise SourceBundleError(f"{field} possui campos ausentes ou inesperados")
    _validate_file_entry(
        {
            key: entry[key]
            for key in ("origin", "purpose", "sha256", "size", "staging_path")
        },
        field=field,
    )
    if not all(
        isinstance(entry[key], str) and entry[key]
        for key in (
            "component",
            "coverage",
            "filename",
            "integrity_authority",
            "official_upstream",
            "version",
        )
    ):
        raise SourceBundleError(f"{field} possui identidade ou cobertura inválida")
    if entry["filename"] != PurePosixPath(entry["staging_path"]).name:
        raise SourceBundleError(f"{field}.filename diverge do staging_path")
    if entry["status"] not in _SOURCE_STATUSES:
        raise SourceBundleError(f"{field}.status inválido")
    return entry


def _validate_metadata_collection(entry: Any, *, field: str) -> dict[str, Any]:
    required = {
        "file_count",
        "inventory_sha256",
        "origin_authorities",
        "purpose",
        "staging_root",
    }
    if not isinstance(entry, dict) or set(entry) != required:
        raise SourceBundleError(f"{field} possui campos ausentes ou inesperados")
    root = _validate_relative_path(entry["staging_root"], field=f"{field}.staging_root")
    if PurePosixPath(root).name in {"", "."}:
        raise SourceBundleError(f"{field}.staging_root é inválido")
    if not isinstance(entry["file_count"], int) or entry["file_count"] < 1:
        raise SourceBundleError(f"{field}.file_count deve ser positivo")
    if not _HEX_64.fullmatch(entry.get("inventory_sha256", "")):
        raise SourceBundleError(f"{field}.inventory_sha256 é inválido")
    authorities = entry["origin_authorities"]
    if (
        not isinstance(authorities, list)
        or not authorities
        or not all(
            isinstance(value, str) and value.startswith("https://")
            for value in authorities
        )
    ):
        raise SourceBundleError(f"{field}.origin_authorities é inválido")
    if not isinstance(entry["purpose"], str) or not entry["purpose"]:
        raise SourceBundleError(f"{field}.purpose deve explicar a coleção")
    return entry


def _validate_cpython_runtime_structure(cpython: Any) -> None:
    if cpython == {"status": "conditional"}:
        return
    required = {
        "archive",
        "bundled_sources",
        "external_pins",
        "metadata_collection_root",
        "non_material_externals",
        "runtime_correspondence",
        "setup_python",
        "status",
        "technical_status",
    }
    if not isinstance(cpython, dict) or set(cpython) != required:
        raise SourceBundleError("Correspondência CPython possui estrutura inválida")
    if cpython["status"] != "verified" or cpython["technical_status"] != "resolved":
        raise SourceBundleError("Estado da correspondência CPython é inválido")
    _validate_relative_path(
        cpython["metadata_collection_root"],
        field="correspondence.cpython_runtime.metadata_collection_root",
    )
    archive = cpython["archive"]
    archive_required = {
        "archive_git_common_blobs",
        "archive_git_direct_matches",
        "archive_git_eol_normalized_matches",
        "archive_only_members",
        "archive_root",
        "commit",
        "expected_file_count",
        "filename",
        "commit_metadata_path",
        "release_date",
        "sha256",
        "sigstore_digest_base64",
        "sigstore_metadata_path",
        "staging_path",
        "status",
        "tag",
        "tag_object_metadata_path",
        "tag_object",
        "tag_ref_metadata_path",
        "tree",
        "tree_metadata_path",
    }
    if not isinstance(archive, dict) or set(archive) != archive_required:
        raise SourceBundleError("Archive CPython possui estrutura inválida")
    _validate_relative_path(
        archive["staging_path"], field="correspondence.cpython_runtime.archive"
    )
    if archive["status"] != "verified" or not _HEX_64.fullmatch(
        archive.get("sha256", "")
    ):
        raise SourceBundleError("Archive CPython não está verificado")
    if not all(
        isinstance(archive.get(field), int) and archive[field] >= 0
        for field in (
            "archive_git_common_blobs",
            "archive_git_direct_matches",
            "archive_git_eol_normalized_matches",
            "expected_file_count",
        )
    ):
        raise SourceBundleError("Contagens do archive CPython são inválidas")
    bundled = cpython["bundled_sources"]
    if not isinstance(bundled, list) or {
        item.get("component") for item in bundled if isinstance(item, dict)
    } != {"Expat", "mpdecimal"}:
        raise SourceBundleError("Sources vendorizados CPython estão incompletos")
    if any(
        item.get("status") != "covered-by-parent"
        or item.get("separate_source_required") is not False
        for item in bundled
    ):
        raise SourceBundleError("Source vendorizado CPython foi aberto indevidamente")
    pins = cpython["external_pins"]
    if not isinstance(pins, list) or {
        item.get("component") for item in pins if isinstance(item, dict)
    } != set(OFFICIAL_CPYTHON_EXTERNAL_PINS):
        raise SourceBundleError("Pins externos CPython estão incompletos")
    for pin in pins:
        required_pin_fields = {
            "archive_blob_count",
            "archive_direct_matches",
            "archive_eol_normalized_matches",
            "archive_root",
            "component",
            "coverage",
            "cpython_pin_evidence",
            "expected_source_archive",
            "integrity_authority",
            "license_references",
            "material_evidence",
            "material_role",
            "patches",
            "preservation_filename",
            "source_archive_component",
            "source_archive_strategy",
            "source_commit",
            "source_filename",
            "source_repository",
            "source_sha256",
            "source_size",
            "source_staging_path",
            "source_tag",
            "source_tree",
            "status",
            "technical_status",
            "tree_metadata_path",
            "upstream",
            "version",
            "windows_configuration",
        }
        if not required_pin_fields.issubset(pin):
            raise SourceBundleError("Pin externo CPython possui campos ausentes")
        if (
            pin.get("status") != "verified"
            or pin.get("technical_status") != "resolved"
            or not _HEX_64.fullmatch(pin.get("source_sha256", ""))
            or not isinstance(pin.get("source_size"), int)
            or pin["source_size"] < 1
            or pin.get("integrity_authority") != "local_calculated_verified_revision"
            or not isinstance(pin.get("license_references"), list)
            or not pin["license_references"]
            or not isinstance(pin.get("expected_source_archive"), str)
            or not isinstance(pin.get("source_repository"), str)
            or not isinstance(pin.get("upstream"), str)
        ):
            raise SourceBundleError("Pin externo CPython possui estado inválido")
        for field in (
            "expected_source_archive",
            "preservation_filename",
            "source_filename",
        ):
            if pin[field] != PurePosixPath(pin["source_staging_path"]).name:
                raise SourceBundleError("Nome do archive externo CPython diverge")
        _validate_relative_path(
            pin["source_staging_path"],
            field=f"external_pins.{pin['component']}.source_staging_path",
        )
        _validate_relative_path(
            pin["tree_metadata_path"],
            field=f"external_pins.{pin['component']}.tree_metadata_path",
        )
        for field in ("source_commit", "source_tree"):
            if not isinstance(pin.get(field), str) or not re.fullmatch(
                r"[0-9a-f]{40}", pin[field]
            ):
                raise SourceBundleError("Revision de external CPython é inválida")
    if cpython["setup_python"].get("patch_provenance") != "B":
        raise SourceBundleError("Proveniência do patch CPython foi ampliada")


def _walk_strings(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, str):
        yield value


def _validate_native_curl_structure(native_curl: dict[str, Any]) -> None:
    """Valida o contrato detalhado da closure nativa quando presente."""
    if "parents" not in native_curl:
        return
    required = {
        "build_reproducibility_status",
        "closure",
        "closure_status",
        "curl_cffi_commit",
        "curl_impersonate_commit",
        "curl_impersonate_tag",
        "curl_tree_metadata_path",
        "embedded_evidence",
        "parents",
        "patches",
        "sfparse",
        "status",
        "submodules",
    }
    if set(native_curl) != required:
        raise SourceBundleError("Closure curl nativa possui campos divergentes")
    parents = native_curl["parents"]
    if not isinstance(parents, list) or not parents:
        raise SourceBundleError("Parents da closure curl estão ausentes")
    parent_required = {
        "archive_strategy",
        "component",
        "coverage",
        "expected_archive_file_count",
        "filename",
        "integrity_authority",
        "license_files",
        "local_preservation_filename",
        "metadata",
        "patches",
        "revision",
        "sha256",
        "size",
        "source_staging_path",
        "submodule_status",
        "tag",
        "technical_status",
        "tree",
        "upstream",
        "verification",
    }
    components: set[str] = set()
    for index, parent in enumerate(parents):
        field = f"correspondence.native_curl.parents[{index}]"
        if not isinstance(parent, dict) or set(parent) != parent_required:
            raise SourceBundleError(f"{field} possui campos divergentes")
        component = parent["component"]
        if not isinstance(component, str) or not component or component in components:
            raise SourceBundleError(f"{field}.component é inválido ou duplicado")
        components.add(component)
        for key in (
            "coverage",
            "filename",
            "local_preservation_filename",
            "revision",
            "submodule_status",
            "tree",
            "upstream",
            "verification",
        ):
            if not isinstance(parent[key], str) or not parent[key]:
                raise SourceBundleError(f"{field}.{key} deve ser texto não vazio")
        if parent["filename"] != parent["local_preservation_filename"]:
            raise SourceBundleError(f"{field} possui filenames divergentes")
        if parent["integrity_authority"] not in _NATIVE_INTEGRITY_AUTHORITIES:
            raise SourceBundleError(f"{field}.integrity_authority é inválido")
        if parent["archive_strategy"] not in _NATIVE_ARCHIVE_STRATEGIES:
            raise SourceBundleError(f"{field}.archive_strategy é inválido")
        if parent["technical_status"] not in _NATIVE_TECHNICAL_STATUSES:
            raise SourceBundleError(f"{field}.technical_status é inválido")
        if not isinstance(parent["size"], int) or parent["size"] <= 0:
            raise SourceBundleError(f"{field}.size é inválido")
        if (
            not isinstance(parent["expected_archive_file_count"], int)
            or parent["expected_archive_file_count"] <= 0
        ):
            raise SourceBundleError(f"{field} possui contagem de arquivos inválida")
        if not isinstance(parent["sha256"], str) or not _HEX_64.fullmatch(
            parent["sha256"]
        ):
            raise SourceBundleError(f"{field}.sha256 é inválido")
        _validate_relative_path(
            parent["source_staging_path"], field=f"{field}.source_staging_path"
        )
        if parent["tag"] is not None and (
            not isinstance(parent["tag"], str) or not parent["tag"]
        ):
            raise SourceBundleError(f"{field}.tag é inválido")
        if not isinstance(parent["patches"], list) or not all(
            isinstance(item, str) and item for item in parent["patches"]
        ):
            raise SourceBundleError(f"{field}.patches é inválido")
        if not isinstance(parent["license_files"], list) or not parent["license_files"]:
            raise SourceBundleError(f"{field}.license_files é inválido")
        metadata = parent["metadata"]
        if not isinstance(metadata, dict) or not metadata:
            raise SourceBundleError(f"{field}.metadata é inválido")
        for key, value in metadata.items():
            if not isinstance(key, str):
                raise SourceBundleError(f"{field}.metadata possui chave inválida")
            _validate_relative_path(value, field=f"{field}.metadata.{key}")
    if components != {
        "BoringSSL",
        "Brotli native",
        "nghttp2",
        "nghttp3",
        "ngtcp2",
        "zlib",
        "zstd",
    }:
        raise SourceBundleError("Conjunto de parents curl nativos diverge")
    _validate_relative_path(
        native_curl["curl_tree_metadata_path"],
        field="correspondence.native_curl.curl_tree_metadata_path",
    )
    if native_curl["closure_status"] != "resolved-source-correspondence":
        raise SourceBundleError("Closure curl source não está tecnicamente resolvida")
    if native_curl["build_reproducibility_status"] != "partial":
        raise SourceBundleError("Reprodutibilidade curl foi indevidamente ampliada")
    sfparse = native_curl["sfparse"]
    if not isinstance(sfparse, dict) or sfparse.get("status") not in {
        "covered-by-parent",
        "resolved-separately",
    }:
        raise SourceBundleError("Estado do sfparse é inválido")
    if not isinstance(native_curl["patches"], list) or not native_curl["patches"]:
        raise SourceBundleError("Mapa de patches curl está ausente")
    patch_required = {
        "allowed_preimage_mismatches",
        "expected_new_files",
        "expected_verified_preimages",
        "mechanical_replay_status",
        "path",
        "purpose",
        "sha256",
        "size",
        "target_components",
        "technical_status",
    }
    for index, patch in enumerate(native_curl["patches"]):
        field = f"correspondence.native_curl.patches[{index}]"
        if not isinstance(patch, dict) or set(patch) != patch_required:
            raise SourceBundleError(f"{field} possui campos divergentes")
        _validate_relative_path(patch["path"], field=f"{field}.path")
        if not isinstance(patch["sha256"], str) or not _HEX_64.fullmatch(
            patch["sha256"]
        ):
            raise SourceBundleError(f"{field}.sha256 é inválido")
        if not isinstance(patch["size"], int) or patch["size"] <= 0:
            raise SourceBundleError(f"{field}.size é inválido")
        for key in ("expected_new_files", "expected_verified_preimages"):
            if not isinstance(patch[key], int) or patch[key] < 0:
                raise SourceBundleError(f"{field}.{key} é inválido")
        if (
            not isinstance(patch["target_components"], list)
            or not patch["target_components"]
        ):
            raise SourceBundleError(f"{field}.target_components é inválido")
        if not isinstance(patch["allowed_preimage_mismatches"], list):
            raise SourceBundleError(f"{field} possui exceções inválidas")
    if not isinstance(native_curl["submodules"], list):
        raise SourceBundleError("Mapa de submodules curl é inválido")
    for index, submodule in enumerate(native_curl["submodules"]):
        if not isinstance(submodule, dict) or set(submodule) != {
            "classification",
            "disposition",
            "material",
            "parent",
            "path",
            "revision",
        }:
            raise SourceBundleError(
                f"correspondence.native_curl.submodules[{index}] é inválido"
            )


def _validate_python_p2_structure(python_p2: dict[str, Any]) -> None:
    """Valida o contrato dos packages Python materiais do lote P2."""
    if "packages" not in python_p2:
        if python_p2 == {"status": "conditional"}:
            return
        raise SourceBundleError("Packages Python P2 estão ausentes")
    required = {
        "build_only_dependencies",
        "native_closures",
        "packages",
        "status",
        "technical_status",
        "vendors",
    }
    if set(python_p2) != required:
        raise SourceBundleError("Closure Python P2 possui campos divergentes")
    if python_p2["status"] not in _SOURCE_STATUSES:
        raise SourceBundleError("Status da closure Python P2 é inválido")
    if python_p2["technical_status"] not in {"blocked", "partial", "resolved"}:
        raise SourceBundleError("Estado técnico da closure Python P2 é inválido")
    packages = python_p2["packages"]
    if not isinstance(packages, list) or not packages:
        raise SourceBundleError("Packages Python P2 estão ausentes")
    package_required = {
        "archive_root",
        "build_only_dependencies",
        "component",
        "coverage",
        "dist_info_status",
        "integrity_authority",
        "license_files",
        "lock_hash",
        "lock_path",
        "material_name",
        "metadata_staging_path",
        "native_status",
        "observed_native_extensions",
        "observed_python_modules",
        "package",
        "required_archive_members",
        "source_filename",
        "source_sha256",
        "source_size",
        "source_staging_path",
        "technical_status",
        "upstream",
        "vendor_status",
        "version",
    }
    components: set[str] = set()
    package_names: set[str] = set()
    for index, package in enumerate(packages):
        field = f"correspondence.python_p2.packages[{index}]"
        if not isinstance(package, dict) or set(package) != package_required:
            raise SourceBundleError(f"{field} possui campos divergentes")
        component = package["component"]
        package_name = package["package"]
        if (
            not isinstance(component, str)
            or not component
            or component in components
            or not isinstance(package_name, str)
            or not package_name
            or package_name in package_names
        ):
            raise SourceBundleError(f"{field} possui identidade inválida")
        components.add(component)
        package_names.add(package_name)
        for key in (
            "archive_root",
            "coverage",
            "dist_info_status",
            "integrity_authority",
            "material_name",
            "native_status",
            "source_filename",
            "upstream",
            "vendor_status",
            "version",
        ):
            if not isinstance(package[key], str) or not package[key]:
                raise SourceBundleError(f"{field}.{key} deve ser texto não vazio")
        for key in ("lock_path", "metadata_staging_path", "source_staging_path"):
            _validate_relative_path(package[key], field=f"{field}.{key}")
        for key in ("lock_hash", "source_sha256"):
            if not isinstance(package[key], str) or not _HEX_64.fullmatch(package[key]):
                raise SourceBundleError(f"{field}.{key} é inválido")
        if not isinstance(package["source_size"], int) or package["source_size"] <= 0:
            raise SourceBundleError(f"{field}.source_size é inválido")
        for key in ("observed_native_extensions", "observed_python_modules"):
            if not isinstance(package[key], int) or package[key] < 0:
                raise SourceBundleError(f"{field}.{key} é inválido")
        for key in (
            "build_only_dependencies",
            "license_files",
            "required_archive_members",
        ):
            values = package[key]
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise SourceBundleError(f"{field}.{key} é inválido")
            if values != sorted(set(values)):
                raise SourceBundleError(f"{field}.{key} deve ser determinístico")
        if not package["license_files"] or not package["required_archive_members"]:
            raise SourceBundleError(f"{field} não fixa source/licença suficientes")
        if package["technical_status"] not in {"blocked", "partial", "resolved"}:
            raise SourceBundleError(f"{field}.technical_status é inválido")
    vendors = python_p2["vendors"]
    if not isinstance(vendors, list):
        raise SourceBundleError("Mapa de vendors setuptools é inválido")
    vendor_required = {
        "license_paths",
        "material_in_executable",
        "material_name",
        "parent_package",
        "source_additional_required",
        "source_path_prefix",
        "technical_status",
        "version",
    }
    vendor_names: set[str] = set()
    for index, vendor in enumerate(vendors):
        field = f"correspondence.python_p2.vendors[{index}]"
        if not isinstance(vendor, dict) or set(vendor) != vendor_required:
            raise SourceBundleError(f"{field} possui campos divergentes")
        name = vendor["material_name"]
        if not isinstance(name, str) or not name or name in vendor_names:
            raise SourceBundleError(f"{field}.material_name é inválido")
        vendor_names.add(name)
        if vendor["parent_package"] != "setuptools":
            raise SourceBundleError(f"{field} possui parent divergente")
        if vendor["material_in_executable"] is not True:
            raise SourceBundleError(f"{field} não está marcado como material")
        if vendor["source_additional_required"] is not False:
            raise SourceBundleError(f"{field} ampliou a closure de vendors")
        if vendor["technical_status"] != "covered-by-parent":
            raise SourceBundleError(f"{field}.technical_status é inválido")
        for key in ("source_path_prefix", "version"):
            if not isinstance(vendor[key], str) or not vendor[key]:
                raise SourceBundleError(f"{field}.{key} é inválido")
        if not isinstance(vendor["license_paths"], list) or not vendor["license_paths"]:
            raise SourceBundleError(f"{field}.license_paths é inválido")
        if not all(
            isinstance(path, str) and path for path in vendor["license_paths"]
        ) or vendor["license_paths"] != sorted(set(vendor["license_paths"])):
            raise SourceBundleError(f"{field}.license_paths deve ser determinístico")
        _validate_relative_path(
            vendor["source_path_prefix"], field=f"{field}.source_path_prefix"
        )
    build_only = python_p2["build_only_dependencies"]
    if not isinstance(build_only, list):
        raise SourceBundleError("Mapa build-only Python P2 é inválido")
    for index, dependency in enumerate(build_only):
        if not isinstance(dependency, dict) or set(dependency) != {
            "classification",
            "component",
            "material_in_executable",
            "parent",
            "reason",
            "source_required",
        }:
            raise SourceBundleError(
                f"correspondence.python_p2.build_only_dependencies[{index}] é inválido"
            )
        if (
            dependency["classification"] != "build-only"
            or dependency["material_in_executable"] is not False
            or dependency["source_required"] is not False
        ):
            raise SourceBundleError(
                "Dependência build-only foi promovida indevidamente"
            )
        if not all(
            isinstance(dependency[key], str) and dependency[key]
            for key in ("component", "parent", "reason")
        ):
            raise SourceBundleError("Dependência build-only possui texto inválido")
    native_closures = python_p2["native_closures"]
    if not isinstance(native_closures, list):
        raise SourceBundleError("Mapa de closures nativas Python P2 é inválido")
    for index, closure in enumerate(native_closures):
        if not isinstance(closure, dict) or set(closure) != {
            "component",
            "evidence",
            "parent",
            "separate_source_required",
            "status",
        }:
            raise SourceBundleError(
                f"correspondence.python_p2.native_closures[{index}] é inválido"
            )
        if (
            closure["status"] != "covered-by-parent"
            or closure["separate_source_required"] is not False
        ):
            raise SourceBundleError("Closure nativa Python P2 permanece aberta")
        if not all(
            isinstance(closure[key], str) and closure[key]
            for key in ("component", "evidence", "parent")
        ):
            raise SourceBundleError("Closure nativa Python P2 possui texto inválido")


def validate_manifest_structure(manifest: Any) -> dict[str, Any]:
    """Valida estrutura, privacidade e allowlist do manifesto."""
    if not isinstance(manifest, dict):
        raise SourceBundleError("Manifesto deve ser um objeto JSON")
    required = {
        "build_inputs",
        "component",
        "correspondence",
        "dependencies",
        "executable",
        "metadata_collections",
        "missing_sources",
        "provenance_metadata",
        "release_commit",
        "release_tag",
        "requirements_locks",
        "schema_version",
        "source_archive",
        "source_archives",
        "source_bundle",
        "source_commit",
        "toolchain",
        "version",
    }
    if set(manifest) != required:
        raise SourceBundleError("Manifesto possui campos ausentes ou inesperados")
    for text in _walk_strings(manifest):
        if _WINDOWS_ABSOLUTE_PATH.search(text) or "USERPROFILE" in text.upper():
            raise SourceBundleError(
                "Manifesto contém caminho local ou variável pessoal"
            )
    source = _validate_file_entry(manifest["source_archive"], field="source_archive")
    build_inputs = manifest["build_inputs"]
    if not isinstance(build_inputs, list) or not build_inputs:
        raise SourceBundleError("build_inputs deve ser uma lista não vazia")
    for index, entry in enumerate(build_inputs):
        _validate_file_entry(entry, field=f"build_inputs[{index}]")
    source_archives = manifest["source_archives"]
    if not isinstance(source_archives, list) or not source_archives:
        raise SourceBundleError("source_archives deve ser uma lista não vazia")
    for index, entry in enumerate(source_archives):
        _validate_source_entry(entry, field=f"source_archives[{index}]")
    provenance_metadata = manifest["provenance_metadata"]
    if not isinstance(provenance_metadata, list) or not provenance_metadata:
        raise SourceBundleError("provenance_metadata deve ser uma lista não vazia")
    for index, entry in enumerate(provenance_metadata):
        _validate_file_entry(entry, field=f"provenance_metadata[{index}]")
    metadata_collections = manifest["metadata_collections"]
    if not isinstance(metadata_collections, list):
        raise SourceBundleError("metadata_collections deve ser uma lista")
    for index, entry in enumerate(metadata_collections):
        _validate_metadata_collection(entry, field=f"metadata_collections[{index}]")
    correspondence = manifest["correspondence"]
    if not isinstance(correspondence, dict) or set(correspondence) != {
        "certifi",
        "cpython_runtime",
        "ejs",
        "native_curl",
        "python_p2",
    }:
        raise SourceBundleError(
            "correspondence deve mapear Certifi, EJS, curl nativo e Python P2"
        )
    for component, entry in correspondence.items():
        if not isinstance(entry, dict) or entry.get("status") not in _SOURCE_STATUSES:
            raise SourceBundleError(f"correspondence.{component}.status inválido")
    _validate_native_curl_structure(correspondence["native_curl"])
    _validate_python_p2_structure(correspondence["python_p2"])
    _validate_cpython_runtime_structure(correspondence["cpython_runtime"])
    paths = [
        source["staging_path"],
        *(entry["staging_path"] for entry in build_inputs),
        *(entry["staging_path"] for entry in source_archives),
        *(entry["staging_path"] for entry in provenance_metadata),
    ]
    if len(paths) != len(set(paths)):
        raise SourceBundleError("Manifesto contém staging_path duplicado")
    if [entry["staging_path"] for entry in build_inputs] != sorted(
        entry["staging_path"] for entry in build_inputs
    ):
        raise SourceBundleError("build_inputs deve permanecer em ordem determinística")
    for field, entries in (
        ("source_archives", source_archives),
        ("provenance_metadata", provenance_metadata),
        ("metadata_collections", metadata_collections),
    ):
        path_field = (
            "staging_root" if field == "metadata_collections" else "staging_path"
        )
        if [entry[path_field] for entry in entries] != sorted(
            entry[path_field] for entry in entries
        ):
            raise SourceBundleError(f"{field} deve permanecer em ordem determinística")
    collection_roots = [
        entry["staging_root"].rstrip("/") for entry in metadata_collections
    ]
    if len(collection_roots) != len(set(collection_roots)) or any(
        left.startswith(f"{right}/") or right.startswith(f"{left}/")
        for index, left in enumerate(collection_roots)
        for right in collection_roots[index + 1 :]
    ):
        raise SourceBundleError("metadata_collections possui roots sobrepostos")
    _validate_relative_path(
        manifest["source_bundle"].get("bundle_filename"),
        field="source_bundle.bundle_filename",
    )
    return manifest


def validate_official_identity(manifest: dict[str, Any]) -> None:
    """Fixa a identidade da única baseline operacional autorizada."""
    if manifest.get("schema_version") != 3:
        raise SourceBundleError("Versão do schema de provenance divergente")
    expected = {
        "component": OFFICIAL_COMPONENT,
        "version": OFFICIAL_VERSION,
        "release_tag": OFFICIAL_VERSION,
        "source_commit": OFFICIAL_SOURCE_COMMIT,
        "release_commit": OFFICIAL_RELEASE_COMMIT,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise SourceBundleError(f"Baseline oficial divergente em {field}")
    executable = manifest.get("executable")
    if not isinstance(executable, dict) or executable.get("sha256") != (
        OFFICIAL_EXECUTABLE_SHA256
    ):
        raise SourceBundleError("Baseline oficial divergente no executável")
    source = manifest["source_archive"]
    if (
        source["staging_path"] != "upstream/yt-dlp.tar.gz"
        or source["size"] != 6_020_567
        or source["sha256"] != OFFICIAL_SOURCE_ARCHIVE_SHA256
    ):
        raise SourceBundleError("Baseline oficial divergente no source archive")
    toolchain = manifest.get("toolchain", {})
    if toolchain.get("python", {}).get("embedded_version") != "3.10.11":
        raise SourceBundleError("Proveniência Python divergente")
    if toolchain.get("pyinstaller", {}).get("version") != "6.22.0":
        raise SourceBundleError("Proveniência PyInstaller divergente")
    if toolchain.get("pyinstaller", {}).get("source_asset_status") != (
        "verified-preserved"
    ):
        raise SourceBundleError("Source PyInstaller não está preservado")
    if (
        toolchain.get("pyinstaller", {}).get("builds_release_tag")
        != "2026.08.19.215425"
        or toolchain.get("pyinstaller", {}).get("builds_release_commit")
        != "5eb86b862d61adc3df0f44e6e0b815b7d74fa3f5"
        or toolchain.get("pyinstaller", {}).get("source_asset_sha256")
        != "2FADBED5D951D53F003ED899312823A07DBBA59990A223CBE538933E1C42A168"
        or toolchain.get("pyinstaller", {}).get("wheel_sha256")
        != "294099ECB5FDD2A13AE4C29006D4E335B697A63B6A16CF052B90EC2B40BEF05A"
        or toolchain.get("pyinstaller", {}).get("wheel_size") != 1_101_025
    ):
        raise SourceBundleError("Identidade PyInstaller da baseline diverge")
    source_statuses = {
        entry["component"]: entry["status"] for entry in manifest["source_archives"]
    }
    if source_statuses != {
        "Astring": "verified",
        "Astring package input": "verified",
        "BoringSSL": "verified",
        "Brotli Python": "verified",
        "Brotli native": "verified",
        "CPython": "verified",
        "CPython OpenSSL runtime": "verified",
        "CPython SQLite runtime": "verified",
        "CPython XZ/liblzma runtime": "verified",
        "CPython bzip2 runtime": "verified",
        "CPython libffi runtime": "verified",
        "CPython zlib runtime": "verified",
        "Meriyah": "verified",
        "Meriyah package input": "verified",
        "Mozilla certdata": "verified",
        "PyCryptodome": "verified",
        "PyInstaller": "verified",
        "certifi": "verified",
        "cffi": "verified",
        "charset-normalizer": "verified",
        "curl": "verified",
        "curl_cffi": "verified",
        "curl-impersonate": "verified",
        "idna": "verified",
        "mutagen": "verified",
        "nghttp2": "verified",
        "nghttp3": "verified",
        "ngtcp2": "verified",
        "pycparser": "verified",
        "requests": "verified",
        "typing-extensions": "verified",
        "urllib3": "verified",
        "websockets": "verified",
        "yt-dlp-ejs": "verified",
        "zlib": "verified",
        "zstd": "verified",
    }:
        raise SourceBundleError("Estado dos sources externos diverge da baseline")
    correspondence = manifest["correspondence"]
    if (
        correspondence["certifi"].get("status") != "verified"
        or correspondence["cpython_runtime"].get("status") != "verified"
        or correspondence["ejs"].get("status") != "verified"
        or correspondence["native_curl"].get("status") != "verified"
        or correspondence["python_p2"].get("status") != "verified"
    ):
        raise SourceBundleError("Closure Certifi/EJS/curl/P2 diverge da baseline")
    certifi = correspondence["certifi"]
    if (
        certifi.get("certdata_commit") != "4e9426ae522c67de47ff3e060774328b42df0134"
        or certifi.get("mkcert_service_commit")
        != "90d0d3395d94391b365bf6a3a3bfa444be5cc4b8"
        or certifi.get("trusted_certificate_count") != 121
        or certifi.get("cacert_sha256")
        != "9CC2A774B5198DCFF14D9BE1E66091F538975D867CE029A96BCE15A55DFD730F"
    ):
        raise SourceBundleError("Correspondência Certifi/certdata diverge")
    ejs_dependencies = {
        item.get("component"): item.get("source_status")
        for item in correspondence["ejs"].get("bundled_dependencies", [])
    }
    if ejs_dependencies != {"Astring": "verified", "Meriyah": "verified"}:
        raise SourceBundleError("Sources incorporados pelo EJS estão incompletos")
    native_curl = correspondence["native_curl"]
    parent_statuses = {
        item.get("component"): item.get("technical_status")
        for item in native_curl.get("parents", [])
    }
    if parent_statuses != {
        "BoringSSL": "resolved",
        "Brotli native": "resolved",
        "nghttp2": "resolved",
        "nghttp3": "resolved",
        "ngtcp2": "resolved",
        "zlib": "resolved",
        "zstd": "resolved",
    }:
        raise SourceBundleError("Parents nativos da closure curl estão incompletos")
    parent_revisions = {
        item.get("component"): item.get("revision")
        for item in native_curl.get("parents", [])
    }
    if parent_revisions != {
        "BoringSSL": "156c7b75ae9b8c3b3f847acf264f17594c3859fb",
        "Brotli native": "1.2.0",
        "nghttp2": "8f44147c385fb1ed93a6f39911eeb30279bfd2dd",
        "nghttp3": "d326f4c1eb3f6a780d77793b30e16756c498f913",
        "ngtcp2": "ca898d32348c93af9fbbc81538505a1c1c062685",
        "zlib": "1.3.1",
        "zstd": "1.5.7",
    }:
        raise SourceBundleError("Revisions dos parents curl divergem da baseline")
    if (
        native_curl.get("sfparse", {}).get("status") != "covered-by-parent"
        or native_curl.get("sfparse", {}).get("revision")
        != "ff7f230e7df2844afef7dc49631cda03a30455f3"
        or native_curl.get("closure_status") != "resolved-source-correspondence"
        or native_curl.get("build_reproducibility_status") != "partial"
    ):
        raise SourceBundleError("Closure curl ou sfparse diverge da baseline")
    material_submodules = {
        (item.get("parent"), item.get("path"), item.get("revision"))
        for item in native_curl.get("submodules", [])
        if item.get("material") is True
    }
    if material_submodules != {
        (
            "nghttp3",
            "lib/sfparse",
            "ff7f230e7df2844afef7dc49631cda03a30455f3",
        )
    } or any(
        item.get("material") is not False
        for item in native_curl.get("submodules", [])
        if (item.get("parent"), item.get("path"), item.get("revision"))
        not in material_submodules
    ):
        raise SourceBundleError("Classificação dos submodules curl diverge")
    python_p2 = correspondence["python_p2"]
    package_versions = {
        item.get("package"): item.get("version")
        for item in python_p2.get("packages", [])
    }
    if package_versions != {
        "brotli": "1.2.0",
        "cffi": "2.1.1",
        "charset-normalizer": "3.5.0",
        "idna": "3.18",
        "pycparser": "3.0",
        "pycryptodomex": "3.23.0",
        "requests": "2.34.2",
        "typing-extensions": "4.16.0",
        "urllib3": "2.7.0",
        "websockets": "16.1.1",
    }:
        raise SourceBundleError("Packages Python P2 divergem da baseline")
    if python_p2.get("technical_status") != "resolved" or any(
        item.get("technical_status") != "resolved"
        for item in python_p2.get("packages", [])
    ):
        raise SourceBundleError("Closure Python P2 permanece incompleta")
    cpython = correspondence["cpython_runtime"]
    archive = cpython["archive"]
    if (
        archive.get("sha256") != OFFICIAL_CPYTHON_SOURCE_SHA256
        or archive.get("commit") != OFFICIAL_CPYTHON_COMMIT
        or archive.get("tree") != OFFICIAL_CPYTHON_TREE
        or archive.get("tag_object") != OFFICIAL_CPYTHON_TAG_OBJECT
        or archive.get("tag") != "v3.10.11"
        or archive.get("expected_file_count") != 4278
        or archive.get("archive_git_common_blobs") != 4277
        or archive.get("archive_git_direct_matches") != 4127
        or archive.get("archive_git_eol_normalized_matches") != 150
        or archive.get("archive_only_members") != ["Misc/NEWS"]
    ):
        raise SourceBundleError("Identidade do source CPython diverge da baseline")
    pin_revisions = {
        item.get("component"): (
            item.get("source_tag"),
            item.get("source_commit"),
            item.get("source_tree"),
        )
        for item in cpython.get("external_pins", [])
    }
    if pin_revisions != OFFICIAL_CPYTHON_EXTERNAL_PINS:
        raise SourceBundleError("Pins PCbuild CPython divergem da baseline")
    setup_python = cpython["setup_python"]
    if (
        setup_python.get("action_commit") != "ece7cb06caefa5fff74198d8649806c4678c61a1"
        or setup_python.get("manifest_commit")
        != "db69292aaf8695dd9a240def024d487e61e3078e"
        or setup_python.get("toolcache_sha256")
        != "C7C029492644331F01FACB97382D1F145882B162D920F6B58B297AF22BF459C4"
        or setup_python.get("runtime_package_downloaded") is not False
        or setup_python.get("exact_job_consumption_proven") is not False
    ):
        raise SourceBundleError("Proveniência setup-python diverge da baseline")
    if python_p2.get("vendors") != []:
        raise SourceBundleError("Vendors não materiais foram mantidos na baseline")
    if manifest["missing_sources"] != []:
        raise SourceBundleError("Ainda há lacuna material de source na baseline")
    metadata_collections = manifest.get("metadata_collections")
    expected_collection = {
        "file_count": OFFICIAL_CPYTHON_METADATA_FILE_COUNT,
        "inventory_sha256": OFFICIAL_CPYTHON_METADATA_INVENTORY_SHA256,
        "purpose": (
            "metadata oficial de release, tag/tree, setup-python, toolcache "
            "e refs PCbuild do CPython 3.10.11"
        ),
        "staging_root": "source-metadata/lot-1e",
    }
    if not isinstance(metadata_collections, list) or len(metadata_collections) != 2:
        raise SourceBundleError("Coleções de metadata CPython divergem da baseline")
    metadata_collection = metadata_collections[0]
    if (
        not isinstance(metadata_collection, dict)
        or {
            key: value
            for key, value in metadata_collection.items()
            if key != "origin_authorities"
        }
        != expected_collection
        or tuple(metadata_collection.get("origin_authorities", ()))
        != tuple(
            f"https://{host}" for host in OFFICIAL_CPYTHON_METADATA_AUTHORITY_HOSTS
        )
    ):
        raise SourceBundleError("Coleção de metadata CPython diverge da baseline")
    external_collection = metadata_collections[1]
    if external_collection != {
        "file_count": OFFICIAL_CPYTHON_EXTERNAL_METADATA_FILE_COUNT,
        "inventory_sha256": OFFICIAL_CPYTHON_EXTERNAL_METADATA_INVENTORY_SHA256,
        "origin_authorities": [
            f"https://{host}"
            for host in OFFICIAL_CPYTHON_EXTERNAL_METADATA_AUTHORITY_HOSTS
        ],
        "purpose": (
            "trees recursivas oficiais das seis revisions cpython-source-deps "
            "materiais do runtime CPython 3.10.11"
        ),
        "staging_root": "source-metadata/lot-1f",
    }:
        raise SourceBundleError("Metadata dos externals CPython diverge da baseline")
    external_sources = {
        entry["component"]: entry
        for entry in manifest["source_archives"]
        if entry["component"].startswith("CPython ") and entry["component"] != "CPython"
    }
    expected_external_components = {
        f"CPython {component.removesuffix(' runtime')} runtime"
        for component in OFFICIAL_CPYTHON_EXTERNAL_ARCHIVES
    }
    if set(external_sources) != expected_external_components:
        raise SourceBundleError("Sources dos externals CPython estão incompletos")
    for pin in cpython["external_pins"]:
        archive_identity = OFFICIAL_CPYTHON_EXTERNAL_ARCHIVES[pin["component"]]
        expected_component = (
            f"CPython {pin['component'].removesuffix(' runtime')} runtime"
        )
        source_entry = external_sources[expected_component]
        if (
            pin["source_sha256"] != archive_identity["sha256"]
            or pin["source_size"] != archive_identity["size"]
            or pin["source_filename"] != archive_identity["filename"]
            or pin["archive_root"] != archive_identity["archive_root"]
            or pin["archive_blob_count"] != archive_identity["archive_blob_count"]
            or pin["archive_direct_matches"]
            != archive_identity["archive_direct_matches"]
            or pin["archive_eol_normalized_matches"]
            != archive_identity["archive_eol_normalized_matches"]
            or pin["tree_metadata_path"] != archive_identity["tree_metadata_path"]
            or pin["version"] != archive_identity["version"]
            or tuple(pin["license_references"])
            != archive_identity["license_references"]
            or pin["source_archive_component"] != expected_component
            or source_entry["sha256"] != archive_identity["sha256"]
            or source_entry["size"] != archive_identity["size"]
            or source_entry["filename"] != archive_identity["filename"]
            or source_entry["staging_path"] != pin["source_staging_path"]
            or source_entry["integrity_authority"]
            != "local_calculated_verified_revision"
        ):
            raise SourceBundleError(
                f"Archive externo CPython diverge: {pin['component']}"
            )
    source_bundle = manifest.get("source_bundle", {})
    if (
        source_bundle.get("completeness_class") != "A"
        or source_bundle.get("status") != "technically-complete-pending-legal-review"
    ):
        raise SourceBundleError("Estado de completude técnica do bundle diverge")


def load_manifest(
    path: Path, *, enforce_official_baseline: bool = True
) -> dict[str, Any]:
    """Carrega manifesto e, no fluxo real, exige seu hash versionado."""
    try:
        content = path.read_bytes()
        manifest = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SourceBundleError("Manifesto ausente, ilegível ou inválido") from error
    validate_manifest_structure(manifest)
    if enforce_official_baseline:
        if sha256_bytes(content) != OFFICIAL_MANIFEST_SHA256:
            raise SourceBundleError("Manifesto oficial adulterado")
        validate_official_identity(manifest)
    return manifest


def expected_staging_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Retorna os arquivos permitidos no staging, indexados pelo caminho."""
    entries = [
        manifest["source_archive"],
        *manifest["build_inputs"],
        *manifest["provenance_metadata"],
        *manifest["source_archives"],
    ]
    return {entry["staging_path"]: entry for entry in entries}


def verify_certifi_correspondence(manifest: dict[str, Any], staging: Path) -> None:
    """Confirma a equivalência entre o certdata Mozilla e o cacert do sdist."""
    correspondence = manifest["correspondence"]["certifi"]
    if correspondence.get("status") != "verified":
        return
    required = {
        "cacert_archive_member",
        "cacert_sha256",
        "certdata_commit",
        "certdata_staging_path",
        "mkcert_service_commit",
        "status",
        "trusted_certificate_count",
        "verification",
        "verification_as_of_utc",
    }
    if set(correspondence) != required:
        raise SourceBundleError("Correspondência Certifi/certdata está incompleta")
    certifi_entries = [
        entry
        for entry in manifest["source_archives"]
        if entry["component"] == "certifi"
    ]
    if len(certifi_entries) != 1:
        raise SourceBundleError("Source certifi não é único no manifesto")
    certdata_path = _validate_relative_path(
        correspondence["certdata_staging_path"],
        field="correspondence.certifi.certdata_staging_path",
    )
    expected = expected_staging_entries(manifest)
    if certdata_path not in expected:
        raise SourceBundleError("certdata Mozilla não pertence ao manifesto")
    if expected[certdata_path].get("component") != "Mozilla certdata":
        raise SourceBundleError("certdata Mozilla possui identidade divergente")
    try:
        verification_as_of = datetime.fromisoformat(
            correspondence["verification_as_of_utc"].replace("Z", "+00:00")
        )
    except (AttributeError, ValueError) as error:
        raise SourceBundleError("Data da correspondência Certifi é inválida") from error
    certifi_path = staging / certifi_entries[0]["staging_path"]
    try:
        with tarfile.open(certifi_path, "r:gz") as archive:
            member = archive.getmember(correspondence["cacert_archive_member"])
            if not member.isreg():
                raise SourceBundleError("cacert.pem no sdist não é arquivo regular")
            stream = archive.extractfile(member)
            if stream is None:
                raise SourceBundleError("cacert.pem não pôde ser lido do sdist")
            cacert = stream.read()
    except (OSError, KeyError, tarfile.TarError) as error:
        raise SourceBundleError("sdist certifi não contém o cacert esperado") from error
    if sha256_bytes(cacert) != correspondence["cacert_sha256"]:
        raise SourceBundleError("SHA-256 do cacert.pem diverge")
    certdata = (staging / certdata_path).read_bytes()
    certdata_hashes = trusted_certdata_certificate_hashes(
        certdata, as_of=verification_as_of
    )
    cacert_hashes = pem_certificate_hashes(cacert)
    expected_count = correspondence["trusted_certificate_count"]
    if not isinstance(expected_count, int) or expected_count <= 0:
        raise SourceBundleError("Contagem de certificados confiáveis é inválida")
    if len(certdata_hashes) != expected_count or len(cacert_hashes) != expected_count:
        raise SourceBundleError("Contagem certdata/cacert diverge")
    if certdata_hashes != cacert_hashes:
        raise SourceBundleError("certdata Mozilla não corresponde ao cacert.pem")


def _load_staged_json(staging: Path, relative: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads((staging / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SourceBundleError(f"Metadata {label} ausente ou inválida") from error
    if not isinstance(value, dict):
        raise SourceBundleError(f"Metadata {label} deve ser um objeto")
    return value


def _archive_member_bytes(archive: tarfile.TarFile, name: str) -> bytes:
    try:
        member = archive.getmember(name)
    except KeyError as error:
        raise SourceBundleError(
            f"Archive não contém membro esperado: {name}"
        ) from error
    if not member.isfile():
        raise SourceBundleError(f"Membro esperado não é arquivo regular: {name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise SourceBundleError(f"Membro esperado não pôde ser lido: {name}")
    return stream.read()


def _regular_archive_members(path: Path) -> tuple[str, set[str]]:
    """Lista arquivos regulares e a raiz única de um tar/zip oficial."""
    try:
        if path.suffix.casefold() == ".zip":
            with zipfile.ZipFile(path) as archive:
                members = {
                    item.filename for item in archive.infolist() if not item.is_dir()
                }
        else:
            with tarfile.open(path, "r:*") as archive:
                members = {item.name for item in archive if item.isfile()}
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise SourceBundleError(f"Source archive ilegível: {path.name}") from error
    roots = {PurePosixPath(name).parts[0] for name in members}
    if len(roots) != 1:
        raise SourceBundleError(f"Source archive sem raiz única: {path.name}")
    return roots.pop(), members


def _verify_native_curl_recipe_correspondence(
    manifest: dict[str, Any], staging: Path
) -> None:
    """Verifica a closure 2.0.0 diretamente contra a receita CMake oficial."""
    native = manifest["correspondence"]["native_curl"]
    sources = {entry["component"]: entry for entry in manifest["source_archives"]}
    expected_entries = expected_staging_entries(manifest)
    recipe_entry = sources.get("curl-impersonate")
    if recipe_entry is None:
        raise SourceBundleError("Source curl-impersonate está ausente")
    recipe_path = staging / recipe_entry["staging_path"]
    recipe_root, recipe_members = _regular_archive_members(recipe_path)
    if recipe_root != "curl-impersonate-2.0.0":
        raise SourceBundleError("Raiz do source curl-impersonate diverge")
    try:
        with tarfile.open(recipe_path, "r:gz") as archive:
            cmake = _archive_member_bytes(
                archive, f"{recipe_root}/CMakeLists.txt"
            ).decode("utf-8")
    except (OSError, UnicodeError, tarfile.TarError) as error:
        raise SourceBundleError(
            "Receita CMake curl-impersonate está ilegível"
        ) from error

    recipe_specs = {
        "BoringSSL": (
            "BORINGSSL_COMMIT",
            "156c7b75ae9b8c3b3f847acf264f17594c3859fb",
            "BORINGSSL_URL_HASH",
        ),
        "Brotli native": ("BROTLI_VERSION", "1.2.0", "BROTLI_URL_HASH"),
        "nghttp2": ("NGHTTP2_VERSION", "1.63.0", "NGHTTP2_URL_HASH"),
        "nghttp3": ("NGHTTP3_VERSION", "1.15.0", "NGHTTP3_URL_HASH"),
        "ngtcp2": ("NGTCP2_VERSION", "1.20.0", "NGTCP2_URL_HASH"),
        "zlib": ("ZLIB_VERSION", "1.3.1", "ZLIB_URL_HASH"),
        "zstd": ("ZSTD_VERSION", "1.5.7", "ZSTD_URL_HASH"),
    }
    root_overrides = {"Brotli native": "brotli-1.2.0"}
    for parent in native["parents"]:
        component = parent["component"]
        source = sources.get(component)
        if source is None or parent["source_staging_path"] not in expected_entries:
            raise SourceBundleError(
                f"Parent curl não pertence ao manifesto: {component}"
            )
        if any(
            source[field] != parent[field] for field in ("filename", "sha256", "size")
        ):
            raise SourceBundleError(
                f"Parent curl diverge do source archive: {component}"
            )
        version_var, version, hash_var = recipe_specs[component]
        if (
            f'set({version_var} "{version}")' not in cmake
            or f'set({hash_var} "SHA256={parent["sha256"].casefold()}")' not in cmake
        ):
            raise SourceBundleError(f"Pin CMake diverge no parent: {component}")
        root, members = _regular_archive_members(
            staging / parent["source_staging_path"]
        )
        expected_root = root_overrides.get(component)
        if expected_root is None:
            expected_root = parent["filename"]
            for suffix in (".tar.bz2", ".tar.gz", ".zip"):
                expected_root = expected_root.removesuffix(suffix)
        if (
            root != expected_root
            or len(members) != parent["expected_archive_file_count"]
        ):
            raise SourceBundleError(f"Conteúdo do parent curl diverge: {component}")
        for license_path in parent["license_files"]:
            if f"{root}/{license_path}" not in members:
                raise SourceBundleError(f"Licença do parent curl ausente: {component}")

    curl_source = sources.get("curl")
    if curl_source is None:
        raise SourceBundleError("Source curl está ausente")
    if (
        'set(CURL_VERSION "curl-8_21_0")' not in cmake
        or f'set(CURL_URL_HASH "SHA256={curl_source["sha256"].casefold()}")'
        not in cmake
        or "set(_use_libidn2_default OFF)" not in cmake
    ):
        raise SourceBundleError("Pin CMake do curl/WinIDN diverge")
    curl_root, curl_members = _regular_archive_members(
        staging / curl_source["staging_path"]
    )
    if curl_root != "curl-curl-8_21_0" or f"{curl_root}/COPYING" not in curl_members:
        raise SourceBundleError("Source/licença curl diverge")

    expected_patch_paths = {
        f"{recipe_root}/{patch['path']}" for patch in native["patches"]
    }
    if not expected_patch_paths.issubset(recipe_members):
        raise SourceBundleError("Receita curl-impersonate não contém todos os patches")
    with tarfile.open(recipe_path, "r:gz") as archive:
        for patch in native["patches"]:
            content = _archive_member_bytes(archive, f"{recipe_root}/{patch['path']}")
            if (
                len(content) != patch["size"]
                or sha256_bytes(content) != patch["sha256"]
            ):
                raise SourceBundleError(f"Patch preservado diverge: {patch['path']}")
            try:
                patch_text = content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise SourceBundleError(
                    f"Patch preservado não está em UTF-8: {patch['path']}"
                ) from error
            if "diff --git " not in patch_text or "\nindex " not in patch_text:
                raise SourceBundleError(
                    f"Estrutura do patch preservado diverge: {patch['path']}"
                )
    sfparse = native["sfparse"]
    if sfparse["status"] == "covered-by-parent":
        nghttp3 = next(
            item for item in native["parents"] if item["component"] == "nghttp3"
        )
        verify_sfparse_coverage(staging / nghttp3["source_staging_path"], sfparse)


def _patch_preimages(content: bytes) -> list[tuple[str, str]]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise SourceBundleError("Patch preservado não está em UTF-8") from error
    records: list[tuple[str, str]] = []
    old_path: str | None = None
    for line in lines:
        match = re.fullmatch(r"diff --git a/(.+) b/(.+)", line)
        if match:
            old_path = match.group(1)
            continue
        match = re.fullmatch(r"index ([0-9a-f]+)\.\.([0-9a-f]+)(?: [0-7]+)?", line)
        if match:
            if old_path is None:
                raise SourceBundleError("Patch possui index sem path")
            records.append((old_path, match.group(1)))
    if not records:
        raise SourceBundleError("Patch preservado não contém preimages")
    return records


def verify_native_curl_correspondence(manifest: dict[str, Any], staging: Path) -> None:
    """Verifica offline os parents, sfparse e patches da closure curl nativa."""
    native = manifest["correspondence"]["native_curl"]
    if native.get("status") != "verified" or "parents" not in native:
        return
    if any(
        parent["archive_strategy"] == "official_recipe_hash"
        for parent in native["parents"]
    ):
        _verify_native_curl_recipe_correspondence(manifest, staging)
        return
    expected_entries = expected_staging_entries(manifest)
    source_entries = {
        entry["staging_path"]: entry for entry in manifest["source_archives"]
    }
    tree_by_component: dict[str, dict[str, Any]] = {}
    for parent in native["parents"]:
        source_path = parent["source_staging_path"]
        if source_path not in expected_entries or source_path not in source_entries:
            raise SourceBundleError(
                f"Parent curl não pertence ao manifesto: {parent['component']}"
            )
        source_entry = source_entries[source_path]
        if (
            source_entry["filename"] != parent["filename"]
            or source_entry["sha256"] != parent["sha256"]
            or source_entry["size"] != parent["size"]
        ):
            raise SourceBundleError(
                f"Parent curl diverge do source archive: {parent['component']}"
            )
        for metadata_path in parent["metadata"].values():
            if metadata_path not in expected_entries:
                raise SourceBundleError(
                    f"Metadata do parent não pertence ao manifesto: {metadata_path}"
                )
        commit = _load_staged_json(
            staging, parent["metadata"]["commit"], label=parent["component"]
        )
        tree = _load_staged_json(
            staging, parent["metadata"]["tree"], label=parent["component"]
        )
        if (
            commit.get("sha") != parent["revision"]
            or commit.get("tree", {}).get("sha") != parent["tree"]
            or tree.get("sha") != parent["tree"]
        ):
            raise SourceBundleError(
                f"Revisão Git divergente no parent: {parent['component']}"
            )
        tree_by_component[parent["component"]] = tree
        archive_path = staging / source_path
        if parent["archive_strategy"] == "official_release_asset":
            tag_ref = _load_staged_json(
                staging,
                parent["metadata"]["tag_ref"],
                label=f"tag ref {parent['component']}",
            )
            tag_object = _load_staged_json(
                staging,
                parent["metadata"]["tag_object"],
                label=f"tag object {parent['component']}",
            )
            release = _load_staged_json(
                staging,
                parent["metadata"]["release"],
                label=f"release {parent['component']}",
            )
            if (
                tag_ref.get("object", {}).get("sha") != tag_object.get("sha")
                or tag_object.get("object", {}).get("sha") != parent["revision"]
                or release.get("tag_name") != parent["tag"]
            ):
                raise SourceBundleError(
                    f"Tag/release divergente no parent: {parent['component']}"
                )
            assets = release.get("assets")
            if not isinstance(assets, list):
                raise SourceBundleError("Release oficial não contém assets")
            matching_assets = [
                asset
                for asset in assets
                if isinstance(asset, dict) and asset.get("name") == parent["filename"]
            ]
            if (
                len(matching_assets) != 1
                or matching_assets[0].get("size") != parent["size"]
            ):
                raise SourceBundleError(
                    f"Asset oficial divergente no parent: {parent['component']}"
                )
            digest = matching_assets[0].get("digest")
            if digest not in {None, f"sha256:{parent['sha256'].casefold()}"}:
                raise SourceBundleError(
                    f"Digest oficial divergente no parent: {parent['component']}"
                )
            try:
                checksums = (staging / parent["metadata"]["checksums"]).read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeError) as error:
                raise SourceBundleError("Checksums oficiais ausentes") from error
            if (
                parent["sha256"].casefold() not in checksums.casefold()
                or parent["filename"] not in checksums
            ):
                raise SourceBundleError(
                    f"Checksum oficial divergente no parent: {parent['component']}"
                )
            root, blobs = archive_git_blobs(archive_path)
            expected_root = parent["filename"].removesuffix(".tar.bz2")
            if (
                root != expected_root
                or len(blobs) != parent["expected_archive_file_count"]
            ):
                raise SourceBundleError(
                    f"Conteúdo do release archive diverge: {parent['component']}"
                )
        else:
            expected_root = parent["filename"].removesuffix(".tar.gz")
            verify_commit_snapshot_archive(
                archive_path,
                tree,
                expected_root=expected_root,
                strategy=parent["archive_strategy"],
                expected_file_count=parent["expected_archive_file_count"],
            )
    sfparse = native["sfparse"]
    if sfparse["status"] == "covered-by-parent":
        nghttp3 = next(
            item for item in native["parents"] if item["component"] == "nghttp3"
        )
        verify_sfparse_coverage(staging / nghttp3["source_staging_path"], sfparse)
    elif sfparse.get("separate_source_staging_path") not in source_entries:
        raise SourceBundleError("Source sfparse separado está ausente")
    curl_tree = _load_staged_json(
        staging, native["curl_tree_metadata_path"], label="curl patch tree"
    )
    tree_by_component["curl"] = curl_tree
    tree_blobs = {
        component: {
            entry.get("path"): entry.get("sha")
            for entry in tree.get("tree", [])
            if isinstance(entry, dict) and entry.get("type") == "blob"
        }
        for component, tree in tree_by_component.items()
    }
    curl_impersonate = next(
        entry
        for entry in manifest["source_archives"]
        if entry["component"] == "curl-impersonate"
    )
    allowed_exceptions = {
        (
            exception["patch_path"],
            exception["component"],
            exception["path"],
            exception["patch_blob_prefix"],
            exception["tree_blob"],
        )
        for patch in native["patches"]
        for exception in patch.get("allowed_preimage_mismatches", [])
    }
    observed_exceptions: set[tuple[str, str, str, str, str]] = set()
    try:
        with tarfile.open(
            staging / curl_impersonate["staging_path"], "r:gz"
        ) as archive:
            for patch in native["patches"]:
                member_name = f"curl-impersonate-1.5.2/{patch['path']}"
                content = _archive_member_bytes(archive, member_name)
                if (
                    len(content) != patch["size"]
                    or sha256_bytes(content) != patch["sha256"]
                ):
                    raise SourceBundleError(
                        f"Patch preservado diverge: {patch['path']}"
                    )
                verified = 0
                new_files = 0
                for old_path, old_blob in _patch_preimages(content):
                    if set(old_blob) == {"0"}:
                        new_files += 1
                        continue
                    if patch["path"] == "win/deps.patch":
                        match = re.fullmatch(r"deps/(curl|zstd)/(.+)", old_path)
                        if not match:
                            raise SourceBundleError(
                                "win/deps.patch possui target inesperado"
                            )
                        component, relative = match.groups()
                    else:
                        component = patch["target_components"][0]
                        relative = old_path
                    actual_blob = tree_blobs.get(component, {}).get(relative)
                    if actual_blob and actual_blob.startswith(old_blob):
                        verified += 1
                        continue
                    exception = (
                        patch["path"],
                        component,
                        relative,
                        old_blob,
                        actual_blob,
                    )
                    if exception not in allowed_exceptions:
                        raise SourceBundleError(
                            f"Preimage de patch divergente: {patch['path']}"
                        )
                    observed_exceptions.add(exception)
                if (
                    verified != patch["expected_verified_preimages"]
                    or new_files != patch["expected_new_files"]
                ):
                    raise SourceBundleError(
                        f"Cobertura de patch divergente: {patch['path']}"
                    )
    except (OSError, tarfile.TarError) as error:
        raise SourceBundleError("Source curl-impersonate está ilegível") from error
    if observed_exceptions != allowed_exceptions:
        raise SourceBundleError("Exceções de preimage de patch divergiram")


def _normalized_python_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def verify_python_p2_correspondence(manifest: dict[str, Any], staging: Path) -> None:
    """Confirma sdists P2 contra metadata, locks e membros materiais."""
    python_p2 = manifest["correspondence"]["python_p2"]
    if python_p2.get("status") != "verified":
        return
    expected_entries = expected_staging_entries(manifest)
    sources_by_component = {
        entry["component"]: entry for entry in manifest["source_archives"]
    }
    archive_members_by_package: dict[str, set[str]] = {}
    for package in python_p2["packages"]:
        component = package["component"]
        source_entry = sources_by_component.get(component)
        if source_entry is None:
            raise SourceBundleError(f"Source Python P2 ausente: {component}")
        if (
            source_entry["filename"] != package["source_filename"]
            or source_entry["staging_path"] != package["source_staging_path"]
            or source_entry["sha256"] != package["source_sha256"]
            or source_entry["size"] != package["source_size"]
            or source_entry["version"] != package["version"]
        ):
            raise SourceBundleError(f"Source Python P2 divergente: {component}")
        if package["source_sha256"] != package["lock_hash"]:
            raise SourceBundleError(f"Hash do lock Python P2 diverge: {component}")
        metadata_path = package["metadata_staging_path"]
        lock_path = package["lock_path"]
        if metadata_path not in expected_entries or lock_path not in expected_entries:
            raise SourceBundleError(
                f"Metadata/lock Python P2 não pertence ao manifesto: {component}"
            )
        metadata = _load_staged_json(staging, metadata_path, label=component)
        info = metadata.get("info")
        if not isinstance(info, dict) or (
            _normalized_python_package_name(str(info.get("name", "")))
            != _normalized_python_package_name(package["package"])
            or info.get("version") != package["version"]
        ):
            raise SourceBundleError(f"Identidade PyPI divergente: {component}")
        urls = metadata.get("urls")
        if not isinstance(urls, list):
            raise SourceBundleError(f"Metadata PyPI sem arquivos: {component}")
        matching_sdists = [
            entry
            for entry in urls
            if isinstance(entry, dict)
            and entry.get("packagetype") == "sdist"
            and entry.get("filename") == package["source_filename"]
        ]
        if len(matching_sdists) != 1:
            raise SourceBundleError(f"sdist PyPI não é único: {component}")
        sdist = matching_sdists[0]
        digests = sdist.get("digests")
        if (
            not isinstance(digests, dict)
            or str(digests.get("sha256", "")).upper() != package["source_sha256"]
            or sdist.get("size") != package["source_size"]
            or sdist.get("url") != source_entry["origin"]
        ):
            raise SourceBundleError(f"Proveniência PyPI divergente: {component}")
        try:
            lock = (staging / lock_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise SourceBundleError(f"Lock Python P2 ilegível: {component}") from error
        requirement = re.compile(
            rf"(?m)^{re.escape(package['package'])}=={re.escape(package['version'])}"
            rf"(?:\s|;|\\)"
        )
        if not requirement.search(lock) or (
            f"--hash=sha256:{package['lock_hash'].casefold()}" not in lock.casefold()
        ):
            raise SourceBundleError(f"Lock Python P2 divergente: {component}")
        try:
            with tarfile.open(
                staging / package["source_staging_path"], "r:gz"
            ) as archive:
                regular_members = {member.name for member in archive if member.isfile()}
        except (OSError, tarfile.TarError) as error:
            raise SourceBundleError(f"sdist Python P2 ilegível: {component}") from error
        roots = {PurePosixPath(name).parts[0] for name in regular_members}
        if roots != {package["archive_root"]}:
            raise SourceBundleError(f"Raiz do sdist Python P2 diverge: {component}")
        required_members = {
            f"{package['archive_root']}/{relative}"
            for relative in (
                package["required_archive_members"] + package["license_files"]
            )
        }
        missing_members = sorted(required_members - regular_members)
        if missing_members:
            raise SourceBundleError(
                f"Membro material Python P2 ausente: {missing_members[0]}"
            )
        archive_members_by_package[package["package"]] = regular_members
    vendors = python_p2["vendors"]
    setuptools = archive_members_by_package.get("setuptools")
    if vendors and setuptools is None:
        raise SourceBundleError("Source setuptools P2 ausente")
    setuptools_root = next(
        (
            package["archive_root"]
            for package in python_p2["packages"]
            if package["package"] == "setuptools"
        ),
        "",
    )
    for vendor in vendors:
        prefix = f"{setuptools_root}/{vendor['source_path_prefix']}"
        if not any(path.startswith(prefix) for path in setuptools):
            raise SourceBundleError(
                f"Vendor setuptools ausente: {vendor['material_name']}"
            )
        for relative in vendor["license_paths"]:
            if f"{setuptools_root}/{relative}" not in setuptools:
                raise SourceBundleError(
                    f"Licença de vendor setuptools ausente: {vendor['material_name']}"
                )


def _metadata_collection_inventory(
    staging: Path, collection: dict[str, Any]
) -> list[dict[str, Any]]:
    root = staging / collection["staging_root"]
    if not root.is_dir():
        raise SourceBundleError("Coleção de metadata ausente")
    inventory: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SourceBundleError("Coleção de metadata não aceita links simbólicos")
        if not path.is_file():
            continue
        relative = path.relative_to(staging).as_posix()
        _validate_relative_path(relative, field="metadata_collection.relative_path")
        inventory.append(
            {
                "relative_path": relative,
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    if len(inventory) != collection["file_count"]:
        raise SourceBundleError("Quantidade da coleção de metadata diverge")
    if sha256_bytes(canonical_json_bytes(inventory)) != collection["inventory_sha256"]:
        raise SourceBundleError("Inventário da coleção de metadata diverge")
    return inventory


def _load_staging_json(staging: Path, relative: str, *, label: str) -> Any:
    try:
        return json.loads((staging / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SourceBundleError(f"Metadata {label} ausente ou inválida") from error


def verify_cpython_external_archive(pin: dict[str, Any], staging: Path) -> None:
    """Compara um ZIP source-deps preservado com a tree Git oficial fixada."""
    component = pin["component"]
    identity = OFFICIAL_CPYTHON_EXTERNAL_ARCHIVES[component]
    archive_path = staging / pin["source_staging_path"]
    if (
        not archive_path.is_file()
        or archive_path.stat().st_size != pin["source_size"]
        or sha256_file(archive_path) != pin["source_sha256"]
    ):
        raise SourceBundleError(f"Archive externo CPython diverge: {component}")
    tree = _load_staging_json(
        staging,
        pin["tree_metadata_path"],
        label=f"tree source-deps {pin['source_tag']}",
    )
    if tree.get("sha") != pin["source_tree"] or tree.get("truncated") is not False:
        raise SourceBundleError(f"Tree externo CPython diverge: {component}")
    if any(item.get("type") == "commit" for item in tree.get("tree", [])):
        raise SourceBundleError(f"External CPython contém submodule: {component}")
    git_blobs = {
        item["path"]: item["sha"]
        for item in tree.get("tree", [])
        if item.get("type") == "blob"
    }
    selected: dict[str, bytes] = {}
    direct_matches = 0
    normalized_matches = 0
    archive_paths: set[str] = set()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                pure = PurePosixPath(member.filename)
                if (
                    not pure.parts
                    or pure.parts[0] != pin["archive_root"]
                    or ".." in pure.parts
                ):
                    raise SourceBundleError(
                        f"Archive externo CPython contém path inseguro: {component}"
                    )
                relative = PurePosixPath(*pure.parts[1:]).as_posix()
                content = archive.read(member)
                archive_paths.add(relative)
                if (
                    relative in identity["required_fragments"]
                    or relative in (pin["license_references"])
                ):
                    selected[relative] = content
                expected_blob = git_blobs.get(relative)
                if expected_blob is None:
                    raise SourceBundleError(
                        f"Archive externo CPython possui arquivo fora da tree: "
                        f"{component}"
                    )
                if git_blob_sha1(content) == expected_blob:
                    direct_matches += 1
                elif git_blob_sha1(content.replace(b"\r\n", b"\n")) == expected_blob:
                    normalized_matches += 1
                else:
                    raise SourceBundleError(
                        f"Source externo CPython diverge da tree: {component}"
                    )
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise SourceBundleError(
            f"Archive externo CPython ausente ou inválido: {component}"
        ) from error
    if archive_paths != set(git_blobs):
        raise SourceBundleError(f"Archive externo CPython está incompleto: {component}")
    observed = {
        "archive_blob_count": len(archive_paths),
        "archive_direct_matches": direct_matches,
        "archive_eol_normalized_matches": normalized_matches,
    }
    if any(pin[field] != value for field, value in observed.items()):
        raise SourceBundleError(
            f"Composição do archive externo CPython diverge: {component}"
        )
    required_paths = set(identity["required_fragments"]) | set(
        pin["license_references"]
    )
    if set(selected) != required_paths:
        raise SourceBundleError(f"Licença ou versão externa ausente: {component}")
    for relative, fragments in identity["required_fragments"].items():
        if any(fragment not in selected[relative] for fragment in fragments):
            raise SourceBundleError(f"Versão ou licença externa diverge: {component}")


def verify_cpython_runtime_correspondence(
    manifest: dict[str, Any], staging: Path
) -> None:
    """Verifica source CPython, tag/tree, Sigstore, pins e toolcache sem rede."""
    cpython = manifest["correspondence"]["cpython_runtime"]
    if cpython.get("status") != "verified":
        return
    archive_spec = cpython["archive"]
    archive_path = staging / archive_spec["staging_path"]
    required_members = {
        "Include/patchlevel.h",
        "LICENSE",
        "Modules/_decimal/libmpdec/mpdecimal.h",
        "Modules/expat/COPYING",
        "Modules/expat/expat.h",
        "PCbuild/get_external.py",
        "PCbuild/get_externals.bat",
        "PCbuild/python.props",
        "PCbuild/readme.txt",
    }
    selected: dict[str, bytes] = {}
    direct_matches = 0
    normalized_matches = 0
    common_blobs = 0
    archive_only: set[str] = set()
    tree = _load_staging_json(
        staging, archive_spec["tree_metadata_path"], label="tree CPython"
    )
    if tree.get("sha") != archive_spec["tree"] or tree.get("truncated") is not False:
        raise SourceBundleError("Tree CPython oficial diverge")
    git_blobs = {
        item["path"]: item["sha"]
        for item in tree.get("tree", [])
        if item.get("type") == "blob"
    }
    regular_files = 0
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                regular_files += 1
                pure = PurePosixPath(member.name)
                if (
                    not pure.parts
                    or pure.parts[0] != archive_spec["archive_root"]
                    or ".." in pure.parts
                ):
                    raise SourceBundleError("Archive CPython contém path inseguro")
                relative = PurePosixPath(*pure.parts[1:]).as_posix()
                stream = archive.extractfile(member)
                if stream is None:
                    raise SourceBundleError("Archive CPython contém membro ilegível")
                content = stream.read()
                if relative in required_members:
                    selected[relative] = content
                expected_blob = git_blobs.get(relative)
                if expected_blob is None:
                    archive_only.add(relative)
                else:
                    common_blobs += 1
                    if git_blob_sha1(content) == expected_blob:
                        direct_matches += 1
                    elif git_blob_sha1(content.replace(b"\r\n", b"\n")) == (
                        expected_blob
                    ):
                        normalized_matches += 1
                    else:
                        raise SourceBundleError(
                            f"Source CPython diverge da tag em {relative}"
                        )
    except (OSError, tarfile.TarError) as error:
        raise SourceBundleError("Archive CPython ausente ou inválido") from error
    if set(selected) != required_members:
        raise SourceBundleError("Archive CPython não cobre os membros obrigatórios")
    observed = {
        "archive_git_common_blobs": common_blobs,
        "archive_git_direct_matches": direct_matches,
        "archive_git_eol_normalized_matches": normalized_matches,
        "archive_only_members": sorted(archive_only),
        "expected_file_count": regular_files,
    }
    if any(archive_spec[field] != value for field, value in observed.items()):
        raise SourceBundleError("Composição do archive CPython diverge")
    required_fragments = {
        "Include/patchlevel.h": [
            b"PY_MICRO_VERSION        11",
            b'PY_VERSION              "3.10.11"',
        ],
        "Modules/_decimal/libmpdec/mpdecimal.h": [b'#define MPD_VERSION "2.5.1"'],
        "Modules/expat/expat.h": [
            b"XML_MAJOR_VERSION 2",
            b"XML_MINOR_VERSION 5",
            b"XML_MICRO_VERSION 0",
        ],
        "PCbuild/python.props": [
            b"bzip2-1.0.8",
            b"libffi-3.3.0",
            b"openssl-1.1.1t",
            b"sqlite-3.40.1.0",
            b"xz-5.2.5",
            b"zlib-1.2.13",
        ],
    }
    for member, fragments in required_fragments.items():
        if any(fragment not in selected[member] for fragment in fragments):
            raise SourceBundleError(f"Identidade CPython divergente em {member}")
    if b"Permission is hereby granted" not in selected["Modules/expat/COPYING"]:
        raise SourceBundleError("Licença Expat ausente do parent CPython")
    if (
        b"Redistribution and use in source and binary forms"
        not in selected["Modules/_decimal/libmpdec/mpdecimal.h"]
    ):
        raise SourceBundleError("Licença mpdecimal ausente do parent CPython")
    if sha256_file(archive_path) != archive_spec["sha256"]:
        raise SourceBundleError("SHA-256 do source CPython diverge")
    sigstore = _load_staging_json(
        staging, archive_spec["sigstore_metadata_path"], label="Sigstore CPython"
    )
    try:
        digest = sigstore["messageSignature"]["messageDigest"]
        decoded_digest = base64.b64decode(digest["digest"], validate=True).hex().upper()
    except (KeyError, TypeError, ValueError) as error:
        raise SourceBundleError("Bundle Sigstore CPython é inválido") from error
    if (
        digest.get("algorithm") != "SHA2_256"
        or digest["digest"] != archive_spec["sigstore_digest_base64"]
        or decoded_digest != archive_spec["sha256"]
    ):
        raise SourceBundleError("Digest Sigstore CPython diverge")
    tag_ref = _load_staging_json(
        staging, archive_spec["tag_ref_metadata_path"], label="tag ref CPython"
    )
    tag_object = _load_staging_json(
        staging, archive_spec["tag_object_metadata_path"], label="tag CPython"
    )
    commit = _load_staging_json(
        staging, archive_spec["commit_metadata_path"], label="commit CPython"
    )
    if (
        tag_ref.get("object", {}).get("sha") != archive_spec["tag_object"]
        or tag_object.get("object", {}).get("sha") != archive_spec["commit"]
        or commit.get("tree", {}).get("sha") != archive_spec["tree"]
    ):
        raise SourceBundleError("Tag, commit ou tree CPython diverge")
    for pin in cpython["external_pins"]:
        tag = pin["source_tag"]
        prefix = cpython["metadata_collection_root"]
        ref = _load_staging_json(
            staging,
            f"{prefix}/cpython-source-deps-{tag}.tag-ref.json",
            label=f"source-deps {tag}",
        )
        pin_commit = _load_staging_json(
            staging,
            f"{prefix}/cpython-source-deps-{tag}.commit.json",
            label=f"commit source-deps {tag}",
        )
        if (
            ref.get("object", {}).get("sha") != pin["source_commit"]
            or pin_commit.get("tree", {}).get("sha") != pin["source_tree"]
        ):
            raise SourceBundleError(f"Pin source-deps diverge: {pin['component']}")
        binary_pin = pin.get("binary_pin")
        if binary_pin is not None:
            binary_tag = binary_pin["tag"]
            binary_ref = _load_staging_json(
                staging,
                f"{prefix}/cpython-bin-deps-{binary_tag}.tag-ref.json",
                label=f"bin-deps {binary_tag}",
            )
            binary_commit = _load_staging_json(
                staging,
                f"{prefix}/cpython-bin-deps-{binary_tag}.commit.json",
                label=f"commit bin-deps {binary_tag}",
            )
            if (
                binary_ref.get("object", {}).get("sha") != binary_pin["commit"]
                or binary_commit.get("tree", {}).get("sha") != binary_pin["tree"]
            ):
                raise SourceBundleError(f"Pin bin-deps diverge: {pin['component']}")
        verify_cpython_external_archive(pin, staging)
    setup = cpython["setup_python"]
    manifest_data = _load_staging_json(
        staging, setup["manifest_metadata_path"], label="manifest python-versions"
    )
    release = next(
        (item for item in manifest_data if item.get("version") == "3.10.11"), None
    )
    if release is None or release.get("release_url") != setup["toolcache_release_url"]:
        raise SourceBundleError("Release toolcache CPython diverge")
    package = next(
        (
            item
            for item in release.get("files", [])
            if item.get("platform") == "win32" and item.get("arch") == "x64"
        ),
        None,
    )
    if package is None or package.get("filename") != setup["toolcache_filename"]:
        raise SourceBundleError("Pacote toolcache Windows x64 diverge")
    try:
        checksums = (staging / setup["checksums_metadata_path"]).read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError) as error:
        raise SourceBundleError("Checksums toolcache ausentes") from error
    expected_line = f"{setup['toolcache_sha256']} {setup['toolcache_filename']}"
    if expected_line not in checksums.splitlines():
        raise SourceBundleError("SHA-256 toolcache CPython diverge")


def verify_staging(manifest: dict[str, Any], staging: Path) -> list[dict[str, Any]]:
    """Falha se faltar, sobrar ou divergir qualquer arquivo do staging."""
    if not staging.is_dir():
        raise SourceBundleError("Diretório de staging ausente")
    expected = expected_staging_entries(manifest)
    actual: dict[str, Path] = {}
    for path in staging.rglob("*"):
        if path.is_symlink():
            raise SourceBundleError("Staging não aceita links simbólicos")
        if not path.is_file():
            continue
        relative = path.relative_to(staging).as_posix()
        if relative == manifest["source_bundle"]["bundle_filename"]:
            continue
        actual[relative] = path
    collection_inventory: list[dict[str, Any]] = []
    for collection in manifest["metadata_collections"]:
        collection_inventory.extend(_metadata_collection_inventory(staging, collection))
    collection_paths = {entry["relative_path"] for entry in collection_inventory}
    if collection_paths & set(expected):
        raise SourceBundleError("Coleção de metadata sobrepõe arquivo explícito")
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected) - collection_paths)
    if missing:
        raise SourceBundleError(f"Arquivo oficial necessário ausente: {missing[0]}")
    if unexpected:
        raise SourceBundleError(f"Arquivo inesperado no staging: {unexpected[0]}")
    inventory: list[dict[str, Any]] = []
    for relative in sorted(expected):
        entry = expected[relative]
        path = actual[relative]
        if path.stat().st_size != entry["size"]:
            raise SourceBundleError(f"Tamanho divergente: {relative}")
        digest = sha256_file(path)
        if digest != entry["sha256"]:
            raise SourceBundleError(f"SHA-256 divergente: {relative}")
        inventory.append(
            {"relative_path": relative, "sha256": digest, "size": entry["size"]}
        )
    inventory.extend(collection_inventory)
    inventory.sort(key=lambda item: item["relative_path"])
    verify_certifi_correspondence(manifest, staging)
    verify_native_curl_correspondence(manifest, staging)
    verify_python_p2_correspondence(manifest, staging)
    verify_cpython_runtime_correspondence(manifest, staging)
    return inventory


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _inventory_document(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "entries": entries,
        "inventory_sha256": sha256_bytes(canonical_json_bytes(entries)),
        "schema_version": 1,
    }


def assemble_bundle(
    manifest_path: Path,
    staging: Path,
    output: Path,
    *,
    enforce_official_baseline: bool = True,
) -> dict[str, Any]:
    """Monta ZIP determinístico usando somente staging previamente verificado."""
    manifest = load_manifest(
        manifest_path, enforce_official_baseline=enforce_official_baseline
    )
    verified = verify_staging(manifest, staging)
    bundle_entries = [
        {
            **entry,
            "relative_path": f"{BUNDLE_ROOT}/{entry['relative_path']}",
        }
        for entry in verified
    ]
    manifest_bytes = formatted_json_bytes(manifest)
    bundle_entries.append(
        {
            "relative_path": f"{BUNDLE_ROOT}/SOURCE_PROVENANCE.json",
            "sha256": sha256_bytes(manifest_bytes),
            "size": len(manifest_bytes),
        }
    )
    bundle_entries.sort(key=lambda item: item["relative_path"])
    inventory = _inventory_document(bundle_entries)
    inventory_bytes = formatted_json_bytes(inventory)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for entry in bundle_entries:
                name = entry["relative_path"]
                if name.endswith("/SOURCE_PROVENANCE.json"):
                    content = manifest_bytes
                else:
                    staging_relative = name.removeprefix(f"{BUNDLE_ROOT}/")
                    content = (staging / staging_relative).read_bytes()
                archive.writestr(_zip_info(name), content, compresslevel=9)
            archive.writestr(
                _zip_info(f"{BUNDLE_ROOT}/SOURCE-BUNDLE-INVENTORY.json"),
                inventory_bytes,
                compresslevel=9,
            )
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return verify_bundle(
        manifest_path,
        output,
        enforce_official_baseline=enforce_official_baseline,
    )


def verify_bundle(
    manifest_path: Path,
    bundle: Path,
    *,
    enforce_official_baseline: bool = True,
) -> dict[str, Any]:
    """Reabre o ZIP e valida manifesto, inventário, root hash e composição."""
    manifest = load_manifest(
        manifest_path, enforce_official_baseline=enforce_official_baseline
    )
    expected_manifest = formatted_json_bytes(manifest)
    inventory_name = f"{BUNDLE_ROOT}/SOURCE-BUNDLE-INVENTORY.json"
    manifest_name = f"{BUNDLE_ROOT}/SOURCE_PROVENANCE.json"
    try:
        with zipfile.ZipFile(bundle, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise SourceBundleError("Bundle contém caminhos duplicados")
            for name in names:
                _validate_relative_path(name, field="bundle.relative_path")
            if inventory_name not in names or manifest_name not in names:
                raise SourceBundleError("Bundle não contém manifesto e inventário")
            if archive.read(manifest_name) != expected_manifest:
                raise SourceBundleError("Manifesto interno do bundle diverge")
            inventory = json.loads(archive.read(inventory_name).decode("utf-8"))
            entries = inventory.get("entries")
            if not isinstance(entries, list):
                raise SourceBundleError("Inventário interno inválido")
            expected_names = {entry["relative_path"] for entry in entries}
            if set(names) != expected_names | {inventory_name}:
                raise SourceBundleError("Composição do ZIP diverge do inventário")
            recomputed: list[dict[str, Any]] = []
            for entry in sorted(entries, key=lambda item: item["relative_path"]):
                name = _validate_relative_path(
                    entry.get("relative_path"), field="inventory.relative_path"
                )
                content = archive.read(name)
                recomputed.append(
                    {
                        "relative_path": name,
                        "sha256": sha256_bytes(content),
                        "size": len(content),
                    }
                )
    except (OSError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as error:
        raise SourceBundleError("Bundle ausente, ilegível ou inválido") from error
    if recomputed != entries:
        raise SourceBundleError("Conteúdo do bundle diverge do inventário")
    root_hash = sha256_bytes(canonical_json_bytes(entries))
    if inventory.get("inventory_sha256") != root_hash:
        raise SourceBundleError("Hash raiz do inventário diverge")
    return {
        "bundle_sha256": sha256_file(bundle),
        "bundle_size": bundle.stat().st_size,
        "file_count": len(entries) + 1,
        "inventory_sha256": root_hash,
    }


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_staging_parser = subparsers.add_parser("verify-staging")
    verify_staging_parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    assemble_parser.add_argument("--output", type=Path, default=DEFAULT_BUNDLE)
    verify_bundle_parser = subparsers.add_parser("verify-bundle")
    verify_bundle_parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Executa somente verificações/montagem offline; nunca realiza downloads."""
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "verify-staging":
            manifest = load_manifest(args.manifest)
            inventory = verify_staging(manifest, args.staging)
            result = {
                "file_count": len(inventory),
                "inventory_sha256": sha256_bytes(canonical_json_bytes(inventory)),
                "status": "verified",
            }
        elif args.command == "assemble":
            result = assemble_bundle(args.manifest, args.staging, args.output)
            result["bundle_path"] = _display_path(args.output)
        else:
            result = verify_bundle(args.manifest, args.bundle)
            result["bundle_path"] = _display_path(args.bundle)
    except SourceBundleError as error:
        print(f"source_bundle_invalid: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
