"""Valida e monta a closure de source do runtime CPython 3.14.6 congelado."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_MANIFEST = Path("docs/compliance/python/CPYTHON_RUNTIME_SOURCE_PROVENANCE.json")
DEFAULT_STAGING = Path("build-compliance-python-runtime/staging")
DEFAULT_BUNDLE = Path(
    "build-compliance-python-runtime/bundles/"
    "EduDownloader-ThirdParty-Source-CPython-3.14.6-COMPLETE.zip"
)
DEFAULT_FROZEN_MANIFEST = Path(
    "docs/compliance/build/FROZEN_CANDIDATE_COMPOSITION.json"
)
DEFAULT_FROZEN_CANDIDATE = Path(
    "build-community-candidate-0.9.5/dist/EduDownloader-Portable"
)
BUNDLE_ROOT = "EduDownloader-ThirdParty-Source-CPython-3.14.6"
OFFICIAL_COMPONENT = "CPython frozen runtime source closure"
OFFICIAL_MANIFEST_SHA256 = (
    "C091D37CB18D757282BE240A02370565A94673968A32C7AF4CAB66A974F2BC72"
)

OFFICIAL_CANDIDATE = {
    "classification": "INTERNAL_ANALYSIS_CANDIDATE",
    "file_count": 1068,
    "inventory_sha256": (
        "26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857"
    ),
    "source_commit": "621a72b8c3329dc68abc0c581ec152d6c3bd9e08",
    "total_size_bytes": 382_736_507,
}
OFFICIAL_GATES = {
    "activation_operational": True,
    "activation_required_for_current_edition": False,
    "app_version": "0.9.5",
    "default_trust_store_key_count": 1,
    "operational_private_key_configured": False,
    "operational_public_key_configured": True,
    "product_edition": "community",
    "production_crypto_configured": True,
    "production_ready": False,
    "public_release_allowed": False,
}
OFFICIAL_PARENT_IDENTITIES = {
    "bzip2": (
        "1.0.8",
        "REUSED_EXISTING_SOURCE",
        "12C17D15F99E27235529574A722FB484A4E8FDF2427CEF53B1B68BDF07E404A9",
        "05301997b2f9590f49c672cf3dfd3d3dfa7ad521",
        "933e65e88f0a28f9bcbc8abe5a4c12e3f618c043",
    ),
    "cpython": (
        "3.14.6",
        "PRESERVED_NEW",
        "143B1DDDEFAEC3BD2E21E3B839B34A2B7FB9842272883C576420D605E9F30C63",
        "c63aec69bd59c55314c06c23f4c22c03de76fe45",
        "ad415ee943062293d0032daad921a37a3b760410",
    ),
    "libffi": (
        "3.4.4",
        "PRESERVED_NEW",
        "9D802681ADFEA27D84CAE0487A785FB9CAA925BDAD44C401B364C59AB2B8EDDA",
        "73b247f34ef3ae1859b8c2c34d321d34ebc5db15",
        "dba0e3bd6143ae50d7017850345f7053775c6677",
    ),
    "mpdecimal": (
        "4.0.0",
        "PRESERVED_NEW",
        "338FAC3FB8CDD60F406B6326431338756F58A8AF94229FFD9BF1E7C2B1AD71CA",
        "48316ec025c1ebe500854c332be0a12c640c7301",
        "1ecd3b3fb74d2b6c93f384b553a6023a88e0de34",
    ),
    "openssl": (
        "3.5.7",
        "PRESERVED_NEW",
        "CA94E7C6C223D9CAF77BB51AAC5949186379608EA2A0CAD3AA8BDF31856912E9",
        "6a6901fa60c604816acb50b4e167791e5339c8f8",
        "4f5b47534bc1016b89e70bd6dc27382670adcee5",
    ),
    "tcl": (
        "8.6.15.0",
        "PRESERVED_NEW",
        "4C23F0DD3EFCBE6F3A22C503A68D147617BB30C4F5290F1EB3EAACF0B460440B",
        "275286594fd3e162af29e8c0ba4e365d3d1f7775",
        "85bd8c2c9b2f8db34f56d08efdb3f65dd909b7c3",
    ),
    "tk": (
        "8.6.15.0",
        "PRESERVED_NEW",
        "0AE56D39BCA92865F338529557A1E56D110594184B6DC5A91339C5675751E264",
        "a526badcf885e4986e13e68695398a0bb64d5ea1",
        "642dd68515c70ff138bc867919304f0936cf3fe9",
    ),
    "xz": (
        "5.2.5",
        "REUSED_EXISTING_SOURCE",
        "6A4389CC05143BEB2679B1299CECEE71B02BAA55E70F68A88B44DC01AD495424",
        "c6bc0c612605622aaef101a33a751f9de2ecc193",
        "2b8fb6a3c0b111c2175bec896b2a22448fd0ac4b",
    ),
    "zlib-ng": (
        "2.2.4",
        "PRESERVED_NEW",
        "00BBD88709BC416CB96160AB61D3E1C8F76E106799AF7328D0FE434DC7DD5004",
        "a502e047655c31db29601def76ad6539acacf43d",
        "897870eecd4dd0e8cc94db018ddb09bc01348671",
    ),
    "zstandard": (
        "1.5.7",
        "PRESERVED_NEW",
        "F24B52470D12F466E9FA4FCC94E6C530625ADA51D7B36DE7FDC6ED7E6F499C8E",
        "eef946ae8cf1591c0e5cc5f43486210768647c2e",
        "65df13bfb803791fd5d2073f3ce86a8743dd05ff",
    ),
}
OFFICIAL_BIN_DEPS = {
    "libffi-3.4.4": (
        "94cb9a1c7feb608adf2b9f8fe2dbd6925ffbf90d",
        "bf8087b61bea675a2d4ab393e25e017a9eea9734",
    ),
    "openssl-bin-3.5.7": (
        "3217be5a2a7e20dbc5f5b5160ef21a9c84de7138",
        "489fe20520999c58ed7f39d43bea3c482ec46cee",
    ),
    "tcltk-8.6.15.0": (
        "5a51bb7b87efa119332c52b04a84c49d3042279c",
        "d30680904f4152fa2fd06bda1f332b7041c8728c",
    ),
}
OFFICIAL_COLLECTIONS = {
    "licenses": (
        20,
        215_720,
        "B7BF8C3C466D1078262C72769189CFB146ECB9B0CCB6EA04AC6C34E60F9A63B0",
    ),
    "metadata/bin-deps": (
        9,
        970_877,
        "373DAF487D78FF0F28973BE7EB52B35BC5E4ED6D64B57E00B112D6FDD9CF0036",
    ),
    "metadata/cpython": (
        33,
        1_645_515,
        "EE330CEDFD76A7F0F97340554915CBF4C70940C1D903533437E7C788F1279681",
    ),
    "metadata/release": (
        6,
        3_157_090,
        "BB25E7F6D81DD1D56932298945ABF66FCA9E371AA2B5AD85C0F4B8EF2A985756",
    ),
    "metadata/reused": (
        4,
        310_952,
        "E05653EDF3BAD3CD552F4878A0866B639098B63BED31F337E98B8E2B095EBCEF",
    ),
    "metadata/source-deps": (
        22,
        2_766_416,
        "D1E5C7BF6BC9E6F176137D7785901ADE75711E64A9C419D0249D12368859098D",
    ),
}
OFFICIAL_COVERED = {
    "expat": ("2.8.1", "PRESERVED_WITH_PARENT"),
    "hacl": (
        "8ba599b2f6c9701b3dc961db895b0856a2210f76",
        "PRESERVED_WITH_PARENT",
    ),
    "libtommath": ("Tcl 8.6.15.0 vendored snapshot", "PRESERVED_WITH_PARENT"),
    "tcl-zlib": ("1.3.1", "PRESERVED_WITH_PARENT"),
    "unicode": ("16.0.0", "PRESERVED_WITH_PARENT"),
}
_HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX_64 = re.compile(r"[0-9A-F]{64}\Z")
_WINDOWS_ABSOLUTE = re.compile(r"\b[A-Za-z]:[\\/]")
_ALLOWED_PRESERVATION = {
    "PRESERVED_NEW",
    "PRESERVED_WITH_PARENT",
    "REUSED_EXISTING_SOURCE",
}
_PROHIBITED_SUFFIXES = {
    ".dll",
    ".edulic",
    ".edureq",
    ".exe",
    ".pyd",
}
_PROHIBITED_PARTS = {
    "activation_issuer",
    "backups",
    "private",
    "wheelhouse",
}


class SourceBundleError(RuntimeError):
    """Indica que manifesto, staging ou bundle falhou fechado."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceBundleError(message)


