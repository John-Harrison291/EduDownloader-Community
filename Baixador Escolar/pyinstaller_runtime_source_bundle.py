"""Closure offline e source-only do PyInstaller material no candidate 0.9.5."""

from __future__ import annotations

import argparse
import hashlib
import json
import marshal
import posixpath
import re
import struct
import tarfile
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_MANIFEST = Path(
    "docs/compliance/python/PYINSTALLER_RUNTIME_SOURCE_PROVENANCE.json"
)
WORK_ROOT = Path("build-compliance-pyinstaller-runtime")
DEFAULT_STAGING = WORK_ROOT / "staging"
BUNDLE_ROOT = "EduDownloader-ThirdParty-Source-PyInstaller-6.21.0"
DEFAULT_BUNDLE = WORK_ROOT / "bundles" / f"{BUNDLE_ROOT}-COMPLETE.zip"
FROZEN_MANIFEST = Path("docs/compliance/build/FROZEN_CANDIDATE_COMPOSITION.json")
FROZEN_ROOT = Path("build-community-candidate-0.9.5/dist/EduDownloader-Portable")
OFFICIAL_MANIFEST_SHA256 = (
    "2AA4AE06C1E13014DC610533C9AD459A385811EE07282E7AB3DABC0A9660B1AF"
)
PARENTS = {
    "pyinstaller": {
        "version": "6.21.0",
        "preservation": "REUSED_EXISTING_SOURCE",
        "commit": "1cda34561015a90b6e1ae31dc89703799adaf13e",
        "tree": "b1e4e629352ba8710e0ffb8449e1b959877005c5",
        "archive_sha256": "190A36D44D2F024168F94DE11C0CDD37DFC37997F7F2D07CD16E2649551D2529",
        "archive_size": 3518947,
        "input_path": "compliance_artifacts/yt-dlp/2026.07.04/sources/lot-1/pyinstaller-6.21.0.tar.gz",
        "prefix": "pyinstaller-6.21.0",
    },
    "hooks-contrib": {
        "version": "2026.6",
        "preservation": "PRESERVED_NEW",
        "commit": "791432e2a150b2282f8048df71c9ec3665aabb48",
        "tree": "518f9bd4216346a782984b741a91081a4a3cc2fa",
        "archive_sha256": "BEF5002C32F4F50BD55B005DA12CFF64ECA8783E7EAF86A06A62410164BAB725",
        "archive_size": 173354,
        "input_path": "build-compliance-pyinstaller-runtime/inputs/pyinstaller_hooks_contrib-2026.6.tar.gz",
        "prefix": "pyinstaller_hooks_contrib-2026.6",
    },
}
LICENSES = {
    "pyinstaller/COPYING.txt": "DCF75FDB959DB1E3B41C0F8505069D2ECE781B5EC6B3D0A4D30975CFC6580245",
    "pyinstaller/bootloader/zlib/LICENSE": "E32FF4E00D9D94930537635291DA39E7E612703334BF6FDE8C7F1686FE8A45A2",
    "hooks-contrib/LICENSE": "91D0BAAFF00773038E72C0A1FC9D5D2D38706B7A2B9C04F34296608F931B9CD0",
}
EXCEPTION_SHA256 = "711C0CD077A0985A5C35A1464D604FBAC42EAACB8B4E42C17C4896C521514D56"
RUNTIME_SOURCES = {
    **{
        name: f"pyinstaller/PyInstaller/loader/{name}.py"
        for name in (
            "pyimod01_archive",
            "pyimod02_importers",
            "pyimod03_ctypes",
            "pyimod04_pywin32",
            "pyiboot01_bootstrap",
        )
    },
    "pyi_rth_inspect": "pyinstaller/PyInstaller/hooks/rthooks/pyi_rth_inspect.py",
    "pyi_rth__tkinter": "pyinstaller/PyInstaller/hooks/rthooks/pyi_rth__tkinter.py",
    "pyi_rth_cryptography_openssl": "hooks-contrib/_pyinstaller_hooks_contrib/rthooks/pyi_rth_cryptography_openssl.py",
}
ICON = "pyinstaller/PyInstaller/bootloader/images/icon-windowed.ico"
ICON_SHA256 = "168DB1B8A7C62FA2AB92C1210185D145923F31C1BE23FDED42D9420F48B98392"
EXE_SHA256 = "2A6B49C2B67D596FFC6445D7D7725B219E80E34D5EC2C112ECA814FCE5FE367B"
PROHIBITED_SUFFIXES = {
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".pyd",
    ".pyc",
    ".pyo",
    ".whl",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".dpapi",
    ".edulic",
    ".edureq",
    ".zip",
    ".gz",
    ".tgz",
    ".xz",
    ".bz2",
    ".7z",
}
MAGICS = (b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 25 * 1024 * 1024


class SourceBundleError(ValueError):
    """Falha fechada na identidade ou no escopo da closure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceBundleError(message)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def formatted(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def safe_name(name: str) -> str:
    require(isinstance(name, str) and bool(name), "Path ausente")
    path = PurePosixPath(name)
    require(
        not path.is_absolute()
        and "\\" not in name
        and ":" not in name
        and all(p not in ("", ".", "..") for p in name.split("/"))
        and all(not p.endswith((" ", ".")) for p in path.parts),
        "Path inseguro",
    )
    require(not any(ord(c) < 32 for c in name), "Controle em path")
    return name


def check_payload(name: str, data: bytes) -> None:
    safe_name(name)
    require(
        PurePosixPath(name).suffix.lower() not in PROHIBITED_SUFFIXES,
        "Payload proibido",
    )
    require(not data.startswith(MAGICS), "Executável incorporado proibido")
    require(len(data) <= MAX_FILE, "Payload excede limite")
    require(
        not any(
            p.lower() in {"activation_issuer", "wheelhouse", "backups"}
            for p in PurePosixPath(name).parts
        ),
        "Material administrativo proibido",
    )


def records(files: dict[str, bytes]) -> list[dict[str, Any]]:
    return [
        {"path": p, "size": len(b), "sha256": sha256(b)}
        for p, b in sorted(files.items())
    ]


def inventory(files: dict[str, bytes]) -> dict[str, Any]:
    entries = records(files)
    return {
        "file_count": len(entries),
        "total_size": sum(x["size"] for x in entries),
        "inventory_sha256": sha256(canonical(entries)),
        "files": entries,
    }


def project_archive(
    path: Path, parent: dict[str, Any]
) -> tuple[dict[str, bytes], list[dict[str, str]]]:
    """Lê o input pinado; não extrai links nem inclui binários/fixtures binárias."""
    require(path.is_file() and not path.is_symlink(), "Source input ausente/inseguro")
    raw = path.read_bytes()
    require(len(raw) == parent["archive_size"], "Source archive size diverge")
    require(sha256(raw) == parent["archive_sha256"], "Source archive hash diverge")
    files: dict[str, bytes] = {}
    links: dict[str, str] = {}
    excluded = []
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        require(len(members) < 10000, "Archive excede limite")
        require(
            sum(m.size for m in members) <= MAX_TOTAL, "Archive expandido excede limite"
        )
        seen: set[str] = set()
        for member in members:
            name = safe_name(member.name.rstrip("/"))
            require(
                name == parent["prefix"] or name.startswith(parent["prefix"] + "/"),
                "Raiz do source diverge",
            )
            if member.isdir():
                continue
            rel = safe_name(name[len(parent["prefix"]) + 1 :])
            require(rel.casefold() not in seen, "Source path duplicado")
            seen.add(rel.casefold())
            if member.issym():
                target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(rel), member.linkname)
                )
                links[rel] = safe_name(target)
                continue
            require(
                member.isfile() and member.size <= MAX_FILE,
                "Tipo/tamanho de source inválido",
            )
            stream = archive.extractfile(member)
            require(stream is not None, "Source ilegível")
            data = stream.read()
            prebuilt = rel.startswith("PyInstaller/bootloader/") and not rel.startswith(
                "PyInstaller/bootloader/images/"
            )
            forbidden = PurePosixPath(
                rel
            ).suffix.lower() in PROHIBITED_SUFFIXES or data.startswith(MAGICS)
            if prebuilt or forbidden:
                require(
                    prebuilt or rel.startswith("tests/"),
                    "Payload inesperado fora das exclusões auditadas",
                )
                excluded.append(
                    {
                        "path": rel,
                        "sha256": sha256(data),
                        "reason": "PREBUILT_BOOTLOADER"
                        if prebuilt
                        else "UPSTREAM_NON_RUNTIME_TEST_FIXTURE",
                    }
                )
            else:
                check_payload(rel, data)
                files[rel] = data
        for name, target in links.items():
            require(target in files, "Link não resolvido dentro do parent")
            files[name] = files[target]
    return files, sorted(excluded, key=lambda x: x["path"])


def validate_structure(manifest: dict[str, Any]) -> None:
    require(manifest.get("schema_version") == 1, "Schema inválido")
    require(
        manifest.get("parents") == PARENTS,
        "Identidade/commit/tree/reuso dos parents diverge",
    )
    require(
        manifest.get("counts")
        == {
            "logical_parents": 2,
            "new_acquisitions": 1,
            "reused": 1,
            "transitive_parents": 0,
            "pending": 0,
            "blocked": 0,
            "unknown": 0,
        },
        "Contagem/source gap incompatível com A",
    )
    require(
        manifest.get("status")
        == {
            "source_correspondence": "A",
            "bundle": "COMPLETE_CANDIDATE_FOR_LEGAL_REVIEW",
            "candidate_notice_delivery": "PENDING_FIX",
            "legal_review": "PENDING",
            "build_reproducibility": "SEPARATE_PENDING_REVIEW",
            "microsoft": "SEPARATE_P3_REVIEW",
        },
        "Classificação/gate inválido",
    )
    require(
        manifest.get("runtime_sources") == RUNTIME_SOURCES,
        "Cobertura runtime incompleta",
    )
    require(manifest.get("licenses") == LICENSES, "Licenças divergentes")
    require(
        manifest.get("materiality", {}).get("hooks-contrib")
        == "DISTRIBUTED_RUNTIME_HOOK",
        "hooks-contrib não é somente build",
    )
    require(
        manifest["materiality"].get("analysis_hooks") == "BUILD_ONLY_NOT_DISTRIBUTED",
        "Analysis hooks não são runtime",
    )
    entries = manifest["staging"]["files"]
    names = [safe_name(e["path"]) for e in entries]
    require(
        names == sorted(set(names))
        and len(names) == len({p.casefold() for p in names}),
        "Inventário duplicado/desordenado",
    )
    required = {"sources/" + p for p in [*RUNTIME_SOURCES.values(), *LICENSES, ICON]}
    required |= {
        f"sources/pyinstaller/bootloader/{p}"
        for p in (
            "wscript",
            "src/main.c",
            "src/pyi_archive.c",
            "zlib/inflate.c",
            "zlib/inftrees.c",
            "zlib/crc32.c",
            "zlib/crc32.h",
            "zlib/inffixed.h",
            "zlib/README",
        )
    }
    require(required <= set(names), "Material source obrigatório ausente")
    require(
        sha256(canonical(entries)) == manifest["staging"]["inventory_sha256"],
        "Inventário não canônico",
    )
    require(
        manifest["staging"]["file_count"] == len(entries), "Contagem de staging diverge"
    )
    require(
        manifest["staging"]["total_size"] == sum(e["size"] for e in entries),
        "Tamanho staging diverge",
    )
    require(
        not re.search(r"\b[A-Za-z]:[\\/]", formatted(manifest).decode()),
        "Path pessoal no manifesto",
    )


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    raw = path.read_bytes()
    require(
        sha256(raw) == OFFICIAL_MANIFEST_SHA256, "Manifesto diverge da baseline pinada"
    )
    manifest = json.loads(raw)
    require(raw == formatted(manifest), "JSON não canônico")
    validate_structure(manifest)
    return manifest


def read_staging(staging: Path) -> dict[str, bytes]:
    require(staging.is_dir() and not staging.is_symlink(), "Staging ausente/inseguro")
    files = {}
    for path in staging.rglob("*"):
        require(not path.is_symlink() and not path.is_junction(), "Link no staging")
        if path.is_file():
            require(path.stat().st_size <= MAX_FILE, "Arquivo excede limite")
            name = path.relative_to(staging).as_posix()
            data = path.read_bytes()
            check_payload(name, data)
            files[name] = data
    require(sum(map(len, files.values())) <= MAX_TOTAL, "Staging excede limite")
    return files


def verify_payload(manifest: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    """Inventário esperado é externo ao ZIP, não confiado ao próprio bundle."""
    validate_structure(manifest)
    for name, data in files.items():
        check_payload(name, data)
    result = inventory(files)
    require(
        result == manifest["staging"],
        "Conteúdo/arquivo inesperado ou ausente no staging",
    )
    for name, digest in LICENSES.items():
        require(sha256(files["sources/" + name]) == digest, "License hash diverge")
    copying = files["sources/pyinstaller/COPYING.txt"].replace(b"\r\n", b"\n")
    start = copying.index(b"Bootloader Exception")
    end = copying.index(b"Run-time Hooks", start)
    require(
        sha256(copying[start:end]) == EXCEPTION_SHA256, "Bootloader exception diverge"
    )
    require(sha256(files["sources/" + ICON]) == ICON_SHA256, "Icon source diverge")
    for parent_id, parent in PARENTS.items():
        tree = json.loads(files[f"metadata/{parent_id}/tree.json"])
        commit = json.loads(files[f"metadata/{parent_id}/commit.json"])
        require(
            tree["sha"] == parent["tree"] and not tree["truncated"],
            "Tree metadata diverge",
        )
        require(
            commit["sha"] == parent["commit"]
            and commit["tree"]["sha"] == parent["tree"],
            "Commit metadata diverge",
        )
        for entry in manifest["source_comparison"][parent_id]:
            data = files[f"sources/{parent_id}/{entry['path']}"]
            if entry["normalize_lf"]:
                data = data.replace(b"\r\n", b"\n")
            blob = hashlib.sha1(
                b"blob " + str(len(data)).encode() + b"\0" + data
            ).hexdigest()
            require(blob == entry["git_blob"], "Source blob não corresponde ao commit")
            require(
                any(
                    x["path"] == entry["path"] and x["sha"] == blob
                    for x in tree["tree"]
                ),
                "Blob ausente da tree",
            )
    return {k: v for k, v in result.items() if k != "files"}


def verify_staging(manifest: dict[str, Any], staging: Path) -> dict[str, Any]:
    return verify_payload(manifest, read_staging(staging))


def verify_inputs(manifest: dict[str, Any], root: Path, staging: Path) -> None:
    """Revalida os dois archives originais sem copiá-los para o bundle."""
    for parent_id, parent in PARENTS.items():
        files, excluded = project_archive(root / parent["input_path"], parent)
        require(
            excluded == manifest["excluded_input_members"][parent_id],
            "Exclusões do input divergem",
        )
        actual = read_staging(staging / "sources" / parent_id)
        require(files == actual, "Projeção source diverge do archive preservado")


def archive_entries(exe: bytes) -> dict[str, bytes]:
    pos = exe.rfind(b"MEI\x0c\x0b\x0a\x0b\x0e")
    require(pos >= 0, "CArchive ausente")
    _, total, offset, length, _, _ = struct.unpack_from("!8sIIII64s", exe, pos)
    start = pos + 88 - total
    cursor = start + offset
    result = {}
    while cursor < start + offset + length:
        size, at, stored, _, compressed, kind = struct.unpack_from(
            "!IIIIBc", exe, cursor
        )
        require(size >= 18, "TOC inválida")
        name = exe[cursor + 18 : cursor + size].rstrip(b"\0").decode()
        if kind != b"o":
            data = exe[start + at : start + at + stored]
            result[name] = zlib.decompress(data) if compressed else data
        cursor += size
    return result


def verify_frozen(manifest: dict[str, Any], staging: Path, root: Path) -> None:
    """Somente leitura: não importa nem executa código do candidate."""
    frozen_bytes = (root / FROZEN_MANIFEST).read_bytes()
    require(
        sha256(frozen_bytes) == manifest["candidate"]["manifest_sha256"],
        "Frozen manifest diverge",
    )
    exe = (root / FROZEN_ROOT / "EduDownloader.exe").read_bytes()
    require(sha256(exe) == EXE_SHA256, "Frozen EXE diverge")
    entries = archive_entries(exe)
    require(
        sorted(entries) == manifest["candidate"]["carchive_entries"],
        "Material CArchive diverge",
    )
    for name, source in RUNTIME_SOURCES.items():
        frozen_code = marshal.loads(entries[name])
        source_code = compile(
            (staging / "sources" / source).read_bytes(),
            frozen_code.co_filename,
            "exec",
            dont_inherit=True,
            optimize=0,
        )
        require(
            source_code == frozen_code,
            "Source/runtime hook não corresponde ao CArchive",
        )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def bundle_files(manifest: dict[str, Any], files: dict[str, bytes]) -> dict[str, bytes]:
    result = {f"{BUNDLE_ROOT}/{p}": b for p, b in files.items()}
    result[f"{BUNDLE_ROOT}/SOURCE_PROVENANCE.json"] = formatted(manifest)
    result[f"{BUNDLE_ROOT}/SOURCE-BUNDLE-INVENTORY.json"] = formatted(inventory(result))
    return result


def assemble(manifest: dict[str, Any], staging: Path, output: Path) -> dict[str, Any]:
    files = read_staging(staging)
    verify_payload(manifest, files)
    require(not output.exists(), "Saída já existe; não sobrescrever")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = bundle_files(manifest, files)
    with zipfile.ZipFile(
        output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, data in sorted(payload.items()):
            archive.writestr(_zip_info(name), data, compresslevel=9)
    return verify_bundle(manifest, output)


def verify_bundle(manifest: dict[str, Any], path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        require(
            len(infos) == len({i.filename.casefold() for i in infos}), "ZIP duplicado"
        )
        require(sum(i.file_size for i in infos) <= MAX_TOTAL, "ZIP excede limite")
        for item in infos:
            safe_name(item.filename)
            require(
                item.date_time == (1980, 1, 1, 0, 0, 0)
                and item.external_attr == 0o100644 << 16,
                "ZIP metadata inválida",
            )
        payload = {i.filename: archive.read(i) for i in infos}
    prefix = BUNDLE_ROOT + "/"
    require(all(p.startswith(prefix) for p in payload), "Raiz ZIP inválida")
    extras = {
        prefix + "SOURCE_PROVENANCE.json",
        prefix + "SOURCE-BUNDLE-INVENTORY.json",
    }
    files = {p[len(prefix) :]: b for p, b in payload.items() if p not in extras}
    verify_payload(manifest, files)
    require(
        payload == bundle_files(manifest, files), "Provenance/inventário ZIP diverge"
    )
    result = inventory(payload)
    return {
        "file_count": result["file_count"],
        "total_size": result["total_size"],
        "inventory_sha256": result["inventory_sha256"],
        "zip_size": path.stat().st_size,
        "zip_sha256": sha256(path.read_bytes()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("verify-staging", "assemble", "verify-bundle", "verify-frozen"),
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "verify-bundle":
            report = verify_bundle(manifest, args.bundle)
        else:
            verify_inputs(manifest, Path("."), args.staging)
            report = verify_staging(manifest, args.staging)
            if args.command == "assemble":
                report = assemble(manifest, args.staging, args.bundle)
            elif args.command == "verify-frozen":
                verify_frozen(manifest, args.staging, Path("."))
        print(json.dumps({"status": "PASS", **report}, sort_keys=True))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        print(f"FAIL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
