"""D6: verificação offline da closure material CFFI/cryptography Windows x64.

Não adquire, instala, importa ou executa código upstream/candidate. O manifesto
pinado é a autoridade externa ao staging/ZIP; inventários internos não bastam.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

from pyinstaller_runtime_source_bundle import (
    _zip_info,
    canonical,
    formatted,
    inventory,
    require,
    safe_name,
    sha256,
)
from pyinstaller_runtime_source_bundle import SourceBundleError as SourceBundleError

DEFAULT_MANIFEST = Path(
    "docs/compliance/python/CRYPTOGRAPHY_CFFI_RUNTIME_SOURCE_PROVENANCE.json"
)
WORK_ROOT = Path("build-compliance-cryptography-cffi")
DEFAULT_STAGING = WORK_ROOT / "staging-source-only"
BUNDLE_ROOT = "EduDownloader-ThirdParty-Source-Cryptography-CFFI"
DEFAULT_BUNDLE = WORK_ROOT / "bundles" / f"{BUNDLE_ROOT}-COMPLETE.zip"
OFFICIAL_MANIFEST_SHA256 = (
    "0F21F58A83A63182F0D3625194591AB6EDE799736CB1EABA0A019D9A9BFEBFFE"
)
RUST_LIB = "rust-src/lib/rustlib/src/rust/library/"
LOCK_SHA = "104F567EE229A7D3D27189D404E276BE705BF2CA384753DB6669FCF706591B1D"
LIBFFI_LICENSE_SHA = "40A537C7D74BAEED3831304E92D1664ABABD7AD8A3CF29F11A257C9E47145248"
RUNTIME = frozenset(
    "asn1 base64 bitflags cfg-if foreign-types foreign-types-shared itoa libc once_cell openssl openssl-sys pem pyo3 pyo3-ffi self_cell".split()
)
CODEGEN = frozenset(
    "asn1_derive openssl-macros pyo3-macros pyo3-macros-backend".split()
)
BUILD_ONLY = frozenset(
    "cc find-msvc-tools pkg-config pyo3-build-config shlex target-lexicon vcpkg heck proc-macro2 quote syn unicode-ident".split()
)
LOCAL = frozenset(
    "cryptography-cffi cryptography-crypto cryptography-keepalive cryptography-key-parsing cryptography-openssl cryptography-rust cryptography-x509 cryptography-x509-verification".split()
)
EXPECTED_STATUS = {
    "open_source_correspondence": "A",
    "bundle": "COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW",
    "notice_identity": "RESOLVED",
    "notice_delivery": "PENDING_FIX",
    "legal_review": "PENDING",
    "microsoft": "P3_PENDING_REVIEW",
    "static_crt_object_composition": "UNKNOWN",
    "build_reproducibility": "P2_SEPARATE_PENDING",
}
REQUIRED = {
    "cffi": [
        "src/c/_cffi_backend.c",
        "setup.py",
        "MANIFEST.in",
        "LICENSE",
        *[
            "src/c/libffi_x86_x64/" + n
            for n in (
                "ffi.c",
                "ffi.h",
                "ffi_common.h",
                "fficonfig.h",
                "ffitarget.h",
                "prep_cif.c",
                "types.c",
                "win32.c",
                "win64.asm",
            )
        ],
    ],
    "cffi-generator": ["src/cffi/_cffi_include.h", "src/cffi/recompiler.py", "LICENSE"],
    "cryptography": [
        "Cargo.lock",
        "Cargo.toml",
        "pyproject.toml",
        "src/rust/cryptography-cffi/build.rs",
        "src/_cffi_src/build_openssl.py",
        "LICENSE",
        "LICENSE.APACHE",
        "LICENSE.BSD",
    ],
    "openssl-source": [
        "Configure",
        "LICENSE.txt",
        "crypto/evp/evp_lib.c",
        "include/openssl/opensslv.h.in",
        "Configurations/10-main.conf",
    ],
    "rust": [
        "LICENSE-MIT",
        "LICENSE-APACHE",
        "COPYRIGHT",
        *[
            RUST_LIB + n
            for n in (
                "Cargo.lock",
                "core/src/lib.rs",
                "alloc/src/lib.rs",
                "std/src/lib.rs",
                "std/src/sys/pal/windows/mod.rs",
                "panic_unwind/src/seh.rs",
                "compiler-builtins/compiler-builtins/Cargo.toml",
                "compiler-builtins/compiler-builtins/src/lib.rs",
                "compiler-builtins/LICENSE.txt",
                "backtrace/src/lib.rs",
                "backtrace/LICENSE-MIT",
                "std_detect/src/lib.rs",
                "stdarch/crates/core_arch/src/lib.rs",
                "windows_link/src/lib.rs",
            )
        ],
    ],
}
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 400 * 1024 * 1024
PROHIBITED = frozenset(
    ".exe .dll .pyd .so .dylib .whl .pyc .pyo .obj .a .lib .pem .key .der .p12 .pfx .dpapi .edulic .edureq .gz .xz .zip .crate .bz2 .7z".split()
)
PRIVATE_BLOCK = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*(?:PRIVATE KEY)-----")
# These exact upstream source files contain format delimiters/documentation;
# pkey_ctx.rs and pem/lib.rs also embed PUBLIC upstream test vectors. Removing
# their whole files would remove material source. No operator key is allowed.
PUBLIC_UPSTREAM_SOURCE = {
    "sources/cryptography/src/cryptography/hazmat/primitives/serialization/ssh.py": "1D5E99A888EA34D68D50BE8CE2043234926D67BE44B22499B3ACB175DA81AD62",
    "sources/openssl/src/dsa.rs": "DAAE069D1AC7E5BDE19C5DFE5590249E74ECB8C95CAA28EFD2058872583B3523",
    "sources/openssl/src/ec.rs": "816BA627279B1B3AA8B8EB6C537C1119A939671AD95EFBF83C5BB448372BF52B",
    "sources/openssl/src/pkey.rs": "1F32BE54D88EE49AD3DB4DEA4415F2CA8D508AC4DE635DBAB83957D5B414F16C",
    "sources/openssl/src/pkey_ctx.rs": "F5A2F708AFDD360135CAA7C7984D639003DEC6B012534B5C538FC9CA452AAAAA",
    "sources/openssl/src/rsa.rs": "32A1CE25338B49D50CE1B7DE1C9F7F8B82FFD246328E5A2B672A469352BCAC85",
    "sources/pem/src/lib.rs": "BE6A429443A8687241F20F9BD2511614B9B8A150E52ED89E445960FBD2AE1906",
}


def prohibited(name: str, data: bytes) -> bool:
    return (
        PurePosixPath(name).suffix.lower() in PROHIBITED
        or data.startswith((b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe"))
        or (
            PRIVATE_BLOCK.search(data) is not None
            and PUBLIC_UPSTREAM_SOURCE.get(name) != sha256(data)
        )
    )


def check_payload(name: str, data: bytes) -> None:
    safe_name(name)
    require(len(data) <= MAX_FILE, "Arquivo excede limite")
    require(not prohibited(name, data), "Binário/private payload proibido")
    require(
        not any(
            p.lower()
            in {"activation_issuer", "wheelhouse", "backups", "activation.dat"}
            for p in PurePosixPath(name).parts
        ),
        "Material administrativo proibido",
    )


def archive_files(path: Path, parent: dict) -> dict[str, bytes]:
    require(path.is_file() and not path.is_symlink(), "Source input ausente/inseguro")
    raw = path.read_bytes()
    require(
        len(raw) == parent["archive_size"] and sha256(raw) == parent["archive_sha256"],
        "Source archive hash/size diverge",
    )
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
        members = archive.getmembers()
        require(
            len(members) <= 30000 and sum(m.size for m in members) <= MAX_TOTAL,
            "Archive excede limites",
        )
        seen = set()
        for m in members:
            name = safe_name(m.name.rstrip("/"))
            if m.isdir():
                continue
            require(
                m.isfile() and m.size <= MAX_FILE, "Tipo/tamanho de membro inválido"
            )
            require(name.casefold() not in seen, "Membro duplicado")
            seen.add(name.casefold())
            prefix = parent["prefix"] + "/"
            if parent.get("vendored_reuse"):
                if not name.startswith(prefix):
                    continue
            else:
                require(name.startswith(prefix), "Raiz do archive diverge")
            stream = archive.extractfile(m)
            require(stream is not None, "Membro ilegível")
            result[safe_name(name[len(prefix) :])] = stream.read()
    require(bool(result), "Source vazio")
    return result


def verify_crate(files: dict[str, bytes], parent: dict) -> None:
    require("Cargo.toml" in files, "Cargo.toml ausente")
    package = tomllib.loads(files["Cargo.toml"].decode())["package"]
    require(
        package["name"] == parent["name"] and package["version"] == parent["version"],
        "Crate name/version diverge",
    )
    require(
        package.get("license") == parent["license_expression"], "Crate licença diverge"
    )
    require(any(p.startswith("src/") for p in files), "Crate source ausente")
    require(
        any(PurePosixPath(p).name.startswith(("LICENSE", "COPYING")) for p in files),
        "Crate licença ausente",
    )
    if parent.get("vendored_reuse"):
        checks = json.loads(files[".cargo-checksum.json"])
        require(
            checks["package"].upper() == parent["crate_checksum"],
            "Reuso package checksum diverge",
        )
        require(
            set(files) == set(checks["files"]) | {".cargo-checksum.json"},
            "Reuso file set diverge",
        )
        for name, digest in checks["files"].items():
            require(sha256(files[name]) == digest.upper(), "Reuso conteúdo diverge")


def project_archive(path: Path, parent: dict) -> tuple[dict, list]:
    files = archive_files(path, parent)
    if "crate_checksum" in parent:
        verify_crate(files, parent)
    excluded = []
    output = {}
    for name, data in files.items():
        scoped = f"sources/{parent.get('id', parent['name'])}/{name}"
        if prohibited(scoped, data):
            # Raw archive is immutable and hash-pinned. Exclusions never license
            # arbitrary payloads: each is recorded in the pinned manifest.
            excluded.append(
                {
                    "path": name,
                    "sha256": sha256(data),
                    "reason": "UPSTREAM_PREBUILT_OR_NON_RUNTIME_FIXTURE",
                }
            )
        else:
            check_payload(scoped, data)
            output[name] = data
    return output, sorted(excluded, key=lambda e: e["path"])


def validate_structure(manifest: dict) -> None:
    require(manifest.get("schema_version") == 1, "Schema inválido")
    require(manifest.get("status") == EXPECTED_STATUS, "Classificação/gate diverge")
    require(
        manifest.get("counts")
        == {
            "logical_parents": 26,
            "new_acquisitions": 23,
            "reuses": 3,
            "pending": 0,
            "blocked": 0,
            "open_source_unknown": 0,
        },
        "Source gap/contagem incompatível com A",
    )
    parents = manifest["parents"]
    require(
        set(parents)
        == set(REQUIRED) | RUNTIME | CODEGEN | {"hashbrown", "rustc-demangle"},
        "Parent material ausente/indevido",
    )
    require(
        {k for k, v in parents.items() if v["preservation"] == "REUSED_EXISTING_SOURCE"}
        == {"cffi-generator", "cfg-if", "rustc-demangle"},
        "Reuso diverge",
    )
    require(
        {k for k, v in parents.items() if v["role"] == "MATERIAL_RUNTIME"} == RUNTIME,
        "Runtime crates divergem",
    )
    require(
        {k for k, v in parents.items() if v["role"] == "MATERIAL_CODEGEN"} == CODEGEN,
        "Codegen crates divergem",
    )
    require(
        set(manifest["build_only"]) == BUILD_ONLY
        and manifest["target_not_applicable"] == {"portable-atomic": "1.13.1"},
        "Exclusões de materialidade divergem",
    )
    require(set(manifest["local_crates"]) == LOCAL, "Crates locais incompletos")
    require(
        manifest["generated_source_inputs"]
        == {
            "consumer": "_rust.pyd",
            "parents": ["cffi-generator", "cryptography", "openssl-source"],
            "outputs_not_separate_parents": [
                "_openssl.c",
                "_openssl.a",
                "generated constants",
                "generated bindings",
            ],
        },
        "Provenance de geração ausente/diverge",
    )
    entries = manifest["staging"]["files"]
    names = [safe_name(e["path"]) for e in entries]
    require(
        names == sorted(set(names))
        and len(names) == len({n.casefold() for n in names}),
        "Inventário duplicado/desordenado",
    )
    required = {f"sources/{key}/{p}" for key, paths in REQUIRED.items() for p in paths}
    required |= {
        f"sources/{key}/Cargo.toml"
        for key in RUNTIME | CODEGEN | {"hashbrown", "rustc-demangle"}
    }
    required |= {f"sources/cryptography/{p}" for p in manifest["local_crates"].values()}
    required |= {
        "metadata/cffi/libffi-LICENSE",
        "metadata/wheel/openssl-sbom.json",
        "metadata/wheel/rust-sbom.json",
    }
    required |= set(PUBLIC_UPSTREAM_SOURCE)
    require(required <= set(names), "Cobertura source/license obrigatória ausente")
    for name in manifest["licenses"]:
        require(name in names, "Texto de licença ausente")
    require(
        sha256(canonical(entries)) == manifest["staging"]["inventory_sha256"],
        "Inventário não canônico",
    )
    require(
        manifest["staging"]["file_count"] == len(entries)
        and manifest["staging"]["total_size"] == sum(e["size"] for e in entries),
        "Totais divergentes",
    )
    require(
        not re.search(r"\b[A-Za-z]:[\\/]", formatted(manifest).decode()),
        "Path pessoal no manifesto",
    )


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    raw = path.read_bytes()
    require(
        sha256(raw) == OFFICIAL_MANIFEST_SHA256,
        "Manifesto diverge da autoridade pinada",
    )
    result = json.loads(raw)
    require(raw == formatted(result), "JSON não canônico")
    validate_structure(result)
    return result


def read_staging(path: Path) -> dict[str, bytes]:
    require(
        path.is_dir() and not path.is_symlink() and not path.is_junction(),
        "Staging ausente/inseguro",
    )
    result = {}
    total = 0
    for p in path.rglob("*"):
        require(not p.is_symlink() and not p.is_junction(), "Link no staging")
        if p.is_file():
            total += p.stat().st_size
            require(
                p.stat().st_size <= MAX_FILE and total <= MAX_TOTAL,
                "Staging excede limites",
            )
            name = p.relative_to(path).as_posix()
            data = p.read_bytes()
            check_payload(name, data)
            result[name] = data
    return result


def verify_graph(manifest: dict, files: dict[str, bytes]) -> None:
    raw = files["sources/cryptography/Cargo.lock"]
    require(sha256(raw) == LOCK_SHA, "Cargo.lock diverge")
    packages = {p["name"]: p for p in tomllib.loads(raw.decode())["package"]}
    require(
        set(packages) == RUNTIME | CODEGEN | BUILD_ONLY | LOCAL | {"portable-atomic"},
        "Cargo graph diverge",
    )
    for name in RUNTIME | CODEGEN:
        parent = manifest["parents"][name]
        require(
            packages[name]["version"] == parent["version"]
            and packages[name]["checksum"].upper() == parent["crate_checksum"],
            "Crate checksum/lock diverge",
        )
    std = tomllib.loads(files[f"sources/rust/{RUST_LIB}Cargo.lock"].decode())
    for name in ("cfg-if", "hashbrown", "rustc-demangle"):
        (package,) = [p for p in std["package"] if p["name"] == name]
        parent = manifest["parents"][name]
        require(
            package["version"] == parent["version"]
            and package["checksum"].upper() == parent["crate_checksum"],
            "Std dependency diverge",
        )
    for name, path in manifest["local_crates"].items():
        package = tomllib.loads(files[f"sources/cryptography/{path}"].decode())[
            "package"
        ]
        workspace = tomllib.loads(files["sources/cryptography/Cargo.toml"].decode())[
            "workspace"
        ]["package"]
        require(
            package["name"] == name
            and package["version"] == {"workspace": True}
            and workspace["version"] == "0.49.0",
            "Local crate diverge",
        )
    builtins = tomllib.loads(
        files[
            f"sources/rust/{RUST_LIB}compiler-builtins/compiler-builtins/Cargo.toml"
        ].decode()
    )["package"]
    require(builtins["version"] == "0.1.160", "Compiler builtins diverge")
    pyo = files["sources/pyo3/Cargo.toml"].decode()
    require(
        'not(target_has_atomic = "64")' in pyo and "portable-atomic" in pyo,
        "Target exclusion sem evidência",
    )
    sbom = json.loads(files["metadata/wheel/rust-sbom.json"])
    identities = {
        (c["name"], c["version"])
        for c in [*sbom["components"], sbom["metadata"]["component"]]
    }
    require(
        identities == {(p["name"], p["version"]) for p in packages.values()},
        "SBOM/Cargo graph diverge",
    )
    require(
        manifest["parents"]["openssl-source"]["archive_sha256"].lower().encode()
        in files["metadata/wheel/openssl-sbom.json"].lower(),
        "OpenSSL SBOM/hash diverge",
    )


def verify_payload(manifest: dict, files: dict[str, bytes]) -> dict:
    validate_structure(manifest)
    for name, data in files.items():
        check_payload(name, data)
    require(
        inventory(files) == manifest["staging"],
        "Inventário não corresponde: ausente/alterado/indevido",
    )
    for name, digest in manifest["licenses"].items():
        require(sha256(files[name]) == digest, "License hash diverge")
    require(
        sha256(files["metadata/cffi/libffi-LICENSE"]) == LIBFFI_LICENSE_SHA,
        "Libffi license diverge",
    )
    verify_upstream(manifest, files)
    verify_graph(manifest, files)
    return {k: v for k, v in manifest["staging"].items() if k != "files"}


def verify_upstream(manifest: dict, files: dict[str, bytes]) -> None:
    """Vínculo ref -> commit -> tree e source blobs; nunca executa upstream."""
    for key in REQUIRED:
        parent = manifest["parents"][key]
        meta = "openssl" if key == "openssl-source" else key
        tree = json.loads(files[f"metadata/{meta}/tree.json"])
        commit = json.loads(files[f"metadata/{meta}/commit.json"])
        ref = json.loads(files[f"metadata/{meta}/ref.json"])
        require(
            commit["sha"] == parent["commit"]
            and commit["tree"]["sha"] == parent["tree"] == tree["sha"]
            and not tree["truncated"],
            "Git identity diverge",
        )
        target = ref["object"]
        if target["type"] == "tag":
            tag = json.loads(files[f"metadata/{meta}/tag.json"])
            require(tag["sha"] == target["sha"], "Tag object diverge")
            target = tag["object"]
        require(
            ref["ref"] == "refs/tags/" + parent["tag"]
            and target["sha"] == parent["commit"],
            "Tag/commit diverge",
        )
        comparison = manifest["source_comparison"][key]
        matches = list(comparison["matched"])
        if key == "rust":
            library = json.loads(files["metadata/rust/library-tree.json"])
            require(
                next(e for e in tree["tree"] if e["path"] == "library")["sha"]
                == library["sha"],
                "Rust library tree diverge",
            )
            require(
                next(e for e in library["tree"] if e["path"] == "backtrace")["sha"]
                == "28ec93b503bf0410745bc3d571bf3dc1caac3019",
                "Backtrace revision diverge",
            )
            matches.extend(comparison["backtrace"]["matched"])
        for entry in matches:
            name = f"sources/{key}/{entry['path']}"
            if name not in files:
                require(
                    any(
                        e["path"] == entry["path"]
                        for e in manifest["excluded_input_members"][key]
                    ),
                    "Source blob ausente",
                )
                continue
            data = files[name]
            if entry["normalize_lf"]:
                data = data.replace(b"\r\n", b"\n")
            digest = hashlib.sha1(
                b"blob " + str(len(data)).encode() + b"\0" + data
            ).hexdigest()
            require(digest == entry["git_blob"], "Source blob diverge do upstream")


def verify_staging(manifest: dict, staging: Path) -> dict:
    return verify_payload(manifest, read_staging(staging))


def verify_inputs(manifest: dict, root: Path, staging: Path) -> None:
    actual = read_staging(staging)
    for key, parent in manifest["parents"].items():
        files, excluded = project_archive(root / parent["input_path"], parent)
        require(
            excluded == manifest["excluded_input_members"][key],
            "Exclusão não corresponde ao archive",
        )
        prefix = f"sources/{key}/"
        require(
            files
            == {p[len(prefix) :]: b for p, b in actual.items() if p.startswith(prefix)},
            "Source projection diverge",
        )


def verify_frozen(manifest: dict, root: Path) -> None:
    from validate_frozen_candidate import build_file_inventory

    candidate = manifest["candidate"]
    require(
        sha256((root / candidate["manifest_path"]).read_bytes())
        == candidate["manifest_sha256"],
        "Frozen manifest diverge",
    )
    frozen = root / candidate["path"]
    inv = build_file_inventory(frozen)
    require(
        inv["inventory_sha256"] == candidate["inventory_sha256"]
        and inv["file_count"] == 1068
        and inv["total_size_bytes"] == 382736507,
        "Candidate não pristine",
    )
    for entry in manifest["wheels"].values():
        raw = (root / entry["path"]).read_bytes()
        require(sha256(raw) == entry["sha256"], "Wheel diverge")
        native = (frozen / entry["native_path"]).read_bytes()
        require(sha256(native) == entry["native_sha256"], "Native frozen diverge")
        with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
            require(
                wheel.read(entry["wheel_native_member"]) == native,
                "Wheel/native diverge",
            )
    require(
        sha256((root / manifest["wheel_provenance"]["path"]).read_bytes())
        == manifest["wheel_provenance"]["sha256"],
        "Wheel provenance diverge",
    )


def bundle_files(manifest: dict, files: dict) -> dict:
    output = {f"{BUNDLE_ROOT}/{n}": b for n, b in files.items()}
    output[f"{BUNDLE_ROOT}/SOURCE_PROVENANCE.json"] = formatted(manifest)
    output[f"{BUNDLE_ROOT}/SOURCE-BUNDLE-INVENTORY.json"] = formatted(inventory(output))
    return output


def assemble(manifest: dict, staging: Path, output: Path) -> dict:
    files = read_staging(staging)
    verify_payload(manifest, files)
    require(not output.exists(), "Saída existe; não sobrescrever")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, data in sorted(bundle_files(manifest, files).items()):
            archive.writestr(_zip_info(name), data, compresslevel=9)
    return verify_bundle(manifest, output)


def verify_bundle(manifest: dict, path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        require(
            names == sorted(set(names))
            and len(names) == len({n.casefold() for n in names}),
            "ZIP duplicado/desordenado",
        )
        require(sum(i.file_size for i in infos) <= MAX_TOTAL, "ZIP excede limite")
        for i in infos:
            safe_name(i.filename)
            require(
                i.file_size <= MAX_FILE
                and i.date_time == (1980, 1, 1, 0, 0, 0)
                and i.external_attr == 0o100644 << 16,
                "ZIP metadata/tamanho inválido",
            )
        payload = {i.filename: archive.read(i) for i in infos}
    prefix = BUNDLE_ROOT + "/"
    extras = {
        prefix + "SOURCE_PROVENANCE.json",
        prefix + "SOURCE-BUNDLE-INVENTORY.json",
    }
    files = {
        n[len(prefix) :]: b
        for n, b in payload.items()
        if n.startswith(prefix) and n not in extras
    }
    verify_payload(manifest, files)
    require(
        payload == bundle_files(manifest, files),
        "Bundle metadata/conteúdo não corresponde",
    )
    inv = inventory(payload)
    return {
        "entries": inv["file_count"],
        "uncompressed_size": inv["total_size"],
        "inventory_sha256": inv["inventory_sha256"],
        "size": path.stat().st_size,
        "sha256": sha256(path.read_bytes()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "verify-staging",
            "verify-inputs",
            "verify-frozen",
            "assemble",
            "verify-bundle",
        ),
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "verify-staging":
            result = verify_staging(manifest, args.staging)
        elif args.command == "verify-inputs":
            result = verify_inputs(manifest, args.root, args.staging)
        elif args.command == "verify-frozen":
            result = verify_frozen(manifest, args.root)
        elif args.command == "assemble":
            result = assemble(manifest, args.staging, args.bundle)
        else:
            result = verify_bundle(manifest, args.bundle)
        print(json.dumps({"status": "PASS", "result": result}, sort_keys=True))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
