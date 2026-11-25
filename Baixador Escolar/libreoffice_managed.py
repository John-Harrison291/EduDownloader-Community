"""Aquisição assistida da imagem local do MSI oficial do LibreOffice."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from component_transactions import (
    ComponentFileLock,
    ManagedStage,
    component_lock,
    create_stage,
    recover_staging,
)
from documents_component import (
    ENGINE_VERSION,
    DocumentsComponentService,
    DocumentsComponentStatus,
)
from libreoffice_image import (
    profile_directory,
    prune_ui_resources,
    read_removal_catalog,
    record_office_ownership,
)
from constants import APP_VERSION, PRODUCT_EDITION, ProductEdition
from paths import (
    ManagedRootState,
    documents_conversion_temp_parent,
    get_community_install_root,
    get_managed_components_dir,
    probe_managed_root,
)

_HTTPS = "https://"
_FILENAME = "LibreOffice_26.8.3_Win_x86-64.msi"
_MIRROR_ROOT = _HTTPS + "tdf.c3sl.ufpr.br/libreoffice/stable/26.8.3/win/x86_64/"
_DOWNLOAD_HOSTS = frozenset({"tdf.c3sl.ufpr.br", "download.documentfoundation.org"})
_MAX_REDIRECTS = 3
_DOWNLOAD_TIMEOUT_SECONDS = 20
_INSTALLED_BYTES = 1_603_968_965  # Imagem administrativa x64 observada em QA.
_SAFETY_RESERVE_BYTES = 256 * 1024 * 1024
_MAX_COMPONENT_PATH_LENGTH = 100  # A PoC exigiu um destino curto.
_ACTIVE_RELATIVE_PATH = "L"
_REPAIR_RELATIVE_PATH = re.compile(r"L-repair-[0-9a-f]{8}\Z")
_MSI_USER_CANCELLED = 1602
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LibreOfficeBaseline:
    component_id: str = "edudownloader.documents.libreoffice"
    publisher: str = "The Document Foundation"
    display_version: str = "26.8.3"
    package_version: str = ENGINE_VERSION
    engine_version: str = ENGINE_VERSION
    variant: str = "MSI"
    architecture: str = "windows-x64"
    installer_filename: str = _FILENAME
    installer_size: int = 376_311_808
    installer_sha256: str = (
        "0E6918C273EABBDBBD800EE0DACBBF130A14C13C2E4CEC861B06DD59E015BF94"
    )
    authority_url: str = _HTTPS + "www.libreoffice.org/release-notes/"
    download_url: str = _MIRROR_ROOT + _FILENAME
    compatibility: str = "EduDownloader 2.5.0; DOCX/ODT via DocumentsComponentService"


APPROVED_BASELINE = LibreOfficeBaseline()


class AcquisitionStatus(StrEnum):
    INSTALLED = "installed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BUSY = "busy"
    ALREADY_INSTALLED = "already-installed"


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    status: AcquisitionStatus
    component_root: Path | None
    diagnostic_code: str


class AcquisitionError(Exception):
    """Erro técnico com código estável; não inclui URL nem path pessoal."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AcquisitionCancelled(AcquisitionError):
    def __init__(self) -> None:
        super().__init__("cancelled")


class InstallerPending(AcquisitionError):
    """Janela oficial ainda aberta; preservar payload e locks, não matar processo."""

    def __init__(self, process: subprocess.Popen) -> None:
        super().__init__("installer_pending")
        self.process = process


class InstallerRunner(Protocol):
    def run(
        self,
        installer: Path,
        destination_parent: Path,
        on_opened: Callable[[], None],
    ) -> int: ...


