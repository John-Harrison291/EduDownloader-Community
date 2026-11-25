"""D10/D11: verify the Deno 2.9.5 Windows x64 source/license closure.

The resolver is deliberately independent from Cargo executables.  It consumes
the pinned Deno source archive, Cargo.lock and the canonical crates.io sparse
index records, applies Cargo features and target predicates, and produces an
offline-verifiable resolution. D11A adds the exact rusty_v8 GN material trace;
D11D extends the authoritative license evidence without synthesizing legal text.
Network acquisition is an explicit command; all validation and bundle
operations remain offline and fail closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import time
import tomllib
import urllib.request
import zipfile
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class SourceBundleError(RuntimeError):
    """Raised when source correspondence evidence is incomplete or inconsistent."""


WORK_ROOT = Path("build-compliance-deno")
PROJECT_ROOT = Path(__file__).resolve().parent
INPUT_ROOT = WORK_ROOT / "inputs"
INDEX_ROOT = WORK_ROOT / "registry-index"
CRATE_ROOT = INPUT_ROOT / "crates"
RESOLUTION_PATH = WORK_ROOT / "cargo-resolution.json"
ACQUISITION_PATH = WORK_ROOT / "crate-acquisitions.json"
CRATE_INSPECTION_PATH = WORK_ROOT / "crate-inspection.json"
FINAL_RESOLUTION_PATH = WORK_ROOT / "cargo-resolution-final.json"
PARENT_INSPECTION_PATH = WORK_ROOT / "parent-inspection.json"
DEFAULT_MANIFEST = Path("docs/compliance/deno/DENO_RUNTIME_SOURCE_PROVENANCE.json")
DEFAULT_NOTICE_MANIFEST = Path("docs/compliance/deno/DENO_THIRD_PARTY_INVENTORY.json")
DEFAULT_NOTICE_TEXT = Path("docs/compliance/deno/DENO_THIRD_PARTY_NOTICES.txt")
DEFAULT_REVIEW_MANIFEST = Path("docs/compliance/deno/DENO_SOURCE_REVIEW_BUNDLE.json")
DEFAULT_REVIEW_README = Path("docs/compliance/deno/DENO_SOURCE_REVIEW_BUNDLE_README.md")
REVIEW_STAGING = WORK_ROOT / "source-review-staging"
REVIEW_STAGING_INCOMPLETE = WORK_ROOT / "source-review-staging.incomplete"
REVIEW_BUNDLE_FILENAME = "EduDownloader-ThirdParty-Source-Deno-2.9.5-COMPLETE.zip"
REVIEW_BUNDLE = WORK_ROOT / REVIEW_BUNDLE_FILENAME
REVIEW_BUNDLE_SECOND = WORK_ROOT / (
    "EduDownloader-ThirdParty-Source-Deno-2.9.5-COMPLETE-second.zip"
)
REVIEW_BUNDLE_ROOT = REVIEW_BUNDLE_FILENAME.removesuffix(".zip")
REVIEW_BUNDLE_MANIFEST_NAME = "BUNDLE_MANIFEST.json"
REVIEW_BUNDLE_INVENTORY_NAME = "SOURCE-BUNDLE-INVENTORY.json"
OFFICIAL_REVIEW_MANIFEST_SHA256 = (
    "97661D752AB991A63ED7EF808A2C2A529B3CC35EE3F67931A219D71C9ABA0FD9"
)
REVIEW_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MAX_REVIEW_FILES = 4_000
MAX_REVIEW_BYTES = 2 * 1024 * 1024 * 1024
REVIEW_EXCLUDED_METADATA = {
    "deno/deno-x86_64-pc-windows-msvc.sha256sum": {
        "reason": "BINARY_ONLY_METADATA_CONTAINS_ABSOLUTE_UPSTREAM_BUILD_PATH",
        "sha256": "05B252FADFD508A3D0DFFCDD025DCF1F91C5D768D9A5FB8F18CA391C801BD6CF",
        "size": 154,
    },
    "deno/deno-x86_64-pc-windows-msvc.zip.sha256sum": {
        "reason": "BINARY_ONLY_METADATA_CONTAINS_ABSOLUTE_UPSTREAM_BUILD_PATH",
        "sha256": "8616CBDA331796828C738F61635A8CB988C9F4FE8B30CD619A64CE47B2E8E993",
        "size": 177,
    },
}
SPDX_REFERENCE_ROOT = Path("docs/compliance/licenses/spdx-reference")
SPDX_REFERENCE_MANIFEST = SPDX_REFERENCE_ROOT / "SPDX_CANONICAL_REFERENCES.json"
SPDX_REFERENCE_MANIFEST_SHA256 = (
    "47AD84418F020E2BCD67ED763576310515AE3CE7807AB4106121FC206424B7E1"
)
SPDX_SNAPSHOT_VERSION = "3.28.0"
SPDX_SNAPSHOT_TAG = "v3.28.0"
SPDX_SNAPSHOT_TAG_OBJECT = "779ef2e5dff6d4af389c53de5e97116ab0bb52e8"
SPDX_SNAPSHOT_COMMIT = "c4a7237ec8f4654e867546f9f409749300f1bf4c"
D11H_COMPONENT_EXPRESSIONS = {
    ("aead-gcm-stream", "0.4.0"): "MIT",
    ("convert_case", "0.4.0"): "MIT",
    ("deno_native_certs", "0.3.0"): "MIT",
    ("deno_tunnel", "0.8.1"): "MIT",
    ("derive-io", "0.4.1"): "MIT OR Apache-2.0",
    ("derive-io-macros", "0.4.1"): "MIT OR Apache-2.0",
    ("fqdn", "0.5.2"): "MIT",
    ("hexf-parse", "0.2.1"): "CC0-1.0",
    ("rustls-tokio-stream", "0.8.0"): "MIT",
    ("sacabase", "2.0.0"): "MIT",
    ("sptr", "0.3.2"): "MIT OR Apache-2.0",
    ("sys_traits", "0.1.28"): "MIT",
    ("sys_traits_macros", "0.1.0"): "MIT",
    ("zune-core", "0.4.12"): "MIT OR Apache-2.0 OR Zlib",
    ("zune-jpeg", "0.4.13"): "MIT OR Apache-2.0 OR Zlib",
}
D11H_PARTIAL_UPSTREAM_TEXT = {
    ("zune-core", "0.4.12"),
    ("zune-jpeg", "0.4.13"),
}
LICENSE_EVIDENCE_INDEX = (
    WORK_ROOT / "license-evidence/upstream-license-acquisitions.json"
)
OFFICIAL_MANIFEST_SHA256 = (
    "9819DB881B0D819B0F00FF6A00D2160BDFE37393651357971B60D26A15D06382"
)
OFFICIAL_NOTICE_MANIFEST_SHA256 = (
    "155D6C10D7021108ED27BCEE928C436742E9EC91F9910382C3FE76D743F210CF"
)
OFFICIAL_NOTICE_TEXT_SHA256 = (
    "5DCE768CB069D3CF0A73F4F2DC3308FE6B0786FD2A4DFF602ACA6E36E5532347"
)
LICENSE_EVIDENCE_INDEX_SHA256 = (
    "44794C785B42C2CE8C8D32640673A28E60A2D2802752D5ECB5A494CABEFF95FD"
)
TARGET = "x86_64-pc-windows-msvc"
DENO_VERSION = "2.9.5"
DENO_COMMIT = "17fadf33a8df3af9488b9f42efd1f2290d6dc7a3"
DENO_TREE = "e6af10b0db821bc8b0c110d66726270d2a50995a"
DENO_ARCHIVE_SHA256 = "9890BA7947C8DB2F31A91A374471FAF86D19C1682F623C170AEB2F86F58A2112"
DENO_ARCHIVE_SIZE = 32_639_976
DENO_LICENSE_SHA256 = "F62497FFFECC0852960C8D3E6934B9DB86D16396E9B604072E923892CAE3A588"
CARGO_LOCK_SHA256 = "5946663ECFE578B71BBDEDA92FE6A4BDD6F5C66E0FFCABBE78C589D2BB1FA4AB"
V8_CRATE_SHA256 = "42A978FF11F15B24E5C05A7123CF2B68F41E763546699781A924EF4E2CF43A49"
RUST_SRC_SHA256 = "67B09138C8DB96AFC4BBFC69EA771AC9A091FD777698ACB43F6DFD9FB7DEA363"
V8_COMMIT = "ac1e23989121713ca642f6650b34deff7b686896"
V8_TREE = "ff06e1a909291763a6f8526b44079551f037246a"
V8_ARCHIVE_SHA256 = "208FC32BB41A5758BDB0E130A0019C908E68599FF5D9A40EF029A8E793B9039E"
V8_ARCHIVE_SIZE = 32_860_562
V8_RUST_COMMIT = "26e8ff47f18a8d28d6187a04b6a16cb7332356f8"
V8_RUST_TREE = "b11eaf710e48d9c3d757090338131ac8d006d65d"
V8_RUST_ARCHIVE_SHA256 = (
    "E10326E9AFF0AE922879071E71BA39C503390472EC643221D0349A9D00E2CE19"
)
V8_RUST_ARCHIVE_SIZE = 33_689_546
V8_RUST_ARCHIVE_FILE_COUNT = 11_275
V8_GN_PROJECT_PATH = (
    WORK_ROOT / "gn-trace" / "windows-x64-simdutf-release" / "project.json"
)
V8_GN_ROOT_TARGET = "//:rusty_v8"
V8_GN_DEFAULT_TOOLCHAIN = "//build/toolchain/win:win_clang_x64"
RUSTY_V8_CI_SHA256 = "B7EB1E8F8E424B8C0838FCF1E1CCAF9EF9994EDA85767E55EFFFE9A459E7A6EF"
RUSTY_V8_CI_GIT_BLOB = "8fd61799619ced98022ac6bf1ddb168730b20a94"
GN_REVISION = "3357c4f51b1a9e676378c695dd9c7e9911c35ee6"
GN_SHA256 = "154197D2DA4217A7B1F607B5EC81981DC7E7A2B2257A7D6EBA75FE1FB8075B07"
NINJA_VERSION = "1.12.1"
NINJA_CIPD_VERSION = "3@1.12.1.chromium.4"
NINJA_SHA256 = "48F6F1B2653E37A846DB3FADDD1C713C697B74C79318510E573D8EF53DB751AC"
V8_CLOSURE_TARGETS_SHA256 = (
    "7BFFBE7AE60289E33B3CF7B5AD2A8FB8665830016809825FD846726BB084FE61"
)
V8_CLOSURE_EDGES_SHA256 = (
    "F15754AC62802C35EDEE43C5D1D3EC97D5AAE7EC0D58FBA1AD95E79265368DBA"
)
V8_NORMALIZED_GRAPH_SHA256 = (
    "3F99871488C47B78D18A70F2B20DC635686E45B169F3F2A57FD0A429C9526F68"
)
V8_SOURCE_PATH_INVENTORY_SHA256 = (
    "00D31ED670FACF0481ACC9CEC4D73214E0961928DC7904D0E15BF4E195FC6EFE"
)
V8_RUSTY_PARENT_PATHS_SHA256 = (
    "08AB20C67F97498B6E130C9C8B43347C592F514D37351A9D86F87EB08F9C7567"
)
V8_SEPARATE_RUST_PARENT_PATHS_SHA256 = (
    "065E975CAFF88D504A29CE2AC3DB3ED4FB23EDEAF92D34A9D150AD03F6900C94"
)
V8_GENERATED_PATHS_SHA256 = (
    "F0AB0FC42FCDB6D2D030851628C74EE0FBDA77F901F8CC830A80CA99F7EB6CE0"
)
RUST_COMMIT = "59807616e1fa2540724bfbac14d7976d7e4a3860"
RUST_TREE = "e09ec02e7b522ab6b45c97b9742429e84940892e"
RUST_REQUIRED = (
    "library/Cargo.lock",
    "library/core/src/lib.rs",
    "library/alloc/src/lib.rs",
    "library/std/src/lib.rs",
    "library/std/src/sys/pal/windows/mod.rs",
    "library/panic_abort/src/lib.rs",
    "library/proc_macro/src/lib.rs",
    "library/compiler-builtins/compiler-builtins/src/lib.rs",
    "library/backtrace/src/lib.rs",
    "library/std_detect/src/lib.rs",
    "library/stdarch/crates/core_arch/src/lib.rs",
)
ROOTS = (
    ("deno", "2.9.5", ("panic-trace",)),
    ("denort", None, ()),
    ("test_server", None, ()),
)
TARGET_VALUES = {
    "target_arch": "x86_64",
    "target_env": "msvc",
    "target_family": "windows",
    "target_os": "windows",
    "target_pointer_width": "64",
    "target_vendor": "pc",
}
TARGET_FLAGS = {"windows": True, "unix": False}
HTTPS_PREFIX = "https:" + "//"
SWC_REPOSITORY = HTTPS_PREFIX + "github.com/swc-project/swc.git"
HTTP_PREFIX = "http:" + "//"
REGISTRY = "registry+" + HTTPS_PREFIX + "github.com/rust-lang/crates.io-index"
USER_AGENT = "EduDownloader-D10-source-correspondence/0.9.5"
MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_CRATE_BYTES = 256 * 1024 * 1024
PROHIBITED_SOURCE_SUFFIXES = frozenset(
    ".exe .dll .pyd .so .dylib .obj .lib .a .whl .pyc .pyo .pem .key .der .p12 .pfx .dpapi .edulic .edureq".split()
)
PRIVATE_PEM_BLOCK_PATTERN = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
CFG_TOKEN_PATTERN = re.compile(
    r'\s*(?:(?P<ident>[A-Za-z_][A-Za-z0-9_-]*)|(?P<string>"[^"]*")|(?P<op>[(),=]))'
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceBundleError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def formatted(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def spdx_expression_identifiers(expression: str) -> list[str]:
    """Return every license/exception identifier without choosing OR branches."""

    require(expression.strip() == expression and expression, "SPDX expression vazia")
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9.+-]*", expression)
    operators = {"AND", "OR", "WITH"}
    identifiers = [token for token in tokens if token.upper() not in operators]
    require(identifiers, f"SPDX expression sem identifier: {expression}")
    require(
        "OR" not in tokens or len(identifiers) >= 2,
        f"SPDX OR sem alternativas completas: {expression}",
    )
    if "WITH" in tokens:
        with_index = tokens.index("WITH")
        require(
            with_index > 0
            and with_index + 1 < len(tokens)
            and tokens[with_index - 1].upper() not in operators
            and tokens[with_index + 1].upper() not in operators,
            f"SPDX WITH sem license + exception: {expression}",
        )
    return list(dict.fromkeys(identifiers))


def validate_spdx_reference_manifest(
    payload: dict, *, verify_files: bool = True
) -> None:
    require(payload.get("schema") == 1, "SPDX reference schema diverge")
    require(
        payload.get("classification") == "SPDX_CANONICAL_REFERENCE_TEXT"
        and payload.get("policy") == "ADOPT_CANONICAL_REFERENCE_POLICY_FOR_P3_REVIEW",
        "SPDX reference provenance ambígua",
    )
    require(
        payload.get("snapshot")
        == {
            "commit": SPDX_SNAPSHOT_COMMIT,
            "repository": HTTPS_PREFIX + "github.com/spdx/license-list-data",
            "tag": SPDX_SNAPSHOT_TAG,
            "tag_object": SPDX_SNAPSHOT_TAG_OBJECT,
            "version": SPDX_SNAPSHOT_VERSION,
        },
        "SPDX reference snapshot não pinado/diverge",
    )
    require(
        payload.get("acquisition")
        == {
            "acquired_at": "2026-09-10",
            "method": "GITHUB_RAW_EXACT_COMMIT",
            "scope": "FOUR_SMALL_OFFICIAL_TEXT_FILES_ONLY",
        },
        "SPDX reference acquisition provenance diverge",
    )
    expected = {
        "Apache-2.0": (
            "Apache License 2.0",
            10_280,
            "074E6E32C86A4C0EF8B3ED25B721CA23ACA83DF277CD88106EF7177C354615FF",
        ),
        "CC0-1.0": (
            "Creative Commons Zero v1.0 Universal",
            7_048,
            "A2010F343487D3F7618AFFE54F789F5487602331C0A8D03F49E9A7C547CF0499",
        ),
        "MIT": (
            "MIT License",
            1_078,
            "B05785F9F18E6716BAB63424B11454513B9943A222595B70411009202FC592B5",
        ),
        "Zlib": (
            "zlib License",
            838,
            "BFB1112D49DB5B1DAECDFEF24BD7E2F3EA0BAFB33AA67AA0AB51E2BF8407C03D",
        ),
    }
    references = payload.get("references", [])
    require(len(references) == len(expected), "SPDX reference count diverge")
    by_identifier = {item.get("identifier"): item for item in references}
    require(set(by_identifier) == set(expected), "SPDX reference identifier diverge")
    for identifier, (name, size, digest) in expected.items():
        item = by_identifier[identifier]
        source_path = f"text/{identifier}.txt"
        local_path = SPDX_REFERENCE_ROOT / source_path
        require(
            item
            == {
                "classification": "SPDX_CANONICAL_REFERENCE_TEXT",
                "identifier": identifier,
                "name": name,
                "path": local_path.as_posix(),
                "sha256": digest,
                "size": size,
                "source_path": source_path,
                "source_url": (
                    HTTPS_PREFIX + "raw.githubusercontent.com/spdx/license-list-data/"
                    f"{SPDX_SNAPSHOT_COMMIT}/{source_path}"
                ),
            },
            f"SPDX reference metadata diverge: {identifier}",
        )
        if verify_files:
            require(local_path.is_file(), f"SPDX reference ausente: {identifier}")
            require(
                local_path.stat().st_size == size and sha256_file(local_path) == digest,
                f"SPDX reference hash diverge: {identifier}",
            )


def load_spdx_reference_manifest() -> dict:
    raw = SPDX_REFERENCE_MANIFEST.read_bytes()
    require(
        sha256_bytes(raw) == SPDX_REFERENCE_MANIFEST_SHA256,
        "SPDX reference manifest hash diverge",
    )
    payload = json.loads(raw)
    require(raw == formatted(payload), "SPDX reference manifest não canônico")
    validate_spdx_reference_manifest(payload)
    return payload


def d11h_component_policy(component: str, version: str, expression: str) -> dict | None:
    identity = (component, version)
    expected_expression = D11H_COMPONENT_EXPRESSIONS.get(identity)
    if expected_expression is None:
        return None
    require(
        expression == expected_expression,
        f"D11H license expression diverge: {component}@{version}",
    )
    return {
        "attribution_metadata": "PARTIAL",
        "canonical_reference_set": spdx_expression_identifiers(expression),
        "canonical_reference_text": "AVAILABLE_FROM_PINNED_SPDX",
        "d11f_category": "D" if " OR " in expression else "C",
        "legal_review": "P3_REQUIRED",
        "license_identity": "RESOLVED_FROM_EXACT_UPSTREAM_METADATA",
        "notice_delivery": "PENDING_FIX",
        "notice_identity": "RESOLVED",
        "policy": "ADOPT_CANONICAL_REFERENCE_POLICY_FOR_P3_REVIEW",
        "upstream_license_text": (
            "PARTIAL" if identity in D11H_PARTIAL_UPSTREAM_TEXT else "ABSENT"
        ),
    }


class CfgParser:
    """Small strict parser for Cargo cfg expressions used by registry metadata."""

    def __init__(self, value: str):
        self.tokens = []
        position = 0
        while position < len(value):
            match = CFG_TOKEN_PATTERN.match(value, position)
            require(match is not None, f"cfg token desconhecido: {value[position:]}")
            position = match.end()
            kind = (
                "ident"
                if match.group("ident")
                else "string"
                if match.group("string")
                else "op"
            )
            token = match.group(kind)
            self.tokens.append((kind, token))
        self.position = 0

    def pop(self, expected: str | None = None) -> tuple[str, str]:
        require(self.position < len(self.tokens), "cfg truncado")
        token = self.tokens[self.position]
        self.position += 1
        if expected is not None:
            require(token[1] == expected, f"cfg esperava {expected!r}")
        return token

    def peek(self, value: str) -> bool:
        return (
            self.position < len(self.tokens) and self.tokens[self.position][1] == value
        )

    def expression(self) -> bool:
        kind, name = self.pop()
        require(kind == "ident", "cfg esperava identificador")
        if self.peek("("):
            self.pop("(")
            values = []
            if not self.peek(")"):
                while True:
                    values.append(self.expression())
                    if not self.peek(","):
                        break
                    self.pop(",")
            self.pop(")")
            require(
                name in {"all", "any", "not", "cfg"}, f"função cfg desconhecida: {name}"
            )
            if name == "all":
                return all(values)
            if name == "any":
                return any(values)
            if name == "not":
                require(len(values) == 1, "not() exige um operando")
                return not values[0]
            require(len(values) == 1, "cfg() exige um operando")
            return values[0]
        if self.peek("="):
            self.pop("=")
            value_kind, value = self.pop()
            require(value_kind == "string", "cfg value deve ser string")
            return TARGET_VALUES.get(name) == value[1:-1]
        return TARGET_FLAGS.get(name, False)

    def parse(self) -> bool:
        result = self.expression()
        require(self.position == len(self.tokens), "cfg possui tokens residuais")
        return result


def target_matches(value: str | None) -> bool:
    if not value:
        return True
    value = value.strip()
    if value.startswith("cfg("):
        return CfgParser(value).parse()
    return value == TARGET


def _version(value: str) -> tuple[tuple[int, int, int], tuple[str, ...]]:
    without_build = value.partition("+")[0]
    main, _, pre = without_build.partition("-")
    numbers = main.split(".")
    require(all(part.isdigit() for part in numbers), f"versão Cargo inválida: {value}")
    padded = tuple(int(part) for part in (numbers + ["0", "0"])[:3])
    return padded, tuple(pre.split(".")) if pre else ()


def _compare(left: str, right: str) -> int:
    left_main, left_pre = _version(left)
    right_main, right_pre = _version(right)
    if left_main != right_main:
        return -1 if left_main < right_main else 1
    if left_pre == right_pre:
        return 0
    if not left_pre:
        return 1
    if not right_pre:
        return -1
    return -1 if left_pre < right_pre else 1


def _caret_bounds(text: str) -> tuple[str, str]:
    main, separator, prerelease = text.partition("-")
    parts = main.split(".")
    numbers = [int(p) for p in parts]
    while len(numbers) < 3:
        numbers.append(0)
    lower = ".".join(map(str, numbers))
    if separator:
        lower += f"-{prerelease}"
    if numbers[0]:
        upper = f"{numbers[0] + 1}.0.0"
    elif len(parts) == 1:
        upper = "1.0.0"
    elif numbers[1]:
        upper = f"0.{numbers[1] + 1}.0"
    elif len(parts) == 2:
        upper = "0.1.0"
    else:
        upper = f"0.0.{numbers[2] + 1}"
    return lower, upper


def version_matches(requirement: str | None, candidate: str) -> bool:
    """Evaluate the Cargo requirement forms present in the pinned closure."""

    if requirement is None or requirement.strip() in {"", "*"}:
        return True
    for clause in (part.strip() for part in requirement.split(",")):
        if not clause or clause == "*":
            continue
        wildcard = clause.replace("X", "*").replace("x", "*")
        if "*" in wildcard:
            prefix = wildcard.split("*")[0].rstrip(".")
            if not candidate.startswith(prefix + ".") and candidate != prefix:
                return False
            continue
        match = re.fullmatch(
            r"(\^|~|=|>=|<=|>|<)?\s*(\d+(?:\.\d+){0,2}(?:-[0-9A-Za-z.-]+)?)", clause
        )
        require(match is not None, f"requirement Cargo não suportado: {requirement}")
        operator, wanted = match.groups()
        if operator in {">", ">=", "<", "<=", "="}:
            main = wanted.partition("-")[0]
            component_count = len(main.split("."))
            lower = ".".join((main.split(".") + ["0", "0"])[:3])
            if "-" in wanted:
                lower += "-" + wanted.partition("-")[2]
            numbers = [int(part) for part in main.split(".")]
            if component_count < 3:
                numbers[-1] += 1
                upper_numbers = numbers + [0] * (3 - component_count)
                upper = ".".join(map(str, upper_numbers))
            else:
                upper = lower
            comparison = _compare(candidate, lower)
            accepted = {
                ">": _compare(candidate, upper) >= 0
                if component_count < 3
                else comparison > 0,
                ">=": comparison >= 0,
                "<": comparison < 0,
                "<=": _compare(candidate, upper) < 0
                if component_count < 3
                else comparison <= 0,
                "=": comparison >= 0
                and (
                    _compare(candidate, upper) < 0
                    if component_count < 3
                    else comparison == 0
                ),
            }[operator]
            if not accepted:
                return False
        elif operator == "~":
            parts = wanted.split(".")
            lower = ".".join((parts + ["0", "0"])[:3])
            if len(parts) == 1:
                upper = f"{int(parts[0]) + 1}.0.0"
            else:
                upper = f"{parts[0]}.{int(parts[1]) + 1}.0"
            if _compare(candidate, lower) < 0 or _compare(candidate, upper) >= 0:
                return False
        else:
            lower, upper = _caret_bounds(wanted.lstrip("^"))
            if _compare(candidate, lower) < 0 or _compare(candidate, upper) >= 0:
                return False
    return True


def index_relative_path(name: str) -> PurePosixPath:
    lowered = name.lower()
    if len(lowered) == 1:
        return PurePosixPath("1", lowered)
    if len(lowered) == 2:
        return PurePosixPath("2", lowered)
    if len(lowered) == 3:
        return PurePosixPath("3", lowered[0], lowered)
    return PurePosixPath(lowered[:2], lowered[2:4], lowered)


def _download(url: str, destination: Path, max_bytes: int) -> dict:
    require(url.startswith(HTTPS_PREFIX), "aquisição exige HTTPS")
    require(not destination.exists(), f"destino já existe: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    require(not partial.exists(), f"parcial pré-existente: {partial}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            partial.open("xb") as output,
        ):
            total = 0
            digest = hashlib.sha256()
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                require(total <= max_bytes, f"download excede limite: {url}")
                output.write(chunk)
                digest.update(chunk)
        os.replace(partial, destination)
    except Exception:
        # Keep a non-empty partial for operator inspection; never replace it.
        if partial.exists() and partial.stat().st_size == 0:
            partial.unlink()
        raise
    return {"url": url, "size": total, "sha256": digest.hexdigest().upper()}


def fetch_index(name: str, index_root: Path = INDEX_ROOT) -> dict:
    relative = index_relative_path(name)
    destination = index_root.joinpath(*relative.parts)
    if destination.exists():
        return {
            "url": f"{HTTPS_PREFIX}index.crates.io/{relative.as_posix()}",
            "size": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "reused": True,
        }
    result = _download(
        f"{HTTPS_PREFIX}index.crates.io/{relative.as_posix()}",
        destination,
        MAX_INDEX_BYTES,
    )
    result["reused"] = False
    return result


def load_index_version(name: str, version: str, index_root: Path = INDEX_ROOT) -> dict:
    path = index_root.joinpath(*index_relative_path(name).parts)
    require(path.is_file(), f"índice ausente: {name}")
    matches = []
    for line in path.read_bytes().splitlines():
        if not line:
            continue
        item = json.loads(line)
        if item.get("name") == name and item.get("vers") == version:
            matches.append(item)
    require(len(matches) == 1, f"versão não única no índice: {name} {version}")
    return matches[0]


@dataclass(frozen=True, order=True)
class PackageKey:
    name: str
    version: str
    source: str

    @property
    def text(self) -> str:
        scope = "registry" if self.source.startswith("registry+") else "workspace"
        return f"{self.name}@{self.version}#{scope}"


def parse_lock_dependency(value: str) -> tuple[str, str | None]:
    value = value.split(" (", 1)[0]
    parts = value.rsplit(" ", 1)
    if len(parts) == 2 and re.fullmatch(
        r"\d+(?:\.\d+){1,2}(?:-[0-9A-Za-z.-]+)?", parts[1]
    ):
        return parts[0], parts[1]
    return value, None


class CargoResolver:
    def __init__(
        self,
        source_root: Path,
        index_root: Path = INDEX_ROOT,
        acquire_index: bool = False,
    ):
        self.source_root = source_root
        self.index_root = index_root
        self.acquire_index = acquire_index
        self.root_manifest = tomllib.loads(
            (source_root / "Cargo.toml").read_text(encoding="utf-8")
        )
        self.lock_raw = (source_root / "Cargo.lock").read_bytes()
        self.lock = tomllib.loads(self.lock_raw.decode())
        self.lock_packages: dict[PackageKey, dict] = {}
        for package in self.lock["package"]:
            key = PackageKey(
                package["name"], package["version"], package.get("source", "workspace")
            )
            require(
                key not in self.lock_packages, f"package duplicado no lock: {key.text}"
            )
            self.lock_packages[key] = package
        self.local = self._load_local_packages()
        self.acquisitions: dict[str, dict] = {}
        self.unknown: list[dict] = []
        self.observed = defaultdict(set)
        self.observed_packages = defaultdict(set)

    def _load_local_packages(self) -> dict[PackageKey, dict]:
        result = {}
        workspace = self.root_manifest["workspace"]
        root_package = workspace.get("package", {})
        for pattern in workspace["members"]:
            paths = (
                sorted(self.source_root.glob(pattern))
                if "*" in pattern
                else [self.source_root / pattern]
            )
            for directory in paths:
                manifest_path = directory / "Cargo.toml"
                require(
                    manifest_path.is_file(), f"workspace manifest ausente: {pattern}"
                )
                raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
                package = raw.get("package")
                require(
                    package is not None, f"workspace package ausente: {manifest_path}"
                )
                version = package.get("version")
                if isinstance(version, dict) and version.get("workspace"):
                    version = root_package["version"]
                key = PackageKey(package["name"], version, "workspace")
                require(key not in result, f"workspace package duplicado: {key.text}")
                result[key] = {
                    "raw": raw,
                    "path": directory.relative_to(self.source_root).as_posix(),
                }
        # A few path dependencies (for example ext/os and serde_v8/utilities)
        # intentionally live outside workspace.members, but remain local lock
        # packages and are material to deno.exe.  Add only Cargo.toml files that
        # match an exact source-less Cargo.lock identity; fixtures stay excluded.
        wanted = {
            (key.name, key.version)
            for key in self.lock_packages
            if key.source == "workspace" and key not in result
        }
        matches = defaultdict(list)
        for manifest_path in self.source_root.rglob("Cargo.toml"):
            if any(
                item["path"]
                == manifest_path.parent.relative_to(self.source_root).as_posix()
                for item in result.values()
            ):
                continue
            raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            package = raw.get("package")
            if not package:
                continue
            version = package.get("version")
            if isinstance(version, dict) and version.get("workspace"):
                version = root_package["version"]
            identity = (package.get("name"), version)
            if identity in wanted:
                matches[identity].append((manifest_path, raw))
        for identity in sorted(wanted):
            candidates = matches[identity]
            require(
                len(candidates) == 1,
                f"path dependency local ausente/ambígua: {identity}",
            )
            manifest_path, raw = candidates[0]
            key = PackageKey(identity[0], identity[1], "workspace")
            result[key] = {
                "raw": raw,
                "path": manifest_path.parent.relative_to(self.source_root).as_posix(),
            }
        return result

    def _normalize_dep(
        self, alias: str, spec: object, kind: str, target: str | None
    ) -> dict:
        if isinstance(spec, str):
            spec = {"version": spec}
        else:
            spec = dict(spec)
        if spec.pop("workspace", False):
            inherited = self.root_manifest["workspace"]["dependencies"].get(alias)
            require(inherited is not None, f"workspace dependency ausente: {alias}")
            inherited = (
                {"version": inherited}
                if isinstance(inherited, str)
                else dict(inherited)
            )
            inherited.update(spec)
            spec = inherited
        return {
            "alias": alias,
            "name": spec.get("package", alias),
            "req": spec.get("version"),
            "features": list(spec.get("features", [])),
            "optional": bool(spec.get("optional", False)),
            "default_features": bool(spec.get("default-features", True)),
            "kind": kind,
            "target": target,
        }

    def _local_metadata(self, key: PackageKey) -> dict:
        raw = self.local[key]["raw"]
        deps = []
        for table_name, kind in (
            ("dependencies", "normal"),
            ("build-dependencies", "build"),
            ("dev-dependencies", "dev"),
        ):
            for alias, spec in raw.get(table_name, {}).items():
                deps.append(self._normalize_dep(alias, spec, kind, None))
        for target, tables in raw.get("target", {}).items():
            for table_name, kind in (
                ("dependencies", "normal"),
                ("build-dependencies", "build"),
                ("dev-dependencies", "dev"),
            ):
                for alias, spec in tables.get(table_name, {}).items():
                    deps.append(self._normalize_dep(alias, spec, kind, target))
        package = raw["package"]
        return {
            "name": key.name,
            "vers": key.version,
            "deps": deps,
            "features": dict(raw.get("features", {})),
            "license": package.get(
                "license",
                self.root_manifest["workspace"].get("package", {}).get("license"),
            ),
            "links": package.get("links"),
            "path": self.local[key]["path"],
        }

    def metadata(self, key: PackageKey) -> dict:
        if key.source == "workspace":
            return self._local_metadata(key)
        path = self.index_root.joinpath(*index_relative_path(key.name).parts)
        if not path.exists() and self.acquire_index:
            self.acquisitions[key.name] = fetch_index(key.name, self.index_root)
        raw = load_index_version(key.name, key.version, self.index_root)
        deps = []
        for dep in raw.get("deps", []):
            deps.append(
                {
                    "alias": dep["name"],
                    "name": dep.get("package") or dep["name"],
                    "req": dep.get("req"),
                    "features": list(dep.get("features", [])),
                    "optional": bool(dep.get("optional", False)),
                    "default_features": bool(dep.get("default_features", True)),
                    "kind": dep.get("kind") or "normal",
                    "target": dep.get("target"),
                }
            )
        features = dict(raw.get("features", {}))
        features.update(raw.get("features2", {}))
        return {
            "name": key.name,
            "vers": key.version,
            "deps": deps,
            "features": features,
            "license": raw.get("license"),
            "links": raw.get("links"),
            "checksum": raw.get("cksum"),
            "yanked": raw.get("yanked", False),
        }

    def find_key(
        self, name: str, version: str | None = None, source: str | None = None
    ) -> PackageKey:
        candidates = [
            key
            for key in self.lock_packages
            if key.name == name
            and (version is None or key.version == version)
            and (source is None or key.source == source)
        ]
        require(
            len(candidates) == 1,
            f"package lock ambíguo/ausente: {name} {version or ''}",
        )
        return candidates[0]

    def dependency_key(self, parent: PackageKey, dep: dict) -> PackageKey:
        locked = self.lock_packages[parent].get("dependencies", [])
        allowed = []
        for value in locked:
            name, version = parse_lock_dependency(value)
            if name != dep["name"]:
                continue
            for key in self.lock_packages:
                if key.name == name and (version is None or key.version == version):
                    if version_matches(dep.get("req"), key.version):
                        allowed.append(key)
        allowed = sorted(set(allowed))
        require(
            len(allowed) == 1,
            f"dependency lock ambígua/ausente: {parent.text} -> {dep['name']} {dep.get('req')}",
        )
        return allowed[0]

    def observe_skipped_dependency(
        self, category: str, parent: PackageKey, dep: dict
    ) -> None:
        """Record a skipped package when Cargo.lock contains that branch.

        Fully disabled optional dependencies may not occur in the lock at all;
        those are edge observations, not members of the 1,133-package universe.
        """

        try:
            child = self.dependency_key(parent, dep)
        except SourceBundleError:
            return
        self.observed_packages[category].add(child)

    @staticmethod
    def _expand_features(
        metadata: dict, requested: set[str]
    ) -> tuple[set[str], set[str], dict[str, set[str]]]:
        features = set(requested)
        optional = set()
        dependency_features: dict[str, set[str]] = defaultdict(set)
        queue = deque(sorted(features))
        seen = set()
        dependency_aliases = {
            dep["alias"] for dep in metadata["deps"] if dep["optional"]
        }
        explicit_dep_aliases = {
            item[4:]
            for values in metadata["features"].values()
            for item in values
            if item.startswith("dep:")
        }
        while queue:
            feature = queue.popleft()
            if feature in seen:
                continue
            seen.add(feature)
            values = metadata["features"].get(feature)
            if values is None:
                if (
                    feature in dependency_aliases
                    and feature not in explicit_dep_aliases
                ):
                    optional.add(feature)
                continue
            for value in values:
                if value.startswith("dep:"):
                    optional.add(value[4:])
                elif "/" in value:
                    alias, child_feature = value.split("/", 1)
                    weak = alias.endswith("?")
                    alias = alias.rstrip("?")
                    if not weak:
                        optional.add(alias)
                    dependency_features[alias].add(child_feature)
                elif value not in features:
                    features.add(value)
                    queue.append(value)
        return features, optional, dependency_features

    def resolve(self) -> dict:
        normal_features: dict[PackageKey, set[str]] = defaultdict(set)
        build_features: dict[PackageKey, set[str]] = defaultdict(set)
        normal_defaults = set()
        build_defaults = set()
        roots = []
        for name, version, features in ROOTS:
            key = self.find_key(name, version)
            roots.append(key)
            normal_features[key].update(features)
            normal_defaults.add(key)
        edges = set()
        changed = True
        metadata_cache = {}
        while changed:
            changed = False
            for context, states, defaults in (
                ("normal", normal_features, normal_defaults),
                ("build", build_features, build_defaults),
            ):
                for key in list(states):
                    metadata = metadata_cache.get(key)
                    if metadata is None:
                        metadata = self.metadata(key)
                        metadata_cache[key] = metadata
                    requested = set(states[key])
                    if key in defaults:
                        requested.add("default")
                    expanded, optional, child_features = self._expand_features(
                        metadata, requested
                    )
                    if not expanded.issubset(states[key]):
                        states[key].update(expanded)
                        changed = True
                    for dep in metadata["deps"]:
                        observation = f"{key.text}:{dep['alias']}"
                        if dep["kind"] == "dev":
                            self.observed["dev"].add(observation)
                            self.observe_skipped_dependency("dev", key, dep)
                            continue
                        if not target_matches(dep["target"]):
                            self.observed["target"].add(observation)
                            self.observe_skipped_dependency("target", key, dep)
                            continue
                        if dep["optional"] and dep["alias"] not in optional:
                            self.observed["optional"].add(observation)
                            self.observe_skipped_dependency("optional", key, dep)
                            continue
                        child = self.dependency_key(key, dep)
                        child_context = (
                            "build"
                            if context == "build" or dep["kind"] == "build"
                            else "normal"
                        )
                        edge = (context, key, child_context, child, dep["alias"])
                        if edge not in edges:
                            edges.add(edge)
                            changed = True
                        child_states = (
                            build_features
                            if child_context == "build"
                            else normal_features
                        )
                        before = len(child_states[child])
                        child_states[child].update(dep["features"])
                        child_states[child].update(
                            child_features.get(dep["alias"], set())
                        )
                        if len(child_states[child]) != before:
                            changed = True
                        child_defaults = (
                            build_defaults
                            if child_context == "build"
                            else normal_defaults
                        )
                        if dep["default_features"] and child not in child_defaults:
                            child_defaults.add(child)
                            changed = True

        deno = roots[0]
        material = {deno}
        queue = deque([deno])
        normal_adjacency = defaultdict(set)
        for parent_context, parent, child_context, child, _alias in edges:
            if parent_context == child_context == "normal":
                normal_adjacency[parent].add(child)
        while queue:
            parent = queue.popleft()
            for child in normal_adjacency[parent]:
                if child not in material:
                    material.add(child)
                    queue.append(child)
        build_only = set(build_features) - material
        all_reached = set(normal_features) | set(build_features)
        remaining = set(self.lock_packages) - all_reached
        dev_only = self.observed_packages["dev"] & remaining
        target_not_applicable = (
            self.observed_packages["target"] & remaining
        ) - dev_only
        optional_disabled = (
            (self.observed_packages["optional"] & remaining)
            - dev_only
            - target_not_applicable
        )
        unreachable = (
            set(self.lock_packages)
            - material
            - build_only
            - dev_only
            - target_not_applicable
            - optional_disabled
        )
        package_records = []
        for key in sorted(self.lock_packages):
            metadata = metadata_cache.get(key)
            classification = (
                "MATERIAL_RUNTIME"
                if key in material
                else "BUILD_ONLY"
                if key in build_only
                else "DEV_ONLY"
                if key in dev_only
                else "TARGET_NOT_APPLICABLE"
                if key in target_not_applicable
                else "OPTIONAL_DISABLED"
                if key in optional_disabled
                else "UNREACHABLE"
            )
            package_records.append(
                {
                    "id": key.text,
                    "name": key.name,
                    "version": key.version,
                    "source": key.source,
                    "classification": classification,
                    "checksum": self.lock_packages[key].get("checksum"),
                    "license_expression": metadata.get("license") if metadata else None,
                    "links": metadata.get("links") if metadata else None,
                    "features": sorted(normal_features.get(key, set())),
                    "build_features": sorted(build_features.get(key, set())),
                }
            )
        result = {
            "schema": 1,
            "authority": {
                "deno_version": DENO_VERSION,
                "target": TARGET,
                "resolver": self.root_manifest["workspace"]["resolver"],
                "profile": "release",
                "roots": [key.text for key in roots],
                "explicit_features": ["deno/panic-trace"],
                "default_features": True,
                "cargo_lock_sha256": sha256_bytes(self.lock_raw),
            },
            "counts": {
                "lock_packages": len(self.lock_packages),
                "workspace": sum(
                    key.source == "workspace" for key in self.lock_packages
                ),
                "registry": sum(
                    key.source.startswith("registry+") for key in self.lock_packages
                ),
                "material": len(material),
                "build_only": len(build_only),
                "dev_only": len(dev_only),
                "target_not_applicable": len(target_not_applicable),
                "optional_disabled": len(optional_disabled),
                "unreachable": len(unreachable),
                "index_records_acquired": len(self.acquisitions),
                "unknown": len(self.unknown),
            },
            "observations": {
                name: len(values) for name, values in sorted(self.observed.items())
            },
            "index_acquisitions": dict(sorted(self.acquisitions.items())),
            "packages": package_records,
            "edges": [
                {
                    "parent_context": parent_context,
                    "parent": parent.text,
                    "child_context": child_context,
                    "child": child.text,
                    "alias": alias,
                }
                for parent_context, parent, child_context, child, alias in sorted(edges)
            ],
        }
        require(
            result["authority"]["cargo_lock_sha256"] == CARGO_LOCK_SHA256,
            "Cargo.lock diverge",
        )
        require(result["counts"]["unknown"] == 0, "Cargo resolution possui UNKNOWN")
        return result


def verify_wave_a(source_root: Path) -> dict:
    paths = {
        "deno": (
            INPUT_ROOT / "deno-2.9.5.tar.gz",
            DENO_ARCHIVE_SIZE,
            DENO_ARCHIVE_SHA256,
        ),
        "v8_crate": (INPUT_ROOT / "v8-150.4.0.crate", 36_296_166, V8_CRATE_SHA256),
        "rust_src": (INPUT_ROOT / "rust-src-1.95.0.tar.xz", 3_827_368, RUST_SRC_SHA256),
    }
    result = {}
    for name, (path, size, digest) in paths.items():
        require(
            path.is_file() and not path.is_symlink(), f"input ausente/inseguro: {path}"
        )
        require(path.stat().st_size == size, f"size diverge: {path}")
        require(sha256_file(path) == digest, f"hash diverge: {path}")
        result[name] = {"path": path.as_posix(), "size": size, "sha256": digest}
    license_path = source_root / "LICENSE.md"
    lock_path = source_root / "Cargo.lock"
    require(sha256_file(license_path) == DENO_LICENSE_SHA256, "Deno LICENSE diverge")
    require(sha256_file(lock_path) == CARGO_LOCK_SHA256, "Deno Cargo.lock diverge")
    return result


def material_registry(resolution: dict) -> list[dict]:
    return [
        package
        for package in resolution["packages"]
        if package["classification"].startswith("MATERIAL_")
        and package["source"].startswith("registry+")
    ]


def acquire_crates(resolution: dict) -> dict:
    records = []
    reused = []
    available = defaultdict(list)
    for directory in Path.cwd().glob("build-compliance-*"):
        if directory == WORK_ROOT:
            continue
        for path in directory.rglob("*.crate"):
            available[path.name].append(path)
    for package in material_registry(resolution):
        name = package["name"]
        version = package["version"]
        checksum = package["checksum"].upper()
        filename = f"{name}-{version}.crate"
        destination = CRATE_ROOT / filename
        if name == "v8" and version == "150.4.0":
            source = INPUT_ROOT / "v8-150.4.0.crate"
            require(sha256_file(source) == checksum, "v8 reuse hash diverge")
            reused.append(
                {
                    "name": name,
                    "version": version,
                    "path": source.as_posix(),
                    "sha256": checksum,
                }
            )
            continue
        if destination.exists():
            require(
                sha256_file(destination) == checksum,
                f"crate existente diverge: {filename}",
            )
            records.append(
                {
                    "name": name,
                    "version": version,
                    "path": destination.as_posix(),
                    "sha256": checksum,
                    "reused": True,
                }
            )
            continue
        exact = [
            path
            for path in available.get(filename, [])
            if sha256_file(path) == checksum
        ]
        if exact:
            require(len(exact) == 1, f"reuso ambíguo: {filename}")
            reused.append(
                {
                    "name": name,
                    "version": version,
                    "path": exact[0].as_posix(),
                    "sha256": checksum,
                }
            )
            continue
        result = _download(
            f"{HTTPS_PREFIX}static.crates.io/crates/{name}/{filename}",
            destination,
            MAX_CRATE_BYTES,
        )
        require(
            result["sha256"] == checksum, f"checksum Cargo.lock diverge: {filename}"
        )
        records.append(
            {
                "name": name,
                "version": version,
                "path": destination.as_posix(),
                "sha256": checksum,
                "size": result["size"],
                "reused": False,
            }
        )
        time.sleep(0.05)
    return {"acquired": records, "reused": reused}


def _crate_path_map(acquisitions: dict) -> dict[tuple[str, str], Path]:
    result = {}
    for record in acquisitions["acquired"] + acquisitions["reused"]:
        key = (record["name"], record["version"])
        require(key not in result, f"crate acquisition duplicada: {key}")
        result[key] = Path(record["path"])
    return result


def inspect_crate(path: Path, package: dict) -> dict:
    require(path.is_file() and not path.is_symlink(), f"crate ausente/inseguro: {path}")
    checksum = package["checksum"].upper()
    require(sha256_file(path) == checksum, f"crate checksum diverge: {path.name}")
    expected_root = f"{package['name']}-{package['version']}/"
    license_files = []
    notice_files = []
    copyright_lines = set()
    native_sources = 0
    rust_sources = 0
    total_files = 0
    total_size = 0
    manifest_data = None
    original_manifest_data = None
    vcs_data = None
    build_script = b""
    with tarfile.open(path, "r:gz") as archive:
        seen = set()
        for member in archive.getmembers():
            require(
                member.isfile() or member.isdir(),
                f"tipo de membro inesperado em crate: {path.name}:{member.name}",
            )
            pure = PurePosixPath(member.name)
            require(
                not pure.is_absolute() and ".." not in pure.parts,
                f"path inseguro em crate: {path.name}:{member.name}",
            )
            if member.isdir():
                continue
            require(
                member.name.startswith(expected_root),
                f"raiz de crate diverge: {path.name}",
            )
            relative = member.name[len(expected_root) :]
            require(
                relative.casefold() not in seen,
                f"membro duplicado em crate: {path.name}",
            )
            seen.add(relative.casefold())
            total_files += 1
            total_size += member.size
            suffix = PurePosixPath(relative).suffix.lower()
            rust_sources += suffix == ".rs"
            native_sources += suffix in {".c", ".cc", ".cpp", ".cxx", ".s", ".asm"}
            base = PurePosixPath(relative).name.upper()
            wanted = base.startswith(
                (
                    "LICENSE",
                    "LICENCE",
                    "COPYING",
                    "NOTICE",
                    "COPYRIGHT",
                    "UNLICENSE",
                    "AUTHORS",
                )
            )
            if (
                relative
                in {
                    "Cargo.toml",
                    "Cargo.toml.orig",
                    ".cargo_vcs_info.json",
                    "build.rs",
                }
                or wanted
            ):
                stream = archive.extractfile(member)
                require(stream is not None, f"membro ilegível: {path.name}:{relative}")
                data = stream.read()
                if relative == "Cargo.toml":
                    manifest_data = data
                elif relative == "Cargo.toml.orig":
                    original_manifest_data = data
                elif relative == ".cargo_vcs_info.json":
                    vcs_data = data
                elif relative == "build.rs":
                    build_script = data
                else:
                    role = (
                        "NOTICE"
                        if base.startswith("NOTICE")
                        else "COPYRIGHT"
                        if base.startswith("COPYRIGHT")
                        else "AUTHORS"
                        if base.startswith("AUTHORS")
                        else "LICENSE"
                    )
                    record = {
                        "path": relative,
                        "size": len(data),
                        "sha256": sha256_bytes(data),
                        "role": role,
                    }
                    (notice_files if role != "LICENSE" else license_files).append(
                        record
                    )
                    for line in data.decode("utf-8", errors="replace").splitlines():
                        if "copyright" in line.casefold() and len(line.strip()) <= 300:
                            copyright_lines.add(line.strip())
    require(
        manifest_data is not None and rust_sources > 0,
        f"crate sem manifest/source: {path.name}",
    )
    manifest = tomllib.loads(manifest_data.decode())
    metadata = manifest["package"]
    original_manifest_text = (
        original_manifest_data.decode("utf-8", errors="replace")
        if original_manifest_data
        else ""
    )
    vcs = json.loads(vcs_data) if vcs_data else {}
    require(
        metadata["name"] == package["name"]
        and metadata["version"] == package["version"],
        f"crate identity diverge: {path.name}",
    )
    crate_license_expression = metadata.get("license")
    index_license_expression = package.get("license_expression")
    require(
        not crate_license_expression
        or not index_license_expression
        or crate_license_expression == index_license_expression,
        f"crate/index license metadata diverge: {path.name}",
    )
    license_expression = crate_license_expression or index_license_expression
    proc_macro = bool(manifest.get("lib", {}).get("proc-macro", False))
    build_text = build_script.decode("utf-8", errors="replace").casefold()
    network_in_build = any(
        marker in build_text
        for marker in (HTTPS_PREFIX, HTTP_PREFIX, "git clone", "curl ")
    )
    links = metadata.get("links") or package.get("links")
    if package["name"] == "v8":
        native_coverage = "V8_NATIVE_PARENT_REQUIRED"
    elif links and native_sources:
        native_coverage = "COVERED_BY_CRATE_PARENT"
    elif links:
        native_coverage = "SOURCE_PARENT_REVIEW_REQUIRED"
    else:
        native_coverage = "NOT_APPLICABLE"
    special = []
    expression_upper = (license_expression or "").upper()
    for marker in (
        "MPL-2.0",
        "UNICODE",
        "LLVM-EXCEPTION",
        "BSD",
        "ISC",
        "ZLIB",
        "BZIP2",
    ):
        if marker in expression_upper:
            special.append(marker)
    return {
        "name": package["name"],
        "version": package["version"],
        "checksum": checksum,
        "archive_size": path.stat().st_size,
        "source_file_count": total_files,
        "source_uncompressed_size": total_size,
        "rust_source_count": rust_sources,
        "native_source_count": native_sources,
        "proc_macro": proc_macro,
        "links": links,
        "license_expression": license_expression,
        "license_file_declared": metadata.get("license-file"),
        "license_files": sorted(license_files, key=lambda item: item["path"]),
        "notice_files": sorted(notice_files, key=lambda item: item["path"]),
        "repository": metadata.get("repository"),
        "homepage": metadata.get("homepage"),
        "vcs_commit": vcs.get("git", {}).get("sha1"),
        "path_in_vcs": vcs.get("path_in_vcs"),
        "workspace_license_inherited": bool(
            re.search(
                r"(?m)^\s*license\.workspace\s*=\s*true\s*$", original_manifest_text
            )
        ),
        "copyright_evidence": sorted(copyright_lines)[:20],
        "special_license_flags": special,
        "network_reference_in_build_script": network_in_build,
        "native_source_coverage": native_coverage,
    }


def inspect_material_crates(
    resolution: dict, acquisitions: dict, source_root: Path
) -> tuple[dict, dict]:
    paths = _crate_path_map(acquisitions)
    material_packages = [
        package
        for package in resolution["packages"]
        if package["classification"] == "MATERIAL_RUNTIME"
    ]
    registry_packages = [
        package
        for package in material_packages
        if package["source"].startswith("registry+")
    ]
    require(
        len(paths) == len(registry_packages),
        "acquisition set diverge da closure material",
    )
    summaries = []
    proc_macro_ids = set()
    for package in registry_packages:
        key = (package["name"], package["version"])
        require(key in paths, f"crate material ausente: {key}")
        summary = inspect_crate(paths[key], package)
        summary["source_path"] = paths[key].as_posix()
        summaries.append(summary)
        if summary["proc_macro"]:
            proc_macro_ids.add(package["id"])

    resolver = CargoResolver(source_root)
    for key, local in resolver.local.items():
        package_id = key.text
        if package_id not in {package["id"] for package in material_packages}:
            continue
        raw = local["raw"]
        if bool(raw.get("lib", {}).get("proc-macro", False)):
            proc_macro_ids.add(package_id)

    adjacency = defaultdict(set)
    for edge in resolution["edges"]:
        if edge["parent_context"] == edge["child_context"] == "normal":
            adjacency[edge["parent"]].add(edge["child"])
    deno_id = next(
        root for root in resolution["authority"]["roots"] if root.startswith("deno@")
    )
    contexts = defaultdict(set)
    queue = deque([(deno_id, "runtime")])
    while queue:
        package_id, context = queue.popleft()
        if context in contexts[package_id]:
            continue
        contexts[package_id].add(context)
        for child in adjacency[package_id]:
            child_context = (
                "codegen"
                if context == "codegen" or child in proc_macro_ids
                else "runtime"
            )
            queue.append((child, child_context))
    material_ids = {package["id"] for package in material_packages}
    require(
        set(contexts) == material_ids,
        "runtime/codegen traversal diverge da closure material",
    )
    runtime_count = 0
    codegen_count = 0
    for package in resolution["packages"]:
        if package["id"] not in material_ids:
            continue
        package_contexts = contexts[package["id"]]
        if package["id"] in proc_macro_ids or package_contexts == {"codegen"}:
            package["classification"] = "MATERIAL_CODEGEN"
            codegen_count += 1
        else:
            package["classification"] = "MATERIAL_RUNTIME"
            runtime_count += 1
        package["material_contexts"] = sorted(package_contexts)
        package["proc_macro"] = package["id"] in proc_macro_ids
    resolution["counts"]["material_runtime"] = runtime_count
    resolution["counts"]["material_codegen"] = codegen_count
    resolution["counts"]["material"] = runtime_count + codegen_count
    license_missing = [
        f"{summary['name']}@{summary['version']}"
        for summary in summaries
        if not summary["license_expression"] or not summary["license_files"]
    ]
    native_review = [
        f"{summary['name']}@{summary['version']}"
        for summary in summaries
        if summary["native_source_coverage"]
        in {"V8_NATIVE_PARENT_REQUIRED", "SOURCE_PARENT_REVIEW_REQUIRED"}
    ]
    inspection = {
        "schema": 1,
        "generated_by": "EduDownloader D10 project tooling",
        "classification": "PROJECT_GENERATED_NOT_UPSTREAM_DENO_NOTICE",
        "counts": {
            "registry_material": len(summaries),
            "proc_macro_registry": sum(item["proc_macro"] for item in summaries),
            "license_inventory_missing": len(license_missing),
            "native_parent_review": len(native_review),
        },
        "license_inventory_missing": license_missing,
        "native_parent_review": native_review,
        "packages": sorted(summaries, key=lambda item: (item["name"], item["version"])),
    }
    return resolution, inspection


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_git_archive(archive_path: Path, prefix: str, tree_path: Path) -> dict:
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    require(not tree.get("truncated", False), f"Git tree truncada: {tree_path}")
    blobs = {
        item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"
    }
    gitlinks = [item for item in tree["tree"] if item["type"] == "commit"]
    actual = {}
    symlinks = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            require(
                member.name.startswith(prefix + "/"),
                f"Git archive root diverge: {member.name}",
            )
            relative = member.name[len(prefix) + 1 :]
            pure = PurePosixPath(relative)
            require(
                relative and not pure.is_absolute() and ".." not in pure.parts,
                "Git archive path inseguro",
            )
            if member.issym():
                data = member.linkname.encode()
                symlinks += 1
            else:
                require(member.isfile(), f"Git archive type inesperado: {relative}")
                stream = archive.extractfile(member)
                require(stream is not None, f"Git archive membro ilegível: {relative}")
                data = stream.read()
            require(relative not in actual, f"Git archive membro duplicado: {relative}")
            actual[relative] = git_blob_sha(data)
    missing = sorted(set(blobs) - set(actual))
    extra = sorted(set(actual) - set(blobs))
    mismatch = sorted(
        path for path in set(blobs) & set(actual) if blobs[path] != actual[path]
    )
    require(
        not missing and not extra and not mismatch,
        f"Git archive não corresponde à tree: {archive_path}",
    )
    return {
        "archive": archive_path.as_posix(),
        "archive_size": archive_path.stat().st_size,
        "archive_sha256": sha256_file(archive_path),
        "tree": tree["sha"],
        "blob_count": len(blobs),
        "archive_file_count": len(actual),
        "symlink_count": symlinks,
        "gitlinks": [
            {"path": item["path"], "commit": item["sha"]} for item in gitlinks
        ],
    }


def archive_member_bytes(path: Path, member_name: str) -> bytes:
    with tarfile.open(path, "r:*") as archive:
        member = archive.getmember(member_name)
        require(member.isfile(), f"archive member não regular: {member_name}")
        stream = archive.extractfile(member)
        require(stream is not None, f"archive member ilegível: {member_name}")
        return stream.read()


def inspect_parents() -> dict:
    deno_archive = INPUT_ROOT / "deno-2.9.5.tar.gz"
    deno_tree_path = WORK_ROOT / "metadata" / "deno" / "tree.json"
    deno = verify_git_archive(deno_archive, "deno-2.9.5", deno_tree_path)
    require(deno["archive_sha256"] == DENO_ARCHIVE_SHA256, "Deno source hash diverge")
    require(deno["tree"] == DENO_TREE, "Deno source tree diverge")

    v8_archive = INPUT_ROOT / f"denoland-v8-{V8_COMMIT}.tar.gz"
    v8_tree_path = WORK_ROOT / "metadata" / "v8" / "tree-recursive.json"
    require(v8_archive.stat().st_size == V8_ARCHIVE_SIZE, "V8 source size diverge")
    v8 = verify_git_archive(v8_archive, f"v8-{V8_COMMIT}", v8_tree_path)
    require(v8["archive_sha256"] == V8_ARCHIVE_SHA256, "V8 source hash diverge")
    require(v8["tree"] == V8_TREE, "V8 source tree diverge")

    v8_crate = INPUT_ROOT / "v8-150.4.0.crate"
    vcs = json.loads(archive_member_bytes(v8_crate, "v8-150.4.0/.cargo_vcs_info.json"))
    require(
        vcs["git"]["sha1"] == "5c15a6995c9bb4bacd3e341b59fff32c909c80bf",
        "rusty_v8 crate commit diverge",
    )
    version_header = archive_member_bytes(
        v8_crate, "v8-150.4.0/v8/include/v8-version.h"
    ).decode()
    for line in (
        "#define V8_MAJOR_VERSION 15",
        "#define V8_MINOR_VERSION 0",
        "#define V8_BUILD_NUMBER 245",
        "#define V8_PATCH_LEVEL 2",
    ):
        require(line in version_header, f"V8 version header diverge: {line}")

    rust_archive = INPUT_ROOT / "rust-src-1.95.0.tar.xz"
    require(rust_archive.stat().st_size == 3_827_368, "rust-src size diverge")
    require(sha256_file(rust_archive) == RUST_SRC_SHA256, "rust-src hash diverge")
    rust_prefix = "rust-src-1.95.0/rust-src/lib/rustlib/src/rust/"
    with tarfile.open(rust_archive, "r:xz") as archive:
        files = {member.name for member in archive.getmembers() if member.isfile()}
    missing_rust = [path for path in RUST_REQUIRED if rust_prefix + path not in files]
    require(not missing_rust, f"rust-src coverage ausente: {missing_rust}")
    channel = tomllib.loads(
        (WORK_ROOT / "metadata" / "rust" / "channel-rust-1.95.0.toml").read_text(
            encoding="utf-8"
        )
    )
    rust_target = channel["pkg"]["rust-src"]["target"]["*"]
    require(
        rust_target["xz_hash"].upper() == RUST_SRC_SHA256,
        "rust channel checksum diverge",
    )
    rust_licenses = []
    for name in ("LICENSE-MIT", "LICENSE-APACHE", "COPYRIGHT"):
        path = WORK_ROOT / "metadata" / "rust" / name
        require(path.is_file(), f"Rust license ausente: {name}")
        rust_licenses.append(
            {
                "path": path.as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    rusty_license = WORK_ROOT / "metadata" / "rusty-v8" / "LICENSE"
    require(rusty_license.is_file(), "rusty_v8 LICENSE ausente")

    v8_rust_archive = INPUT_ROOT / f"chromium-third_party-rust-{V8_RUST_COMMIT}.tar.gz"
    require(
        v8_rust_archive.stat().st_size == V8_RUST_ARCHIVE_SIZE,
        "V8 Rust source size diverge",
    )
    require(
        sha256_file(v8_rust_archive) == V8_RUST_ARCHIVE_SHA256,
        "V8 Rust source hash diverge",
    )
    v8_rust_metadata_path = WORK_ROOT / "metadata" / "v8-rust" / "commit.json"
    v8_rust_metadata = json.loads(v8_rust_metadata_path.read_text(encoding="utf-8"))
    require(v8_rust_metadata["commit"] == V8_RUST_COMMIT, "V8 Rust commit diverge")
    require(v8_rust_metadata["tree"] == V8_RUST_TREE, "V8 Rust tree diverge")
    with tarfile.open(v8_rust_archive, "r:gz") as archive:
        v8_rust_files = []
        for member in archive.getmembers():
            if not member.isfile():
                continue
            pure = PurePosixPath(member.name)
            require(
                member.name and not pure.is_absolute() and ".." not in pure.parts,
                "V8 Rust archive path inseguro",
            )
            v8_rust_files.append(member.name)
    require(
        len(v8_rust_files) == V8_RUST_ARCHIVE_FILE_COUNT,
        "V8 Rust archive file count diverge",
    )

    return {
        "schema": 1,
        "deno": deno,
        "rust": {
            "version": "1.95.0",
            "commit": RUST_COMMIT,
            "tree": RUST_TREE,
            "archive": rust_archive.as_posix(),
            "archive_size": rust_archive.stat().st_size,
            "archive_sha256": RUST_SRC_SHA256,
            "archive_file_count": len(files),
            "required_coverage": list(RUST_REQUIRED),
            "license_evidence": rust_licenses,
        },
        "rusty_v8": {
            "crate_version": "150.4.0",
            "crate_sha256": V8_CRATE_SHA256,
            "commit": vcs["git"]["sha1"],
            "tree": "acf05da94a5a7fd47488a4198a0838a8e114b5d2",
            "license_evidence": {
                "path": rusty_license.as_posix(),
                "size": rusty_license.stat().st_size,
                "sha256": sha256_file(rusty_license),
            },
        },
        "v8": {
            **v8,
            "commit": V8_COMMIT,
            "version": "15.0.245.2-rusty",
            "revision": V8_COMMIT,
            "crate_source_role": "VENDORED_MATERIAL_SOURCE_WITH_EXCLUDED_LICENSE_TEXTS",
            "repository_source_role": "EXACT_V8_PARENT_AND_LICENSES",
        },
        "v8_rust": {
            "commit": V8_RUST_COMMIT,
            "tree": V8_RUST_TREE,
            "archive": v8_rust_archive.as_posix(),
            "archive_url": (
                HTTPS_PREFIX
                + "chromium.googlesource.com/chromium/src/third_party/rust/"
                f"+archive/{V8_RUST_COMMIT}.tar.gz"
            ),
            "archive_size": V8_RUST_ARCHIVE_SIZE,
            "archive_sha256": V8_RUST_ARCHIVE_SHA256,
            "archive_file_count": len(v8_rust_files),
            "source_role": "EXACT_SEPARATE_PARENT_FOR_GN_REACHED_TEMPORAL_RUST",
            "metadata": relative_artifact(v8_rust_metadata_path),
            "metadata_url": (
                HTTPS_PREFIX
                + "chromium.googlesource.com/chromium/src/third_party/rust/"
                f"+/{V8_RUST_COMMIT}?format=JSON"
            ),
        },
    }


def relative_artifact(path: Path) -> dict:
    require(
        path.is_file() and not path.is_symlink(), f"artifact ausente/inseguro: {path}"
    )
    return {
        "path": path.as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def validate_source_member(name: str, data: bytes) -> None:
    pure = PurePosixPath(name)
    require(
        name and not pure.is_absolute() and ".." not in pure.parts,
        "source path inseguro",
    )
    require(
        pure.suffix.lower() not in PROHIBITED_SOURCE_SUFFIXES,
        "payload binário/privado proibido",
    )
    require(
        not data.startswith((b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe")),
        "executável proibido",
    )
    require(
        PRIVATE_PEM_BLOCK_PATTERN.search(data) is None,
        "chave privada proibida",
    )
    lowered_parts = {part.casefold() for part in pure.parts}
    require(
        not lowered_parts.intersection(
            {"activation_issuer", "wheelhouse", "backups", "activation.dat"}
        ),
        "material administrativo privado proibido",
    )


def _metadata_inventory() -> list[dict]:
    root = WORK_ROOT / "metadata"
    return [
        relative_artifact(path) for path in sorted(root.rglob("*")) if path.is_file()
    ]


def _index_inventory() -> list[dict]:
    return [
        relative_artifact(path)
        for path in sorted(INDEX_ROOT.rglob("*"))
        if path.is_file()
    ]


V8_NATIVE_CANDIDATES = (
    ("third_party/icu", "ee5f27adc28bd3f15b2c293f726d14d2e336cbd5", "Unicode-3.0"),
    ("third_party/simdutf", "f7356eed293f8208c40b3c1b344a50bd70971983", "MIT"),
    (
        "third_party/abseil-cpp",
        "d16e32215c3ab90ba57c2e904a5344d85c7353e4",
        "Apache-2.0",
    ),
    ("third_party/partition_alloc", "ff3b8b885b8374cbd3902642d94dc737bda93d5d", None),
    (
        "third_party/libc++/src",
        "5abc7f839700f0f17338434e1c1c6a8c87c00c11",
        "Apache-2.0 WITH LLVM-exception",
    ),
    (
        "third_party/libc++abi/src",
        "8f11bb1d4438d0239d0dfc1bd9456a9f31629dda",
        "Apache-2.0 WITH LLVM-exception",
    ),
    (
        "third_party/libunwind/src",
        "d6c7a21e978f0adaa43accaad53bc64f0b64f6ec",
        "Apache-2.0 WITH LLVM-exception",
    ),
    (
        "third_party/llvm-libc/src",
        "9309c117ebae84dd2f9df1ef99de4782162527d5",
        "Apache-2.0 WITH LLVM-exception",
    ),
    ("third_party/rust", "26e8ff47f18a8d28d6187a04b6a16cb7332356f8", None),
    (
        "third_party/highway/src",
        "2607d3b5b0113992fe84d3848859eae13b3b52c1",
        "Apache-2.0",
    ),
    (
        "third_party/fast_float/src",
        "05087a303dad9c98768b33c829d398223a649bc6",
        "MIT OR Apache-2.0 OR BSL-1.0",
    ),
    ("third_party/fp16/src", "3d2de1816307bac63c16a297e8c4dc501b4076df", "MIT"),
    ("third_party/dragonbox/src", "beeeef91cf6fef89a4d4ba5e95d47ca64ccb3a44", None),
    (
        "third_party/googletest/src",
        "4fe3307fb2d9f86d19777c7eb0e4809e9694dde7",
        "BSD-3-Clause",
    ),
)

V8_NATIVE_CLASSIFICATIONS = {
    "third_party/icu": "VENDORED_WITH_V8",
    "third_party/simdutf": "VENDORED_WITH_V8",
    "third_party/abseil-cpp": "VENDORED_WITH_V8",
    "third_party/partition_alloc": "FEATURE_DISABLED",
    "third_party/libc++/src": "VENDORED_WITH_V8",
    "third_party/libc++abi/src": "TARGET_NOT_APPLICABLE",
    "third_party/libunwind/src": "TARGET_NOT_APPLICABLE",
    "third_party/llvm-libc/src": "VENDORED_WITH_V8",
    "third_party/rust": "MATERIAL_SOURCE_PARENT",
    "third_party/highway/src": "VENDORED_WITH_V8",
    "third_party/fast_float/src": "VENDORED_WITH_V8",
    "third_party/fp16/src": "VENDORED_WITH_V8",
    "third_party/dragonbox/src": "VENDORED_WITH_V8",
    "third_party/googletest/src": "TEST_ONLY",
}
V8_MATERIAL_CLASSIFICATIONS = {"MATERIAL_SOURCE_PARENT", "VENDORED_WITH_V8"}
V8_GN_EXPLICIT_ARGS = {
    "is_debug": False,
    "rusty_v8_enable_simdutf": True,
    "use_custom_libcxx": True,
    "v8_enable_pointer_compression": False,
    "v8_enable_sandbox": False,
    "v8_enable_v8_checks": False,
}
V8_GN_EFFECTIVE_SOURCE_ARGS = {
    **V8_GN_EXPLICIT_ARGS,
    "enable_rust": True,
    "enable_rust_cxx": True,
    "icu_use_data_file": False,
    "is_component_build": False,
    "symbol_level": 1,
    "use_custom_libunwind": False,
    "v8_depend_on_icu_data_file": False,
    "v8_enable_fuzztest": False,
    "v8_enable_i18n_support": True,
    "v8_enable_partition_alloc": False,
    "v8_enable_snapshot_compression": False,
    "v8_enable_temporal_support": True,
    "v8_enable_wasm_simd256_revec": True,
    "v8_enable_webassembly": True,
    "v8_monolithic": False,
    "v8_use_external_startup_data": False,
    "v8_use_zlib": False,
}
V8_CANDIDATE_TARGET_PREFIXES = {
    "third_party/icu": ("//third_party/icu",),
    "third_party/simdutf": ("//third_party/simdutf",),
    "third_party/abseil-cpp": ("//third_party/abseil-cpp",),
    "third_party/partition_alloc": ("//third_party/partition_alloc",),
    "third_party/libc++/src": ("//buildtools/third_party/libc++",),
    "third_party/libc++abi/src": ("//buildtools/third_party/libc++abi",),
    "third_party/libunwind/src": ("//buildtools/third_party/libunwind",),
    "third_party/llvm-libc/src": ("//third_party/llvm-libc",),
    "third_party/rust": ("//third_party/rust",),
    "third_party/highway/src": ("//third_party/highway",),
    "third_party/fast_float/src": ("//third_party/fast_float",),
    "third_party/fp16/src": ("//third_party/fp16",),
    "third_party/dragonbox/src": ("//third_party/dragonbox",),
    "third_party/googletest/src": ("//third_party/googletest",),
}
V8_CONFIG_SOURCE_EVIDENCE = {
    "third_party/llvm-libc/src": (
        "third_party/llvm-libc/src/include/llvm-libc-types/mbstate_t.h",
    ),
}
V8_EXCLUDED_CANDIDATE_EVIDENCE = {
    "third_party/partition_alloc": {
        "authority": "GN_EFFECTIVE_ARG",
        "condition": "v8_enable_partition_alloc=false",
    },
    "third_party/libc++abi/src": {
        "authority": "GN_WINDOWS_CONDITION",
        "condition": (
            "//buildtools/third_party/libc++:libc++ adds libc++abi only when !is_win"
        ),
    },
    "third_party/libunwind/src": {
        "authority": "GN_EFFECTIVE_ARG",
        "condition": "use_custom_libunwind=false",
    },
    "third_party/googletest/src": {
        "authority": "GN_TARGET_UNIVERSE",
        "condition": "all candidate targets are testonly and none is root-reachable",
    },
}
V8_NATIVE_LICENSE_FILES = {
    "third_party/icu": ("icu/LICENSE",),
    "third_party/simdutf": ("simdutf/LICENSE",),
    "third_party/abseil-cpp": ("abseil-cpp/LICENSE",),
    "third_party/libc++/src": ("libcxx/LICENSE.TXT",),
    "third_party/llvm-libc/src": ("llvm-libc/LICENSE.TXT",),
    "third_party/fast_float/src": (
        "fast_float/LICENSE-APACHE",
        "fast_float/LICENSE-BOOST",
        "fast_float/LICENSE-MIT",
    ),
    "third_party/dragonbox/src": (
        "dragonbox/LICENSE-Apache2-LLVM",
        "dragonbox/LICENSE-Boost",
    ),
}
V8_NATIVE_LICENSE_REPOSITORIES = {
    "third_party/icu": HTTPS_PREFIX + "chromium.googlesource.com/chromium/deps/icu",
    "third_party/simdutf": (
        HTTPS_PREFIX + "chromium.googlesource.com/chromium/src/third_party/simdutf"
    ),
    "third_party/abseil-cpp": (
        HTTPS_PREFIX + "chromium.googlesource.com/chromium/src/third_party/abseil-cpp"
    ),
    "third_party/libc++/src": (
        HTTPS_PREFIX
        + "chromium.googlesource.com/external/github.com/llvm/llvm-project/libcxx"
    ),
    "third_party/llvm-libc/src": (
        HTTPS_PREFIX
        + "chromium.googlesource.com/external/github.com/llvm/llvm-project/libc"
    ),
    "third_party/fast_float/src": (
        HTTPS_PREFIX
        + "chromium.googlesource.com/external/github.com/fastfloat/fast_float"
    ),
    "third_party/dragonbox/src": (
        HTTPS_PREFIX + "chromium.googlesource.com/external/github.com/jk-jeon/dragonbox"
    ),
}
V8_ARCHIVE_LICENSE_FILES = {
    "third_party/highway/src": ("third_party/highway/LICENSE",),
    "third_party/fp16/src": ("third_party/fp16/LICENSE",),
}
V8_LICENSE_EXPRESSIONS = {
    "third_party/icu": "Unicode-3.0",
    "third_party/simdutf": "MIT",
    "third_party/abseil-cpp": "Apache-2.0",
    "third_party/libc++/src": "Apache-2.0 WITH LLVM-exception",
    "third_party/llvm-libc/src": "Apache-2.0 WITH LLVM-exception",
    "third_party/rust": "MULTIPLE_PER_REACHED_CRATE",
    "third_party/highway/src": "Apache-2.0",
    "third_party/fast_float/src": "MIT OR Apache-2.0 OR BSL-1.0",
    "third_party/fp16/src": "MIT",
    "third_party/dragonbox/src": ("(Apache-2.0 WITH LLVM-exception) OR BSL-1.0"),
}
V8_OTHER_THIRD_PARTY_LICENSES = {
    "v8/third_party/glibc": ("LGPL-2.1-or-later", ("third_party/glibc/LICENSE",)),
    "v8/third_party/inspector_protocol": (
        "BSD-3-Clause",
        ("third_party/inspector_protocol/LICENSE",),
    ),
    "v8/third_party/rapidhash-v8": (
        "BSD-2-Clause",
        ("third_party/rapidhash-v8/LICENSE",),
    ),
    "v8/third_party/siphash": ("CC0-1.0", ("third_party/siphash/LICENSE",)),
    "v8/third_party/utf8-decoder": (
        "MIT",
        ("third_party/utf8-decoder/LICENSE",),
    ),
    "v8/third_party/v8": (
        "PSF-2.0 AND MIT",
        ("third_party/v8/builtins/LICENSE", "third_party/v8/codegen/LICENSE"),
    ),
    "v8/third_party/valgrind": (
        "BSD-4-Clause",
        ("third_party/valgrind/LICENSE",),
    ),
}


def archive_member_record(path: Path, member_name: str) -> dict:
    with tarfile.open(path, "r:*") as archive:
        return _open_archive_member_record(archive, path, member_name)


def _open_archive_member_record(
    archive: tarfile.TarFile, path: Path, member_name: str
) -> dict:
    member = archive.getmember(member_name)
    require(member.isfile(), f"archive member não regular: {member_name}")
    stream = archive.extractfile(member)
    require(stream is not None, f"archive member ilegível: {member_name}")
    data = stream.read()
    return {
        "path": f"{path.as_posix()}::{member_name}",
        "size": len(data),
        "sha256": sha256_bytes(data),
    }


def _normalize_gn_path(value: str, build_dir: str) -> str:
    normalized = value.replace("\\", "/")
    normalized_build = build_dir.replace("\\", "/").rstrip("/") + "/"
    if normalized.startswith(normalized_build):
        return "$BUILD_DIR/" + normalized[len(normalized_build) :]
    require(
        normalized.startswith("//") or not re.match(r"^/?[A-Za-z]:/", normalized),
        f"GN path absoluto inesperado: {value}",
    )
    return normalized


def _target_closure(targets: dict, root: str) -> list[str]:
    require(root in targets, f"GN root target ausente: {root}")
    seen = set()
    pending = [root]
    while pending:
        label = pending.pop()
        if label in seen:
            continue
        require(label in targets, f"GN dependency target ausente: {label}")
        seen.add(label)
        pending.extend(targets[label].get("deps", []))
    return sorted(seen)


def _gn_declared_paths(target: dict) -> list[str]:
    public = target.get("public", [])
    if not isinstance(public, list):
        public = []
    return [*target.get("sources", []), *public]


def _v8_rust_notice_inventory(
    archive_path: Path, vendor_directories: set[str]
) -> list[dict]:
    result = []
    with tarfile.open(archive_path, "r:gz") as archive:
        regular = {
            member.name: member for member in archive.getmembers() if member.isfile()
        }
        for directory in sorted(vendor_directories):
            prefix = f"chromium_crates_io/vendor/{directory}/"
            cargo_name = prefix + "Cargo.toml"
            require(cargo_name in regular, f"V8 Rust Cargo.toml ausente: {directory}")
            stream = archive.extractfile(regular[cargo_name])
            require(stream is not None, f"V8 Rust Cargo.toml ilegível: {directory}")
            package = tomllib.loads(stream.read().decode())["package"]
            license_members = []
            for name in sorted(regular):
                if not name.startswith(prefix):
                    continue
                leaf = name[len(prefix) :]
                if "/" in leaf:
                    continue
                if re.match(
                    r"^(?:LICENSE|COPYING|COPYRIGHT|NOTICE)(?:[.\-_]|$)", leaf, re.I
                ):
                    license_members.append(
                        _open_archive_member_record(archive, archive_path, name)
                    )
            require(
                package.get("license") or package.get("license-file"),
                f"V8 Rust license identity ausente: {directory}",
            )
            require(license_members, f"V8 Rust license text ausente: {directory}")
            result.append(
                {
                    "directory": directory,
                    "name": package["name"],
                    "version": package["version"],
                    "license_expression": package.get("license"),
                    "license_file_declared": package.get("license-file"),
                    "license_files": license_members,
                    "notice_identity_status": "VERIFIED",
                }
            )
    return result


def build_v8_native_closure(parents: dict) -> dict:
    project_path = V8_GN_PROJECT_PATH
    source_root = WORK_ROOT / "work" / "v8" / "v8-150.4.0"
    rust_archive = INPUT_ROOT / f"chromium-third_party-rust-{V8_RUST_COMMIT}.tar.gz"
    require(
        parents["rusty_v8"]["commit"] == "5c15a6995c9bb4bacd3e341b59fff32c909c80bf",
        "rusty_v8 trace parent diverge",
    )
    require(parents["v8"]["commit"] == V8_COMMIT, "V8 trace parent diverge")
    require(
        parents["v8_rust"]["commit"] == V8_RUST_COMMIT, "V8 Rust trace parent diverge"
    )
    workflow = WORK_ROOT / "metadata" / "rusty-v8" / "ci.yml"
    require(
        sha256_file(workflow) == RUSTY_V8_CI_SHA256, "rusty_v8 workflow hash diverge"
    )
    require(
        git_blob_sha(workflow.read_bytes()) == RUSTY_V8_CI_GIT_BLOB,
        "rusty_v8 workflow blob diverge",
    )
    gn_path = WORK_ROOT / "tools" / "gn-ninja" / "gn" / "gn.exe"
    ninja_path = WORK_ROOT / "tools" / "gn-ninja" / "ninja" / "ninja.exe"
    require(sha256_file(gn_path) == GN_SHA256, "GN executable hash diverge")
    require(sha256_file(ninja_path) == NINJA_SHA256, "Ninja executable hash diverge")
    args_path = project_path.with_name("args.gn")
    parsed_args = {}
    for raw_line in args_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, raw_value = line.partition("=")
        require(separator == "=", f"GN args line inválida: {raw_line}")
        parsed_args[name.strip()] = raw_value.strip()
    expected_arg_names = set(V8_GN_EXPLICIT_ARGS) | {
        "clang_base_path",
        "cc_wrapper",
        "rust_sysroot_absolute",
        "rustc_version",
    }
    require(set(parsed_args) == expected_arg_names, "GN args input set diverge")
    for name, value in V8_GN_EXPLICIT_ARGS.items():
        require(
            parsed_args[name] == str(value).lower(), f"GN explicit arg diverge: {name}"
        )
    require(
        parsed_args["rustc_version"] == '"TRACE_HARNESS_NO_COMPILER"',
        "GN trace harness identity diverge",
    )
    project = json.loads(project_path.read_text(encoding="utf-8"))
    require(
        set(project) == {"build_settings", "targets", "toolchains"},
        "GN project schema diverge",
    )
    require(len(project["targets"]) == 731, "GN generated target universe diverge")
    require(
        project["build_settings"]["default_toolchain"] == V8_GN_DEFAULT_TOOLCHAIN,
        "GN default toolchain diverge",
    )
    targets = project["targets"]
    closure = _target_closure(targets, V8_GN_ROOT_TARGET)
    root = targets[V8_GN_ROOT_TARGET]
    require(root["type"] == "static_library", "rusty_v8 root type diverge")
    require(
        any(
            str(output).replace("\\", "/").endswith("/obj/rusty_v8.lib")
            for output in root["outputs"]
        ),
        "rusty_v8 root output diverge",
    )
    require(
        "//third_party/simdutf:simdutf" in root["deps"],
        "rusty_v8 simdutf dependency ausente",
    )
    require(
        not any(targets[label].get("testonly") for label in closure),
        "test target alcançado",
    )

    role_by_type = {
        "static_library": "source_targets",
        "source_set": "source_targets",
        "rust_library": "source_targets",
        "rust_proc_macro": "source_targets",
        "action": "generated_targets",
        "copy": "generated_targets",
        "executable": "build_only_targets",
        "group": "build_only_targets",
    }
    role_counts = defaultdict(int)
    for label in closure:
        target_type = targets[label]["type"]
        require(
            target_type in role_by_type,
            f"GN target type sem classificação: {target_type}",
        )
        role_counts[role_by_type[target_type]] += 1

    build_dir = project["build_settings"]["build_dir"]
    graph = []
    all_paths = []
    edges = []
    for label in closure:
        target = targets[label]
        deps = sorted(target.get("deps", []))
        edges.extend({"from": label, "to": dep} for dep in deps)
        sources = [
            _normalize_gn_path(path, build_dir)
            for path in _gn_declared_paths(target)
            if path
        ]
        all_paths.extend(sources)
        graph.append(
            {
                "label": label,
                "type": target["type"],
                "testonly": bool(target.get("testonly")),
                "toolchain": target["toolchain"],
                "deps": deps,
                "sources": sorted(sources),
                "outputs": sorted(
                    _normalize_gn_path(path, build_dir)
                    for path in target.get("outputs", [])
                ),
            }
        )

    unique_paths = sorted(set(all_paths))
    crate_covered = []
    rust_covered = []
    generated = []
    rust_members = set()
    with tarfile.open(rust_archive, "r:gz") as archive:
        rust_members = {
            member.name for member in archive.getmembers() if member.isfile()
        }
    for path in unique_paths:
        if path.startswith("$BUILD_DIR/"):
            generated.append(path)
            continue
        require(path.startswith("//"), f"GN source path inválido: {path}")
        relative = path[2:]
        if (source_root / PurePosixPath(relative)).is_file():
            crate_covered.append(path)
        elif path.startswith("//third_party/rust/"):
            member = path[len("//third_party/rust/") :]
            require(member in rust_members, f"V8 Rust source ausente: {member}")
            rust_covered.append(path)
        else:
            raise SourceBundleError(f"GN source material sem parent: {path}")

    generated_outputs = {
        item
        for record in graph
        for item in record["outputs"]
        if item.startswith("$BUILD_DIR/")
    }
    require(
        set(generated).issubset(generated_outputs),
        "GN generated source sem action/output coberto",
    )

    archive_v8 = INPUT_ROOT / f"denoland-v8-{V8_COMMIT}.tar.gz"
    v8_prefix = f"v8-{V8_COMMIT}/"
    needed_v8_license_members = {
        v8_prefix + member
        for members in (
            *V8_ARCHIVE_LICENSE_FILES.values(),
            *(item[1] for item in V8_OTHER_THIRD_PARTY_LICENSES.values()),
        )
        for member in members
    }
    with tarfile.open(archive_v8, "r:gz") as archive:
        v8_license_records = {
            member: _open_archive_member_record(archive, archive_v8, member)
            for member in sorted(needed_v8_license_members)
        }
    candidates = []
    for path, revision, _d10_expression in V8_NATIVE_CANDIDATES:
        classification = V8_NATIVE_CLASSIFICATIONS[path]
        prefixes = V8_CANDIDATE_TARGET_PREFIXES[path]
        reached_targets = sorted(
            label for label in closure if label.startswith(prefixes)
        )
        universe_targets = sorted(
            label for label in targets if label.startswith(prefixes)
        )
        material = classification in V8_MATERIAL_CLASSIFICATIONS
        if material:
            require(reached_targets, f"material V8 candidate sem target: {path}")
        elif classification == "TEST_ONLY":
            require(universe_targets, f"V8 test-only candidate sem target: {path}")
            require(
                all(targets[label].get("testonly") for label in universe_targets),
                f"V8 candidate não exclusivamente test-only: {path}",
            )
            require(not reached_targets, f"V8 test-only candidate alcançado: {path}")
        else:
            require(not reached_targets, f"V8 excluded candidate alcançado: {path}")
        candidate_sources = sorted(
            item for item in unique_paths if item.startswith("//" + path + "/")
        )
        if path == "third_party/libc++/src":
            candidate_sources = sorted(
                item
                for item in unique_paths
                if item.startswith("//third_party/libc++/src/")
            )
        config_source_evidence = []
        for relative in V8_CONFIG_SOURCE_EVIDENCE.get(path, ()):
            source_path = source_root / PurePosixPath(relative)
            require(source_path.is_file(), f"V8 config source ausente: {relative}")
            config_source_evidence.append(
                {
                    "path": "//" + relative,
                    "size": source_path.stat().st_size,
                    "sha256": sha256_file(source_path),
                    "authority": "GN_PUBLIC_CONFIG_INCLUDE_SOURCE",
                }
            )
        if config_source_evidence:
            candidate_sources = sorted(
                {*candidate_sources, *(item["path"] for item in config_source_evidence)}
            )
        if material:
            require(candidate_sources, f"material V8 candidate sem source: {path}")
        candidate_target_set = set(reached_targets)
        consumer_edges = sorted(
            (
                edge
                for edge in edges
                if edge["to"] in candidate_target_set
                and edge["from"] not in candidate_target_set
            ),
            key=lambda item: (item["from"], item["to"]),
        )
        if material:
            require(consumer_edges, f"material V8 candidate sem consumer edge: {path}")
        license_files = []
        for relative in V8_NATIVE_LICENSE_FILES.get(path, ()):
            evidence = relative_artifact(
                WORK_ROOT / "metadata" / "v8-native-licenses" / relative
            )
            filename = PurePosixPath(relative).name
            evidence["origin"] = (
                f"{V8_NATIVE_LICENSE_REPOSITORIES[path]}/+/"
                f"{revision}/{filename}?format=TEXT"
            )
            license_files.append(evidence)
        for member in V8_ARCHIVE_LICENSE_FILES.get(path, ()):
            license_files.append(v8_license_records[v8_prefix + member])
        record = {
            "path": path,
            "revision": revision,
            "classification": classification,
            "material": material,
            "targets": reached_targets,
            "universe_targets": universe_targets if not reached_targets else [],
            "consumer_edges": consumer_edges,
            "source_paths": candidate_sources,
            "config_source_evidence": config_source_evidence,
            "selection_evidence": (
                {
                    "authority": "GN_ROOT_TRANSITIVE_DEPENDENCY",
                    "consumer_edges": consumer_edges,
                }
                if material
                else V8_EXCLUDED_CANDIDATE_EVIDENCE[path]
            ),
            "source_coverage": (
                "SEPARATE_PARENT_REQUIRED"
                if path == "third_party/rust"
                else "COVERED_BY_RUSTY_V8_PARENT"
                if material
                else "NOT_REQUIRED"
            ),
            "source_status": "RESOLVED" if material else "NOT_REQUIRED",
            "license_expression": V8_LICENSE_EXPRESSIONS.get(path),
            "license_files": license_files,
            "notice_identity_status": "VERIFIED" if material else "NOT_APPLICABLE",
        }
        candidates.append(record)

    rust_vendors = {
        path.split("/")[6]
        for path in rust_covered
        if path.startswith("//third_party/rust/chromium_crates_io/vendor/")
    }
    rust_notices = _v8_rust_notice_inventory(rust_archive, rust_vendors)
    require(len(rust_notices) == 45, "V8 Rust material crate count diverge")
    rust_record = next(
        item for item in candidates if item["path"] == "third_party/rust"
    )
    rust_record["license_components"] = rust_notices
    rust_record["notice_identity_status"] = "VERIFIED_45_REACHED_CRATES"

    other_third_party = []
    for component, (
        expression,
        license_members,
    ) in V8_OTHER_THIRD_PARTY_LICENSES.items():
        component_sources = sorted(
            item for item in unique_paths if item.startswith("//" + component + "/")
        )
        require(component_sources, f"V8 third_party material ausente: {component}")
        other_third_party.append(
            {
                "component": component,
                "classification": "VENDORED_WITH_V8",
                "source_coverage": "COVERED_BY_V8_PARENT",
                "source_paths": component_sources,
                "license_expression": expression,
                "license_files": [
                    v8_license_records[v8_prefix + member] for member in license_members
                ],
                "notice_identity_status": "VERIFIED",
            }
        )

    codegen_targets = {
        "torque": [
            "//v8:torque",
            "//v8:torque_base",
            "//v8:run_torque",
            "//v8:torque_generated_definitions",
            "//v8:torque_generated_initializers",
            "//v8:torque_runtime_support",
        ],
        "snapshot": [
            "//v8:mksnapshot",
            "//v8:run_mksnapshot_default",
            "//v8:v8_snapshot",
        ],
        "bytecode_builtins": [
            "//v8:bytecode_builtins_list_generator",
            "//v8:generate_bytecode_builtins_list",
        ],
        "regexp_special_case": [
            "//v8:gen-regexp-special-case",
            "//v8:run_gen-regexp-special-case",
        ],
        "embedded_assembly": ["//v8:asm_to_inline_asm_default"],
    }
    for name, labels in codegen_targets.items():
        require(set(labels).issubset(closure), f"V8 codegen closure diverge: {name}")

    sorted_edges = sorted(edges, key=lambda item: (item["from"], item["to"]))
    normalized_graph_sha256 = sha256_bytes(canonical(graph))
    return {
        "status": "RESOLVED_EXACT_GN_TRACE",
        "authority": {
            "rusty_v8_workflow": {
                "path": "build-compliance-deno/metadata/rusty-v8/ci.yml",
                "sha256": RUSTY_V8_CI_SHA256,
                "git_blob": RUSTY_V8_CI_GIT_BLOB,
                "commit": parents["rusty_v8"]["commit"],
                "job": "release x86_64-pc-windows-msvc simdutf",
                "environment": {"V8_FROM_SOURCE": True, "RUSTFLAGS": "-D warnings"},
                "artifact": "rusty_v8_simdutf_release_x86_64-pc-windows-msvc.lib.gz",
            },
            "gn": {"revision": GN_REVISION, "sha256": GN_SHA256},
            "ninja": {
                "version": NINJA_VERSION,
                "cipd_version": NINJA_CIPD_VERSION,
                "sha256": NINJA_SHA256,
            },
            "trace_harness": (
                "SOURCE_MATERIALITY_EXACT_TOOLCHAIN_PATHS_NORMALIZED; no compiler, "
                "Ninja, Cargo, Rust or V8 binary build executed"
            ),
            "patching": (
                "RUSTY_V8_150_4_0_CRATE_SOURCE_IS_THE_PATCHED_V8_BUILD_AUTHORITY; "
                "no additional Deno patch layer applied by this trace"
            ),
        },
        "target": {
            "triple": TARGET,
            "os": "windows",
            "cpu": "x64",
            "toolchain": V8_GN_DEFAULT_TOOLCHAIN,
            "profile": "release",
            "simdutf": True,
        },
        "gn_args": {
            "explicit_from_rusty_v8_build_rs": V8_GN_EXPLICIT_ARGS,
            "effective_source_selection": V8_GN_EFFECTIVE_SOURCE_ARGS,
            "target_cpu_and_os": (
                "native x86_64 Windows defaults; workflow target and "
                "//build/toolchain/win:win_clang_x64 are the effective authority"
            ),
            "trace_only_overrides": [
                "clang_base_path",
                "cc_wrapper",
                "rust_sysroot_absolute",
                "rustc_version",
            ],
        },
        "root_target": {
            "label": V8_GN_ROOT_TARGET,
            "type": root["type"],
            "output": "$BUILD_DIR/obj/rusty_v8.lib",
            "linkage": "STATIC_LIBRARY_NON_COMPONENT_BUILD",
            "direct_deps": sorted(root["deps"]),
        },
        "trace_method": "GN_PROJECT_JSON_TRANSITIVE_DEPS_WITH_SOURCE_PUBLIC_AND_OUTPUT_COVERAGE",
        "counts": {
            "generated_universe_targets": len(targets),
            "reached_targets": len(closure),
            **dict(role_counts),
            "reached_edges": len(edges),
            "declared_source_references": len(all_paths),
            "unique_source_paths": len(unique_paths),
            "covered_by_rusty_v8_parent": len(crate_covered),
            "covered_by_separate_v8_rust_parent": len(rust_covered),
            "generated_from_covered_source": len(generated),
            "v8_candidates": len(candidates),
            "v8_material_candidates": sum(item["material"] for item in candidates),
            "v8_excluded_candidates": sum(not item["material"] for item in candidates),
            "v8_rust_license_components": len(rust_notices),
            "other_material_v8_third_party": len(other_third_party),
        },
        "closure_targets": closure,
        "closure_targets_sha256": sha256_bytes(canonical(closure)),
        "closure_edges": sorted_edges,
        "closure_edges_sha256": sha256_bytes(canonical(sorted_edges)),
        "normalized_graph_sha256": normalized_graph_sha256,
        "source_path_inventory_sha256": sha256_bytes(canonical(unique_paths)),
        "source_coverage": {
            "rusty_v8_parent": {
                "status": "COVERED",
                "rusty_v8_commit": parents["rusty_v8"]["commit"],
                "rusty_v8_crate_sha256": parents["rusty_v8"]["crate_sha256"],
                "v8_revision": parents["v8"]["revision"],
                "v8_tree": parents["v8"]["tree"],
                "path_count": len(crate_covered),
                "inventory_sha256": sha256_bytes(canonical(crate_covered)),
            },
            "v8_rust_parent": {
                "status": "COVERED",
                "commit": V8_RUST_COMMIT,
                "tree": V8_RUST_TREE,
                "archive_sha256": V8_RUST_ARCHIVE_SHA256,
                "path_count": len(rust_covered),
                "inventory_sha256": sha256_bytes(canonical(rust_covered)),
            },
            "generated": {
                "status": "GENERATED_FROM_COVERED_SOURCE",
                "path_count": len(generated),
                "inventory_sha256": sha256_bytes(canonical(generated)),
            },
            "missing": [],
        },
        "candidates": candidates,
        "zlib": {
            "revision": "3246f1b60849cc505e231c5d19d0cbf358093555",
            "classification": "TARGET_NOT_APPLICABLE",
            "targets": [],
            "evidence": {
                "v8_use_zlib": False,
                "v8_enable_snapshot_compression": False,
            },
        },
        "codegen": {
            "classification": "GENERATED_FROM_COVERED_SOURCE",
            "targets": codegen_targets,
            "source_coverage": "COVERED_BY_V8_AND_RUSTY_V8_PARENTS",
        },
        "other_material_v8_third_party": other_third_party,
        "remaining_unknowns": [],
    }


def validate_v8_native_closure(trace: dict) -> None:
    require(trace["status"] == "RESOLVED_EXACT_GN_TRACE", "V8 GN trace status diverge")
    authority = trace["authority"]
    workflow = authority["rusty_v8_workflow"]
    require(workflow["sha256"] == RUSTY_V8_CI_SHA256, "rusty_v8 workflow hash diverge")
    require(
        workflow["git_blob"] == RUSTY_V8_CI_GIT_BLOB, "rusty_v8 workflow blob diverge"
    )
    require(
        workflow["artifact"]
        == "rusty_v8_simdutf_release_x86_64-pc-windows-msvc.lib.gz",
        "rusty_v8 workflow artifact diverge",
    )
    require(
        authority["gn"] == {"revision": GN_REVISION, "sha256": GN_SHA256},
        "GN authority diverge",
    )
    require(
        authority["ninja"]
        == {
            "version": NINJA_VERSION,
            "cipd_version": NINJA_CIPD_VERSION,
            "sha256": NINJA_SHA256,
        },
        "Ninja authority diverge",
    )
    require(trace["target"]["triple"] == TARGET, "V8 GN target triple diverge")
    require(
        trace["target"]["toolchain"] == V8_GN_DEFAULT_TOOLCHAIN,
        "V8 GN toolchain diverge",
    )
    require(
        trace["target"]
        == {
            "triple": TARGET,
            "os": "windows",
            "cpu": "x64",
            "toolchain": V8_GN_DEFAULT_TOOLCHAIN,
            "profile": "release",
            "simdutf": True,
        },
        "V8 GN target identity diverge",
    )
    require(trace["root_target"]["label"] == V8_GN_ROOT_TARGET, "V8 GN root diverge")
    require(trace["root_target"]["type"] == "static_library", "V8 GN root type diverge")
    require(
        trace["root_target"]["output"] == "$BUILD_DIR/obj/rusty_v8.lib",
        "V8 GN output diverge",
    )
    require(
        trace["root_target"]["linkage"] == "STATIC_LIBRARY_NON_COMPONENT_BUILD",
        "V8 GN linkage diverge",
    )
    require(
        "//third_party/simdutf:simdutf" in trace["root_target"]["direct_deps"],
        "V8 GN simdutf root edge diverge",
    )
    require(
        trace["gn_args"]["explicit_from_rusty_v8_build_rs"] == V8_GN_EXPLICIT_ARGS,
        "V8 GN explicit args diverge",
    )
    require(
        trace["gn_args"]["effective_source_selection"] == V8_GN_EFFECTIVE_SOURCE_ARGS,
        "V8 GN effective args diverge",
    )
    expected_counts = {
        "generated_universe_targets": 731,
        "reached_targets": 356,
        "source_targets": 273,
        "generated_targets": 39,
        "build_only_targets": 44,
        "reached_edges": 1710,
        "declared_source_references": 6647,
        "unique_source_paths": 6576,
        "covered_by_rusty_v8_parent": 4456,
        "covered_by_separate_v8_rust_parent": 793,
        "generated_from_covered_source": 1327,
        "v8_candidates": 14,
        "v8_material_candidates": 10,
        "v8_excluded_candidates": 4,
        "v8_rust_license_components": 45,
        "other_material_v8_third_party": 7,
    }
    for key, value in expected_counts.items():
        require(trace["counts"].get(key) == value, f"V8 GN trace count diverge: {key}")
    require(len(trace["closure_targets"]) == 356, "V8 GN closure target list diverge")
    require(len(trace["closure_edges"]) == 1710, "V8 GN closure edge list diverge")
    require(
        sha256_bytes(canonical(trace["closure_targets"]))
        == trace["closure_targets_sha256"]
        == V8_CLOSURE_TARGETS_SHA256,
        "V8 GN closure targets hash diverge",
    )
    require(
        sha256_bytes(canonical(trace["closure_edges"]))
        == trace["closure_edges_sha256"]
        == V8_CLOSURE_EDGES_SHA256,
        "V8 GN closure edges hash diverge",
    )
    require(
        trace["normalized_graph_sha256"] == V8_NORMALIZED_GRAPH_SHA256,
        "V8 GN normalized graph hash diverge",
    )
    require(
        trace["source_path_inventory_sha256"] == V8_SOURCE_PATH_INVENTORY_SHA256,
        "V8 GN source inventory hash diverge",
    )
    require(len(trace["candidates"]) == 14, "V8 candidate inventory diverge")
    actual = {item["path"]: item["classification"] for item in trace["candidates"]}
    require(actual == V8_NATIVE_CLASSIFICATIONS, "V8 candidate classification diverge")
    revisions = {path: revision for path, revision, _expression in V8_NATIVE_CANDIDATES}
    candidate_by_path = {item["path"]: item for item in trace["candidates"]}
    for candidate in trace["candidates"]:
        path = candidate["path"]
        require(
            candidate["revision"] == revisions[path],
            f"V8 candidate revision diverge: {path}",
        )
        if candidate["material"]:
            require(candidate["targets"], f"V8 material target ausente: {path}")
            require(
                candidate["consumer_edges"],
                f"V8 material consumer edge ausente: {path}",
            )
            require(candidate["source_paths"], f"V8 material source ausente: {path}")
            require(
                candidate["source_status"] == "RESOLVED",
                f"V8 source status diverge: {path}",
            )
        else:
            require(not candidate["targets"], f"V8 excluded target alcançado: {path}")
            require(
                candidate["selection_evidence"] == V8_EXCLUDED_CANDIDATE_EVIDENCE[path],
                f"V8 excluded evidence diverge: {path}",
            )
    llvm_libc = candidate_by_path["third_party/llvm-libc/src"]
    require(
        llvm_libc["config_source_evidence"]
        == [
            {
                "path": (
                    "//third_party/llvm-libc/src/include/llvm-libc-types/mbstate_t.h"
                ),
                "size": 621,
                "sha256": (
                    "6F6B3DEF4D45E0EC490E5FA18CE078A800211BF5844C0214C365BF3E489D84CE"
                ),
                "authority": "GN_PUBLIC_CONFIG_INCLUDE_SOURCE",
            }
        ],
        "V8 llvm-libc config source evidence diverge",
    )
    require(
        all(
            item["notice_identity_status"].startswith("VERIFIED")
            for item in trace["candidates"]
            if item["material"]
        ),
        "V8 native notice identity incomplete",
    )
    require(
        trace["source_coverage"]["v8_rust_parent"]["commit"] == V8_RUST_COMMIT
        and trace["source_coverage"]["v8_rust_parent"]["tree"] == V8_RUST_TREE
        and trace["source_coverage"]["v8_rust_parent"]["archive_sha256"]
        == V8_RUST_ARCHIVE_SHA256,
        "V8 Rust source parent identity diverge",
    )
    require(
        trace["source_coverage"]["rusty_v8_parent"]["rusty_v8_commit"]
        == "5c15a6995c9bb4bacd3e341b59fff32c909c80bf"
        and trace["source_coverage"]["rusty_v8_parent"]["rusty_v8_crate_sha256"]
        == V8_CRATE_SHA256
        and trace["source_coverage"]["rusty_v8_parent"]["v8_revision"] == V8_COMMIT
        and trace["source_coverage"]["rusty_v8_parent"]["v8_tree"] == V8_TREE,
        "rusty_v8/V8 source parent identity diverge",
    )
    require(
        trace["source_coverage"]["rusty_v8_parent"]["inventory_sha256"]
        == V8_RUSTY_PARENT_PATHS_SHA256
        and trace["source_coverage"]["v8_rust_parent"]["inventory_sha256"]
        == V8_SEPARATE_RUST_PARENT_PATHS_SHA256
        and trace["source_coverage"]["generated"]["inventory_sha256"]
        == V8_GENERATED_PATHS_SHA256,
        "V8 source parent path inventory diverge",
    )
    require(not trace["source_coverage"]["missing"], "V8 native source ausente")
    require(not trace["remaining_unknowns"], "V8 native UNKNOWN presente")
    require(
        trace["zlib"]["classification"] == "TARGET_NOT_APPLICABLE",
        "V8 zlib status diverge",
    )


def _evidence_role(path: str) -> str:
    name = PurePosixPath(path).name.upper()
    if "EXCEPTION" in name:
        return "EXCEPTION"
    if name.startswith("NOTICE"):
        return "NOTICE"
    if name.startswith("COPYRIGHT"):
        return "COPYRIGHT"
    if name.startswith("AUTHORS"):
        return "AUTHORS"
    return "LICENSE"


def _external_evidence_path(relative: Path) -> Path:
    root = os.environ.get("EDUDOWNLOADER_COMPLIANCE_INPUTS")
    if root and not relative.is_absolute():
        if ".." in relative.parts:
            raise SourceBundleError("Caminho de evidência fora do diretório de insumos")
        return Path(root).resolve(strict=True) / relative
    return relative


def _evidence_bytes(record: dict) -> bytes:
    if record.get("artifact") and record.get("member"):
        return archive_member_bytes(
            _external_evidence_path(Path(record["artifact"])), record["member"]
        )
    path = record["path"]
    if "::" in path:
        archive_path, member = path.split("::", 1)
        return archive_member_bytes(_external_evidence_path(Path(archive_path)), member)
    return _external_evidence_path(Path(path)).read_bytes()


def _validate_evidence_record(record: dict) -> None:
    data = _evidence_bytes(record)
    require(len(data) == record["size"], f"license evidence size diverge: {record}")
    require(
        sha256_bytes(data) == record["sha256"],
        f"license evidence hash diverge: {record}",
    )
    validate_source_member(record.get("member") or record["path"], data)


def _crate_evidence_records(
    summary: dict,
    records: list[dict],
    method: str,
    *,
    donor: str | None = None,
) -> list[dict]:
    prefix = f"{summary['name']}-{summary['version']}/"
    source_path = Path(summary["source_path"])
    if source_path.is_absolute():
        try:
            source_path = source_path.resolve().relative_to(PROJECT_ROOT)
        except ValueError as error:
            raise SourceBundleError(
                f"crate evidence fora do projeto: {summary['source_path']}"
            ) from error
    source_artifact = source_path.as_posix()
    result = []
    for record in records:
        evidence = {
            "artifact": source_artifact,
            "member": prefix + record["path"],
            "path": source_artifact + "::" + prefix + record["path"],
            "size": record["size"],
            "sha256": record["sha256"],
            "role": record.get("role", _evidence_role(record["path"])),
            "provenance_method": method,
        }
        if donor:
            evidence["donor_component"] = donor
        _validate_evidence_record(evidence)
        result.append(evidence)
    return sorted(result, key=lambda item: (item["role"], item["path"]))


def load_upstream_license_evidence() -> tuple[
    dict, dict[str, list[dict]], dict[str, dict]
]:
    require(LICENSE_EVIDENCE_INDEX.is_file(), "D11D license evidence index ausente")
    raw = LICENSE_EVIDENCE_INDEX.read_bytes()
    require(
        sha256_bytes(raw) == LICENSE_EVIDENCE_INDEX_SHA256,
        "D11D license evidence index hash diverge",
    )
    payload = json.loads(raw)
    require(raw == formatted(payload), "D11D license evidence index não canônico")
    require(
        payload.get("schema") == 2
        and payload.get("authority")
        == "OFFICIAL_UPSTREAM_IMMUTABLE_REVISION_OR_EXACT_RELEASE_TAG",
        "D11D license evidence index authority diverge",
    )
    by_component = defaultdict(list)
    seen = set()
    for item in payload["records"]:
        identity = (
            item["owner"].casefold(),
            item["repository"].casefold(),
            item["commit"],
            item["path"].casefold(),
        )
        require(identity not in seen, "D11D license evidence duplicada")
        seen.add(identity)
        local_path = (
            WORK_ROOT
            / "license-evidence/upstream/github"
            / item["owner"]
            / item["repository"]
            / item["commit"]
            / PurePosixPath(item["path"])
        )
        evidence = {
            "path": local_path.as_posix(),
            "size": item["size"],
            "sha256": item["sha256"],
            "role": _evidence_role(item["path"]),
            "provenance_method": item.get(
                "provenance_method", "GITHUB_RAW_EXACT_CRATE_VCS_COMMIT"
            ),
            "repository": f"{item['owner']}/{item['repository']}",
            "commit": item["commit"],
            "upstream_path": item["path"],
            "origin": item["url"],
        }
        if item.get("download_url"):
            evidence["download_url"] = item["download_url"]
        if item.get("git_blob"):
            evidence["git_blob"] = item["git_blob"]
        if item.get("exact_release_tag"):
            evidence["exact_release_tag"] = item["exact_release_tag"]
        _validate_evidence_record(evidence)
        for component in item["components"]:
            by_component[component].append(evidence)
    mapping_by_component = {}
    for mapping in payload["component_mappings"]:
        component = mapping["component"]
        require(
            component not in mapping_by_component,
            f"D11D component mapping duplicado: {component}",
        )
        require(
            mapping["resolution_status"] in {"TEXT_RESOLVED", "TEXT_PENDING"},
            f"D11D mapping status inválido: {component}",
        )
        require(
            mapping.get("resolution_phase") in {None, "D11D"},
            f"D11D mapping phase inválida: {component}",
        )
        require(
            mapping.get("notice_status")
            in {None, "NOTICE_NOT_REQUIRED_BY_UPSTREAM_STRUCTURE"},
            f"D11D mapping notice status inválido: {component}",
        )
        require(
            re.fullmatch(r"[0-9A-F]{64}", mapping["crate_checksum"]) is not None,
            f"D11D crate checksum inválido: {component}",
        )
        for key in ("package_manifest", "workspace_manifest"):
            record = mapping.get(key)
            if not record:
                continue
            local_path = (
                WORK_ROOT
                / "license-evidence/upstream/github"
                / record["owner"]
                / record["repository"]
                / record["commit"]
                / PurePosixPath(record["path"])
            )
            data = local_path.read_bytes()
            require(
                len(data) == record["size"]
                and sha256_bytes(data) == record["sha256"]
                and git_blob_sha(data) == record["git_blob"],
                f"D11D mapping evidence diverge: {component} {key}",
            )
            validate_source_member(local_path.as_posix(), data)
        if mapping["resolution_status"] == "TEXT_RESOLVED":
            require(
                mapping["root_license_paths"],
                f"D11D resolved mapping sem licença raiz: {component}",
            )
        else:
            require(
                mapping.get("pending_reason")
                and (
                    not mapping["root_license_paths"]
                    or mapping["component"] in {"zune-core@0.4.12", "zune-jpeg@0.4.13"}
                ),
                f"D11D pending mapping inconsistente: {component}",
            )
        mapping_by_component[component] = mapping
    require(
        len(mapping_by_component) == 44,
        "D11D 44-component mapping inventory diverge",
    )
    return (
        payload,
        {
            component: sorted(records, key=lambda item: (item["role"], item["path"]))
            for component, records in by_component.items()
        },
        mapping_by_component,
    )


def _complete_text_set(expression: str | None, records: list[dict]) -> bool:
    if not records:
        return False
    if not expression:
        return True
    text = b"\n".join(_evidence_bytes(record) for record in records).upper()
    expression_upper = expression.upper()
    if "MIT" in expression_upper and b"PERMISSION IS HEREBY GRANTED" not in text:
        return False
    if "APACHE" in expression_upper and b"APACHE LICENSE" not in text:
        return False
    if "BSD" in expression_upper and b"REDISTRIBUTION AND USE" not in text:
        return False
    if "ISC" in expression_upper and b"PERMISSION TO USE, COPY, MODIFY" not in text:
        return False
    if "LLVM-EXCEPTION" in expression_upper and b"LLVM EXCEPTION" not in text:
        return False
    if "ZLIB" in expression_upper:
        zlib_markers = (
            b"THIS SOFTWARE IS PROVIDED 'AS-IS'",
            b"ALTERED SOURCE VERSIONS MUST BE PLAINLY MARKED",
        )
        if not all(marker in text for marker in zlib_markers):
            return False
    if "MPL-2.0" in expression_upper and b"MOZILLA PUBLIC LICENSE" not in text:
        return False
    if "CC0-1.0" in expression_upper and b"CC0 1.0 UNIVERSAL" not in text:
        return False
    return True


def _pending_category(summary: dict) -> str:
    expression = summary["license_expression"] or ""
    if any(
        path["path"].upper().startswith("LICENCE") for path in summary["license_files"]
    ):
        return "OTHER"
    if summary["workspace_license_inherited"]:
        return "WORKSPACE_INHERITED"
    if any(marker in expression.upper() for marker in (" OR ", " AND ", "/")):
        return "MULTIPLE_LICENSE_EXPRESSION"
    if summary["repository"] and summary["vcs_commit"]:
        return "LICENSE_FILE_NOT_PACKAGED"
    if summary["repository"]:
        return "UPSTREAM_LICENSE_REFERENCE"
    return "LICENSE_METADATA_ONLY"


def _special_review_flags(expression: str | None) -> list[str]:
    expression_upper = (expression or "").upper()
    result = []
    for marker in (
        "MPL-2.0",
        "UNICODE",
        "LLVM-EXCEPTION",
        "BSD",
        "ISC",
        "ZLIB",
        "BZIP2",
        "CC0",
    ):
        if marker in expression_upper:
            result.append(marker)
    return result


def _native_notice_components(v8_native: dict, parents: dict) -> list[dict]:
    components = []
    for candidate in v8_native["candidates"]:
        if not candidate["material"] or candidate["path"] == "third_party/rust":
            continue
        license_files = []
        notice_files = []
        for raw in candidate["license_files"]:
            record = {
                **raw,
                "role": _evidence_role(raw["path"]),
                "provenance_method": "D11A_EXACT_GN_MATERIAL_LICENSE",
            }
            _validate_evidence_record(record)
            (
                notice_files
                if record["role"] in {"NOTICE", "COPYRIGHT", "AUTHORS"}
                else license_files
            ).append(record)
        components.append(
            {
                "component": "v8-native:" + candidate["path"],
                "version": candidate["revision"],
                "source": "D11A_EXACT_GN_TRACE",
                "checksum": V8_CRATE_SHA256,
                "materiality": "MATERIAL_NATIVE",
                "consumers": sorted(
                    {edge["from"] for edge in candidate["consumer_edges"]}
                ),
                "source_parent": candidate["source_coverage"],
                "license_expression": candidate["license_expression"],
                "license_expression_status": "RESOLVED_FROM_UPSTREAM",
                "license_files": license_files,
                "notice_files": notice_files,
                "license_text_status": "TEXT_RESOLVED",
                "notice_status": (
                    "NOTICE_RESOLVED"
                    if notice_files
                    else "NOTICE_NOT_TRACKED_IN_PRESERVED_EVIDENCE"
                ),
                "provenance_method": "D11A_EXACT_GN_MATERIAL_LICENSE",
                "review_flags": _special_review_flags(candidate["license_expression"]),
                "review_status": "P3_REVIEW_REQUIRED",
            }
        )

    rust_candidate = next(
        item for item in v8_native["candidates"] if item["path"] == "third_party/rust"
    )
    for crate in rust_candidate["license_components"]:
        license_files = []
        notice_files = []
        for raw in crate["license_files"]:
            record = {
                **raw,
                "role": _evidence_role(raw["path"]),
                "provenance_method": "D11A_V8_RUST_EXACT_PARENT",
            }
            _validate_evidence_record(record)
            (
                notice_files
                if record["role"] in {"NOTICE", "COPYRIGHT", "AUTHORS"}
                else license_files
            ).append(record)
        components.append(
            {
                "component": "v8-rust:" + crate["name"],
                "version": crate["version"],
                "source": "chromium/src/third_party/rust@" + V8_RUST_COMMIT,
                "checksum": V8_RUST_ARCHIVE_SHA256,
                "materiality": "MATERIAL_NATIVE",
                "consumers": ["v8-native:third_party/rust"],
                "source_parent": "CHROMIUM_RUST_EXACT_PARENT",
                "license_expression": crate["license_expression"],
                "license_expression_status": "RESOLVED_FROM_UPSTREAM",
                "license_files": license_files,
                "notice_files": notice_files,
                "license_text_status": "TEXT_RESOLVED",
                "notice_status": (
                    "NOTICE_RESOLVED"
                    if notice_files
                    else "NOTICE_NOT_TRACKED_IN_PRESERVED_EVIDENCE"
                ),
                "provenance_method": "D11A_V8_RUST_EXACT_PARENT",
                "review_flags": _special_review_flags(crate["license_expression"]),
                "review_status": "P3_REVIEW_REQUIRED",
            }
        )

    for item in v8_native["other_material_v8_third_party"]:
        license_files = []
        notice_files = []
        for raw in item["license_files"]:
            record = {
                **raw,
                "role": _evidence_role(raw["path"]),
                "provenance_method": "D11A_V8_OTHER_THIRD_PARTY",
            }
            _validate_evidence_record(record)
            (
                notice_files
                if record["role"] in {"NOTICE", "COPYRIGHT", "AUTHORS"}
                else license_files
            ).append(record)
        components.append(
            {
                "component": "v8-native:" + item["component"],
                "version": V8_COMMIT,
                "source": "denoland/v8@" + V8_COMMIT,
                "checksum": V8_ARCHIVE_SHA256,
                "materiality": "MATERIAL_NATIVE",
                "consumers": ["v8-native"],
                "source_parent": item["source_coverage"],
                "license_expression": item["license_expression"],
                "license_expression_status": "RESOLVED_FROM_UPSTREAM",
                "license_files": license_files,
                "notice_files": notice_files,
                "license_text_status": "TEXT_RESOLVED",
                "notice_status": (
                    "NOTICE_RESOLVED"
                    if notice_files
                    else "NOTICE_NOT_TRACKED_IN_PRESERVED_EVIDENCE"
                ),
                "provenance_method": "D11A_V8_OTHER_THIRD_PARTY",
                "review_flags": _special_review_flags(item["license_expression"]),
                "review_status": "P3_REVIEW_REQUIRED",
            }
        )

    rust_license_files = []
    rust_notice_files = []
    for raw in parents["rust"]["license_evidence"]:
        record = {
            **raw,
            "role": _evidence_role(raw["path"]),
            "provenance_method": "RUST_1_95_EXACT_SOURCE_PARENT",
        }
        _validate_evidence_record(record)
        (
            rust_notice_files
            if record["role"] in {"NOTICE", "COPYRIGHT", "AUTHORS"}
            else rust_license_files
        ).append(record)
    components.append(
        {
            "component": "rust-std",
            "version": parents["rust"]["version"],
            "source": "rust-lang/rust@" + parents["rust"]["commit"],
            "checksum": parents["rust"]["archive_sha256"],
            "materiality": "MATERIAL_RUNTIME_PARENT",
            "consumers": ["deno.exe"],
            "source_parent": "RUST_1_95_SOURCE_PARENT",
            "license_expression": "MIT OR Apache-2.0",
            "license_expression_status": "RESOLVED_FROM_UPSTREAM",
            "license_files": rust_license_files,
            "notice_files": rust_notice_files,
            "license_text_status": "TEXT_RESOLVED",
            "notice_status": "NOTICE_RESOLVED",
            "provenance_method": "RUST_1_95_EXACT_SOURCE_PARENT",
            "review_flags": [],
            "review_status": "P3_REVIEW_REQUIRED",
        }
    )
    return components


def render_notice_text(notice: dict) -> bytes:
    lines = [
        "EDUDOWNLOADER-GENERATED DENO THIRD-PARTY NOTICE INVENTORY",
        "Deno 2.9.5 official Windows x86_64 release",
        "NOT AN OFFICIAL DENO NOTICE. NOT LEGAL APPROVAL.",
        "TEXT RENDERING: LF; trailing horizontal whitespace removed; hashes identify original evidence bytes.",
        f"STATUS: {notice['status']}",
        "",
        "COMPONENT MAPPING",
        "=================",
    ]
    texts = defaultdict(lambda: {"components": set(), "records": [], "data": b""})
    for component in notice["components"]:
        identity = f"{component['component']}@{component['version']}"
        lines.extend(
            [
                "",
                identity,
                f"  materiality: {component['materiality']}",
                f"  expression: {component['license_expression'] or '[license-file]'}",
                f"  expression_status: {component['license_expression_status']}",
                f"  text_status: {component['license_text_status']}",
                f"  notice_status: {component['notice_status']}",
                f"  source_parent: {component['source_parent']}",
            ]
        )
        if component.get("pending_reason"):
            lines.append(f"  pending_reason: {component['pending_reason']}")
        if component.get("d11h_license_policy"):
            policy = component["d11h_license_policy"]
            lines.extend(
                [
                    f"  upstream_license_text: {policy['upstream_license_text']}",
                    f"  canonical_reference_text: {policy['canonical_reference_text']}",
                    "  canonical_reference_set: "
                    + ", ".join(policy["canonical_reference_set"]),
                    f"  attribution_metadata: {policy['attribution_metadata']}",
                    f"  legal_review: {policy['legal_review']}",
                ]
            )
        if component.get("upstream_mapping"):
            mapping = component["upstream_mapping"]
            lines.extend(
                [
                    f"  mapping_relation: {mapping['relation']}",
                    f"  mapping_resolution_phase: {mapping.get('resolution_phase') or '[prior phase]'}",
                    f"  mapping_notice_status: {mapping.get('notice_status') or '[not evaluated]'}",
                    f"  mapping_repository: {mapping['repository'] or '[not declared]'}",
                    f"  mapping_crate_vcs_commit: {mapping['crate_vcs_commit'] or '[not declared]'}",
                    f"  mapping_evidence_commit: {mapping['evidence_commit'] or '[not available]'}",
                    f"  mapping_exact_release_tag: {mapping['exact_release_tag'] or '[not available]'}",
                    f"  mapping_workspace_path: {mapping['workspace_path'] or '[repository root]'}",
                ]
            )
        for record in component["license_files"] + component["notice_files"]:
            texts[record["sha256"]]["components"].add(identity)
            texts[record["sha256"]]["records"].append(record["path"])
            if not texts[record["sha256"]]["data"]:
                texts[record["sha256"]]["data"] = _evidence_bytes(record)
            lines.append(
                f"  {record['role'].lower()}: sha256={record['sha256']} path={record['path']}"
            )
    lines.extend(
        ["", "", "DEDUPLICATED AUTHORITATIVE TEXTS", "================================"]
    )
    for digest in sorted(texts):
        item = texts[digest]
        rendered_text = "\n".join(
            line.rstrip(" \t")
            for line in item["data"].decode("utf-8", errors="replace").splitlines()
        )
        lines.extend(
            [
                "",
                f"SHA-256: {digest}",
                "Components: " + ", ".join(sorted(item["components"])),
                "Evidence: " + " | ".join(sorted(set(item["records"]))),
                "--- BEGIN AUTHORITATIVE TEXT ---",
                rendered_text,
                "--- END AUTHORITATIVE TEXT ---",
            ]
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_notice_inventory(
    resolution: dict, inspection: dict, v8_native: dict, parents: dict
) -> dict:
    spdx_references = load_spdx_reference_manifest()
    summaries = {
        (item["name"], item["version"]): item for item in inspection["packages"]
    }
    consumers = defaultdict(set)
    for edge in resolution["edges"]:
        if edge["parent_context"] == edge["child_context"] == "normal":
            consumers[edge["child"]].add(edge["parent"])
    legacy_pending = {
        (item["name"], item["version"])
        for item in inspection["packages"]
        if not [
            record
            for record in item["license_files"] + item["notice_files"]
            if not record["path"].upper().startswith("LICENCE")
        ]
    }
    require(len(legacy_pending) == 88, "D11B initial pending baseline diverge")
    (
        upstream_index,
        upstream_by_component,
        upstream_mapping_by_component,
    ) = load_upstream_license_evidence()
    exact_commit_donors = defaultdict(list)
    for summary in inspection["packages"]:
        if summary["vcs_commit"] and summary["license_files"]:
            exact_commit_donors[summary["vcs_commit"]].append(summary)
    components = []
    for package in resolution["packages"]:
        if package["classification"] not in {"MATERIAL_RUNTIME", "MATERIAL_CODEGEN"}:
            continue
        if package["source"] == "workspace":
            license_expression = "MIT"
            license_files = [
                {
                    "path": (WORK_ROOT / "work/deno/deno-2.9.5/LICENSE.md").as_posix(),
                    "size": (WORK_ROOT / "work/deno/deno-2.9.5/LICENSE.md")
                    .stat()
                    .st_size,
                    "sha256": DENO_LICENSE_SHA256,
                    "role": "LICENSE",
                    "provenance_method": "COVERED_BY_DENO_PARENT",
                }
            ]
            notice_files = []
            source_parent = "DENO_SOURCE_PARENT"
            expression_status = "RESOLVED_FROM_DENO_PARENT"
            text_status = "TEXT_RESOLVED"
            provenance_method = "COVERED_BY_DENO_PARENT"
            pending_category = None
            attempted_authorities = []
        else:
            summary = summaries[(package["name"], package["version"])]
            license_expression = summary["license_expression"]
            identity = f"{package['name']}@{package['version']}"
            upstream_mapping = upstream_mapping_by_component.get(identity)
            license_files = _crate_evidence_records(
                summary, summary["license_files"], "EXACT_CRATE"
            )
            notice_files = _crate_evidence_records(
                summary, summary["notice_files"], "EXACT_CRATE"
            )
            source_parent = (
                "RUSTY_V8_AND_V8_SOURCE_PARENTS"
                if package["name"] == "v8"
                else "CANONICAL_CRATE"
            )
            expression_status = (
                "RESOLVED_FROM_CARGO_METADATA"
                if license_expression
                else "RESOLVED_FROM_LICENSE_FILE"
                if summary["license_file_declared"] and license_files
                else "PENDING"
            )
            initial_pending = (package["name"], package["version"]) in legacy_pending
            pending_category = _pending_category(summary) if initial_pending else None
            attempted_authorities = (
                [
                    {
                        "authority": "EXACT_CRATE_CONTENTS",
                        "result": "LICENSE_TEXT_ABSENT_UNDER_LEGACY_SCANNER",
                    }
                ]
                if initial_pending
                else []
            )
            provenance_method = "EXACT_CRATE"
            if initial_pending and not _complete_text_set(
                license_expression, license_files
            ):
                donors = [
                    donor
                    for donor in exact_commit_donors.get(summary["vcs_commit"], [])
                    if donor["name"] != summary["name"]
                    and donor["license_expression"] == license_expression
                ]
                for donor in sorted(
                    donors, key=lambda item: (item["name"], item["version"])
                ):
                    candidate = _crate_evidence_records(
                        donor,
                        donor["license_files"],
                        "EXACT_SIBLING_CRATE_SAME_VCS_COMMIT",
                        donor=f"{donor['name']}@{donor['version']}",
                    )
                    if _complete_text_set(license_expression, candidate):
                        license_files = candidate
                        provenance_method = "EXACT_SIBLING_CRATE_SAME_VCS_COMMIT"
                        attempted_authorities.append(
                            {
                                "authority": "EXACT_SIBLING_CRATE_SAME_VCS_COMMIT",
                                "component": f"{donor['name']}@{donor['version']}",
                                "commit": summary["vcs_commit"],
                                "result": "TEXT_RESOLVED",
                            }
                        )
                        break
            if initial_pending and not _complete_text_set(
                license_expression, license_files
            ):
                candidate = upstream_by_component.get(identity, [])
                if candidate:
                    candidate_method = (
                        upstream_mapping["relation"]
                        if upstream_mapping
                        else "UPSTREAM_EXACT_VCS_COMMIT"
                    )
                    attempted_authorities.append(
                        {
                            "authority": candidate_method,
                            "commit": summary["vcs_commit"],
                            "evidence_commit": (
                                upstream_mapping["evidence_commit"]
                                if upstream_mapping
                                else summary["vcs_commit"]
                            ),
                            "exact_release_tag": (
                                upstream_mapping["exact_release_tag"]
                                if upstream_mapping
                                else None
                            ),
                            "repository": summary["repository"] or summary["homepage"],
                            "result": (
                                "TEXT_RESOLVED"
                                if _complete_text_set(license_expression, candidate)
                                else "TEXT_SET_INCOMPLETE_FOR_DECLARED_EXPRESSION"
                            ),
                        }
                    )
                    license_files = candidate
                    provenance_method = candidate_method
            if initial_pending:
                text_status = (
                    "TEXT_RESOLVED"
                    if _complete_text_set(license_expression, license_files)
                    else "TEXT_PENDING"
                )
            else:
                text_status = (
                    "TEXT_RESOLVED"
                    if license_files
                    or _complete_text_set(license_expression, notice_files)
                    else "TEXT_PENDING"
                )
            if initial_pending and text_status == "TEXT_PENDING":
                if upstream_mapping:
                    attempted_authorities.append(
                        {
                            "authority": upstream_mapping["relation"],
                            "commit": upstream_mapping["evidence_commit"],
                            "exact_release_tag": upstream_mapping["exact_release_tag"],
                            "repository": upstream_mapping["repository"],
                            "result": upstream_mapping["pending_reason"],
                        }
                    )
                attempted_authorities.append(
                    {
                        "authority": "UPSTREAM_EXACT_VERSION_OR_COMMIT",
                        "repository": summary["repository"] or summary["homepage"],
                        "commit": summary["vcs_commit"],
                        "result": "NO_COMPLETE_AUTHORITATIVE_TEXT_SET_PRESERVED",
                    }
                )
        if upstream_mapping and upstream_mapping.get("notice_status"):
            notice_status = upstream_mapping["notice_status"]
        else:
            notice_status = (
                "NOTICE_RESOLVED"
                if notice_files
                else "NOTICE_IDENTITY_PENDING"
                if text_status == "TEXT_PENDING"
                else "NOTICE_NOT_TRACKED_IN_PRESERVED_EVIDENCE"
            )
        pending_reason = None
        if text_status == "TEXT_PENDING":
            pending_reason = (
                "AUTHORITATIVE_UPSTREAM_LICENSE_TEXT_SET_INCOMPLETE; "
                "SPDX canonical reference is complementary and requires P3 review"
            )
        component_record = {
            "component": package["name"],
            "version": package["version"],
            "source": package["source"],
            "checksum": package.get("checksum"),
            "materiality": package["classification"],
            "license_expression": license_expression,
            "license_expression_status": expression_status,
            "license_files": license_files,
            "notice_files": notice_files,
            "source_parent": source_parent,
            "consumers": sorted(consumers.get(package["id"], {"deno.exe"})),
            "license_text_status": text_status,
            "notice_status": notice_status,
            "provenance_method": provenance_method,
            "initial_d11b_text_pending": (
                (package["name"], package["version"]) in legacy_pending
                if package["source"] != "workspace"
                else False
            ),
            "pending_category": pending_category,
            "pending_reason": pending_reason,
            "attempted_authorities": attempted_authorities,
            "upstream_mapping": (
                upstream_mapping if package["source"] != "workspace" else None
            ),
            "review_flags": _special_review_flags(license_expression),
            "review_status": "P3_REVIEW_REQUIRED",
        }
        policy = d11h_component_policy(
            package["name"], package["version"], license_expression or ""
        )
        if policy is not None:
            component_record["d11h_license_policy"] = policy
        components.append(component_record)
    components.extend(_native_notice_components(v8_native, parents))
    components.sort(
        key=lambda item: (
            item["component"].casefold(),
            item["version"],
            item["source"],
        )
    )
    missing_text = [
        f"{item['component']}@{item['version']}"
        for item in components
        if item["license_text_status"] == "TEXT_PENDING"
    ]
    missing_expression = [
        f"{item['component']}@{item['version']}"
        for item in components
        if item["license_expression_status"] == "PENDING"
    ]
    notice_pending = [
        f"{item['component']}@{item['version']}"
        for item in components
        if item["notice_status"] == "NOTICE_IDENTITY_PENDING"
    ]
    result = {
        "schema": 2,
        "title": "EduDownloader generated third-party inventory for Deno 2.9.5 official Windows x86_64 release",
        "authority": "PROJECT_GENERATED_FROM_EXACT_MATERIAL_CLOSURE_NOT_UPSTREAM_DENO_NOTICE",
        "target": TARGET,
        "counts": {
            "components": len(components),
            "cargo_components": sum(
                item["materiality"] in {"MATERIAL_RUNTIME", "MATERIAL_CODEGEN"}
                for item in components
            ),
            "native_components": sum(
                item["materiality"] in {"MATERIAL_NATIVE", "MATERIAL_RUNTIME_PARENT"}
                for item in components
            ),
            "runtime": sum(
                item["materiality"] == "MATERIAL_RUNTIME" for item in components
            ),
            "codegen": sum(
                item["materiality"] == "MATERIAL_CODEGEN" for item in components
            ),
            "license_expression_resolved": sum(
                item["license_expression_status"] != "PENDING" for item in components
            ),
            "license_expression_pending": len(missing_expression),
            "license_text_resolved": sum(
                item["license_text_status"] == "TEXT_RESOLVED" for item in components
            ),
            "license_text_pending": len(missing_text),
            "notice_resolved": sum(
                item["notice_status"] == "NOTICE_RESOLVED" for item in components
            ),
            "notice_not_required": sum(
                item["notice_status"] == "NOTICE_NOT_REQUIRED_BY_UPSTREAM_STRUCTURE"
                for item in components
            ),
            "notice_pending": len(notice_pending),
            "special_review": sum(bool(item["review_flags"]) for item in components),
            "unknown": 0,
            "d11b_initial_text_pending": len(legacy_pending),
            "d11b_text_resolved": len(legacy_pending) - len(missing_text),
            "d11c_initial_text_pending": len(upstream_mapping_by_component),
            "d11c_text_resolved": sum(
                item["resolution_status"] == "TEXT_RESOLVED"
                and item.get("resolution_phase") != "D11D"
                for item in upstream_mapping_by_component.values()
            ),
            "d11d_initial_text_pending": 16,
            "d11d_text_resolved": sum(
                item["resolution_status"] == "TEXT_RESOLVED"
                and item.get("resolution_phase") == "D11D"
                for item in upstream_mapping_by_component.values()
            ),
            "d11h_canonical_reference_available": sum(
                "d11h_license_policy" in item for item in components
            ),
            "d11h_canonical_reference_missing": 0,
            "d11h_category_c": sum(
                item.get("d11h_license_policy", {}).get("d11f_category") == "C"
                for item in components
            ),
            "d11h_category_d": sum(
                item.get("d11h_license_policy", {}).get("d11f_category") == "D"
                for item in components
            ),
            "d11h_upstream_license_text_absent": sum(
                item.get("d11h_license_policy", {}).get("upstream_license_text")
                == "ABSENT"
                for item in components
            ),
            "d11h_upstream_license_text_partial": sum(
                item.get("d11h_license_policy", {}).get("upstream_license_text")
                == "PARTIAL"
                for item in components
            ),
        },
        "missing_license_text": missing_text,
        "missing_license_expression": missing_expression,
        "missing_notice_identity": notice_pending,
        "license_evidence_index": {
            "path": LICENSE_EVIDENCE_INDEX.as_posix(),
            "sha256": LICENSE_EVIDENCE_INDEX_SHA256,
            "records": len(upstream_index["records"]),
            "mappings": len(upstream_index["component_mappings"]),
            "authority": upstream_index["authority"],
        },
        "spdx_canonical_reference_policy": {
            "classification": spdx_references["classification"],
            "manifest_path": SPDX_REFERENCE_MANIFEST.as_posix(),
            "manifest_sha256": SPDX_REFERENCE_MANIFEST_SHA256,
            "policy": spdx_references["policy"],
            "reference_count": len(spdx_references["references"]),
            "snapshot_commit": spdx_references["snapshot"]["commit"],
            "snapshot_tag": spdx_references["snapshot"]["tag"],
            "snapshot_version": spdx_references["snapshot"]["version"],
        },
        "compliance_layers": {
            "canonical_reference_coverage": "COMPLETE_FOR_D11H_SCOPE",
            "legal_review": "P3_REQUIRED",
            "license_identity": "RESOLVED",
            "notice_delivery": "PENDING_FIX",
            "notice_identity": "RESOLVED",
            "source_correspondence": "TECHNICALLY_COMPLETE",
            "upstream_license_text": "13_ABSENT_2_PARTIAL_REMAINDER_PRESENT",
        },
        "status": "PARTIAL_GENERATED_INVENTORY",
        "components": components,
    }
    notice_text = render_notice_text(result)
    result["generated_notice"] = {
        "path": DEFAULT_NOTICE_TEXT.as_posix(),
        "size": len(notice_text),
        "sha256": sha256_bytes(notice_text),
        "classification": "PARTIAL_FUTURE_CANDIDATE_INPUT_NOT_DELIVERED",
    }
    return result


def generate_manifests() -> tuple[dict, dict]:
    resolution = json.loads(FINAL_RESOLUTION_PATH.read_text(encoding="utf-8"))
    inspection = json.loads(CRATE_INSPECTION_PATH.read_text(encoding="utf-8"))
    parents = json.loads(PARENT_INSPECTION_PATH.read_text(encoding="utf-8"))
    acquisitions = json.loads(ACQUISITION_PATH.read_text(encoding="utf-8"))
    v8_native = build_v8_native_closure(parents)
    candidate = json.loads(
        Path("docs/compliance/build/FROZEN_CANDIDATE_COMPOSITION.json").read_text(
            encoding="utf-8"
        )
    )
    notice = build_notice_inventory(resolution, inspection, v8_native, parents)
    deno_binary = next(
        item
        for item in candidate["external_binaries"]
        if item["filename"] == "deno.exe"
    )
    crate_records = []
    for item in inspection["packages"]:
        crate_records.append(
            {
                key: value
                for key, value in item.items()
                if key not in {"source_path", "copyright_evidence"}
            }
        )
    source_inputs = [
        relative_artifact(path)
        for path in sorted(INPUT_ROOT.iterdir())
        if path.is_file()
    ]
    manifest = {
        "schema": 2,
        "scope": "DENO_2_9_5_OFFICIAL_WINDOWS_X86_64_FROZEN_RUNTIME",
        "status": {
            "open_source_correspondence": "TECHNICALLY_COMPLETE",
            "source_correspondence": "TECHNICALLY_COMPLETE",
            "license_identity": "RESOLVED",
            "upstream_license_text": "PARTIAL",
            "canonical_reference_coverage": "COMPLETE_FOR_D11H_SCOPE",
            "cargo_closure": "RESOLVED",
            "rust_std_source": "RESOLVED",
            "rusty_v8_source": "RESOLVED_BY_CRATE_AND_OFFICIAL_METADATA",
            "v8_source": "RESOLVED",
            "v8_native_closure": "RESOLVED",
            "notice_inventory": "PARTIAL_GENERATED_INVENTORY",
            "notice_identity": "RESOLVED",
            "notice_delivery": "PENDING_FIX",
            "staging": "NOT_CREATED_PARTIAL",
            "bundle": "NOT_CREATED_PARTIAL",
            "legal_review": "P3_REQUIRED",
            "microsoft": "P3_PENDING_REVIEW",
            "build_reproducibility": "P2_SEPARATE_PENDING",
        },
        "counts": {
            **resolution["counts"],
            "source_pending": 0,
            "source_blocked": 0,
            "open_source_unknown": 0,
            "license_text_pending": notice["counts"]["license_text_pending"],
            "license_expression_pending": notice["counts"][
                "license_expression_pending"
            ],
            "notice_identity_pending": notice["counts"]["notice_pending"],
            "license_identity_resolved": notice["counts"]["components"],
            "upstream_license_text_present": notice["counts"]["license_text_resolved"],
            "upstream_license_text_absent": notice["counts"][
                "d11h_upstream_license_text_absent"
            ],
            "upstream_license_text_partial": notice["counts"][
                "d11h_upstream_license_text_partial"
            ],
            "canonical_reference_available": notice["counts"][
                "d11h_canonical_reference_available"
            ],
            "canonical_reference_missing": notice["counts"][
                "d11h_canonical_reference_missing"
            ],
            "crate_acquisitions": len(acquisitions["acquired"]),
            "crate_reuses": len(acquisitions["reused"]),
            "v8_native_candidates_traced": len(v8_native["candidates"]),
        },
        "candidate": {
            "classification": candidate["candidate_classification"],
            "source_commit": candidate["build_provenance"]["source_commit"],
            "file_count": candidate["pristine_inventory"]["file_count"],
            "total_size": candidate["pristine_inventory"]["total_size_bytes"],
            "inventory_sha256": candidate["pristine_inventory"]["inventory_sha256"],
            "deno_binary": deno_binary,
            "application": candidate["application"],
            "gates": candidate["gates"],
            "modified": False,
        },
        "release_build": {
            "workspace_resolver": "2",
            "target": TARGET,
            "profile": "release",
            "packages": ["deno", "denort", "test_server"],
            "bins": ["deno", "denort", "test_server"],
            "explicit_features": ["deno/panic-trace"],
            "default_features": True,
            "environment": {"DENO_SNAPSHOT_MINIFY_SOURCES": "1"},
            "workflow_path": ".github/workflows/ci.generated.yml",
            "workflow_lines": "2884-2897",
        },
        "parents": parents,
        "source_inputs": source_inputs,
        "metadata_evidence": _metadata_inventory(),
        "registry_index_evidence": _index_inventory(),
        "cargo_resolution": resolution,
        "material_crates": crate_records,
        "v8_native_closure": v8_native,
        "license_evidence": notice["license_evidence_index"],
        "spdx_canonical_references": notice["spdx_canonical_reference_policy"],
        "generated_notice": notice["generated_notice"],
        "special_components": {
            "aws_lc": "COVERED_BY_AWS_LC_SYS_CRATE_PARENT",
            "ring": "MATERIAL_AND_COVERED_BY_CRATE_PARENT",
            "sqlite": "BUNDLED_SOURCE_COVERED_BY_LIBSQLITE3_SYS_CRATE_PARENT",
            "typescript_6_0_3": "COVERED_BY_DENO_PARENT_CLI_TSC_00_TYPESCRIPT_JS",
            "js_snapshots": "GENERATED_WITH_DENO_PARENT_AND_RESOLVED_CARGO_INPUTS",
            "prebuilt_rusty_v8": {
                "role": "BUILD_PROVENANCE_BINARY_NOT_CORRESPONDING_SOURCE",
                "filename": "rusty_v8_simdutf_release_x86_64-pc-windows-msvc.lib.gz",
                "size": 39_225_458,
                "sha256": "F231F82CBACB9AEFE6D9AF57E6DF2E8959A40E001F79306485133E3C075B98F0",
                "acquired": False,
            },
        },
        "minimum_source_parent_model": {
            "root_parents": [
                "Deno source",
                "Rust 1.95 rust-src",
                "rusty_v8 v8 crate",
                "denoland/v8 source",
                "chromium/src/third_party/rust source",
            ],
            "crate_parents": len(material_registry(resolution)),
            "reused_parents": len(acquisitions["reused"]),
            "v8_native_parents": {
                "covered_declared_paths_by_rusty_v8_parent": 4456,
                "covered_declared_paths_by_separate_v8_rust_parent": 793,
                "generated_paths_from_covered_source": 1327,
                "full_v8_revision_parent": V8_COMMIT,
                "separate_parents": ["chromium/src/third_party/rust"],
                "status": "RESOLVED",
            },
            "rust_std_parents": ["rust-src 1.95.0"],
        },
        "separate_boundaries": {
            "p2": [
                "Rust/Cargo binaries",
                "GN",
                "Ninja",
                "Clang",
                "MSVC",
                "Windows SDK",
                "prebuilt rusty_v8",
                "release workflow exact environment",
            ],
            "p3": ["Microsoft static CRT object composition", "legal review"],
            "other_blocks": "FFmpeg/BtbN A; yt-dlp A; CPython/Tcl-Tk A; PyInstaller/hooks A; cffi/cryptography A; Wheel Integrity A; Pillow/PDFium RESOLVED; CustomTkinter PARTIAL; Gyan active; BtbN CANDIDATE_NOT_PROMOTED",
        },
    }
    validate_manifest_structure(manifest, notice)
    return manifest, notice


def validate_manifest_structure(manifest: dict, notice: dict) -> None:
    spdx_references = load_spdx_reference_manifest()
    require(manifest["schema"] == 2, "manifest schema diverge")
    require(
        manifest["scope"] == "DENO_2_9_5_OFFICIAL_WINDOWS_X86_64_FROZEN_RUNTIME",
        "manifest scope diverge",
    )
    require(
        manifest["status"]["open_source_correspondence"]
        == manifest["status"]["source_correspondence"]
        == "TECHNICALLY_COMPLETE",
        "source correspondence status diverge",
    )
    require(
        manifest["status"]["license_identity"] == "RESOLVED"
        and manifest["status"]["upstream_license_text"] == "PARTIAL"
        and manifest["status"]["canonical_reference_coverage"]
        == "COMPLETE_FOR_D11H_SCOPE"
        and manifest["status"]["notice_identity"] == "RESOLVED"
        and manifest["status"]["notice_delivery"] == "PENDING_FIX"
        and manifest["status"]["legal_review"] == "P3_REQUIRED",
        "D11H compliance layer status diverge",
    )
    require(
        manifest["status"]["v8_native_closure"] == "RESOLVED",
        "V8 closure status diverge",
    )
    require(
        manifest["status"]["bundle"] == "NOT_CREATED_PARTIAL", "bundle status diverge"
    )
    counts = manifest["counts"]
    expected = {
        "lock_packages": 1133,
        "workspace": 82,
        "registry": 1051,
        "material": 869,
        "material_runtime": 765,
        "material_codegen": 104,
        "build_only": 29,
        "dev_only": 17,
        "target_not_applicable": 68,
        "optional_disabled": 12,
        "unreachable": 138,
        "unknown": 0,
        "source_pending": 0,
        "source_blocked": 0,
        "open_source_unknown": 0,
        "crate_acquisitions": 791,
        "crate_reuses": 19,
        "license_text_pending": 15,
        "license_expression_pending": 0,
        "notice_identity_pending": 0,
        "license_identity_resolved": 931,
        "upstream_license_text_present": 916,
        "upstream_license_text_absent": 13,
        "upstream_license_text_partial": 2,
        "canonical_reference_available": 15,
        "canonical_reference_missing": 0,
        "v8_native_candidates_traced": 14,
    }
    for key, value in expected.items():
        require(counts.get(key) == value, f"manifest count diverge: {key}")
    packages = manifest["cargo_resolution"]["packages"]
    require(
        len(packages) == 1133 and len({item["id"] for item in packages}) == 1133,
        "Cargo package inventory diverge",
    )
    classifications = defaultdict(int)
    for package in packages:
        classifications[package["classification"]] += 1
    require(
        classifications["MATERIAL_RUNTIME"] == 765, "runtime classification diverge"
    )
    require(
        classifications["MATERIAL_CODEGEN"] == 104, "codegen classification diverge"
    )
    require(len(manifest["material_crates"]) == 810, "material crate inventory diverge")
    require(
        manifest["minimum_source_parent_model"]["crate_parents"] == 810,
        "crate parent count diverge",
    )
    require(
        manifest["minimum_source_parent_model"]["root_parents"]
        == [
            "Deno source",
            "Rust 1.95 rust-src",
            "rusty_v8 v8 crate",
            "denoland/v8 source",
            "chromium/src/third_party/rust source",
        ],
        "root source parent inventory diverge",
    )
    require(
        manifest["minimum_source_parent_model"]["v8_native_parents"]
        == {
            "covered_declared_paths_by_rusty_v8_parent": 4456,
            "covered_declared_paths_by_separate_v8_rust_parent": 793,
            "generated_paths_from_covered_source": 1327,
            "full_v8_revision_parent": V8_COMMIT,
            "separate_parents": ["chromium/src/third_party/rust"],
            "status": "RESOLVED",
        },
        "V8 native source parent model diverge",
    )
    require(not manifest["candidate"]["modified"], "candidate modification prohibited")
    require(
        manifest["candidate"]["deno_binary"]["sha256"]
        == "98F8C2A2D470E4CCB04C935C86FF8050817D877762AEC5EAEEB9E409CCB3B9FD",
        "Deno binary authority diverge",
    )
    require(
        manifest["candidate"]["application"]["app_version"] == "0.9.5",
        "APP_VERSION diverge",
    )
    require(
        manifest["candidate"]["application"]["product_edition"] == "community",
        "ProductEdition diverge",
    )
    require(
        not manifest["candidate"]["application"][
            "activation_required_for_current_edition"
        ],
        "Community activation gate diverge",
    )
    require(
        not manifest["candidate"]["gates"]["production_ready"], "production gate opened"
    )
    require(
        not manifest["candidate"]["gates"]["public_release_allowed"],
        "release gate opened",
    )
    require(
        not manifest["candidate"]["gates"]["operational_private_key_configured"],
        "private key configured",
    )
    require(
        manifest["candidate"]["file_count"] == 1068
        and manifest["candidate"]["total_size"] == 382_736_507
        and manifest["candidate"]["inventory_sha256"]
        == "26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857",
        "frozen candidate baseline diverge",
    )
    require(
        manifest["parents"]["v8_rust"]["commit"] == V8_RUST_COMMIT
        and manifest["parents"]["v8_rust"]["tree"] == V8_RUST_TREE
        and manifest["parents"]["v8_rust"]["archive_sha256"] == V8_RUST_ARCHIVE_SHA256,
        "V8 Rust parent diverge",
    )
    validate_v8_native_closure(manifest["v8_native_closure"])
    require(
        notice["authority"]
        == "PROJECT_GENERATED_FROM_EXACT_MATERIAL_CLOSURE_NOT_UPSTREAM_DENO_NOTICE",
        "notice authority diverge",
    )
    require(notice["schema"] == 2, "notice schema diverge")
    require(
        notice.get("spdx_canonical_reference_policy")
        == {
            "classification": "SPDX_CANONICAL_REFERENCE_TEXT",
            "manifest_path": SPDX_REFERENCE_MANIFEST.as_posix(),
            "manifest_sha256": SPDX_REFERENCE_MANIFEST_SHA256,
            "policy": "ADOPT_CANONICAL_REFERENCE_POLICY_FOR_P3_REVIEW",
            "reference_count": 4,
            "snapshot_commit": SPDX_SNAPSHOT_COMMIT,
            "snapshot_tag": SPDX_SNAPSHOT_TAG,
            "snapshot_version": SPDX_SNAPSHOT_VERSION,
        }
        == manifest.get("spdx_canonical_references"),
        "D11H SPDX reference policy identity diverge",
    )
    require(
        notice.get("compliance_layers")
        == {
            "canonical_reference_coverage": "COMPLETE_FOR_D11H_SCOPE",
            "legal_review": "P3_REQUIRED",
            "license_identity": "RESOLVED",
            "notice_delivery": "PENDING_FIX",
            "notice_identity": "RESOLVED",
            "source_correspondence": "TECHNICALLY_COMPLETE",
            "upstream_license_text": "13_ABSENT_2_PARTIAL_REMAINDER_PRESENT",
        },
        "D11H compliance layer model diverge",
    )
    available_spdx_ids = {item["identifier"] for item in spdx_references["references"]}
    require(notice["counts"]["components"] == 931, "notice component count diverge")
    require(notice["counts"]["cargo_components"] == 869, "Cargo notice count diverge")
    require(notice["counts"]["native_components"] == 62, "native notice count diverge")
    require(
        notice["counts"]["d11b_initial_text_pending"] == 88
        and notice["counts"]["d11b_text_resolved"] == 73,
        "D11B 88-item reconciliation diverge",
    )
    require(
        notice["counts"]["d11c_initial_text_pending"] == 44
        and notice["counts"]["d11c_text_resolved"] == 28,
        "D11C 44-item reconciliation diverge",
    )
    require(
        notice["counts"]["d11d_initial_text_pending"] == 16
        and notice["counts"]["d11d_text_resolved"] == 1,
        "D11D 16-item reconciliation diverge",
    )
    require(
        notice["counts"]["notice_resolved"] == 29
        and notice["counts"]["notice_not_required"] == 27
        and notice["counts"]["notice_pending"] == 0,
        "D11D notice accounting diverge",
    )
    require(
        notice["counts"]["license_text_pending"] == counts["license_text_pending"],
        "notice pending count diverge",
    )
    require(
        notice["counts"]["license_text_resolved"]
        + notice["counts"]["license_text_pending"]
        == notice["counts"]["components"],
        "notice coverage count diverge",
    )
    require(
        len(notice["missing_license_text"]) == notice["counts"]["license_text_pending"],
        "notice missing-license inventory diverge",
    )
    require(
        notice["counts"]["license_expression_pending"]
        == counts["license_expression_pending"],
        "notice expression-pending count diverge",
    )
    require(
        len(notice["missing_license_expression"])
        == notice["counts"]["license_expression_pending"],
        "notice missing-expression inventory diverge",
    )
    require(
        len(notice["missing_notice_identity"])
        == notice["counts"]["notice_pending"]
        == counts["notice_identity_pending"],
        "notice identity-pending inventory diverge",
    )
    require(notice["counts"]["unknown"] == 0, "notice UNKNOWN presente")
    required_component_fields = {
        "component",
        "version",
        "source",
        "checksum",
        "materiality",
        "consumers",
        "license_expression_status",
        "license_expression",
        "license_files",
        "notice_files",
        "license_text_status",
        "notice_status",
        "provenance_method",
        "source_parent",
        "review_flags",
        "review_status",
    }
    identities = set()
    d11c_mappings = []
    derived_missing_text = []
    derived_missing_expression = []
    derived_missing_notice = []
    d11h_identities = set()
    for component in notice["components"]:
        require(
            required_component_fields <= component.keys(),
            f"notice component incompleto: {component.get('component')}",
        )
        identity = (
            component["component"],
            component["version"],
            component["source"],
        )
        require(identity not in identities, f"notice component duplicado: {identity}")
        identities.add(identity)
        require(
            component["license_expression_status"] != "PENDING"
            or component["license_expression"] is None,
            f"license expression status inconsistente: {identity}",
        )
        require(
            component["license_text_status"] in {"TEXT_RESOLVED", "TEXT_PENDING"},
            f"license text status inválido: {identity}",
        )
        all_text_records = component["license_files"] + component["notice_files"]
        require(
            all(
                not record["path"].startswith(SPDX_REFERENCE_ROOT.as_posix() + "/")
                for record in all_text_records
            ),
            f"SPDX reference apresentada como upstream: {identity}",
        )
        if component["license_text_status"] == "TEXT_RESOLVED":
            require(all_text_records, f"resolved component sem texto: {identity}")
        else:
            derived_missing_text.append(
                f"{component['component']}@{component['version']}"
            )
        if component["license_expression_status"] == "PENDING":
            derived_missing_expression.append(
                f"{component['component']}@{component['version']}"
            )
        if component["notice_status"] == "NOTICE_IDENTITY_PENDING":
            derived_missing_notice.append(
                f"{component['component']}@{component['version']}"
            )
        if component["notice_status"] == "NOTICE_RESOLVED":
            require(
                component["notice_files"],
                f"resolved notice sem arquivo: {identity}",
            )
        if component.get("initial_d11b_text_pending"):
            complete = _complete_text_set(
                component["license_expression"], component["license_files"]
            )
            require(
                complete == (component["license_text_status"] == "TEXT_RESOLVED"),
                f"D11B license text status inconsistente: {identity}",
            )
        if component.get("upstream_mapping"):
            mapping = component["upstream_mapping"]
            d11c_mappings.append(mapping)
            require(
                mapping["component"]
                == f"{component['component']}@{component['version']}"
                and mapping["crate_checksum"] == (component["checksum"] or "").upper()
                and mapping["license_expression"] == component["license_expression"]
                and mapping["resolution_status"] == component["license_text_status"],
                f"D11C component mapping diverge: {identity}",
            )
        if component.get("d11h_license_policy"):
            policy = component["d11h_license_policy"]
            d11h_identity = (component["component"], component["version"])
            d11h_identities.add(d11h_identity)
            expected_expression = D11H_COMPONENT_EXPRESSIONS.get(d11h_identity)
            require(
                expected_expression == component["license_expression"],
                f"D11H component identity/expression diverge: {identity}",
            )
            expected_upstream = (
                "PARTIAL" if d11h_identity in D11H_PARTIAL_UPSTREAM_TEXT else "ABSENT"
            )
            expected_references = spdx_expression_identifiers(expected_expression)
            require(
                policy
                == {
                    "attribution_metadata": "PARTIAL",
                    "canonical_reference_set": expected_references,
                    "canonical_reference_text": "AVAILABLE_FROM_PINNED_SPDX",
                    "d11f_category": ("D" if " OR " in expected_expression else "C"),
                    "legal_review": "P3_REQUIRED",
                    "license_identity": "RESOLVED_FROM_EXACT_UPSTREAM_METADATA",
                    "notice_delivery": "PENDING_FIX",
                    "notice_identity": "RESOLVED",
                    "policy": "ADOPT_CANONICAL_REFERENCE_POLICY_FOR_P3_REVIEW",
                    "upstream_license_text": expected_upstream,
                },
                f"D11H component policy diverge: {identity}",
            )
            require(
                set(expected_references) <= available_spdx_ids,
                f"D11H canonical reference ausente: {identity}",
            )
            require(
                component["license_text_status"] == "TEXT_PENDING",
                f"SPDX reference promoveu upstream text indevidamente: {identity}",
            )
            require(
                (expected_upstream == "PARTIAL") == bool(component["license_files"]),
                f"D11H upstream text accounting diverge: {identity}",
            )
        for record in component["license_files"] + component["notice_files"]:
            require(
                {"path", "size", "sha256", "role", "provenance_method"}
                <= record.keys(),
                f"license evidence record incompleto: {identity}",
            )
            require(
                record["size"] > 0
                and re.fullmatch(r"[0-9A-F]{64}", record["sha256"]) is not None,
                f"license evidence identity inválida: {identity}",
            )
    require(
        derived_missing_text == notice["missing_license_text"],
        "derived missing-license inventory diverge",
    )
    require(
        derived_missing_expression == notice["missing_license_expression"],
        "derived missing-expression inventory diverge",
    )
    require(
        derived_missing_notice == notice["missing_notice_identity"],
        "derived missing-notice inventory diverge",
    )
    require(len(identities) == 931, "notice component identity count diverge")
    require(
        d11h_identities == set(D11H_COMPONENT_EXPRESSIONS),
        "D11H 15-component policy coverage diverge",
    )
    require(
        notice["counts"]["d11h_canonical_reference_available"] == 15
        and notice["counts"]["d11h_canonical_reference_missing"] == 0
        and notice["counts"]["d11h_category_c"] == 10
        and notice["counts"]["d11h_category_d"] == 5
        and notice["counts"]["d11h_upstream_license_text_absent"] == 13
        and notice["counts"]["d11h_upstream_license_text_partial"] == 2,
        "D11H accounting diverge",
    )
    require(
        len(d11c_mappings) == 44
        and len({item["component"] for item in d11c_mappings}) == 44,
        "D11C component mapping coverage diverge",
    )
    swc_mappings = [
        item for item in d11c_mappings if item["repository"] == SWC_REPOSITORY
    ]
    require(
        len(swc_mappings) == 27
        and all(
            item["evidence_commit"] == "b0ab736714f7574cd8e5f12eee224d666f01fccc"
            and item["exact_release_tag"] == "swc_core@v48.0.4"
            and item["workspace_license_inherited"]
            and item["relation"] == "EXACT_RELEASE_TAG_WORKSPACE_LICENSE_INHERITANCE"
            and item["resolution_status"] == "TEXT_RESOLVED"
            for item in swc_mappings
        ),
        "D11C SWC family mapping diverge",
    )
    dlopen_mapping = next(
        item for item in d11c_mappings if item["component"] == "dlopen2@0.6.1"
    )
    require(
        dlopen_mapping["crate_vcs_commit"] is None
        and dlopen_mapping["evidence_commit"]
        == "8580a7c1eafad6507b6c5fd37cb2e404af7e214d"
        and dlopen_mapping["relation"]
        == "EXACT_VERSION_COMMIT_CRATE_MANIFEST_MATCH_WORKSPACE_ROOT_LICENSE"
        and dlopen_mapping["resolution_phase"] == "D11D"
        and dlopen_mapping["resolution_status"] == "TEXT_RESOLVED"
        and dlopen_mapping["root_license_paths"] == ["LICENSE"]
        and dlopen_mapping["package_manifest"]["path"] == "dlopen2/Cargo.toml"
        and dlopen_mapping["workspace_manifest"]["path"] == "Cargo.toml",
        "D11D dlopen2 exact-version mapping diverge",
    )
    dlopen_component = next(
        item
        for item in notice["components"]
        if item["component"] == "dlopen2" and item["version"] == "0.6.1"
    )
    require(
        {record["sha256"] for record in dlopen_component["license_files"]}
        == {"39FA265207450E77C62E90C5594A06C085B655D8374C7CED4BF7894B6BD95DD2"},
        "D11D dlopen2 license text diverge",
    )
    require(
        sum(item["resolution_status"] == "TEXT_RESOLVED" for item in d11c_mappings)
        == 29
        and sum(item["resolution_status"] == "TEXT_PENDING" for item in d11c_mappings)
        == 15,
        "D11D resolved/pending accounting diverge",
    )
    require(
        sum(
            item.get("notice_status") == "NOTICE_NOT_REQUIRED_BY_UPSTREAM_STRUCTURE"
            for item in d11c_mappings
        )
        == 16,
        "D11D exact-upstream notice accounting diverge",
    )
    require(
        notice["license_evidence_index"]
        == {
            "path": LICENSE_EVIDENCE_INDEX.as_posix(),
            "sha256": LICENSE_EVIDENCE_INDEX_SHA256,
            "records": 60,
            "mappings": 44,
            "authority": "OFFICIAL_UPSTREAM_IMMUTABLE_REVISION_OR_EXACT_RELEASE_TAG",
        },
        "D11D license evidence identity diverge",
    )
    generated_notice = notice["generated_notice"]
    rendered_notice = render_notice_text(notice)
    require(
        generated_notice
        == {
            "path": DEFAULT_NOTICE_TEXT.as_posix(),
            "size": len(rendered_notice),
            "sha256": sha256_bytes(rendered_notice),
            "classification": "PARTIAL_FUTURE_CANDIDATE_INPUT_NOT_DELIVERED",
        },
        "generated notice metadata diverge",
    )
    require(notice["status"] == "PARTIAL_GENERATED_INVENTORY", "notice status diverge")


def load_manifest(path: Path = DEFAULT_MANIFEST) -> tuple[dict, dict]:
    raw = path.read_bytes()
    if path == DEFAULT_MANIFEST:
        require(OFFICIAL_MANIFEST_SHA256 != "UNPINNED", "manifest pin não configurado")
        require(sha256_bytes(raw) == OFFICIAL_MANIFEST_SHA256, "manifest hash diverge")
    manifest = json.loads(raw)
    notice_path = path.with_name("DENO_THIRD_PARTY_INVENTORY.json")
    notice_raw = notice_path.read_bytes()
    if path == DEFAULT_MANIFEST:
        require(
            OFFICIAL_NOTICE_MANIFEST_SHA256 != "UNPINNED",
            "notice manifest pin não configurado",
        )
        require(
            sha256_bytes(notice_raw) == OFFICIAL_NOTICE_MANIFEST_SHA256,
            "notice manifest hash diverge",
        )
    notice = json.loads(notice_raw)
    notice_text_path = path.with_name("DENO_THIRD_PARTY_NOTICES.txt")
    notice_text = notice_text_path.read_bytes()
    if path == DEFAULT_MANIFEST:
        require(
            OFFICIAL_NOTICE_TEXT_SHA256 != "UNPINNED",
            "notice text pin não configurado",
        )
        require(
            sha256_bytes(notice_text) == OFFICIAL_NOTICE_TEXT_SHA256,
            "notice text hash diverge",
        )
    require(
        len(notice_text) == notice["generated_notice"]["size"]
        and sha256_bytes(notice_text) == notice["generated_notice"]["sha256"],
        "generated notice text identity diverge",
    )
    validate_manifest_structure(manifest, notice)
    return manifest, notice


def _review_logical_path(value: str) -> str:
    pure = PurePosixPath(value)
    require(
        value == pure.as_posix()
        and value
        and not pure.is_absolute()
        and re.match(r"^[A-Za-z]:", value) is None
        and ".." not in pure.parts
        and "\\" not in value,
        f"review bundle path inseguro: {value}",
    )
    return value


def _review_content_is_archive(path: str) -> bool:
    return path.endswith((".crate", ".tar.gz", ".tar.xz"))


def validate_review_member(path: str, data: bytes | None = None) -> None:
    logical = _review_logical_path(path)
    validate_source_member(logical, b"" if data is None else data)
    lowered = logical.casefold()
    lowered_parts = {part.casefold() for part in PurePosixPath(logical).parts}
    require(
        not lowered_parts.intersection(
            {
                ".venv",
                "__pycache__",
                "activation_issuer",
                "build-cache",
                "logs",
                "private-register",
            }
        )
        and PurePosixPath(lowered).suffix not in {".part", ".partial", ".tmp"},
        f"review bundle contém namespace proibido: {logical}",
    )
    if data is None or _review_content_is_archive(logical):
        return
    lowered_data = data.lower()
    require(
        b"c:/users/" not in lowered_data and b"c:\\users\\" not in lowered_data,
        f"review bundle contém path pessoal: {logical}",
    )
    require(
        b"baixador escolar" not in lowered_data
        and b"appdata\\local" not in lowered_data,
        f"review bundle contém path local do projeto: {logical}",
    )
    require(
        re.search(rb"(?i)(?:^|[\s\"'=])[a-z]:[\\/]", data) is None
        and re.search(rb"(?i)(?:^|[\s\"'=])/(?:home|users)/", data) is None,
        f"review bundle contém path absoluto local: {logical}",
    )


def _review_entry(
    logical_path: str,
    source: Path,
    role: str,
    authority: str,
    **metadata: object,
) -> dict:
    validate_review_member(logical_path)
    require(source.is_file() and not source.is_symlink(), f"input ausente: {source}")
    entry = {
        "authority": authority,
        "logical_path": logical_path,
        "role": role,
        "sha256": sha256_file(source),
        "size": source.stat().st_size,
    }
    entry.update(metadata)
    if not _review_content_is_archive(logical_path):
        validate_review_member(logical_path, source.read_bytes())
    return entry


def _review_add_file(
    files: list[dict],
    sources: dict[str, Path],
    logical_path: str,
    source: Path,
    role: str,
    authority: str,
    **metadata: object,
) -> None:
    entry = _review_entry(logical_path, source, role, authority, **metadata)
    folded = logical_path.casefold()
    require(
        all(item["logical_path"].casefold() != folded for item in files),
        f"review bundle path duplicado: {logical_path}",
    )
    files.append(entry)
    sources[logical_path] = source


def require_review_candidate(manifest: dict, notice: dict) -> None:
    counts = manifest["counts"]
    status = manifest["status"]
    require(
        counts["source_pending"]
        == counts["source_blocked"]
        == counts["open_source_unknown"]
        == 0,
        "source correspondence incompleta para review bundle",
    )
    require(
        counts["license_expression_pending"] == 0
        and status["license_identity"] == "RESOLVED",
        "license identity incompleta para review bundle",
    )
    require(
        counts["license_text_pending"] == 15
        and counts["upstream_license_text_absent"] == 13
        and counts["upstream_license_text_partial"] == 2,
        "D11H upstream license accounting diverge",
    )
    require(
        counts["canonical_reference_available"] == 15
        and counts["canonical_reference_missing"] == 0
        and status["canonical_reference_coverage"] == "COMPLETE_FOR_D11H_SCOPE",
        "D11H canonical reference coverage incompleta",
    )
    require(
        notice["counts"]["d11h_category_c"] == 10
        and notice["counts"]["d11h_category_d"] == 5,
        "D11H category C/D accounting diverge",
    )
    require(
        status["source_correspondence"] == "TECHNICALLY_COMPLETE"
        and status["notice_identity"] == "RESOLVED"
        and status["notice_delivery"] == "PENDING_FIX"
        and status["legal_review"] == "P3_REQUIRED"
        and status["build_reproducibility"] == "P2_SEPARATE_PENDING"
        and status["microsoft"] == "P3_PENDING_REVIEW",
        "review bundle compliance boundary diverge",
    )
    require(
        status["staging"] == status["bundle"] == "NOT_CREATED_PARTIAL",
        "D11H historical manifest foi indevidamente reescrito",
    )


def _review_payload_inventory(files: list[dict]) -> dict:
    ordered = sorted(files, key=lambda item: item["logical_path"])
    return {
        "byte_count": sum(item["size"] for item in ordered),
        "file_count": len(ordered),
        "inventory_sha256": sha256_bytes(canonical(ordered)),
    }


def build_review_manifest() -> tuple[dict, dict[str, Path]]:
    deno_manifest, notice = load_manifest()
    require_review_candidate(deno_manifest, notice)
    spdx = load_spdx_reference_manifest()
    files: list[dict] = []
    sources: dict[str, Path] = {}

    parent_specs = (
        (
            "deno",
            Path(deno_manifest["parents"]["deno"]["archive"]),
            "sources/deno/deno-2.9.5.tar.gz",
        ),
        (
            "rust",
            Path(deno_manifest["parents"]["rust"]["archive"]),
            "sources/rust/rust-src-1.95.0.tar.xz",
        ),
        (
            "v8",
            Path(deno_manifest["parents"]["v8"]["archive"]),
            f"sources/v8/denoland-v8-{V8_COMMIT}.tar.gz",
        ),
        (
            "v8_rust",
            Path(deno_manifest["parents"]["v8_rust"]["archive"]),
            f"sources/v8/chromium-third-party-rust-{V8_RUST_COMMIT}.tar.gz",
        ),
    )
    source_parents = []
    for name, source, logical_path in parent_specs:
        parent = deno_manifest["parents"][name]
        require(
            source.stat().st_size == parent["archive_size"]
            and sha256_file(source) == parent["archive_sha256"],
            f"source parent diverge: {name}",
        )
        _review_add_file(
            files,
            sources,
            logical_path,
            source,
            "source_parent_archive",
            "PINNED_UPSTREAM_SOURCE_ARCHIVE",
            component=name,
        )
        source_parents.append(
            {
                "component": name,
                "logical_path": logical_path,
                "sha256": parent["archive_sha256"],
                "size": parent["archive_size"],
            }
        )

    acquisitions = json.loads(ACQUISITION_PATH.read_text(encoding="utf-8"))
    acquired = {
        (item["name"], item["version"]): item
        for item in acquisitions["acquired"] + acquisitions["reused"]
    }
    material = {
        (item["name"], item["version"]): item
        for item in deno_manifest["material_crates"]
    }
    require(
        len(acquired) == len(material) == 810, "Cargo material archive count diverge"
    )
    require(set(acquired) == set(material), "Cargo material archive identities diverge")
    for identity in sorted(material, key=lambda item: (item[0].casefold(), item[1])):
        package = material[identity]
        acquisition = acquired[identity]
        source = Path(acquisition["path"])
        checksum = package["checksum"].upper()
        require(
            acquisition["sha256"] == checksum and sha256_file(source) == checksum,
            f"Cargo material archive diverge: {identity}",
        )
        logical_path = f"sources/cargo/{identity[0]}-{identity[1]}.crate"
        _review_add_file(
            files,
            sources,
            logical_path,
            source,
            "cargo_material_source_archive",
            "CARGO_LOCK_AND_CRATES_IO_CHECKSUM",
            component=identity[0],
            version=identity[1],
        )
        if identity == ("v8", "150.4.0"):
            source_parents.append(
                {
                    "component": "rusty_v8",
                    "logical_path": logical_path,
                    "sha256": checksum,
                    "size": source.stat().st_size,
                }
            )

    excluded_evidence = []
    for record in deno_manifest["metadata_evidence"]:
        source = Path(record["path"])
        require(
            source.stat().st_size == record["size"]
            and sha256_file(source) == record["sha256"],
            f"metadata evidence diverge: {source}",
        )
        relative = source.relative_to(WORK_ROOT / "metadata").as_posix()
        if relative in REVIEW_EXCLUDED_METADATA:
            expected = REVIEW_EXCLUDED_METADATA[relative]
            require(
                record["size"] == expected["size"]
                and record["sha256"] == expected["sha256"],
                f"excluded review metadata identity diverge: {relative}",
            )
            excluded_evidence.append(
                {
                    "logical_source": f"evidence/metadata/{relative}",
                    **expected,
                }
            )
            continue
        _review_add_file(
            files,
            sources,
            f"evidence/metadata/{relative}",
            source,
            "source_provenance_metadata",
            "PINNED_UPSTREAM_METADATA",
        )
    for record in deno_manifest["registry_index_evidence"]:
        source = Path(record["path"])
        require(
            source.stat().st_size == record["size"]
            and sha256_file(source) == record["sha256"],
            f"registry index evidence diverge: {source}",
        )
        relative = source.relative_to(INDEX_ROOT).as_posix()
        _review_add_file(
            files,
            sources,
            f"evidence/crates-io-index/{relative}",
            source,
            "cargo_registry_index_metadata",
            "PINNED_CRATES_IO_INDEX_RECORD",
        )

    evidence_root = WORK_ROOT / "license-evidence"
    for source in sorted(path for path in evidence_root.rglob("*") if path.is_file()):
        relative = source.relative_to(evidence_root).as_posix()
        is_license_text = re.match(
            r"^(?:LICENSE|LICENCE|COPYING)(?:[-._].*)?$", source.name
        ) is not None or (
            source.parent.name.casefold() == "license"
            and source.name in {"APACHE", "MIT"}
        )
        namespace = "upstream" if is_license_text else "attribution"
        role = (
            "upstream_license_text_evidence"
            if is_license_text
            else "attribution_or_notice_evidence"
        )
        _review_add_file(
            files,
            sources,
            f"licenses/{namespace}/{relative}",
            source,
            role,
            "EXACT_UPSTREAM_EVIDENCE_PRESERVED_BY_D11D",
        )

    spdx_paths = [
        SPDX_REFERENCE_MANIFEST,
        SPDX_REFERENCE_ROOT / "SPDX_CANONICAL_REFERENCE_POLICY.md",
    ]
    spdx_paths.extend(
        SPDX_REFERENCE_ROOT / item["source_path"] for item in spdx["references"]
    )
    for source in spdx_paths:
        relative = source.relative_to(SPDX_REFERENCE_ROOT).as_posix()
        role = (
            "spdx_canonical_reference_text"
            if relative.startswith("text/")
            else "spdx_reference_policy_metadata"
        )
        _review_add_file(
            files,
            sources,
            f"licenses/spdx-reference/{relative}",
            source,
            role,
            "SPDX_LICENSE_LIST_3_28_0_PINNED_REFERENCE",
        )

    review_documents = (
        DEFAULT_MANIFEST,
        DEFAULT_NOTICE_MANIFEST,
        DEFAULT_NOTICE_TEXT,
        Path("docs/compliance/deno/DENO_RUNTIME_SOURCE_CORRESPONDENCE.md"),
        DEFAULT_REVIEW_README,
    )
    for source in review_documents:
        _review_add_file(
            files,
            sources,
            f"review/{source.name}",
            source,
            "review_policy_or_inventory",
            "EDUDOWNLOADER_GENERATED_COMPLIANCE_METADATA",
        )

    files.sort(key=lambda item: item["logical_path"])
    manifest = {
        "bundle": {
            "classification": "COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW",
            "complete_meaning": "TECHNICAL_SOURCE_AND_EVIDENCE_COMPLETE_FOR_LEGAL_REVIEW_ONLY",
            "filename": REVIEW_BUNDLE_FILENAME,
            "root": REVIEW_BUNDLE_ROOT,
        },
        "cargo_material": {
            "archive_count": 810,
            "codegen": 104,
            "registry": 810,
            "runtime": 765,
            "workspace": 59,
        },
        "compliance": {
            "build_reproducibility": "P2_SEPARATE_PENDING",
            "canonical_reference_coverage": "COMPLETE",
            "legal_review": "P3_REQUIRED",
            "license_identity": "RESOLVED",
            "microsoft": "P3_PENDING_REVIEW",
            "notice_delivery": "PENDING_FIX",
            "notice_identity": "RESOLVED",
            "source_correspondence": "TECHNICALLY_COMPLETE",
        },
        "deno": {
            "commit": DENO_COMMIT,
            "source_archive_sha256": DENO_ARCHIVE_SHA256,
            "target": TARGET,
            "tree": DENO_TREE,
            "version": DENO_VERSION,
        },
        "excluded": [
            "BUILD_ONLY_CARGO",
            "DEV_ONLY_CARGO",
            "DENO_EXECUTABLE",
            "FROZEN_EDUDOWNLOADER_CANDIDATE",
            "GN_NINJA_EXECUTABLES",
            "OPTIONAL_DISABLED_CARGO",
            "PRIVATE_OR_ACTIVATION_MATERIAL",
            "PROPRIETARY_EDUDOWNLOADER_SOURCE",
            "PYTHON_VIRTUAL_ENVIRONMENTS",
            "TARGET_NOT_APPLICABLE_CARGO",
            "UNREACHABLE_CARGO",
        ],
        "excluded_evidence": excluded_evidence,
        "files": files,
        "frozen_candidate": {
            "file_count": 1068,
            "inventory_sha256": "26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857",
            "modified": False,
            "total_size_bytes": 382736507,
        },
        "license_accounting": {
            "category_c": 10,
            "category_d": 5,
            "legacy_text_pending": 15,
            "present_or_text_resolved": 916,
            "upstream_absent": 13,
            "upstream_partial": 2,
            "zune_partial": ["zune-core@0.4.12", "zune-jpeg@0.4.13"],
        },
        "payload_inventory": _review_payload_inventory(files),
        "schema": 1,
        "source_parents": sorted(source_parents, key=lambda item: item["component"]),
        "spdx": {
            "classification": "SPDX_CANONICAL_REFERENCE_TEXT",
            "commit": SPDX_SNAPSHOT_COMMIT,
            "identifiers": ["Apache-2.0", "CC0-1.0", "MIT", "Zlib"],
            "reference_count": 4,
            "tag": SPDX_SNAPSHOT_TAG,
            "version": SPDX_SNAPSHOT_VERSION,
        },
        "title": "EduDownloader Deno 2.9.5 source review bundle manifest",
    }
    return manifest, sources


def validate_review_manifest(manifest: dict) -> None:
    require(manifest.get("schema") == 1, "review manifest schema diverge")
    require(
        manifest.get("bundle")
        == {
            "classification": "COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW",
            "complete_meaning": "TECHNICAL_SOURCE_AND_EVIDENCE_COMPLETE_FOR_LEGAL_REVIEW_ONLY",
            "filename": REVIEW_BUNDLE_FILENAME,
            "root": REVIEW_BUNDLE_ROOT,
        },
        "review bundle classification diverge",
    )
    require(
        manifest.get("cargo_material")
        == {
            "archive_count": 810,
            "codegen": 104,
            "registry": 810,
            "runtime": 765,
            "workspace": 59,
        },
        "review bundle Cargo accounting diverge",
    )
    require(
        manifest.get("compliance")
        == {
            "build_reproducibility": "P2_SEPARATE_PENDING",
            "canonical_reference_coverage": "COMPLETE",
            "legal_review": "P3_REQUIRED",
            "license_identity": "RESOLVED",
            "microsoft": "P3_PENDING_REVIEW",
            "notice_delivery": "PENDING_FIX",
            "notice_identity": "RESOLVED",
            "source_correspondence": "TECHNICALLY_COMPLETE",
        },
        "review bundle compliance boundary diverge",
    )
    require(
        manifest.get("deno")
        == {
            "commit": DENO_COMMIT,
            "source_archive_sha256": DENO_ARCHIVE_SHA256,
            "target": TARGET,
            "tree": DENO_TREE,
            "version": DENO_VERSION,
        },
        "review bundle Deno identity diverge",
    )
    require(
        manifest.get("license_accounting")
        == {
            "category_c": 10,
            "category_d": 5,
            "legacy_text_pending": 15,
            "present_or_text_resolved": 916,
            "upstream_absent": 13,
            "upstream_partial": 2,
            "zune_partial": ["zune-core@0.4.12", "zune-jpeg@0.4.13"],
        },
        "review bundle license accounting diverge",
    )
    require(
        manifest.get("spdx")
        == {
            "classification": "SPDX_CANONICAL_REFERENCE_TEXT",
            "commit": SPDX_SNAPSHOT_COMMIT,
            "identifiers": ["Apache-2.0", "CC0-1.0", "MIT", "Zlib"],
            "reference_count": 4,
            "tag": SPDX_SNAPSHOT_TAG,
            "version": SPDX_SNAPSHOT_VERSION,
        },
        "review bundle SPDX identity diverge",
    )
    require(
        manifest.get("frozen_candidate")
        == {
            "file_count": 1068,
            "inventory_sha256": "26B6CCDAA3332D46DAF30DCEE44100EADFA53971C990F995A418A0A65B073857",
            "modified": False,
            "total_size_bytes": 382736507,
        },
        "historical frozen candidate boundary diverge",
    )
    require(
        manifest.get("excluded_evidence")
        == [
            {
                "logical_source": f"evidence/metadata/{relative}",
                **REVIEW_EXCLUDED_METADATA[relative],
            }
            for relative in sorted(REVIEW_EXCLUDED_METADATA)
        ],
        "review bundle excluded evidence diverge",
    )
    files = manifest.get("files")
    require(isinstance(files, list) and files, "review bundle file inventory ausente")
    require(
        files == sorted(files, key=lambda item: item["logical_path"]),
        "review bundle file inventory desordenado",
    )
    folded = [item["logical_path"].casefold() for item in files]
    require(len(folded) == len(set(folded)), "review bundle paths duplicados")
    for item in files:
        require(
            set(item) >= {"authority", "logical_path", "role", "sha256", "size"}
            and re.fullmatch(r"[A-F0-9]{64}", item["sha256"])
            and isinstance(item["size"], int)
            and item["size"] >= 0,
            "review bundle file record inválido",
        )
        validate_review_member(item["logical_path"])
    require(
        manifest.get("payload_inventory") == _review_payload_inventory(files),
        "review bundle payload inventory diverge",
    )
    require(
        sum(item["role"] == "cargo_material_source_archive" for item in files) == 810,
        "review bundle não contém 810 Cargo material archives",
    )
    require(
        sum(item["role"] == "spdx_canonical_reference_text" for item in files) == 4,
        "review bundle não contém quatro referências SPDX",
    )
    role_counts = {
        role: sum(item["role"] == role for item in files)
        for role in {item["role"] for item in files}
    }
    require(
        role_counts
        == {
            "attribution_or_notice_evidence": 33,
            "cargo_material_source_archive": 810,
            "cargo_registry_index_metadata": 758,
            "review_policy_or_inventory": 5,
            "source_parent_archive": 4,
            "source_provenance_metadata": 34,
            "spdx_canonical_reference_text": 4,
            "spdx_reference_policy_metadata": 2,
            "upstream_license_text_evidence": 60,
        },
        "review bundle role accounting diverge",
    )
    source_parents = manifest.get("source_parents")
    require(
        isinstance(source_parents, list)
        and {item.get("component") for item in source_parents}
        == {"deno", "rust", "rusty_v8", "v8", "v8_rust"},
        "review bundle source parents diverge",
    )
    by_path = {item["logical_path"]: item for item in files}
    for parent in source_parents:
        source_entry = by_path.get(parent.get("logical_path"))
        require(
            source_entry is not None
            and source_entry["sha256"] == parent.get("sha256")
            and source_entry["size"] == parent.get("size"),
            f"review bundle source parent record diverge: {parent.get('component')}",
        )
    require(
        manifest["payload_inventory"]["file_count"] <= MAX_REVIEW_FILES
        and manifest["payload_inventory"]["byte_count"] <= MAX_REVIEW_BYTES,
        "review bundle excede limites",
    )
    raw = formatted(manifest)
    require(
        b"C:/Users/" not in raw
        and b"C:\\Users\\" not in raw
        and b"Baixador Escolar" not in raw,
        "review manifest contém path pessoal",
    )


def load_review_manifest(path: Path = DEFAULT_REVIEW_MANIFEST) -> dict:
    raw = path.read_bytes()
    if path == DEFAULT_REVIEW_MANIFEST:
        require(
            OFFICIAL_REVIEW_MANIFEST_SHA256 != "UNPINNED",
            "review manifest pin não configurado",
        )
        require(
            sha256_bytes(raw) == OFFICIAL_REVIEW_MANIFEST_SHA256,
            "review manifest hash diverge",
        )
    manifest = json.loads(raw)
    require(raw == formatted(manifest), "review manifest não canônico")
    validate_review_manifest(manifest)
    return manifest


def verify_review_staging(
    manifest: dict, staging: Path, *, validate_policy: bool = True
) -> dict:
    if validate_policy:
        validate_review_manifest(manifest)
    require(staging.is_dir(), "review staging ausente")
    expected = {item["logical_path"]: item for item in manifest["files"]}
    manifest_bytes = formatted(manifest)
    expected[REVIEW_BUNDLE_MANIFEST_NAME] = {
        "logical_path": REVIEW_BUNDLE_MANIFEST_NAME,
        "role": "bundle_manifest",
        "sha256": sha256_bytes(manifest_bytes),
        "size": len(manifest_bytes),
    }
    actual = {}
    for path in staging.rglob("*"):
        require(not path.is_symlink(), "review staging contém link simbólico")
        if path.is_file():
            relative = path.relative_to(staging).as_posix()
            validate_review_member(relative)
            actual[relative] = path
    require(set(actual) == set(expected), "review staging composição diverge")
    entries = []
    for relative in sorted(expected):
        record = expected[relative]
        path = actual[relative]
        require(
            path.stat().st_size == record["size"]
            and sha256_file(path) == record["sha256"],
            f"review staging file diverge: {relative}",
        )
        if not _review_content_is_archive(relative):
            validate_review_member(relative, path.read_bytes())
        entries.append(
            {
                "relative_path": relative,
                "sha256": record["sha256"],
                "size": record["size"],
            }
        )
    return {
        "byte_count": sum(item["size"] for item in entries),
        "entries": entries,
        "file_count": len(entries),
        "inventory_sha256": sha256_bytes(canonical(entries)),
    }


def create_review_staging(
    manifest: dict, sources: dict[str, Path], staging: Path
) -> dict:
    if staging.exists():
        result = verify_review_staging(manifest, staging)
        result["reused"] = True
        return result
    incomplete = staging.with_name(staging.name + ".incomplete")
    require(
        not incomplete.exists(), f"review staging incompleto preservado: {incomplete}"
    )
    incomplete.mkdir(parents=True)
    for item in manifest["files"]:
        logical = item["logical_path"]
        source = sources.get(logical)
        require(source is not None, f"review staging source ausente: {logical}")
        destination = incomplete / PurePosixPath(logical)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (incomplete / REVIEW_BUNDLE_MANIFEST_NAME).write_bytes(formatted(manifest))
    result = verify_review_staging(manifest, incomplete)
    incomplete.rename(staging)
    result["reused"] = False
    return result


def _review_zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=REVIEW_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _review_inventory_document(entries: list[dict]) -> dict:
    return {
        "entries": entries,
        "inventory_sha256": sha256_bytes(canonical(entries)),
        "schema": 1,
    }


def assemble_review_bundle(
    manifest: dict,
    staging: Path,
    output: Path,
    *,
    validate_policy: bool = True,
) -> dict:
    if validate_policy:
        validate_review_manifest(manifest)
    staging_inventory = verify_review_staging(
        manifest, staging, validate_policy=validate_policy
    )
    if output.exists():
        result = verify_review_bundle(manifest, output, validate_policy=validate_policy)
        result["reused"] = True
        return result
    incomplete = output.with_name(output.name + ".incomplete")
    require(
        not incomplete.exists(), f"review bundle incompleto preservado: {incomplete}"
    )
    inventory = _review_inventory_document(staging_inventory["entries"])
    inventory_bytes = formatted(inventory)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        incomplete, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        names = [
            f"{REVIEW_BUNDLE_ROOT}/{item['relative_path']}"
            for item in staging_inventory["entries"]
        ]
        inventory_name = f"{REVIEW_BUNDLE_ROOT}/{REVIEW_BUNDLE_INVENTORY_NAME}"
        for name in sorted(names + [inventory_name]):
            if name == inventory_name:
                archive.writestr(
                    _review_zip_info(name), inventory_bytes, compresslevel=9
                )
                continue
            relative = name.removeprefix(f"{REVIEW_BUNDLE_ROOT}/")
            with (staging / PurePosixPath(relative)).open("rb") as source_stream:
                with archive.open(
                    _review_zip_info(name), "w", force_zip64=True
                ) as target:
                    shutil.copyfileobj(source_stream, target, length=1024 * 1024)
    incomplete.rename(output)
    result = verify_review_bundle(manifest, output, validate_policy=validate_policy)
    result["reused"] = False
    return result


def verify_review_bundle(
    manifest: dict,
    bundle: Path,
    *,
    validate_policy: bool = True,
) -> dict:
    if validate_policy:
        validate_review_manifest(manifest)
    expected_manifest = formatted(manifest)
    inventory_name = f"{REVIEW_BUNDLE_ROOT}/{REVIEW_BUNDLE_INVENTORY_NAME}"
    manifest_name = f"{REVIEW_BUNDLE_ROOT}/{REVIEW_BUNDLE_MANIFEST_NAME}"
    try:
        with zipfile.ZipFile(bundle) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            require(names == sorted(names), "review bundle ZIP desordenado")
            require(
                len(names) == len({name.casefold() for name in names}),
                "review bundle ZIP duplicado",
            )
            require(
                inventory_name in names and manifest_name in names,
                "review bundle metadata ausente",
            )
            for info in infos:
                require(
                    info.date_time == REVIEW_ZIP_TIMESTAMP
                    and info.compress_type == zipfile.ZIP_DEFLATED
                    and info.create_system == 3
                    and info.external_attr == 0o100644 << 16,
                    f"review bundle ZIP metadata diverge: {info.filename}",
                )
                relative = info.filename.removeprefix(f"{REVIEW_BUNDLE_ROOT}/")
                require(
                    info.filename == f"{REVIEW_BUNDLE_ROOT}/{relative}",
                    "review bundle root diverge",
                )
                validate_review_member(relative)
            require(
                archive.read(manifest_name) == expected_manifest,
                "review bundle manifest diverge",
            )
            inventory_raw = archive.read(inventory_name)
            inventory = json.loads(inventory_raw)
            require(
                inventory_raw == formatted(inventory),
                "review bundle inventory não canônico",
            )
            entries = inventory.get("entries")
            require(isinstance(entries, list), "review bundle inventory inválido")
            expected_names = {
                f"{REVIEW_BUNDLE_ROOT}/{item['relative_path']}" for item in entries
            }
            require(
                set(names) == expected_names | {inventory_name},
                "review bundle composição diverge",
            )
            recomputed = []
            for item in entries:
                name = f"{REVIEW_BUNDLE_ROOT}/{item['relative_path']}"
                digest = hashlib.sha256()
                size = 0
                with archive.open(name) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                recomputed.append(
                    {
                        "relative_path": item["relative_path"],
                        "sha256": digest.hexdigest().upper(),
                        "size": size,
                    }
                )
            require(recomputed == entries, "review bundle bytes divergem do inventário")
            inventory_hash = sha256_bytes(canonical(entries))
            require(
                inventory.get("inventory_sha256") == inventory_hash,
                "review bundle inventory hash diverge",
            )
            uncompressed = sum(info.file_size for info in infos)
            compressed = sum(info.compress_size for info in infos)
    except (OSError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as error:
        raise SourceBundleError("review bundle ausente ou inválido") from error
    return {
        "bundle_sha256": sha256_file(bundle),
        "bundle_size": bundle.stat().st_size,
        "compressed_payload_bytes": compressed,
        "file_count": len(infos),
        "inventory_sha256": inventory_hash,
        "uncompressed_byte_count": uncompressed,
    }


def compare_review_bundles(first: Path, second: Path) -> dict:
    require(
        first.is_file() and second.is_file(), "review bundle comparison input ausente"
    )
    first_hash = sha256_file(first)
    second_hash = sha256_file(second)
    equal = first.stat().st_size == second.stat().st_size and first_hash == second_hash
    if equal:
        with first.open("rb") as left, second.open("rb") as right:
            while True:
                left_chunk = left.read(1024 * 1024)
                right_chunk = right.read(1024 * 1024)
                if left_chunk != right_chunk:
                    equal = False
                    break
                if not left_chunk:
                    break
    require(equal, "review bundle assemblies não são byte-identical")
    return {
        "byte_equal": True,
        "first_sha256": first_hash,
        "second_sha256": second_hash,
        "size": first.stat().st_size,
    }


def require_complete(manifest: dict) -> None:
    counts = manifest["counts"]
    require(
        counts["source_pending"]
        == counts["source_blocked"]
        == counts["open_source_unknown"]
        == 0,
        "closure parcial: staging/bundle COMPLETE proibido",
    )
    require(
        counts["license_text_pending"] == 0,
        "licenses pendentes: bundle COMPLETE proibido",
    )
    require(
        counts["license_expression_pending"] == 0,
        "expressões de licença pendentes: bundle COMPLETE proibido",
    )
    require(manifest["status"]["open_source_correspondence"] == "A", "classe A ausente")
    require(
        manifest["status"]["v8_native_closure"] == "RESOLVED",
        "V8 native closure incompleta",
    )
    require(
        manifest["status"]["notice_inventory"] == "COMPLETE_GENERATED_INVENTORY",
        "notice inventory incompleto",
    )


def verify_evidence(
    manifest: dict,
    notice: dict,
    source_root: Path,
    *,
    notice_text_path: Path | None = None,
) -> None:
    verify_wave_a(source_root)
    current_parents = inspect_parents()
    require(
        canonical(current_parents) == canonical(manifest["parents"]),
        "parent evidence diverge",
    )
    for record in manifest["metadata_evidence"] + manifest["registry_index_evidence"]:
        path = Path(record["path"])
        require(
            path.is_file() and path.stat().st_size == record["size"],
            f"evidence ausente/diverge: {path}",
        )
        require(sha256_file(path) == record["sha256"], f"evidence hash diverge: {path}")
    resolution = CargoResolver(source_root).resolve()
    acquisitions = json.loads(ACQUISITION_PATH.read_text(encoding="utf-8"))
    final_resolution, inspection = inspect_material_crates(
        resolution, acquisitions, source_root
    )
    require(
        canonical(final_resolution) == canonical(manifest["cargo_resolution"]),
        "Cargo closure diverge",
    )
    regenerated_v8 = build_v8_native_closure(current_parents)
    regenerated_notice = build_notice_inventory(
        final_resolution, inspection, regenerated_v8, current_parents
    )
    require(
        canonical(regenerated_notice) == canonical(notice), "notice inventory diverge"
    )
    require(
        (notice_text_path or DEFAULT_NOTICE_TEXT).read_bytes()
        == render_notice_text(regenerated_notice),
        "generated notice text diverge",
    )
    require(
        canonical(regenerated_v8) == canonical(manifest["v8_native_closure"]),
        "V8 native GN evidence diverge",
    )


def source_root_from_args(value: str | None) -> Path:
    if value:
        return Path(value)
    matches = list((WORK_ROOT / "work" / "deno").glob("deno-*"))
    require(len(matches) == 1, "projeção Deno de trabalho ausente/ambígua")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify-wave-a")
    resolve_parser = sub.add_parser("resolve")
    resolve_parser.add_argument("--acquire-index", action="store_true")
    sub.add_parser("acquire-crates")
    sub.add_parser("inspect-crates")
    sub.add_parser("inspect-parents")
    sub.add_parser("generate-manifests")
    sub.add_parser("generate-review-manifest")
    sub.add_parser("verify-evidence")
    stage_parser = sub.add_parser("stage-review-bundle")
    stage_parser.add_argument("--staging", type=Path, default=REVIEW_STAGING)
    verify_staging_parser = sub.add_parser("verify-staging")
    verify_staging_parser.add_argument("--staging", type=Path, default=REVIEW_STAGING)
    assemble_parser = sub.add_parser("assemble")
    assemble_parser.add_argument("--staging", type=Path, default=REVIEW_STAGING)
    assemble_parser.add_argument("--output", type=Path, default=REVIEW_BUNDLE)
    verify_bundle_parser = sub.add_parser("verify-bundle")
    verify_bundle_parser.add_argument("--bundle", type=Path, default=REVIEW_BUNDLE)
    determinism_parser = sub.add_parser("verify-determinism")
    determinism_parser.add_argument("--first", type=Path, default=REVIEW_BUNDLE)
    determinism_parser.add_argument("--second", type=Path, default=REVIEW_BUNDLE_SECOND)
    args = parser.parse_args(argv)
    source_root = source_root_from_args(args.source_root)
    if args.command == "verify-wave-a":
        print(json.dumps(verify_wave_a(source_root), indent=2))
        return 0
    if args.command == "inspect-parents":
        result = inspect_parents()
        PARENT_INSPECTION_PATH.write_bytes(formatted(result))
        print(
            json.dumps(
                {
                    "deno_blobs": result["deno"]["blob_count"],
                    "v8_blobs": result["v8"]["blob_count"],
                    "rust_files": result["rust"]["archive_file_count"],
                    "manifest": PARENT_INSPECTION_PATH.as_posix(),
                },
                indent=2,
            )
        )
        return 0
    if args.command == "generate-manifests":
        manifest, notice = generate_manifests()
        DEFAULT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_MANIFEST.write_bytes(formatted(manifest))
        DEFAULT_NOTICE_MANIFEST.write_bytes(formatted(notice))
        DEFAULT_NOTICE_TEXT.write_bytes(render_notice_text(notice))
        print(f"manifest_sha256={sha256_file(DEFAULT_MANIFEST)}")
        print(f"notice_sha256={sha256_file(DEFAULT_NOTICE_MANIFEST)}")
        print(f"notice_text_sha256={sha256_file(DEFAULT_NOTICE_TEXT)}")
        return 0
    if args.command == "generate-review-manifest":
        review_manifest, _sources = build_review_manifest()
        DEFAULT_REVIEW_MANIFEST.write_bytes(formatted(review_manifest))
        print(f"review_manifest_sha256={sha256_file(DEFAULT_REVIEW_MANIFEST)}")
        print(json.dumps(review_manifest["payload_inventory"], indent=2))
        return 0
    if args.command == "verify-evidence":
        manifest, notice = load_manifest()
        verify_evidence(manifest, notice, source_root)
        print(
            "Deno D11H evidence: PASS (source technically complete; "
            "15 upstream license texts pending; canonical references complete)"
        )
        return 0
    if args.command == "stage-review-bundle":
        review_manifest = load_review_manifest()
        rebuilt, sources = build_review_manifest()
        require(
            canonical(rebuilt) == canonical(review_manifest),
            "review manifest/input set diverge",
        )
        result = create_review_staging(review_manifest, sources, args.staging)
        print(
            json.dumps(
                {key: value for key, value in result.items() if key != "entries"},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "verify-staging":
        result = verify_review_staging(load_review_manifest(), args.staging)
        print(
            json.dumps(
                {key: value for key, value in result.items() if key != "entries"},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "assemble":
        result = assemble_review_bundle(
            load_review_manifest(), args.staging, args.output
        )
        result["bundle"] = args.output.as_posix()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-bundle":
        result = verify_review_bundle(load_review_manifest(), args.bundle)
        result["bundle"] = args.bundle.as_posix()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-determinism":
        result = compare_review_bundles(args.first, args.second)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "resolve":
        verify_wave_a(source_root)
        result = CargoResolver(source_root, acquire_index=args.acquire_index).resolve()
        RESOLUTION_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESOLUTION_PATH.write_bytes(formatted(result))
        print(json.dumps(result["counts"], indent=2))
        print(f"resolution={RESOLUTION_PATH}")
        return 0
    resolution = json.loads(RESOLUTION_PATH.read_text(encoding="utf-8"))
    if args.command == "acquire-crates":
        acquisitions = acquire_crates(resolution)
        ACQUISITION_PATH.write_bytes(formatted(acquisitions))
        print(
            json.dumps(
                {
                    "acquired_or_existing": len(acquisitions["acquired"]),
                    "reused_from_exact_parent": len(acquisitions["reused"]),
                    "manifest": ACQUISITION_PATH.as_posix(),
                },
                indent=2,
            )
        )
        return 0
    acquisitions = json.loads(ACQUISITION_PATH.read_text(encoding="utf-8"))
    final_resolution, inspection = inspect_material_crates(
        resolution, acquisitions, source_root
    )
    FINAL_RESOLUTION_PATH.write_bytes(formatted(final_resolution))
    CRATE_INSPECTION_PATH.write_bytes(formatted(inspection))
    print(json.dumps(final_resolution["counts"], indent=2))
    print(json.dumps(inspection["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
