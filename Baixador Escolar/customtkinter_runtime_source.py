"""Offline D8 evidence verification; partial provenance never becomes a bundle."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import marshal
import struct
import tarfile
import zipfile
import zlib
from pathlib import Path

from pyinstaller_runtime_source_bundle import (
    SourceBundleError,
    archive_entries,
    formatted,
    inventory,
    require,
    safe_name,
    sha256,
)


MANIFEST = Path("docs/compliance/python/CUSTOMTKINTER_RUNTIME_SOURCE_PROVENANCE.json")
WORK = Path("build-compliance-customtkinter")
FROZEN = Path("build-community-candidate-0.9.5/dist/EduDownloader-Portable")
WHEEL = Path("build-compliance-wheels/wheelhouse/customtkinter-5.2.2-py3-none-any.whl")
MANIFEST_SHA256 = "1BCB64DC641FEDEF7041D279018EA17EBD2F360D549D4B46DF075D840BB71F8C"
CTK_COMMIT = "a2f0ecd144c6fee931fc06c823a14d9ae0d01bdb"
CTK_TREE = "acaba786f081b183465f61772b18cef182233643"
DIGSBY_COMMIT = "f5fe00244744aa131e07f09348d10563f3d8fa99"
DIGSBY_TREE = "fd48fba90bb227017ac2da9786d59f9b9130aaf0"
SDIST_SHA = "FD8DB3BAFA961C982EE6030DBA80B4C2E25858630756B513986DB19113D8D207"
WHEEL_SHA = "14AD3E7CD3CB3B9EB642B9D4E8711AE80D3F79FB82545AD11258EEFFB2E6B37C"
MIT_SHA = "C973B8600E620159CB0473EB9B08783143E0D9ED5333F350FC933368D94D9E0D"
ROBOTO = {
    "Regular": "319CFF6E7A31F0F2A41C475DCA42890AA5D19FE16017E2290F8C1D4E14F76481",
    "Medium": "4AC8E03606FFA4C37F61A6510A2080F1F37A7054F4726C214887D3B23F72E369",
}
DIGSBY_SOURCE = "digsby/src/gui/native/win/winfonts.py"
DIGSBY_SOURCE_SHA = "3F20A0E42E8DD2F779AA1DD800925909DEF1E7A04B8FF525040AE2E65674CA90"
DIGSBY_LICENSE_SHA = "40DDC25914FCC63289871553C5D478CCC7CCC196987F69F5BDE4A8EC399FC374"


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def inventory_summary(files: dict[str, bytes]) -> dict:
    return {key: value for key, value in inventory(files).items() if key != "files"}


def read_archive(path: Path, prefix: str) -> dict[str, bytes]:
    """Inventory in memory; never extract, execute or follow an upstream link."""
    files: dict[str, bytes] = {}
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for index, member in enumerate(archive):
            require(index < 15000, "archive member limit")
            name = member.name.rstrip("/")
            require(name == prefix or name.startswith(prefix + "/"), "archive prefix")
            if member.isdir():
                continue
            relative = safe_name(name[len(prefix) + 1 :])
            require(relative not in files, "duplicate archive member")
            require(member.isfile() or member.issym(), "unsupported archive member")
            if member.issym():
                # Git stores the target text as a blob; no dereference is needed.
                data = member.linkname.encode("utf-8")
            else:
                require(member.size <= 64 * 1024 * 1024, "archive member size")
                total += member.size
                require(total <= 500 * 1024 * 1024, "archive total size")
                stream = archive.extractfile(member)
                require(stream is not None, "archive member missing")
                data = stream.read()
                require(len(data) == member.size, "archive member truncated")
            files[relative] = data
    require(bool(files), "empty archive")
    return files


def check_tree(files: dict[str, bytes], tree: dict, paths: list[str]) -> None:
    require(tree.get("truncated") is False, "truncated Git tree")
    blobs = {
        item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"
    }
    for path in paths:
        require(path in files and path in blobs, "missing source/tag file: " + path)
        require(git_blob(files[path]) == blobs[path], "tag mismatch: " + path)


def check_license(sdist: dict[str, bytes], metadata: bytes, candidate: bytes) -> None:
    require(sha256(sdist.get("LICENSE", b"")) == MIT_SHA, "missing/wrong MIT LICENSE")
    require(
        candidate.replace(b"\r\n", b"\n") == sdist["LICENSE"], "MIT CRLF normalization"
    )
    for data in (sdist.get("setup.cfg", b""), metadata):
        require(
            b"Creative Commons Zero v1.0 Universal" in data, "CC0 evidence normalized"
        )
        require(
            b"License :: OSI Approved :: MIT License" in data, "MIT classifier missing"
        )


def check_package(
    source: dict[str, bytes], files: dict[str, bytes], tree: dict
) -> None:
    runtime = [name for name in files if name.startswith("customtkinter/")]
    require(len(runtime) == 52, "unexplained wheel member")
    require(
        sum(name.endswith(".py") for name in runtime) == 43, "43 Python source files"
    )
    for path in runtime:
        require(source.get(path) == files[path], "sdist/wheel mismatch: " + path)
        if Path(path).name != ".DS_Store":
            check_tree(source, tree, [path])
        else:
            require(
                path not in {item["path"] for item in tree["tree"]},
                "unexpected DS_Store in tag",
            )
    check_tree(source, tree, ["LICENSE", "MANIFEST.in"])
    tagged = {item["path"] for item in tree["tree"] if item["type"] == "blob"}
    check_tree(source, tree, sorted((set(source) & tagged) - {"setup.cfg"}))


def check_setup_cfg(sdist: bytes, upstream: bytes) -> None:
    before = configparser.ConfigParser(interpolation=None)
    after = configparser.ConfigParser(interpolation=None)
    before.read_string(upstream.decode())
    after.read_string(sdist.decode())
    require(
        dict(after["egg_info"]) == {"tag_build": "", "tag_date": "0"},
        "generated egg_info changed",
    )
    after.remove_section("egg_info")
    require(
        {section: dict(before[section]) for section in before.sections()}
        == {section: dict(after[section]) for section in after.sections()},
        "setup.cfg semantic mismatch",
    )


def require_complete(manifest: dict) -> None:
    # D8 deliberately does not implement staging/building an unresolved parent.
    require(
        manifest["roboto"]["producer_status"] == "RESOLVED",
        "Roboto producer unresolved",
    )
    require(
        bool(manifest["roboto"]["producing_parent"]), "version-only Roboto provenance"
    )
    require(
        manifest["source_pending"] == 0 and manifest["unknown_material_files"] == 0,
        "source material unresolved",
    )
    raise SourceBundleError(
        "Complete assembly requires a separately reviewed closure implementation"
    )


def validate_manifest(manifest: dict) -> None:
    require(manifest["classification"] == "PARTIAL", "unproved COMPLETE status")
    require(manifest["customtkinter"]["commit"] == CTK_COMMIT, "CustomTkinter commit")
    require(manifest["customtkinter"]["tree"] == CTK_TREE, "CustomTkinter tree")
    require(manifest["customtkinter"]["sdist_sha256"] == SDIST_SHA, "sdist identity")
    require(manifest["customtkinter"]["wheel_sha256"] == WHEEL_SHA, "wheel identity")
    require(manifest["digsby"]["commit"] == DIGSBY_COMMIT, "Digsby commit")
    require(manifest["digsby"]["tree"] == DIGSBY_TREE, "Digsby tree")
    require(
        manifest["digsby"]["source_sha256"] == DIGSBY_SOURCE_SHA,
        "Digsby source identity",
    )
    require(
        manifest["digsby"]["license_sha256"] == DIGSBY_LICENSE_SHA,
        "Digsby license identity",
    )
    require(len(manifest["modules"]) == 43, "43 module coverage")
    require(manifest["roboto"]["hashes"] == ROBOTO, "Roboto exact bytes")
    require(
        manifest["roboto"]["producer_status"] == "PROVENANCE_PENDING"
        and manifest["roboto"]["producing_parent"] is None,
        "version-only Roboto provenance",
    )
    require(
        manifest["source_pending"] == 1 and manifest["unknown_material_files"] == 2,
        "unresolved Roboto accounting",
    )
    require(manifest["notice_delivery"] == "PENDING_FIX", "unperformed notice delivery")
    require(
        manifest["license_discrepancy"] == "METADATA_DISCREPANCY_EXPLAINED",
        "license signals silently reconciled",
    )
    require(manifest["license_signals"]["license_lf_sha256"] == MIT_SHA, "MIT identity")
    require(
        manifest["license_signals"]["metadata_license"]
        == "Creative Commons Zero v1.0 Universal",
        "stale CC0 metadata removed",
    )
    require(
        "roboto-historical-LICENSE.txt" in manifest["acquisitions"],
        "missing Roboto license",
    )
    require("digsby-LICENSE" in manifest["acquisitions"], "missing Digsby license")
    require("so-revisions.json" in manifest["acquisitions"], "missing SO revisions")
    require(
        manifest["stack_overflow"]["answer_id"] == 30631309
        and manifest["stack_overflow"]["author"] == "Felipe"
        and len(manifest["stack_overflow"]["revisions"]) == 4,
        "missing SO attribution",
    )


def load_manifest(path: Path = MANIFEST) -> dict:
    data = path.read_bytes()
    require(sha256(data) == MANIFEST_SHA256, "unapproved provenance manifest")
    manifest = json.loads(data)
    require(formatted(manifest) == data, "noncanonical provenance JSON")
    validate_manifest(manifest)
    return manifest


def verify_inputs(manifest: dict, work: Path = WORK, wheel: Path = WHEEL) -> dict:
    """Verify preserved evidence and every package member, offline and read-only."""
    validate_manifest(manifest)
    inputs = work / "inputs"
    for name, record in manifest["acquisitions"].items():
        data = (inputs / safe_name(name)).read_bytes()
        require(
            len(data) == record["size"] and sha256(data) == record["sha256"],
            "evidence hash mismatch: " + name,
        )
    require(
        sha256((inputs / "customtkinter-5.2.2.tar.gz").read_bytes()) == SDIST_SHA,
        "sdist hash",
    )
    require(sha256(wheel.read_bytes()) == WHEEL_SHA, "wheel hash")
    source = read_archive(inputs / "customtkinter-5.2.2.tar.gz", "customtkinter-5.2.2")
    require(inventory(source) == manifest["sdist_inventory"], "sdist inventory")
    tree = json.loads((inputs / "ctk-tree.json").read_bytes())
    commit = json.loads((inputs / "ctk-commit.json").read_bytes())
    # GitHub /git/trees/<commit> echoes the requested commit in its sha field.
    require(
        tree["sha"] == CTK_COMMIT
        and commit["sha"] == CTK_COMMIT
        and commit["tree"]["sha"] == CTK_TREE,
        "tag tree identity",
    )
    tag = json.loads((inputs / "ctk-tag.json").read_bytes())
    require(tag["object"]["sha"] == CTK_COMMIT, "tag target")
    with zipfile.ZipFile(wheel) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    require(inventory(files) == manifest["wheel_inventory"], "wheel inventory")
    check_package(source, files, tree)
    upstream_cfg = (inputs / "ctk-setup.cfg").read_bytes()
    check_tree({"setup.cfg": upstream_cfg}, tree, ["setup.cfg"])
    check_setup_cfg(source["setup.cfg"], upstream_cfg)
    check_license(
        source,
        files["customtkinter-5.2.2.dist-info/METADATA"],
        (Path("Licencas") / "CUSTOMTKINTER_LICENSE.txt").read_bytes(),
    )
    digsby = read_archive(
        inputs / ("digsby-" + DIGSBY_COMMIT + ".tar.gz"), "digsby-" + DIGSBY_COMMIT
    )
    require(
        inventory_summary(digsby) == manifest["digsby"]["inventory"], "Digsby inventory"
    )
    dtree = json.loads((inputs / "digsby-tree.json").read_bytes())
    dcommit = json.loads((inputs / "digsby-commit.json").read_bytes())
    require(
        dtree["sha"] == DIGSBY_COMMIT
        and dcommit["sha"] == DIGSBY_COMMIT
        and dcommit["tree"]["sha"] == DIGSBY_TREE,
        "Digsby tree",
    )
    require(
        sha256(digsby.get(DIGSBY_SOURCE, b"")) == DIGSBY_SOURCE_SHA, "Digsby source"
    )
    require(sha256(digsby.get("LICENSE", b"")) == DIGSBY_LICENSE_SHA, "Digsby LICENSE")
    check_tree(digsby, dtree, list(digsby))
    return {"source": source, "wheel": files}


def frozen_coverage(files: dict[str, bytes], frozen: Path = FROZEN) -> dict:
    pyz = archive_entries((frozen / "EduDownloader.exe").read_bytes())["PYZ.pyz"]
    toc = dict(marshal.loads(pyz[struct.unpack("!i", pyz[8:12])[0] :]))
    names = sorted(
        name
        for name in toc
        if name == "customtkinter" or name.startswith("customtkinter.")
    )
    require(len(names) == 43, "43 frozen modules")
    modules = []
    for name in names:
        kind, offset, size = toc[name]
        data = zlib.decompress(pyz[offset : offset + size])
        code = marshal.loads(data)
        path = name.replace(".", "/") + ("/__init__.py" if kind == 1 else ".py")
        require(path in files, "missing module source: " + path)
        require(
            compile(
                files[path], code.co_filename, "exec", dont_inherit=True, optimize=0
            )
            == code,
            "frozen module mismatch: " + name,
        )
        modules.append(
            {
                "module": name,
                "path": path,
                "source_sha256": sha256(files[path]),
                "frozen_code_sha256": sha256(data),
                "classification": "SOURCE_MATCH",
            }
        )
    data_records = []
    for path, data in sorted(files.items()):
        if not path.startswith("customtkinter/assets/"):
            continue
        require(
            (frozen / "_internal" / path).read_bytes() == data,
            "frozen asset mismatch: " + path,
        )
        data_records.append(
            {
                "path": path,
                "size": len(data),
                "sha256": sha256(data),
                "classification": "NON_RUNTIME_PACKAGING_RESIDUE"
                if Path(path).name == ".DS_Store"
                else "SOURCE_MATCH",
            }
        )
    require(len(data_records) == 9, "9 frozen package data")
    return {"modules": modules, "data": data_records}


def verify_frozen(
    manifest: dict, files: dict[str, bytes], frozen: Path = FROZEN
) -> None:
    from validate_frozen_candidate import build_file_inventory

    authority = manifest["frozen_authority"]
    require(
        build_file_inventory(frozen)["inventory_sha256"]
        == authority["inventory_sha256"],
        "pristine candidate changed",
    )
    coverage = frozen_coverage(files, frozen)
    require(coverage["modules"] == manifest["modules"], "module evidence mismatch")
    require(coverage["data"] == manifest["data"], "data evidence mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "verify-inputs",
            "verify-frozen",
            "verify-staging",
            "assemble",
            "verify-bundle",
        ),
    )
    args = parser.parse_args()
    try:
        manifest = load_manifest()
        if args.command in {"verify-staging", "assemble", "verify-bundle"}:
            require_complete(manifest)
        result = verify_inputs(manifest)
        if args.command == "verify-frozen":
            verify_frozen(manifest, result["wheel"])
        print(
            "PASS: preserved evidence; correspondence PARTIAL; Roboto producer pending; no bundle"
        )
        return 0
    except (
        OSError,
        KeyError,
        ValueError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        print("FAIL:", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
