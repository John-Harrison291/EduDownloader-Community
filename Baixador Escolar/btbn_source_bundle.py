"""Valida e monta o bundle de source do candidato FFmpeg BtbN."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_MANIFEST = Path("docs/compliance/ffmpeg/BTBN_SOURCE_PROVENANCE.json")
DEFAULT_STAGING = Path(
    "build-compliance-ffmpeg-btbn/autobuild-2026-08-25-13-06/source-staging"
)
DEFAULT_BUNDLE = (
    DEFAULT_STAGING.parent
    / "bundles"
    / (
        "EduDownloader-ThirdParty-Source-FFmpeg-BtbN-"
        "autobuild-2026-08-25-13-06-COMPLETE-CANDIDATE.zip"
    )
)
OFFICIAL_CANDIDATE_MANIFEST = Path(
    "docs/compliance/ffmpeg/BTBN_CANDIDATE_PROVENANCE.json"
)
OFFICIAL_MANIFEST_SHA256 = (
    "D7DB1D53B855484F5BDEE2F5DCA2360719CFAC1E338A1A073138C9D0A1D1F8FE"
)
OFFICIAL_BTBN_COMMIT = "a1b5c414d3c53f5abf5baf73df9607cdf77bb46a"
OFFICIAL_FFMPEG_COMMIT = "7c533d0f86f13a06ec93968f6194349665b3536a"
OFFICIAL_RELEASE = "autobuild-2026-08-25-13-06"
OFFICIAL_VARIANT = "win64-lgpl-8.1 static"
OFFICIAL_SOURCE_CORRESPONDENCE = "A_TECHNICALLY_COMPLETE_FOR_LEGAL_REVIEW"
OFFICIAL_BASELINE_PARENT_COUNT = 84
OFFICIAL_DEPENDENCY_PARENT_COUNT = 58
OFFICIAL_SOURCE_PARENT_RECORD_COUNT = 142
OFFICIAL_MATERIAL_PARENT_COUNT = 138
OFFICIAL_BASELINE_PRESERVED_COUNT = 80
OFFICIAL_MATERIAL_PRESERVED_COUNT = 138
OFFICIAL_CARGO_MATERIAL_COUNT = 48
OFFICIAL_CARGO_PRESERVED_COUNT = 48
OFFICIAL_CARGO_PENDING_COUNT = 0
C4C_CARGO_PRESERVED_COUNT = 40
C4C_CARGO_PENDING_COUNT = 8
C4D_PACKAGES = {
    ("av1-grain", "0.2.4"),
    ("built", "0.8.0"),
    ("minimal-lexical", "0.2.1"),
    ("nom", "7.1.3"),
    ("num-derive", "0.4.2"),
    ("profiling", "1.0.16"),
    ("profiling-procmacros", "1.0.16"),
    ("simd_helpers", "0.1.0"),
}
C5_SUPERSEDED_NV = {
    "833faee5f7b8d3f56444347c587f4aed11ee213f": "FFVER < 800",
    "ced4f8eba3ba5dd431932cba17928f0dffdaeb2b": "800 <= FFVER <= 801",
}
C5_MATERIAL_REVISIONS = {
    "AMF": "c35f613aea2e5057a688c979e75b1cf24253297e",
    "OpenCL-Headers": "c9c8ccfab584f9f7610057c4633dbd3df7e012cc",
    "OpenCL-ICD-Loader": "18fdcd58286376124f938948aa8ed156079c1c16",
    "SPIRV-Cross": "9c3c8e2cefdd8194b193bb8ed2fdff4d5527e382",
    "SPIRV-Headers": "f0bf307f7c49d26484db596185cece53c37701fc",
    "Vulkan-Headers (libplacebo submodule)": (
        "74d8a6cb930c68ef617b202c3ff3c59d919e086b"
    ),
    "Vulkan-Shim-Loader": "65b3936528cd92eb4ea3de485d03f858a3850484",
    "libva": "6b07f7100512817f736967e899b8c26313c20623",
    "libvpl": "674d015bcb294bc39fa276e99a652ea045423e82",
    "nv-codec-headers": "eddcea9e27f6b772057c9b3f87de2cc1737faffc",
    "shaderc": "7060a6615a1c6e2515e696651eea685524ecadb5",
}
C5_SHADERC_DEPENDENCIES = {
    "shaderc/glslang": "2ee090f606ace31e07f584b1c1b9ddf4909ce202",
    "shaderc/SPIRV-Tools": "f589ef005c49f6f19c8e78eb5269104ba293beb4",
    "shaderc/SPIRV-Headers": "942fe4b988359a0750b79f0ae7ed735994d3147d",
}
PARTIAL_BUNDLE_CLASSIFICATION = "PARTIAL_CANDIDATE_NOT_FOR_RELEASE"
OFFICIAL_BUNDLE_CLASSIFICATION = "COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW"
C7_CROSSTOOL_COMMIT = "185f3483e0e5028357b131fb97c4331551a70a1e"
C7_CROSSTOOL_TREE = "04baf30606d28a3d171e7bec27d6d794056357d3"
C7_GCC_SHA256 = "438FD996826B0C82485A29DA03A72D71D6E3541A83EC702DF4271F6FE025D24E"
C7_MINGW_BASE_SHA256 = (
    "5AFE822AF5C4EDBF67DAAF45EEC61D538F49EEF6B19524DE64897C6B95828CAF"
)
C7_MINGW_FINAL_COMMIT = "5ea8e9facd013b815f5f29f20ef26a566319a3de"
C7_MINGW_FINAL_TREE = "3c7e2520b411fada94cbd9e03cfc72d0e123a866"
C7_RUST_COMMIT = "8bab26f4f68e0e26f0bb7960be334d5b520ea452"
C7_RUST_SHA256 = "E9A1E616D04C6845895C827A178B9227F7C7199F3F4A80AF81AB3AFF7B80156B"
C7_COMPILER_BUILTINS_TREE = "925f8304d5fef8e702c62f9e05fbe8fbc607e4aa"
C7_BACKTRACE_COMMIT = "28ec93b503bf0410745bc3d571bf3dc1caac3019"
CARGO_REGISTRY_SOURCE = (
    "registry+" + "https:" + "//github.com/rust-lang/crates.io-index"
)
STATUS_VALUES = {
    "PRESERVED",
    "PENDING",
    "NOT_REQUIRED",
    "BUILD_ONLY",
    "CONDITIONAL",
    "BLOCKED",
}
TRANSITIVE_STATUS_VALUES = {
    *STATUS_VALUES,
    "PRESERVED_WITH_PARENT",
    "UNKNOWN",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")


class SourceBundleError(RuntimeError):
    """Indica divergência de provenance, staging ou bundle."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceBundleError(message)


def sha256_bytes(content: bytes) -> str:
    """Retorna SHA-256 hexadecimal maiúsculo."""
    return hashlib.sha256(content).hexdigest().upper()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calcula SHA-256 sem carregar arquivos grandes integralmente."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def canonical_json_bytes(value: Any) -> bytes:
    """Serializa a identidade canônica de um inventário."""
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def formatted_json_bytes(value: Any) -> bytes:
    """Serializa JSON legível e determinístico."""
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _validate_relative_path(value: Any, *, field: str) -> str:
    _require(isinstance(value, str) and value, f"{field} inválido")
    path = PurePosixPath(value)
    _require(
        not path.is_absolute() and ".." not in path.parts and "\\" not in value,
        f"{field} deve ser relativo e normalizado",
    )
    return value


def _git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _parse_json_bytes(content: bytes, *, label: str) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
        if text.startswith(")]}'"):
            text = text.split("\n", 1)[1]
        value = json.loads(text)
    except (UnicodeError, json.JSONDecodeError, IndexError) as error:
        raise SourceBundleError(f"Metadata JSON inválida: {label}") from error
    _require(isinstance(value, dict), f"Metadata JSON não é objeto: {label}")
    return value


