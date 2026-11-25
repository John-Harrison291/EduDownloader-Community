"""Catálogo de componentes Community, com confiança separada da ativação."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

from constants import APP_VERSION, PRODUCT_EDITION, ProductEdition
from component_transactions import component_lock


CATALOGUE_SCHEMA = 1
CATALOGUE_LIMIT = 2 * 1024 * 1024
CATALOGUE_DOMAIN = b"EduDownloader Community component catalogue v1\0"

# A raiz pública exclusiva da Community será incorporada com a publicação do
# catálogo. A distribuição de QA usa as aprovações locais incorporadas.
REMOTE_CATALOGUE_KEYS: dict[str, bytes] = {}

COMPONENTS = frozenset({"yt-dlp", "deno", "ffmpeg-ffprobe", "ocr", "libreoffice"})
VERSION = re.compile(r"(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{1,4}){1,3}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
PATH_PART = re.compile(r"[A-Za-z0-9_.+ -]{1,100}\Z")
RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"{name}{n}" for name in ("com", "lpt") for n in range(10)}
)
OFFICIAL_HOSTS = frozenset(
    {
        "github.com",
        "raw.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
        "gyan.dev",
        "www.gyan.dev",
        "ffmpeg.org",
        "tdf.c3sl.ufpr.br",
        "download.documentfoundation.org",
        "static.crates.io",
    }
)


class CatalogueError(ValueError):
    """Catálogo ou aprovação incompatível com a política."""


def version_key(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or VERSION.fullmatch(value) is None:
        raise CatalogueError("invalid_stable_version")
    parts = tuple(int(part) for part in value.split("."))
    return parts + (0,) * (4 - len(parts))


def package_path(text: str) -> PurePosixPath:
    if not isinstance(text, str) or not text or len(text) > 220:
        raise CatalogueError("invalid_package_path")
    for item in text.split("/"):
        if (
            PATH_PART.fullmatch(item) is None
            or item.strip(" .") != item
            or item.split(".")[0].casefold() in RESERVED
        ):
            raise CatalogueError("invalid_package_path")
    return PurePosixPath(text)


def artifact_url(value: str) -> str:
    if not isinstance(value, str) or any(character.isspace() for character in value):
        raise CatalogueError("invalid_artifact_url")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc not in OFFICIAL_HOSTS
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
    ):
        raise CatalogueError("invalid_artifact_url")
    return value


def _object(value: object, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise CatalogueError("invalid_catalogue_fields")
    return value


def _sha(value: str) -> str:
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise CatalogueError("invalid_catalogue_digest")
    return value


def _positive(value: object, maximum: int) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise CatalogueError("invalid_catalogue_number")
    return value


def _time(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value
    ):
        raise CatalogueError("invalid_catalogue_time")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise CatalogueError("duplicate_catalogue_key")
    return result


def _decode(data: bytes) -> dict:
    if not data or len(data) > CATALOGUE_LIMIT:
        raise CatalogueError("invalid_catalogue_size")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_unique)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CatalogueError("invalid_catalogue_json") from exc


def canonical_catalogue(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise CatalogueError("invalid_catalogue_json") from exc


@dataclass(frozen=True, slots=True)
class PackageFile:
    source: str
    target: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PackageAsset:
    url: str
    kind: str
    size: int
    sha256: str
    signer: str | None
    files: tuple[PackageFile, ...]


@dataclass(frozen=True, slots=True)
class Approval:
    component: str
    version: str
    minimum_app: str
    maximum_app: str
    provenance: str
    notices: tuple[str, ...]
    assets: tuple[PackageAsset, ...]

    def compatible(self, app_version: str = APP_VERSION) -> bool:
        return (
            version_key(self.minimum_app)
            <= version_key(app_version)
            <= version_key(self.maximum_app)
        )


@dataclass(frozen=True, slots=True)
class Catalogue:
    revision: int
    issued: datetime
    expires: datetime
    approvals: tuple[Approval, ...]
    revoked: frozenset[tuple[str, str]]

    def is_revoked(self, component: str, version: str) -> bool:
        key = version_key(version)
        return any(
            name == component and version_key(value) == key
            for name, value in self.revoked
        )

    def available(
        self, component: str, app_version: str = APP_VERSION
    ) -> Approval | None:
        return max(
            (
                release
                for release in self.approvals
                if release.component == component
                and not self.is_revoked(component, release.version)
                and release.compatible(app_version)
            ),
            key=lambda release: version_key(release.version),
            default=None,
        )


def _asset(value: object) -> PackageAsset:
    asset = _object(value, {"url", "kind", "size", "sha256", "signer", "files"})
    size = _positive(asset["size"], 2_000_000_000)
    digest = _sha(asset["sha256"])
    signer = asset["signer"]
    if signer is not None and (
        not isinstance(signer, str) or re.fullmatch(r"[0-9a-f]{40}", signer) is None
    ):
        raise CatalogueError("invalid_signer")
    if asset["kind"] not in ("zip", "file", "msi", "packaged") or not isinstance(
        asset["files"], list
    ):
        raise CatalogueError("invalid_asset_shape")
    files = []
    for item in asset["files"]:
        fields = _object(item, {"source", "target", "size", "sha256"})
        files.append(
            PackageFile(
                package_path(fields["source"]).as_posix(),
                package_path(fields["target"]).as_posix(),
                _positive(fields["size"], 2_000_000_000),
                _sha(fields["sha256"]),
            )
        )
    paths = {item.source.casefold() for item in files}
    if (
        len(paths) != len(files)
        or (
            asset["kind"] in ("file", "packaged")
            and (len(files) != 1 or files[0].size != size or files[0].sha256 != digest)
        )
        or (asset["kind"] == "msi" and (files or signer is None))
        or (asset["kind"] == "zip" and not files)
    ):
        raise CatalogueError("invalid_asset_files")
    return PackageAsset(
        artifact_url(asset["url"]), asset["kind"], size, digest, signer, tuple(files)
    )


def _approval(value: object) -> Approval:
    entry = _object(
        value,
        {
            "component",
            "version",
            "architecture",
            "minimum_app",
            "maximum_app",
            "provenance",
            "notices",
            "assets",
        },
    )
    component = entry["component"]
    if (
        not isinstance(component, str)
        or component not in COMPONENTS
        or entry["architecture"] != "windows-x64"
    ):
        raise CatalogueError("incompatible_package_identity")
    version_key(entry["version"])
    if version_key(entry["minimum_app"]) > version_key(entry["maximum_app"]):
        raise CatalogueError("invalid_compatibility_range")
    if not isinstance(entry["assets"], list) or not 1 <= len(entry["assets"]) <= 24:
        raise CatalogueError("invalid_approval_assets")
    if not isinstance(entry["notices"], list) or not entry["notices"]:
        raise CatalogueError("missing_component_notices")
    assets = tuple(_asset(asset) for asset in entry["assets"])
    notices = tuple(package_path(path).as_posix() for path in entry["notices"])
    wanted = [file.target.casefold() for item in assets for file in item.files]
    if len(wanted) != len(set(wanted)):
        raise CatalogueError("duplicate_component_files")
    if component == "libreoffice":
        if sum(asset.kind == "msi" for asset in assets) != 1:
            raise CatalogueError("invalid_office_assets")
    elif any(asset.kind == "msi" for asset in assets) or any(
        name.casefold() not in wanted for name in notices
    ):
        raise CatalogueError("missing_component_notices")
    return Approval(
        component,
        entry["version"],
        entry["minimum_app"],
        entry["maximum_app"],
        artifact_url(entry["provenance"]),
        notices,
        assets,
    )


def parse_catalogue(value: object) -> Catalogue:
    data = _object(
        value,
        {"schema", "edition", "revision", "issued", "expires", "approvals", "revoked"},
    )
    if (
        type(data["schema"]) is not int
        or data["schema"] != CATALOGUE_SCHEMA
        or data["edition"] != "community"
    ):
        raise CatalogueError("unsupported_catalogue")
    issued, expires = _time(data["issued"]), _time(data["expires"])
    if not issued < expires <= issued + timedelta(days=90):
        raise CatalogueError("invalid_catalogue_lifetime")
    if (
        not isinstance(data["approvals"], list)
        or len(data["approvals"]) > 200
        or not isinstance(data["revoked"], list)
    ):
        raise CatalogueError("invalid_catalogue_lists")
    approvals = tuple(_approval(entry) for entry in data["approvals"])
    if len({(item.component, version_key(item.version)) for item in approvals}) != len(
        approvals
    ):
        raise CatalogueError("duplicate_component_approval")
    revoked = set()
    for value in data["revoked"]:
        entry = _object(value, {"component", "version"})
        if (
            not isinstance(entry["component"], str)
            or entry["component"] not in COMPONENTS
        ):
            raise CatalogueError("unknown_revoked_component")
        version_key(entry["version"])
        revoked.add((entry["component"], entry["version"]))
    return Catalogue(
        _positive(data["revision"], 2**63 - 1),
        issued,
        expires,
        approvals,
        frozenset(revoked),
    )


def verify_signed_catalogue(data: bytes, keys: dict[str, bytes]) -> Catalogue:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    envelope = _object(_decode(data), {"key_id", "payload", "signature"})
    key_id = envelope["key_id"]
    key = keys.get(key_id) if isinstance(key_id, str) else None
    if key is None:
        raise CatalogueError("untrusted_catalogue_key")
    try:
        signature = base64.b64decode(envelope["signature"], validate=True)
        Ed25519PublicKey.from_public_bytes(key).verify(
            signature, CATALOGUE_DOMAIN + canonical_catalogue(envelope["payload"])
        )
    except (InvalidSignature, ValueError, TypeError, binascii.Error) as exc:
        raise CatalogueError("invalid_catalogue_signature") from exc
    return parse_catalogue(envelope["payload"])


class CatalogueCache:
    """Preserva revisão e revogações verificadas mesmo após o vencimento."""

    def __init__(
        self, root: Path, built_in: Catalogue, *, keys: dict[str, bytes] | None = None
    ):
        self.root = root
        self.built_in = built_in
        self.keys = REMOTE_CATALOGUE_KEYS if keys is None else keys
        self.path = root / "catalogue-v1.signed.json"

    def _read(self) -> Catalogue | None:
        if not self.keys:
            return None
        if any(
            path.is_symlink() or path.is_junction()
            for path in (self.path, *self.path.parents)
        ):
            raise CatalogueError("redirected_catalogue_cache")
        try:
            if self.path.stat().st_size > CATALOGUE_LIMIT:
                raise CatalogueError("invalid_catalogue_size")
            return verify_signed_catalogue(self.path.read_bytes(), self.keys)
        except FileNotFoundError:
            return None

    def accept(self, raw: bytes, *, now: datetime | None = None) -> Catalogue:
        from component_transactions import atomic_component_bytes

        if PRODUCT_EDITION is not ProductEdition.COMMUNITY:
            raise CatalogueError("unsupported_catalogue")
        instant = datetime.now(UTC) if now is None else now
        proposed = verify_signed_catalogue(raw, self.keys)
        if not proposed.issued <= instant < proposed.expires:
            raise CatalogueError("catalogue_outside_validity")
        with component_lock(self.root, "catalogue"):
            previous = self._read() or self.built_in
            if proposed.revision < max(previous.revision, self.built_in.revision) or (
                proposed.revision == previous.revision and proposed != previous
            ):
                raise CatalogueError("catalogue_revision_regressed")
            if not previous.revoked.issubset(proposed.revoked):
                raise CatalogueError("catalogue_revocation_regressed")
            atomic_component_bytes(self.path, raw)
        return self.effective(now=instant)

    def effective(
        self, *, now: datetime | None = None, for_execution: bool = False
    ) -> Catalogue:
        instant = datetime.now(UTC) if now is None else now
        previous = self._read()
        local = self.built_in
        if previous is None:
            return local
        old = replace_revocations(local, local.revoked | previous.revoked)
        if (
            previous.revision < local.revision
            or previous.issued > instant
            or (not for_execution and instant >= previous.expires)
        ):
            return old
        merged = {
            (item.component, version_key(item.version)): item
            for item in local.approvals
        }
        merged.update(
            {
                (item.component, version_key(item.version)): item
                for item in previous.approvals
            }
        )
        return Catalogue(
            previous.revision,
            previous.issued,
            previous.expires,
            tuple(merged.values()),
            old.revoked,
        )


def replace_revocations(
    catalogue: Catalogue, revocations: frozenset[tuple[str, str]]
) -> Catalogue:
    return Catalogue(
        catalogue.revision,
        catalogue.issued,
        catalogue.expires,
        catalogue.approvals,
        revocations,
    )


def load_local_catalogue(raw: bytes) -> Catalogue:
    return parse_catalogue(_decode(raw))
