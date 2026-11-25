"""Inventário local dos componentes externos, sem instalação ou acesso à rede."""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from threading import Lock

from component_transactions import recover_staging
from constants import PRODUCT_EDITION, ProductEdition
from documents_component import DocumentsComponentService, DocumentsComponentStatus
from downloader import locate_tools
from component_runtime import active_component
from paths import (
    ManagedRootCheck as ManagedRootCheck,
    ManagedRootState as ManagedRootState,
    get_app_dir,
    get_community_install_root,
    get_managed_components_dir,
    probe_managed_root as probe_managed_root,
)
from pdf_ocr_runtime import OcrRuntime, bundled_ocr_directory
from yt_dlp_update import recover_pending_activation, resolve_active_yt_dlp

LOGGER = logging.getLogger(__name__)
_VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}")
_VERSION_TIMEOUT_SECONDS = 3


class ComponentId(StrEnum):
    YT_DLP = "yt-dlp"
    DENO = "deno"
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"
    FFMPEG_FFPROBE = "ffmpeg-ffprobe"
    LIBREOFFICE = "libreoffice"
    OCR = "ocr"


class ComponentOrigin(StrEnum):
    BUNDLED = "bundled"
    MANAGED = "managed"
    USER_PROVIDED = "user-provided"


class ComponentCapability(StrEnum):
    DETECT = "detect"
    VERIFY = "verify"
    CHECK_UPDATE = "check-update"
    UPDATE = "update"
    INSTALL = "install"


class ComponentState(StrEnum):
    NOT_CHECKED = "not-checked"
    NOT_CONFIGURED = "not-configured"
    READY = "ready"
    MISSING = "missing"
    INVALID = "invalid"
    VERSION_MISMATCH = "version-mismatch"
    CORRUPTED = "corrupted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ComponentDefinition:
    component_id: ComponentId
    display_name: str
    origin: ComponentOrigin
    required: bool
    capabilities: frozenset[ComponentCapability]
    executable_ids: tuple[ComponentId, ...] = ()


@dataclass(frozen=True, slots=True)
class ComponentSnapshot:
    component_id: ComponentId
    display_name: str
    origin: ComponentOrigin
    required: bool
    state: ComponentState
    version: str | None
    path: Path | None
    capabilities: frozenset[ComponentCapability]
    detail: str
    executable_paths: tuple[Path, ...] = ()


_BUNDLED_CAPABILITIES = frozenset(
    {ComponentCapability.DETECT, ComponentCapability.VERIFY}
)
_YT_DLP_CAPABILITIES = _BUNDLED_CAPABILITIES | frozenset(
    {ComponentCapability.CHECK_UPDATE, ComponentCapability.UPDATE}
)
COMPONENT_REGISTRY = (
    ComponentDefinition(
        ComponentId.YT_DLP,
        "yt-dlp",
        ComponentOrigin.BUNDLED,
        True,
        _YT_DLP_CAPABILITIES,
        (ComponentId.YT_DLP,),
    ),
    ComponentDefinition(
        ComponentId.DENO,
        "Deno",
        ComponentOrigin.BUNDLED,
        True,
        _BUNDLED_CAPABILITIES,
        (ComponentId.DENO,),
    ),
    ComponentDefinition(
        ComponentId.FFMPEG_FFPROBE,
        "FFmpeg / FFprobe",
        ComponentOrigin.BUNDLED,
        True,
        _BUNDLED_CAPABILITIES,
        (ComponentId.FFMPEG, ComponentId.FFPROBE),
    ),
    ComponentDefinition(
        ComponentId.LIBREOFFICE,
        "LibreOffice",
        ComponentOrigin.USER_PROVIDED,
        False,
        _BUNDLED_CAPABILITIES | frozenset({ComponentCapability.INSTALL}),
    ),
)
if PRODUCT_EDITION is ProductEdition.COMMUNITY:
    COMPONENT_REGISTRY += (
        ComponentDefinition(
            ComponentId.OCR,
            "OCR e modelos de idioma",
            ComponentOrigin.BUNDLED,
            False,
            _BUNDLED_CAPABILITIES,
        ),
    )