def _validate_manifest(
    manifest: dict[str, Any], *, enforce_official_baseline: bool
) -> None:
    _require(manifest.get("schema_version") == 1, "Schema BTBN source inválido")
    correspondence = manifest.get("source_correspondence")
    _require(
        correspondence in {"PARTIAL", OFFICIAL_SOURCE_CORRESPONDENCE},
        "Classificação de source correspondence inválida",
    )
    if enforce_official_baseline:
        _require(
            correspondence == OFFICIAL_SOURCE_CORRESPONDENCE,
            "Closure oficial não está tecnicamente completa",
        )
    bundle = manifest.get("bundle")
    _require(isinstance(bundle, dict), "Definição de bundle ausente")
    expected_classification = (
        OFFICIAL_BUNDLE_CLASSIFICATION
        if correspondence == OFFICIAL_SOURCE_CORRESPONDENCE
        else PARTIAL_BUNDLE_CLASSIFICATION
    )
    _require(
        bundle.get("classification") == expected_classification,
        "Classificação do bundle diverge da source correspondence",
    )
    _require(bundle.get("deterministic_zip") is True, "Bundle não determinístico")
    root = _validate_relative_path(bundle.get("root"), field="bundle.root")
    if correspondence == "PARTIAL":
        _require("partial" in root.lower(), "Root do bundle não declara estado parcial")
    else:
        _require(
            "complete" in root.lower() and "legal" not in root.lower(),
            "Root completo não declara estado técnico ou sugere aprovação jurídica",
        )

    parents = manifest.get("parents")
    _require(isinstance(parents, list) and parents, "Parents ausentes")
    expected_parent_count = (
        OFFICIAL_BASELINE_PARENT_COUNT if enforce_official_baseline else len(parents)
    )
    _require(len(parents) == expected_parent_count, "Quantidade de parents divergente")
    dependency_parents = manifest.get("dependency_parents", [])
    _require(isinstance(dependency_parents, list), "Dependency parents inválidos")
    if enforce_official_baseline:
        _require(
            len(dependency_parents) == OFFICIAL_DEPENDENCY_PARENT_COUNT,
            "Quantidade de dependency parents divergente",
        )
    dedupe_keys: list[str] = []
    for parent in [*parents, *dependency_parents]:
        _require(isinstance(parent, dict), "Parent inválido")
        dedupe = parent.get("dedupe_key")
        _require(isinstance(dedupe, str) and dedupe, "Parent sem dedupe_key")
        dedupe_keys.append(dedupe)
        status = parent.get("preservation_status")
        _require(status in STATUS_VALUES, f"Status de parent inválido: {status}")
        _require(
            parent.get("class") in {"A", "B", "C", "D", "E", "F"}, "Classe inválida"
        )
        source = parent.get("source")
        metadata = parent.get("metadata")
        _require(isinstance(metadata, list), "Metadata de parent inválida")
        source_scope = parent.get("source_scope")
        if enforce_official_baseline or source_scope is not None:
            _require(
                source_scope in {"BTBN_BUILD_PARENT", "DISTRIBUTED_PAIR_SOURCE_PARENT"},
                "Escopo de source parent inválido",
            )
            pair_status = parent.get("distributed_pair_status")
            _require(
                pair_status
                in {
                    "MATERIAL_TO_DISTRIBUTED_PAIR",
                    "BUILD_INPUT_FOR_DISTRIBUTED_PAIR",
                    "NOT_REQUIRED_FOR_DISTRIBUTED_PAIR",
                },
                "Status de materialidade do par distribuído inválido",
            )
            if pair_status == "NOT_REQUIRED_FOR_DISTRIBUTED_PAIR":
                _require(
                    source_scope == "BTBN_BUILD_PARENT"
                    and status == "NOT_REQUIRED"
                    and source is None
                    and bool(parent.get("distributed_pair_evidence")),
                    "Parent excluído do par distribuído sem evidência",
                )
            elif source_scope == "DISTRIBUTED_PAIR_SOURCE_PARENT":
                _require(
                    status != "NOT_REQUIRED",
                    "Source material do par distribuído foi excluído",
                )
        if parent.get("source_type") == "Cargo Registry":
            _require(
                parent.get("batch") in {"C4c", "C4d"}
                and re.fullmatch(
                    r"[0-9a-f]{64}", str(parent.get("cargo_lock_checksum", ""))
                )
                is not None
                and isinstance(parent.get("cargo_package"), str)
                and isinstance(parent.get("cargo_version"), str)
                and parent.get("upstream") == CARGO_REGISTRY_SOURCE,
                "Crate sem identidade oficial Cargo C4c/C4d",
            )
        if status == "PRESERVED":
            _require(isinstance(source, dict), "Parent preservado sem source")
            _validate_source_entry(source)
            _require(
                parent.get("batch")
                in {"C1", "C2", "C3", "C4", "C4b", "C4c", "C4d", "C5", "C7"},
                "Parent preservado fora de lote autorizado",
            )
            source_type = parent.get("source_type")
            if source_type == "Git":
                _require(
                    bool(HEX40.fullmatch(str(parent.get("full_revision", "")))),
                    "Commit Git não imutável",
                )
                _require(
                    bool(HEX40.fullmatch(str(parent.get("tree", "")))),
                    "Tree Git ausente",
                )
                if parent.get("pin_kind") == "git_tag_or_ref":
                    _require(bool(parent.get("ref")), "Ref Git ausente")
                    _require(
                        bool(HEX40.fullmatch(str(parent.get("tag_object", "")))),
                        "Tag object ausente",
                    )
            elif source_type == "SVN":
                _require(
                    parent.get("full_revision") == "6761", "Revision LAME divergente"
                )
            elif source_type == "Cargo Registry":
                checksum = str(parent["cargo_lock_checksum"])
                _require(
                    source.get("authority") == "cargo_lock_and_crates_io_index_checksum"
                    and str(source.get("sha256", "")).lower() == checksum,
                    "Crate preservada diverge do checksum Cargo.lock",
                )
            elif source_type == "Release Archive":
                _require(
                    parent.get("batch") == "C7"
                    and isinstance(parent.get("version"), str)
                    and bool(parent["version"])
                    and source.get("tree_verification", {}).get("strategy")
                    == "official_release_archive_inventory",
                    "Release archive C7 sem identidade/inventário oficial",
                )
            else:
                raise SourceBundleError("Tipo de source preservado inválido")
        else:
            _require(source is None, "Parent não preservado contém source")
    _require(len(dedupe_keys) == len(set(dedupe_keys)), "Parent duplicado")

    counts = Counter(parent["preservation_status"] for parent in parents)
    baseline_count_key = f"counts_for_baseline_{len(parents)}"
    recorded_counts = manifest.get("parent_status", {}).get(baseline_count_key)
    if recorded_counts is None and not enforce_official_baseline:
        recorded_counts = manifest.get("parent_status", {}).get(
            "counts_for_baseline_81"
        )
    _require(isinstance(recorded_counts, dict), "Contagens de status ausentes")
    _require(
        {status: counts.get(status, 0) for status in sorted(STATUS_VALUES)}
        == {status: recorded_counts.get(status, 0) for status in sorted(STATUS_VALUES)},
        "Contagens de status divergentes",
    )
    preserved_count = counts["PRESERVED"]
    dependency_counts = Counter(
        parent["preservation_status"] for parent in dependency_parents
    )
    recorded_dependency_counts = manifest.get("parent_status", {}).get(
        "counts_for_dependency_parents"
    )
    if dependency_parents:
        _require(
            isinstance(recorded_dependency_counts, dict),
            "Contagens de dependency parents ausentes",
        )
        _require(
            {
                status: dependency_counts.get(status, 0)
                for status in sorted(STATUS_VALUES)
            }
            == {
                status: recorded_dependency_counts.get(status, 0)
                for status in sorted(STATUS_VALUES)
            },
            "Contagens de dependency parents divergentes",
        )
    material_parents = [
        parent
        for parent in [*parents, *dependency_parents]
        if parent.get("distributed_pair_status") != "NOT_REQUIRED_FOR_DISTRIBUTED_PAIR"
    ]
    material_counts = Counter(
        parent["preservation_status"] for parent in material_parents
    )
    if correspondence == OFFICIAL_SOURCE_CORRESPONDENCE:
        _require(
            material_counts["PRESERVED"] == len(material_parents)
            and material_counts["PENDING"] == 0
            and material_counts["BLOCKED"] == 0
            and material_counts["CONDITIONAL"] == 0,
            "Closure completa contém material source não preservado",
        )
    material_count_key = f"counts_for_material_parents_{len(material_parents)}"
    recorded_material_counts = manifest.get("parent_status", {}).get(material_count_key)
    if dependency_parents:
        _require(
            isinstance(recorded_material_counts, dict),
            "Contagens totais de material parents ausentes",
        )
        _require(
            {status: material_counts.get(status, 0) for status in sorted(STATUS_VALUES)}
            == {
                status: recorded_material_counts.get(status, 0)
                for status in sorted(STATUS_VALUES)
            },
            "Contagens de material parents divergentes",
        )
        _require(
            manifest.get("parent_status", {}).get("adjusted_material_parent_count")
            == len(material_parents),
            "Total ajustado de material parents divergente",
        )
        recorded_source_parent_count = manifest.get("parent_status", {}).get(
            "source_parent_record_count"
        )
        if recorded_source_parent_count is not None:
            _require(
                recorded_source_parent_count == len(parents) + len(dependency_parents),
                "Total de registros de source parents divergente",
            )

    batches = manifest.get("batches")
    if batches is not None:
        _require(
            isinstance(batches, list)
            and [item.get("id") for item in batches]
            == ["C1", "C2", "C3", "C4", "C4b", "C4c", "C4d", "C5", "C7"],
            "Histórico de lotes C1-C5/C7 inválido",
        )
        c2 = batches[1]
        _require(c2.get("external_parent_limit") == 16, "Limite C2 divergente")
        _require(c2.get("new_source_parent_count") == 16, "Lote C2 não tem 16")
        _require(
            c2.get("additional_parent_preserved_count") == 12,
            "Segundo lote adicional não tem 12 parents",
        )
        c3 = batches[2]
        _require(c3.get("external_parent_limit") == 16, "Limite C3 divergente")
        _require(c3.get("new_source_parent_count") == 12, "Lote C3 não tem 12")
        _require(
            c3.get("mandatory_parent_preserved_count") == 2
            and c3.get("additional_parent_preserved_count") == 10,
            "Terceiro lote não preserva 2 obrigatórios e 10 adicionais",
        )
        c4 = batches[3]
        _require(c4.get("external_parent_limit") == 20, "Limite C4 divergente")
        _require(c4.get("new_source_parent_count") == 20, "Lote C4 não tem 20")
        _require(
            c4.get("mandatory_parent_preserved_count") == 2
            and c4.get("additional_parent_preserved_count") == 18,
            "Quarto lote não preserva 2 obrigatórios e 18 adicionais",
        )
        c4b = batches[4]
        _require(c4b.get("external_parent_limit") == 12, "Limite C4b divergente")
        _require(c4b.get("new_source_parent_count") == 8, "Lote C4b não tem 8")
        _require(
            c4b.get("preserved_baseline_parent_count") == 6
            and c4b.get("preserved_dependency_parent_count") == 2
            and c4b.get("not_required_baseline_parent_count") == 1,
            "Lote C4b não preserva 6 parents, 2 transitivas e 1 exclusão",
        )
        c4c = batches[5]
        _require(
            c4c.get("external_source_package_limit") == 40
            and c4c.get("material_package_count") == OFFICIAL_CARGO_MATERIAL_COUNT
            and c4c.get("new_source_parent_count") == C4C_CARGO_PRESERVED_COUNT
            and c4c.get("pending_material_package_count") == C4C_CARGO_PENDING_COUNT,
            "Lote C4c não respeita o boundary 40/48",
        )
        c4d = batches[6]
        _require(
            c4d.get("authorized_source_package_count") == 8
            and c4d.get("material_package_count") == OFFICIAL_CARGO_MATERIAL_COUNT
            and c4d.get("new_source_parent_count") == 8
            and c4d.get("pending_material_package_count") == 0
            and c4d.get("preserved_dependency_parent_count")
            == OFFICIAL_CARGO_PRESERVED_COUNT
            and {tuple(str(value).rsplit(" ", 1)) for value in c4d.get("selection", [])}
            == C4D_PACKAGES,
            "Lote C4d não contém exatamente as oito crates autorizadas",
        )
        c5 = batches[7]
        _require(
            c5.get("authorized_source_parent_limit") == 18
            and c5.get("new_source_parent_count") == 14
            and c5.get("original_hardware_identity_count") == 13
            and c5.get("preserved_baseline_parent_count") == 10
            and c5.get("not_required_baseline_parent_count") == 2
            and c5.get("preserved_existing_dependency_parent_count") == 1
            and c5.get("preserved_new_dependency_parent_count") == 3
            and c5.get("shaderc_material_transitive_count") == 3
            and c5.get("shaderc_material_transitive_limit") == 5
            and c5.get("status") == "HARDWARE_HEADER_SOURCE_MATERIAL_CLOSED",
            "Lote C5 não respeita o boundary autorizado de Hardware/Headers",
        )
        c7 = batches[8]
        _require(
            c7.get("authorized_source_parent_count") == 4
            and c7.get("new_source_parent_count") == 4
            and c7.get("preserved_material_parent_count") == 4
            and c7.get("not_required_parent_count") == 1
            and c7.get("gcc_patch_count") == 19
            and c7.get("mingw_patch_count") == 7
            and c7.get("status") == "RUNTIME_TOOLCHAIN_SOURCE_MATERIAL_CLOSED",
            "Lote C7 não fecha exatamente o boundary Runtime/Toolchain autorizado",
        )

    transitives = manifest.get("transitives_discovered", [])
    _require(isinstance(transitives, list), "Mapa de transitivas inválido")
    transitive_components = [item.get("component") for item in transitives]
    _require(
        all(
            isinstance(component, str) and component
            for component in transitive_components
        )
        and len(transitive_components) == len(set(transitive_components)),
        "Dependency transitiva ausente ou duplicada",
    )
    transitive_statuses = Counter(item.get("status") for item in transitives)
    recorded_transitive_counts = manifest.get("parent_status", {}).get(
        "transitive_classification_counts"
    )
    if recorded_transitive_counts is not None:
        _require(
            recorded_transitive_counts == dict(sorted(transitive_statuses.items())),
            "Contagens de dependency transitiva divergentes",
        )
    for item in transitives:
        _require(
            item.get("status") in TRANSITIVE_STATUS_VALUES,
            "Status de dependency transitiva inválido",
        )
        if item.get("materiality") in {"MATERIAL_SOURCE", "MATERIAL_BUILD_INPUT"}:
            _require(
                item.get("status") == "PRESERVED",
                "Nova dependency material não foi preservada",
            )
        if item.get("materiality") == "MATERIAL_SOURCE_PENDING":
            _require(
                item.get("status") == "PENDING",
                "Dependency material pendente não falha de forma fechada",
            )
        if item.get("materiality") == "BUILD_ONLY":
            _require(
                item.get("status") == "BUILD_ONLY",
                "Dependency build-only não foi classificada corretamente",
            )
        dependency_key = item.get("dependency_dedupe_key")
        if dependency_key is not None:
            dependency = next(
                (
                    parent
                    for parent in dependency_parents
                    if parent.get("dedupe_key") == dependency_key
                ),
                None,
            )
            if dependency is None:
                dependency = next(
                    (
                        parent
                        for parent in parents
                        if parent.get("dedupe_key") == dependency_key
                    ),
                    None,
                )
            _require(dependency is not None, "Dependency deduplicada ausente")
            if item.get("status") == "PRESERVED":
                _require(
                    dependency.get("preservation_status") == "PRESERVED",
                    "Dependency transitiva preservada aponta para parent não preservado",
                )
            if item.get("status") == "PENDING":
                _require(
                    dependency.get("preservation_status") == "PENDING",
                    "Dependency transitiva pendente aponta para parent não pendente",
                )
    if enforce_official_baseline:
        _require(
            preserved_count == OFFICIAL_BASELINE_PRESERVED_COUNT,
            "Baseline oficial não tem 80 parents preservados",
        )
        _require(
            manifest.get("parent_status", {}).get("baseline_parent_count")
            == OFFICIAL_BASELINE_PARENT_COUNT,
            "Baseline oficial não tem 84 parents",
        )
        _require(
            material_counts["PRESERVED"] == OFFICIAL_MATERIAL_PRESERVED_COUNT,
            "Closure oficial não tem 138 material parents preservados",
        )
        _require(
            manifest.get("parent_status", {}).get("adjusted_material_parent_count")
            == OFFICIAL_MATERIAL_PARENT_COUNT,
            "Total material oficial não é 138",
        )
        _require(
            manifest.get("parent_status", {}).get("source_parent_record_count")
            == OFFICIAL_SOURCE_PARENT_RECORD_COUNT,
            "Total oficial de registros de source parents não é 142",
        )
        required_dependencies = {
            "mbedtls-framework": (
                "PRESERVED",
                "dde0c4a0e448a0552f18817dcea633bb851fd288",
            ),
            "TF-PSA-Crypto": ("PRESERVED", "73c5da561c8e5253db7b1fb440eda86fde8d8024"),
            "mldsa-native": (
                "PRESERVED",
                "5772b4f4a0105694b1203abb582273f78fa951b7",
            ),
            "graphengine": (
                "PRESERVED",
                "cb5b2ce13384ec2491f0c37256ea210034799f69",
            ),
        }
        actual_dependencies = {
            item.get("component"): (
                item.get("preservation_status"),
                item.get("full_revision"),
            )
            for item in dependency_parents
        }
        _require(
            all(
                actual_dependencies.get(name) == value
                for name, value in required_dependencies.items()
            ),
            "Dependency parents materiais fundamentais divergem",
        )

    if enforce_official_baseline or "closure_islands" in manifest:
        _validate_closure_islands(manifest, parents, dependency_parents)

    btbn = manifest.get("btbn_snapshot")
    _require(isinstance(btbn, dict), "Snapshot BtbN ausente")
    _require(bool(HEX40.fullmatch(str(btbn.get("commit", "")))), "Commit BtbN inválido")
    _require(bool(HEX40.fullmatch(str(btbn.get("tree", "")))), "Tree BtbN inválida")
    _require(
        btbn.get("preservation_status") == "PRESERVED", "Snapshot BtbN não preservado"
    )
    _validate_source_entry(btbn.get("source"))

    patches = manifest.get("patches")
    _require(isinstance(patches, list), "Lista de patches inválida")
    patch_paths: list[str] = []
    for patch in patches:
        producer = patch.get("producer", "BtbN")
        if producer == "crosstool-NG":
            path = _validate_relative_path(
                patch.get("relative_path"), field="patch.relative_path"
            )
            _require(
                path.startswith("metadata/crosstool-ng/")
                and patch.get("producer_commit") == C7_CROSSTOOL_COMMIT
                and patch.get("producer_tree") == C7_CROSSTOOL_TREE
                and patch.get("source_parent") in {"GCC 15.2.0", "mingw-w64 v13.0.0"}
                and isinstance(patch.get("path_at_producer"), str),
                "Patch crosstool-NG C7 sem provenance imutável",
            )
        else:
            _require(producer == "BtbN", "Producer de patch não autorizado")
            path = _validate_relative_path(
                patch.get("path_in_btbn_snapshot"), field="patch.path"
            )
        patch_paths.append(path)
        _require(
            re.fullmatch(r"[0-9A-F]{64}", str(patch.get("sha256", ""))) is not None,
            "SHA de patch inválido",
        )
        _require(
            patch.get("application_status")
            in {
                "APPLIES_CLEANLY",
                "PARTIAL",
                "NOT_APPLICABLE",
                "BLOCKED",
            },
            "Status de patch inválido",
        )
        if patch.get("application_status") == "APPLIES_CLEANLY":
            _require(
                isinstance(patch.get("application_order"), int)
                and patch["application_order"] > 0,
                "Ordem de patch inválida",
            )
            replay = _validate_relative_path(
                patch.get("replay_metadata"), field="patch.replay_metadata"
            )
            _require(replay.startswith("metadata/"), "Replay fora de metadata")
            expected_preimage = (
                "OFFICIAL_RELEASE_ARCHIVE_VERIFIED"
                if producer == "crosstool-NG"
                else "EXACT_UPSTREAM_TREE_VERIFIED"
            )
            _require(
                patch.get("preimage_status") == expected_preimage,
                "Preimage de patch não verificada",
            )
            _require(
                isinstance(patch.get("target_files"), list) and patch["target_files"],
                "Targets de patch ausentes",
            )
        if producer == "crosstool-NG":
            _require(
                patch.get("target_applicability")
                in {"MATERIAL_FOR_WIN64_X86_64", "NOT_APPLICABLE_TO_WIN64_X86_64"},
                "Aplicabilidade target de patch C7 ausente",
            )
            if patch.get("target_applicability") == "MATERIAL_FOR_WIN64_X86_64":
                _require(
                    patch.get("application_status") == "APPLIES_CLEANLY",
                    "Patch material C7 não aplica de forma limpa",
                )
            else:
                _require(
                    patch.get("application_status") == "NOT_APPLICABLE",
                    "Patch não aplicável C7 foi promovido indevidamente",
                )
    _require(len(patch_paths) == len(set(patch_paths)), "Patch duplicado")

    policy = manifest.get("proprietary_source_policy")
    _require(isinstance(policy, dict), "Política de source proprietário ausente")
    _require(
        policy.get("allowed_roots") == ["metadata", "sources"],
        "Roots de staging ampliados",
    )

    if enforce_official_baseline:
        candidate = manifest.get("candidate", {})
        expected = {
            "release": OFFICIAL_RELEASE,
            "variant": OFFICIAL_VARIANT,
            "btbn_commit": OFFICIAL_BTBN_COMMIT,
            "ffmpeg_commit": OFFICIAL_FFMPEG_COMMIT,
        }
        for key, value in expected.items():
            _require(
                candidate.get(key) == value, f"Identidade oficial divergente: {key}"
            )
        _require(
            btbn.get("commit") == OFFICIAL_BTBN_COMMIT,
            "Commit do snapshot BtbN diverge",
        )
        ffmpeg = next(
            (item for item in parents if item.get("component") == "FFmpeg"), None
        )
        _require(
            ffmpeg is not None
            and ffmpeg.get("full_revision") == OFFICIAL_FFMPEG_COMMIT,
            "FFmpeg core diverge",
        )
        lame = next(
            (item for item in parents if item.get("component") == "libmp3lame"), None
        )
        _require(
            lame is not None and lame.get("full_revision") == "6761",
            "LAME r6761 ausente",
        )
        mbedtls = next(
            (item for item in parents if item.get("component") == "mbedtls"), None
        )
        _require(
            mbedtls is not None and mbedtls.get("component_result") == "RESOLVED",
            "mbedTLS não foi resolvido após preservar mldsa-native",
        )
        openssl = next(
            (item for item in parents if item.get("component") == "openssl"), None
        )
        _require(
            openssl is not None and openssl.get("component_result") == "RESOLVED",
            "OpenSSL não foi resolvido após análise dos submódulos",
        )
        openssl_transitives = [
            item
            for item in manifest.get("transitives_discovered", [])
            if str(item.get("component", "")).startswith("openssl/")
        ]
        _require(len(openssl_transitives) == 11, "Mapa OpenSSL não tem 11 submódulos")
        _require(
            all(item.get("status") == "NOT_REQUIRED" for item in openssl_transitives),
            "Submódulo OpenSSL material permanece sem source",
        )
        zimg = next((item for item in parents if item.get("component") == "zimg"), None)
        _require(
            zimg is not None and zimg.get("component_result") == "RESOLVED",
            "zimg não foi resolvido após preservar graphengine",
        )
        c3_components = {
            "fontconfig",
            "gnulib",
            "harfbuzz",
            "libaribcaption",
            "libiconv",
            "libpng",
            "libssh-mirror",
            "libunibreak",
            "srt",
            "zvbi",
        }
        c3_parents = {
            item.get("component"): item
            for item in parents
            if item.get("component") in c3_components
        }
        _require(set(c3_parents) == c3_components, "Parent C3 obrigatório ausente")
        _require(
            all(
                item.get("batch") == "C3"
                and item.get("preservation_status") == "PRESERVED"
                and item.get("component_result") == "RESOLVED"
                for item in c3_parents.values()
            ),
            "Parent C3 não está preservado/resolvido",
        )
        blocked = {
            item.get("component"): item
            for item in parents
            if item.get("preservation_status") == "BLOCKED"
        }
        _require(
            not blocked,
            "Closure C7 oficial ainda contém parent BLOCKED",
        )
        required_not_material = {
            "graphengine/test/googletest",
            "srt/submodules/abi-compliance-checker",
        }
        transitive_map = {
            item.get("component"): item
            for item in manifest.get("transitives_discovered", [])
        }
        _require(
            all(
                transitive_map.get(component, {}).get("status") == "NOT_REQUIRED"
                for component in required_not_material
            ),
            "Submódulo C3 test/ABI permanece material ou sem classificação",
        )
        c4_components = {
            "Little-CMS",
            "brotli",
            "chromaprint",
            "fftw3",
            "gmplib",
            "libbluray",
            "librist",
            "libsamplerate",
            "libudfread",
            "libzmq",
            "lilv",
            "lv2",
            "openapv",
            "openmpt",
            "serd",
            "snappy",
            "sord",
            "sratom",
            "vmaf",
            "zix",
        }
        c4_parents = {
            item.get("component"): item
            for item in parents
            if item.get("component") in c4_components
        }
        _require(set(c4_parents) == c4_components, "Parent C4 obrigatório ausente")
        _require(
            all(
                item.get("batch") == "C4"
                and item.get("preservation_status") == "PRESERVED"
                and item.get("component_result") == "RESOLVED"
                for item in c4_parents.values()
            ),
            "Parent C4 não está preservado/resolvido",
        )
        required_c4_not_material = {
            "chromaprint/src/3rdparty/googletest",
            "chromaprint/src/3rdparty/kissfft",
            "libbluray/contrib/libudfread",
            "librist/contrib/mbedtls",
            "libzmq/external/sha1",
            "libzmq/external/unity",
            "lilv/subprojects/sphinxygen.wrap",
            "openmpt disabled bundled optional libraries",
            "serd/subprojects/sphinxygen.wrap",
            "snappy/third_party/benchmark",
            "snappy/third_party/googletest",
            "sratom/subprojects/sphinxygen.wrap",
            "zix/subprojects/sphinxygen.wrap",
        }
        _require(
            all(
                transitive_map.get(component, {}).get("status") == "NOT_REQUIRED"
                for component in required_c4_not_material
            ),
            "Dependency C4 não material permanece pendente ou sem classificação",
        )
        required_c4_bundled = {
            "Little-CMS/plugins/fast_float",
            "Little-CMS/plugins/threaded",
            "chromaprint included FFmpeg portions",
            "libzmq/external/wepoll",
            "openmpt/include/minimp3",
            "vmaf/libvmaf/src/feature/third_party/xiph",
        }
        _require(
            all(
                transitive_map.get(component, {}).get("status")
                == "PRESERVED_WITH_PARENT"
                for component in required_c4_bundled
            ),
            "Código bundled material C4 não está preservado com o parent",
        )
        c4b_components = {
            "LCEVCdec",
            "game-music-emu",
            "libjxl",
            "libplacebo",
            "openal-soft",
            "rav1e",
        }
        c4b_parents = {
            item.get("component"): item
            for item in parents
            if item.get("component") in c4b_components
        }
        _require(set(c4b_parents) == c4b_components, "Parent C4b obrigatório ausente")
        _require(
            all(
                item.get("batch") == "C4b"
                and item.get("preservation_status") == "PRESERVED"
                and item.get("source_scope") == "DISTRIBUTED_PAIR_SOURCE_PARENT"
                and bool(item.get("distributed_pair_evidence"))
                for item in c4b_parents.values()
            ),
            "Parent C4b material não está preservado ou evidenciado",
        )
        sdl = next((item for item in parents if item.get("component") == "SDL"), None)
        _require(
            sdl is not None
            and sdl.get("source_scope") == "BTBN_BUILD_PARENT"
            and sdl.get("distributed_pair_status")
            == "NOT_REQUIRED_FOR_DISTRIBUTED_PAIR"
            and sdl.get("component_result") == "NOT_REQUIRED_FOR_DISTRIBUTED_PAIR"
            and sdl.get("preservation_status") == "NOT_REQUIRED"
            and sdl.get("source") is None,
            "SDL não está classificado como exclusivo do ffplay",
        )
        dependency_map = {item.get("component"): item for item in dependency_parents}
        for component in ("fast_float", "highway"):
            _require(
                dependency_map.get(component, {}).get("preservation_status")
                == "PRESERVED"
                and dependency_map[component].get("batch") == "C4b",
                f"Dependency C4b preservada ausente: {component}",
            )
        vulkan_submodule = dependency_map.get(
            "Vulkan-Headers (libplacebo submodule)", {}
        )
        _require(
            vulkan_submodule.get("preservation_status") == "PRESERVED"
            and vulkan_submodule.get("batch") == "C5"
            and vulkan_submodule.get("island") == "hardware_headers",
            "Vulkan-Headers de libplacebo não foi preservado em Hardware/Headers",
        )
        cargo_dependencies = [
            item
            for item in dependency_parents
            if str(item.get("component", "")).startswith("rav1e crate ")
        ]
        cargo_preserved = [
            item
            for item in cargo_dependencies
            if item.get("preservation_status") == "PRESERVED"
        ]
        cargo_pending = [
            item
            for item in cargo_dependencies
            if item.get("preservation_status") == "PENDING"
        ]
        _require(
            len(cargo_dependencies) == OFFICIAL_CARGO_MATERIAL_COUNT
            and len(cargo_preserved) == OFFICIAL_CARGO_PRESERVED_COUNT
            and len(cargo_pending) == OFFICIAL_CARGO_PENDING_COUNT
            and all(
                item.get("batch") in {"C4c", "C4d"}
                and item.get("source_type") == "Cargo Registry"
                and item.get("cargo_dependency_type")
                in {"RUNTIME_MATERIAL", "CODEGEN_MATERIAL"}
                and item.get("upstream") == CARGO_REGISTRY_SOURCE
                and re.fullmatch(
                    r"[0-9a-f]{64}", str(item.get("cargo_lock_checksum", ""))
                )
                for item in cargo_dependencies
            ),
            "Inventário material Cargo C4d do rav1e diverge",
        )
        _require(
            {
                (str(item.get("cargo_package")), str(item.get("cargo_version")))
                for item in cargo_dependencies
                if item.get("batch") == "C4d"
            }
            == C4D_PACKAGES
            and sum(item.get("batch") == "C4c" for item in cargo_dependencies)
            == C4C_CARGO_PRESERVED_COUNT,
            "Boundary histórico C4c/C4d das crates diverge",
        )
        _require(
            len({item.get("cargo_package") for item in cargo_dependencies})
            == OFFICIAL_CARGO_MATERIAL_COUNT
            and all(
                item.get("component")
                == f"rav1e crate {item.get('cargo_package')} {item.get('cargo_version')}"
                and item.get("cargo_target_applicability") == "x86_64-pc-windows-gnu"
                for item in cargo_dependencies
            ),
            "Identidade/target das crates C4d diverge",
        )
        _require(
            all(
                item.get("source", {}).get("authority")
                == "cargo_lock_and_crates_io_index_checksum"
                and str(item["source"].get("sha256", "")).lower()
                == item["cargo_lock_checksum"]
                for item in cargo_preserved
            )
            and not cargo_pending,
            "Crate C4d preservada não falha de forma fechada",
        )
        for item in cargo_dependencies:
            if item.get("cargo_dependency_type") == "CODEGEN_MATERIAL":
                _require(
                    isinstance(item.get("cargo_codegen_role"), str)
                    and bool(item["cargo_codegen_role"]),
                    "Crate codegen material sem papel explícito",
                )
        rav1e = c4b_parents["rav1e"]
        rav1e_metadata = {
            item.get("relative_path") for item in rav1e.get("metadata", [])
        }
        _require(
            {
                "metadata/rav1e-cargo-binary-evidence.json",
                "metadata/rav1e-cargo-lock-inventory.json",
                "metadata/rav1e-cargo-closure-c4c.json",
                "metadata/rav1e-cargo-closure-c4d.json",
            }.issubset(rav1e_metadata)
            and rav1e.get("component_result") == "RESOLVED",
            "Closure Cargo material do rav1e não está resolvida/evidenciada",
        )
        libplacebo = c4b_parents["libplacebo"]
        _require(
            libplacebo.get("component_result") == "RESOLVED",
            "libplacebo não foi resolvido após preservar Vulkan-Headers",
        )
        for component in ("openal-soft", "game-music-emu", "libjxl", "LCEVCdec"):
            _require(
                c4b_parents[component].get("component_result") == "RESOLVED",
                f"Parent C4b deveria estar resolvido: {component}",
            )
        required_c4b_transitives = {
            "libplacebo/3rdparty/fast_float": "PRESERVED",
            "libplacebo/3rdparty/Vulkan-Headers": "PRESERVED",
            "libplacebo/3rdparty/jinja": "BUILD_ONLY",
            "libplacebo/3rdparty/markupsafe": "BUILD_ONLY",
            "libjxl/third_party/highway": "PRESERVED",
            "libjxl/third_party/brotli": "PRESERVED",
            "libjxl/third_party/lcms": "PRESERVED",
            "libjxl/third_party/zlib": "PRESERVED",
            "libjxl/third_party/libpng": "PRESERVED",
            "openal-soft/fmt-11.2.0": "PRESERVED_WITH_PARENT",
            "openal-soft/gsl": "PRESERVED_WITH_PARENT",
            "game-music-emu/gme/ext/emu2413": "PRESERVED_WITH_PARENT",
        }
        _require(
            all(
                transitive_map.get(component, {}).get("status") == status
                for component, status in required_c4b_transitives.items()
            ),
            "Mapa de transitivas C4b diverge",
        )
        cargo_transitives = [
            item
            for item in manifest.get("transitives_discovered", [])
            if str(item.get("component", "")).startswith("rav1e/crate/")
        ]
        _require(
            len(cargo_transitives) == OFFICIAL_CARGO_MATERIAL_COUNT
            and all(
                item.get("status") == "PRESERVED"
                and item.get("materiality") == "MATERIAL_SOURCE"
                for item in cargo_transitives
            ),
            "Transitivas materiais Cargo do rav1e divergem",
        )
        cargo_closure = manifest.get("rav1e_cargo_closure")
        _require(isinstance(cargo_closure, dict), "Closure Cargo C4d ausente")
        _require(
            cargo_closure.get("status") == "RESOLVED"
            and cargo_closure.get("material_package_counts")
            == {
                "CODEGEN_MATERIAL": 13,
                "PENDING": OFFICIAL_CARGO_PENDING_COUNT,
                "PRESERVED": OFFICIAL_CARGO_PRESERVED_COUNT,
                "RUNTIME_MATERIAL": 35,
                "TOTAL": OFFICIAL_CARGO_MATERIAL_COUNT,
            }
            and cargo_closure.get("classification_counts")
            == {
                "BUILD_ONLY": 32,
                "CODEGEN_MATERIAL": 13,
                "DEV_ONLY": 21,
                "OPTIONAL_DISABLED": 110,
                "RUNTIME_MATERIAL": 35,
                "TARGET_NOT_APPLICABLE": 2,
                "UNREACHABLE": 59,
            },
            "Contagens da closure Cargo C4d divergem",
        )
        _require(
            cargo_closure.get("cargo_update_cc", {}).get("status")
            == "REPRODUCIBILITY_PENDING"
            and cargo_closure.get("cargo_update_cc", {}).get("classification")
            == "BUILD_ONLY"
            and cargo_closure.get("rust_runtime_materiality", {}).get("status")
            == "NEEDS_REVIEW",
            "cc/Rust runtime não permanecem em camada especializada",
        )
        pair_scope = manifest.get("distributed_pair_scope")
        _require(isinstance(pair_scope, dict), "Escopo do par distribuído ausente")
        _require(
            pair_scope.get("distributed_programs") == ["ffmpeg.exe", "ffprobe.exe"]
            and pair_scope.get("excluded_programs") == ["ffplay.exe"]
            and isinstance(pair_scope.get("evidence"), list)
            and {item.get("relative_path") for item in pair_scope["evidence"]}
            == {
                "metadata/c4b-distributed-pair-materiality.json",
                "metadata/c5-hardware-header-materiality.json",
                "metadata/c7-runtime-toolchain-materiality.json",
            },
            "Escopo/evidência ffmpeg+ffprobe diverge",
        )
        remaining = manifest.get("remaining_pending_classification")
        _require(isinstance(remaining, dict), "Classificação pendente C4b ausente")
        _require(
            remaining.get("NORMAL_LIBRARY_PENDING") == []
            and remaining.get("NORMAL_LIBRARY_UNKNOWN_COUNT") == 0
            and remaining.get("NORMAL_LIBRARY_UNKNOWN_INVENTORY")
            == "metadata/rav1e-cargo-closure-c4d.json",
            "Closure normal/Cargo C4d diverge",
        )
        normal_closure = manifest.get("normal_library_closure")
        _require(
            isinstance(normal_closure, dict)
            and normal_closure.get("status") == "RESOLVED"
            and normal_closure.get("pending_material_source_count")
            == OFFICIAL_CARGO_PENDING_COUNT
            and normal_closure.get("unknown_cargo_entry_count") == 0
            and normal_closure.get("next") == "RUNTIME_TOOLCHAIN",
            "Veredito da ilha normal C4d diverge",
        )
        hardware_pending = [
            item["dedupe_key"]
            for item in manifest["closure_islands"]["hardware_headers"]["members"]
            if item["status"] == "PENDING"
        ]
        _require(
            remaining.get("HARDWARE_HEADER_PENDING") == hardware_pending
            and hardware_pending == [],
            "Classificação Hardware/Headers C5 permanece pendente",
        )
        _require(
            remaining.get("RUNTIME_TOOLCHAIN_BLOCKED") == []
            and remaining.get("RUNTIME_TOOLCHAIN_PENDING") == []
            and remaining.get("RUNTIME_TOOLCHAIN_UNKNOWN_COUNT") == 0,
            "Runtime/toolchain C7 permanece pendente, bloqueado ou desconhecido",
        )
        _validate_c5_hardware_closure(
            manifest, parents, dependency_parents, transitive_map
        )
        _validate_c7_runtime_closure(manifest, parents, transitive_map)
        excluded_components = manifest.get("excluded_non_material_components")
        _require(
            isinstance(excluded_components, list)
            and {
                item.get("component")
                for item in excluded_components
                if item.get("class") == "E" and item.get("status") == "NOT_REQUIRED"
            }
            == {
                "avisynth",
                "davs2",
                "libdvdcss",
                "libdvdnav",
                "libdvdread",
                "frei0r",
                "rubberband",
                "vidstab",
                "x264",
                "x265",
                "xavs2",
                "xvid",
            },
            "Componentes GPL/recipe E excluídos divergem",
        )
        _verify_candidate_baseline(parents)


