"""Aquisição, validação e publicação atômica dos componentes Community."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import threading
import zipfile

from component_catalog import (
    Approval,
    Catalogue,
    CatalogueCache,
    OFFICIAL_HOSTS,
    PackageAsset,
    canonical_catalogue,
    load_local_catalogue,
    package_path,
    version_key,
)
from component_smoke import verify_component
from component_transactions import (
    ComponentBusyError,
    atomic_component_bytes,
    component_lock,
    create_stage,
    ordinary_component_path,
    recover_staging,
)
from constants import PRODUCT_EDITION, ProductEdition
from paths import (
    get_app_dir,
    get_bundled_components_dir,
    get_community_install_root,
    get_managed_components_dir,
)
from yt_dlp_update import OfficialTransport, UpdateCancelled, UpdateError, UpdateStatus


TOOL_FILES = {
    "deno": frozenset({"deno.exe"}),
    "ffmpeg-ffprobe": frozenset({"ffmpeg.exe", "ffprobe.exe"}),
    "ocr": frozenset(
        {
            "tesseract.exe",
            "tessdata_fast/por.traineddata",
            "tessdata_best/por.traineddata",
            "tessdata_fast/osd.traineddata",
        }
    ),
}
TOOL_COMPONENT = {
    "deno.exe": "deno",
    "ffmpeg.exe": "ffmpeg-ffprobe",
    "ffprobe.exe": "ffmpeg-ffprobe",
}
MINIMUM_SPACE = 32 * 1024 * 1024
_LOCAL_CATALOGUE = "community-components-v1.json"
REMOTE_CATALOGUE_URL: str | None = None
_OFFICE_PROFILE_FILES = frozenset(
    {
        "libreoffice-image.json",
        "libreoffice-ui-resources.txt",
        "libreoffice-signatures.json",
    }
)
_OFFICE_ENGINES = frozenset({"soffice.com", "soffice.exe", "soffice.bin"})


def runtime_package_root(base_dir: Path) -> Path:
    return get_managed_components_dir(base_dir) / "gerenciados-v1"


def _installation(base_dir: Path) -> str:
    return str(get_community_install_root(base_dir) or base_dir.resolve())


def _managed_allowed() -> bool:
    if PRODUCT_EDITION is not ProductEdition.COMMUNITY:
        return False
    if os.name != "nt":
        return True
    import ctypes

    try:
        return not bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


@lru_cache(maxsize=1)
def builtin_catalogue() -> Catalogue:
    base = (
        Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
    )
    return load_local_catalogue((base / "installer" / _LOCAL_CATALOGUE).read_bytes())


def _packaged_file(base_dir: Path, relative: str) -> Path:
    if relative in ("ffmpeg.exe", "ffprobe.exe"):
        return base_dir / relative
    if (
        relative == "installer/component-assets/DENO-BASELINE-LICENSES.txt"
        and not getattr(sys, "frozen", False)
    ):
        return (
            Path(__file__).parent / "docs/compliance/deno/DENO_THIRD_PARTY_NOTICES.txt"
        )
    if relative in (
        "installer/component-assets/FFMPEG_BTBN_LICENSE.txt",
        "installer/component-assets/FFMPEG_BTBN_NOTICE.txt",
    ) and not getattr(sys, "frozen", False):
        return Path(__file__).parent / "Licencas" / Path(relative).name
    if relative.startswith("Componentes/OCR/"):
        subdirectory = "OCR" if getattr(sys, "frozen", False) else "OCR-Community"
        return (
            get_bundled_components_dir(base_dir)
            / subdirectory
            / relative.removeprefix("Componentes/OCR/")
        )
    if not relative.startswith("installer/component-assets/"):
        raise UpdateError("unknown_packaged_asset")
    root = (
        Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
    )
    return root / relative


def effective_catalogue(base_dir: Path, *, for_execution: bool = False) -> Catalogue:
    return CatalogueCache(
        runtime_package_root(base_dir), builtin_catalogue()
    ).effective(for_execution=for_execution)


def _identity(approval: Approval) -> str:
    return hashlib.sha256(canonical_catalogue(asdict(approval))).hexdigest()[:24]


def _layout(approval: Approval) -> dict[str, tuple[int, str]]:
    return {
        path.target: (path.size, path.sha256)
        for asset in approval.assets
        for path in asset.files
    }


def _metadata(path: Path) -> dict:
    if not ordinary_component_path(path) or path.stat().st_size > 8192:
        raise UpdateError("invalid_component_state")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise UpdateError("invalid_component_state")
    return result


def _sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


@lru_cache(maxsize=160)
def _cached_hash(path: Path, size: int, mtime: int, ctime: int, inode: int) -> str:
    return _sha(path)


def _valid_file(path: Path, size: int, digest: str) -> bool:
    if not ordinary_component_path(path) or not path.is_file():
        return False
    info = path.stat()
    return (
        info.st_size == size
        and _cached_hash(path, size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
        == digest
    )


def _verify_layout(root: Path, approval: Approval) -> None:
    layout = _layout(approval)
    if not TOOL_FILES[approval.component].issubset(layout) or any(
        not _valid_file(root / relative, *expected)
        for relative, expected in layout.items()
    ):
        raise UpdateError("invalid_component_layout")
    for relative in TOOL_FILES[approval.component]:
        if relative.endswith(".exe") and not _pe_x64(root / relative):
            raise UpdateError("component_architecture_mismatch")


def _pe_x64(path: Path) -> bool:
    with path.open("rb") as stream:
        dos = stream.read(64)
        if len(dos) != 64 or dos[:2] != b"MZ":
            return False
        offset = struct.unpack_from("<I", dos, 60)[0]
        if not 64 <= offset <= 65536:
            return False
        stream.seek(offset)
        return stream.read(6) == b"PE\0\0\x64\x86"


def _version_dir(base: Path, approval: Approval) -> Path:
    return base / approval.component / "versions" / _identity(approval)


def _current_approval(base_dir: Path, component: str) -> Approval | None:
    managed = runtime_package_root(base_dir)
    data = _metadata(managed / component / "active.json")
    catalogue = effective_catalogue(base_dir, for_execution=True)
    return next(
        (
            approval
            for approval in catalogue.approvals
            if approval.component == component
            and approval.compatible()
            and approval.version == data.get("version")
            and _identity(approval) == data.get("identity")
            and not catalogue.is_revoked(component, approval.version)
        ),
        None,
    )


def active_component(base_dir: Path, component: str) -> tuple[Path, str] | None:
    if not _managed_allowed() or component not in TOOL_FILES:
        return None
    try:
        approval = _current_approval(base_dir, component)
        if approval is not None:
            target = _version_dir(runtime_package_root(base_dir), approval)
            _verify_layout(target, approval)
            return target, approval.version
    except (OSError, ValueError, UpdateError):
        return None
    return None


def active_ocr(base_dir: Path) -> tuple[Path, dict[str, str]] | None:
    if not _managed_allowed():
        return None
    try:
        approval = _current_approval(base_dir, "ocr")
        if approval is None:
            return None
        target = _version_dir(runtime_package_root(base_dir), approval)
        _verify_layout(target, approval)
        return target, {name: digest for name, (_, digest) in _layout(approval).items()}
    except (OSError, ValueError, UpdateError):
        return None


@contextmanager
def component_use(base_dir: Path, *names: str):
    """Leases simultâneos de leitura, exclusivos contra mutações de um componente."""
    with ExitStack() as stack:
        if _managed_allowed():
            catalogue = effective_catalogue(base_dir, for_execution=True)
            for name in sorted(set(names)):
                root = (
                    get_managed_components_dir(base_dir)
                    if name == "yt-dlp"
                    else runtime_package_root(base_dir)
                )
                try:
                    stack.enter_context(component_lock(root, name, shared=True))
                except (OSError, ValueError):
                    # Um destino portátil somente leitura pode continuar com os
                    # executáveis empacotados. Nenhuma aquisição escreve nele.
                    if (root / name / "active.json").exists():
                        raise
                _verify_unrevoked_runtime(base_dir, name, catalogue)
        yield


def _verify_unrevoked_runtime(base_dir: Path, name: str, catalogue: Catalogue) -> None:
    if not any(component == name for component, _ in catalogue.revoked):
        return
    if name == "yt-dlp":
        from yt_dlp_update import _probe_version, resolve_active_yt_dlp

        runtime = resolve_active_yt_dlp(base_dir)
        version = runtime.version or _probe_version(runtime.path)
    elif name in TOOL_FILES:
        active = active_component(base_dir, name)
        version = (
            active[1]
            if active
            else {"deno": "2.9.5", "ffmpeg-ffprobe": "8.1.2", "ocr": "5.5.4"}[name]
        )
    else:
        return
    if version is None or catalogue.is_revoked(name, version):
        raise OSError("component_release_revoked")


def _files_in_zip(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > 4096 or sum(entry.file_size for entry in entries) > 3_000_000_000:
        raise UpdateError("archive_limits")
    indexed = {}
    for entry in entries:
        name = package_path(entry.filename.removesuffix("/")).as_posix()
        canonical = name.casefold()
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if (
            canonical in indexed
            or entry.flag_bits & 1
            or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
        ):
            raise UpdateError("unexpected_archive_entry")
        if (
            entry.create_system == 0
            and entry.external_attr & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise UpdateError("unexpected_archive_entry")
        indexed[canonical] = entry
    return indexed


def _unpack(
    archive_path: Path, asset: PackageAsset, target: Path, cancel: threading.Event
) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        indexed = _files_in_zip(archive)
        for member in asset.files:
            info = indexed.get(member.source.casefold())
            if (
                info is None
                or info.is_dir()
                or info.filename != member.source
                or info.file_size != member.size
            ):
                raise UpdateError("missing_expected_archive_file")
            output = target / member.target
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, output.open("xb") as destination:
                count = 0
                while chunk := source.read(256 * 1024):
                    if cancel.is_set():
                        raise UpdateCancelled
                    count += len(chunk)
                    if count > member.size:
                        raise UpdateError("invalid_archive_size")
                    destination.write(chunk)


def _check_signer(path: Path, thumbprint: str) -> None:
    import subprocess

    executable = (
        Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    safe_argument = str(path).replace("'", "''")
    result = subprocess.run(
        [
            str(executable),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$ErrorActionPreference='Stop'; "
            "Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1'); "
            f"$signature=Get-AuthenticodeSignature -LiteralPath '{safe_argument}'; "
            "if ($signature.Status -ne 'Valid') { exit 1 }; $signature.SignerCertificate.Thumbprint",
        ],
        capture_output=True,
        check=False,
        timeout=35,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode or result.stdout.strip().casefold() != thumbprint:
        raise UpdateError("invalid_component_signature")


def _current_fixed_drive(path: Path) -> bool:
    if not ordinary_component_path(path) or not path.is_absolute():
        return False
    if os.name != "nt":
        return True
    import ctypes

    return (
        len(path.drive) == 2 and ctypes.windll.kernel32.GetDriveTypeW(path.anchor) == 3
    )


def _office_assets(
    approval: Approval,
) -> tuple[PackageAsset, dict[str, PackageAsset]] | None:
    if approval.component != "libreoffice" or len(approval.assets) != 4:
        return None
    installer = next((item for item in approval.assets if item.kind == "msi"), None)
    files = {
        item.files[0].target: item
        for item in approval.assets
        if item.kind == "file" and item.size <= 2 * 1024 * 1024
    }
    if installer is None or set(files) != _OFFICE_PROFILE_FILES:
        return None
    filename = Path(installer.url).name
    display = ".".join(approval.version.split(".")[:3])
    if filename != f"LibreOffice_{display}_Win_x86-64.msi":
        return None
    return installer, files


def verify_office_executables(root: Path, profile: Path, version: str) -> None:
    signatures = _metadata(profile / "libreoffice-signatures.json")
    binary_hashes = signatures.get("sha256")
    if (
        signatures.get("version") != version
        or not isinstance(binary_hashes, dict)
        or set(binary_hashes) != _OFFICE_ENGINES
    ):
        raise UpdateError("office_profile_mismatch")
    for executable, digest in binary_hashes.items():
        path = root / "program" / executable
        if not isinstance(digest, str) or not _valid_file(
            path, path.stat().st_size, digest.casefold()
        ):
            raise UpdateError("office_engine_integrity_failed")


def signed_office_root(base_dir: Path, record: dict | None = None) -> Path | None:
    """Aceita a imagem administrada apenas com a aprovação autenticada original."""
    if not _managed_allowed():
        return None
    managed = get_managed_components_dir(base_dir)
    try:
        data = _metadata(managed / "active.json") if record is None else record
        relative = data.get("relative_path")
        if (
            set(data) != {"schema", "version", "identity", "relative_path"}
            or data["schema"] != 2
            or (
                not isinstance(relative, str)
                or re.fullmatch(r"L(?:-repair-[0-9a-f]{8})?", relative) is None
            )
        ):
            return None
        catalogue = effective_catalogue(get_app_dir(), for_execution=True)
        release = next(
            (
                approval
                for approval in catalogue.approvals
                if approval.component == "libreoffice"
                and approval.compatible()
                and approval.version == data["version"]
                and _identity(approval) == data["identity"]
                and not catalogue.is_revoked("libreoffice", approval.version)
            ),
            None,
        )
        if release is None or (assets := _office_assets(release)) is None:
            return None
        root = managed / relative
        profile = root / ".edudownloader-profile"
        if not all(
            _valid_file(profile / name, item.size, item.sha256)
            for name, item in assets[1].items()
        ):
            return None
        verify_office_executables(root, profile, release.version)
        return root
    except (OSError, ValueError, UpdateError):
        return None


class ComponentUpdateService:
    def __init__(self, base_dir: Path, *, transport=None):
        self.base_dir = base_dir
        self.root = runtime_package_root(base_dir)
        self.transport = OfficialTransport() if transport is None else transport

    def yt_dlp_notices(self, release) -> tuple[tuple[str, str, str], ...]:
        from component_release_policy import YTDLP_NOTICE_NAMES, approved_yt_dlp_notices

        catalogue = effective_catalogue(self.base_dir)
        if catalogue.is_revoked("yt-dlp", release.version):
            raise UpdateError("component_release_revoked")
        approved = catalogue.available("yt-dlp")
        if approved is None or approved.version != release.version:
            return approved_yt_dlp_notices(release)
        files = {
            asset.files[0].target: asset
            for asset in approved.assets
            if asset.kind == "file"
        }
        binary, sums = files.get("yt-dlp.exe"), files.get("SHA2-256SUMS")
        if (
            binary is None
            or sums is None
            or (binary.url, binary.size, binary.sha256, sums.url, sums.sha256)
            != (
                release.binary_url,
                release.binary_size,
                release.binary_digest,
                release.sums_url,
                release.sums_digest,
            )
            or any(name not in files for name in YTDLP_NOTICE_NAMES)
        ):
            raise UpdateError("component_approval_changed")
        return tuple(
            (name, files[name].url, files[name].sha256) for name in YTDLP_NOTICE_NAMES
        )

    def approve_yt_dlp(self, release) -> bool:
        try:
            self.yt_dlp_notices(release)
        except (OSError, ValueError, UpdateError):
            return False
        return True

    def available(self, component: str, installed: str | None) -> Approval | None:
        if not _managed_allowed() or component not in (*TOOL_FILES, "libreoffice"):
            return None
        approval = effective_catalogue(self.base_dir).available(component)
        if approval is None or (
            installed is not None
            and version_key(installed) >= version_key(approval.version)
        ):
            return None
        if (
            component == "libreoffice"
            and not self._approved_office(approval)
            and _office_assets(approval) is None
        ):
            return None
        return approval

    def refresh_catalogue(self) -> Catalogue:
        if REMOTE_CATALOGUE_URL is None:
            return effective_catalogue(self.base_dir)
        cache = CatalogueCache(self.root, builtin_catalogue())
        from component_catalog import artifact_url, CATALOGUE_LIMIT

        raw = self.transport.read_bytes(
            artifact_url(REMOTE_CATALOGUE_URL),
            limit=CATALOGUE_LIMIT,
            allowed_hosts=OFFICIAL_HOSTS,
        )
        return cache.accept(raw)

    def update(
        self, approval: Approval, *, cancel: threading.Event, progress=None
    ) -> tuple[UpdateStatus, str]:
        if not _managed_allowed() or not _current_fixed_drive(self.root):
            return UpdateStatus.FAILED, "managed_root_unavailable"
        name = approval.component
        try:
            if name == "libreoffice":
                return self._update_office(approval, cancel, progress)
            if name not in TOOL_FILES:
                raise UpdateError("component_update_unsupported")
            # A recuperação usa o mesmo lock. Faça-a antes de tomar o lock
            # principal desta aquisição.
            recover_staging(self.root, name)
            with component_lock(self.root, name):
                if effective_catalogue(self.base_dir).available(name) != approval:
                    raise UpdateError("component_approval_changed")
                current = active_component(self.base_dir, name)
                if current is not None and version_key(current[1]) > version_key(
                    approval.version
                ):
                    raise UpdateError("component_downgrade_refused")
                return self._acquire(approval, cancel, progress)
        except ComponentBusyError:
            return UpdateStatus.FAILED, "component_busy"
        except UpdateCancelled:
            return UpdateStatus.CANCELLED, "cancelled"
        except UpdateError as error:
            return UpdateStatus.FAILED, error.code
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
            return UpdateStatus.FAILED, "component_preparation_failed"

    @staticmethod
    def _approved_office(approval: Approval) -> bool:
        from libreoffice_managed import APPROVED_BASELINE

        baseline = APPROVED_BASELINE
        return (
            approval.version == baseline.engine_version
            and len(approval.assets) == 1
            and (
                approval.assets[0].kind,
                approval.assets[0].url,
                approval.assets[0].size,
                approval.assets[0].sha256,
                approval.assets[0].signer,
            )
            == (
                "msi",
                baseline.download_url,
                baseline.installer_size,
                baseline.installer_sha256.casefold(),
                "6b5da216489de6c1d7db498ed672b7ed0f599513",
            )
        )

    def _update_office(
        self, approval: Approval, cancel: threading.Event, progress
    ) -> tuple[UpdateStatus, str]:
        from libreoffice_managed import (
            AcquisitionStatus,
            LibreOfficeAcquisitionService,
            OfficialAdministrativeInstaller,
        )

        if effective_catalogue(self.base_dir).available("libreoffice") != approval:
            raise UpdateError("component_approval_changed")
        if self._approved_office(approval):
            result = LibreOfficeAcquisitionService(
                self.base_dir,
                user_data=True,
                installer=OfficialAdministrativeInstaller(),
            ).install(cancel=cancel, progress=progress, repair=True)
        else:
            result = self._update_office_profile(approval, cancel, progress)
        status = {
            AcquisitionStatus.INSTALLED: UpdateStatus.UPDATED,
            AcquisitionStatus.CANCELLED: UpdateStatus.CANCELLED,
        }.get(result.status, UpdateStatus.FAILED)
        return (
            status,
            "component_busy"
            if result.status is AcquisitionStatus.BUSY
            else result.diagnostic_code,
        )

    def _update_office_profile(
        self, approval: Approval, cancel: threading.Event, progress
    ):
        from documents_component import DocumentsComponentService
        from libreoffice_image import read_removal_catalog
        from libreoffice_managed import (
            APPROVED_BASELINE,
            LibreOfficeAcquisitionService,
            OfficialAdministrativeInstaller,
        )

        assets = _office_assets(approval)
        if assets is None:
            raise UpdateError("office_profile_missing")
        installer, documents = assets
        recover_staging(self.root, "libreoffice")
        with component_lock(self.root, "libreoffice"):
            if cancel.is_set():
                raise UpdateCancelled
            stage = create_stage(self.root, "libreoffice", approval.version)
            try:
                for name, item in documents.items():
                    path = stage.path / name
                    found = self.transport.download(
                        item.url,
                        path,
                        expected_size=item.size,
                        cancel=cancel,
                        allowed_hosts=OFFICIAL_HOSTS,
                    )
                    if found != item.sha256 or not _valid_file(
                        path, item.size, item.sha256
                    ):
                        raise UpdateError("office_profile_sha256_mismatch")
                profile, _ = read_removal_catalog(stage.path)
                signature = _metadata(stage.path / "libreoffice-signatures.json")
                if (
                    profile["engine_version"] != approval.version
                    or profile["source_msi_sha256"].casefold() != installer.sha256
                    or signature.get("authority") != "The Document Foundation"
                    or signature.get("version") != approval.version
                    or str(signature.get("thumbprint", "")).casefold()
                    != installer.signer
                    or not 0 < profile["administrative_image_bytes"] <= 4_000_000_000
                ):
                    raise UpdateError("office_profile_mismatch")
                baseline = replace(
                    APPROVED_BASELINE,
                    display_version=".".join(approval.version.split(".")[:3]),
                    package_version=approval.version,
                    engine_version=approval.version,
                    installer_filename=Path(installer.url).name,
                    installer_size=installer.size,
                    installer_sha256=installer.sha256.upper(),
                    download_url=installer.url,
                )
                return LibreOfficeAcquisitionService(
                    self.base_dir,
                    baseline=baseline,
                    component_service=DocumentsComponentService(
                        expected_engine=approval.version
                    ),
                    user_data=True,
                    installer=OfficialAdministrativeInstaller(),
                    image_profile=stage.path,
                    approval_identity=_identity(approval),
                ).install(cancel=cancel, progress=progress, repair=True)
            finally:
                stage.cleanup()

    def _acquire(
        self, approval: Approval, cancel: threading.Event, progress
    ) -> tuple[UpdateStatus, str]:
        final = _version_dir(self.root, approval)
        active = self.root / approval.component / "active.json"
        count = sum(asset.size for asset in approval.assets)
        expanded = sum(size for size, _ in _layout(approval).values())
        if shutil.disk_usage(self.root).free < count + expanded + MINIMUM_SPACE:
            raise UpdateError("insufficient_space")
        if cancel.is_set():
            raise UpdateCancelled
        stage = create_stage(self.root, approval.component, approval.version)
        try:
            stage.set_stage("download")
            prepared = stage.path / "prepared"
            prepared.mkdir()
            already = 0
            for index, asset in enumerate(approval.assets):
                destination = stage.path / f"asset-{index}" / Path(asset.url).name
                destination.parent.mkdir()

                def report(done, _total):
                    if progress is not None:
                        progress(already + done, count)

                if asset.kind == "packaged":
                    origin = _packaged_file(self.base_dir, asset.files[0].source)
                    if not _valid_file(origin, asset.size, asset.sha256):
                        raise UpdateError("packaged_component_integrity_failed")
                    shutil.copyfile(origin, destination)
                    digest = asset.sha256
                    report(asset.size, asset.size)
                else:
                    digest = self.transport.download(
                        asset.url,
                        destination,
                        expected_size=asset.size,
                        cancel=cancel,
                        progress=report,
                        allowed_hosts=OFFICIAL_HOSTS,
                        maximum_size=count,
                    )
                if digest != asset.sha256 or _sha(destination) != asset.sha256:
                    raise UpdateError("component_sha256_mismatch")
                if asset.kind == "zip":
                    _unpack(destination, asset, prepared, cancel)
                    if asset.signer is not None:
                        for file in asset.files:
                            if file.target.endswith(".exe"):
                                _check_signer(prepared / file.target, asset.signer)
                else:
                    if asset.signer is not None:
                        _check_signer(destination, asset.signer)
                    output = prepared / asset.files[0].target
                    output.parent.mkdir(parents=True, exist_ok=True)
                    destination.rename(output)
                already += asset.size
            stage.set_stage("verified")
            _verify_layout(prepared, approval)
            verify_component(
                approval.component,
                prepared,
                stage.path / "probe",
                approval.version,
                cancel,
            )
            if cancel.is_set():
                raise UpdateCancelled
            if (
                effective_catalogue(self.base_dir).available(approval.component)
                != approval
            ):
                raise UpdateError("component_approval_changed")
            if not ordinary_component_path(final):
                raise UpdateError("redirected_component_destination")
            if final.exists():
                _verify_layout(final, approval)
                if _metadata(final / ".owned.json")["installation"] != _installation(
                    self.base_dir
                ):
                    raise UpdateError("unowned_component_version")
            else:
                record = {
                    "installation": _installation(self.base_dir),
                    "identity": _identity(approval),
                    "version": approval.version,
                    "files": _layout(approval),
                }
                atomic_component_bytes(
                    prepared / ".owned.json", canonical_catalogue(record)
                )
                final.parent.mkdir(parents=True, exist_ok=True)
                prepared.rename(final)
        finally:
            if not stage.cleanup():
                raise UpdateError("component_cleanup_pending")
        pointer = {"version": approval.version, "identity": _identity(approval)}
        atomic_component_bytes(active, canonical_catalogue(pointer))
        return UpdateStatus.UPDATED, "updated"


def remove_owned_components(base_dir: Path) -> None:
    root = runtime_package_root(base_dir)
    for name in TOOL_FILES:
        parent = root / name / "versions"
        if not parent.is_dir() or not ordinary_component_path(parent):
            continue
        recover_staging(root, name)
        with component_lock(root, name):
            removed = set()
            for package in parent.iterdir():
                if not re.fullmatch(
                    r"[0-9a-f]{24}", package.name
                ) or not ordinary_component_path(package):
                    continue
                marker = package / ".owned.json"
                try:
                    data = _metadata(marker)
                    if (
                        data.get("installation") != _installation(base_dir)
                        or data.get("identity") != package.name
                    ):
                        continue
                    files = data.get("files")
                    if not isinstance(files, dict) or not TOOL_FILES[name].issubset(
                        files
                    ):
                        continue
                    owned = [
                        (package / package_path(relative), expected)
                        for relative, expected in files.items()
                    ]
                    if not all(
                        isinstance(record, list)
                        and len(record) == 2
                        and type(record[0]) is int
                        and isinstance(record[1], str)
                        for _, record in owned
                    ):
                        continue
                except (OSError, ValueError, UpdateError):
                    continue
                directories = {package}
                blocked = False
                for path, expected in owned:
                    if _valid_file(path, *expected):
                        path.unlink()
                        directories.update(
                            directory
                            for directory in path.parents
                            if directory.is_relative_to(package)
                        )
                    elif path.exists() or not ordinary_component_path(path):
                        blocked = True
                if not blocked:
                    marker.unlink()
                    removed.add(package.name)
                    for directory in sorted(
                        directories, key=lambda item: len(item.parts), reverse=True
                    ):
                        if not any(directory.iterdir()):
                            directory.rmdir()
            pointer = root / name / "active.json"
            if pointer.is_file() and _metadata(pointer).get("identity") in removed:
                pointer.unlink()