_DEFINITIONS = {item.component_id: item for item in COMPONENT_REGISTRY}
_ALIASES = {
    ComponentId.FFMPEG: ComponentId.FFMPEG_FFPROBE,
    ComponentId.FFPROBE: ComponentId.FFMPEG_FFPROBE,
}
_DOCUMENT_STATES = {
    DocumentsComponentStatus.NOT_CONFIGURED: ComponentState.NOT_CONFIGURED,
    DocumentsComponentStatus.AVAILABLE: ComponentState.READY,
    DocumentsComponentStatus.INVALID: ComponentState.INVALID,
    DocumentsComponentStatus.VERSION_MISMATCH: ComponentState.VERSION_MISMATCH,
    DocumentsComponentStatus.CORRUPTED: ComponentState.CORRUPTED,
}


def _component_key(value: ComponentId | str) -> ComponentId:
    key = ComponentId(value)
    return _ALIASES.get(key, key)


def _local_version(path: Path, *arguments: str) -> str:
    result = subprocess.run(
        [str(path), *arguments],
        shell=False,
        capture_output=True,
        text=True,
        timeout=_VERSION_TIMEOUT_SECONDS,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise ValueError("version probe failed")
    first_line = result.stdout.splitlines()[:1]
    match = _VERSION_PATTERN.search(first_line[0]) if first_line else None
    if match is None:
        raise ValueError("version unavailable")
    return match.group(0)


class ComponentManager:
    """Observa componentes locais sem executar instalação ou consulta remota."""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        documents_service: DocumentsComponentService | None = None,
        documents_path: Callable[[], Path | str | None] | None = None,
        documents_managed: Callable[[], bool] | None = None,
    ) -> None:
        self._base_dir = base_dir if base_dir is not None else get_app_dir()
        self._documents_service = documents_service or DocumentsComponentService()
        self._documents_path = documents_path or (lambda: None)
        self._documents_managed = documents_managed or (lambda: False)
        self._lock = Lock()
        self._snapshots = {
            definition.component_id: self._snapshot(
                definition,
                ComponentState.NOT_CHECKED,
                None,
                None,
                "Ainda não verificado",
            )
            for definition in COMPONENT_REGISTRY
        }

    @staticmethod
    def _snapshot(
        definition: ComponentDefinition,
        state: ComponentState,
        version: str | None,
        path: Path | None,
        detail: str,
        executable_paths: tuple[Path, ...] = (),
    ) -> ComponentSnapshot:
        return ComponentSnapshot(
            definition.component_id,
            definition.display_name,
            definition.origin,
            definition.required,
            state,
            version,
            path,
            definition.capabilities,
            detail,
            executable_paths,
        )

    def list_components(self) -> tuple[ComponentSnapshot, ...]:
        with self._lock:
            return tuple(
                self._snapshots[item.component_id] for item in COMPONENT_REGISTRY
            )

    def get_component(self, component_id: ComponentId | str) -> ComponentSnapshot:
        key = _component_key(component_id)
        with self._lock:
            return self._snapshots[key]

    def refresh(self, component_id: ComponentId | str) -> ComponentSnapshot:
        key = _component_key(component_id)
        definition = _DEFINITIONS[key]
        try:
            if key in (ComponentId.YT_DLP, ComponentId.LIBREOFFICE):
                if key is ComponentId.YT_DLP:
                    recover_pending_activation(self._base_dir)
                report = recover_staging(
                    get_managed_components_dir(self._base_dir),
                    key.value,
                )
                if report.cleaned or report.unknown:
                    LOGGER.info(
                        "Staging de %s: recuperados=%d desconhecidos=%d",
                        key.value,
                        report.cleaned,
                        report.unknown,
                    )
            if key is ComponentId.LIBREOFFICE:
                snapshot = self._refresh_documents(definition)
            elif key is ComponentId.OCR:
                snapshot = self._refresh_ocr(definition)
            else:
                snapshot = self._refresh_bundled(definition)
        except Exception as error:
            LOGGER.warning(
                "Falha na verificação local de %s (%s)", key, type(error).__name__
            )
            snapshot = self._snapshot(
                definition, ComponentState.FAILED, None, None, "Falha na verificação"
            )
        with self._lock:
            self._snapshots[key] = snapshot
        return snapshot

    def refresh_all(self) -> tuple[ComponentSnapshot, ...]:
        for definition in COMPONENT_REGISTRY:
            self.refresh(definition.component_id)
        return self.list_components()

    def _refresh_bundled(self, definition: ComponentDefinition) -> ComponentSnapshot:
        tools = locate_tools(self._base_dir)
        paths = {
            ComponentId.YT_DLP: tools.yt_dlp,
            ComponentId.DENO: tools.deno,
            ComponentId.FFMPEG: tools.ffmpeg,
            ComponentId.FFPROBE: tools.ffprobe,
        }
        executable_paths = tuple(paths[item] for item in definition.executable_ids)
        display_path = (
            self._base_dir if len(executable_paths) > 1 else executable_paths[0]
        )
        if any(not path.exists() for path in executable_paths):
            return self._snapshot(
                definition,
                ComponentState.MISSING,
                None,
                display_path,
                "Executável não encontrado",
                executable_paths,
            )
        if any(not path.is_file() for path in executable_paths):
            return self._snapshot(
                definition,
                ComponentState.INVALID,
                None,
                display_path,
                "Componente inválido",
                executable_paths,
            )
        arguments = {
            ComponentId.YT_DLP: ("--version",),
            ComponentId.DENO: ("--version",),
            ComponentId.FFMPEG: ("-version",),
            ComponentId.FFPROBE: ("-version",),
        }
        versions = tuple(
            _local_version(paths[item], *arguments[item])
            for item in definition.executable_ids
        )
        if len(set(versions)) != 1:
            return self._snapshot(
                definition,
                ComponentState.VERSION_MISMATCH,
                None,
                display_path,
                "Versões incompatíveis",
                executable_paths,
            )
        snapshot = self._snapshot(
            definition,
            ComponentState.READY,
            versions[0],
            display_path,
            "Pronto",
            executable_paths,
        )
        if definition.component_id is ComponentId.YT_DLP:
            active = resolve_active_yt_dlp(self._base_dir)
            return replace(
                snapshot,
                origin=(
                    ComponentOrigin.MANAGED
                    if active.managed
                    else ComponentOrigin.BUNDLED
                ),
                detail=(
                    "Versão original disponível; atualização indisponível por problema"
                    if active.managed_issue is not None
                    else snapshot.detail
                ),
            )
        if any(path.parent != self._base_dir for path in executable_paths):
            return replace(snapshot, origin=ComponentOrigin.MANAGED)
        return snapshot

    def _refresh_ocr(self, definition: ComponentDefinition) -> ComponentSnapshot:
        managed = active_component(self._base_dir, "ocr")
        if managed is not None:
            root, version = managed
            return replace(
                self._snapshot(
                    definition,
                    ComponentState.READY,
                    version,
                    root,
                    "Pronto",
                    (root / "tesseract.exe",),
                ),
                origin=ComponentOrigin.MANAGED,
            )
        root = bundled_ocr_directory(self._base_dir)
        executable = root / "tesseract.exe"
        if not executable.is_file():
            return self._snapshot(
                definition, ComponentState.MISSING, None, root, "Motor OCR ausente"
            )
        if not OcrRuntime(root).all_models_available():
            return self._snapshot(
                definition,
                ComponentState.CORRUPTED,
                None,
                root,
                "Falha de integridade do motor ou dos modelos de idioma",
            )
        return self._snapshot(
            definition,
            ComponentState.READY,
            _local_version(executable, "--version"),
            root,
            "Pronto",
            (executable,),
        )

    def _refresh_documents(self, definition: ComponentDefinition) -> ComponentSnapshot:
        configured_path = self._documents_path()
        if self._documents_managed() and configured_path is None:
            return replace(
                self._snapshot(
                    definition,
                    ComponentState.INVALID,
                    None,
                    None,
                    "LibreOffice precisa de reparo",
                ),
                origin=ComponentOrigin.MANAGED,
            )
        check = self._documents_service.fast_check(configured_path)
        state = _DOCUMENT_STATES[check.status]
        version = (
            check.component.engine_version if check.component is not None else None
        )
        path = check.component.root if check.component is not None else None
        detail = {
            ComponentState.NOT_CONFIGURED: "Não configurado",
            ComponentState.READY: "Pronto",
            ComponentState.INVALID: "Com problema",
            ComponentState.VERSION_MISMATCH: "Versão incompatível",
            ComponentState.CORRUPTED: "Com problema",
        }[state]
        snapshot = self._snapshot(definition, state, version, path, detail)
        installation = get_community_install_root(self._base_dir)
        bundled = (
            installation is not None
            and path is not None
            and path.is_relative_to(installation / "Componentes" / "LibreOffice")
        )
        return replace(
            snapshot,
            origin=(
                ComponentOrigin.MANAGED
                if self._documents_managed() or bundled
                else ComponentOrigin.USER_PROVIDED
            ),
        )