def _validate_c7_runtime_closure(
    manifest: dict[str, Any],
    parents: list[dict[str, Any]],
    transitive_map: dict[str, dict[str, Any]],
) -> None:
    """Valida a closure técnica C7 sem promover o candidato nem emitir parecer legal."""
    by_component = {str(item.get("component")): item for item in parents}
    gcc = by_component.get("GCC 15.2.0", {})
    mingw_base = by_component.get("mingw-w64 v13.0.0", {})
    mingw_final = by_component.get("mingw-w64", {})
    mingw_std = by_component.get("mingw-std-threads", {})
    rust = by_component.get("rust-src 1.97.1", {})
    _require(
        gcc.get("batch") == "C7"
        and gcc.get("preservation_status") == "PRESERVED"
        and gcc.get("source", {}).get("sha256") == C7_GCC_SHA256
        and gcc.get("materiality") == "MATERIAL_SOURCE_PARENT",
        "Parent GCC 15.2.0 C7 ausente ou divergente",
    )
    _require(
        mingw_base.get("batch") == "C7"
        and mingw_base.get("preservation_status") == "PRESERVED"
        and mingw_base.get("source", {}).get("sha256") == C7_MINGW_BASE_SHA256
        and mingw_base.get("revision_role") == "MINGW_BASE_TOOLCHAIN_SOURCE",
        "Parent mingw-w64 base C7 ausente ou divergente",
    )
    _require(
        mingw_final.get("batch") == "C7"
        and mingw_final.get("preservation_status") == "PRESERVED"
        and mingw_final.get("full_revision") == C7_MINGW_FINAL_COMMIT
        and mingw_final.get("tree") == C7_MINGW_FINAL_TREE
        and mingw_final.get("revision_role") == "MINGW_FINAL_OVERLAY_SOURCE",
        "Parent mingw-w64 final C7 ausente ou divergente",
    )
    _require(
        mingw_base.get("full_revision") != mingw_final.get("full_revision")
        and mingw_base.get("source", {}).get("sha256")
        != mingw_final.get("source", {}).get("sha256"),
        "Revisões mingw base/final foram deduplicadas indevidamente",
    )
    _require(
        mingw_std.get("batch") == "C7"
        and mingw_std.get("preservation_status") == "NOT_REQUIRED"
        and mingw_std.get("distributed_pair_status")
        == "NOT_REQUIRED_FOR_DISTRIBUTED_PAIR"
        and mingw_std.get("materiality") == "BUILD_REPRODUCIBILITY_INPUT"
        and mingw_std.get("source") is None,
        "mingw-std-threads não permanece NOT_REQUIRED",
    )
    _require(
        rust.get("batch") == "C7"
        and rust.get("preservation_status") == "PRESERVED"
        and rust.get("full_revision") == C7_RUST_COMMIT
        and rust.get("version") == "1.97.1"
        and rust.get("source", {}).get("sha256") == C7_RUST_SHA256,
        "Parent rust-src 1.97.1 C7 ausente ou divergente",
    )

    expected_coverage = {
        "GCC/libgcc",
        "GCC/libgcc_eh",
        "GCC/libstdc++-v3",
        "GCC/libgomp",
        "mingw-w64 v13.0.0/headers",
        "mingw-w64 v13.0.0/CRT",
        "mingw-w64 v13.0.0/winpthreads",
        "mingw-w64 final/headers",
        "mingw-w64 final/CRT",
        "mingw-w64 final/startup",
        "mingw-w64 final/import-library-generators",
        "mingw-w64 final/winpthreads",
        "rust-src/core",
        "rust-src/alloc",
        "rust-src/std",
        "rust-src/panic_abort",
        "rust-src/panic_unwind",
        "rust-src/compiler_builtins",
        "rust-src/backtrace",
        "rust-src/windows-gnu-pal",
    }
    _require(
        all(
            transitive_map.get(component, {}).get("status") == "PRESERVED_WITH_PARENT"
            and transitive_map[component].get("materiality")
            == "MATERIAL_COVERED_BY_PARENT"
            and transitive_map[component].get("batch") == "C7"
            for component in expected_coverage
        ),
        "Cobertura runtime C7 por parent está incompleta",
    )

    closure = manifest.get("runtime_toolchain_closure")
    _require(isinstance(closure, dict), "Closure Runtime/Toolchain C7 ausente")
    _require(
        closure.get("status") == "RESOLVED"
        and closure.get("material_source_gap_count") == 0
        and closure.get("unknown_materiality_count") == 0
        and closure.get("pending_material_source_count") == 0
        and closure.get("blocked_material_source_count") == 0
        and set(closure.get("coverage", [])) == expected_coverage,
        "Veredito Runtime/Toolchain C7 não está fechado",
    )
    _require(
        closure.get("build_reproducibility", {}).get("status") == "PARTIAL"
        and set(closure["build_reproducibility"].get("build_only", []))
        == {
            "GCC compiler",
            "binutils 2.46.0",
            "crosstool-NG",
            "rustc",
            "Cargo",
            "cargo-c",
            "cc crate post-update",
        }
        and set(closure.get("system_runtime", []))
        == {"UCRT/API sets", "Windows system DLLs"},
        "Camadas BUILD_ONLY/system runtime C7 foram promovidas indevidamente",
    )
    evidence = closure.get("evidence")
    _require(
        isinstance(evidence, dict)
        and evidence.get("relative_path")
        == "metadata/c7-runtime-toolchain-materiality.json",
        "Evidência Runtime/Toolchain C7 ausente",
    )

    c7_patches = [
        item
        for item in manifest.get("patches", [])
        if item.get("producer") == "crosstool-NG"
    ]
    _require(
        len(c7_patches) == 26
        and sum(item.get("source_parent") == "GCC 15.2.0" for item in c7_patches) == 19
        and sum(item.get("source_parent") == "mingw-w64 v13.0.0" for item in c7_patches)
        == 7
        and all(
            item.get("application_status") not in {"PARTIAL", "BLOCKED"}
            for item in c7_patches
        ),
        "Patchset material C7 não está integralmente classificado/preservado",
    )