def _check_url(url: str) -> None:
    try:
        parts = urllib.parse.urlsplit(url)
        valid_port = parts.port in (None, 443)
    except ValueError:
        raise AcquisitionError("invalid_download_url") from None
    if (
        parts.scheme != "https"
        or parts.hostname not in _DOWNLOAD_HOSTS
        or not valid_port
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise AcquisitionError("invalid_download_url")


class LibreOfficeTransport:
    """Baixa apenas a asset pinada de um host HTTPS aprovado."""

    def download(
        self,
        baseline: LibreOfficeBaseline,
        destination: Path,
        cancel: threading.Event,
        progress: Callable[[int, int | None], None] | None = None,
    ) -> str:
        # SSL/socket só entram na memória após ação explícita de aquisição.
        # O bootstrap mantém importação sem efeitos de rede/hardware.
        import urllib.request

        class SafeRedirects(urllib.request.HTTPRedirectHandler):
            def __init__(self) -> None:
                self.count = 0

            def redirect_request(self, req, fp, code, msg, headers, newurl):
                self.count += 1
                if self.count > _MAX_REDIRECTS:
                    raise AcquisitionError("too_many_redirects")
                _check_url(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        _check_url(baseline.download_url)
        request = urllib.request.Request(
            baseline.download_url,
            headers={"User-Agent": f"EduDownloader/{APP_VERSION} (LibreOffice opt-in)"},
        )
        opener = urllib.request.build_opener(SafeRedirects())
        try:
            response = opener.open(request, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
        except (urllib.error.URLError, OSError, TimeoutError):
            raise AcquisitionError("network_failure") from None
        digest = hashlib.sha256()
        count = 0
        try:
            with response:
                _check_url(response.geturl())
                if response.status != 200:
                    raise AcquisitionError("http_failure")
                length_text = response.headers.get("Content-Length")
                length = (
                    int(length_text)
                    if length_text is not None and length_text.isdecimal()
                    else None
                )
                if length is not None and length != baseline.installer_size:
                    raise AcquisitionError("size_mismatch")
                with destination.open("xb") as output:
                    while True:
                        if cancel.is_set():
                            raise AcquisitionCancelled
                        try:
                            chunk = response.read(256 * 1024)
                        except (urllib.error.URLError, OSError, TimeoutError):
                            raise AcquisitionError("network_failure") from None
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > baseline.installer_size:
                            raise AcquisitionError("oversized_download")
                        output.write(chunk)
                        digest.update(chunk)
                        if progress is not None:
                            progress(count, length)
                    output.flush()
                    os.fsync(output.fileno())
        finally:
            response.close()
        if cancel.is_set():
            raise AcquisitionCancelled
        if count != baseline.installer_size:
            raise AcquisitionError("truncated_download")
        return digest.hexdigest().upper()


class OfficialGuidedInstaller:
    """Abre o assistente do MSI para criar uma imagem administrativa local."""

    def run(
        self,
        installer: Path,
        destination_parent: Path,
        on_opened: Callable[[], None],
    ) -> int:
        msiexec = Path(os.environ.get("SystemRoot", "")) / "System32" / "msiexec.exe"
        if not msiexec.is_absolute():
            raise AcquisitionError("installer_launch_failed")
        # Cotar o valor de TARGETDIR separadamente para o parser do MSI.
        command = subprocess.list2cmdline([str(msiexec), "/a", str(installer)])
        target = subprocess.list2cmdline([str(destination_parent)])
        try:
            process = subprocess.Popen(
                f"{command} TARGETDIR={target} /norestart",
                executable=str(msiexec),
                cwd=destination_parent,
                shell=False,
            )
        except OSError:
            raise AcquisitionError("installer_launch_failed") from None
        on_opened()
        # A interação pode demorar. Não encerra nem remove o payload enquanto
        # a janela oficial ainda estiver aberta.
        try:
            return process.wait(timeout=15 * 60)
        except subprocess.TimeoutExpired:
            raise InstallerPending(process) from None


class OfficialAdministrativeInstaller:
    """Prepara apenas uma imagem de atualização consentida no destino reservado."""

    def run(
        self, installer: Path, destination_parent: Path, on_opened: Callable[[], None]
    ) -> int:
        msiexec = Path(os.environ["SystemRoot"]) / "System32/msiexec.exe"
        command = subprocess.list2cmdline([str(msiexec), "/a", str(installer)])
        target = subprocess.list2cmdline([str(destination_parent)])
        process = subprocess.Popen(
            f"{command} TARGETDIR={target} /qn /norestart",
            executable=str(msiexec),
            cwd=destination_parent,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        on_opened()
        return process.wait()


def _verified_windows_msi(path: Path, profile_path: Path | None = None) -> bool:
    """Valida o certificado do pacote exato, sem elevar ou registrar o produto."""
    profile = json.loads(
        (
            (profile_path or profile_directory()) / "libreoffice-signatures.json"
        ).read_text("ascii")
    )
    ps = (
        Path(os.environ.get("SystemRoot", ""))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    if not ps.is_absolute() or not ps.is_file():
        return False
    completed = subprocess.run(
        [
            ps,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$ErrorActionPreference='Stop'; "
            "Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Security'); "
            "$s=Get-AuthenticodeSignature -LiteralPath $env:EDUDOWNLOADER_MSI; "
            "if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Thumbprint "
            "-eq $env:EDUDOWNLOADER_MSI_SIGNER) { exit 0 }; exit 1",
        ],
        env={
            **os.environ,
            "EDUDOWNLOADER_MSI": str(path),
            "EDUDOWNLOADER_MSI_SIGNER": profile["thumbprint"],
        },
        capture_output=True,
        shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=30,
        check=False,
    )
    return completed.returncode == 0


def _smoke_office(entrypoint: Path) -> bool:
    from zipfile import ZIP_STORED, ZipFile

    import pypdfium2
    from docx_writer import Page, Paragraph, Run, package_parts, save_parts

    token = "EduDownloader DOCX ODT"
    with tempfile.TemporaryDirectory(
        dir=documents_conversion_temp_parent(), prefix="EduDownloader-office-"
    ) as directory:
        root = Path(directory)
        docx = root / "word.docx"
        odt = root / "writer.odt"
        parts, _ = package_parts([Page(612, 792, (Paragraph((Run(token),)),))])
        with docx.open("xb") as stream:
            save_parts(parts, stream)
        with ZipFile(odt, "x") as document:
            mime = "application/vnd.oasis.opendocument.text"
            document.writestr("mimetype", mime, compress_type=ZIP_STORED)
            document.writestr(
                "META-INF/manifest.xml",
                (
                    '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
                    f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>'
                    '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                    "</manifest:manifest>"
                ),
            )
            document.writestr(
                "content.xml",
                (
                    '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
                    f"<office:body><office:text><text:p>{token}</text:p></office:text></office:body></office:document-content>"
                ),
            )
        result = subprocess.run(
            [
                entrypoint,
                "-env:UserInstallation=" + (root / "perfil").as_uri(),
                "--headless",
                "--nologo",
                "--nodefault",
                "--norestore",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                root,
                docx,
                odt,
            ],
            cwd=root,
            timeout=75,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "TEMP": str(root),
                "TMP": str(root),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return False
        for source in (docx, odt):
            pdf = source.with_suffix(".pdf")
            if not pdf.is_file():
                return False
            with pypdfium2.PdfDocument(pdf) as output:
                if len(output) != 1:
                    return False
                page = output[0]
                text = page.get_textpage()
                try:
                    if token not in text.get_text_bounded():
                        return False
                finally:
                    text.close()
                    page.close()
        return True


def managed_component_root(base_dir: Path) -> Path:
    return get_managed_components_dir(base_dir) / _ACTIVE_RELATIVE_PATH


def _active_metadata_path(base_dir: Path) -> Path:
    return get_managed_components_dir(base_dir) / "active.json"


def resolve_managed_component(base_dir: Path) -> Path | None:
    """Resolve só metadata conhecida, sem sondagem global ou fallback manual."""

    active = _active_metadata_path(base_dir)
    try:
        parent = active.parent
        if parent.is_symlink() or parent.is_junction():
            return None
        if active.is_symlink() or active.stat().st_size > 16 * 1024:
            return None
        data = json.loads(active.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if isinstance(data, dict) and data.get("schema") == 2:
        from constants import PRODUCT_EDITION, ProductEdition

        if PRODUCT_EDITION is ProductEdition.COMMUNITY:
            from component_updates import signed_office_root

            return signed_office_root(base_dir, data)
        return None
    if not isinstance(data, dict) or any(
        data.get(key) != value
        for key, value in (
            ("component_id", APPROVED_BASELINE.component_id),
            ("display_version", APPROVED_BASELINE.display_version),
            ("installer_sha256", APPROVED_BASELINE.installer_sha256),
        )
    ):
        return None
    relative = data.get("relative_path")
    if (
        len(data) == 4
        and isinstance(relative, str)
        and (
            relative == _ACTIVE_RELATIVE_PATH
            or _REPAIR_RELATIVE_PATH.fullmatch(relative)
        )
    ):
        return get_managed_components_dir(base_dir) / relative
    external = data.get("external_path")
    if (
        len(data) == 4
        and isinstance(external, str)
        and not external.startswith(("\\\\", "//"))
        and Path(external).is_absolute()
    ):
        return Path(external)
    return None


def configured_component_path(settings: dict, base_dir: Path) -> Path | str | None:
    if settings.get("documents_component_origin") == "MANAGED":
        return resolve_managed_component(base_dir)
    return settings.get("documents_component_path")


def documents_data_root() -> Path:
    """Estado externo do setup 2.0; nenhum fallback silencioso para a pasta do app."""
    value = os.environ.get("LOCALAPPDATA", "")
    if not value or not Path(value).is_absolute() or value.startswith(("\\\\", "//")):
        raise AcquisitionError("managed_root_unavailable")
    root = Path(value) / "EduDocuments"
    if any(item.is_symlink() or item.is_junction() for item in (root, *root.parents)):
        raise AcquisitionError("managed_root_unavailable")
    return root


def detected_component_path(
    settings: dict, base_dir: Path, service: DocumentsComponentService
) -> Path | None:
    """Preferência válida, sistema, estado gerenciado atual/legado; sem rede."""
    preferred = configured_component_path(settings, base_dir)
    candidates: list[Path] = []
    try:
        current = resolve_managed_component(documents_data_root())
        if current is not None:
            candidates.append(current)
            if (
                settings.get("documents_component_origin") == "MANAGED"
                and preferred is None
            ):
                preferred = current
    except AcquisitionError:
        pass
    legacy = resolve_managed_component(base_dir)
    if legacy is not None:
        candidates.append(legacy)
    installed = get_community_install_root(base_dir)
    if installed is not None:
        candidates.append(installed / "Componentes" / "LibreOffice" / ENGINE_VERSION)
    # Local de instalação orientado pela versão 1.6, sem varrer o perfil.
    profile = os.environ.get("USERPROFILE", "")
    if profile and Path(profile).is_absolute():
        candidates.append(Path(profile) / "EduDownloaderComponentes")
    result = service.discover(preferred, managed=tuple(candidates))
    return result.component.root if result.component is not None else None


def _atomic_json(path: Path, data: dict[str, str]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".active-",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump(data, output, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class LibreOfficeAcquisitionService:
    """Instala baseline pinada somente após chamada explícita da UI."""

    def __init__(
        self,
        base_dir: Path,
        *,
        baseline: LibreOfficeBaseline = APPROVED_BASELINE,
        transport: LibreOfficeTransport | None = None,
        installer: InstallerRunner | None = None,
        component_service: DocumentsComponentService | None = None,
        user_data: bool = False,
        image_profile: Path | None = None,
        approval_identity: str | None = None,
    ) -> None:
        self._user_data = user_data
        self._community_install = (
            (get_community_install_root(base_dir) or Path(base_dir).resolve())
            if user_data and PRODUCT_EDITION is ProductEdition.COMMUNITY
            else None
        )
        self.base_dir = Path(base_dir)
        self.baseline = baseline
        self._image_profile = image_profile
        self._approval_identity = approval_identity
        self._image_bytes = (
            read_removal_catalog(image_profile)[0]["administrative_image_bytes"]
            if image_profile is not None
            else _INSTALLED_BYTES
        )
        self.transport = transport or LibreOfficeTransport()
        self.installer = installer or OfficialGuidedInstaller()
        self.component_service = component_service or DocumentsComponentService()
        self._lock = threading.Lock()
        self._pending: (
            tuple[subprocess.Popen, ManagedStage, ComponentFileLock, Path, bool] | None
        ) = None

    @property
    def has_pending_installer(self) -> bool:
        return self._pending is not None

    def finish_pending_installation(self) -> AcquisitionResult | None:
        """Recheck explícito, não bloqueante, após handoff interativo demorado."""
        if not self._lock.acquire(blocking=False):
            return None
        try:
            if self._pending is None:
                return None
            process, stage, lock, parent, repair = self._pending
            code = process.poll()
            if code is None:
                return AcquisitionResult(
                    AcquisitionStatus.BUSY, None, "installer_pending"
                )
            try:
                if not stage.cleanup():
                    raise AcquisitionError("cleanup_failed")
                if code == _MSI_USER_CANCELLED:
                    return AcquisitionResult(
                        AcquisitionStatus.CANCELLED, None, "cancelled"
                    )
                if code != 0:
                    return AcquisitionResult(
                        AcquisitionStatus.FAILED, None, "installer_cancelled_or_failed"
                    )
                return self.verify_installation(
                    parent, repair=repair, _owned=True, _record_owned=True
                )
            finally:
                lock.close()
                self._pending = None
        finally:
            self._lock.release()

    def destination_parent(self, chosen: Path | None = None) -> Path:
        parent = (
            Path(chosen)
            if chosen is not None
            else managed_component_root(self.base_dir)
        )
        if not parent.is_absolute():
            raise AcquisitionError("invalid_destination")
        if len(str(parent)) > _MAX_COMPONENT_PATH_LENGTH:
            raise AcquisitionError("managed_path_too_long")
        if any(
            item.is_symlink() or item.is_junction()
            for item in (parent, *parent.parents)
        ):
            raise AcquisitionError("managed_root_unavailable")
        return parent

    def _record_owned_image(self, parent: Path, entrypoint: Path) -> None:
        if (
            self._community_install is not None
            and parent.parent == get_managed_components_dir(self.base_dir)
            and (
                parent.name == _ACTIVE_RELATIVE_PATH
                or _REPAIR_RELATIVE_PATH.fullmatch(parent.name)
            )
        ):
            profile_path = self._image_profile or profile_directory()
            profile, catalog = read_removal_catalog(profile_path)
            if profile["source_msi_sha256"].upper() != self.baseline.installer_sha256:
                raise AcquisitionError("image_profile_mismatch")
            if self._image_profile is not None:
                from libreoffice_image import IMAGE_FILES
                from component_updates import verify_office_executables

                verify_office_executables(
                    parent, profile_path, self.baseline.engine_version
                )
                destination = parent / ".edudownloader-profile"
                destination.mkdir()
                for name in IMAGE_FILES:
                    shutil.copyfile(profile_path / name, destination / name)
            prune_ui_resources(parent, catalog)
            if not _smoke_office(entrypoint):
                raise AcquisitionError("installed_smoke_failed")
            record_office_ownership(parent, self._community_install)

    def preflight(
        self, destination_parent: Path | None = None, *, repair: bool = False
    ) -> Path:
        if os.name != "nt":
            raise AcquisitionError("windows_required")
        parent = self.destination_parent(destination_parent)
        if probe_managed_root(self.base_dir).state is not ManagedRootState.AVAILABLE:
            raise AcquisitionError("managed_root_unavailable")
        if parent.exists() and not parent.is_dir():
            raise AcquisitionError("managed_root_unavailable")
        if destination_parent is not None and parent != managed_component_root(
            self.base_dir
        ):
            internal_repair = repair and parent.parent == get_managed_components_dir(
                self.base_dir
            )
            if not parent.is_dir() and not internal_repair:
                raise AcquisitionError("managed_root_unavailable")
            if parent.is_dir():
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=parent, prefix=".edudownloader-probe-"
                    ):
                        pass
                except OSError:
                    raise AcquisitionError("managed_root_unavailable") from None
        if parent.is_dir() and any(parent.iterdir()):
            raise AcquisitionError("already_installed_or_needs_repair")
        if _active_metadata_path(self.base_dir).exists() and not repair:
            raise AcquisitionError("already_installed_or_needs_repair")
        try:
            download_free = shutil.disk_usage(self.base_dir).free
            destination_free = shutil.disk_usage(
                next(
                    ancestor
                    for ancestor in (parent, *parent.parents)
                    if ancestor.exists()
                )
            ).free
        except OSError:
            raise AcquisitionError("disk_space_unavailable") from None
        except StopIteration:
            raise AcquisitionError("disk_space_unavailable") from None
        if (
            download_free < self.baseline.installer_size + _SAFETY_RESERVE_BYTES
            or destination_free < self._image_bytes + _SAFETY_RESERVE_BYTES
            or (
                os.path.splitdrive(str(parent))[0]
                == os.path.splitdrive(str(self.base_dir))[0]
                and download_free
                < self.baseline.installer_size
                + self._image_bytes
                + _SAFETY_RESERVE_BYTES
            )
        ):
            raise AcquisitionError("insufficient_disk_space")
        return parent

    def verify_installation(
        self,
        destination_parent: Path,
        *,
        repair: bool = False,
        _owned: bool = False,
        _record_owned: bool = False,
    ) -> AcquisitionResult:
        """Verifica somente o destino consentido; não procura no sistema inteiro."""

        if not _owned and not self._lock.acquire(blocking=False):
            return AcquisitionResult(AcquisitionStatus.BUSY, None, "busy")
        cross_lock: ComponentFileLock | None = None
        try:
            if not _owned:
                cross_lock = component_lock(
                    get_managed_components_dir(self.base_dir), "libreoffice"
                )
                if not cross_lock.acquire():
                    return AcquisitionResult(AcquisitionStatus.BUSY, None, "busy")
            parent = self.destination_parent(destination_parent)
            component = parent
            managed_root = get_managed_components_dir(self.base_dir)
            if (
                managed_root.is_symlink()
                or managed_root.is_junction()
                or probe_managed_root(self.base_dir).state
                is not ManagedRootState.AVAILABLE
            ):
                raise AcquisitionError("managed_root_unavailable")
            ready = self.component_service.full_verify(component)
            if (
                ready.status is not DocumentsComponentStatus.AVAILABLE
                or ready.component is None
            ):
                raise AcquisitionError("installed_structure_invalid")
            if _record_owned:
                self._record_owned_image(parent, ready.component.soffice_entrypoint)
            metadata = _active_metadata_path(self.base_dir)
            metadata.parent.mkdir(parents=True, exist_ok=True)
            if metadata.is_symlink() or metadata.is_junction():
                raise AcquisitionError("invalid_managed_metadata")
            if (
                metadata.exists()
                and resolve_managed_component(self.base_dir) != component
                and not repair
            ):
                raise AcquisitionError("already_installed_or_needs_repair")
            relative = component.name if component.parent == managed_root else None
            location = (
                {"relative_path": relative}
                if relative is not None
                and (
                    relative == _ACTIVE_RELATIVE_PATH
                    or _REPAIR_RELATIVE_PATH.fullmatch(relative)
                )
                else {"external_path": str(component)}
            )
            if self._approval_identity is None:
                active = {
                    "component_id": self.baseline.component_id,
                    "display_version": self.baseline.display_version,
                    "installer_sha256": self.baseline.installer_sha256,
                    **location,
                }
            else:
                if self._approval_identity and "relative_path" not in location:
                    raise AcquisitionError("invalid_managed_metadata")
                active = {
                    "schema": 2,
                    "version": self.baseline.engine_version,
                    "identity": self._approval_identity,
                    "relative_path": relative,
                }
            _atomic_json(metadata, active)
            return AcquisitionResult(
                AcquisitionStatus.INSTALLED, component, "installed"
            )
        except AcquisitionError as error:
            return AcquisitionResult(AcquisitionStatus.FAILED, None, error.code)
        except (OSError, ValueError, subprocess.SubprocessError):
            return AcquisitionResult(
                AcquisitionStatus.FAILED, None, "verification_failed"
            )
        finally:
            if cross_lock is not None:
                cross_lock.close()
            if not _owned:
                self._lock.release()

    def install(
        self,
        *,
        cancel: threading.Event,
        phase: Callable[[str], None] | None = None,
        progress: Callable[[int, int | None], None] | None = None,
        destination_parent: Path | None = None,
        await_launch: Callable[[Path], Path | None] | None = None,
        repair: bool = False,
    ) -> AcquisitionResult:
        if not self._lock.acquire(blocking=False):
            return AcquisitionResult(AcquisitionStatus.BUSY, None, "busy")
        managed_root = get_managed_components_dir(self.base_dir)
        download_stage: ManagedStage | None = None
        cross_lock: ComponentFileLock | None = None
        cleanup_failed = False
        operation_id = "none"
        operation_stage = "preflight"
        try:
            if self._pending is not None:
                return AcquisitionResult(
                    AcquisitionStatus.BUSY, None, "installer_pending"
                )
            if self._user_data:
                self.base_dir = documents_data_root()
                self.base_dir.mkdir(parents=True, exist_ok=True)
                managed_root = get_managed_components_dir(self.base_dir)
                recover_staging(managed_root, "libreoffice")
            cross_lock = component_lock(managed_root, "libreoffice")
            if not cross_lock.acquire():
                return AcquisitionResult(AcquisitionStatus.BUSY, None, "busy")
            if (
                self._user_data
                and _active_metadata_path(self.base_dir).exists()
                and resolve_managed_component(self.base_dir) is None
            ):
                repair = True
            if (
                destination_parent is None
                and managed_component_root(self.base_dir).exists()
                and (
                    repair
                    or (
                        self._user_data
                        and resolve_managed_component(self.base_dir) is None
                    )
                )
            ):
                destination_parent = managed_root / f"L-repair-{uuid.uuid4().hex[:8]}"
                repair = True
            parent = self.preflight(destination_parent, repair=repair)
            if cancel.is_set():
                raise AcquisitionCancelled
            managed_root.mkdir(exist_ok=True)
            download_stage = create_stage(
                managed_root, "libreoffice", self.baseline.display_version
            )
            operation_id = download_stage.path.name
            download_stage.set_stage("download")
            operation_stage = "download"
            download = download_stage.path / (
                self.baseline.installer_filename + ".part"
            )
            if phase is not None:
                phase("download")
            digest = self.transport.download(self.baseline, download, cancel, progress)
            if (
                digest != self.baseline.installer_sha256
                or download.stat().st_size != self.baseline.installer_size
                or _sha256_file(download) != self.baseline.installer_sha256
            ):
                raise AcquisitionError("hash_mismatch")
            if cancel.is_set():
                raise AcquisitionCancelled
            verified = download_stage.path / self.baseline.installer_filename
            download.rename(verified)
            download = verified
            download_stage.set_stage("verified")
            operation_stage = "verified"

            if await_launch is not None:
                chosen = await_launch(parent)
                if chosen is None:
                    raise AcquisitionCancelled
                parent = self.preflight(chosen, repair=repair)
            if cancel.is_set():
                raise AcquisitionCancelled
            if self._community_install is not None:
                signature_ok = (
                    _verified_windows_msi(download)
                    if self._image_profile is None
                    else _verified_windows_msi(download, self._image_profile)
                )
                if not signature_ok:
                    raise AcquisitionError("installer_signature_mismatch")
            parent.mkdir(parents=True, exist_ok=True)
            if phase is not None:
                phase("installer")
            download_stage.set_stage("installer")
            operation_stage = "installer"
            try:
                return_code = self.installer.run(
                    download,
                    parent,
                    lambda: phase("installer_opened") if phase else None,
                )
            except InstallerPending as pending:
                self._pending = (
                    pending.process,
                    download_stage,
                    cross_lock,
                    parent,
                    repair,
                )
                download_stage = None
                cross_lock = None
                return AcquisitionResult(
                    AcquisitionStatus.BUSY, None, "installer_pending"
                )
            if phase is not None:
                phase("verify")
            if return_code == _MSI_USER_CANCELLED:
                raise AcquisitionCancelled
            if return_code != 0:
                raise AcquisitionError("installer_cancelled_or_failed")
            if cancel.is_set():
                raise AcquisitionCancelled
            # A saída do processo não é sucesso: somente a verificação é authority.
            download_stage.set_stage("verify")
            operation_stage = "verify"
            if not download_stage.cleanup():
                raise AcquisitionError("cleanup_failed")
            download_stage = None
            return self.verify_installation(
                parent, repair=repair, _owned=True, _record_owned=True
            )
        except AcquisitionCancelled:
            LOGGER.info(
                "Aquisição LibreOffice cancelada (op=%s, etapa=%s)",
                operation_id,
                operation_stage,
            )
            return AcquisitionResult(AcquisitionStatus.CANCELLED, None, "cancelled")
        except AcquisitionError as error:
            LOGGER.warning(
                "Aquisição LibreOffice não aplicada (op=%s, etapa=%s, falha=%s)",
                operation_id,
                operation_stage,
                error.code,
            )
            return AcquisitionResult(AcquisitionStatus.FAILED, None, error.code)
        except (OSError, ValueError, subprocess.SubprocessError):
            LOGGER.warning(
                "Aquisição LibreOffice não aplicada (op=%s, etapa=%s, falha=installation_failed)",
                operation_id,
                operation_stage,
            )
            return AcquisitionResult(
                AcquisitionStatus.FAILED, None, "installation_failed"
            )
        finally:
            if download_stage is not None:
                try:
                    if not download_stage.cleanup():
                        cleanup_failed = True
                except (OSError, ValueError):
                    cleanup_failed = True
            if cross_lock is not None:
                cross_lock.close()
            self._lock.release()
            if cleanup_failed:
                # Nunca relatar sucesso com temporários próprios não removidos.
                raise AcquisitionError("cleanup_failed")