def sha256_bytes(content: bytes) -> str:
    """Retorna SHA-256 hexadecimal maiúsculo."""
    return hashlib.sha256(content).hexdigest().upper()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calcula SHA-256 sem manter o arquivo inteiro na memória."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def canonical_json_bytes(value: Any) -> bytes:
    """Serializa a identidade canônica usada nos inventários."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def formatted_json_bytes(value: Any) -> bytes:
    """Serializa JSON legível de forma determinística."""
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _validate_relative_path(value: Any, *, field: str) -> str:
    _require(isinstance(value, str) and value, f"Path inválido: {field}")
    _require("\\" not in value, f"Path não canônico: {field}")
    pure = PurePosixPath(value)
    _require(not pure.is_absolute(), f"Path absoluto proibido: {field}")
    _require(".." not in pure.parts, f"Travessia de path proibida: {field}")
    _require(pure.as_posix() == value, f"Path não canônico: {field}")
    return value


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _validate_hash(value: Any, *, field: str) -> str:
    _require(isinstance(value, str) and bool(_HEX_64.fullmatch(value)), field)
    return value


def _validate_git_hash(value: Any, *, field: str) -> str:
    _require(isinstance(value, str) and bool(_HEX_40.fullmatch(value)), field)
    return value


def _validate_file_entry(entry: Any, *, field: str) -> dict[str, Any]:
    _require(isinstance(entry, dict), f"Entrada inválida: {field}")
    _validate_relative_path(entry.get("staging_path"), field=f"{field}.staging_path")
    _validate_hash(entry.get("sha256"), field=f"SHA-256 inválido: {field}")
    _require(
        isinstance(entry.get("size_bytes"), int) and entry["size_bytes"] > 0,
        f"Tamanho inválido: {field}",
    )
    _require(
        isinstance(entry.get("origin"), str) and entry["origin"].startswith("https://"),
        f"Origem inválida: {field}",
    )
    return entry


def validate_manifest_structure(manifest: Any) -> dict[str, Any]:
    """Valida o contrato estrutural sem confiar em campos de classificação."""
    _require(isinstance(manifest, dict), "Manifesto deve ser objeto JSON")
    required = {
        "bin_deps_evidence",
        "bundle",
        "classification",
        "component",
        "counts",
        "covered_by_parent",
        "distribution_notice",
        "frozen_candidate",
        "gates",
        "metadata_collections",
        "non_material",
        "parents",
        "schema_version",
        "separations",
    }
    _require(set(manifest) == required, "Campos raiz do manifesto divergem")
    _require(manifest["schema_version"] == 1, "Schema do manifesto diverge")
    _require(isinstance(manifest["component"], str), "Componente inválido")
    strings = list(_walk_strings(manifest))
    _require(
        not any(_WINDOWS_ABSOLUTE.search(value) for value in strings),
        "Manifesto contém path absoluto Windows",
    )
    _require(
        not any(value.startswith("file://") for value in strings),
        "Manifesto contém URI local",
    )

    counts = manifest["counts"]
    expected_count_keys = {
        "blocked",
        "logical_source_parents",
        "new_acquisitions",
        "pending",
        "preserved",
        "reused_existing",
        "unknown_material",
    }
    _require(
        isinstance(counts, dict) and set(counts) == expected_count_keys,
        "Contagens do manifesto divergem",
    )
    _require(
        all(isinstance(value, int) and value >= 0 for value in counts.values()),
        "Contagem inválida",
    )

    parents = manifest["parents"]
    _require(isinstance(parents, list), "Parents devem ser lista")
    _require(len(parents) == counts["logical_source_parents"], "Parent count diverge")
    ids: set[str] = set()
    staging_paths: set[str] = set()
    for index, parent in enumerate(parents):
        field = f"parents[{index}]"
        _require(isinstance(parent, dict), f"Parent inválido: {field}")
        parent_id = parent.get("id")
        _require(isinstance(parent_id, str) and parent_id, f"ID inválido: {field}")
        _require(parent_id not in ids, "Parent duplicado")
        ids.add(parent_id)
        _require(
            parent.get("preservation_status") in _ALLOWED_PRESERVATION,
            f"Status de preservação inválido: {parent_id}",
        )
        archive = _validate_file_entry(parent.get("source_archive"), field=field)
        _require(archive["staging_path"] not in staging_paths, "Source path duplicado")
        staging_paths.add(archive["staging_path"])
        git = parent.get("git")
        _require(isinstance(git, dict), f"Git identity ausente: {parent_id}")
        _validate_git_hash(git.get("commit"), field=f"Commit inválido: {parent_id}")
        _validate_git_hash(git.get("tree"), field=f"Tree inválida: {parent_id}")
        _require(isinstance(parent.get("consumers"), list), "Consumers ausentes")
        _require(parent["consumers"], f"Consumer ausente: {parent_id}")
        licenses = parent.get("licenses")
        _require(isinstance(licenses, list) and licenses, "Licença ausente")
        for license_entry in licenses:
            _require(isinstance(license_entry, dict), "Licença inválida")
            _validate_relative_path(
                license_entry.get("archive_path"), field="license.archive_path"
            )
            _validate_relative_path(
                license_entry.get("staging_path"), field="license.staging_path"
            )
            _validate_hash(license_entry.get("sha256"), field="Hash de licença")
            _require(
                isinstance(license_entry.get("size_bytes"), int)
                and license_entry["size_bytes"] > 0,
                "Tamanho de licença inválido",
            )

    collections = manifest["metadata_collections"]
    _require(isinstance(collections, list) and collections, "Coleções ausentes")
    roots: set[str] = set()
    for collection in collections:
        _require(isinstance(collection, dict), "Coleção inválida")
        root = _validate_relative_path(collection.get("root"), field="collection.root")
        _require(root not in roots, "Root de coleção duplicado")
        roots.add(root)
        _validate_hash(collection.get("inventory_sha256"), field="Hash da coleção")
        _require(
            isinstance(collection.get("file_count"), int)
            and collection["file_count"] > 0,
            "Contagem da coleção inválida",
        )
        _require(
            isinstance(collection.get("total_size_bytes"), int)
            and collection["total_size_bytes"] > 0,
            "Tamanho da coleção inválido",
        )

    classification = manifest["classification"]
    _require(isinstance(classification, dict), "Classificação inválida")
    if classification.get("source_correspondence") == "A":
        _require(
            classification.get("technical_status")
            == "technically-complete-pending-legal-review",
            "Classe A exige conclusão técnica explícita",
        )
        _require(
            counts["pending"] == counts["blocked"] == counts["unknown_material"] == 0,
            "Classe A não aceita material pendente, bloqueado ou desconhecido",
        )
        _require(
            counts["preserved"] == counts["logical_source_parents"],
            "Classe A exige todos os parents preservados",
        )
    bundle = manifest["bundle"]
    _require(isinstance(bundle, dict), "Bundle inválido")
    _require(
        bundle.get("classification") == "COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW",
        "Classificação do bundle inválida",
    )
    _require(bundle.get("root") == BUNDLE_ROOT, "Root do bundle diverge")
    _validate_relative_path(bundle.get("filename"), field="bundle.filename")
    return manifest


def validate_official_identity(manifest: dict[str, Any]) -> None:
    """Exige a baseline oficial D1/D2 e impede enfraquecimento silencioso."""
    _require(manifest["component"] == OFFICIAL_COMPONENT, "Componente diverge")
    _require(manifest["frozen_candidate"] == OFFICIAL_CANDIDATE, "Candidato diverge")
    _require(manifest["gates"] == OFFICIAL_GATES, "Versão/edição/gates divergiram")
    counts = manifest["counts"]
    _require(
        counts
        == {
            "blocked": 0,
            "logical_source_parents": 10,
            "new_acquisitions": 8,
            "pending": 0,
            "preserved": 10,
            "reused_existing": 2,
            "unknown_material": 0,
        },
        "Contagens oficiais divergiram",
    )
    actual_parents = {item["id"]: item for item in manifest["parents"]}
    _require(
        set(actual_parents) == set(OFFICIAL_PARENT_IDENTITIES), "Parents divergiram"
    )
    for parent_id, expected in OFFICIAL_PARENT_IDENTITIES.items():
        parent = actual_parents[parent_id]
        version, status, source_hash, commit, tree = expected
        _require(parent["version"] == version, f"Versão diverge: {parent_id}")
        _require(
            parent["preservation_status"] == status,
            f"Status diverge: {parent_id}",
        )
        _require(
            parent["source_archive"]["sha256"] == source_hash,
            f"Source hash diverge: {parent_id}",
        )
        _require(parent["git"]["commit"] == commit, f"Commit diverge: {parent_id}")
        _require(parent["git"]["tree"] == tree, f"Tree diverge: {parent_id}")
    covered = {item["id"]: item for item in manifest["covered_by_parent"]}
    _require(set(covered) == set(OFFICIAL_COVERED), "Cobertura por parent diverge")
    for component, expected in OFFICIAL_COVERED.items():
        _require(
            (covered[component]["version"], covered[component]["status"]) == expected,
            f"Cobertura interna diverge: {component}",
        )
    collections = {
        item["root"]: (
            item["file_count"],
            item["total_size_bytes"],
            item["inventory_sha256"],
        )
        for item in manifest["metadata_collections"]
    }
    _require(collections == OFFICIAL_COLLECTIONS, "Coleções oficiais divergiram")
    bin_deps = {
        item["tag"]: (item["commit"], item["tree"])
        for item in manifest["bin_deps_evidence"]
    }
    _require(bin_deps == OFFICIAL_BIN_DEPS, "Bin-deps evidence diverge")
    _require(
        manifest["non_material"]
        == [
            {
                "component": "SQLite",
                "reason": (
                    "_sqlite3.pyd e sqlite3.dll não existem no frozen candidate; "
                    "o pin PCbuild não participa da composição distribuída"
                ),
                "source_required": False,
                "status": "NOT_REQUIRED",
                "version": "3.50.4.0",
            }
        ],
        "Fronteira SQLite diverge",
    )
    _require(
        manifest["separations"]["active_ffmpeg"] == "GYAN",
        "FFmpeg ativo divergiu",
    )
    _require(
        manifest["separations"]["btbn"] == "CANDIDATE_NOT_PROMOTED",
        "BtbN foi promovido indevidamente",
    )
    _require(
        manifest["separations"]["microsoft_runtime"] == "P3_PENDING_LEGAL_REVIEW",
        "Microsoft runtime foi fechado indevidamente",
    )


def load_manifest(
    path: Path, *, enforce_official_baseline: bool = True
) -> dict[str, Any]:
    """Carrega o manifesto e, no fluxo real, exige o hash versionado."""
    try:
        content = path.read_bytes()
        manifest = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SourceBundleError("Manifesto ausente, ilegível ou inválido") from error
    validate_manifest_structure(manifest)
    if enforce_official_baseline:
        _require(
            sha256_bytes(content) == OFFICIAL_MANIFEST_SHA256, "Manifesto adulterado"
        )
        validate_official_identity(manifest)
    return manifest


def _git_blob_sha1(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _archive_files(path: Path) -> tuple[str, dict[str, bytes]]:
    roots: set[str] = set()
    files: dict[str, bytes] = {}
    try:
        if path.suffix.casefold() == ".zip":
            with zipfile.ZipFile(path, "r") as archive:
                for member in archive.infolist():
                    pure = PurePosixPath(member.filename)
                    if not pure.parts:
                        continue
                    _require(
                        not pure.is_absolute() and ".." not in pure.parts,
                        "Source ZIP contém path inseguro",
                    )
                    roots.add(pure.parts[0])
                    if member.is_dir() or len(pure.parts) == 1:
                        continue
                    relative = PurePosixPath(*pure.parts[1:]).as_posix()
                    _require(relative not in files, "Source ZIP contém path duplicado")
                    files[relative] = archive.read(member)
        else:
            with tarfile.open(path, "r:*") as archive:
                for member in archive.getmembers():
                    pure = PurePosixPath(member.name)
                    if not pure.parts:
                        continue
                    _require(
                        not pure.is_absolute() and ".." not in pure.parts,
                        "Source TAR contém path inseguro",
                    )
                    roots.add(pure.parts[0])
                    if len(pure.parts) == 1:
                        continue
                    relative = PurePosixPath(*pure.parts[1:]).as_posix()
                    if member.isfile():
                        stream = archive.extractfile(member)
                        _require(
                            stream is not None, "Source TAR contém arquivo ilegível"
                        )
                        content = stream.read()
                    elif member.issym():
                        content = member.linkname.encode("utf-8")
                    else:
                        continue
                    _require(relative not in files, "Source TAR contém path duplicado")
                    files[relative] = content
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise SourceBundleError("Source archive ausente ou inválido") from error
    _require(len(roots) == 1 and files, "Source archive sem root único")
    return next(iter(roots)), files


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SourceBundleError(f"JSON ausente ou inválido: {label}") from error
    _require(isinstance(result, dict), f"JSON deve ser objeto: {label}")
    return result


def _verify_git_metadata(parent: dict[str, Any], staging: Path) -> dict[str, Any]:
    git = parent["git"]
    parent_id = parent["id"]
    tree_path = staging / _validate_relative_path(
        git["tree_metadata_path"], field=f"{parent_id}.tree_metadata_path"
    )
    tree = _read_json(tree_path, label=f"tree {parent_id}")
    _require(tree.get("sha") == git["tree"], f"Tree metadata diverge: {parent_id}")
    _require(tree.get("truncated") is False, f"Tree truncada: {parent_id}")
    if parent["preservation_status"] == "REUSED_EXISTING_SOURCE":
        provenance = _read_json(
            staging / git["reuse_provenance_path"], label="proveniência reutilizada"
        )
        pins = provenance["correspondence"]["cpython_runtime"]["external_pins"]
        matches = [item for item in pins if item.get("source_tag") == git["tag"]]
        _require(len(matches) == 1, f"Reuse provenance ausente: {parent_id}")
        reused = matches[0]
        _require(reused.get("source_commit") == git["commit"], "Reuse commit diverge")
        _require(reused.get("source_tree") == git["tree"], "Reuse tree diverge")
        _require(
            reused.get("source_sha256") == parent["source_archive"]["sha256"],
            "Reuse archive hash diverge",
        )
        return tree

    ref = _read_json(staging / git["ref_metadata_path"], label=f"ref {parent_id}")
    _require(ref.get("ref") == f"refs/tags/{git['tag']}", f"Tag diverge: {parent_id}")
    ref_object = ref.get("object", {})
    _require(ref_object.get("type") == git["ref_type"], "Tipo do tag ref diverge")
    _require(ref_object.get("sha") == git["ref_sha"], "SHA do tag ref diverge")
    if git["ref_type"] == "tag":
        tag_object = _read_json(
            staging / git["tag_object_metadata_path"], label=f"tag {parent_id}"
        )
        _require(tag_object.get("sha") == git["ref_sha"], "Tag object diverge")
        _require(
            tag_object.get("object", {}).get("type") == "commit", "Tag target diverge"
        )
        _require(
            tag_object.get("object", {}).get("sha") == git["commit"],
            "Tag commit diverge",
        )
    else:
        _require(git["ref_sha"] == git["commit"], "Ref direta diverge do commit")
    commit = _read_json(
        staging / git["commit_metadata_path"], label=f"commit {parent_id}"
    )
    _require(
        commit.get("sha") == git["commit"], f"Commit metadata diverge: {parent_id}"
    )
    _require(
        commit.get("tree", {}).get("sha") == git["tree"],
        f"Commit/tree diverge: {parent_id}",
    )
    return tree


def _verify_archive_tree(
    parent: dict[str, Any], staging: Path, tree: dict[str, Any]
) -> dict[str, int]:
    archive_path = staging / parent["source_archive"]["staging_path"]
    root, files = _archive_files(archive_path)
    verification = parent["archive_tree_verification"]
    _require(
        root == verification["archive_root"], f"Archive root diverge: {parent['id']}"
    )
    expected = {
        item.get("path"): item.get("sha")
        for item in tree.get("tree", [])
        if isinstance(item, dict) and item.get("type") == "blob"
    }
    actual = {path: _git_blob_sha1(content) for path, content in files.items()}
    missing = set(expected) - set(actual)
    extra = set(actual) - set(expected)
    mismatches = {
        path for path in set(actual) & set(expected) if actual[path] != expected[path]
    }
    normalized = {
        path
        for path in mismatches
        if _git_blob_sha1(files[path].replace(b"\r\n", b"\n")) == expected[path]
    }
    unexplained = mismatches - normalized
    expected_counts = {
        "archive_file_count": len(files),
        "direct_matches": len(set(actual) & set(expected)) - len(mismatches),
        "eol_normalized_matches": len(normalized),
        "extra_files": len(extra),
        "missing_tree_blobs": len(missing),
        "tree_blob_count": len(expected),
    }
    _require(not unexplained, f"Archive/tree diverge: {parent['id']}")
    _require(
        expected_counts == verification["counts"],
        f"Contagem tree diverge: {parent['id']}",
    )
    _require(
        sorted(extra) == verification.get("allowed_archive_only", []),
        f"Arquivo extra não explicado: {parent['id']}",
    )
    if verification["strategy"] == "git-archive-exact":
        _require(
            not missing and not extra and not normalized, "Snapshot Git não é exato"
        )
    elif verification["strategy"] == "git-archive-eol-normalized":
        _require(not missing and not extra, "Snapshot Git normalizado está incompleto")
    else:
        _require(
            verification["strategy"] == "official-release-export",
            "Estratégia de archive inválida",
        )
    return expected_counts


def _archive_member(parent: dict[str, Any], staging: Path, relative: str) -> bytes:
    _, files = _archive_files(staging / parent["source_archive"]["staging_path"])
    try:
        return files[relative]
    except KeyError as error:
        raise SourceBundleError(
            f"Membro source ausente em {parent['id']}: {relative}"
        ) from error


def _verify_license_files(parent: dict[str, Any], staging: Path) -> None:
    for entry in parent["licenses"]:
        archive_content = _archive_member(parent, staging, entry["archive_path"])
        staged_path = staging / entry["staging_path"]
        try:
            staged_content = staged_path.read_bytes()
        except OSError as error:
            raise SourceBundleError("Licença extraída ausente") from error
        _require(
            staged_content == archive_content, "Licença extraída diverge do source"
        )
        _require(
            len(staged_content) == entry["size_bytes"], "Tamanho da licença diverge"
        )
        _require(
            sha256_bytes(staged_content) == entry["sha256"], "Hash da licença diverge"
        )


def _collection_inventory(staging: Path, root: str) -> list[dict[str, Any]]:
    directory = staging / root
    _require(directory.is_dir(), f"Coleção ausente: {root}")
    entries: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        _require(not path.is_symlink(), "Coleção não aceita link simbólico")
        if path.is_file():
            entries.append(
                {
                    "relative_path": path.relative_to(staging).as_posix(),
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
    return entries


def _verify_collection(
    collection: dict[str, Any], staging: Path
) -> list[dict[str, Any]]:
    entries = _collection_inventory(staging, collection["root"])
    _require(len(entries) == collection["file_count"], "Contagem da coleção diverge")
    _require(
        sum(item["size"] for item in entries) == collection["total_size_bytes"],
        "Tamanho da coleção diverge",
    )
    _require(
        sha256_bytes(canonical_json_bytes(entries)) == collection["inventory_sha256"],
        "Inventário da coleção diverge",
    )
    return entries


def _verify_release_metadata(manifest: dict[str, Any], staging: Path) -> None:
    cpython = next(item for item in manifest["parents"] if item["id"] == "cpython")
    source_hash = cpython["source_archive"]["sha256"]
    source_sbom = _read_json(
        staging / "metadata/release/Python-3.14.6.tar.xz.spdx.json",
        label="CPython source SBOM",
    )
    packages = [
        item
        for item in source_sbom.get("packages", [])
        if item.get("name") == "CPython"
    ]
    _require(len(packages) == 1, "CPython ausente do source SBOM")
    package = packages[0]
    hashes = {
        item.get("algorithm"): item.get("checksumValue", "").upper()
        for item in package.get("checksums", [])
    }
    _require(hashes.get("SHA256") == source_hash, "Source SBOM hash diverge")
    _require(package.get("versionInfo") == "3.14.6", "Source SBOM version diverge")
    _require(package.get("licenseConcluded") == "PSF-2.0", "Licença CPython diverge")

    sigstore = _read_json(
        staging / "metadata/release/Python-3.14.6.tar.xz.sigstore",
        label="CPython Sigstore bundle",
    )
    digest = sigstore.get("messageSignature", {}).get("messageDigest", {})
    _require(digest.get("algorithm") == "SHA2_256", "Algoritmo Sigstore diverge")
    _require(
        base64.b64decode(digest.get("digest", "")) == bytes.fromhex(source_hash),
        "Digest Sigstore diverge",
    )

    windows_manifest_path = staging / "metadata/release/windows-3.14.6.json"
    windows_manifest = _read_json(
        windows_manifest_path, label="Windows release manifest"
    )
    versions = [
        item
        for item in windows_manifest.get("versions", [])
        if item.get("id") == "pythoncore-3.14-64"
    ]
    _require(len(versions) == 1, "Runtime Windows AMD64 ausente do release manifest")
    runtime = versions[0]
    _require(runtime.get("sort-version") == "3.14.6", "Runtime Windows diverge")
    _require(runtime.get("company") == "PythonCore", "Authority Windows diverge")
    windows_sigstore = _read_json(
        staging / "metadata/release/windows-3.14.6.json.sigstore",
        label="Windows manifest Sigstore bundle",
    )
    windows_digest = windows_sigstore["messageSignature"]["messageDigest"]
    _require(windows_digest["algorithm"] == "SHA2_256", "Sigstore Windows diverge")
    _require(
        base64.b64decode(windows_digest["digest"])
        == hashlib.sha256(windows_manifest_path.read_bytes()).digest(),
        "Digest Sigstore do manifest Windows diverge",
    )


def _verify_externals_sbom(manifest: dict[str, Any], staging: Path) -> None:
    sbom = _read_json(
        staging / "metadata/cpython/Misc/externals.spdx.json",
        label="CPython externals SBOM",
    )
    packages = {item.get("name"): item for item in sbom.get("packages", [])}
    parents = {item["id"]: item for item in manifest["parents"]}
    for parent in parents.values():
        package_name = parent.get("external_sbom_package")
        if package_name is None:
            continue
        _require(package_name in packages, f"External ausente do SBOM: {package_name}")
        package = packages[package_name]
        _require(
            package.get("versionInfo") == parent["external_sbom_version"],
            f"Versão SBOM diverge: {package_name}",
        )
        _require(
            package.get("downloadLocation") == parent["external_sbom_url"],
            f"URL SBOM diverge: {package_name}",
        )
        checksums = {
            item.get("algorithm"): item.get("checksumValue", "").upper()
            for item in package.get("checksums", [])
        }
        _require(
            checksums.get("SHA256") == parent["external_sbom_sha256"],
            f"Hash SBOM diverge: {package_name}",
        )
    sqlite = packages.get("sqlite", {})
    _require(sqlite.get("versionInfo") == "3.50.4.0", "Pin SQLite diverge")
    _require(
        not any(item["id"] == "sqlite" for item in manifest["parents"]),
        "SQLite foi promovido sem material distribuído",
    )


def _verify_internal_coverage(manifest: dict[str, Any], staging: Path) -> None:
    parents = {item["id"]: item for item in manifest["parents"]}
    cpython = parents["cpython"]
    required_cpython = {
        "Include/patchlevel.h": b'#define PY_VERSION              "3.14.6"',
        "Modules/_hacl/refresh.sh": b"8ba599b2f6c9701b3dc961db895b0856a2210f76",
        "Modules/_tkinter.c": b"PyInit__tkinter",
        "Modules/_zstd/_zstdmodule.c": b"PyInit__zstd",
        "Modules/expat/refresh.sh": b'expected_libexpat_version="2.8.1"',
        "Modules/unicodedata_db.h": b'#define UNIDATA_VERSION "16.0.0"',
        "PCbuild/python.props": b"zlib-ng-2.2.4",
    }
    for path, fragment in required_cpython.items():
        _require(
            fragment in _archive_member(cpython, staging, path),
            f"CPython coverage ausente: {path}",
        )
    tcl = parents["tcl"]
    _require(
        b'#define ZLIB_VERSION "1.3.1"'
        in _archive_member(tcl, staging, "compat/zlib/zlib.h"),
        "Tcl zlib 1.3.1 não está coberto",
    )
    _require(
        b"LibTomMath" in _archive_member(tcl, staging, "libtommath/tommath.h"),
        "libtommath não está coberto pelo Tcl",
    )
    _require(
        len(
            [
                path
                for path in _archive_files(
                    staging / tcl["source_archive"]["staging_path"]
                )[1]
                if path.startswith("compat/zlib/")
            ]
        )
        == 266,
        "Closure zlib interna do Tcl diverge",
    )
    _require(
        len(
            [
                path
                for path in _archive_files(
                    staging / tcl["source_archive"]["staging_path"]
                )[1]
                if path.startswith("libtommath/")
            ]
        )
        == 76,
        "Closure libtommath interna do Tcl diverge",
    )


def _verify_bin_deps(manifest: dict[str, Any], staging: Path) -> None:
    for item in manifest["bin_deps_evidence"]:
        ref = _read_json(staging / item["ref_metadata_path"], label="bin-deps ref")
        commit = _read_json(
            staging / item["commit_metadata_path"], label="bin-deps commit"
        )
        tree = _read_json(staging / item["tree_metadata_path"], label="bin-deps tree")
        _require(
            ref.get("object", {}).get("sha") == item["commit"], "Bin-deps ref diverge"
        )
        _require(commit.get("sha") == item["commit"], "Bin-deps commit diverge")
        _require(
            commit.get("tree", {}).get("sha") == item["tree"], "Bin-deps tree diverge"
        )
        _require(
            tree.get("sha") == item["tree"] and tree.get("truncated") is False,
            "Bin-deps tree metadata diverge",
        )


def verify_staging(manifest: dict[str, Any], staging: Path) -> list[dict[str, Any]]:
    """Falha se qualquer source, metadata, licença, path ou relação divergir."""
    _require(staging.is_dir(), "Staging ausente")
    actual: dict[str, Path] = {}
    for path in staging.rglob("*"):
        _require(not path.is_symlink(), "Staging não aceita link simbólico")
        if not path.is_file():
            continue
        relative = path.relative_to(staging).as_posix()
        actual[relative] = path
        pure = PurePosixPath(relative)
        _require(
            pure.suffix.casefold() not in _PROHIBITED_SUFFIXES,
            f"Executável/candidato proibido no staging: {relative}",
        )
        _require(
            not (_PROHIBITED_PARTS & {part.casefold() for part in pure.parts}),
            f"Material privado ou fora de escopo no staging: {relative}",
        )
    inventory: list[dict[str, Any]] = []
    expected: set[str] = set()
    for parent in manifest["parents"]:
        archive = parent["source_archive"]
        relative = archive["staging_path"]
        expected.add(relative)
        path = staging / relative
        _require(path.is_file(), f"Source ausente: {parent['id']}")
        _require(path.stat().st_size == archive["size_bytes"], "Source size diverge")
        _require(sha256_file(path) == archive["sha256"], "Source hash diverge")
        inventory.append(
            {
                "relative_path": relative,
                "sha256": archive["sha256"],
                "size": archive["size_bytes"],
            }
        )
    for collection in manifest["metadata_collections"]:
        collection_inventory = _verify_collection(collection, staging)
        inventory.extend(collection_inventory)
        expected.update(item["relative_path"] for item in collection_inventory)
    missing = sorted(expected - set(actual))
    unexpected = sorted(set(actual) - expected)
    _require(not missing, f"Arquivo esperado ausente: {missing[:1]}")
    _require(not unexpected, f"Arquivo inesperado no staging: {unexpected[:1]}")

    if manifest["component"] == OFFICIAL_COMPONENT:
        for parent in manifest["parents"]:
            tree = _verify_git_metadata(parent, staging)
            _verify_archive_tree(parent, staging, tree)
            _verify_license_files(parent, staging)
        _verify_release_metadata(manifest, staging)
        _verify_externals_sbom(manifest, staging)
        _verify_internal_coverage(manifest, staging)
        _verify_bin_deps(manifest, staging)
    inventory.sort(key=lambda item: item["relative_path"])
    return inventory


def verify_frozen_consistency(
    manifest: dict[str, Any], frozen_manifest_path: Path
) -> dict[str, Any]:
    """Confere a autoridade do candidate sem reconstruí-lo ou modificá-lo."""
    frozen = _read_json(frozen_manifest_path, label="frozen composition manifest")
    candidate = manifest["frozen_candidate"]
    _require(
        frozen.get("candidate_classification") == candidate["classification"],
        "Classificação do frozen candidate diverge",
    )
    _require(
        frozen.get("build_provenance", {}).get("source_commit")
        == candidate["source_commit"],
        "Commit-fonte do frozen candidate diverge",
    )
    pristine = frozen.get("pristine_inventory", {})
    _require(
        pristine.get("file_count") == candidate["file_count"],
        "File count do candidate diverge",
    )
    _require(
        pristine.get("total_size_bytes") == candidate["total_size_bytes"],
        "Tamanho do candidate diverge",
    )
    _require(
        pristine.get("inventory_sha256") == candidate["inventory_sha256"],
        "Inventário do candidate diverge",
    )
    application = frozen.get("application", {})
    _require(
        application.get("app_version") == manifest["gates"]["app_version"],
        "APP_VERSION do candidate diverge",
    )
    _require(
        application.get("product_edition") == manifest["gates"]["product_edition"],
        "ProductEdition do candidate diverge",
    )
    frozen_gates = {**frozen.get("gates", {}), **application}
    for key, value in manifest["gates"].items():
        _require(frozen_gates.get(key) == value, f"Gate do candidate diverge: {key}")
    microsoft = next(
        item
        for item in frozen.get("group_summaries", [])
        if item.get("group") == "microsoft_runtime"
    )
    _require(
        microsoft
        == {
            "file_count": 45,
            "group": "microsoft_runtime",
            "total_size_bytes": 2_522_376,
        },
        "Runtime Microsoft diverge",
    )
    return {
        "candidate_classification": candidate["classification"],
        "file_count": candidate["file_count"],
        "inventory_sha256": candidate["inventory_sha256"],
        "status": "verified",
    }


def verify_candidate_notices(
    manifest: dict[str, Any], staging: Path, candidate: Path
) -> dict[str, Any]:
    """Confere a licença Tk e mantém a ausência Tcl como notice gap separado."""
    notice = manifest["distribution_notice"]
    tk_path = candidate / "_internal/_tk_data/license.terms"
    _require(tk_path.is_file(), "Licença Tk ausente do frozen candidate")
    _require(
        sha256_file(tk_path) == notice["candidate_tk_license_sha256"],
        "Hash da licença Tk do candidate diverge",
    )
    source = (staging / notice["source_tk_license_path"]).read_bytes()
    candidate_bytes = tk_path.read_bytes()
    normalized_source = source.replace(b"\r\n", b"\n")
    normalized_candidate = candidate_bytes.replace(b"\r\n", b"\n")
    _require(
        normalized_source == normalized_candidate,
        "Licença Tk não corresponde ao source",
    )
    tcl_notice_files = [
        path
        for path in (candidate / "_internal/_tcl_data").rglob("*")
        if path.is_file() and re.search(r"license|copying|notice", path.name, re.I)
    ]
    _require(not tcl_notice_files, "Baseline de ausência da licença Tcl diverge")
    _require(
        notice["tcl_license_status"] == "NOTICE_GAP_TO_FIX_LATER",
        "Gap de notice Tcl foi mascarado",
    )
    return {
        "candidate_tk_license_sha256": sha256_file(tk_path),
        "normalized_equal": True,
        "tcl_license_status": notice["tcl_license_status"],
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _inventory_document(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "classification": "COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW",
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
    """Monta ZIP determinístico usando somente o staging verificado."""
    manifest = load_manifest(
        manifest_path, enforce_official_baseline=enforce_official_baseline
    )
    verified = verify_staging(manifest, staging)
    entries = [
        {**item, "relative_path": f"{BUNDLE_ROOT}/{item['relative_path']}"}
        for item in verified
    ]
    manifest_bytes = formatted_json_bytes(manifest)
    entries.append(
        {
            "relative_path": f"{BUNDLE_ROOT}/SOURCE_PROVENANCE.json",
            "sha256": sha256_bytes(manifest_bytes),
            "size": len(manifest_bytes),
        }
    )
    entries.sort(key=lambda item: item["relative_path"])
    inventory_bytes = formatted_json_bytes(_inventory_document(entries))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for entry in entries:
                name = entry["relative_path"]
                if name.endswith("/SOURCE_PROVENANCE.json"):
                    content = manifest_bytes
                else:
                    content = (
                        staging / name.removeprefix(f"{BUNDLE_ROOT}/")
                    ).read_bytes()
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
        manifest_path, output, enforce_official_baseline=enforce_official_baseline
    )


def verify_bundle(
    manifest_path: Path,
    bundle: Path,
    *,
    enforce_official_baseline: bool = True,
) -> dict[str, Any]:
    """Reabre o ZIP e confere manifesto, inventário e todos os bytes."""
    manifest = load_manifest(
        manifest_path, enforce_official_baseline=enforce_official_baseline
    )
    manifest_name = f"{BUNDLE_ROOT}/SOURCE_PROVENANCE.json"
    inventory_name = f"{BUNDLE_ROOT}/SOURCE-BUNDLE-INVENTORY.json"
    try:
        with zipfile.ZipFile(bundle, "r") as archive:
            names = archive.namelist()
            _require(len(names) == len(set(names)), "Bundle contém paths duplicados")
            for name in names:
                _validate_relative_path(name, field="bundle.path")
            _require(
                manifest_name in names and inventory_name in names,
                "Manifesto/inventário ausente do bundle",
            )
            _require(
                archive.read(manifest_name) == formatted_json_bytes(manifest),
                "Manifesto interno diverge",
            )
            inventory = json.loads(archive.read(inventory_name).decode("utf-8"))
            entries = inventory.get("entries")
            _require(isinstance(entries, list), "Inventário interno inválido")
            expected_names = {item["relative_path"] for item in entries}
            _require(
                set(names) == expected_names | {inventory_name},
                "Composição do bundle diverge",
            )
            recomputed = []
            for entry in sorted(entries, key=lambda item: item["relative_path"]):
                name = _validate_relative_path(
                    entry["relative_path"], field="inventory.path"
                )
                content = archive.read(name)
                recomputed.append(
                    {
                        "relative_path": name,
                        "sha256": sha256_bytes(content),
                        "size": len(content),
                    }
                )
    except (
        OSError,
        KeyError,
        UnicodeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as error:
        raise SourceBundleError("Bundle ausente ou inválido") from error
    _require(recomputed == entries, "Conteúdo do bundle diverge do inventário")
    root_hash = sha256_bytes(canonical_json_bytes(entries))
    _require(inventory.get("inventory_sha256") == root_hash, "Hash raiz diverge")
    _require(
        inventory.get("classification") == manifest["bundle"]["classification"],
        "Classificação interna diverge",
    )
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
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify-staging")
    verify.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    assemble = commands.add_parser("assemble")
    assemble.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    assemble.add_argument("--output", type=Path, default=DEFAULT_BUNDLE)
    verify_bundle_parser = commands.add_parser("verify-bundle")
    verify_bundle_parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    frozen = commands.add_parser("verify-frozen")
    frozen.add_argument("--frozen-manifest", type=Path, default=DEFAULT_FROZEN_MANIFEST)
    notices = commands.add_parser("verify-candidate-notices")
    notices.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    notices.add_argument("--candidate", type=Path, default=DEFAULT_FROZEN_CANDIDATE)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Executa somente validações/montagem offline; nunca baixa arquivos."""
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "verify-staging":
            manifest = load_manifest(args.manifest)
            inventory = verify_staging(manifest, args.staging)
            result = {
                "file_count": len(inventory),
                "inventory_sha256": sha256_bytes(canonical_json_bytes(inventory)),
                "status": "verified",
                "total_size_bytes": sum(item["size"] for item in inventory),
            }
        elif args.command == "assemble":
            result = assemble_bundle(args.manifest, args.staging, args.output)
            result["bundle_path"] = _display_path(args.output)
        elif args.command == "verify-bundle":
            result = verify_bundle(args.manifest, args.bundle)
            result["bundle_path"] = _display_path(args.bundle)
        elif args.command == "verify-frozen":
            manifest = load_manifest(args.manifest)
            result = verify_frozen_consistency(manifest, args.frozen_manifest)
        else:
            manifest = load_manifest(args.manifest)
            result = verify_candidate_notices(manifest, args.staging, args.candidate)
    except (OSError, SourceBundleError) as error:
        print(f"python_runtime_source_bundle_invalid: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