def _validate_c5_hardware_closure(
    manifest: dict[str, Any],
    parents: list[dict[str, Any]],
    dependency_parents: list[dict[str, Any]],
    transitive_map: dict[str, dict[str, Any]],
) -> None:
    """Valida materialidade e preservação fail-closed da ilha C5."""
    all_parents = [*parents, *dependency_parents]
    by_identity = {
        (str(item.get("component")), str(item.get("full_revision"))): item
        for item in all_parents
    }
    _require(
        len(by_identity) == len(all_parents),
        "Identidade/revisão de source parent C5 duplicada",
    )

    expected_material = {**C5_MATERIAL_REVISIONS, **C5_SHADERC_DEPENDENCIES}
    expected_shapes = {
        "AMF": ("INTERFACE_DECLARATIONS_MATERIAL", True, False),
        "OpenCL-Headers": ("HEADER_CODE_MATERIAL", True, False),
        "OpenCL-ICD-Loader": ("LOADER_MATERIAL", False, True),
        "SPIRV-Cross": ("STATIC_CODE_MATERIAL", False, True),
        "SPIRV-Headers": ("HEADER_CODE_MATERIAL", True, False),
        "Vulkan-Headers (libplacebo submodule)": (
            "HEADER_CODE_MATERIAL",
            True,
            False,
        ),
        "Vulkan-Shim-Loader": ("STATIC_CODE_MATERIAL", False, True),
        "libva": ("LOADER_MATERIAL", False, True),
        "libvpl": ("LOADER_MATERIAL", False, True),
        "nv-codec-headers": ("HEADER_CODE_MATERIAL", True, False),
        "shaderc": ("STATIC_CODE_MATERIAL", False, True),
        "shaderc/glslang": ("STATIC_CODE_MATERIAL", False, True),
        "shaderc/SPIRV-Tools": ("STATIC_CODE_MATERIAL", False, True),
        "shaderc/SPIRV-Headers": ("HEADER_CODE_MATERIAL", True, False),
    }
    for component, revision in expected_material.items():
        item = by_identity.get((component, revision))
        _require(item is not None, f"Source material C5 ausente: {component}")
        materiality, header_only, static_code = expected_shapes[component]
        _require(
            item.get("batch") == "C5"
            and item.get("preservation_status") == "PRESERVED"
            and item.get("distributed_pair_status") == "MATERIAL_TO_DISTRIBUTED_PAIR"
            and item.get("component_result") == "RESOLVED"
            and item.get("materiality") == materiality
            and item.get("header_only") is header_only
            and item.get("static_code") is static_code
            and isinstance(item.get("materiality_roles"), list)
            and bool(item["materiality_roles"])
            and isinstance(item.get("target_applicability"), str)
            and bool(item["target_applicability"])
            and "NOT_APPLICABLE" not in item["target_applicability"]
            and isinstance(item.get("external_runtime"), list)
            and isinstance(item.get("external_driver"), list)
            and isinstance(item.get("source"), dict),
            f"Materialidade/source C5 diverge: {component}",
        )

    nv_records = {
        str(item.get("full_revision")): item
        for item in parents
        if item.get("component") == "nv-codec-headers"
    }
    _require(
        set(nv_records)
        == {*C5_SUPERSEDED_NV, C5_MATERIAL_REVISIONS["nv-codec-headers"]},
        "Revisões NVIDIA C5 divergem",
    )
    for revision, applicability in C5_SUPERSEDED_NV.items():
        item = nv_records[revision]
        _require(
            item.get("batch") == "C5"
            and item.get("preservation_status") == "NOT_REQUIRED"
            and item.get("distributed_pair_status")
            == "NOT_REQUIRED_FOR_DISTRIBUTED_PAIR"
            and item.get("materiality") == "NOT_REQUIRED_FOR_DISTRIBUTED_PAIR"
            and item.get("revision_role") == "SUPERSEDED_BUILD_INPUT"
            and item.get("target_applicability") == applicability
            and item.get("source_scope") == "BTBN_BUILD_PARENT"
            and item.get("source") is None
            and bool(item.get("distributed_pair_evidence")),
            "Revisão NVIDIA superseded foi promovida ou ficou sem evidência",
        )

    standalone_vulkan = next(
        item for item in parents if item.get("component") == "Vulkan-Headers"
    )
    libplacebo_vulkan = by_identity[
        (
            "Vulkan-Headers (libplacebo submodule)",
            C5_MATERIAL_REVISIONS["Vulkan-Headers (libplacebo submodule)"],
        )
    ]
    _require(
        standalone_vulkan.get("full_revision") != libplacebo_vulkan.get("full_revision")
        and standalone_vulkan.get("tree") != libplacebo_vulkan.get("tree"),
        "Vulkan-Headers distintos foram deduplicados incorretamente",
    )

    for component, revision in C5_SHADERC_DEPENDENCIES.items():
        transitive = transitive_map.get(component, {})
        _require(
            transitive.get("batch") == "C5"
            and transitive.get("status") == "PRESERVED"
            and transitive.get("materiality") == "MATERIAL_SOURCE"
            and transitive.get("revision") == revision,
            f"Dependency material shaderc diverge: {component}",
        )
    shaderc_test_only = {
        "shaderc/abseil_cpp": "dbf88f932096c7f7714356e919f04749eb87c3e9",
        "shaderc/effcee": "910ed15722d5d05c9d71ecf36c1a22243cb79b02",
        "shaderc/googletest": "52eb8108c5bdec04579160ae17225d66034bd723",
        "shaderc/re2": "927f5d53caf8111721e734cf24724686bb745f55",
    }
    for component, revision in shaderc_test_only.items():
        transitive = transitive_map.get(component, {})
        _require(
            transitive.get("batch") == "C5"
            and transitive.get("status") == "NOT_REQUIRED"
            and transitive.get("materiality") == "TEST_ONLY"
            and transitive.get("revision") == revision,
            f"Dependency test-only shaderc foi promovida: {component}",
        )

    libva = by_identity[("libva", C5_MATERIAL_REVISIONS["libva"])]
    _require(
        "WIN64_LGPL_8_1_STATIC" in libva["target_applicability"]
        and "with_win32" in str(libva.get("dependency_coverage", "")),
        "Aplicabilidade Windows da libva diverge",
    )
    libvpl = by_identity[("libvpl", C5_MATERIAL_REVISIONS["libvpl"])]
    _require(
        "libmfx64-gen.dll" in libvpl["external_runtime"]
        and all("libmfx" not in name.lower() for name in expected_material),
        "Runtime externo oneVPL foi tratado como source material",
    )

    closure = manifest.get("hardware_header_closure")
    _require(
        isinstance(closure, dict)
        and closure.get("status") == "RESOLVED"
        and closure.get("original_identity_count") == 13
        and closure.get("new_material_transitive_count") == 3
        and closure.get("new_material_transitives") == list(C5_SHADERC_DEPENDENCIES)
        and closure.get("pending_material_source_count") == 0
        and closure.get("unknown_count") == 0,
        "Closure C5 Hardware/Headers diverge",
    )
    interfaces = closure.get("external_interfaces")
    _require(
        isinstance(interfaces, list)
        and len(interfaces) == 6
        and all(
            item.get("classification") == "EXTERNAL_RUNTIME_INTERFACE_AND_DRIVER"
            and item.get("distributed") is False
            and isinstance(item.get("runtime"), list)
            and bool(item["runtime"])
            for item in interfaces
        ),
        "Runtime/driver externo foi promovido a material distribuído",
    )


def _validate_closure_islands(
    manifest: dict[str, Any],
    parents: list[dict[str, Any]],
    dependency_parents: list[dict[str, Any]],
) -> None:
    islands = manifest.get("closure_islands")
    required_names = {
        "codec_audio_video",
        "network_tls",
        "text_rendering",
        "compression",
        "processing",
        "hardware_headers",
        "runtime_toolchain",
    }
    _require(
        isinstance(islands, dict) and set(islands) == required_names,
        "Mapa de ilhas C4 ausente ou divergente",
    )
    authoritative = {
        item["dedupe_key"]: item["preservation_status"]
        for item in [*parents, *dependency_parents]
    }
    seen: set[str] = set()
    for name, island in islands.items():
        _require(isinstance(island, dict), f"Ilha inválida: {name}")
        members = island.get("members")
        _require(isinstance(members, list) and members, f"Ilha vazia: {name}")
        counts = Counter()
        for member in members:
            _require(isinstance(member, dict), f"Membro de ilha inválido: {name}")
            dedupe = member.get("dedupe_key")
            _require(
                dedupe in authoritative and dedupe not in seen,
                f"Parent de ilha ausente ou duplicado: {dedupe}",
            )
            _require(
                member.get("status") == authoritative[dedupe],
                f"Status de ilha diverge: {dedupe}",
            )
            seen.add(dedupe)
            counts[str(member["status"])] += 1
        _require(
            island.get("counts") == dict(sorted(counts.items())),
            f"Contagens da ilha divergem: {name}",
        )
        unresolved = counts["PENDING"] + counts["CONDITIONAL"] + counts["BLOCKED"]
        expected_status = (
            "RESOLVED"
            if unresolved == 0
            else "NOT_STARTED"
            if counts["PRESERVED"] == 0
            else "PARTIAL"
        )
        _require(
            island.get("status") == expected_status,
            f"Status agregado da ilha diverge: {name}",
        )
    _require(seen == set(authoritative), "Mapa de ilhas não cobre todos os parents")
    _require(
        islands["network_tls"]["status"] == "RESOLVED",
        "Ilha Network/TLS não está resolvida",
    )
    _require(
        islands["text_rendering"]["status"] == "RESOLVED",
        "Ilha Text/Rendering não está resolvida",
    )
    _require(
        islands["compression"]["status"] == "RESOLVED",
        "Ilha Compression não está resolvida",
    )
    _require(
        islands["processing"]["status"] == "RESOLVED",
        "Ilha Processing não está resolvida para o par distribuído",
    )
    _require(
        islands["codec_audio_video"]["status"] == "RESOLVED",
        "Ilha Codec/Audio/Video não está resolvida",
    )
    _require(
        islands["hardware_headers"]["status"] == "RESOLVED",
        "Ilha Hardware/Headers não está resolvida",
    )
    _require(
        islands["runtime_toolchain"]["status"]
        == (
            "RESOLVED"
            if manifest.get("source_correspondence") == OFFICIAL_SOURCE_CORRESPONDENCE
            else "NOT_STARTED"
        ),
        "Status da ilha Runtime/Toolchain diverge da source correspondence",
    )


def _validate_source_entry(source: Any) -> None:
    _require(isinstance(source, dict), "Entrada de source inválida")
    path = _validate_relative_path(
        source.get("relative_path"), field="source.relative_path"
    )
    _require(path.startswith("sources/"), "Source fora da raiz sources")
    _require(
        isinstance(source.get("size"), int) and source["size"] > 0,
        "Tamanho de source inválido",
    )
    _require(
        re.fullmatch(r"[0-9A-F]{64}", str(source.get("sha256", ""))) is not None,
        "SHA-256 de source inválido",
    )
    _require(
        source.get("authority")
        in {
            "local_calculated_verified_revision",
            "cargo_lock_and_crates_io_index_checksum",
            "official_release_checksum_and_inventory",
            "official_rust_channel_manifest",
        },
        "Autoridade de source inválida",
    )
    license_files = source.get("license_files")
    _require(isinstance(license_files, list), "Lista de licenças upstream inválida")
    if not license_files:
        _require(
            source.get("authority") == "cargo_lock_and_crates_io_index_checksum"
            and source.get("license_files_absent_from_published_crate") is True
            and isinstance(source.get("license_declared_upstream"), str)
            and bool(source["license_declared_upstream"])
            and isinstance(source.get("license_files_note"), str)
            and bool(source["license_files_note"]),
            "Ausência de arquivo de licença Cargo não documentada",
        )
    _require(
        isinstance(source.get("required_files"), list), "Arquivos requeridos ausentes"
    )
    verification = source.get("tree_verification")
    _require(isinstance(verification, dict), "Verificação de tree ausente")
    if verification.get("strategy") == "official_release_archive_inventory":
        _require(
            isinstance(verification.get("archive_file_count"), int)
            and verification["archive_file_count"] > 0
            and isinstance(verification.get("archive_payload_size"), int)
            and verification["archive_payload_size"] > 0
            and re.fullmatch(
                r"[0-9A-F]{64}", str(verification.get("path_inventory_sha256", ""))
            )
            is not None,
            "Inventário de release archive inválido",
        )
    if verification.get("strategy") == "git_tree_material_subset_comparison":
        subset_paths = verification.get("material_subset_paths")
        _require(
            source.get("archive_strategy") == "exact_material_subset_from_git_tree"
            and isinstance(subset_paths, list)
            and len(subset_paths) == verification.get("expected_blob_count")
            and len(subset_paths) == len(set(subset_paths)),
            "Contrato de subconjunto material inválido",
        )


def _verify_candidate_baseline(parents: list[dict[str, Any]]) -> None:
    try:
        candidate = json.loads(OFFICIAL_CANDIDATE_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SourceBundleError(
            "Provenance candidata oficial ausente ou inválida"
        ) from error
    baseline = candidate.get("source_parents", {}).get("parents")
    _require(
        isinstance(baseline, list) and len(baseline) == 81,
        "Baseline candidata não tem 81 parents",
    )
    expected = {
        item["dedupe_key"]: (
            item.get("component"),
            item.get("materiality"),
            item.get("pin"),
            item.get("repository"),
        )
        for item in baseline
    }
    actual = {
        item["dedupe_key"]: (
            item.get("component"),
            item.get("class"),
            item.get("recipe_pin"),
            item.get("upstream"),
        )
        for item in parents
        if item["dedupe_key"] in expected
    }
    _require(actual == expected, "Mapa dos 81 parents diverge da provenance candidata")
    c7_additions = [item for item in parents if item["dedupe_key"] not in expected]
    _require(
        {item.get("component") for item in c7_additions}
        == {"GCC 15.2.0", "mingw-w64 v13.0.0", "rust-src 1.97.1"}
        and all(item.get("batch") == "C7" for item in c7_additions),
        "Parents adicionais C7 divergem do boundary autorizado",
    )
    excluded_gpl = {
        "avisynth",
        "davs2",
        "dvdread",
        "dvdnav",
        "frei0r",
        "rubberband",
        "vidstab",
        "x264",
        "x265",
        "xavs2",
        "xvid",
    }
    declared_excluded = set(
        candidate.get("candidate", {})
        .get("capabilities", {})
        .get("gpl_components_confirmed_disabled", [])
    )
    _require(
        declared_excluded == excluded_gpl,
        "Componentes GPL excluídos da variante LGPL divergem",
    )
    parent_names = {str(item.get("component", "")).lower() for item in parents}
    _require(
        excluded_gpl.isdisjoint(parent_names),
        "Componente GPL excluído foi incluído na source closure",
    )


def load_manifest(
    path: Path = DEFAULT_MANIFEST, *, enforce_official_baseline: bool = True
) -> dict[str, Any]:
    """Carrega manifesto canônico e valida seu contrato fail-closed."""
    try:
        content = path.read_bytes()
        manifest = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SourceBundleError("Manifesto BTBN source ausente ou inválido") from error
    _require(isinstance(manifest, dict), "Manifesto BTBN source não é objeto")
    _require(content == formatted_json_bytes(manifest), "Manifesto JSON não canônico")
    if enforce_official_baseline:
        _require(
            sha256_bytes(content) == OFFICIAL_MANIFEST_SHA256,
            "Hash do manifesto oficial diverge",
        )
    _validate_manifest(manifest, enforce_official_baseline=enforce_official_baseline)
    return manifest


def _add_expected(expected: dict[str, dict[str, Any]], entry: dict[str, Any]) -> None:
    relative = _validate_relative_path(
        entry.get("relative_path"), field="entry.relative_path"
    )
    _require(relative not in expected, f"Arquivo de staging duplicado: {relative}")
    _require(
        isinstance(entry.get("size"), int) and entry["size"] >= 0, "Tamanho inválido"
    )
    _require(
        re.fullmatch(r"[0-9A-F]{64}", str(entry.get("sha256", ""))) is not None,
        "SHA-256 inválido",
    )
    expected[relative] = {
        "relative_path": relative,
        "sha256": entry["sha256"],
        "size": entry["size"],
    }


def expected_staging_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Retorna os sources e metadata explicitamente autorizados no staging."""
    expected: dict[str, dict[str, Any]] = {}
    btbn = manifest["btbn_snapshot"]
    _add_expected(expected, btbn["source"])
    for entry in btbn["metadata"]:
        _add_expected(expected, entry)
    for parent in [*manifest["parents"], *manifest.get("dependency_parents", [])]:
        if parent["preservation_status"] != "PRESERVED":
            continue
        _add_expected(expected, parent["source"])
        for entry in parent["metadata"]:
            _add_expected(expected, entry)
    pair_scope = manifest.get("distributed_pair_scope")
    if isinstance(pair_scope, dict):
        for entry in pair_scope.get("evidence", []):
            _add_expected(expected, entry)
    for patch in manifest.get("patches", []):
        if patch.get("producer") == "crosstool-NG":
            _add_expected(expected, patch)
    return expected


def _archive_files(path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path, "r") as archive:
                infos = archive.infolist()
                _require(
                    len(infos) == len({info.filename for info in infos}),
                    "Archive contém caminhos duplicados",
                )
                for info in infos:
                    if info.is_dir():
                        continue
                    name = _validate_relative_path(
                        info.filename.rstrip("/"), field="archive.path"
                    )
                    files[name] = archive.read(info)
        else:
            with tarfile.open(path, "r:*") as archive:
                members = archive.getmembers()
                names = [member.name for member in members]
                _require(
                    len(names) == len(set(names)), "Archive contém caminhos duplicados"
                )
                for member in members:
                    if member.isdir():
                        continue
                    name = _validate_relative_path(
                        member.name.rstrip("/"), field="archive.path"
                    )
                    if member.issym():
                        files[name] = member.linkname.encode("utf-8")
                    elif member.isfile():
                        stream = archive.extractfile(member)
                        _require(stream is not None, f"Membro ilegível: {name}")
                        files[name] = stream.read()
                    elif not member.islnk():
                        raise SourceBundleError(f"Tipo de membro não aceito: {name}")
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise SourceBundleError(f"Archive inválido: {path.name}") from error
    return files


def _release_archive_inventory(path: Path, root: str | None) -> dict[str, Any]:
    """Inventaria um release archive grande sem carregar seus payloads em memória."""
    records: list[dict[str, Any]] = []
    paths: set[str] = set()
    forbidden: list[str] = []
    try:
        with tarfile.open(path, "r:*") as archive:
            for member in archive.getmembers():
                if member.isdir():
                    continue
                name = _validate_relative_path(
                    member.name.rstrip("/"), field="archive.path"
                )
                if root is not None:
                    prefix = f"{root}/"
                    _require(name.startswith(prefix), "Root do release archive diverge")
                    name = name.removeprefix(prefix)
                _require(
                    name and name not in paths, "Release archive contém path duplicado"
                )
                paths.add(name)
                if member.issym():
                    kind = "symlink"
                elif member.islnk():
                    kind = "hardlink"
                elif member.isfile():
                    kind = "file"
                else:
                    raise SourceBundleError(f"Tipo de membro não aceito: {name}")
                records.append(
                    {
                        "link": member.linkname
                        if member.issym() or member.islnk()
                        else "",
                        "relative_path": name,
                        "size": member.size,
                        "type": kind,
                    }
                )
                if PurePosixPath(name).suffix.lower() in {
                    ".dll",
                    ".exe",
                    ".msi",
                    ".sys",
                }:
                    forbidden.append(name)
    except (OSError, tarfile.TarError) as error:
        raise SourceBundleError(f"Release archive inválido: {path.name}") from error
    return {
        "archive_file_count": len(records),
        "archive_payload_size": sum(item["size"] for item in records),
        "forbidden_executable_paths": forbidden,
        "path_inventory_sha256": sha256_bytes(canonical_json_bytes(records)),
        "paths": paths,
    }


def _strip_archive_root(files: dict[str, bytes], root: str | None) -> dict[str, bytes]:
    if root is None:
        return files
    prefix = f"{root}/"
    _require(
        files and all(name.startswith(prefix) for name in files),
        "Root do archive diverge",
    )
    return {name.removeprefix(prefix): content for name, content in files.items()}


def _tree_entries(content: bytes, *, label: str) -> tuple[str, bool, dict[str, str]]:
    metadata = _parse_json_bytes(content, label=label)
    entries = metadata.get("tree")
    _require(isinstance(entries, list), f"Tree metadata sem entries: {label}")
    blobs = {
        item["path"]: item["sha"] for item in entries if item.get("type") == "blob"
    }
    _require(
        len(blobs) == sum(1 for item in entries if item.get("type") == "blob"),
        "Tree contém blob duplicado",
    )
    return str(metadata.get("sha")), bool(metadata.get("truncated", False)), blobs


def _matches_eol_normalized(content: bytes, expected_sha: str) -> bool:
    variants = {
        content.replace(b"\r\n", b"\n"),
        content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"),
    }
    return any(_git_blob_sha(value) == expected_sha for value in variants)


def _verify_tree_correspondence(
    source: dict[str, Any], archive: dict[str, bytes], staging: Path
) -> None:
    verification = source["tree_verification"]
    strategy = verification.get("strategy")
    if strategy == "cargo_registry_checksum":
        checksum = str(verification.get("cargo_checksum", ""))
        _require(
            re.fullmatch(r"[0-9a-f]{64}", checksum) is not None
            and str(source.get("sha256", "")).lower() == checksum,
            "Checksum oficial Cargo diverge do source",
        )
        _require(
            len(archive) == verification.get("archive_blob_count"),
            "Contagem do archive Cargo diverge",
        )
        return
    if strategy not in {
        "git_tree_blob_comparison",
        "git_tree_material_subset_comparison",
    }:
        return
    metadata_path = _validate_relative_path(
        verification.get("tree_metadata"), field="tree_metadata"
    )
    tree_sha, truncated, expected = _tree_entries(
        (staging / metadata_path).read_bytes(), label=metadata_path
    )
    _require(
        not truncated and verification.get("tree_truncated") is False,
        "Tree metadata truncada",
    )
    _require(tree_sha == verification.get("tree"), "Tree identity diverge")
    allowed_missing = set(verification.get("allowed_missing", []))
    eol_paths = set(verification.get("eol_normalized_paths", []))
    if strategy == "git_tree_material_subset_comparison":
        subset_paths = verification.get("material_subset_paths")
        _require(
            isinstance(subset_paths, list)
            and len(subset_paths) == len(set(subset_paths))
            and set(subset_paths) == set(archive)
            and set(subset_paths).issubset(expected),
            "Subconjunto material do archive diverge",
        )
        expected = {name: expected[name] for name in subset_paths}
        _require(not allowed_missing, "Subconjunto material aceita missing indevido")
    else:
        missing = set(expected) - set(archive)
        _require(
            missing == allowed_missing,
            "Arquivos ausentes divergem da allowlist export-ignore",
        )
    unexpected = set(archive) - set(expected)
    if unexpected:
        raise SourceBundleError(
            f"Archive contém arquivo fora da tree: {sorted(unexpected)[0]}"
        )
    for name in sorted(set(expected) & set(archive)):
        actual_sha = _git_blob_sha(archive[name])
        if actual_sha == expected[name]:
            continue
        if name in eol_paths and _matches_eol_normalized(archive[name], expected[name]):
            continue
        raise SourceBundleError(f"Blob Git divergente: {name}")
    _require(
        len(expected) == verification.get("expected_blob_count"),
        "Contagem da tree diverge",
    )
    _require(
        len(archive) == verification.get("archive_blob_count"),
        "Contagem do archive diverge",
    )


def _verify_metadata_identity(
    owner: dict[str, Any], staging: Path, *, is_btbn: bool = False
) -> None:
    metadata_entries = owner["metadata"]
    revision = owner["commit"] if is_btbn else owner.get("full_revision")
    tree = owner.get("tree")
    for entry in metadata_entries:
        relative = entry["relative_path"]
        content = (staging / relative).read_bytes()
        if relative.endswith("-commit.json"):
            if not is_btbn and owner.get("source_type") == "Release Archive":
                continue
            parsed = _parse_json_bytes(content, label=relative)
            actual_revision = parsed.get("sha", parsed.get("commit"))
            actual_tree = parsed.get("tree")
            if actual_tree is None and isinstance(parsed.get("commit"), dict):
                actual_tree = parsed["commit"].get("tree")
            if isinstance(actual_tree, dict):
                actual_tree = actual_tree.get("sha")
            _require(
                actual_revision == revision, f"Commit metadata diverge: {relative}"
            )
            _require(actual_tree == tree, f"Tree do commit diverge: {relative}")
        elif relative.endswith("freetype-commit.txt"):
            text = content.decode("utf-8")
            _require(f"commit={revision}" in text, "Commit FreeType diverge")
            _require(f"tree={tree}" in text, "Tree FreeType diverge")
        elif relative.endswith("-tag.json"):
            parsed = _parse_json_bytes(content, label=relative)
            _require(parsed.get("sha") == owner.get("tag_object"), "Tag object diverge")
            _require(parsed.get("tag") == owner.get("ref"), "Nome da tag diverge")
            _require(
                parsed.get("object", {}).get("sha") == revision,
                "Tag não aponta ao commit",
            )


def _verify_source_archive(
    owner: dict[str, Any], staging: Path, *, is_btbn: bool = False
) -> dict[str, bytes]:
    source = owner["source"]
    strategy = source["tree_verification"].get("strategy")
    if strategy == "official_release_archive_inventory":
        verification = source["tree_verification"]
        inventory = _release_archive_inventory(
            staging / source["relative_path"], verification.get("archive_root")
        )
        _require(
            inventory["archive_file_count"] == verification["archive_file_count"]
            and inventory["archive_payload_size"]
            == verification["archive_payload_size"]
            and inventory["path_inventory_sha256"]
            == verification["path_inventory_sha256"],
            f"Inventário do release archive diverge: {owner.get('component')}",
        )
        _require(
            not inventory["forbidden_executable_paths"],
            "Release archive C7 contém executável/binário proibido",
        )
        for required in [*source["required_files"], *source["license_files"]]:
            _require(
                required in inventory["paths"],
                f"Arquivo requerido ausente no source: {required}",
            )
        _verify_metadata_identity(owner, staging, is_btbn=is_btbn)
        return {}
    archive = _archive_files(staging / source["relative_path"])
    root = source["tree_verification"].get("archive_root")
    stripped = _strip_archive_root(archive, root)
    if owner.get("batch") in {"C5", "C7"}:
        forbidden_binary = next(
            (
                name
                for name in sorted(stripped)
                if PurePosixPath(name).suffix.lower()
                in {".dll", ".exe", ".msi", ".sys"}
            ),
            None,
        )
        _require(
            forbidden_binary is None,
            f"Binário proprietário/externo indevido no source C5: {forbidden_binary}",
        )
    for required in [*source["required_files"], *source["license_files"]]:
        _require(
            required in stripped, f"Arquivo requerido ausente no source: {required}"
        )
    _verify_tree_correspondence(source, stripped, staging)
    _verify_metadata_identity(owner, staging, is_btbn=is_btbn)
    if strategy == "official_sourceforge_svn_revision_snapshot":
        _require(
            source["tree_verification"].get("svn_revision") == 6761,
            "Snapshot SVN não é r6761",
        )
        _require(
            "r6761" in source["relative_path"], "Nome do snapshot SVN não prova r6761"
        )
    return stripped


def _verify_patches(
    manifest: dict[str, Any], staging: Path, btbn_files: dict[str, bytes]
) -> None:
    for patch in manifest["patches"]:
        if patch.get("producer") == "crosstool-NG":
            path = patch["relative_path"]
            try:
                content = (staging / path).read_bytes()
            except OSError as error:
                raise SourceBundleError(
                    f"Patch C7 ausente do staging: {path}"
                ) from error
        else:
            path = patch["path_in_btbn_snapshot"]
            _require(path in btbn_files, f"Patch ausente do snapshot BtbN: {path}")
            content = btbn_files[path]
        _require(len(content) == patch["size"], f"Tamanho de patch diverge: {path}")
        _require(sha256_bytes(content) == patch["sha256"], f"Patch diverge: {path}")


def _tree_records(
    content: bytes, *, label: str
) -> tuple[str, bool, dict[str, tuple[str, str]]]:
    metadata = _parse_json_bytes(content, label=label)
    entries = metadata.get("tree")
    _require(isinstance(entries, list), f"Tree metadata sem entries: {label}")
    blobs: dict[str, tuple[str, str]] = {}
    for item in entries:
        if item.get("type") != "blob":
            continue
        path = item.get("path")
        sha = item.get("sha")
        mode = item.get("mode", "100644")
        _require(
            isinstance(path, str)
            and isinstance(sha, str)
            and isinstance(mode, str)
            and path not in blobs,
            "Tree contém blob inválido ou duplicado",
        )
        blobs[path] = (mode, sha)
    return str(metadata.get("sha")), bool(metadata.get("truncated", False)), blobs


def _run_git(repo: Path, *arguments: str) -> str:
    repo = repo.resolve(strict=True)
    isolated_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    isolated_env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    if arguments[:1] == ("commit",):
        temporary = Path(tempfile.gettempdir()).resolve(strict=True)
        parent = repo.parent
        git_dir = repo / ".git"
        if (
            repo.name != "source"
            or parent.parent != temporary
            or not parent.name.startswith("EduDownloader-")
            or "-patch-" not in parent.name
            or any((ancestor / ".git").exists() for ancestor in parent.parents)
            or not git_dir.is_dir()
            or git_dir.is_symlink()
            or git_dir.is_junction()
        ):
            raise SourceBundleError("Destino Git do replay não está isolado")
        resolved = _run_git(
            repo,
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--git-common-dir",
        ).splitlines()
        if [Path(value).resolve() for value in resolved] != [repo, git_dir] or _run_git(
            repo, "remote"
        ):
            raise SourceBundleError("Destino Git do replay não corresponde à fixture")
        arguments = (
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=.git/disabled-hooks",
            *arguments,
        )
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            env=isolated_env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        raise SourceBundleError(
            "Git indisponível para replay mecânico de patch"
        ) from error
    _require(
        completed.returncode == 0,
        f"Replay Git falhou em {' '.join(arguments)}: "
        f"{(completed.stdout + completed.stderr).strip()}",
    )
    return (completed.stdout + completed.stderr).strip()


def _patch_targets(content: bytes) -> list[str]:
    return sorted(
        {
            match.group(1).decode("utf-8")
            for match in re.finditer(
                rb"^diff --git a/(.+?) b/.+$", content, flags=re.MULTILINE
            )
        }
    )


def _verify_patch_replays(
    manifest: dict[str, Any], staging: Path, btbn_files: dict[str, bytes]
) -> None:
    applicable = [
        patch
        for patch in manifest["patches"]
        if patch.get("application_status") == "APPLIES_CLEANLY"
        and patch.get("producer", "BtbN") == "BtbN"
    ]
    if not applicable:
        return
    parents = {
        item["component"]: item
        for item in [
            *manifest["parents"],
            *manifest.get("dependency_parents", []),
        ]
    }
    components = sorted({patch["applies_to"] for patch in applicable})
    for component in components:
        owner = parents.get(component)
        _require(owner is not None, f"Parent de patch ausente: {component}")
        source = owner["source"]
        verification = source["tree_verification"]
        _require(
            verification.get("strategy") == "git_tree_blob_comparison",
            f"Replay sem tree Git verificável: {component}",
        )
        _require(
            not verification.get("allowed_missing"),
            f"Replay não aceita archive incompleto: {component}",
        )
        tree_metadata = _validate_relative_path(
            verification.get("tree_metadata"), field="patch.tree_metadata"
        )
        tree_sha, truncated, tree_records = _tree_records(
            (staging / tree_metadata).read_bytes(), label=tree_metadata
        )
        _require(not truncated, f"Tree truncada no replay: {component}")
        _require(tree_sha == owner.get("tree"), f"Tree de replay diverge: {component}")

        archive = _archive_files(staging / source["relative_path"])
        archive = _strip_archive_root(archive, verification.get("archive_root"))
        eol_paths = set(verification.get("eol_normalized_paths", []))
        reconstructed = {
            path: content.replace(b"\r\n", b"\n") if path in eol_paths else content
            for path, content in archive.items()
        }
        _require(
            set(reconstructed) == set(tree_records),
            f"Paths do preimage de replay divergem: {component}",
        )
        for path, content in reconstructed.items():
            _require(
                _git_blob_sha(content) == tree_records[path][1],
                f"Blob do preimage de replay diverge: {component}/{path}",
            )

        component_patches = sorted(
            (patch for patch in applicable if patch["applies_to"] == component),
            key=lambda patch: patch["application_order"],
        )
        _require(
            [patch["application_order"] for patch in component_patches]
            == list(range(1, len(component_patches) + 1)),
            f"Ordem de patches não contígua: {component}",
        )
        replay_paths = {patch["replay_metadata"] for patch in component_patches}
        _require(len(replay_paths) == 1, f"Replay metadata divergente: {component}")
        replay_path = replay_paths.pop()
        replay = _parse_json_bytes(
            (staging / replay_path).read_bytes(), label=replay_path
        )
        _require(
            replay.get("application_status") == "APPLIES_CLEANLY"
            and replay.get("component") == component
            and replay.get("baseline_tree") == tree_sha
            and replay.get("full_recipe_replay_claimed") is False,
            f"Evidência de replay inválida: {component}",
        )
        recorded_patches = replay.get("patches")
        _require(
            isinstance(recorded_patches, list)
            and len(recorded_patches) == len(component_patches),
            f"Quantidade de patches no replay diverge: {component}",
        )

        with tempfile.TemporaryDirectory(
            prefix=f"EduDownloader-{component}-patch-"
        ) as temporary_name:
            repo = Path(temporary_name) / "source"
            repo.mkdir()
            for relative, content in reconstructed.items():
                destination = repo / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            _run_git(repo, "init", "--quiet", "--template=")
            _run_git(repo, "config", "core.autocrlf", "false")
            _run_git(repo, "config", "user.name", "EduDownloader compliance replay")
            _run_git(repo, "config", "user.email", "compliance.invalid")
            _run_git(repo, "add", "--force", "--all")
            for relative, (mode, sha) in tree_records.items():
                if mode == "100755":
                    _run_git(repo, "update-index", "--chmod=+x", "--", relative)
                elif mode == "120000":
                    _run_git(
                        repo,
                        "update-index",
                        "--add",
                        "--cacheinfo",
                        f"120000,{sha},{relative}",
                    )
                else:
                    _require(mode == "100644", f"Modo Git não suportado: {mode}")
            _run_git(repo, "commit", "--quiet", "-m", "exact upstream preimage")
            _require(
                _run_git(repo, "rev-parse", "HEAD^{tree}") == tree_sha,
                f"Tree reconstruída diverge antes do replay: {component}",
            )
            for patch, recorded in zip(
                component_patches, recorded_patches, strict=True
            ):
                path = patch["path_in_btbn_snapshot"]
                content = btbn_files[path]
                targets = _patch_targets(content)
                _require(
                    recorded.get("application_order") == patch["application_order"]
                    and recorded.get("path_in_btbn_snapshot") == path
                    and recorded.get("sha256") == patch["sha256"]
                    and recorded.get("size") == patch["size"]
                    and recorded.get("target_files") == targets
                    and patch.get("target_files") == targets,
                    f"Evidência por patch diverge: {path}",
                )
                patch_file = (
                    Path(temporary_name) / f"{patch['application_order']:02d}.patch"
                )
                patch_file.write_bytes(content)
                _run_git(repo, "am", "--keep-cr", str(patch_file))
            _require(
                _run_git(repo, "rev-parse", "HEAD^{tree}")
                == replay.get("final_tree_after_patch_sequence"),
                f"Tree final do replay diverge: {component}",
            )


def _check_proprietary_paths(manifest: dict[str, Any], paths: set[str]) -> None:
    markers = [
        value.lower()
        for value in manifest["proprietary_source_policy"]["forbidden_markers"]
    ]
    for path in sorted(paths):
        lowered = path.lower()
        if any(marker in lowered for marker in markers):
            raise SourceBundleError(f"Possível source proprietário no staging: {path}")


def _verify_cargo_closure(manifest: dict[str, Any], staging: Path) -> None:
    closure = manifest.get("rav1e_cargo_closure")
    if closure is None:
        return
    _require(isinstance(closure, dict), "Closure Cargo C4d inválida")
    evidence = closure.get("evidence")
    _require(isinstance(evidence, dict), "Evidência Cargo C4d ausente")
    relative = _validate_relative_path(
        evidence.get("relative_path"), field="rav1e_cargo_closure.evidence"
    )
    document = _parse_json_bytes((staging / relative).read_bytes(), label=relative)
    _require(document.get("schema_version") == 1, "Schema Cargo C4d divergente")
    c4d = document.get("c4d")
    _require(
        document.get("batch") == "C4d"
        and isinstance(c4d, dict)
        and c4d.get("authorized_package_count") == 8
        and c4d.get("status") == "RAV1E_CARGO_SOURCE_MATERIAL_CLOSED"
        and c4d.get("external_fetch_material_found") is False,
        "Evidência de fechamento C4d ausente ou divergente",
    )
    c4d_packages = c4d.get("packages")
    _require(
        isinstance(c4d_packages, list)
        and {(str(item.get("name")), str(item.get("version"))) for item in c4d_packages}
        == C4D_PACKAGES
        and all(
            item.get("materiality") in {"RUNTIME_MATERIAL", "CODEGEN_MATERIAL"}
            and re.fullmatch(r"[0-9a-f]{64}", str(item.get("checksum", "")))
            for item in c4d_packages
        ),
        "Inventário das oito crates C4d diverge",
    )
    _require(
        document.get("cargo_lock")
        == {
            "package_count": 272,
            "sha256": "A82FFA5F59E3FC3A70C14579CE3D4B9157784BB56B7BC387B7E0878799E659C0",
            "version": 4,
        },
        "Identidade do Cargo.lock C4d diverge",
    )

    all_packages = document.get("all_package_classification")
    _require(
        isinstance(all_packages, list) and len(all_packages) == 272,
        "Inventário Cargo C4d não classifica 272 pacotes",
    )
    all_identities: set[tuple[str, str, str]] = set()
    lock_map: dict[tuple[str, str], dict[str, Any]] = {}
    calculated_classifications = Counter()
    valid_classifications = {
        "BUILD_ONLY",
        "CODEGEN_MATERIAL",
        "DEV_ONLY",
        "OPTIONAL_DISABLED",
        "RUNTIME_MATERIAL",
        "TARGET_NOT_APPLICABLE",
        "UNREACHABLE",
    }
    for package in all_packages:
        _require(isinstance(package, dict), "Pacote Cargo C4d inválido")
        identity = (
            str(package.get("name", "")),
            str(package.get("version", "")),
            str(package.get("source", "")),
        )
        _require(
            all(identity[:2]) and identity not in all_identities,
            "Pacote Cargo C4d duplicado",
        )
        all_identities.add(identity)
        lock_identity = identity[:2]
        _require(
            lock_identity not in lock_map,
            "Cargo.lock C4d repete nome/versão com source ambíguo",
        )
        lock_map[lock_identity] = package
        classification = package.get("classification")
        _require(
            classification in valid_classifications,
            "Pacote Cargo C4d UNKNOWN ou sem classificação",
        )
        if package.get("source") is None:
            _require(
                package.get("checksum") is None,
                "Pacote local Cargo C4d possui checksum de registry",
            )
        else:
            _require(
                package.get("source") == CARGO_REGISTRY_SOURCE
                and re.fullmatch(r"[0-9a-f]{64}", str(package.get("checksum", "")))
                is not None,
                "Source/checksum Cargo.lock inválido na closure C4d",
            )
        calculated_classifications[str(classification)] += 1
    _require(
        dict(sorted(calculated_classifications.items()))
        == document.get("classification_counts")
        == closure.get("classification_counts"),
        "Contagens de classificação Cargo C4d divergem",
    )
    _require(
        document.get("unknown_packages") == [],
        "Closure Cargo C4d contém pacotes UNKNOWN",
    )

    material = document.get("material_packages")
    _require(
        isinstance(material, list) and len(material) == OFFICIAL_CARGO_MATERIAL_COUNT,
        "Grafo material Cargo C4d não tem 48 pacotes",
    )
    material_map: dict[tuple[str, str], dict[str, Any]] = {}
    calculated_material = Counter()
    for package in material:
        _require(isinstance(package, dict), "Pacote material Cargo C4d inválido")
        identity = (str(package.get("name", "")), str(package.get("version", "")))
        _require(
            all(identity) and identity not in material_map,
            "Pacote material Cargo C4d duplicado",
        )
        material_map[identity] = package
        classification = package.get("classification")
        status = package.get("preservation_status")
        _require(
            classification in {"RUNTIME_MATERIAL", "CODEGEN_MATERIAL"}
            and status in {"PRESERVED", "PENDING"},
            "Materialidade/status Cargo C4d inválido",
        )
        _require(
            package.get("registry_source") == CARGO_REGISTRY_SOURCE
            and re.fullmatch(
                r"[0-9a-f]{64}", str(package.get("cargo_lock_checksum", ""))
            )
            is not None
            and package.get("target_applicability") == "x86_64-pc-windows-gnu",
            "Registry/checksum/target material Cargo C4d diverge",
        )
        calculated_material[str(classification)] += 1
        calculated_material[str(status)] += 1
    calculated_material["PENDING"] += 0
    calculated_material["PRESERVED"] += 0
    calculated_material["TOTAL"] = len(material)
    _require(
        dict(sorted(calculated_material.items()))
        == document.get("material_package_counts")
        == closure.get("material_package_counts"),
        "Contagens do grafo material Cargo C4d divergem",
    )
    for identity, package in material_map.items():
        locked = lock_map.get(identity)
        _require(
            locked is not None
            and locked.get("source") == CARGO_REGISTRY_SOURCE
            and locked.get("checksum") == package.get("cargo_lock_checksum")
            and locked.get("classification") == package.get("classification"),
            f"Pacote material diverge do Cargo.lock classificado: {identity[0]}",
        )
        dependencies = package.get("dependencies")
        _require(
            isinstance(dependencies, list),
            f"Dependencies materiais inválidas: {identity[0]}",
        )
        for dependency in dependencies:
            _require(
                isinstance(dependency, dict)
                and dependency.get("role") in {"RUNTIME_MATERIAL", "CODEGEN_MATERIAL"}
                and (
                    str(dependency.get("package", "")),
                    str(dependency.get("version", "")),
                )
                in material_map,
                f"Dependency material ausente da closure: {identity[0]}",
            )

    cargo_parents = [
        item
        for item in manifest.get("dependency_parents", [])
        if item.get("source_type") == "Cargo Registry"
    ]
    parent_map: dict[tuple[str, str], dict[str, Any]] = {}
    for parent in cargo_parents:
        identity = (
            str(parent.get("cargo_package", "")),
            str(parent.get("cargo_version", "")),
        )
        _require(identity not in parent_map, "Parent Cargo C4d duplicado")
        parent_map[identity] = parent
    _require(
        set(parent_map) == set(material_map),
        "Parents Cargo C4d não correspondem ao grafo material",
    )
    for identity, package in material_map.items():
        parent = parent_map[identity]
        checksum = str(package.get("cargo_lock_checksum", ""))
        _require(
            parent.get("cargo_lock_checksum") == checksum
            and parent.get("cargo_dependency_type") == package.get("classification")
            and parent.get("preservation_status") == package.get("preservation_status")
            and parent.get("cargo_features") == package.get("active_features")
            and parent.get("cargo_target_applicability")
            == package.get("target_applicability"),
            f"Parent Cargo C4d diverge da closure: {identity[0]}",
        )
        source = package.get("source")
        if package["preservation_status"] == "PRESERVED":
            parent_source = parent.get("source")
            _require(
                isinstance(source, dict)
                and isinstance(parent_source, dict)
                and source.get("authority") == "cargo_lock_and_crates_io_index_checksum"
                and str(source.get("sha256", "")).lower() == checksum,
                f"Source material Cargo C4d inválido: {identity[0]}",
            )
            license_files = package.get("license_files")
            license_absent = isinstance(license_files, list) and not license_files
            _require(
                parent.get("license_declared_upstream") == package.get("license")
                and isinstance(package.get("license"), str)
                and bool(package["license"])
                and parent_source.get("relative_path") == source.get("relative_path")
                and parent_source.get("size") == source.get("size")
                and parent_source.get("sha256") == source.get("sha256")
                and parent_source.get("license_files") == package.get("license_files")
                and parent_source.get("tree_verification", {}).get("archive_blob_count")
                == source.get("archive_file_count")
                and source.get("cargo_toml_orig_present") is True
                and source.get("vendored_paths") == [],
                f"Metadata/source/license Cargo C4d diverge: {identity[0]}",
            )
            _require(
                parent_source.get("license_files_absent_from_published_crate")
                is license_absent
                and (
                    not license_absent
                    or (
                        isinstance(parent_source.get("license_files_note"), str)
                        and bool(parent_source["license_files_note"])
                    )
                ),
                f"Ausência de licença Cargo não documentada: {identity[0]}",
            )
        else:
            _require(source is None, f"Crate pendente possui source: {identity[0]}")

    nonmaterial = {
        (str(item.get("name", "")), str(item.get("version", "")))
        for item in all_packages
        if item.get("classification")
        in {
            "BUILD_ONLY",
            "DEV_ONLY",
            "OPTIONAL_DISABLED",
            "TARGET_NOT_APPLICABLE",
            "UNREACHABLE",
        }
    }
    _require(
        nonmaterial.isdisjoint(parent_map),
        "Pacote Cargo não material foi incluído como source parent",
    )
    _require(
        document.get("git_material_dependencies") == [],
        "Dependency Git material inesperada na closure Cargo C4d",
    )
    _require(
        document.get("cargo_update_cc") == closure.get("cargo_update_cc")
        and document.get("cargo_update_cc", {}).get("status")
        == "REPRODUCIBILITY_PENDING"
        and document.get("cargo_update_cc", {}).get("classification") == "BUILD_ONLY",
        "cargo update cc não permanece fail-closed para reprodutibilidade",
    )
    _require(
        document.get("rust_runtime_materiality")
        == closure.get("rust_runtime_materiality")
        and document.get("rust_runtime_materiality", {}).get("status")
        == "NEEDS_REVIEW",
        "Materialidade do runtime Rust não permanece em revisão",
    )


def _verify_c5_hardware_evidence(manifest: dict[str, Any], staging: Path) -> None:
    relative = "metadata/c5-hardware-header-materiality.json"
    document = _parse_json_bytes((staging / relative).read_bytes(), label=relative)
    _require(
        document.get("batch") == "C5"
        and document.get("status") == "RESOLVED"
        and document.get("unknown_count") == 0
        and document.get("distributed_pair") == ["ffmpeg.exe", "ffprobe.exe"]
        and document.get("excluded_program") == "ffplay.exe"
        and document.get("patches") == {"count": 0, "status": "NOT_APPLICABLE"},
        "Evidência de materialidade C5 diverge",
    )

    expected_original = {
        (component, revision, "PRESERVED")
        for component, revision in C5_MATERIAL_REVISIONS.items()
    } | {("nv-codec-headers", revision, "SUPERSEDED") for revision in C5_SUPERSEDED_NV}
    original = document.get("original_identity_results")
    _require(
        isinstance(original, list)
        and {
            (item.get("component"), item.get("revision"), item.get("result"))
            for item in original
        }
        == expected_original,
        "Inventário das 13 identidades Hardware/Headers diverge",
    )

    all_parents = [*manifest["parents"], *manifest.get("dependency_parents", [])]
    material_parents = {
        (str(item.get("component")), str(item.get("full_revision"))): item
        for item in all_parents
        if item.get("component") in {**C5_MATERIAL_REVISIONS, **C5_SHADERC_DEPENDENCIES}
        and item.get("preservation_status") == "PRESERVED"
    }
    sources = document.get("sources")
    _require(
        isinstance(sources, list) and len(sources) == 14,
        "Evidência C5 não contém exatamente 14 source parents",
    )
    seen: set[tuple[str, str]] = set()
    for source in sources:
        identity = (str(source.get("component")), str(source.get("revision")))
        parent = material_parents.get(identity)
        _require(parent is not None and identity not in seen, "Source C5 inesperado")
        seen.add(identity)
        parent_source = parent["source"]
        _require(
            source.get("tree") == parent.get("tree")
            and source.get("archive")
            == PurePosixPath(parent_source["relative_path"]).name
            and source.get("sha256") == parent_source.get("sha256")
            and source.get("size") == parent_source.get("size")
            and source.get("materiality") == parent.get("materiality")
            and source.get("license") == parent.get("license_declared_upstream"),
            f"Source/evidência C5 diverge: {identity[0]}",
        )
    _require(
        seen == set(material_parents),
        "Source material C5 ausente da evidência",
    )

    shader_dependencies = document.get("shaderc_dependencies")
    expected_shader = {
        (component, revision, "MATERIAL", "PRESERVED")
        for component, revision in C5_SHADERC_DEPENDENCIES.items()
    } | {
        (
            "shaderc/abseil_cpp",
            "dbf88f932096c7f7714356e919f04749eb87c3e9",
            "TEST_ONLY",
            "NOT_REQUIRED",
        ),
        (
            "shaderc/effcee",
            "910ed15722d5d05c9d71ecf36c1a22243cb79b02",
            "TEST_ONLY",
            "NOT_REQUIRED",
        ),
        (
            "shaderc/googletest",
            "52eb8108c5bdec04579160ae17225d66034bd723",
            "TEST_ONLY",
            "NOT_REQUIRED",
        ),
        (
            "shaderc/re2",
            "927f5d53caf8111721e734cf24724686bb745f55",
            "TEST_ONLY",
            "NOT_REQUIRED",
        ),
    }
    _require(
        isinstance(shader_dependencies, list)
        and {
            (
                item.get("component"),
                item.get("revision"),
                item.get("classification"),
                item.get("status"),
            )
            for item in shader_dependencies
        }
        == expected_shader
        and document.get("new_material_transitives") == shader_dependencies[:3],
        "Closure transitiva shaderc C5 diverge",
    )
    _require(
        document.get("external_interfaces")
        == manifest.get("hardware_header_closure", {}).get("external_interfaces"),
        "Evidência de runtimes/drivers externos C5 diverge",
    )


def _verify_c7_runtime_evidence(manifest: dict[str, Any], staging: Path) -> None:
    """Confere authorities, patch blobs e cobertura Rust material da C7."""
    closure = manifest.get("runtime_toolchain_closure")
    if closure is None:
        return
    evidence = closure["evidence"]
    relative = _validate_relative_path(
        evidence.get("relative_path"), field="runtime_toolchain_closure.evidence"
    )
    document = _parse_json_bytes((staging / relative).read_bytes(), label=relative)
    _require(
        document.get("schema_version") == 1
        and document.get("batch") == "C7"
        and document.get("status") == "RUNTIME_TOOLCHAIN_SOURCE_MATERIAL_CLOSED"
        and document.get("material_source_gap_count") == 0
        and document.get("unknown_materiality_count") == 0
        and document.get("pending_material_source_count") == 0
        and document.get("blocked_material_source_count") == 0
        and document.get("legal_review") == "PENDING"
        and document.get("btbn_promotion") == "NO_GO",
        "Evidência de fechamento Runtime/Toolchain C7 diverge",
    )

    authorities = document.get("authorities")
    required_authorities = {
        "backtrace_commit": "metadata/rust-backtrace-commit.json",
        "backtrace_tree": "metadata/rust-backtrace-tree.json",
        "compiler_builtins_tree": "metadata/rust-compiler-builtins-tree.json",
        "crosstool_commit": "metadata/crosstool-ng-commit.json",
        "crosstool_tree": "metadata/crosstool-ng-tree.json",
        "gcc_checksum": "metadata/gcc-15.2.0-chksum.txt",
        "mingw_base_checksum": "metadata/mingw-w64-v13.0.0-chksum.txt",
        "mingw_final_commit": "metadata/mingw-w64-final-commit.json",
        "mingw_final_tree": "metadata/mingw-w64-final-tree.json",
        "rust_channel_manifest": "metadata/channel-rust-1.97.1.toml",
        "rust_commit": "metadata/rust-commit.json",
    }
    _require(authorities == required_authorities, "Mapa de authorities C7 diverge")

    crosstool_commit = _parse_json_bytes(
        (staging / authorities["crosstool_commit"]).read_bytes(),
        label=authorities["crosstool_commit"],
    )
    crosstool_tree = _parse_json_bytes(
        (staging / authorities["crosstool_tree"]).read_bytes(),
        label=authorities["crosstool_tree"],
    )
    _require(
        crosstool_commit.get("sha") == C7_CROSSTOOL_COMMIT
        and crosstool_commit.get("commit", {}).get("tree", {}).get("sha")
        == C7_CROSSTOOL_TREE
        and crosstool_tree.get("sha") == C7_CROSSTOOL_TREE
        and crosstool_tree.get("truncated") is False,
        "Commit/tree crosstool-NG C7 diverge",
    )
    crosstool_blobs = {
        item["path"]: item["sha"]
        for item in crosstool_tree.get("tree", [])
        if item.get("type") == "blob"
    }
    for patch in manifest["patches"]:
        if patch.get("producer") != "crosstool-NG":
            continue
        content = (staging / patch["relative_path"]).read_bytes()
        _require(
            crosstool_blobs.get(patch["path_at_producer"]) == _git_blob_sha(content),
            f"Patch C7 não coincide com blob crosstool-NG: {patch['path_at_producer']}",
        )

    gcc_checksums = (staging / authorities["gcc_checksum"]).read_text(encoding="utf-8")
    mingw_checksums = (staging / authorities["mingw_base_checksum"]).read_text(
        encoding="utf-8"
    )
    _require(
        f"sha256 gcc-15.2.0.tar.xz {C7_GCC_SHA256.lower()}" in gcc_checksums,
        "Checksum authority GCC C7 diverge",
    )
    _require(
        f"sha256 mingw-w64-v13.0.0.tar.bz2 {C7_MINGW_BASE_SHA256.lower()}"
        in mingw_checksums,
        "Checksum authority mingw base C7 diverge",
    )

    rust_channel = tomllib.loads(
        (staging / authorities["rust_channel_manifest"]).read_text(encoding="utf-8")
    )
    rust_package = rust_channel.get("pkg", {}).get("rust-src", {})
    rust_target = rust_package.get("target", {}).get("*", {})
    _require(
        rust_channel.get("date") == "2026-07-16"
        and rust_package.get("git_commit_hash") == C7_RUST_COMMIT
        and rust_package.get("version", "").startswith("1.97.1 ")
        and str(rust_target.get("xz_hash", "")).upper() == C7_RUST_SHA256,
        "Manifest oficial rust-src C7 diverge",
    )
    rust_commit = _parse_json_bytes(
        (staging / authorities["rust_commit"]).read_bytes(),
        label=authorities["rust_commit"],
    )
    _require(rust_commit.get("sha") == C7_RUST_COMMIT, "Commit Rust C7 diverge")

    rust_parent = next(
        item
        for item in manifest["parents"]
        if item.get("component") == "rust-src 1.97.1"
    )
    rust_files = _strip_archive_root(
        _archive_files(staging / rust_parent["source"]["relative_path"]),
        "rust-src-1.97.1",
    )
    rust_subtrees = document.get("rust_subtrees")
    _require(isinstance(rust_subtrees, dict), "Inventário de subtrees Rust C7 ausente")
    subtree_specs = {
        "compiler_builtins": (
            "rust-src/lib/rustlib/src/rust/library/compiler-builtins/",
            authorities["compiler_builtins_tree"],
            C7_COMPILER_BUILTINS_TREE,
        ),
        "backtrace": (
            "rust-src/lib/rustlib/src/rust/library/backtrace/",
            authorities["backtrace_tree"],
            rust_subtrees.get("backtrace", {}).get("tree"),
        ),
    }
    for component, (prefix, metadata_path, expected_tree) in subtree_specs.items():
        tree_sha, truncated, blobs = _tree_entries(
            (staging / metadata_path).read_bytes(), label=metadata_path
        )
        recorded = rust_subtrees.get(component, {})
        actual = {
            path.removeprefix(prefix): content
            for path, content in rust_files.items()
            if path.startswith(prefix)
        }
        missing = sorted(set(blobs) - set(actual))
        unexpected = sorted(set(actual) - set(blobs))
        _require(
            not truncated
            and tree_sha == expected_tree
            and recorded.get("tree") == tree_sha
            and recorded.get("expected_blob_count") == len(blobs)
            and recorded.get("archive_blob_count") == len(actual)
            and recorded.get("allowed_missing") == missing
            and not unexpected
            and all(
                _git_blob_sha(actual[path]) == blobs[path]
                for path in set(blobs) & set(actual)
            ),
            f"Subtree Rust C7 diverge: {component}",
        )
    backtrace_commit = _parse_json_bytes(
        (staging / authorities["backtrace_commit"]).read_bytes(),
        label=authorities["backtrace_commit"],
    )
    _require(
        backtrace_commit.get("sha") == C7_BACKTRACE_COMMIT
        and backtrace_commit.get("commit", {}).get("tree", {}).get("sha")
        == rust_subtrees["backtrace"]["tree"],
        "Commit/tree backtrace C7 diverge",
    )

    sources = document.get("sources")
    _require(
        isinstance(sources, dict)
        and sources.get("gcc", {}).get("sha256") == C7_GCC_SHA256
        and sources.get("mingw_base", {}).get("sha256") == C7_MINGW_BASE_SHA256
        and sources.get("mingw_final", {}).get("commit") == C7_MINGW_FINAL_COMMIT
        and sources.get("mingw_final", {}).get("tree") == C7_MINGW_FINAL_TREE
        and sources.get("rust_src", {}).get("sha256") == C7_RUST_SHA256
        and document.get("forbidden_executable_count") == 0,
        "Identidade ou auditoria de executáveis C7 diverge",
    )


def verify_staging(manifest: dict[str, Any], staging: Path) -> list[dict[str, Any]]:
    """Valida composição, hashes, revisions, trees, licenses e patches offline."""
    _require(staging.is_dir(), "Diretório de staging ausente")
    expected = expected_staging_entries(manifest)
    actual: dict[str, Path] = {}
    for path in staging.rglob("*"):
        if path.is_symlink():
            raise SourceBundleError("Staging não aceita links simbólicos")
        if path.is_file():
            relative = path.relative_to(staging).as_posix()
            _validate_relative_path(relative, field="staging.path")
            actual[relative] = path
    _check_proprietary_paths(manifest, set(actual))
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    _require(
        not missing,
        f"Source/metadata esperado ausente: {missing[0] if missing else ''}",
    )
    _require(
        not unexpected,
        f"Arquivo inesperado no staging: {unexpected[0] if unexpected else ''}",
    )
    inventory: list[dict[str, Any]] = []
    for relative in sorted(expected):
        entry = expected[relative]
        path = actual[relative]
        _require(
            path.stat().st_size == entry["size"], f"Tamanho divergente: {relative}"
        )
        digest = sha256_file(path)
        _require(digest == entry["sha256"], f"SHA-256 divergente: {relative}")
        inventory.append(
            {"relative_path": relative, "sha256": digest, "size": entry["size"]}
        )
    _verify_cargo_closure(manifest, staging)
    pair_evidence = manifest.get("distributed_pair_scope", {}).get("evidence", [])
    if any(
        entry.get("relative_path") == "metadata/c5-hardware-header-materiality.json"
        for entry in pair_evidence
    ):
        _verify_c5_hardware_evidence(manifest, staging)
    if manifest.get("runtime_toolchain_closure") is not None:
        _verify_c7_runtime_evidence(manifest, staging)
    btbn_files = _verify_source_archive(
        manifest["btbn_snapshot"], staging, is_btbn=True
    )
    _verify_patches(manifest, staging, btbn_files)
    _verify_patch_replays(manifest, staging, btbn_files)
    for parent in [*manifest["parents"], *manifest.get("dependency_parents", [])]:
        if parent["preservation_status"] == "PRESERVED":
            _verify_source_archive(parent, staging)
    return inventory


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _inventory_document(
    entries: list[dict[str, Any]], *, classification: str
) -> dict[str, Any]:
    return {
        "classification": classification,
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
    """Monta ZIP determinístico a partir do staging verificado."""
    manifest = load_manifest(
        manifest_path, enforce_official_baseline=enforce_official_baseline
    )
    verified = verify_staging(manifest, staging)
    root = manifest["bundle"]["root"]
    entries = [
        {**item, "relative_path": f"{root}/{item['relative_path']}"}
        for item in verified
    ]
    manifest_bytes = formatted_json_bytes(manifest)
    entries.append(
        {
            "relative_path": f"{root}/SOURCE_PROVENANCE.json",
            "sha256": sha256_bytes(manifest_bytes),
            "size": len(manifest_bytes),
        }
    )
    entries.sort(key=lambda item: item["relative_path"])
    inventory_bytes = formatted_json_bytes(
        _inventory_document(
            entries, classification=manifest["bundle"]["classification"]
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for entry in entries:
                name = entry["relative_path"]
                if name.endswith("/SOURCE_PROVENANCE.json"):
                    content = manifest_bytes
                else:
                    content = (staging / name.removeprefix(f"{root}/")).read_bytes()
                archive.writestr(_zip_info(name), content, compresslevel=9)
            archive.writestr(
                _zip_info(f"{root}/SOURCE-BUNDLE-INVENTORY.json"),
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
    """Reabre o bundle e confere composição, hashes e manifesto interno."""
    manifest = load_manifest(
        manifest_path, enforce_official_baseline=enforce_official_baseline
    )
    root = manifest["bundle"]["root"]
    manifest_name = f"{root}/SOURCE_PROVENANCE.json"
    inventory_name = f"{root}/SOURCE-BUNDLE-INVENTORY.json"
    try:
        with zipfile.ZipFile(bundle, "r") as archive:
            names = archive.namelist()
            _require(len(names) == len(set(names)), "Bundle contém caminhos duplicados")
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
            inventory = _parse_json_bytes(
                archive.read(inventory_name), label=inventory_name
            )
            _require(
                inventory.get("classification") == manifest["bundle"]["classification"],
                "Classificação do inventário diverge do manifesto",
            )
            entries = inventory.get("entries")
            _require(isinstance(entries, list), "Entries do inventário inválidas")
            _require(
                set(names)
                == {item["relative_path"] for item in entries} | {inventory_name},
                "Composição do bundle diverge",
            )
            recomputed = []
            for entry in sorted(entries, key=lambda item: item["relative_path"]):
                name = _validate_relative_path(
                    entry.get("relative_path"), field="inventory.path"
                )
                content = archive.read(name)
                recomputed.append(
                    {
                        "relative_path": name,
                        "sha256": sha256_bytes(content),
                        "size": len(content),
                    }
                )
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise SourceBundleError("Bundle ausente ou inválido") from error
    _require(recomputed == entries, "Conteúdo do bundle diverge do inventário")
    root_hash = sha256_bytes(canonical_json_bytes(entries))
    _require(
        inventory.get("inventory_sha256") == root_hash,
        "Hash raiz do inventário diverge",
    )
    return {
        "bundle_sha256": sha256_file(bundle),
        "bundle_size": bundle.stat().st_size,
        "classification": manifest["bundle"]["classification"],
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
    return parser


def main(argv: list[str] | None = None) -> int:
    """Executa somente verificação/montagem offline; nunca baixa arquivos."""
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
        print(f"btbn_source_bundle_invalid: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
