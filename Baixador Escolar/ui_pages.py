"""Componentes visuais persistentes da janela principal."""

from __future__ import annotations

import ntpath
import os
import stat
import tkinter as tk
import threading
import time
import unicodedata
from collections import Counter
from contextlib import nullcontext
from functools import partial
from urllib.parse import urlsplit
from math import ceil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING, Any, NamedTuple

import customtkinter as ctk
from ui_scroll import ScrollableFrame
from PIL import Image, ImageTk
from pdf_to_docx import PdfToDocxService, PdfToDocxResult
from pdf_previews import PageRenderer, PreviewSpec, PreviewWorker
from pdf_preview_ui import PagePreviewPane
from image_drag import ImageListDrag
from image_preparation import (
    ImagePreparationReader,
    ImagePreparation,
    PRINT_WARNING_PPI,
)
from pdf_results import PdfResultReader, ResultRequest, ResultInfo
from settings import PDF_PREFERENCE_CHOICES, normalize_pdf_preferences

from component_manager import (
    ComponentId,
    ComponentManager,
    ComponentOrigin,
    ComponentSnapshot,
    ComponentState,
)
from component_release_policy import ComponentReleaseObserver, ReleaseObservation

if TYPE_CHECKING:
    from component_catalog import Approval
    from component_updates import ComponentUpdateService
from paths import ManagedRootCheck, ManagedRootState, probe_managed_root
from settings import DialogFolderPreferences
from download_queue import QueueItem, QueueState
from constants import (
    DEFAULT_TEXT_SCALE,
    CONTENT_TYPES,
    CONTENT_TYPE_AUDIO,
    LEGAL_NOTICE,
    PRODUCT_EDITION,
    ProductEdition,
    VIDEO_QUALITIES,
)
from documents_component import (
    DocumentsComponentCheck,
    DocumentsComponentService,
    DocumentsComponentStatus,
)
from libreoffice_managed import (
    AcquisitionError,
    AcquisitionResult,
    AcquisitionStatus,
    LibreOfficeAcquisitionService,
)
from documents_tools import (
    DocumentConversionRequest,
    DocumentConversionResult,
    DocumentConversionStatus,
    DocumentInputFormat,
    DocumentsConversionService,
)
from file_preview import (
    DOCUMENT_PREVIEW_SUFFIXES,
    FilePreviewResult,
    FilePreviewService,
    PreviewKind,
    PreviewStatus,
)
from local_files import (
    LocalFileCategory,
    LocalFileEntry,
    LocalFileProjection,
    LocalFilesError,
    LocalFileSort,
    list_local_files,
    open_local_file,
    project_local_files,
    reveal_local_file,
    revalidate_local_file,
    validate_local_regular_file,
)
from media_tools import (
    SUPPORTED_VIDEO_SUFFIXES,
    MediaConversionProgress,
    MediaConversionResult,
    MediaOperationCancelled,
    MediaToolsError,
    MediaToolsService,
)
from media_time import parse_media_segment
from mp3_quality import DEFAULT_MP3_QUALITY, MP3_QUALITY_OPTIONS
from pdf_tools import (
    SUPPORTED_IMAGE_SUFFIXES,
    ImagesToPdfProgress,
    InvalidPageSelectionError,
    PdfImageExportResult,
    PdfOperationCancelled,
    PdfOperationProgress,
    PdfOperationResult,
    PdfToolsError,
    PdfToolsService,
    parse_page_selection,
)
from poster_tools import (
    PosterOperationCancelled,
    PosterPlan,
    PosterRequest,
    PosterResult,
    PosterService,
    PosterToolsError,
    plan_poster,
)
from print_layout import (
    ContainPlacement,
    ImagePageLayout,
    MarginPreset,
    Orientation,
    OverlapPreset,
    PaperSize,
    PdfImageQuality,
    PpiQuality,
    Rect,
    Size,
    PosterGrid,
    PosterLayout,
    choose_image_page_orientation,
    contain_image,
    image_slots,
    page_content_rect,
    page_dimensions,
    paginate_images,
)
from yt_dlp_update import (
    OfficialRelease,
    UpdateCheck,
    UpdateCheckStatus,
    UpdateError,
    UpdateResult,
    UpdateStatus,
    YtDlpUpdateService,
    resolve_active_yt_dlp,
)
from settings import (
    FavoriteFolderResult,
    add_favorite_folder,
    favorite_folder_comparison_key,
    get_favorite_folders,
    is_favorite_folder,
    remove_favorite_folder,
)
from utils import format_duration, format_size
from ui_design import (
    CANVAS,
    CARD_INSET,
    CONTROL_HEIGHT as DESIGN_CONTROL_HEIGHT,
    CONTROL_RADIUS,
    DANGER,
    DANGER_HOVER,
    DISABLED_TEXT,
    ERROR_TEXT,
    LINK,
    MUTED,
    ON_PRIMARY,
    PAGE_INSET,
    PRIMARY,
    PRIMARY_HOVER,
    SOFT,
    SOFT_HOVER,
    SURFACE,
    TEXT,
    Design,
    ToolOutputFolder,
    keyboard_control,
    reveal_scrollable_focus,
    surface,
    wrap_to_frame,
)
from ui_files_layout import FilesWorkspace
from ui_feedback import ProgressBar
from ui_motion import mix_color
from ui_settings_layout import SettingsLayout
from ui_start import CatalogPage
from ui_events import CoalescingQueue


PAGE_BACKGROUND = CANVAS
CARD_BACKGROUND = SURFACE
INSET_BACKGROUND = SOFT
CARD_BORDER = ("#DFE8F1", "#31475E")
PRIMARY_BLUE = ("#1264A3", "#3182BF")
SUCCESS_GREEN = ("#18794E", "#55CC91")
SECONDARY_BUTTON_COLOR = ("#E6EFF7", "#2A4158")
SECONDARY_BUTTON_HOVER = ("#D5E5F2", "#36536F")
SECONDARY_TEXT_COLOR = ("#1D4968", "#ECF5FC")
MUTED_TEXT_COLOR = ("#53687B", "#ADBED0")
PAGE_MARGIN = 34
CARD_RADIUS = 14
CONTROL_HEIGHT = 42
DANGER_BUTTON_COLOR = ("#B91C1C", "#DC2626")
DANGER_BUTTON_HOVER = ("#991B1B", "#B91C1C")
_PDF_SUFFIXES = frozenset({".pdf"})
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)


def _configure_if_changed(widget, **options) -> None:
    """Evita redesenhos do CTk quando as propriedades já têm o valor pedido."""
    changed = {
        name: value for name, value in options.items() if widget.cget(name) != value
    }
    if changed:
        widget.configure(**changed)


def _set_grid_visible(widget, visible: bool) -> None:
    if (widget.winfo_manager() == "grid") != visible:
        if visible:
            widget.grid()
        else:
            widget.grid_remove()


class _PreviewCanvas:
    """Reutiliza itens de um único quadro; não mantém histórico de imagens."""

    def __init__(self, canvas: tk.Canvas, key: tuple) -> None:
        self.canvas = canvas
        self.key = key
        self.items = vars(canvas).get("_edu_preview_items", [])
        self.index = 0

    def __enter__(self):
        return self

    def __exit__(self, error_type, _error, _traceback):
        for _kind, handle, _coords, _options in self.items[self.index :]:
            self.canvas.delete(handle)
        del self.items[self.index :]
        # Itens novos podem ter sido inseridos entre itens reaproveitados.
        for _kind, handle, _coords, _options in self.items:
            self.canvas.tag_raise(handle)
        self.canvas._edu_preview_items = self.items
        self.canvas._edu_preview_key = self.key if error_type is None else None

    def __getattr__(self, name):
        if not name.startswith("create_"):
            return getattr(self.canvas, name)

        def draw(*coords, **options):
            previous = self.items[self.index] if self.index < len(self.items) else None
            if previous is not None and (
                previous[0] != name or previous[3].keys() != options.keys()
            ):
                self.canvas.delete(previous[1])
                previous = None
            if previous is None:
                handle = getattr(self.canvas, name)(*coords, **options)
            else:
                _, handle, old_coords, old_options = previous
                if coords != old_coords:
                    self.canvas.coords(handle, *coords)
                changed = {
                    key: value
                    for key, value in options.items()
                    if old_options[key] != value
                }
                if changed:
                    self.canvas.itemconfigure(handle, **changed)
            item = (name, handle, coords, options)
            if self.index == len(self.items):
                self.items.append(item)
            else:
                self.items[self.index] = item
            self.index += 1
            return handle

        return draw


def _card(master: ctk.CTkBaseClass, *, inset: bool = False) -> ctk.CTkFrame:
    """Superfície discreta e legível nos dois temas."""

    return ctk.CTkFrame(
        master,
        corner_radius=CARD_RADIUS,
        fg_color=INSET_BACKGROUND if inset else CARD_BACKGROUND,
        border_width=1,
        border_color=CARD_BORDER,
    )


def _page_header(
    master: ctk.CTkBaseClass, title: str, description: str
) -> ctk.CTkFrame:
    """Mantém a mesma hierarquia de título nas sete páginas."""

    header = ctk.CTkFrame(master, fg_color="transparent")
    header.grid(row=0, column=0, padx=PAGE_MARGIN, pady=(28, 18), sticky="ew")
    ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=28, weight="bold")).pack(
        anchor="w"
    )
    ctk.CTkLabel(
        header,
        text=description,
        text_color=MUTED_TEXT_COLOR,
        anchor="w",
        justify="left",
    ).pack(anchor="w", pady=(6, 0))
    return header


def _shorten_cell(value, width, measure):
    if measure(value) <= width:
        return value
    start, end = 0, len(value)
    width -= measure("…")
    while start < end:
        middle = (start + end + 1) // 2
        if measure(value[:middle]) <= width:
            start = middle
        else:
            end = middle - 1
    return value[:start].rstrip() + "…"


def _format_count(count: int, singular: str, plural: str) -> str:
    """Formata uma contagem curta com concordância em PT-BR."""

    return f"{count} {singular if count == 1 else plural}"


def _preview_image_size(path: Path) -> tuple[Size, bool]:
    """Lê apenas metadados suficientes para o preview, com fallback seguro."""

    try:
        with Image.open(path, formats=("JPEG", "PNG")) as image:
            width, height = image.size
            exif_orientation = image.getexif().get(274)
        if exif_orientation in {5, 6, 7, 8}:
            width, height = height, width
        return Size(float(width), float(height)), False
    except Exception:
        return Size(1.0, 1.0), True


def _build_images_pdf_preview(
    paths: tuple[Path, ...],
    layout: ImagePageLayout,
) -> _ImagesPdfPreview:
    """Calcula a primeira página do preview usando os contratos de impressão."""

    groups = paginate_images(paths, layout.images_per_page)
    if not groups:
        raise ValueError("O preview requer ao menos uma imagem.")
    first_group = groups[0]
    inspected = tuple(_preview_image_size(path) for path in first_group)
    sizes = tuple(item[0] for item in inspected)
    orientation = choose_image_page_orientation(sizes, layout)
    slots = image_slots(
        layout.paper,
        orientation,
        layout.margin,
        layout.images_per_page,
    )
    return _ImagesPdfPreview(
        page_size=page_dimensions(layout.paper, orientation),
        content_rect=page_content_rect(layout.paper, orientation, layout.margin),
        slots=slots,
        placements=tuple(contain_image(size, slot) for size, slot in zip(sizes, slots)),
        failed_items=tuple(item[1] for item in inspected),
        orientation=orientation,
        total_pages=len(groups),
    )


def _build_poster_preview(path: Path, layout: PosterLayout) -> _PosterPreview:
    """Decodifica uma miniatura e planeja o painel sem usar objetos Tk."""

    renderer = PageRenderer()
    try:
        raster, image_size = renderer.image_thumbnail(path, (480, 360))
        return _PosterPreview(
            plan=plan_poster(image_size, layout), thumbnail=raster.image()
        )
    finally:
        renderer.close()


def _poster_quality_message(quality: PpiQuality) -> str:
    """Traduz a avaliação técnica do motor para linguagem simples."""

    return {
        PpiQuality.OK: "Qualidade adequada para este tamanho.",
        PpiQuality.LOW: "A imagem pode perder definição neste tamanho.",
        PpiQuality.VERY_LOW: ("A imagem pode ficar bastante pixelada neste tamanho."),
    }[quality]


def _validated_handoff_file(
    value: Path | str,
    supported_suffixes: frozenset[str],
) -> Path | None:
    """Valida somente existência, tipo regular e extensão para um handoff local."""

    try:
        path = Path(value)
        if path.suffix.casefold() not in supported_suffixes:
            return None
        metadata = os.stat(path, follow_symlinks=False)
    except (OSError, TypeError, ValueError):
        return None
    if not stat.S_ISREG(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    ):
        return None
    return path


@dataclass(frozen=True)
class DownloadsPageActions:
    """Ações fornecidas pelo shell sem acoplar a página ao serviço."""

    on_link_enter: Callable[[tk.Event[tk.Misc]], str]
    paste_link: Callable[[], None]
    clear_link: Callable[[], None]
    adapt_quality: Callable[[], None]
    change_quality: Callable[[str], None]
    start_download: Callable[[], None]
    cancel_download: Callable[[], None]
    open_downloads: Callable[[], None]
    choose_destination: Callable[[], None]
    open_result_file: Callable[[], None]
    open_result_folder: Callable[[], None]
    cancel_item: Callable[[str], None] | None = None
    remove_item: Callable[[str], None] | None = None
    open_item_file: Callable[[str], None] | None = None
    open_item_folder: Callable[[str], None] | None = None
    retry_queue: Callable[[], None] | None = None
    retry_item: Callable[[str], None] | None = None
    review_item: Callable[[str], None] | None = None
    recent_result_path: Callable[[], Path | None] | None = None


@dataclass(frozen=True)
class PdfPageActions:
    """Dialogs run on Tk; result opening callbacks run on the result worker."""

    show_info: Callable[[str], None]
    show_warning: Callable[[str], None]
    show_error: Callable[[str], None]
    confirm_overwrite: Callable[[str], bool]
    open_result_file: Callable[[Path], bool] | None = None
    open_result_folder: Callable[[Path], bool] | None = None
    notify: Callable[[str, str], None] | None = None


@dataclass(frozen=True)
class MediaPageActions:
    """Diálogos do shell usados pela página de conversões de mídia."""

    show_info: Callable[[str], None]
    show_warning: Callable[[str], None]
    show_error: Callable[[str], None]
    confirm_overwrite: Callable[[str], bool]
    open_result_file: Callable[[Path], bool] | None = None
    open_result_folder: Callable[[Path], bool] | None = None
    notify: Callable[[str, str], None] | None = None


@dataclass(frozen=True)
class DocumentsPageActions:
    """Ações do shell usadas pela página de documentos."""

    show_info: Callable[[str], None]
    show_warning: Callable[[str], None]
    show_error: Callable[[str], None]
    confirm_overwrite: Callable[[str], bool]
    persist_component_path: Callable[[Path | None], bool]
    open_result_file: Callable[[Path], bool]
    open_result_folder: Callable[[Path], bool]
    start_component_install: Callable[[], None] | None = None
    notify: Callable[[str, str], None] | None = None


@dataclass(frozen=True)
class FilesPageActions:
    """Ações do hub fornecidas pelo shell sem acoplar páginas persistentes."""

    show_warning: Callable[[str], None]
    show_error: Callable[[str], None]
    extract_pages: Callable[[Path], bool]
    pdf_to_images: Callable[[Path], bool]
    image_to_pdf: Callable[[Path], bool]
    video_to_mp3: Callable[[Path], bool]
    create_poster: Callable[[Path], bool] | None = None
    docx_to_pdf: Callable[[Path], bool] | None = None
    odt_to_pdf: Callable[[Path], bool] | None = None
    txt_to_pdf: Callable[[Path], bool] | None = None
    pdf_to_docx: Callable[[Path], bool] | None = None


@dataclass(frozen=True)
class _PdfWorkerResult:
    callback: Callable[[Any], None]
    value: Any = None
    error_message: str | None = None
    operation: str = "general"
    generation: int = 0
    cancelled: bool = False


@dataclass(frozen=True)
class _ImagesPdfPreview:
    """Geometria pequena e independente de Tk para uma página de preview."""

    page_size: Size
    content_rect: Rect
    slots: tuple[Rect, ...]
    placements: tuple[ContainPlacement, ...]
    failed_items: tuple[bool, ...]
    orientation: Orientation
    total_pages: int


@dataclass(frozen=True)
class _ImagesPdfPreviewResult:
    generation: int
    preview: _ImagesPdfPreview | None = None
    failed: bool = False


@dataclass(frozen=True)
class _PosterPreview:
    """Plano e miniatura preparados fora da thread Tk."""

    plan: PosterPlan
    thumbnail: Image.Image


@dataclass(frozen=True)
class _PosterPreviewResult:
    generation: int
    preview: _PosterPreview | None = None
    failed: bool = False


class _ImagesPdfUiState(str, Enum):
    READY = "ready"
    PROCESSING = "processing"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class _PdfOperationUiState(str, Enum):
    READY = "ready"
    PROCESSING = "processing"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(frozen=True)
class _MergeMetadataResult:
    generation: int
    details: tuple[tuple[Path, str], ...]


@dataclass(frozen=True)
class _MediaWorkerResult:
    value: MediaConversionResult | None = None
    error_message: str | None = None
    cancelled: bool = False


class MediaUiState(str, Enum):
    IDLE = "IDLE"
    READY = "READY"
    PREPARING = "PREPARING"
    CONVERTING = "CONVERTING"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class _MediaCancelResult:
    accepted: bool = False
    error_message: str | None = None


class DocumentsUiState(str, Enum):
    """Estados públicos da conversão documental."""

    READY = "READY"
    PREPARING = "PREPARING"
    CONVERTING = "CONVERTING"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"
    COMPONENT_UNAVAILABLE = "COMPONENT_UNAVAILABLE"


_DOCUMENTS_STATE_TEXT = {
    DocumentsUiState.READY: "Pronto para converter",
    DocumentsUiState.PREPARING: "Preparando documento...",
    DocumentsUiState.CONVERTING: "Convertendo documento...",
    DocumentsUiState.CANCELLING: "Cancelando...",
    DocumentsUiState.COMPLETED: "PDF criado.",
    DocumentsUiState.CANCELLED: "Conversão cancelada.",
    DocumentsUiState.ERROR: "Não foi possível converter este documento. Verifique o arquivo e tente novamente.",
    DocumentsUiState.COMPONENT_UNAVAILABLE: (
        "LibreOffice indisponível. Verifique a configuração; TXT para PDF funciona sem ele."
    ),
}

_DOCUMENT_OPERATION_LABELS = {
    DocumentInputFormat.DOCX: "Word para PDF",
    DocumentInputFormat.TXT: "Texto para PDF",
    DocumentInputFormat.ODT: "OpenDocument para PDF",
}
_DOCUMENT_OPERATION_BY_LABEL = {
    label: operation for operation, label in _DOCUMENT_OPERATION_LABELS.items()
}
_DOCUMENT_OPERATION_DETAILS = {
    DocumentInputFormat.DOCX: (
        "Selecione um documento DOCX e escolha onde salvar o PDF.",
        "Selecionar DOCX",
        "Selecione o documento do Word",
        ("Documentos do Word", "*.docx"),
        "Selecione um documento DOCX local e válido.",
    ),
    DocumentInputFormat.TXT: (
        "Selecione um texto UTF-8 e escolha onde salvar o PDF.",
        "Selecionar TXT",
        "Selecione o arquivo de texto",
        ("Arquivos de texto", "*.txt"),
        "Selecione um arquivo TXT local e válido.",
    ),
    DocumentInputFormat.ODT: (
        "Selecione um documento ODT e escolha onde salvar o PDF.",
        "Selecionar ODT",
        "Selecione o documento OpenDocument",
        ("Documentos OpenDocument", "*.odt"),
        "Selecione um documento ODT local e válido.",
    ),
}


@dataclass(frozen=True)
class _DocumentsComponentWorkerResult:
    generation: int
    check: DocumentsComponentCheck
    component_root: Path | None
    persist_choice: bool = False


@dataclass(frozen=True)
class _DocumentsWorkerResult:
    generation: int
    result: DocumentConversionResult


@dataclass(frozen=True)
class _MediaShutdownResult:
    generation: int
    accepted: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class _FilesScanResult:
    directory: Path
    replace_directory: bool
    entries: tuple[LocalFileEntry, ...] | None = None
    error_message: str | None = None


class _PreviewVisualState(str, Enum):
    EMPTY = "empty"
    LOADING = "loading"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


@dataclass(frozen=True)
class _FilesPreviewRequest:
    generation: int
    directory: Path
    entry: LocalFileEntry
    cancel_event: threading.Event = field(
        default_factory=threading.Event, compare=False
    )


@dataclass(frozen=True)
class _FilesPreviewWorkerResult:
    request: _FilesPreviewRequest
    preview: FilePreviewResult


def _favorite_folder_choices(folders: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Cria rótulos curtos e únicos sem expor caminhos absolutos na interface."""

    records: list[tuple[str, str, str, str]] = []
    basename_counts: dict[str, int] = {}
    for folder in folders:
        normalized = ntpath.normpath(folder)
        drive, _tail = ntpath.splitdrive(normalized)
        basename = ntpath.basename(normalized) or drive or "Pasta"
        parent = ntpath.basename(ntpath.dirname(normalized))
        basename_key = unicodedata.normalize("NFC", basename).casefold()
        basename_counts[basename_key] = basename_counts.get(basename_key, 0) + 1
        records.append((folder, basename, parent, drive))

    choices: list[tuple[str, str]] = []
    used_labels: set[str] = set()
    for folder, basename, parent, drive in records:
        basename_key = unicodedata.normalize("NFC", basename).casefold()
        context = parent if parent and parent != basename else drive
        label = (
            f"{basename} — {context}"
            if basename_counts[basename_key] > 1 and context
            else basename
        )
        base_label = label
        suffix = 2
        label_key = unicodedata.normalize("NFC", label).casefold()
        while label_key in used_labels:
            label = f"{base_label} ({suffix})"
            label_key = unicodedata.normalize("NFC", label).casefold()
            suffix += 1
        used_labels.add(label_key)
        choices.append((label, folder))
    return tuple(choices)


class _DownloadRow(NamedTuple):
    frame: ctk.CTkFrame
    title: ctk.CTkLabel
    detail: ctk.CTkLabel
    progress: ctk.CTkProgressBar
    action: ctk.CTkButton
    open_file: ctk.CTkButton
    open_folder: ctk.CTkButton
    retry: ctk.CTkButton
    review: ctk.CTkButton
    feedback: ctk.CTkLabel
    percentage: ctk.CTkLabel
    badge: ctk.CTkLabel


class DownloadsPage(CatalogPage):
    """Formulário persistente e projeção da fila real de downloads."""

    _ACTIVE_STATES = frozenset(
        {
            QueueState.PREPARING,
            QueueState.DOWNLOADING,
            QueueState.PROCESSING,
            QueueState.VERIFYING,
        }
    )

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        design: Design,
        *,
        content_type: tk.StringVar,
        quality: tk.StringVar,
        status: tk.StringVar,
        actions: DownloadsPageActions,
    ) -> None:
        super().__init__(
            master,
            design,
            "Downloads",
            "Cole o link, escolha o formato e acompanhe o resultado.",
        )
        self.destination_text = tk.StringVar(master=self, value="Downloads (padrão)")
        self._queue_actions = actions
        self._queue_rows = {}
        self._queue_result_paths = frozenset()
        self._queue_positions = {}
        self._queue_displayed = {}
        self._queue_pending = {}
        self._queue_render_after_id = None
        self._queue_closing = False

        self._build_form(content_type, quality, actions)
        self._featured_download = ctk.CTkFrame(self, fg_color="transparent")
        self._featured_download.grid_columnconfigure(0, weight=1)
        self._append(self._featured_download)
        self._featured_download.grid_remove()
        self._build_activity(status, actions)
        notice = design.label(
            self, LEGAL_NOTICE, color=MUTED, font=design.small, wraplength=390
        )
        self._append(notice)
        wrap_to_frame(self, notice, reserved=2 * PAGE_INSET)

    def reveal_keyboard_focus(self, widget: tk.Misc) -> None:
        """Rola somente quando o Tab alcança um controle fora da área visível."""
        reveal_scrollable_focus(self, widget)

    def _build_form(self, content_type, quality, actions):
        design = self.design
        card = surface(self)
        self._form = card
        self._append(card)
        card.grid_columnconfigure(0, weight=1)
        design.label(card, "Link do conteúdo", font=design.control).grid(
            row=0, column=0, padx=CARD_INSET, pady=(18, 6), sticky="w"
        )
        link = ctk.CTkFrame(card, fg_color="transparent")
        link.grid(row=1, column=0, padx=CARD_INSET, sticky="ew")
        link.grid_columnconfigure(0, weight=1)
        self.link_entry = design.entry(link, "Cole o endereço do vídeo ou áudio…")
        self.link_entry.configure(height=48, border_color=LINK)
        self.link_entry.bind("<Return>", actions.on_link_enter)
        self.link_entry.bind(
            "<FocusIn>",
            lambda _event: self.link_entry.configure(border_width=2),
            add="+",
        )
        self.link_entry.bind(
            "<FocusOut>",
            lambda _event: self.link_entry.configure(border_width=0),
            add="+",
        )
        self.link_entry.grid(row=0, column=0, sticky="ew")
        self.paste_button = design.button(
            link,
            "Colar link",
            actions.paste_link,
            kind="secondary",
            width=100,
            keyboard=True,
        )
        self.clear_button = design.button(
            link,
            "Limpar",
            actions.clear_link,
            kind="secondary",
            width=80,
            keyboard=True,
        )
        self.paste_button.grid(row=0, column=1, padx=(8, 0))
        self.clear_button.grid(row=0, column=2, padx=(8, 0))

        options = ctk.CTkFrame(card, fg_color="transparent")
        options.grid(row=2, column=0, padx=CARD_INSET, pady=(14, 12), sticky="ew")
        options.grid_columnconfigure((0, 2), weight=1, uniform="option")
        options.grid_columnconfigure(1, minsize=16)
        design.label(options, "Formato", font=design.control).grid(
            row=0, column=0, sticky="w"
        )
        self.quality_label = design.label(options, "Qualidade", font=design.control)
        self.quality_label.grid(row=0, column=2, sticky="w")

        right_padding = None

        def size_options(event):
            nonlocal right_padding
            width = int(card._reverse_widget_scaling(event.width))
            padding = max(CARD_INSET, width - CARD_INSET - 660)
            if padding != right_padding:
                options.grid_configure(padx=(CARD_INSET, padding))
                right_padding = padding

        tk.Misc.bind(card, "<Configure>", size_options, add="+")
        formats = ctk.CTkFrame(options, fg_color="transparent")
        formats.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        formats.grid_columnconfigure((0, 2), weight=1, uniform="format")
        formats.grid_columnconfigure(1, minsize=8)
        self.content_type_buttons = []

        def choose(value):
            if content_type.get() != value:
                content_type.set(value)
                actions.adapt_quality()

        for index, value in enumerate(CONTENT_TYPES):
            button = design.button(
                formats,
                value,
                partial(choose, value),
                kind="secondary",
                width=62,
                keyboard=True,
            )
            button.grid(row=0, column=index * 2, sticky="ew")
            self.content_type_buttons.append(button)

        self.quality_menu = ctk.CTkOptionMenu(
            options,
            values=list(VIDEO_QUALITIES),
            variable=quality,
            width=156,
            height=DESIGN_CONTROL_HEIGHT,
            corner_radius=CONTROL_RADIUS,
            dynamic_resizing=False,
            command=actions.change_quality,
            fg_color=SOFT,
            button_color=SOFT,
            button_hover_color=SOFT_HOVER,
            text_color=TEXT,
            text_color_disabled=DISABLED_TEXT,
            font=design.nav,
            dropdown_fg_color=SURFACE,
            dropdown_hover_color=SOFT_HOVER,
            dropdown_text_color=TEXT,
            dropdown_font=design.nav,
        )
        keyboard_control(
            self.quality_menu,
            self.quality_menu._clicked,
            show_focus=lambda focused: self.quality_menu.configure(
                button_color=SOFT_HOVER if focused else SOFT
            ),
        )
        self.quality_menu.grid(row=1, column=2, pady=(4, 0), sticky="ew")
        self.quality_hint = design.label(
            options, "", color=MUTED, font=design.small, height=20
        )
        self.quality_hint.grid(row=2, column=2, pady=(3, 0), sticky="w")

        destination = ctk.CTkFrame(card, fg_color="transparent")
        destination.grid(row=3, column=0, padx=CARD_INSET, sticky="ew")
        destination.grid_columnconfigure(0, weight=1)
        design.label(destination, "Salvar em", font=design.control).grid(
            row=0, column=0, sticky="w"
        )
        self.destination_label = design.label(
            destination,
            "",
            textvariable=self.destination_text,
            color=MUTED,
            font=design.small,
            wraplength=280,
        )
        self.destination_label.grid(row=1, column=0, pady=(0, 8), sticky="ew")
        self.change_destination_button = design.button(
            destination,
            "Alterar pasta",
            actions.choose_destination,
            kind="secondary",
            width=114,
            keyboard=True,
        )
        self.change_destination_button.grid(row=0, column=1, rowspan=2, padx=(8, 0))
        wrap_to_frame(destination, self.destination_label, reserved=130)

        self.download_button = design.button(
            card,
            "Adicionar à fila",
            actions.start_download,
            width=230,
            keyboard=True,
        )
        self.download_button.grid(
            row=4, column=0, padx=CARD_INSET, pady=(14, 2), sticky="w"
        )
        design.label(
            card,
            "Pressione Enter no link para adicionar à fila.",
            font=design.small,
            color=MUTED,
        ).grid(row=5, column=0, padx=CARD_INSET, pady=(0, 14), sticky="w")
        self.show_format(content_type.get())

    def show_format(self, selected: str) -> None:
        for value, button in zip(CONTENT_TYPES, self.content_type_buttons, strict=True):
            active = value == selected
            _configure_if_changed(
                button,
                fg_color=PRIMARY if active else SOFT,
                hover_color=PRIMARY_HOVER if active else SOFT_HOVER,
                text_color=ON_PRIMARY if active else TEXT,
            )

    def _build_activity(self, status, actions):
        design = self.design
        compact = PRODUCT_EDITION is ProductEdition.COMMUNITY
        summary = ctk.CTkFrame(self) if compact else surface(self)
        if not compact:
            self._append(summary)
        action_parent = self._form if compact else summary
        action_row = 6 if compact else 2
        summary.grid_columnconfigure(0, weight=1)
        self._activity_title = design.label(
            summary, "Nenhum download em andamento", font=design.card_title
        )
        self._activity_title.grid(
            row=0, column=0, padx=CARD_INSET, pady=(12, 0), sticky="w"
        )
        self._empty_message = design.label(
            summary,
            "Adicione um link à fila para começar.",
            color=MUTED,
            font=design.small,
            height=22,
        )
        self._empty_message.grid(row=1, column=0, padx=CARD_INSET, sticky="w")
        self.open_downloads_button = design.button(
            action_parent,
            "Abrir pasta de downloads",
            actions.open_downloads,
            kind="secondary",
            width=200,
            keyboard=True,
        )
        self.open_downloads_button.grid(
            row=action_row,
            column=0,
            padx=CARD_INSET,
            pady=(0 if compact else 8, 14),
            sticky="w",
        )

        self._summary_status = design.label(
            summary, "", textvariable=status, font=design.small, color=MUTED
        )
        self._summary_status.grid(
            row=1, column=0, padx=CARD_INSET, pady=(0, 12), sticky="w"
        )
        self._summary_status.grid_remove()
        # As medições da operação aparecem no próprio cartão do item.
        self.progress_bar = ProgressBar(summary, progress_color=PRIMARY, fg_color=SOFT)
        self.progress_bar.set(0)

        self.queue_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._append(self.queue_frame)
        self.queue_frame.grid_columnconfigure(0, weight=1)
        self.queue_frame.grid_remove()
        queue_header = ctk.CTkFrame(self.queue_frame, fg_color="transparent")
        queue_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        queue_header.grid_remove()
        self._queue_header = queue_header
        self._waiting_count = design.label(
            queue_header, "", font=design.small, color=MUTED
        )
        self._waiting_count.grid(row=0, column=0, padx=(0, 12), sticky="w")
        self.retry_queue_button = design.button(
            queue_header,
            "Retomar fila",
            actions.retry_queue,
            state="disabled",
            kind="secondary",
            width=125,
            keyboard=True,
        )
        self.retry_queue_button.grid(row=0, column=1, sticky="w")
        self.retry_queue_button.grid_remove()

        shortcuts = ctk.CTkFrame(action_parent, fg_color="transparent")
        shortcuts.grid(
            row=action_row, column=0, padx=CARD_INSET, pady=(0, 14), sticky="e"
        )
        self.cancel_button = design.button(
            summary,
            "Cancelar atual",
            actions.cancel_download,
            kind="danger",
            state="disabled",
            width=130,
            keyboard=True,
        )
        self.cancel_button.grid(
            row=1, column=0, padx=CARD_INSET, pady=(0, 12), sticky="e"
        )
        self.cancel_button.grid_remove()
        self.open_result_file_button = design.button(
            shortcuts,
            "Abrir arquivo",
            actions.open_result_file,
            kind="secondary",
            width=108,
            state="disabled",
            keyboard=True,
        )
        self.open_result_folder_button = design.button(
            shortcuts,
            "Abrir pasta",
            actions.open_result_folder,
            kind="secondary",
            width=98,
            state="disabled",
            keyboard=True,
        )
        self.open_result_file_button.grid(row=0, column=0, padx=(0, 6))
        self.open_result_folder_button.grid(row=0, column=1)
        self._result_shortcuts = shortcuts
        shortcuts.grid_remove()

    def _show_activity(self, items, *, blocked, closing):
        compact = PRODUCT_EDITION is ProductEdition.COMMUNITY
        waiting = (
            sum(item.state == QueueState.WAITING for item in items) if compact else 0
        )
        if not compact:
            active = any(item.state in self._ACTIVE_STATES for item in items)
            _configure_if_changed(
                self._activity_title,
                text="Fila de downloads" if items else "Nenhum download em andamento",
            )
            self._display(self._empty_message, not items)
            self._display(self._summary_status, bool(items))
            self._display(self.cancel_button, active and not closing)
        count = (
            "1 download aguardando"
            if waiting == 1
            else f"{waiting} downloads aguardando"
        )
        _configure_if_changed(self._waiting_count, text=count)
        self._display(self._waiting_count, bool(waiting))
        self._display(self.retry_queue_button, blocked)
        self._display(self._queue_header, bool(waiting) or blocked)
        self._display(self._featured_download, bool(items))
        self._display(self.queue_frame, len(items) > 1 or bool(waiting) or blocked)

    @staticmethod
    def _display(widget, visible):
        if bool(widget.grid_info()) != visible:
            if visible:
                widget.grid()
            else:
                widget.grid_remove()

    def show_queue_items(
        self, items: tuple[QueueItem, ...], *, blocked: bool, closing: bool
    ) -> None:
        """Agenda somente linhas alteradas; widgets existentes mantêm identidade."""
        if closing != self._queue_closing:
            self._queue_closing = closing
            self._queue_displayed.clear()
        _configure_if_changed(
            self.retry_queue_button,
            state="normal" if blocked and not closing else "disabled",
        )
        self._queue_result_paths = frozenset(
            item.result.final_output_path for item in items if item.result is not None
        )
        self._show_activity(items, blocked=blocked, closing=closing)
        current = {item.id: item for item in items}
        # A tarefa ativa fica acima da espera. A ordem da espera continua sendo FIFO.
        active = [item for item in items if item.state in DownloadsPage._ACTIVE_STATES]
        waiting = [item for item in items if item.state == QueueState.WAITING]
        recent = [
            item
            for item in reversed(items)
            if item.state not in DownloadsPage._ACTIVE_STATES
            and item.state != QueueState.WAITING
        ]
        positions = {
            item.id: index for index, item in enumerate((*active, *waiting, *recent), 1)
        }
        for item_id in set(self._queue_rows) | set(self._queue_pending):
            if item_id not in current:
                self._queue_pending[item_id] = None
        for item in items:
            if (
                self._queue_displayed.get(item.id) != item
                or item.id in self._queue_pending
                or self._queue_positions.get(item.id) != positions[item.id]
            ):
                self._queue_pending[item.id] = item
        self._queue_positions = positions
        if self._queue_pending and self._queue_render_after_id is None:
            self._queue_render_after_id = self.after_idle(self._render_queue_batch)

    def _render_queue_batch(self) -> None:
        self._queue_render_after_id = None
        deadline = time.monotonic() + 0.008
        count = 0
        while self._queue_pending and count < 4 and time.monotonic() < deadline:
            item_id = next(iter(self._queue_pending))
            item = self._queue_pending.pop(item_id)
            count += 1
            if item is None:
                row = self._queue_rows.pop(item_id, None)
                if row is not None:
                    row.frame.destroy()
                self._queue_displayed.pop(item_id, None)
                continue
            if item_id not in self._queue_rows:
                self._queue_rows[item_id] = self._make_queue_row(item_id)
            row = self._queue_rows[item_id]
            position = self._queue_positions[item_id]
            if int(row.frame.grid_info()["row"]) != position:
                self._place_queue_row(row.frame, position)
            if self._queue_displayed.get(item_id) != item:
                self._update_queue_row(row, item)
                self._queue_displayed[item_id] = item
        if self._queue_pending:
            self._queue_render_after_id = self.after(1, self._render_queue_batch)

    def _make_queue_row(self, item_id: str) -> _DownloadRow:
        design = self.design
        frame = surface(self)
        self._place_queue_row(frame, self._queue_positions[item_id])
        frame.grid_columnconfigure(1, weight=1)
        badge = ctk.CTkLabel(
            frame,
            text="",
            fg_color=SOFT,
            text_color=LINK,
            font=design.control,
            corner_radius=CONTROL_RADIUS,
            width=58,
        )
        badge.grid(
            row=0, column=0, rowspan=3, padx=(CARD_INSET, 0), pady=(12, 10), sticky="ns"
        )
        title = design.label(frame, "", font=design.card_title, wraplength=370)
        title.grid(
            row=0, column=1, columnspan=2, padx=CARD_INSET, pady=(12, 0), sticky="ew"
        )
        detail = design.label(frame, "", color=MUTED, font=design.small, wraplength=370)
        detail.grid(row=1, column=1, columnspan=2, padx=CARD_INSET, sticky="ew")
        feedback = design.label(frame, "", font=design.small, wraplength=330)
        feedback.grid(row=2, column=1, padx=CARD_INSET, pady=(0, 10), sticky="ew")
        percentage = design.label(frame, "", font=design.control, color=LINK)
        percentage.grid(row=2, column=2, padx=(0, CARD_INSET), pady=(0, 10), sticky="e")
        wrap_to_frame(frame, title, detail, feedback, reserved=2 * CARD_INSET + 70)

        progress = ProgressBar(frame, height=8, fg_color=SOFT, progress_color=PRIMARY)
        progress.grid(
            row=3, column=0, columnspan=3, padx=CARD_INSET, pady=(0, 12), sticky="ew"
        )
        controls = ctk.CTkFrame(frame, fg_color="transparent")
        controls.grid(
            row=4, column=0, columnspan=3, padx=CARD_INSET, pady=(0, 14), sticky="ew"
        )
        controls.grid_columnconfigure(3, weight=1)
        actions = self._queue_actions
        action = design.button(
            controls,
            "Cancelar",
            partial(self._queue_row_action, item_id),
            kind="secondary",
            width=128,
            keyboard=True,
        )
        open_file = design.button(
            controls,
            "Abrir arquivo",
            partial(self._call_item_action, actions.open_item_file, item_id),
            width=108,
            keyboard=True,
        )
        open_folder = design.button(
            controls,
            "Abrir pasta",
            partial(self._call_item_action, actions.open_item_folder, item_id),
            kind="secondary",
            width=98,
            keyboard=True,
        )
        retry = design.button(
            controls,
            "Tentar novamente",
            partial(self._call_item_action, actions.retry_item, item_id),
            width=132,
            keyboard=True,
        )
        review = design.button(
            controls,
            "Verificar link",
            partial(self._call_item_action, actions.review_item, item_id),
            kind="secondary",
            width=104,
            keyboard=True,
        )
        # As ações por estado compartilham as mesmas posições, sem reconstruir widgets.
        for widget, column in (
            (open_file, 0),
            (retry, 0),
            (open_folder, 1),
            (review, 1),
            (action, 2),
        ):
            widget.grid(row=0, column=column, padx=(0, 8), sticky="w")
        return _DownloadRow(
            frame,
            title,
            detail,
            progress,
            action,
            open_file,
            open_folder,
            retry,
            review,
            feedback,
            percentage,
            badge,
        )

    def _place_queue_row(self, frame, position):
        featured = position == 1
        # O mesmo widget volta à fila quando perde prioridade.
        frame.grid(
            in_=self._featured_download if featured else self.queue_frame,
            row=position,
            column=0,
            pady=(0, 0 if featured else 12),
            sticky="ew",
        )

    def _call_item_action(self, callback, item_id):
        if callback is not None and not self._queue_closing:
            callback(item_id)

    def _update_queue_row(self, row: _DownloadRow, item: QueueItem) -> None:
        terminal = item.state in {
            QueueState.COMPLETED,
            QueueState.CANCELLED,
            QueueState.ERROR,
        }
        state_name = {
            QueueState.WAITING: "Aguardando na fila",
            QueueState.PREPARING: "Preparando download",
            QueueState.DOWNLOADING: "Baixando",
            QueueState.PROCESSING: "Processando arquivo",
            QueueState.VERIFYING: "Verificando arquivo...",
            QueueState.COMPLETED: "Download concluído",
            QueueState.CANCELLED: "Download cancelado",
            QueueState.ERROR: "Não foi possível concluir o download",
        }[item.state]
        if item.cancel_requested and not terminal:
            state_name = "Cancelando download…"
        filename = item.result.file_path.name if item.result else None
        if filename or item.state == QueueState.ERROR:
            heading = filename or state_name
        else:
            host = urlsplit(item.request.url).hostname
            heading = host or "Download"
        _configure_if_changed(row.title, text=heading)
        profile = (
            item.request.mp3_quality.display_label
            if item.request.content_type == CONTENT_TYPE_AUDIO
            else item.request.quality
        )
        _configure_if_changed(
            row.detail, text=f"{item.request.content_type} • {profile}"
        )
        self._display(row.detail, item.state != QueueState.ERROR)
        feedback = [
            (item.error or "Verifique o link e tente novamente.")
            if item.state == QueueState.ERROR
            else state_name
        ]

        transfer = (
            item.progress
            if item.state == QueueState.DOWNLOADING and not item.cancel_requested
            else None
        )
        percent = transfer.percent if transfer else None
        measured = percent is not None and percent < 100
        if measured:
            _configure_if_changed(row.percentage, text=f"{percent:.1f}%")
        self._display(row.percentage, measured)
        if transfer and transfer.speed is not None:
            feedback.append(f"{format_size(transfer.speed)}/s")
        if transfer and transfer.eta is not None:
            feedback.append(f"Restam {format_duration(transfer.eta)}")
        fraction = (
            percent / 100 if measured else float(item.state == QueueState.COMPLETED)
        )
        show_progress = (
            item.state
            in {QueueState.DOWNLOADING, QueueState.PROCESSING, QueueState.VERIFYING}
            and not item.cancel_requested
        )
        mode = "indeterminate" if show_progress and not measured else "determinate"
        if row.progress.cget("mode") != mode:
            row.progress.stop()
            row.progress.configure(mode=mode)
            if mode == "indeterminate":
                row.progress.start()
        if row.progress.get() != fraction:
            row.progress.set(fraction)
        self._display(row.progress, show_progress)

        detail_color = {
            QueueState.COMPLETED: SUCCESS_GREEN,
            QueueState.ERROR: ERROR_TEXT,
        }.get(item.state, MUTED)
        _configure_if_changed(
            row.feedback, text=" • ".join(feedback), text_color=detail_color
        )
        _configure_if_changed(
            row.action,
            text="Remover da lista" if terminal else "Cancelar",
            fg_color=SOFT if terminal else DANGER,
            hover_color=SOFT_HOVER if terminal else DANGER_HOVER,
            text_color=TEXT if terminal else ON_PRIMARY,
            state="normal"
            if not self._queue_closing and (terminal or not item.cancel_requested)
            else "disabled",
        )
        action_column = 2 if terminal else 3
        if row.action.grid_info()["column"] != action_column:
            row.action.grid_configure(
                column=action_column, sticky="w" if terminal else "e"
            )
        has_result = item.state == QueueState.COMPLETED and item.result is not None
        if has_result:
            _configure_if_changed(
                row.badge,
                text="MP3"
                if item.request.content_type == CONTENT_TYPE_AUDIO
                else "MP4",
            )
        self._display(row.badge, has_result)
        can_retry = item.state in {QueueState.ERROR, QueueState.CANCELLED}
        for button, visible in (
            (
                row.open_file,
                has_result and self._queue_actions.open_item_file is not None,
            ),
            (
                row.open_folder,
                has_result and self._queue_actions.open_item_folder is not None,
            ),
            (row.retry, can_retry and self._queue_actions.retry_item is not None),
            (
                row.review,
                item.state == QueueState.ERROR
                and self._queue_actions.review_item is not None,
            ),
        ):
            self._display(button, visible)
            _configure_if_changed(
                button,
                state="normal" if visible and not self._queue_closing else "disabled",
            )

    def _queue_row_action(self, item_id: str) -> None:
        item = self._queue_displayed.get(item_id)
        if item is None or self._queue_closing:
            return
        callback = (
            self._queue_actions.remove_item
            if item.state
            in {QueueState.COMPLETED, QueueState.CANCELLED, QueueState.ERROR}
            else self._queue_actions.cancel_item
        )
        if callback is not None:
            callback(item_id)

    def forget_queue_item(self, item_id: str) -> None:
        self._queue_displayed.pop(item_id, None)
        row = self._queue_rows.get(item_id)
        if row is not None:
            for button in (
                row.action,
                row.open_file,
                row.open_folder,
                row.retry,
                row.review,
            ):
                _configure_if_changed(button, state="disabled")
        self._queue_pending[item_id] = None
        if self._queue_render_after_id is None:
            self._queue_render_after_id = self.after_idle(self._render_queue_batch)

    def close_queue_view(self) -> None:
        if self._queue_render_after_id is not None:
            self.after_cancel(self._queue_render_after_id)
            self._queue_render_after_id = None

    def show_download_destination(self, destination: Path | None) -> None:
        """Apresenta o destino da sessão sem transformar o texto em estado real."""

        self.destination_text.set(
            "Downloads (padrão)" if destination is None else str(destination)
        )

    def set_result_actions_enabled(self, enabled: bool) -> None:
        """Reflete se há um resultado confirmado disponível nesta sessão."""

        state = "normal" if enabled else "disabled"
        _configure_if_changed(self.open_result_file_button, state=state)
        _configure_if_changed(self.open_result_folder_button, state=state)
        recent = self._queue_actions.recent_result_path
        # As ações do arquivo já estão no seu cartão. O atalho continua
        # disponível para um resultado que não tenha cartão correspondente.
        in_queue = recent is not None and recent() in self._queue_result_paths
        self._display(self._result_shortcuts, enabled and not in_queue)


@dataclass(frozen=True)
class _FilesProjectionRequest:
    generation: int
    entries: tuple[LocalFileEntry, ...]
    category: LocalFileCategory | None
    query: str
    sort: LocalFileSort
    limit: int


class FilesPage(FilesWorkspace, ScrollableFrame):
    """Hub persistente para arquivos locais escolhidos explicitamente."""

    is_placeholder = False
    filter_names = ("Todos", "Documentos", "PDF", "Imagens", "Vídeos", "Áudios")
    sort_names = ("Nome", "Mais recentes")
    _INITIAL_VISIBLE_LIMIT = 500
    _VISIBLE_INCREMENT = 500
    _RENDER_BATCH_SIZE = 100
    _PROJECTION_WORKER_THRESHOLD = 5_000
    _SEARCH_DEBOUNCE_MS = 250
    _PREVIEW_DEBOUNCE_MS = 120
    _PREVIEW_POLL_MS = 50
    _PREVIEW_DISPLAY_SIZE = (272, 256)
    _FAVORITES_PLACEHOLDER = "Pastas favoritas"
    _TREE_STYLE = "EduDownloader.Files.Treeview"
    _TREE_FIELD_ELEMENT = "EduDownloader.Files.Treeview.field"
    _HEADING_STYLE = f"{_TREE_STYLE}.Heading"
    _HEADING_CELL_ELEMENT = "EduDownloader.Files.Treeheading.cell"
    _HEADING_BORDER_ELEMENT = "EduDownloader.Files.Treeheading.border"
    _FILTER_CATEGORIES = {
        "Todos": None,
        "Documentos": LocalFileCategory.DOCUMENT,
        "PDF": LocalFileCategory.PDF,
        "Imagens": LocalFileCategory.IMAGE,
        "Vídeos": LocalFileCategory.VIDEO,
        "Áudios": LocalFileCategory.AUDIO,
    }
    _SORT_MODES = {
        "Nome": LocalFileSort.NAME,
        "Mais recentes": LocalFileSort.RECENT,
    }
    _CATEGORY_LABELS = {
        LocalFileCategory.DOCUMENT: "Documento",
        LocalFileCategory.PDF: "PDF",
        LocalFileCategory.IMAGE: "Imagem",
        LocalFileCategory.VIDEO: "Vídeo",
        LocalFileCategory.AUDIO: "Áudio",
    }
    _DOCUMENT_TYPE_LABELS = {
        ".docx": "Documento do Word",
        ".doc": "Documento do Word (antigo)",
        ".odt": "Documento OpenDocument",
        ".txt": "Arquivo de texto",
    }

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        actions: FilesPageActions,
        design: Design | None = None,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
        list_files: Callable[[Path], tuple[LocalFileEntry, ...]] = list_local_files,
        open_file: Callable[[LocalFileEntry, Path], Path] = open_local_file,
        reveal_file: Callable[[LocalFileEntry, Path], Path] = reveal_local_file,
        revalidate_file: Callable[
            [LocalFileEntry, Path], LocalFileEntry
        ] = revalidate_local_file,
        preview_service: FilePreviewService | None = None,
        preview_thread_factory: Callable[..., threading.Thread] = threading.Thread,
        get_favorites: Callable[[], tuple[str, ...]] = get_favorite_folders,
        add_favorite: Callable[
            [Path | str], FavoriteFolderResult
        ] = add_favorite_folder,
        remove_favorite: Callable[
            [Path | str], FavoriteFolderResult
        ] = remove_favorite_folder,
        is_favorite: Callable[[Path | str], bool] = is_favorite_folder,
    ) -> None:
        super().__init__(
            master, corner_radius=0, fg_color=CANVAS, scrollbar_fg_color=CANVAS
        )
        self.grid_columnconfigure(0, weight=1)
        self._actions = actions
        self._thread_factory = thread_factory
        self._list_files = list_files
        self._open_file = open_file
        self._reveal_file = reveal_file
        self._revalidate_file = revalidate_file
        self._preview_service = preview_service or FilePreviewService()
        self._preview_thread_factory = preview_thread_factory
        self._get_favorites = get_favorites
        self._add_favorite = add_favorite
        self._remove_favorite = remove_favorite
        self._is_favorite = is_favorite
        self._scan_results: Queue[_FilesScanResult] = Queue()
        self._directory: Path | None = None
        self._snapshot: tuple[LocalFileEntry, ...] = ()
        self._visible_entries: tuple[LocalFileEntry, ...] = ()
        self._entry_by_item: dict[str, LocalFileEntry] = {}
        self._selected_entry: LocalFileEntry | None = None
        self._tk_thread_id = threading.get_ident()
        self._preview_generation = 0
        self._preview_cancel_event = threading.Event()
        self._preview_after_id: str | None = None
        self._preview_poll_after_id: str | None = None
        self._preview_requests: Queue[_FilesPreviewRequest | None] = Queue(maxsize=1)
        self._preview_results: Queue[_FilesPreviewWorkerResult] = Queue(maxsize=1)
        self._preview_worker: threading.Thread | None = None
        self._preview_state = _PreviewVisualState.EMPTY
        self._preview_tk_image: ctk.CTkImage | None = None
        self._preview_pil_image: Image.Image | None = None
        self._visible_limit = self._INITIAL_VISIBLE_LIMIT
        self._projection_total_count = 0
        self._projection_generation = 0
        self._projection_pending: _FilesProjectionRequest | None = None
        self._projection_worker_active = False
        self._projection_results: Queue[tuple[int, LocalFileProjection | None]] = Queue(
            maxsize=1
        )
        self._projection_after_id: str | None = None
        self._render_generation = 0
        self._render_after_id: str | None = None
        self._render_removals: list[str] = []
        self._render_entries: tuple[LocalFileEntry, ...] = ()
        self._render_insert_index = 0
        self._render_items_by_path: dict[Path, str] = {}
        self._render_reorder = False
        self._render_present_count = 0
        self._search_generation = 0
        self._search_after_id: str | None = None
        self._loading = False
        self._closed = False
        self._folder_text = tk.StringVar(value="Nenhuma pasta selecionada")
        self._favorite_choice = tk.StringVar(value=self._FAVORITES_PLACEHOLDER)
        self._favorite_path_by_label: dict[str, str] = {}
        self._query = tk.StringVar()
        self._query_trace: str | None = None
        self._sort_name = tk.StringVar(value=self.sort_names[0])
        self._visible_count_text = tk.StringVar(value="Mostrando 0 de 0")
        self._status = tk.StringVar(value="Escolha uma pasta para ver seus arquivos.")
        self._detail_heading = tk.StringVar(value="Nenhum arquivo selecionado")
        self._detail_name = tk.StringVar(value="—")
        self._detail_type = tk.StringVar(value="—")
        self._detail_size = tk.StringVar(value="—")
        self._detail_modified = tk.StringVar(value="—")
        self._preview_text = tk.StringVar(
            value="Selecione um arquivo para ver a prévia."
        )
        self._preview_caption = tk.StringVar()
        self._edu_action_text = tk.StringVar(
            value="Selecione um arquivo para ver os detalhes e ações disponíveis."
        )

        self._files_design = design or Design(self.winfo_toplevel())
        self._build_files_workspace(self._files_design)

        self._query_trace = self._query.trace_add("write", self._schedule_search)
        self._reload_favorites()
        self.apply_theme()
        self._refresh_controls()

    @property
    def is_loading(self) -> bool:
        return self._loading

    @property
    def directory(self) -> Path | None:
        return self._directory

    @property
    def snapshot(self) -> tuple[LocalFileEntry, ...]:
        return self._snapshot

    def close(self) -> None:
        self._assert_tk_thread()
        if self._closed:
            return
        self._closed = True
        if self._query_trace is not None:
            self._query.trace_remove("write", self._query_trace)
            self._query_trace = None
        column_job = getattr(self, "_columns_after", None)
        if column_job is not None:
            self.after_cancel(column_job)
            self._columns_after = None
        self._preview_cancel_event.set()
        self._cancel_search_debounce()
        self._cancel_render()
        if self._projection_after_id is not None:
            self.after_cancel(self._projection_after_id)
            self._projection_after_id = None
        self._projection_pending = None
        self._preview_generation += 1
        self._cancel_preview_debounce()
        self._cancel_preview_poll()
        self._discard_pending_preview_request()
        self._clear_preview_image()
        self._stop_preview_worker()
        close_preview = getattr(self._preview_service, "close", None)
        if close_preview is not None:
            close_preview()
        try:
            self._preview_results.get_nowait()
        except Empty:
            pass

    def destroy(self):
        if not getattr(self, "_closed", True):
            self.close()
        super().destroy()

    def _schedule_preview(self, entry: LocalFileEntry) -> None:
        self._assert_tk_thread()
        self._invalidate_preview(_PreviewVisualState.EMPTY)
        if entry.category not in {
            LocalFileCategory.IMAGE,
            LocalFileCategory.PDF,
            LocalFileCategory.VIDEO,
        } and not (
            entry.category is LocalFileCategory.DOCUMENT
            and entry.suffix.casefold() in DOCUMENT_PREVIEW_SUFFIXES
        ):
            self._set_preview_visual(
                _PreviewVisualState.UNSUPPORTED,
                (
                    "Prévia de .doc não disponível. Use Abrir."
                    if entry.suffix.casefold() == ".doc"
                    else "Prévia visual não disponível."
                    if entry.category is LocalFileCategory.DOCUMENT
                    else None
                ),
            )
            return
        directory = self._directory
        if directory is None:
            self._set_preview_visual(_PreviewVisualState.UNAVAILABLE)
            return
        self._set_preview_visual(_PreviewVisualState.LOADING)
        generation = self._preview_generation
        self._preview_after_id = self.after(
            self._PREVIEW_DEBOUNCE_MS,
            lambda: self._begin_preview(generation, directory, entry),
        )

    def _begin_preview(
        self,
        generation: int,
        directory: Path,
        entry: LocalFileEntry,
    ) -> None:
        self._assert_tk_thread()
        self._preview_after_id = None
        if not self._preview_request_is_current(generation, directory, entry):
            return
        if not self._ensure_preview_worker():
            self._set_preview_visual(_PreviewVisualState.ERROR)
            return
        self._discard_pending_preview_request()
        self._preview_requests.put_nowait(
            _FilesPreviewRequest(
                generation, directory, entry, self._preview_cancel_event
            )
        )

    def _ensure_preview_worker(self) -> bool:
        if self._preview_worker is not None:
            return True
        worker = self._preview_thread_factory(
            target=self._preview_worker_loop,
            daemon=True,
            name="edudownloader-file-preview-worker",
        )
        try:
            worker.start()
        except Exception:
            return False
        self._preview_worker = worker
        self._schedule_preview_poll()
        return True

    def _preview_worker_loop(self) -> None:
        watch = None
        while True:
            try:
                request = (
                    self._preview_requests.get(timeout=1.0)
                    if watch
                    else self._preview_requests.get()
                )
            except Empty:
                request, identity = watch
                if self._closed or request.cancel_event.is_set():
                    watch = None
                    continue
                try:
                    if (
                        self._preview_service.source_identity(
                            request.entry, request.directory
                        )
                        == identity
                    ):
                        continue
                except (OSError, LocalFilesError):
                    pass
                self._publish_preview_result(
                    _FilesPreviewWorkerResult(
                        request, FilePreviewResult(PreviewStatus.LOADING)
                    )
                )
            if request is None:
                return
            if request.cancel_event.is_set():
                continue
            try:
                cancellable = getattr(
                    self._preview_service, "create_cancellable_preview", None
                )
                if cancellable is not None:
                    preview = cancellable(
                        request.entry, request.directory, request.cancel_event
                    )
                else:
                    preview = self._preview_service.create_preview(
                        request.entry, request.directory
                    )
            except Exception:
                preview = FilePreviewResult(
                    PreviewStatus.ERROR,
                    message="Não foi possível gerar a prévia.",
                )
            if not self._closed and not request.cancel_event.is_set():
                self._publish_preview_result(
                    _FilesPreviewWorkerResult(request, preview)
                )
                watch = (
                    (request, preview.source_identity)
                    if preview.source_identity
                    else None
                )

    def _publish_preview_result(self, result: _FilesPreviewWorkerResult) -> None:
        if self._closed:
            return
        try:
            self._preview_results.get_nowait()
        except Empty:
            pass
        self._preview_results.put_nowait(result)
        if self._closed:
            try:
                self._preview_results.get_nowait()
            except Empty:
                pass

    def _schedule_preview_poll(self) -> None:
        if self._closed or self._preview_poll_after_id is not None:
            return
        self._preview_poll_after_id = self.after(
            self._PREVIEW_POLL_MS,
            self._poll_preview_results,
        )

    def _poll_preview_results(self) -> None:
        self._assert_tk_thread()
        self._preview_poll_after_id = None
        if self._closed:
            return
        try:
            result = self._preview_results.get_nowait()
        except Empty:
            self._schedule_preview_poll()
            return
        request = result.request
        if self._preview_request_is_current(
            request.generation,
            request.directory,
            request.entry,
        ):
            self._apply_preview_result(result.preview)
        self._schedule_preview_poll()

    def _preview_request_is_current(
        self,
        generation: int,
        directory: Path,
        entry: LocalFileEntry,
    ) -> bool:
        selected = self._selected_entry
        return (
            not self._closed
            and generation == self._preview_generation
            and self._directory == directory
            and selected is not None
            and selected.path == entry.path
            and any(candidate.path == entry.path for candidate in self._snapshot)
        )

    def _apply_preview_result(self, result: FilePreviewResult) -> None:
        self._assert_tk_thread()
        if result.status is PreviewStatus.LOADING:
            self._set_preview_visual(_PreviewVisualState.LOADING)
        elif result.status is PreviewStatus.SUCCESS:
            if result.kind is PreviewKind.WORD_TEXT:
                self._show_preview_document(result)
            else:
                self._show_preview_image(result)
        elif result.status is PreviewStatus.UNSUPPORTED:
            self._set_preview_visual(_PreviewVisualState.UNSUPPORTED, result.message)
        elif result.status is PreviewStatus.TOO_LARGE:
            self._set_preview_visual(
                _PreviewVisualState.UNAVAILABLE,
                result.message or "Arquivo grande demais para gerar a prévia.",
            )
        elif result.status is PreviewStatus.ERROR:
            self._set_preview_visual(_PreviewVisualState.ERROR)
        else:
            self._set_preview_visual(_PreviewVisualState.UNAVAILABLE, result.message)

    def _show_preview_document(self, result):
        self._clear_preview_image()
        content = (f"Título: {result.title}\n\n" if result.title else "") + (
            result.text or result.message or "Documento sem texto extraível."
        )
        if result.truncated:
            content += "\n\n[Prévia limitada a 20.000 caracteres. Use Abrir para o documento completo.]"
        self.preview_document.configure(state="normal")
        self.preview_document.insert("1.0", content)
        self.preview_document.configure(state="disabled")
        self.preview_document.yview_moveto(0)
        self.preview_label.grid_remove()
        self.preview_document.grid(row=0, column=0, padx=8, pady=6, sticky="nsew")
        self._preview_state = _PreviewVisualState.AVAILABLE
        self._preview_text.set("Prévia textual")
        entry = self._selected_entry
        extension = entry.suffix[1:].upper() if entry is not None else "DOCX"
        self._preview_caption.set(f"Amostra de texto do {extension}")

    def _show_preview_image(self, result: FilePreviewResult) -> None:
        if (
            result.width < 1
            or result.height < 1
            or len(result.rgba) != result.width * result.height * 4
        ):
            self._set_preview_visual(_PreviewVisualState.ERROR)
            return
        image = None
        try:
            image = Image.frombytes(
                "RGBA",
                (result.width, result.height),
                result.rgba,
            )
            display_size = self._fit_preview_display_size(
                image.size,
                self._preview_width_limit(self.preview_frame.winfo_width()),
                self._preview_height_limit(self.preview_frame.winfo_height()),
            )
            tk_image = ctk.CTkImage(
                light_image=image,
                dark_image=image,
                size=display_size,
            )
        except Exception:
            if image is not None:
                image.close()
            self._set_preview_visual(_PreviewVisualState.ERROR)
            return
        self._clear_preview_image()
        self._preview_pil_image = image
        self._preview_tk_image = tk_image
        self._preview_state = _PreviewVisualState.AVAILABLE
        self._preview_text.set("")
        entry = self._selected_entry
        document = entry is not None and entry.category is LocalFileCategory.DOCUMENT
        self._preview_caption.set(
            {
                PreviewKind.PDF_PAGE: (
                    "Primeira página do documento"
                    if document
                    else "Primeira página do PDF"
                ),
                PreviewKind.VIDEO_FRAME: "Quadro do vídeo",
            }.get(result.kind, "Prévia da imagem")
        )
        self.preview_label.configure(image=tk_image)

    def _invalidate_preview(self, state: _PreviewVisualState) -> None:
        self._preview_cancel_event.set()
        self._preview_cancel_event = threading.Event()
        self._preview_generation += 1
        self._cancel_preview_debounce()
        self._discard_pending_preview_request()
        self._set_preview_visual(state)

    def _set_preview_visual(
        self,
        state: _PreviewVisualState,
        message: str | None = None,
    ) -> None:
        self._assert_tk_thread()
        self._clear_preview_image()
        self._preview_state = state
        if message is not None:
            text = message
        else:
            text = {
                _PreviewVisualState.EMPTY: "Selecione um arquivo para ver a prévia.",
                _PreviewVisualState.LOADING: "Carregando prévia...",
                _PreviewVisualState.AVAILABLE: "",
                _PreviewVisualState.UNAVAILABLE: "Não foi possível mostrar a prévia. Tente abrir o arquivo.",
                _PreviewVisualState.UNSUPPORTED: (
                    "Prévia não disponível para este tipo de arquivo."
                ),
                _PreviewVisualState.ERROR: "Não foi possível mostrar a prévia. Tente abrir o arquivo.",
            }[state]
        self._preview_text.set(text)

    def _clear_preview_image(self) -> None:
        previous = self._preview_pil_image
        self._preview_caption.set("")
        self.preview_label.configure(image=None)
        # CTkLabel 5.2.2 does not clear its native image when passed None.
        self.preview_label._label.configure(image="")
        if hasattr(self, "preview_document"):
            self.preview_document.grid_remove()
            self.preview_document.configure(state="normal")
            self.preview_document.delete("1.0", "end")
            self.preview_document.configure(state="disabled")
            self.preview_label.grid()
        self._preview_tk_image = None
        self._preview_pil_image = None
        if previous is not None:
            previous.close()

    def _cancel_preview_debounce(self) -> None:
        after_id = self._preview_after_id
        self._preview_after_id = None
        if after_id is None:
            return
        try:
            self.after_cancel(after_id)
        except (RuntimeError, tk.TclError):
            pass

    def _cancel_preview_poll(self) -> None:
        after_id = self._preview_poll_after_id
        self._preview_poll_after_id = None
        if after_id is None:
            return
        try:
            self.after_cancel(after_id)
        except (RuntimeError, tk.TclError):
            pass

    def _discard_pending_preview_request(self) -> None:
        try:
            self._preview_requests.get_nowait()
        except Empty:
            pass

    def _stop_preview_worker(self) -> None:
        if self._preview_worker is None:
            return
        self._discard_pending_preview_request()
        self._preview_requests.put_nowait(None)
        self._preview_worker = None

    def _resize_preview_image(self, event) -> None:
        if self._preview_tk_image is None or self._preview_pil_image is None:
            return
        size = self._fit_preview_display_size(
            self._preview_pil_image.size,
            self._preview_width_limit(event.width),
            self._preview_height_limit(event.height),
        )
        if self._preview_tk_image.cget("size") != size:
            self._preview_tk_image.configure(size=size)

    def _preview_width_limit(self, pixels: int) -> int:
        if pixels <= 1:
            return self._PREVIEW_DISPLAY_SIZE[0]
        width = self.preview_frame._reverse_widget_scaling(pixels) - 16
        # Limita as variantes de tamanho retidas no cache de CTkImage.
        return max(32, min(512, int(width) // 32 * 32))

    def _preview_height_limit(self, pixels: int) -> int:
        if pixels <= 1:
            return self._PREVIEW_DISPLAY_SIZE[1]
        height = self.preview_frame._reverse_widget_scaling(pixels) - 16
        return max(32, min(384, int(height) // 16 * 16))

    @classmethod
    def _fit_preview_display_size(
        cls,
        size: tuple[int, int],
        width_limit: int | None = None,
        height_limit: int | None = None,
    ) -> tuple[int, int]:
        width, height = size
        max_width, max_height = cls._PREVIEW_DISPLAY_SIZE
        scale = min(
            1.0,
            (width_limit or max_width) / width,
            (height_limit or max_height) / height,
        )
        return max(1, round(width * scale)), max(1, round(height * scale))

    def _assert_tk_thread(self) -> None:
        if threading.get_ident() != self._tk_thread_id:
            raise RuntimeError(
                "Widgets de preview só podem ser alterados na thread Tk."
            )

    def apply_theme(self, selected_theme: str | None = None) -> None:
        """Aplica cores explícitas da Treeview conforme o tema CustomTkinter."""

        dark = (
            selected_theme in {"Escuro", "Dark"}
            if selected_theme is not None
            else ctk.get_appearance_mode() == "Dark"
        )
        index = int(dark)
        palette = {
            "background": SURFACE[index],
            "foreground": TEXT[index],
            "heading": SOFT[index],
            "heading_active": SOFT_HOVER[index],
            "selected": SOFT_HOVER[index],
        }
        style = ttk.Style(self)
        self._ensure_tree_layouts(style)
        style.configure(
            self._TREE_STYLE,
            background=palette["background"],
            fieldbackground=palette["background"],
            bordercolor=palette["background"],
            lightcolor=palette["background"],
            foreground=palette["foreground"],
            rowheight=max(34, self._files_design.nav.metrics("linespace") + 10),
            font=self._files_design.nav,
            borderwidth=0,
        )
        style.map(
            self._TREE_STYLE,
            background=[("selected", palette["selected"])],
            foreground=[("selected", palette["foreground"])],
        )
        style.configure(
            self._HEADING_STYLE,
            background=palette["heading"],
            foreground=palette["foreground"],
            relief="flat",
        )
        style.map(
            self._HEADING_STYLE,
            background=[("active", palette["heading_active"])],
            foreground=[("active", palette["foreground"])],
        )

    @classmethod
    def _ensure_tree_layouts(cls, style: ttk.Style) -> None:
        """Usa elementos que respeitam as cores do tema no campo e no cabeçalho."""

        elements = set(style.element_names())
        for element, source in (
            (cls._TREE_FIELD_ELEMENT, "Treeview.field"),
            (cls._HEADING_CELL_ELEMENT, "Treeheading.cell"),
            (cls._HEADING_BORDER_ELEMENT, "Treeheading.border"),
        ):
            if element in elements:
                continue
            style.element_create(element, "from", "clam", source)
            elements.add(element)
        # O campo nativo do tema vista desenha branco mesmo com fieldbackground.
        # Mantém a área de linhas e a geometria do tema corrente.
        _, field_options = style.layout("Treeview")[0]
        style.layout(cls._TREE_STYLE, [(cls._TREE_FIELD_ELEMENT, field_options)])
        style.layout(
            cls._HEADING_STYLE,
            [
                (cls._HEADING_CELL_ELEMENT, {"sticky": "nswe"}),
                (
                    cls._HEADING_BORDER_ELEMENT,
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "Treeheading.padding",
                                {
                                    "sticky": "nswe",
                                    "children": [
                                        (
                                            "Treeheading.image",
                                            {"side": "right", "sticky": ""},
                                        ),
                                        ("Treeheading.text", {"sticky": "we"}),
                                    ],
                                },
                            )
                        ],
                    },
                ),
            ],
        )

    def _choose_directory(self) -> None:
        if self._loading:
            self._actions.show_warning("Aguarde a leitura da pasta atual terminar.")
            return
        selected = filedialog.askdirectory(
            title="Escolha uma pasta local",
            parent=self.winfo_toplevel(),
            mustexist=True,
        )
        if selected:
            self._start_scan(Path(selected), replace_directory=True)

    def _toggle_current_favorite(self) -> None:
        directory = self._directory
        if directory is None or self._loading:
            return
        try:
            already_favorite = self._is_favorite(directory)
            result = (
                self._remove_favorite(directory)
                if already_favorite
                else self._add_favorite(directory)
            )
        except OSError:
            self._actions.show_error(
                "Não foi possível atualizar suas pastas favoritas."
            )
            return

        if result is FavoriteFolderResult.LIMIT_REACHED:
            self._actions.show_warning("Você pode favoritar até 10 pastas.")
            return
        if result is FavoriteFolderResult.INVALID_PATH:
            self._actions.show_error("Não foi possível favoritar esta pasta.")
            return

        preferred = directory if result is FavoriteFolderResult.ADDED else None
        self._reload_favorites(preferred=preferred)
        if result in {FavoriteFolderResult.ADDED, FavoriteFolderResult.ALREADY_EXISTS}:
            self._status.set("Pasta adicionada aos favoritos.")
        else:
            self._status.set("Pasta removida dos favoritos.")
        self._refresh_controls()

    def _select_favorite(self, label: str) -> None:
        if self._loading:
            return
        folder = self._favorite_path_by_label.get(label)
        if folder is None:
            return
        self._start_scan(
            Path(folder),
            replace_directory=True,
            unavailable_error="Esta pasta favorita não está disponível.",
        )

    def _remove_selected_favorite(self) -> None:
        if self._loading:
            return
        folder = self._favorite_path_by_label.get(self._favorite_choice.get())
        if folder is None:
            return
        try:
            result = self._remove_favorite(folder)
        except OSError:
            self._actions.show_error(
                "Não foi possível atualizar suas pastas favoritas."
            )
            return
        if result is FavoriteFolderResult.INVALID_PATH:
            self._actions.show_error(
                "Não foi possível remover esta pasta dos favoritos."
            )
            return
        self._reload_favorites()
        self._status.set("Pasta removida dos favoritos.")
        self._refresh_controls()

    def _reload_favorites(self, *, preferred: Path | str | None = None) -> None:
        try:
            favorites = self._get_favorites()
        except OSError:
            favorites = ()
        choices = _favorite_folder_choices(favorites)
        self._favorite_path_by_label = {label: folder for label, folder in choices}
        values = [self._FAVORITES_PLACEHOLDER, *(label for label, _folder in choices)]
        self.favorite_menu.configure(values=values)
        self._favorite_choice.set(self._favorite_label_for(preferred))

    def _favorite_label_for(self, directory: Path | str | None) -> str:
        if directory is None:
            return self._FAVORITES_PLACEHOLDER
        comparison_key = favorite_folder_comparison_key(directory)
        if comparison_key is None:
            return self._FAVORITES_PLACEHOLDER
        return next(
            (
                label
                for label, folder in self._favorite_path_by_label.items()
                if favorite_folder_comparison_key(folder) == comparison_key
            ),
            self._FAVORITES_PLACEHOLDER,
        )

    def _refresh_directory(self) -> None:
        if self._loading:
            self._actions.show_warning("Aguarde a leitura da pasta atual terminar.")
            return
        if self._directory is None:
            self._actions.show_warning("Escolha uma pasta antes de atualizar.")
            return
        self._start_scan(self._directory, replace_directory=False)

    def _start_scan(
        self,
        directory: Path,
        *,
        replace_directory: bool,
        unavailable_error: str | None = None,
    ) -> bool:
        if self._loading:
            self._actions.show_warning("Aguarde a leitura da pasta atual terminar.")
            return False
        self._cancel_search_debounce()
        self._cancel_render()
        if replace_directory:
            self._clear_selection()
        self._loading = True
        self._status.set("Lendo os arquivos compatíveis da pasta...")
        self.progress_bar.start()
        self._refresh_controls()

        def run() -> None:
            try:
                entries = self._list_files(directory)
                result = _FilesScanResult(directory, replace_directory, entries=entries)
            except LocalFilesError as error:
                result = _FilesScanResult(
                    directory,
                    replace_directory,
                    error_message=unavailable_error or str(error),
                )
            except Exception:
                result = _FilesScanResult(
                    directory,
                    replace_directory,
                    error_message=(
                        unavailable_error or "Não foi possível ler a pasta selecionada."
                    ),
                )
            self._scan_results.put(result)

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-files-worker",
        )
        try:
            worker.start()
        except Exception:
            self._loading = False
            self.progress_bar.stop()
            self.progress_bar.set(0)
            self._status.set("Não foi possível iniciar a leitura da pasta.")
            self._actions.show_error("Não foi possível iniciar a leitura da pasta.")
            self._refresh_controls()
            return False
        self.after(80, self._poll_scan)
        return True

    def _poll_scan(self) -> None:
        if self._closed or not self._loading:
            return
        try:
            result = self._scan_results.get_nowait()
        except Empty:
            self.after(80, self._poll_scan)
            return
        self._loading = False
        self.progress_bar.stop()
        self.progress_bar.set(0)
        if result.error_message is not None:
            if not result.replace_directory:
                self._directory = None
                self._folder_text.set("Nenhuma pasta selecionada")
                self._favorite_choice.set(self._FAVORITES_PLACEHOLDER)
                self._set_snapshot(())
            self._status.set(result.error_message)
            self._actions.show_error(result.error_message)
            self._refresh_controls()
            return
        self._directory = result.directory
        self._favorite_choice.set(self._favorite_label_for(result.directory))
        self._folder_text.set(str(result.directory))
        self._set_snapshot(result.entries or ())
        self._refresh_controls()

    def _set_snapshot(self, entries: tuple[LocalFileEntry, ...]) -> None:
        self._snapshot = entries
        self._apply_filters(reset_limit=True)

    def _on_filter_change(self, _selected: str) -> None:
        self._cancel_search_debounce()
        self._apply_filters(reset_limit=True)

    def _on_sort_change(self, _selected: str) -> None:
        self._cancel_search_debounce()
        self._apply_filters(reset_limit=True)

    def _schedule_search(self, *_args: object) -> None:
        """Agrupa digitação rápida em uma única projeção após 250 ms."""

        if self._closed:
            return
        self._cancel_search_debounce()
        self._cancel_render()
        self.show_more_button.grid_remove()
        generation = self._search_generation
        self._search_after_id = self.after(
            self._SEARCH_DEBOUNCE_MS,
            lambda: self._apply_debounced_search(generation),
        )

    def _apply_debounced_search(self, generation: int) -> None:
        if self._closed or generation != self._search_generation:
            return
        self._search_after_id = None
        self._apply_filters(reset_limit=True)

    def _apply_search_now(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        self._cancel_search_debounce()
        if not self._closed:
            self._apply_filters(reset_limit=True)
        return "break"

    def _cancel_search_debounce(self) -> None:
        self._search_generation += 1
        self._projection_generation += 1
        self._projection_pending = None
        after_id = self._search_after_id
        self._search_after_id = None
        if after_id is None:
            return
        try:
            self.after_cancel(after_id)
        except (RuntimeError, tk.TclError):
            pass

    def _show_more(self) -> None:
        if self._loading or len(self._visible_entries) >= self._projection_total_count:
            return
        self._visible_limit += self._VISIBLE_INCREMENT
        self._apply_filters(reset_limit=False)

    def _apply_filters(self, *, reset_limit: bool = True) -> None:
        if self._closed:
            return
        if reset_limit:
            self._visible_limit = self._INITIAL_VISIBLE_LIMIT
        selected_filter = self.filter_control.get()
        category = self._FILTER_CATEGORIES.get(selected_filter)
        sort = self._SORT_MODES.get(self._sort_name.get(), LocalFileSort.NAME)
        self._projection_generation += 1
        self._projection_pending = None
        request = _FilesProjectionRequest(
            self._projection_generation,
            self._snapshot,
            category,
            self._query.get(),
            sort,
            self._visible_limit,
        )
        self._cancel_render()
        if len(self._snapshot) >= self._PROJECTION_WORKER_THRESHOLD:
            self._projection_pending = request
            self._status.set("Atualizando lista de arquivos...")
            self.show_more_button.grid_remove()
            self._start_projection_worker()
            return
        projection = self._project_files(request)
        self._accept_projection(projection)

    @staticmethod
    def _project_files(request: _FilesProjectionRequest) -> LocalFileProjection:
        return project_local_files(
            request.entries,
            category=request.category,
            query=request.query,
            sort=request.sort,
            limit=request.limit,
        )

    def _start_projection_worker(self) -> None:
        if (
            self._closed
            or self._projection_worker_active
            or self._projection_pending is None
        ):
            return
        request = self._projection_pending
        self._projection_pending = None
        self._projection_worker_active = True

        def run() -> None:
            try:
                result = self._project_files(request)
            except Exception:
                result = None
            self._projection_results.put_nowait((request.generation, result))

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-files-projection",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._projection_worker_active = False
            self._status.set("Não foi possível atualizar a lista de arquivos.")
            return
        self._projection_after_id = self.after(40, self._poll_projection)

    def _poll_projection(self) -> None:
        self._projection_after_id = None
        if self._closed:
            return
        try:
            generation, projection = self._projection_results.get_nowait()
        except Empty:
            self._projection_after_id = self.after(40, self._poll_projection)
            return
        self._projection_worker_active = False
        if generation == self._projection_generation:
            if projection is None:
                self._status.set("Não foi possível atualizar a lista de arquivos.")
            else:
                self._accept_projection(projection)
        self._start_projection_worker()

    def _accept_projection(self, projection: LocalFileProjection) -> None:
        self._visible_entries = projection.entries
        self._projection_total_count = projection.total_count
        self._refresh_projection_status()
        self._start_render(self._visible_entries)

    def _refresh_projection_status(self) -> None:
        if self._loading:
            return
        if self._directory is None:
            self._status.set("Escolha uma pasta para ver seus arquivos.")
        elif not self._snapshot:
            self._status.set(
                "Nenhum arquivo compatível nesta pasta. Escolha outra pasta."
            )
        elif self._projection_total_count == 0:
            if self._query.get():
                self._status.set(
                    "Nenhum arquivo corresponde à busca. Tente outro termo."
                )
            elif self.filter_control.get() == "Documentos":
                self._status.set(
                    "Nenhum documento encontrado. Escolha outro filtro ou pasta."
                )
            elif self.filter_control.get() != self.filter_names[0]:
                self._status.set("Nenhum arquivo neste filtro. Escolha outro filtro.")
            else:
                self._status.set(
                    "Nenhum arquivo compatível nesta pasta. Escolha outra pasta."
                )
        else:
            self._status.set(
                f"{_format_count(self._projection_total_count, 'arquivo encontrado', 'arquivos encontrados')}."
            )

    def _start_render(self, entries: tuple[LocalFileEntry, ...]) -> None:
        self._cancel_render()
        generation = self._render_generation
        items = self.file_tree.get_children()
        desired_paths = {entry.path for entry in entries}
        self._render_items_by_path = {
            entry.path: item for item, entry in self._entry_by_item.items()
        }
        self._render_removals = [
            item
            for item in items
            if self._entry_by_item[item].path not in desired_paths
        ]
        retained = [
            self._render_items_by_path[key]
            for entry in entries
            if (key := entry.path) in self._render_items_by_path
        ]
        retained_set = set(retained)
        self._render_reorder = retained != [
            item for item in items if item in retained_set
        ]
        self._render_present_count = len(retained)
        self._render_entries = entries
        self._render_insert_index = 0
        if self._selected_entry is not None and (
            self._selected_entry.path not in desired_paths
        ):
            selection = self.file_tree.selection()
            if selection:
                self.file_tree.selection_remove(*selection)
            self._clear_selection()
        self.show_more_button.grid_remove()
        self._render_batch(generation)

    def _schedule_file_columns(self, _event=None) -> None:
        if not self._closed and getattr(self, "_columns_after", None) is None:
            self._columns_after = self.after_idle(self._fit_file_columns)

    def _fit_file_columns(self) -> None:
        self._columns_after = None
        tree = self.file_tree
        available = tree.winfo_width() - 4
        if self._closed or available < 160:
            return
        font = self._files_design.nav
        desired_type = (
            max(font.measure(label) for label in self._DOCUMENT_TYPE_LABELS.values())
            + 16
        )
        size = max(font.measure("999,0 MB") + 16, 72)
        kind = min(desired_type, round(available * 0.38))
        name = available - size - kind
        dimensions = (name, kind, size, font.cget("size"))
        if dimensions == getattr(self, "_file_column_widths", None):
            return
        self._file_column_widths = dimensions
        for column, width in zip(("name", "type", "size"), dimensions[:3], strict=True):
            tree.column(column, width=width, stretch=False, minwidth=0)
        for item_id, entry in self._entry_by_item.items():
            values = self._file_row_values(entry)
            if tree.item(item_id, "values") != values:
                tree.item(item_id, values=values)

    def _file_row_values(self, entry):
        name, kind = entry.name, self._type_label(entry)
        widths = getattr(self, "_file_column_widths", None)
        if widths is not None:
            measure = self._files_design.nav.measure
            name = _shorten_cell(name, widths[0] - 12, measure)
            kind = _shorten_cell(kind, widths[1] - 12, measure)
        return (
            name,
            kind,
            format_size(entry.size_bytes),
            self._format_timestamp(entry.modified_timestamp),
        )

    def _render_batch(self, generation: int) -> None:
        if self._closed or generation != self._render_generation:
            return
        self._render_after_id = None
        remaining = self._RENDER_BATCH_SIZE
        while self._render_removals and remaining:
            item = self._render_removals.pop()
            self.file_tree.delete(item)
            del self._entry_by_item[item]
            remaining -= 1

        while (
            not self._render_removals
            and self._render_insert_index < len(self._render_entries)
            and remaining
        ):
            index = self._render_insert_index
            entry = self._render_entries[index]
            key = entry.path
            item_id = self._render_items_by_path.get(key)
            if item_id is None or self._entry_by_item[item_id] != entry:
                values = self._file_row_values(entry)
                if item_id is None:
                    item_id = f"file-{generation}-{index}"
                    self.file_tree.insert("", index, iid=item_id, values=values)
                    self._render_present_count += 1
                else:
                    self.file_tree.item(item_id, values=values)
                self._entry_by_item[item_id] = entry
            if self._render_reorder and key in self._render_items_by_path:
                self.file_tree.move(item_id, "", index)
            self._render_insert_index += 1
            remaining -= 1

        self._visible_count_text.set(
            f"Mostrando {self._render_present_count} de {self._projection_total_count}"
        )
        if self._render_removals or self._render_insert_index < len(
            self._render_entries
        ):
            self._render_after_id = self.after(
                1,
                lambda: self._render_batch(generation),
            )
            return

        self._on_tree_selection()
        if len(self._visible_entries) < self._projection_total_count:
            self.show_more_button.grid()
            self.show_more_button.configure(state="normal")
        else:
            self.show_more_button.grid_remove()

    def _cancel_render(self) -> None:
        self._render_generation += 1
        after_id = self._render_after_id
        self._render_after_id = None
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except (RuntimeError, tk.TclError):
                pass
        self._render_removals = []
        self._render_entries = ()
        self._render_insert_index = 0
        self._render_items_by_path = {}

    def _on_tree_selection(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selection = self.file_tree.selection()
        entry = self._entry_by_item.get(selection[0]) if selection else None
        if entry is None:
            self._clear_selection()
            return
        if self._selected_entry == entry:
            if self._preview_state in {
                _PreviewVisualState.UNAVAILABLE,
                _PreviewVisualState.ERROR,
            }:
                self._schedule_preview(entry)
            return
        # Os metadados e as ações alteram as larguras da lista e dos detalhes.
        with self._selection_presentation():
            self._selected_entry = entry
            self._detail_heading.set(entry.name)
            self._detail_name.set(entry.name)
            self._detail_type.set(
                f"{self._type_label(entry)} ({entry.suffix.casefold()})"
            )
            self._detail_size.set(format_size(entry.size_bytes))
            self._detail_modified.set(self._format_timestamp(entry.modified_timestamp))
            self._schedule_preview(entry)
            self._refresh_context_actions()
            self._refresh_controls()

    def _on_tree_double_click(self, event: tk.Event[tk.Misc]) -> str:
        item_id = self.file_tree.identify_row(event.y)
        entry = self._entry_by_item.get(item_id)
        if entry is None:
            return "break"
        selection = self.file_tree.selection()
        if (
            not selection
            or selection[0] != item_id
            or self._selected_entry is None
            or self._selected_entry.path != entry.path
        ):
            self.file_tree.selection_set(item_id)
            self.file_tree.focus(item_id)
            self._on_tree_selection()
        self._open_selected()
        return "break"

    def _clear_selection(self) -> None:
        with (
            self._selection_presentation()
            if self._selected_entry is not None
            else nullcontext()
        ):
            self._selected_entry = None
            self._invalidate_preview(_PreviewVisualState.EMPTY)
            self._detail_heading.set("Nenhum arquivo selecionado")
            self._detail_name.set("—")
            self._detail_type.set("—")
            self._detail_size.set("—")
            self._detail_modified.set("—")
            self._refresh_context_actions()
            self._refresh_controls()

    def _selection_presentation(self):
        viewport_change = getattr(self, "_viewport_change", None)
        return (
            viewport_change(pointer=self.file_tree)
            if viewport_change
            else nullcontext()
        )

    def _refresh_context_actions(self) -> None:
        for button in self._context_buttons:
            button.pack_forget()
        entry = self._selected_entry
        if entry is None:
            self._edu_action_text.set(
                "Selecione um arquivo para ver os detalhes e ações disponíveis."
            )
            return
        if entry.category is LocalFileCategory.PDF:
            self._edu_action_text.set("Ferramentas PDF disponíveis:")
            self.extract_button.pack(fill="x", pady=(0, 6))
            self.pdf_images_button.pack(fill="x", pady=(0, 6))
            if self._actions.pdf_to_docx is not None:
                self.pdf_word_button.pack(fill="x", pady=(0, 6))
        elif entry.category is LocalFileCategory.IMAGE:
            self._edu_action_text.set("Ferramentas de imagem disponíveis:")
            self.image_pdf_button.pack(fill="x", pady=(0, 6))
            if self._actions.create_poster is not None:
                self.poster_button.pack(fill="x", pady=(0, 6))
        elif entry.category is LocalFileCategory.VIDEO:
            self._edu_action_text.set("Ferramenta de vídeo disponível:")
            self.video_mp3_button.pack(fill="x", pady=(0, 6))
        elif entry.category is LocalFileCategory.DOCUMENT:
            callbacks = {
                ".docx": self._actions.docx_to_pdf,
                ".odt": self._actions.odt_to_pdf,
                ".txt": self._actions.txt_to_pdf,
            }
            if callbacks.get(entry.suffix.casefold()) is not None:
                self._edu_action_text.set("Ferramenta de documento disponível:")
                self.docx_pdf_button.pack(fill="x", pady=(0, 6))
            else:
                self._edu_action_text.set(
                    "Nenhuma conversão específica disponível para este documento."
                )
        else:
            self._edu_action_text.set(
                "Nenhuma conversão específica disponível para áudio."
            )

    @classmethod
    def _type_label(cls, entry: LocalFileEntry) -> str:
        if entry.category is LocalFileCategory.DOCUMENT:
            return cls._DOCUMENT_TYPE_LABELS.get(entry.suffix.casefold(), "Documento")
        return cls._CATEGORY_LABELS[entry.category]

    def _convert_selected_document(self) -> bool:
        entry = self._selected_entry
        if entry is None:
            return False
        callback = {
            ".docx": self._actions.docx_to_pdf,
            ".odt": self._actions.odt_to_pdf,
            ".txt": self._actions.txt_to_pdf,
        }.get(entry.suffix.casefold())
        return callback is not None and self._route_selected(callback)

    def _open_selected(self) -> bool:
        return self._run_general_action(
            self._open_file,
            "Arquivo enviado ao aplicativo padrão do Windows.",
        )

    def _reveal_selected(self) -> bool:
        return self._run_general_action(
            self._reveal_file,
            "Pasta aberta no Explorador de Arquivos.",
        )

    def _run_general_action(
        self,
        operation: Callable[[LocalFileEntry, Path], Path],
        success_message: str,
    ) -> bool:
        entry = self._selected_entry
        directory = self._directory
        if entry is None or directory is None or self._loading:
            return False
        try:
            operation(entry, directory)
        except LocalFilesError as error:
            self._handle_action_error(entry, error)
            return False
        self._status.set(success_message)
        return True

    def _route_selected(self, callback: Callable[[Path], bool]) -> bool:
        entry = self._revalidated_selected()
        if entry is None:
            return False
        accepted = callback(entry.path)
        if accepted:
            self._status.set("Arquivo preparado na ferramenta escolhida.")
        else:
            self._status.set("A ferramenta está ocupada; o arquivo não foi alterado.")
        return accepted

    def _revalidated_selected(self) -> LocalFileEntry | None:
        entry = self._selected_entry
        directory = self._directory
        if entry is None or directory is None or self._loading:
            return None
        try:
            refreshed = self._revalidate_file(entry, directory)
        except LocalFilesError as error:
            self._handle_action_error(entry, error)
            return None
        self._selected_entry = refreshed
        return refreshed

    def _handle_action_error(
        self,
        entry: LocalFileEntry,
        error: LocalFilesError,
    ) -> None:
        self._actions.show_error(str(error))
        directory = self._directory
        if directory is None:
            return
        try:
            self._revalidate_file(entry, directory)
        except LocalFilesError:
            self._snapshot = tuple(
                candidate
                for candidate in self._snapshot
                if candidate.path != entry.path
            )
            self._apply_filters(reset_limit=False)
            self._status.set(
                "O arquivo não está mais disponível e foi removido da lista."
            )

    def _refresh_controls(self) -> None:
        normal = "normal" if not self._loading else "disabled"
        self.choose_button.configure(state=normal)
        self.initial_choose_button.configure(state=normal)
        self._show_files_workspace()
        self.refresh_button.configure(
            state="normal"
            if self._directory is not None and not self._loading
            else "disabled"
        )
        current_is_favorite = False
        if self._directory is not None:
            try:
                current_is_favorite = self._is_favorite(self._directory)
            except OSError:
                pass
        self.favorite_button.configure(
            text=(
                "Remover dos favoritos" if current_is_favorite else "Favoritar pasta"
            ),
            state=(
                "normal"
                if self._directory is not None and not self._loading
                else "disabled"
            ),
        )
        has_favorites = bool(self._favorite_path_by_label)
        self.favorite_menu.configure(
            state="normal" if has_favorites and not self._loading else "disabled"
        )
        selected_favorite = self._favorite_choice.get() in self._favorite_path_by_label
        self.remove_favorite_button.configure(
            state="normal" if selected_favorite and not self._loading else "disabled"
        )
        action_state = (
            "normal"
            if self._selected_entry is not None and not self._loading
            else "disabled"
        )
        self.open_button.configure(state=action_state)
        self.reveal_button.configure(state=action_state)
        for button in self._context_buttons:
            button.configure(state=action_state)
        if self._loading:
            self.show_more_button.configure(state="disabled")

    @staticmethod
    def _format_timestamp(value: float) -> str:
        try:
            return datetime.fromtimestamp(value).strftime("%d/%m/%Y %H:%M")
        except (OSError, OverflowError, ValueError):
            return "—"


class _PdfOrderRow(ctk.CTkFrame):
    """Mantém as ações acessíveis sem alterar a geometria da linha."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self._visibility_id = None

    def mount(self, radio, design, move):
        radio.grid(row=0, column=0, sticky="nsew")
        rail = ctk.CTkFrame(self, fg_color="transparent", width=32, height=48)
        rail.grid(row=0, column=1, sticky="e", padx=(4, 0))
        rail.grid_propagate(False)
        rail.grid_columnconfigure(0, weight=1)
        self.buttons = {}
        for index, (offset, symbol, key) in enumerate(
            ((-1, "↑", "Up"), (1, "↓", "Down"))
        ):
            button = design.button(
                rail,
                symbol,
                lambda step=offset: move(step),
                kind="secondary",
                keyboard=True,
                width=32,
                height=24,
            )
            button.configure(font=design.nav, fg_color=SURFACE, corner_radius=6)
            rail.grid_rowconfigure(index, weight=1, uniform="arrows")
            button.grid(row=index, column=0, sticky="nsew")
            button.grid_remove()
            self.buttons[offset] = button

            def move_by_key(_event, step=offset):
                move(step)
                return "break"

            tk.Misc.bind(radio, f"<Control-{key}>", move_by_key, add="+")

        tk.Misc.bind(self, "<Enter>", lambda _event: self._show_buttons(True), add="+")
        tk.Misc.bind(self, "<Leave>", self._schedule_visibility, add="+")
        for widget in (radio, *self.buttons.values()):
            tk.Misc.bind(widget, "<FocusIn>", self._reveal_focus, add="+")
            tk.Misc.bind(widget, "<FocusOut>", self._schedule_visibility, add="+")

    def configure_order(self, index, count, enabled):
        for offset, button in self.buttons.items():
            state = "normal" if enabled and 0 <= index + offset < count else "disabled"
            _configure_if_changed(button, state=state)

    def contains(self, widget):
        while widget is not None and widget is not self:
            widget = widget.master
        return widget is self

    def _reveal_focus(self, event):
        self._show_buttons(True)
        reveal_scrollable_focus(self.master, event.widget)

    def _show_buttons(self, show):
        for button in self.buttons.values():
            if show and not button.winfo_manager():
                button.grid()
            elif not show and button.winfo_manager():
                button.grid_remove()

    def _schedule_visibility(self, _event):
        if self._visibility_id is None:
            self._visibility_id = self.after_idle(self._sync_visibility)

    def _sync_visibility(self):
        self._visibility_id = None
        hovered = self.winfo_containing(*self.winfo_pointerxy())
        self._show_buttons(self.contains(hovered) or self.contains(self.focus_get()))

    def destroy(self):
        if self._visibility_id is not None:
            self.after_cancel(self._visibility_id)
        super().destroy()


class _OrderedPathList(ctk.CTkFrame):
    """Lista compacta e reordenável que exibe nomes, nunca caminhos completos."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        empty_text: str,
        on_change: Callable[[], None],
        on_selection_change: Callable[[], None] | None = None,
        detail_for_path: Callable[[Path], str | None] | None = None,
        enable_drag: bool = False,
        inline_order: bool = False,
        design: Design | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._design = design or Design(self.winfo_toplevel())
        self._empty_text = empty_text
        self._on_change = on_change
        self._on_selection_change = on_selection_change
        self._detail_for_path = detail_for_path
        self._inline_order = inline_order
        self._paths: list[Path] = []
        self._selected = tk.IntVar(value=-1)
        self._enabled = True
        self._rows = ScrollableFrame(
            self,
            height=126,
            corner_radius=CONTROL_RADIUS,
            fg_color=SOFT,
            scrollbar_fg_color=SOFT,
        )
        self._rows.pack(fill="x")
        self._rows.grid_columnconfigure(0, weight=1)
        self._row_controls: dict[int, ctk.CTkRadioButton] = {}
        self._drag = ImageListDrag(self) if enable_drag else None
        self._empty_label = self._design.form_label(
            self._rows,
            text=self._empty_text,
            text_color=MUTED,
        )
        self._render()

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(self._paths)

    @property
    def selected_index(self) -> int:
        return self._selected.get()

    def set_paths(self, paths: list[Path]) -> None:
        self._paths = list(paths)
        self._selected.set(0 if self._paths else -1)
        self._render()
        self._on_change()

    def add_paths(self, paths: list[Path]) -> int:
        """Acrescenta caminhos novos preservando ordem e identidade no Windows."""
        known_paths = {self._comparison_key(path) for path in self._paths}
        first_added_index = len(self._paths)
        for path in paths:
            comparison_key = self._comparison_key(path)
            if comparison_key in known_paths:
                continue
            self._paths.append(path)
            known_paths.add(comparison_key)
        added_count = len(self._paths) - first_added_index
        if added_count:
            self._selected.set(first_added_index)
            self._render()
            self._on_change()
        return added_count

    def remove_selected(self) -> None:
        selected = self.selected_index
        if selected < 0 or selected >= len(self._paths):
            return
        del self._paths[selected]
        self._selected.set(min(selected, len(self._paths) - 1))
        self._render()
        self._on_change()

    def move_selected(self, offset: int) -> None:
        self._move_item(self.selected_index, offset)

    def _move_item(self, index: int, offset: int) -> bool:
        target = index + offset
        if not (0 <= index < len(self._paths) and 0 <= target < len(self._paths)):
            return False
        self._paths[index], self._paths[target] = (
            self._paths[target],
            self._paths[index],
        )
        self._selected.set(target)
        self._render()
        self._on_change()
        self._mark_reordered(target)
        return True

    def _move_from_pdf_row(self, index: int, offset: int) -> None:
        if not self._enabled:
            return
        row = self._row_controls[index].master
        keep_focus = row.contains(self.focus_get())
        if self._move_item(index, offset) and keep_focus:
            tk.Misc.focus_set(self._row_controls[index + offset])

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled == enabled:
            return
        self._enabled = enabled
        if not enabled and self._drag is not None:
            self._drag.cancel()
        self._render()

    def move_to_insertion(self, source, insertion):
        if (
            not self._enabled
            or not 0 <= source < len(self._paths)
            or not 0 <= insertion <= len(self._paths)
        ):
            return
        target = insertion - (insertion > source)
        if target == source:
            return
        path = self._paths.pop(source)
        self._paths.insert(target, path)
        self._selected.set(target)
        self._render()
        self._on_change()
        self._mark_reordered(target)

    def _mark_reordered(self, target: int) -> None:
        motion = self._design.motion
        if motion is None or not motion.duration(160):
            return
        control = self._row_controls[target]

        def draw(fraction):
            if control.focus_get() is control:
                colors = LINK
            else:
                colors = tuple(
                    mix_color(a, b, fraction) for a, b in zip(LINK, DISABLED_TEXT)
                )
            _configure_if_changed(control, border_color=colors)

        motion.play(("reorder", id(self)), control, 160, draw)

    def destroy(self):
        if self._drag is not None:
            self._drag.cancel()
        super().destroy()

    def refresh(self) -> None:
        """Atualiza os rótulos sem alterar seleção, ordem ou caminhos."""

        self._render()

    @staticmethod
    def _comparison_key(path: Path) -> str:
        return ntpath.normcase(ntpath.abspath(str(path)))

    def _render(self) -> None:
        # Os controles pertencem às posições, inclusive quando há caminhos repetidos.
        # CTkRadioButton não permite reconfigurar seu value depois da criação.
        controls = {}
        name_counts = Counter(path.name for path in self._paths)
        for index, path in enumerate(self._paths):
            label = path.name
            if name_counts[path.name] > 1:
                label = f"{path.name} — {path.parent.name}"
            if self._detail_for_path is not None:
                detail = self._detail_for_path(path)
                if detail:
                    label = f"{label}\n{detail}"
            options = dict(
                text=f"{index + 1}. {label}",
                state="normal" if self._enabled else "disabled",
            )
            control = self._row_controls.get(index)
            if control is None:
                parent = _PdfOrderRow(self._rows) if self._inline_order else self._rows
                if self._inline_order:
                    options["width"] = 1
                control = self._design.form_radio(
                    parent,
                    variable=self._selected,
                    value=index,
                    command=self._on_selection_change,
                    **options,
                )
                if self._inline_order:
                    parent.mount(
                        control,
                        self._design,
                        lambda offset, i=index: self._move_from_pdf_row(i, offset),
                    )
                if self._drag is not None:
                    self._drag.bind_row(control, index)
            else:
                _configure_if_changed(control, **options)
            row = control.master if self._inline_order else control
            if self._inline_order:
                row.configure_order(index, len(self._paths), self._enabled)
            if not row.winfo_manager() or int(row.grid_info()["row"]) != index:
                row.grid(
                    row=index,
                    column=0,
                    sticky="w" if self._inline_order else "ew",
                    padx=8,
                    pady=4,
                )
            controls[index] = control
        for key, control in self._row_controls.items():
            if key not in controls:
                (control.master if self._inline_order else control).destroy()
        self._row_controls = controls
        if self._paths:
            self._empty_label.grid_remove()
        else:
            self._empty_label.grid(row=0, column=0, sticky="w", padx=8, pady=8)


class _PdfToolTabview(ctk.CTkTabview):
    """Seleciona ferramentas persistentes sem a ocultação adiada do CTkTabview."""

    def set(self, name: str) -> None:
        self.tab(name)  # Valida antes de alterar a ferramenta atual.
        if name == self.get():
            return
        # CTkTabview.set() mantém abas sobrepostas e agenda grid_forget em
        # 100 ms. Um callback antigo pode ocultar a seleção mais recente.
        # Usar a mesma geometria do CTk, mas completar a troca nesta chamada.
        self._grid_forget_all_tabs()
        self._current_name = name
        self._segmented_button.set(name)
        self._set_grid_current_tab()


_PDF_LOCAL_STATUS = "As operações são locais e não enviam arquivos pela rede."


@dataclass
class _PdfToolFeedback:
    status: tk.StringVar
    result_text: tk.StringVar
    paths: tuple[Path, ...] = ()
    info: ResultInfo | None = None
    generation: int = 0
    pending: bool = False
    opening_folder: bool | None = None

    @property
    def path(self) -> Path | None:
        return self.paths[0] if self.paths else None


class PdfToolsPage(ScrollableFrame):
    """Interface persistente para as ferramentas PDF locais."""

    is_placeholder = False
    tool_names = (
        "Juntar PDFs",
        "Extrair páginas",
        "Imagens → PDF",
        "PDF → Imagens",
        "Pôster/Painel",
        "PDF para Word",
    )

    _tool_headings = {
        "Juntar PDFs": (
            "Juntar PDFs",
            "Combine dois ou mais documentos na ordem desejada.",
        ),
        "Extrair páginas": (
            "Extrair páginas de PDF",
            "Crie outro PDF com as páginas escolhidas.",
        ),
        "Imagens → PDF": (
            "Imagens para PDF",
            "Organize as imagens em folhas prontas para imprimir.",
        ),
        "PDF → Imagens": (
            "PDF para imagens",
            "Salve páginas de um PDF como PNG ou JPG.",
        ),
        "Pôster/Painel": (
            "Criar pôster ou painel",
            "Divida uma imagem em folhas para montar um cartaz.",
        ),
        "PDF para Word": (
            "PDF para Word",
            "Transforme páginas digitais ou digitalizadas em um documento editável.",
        ),
    }

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        service: PdfToolsService,
        design: Design | None = None,
        poster_service: PosterService | None = None,
        docx_service: PdfToDocxService | None = None,
        actions: PdfPageActions,
        dialog_preferences: DialogFolderPreferences | None = None,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
        preferences: dict | None = None,
        persist_preferences: Callable | None = None,
    ) -> None:
        super().__init__(
            master, corner_radius=0, fg_color=CANVAS, scrollbar_fg_color=CANVAS
        )
        self._tool_design = design or Design(self.winfo_toplevel())
        self.grid_columnconfigure(0, weight=1)
        self._service = service
        self._poster_service = poster_service or PosterService()
        self._docx_service = docx_service or PdfToDocxService()
        self._word_source: Path | None = None
        self._word_destination: Path | None = None
        self._word_source_text = tk.StringVar(value="Nenhum arquivo selecionado")
        self._word_destination_text = tk.StringVar(
            value="Escolha onde salvar o documento Word"
        )
        self._word_progress_text = tk.StringVar()
        self._dialog_preferences = dialog_preferences or DialogFolderPreferences()
        self._visible_tool = None
        self._working_tool = None
        self._form_write_traces: list[tuple[tk.Variable, str]] = []
        self._tool_feedback = {
            name: _PdfToolFeedback(
                tk.StringVar(
                    master=self,
                    value=_PDF_LOCAL_STATUS,
                ),
                tk.StringVar(master=self),
            )
            for name in self.tool_names
        }
        self._result_after_id = None
        self._result_worker = PreviewWorker(PdfResultReader())
        self._image_rotations = {}
        self._image_analysis = None
        self._analysis_spec = None
        self._analysis_generation = 0
        self._analysis_after_id = None
        self._analysis_worker = PreviewWorker(ImagePreparationReader())
        self._images_estimate = tk.StringVar(
            value="Adicione imagens para estimar o tamanho."
        )
        self._images_quality = tk.StringVar()
        self._pdf_preference_message = tk.StringVar()
        self._persist_pdf_callback = persist_preferences
        self._actions = actions
        self._thread_factory = thread_factory
        self._results: Queue[_PdfWorkerResult] = Queue()
        self._images_progress_results: CoalescingQueue[
            tuple[int, ImagesToPdfProgress]
        ] = CoalescingQueue(lambda event: event[0])
        self._operation_progress_results: CoalescingQueue[
            tuple[int, PdfOperationProgress]
        ] = CoalescingQueue(lambda event: event[0])
        self._images_preview_results: Queue[_ImagesPdfPreviewResult] = Queue()
        self._page_preview_worker = PreviewWorker()
        self._merge_metadata_results: Queue[_MergeMetadataResult] = Queue()
        self._busy = False
        self._closed = False
        self._shutdown_requested = False
        self._images_state = _ImagesPdfUiState.READY
        self._images_generation = 0
        self._images_cancel_event: threading.Event | None = None
        self._images_paper = tk.StringVar(value="A4")
        self._images_orientation = tk.StringVar(value="Automática")
        self._images_margin = tk.StringVar(value="Normal")
        self._images_per_page = tk.StringVar(value="1 por página")
        self._images_margin_help = tk.StringVar()
        self._images_summary = tk.StringVar()
        self._images_progress_text = tk.StringVar()
        self._images_preview_generation = 0
        self._images_preview_after_id: str | None = None
        self._images_preview_worker_active = False
        self._images_preview_pending = False
        self._images_preview: _ImagesPdfPreview | None = None
        self._images_preview_failed = False
        self._images_preview_loading = False
        self._operation_state = _PdfOperationUiState.READY
        self._operation_name: str | None = None
        self._operation_generation = 0
        self._operation_cancel_event: threading.Event | None = None
        self._merge_progress_text = tk.StringVar()
        self._extract_progress_text = tk.StringVar()
        self._pdf_images_progress_text = tk.StringVar()
        self._merge_metadata_generation = 0
        self._merge_metadata_after_id: str | None = None
        self._merge_metadata_worker_active = False
        self._merge_metadata_pending = False
        self._merge_metadata: dict[str, str] = {}
        self._poster_source: Path | None = None
        self._poster_source_text = tk.StringVar(value="Nenhuma imagem selecionada")
        self._poster_grid = tk.StringVar(value="2 × 2")
        self._poster_paper = tk.StringVar(value="A4")
        self._poster_orientation = tk.StringVar(value="Automática")
        self._poster_overlap = tk.StringVar(value="Pequena")
        self._poster_crop_marks = tk.BooleanVar(value=False)
        self._poster_summary = tk.StringVar(value="4 folhas · Painel: 2 × 2 folhas")
        self._poster_quality = tk.StringVar(
            value="Escolha uma imagem para avaliar a qualidade."
        )
        self._poster_progress_text = tk.StringVar()
        self._poster_preview_results: Queue[_PosterPreviewResult] = Queue(maxsize=1)
        self._poster_preview_generation = 0
        self._poster_preview_after_id: str | None = None
        self._poster_preview_worker_active = False
        self._poster_preview_pending = False
        self._poster_preview: _PosterPreview | None = None
        self._poster_preview_failed = False
        self._poster_preview_loading = False
        self._poster_preview_tk_image: ImageTk.PhotoImage | None = None
        self._poster_display_key: tuple | None = None
        self._preview_theme_after_id: str | None = None
        self._preview_resize_after_id: str | None = None
        self._tool_height_after_id: str | None = None
        self._extract_source: Path | None = None
        self._extract_page_count: int | None = None
        self._extract_selection = tk.StringVar()
        self._extract_source_text = tk.StringVar(value="Nenhum PDF selecionado")
        self._extract_pages_text = tk.StringVar(
            value="Selecione um PDF para conferir as páginas."
        )
        self._extract_validation_text = tk.StringVar(
            value="Informe as páginas depois de selecionar um PDF."
        )
        self._extract_summary_text = tk.StringVar()
        self._pdf_images_source: Path | None = None
        self._pdf_images_page_count: int | None = None
        self._pdf_images_destination: Path | None = None
        self._pdf_images_selection = tk.StringVar()
        self._pdf_images_scope = tk.StringVar(value="Todas as páginas")
        self._pdf_images_format = tk.StringVar(value="PNG")
        self._pdf_images_quality = tk.StringVar(value="Padrão")
        self._pdf_images_source_text = tk.StringVar(value="Nenhum PDF selecionado")
        self._pdf_images_pages_text = tk.StringVar(
            value="Selecione um PDF para conferir as páginas."
        )
        self._pdf_images_destination_text = tk.StringVar(
            value="Nenhuma pasta selecionada"
        )
        self._pdf_images_summary_text = tk.StringVar()
        self._tool_title = tk.StringVar(value="Ferramentas PDF")
        self._tool_subtitle = tk.StringVar(
            value="Escolha uma ferramenta para seus arquivos."
        )
        self._tool_design.tool_header(self, self._tool_title, self._tool_subtitle).grid(
            row=0, column=0, padx=PAGE_INSET, pady=(PAGE_INSET, 16), sticky="ew"
        )

        self.tool_picker = ctk.CTkFrame(self, fg_color="transparent")
        self.tool_picker.grid(
            row=1, column=0, padx=PAGE_INSET, pady=(0, 14), sticky="ew"
        )
        self.tool_picker.grid_columnconfigure((0, 1), weight=1, uniform="pdf_tool")
        self.tool_cards: dict[str, ctk.CTkButton] = {}
        tool_descriptions = (
            "Combine arquivos na ordem que preferir.",
            "Salve as páginas escolhidas em outro PDF.",
            "Reúna imagens em páginas de um PDF.",
            "Exporte páginas como imagens.",
            "Prepare um painel para imprimir em folhas.",
            "Crie um documento editável com texto digital e OCR local.",
        )
        for index, (name, description) in enumerate(
            zip(self.tool_names, tool_descriptions, strict=True)
        ):
            row, column = divmod(index, 2)
            tile = _card(self.tool_picker)
            tile.grid(
                row=row,
                column=column,
                padx=(0, 10) if column == 0 else 0,
                pady=(0, 10),
                sticky="nsew",
            )
            tile.grid_columnconfigure(0, weight=1)
            self._tool_design.form_label(
                tile, text=name, font=ctk.CTkFont(size=18, weight="bold")
            ).grid(row=0, column=0, padx=20, pady=(18, 6), sticky="w")
            self._tool_design.form_label(tile, text=description, text_color=MUTED).grid(
                row=1, column=0, padx=20, pady=(0, 14), sticky="w"
            )
            button = self._tool_design.button(
                tile,
                text="Abrir ferramenta",
                height=CONTROL_HEIGHT,
                command=lambda selected=name: self._open_tool(selected),
                kind="secondary",
                keyboard=True,
            )
            button.grid(row=2, column=0, padx=20, pady=(0, 18), sticky="ew")
            self._tool_design.interactive_card(tile, button)
            self.tool_cards[name] = button

        self.tool_back_button = self._tool_design.button(
            self,
            text="Voltar às ferramentas",
            height=CONTROL_HEIGHT,
            width=190,
            command=self._show_tool_picker,
            kind="secondary",
            keyboard=True,
        )
        self.tool_back_button.grid(
            row=2, column=0, padx=PAGE_INSET, pady=(0, 10), sticky="w"
        )
        self.tool_back_button.grid_remove()

        self.tab_view = _PdfToolTabview(
            self, height=500, fg_color=SURFACE, corner_radius=16
        )
        self.tab_view.grid(row=3, column=0, padx=PAGE_INSET, pady=(0, 14), sticky="ew")
        for tool_name in self.tool_names:
            self.tab_view.add(tool_name)

        self._build_merge_tab(self.tab_view.tab(self.tool_names[0]))
        self._build_extract_tab(self.tab_view.tab(self.tool_names[1]))
        self._build_images_tab(self.tab_view.tab(self.tool_names[2]))
        self._build_pdf_to_images_tab(self.tab_view.tab(self.tool_names[3]))
        self._build_poster_tab(self.tab_view.tab(self.tool_names[4]))
        # Word uses a content-sized card, not the fixed-height preview tabs.
        self._word_feedback_active = False
        self.word_card = _card(self)
        self.word_card.grid(row=3, column=0, padx=PAGE_INSET, pady=(0, 28), sticky="ew")
        self._build_word_tab(self.word_card)
        self.word_card.grid_remove()
        # O hub é a navegação: o seletor interno do CTkTabview seria redundante.
        self.tab_view._segmented_button.grid_remove()
        self.tab_view.grid_remove()

        status_frame = _card(self)
        self._pdf_status_frame = status_frame
        status_frame.grid(row=4, column=0, padx=PAGE_INSET, pady=(0, 28), sticky="ew")
        status_frame.grid_remove()
        status_frame.grid_columnconfigure(0, weight=1)
        self._pdf_status_label = self._tool_design.form_label(
            status_frame,
            textvariable=self._status,
            anchor="w",
            justify="left",
            wraplength=680,
        )
        self._pdf_status_label.grid(row=0, column=0, padx=16, pady=(12, 6), sticky="ew")
        self.progress_bar = ProgressBar(status_frame, mode="indeterminate")
        self.progress_bar.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")
        self.progress_bar.set(0)
        result_actions = ctk.CTkFrame(status_frame, fg_color="transparent")
        self._pdf_result_actions = result_actions
        result_actions.grid(row=2, column=0, padx=16, pady=(0, 12), sticky="w")
        self.open_file_button = self._tool_design.button(
            result_actions,
            text="Abrir arquivo",
            state="disabled",
            command=lambda: self._open_result(False),
            kind="secondary",
            keyboard=True,
        )
        self.open_file_button.pack(side="left", padx=(0, 8))
        self.open_folder_button = self._tool_design.button(
            result_actions,
            text="Abrir pasta",
            state="disabled",
            command=lambda: self._open_result(True),
            kind="secondary",
            keyboard=True,
        )
        self.open_folder_button.pack(side="left")
        self._pdf_result_label = self._tool_design.form_label(
            status_frame,
            textvariable=self._feedback_for().result_text,
            wraplength=680,
            anchor="w",
            justify="left",
        )
        self._pdf_result_label.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="ew")

        self._trace_form_write(
            self._extract_selection, lambda *_args: self._on_extract_selection_changed()
        )

        def image_options_changed(*_args):
            self._on_pdf_images_options_changed()

        self._trace_form_write(self._pdf_images_selection, image_options_changed)
        self._trace_form_write(self._pdf_images_scope, image_options_changed)
        self._update_images_summary()
        self._update_poster_summary()
        self._refresh_controls()
        self._load_pdf_preferences(preferences)

    def _build_word_tab(self, tab) -> None:
        design = self._tool_design
        tab.grid_columnconfigure(0, weight=1)
        source = ctk.CTkFrame(tab, fg_color="transparent")
        source.grid(row=0, column=0, padx=CARD_INSET, pady=(18, 10), sticky="ew")
        source.grid_columnconfigure(0, weight=1)
        design.form_label(source, text="Arquivo PDF", font=design.heading).grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.word_source_label = design.form_label(
            source,
            textvariable=self._word_source_text,
            wraplength=235,
            text_color=MUTED,
            fg_color=SOFT,
            corner_radius=CONTROL_RADIUS,
            padx=10,
            pady=8,
        )
        self.word_source_label.grid(row=1, column=0, sticky="ew")
        self.word_select_button = design.button(
            source,
            "Selecionar PDF",
            self._select_word_source,
            width=146,
            keyboard=True,
        )
        self.word_select_button.grid(row=0, column=1, rowspan=2, padx=(10, 0))
        wrap_to_frame(source, self.word_source_label, reserved=178)

        destination = ctk.CTkFrame(tab, fg_color="transparent")
        destination.grid(row=1, column=0, padx=CARD_INSET, pady=(0, 14), sticky="ew")
        destination.grid_columnconfigure(0, weight=1)
        design.form_label(destination, text="Documento Word", font=design.control).grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.word_destination_label = design.form_label(
            destination,
            textvariable=self._word_destination_text,
            text_color=MUTED,
            wraplength=235,
        )
        self.word_destination_label.grid(row=1, column=0, sticky="ew")
        self.word_destination_button = design.button(
            destination,
            "Escolher destino",
            self._choose_word_destination,
            kind="secondary",
            width=146,
            keyboard=True,
        )
        self.word_destination_button.grid(row=0, column=1, rowspan=2, padx=(10, 0))
        wrap_to_frame(destination, self.word_destination_label, reserved=158)

        self.word_hint_label = design.form_label(
            tab,
            text=(
                "A conversão prioriza o texto existente e usa OCR local quando necessário "
                "e disponível. Revise no Word o texto reconhecido e os layouts complexos."
            ),
            fg_color=SOFT,
            corner_radius=CONTROL_RADIUS,
            padx=12,
            pady=10,
            wraplength=520,
            text_color=MUTED,
        )
        self.word_hint_label.grid(
            row=2,
            column=0,
            padx=CARD_INSET,
            pady=(0, 14),
            sticky="ew",
        )
        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=3, column=0, padx=CARD_INSET, pady=(0, 18), sticky="w")
        self.word_convert_button = self._tool_design.button(
            actions,
            text="Converter para Word",
            command=self._convert_word,
            height=CONTROL_HEIGHT,
            width=190,
            kind="primary",
            keyboard=True,
        )
        self.word_convert_button.grid(row=0, column=0, sticky="w")
        self.word_cancel_button = self._tool_design.button(
            actions,
            text="Cancelar",
            command=lambda: self._cancel_pdf_operation("word"),
            kind="danger",
            keyboard=True,
        )
        self.word_cancel_button.grid(row=0, column=1, padx=(10, 0))
        self.word_feedback = ctk.CTkFrame(tab, fg_color="transparent")
        self.word_feedback.grid(
            row=4, column=0, padx=CARD_INSET, pady=(0, 18), sticky="ew"
        )
        self.word_feedback.grid_columnconfigure(0, weight=1)
        self.word_status_label = self._tool_design.form_label(
            self.word_feedback,
            textvariable=self._feedback_for(self.tool_names[-1]).status,
            justify="left",
            anchor="w",
            wraplength=580,
        )
        self.word_status_label.grid(row=0, column=0, sticky="ew")
        self.word_progress = ctk.CTkFrame(self.word_feedback, fg_color="transparent")
        self.word_progress.grid(row=1, column=0, pady=(6, 0), sticky="ew")
        self.word_progress.grid_columnconfigure(0, weight=1)
        self.word_progress_bar = ProgressBar(self.word_progress)
        self.word_progress_bar.grid(row=0, column=0, sticky="ew")
        self._tool_design.form_label(
            self.word_progress,
            textvariable=self._word_progress_text,
            text_color=MUTED,
        ).grid(row=1, column=0, sticky="w")
        self.word_result_actions = ctk.CTkFrame(
            self.word_feedback, fg_color="transparent"
        )
        self.word_result_actions.grid(row=2, column=0, pady=(10, 0), sticky="w")
        self.word_open_file_button = self._tool_design.button(
            self.word_result_actions,
            text="Abrir arquivo",
            command=lambda: self._open_result(False),
            kind="secondary",
            keyboard=True,
        )
        self.word_open_file_button.grid(row=0, column=0)
        self.word_open_folder_button = self._tool_design.button(
            self.word_result_actions,
            text="Abrir pasta",
            command=lambda: self._open_result(True),
            kind="secondary",
            keyboard=True,
        )
        self.word_open_folder_button.grid(row=0, column=1, padx=8)
        self.word_new_button = self._tool_design.button(
            self.word_result_actions,
            text="Nova conversão",
            command=self._new_word_conversion,
            kind="secondary",
            keyboard=True,
        )
        self.word_new_button.grid(row=0, column=2)
        tab.bind("<Configure>", self._resize_word_card, add="+")

    def _resize_word_card(self, event) -> None:
        width = max(180, event.width - 40)
        _configure_if_changed(self.word_hint_label, wraplength=max(140, width - 32))
        _configure_if_changed(self.word_status_label, wraplength=width)
        # Keep post-actions reachable in narrow windows without horizontal scroll.
        narrow = width < 460
        if getattr(self, "_word_layout_narrow", None) != narrow:
            self._word_layout_narrow = narrow
            if narrow:
                self.word_new_button.grid(
                    row=1, column=0, columnspan=2, pady=(8, 0), sticky="w"
                )
            else:
                self.word_new_button.grid(
                    row=0, column=2, columnspan=1, pady=0, sticky="w"
                )

    def _refresh_word_presentation(self) -> None:
        running = self._busy and self._operation_name == "word"
        feedback = self._feedback_for(self.tool_names[-1])
        succeeded = (
            self._word_feedback_active
            and feedback.info is not None
            and not self._shutdown_requested
        )
        for widget, visible in (
            (self.word_cancel_button, running),
            (self.word_feedback, self._word_feedback_active),
            (self.word_progress, running),
            (self.word_result_actions, succeeded),
        ):
            _set_grid_visible(widget, visible)
        progress = self.progress_bar.get() if running else 0
        if self.word_progress_bar.get() != progress:
            self.word_progress_bar.set(progress)
        for button, callback in (
            (self.word_open_file_button, self._actions.open_result_file),
            (self.word_open_folder_button, self._actions.open_result_folder),
        ):
            _configure_if_changed(
                button,
                state="normal"
                if succeeded and callback and not feedback.pending
                else "disabled",
            )
        _configure_if_changed(
            self.word_new_button,
            state="normal" if succeeded and not self._busy else "disabled",
        )

    def _new_word_conversion(self) -> None:
        if not self._can_accept_handoff():
            return
        self._word_feedback_active = False
        self._word_source = self._word_destination = None
        self._word_source_text.set("Nenhum arquivo selecionado")
        self._word_destination_text.set("Escolha onde salvar o documento Word")
        self._word_progress_text.set("")
        self._set_result(None)
        self._refresh_controls()
        self._parent_canvas.yview_moveto(0.0)

    def prepare_pdf_to_docx_source(self, path: Path | str) -> bool:
        """A handoff only selects a local PDF; no parse or conversion on the UI thread."""
        if not self._can_accept_handoff():
            return False
        try:
            source = validate_local_regular_file(path)
            if source.suffix.casefold() != ".pdf":
                raise LocalFilesError("Selecione um arquivo PDF.")
        except LocalFilesError as error:
            self._actions.show_error(str(error))
            return False
        self._word_feedback_active = False
        self._word_source = source
        folder = self._dialog_preferences.available("pdf_word.output") or source.parent
        self._word_destination = folder / (source.stem + ".docx")
        self._word_source_text.set(source.name)
        self._word_destination_text.set(str(self._word_destination))
        self._word_progress_text.set("")
        self._dialog_preferences.remember("pdf_word.input", source.parent)
        self._open_tool("PDF para Word")
        self._set_result(None)
        self._reset_pdf_progress_bar()
        self._status.set(
            "PDF selecionado. Confira o destino e clique em Converter para Word."
        )
        self._refresh_controls()
        return True

    def _select_word_source(self):
        if not self._can_accept_handoff():
            return
        selected = self._dialog_preferences.choose(
            filedialog.askopenfilename,
            "pdf_word.input",
            parent=self.winfo_toplevel(),
            title="Selecionar PDF",
            filetypes=(("Arquivo PDF", "*.pdf"),),
        )
        if selected:
            self.prepare_pdf_to_docx_source(selected)

    def _choose_word_destination(self):
        if not self._can_accept_handoff() or self._word_source is None:
            return
        selected = self._dialog_preferences.choose(
            filedialog.asksaveasfilename,
            "pdf_word.output",
            parent=self.winfo_toplevel(),
            title="Salvar documento Word",
            defaultextension=".docx",
            initialfile=self._word_source.stem + ".docx",
            filetypes=(("Documento Word", "*.docx"),),
            confirmoverwrite=False,
        )
        if selected:
            self._word_feedback_active = False
            self._word_destination = Path(selected)
            self._word_destination_text.set(selected)
            self._set_result(None)
            self._refresh_controls()

    def _convert_word(self):
        if (
            not self._can_accept_handoff()
            or self._word_source is None
            or self._word_destination is None
        ):
            return
        source, output = self._word_source, self._word_destination
        overwrite = output.exists()
        if overwrite and not self._actions.confirm_overwrite(
            f'O arquivo "{output.name}" já existe. Deseja substituí-lo?'
        ):
            return
        self._set_result(None)
        self._word_feedback_active = True
        self._dialog_preferences.remember("pdf_word.output", output.parent)
        self._start_pdf_operation_worker(
            "word",
            lambda cancel, progress: self._docx_service.convert(
                source,
                output,
                overwrite=overwrite,
                cancel_event=cancel,
                progress=progress,
            ),
            self._complete_word,
            "Convertendo para Word…",
        )

    def _complete_word(self, result: PdfToDocxResult):
        self._set_result(result.output_path)
        message = "Documento criado com sucesso."
        if result.non_editable_pages:
            message += " Algumas páginas foram preservadas como imagens e não possuem texto editável."
        if result.ocr_pages:
            count = len(result.ocr_pages)
            unit = "página" if count == 1 else "páginas"
            message += f" Texto em imagens reconhecido em {count} {unit}. Revise o conteúdo no Word, especialmente acentos, números e operações."
        if result.review_pages:
            pages = ", ".join(map(str, result.review_pages[:12]))
            if len(result.review_pages) > 12:
                pages += ", …"
            message += f" Reconhecimento incerto ou parcial nas páginas: {pages}."
        if result.ocr_unavailable_pages:
            message += " O componente OCR local está indisponível: parte do texto em imagens não foi recuperada."
        self._status.set(message)
        if self._actions.notify is None:
            self._actions.show_info(message)
        elif (
            result.ocr_pages
            or result.non_editable_pages
            or result.ocr_unavailable_pages
        ):
            self._actions.notify(
                "warning", "Documento criado. Confira o conteúdo no Word."
            )
        else:
            self._actions.notify("success", "Documento Word criado com sucesso.")

    def _open_tool(self, name: str) -> None:
        """Abre uma ferramenta sem recriar os controles nem o estado existente."""

        if self._shutdown_requested:
            return
        viewport_change = getattr(self, "_viewport_change", nullcontext)
        with (
            viewport_change()
            if getattr(self, "_visible_tool", None) != name
            else nullcontext()
        ):
            self.tab_view.set(name)
            self._visible_tool = name
            title, subtitle = self._tool_headings[name]
            self._tool_title.set(title)
            self._tool_subtitle.set(subtitle)
            if hasattr(self, "_page_preview_worker") and name != "PDF para Word":
                self.tab_view.configure(
                    height=max(500, self.tab_view.tab(name).winfo_reqheight() + 36)
                )
            self.tool_picker.grid_remove()
            self.tool_back_button.grid()
            if name == "PDF para Word":
                self.tab_view.grid_remove()
                self.word_card.grid()
            else:
                self.word_card.grid_remove()
                self.tab_view.grid()
            self._refresh_result_actions()
            self._parent_canvas.yview_moveto(0.0)
            self._schedule_tool_height()

    def _show_tool_picker(self) -> None:
        if self._shutdown_requested:
            return
        viewport_change = getattr(self, "_viewport_change", nullcontext)
        with (
            viewport_change()
            if getattr(self, "_visible_tool", None) is not None
            else nullcontext()
        ):
            self._visible_tool = None
            self.tab_view.grid_remove()
            self.word_card.grid_remove()
            self.tool_back_button.grid_remove()
            self.tool_picker.grid()
            self._refresh_result_actions()
            self._tool_title.set("Ferramentas PDF")
            self._tool_subtitle.set("Escolha uma ferramenta para seus arquivos.")
            self._parent_canvas.yview_moveto(0.0)

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def is_shutdown_ready(self) -> bool:
        return self._shutdown_requested and not self._busy

    def begin_shutdown(self) -> None:
        """Impede novos trabalhos; cancela Word e aguarda a limpeza do worker."""

        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        if self._busy and self._operation_name == "word":
            self._cancel_pdf_operation("word")
            self._status.set("Cancelando a conversão para fechar com segurança...")
        elif self._busy:
            self._status.set("Aguardando a operação PDF terminar com segurança...")
        self._refresh_controls()

    def cancel_shutdown(self) -> None:
        """Restaura a página quando o fechamento global não pode prosseguir."""

        if not self._shutdown_requested:
            return
        self._shutdown_requested = False
        self._refresh_controls()

    def close(self) -> None:
        self._closed = True
        while self._form_write_traces:
            variable, token = self._form_write_traces.pop()
            variable.trace_remove("write", token)
        if hasattr(self, "image_files") and self.image_files._drag is not None:
            self.image_files._drag.cancel()
        for worker in (self._analysis_worker, self._result_worker):
            worker.close()
        for name in ("_analysis_after_id", "_result_after_id"):
            identifier = getattr(self, name, None)
            if identifier is not None:
                self.after_cancel(identifier)
            setattr(self, name, None)
        for name in (
            "merge_page_preview",
            "extract_page_preview",
            "images_page_preview",
            "pdf_images_page_preview",
            "poster_page_preview",
        ):
            pane = getattr(self, name, None)
            if pane is not None:
                pane.close()
        broker = getattr(self, "_page_preview_worker", None)
        if broker is not None:
            broker.close()
        self._images_preview_generation += 1
        self._poster_preview_generation += 1
        self._merge_metadata_generation += 1
        if self._preview_resize_after_id is not None:
            try:
                self.after_cancel(self._preview_resize_after_id)
            except tk.TclError:
                pass
            self._preview_resize_after_id = None
        if self._tool_height_after_id is not None:
            self.after_cancel(self._tool_height_after_id)
            self._tool_height_after_id = None
        if self._preview_theme_after_id is not None:
            try:
                self.after_cancel(self._preview_theme_after_id)
            except tk.TclError:
                pass
            self._preview_theme_after_id = None
        if self._images_preview_after_id is not None:
            try:
                self.after_cancel(self._images_preview_after_id)
            except tk.TclError:
                pass
            self._images_preview_after_id = None
        if self._merge_metadata_after_id is not None:
            try:
                self.after_cancel(self._merge_metadata_after_id)
            except tk.TclError:
                pass
            self._merge_metadata_after_id = None
        if self._poster_preview_after_id is not None:
            try:
                self.after_cancel(self._poster_preview_after_id)
            except tk.TclError:
                pass
            self._poster_preview_after_id = None
        self._clear_poster_preview()
        while True:
            try:
                queued = self._poster_preview_results.get_nowait()
            except Empty:
                break
            if queued.preview is not None:
                queued.preview.thumbnail.close()

    def _schedule_preview_redraw(self) -> None:
        if self._closed or self._preview_resize_after_id is not None:
            return

        def redraw():
            self._preview_resize_after_id = None
            if self._closed:
                return
            if self.images_preview_canvas.winfo_ismapped():
                self._render_images_preview()
            if self.poster_preview_canvas.winfo_ismapped():
                self._render_poster_preview()

        self._preview_resize_after_id = self.after_idle(redraw)

    def _schedule_tool_height(self):
        if self._closed or self._tool_height_after_id is not None:
            return

        def fit():
            self._tool_height_after_id = None
            if self._closed or not self.tab_view.winfo_ismapped():
                return
            panel = self.tab_view.tab(self.tab_view.get())
            height = int(panel._reverse_widget_scaling(panel.winfo_reqheight()))
            _configure_if_changed(self.tab_view, height=max(500, height + 36))

        self._tool_height_after_id = self.after_idle(fit)

    def _arrange_tool_preview(self, tab, preview, *, wide_span, narrow_row):
        wide = None

        def arrange(event):
            nonlocal wide
            fits = tab._reverse_widget_scaling(event.width) >= 720
            if fits == wide:
                return
            wide = fits
            tab.grid_columnconfigure(0, weight=3, uniform="tool_panel" if wide else "")
            tab.grid_columnconfigure(
                1, weight=2 if wide else 0, uniform="tool_panel" if wide else ""
            )
            preview.grid_configure(
                row=1 if wide else narrow_row,
                column=1 if wide else 0,
                rowspan=wide_span if wide else 1,
                columnspan=1 if wide else 2,
                padx=(8, 16) if wide else 16,
            )
            self._schedule_tool_height()

        tk.Misc.bind(tab, "<Configure>", arrange, add="+")

    def destroy(self):
        if not getattr(self, "_closed", True):
            self.close()
        super().destroy()

    def _set_appearance_mode(self, mode_string: str) -> None:
        after_id = getattr(self, "_preview_theme_after_id", None)
        if after_id is not None:
            self.after_cancel(after_id)
            self._preview_theme_after_id = None
        super()._set_appearance_mode(mode_string)
        if not hasattr(self, "images_preview_canvas") or self._closed:
            return

        def redraw():
            self._preview_theme_after_id = None
            if not self._closed:
                self._render_images_preview()
                self._render_poster_preview()

        self._preview_theme_after_id = self.after_idle(redraw)

    def prepare_extract_source(self, path: Path | str) -> bool:
        """Prepara um PDF para Extração de páginas sem iniciar a operação final."""

        if not self._can_accept_handoff():
            return False
        source = _validated_handoff_file(path, _PDF_SUFFIXES)
        if source is None:
            self._actions.show_warning("Selecione um arquivo PDF válido.")
            return False
        self._open_tool(self.tool_names[1])
        self._prepare_extract_source(source)
        return True

    def prepare_pdf_to_images_source(self, path: Path | str) -> bool:
        """Prepara um PDF para exportar imagens sem iniciar a exportação."""

        if not self._can_accept_handoff():
            return False
        source = _validated_handoff_file(path, _PDF_SUFFIXES)
        if source is None:
            self._actions.show_warning("Selecione um arquivo PDF válido.")
            return False
        self._open_tool(self.tool_names[3])
        self._prepare_pdf_images_source(source)
        return True

    def add_image_to_pdf(self, path: Path | str) -> bool:
        """Acrescenta uma imagem válida à lista sem iniciar a criação do PDF."""

        if not self._can_accept_handoff():
            return False
        source = _validated_handoff_file(path, SUPPORTED_IMAGE_SUFFIXES)
        if source is None:
            self._actions.show_warning("Selecione uma imagem JPG ou PNG válida.")
            return False
        self._open_tool(self.tool_names[2])
        if not self._add_image_paths([source]):
            self._status.set(f'"{source.name}" já está na lista de imagens.')
        return True

    def prepare_poster_source(self, path: Path | str) -> bool:
        """Prepara uma imagem no pôster sem iniciar a operação final."""

        if not self._can_accept_handoff():
            return False
        source = _validated_handoff_file(path, SUPPORTED_IMAGE_SUFFIXES)
        if source is None:
            self._actions.show_warning("Selecione uma imagem JPG ou PNG válida.")
            return False
        self._open_tool(self.tool_names[4])
        self._prepare_poster_source(source)
        return True

    def _build_merge_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        self._tool_design.form_label(
            tab,
            text="Arquivos selecionados",
            font=self._tool_design.heading,
            wraplength=640,
        ).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")
        self.merge_select_button = self._tool_design.button(
            tab,
            text="Adicionar PDFs",
            command=self._select_merge_files,
            kind="primary",
            keyboard=True,
        )
        self.merge_select_button.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")
        self.merge_files = _OrderedPathList(
            tab,
            empty_text="Selecione pelo menos dois PDFs.",
            on_change=self._on_merge_list_changed,
            on_selection_change=self._refresh_controls,
            detail_for_path=self._merge_detail_for_path,
            enable_drag=True,
            inline_order=True,
            design=self._tool_design,
        )
        self.merge_files.grid(row=2, column=0, padx=16, sticky="ew")
        order = ctk.CTkFrame(tab, fg_color="transparent")
        order.grid(row=3, column=0, padx=16, pady=8, sticky="w")
        self.merge_remove_button = self._tool_design.button(
            order,
            text="Remover item",
            width=120,
            command=self.merge_files.remove_selected,
            kind="secondary",
            keyboard=True,
        )
        self.merge_remove_button.pack(side="left")
        merge_actions = ctk.CTkFrame(tab, fg_color="transparent")
        merge_actions.grid(row=4, column=0, padx=16, pady=(4, 4), sticky="ew")
        merge_actions.grid_columnconfigure(0, weight=1)
        self.merge_run_button = self._tool_design.button(
            merge_actions,
            text="Juntar e salvar...",
            height=38,
            command=self._start_merge,
            kind="primary",
            keyboard=True,
        )
        self.merge_run_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.merge_cancel_button = self._tool_design.button(
            merge_actions,
            text="Cancelar",
            width=120,
            height=38,
            command=lambda: self._cancel_pdf_operation("merge"),
            kind="danger",
            keyboard=True,
        )
        self.merge_cancel_button.grid(row=0, column=1)
        self._tool_design.form_label(
            tab,
            textvariable=self._merge_progress_text,
            text_color=MUTED,
        ).grid(row=5, column=0, padx=16, pady=(0, 12), sticky="w")
        self.merge_page_preview = PagePreviewPane(
            tab,
            self._page_preview_worker,
            design=self._tool_design,
            on_result=self._merge_preview_ready,
        )
        self.merge_page_preview.grid(row=6, column=0, padx=16, pady=8, sticky="nsew")

    def _build_extract_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        self._tool_design.form_label(
            tab,
            text="Arquivo de origem",
            font=self._tool_design.heading,
            wraplength=640,
        ).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")
        self.extract_select_button = self._tool_design.button(
            tab,
            text="Selecionar PDF",
            command=self._select_extract_source,
            kind="primary",
            keyboard=True,
        )
        self.extract_select_button.grid(
            row=1, column=0, padx=16, pady=(0, 8), sticky="w"
        )
        self._tool_design.form_label(
            tab,
            textvariable=self._extract_source_text,
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=2, column=0, padx=16, sticky="w")
        self._tool_design.form_label(tab, textvariable=self._extract_pages_text).grid(
            row=3, column=0, padx=16, pady=(2, 12), sticky="w"
        )
        self._tool_design.form_label(tab, text="Páginas ou faixas").grid(
            row=4, column=0, padx=16, pady=(0, 4), sticky="w"
        )
        self.extract_entry = self._tool_design.form_entry(
            tab,
            textvariable=self._extract_selection,
            placeholder_text="Ex.: 1-3,5,8-10",
        )
        self.extract_entry.grid(row=5, column=0, padx=16, sticky="ew")
        self._tool_design.form_label(
            tab,
            text="A numeração começa em 1. Páginas repetidas serão mantidas.",
            text_color=MUTED,
        ).grid(row=6, column=0, padx=16, pady=(5, 4), sticky="w")
        self._tool_design.form_label(
            tab,
            textvariable=self._extract_validation_text,
            text_color=MUTED,
        ).grid(row=7, column=0, padx=16, pady=(0, 2), sticky="w")
        self._tool_design.form_label(
            tab,
            textvariable=self._extract_summary_text,
            text_color=MUTED,
        ).grid(row=8, column=0, padx=16, pady=(0, 8), sticky="w")
        extract_actions = ctk.CTkFrame(tab, fg_color="transparent")
        extract_actions.grid(row=9, column=0, padx=16, pady=(0, 4), sticky="ew")
        extract_actions.grid_columnconfigure(0, weight=1)
        self.extract_run_button = self._tool_design.button(
            extract_actions,
            text="Extrair e salvar...",
            height=38,
            command=self._start_extract,
            kind="primary",
            keyboard=True,
        )
        self.extract_run_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.extract_cancel_button = self._tool_design.button(
            extract_actions,
            text="Cancelar",
            width=120,
            height=38,
            command=lambda: self._cancel_pdf_operation("extract"),
            kind="danger",
            keyboard=True,
        )
        self.extract_cancel_button.grid(row=0, column=1)
        self._tool_design.form_label(
            tab,
            textvariable=self._extract_progress_text,
            text_color=MUTED,
        ).grid(row=10, column=0, padx=16, pady=(0, 12), sticky="w")
        self.extract_page_preview = PagePreviewPane(
            tab,
            self._page_preview_worker,
            design=self._tool_design,
            on_toggle_selection=self._toggle_extract_page,
        )
        self.extract_page_preview.grid(row=11, column=0, padx=16, pady=8, sticky="nsew")
        wrap_to_frame(
            tab,
            *(
                child
                for child in tab.winfo_children()
                if isinstance(child, ctk.CTkLabel)
            ),
            reserved=32,
        )

    def _build_images_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure((0, 1), weight=1, uniform="image_pdf_column")
        tab.grid_rowconfigure(4, weight=1)
        self._tool_design.form_label(
            tab,
            text="Imagens selecionadas",
            font=self._tool_design.heading,
            wraplength=640,
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="w")
        self.images_select_button = self._tool_design.button(
            tab,
            text="Adicionar imagens",
            command=self._select_images,
            kind="primary",
            keyboard=True,
        )
        self.images_select_button.grid(
            row=1, column=0, padx=(16, 8), pady=(0, 8), sticky="w"
        )
        self.image_files = _OrderedPathList(
            tab,
            empty_text="Selecione uma ou mais imagens JPG/PNG.",
            on_change=self._on_image_list_changed,
            on_selection_change=self._on_image_selected,
            detail_for_path=self._image_detail,
            enable_drag=True,
            design=self._tool_design,
        )
        self.image_files.grid(row=2, column=0, padx=(16, 8), sticky="ew")
        order = ctk.CTkFrame(tab, fg_color="transparent")
        order.grid(row=3, column=0, padx=(16, 8), pady=8, sticky="w")
        self.images_up_button = self._tool_design.button(
            order,
            text="Subir",
            width=80,
            command=lambda: self.image_files.move_selected(-1),
            kind="secondary",
            keyboard=True,
        )
        self.images_up_button.grid(row=0, column=0, padx=(0, 6))
        self.images_down_button = self._tool_design.button(
            order,
            text="Descer",
            width=80,
            command=lambda: self.image_files.move_selected(1),
            kind="secondary",
            keyboard=True,
        )
        self.images_down_button.grid(row=0, column=1)
        self.images_remove_button = self._tool_design.button(
            order,
            text="Remover item",
            width=100,
            command=self.image_files.remove_selected,
            kind="secondary",
            keyboard=True,
        )
        self.images_remove_button.grid(row=0, column=2, padx=(6, 0))
        self.images_rotate_left = self._tool_design.button(
            order,
            text="↶ 90°",
            width=80,
            command=lambda: self._rotate_image(-90),
            kind="secondary",
            keyboard=True,
        )
        self.images_rotate_left.grid(row=1, column=0, pady=(6, 0))
        self.images_rotate_right = self._tool_design.button(
            order,
            text="↷ 90°",
            width=80,
            command=lambda: self._rotate_image(90),
            kind="secondary",
            keyboard=True,
        )
        self.images_rotate_right.grid(row=1, column=1, pady=(6, 0))

        options = ctk.CTkFrame(tab, fg_color="transparent")
        options.grid(row=4, column=0, padx=(16, 8), pady=(0, 8), sticky="new")
        options.grid_columnconfigure((0, 1), weight=1)
        self._tool_design.form_label(options, text="Papel").grid(
            row=0, column=0, sticky="w"
        )
        self._tool_design.form_label(options, text="Orientação").grid(
            row=0, column=1, sticky="w"
        )
        self.images_paper_menu = self._tool_design.form_menu(
            options,
            values=["A4", "Carta"],
            variable=self._images_paper,
            command=lambda _value: self._on_images_layout_changed(),
        )
        self.images_paper_menu.grid(row=1, column=0, padx=(0, 6), sticky="ew")
        self.images_orientation_menu = self._tool_design.form_menu(
            options,
            values=["Automática", "Retrato", "Paisagem"],
            variable=self._images_orientation,
            command=lambda _value: self._on_images_layout_changed(),
        )
        self.images_orientation_menu.grid(row=1, column=1, sticky="ew")
        self._tool_design.form_label(options, text="Margem").grid(
            row=2, column=0, pady=(7, 0), sticky="w"
        )
        self._tool_design.form_label(options, text="Imagens por página").grid(
            row=2, column=1, pady=(7, 0), sticky="w"
        )
        self.images_margin_menu = self._tool_design.form_menu(
            options,
            values=["Sem margem", "Pequena", "Normal"],
            variable=self._images_margin,
            command=lambda _value: self._on_images_layout_changed(),
        )
        self.images_margin_menu.grid(row=3, column=0, padx=(0, 6), sticky="ew")
        self.images_per_page_menu = self._tool_design.form_menu(
            options,
            values=["1 por página", "2 por página", "4 por página"],
            variable=self._images_per_page,
            command=lambda _value: self._on_images_layout_changed(),
        )
        self.images_per_page_menu.grid(row=3, column=1, sticky="ew")
        self._tool_design.form_label(
            options,
            textvariable=self._images_margin_help,
            text_color=MUTED,
            wraplength=320,
        ).grid(row=4, column=0, columnspan=2, pady=(4, 0), sticky="w")

        preview = ctk.CTkFrame(tab, corner_radius=CONTROL_RADIUS, fg_color=SOFT)
        preview.grid(
            row=1,
            column=1,
            rowspan=4,
            padx=(8, 16),
            pady=(0, 8),
            sticky="nsew",
        )
        preview.grid_columnconfigure(0, weight=1)
        self._tool_design.form_label(
            preview,
            text="Pré-visualização",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(10, 5), sticky="w")
        self.images_page_preview = PagePreviewPane(
            preview,
            self._page_preview_worker,
            height=250,
            design=self._tool_design,
            empty_text="Adicione imagens para visualizar o resultado.",
        )
        self.images_page_preview.grid(row=1, column=0, padx=5, sticky="nsew")
        self.images_preview_canvas = self.images_page_preview.canvas
        self._tool_design.form_label(
            preview,
            textvariable=self._images_summary,
            text_color=MUTED,
        ).grid(row=2, column=0, padx=12, pady=(6, 2), sticky="w")
        self._tool_design.form_label(
            preview,
            textvariable=self._images_progress_text,
            text_color=MUTED,
        ).grid(row=3, column=0, padx=12, pady=(0, 9), sticky="w")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(
            row=5,
            column=0,
            columnspan=2,
            padx=16,
            pady=(4, 14),
            sticky="ew",
        )
        actions.grid_columnconfigure(0, weight=1)
        self.images_run_button = self._tool_design.button(
            actions,
            text="Criar e salvar...",
            height=38,
            command=self._start_images,
            kind="primary",
            keyboard=True,
        )
        self.images_run_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.images_cancel_button = self._tool_design.button(
            actions,
            text="Cancelar",
            width=120,
            height=38,
            command=self._cancel_images,
            kind="danger",
            keyboard=True,
        )
        self.images_cancel_button.grid(row=0, column=1, sticky="e")
        self._arrange_tool_preview(tab, preview, wide_span=4, narrow_row=6)
        self._render_images_preview()

        for row, variable in (
            (4, self._images_estimate),
            (5, self._images_quality),
            (6, self._pdf_preference_message),
        ):
            self._tool_design.form_label(
                preview,
                textvariable=variable,
                wraplength=300,
                anchor="w",
                justify="left",
                text_color=MUTED,
            ).grid(row=row, column=0, padx=12, pady=(2, 6), sticky="ew")

    def _build_pdf_to_images_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        self._tool_design.form_label(
            tab,
            text="Selecione o PDF",
            font=self._tool_design.heading,
            wraplength=640,
        ).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")
        self.pdf_images_select_button = self._tool_design.button(
            tab,
            text="Selecionar PDF",
            command=self._select_pdf_images_source,
            kind="primary",
            keyboard=True,
        )
        self.pdf_images_select_button.grid(
            row=1, column=0, padx=16, pady=(0, 6), sticky="w"
        )
        self._tool_design.form_label(
            tab,
            textvariable=self._pdf_images_source_text,
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=2, column=0, padx=16, sticky="w")
        self._tool_design.form_label(
            tab, textvariable=self._pdf_images_pages_text
        ).grid(row=3, column=0, padx=16, pady=(2, 8), sticky="w")

        scope = ctk.CTkFrame(tab, fg_color="transparent")
        scope.grid(row=4, column=0, padx=16, sticky="w")
        self.pdf_images_all_radio = self._tool_design.form_radio(
            scope,
            text="Todas as páginas",
            variable=self._pdf_images_scope,
            value="Todas as páginas",
        )
        self.pdf_images_all_radio.pack(side="left", padx=(0, 18))
        self.pdf_images_specific_radio = self._tool_design.form_radio(
            scope,
            text="Páginas específicas",
            variable=self._pdf_images_scope,
            value="Páginas específicas",
        )
        self.pdf_images_specific_radio.pack(side="left")
        self.pdf_images_range = ctk.CTkFrame(tab, fg_color="transparent")
        self.pdf_images_range.grid(row=5, column=0, padx=16, pady=(8, 12), sticky="ew")
        self.pdf_images_range.grid_columnconfigure(0, weight=1)
        self._tool_design.form_label(
            self.pdf_images_range,
            text="Páginas ou intervalos",
            font=self._tool_design.control,
        ).grid(row=0, column=0, sticky="w")
        self.pdf_images_entry = self._tool_design.form_entry(
            self.pdf_images_range,
            textvariable=self._pdf_images_selection,
        )
        self.pdf_images_entry.grid(row=1, column=0, sticky="ew")
        self._tool_design.form_label(
            self.pdf_images_range,
            text="Exemplo: 1-3,5",
            text_color=MUTED,
        ).grid(row=2, column=0, sticky="w")
        self.pdf_images_range.grid_remove()

        options = ctk.CTkFrame(tab, fg_color="transparent")
        options.grid(row=6, column=0, padx=16, pady=(0, 8), sticky="ew")
        self._tool_design.form_label(options, text="Formato").pack(
            side="left", padx=(0, 8)
        )
        self.pdf_images_format_menu = self._tool_design.form_menu(
            options,
            values=["PNG", "JPG"],
            variable=self._pdf_images_format,
            width=100,
            command=lambda _value: self._refresh_controls(),
        )
        self.pdf_images_format_menu.pack(side="left", padx=(0, 18))
        self._tool_design.form_label(options, text="Qualidade").pack(
            side="left", padx=(0, 8)
        )
        self.pdf_images_quality_menu = self._tool_design.form_menu(
            options,
            values=["Padrão", "Alta"],
            variable=self._pdf_images_quality,
            width=150,
            command=lambda _value: self._on_pdf_images_options_changed(),
        )
        self.pdf_images_quality_menu.pack(side="left", padx=(0, 18))
        destination = ctk.CTkFrame(tab, fg_color="transparent")
        destination.grid(row=7, column=0, padx=16, pady=(6, 10), sticky="ew")
        compact = PRODUCT_EDITION is ProductEdition.COMMUNITY
        destination_controls = destination
        if compact:
            destination_controls = ctk.CTkFrame(destination, fg_color="transparent")
            destination_controls.grid(row=0, column=0, sticky="w")
        else:
            destination.grid_columnconfigure(0, weight=1)
        self._tool_design.form_label(
            destination_controls,
            text="Salvar imagens em",
            font=self._tool_design.control,
        ).grid(row=0, column=0, sticky="w")
        path_label = self._tool_design.form_label(
            destination,
            textvariable=self._pdf_images_destination_text,
            text_color=MUTED,
            wraplength=220,
        )
        path_label.grid(row=1, column=0, sticky="w" if compact else "ew")
        wrap_to_frame(destination, path_label, reserved=0 if compact else 160)
        self.pdf_images_destination_button = self._tool_design.button(
            destination_controls,
            text="Escolher pasta",
            width=150,
            command=self._select_pdf_images_destination,
            kind="secondary",
            keyboard=True,
        )
        self.pdf_images_destination_button.grid(
            row=0,
            column=1,
            rowspan=1 if compact else 2,
            padx=(12 if compact else 10, 0),
            sticky="w",
        )
        self._tool_design.form_label(
            tab,
            textvariable=self._pdf_images_summary_text,
            text_color=MUTED,
        ).grid(row=8, column=0, padx=16, pady=(0, 8), sticky="w")
        pdf_images_actions = ctk.CTkFrame(tab, fg_color="transparent")
        pdf_images_actions.grid(row=9, column=0, padx=16, pady=(0, 4), sticky="ew")
        pdf_images_actions.grid_columnconfigure(0, weight=1)
        self.pdf_images_run_button = self._tool_design.button(
            pdf_images_actions,
            text="Exportar imagens",
            height=38,
            command=self._start_pdf_to_images,
            kind="primary",
            keyboard=True,
        )
        self.pdf_images_run_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.pdf_images_cancel_button = self._tool_design.button(
            pdf_images_actions,
            text="Cancelar",
            width=120,
            height=38,
            command=lambda: self._cancel_pdf_operation("pdf_images"),
            kind="danger",
            keyboard=True,
        )
        self.pdf_images_cancel_button.grid(row=0, column=1)
        self._tool_design.form_label(
            tab,
            textvariable=self._pdf_images_progress_text,
            text_color=MUTED,
        ).grid(row=10, column=0, padx=16, pady=(0, 12), sticky="w")
        self.pdf_images_page_preview = PagePreviewPane(
            tab, self._page_preview_worker, design=self._tool_design
        )
        self.pdf_images_page_preview.grid(
            row=11, column=0, padx=16, pady=8, sticky="nsew"
        )

    def _build_poster_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure((0, 1), weight=1)
        tab.grid_rowconfigure(1, weight=1)
        self._tool_design.form_label(
            tab,
            text="Imagem escolhida",
            font=self._tool_design.heading,
            wraplength=680,
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="w")

        form = ctk.CTkFrame(tab, fg_color="transparent")
        form.grid(row=1, column=0, padx=(16, 8), pady=(0, 8), sticky="nsew")
        form.grid_columnconfigure((0, 1), weight=1)
        self.poster_select_button = self._tool_design.button(
            form,
            text="Selecionar imagem",
            command=self._select_poster_source,
            kind="primary",
            keyboard=True,
        )
        self.poster_select_button.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._tool_design.form_label(
            form,
            textvariable=self._poster_source_text,
            font=ctk.CTkFont(weight="bold"),
            wraplength=330,
        ).grid(row=1, column=0, columnspan=2, pady=(5, 10), sticky="w")

        labels = (("Folhas", "Papel"), ("Orientação", "Sobreposição"))
        for row, pair in enumerate(labels, start=2):
            for column, label in enumerate(pair):
                self._tool_design.form_label(form, text=label).grid(
                    row=row * 2 - 2, column=column, pady=(4, 0), sticky="w"
                )
        self.poster_grid_menu = self._tool_design.form_menu(
            form,
            values=["2 × 2", "3 × 3", "4 × 4"],
            variable=self._poster_grid,
            command=lambda _value: self._on_poster_options_changed(),
        )
        self.poster_grid_menu.grid(row=3, column=0, padx=(0, 6), sticky="ew")
        self.poster_paper_menu = self._tool_design.form_menu(
            form,
            values=["A4", "Carta"],
            variable=self._poster_paper,
            command=lambda _value: self._on_poster_options_changed(),
        )
        self.poster_paper_menu.grid(row=3, column=1, sticky="ew")
        self.poster_orientation_menu = self._tool_design.form_menu(
            form,
            values=["Automática", "Retrato", "Paisagem"],
            variable=self._poster_orientation,
            command=lambda _value: self._on_poster_options_changed(),
        )
        self.poster_orientation_menu.grid(row=5, column=0, padx=(0, 6), sticky="ew")
        self.poster_overlap_menu = self._tool_design.form_menu(
            form,
            values=["Nenhuma", "Pequena"],
            variable=self._poster_overlap,
            command=lambda _value: self._on_poster_options_changed(),
        )
        self.poster_overlap_menu.grid(row=5, column=1, sticky="ew")
        self.poster_crop_marks_check = ctk.CTkCheckBox(
            form,
            text="Mostrar marcas de corte",
            variable=self._poster_crop_marks,
            command=self._on_poster_options_changed,
        )
        self.poster_crop_marks_check.grid(
            row=6, column=0, columnspan=2, pady=(12, 4), sticky="w"
        )
        self._tool_design.form_label(
            form,
            text=(
                "A sobreposição repete uma pequena faixa entre as folhas para "
                "facilitar a montagem."
            ),
            text_color=MUTED,
            wraplength=340,
            justify="left",
        ).grid(row=7, column=0, columnspan=2, pady=(3, 6), sticky="w")
        self._tool_design.form_label(
            form,
            textvariable=self._poster_summary,
            text_color=MUTED,
        ).grid(row=8, column=0, columnspan=2, pady=(3, 0), sticky="w")
        self._tool_design.form_label(
            form,
            textvariable=self._poster_quality,
            text_color=MUTED,
            wraplength=340,
            justify="left",
        ).grid(row=9, column=0, columnspan=2, pady=(2, 8), sticky="w")

        preview = ctk.CTkFrame(tab, corner_radius=CONTROL_RADIUS, fg_color=SOFT)
        preview.grid(row=1, column=1, padx=(8, 16), pady=(0, 8), sticky="nsew")
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(1, weight=1)
        self._tool_design.form_label(
            preview, text="Pré-visualização", font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, padx=12, pady=(10, 5), sticky="w")
        self.poster_preview_canvas = tk.Canvas(
            preview, width=290, height=245, highlightthickness=0, bd=0
        )
        self.poster_preview_canvas.grid(row=1, column=0, padx=12, sticky="nsew")
        self.poster_preview_canvas.bind(
            "<Configure>", lambda _event: self._schedule_preview_redraw()
        )
        self.poster_preview_canvas.bind(
            "<Map>", lambda _event: self._schedule_preview_redraw()
        )
        self._tool_design.form_label(
            preview,
            text="Para montar corretamente, imprima em tamanho real / 100%.",
            text_color=MUTED,
            wraplength=290,
            justify="left",
        ).grid(row=2, column=0, padx=12, pady=(7, 2), sticky="w")
        self._tool_design.form_label(
            preview,
            textvariable=self._poster_progress_text,
            text_color=MUTED,
        ).grid(row=3, column=0, padx=12, pady=(0, 9), sticky="w")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, padx=16, pady=(4, 14), sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        self.poster_run_button = self._tool_design.button(
            actions,
            text="Gerar PDF",
            height=38,
            command=self._start_poster,
            kind="primary",
            keyboard=True,
        )
        self.poster_run_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.poster_cancel_button = self._tool_design.button(
            actions,
            text="Cancelar",
            width=120,
            height=38,
            command=lambda: self._cancel_pdf_operation("poster"),
            kind="danger",
            keyboard=True,
        )
        self.poster_cancel_button.grid(row=0, column=1)
        self._arrange_tool_preview(tab, preview, wide_span=1, narrow_row=3)
        self._render_poster_preview()

        self.poster_page_preview = PagePreviewPane(
            tab, self._page_preview_worker, design=self._tool_design
        )
        self.poster_page_preview.grid(
            row=3, column=0, columnspan=2, padx=16, pady=8, sticky="nsew"
        )

    def _select_poster_source(self) -> None:
        selected = self._dialog_preferences.choose(
            filedialog.askopenfilename,
            "pdf.input",
            title="Escolha uma imagem para o pôster",
            parent=self.winfo_toplevel(),
            filetypes=(
                ("Imagens JPG e PNG", "*.jpg *.jpeg *.png"),
                ("JPEG", "*.jpg *.jpeg"),
                ("PNG", "*.png"),
            ),
        )
        if selected:
            self._prepare_poster_source(Path(selected))

    def _prepare_poster_source(self, source: Path) -> None:
        self._set_result(None)
        self._poster_source = source
        self._poster_source_text.set(source.name)
        self._poster_quality.set("Avaliando a qualidade da imagem...")
        self._status.set("Imagem preparada. Confira as opções do pôster.")
        self._refresh_controls()
        self._invalidate_poster_preview()

    def _current_poster_layout(self) -> PosterLayout:
        return PosterLayout(
            paper={"A4": PaperSize.A4, "Carta": PaperSize.LETTER}[
                self._poster_paper.get()
            ],
            orientation={
                "Automática": Orientation.AUTO,
                "Retrato": Orientation.PORTRAIT,
                "Paisagem": Orientation.LANDSCAPE,
            }[self._poster_orientation.get()],
            grid={
                "2 × 2": PosterGrid.TWO_BY_TWO,
                "3 × 3": PosterGrid.THREE_BY_THREE,
                "4 × 4": PosterGrid.FOUR_BY_FOUR,
            }[self._poster_grid.get()],
            overlap={
                "Nenhuma": OverlapPreset.NONE,
                "Pequena": OverlapPreset.SMALL,
            }[self._poster_overlap.get()],
            show_crop_marks=self._poster_crop_marks.get(),
        )

    def _on_poster_options_changed(self) -> None:
        self._update_poster_summary()
        self._refresh_controls()
        self._invalidate_poster_preview()

    def _update_poster_summary(self) -> None:
        grid = self._current_poster_layout().grid
        self._poster_summary.set(
            f"{grid.page_count} folhas · Painel: {grid.columns} × {grid.rows} folhas"
        )

    def _invalidate_poster_preview(self) -> None:
        if hasattr(self, "poster_page_preview"):
            paths = (self._poster_source,) if self._poster_source is not None else ()
            self.poster_page_preview.set_context(
                PreviewSpec(
                    "poster",
                    paths,
                    self._current_poster_layout(),
                    self._poster_crop_marks.get(),
                )
            )
        if self._closed:
            return
        self._poster_preview_generation += 1
        self._poster_preview_pending = False
        if self._poster_preview_after_id is not None:
            try:
                self.after_cancel(self._poster_preview_after_id)
            except tk.TclError:
                pass
            self._poster_preview_after_id = None
        self._clear_poster_preview()
        self._poster_preview_loading = self._poster_source is not None
        if self._poster_source is None:
            self._poster_preview_failed = False
            self._poster_quality.set("Escolha uma imagem para avaliar a qualidade.")
            self._render_poster_preview()
            return
        self._poster_preview_failed = False
        self._poster_quality.set("Avaliando a qualidade da imagem...")
        self._render_poster_preview()
        self._poster_preview_after_id = self.after(125, self._request_poster_preview)

    def _request_poster_preview(self) -> None:
        self._poster_preview_after_id = None
        source = self._poster_source
        if self._closed or source is None:
            return
        self._poster_preview_pending = True
        if self._poster_preview_worker_active:
            return
        self._poster_preview_pending = False
        generation = self._poster_preview_generation
        layout = self._current_poster_layout()
        self._poster_preview_worker_active = True

        def run() -> None:
            try:
                result = _PosterPreviewResult(
                    generation,
                    preview=_build_poster_preview(source, layout),
                )
            except Exception:
                result = _PosterPreviewResult(generation, failed=True)
            if self._closed:
                if result.preview is not None:
                    result.preview.thumbnail.close()
                return
            try:
                previous = self._poster_preview_results.get_nowait()
            except Empty:
                pass
            else:
                if previous.preview is not None:
                    previous.preview.thumbnail.close()
            self._poster_preview_results.put_nowait(result)
            if self._closed:
                # close() pode ocorrer entre a primeira checagem e a publicação.
                try:
                    queued = self._poster_preview_results.get_nowait()
                except Empty:
                    pass
                else:
                    if queued.preview is not None:
                        queued.preview.thumbnail.close()

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-poster-preview-worker",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._poster_preview_worker_active = False
            self._poster_preview_loading = False
            self._poster_preview_failed = True
            self._poster_quality.set("Não foi possível avaliar esta imagem.")
            self._render_poster_preview()
            return
        self.after(60, self._poll_poster_preview)

    def _poll_poster_preview(self) -> None:
        if self._closed:
            return
        try:
            result = self._poster_preview_results.get_nowait()
        except Empty:
            self.after(60, self._poll_poster_preview)
            return
        self._poster_preview_worker_active = False
        if result.generation == self._poster_preview_generation:
            self._clear_poster_preview()
            self._poster_preview_loading = False
            self._poster_preview = result.preview
            self._poster_preview_failed = result.failed
            if result.preview is None:
                self._poster_quality.set("Não foi possível avaliar esta imagem.")
            else:
                self._poster_quality.set(
                    _poster_quality_message(result.preview.plan.effective_ppi.quality)
                )
            self._render_poster_preview()
            self._refresh_controls()
        elif result.preview is not None:
            result.preview.thumbnail.close()
        if self._poster_preview_pending:
            self._request_poster_preview()

    def _clear_poster_preview(self) -> None:
        previous = self._poster_preview
        self._poster_preview = None
        self._poster_preview_tk_image = None
        self._poster_display_key = None
        if previous is not None:
            previous.thumbnail.close()

    def _render_poster_preview(self) -> None:
        if self._closed or not hasattr(self, "poster_preview_canvas"):
            return
        canvas = self.poster_preview_canvas
        width = max(canvas.winfo_width(), int(canvas.cget("width")))
        height = max(canvas.winfo_height(), int(canvas.cget("height")))
        dark = ctk.get_appearance_mode() == "Dark"
        key = (
            width,
            height,
            dark,
            self._poster_preview_generation,
            self._poster_preview_loading,
            self._poster_preview_failed,
            id(self._poster_preview),
            self._poster_source,
        )
        if vars(canvas).get("_edu_preview_key") == key:
            return
        with _PreviewCanvas(canvas, key) as canvas:
            background = "#202124" if dark else "#E5E7EB"
            foreground = "#D1D5DB" if dark else "#374151"
            canvas.configure(bg=background)
            if self._poster_source is None:
                canvas.create_text(
                    width / 2,
                    height / 2,
                    text="Escolha uma imagem para criar um pôster.",
                    fill=foreground,
                    width=max(120, width - 36),
                    justify="center",
                )
                return
            if self._poster_preview_loading:
                canvas.create_text(
                    width / 2,
                    height / 2,
                    text="Atualizando pré-visualização...",
                    fill=foreground,
                )
                return
            preview = self._poster_preview
            if preview is None or self._poster_preview_failed:
                canvas.create_text(
                    width / 2,
                    height / 2,
                    text="Pré-visualização indisponível para esta imagem.",
                    fill=foreground,
                    width=max(120, width - 36),
                    justify="center",
                )
                return
            padding = 14.0
            panel = preview.plan.panel_size
            scale = min(
                (width - 2 * padding) / panel.width,
                (height - 2 * padding) / panel.height,
            )
            panel_width = panel.width * scale
            panel_height = panel.height * scale
            origin_x = (width - panel_width) / 2
            origin_y = (height - panel_height) / 2
            canvas.create_rectangle(
                origin_x,
                origin_y,
                origin_x + panel_width,
                origin_y + panel_height,
                fill="#FFFFFF",
                outline="#64748B",
                width=2,
            )
            placement = preview.plan.image_placement
            image_size = (
                max(1, round(placement.width * scale)),
                max(1, round(placement.height * scale)),
            )
            display_key = (
                self._poster_preview_generation,
                id(preview.thumbnail),
                image_size,
            )
            if self._poster_display_key != display_key:
                display = preview.thumbnail.resize(image_size, Image.Resampling.LANCZOS)
                try:
                    self._poster_preview_tk_image = ImageTk.PhotoImage(display)
                    self._poster_display_key = display_key
                finally:
                    display.close()
            canvas.create_image(
                origin_x + (placement.x + placement.width / 2) * scale,
                origin_y + (placement.y + placement.height / 2) * scale,
                image=self._poster_preview_tk_image,
            )
            grid = self._current_poster_layout().grid
            overlap = self._current_poster_layout().overlap.points * scale
            page_labels: list[tuple[float, float, int]] = []
            for tile in preview.plan.tiles:
                box = tile.panel_viewport
                left = origin_x + box.x * scale
                top = origin_y + box.y * scale
                right = left + box.width * scale
                bottom = top + box.height * scale
                if overlap > 0:
                    canvas.create_rectangle(
                        left,
                        top,
                        right,
                        bottom,
                        outline="#F59E0B",
                        dash=(2, 2),
                    )
                center_x = (left + right) / 2
                center_y = (top + bottom) / 2
                page_labels.append((center_x, center_y, tile.page_index + 1))
            for column in range(1, grid.columns):
                x = origin_x + column * panel_width / grid.columns
                canvas.create_line(
                    x, origin_y, x, origin_y + panel_height, fill="#334155"
                )
            for row in range(1, grid.rows):
                y = origin_y + row * panel_height / grid.rows
                canvas.create_line(
                    origin_x, y, origin_x + panel_width, y, fill="#334155"
                )
            for center_x, center_y, page_number in page_labels:
                canvas.create_oval(
                    center_x - 10,
                    center_y - 10,
                    center_x + 10,
                    center_y + 10,
                    fill="#FFFFFF",
                    outline="#334155",
                )
                canvas.create_text(
                    center_x,
                    center_y,
                    text=str(page_number),
                    fill="#111827",
                    font=("TkDefaultFont", 10, "bold"),
                )
            if self._poster_crop_marks.get():
                canvas.create_text(
                    origin_x + 5,
                    origin_y + 5,
                    text="⌜",
                    anchor="nw",
                    fill="#111827",
                    font=("TkDefaultFont", 12, "bold"),
                )

    def _start_poster(self) -> None:
        source = self._poster_source
        if source is None:
            return
        output = self._choose_output(
            f"{self._poster_source.stem}-poster.pdf"
            if self._poster_source
            else "poster.pdf"
        )
        if output is None:
            return
        output_path, overwrite = output
        layout = self._current_poster_layout()
        request = PosterRequest(
            input_path=source,
            output_path=output_path,
            paper=layout.paper,
            orientation=layout.orientation,
            grid=layout.grid,
            overlap=layout.overlap,
            show_crop_marks=layout.show_crop_marks,
            overwrite=overwrite,
        )
        self._start_poster_worker(request)

    def _start_poster_worker(self, request: PosterRequest) -> None:
        def operation(
            cancel_event: threading.Event,
            progress: Callable[[PdfOperationProgress], None],
        ) -> PosterResult:
            configured = PosterRequest(
                input_path=request.input_path,
                output_path=request.output_path,
                paper=request.paper,
                orientation=request.orientation,
                grid=request.grid,
                overlap=request.overlap,
                show_crop_marks=request.show_crop_marks,
                overwrite=request.overwrite,
                cancel_event=cancel_event,
                progress=lambda item: progress(
                    PdfOperationProgress(item.completed_pages, item.total_pages)
                ),
            )
            return self._poster_service.create(configured)

        self._start_pdf_operation_worker(
            "poster",
            operation,
            self._complete_poster,
            "Gerando o pôster localmente...",
        )

    def _complete_poster(self, result: PosterResult) -> None:
        self._set_result(result.output_path)
        message = "Pôster gerado com sucesso. Imprima em tamanho real / 100%."
        self._status.set(message)
        if self._actions.notify is not None:
            self._actions.notify(
                "success", "Pôster PDF criado. Imprima em tamanho real."
            )

    def _select_merge_files(self) -> None:
        selected = self._dialog_preferences.choose(
            filedialog.askopenfilenames,
            "pdf.input",
            title="Adicione PDFs à lista",
            parent=self.winfo_toplevel(),
            filetypes=(("Arquivos PDF", "*.pdf"),),
        )
        if selected:
            self.merge_files.add_paths([Path(value) for value in selected])
            self._status.set(
                f"{_format_count(len(self.merge_files.paths), 'PDF', 'PDFs')} na lista para juntar."
            )

    def _on_merge_list_changed(self) -> None:
        if hasattr(self, "merge_page_preview"):
            self.merge_page_preview.set_context(
                PreviewSpec("merge", self.merge_files.paths),
                count=len(self.merge_files.paths),
            )
        self._set_result(None, tool=self.tool_names[0])
        self._refresh_controls()
        self._merge_metadata_generation += 1
        current_keys = {
            _OrderedPathList._comparison_key(path) for path in self.merge_files.paths
        }
        self._merge_metadata = {
            key: detail
            for key, detail in self._merge_metadata.items()
            if key in current_keys
        }
        for key in current_keys:
            self._merge_metadata.setdefault(
                key,
                "Prévia carregada ao navegar."
                if hasattr(self, "merge_page_preview")
                else "Lendo páginas e tamanho...",
            )
        self.merge_files.refresh()
        self._merge_metadata_pending = bool(self.merge_files.paths)
        if self._merge_metadata_after_id is not None:
            try:
                self.after_cancel(self._merge_metadata_after_id)
            except tk.TclError:
                pass
        if hasattr(self, "merge_page_preview"):
            self._merge_metadata_after_id = None
            self._merge_metadata_pending = False
            return
        self._merge_metadata_after_id = self.after(
            100,
            self._request_merge_metadata,
        )

    def _merge_detail_for_path(self, path: Path) -> str | None:
        return self._merge_metadata.get(_OrderedPathList._comparison_key(path))

    def _merge_preview_ready(self, bundle):
        paths = self.merge_files.paths
        for index, raster in bundle.thumbs:
            if index < len(paths):
                self._merge_metadata[_OrderedPathList._comparison_key(paths[index])] = (
                    "Prévia indisponível"
                    if raster.error
                    else f"{_format_count(raster.count, 'página', 'páginas')} · {format_size(raster.source_bytes)}"
                )
        self.merge_files.refresh()

    def _request_merge_metadata(self) -> None:
        self._merge_metadata_after_id = None
        if self._closed or not self._merge_metadata_pending:
            return
        if self._merge_metadata_worker_active:
            return
        generation = self._merge_metadata_generation
        paths = self.merge_files.paths
        self._merge_metadata_pending = False
        self._merge_metadata_worker_active = True

        def run() -> None:
            details: list[tuple[Path, str]] = []
            for path in paths:
                try:
                    count = self._service.page_count(path)
                    size = format_size(path.stat().st_size)
                    detail = f"{_format_count(count, 'página', 'páginas')} · {size}"
                except Exception:
                    detail = "PDF inválido, protegido ou indisponível"
                details.append((path, detail))
            self._merge_metadata_results.put(
                _MergeMetadataResult(generation, tuple(details))
            )

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-pdf-metadata-worker",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._merge_metadata_worker_active = False
            for key, detail in self._merge_metadata.items():
                if detail == "Lendo páginas e tamanho...":
                    self._merge_metadata[key] = "Metadados indisponíveis"
            self.merge_files.refresh()
            return
        self.after(60, self._poll_merge_metadata)

    def _poll_merge_metadata(self) -> None:
        if self._closed:
            return
        try:
            result = self._merge_metadata_results.get_nowait()
        except Empty:
            self.after(60, self._poll_merge_metadata)
            return
        self._merge_metadata_worker_active = False
        if result.generation == self._merge_metadata_generation:
            current_keys = {
                _OrderedPathList._comparison_key(path)
                for path in self.merge_files.paths
            }
            self._merge_metadata = {
                _OrderedPathList._comparison_key(path): detail
                for path, detail in result.details
                if _OrderedPathList._comparison_key(path) in current_keys
            }
            self.merge_files.refresh()
        if self._merge_metadata_pending:
            self._request_merge_metadata()

    def _select_extract_source(self) -> None:
        selected = self._dialog_preferences.choose(
            filedialog.askopenfilename,
            "pdf.input",
            title="Selecione o PDF",
            parent=self.winfo_toplevel(),
            filetypes=(("Arquivos PDF", "*.pdf"),),
        )
        if selected:
            self._prepare_extract_source(Path(selected))

    def _prepare_extract_source(self, source: Path) -> None:
        if hasattr(self, "extract_page_preview"):
            self.extract_page_preview.set_context(PreviewSpec("pdf", (source,)))
        self._set_result(None)
        self._extract_source = source
        self._extract_page_count = None
        self._extract_selection.set("")
        self._extract_source_text.set(source.name)
        self._extract_pages_text.set("Lendo a quantidade de páginas...")
        self._update_extract_summary()
        self._refresh_controls()
        self._start_worker(
            lambda: self._service.page_count(source),
            lambda count: self._complete_pdf_inspection(source, count),
            "Lendo o PDF selecionado...",
        )

    def _select_images(self) -> None:
        selected = self._dialog_preferences.choose(
            filedialog.askopenfilenames,
            "pdf.input",
            title="Adicione imagens JPG ou PNG à lista",
            parent=self.winfo_toplevel(),
            filetypes=(
                ("Imagens JPG e PNG", "*.jpg *.jpeg *.png"),
                ("JPEG", "*.jpg *.jpeg"),
                ("PNG", "*.png"),
            ),
        )
        if selected:
            self._add_image_paths([Path(value) for value in selected])

    def _add_image_paths(self, paths: list[Path]) -> int:
        added_count = self.image_files.add_paths(paths)
        if added_count:
            self._status.set(
                f"{_format_count(len(self.image_files.paths), 'imagem', 'imagens')} na lista."
            )
        return added_count

    def _image_angles(self):
        return tuple(
            self._image_rotations.get(self.image_files._comparison_key(path), 0)
            for path in self.image_files.paths
        )

    def _image_detail(self, path):
        angle = self._image_rotations.get(self.image_files._comparison_key(path), 0)
        return f"Rotação: {angle}°" if angle else None

    def _rotate_image(self, delta):
        index = self.image_files.selected_index
        if (
            self._busy
            or self._shutdown_requested
            or not 0 <= index < len(self.image_files.paths)
        ):
            return
        path = self.image_files.paths[index]
        key = self.image_files._comparison_key(path)
        self._image_rotations[key] = (self._image_rotations.get(key, 0) + delta) % 360
        self._set_result(None)
        self.image_files.refresh()
        self._invalidate_images_preview()
        self.images_page_preview.goto(
            index // self._current_images_layout().images_per_page
        )

    def _on_image_selected(self):
        self._refresh_controls()
        self._show_image_quality()

    def _request_image_analysis(self, spec):
        if spec == self._analysis_spec:
            return
        self._analysis_spec = spec
        self._analysis_generation += 1
        self._image_analysis = None
        self._analysis_worker.invalidate(0)
        if not spec.paths:
            self._images_estimate.set("Adicione imagens para estimar o tamanho.")
            self._images_quality.set("")
            return
        self._images_estimate.set("Estimando tamanho…")
        self._images_quality.set("Avaliando a resolução para impressão…")
        try:
            self._analysis_worker.submit(0, self._analysis_generation, spec, 0, ())
        except (OSError, RuntimeError):
            self._images_estimate.set("Estimativa indisponível nesta sessão.")
            self._images_quality.set("Qualidade estimada indisponível.")
            return
        if self._analysis_after_id is None:
            self._analysis_after_id = self.after(60, self._poll_image_analysis)

    def _poll_image_analysis(self):
        self._analysis_after_id = None
        if self._closed or not self.image_files.paths:
            return
        value = self._analysis_worker.take(0)
        if value is None:
            self._analysis_after_id = self.after(60, self._poll_image_analysis)
            return
        generation, analysis = value
        if generation != self._analysis_generation:
            self._analysis_after_id = self.after(60, self._poll_image_analysis)
            return
        self._image_analysis = (
            analysis
            if isinstance(analysis, ImagePreparation)
            else ImagePreparation(message="Avaliação indisponível.")
        )
        if self._image_analysis.estimated_bytes:
            low, high = self._image_analysis.estimated_bytes
            self._images_estimate.set(
                f"Tamanho estimado: {format_size(low)} a {format_size(high)} (aproximado)."
            )
        else:
            self._images_estimate.set(
                self._image_analysis.message or "Estimativa indisponível."
            )
        self._show_image_quality()

    def _show_image_quality(self):
        analysis = self._image_analysis
        if analysis is None:
            return
        qualities = analysis.qualities
        if not qualities:
            self._images_quality.set("Qualidade estimada indisponível.")
            return
        count = sum(item.dpi < PRINT_WARNING_PPI for item in qualities)
        text = (
            f"{_format_count(count, 'imagem pode', 'imagens podem')} perder nitidez ao imprimir."
            if count
            else "Sem sinal de baixa resolução; a nitidez final depende da impressão."
        )
        index = self.image_files.selected_index
        if 0 <= index < len(qualities):
            item = qualities[index]
            text += (
                f"\nSelecionada: {item.path.name} · {round(item.dpi)} DPI estimados."
            )
        self._images_quality.set(text)

    def _pdf_preference_vars(self):
        return {
            key: getattr(self, "_" + key)
            for key in (*PDF_PREFERENCE_CHOICES, "poster_crop_marks")
        }

    def _trace_form_write(self, variable: tk.Variable, callback) -> None:
        self._form_write_traces.append(
            (variable, variable.trace_add("write", callback))
        )

    def _load_pdf_preferences(self, values):
        restored = normalize_pdf_preferences(values)
        variables = self._pdf_preference_vars()
        for key, value in restored.items():
            variables[key].set(value)
        self._last_pdf_preferences = {
            key: variable.get() for key, variable in variables.items()
        }
        for variable in variables.values():
            self._trace_form_write(variable, self._save_pdf_preferences)
        self._on_images_layout_changed()
        self._on_poster_options_changed()
        self._on_pdf_images_options_changed()

    def _save_pdf_preferences(self, *_args):
        values = normalize_pdf_preferences(
            {key: var.get() for key, var in self._pdf_preference_vars().items()}
        )
        if values == self._last_pdf_preferences:
            return
        self._last_pdf_preferences = values
        try:
            saved = (
                self._persist_pdf_callback(dict(values))
                if self._persist_pdf_callback
                else True
            )
        except OSError:
            saved = False
        self._pdf_preference_message.set(
            "Configurações mantidas só nesta sessão; não foi possível salvá-las."
            if saved is False
            else ""
        )

    def _on_image_list_changed(self) -> None:
        keys = {
            self.image_files._comparison_key(path) for path in self.image_files.paths
        }
        self._image_rotations = {
            key: value for key, value in self._image_rotations.items() if key in keys
        }
        self._set_result(None, tool=self.tool_names[2])
        self._refresh_controls()
        self._update_images_summary()
        self._invalidate_images_preview()

    def _on_images_layout_changed(self) -> None:
        self._images_margin_help.set(
            "Algumas impressoras podem cortar as bordas."
            if self._images_margin.get() == "Sem margem"
            else ""
        )
        self._refresh_controls()
        self._update_images_summary()
        self._invalidate_images_preview()

    def _current_images_layout(self) -> ImagePageLayout:
        return ImagePageLayout(
            paper={"A4": PaperSize.A4, "Carta": PaperSize.LETTER}[
                self._images_paper.get()
            ],
            orientation={
                "Automática": Orientation.AUTO,
                "Retrato": Orientation.PORTRAIT,
                "Paisagem": Orientation.LANDSCAPE,
            }[self._images_orientation.get()],
            margin={
                "Sem margem": MarginPreset.NONE,
                "Pequena": MarginPreset.SMALL,
                "Normal": MarginPreset.NORMAL,
            }[self._images_margin.get()],
            images_per_page={
                "1 por página": 1,
                "2 por página": 2,
                "4 por página": 4,
            }[self._images_per_page.get()],
        )

    def _update_images_summary(self) -> None:
        image_count = len(self.image_files.paths) if hasattr(self, "image_files") else 0
        if not image_count:
            self._images_summary.set("Nenhuma página será gerada.")
            return
        total_pages = ceil(image_count / self._current_images_layout().images_per_page)
        self._images_summary.set(
            f"{_format_count(total_pages, 'página será gerada', 'páginas serão geradas')}."
        )

    def _invalidate_images_preview(self) -> None:
        if self._closed:
            return
        if hasattr(self, "images_page_preview"):
            self._images_preview_generation += 1
            self._render_images_preview()
            return
        self._images_preview_generation += 1
        self._images_preview_pending = False
        if self._images_preview_after_id is not None:
            try:
                self.after_cancel(self._images_preview_after_id)
            except tk.TclError:
                pass
            self._images_preview_after_id = None
        self._images_preview = None
        self._images_preview_loading = bool(self.image_files.paths)
        if not self.image_files.paths:
            self._images_preview = None
            self._images_preview_failed = False
            self._render_images_preview()
            return
        self._images_preview_failed = False
        self._render_images_preview()
        self._images_preview_after_id = self.after(
            125,
            self._request_images_preview,
        )

    def _request_images_preview(self) -> None:
        self._images_preview_after_id = None
        if self._closed or not self.image_files.paths:
            return
        self._images_preview_pending = True
        if self._images_preview_worker_active:
            return
        self._images_preview_pending = False
        generation = self._images_preview_generation
        paths = self.image_files.paths
        layout = self._current_images_layout()
        self._images_preview_worker_active = True

        def run() -> None:
            try:
                result = _ImagesPdfPreviewResult(
                    generation,
                    preview=_build_images_pdf_preview(paths, layout),
                )
            except Exception:
                result = _ImagesPdfPreviewResult(generation, failed=True)
            self._images_preview_results.put(result)

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-images-preview-worker",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._images_preview_worker_active = False
            self._images_preview_loading = False
            self._images_preview_failed = True
            self._render_images_preview()
            return
        self.after(60, self._poll_images_preview)

    def _poll_images_preview(self) -> None:
        if self._closed:
            return
        try:
            result = self._images_preview_results.get_nowait()
        except Empty:
            self.after(60, self._poll_images_preview)
            return
        self._images_preview_worker_active = False
        if result.generation == self._images_preview_generation:
            self._images_preview_loading = False
            self._images_preview = result.preview
            self._images_preview_failed = result.failed
            self._render_images_preview()
        if self._images_preview_pending:
            self._request_images_preview()

    def _render_images_preview(self) -> None:
        if hasattr(self, "images_page_preview"):
            if not self._closed:
                spec = PreviewSpec(
                    "images",
                    self.image_files.paths,
                    self._current_images_layout(),
                    rotations=self._image_angles(),
                )
                self.images_page_preview.set_context(
                    spec,
                    count=(len(spec.paths) + spec.layout.images_per_page - 1)
                    // spec.layout.images_per_page,
                    preserve_view=True,
                )
                self._request_image_analysis(spec)
            return
        if self._closed or not hasattr(self, "images_preview_canvas"):
            return
        canvas = self.images_preview_canvas
        width = max(canvas.winfo_width(), int(canvas.cget("width")))
        height = max(canvas.winfo_height(), int(canvas.cget("height")))
        dark = ctk.get_appearance_mode() == "Dark"
        key = (
            width,
            height,
            dark,
            self._images_preview_generation,
            self._images_preview_loading,
            self._images_preview_failed,
            id(self._images_preview),
            self.image_files.paths,
        )
        if vars(canvas).get("_edu_preview_key") == key:
            return
        with _PreviewCanvas(canvas, key) as canvas:
            background = "#202124" if dark else "#E5E7EB"
            canvas.configure(bg=background)
            foreground = "#D1D5DB" if dark else "#374151"
            if not self.image_files.paths:
                canvas.create_text(
                    width / 2,
                    height / 2,
                    text="Adicione imagens para visualizar o resultado.",
                    fill=foreground,
                    width=max(120, width - 36),
                    justify="center",
                )
                return
            if self._images_preview_loading:
                canvas.create_text(
                    width / 2,
                    height / 2,
                    text="Atualizando pré-visualização...",
                    fill=foreground,
                )
                return
            preview = self._images_preview
            if preview is None or self._images_preview_failed:
                canvas.create_text(
                    width / 2,
                    height / 2,
                    text=(
                        "Não foi possível visualizar esta configuração.\n"
                        "Você ainda pode tentar criar o PDF."
                    ),
                    fill=foreground,
                    width=max(120, width - 36),
                    justify="center",
                )
                return
            padding = 12.0
            scale = min(
                (width - 2 * padding) / preview.page_size.width,
                (height - 2 * padding) / preview.page_size.height,
            )
            page_width = preview.page_size.width * scale
            page_height = preview.page_size.height * scale
            origin_x = (width - page_width) / 2
            origin_y = (height - page_height) / 2
            canvas.create_rectangle(
                origin_x,
                origin_y,
                origin_x + page_width,
                origin_y + page_height,
                fill="#FFFFFF",
                outline="#9CA3AF",
                width=1,
            )

            def scaled(
                rect: Rect | ContainPlacement,
            ) -> tuple[float, float, float, float]:
                return (
                    origin_x + rect.x * scale,
                    origin_y + rect.y * scale,
                    origin_x + (rect.x + rect.width) * scale,
                    origin_y + (rect.y + rect.height) * scale,
                )

            canvas.create_rectangle(
                *scaled(preview.content_rect),
                outline="#CBD5E1",
                dash=(3, 2),
            )
            for slot in preview.slots:
                canvas.create_rectangle(*scaled(slot), outline="#E5E7EB")
            for index, (placement, failed) in enumerate(
                zip(preview.placements, preview.failed_items, strict=True),
                start=1,
            ):
                box = scaled(placement)
                canvas.create_rectangle(
                    *box,
                    fill="#94A3B8" if failed else "#60A5FA",
                    outline="#475569" if failed else "#2563EB",
                )
                canvas.create_text(
                    (box[0] + box[2]) / 2,
                    (box[1] + box[3]) / 2,
                    text="?" if failed else str(index),
                    fill="#FFFFFF",
                    font=("TkDefaultFont", 9, "bold"),
                )

    def _select_pdf_images_source(self) -> None:
        selected = self._dialog_preferences.choose(
            filedialog.askopenfilename,
            "pdf.input",
            title="Selecione o PDF para converter",
            parent=self.winfo_toplevel(),
            filetypes=(("Arquivos PDF", "*.pdf"),),
        )
        if selected:
            self._prepare_pdf_images_source(Path(selected))

    def _prepare_pdf_images_source(self, source: Path) -> None:
        if hasattr(self, "pdf_images_page_preview"):
            self.pdf_images_page_preview.set_context(PreviewSpec("pdf", (source,)))
        self._set_result(None)
        self._pdf_images_source = source
        self._pdf_images_page_count = None
        self._pdf_images_selection.set("")
        self._pdf_images_source_text.set(source.name)
        self._pdf_images_pages_text.set("Lendo a quantidade de páginas...")
        self._update_pdf_images_summary()
        self._refresh_controls()
        self._start_worker(
            lambda: self._service.page_count(source),
            lambda count: self._complete_pdf_images_inspection(source, count),
            "Lendo o PDF selecionado...",
        )

    def _can_accept_handoff(self) -> bool:
        if self._shutdown_requested:
            return False
        if self._busy:
            self._actions.show_warning("Aguarde a operação PDF atual terminar.")
            return False
        return True

    def _select_pdf_images_destination(self) -> None:
        selected = self._dialog_preferences.choose(
            filedialog.askdirectory,
            "pdf.output",
            directory=True,
            title="Selecione a pasta para as imagens",
            parent=self.winfo_toplevel(),
            mustexist=True,
        )
        if not selected:
            return
        self._pdf_images_destination = Path(selected)
        self._pdf_images_destination_text.set(self._pdf_images_destination.name)
        self._status.set("Pasta de destino selecionada.")
        self._refresh_controls()

    def _start_merge(self) -> None:
        paths = self.merge_files.paths
        output = self._choose_output(
            f"{paths[0].stem}-unidos.pdf" if paths else "pdfs-unidos.pdf"
        )
        if output is None:
            return
        output_path, overwrite = output
        inputs = self.merge_files.paths
        self._start_pdf_operation_worker(
            "merge",
            lambda cancel_event, progress: self._service.merge_pdfs(
                inputs,
                output_path,
                overwrite=overwrite,
                cancel_event=cancel_event,
                progress=progress,
            ),
            lambda result: self._complete_operation("PDFs unidos", result),
            "Juntando PDFs localmente...",
        )

    def _start_extract(self) -> None:
        if self._extract_source is None:
            return
        output = self._choose_output(f"{self._extract_source.stem}-paginas.pdf")
        if output is None:
            return
        output_path, overwrite = output
        selection = self._extract_selection.get()
        source = self._extract_source
        self._start_pdf_operation_worker(
            "extract",
            lambda cancel_event, progress: self._service.extract_pages(
                source,
                selection,
                output_path,
                overwrite=overwrite,
                cancel_event=cancel_event,
                progress=progress,
            ),
            lambda result: self._complete_operation("Páginas extraídas", result),
            "Extraindo páginas localmente...",
        )

    def _start_images(self) -> None:
        paths = self.image_files.paths
        output = self._choose_output(
            f"{paths[0].stem}-imagens.pdf" if paths else "imagens.pdf"
        )
        if output is None:
            return
        output_path, overwrite = output
        inputs = self.image_files.paths
        layout = self._current_images_layout()
        self._start_images_worker(
            inputs,
            output_path,
            overwrite=overwrite,
            layout=layout,
            rotations=self._image_angles(),
        )

    def _start_images_worker(
        self,
        inputs: tuple[Path, ...],
        output_path: Path,
        *,
        overwrite: bool,
        layout: ImagePageLayout,
        rotations: tuple[int, ...] | None = None,
    ) -> None:
        if self._shutdown_requested:
            return
        if self._busy:
            self._actions.show_warning("Aguarde a operação PDF atual terminar.")
            return
        self._images_generation += 1
        generation = self._images_generation
        cancel_event = threading.Event()
        self._images_cancel_event = cancel_event
        self._images_state = _ImagesPdfUiState.PROCESSING
        self._begin_pdf_work("Convertendo imagens localmente...")
        self._images_progress_text.set("Preparando páginas...")
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
        self._refresh_controls()

        def report_progress(progress: ImagesToPdfProgress) -> None:
            self._images_progress_results.put((generation, progress))

        def run() -> None:
            try:
                value = self._service.images_to_pdf(
                    inputs,
                    output_path,
                    overwrite=overwrite,
                    layout=layout,
                    cancel_event=cancel_event,
                    progress=report_progress,
                    **(
                        {"rotations": rotations} if rotations and any(rotations) else {}
                    ),
                )
                self._results.put(
                    _PdfWorkerResult(
                        lambda result: self._complete_operation(
                            "PDF de imagens criado", result
                        ),
                        value=value,
                        operation="images",
                        generation=generation,
                    )
                )
            except PdfOperationCancelled:
                self._results.put(
                    _PdfWorkerResult(
                        lambda _value: None,
                        operation="images",
                        generation=generation,
                        cancelled=True,
                    )
                )
            except PdfToolsError as error:
                self._results.put(
                    _PdfWorkerResult(
                        lambda _value: None,
                        error_message=str(error),
                        operation="images",
                        generation=generation,
                    )
                )
            except Exception:
                self._results.put(
                    _PdfWorkerResult(
                        lambda _value: None,
                        error_message="Não foi possível concluir a operação PDF.",
                        operation="images",
                        generation=generation,
                    )
                )

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-pdf-worker",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._busy = False
            self._images_cancel_event = None
            self._images_state = _ImagesPdfUiState.ERROR
            self._reset_pdf_progress_bar()
            self._images_progress_text.set("")
            self._refresh_controls()
            message = "Não foi possível iniciar a operação. Tente novamente."
            self._status.set(message)
            self._working_tool = None
            self._actions.show_error(message)
            return
        self.after(80, self._poll_worker)

    def _cancel_images(self) -> None:
        if (
            self._images_state is not _ImagesPdfUiState.PROCESSING
            or self._images_cancel_event is None
        ):
            return
        self._images_state = _ImagesPdfUiState.CANCELLING
        self._images_cancel_event.set()
        self._status.set("Cancelando...")
        self._images_progress_text.set("Cancelando...")
        self._refresh_controls()

    def _start_pdf_to_images(self) -> None:
        if self._shutdown_requested:
            return
        source = self._pdf_images_source
        destination = self._pdf_images_destination
        total_pages = self._pdf_images_page_count
        if source is None or destination is None or total_pages is None:
            return
        selection = self._pdf_images_selected_specification()
        image_format = self._pdf_images_format.get()
        quality = (
            PdfImageQuality.HIGH
            if self._pdf_images_quality.get() == "Alta"
            else PdfImageQuality.STANDARD
        )
        try:
            output_paths = self._service.pdf_to_image_output_paths(
                source,
                selection,
                image_format,
                destination,
                total_pages=total_pages,
            )
        except PdfToolsError as error:
            self._status.set("Operação PDF não iniciada.")
            self._actions.show_error(str(error))
            return
        if len(output_paths) > 500:
            self._actions.show_error("A seleção excede o limite seguro de 500 páginas.")
            return
        if len(output_paths) > 100 and not self._actions.confirm_overwrite(
            f"A exportação criará {len(output_paths)} imagens. Deseja continuar?"
        ):
            return
        conflicts = sum(path.exists() for path in output_paths)
        if conflicts and not self._actions.confirm_overwrite(
            (
                f"{_format_count(conflicts, 'imagem', 'imagens')} "
                f"já {'existe' if conflicts == 1 else 'existem'}. "
                f"Deseja {'substituí-la' if conflicts == 1 else 'substituí-las'}?"
            )
        ):
            return
        self._start_pdf_operation_worker(
            "pdf_images",
            lambda cancel_event, progress: self._service.pdf_to_images(
                source,
                selection,
                image_format,
                destination,
                overwrite=bool(conflicts),
                quality=quality,
                cancel_event=cancel_event,
                progress=progress,
            ),
            self._complete_pdf_images_export,
            "Renderizando páginas localmente...",
        )

    def _choose_output(self, suggested_name: str) -> tuple[Path, bool] | None:
        if self._shutdown_requested:
            return None
        selected = self._dialog_preferences.choose(
            filedialog.asksaveasfilename,
            "pdf.output",
            title="Salvar novo PDF",
            parent=self.winfo_toplevel(),
            defaultextension=".pdf",
            initialfile=suggested_name,
            filetypes=(("Arquivo PDF", "*.pdf"),),
            confirmoverwrite=False,
        )
        if not selected:
            return None
        output = Path(selected)
        overwrite = output.exists()
        if overwrite and not self._actions.confirm_overwrite(
            f'O arquivo "{output.name}" já existe. Deseja substituí-lo?'
        ):
            return None
        return output, overwrite

    def _complete_pdf_inspection(self, source: Path, count: int) -> None:
        self._extract_source = source
        self._extract_page_count = count
        self._extract_source_text.set(source.name)
        self._extract_pages_text.set(f"Quantidade de páginas: {count}")
        self._on_extract_selection_changed()
        self._status.set("PDF lido. Informe as páginas que deseja extrair.")
        self._refresh_controls()

    def _complete_pdf_images_inspection(self, source: Path, count: int) -> None:
        self._pdf_images_source = source
        self._pdf_images_page_count = count
        self._pdf_images_source_text.set(source.name)
        self._pdf_images_pages_text.set(f"Quantidade de páginas: {count}")
        self._on_pdf_images_options_changed()
        self._status.set("PDF lido. Escolha as páginas, o formato e a pasta.")
        self._refresh_controls()

    def _complete_operation(self, label: str, result: PdfOperationResult) -> None:
        self._set_result(result.output_path)
        message = (
            f'{label}: "{result.output_path.name}" '
            f"({_format_count(result.page_count, 'página', 'páginas')})."
        )
        self._status.set(message)
        if self._actions.notify is not None:
            self._actions.notify("success", f"{label} com sucesso.")

    def _complete_pdf_images_export(self, result: PdfImageExportResult) -> None:
        self._set_result(
            result.output_paths[0] if result.output_paths else None,
            outputs=result.output_paths,
        )
        message = (
            f"{_format_count(result.page_count, 'imagem', 'imagens')} "
            f'{"exportada" if result.page_count == 1 else "exportadas"} para "'
            f'{result.output_directory.name}".'
        )
        self._status.set(message)
        if self._actions.notify is not None and result.output_paths:
            self._actions.notify("success", "Páginas exportadas com sucesso.")

    def _feedback_for(self, tool: str | None = None) -> _PdfToolFeedback:
        return self._tool_feedback[tool or self._working_tool or self.tab_view.get()]

    @property
    def _status(self) -> tk.StringVar:
        return self._feedback_for().status

    def _set_result(self, path: Path | None, *, outputs=(), tool=None) -> None:
        owner = tool or self._working_tool or self.tab_view.get()
        feedback = self._feedback_for(owner)
        feedback.paths = tuple(outputs) if outputs else (path,) if path else ()
        feedback.generation += 1
        feedback.info = None
        feedback.pending = False
        feedback.opening_folder = None
        feedback.result_text.set(
            f"Resultado: {path.name} · Pasta: {path.parent} · Conferindo tamanho…"
            if path
            else ""
        )
        if path:
            try:
                self._request_pdf_result(owner, ResultRequest(feedback.paths))
            except (OSError, RuntimeError):
                feedback.paths = ()
                feedback.result_text.set(
                    "Não foi possível conferir o resultado nesta sessão."
                )
        else:
            self._result_worker.invalidate(owner)
            feedback.status.set(_PDF_LOCAL_STATUS)
        self._refresh_result_actions()

    def _request_pdf_result(self, owner: str, request: ResultRequest) -> None:
        feedback = self._feedback_for(owner)
        self._result_worker.submit(owner, feedback.generation, request, 0, ())
        feedback.pending = True
        self._schedule_result_poll()

    def _refresh_result_actions(self) -> None:
        tool = self._visible_tool
        feedback = self._feedback_for(tool) if tool is not None else None
        show_panel = feedback is not None and tool != self.tool_names[-1]
        _set_grid_visible(self._pdf_status_frame, show_panel)
        if show_panel:
            for label, variable in (
                (self._pdf_status_label, feedback.status),
                (self._pdf_result_label, feedback.result_text),
            ):
                if str(label.cget("textvariable")) != str(variable):
                    label.configure(textvariable=variable)
        _set_grid_visible(
            self.progress_bar, show_panel and self._busy and self._working_tool == tool
        )
        _set_grid_visible(
            self._pdf_result_actions, show_panel and feedback.info is not None
        )
        _set_grid_visible(
            self._pdf_result_label, show_panel and bool(feedback.result_text.get())
        )
        available = (
            show_panel
            and feedback.info is not None
            and not feedback.pending
            and not self._shutdown_requested
        )
        for button, callback in (
            (self.open_file_button, self._actions.open_result_file),
            (self.open_folder_button, self._actions.open_result_folder),
        ):
            _configure_if_changed(
                button,
                state="normal"
                if available
                and callback is not None
                and (button is self.open_folder_button or len(feedback.paths) == 1)
                else "disabled",
            )
        self._refresh_word_presentation()

    def _open_result(self, folder: bool) -> None:
        owner = self._visible_tool
        if owner is None or self._shutdown_requested:
            return
        feedback = self._feedback_for(owner)
        if feedback.info is None or feedback.pending:
            return
        if not folder and len(feedback.paths) > 1:
            return
        callback = (
            self._actions.open_result_folder
            if folder
            else self._actions.open_result_file
        )
        if callback is not None:
            feedback.generation += 1
            try:
                self._request_pdf_result(
                    owner,
                    ResultRequest(feedback.paths, callback, feedback.info.identity),
                )
            except (OSError, RuntimeError):
                self._actions.show_error(
                    "Não foi possível abrir o resultado nesta sessão."
                )
                return
            feedback.opening_folder = folder
            self._refresh_result_actions()

    def _schedule_result_poll(self):
        if self._result_after_id is None and not self._closed:
            self._result_after_id = self.after(40, self._poll_result)

    def _poll_result(self):
        self._result_after_id = None
        if self._closed:
            return
        changed = False
        for owner, feedback in self._tool_feedback.items():
            if not feedback.pending:
                continue
            value = self._result_worker.take(owner)
            if value is not None and value[0] == feedback.generation:
                self._complete_result(owner, feedback, value[1])
                changed = True
        if any(feedback.pending for feedback in self._tool_feedback.values()):
            self._schedule_result_poll()
        if changed:
            self._refresh_result_actions()

    def _complete_result(self, owner: str, feedback: _PdfToolFeedback, info) -> None:
        feedback.pending = False
        folder = feedback.opening_folder
        feedback.opening_folder = None
        if not isinstance(info, ResultInfo) or info.error:
            message = (
                info.error
                if isinstance(info, ResultInfo)
                else "Não foi possível conferir o resultado."
            )
            self._set_result(None, tool=owner)
            feedback.result_text.set(message)
            if folder is not None:
                self._actions.show_error(message)
            return
        feedback.info = info
        path = feedback.paths[0]
        prefix = (
            f"{len(feedback.paths)} arquivos" if len(feedback.paths) > 1 else path.name
        )
        feedback.result_text.set(
            f"Resultado: {prefix} · Pasta: {path.parent}\nTamanho real: {format_size(info.size_bytes)}"
        )
        if info.opened:
            feedback.status.set(
                "Pasta aberta no Explorador de Arquivos."
                if folder
                else "Arquivo aberto no aplicativo padrão."
            )

    def _toggle_extract_page(self, page: int) -> None:
        count = self._extract_page_count
        if self.is_busy or not count or not 1 <= page <= count:
            return
        text = self._extract_selection.get()
        try:
            pages = parse_page_selection(text, count) if text.strip() else ()
        except InvalidPageSelectionError:
            return
        # Tirar a marca remove todas as aparições dessa página.
        # As outras páginas conservam a ordem e eventuais repetições.
        pages = (
            tuple(value for value in pages if value != page)
            if page in pages
            else (*pages, page)
        )
        self._extract_selection.set(",".join(map(str, pages)))

    def _on_extract_selection_changed(self) -> None:
        self._update_extract_summary()
        self._refresh_controls()

    def _sync_extract_preview_selection(self):
        if hasattr(self, "extract_page_preview"):
            selection = self._extract_selection.get()
            count = self._extract_page_count
            enabled = bool(count) and not self.is_busy
            try:
                pages = (
                    parse_page_selection(selection, count)
                    if count and selection.strip()
                    else ()
                )
            except InvalidPageSelectionError:
                pages, enabled = (), False
            self.extract_page_preview.set_selection(pages, enabled=enabled)

    def _update_extract_summary(self) -> None:
        count = self._extract_page_count
        selection = self._extract_selection.get()
        if count is None:
            self._extract_validation_text.set("Aguardando leitura do PDF.")
            self._extract_summary_text.set("")
            return
        if not selection.strip():
            self._extract_validation_text.set("Informe páginas ou faixas.")
            self._extract_summary_text.set(
                f"Documento: {_format_count(count, 'página', 'páginas')}."
            )
            return
        try:
            pages = parse_page_selection(selection, count)
        except InvalidPageSelectionError as error:
            self._extract_validation_text.set(f"Seleção inválida: {error}")
            self._extract_summary_text.set(
                f"Documento: {_format_count(count, 'página', 'páginas')}."
            )
            return
        self._extract_validation_text.set("Seleção válida.")
        self._extract_summary_text.set(
            f"Documento: {_format_count(count, 'página', 'páginas')}. "
            f"Resultado: {_format_count(len(pages), 'página', 'páginas')}. "
            "Resultado na ordem informada."
        )

    def _on_pdf_images_options_changed(self) -> None:
        specific = self._pdf_images_scope.get() == "Páginas específicas"
        if bool(self.pdf_images_range.grid_info()) != specific:
            if specific:
                self.pdf_images_range.grid()
            else:
                self.pdf_images_range.grid_remove()
            self._schedule_tool_height()
        self._update_pdf_images_summary()
        self._refresh_controls()
        if hasattr(self, "pdf_images_page_preview"):
            try:
                selection = self._pdf_images_selected_specification()
                pages = (
                    parse_page_selection(selection, self._pdf_images_page_count)
                    if selection and self._pdf_images_page_count
                    else None
                )
            except InvalidPageSelectionError:
                pages = ()
            self.pdf_images_page_preview.set_selection(pages)

    def _update_pdf_images_summary(self) -> None:
        count = self._pdf_images_page_count
        if count is None:
            self._pdf_images_summary_text.set("Selecione um PDF para conferir a saída.")
            return
        selection = self._pdf_images_selected_specification()
        if selection is None:
            selected_count = count
        else:
            try:
                pages = parse_page_selection(selection, count)
            except InvalidPageSelectionError as error:
                self._pdf_images_summary_text.set(f"Seleção inválida: {error}")
                return
            if len(set(pages)) != len(pages):
                self._pdf_images_summary_text.set("Não repita páginas na exportação.")
                return
            selected_count = len(pages)
        self._pdf_images_summary_text.set(
            f"{_format_count(selected_count, 'imagem será gerada', 'imagens serão geradas')} · "
            f"{self._pdf_images_quality.get()}."
        )

    def _operation_progress_text(self, name: str) -> tk.StringVar:
        return {
            "merge": self._merge_progress_text,
            "extract": self._extract_progress_text,
            "pdf_images": self._pdf_images_progress_text,
            "poster": self._poster_progress_text,
            "word": self._word_progress_text,
        }[name]

    def _begin_pdf_work(self, status: str) -> None:
        self._working_tool = self.tab_view.get()
        self._busy = True
        self._set_result(None)
        self._status.set(status)

    def _start_pdf_operation_worker(
        self,
        name: str,
        operation: Callable[
            [threading.Event, Callable[[PdfOperationProgress], None]], Any
        ],
        callback: Callable[[Any], None],
        status: str,
    ) -> None:
        if self._shutdown_requested:
            return
        if self._busy:
            self._actions.show_warning("Aguarde a operação PDF atual terminar.")
            return
        self._operation_generation += 1
        generation = self._operation_generation
        cancel_event = threading.Event()
        self._operation_cancel_event = cancel_event
        self._operation_name = name
        self._operation_state = _PdfOperationUiState.PROCESSING
        self._begin_pdf_work(status)
        self._operation_progress_text(name).set("Preparando...")
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
        self._refresh_controls()

        def report_progress(progress: PdfOperationProgress) -> None:
            self._operation_progress_results.put((generation, progress))

        def run() -> None:
            try:
                result = _PdfWorkerResult(
                    callback,
                    value=operation(cancel_event, report_progress),
                    operation=name,
                    generation=generation,
                )
            except (PdfOperationCancelled, PosterOperationCancelled):
                result = _PdfWorkerResult(
                    callback, operation=name, generation=generation, cancelled=True
                )
            except (PdfToolsError, PosterToolsError) as error:
                result = _PdfWorkerResult(
                    callback,
                    error_message=str(error),
                    operation=name,
                    generation=generation,
                )
            except Exception:
                result = _PdfWorkerResult(
                    callback,
                    error_message="Não foi possível concluir a operação PDF.",
                    operation=name,
                    generation=generation,
                )
            self._results.put(result)

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-pdf-worker",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._busy = False
            self._operation_cancel_event = None
            self._operation_name = None
            self._operation_state = _PdfOperationUiState.ERROR
            self._reset_pdf_progress_bar()
            self._operation_progress_text(name).set("")
            self._refresh_controls()
            message = "Não foi possível iniciar a operação. Tente novamente."
            self._status.set(message)
            self._working_tool = None
            self._actions.show_error(message)
            return
        self.after(80, self._poll_worker)

    def _cancel_pdf_operation(self, name: str) -> None:
        if (
            self._operation_name != name
            or self._operation_state is not _PdfOperationUiState.PROCESSING
            or self._operation_cancel_event is None
        ):
            return
        self._operation_state = _PdfOperationUiState.CANCELLING
        self._operation_cancel_event.set()
        self._status.set("Cancelando...")
        self._operation_progress_text(name).set("Cancelando...")
        self._refresh_controls()

    def _start_worker(
        self,
        operation: Callable[[], Any],
        callback: Callable[[Any], None],
        status: str,
    ) -> None:
        if self._shutdown_requested:
            return
        if self._busy:
            self._actions.show_warning("Aguarde a operação PDF atual terminar.")
            return
        self._begin_pdf_work(status)
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self._refresh_controls()

        def run() -> None:
            try:
                self._results.put(_PdfWorkerResult(callback, value=operation()))
            except PdfToolsError as error:
                self._results.put(_PdfWorkerResult(callback, error_message=str(error)))
            except Exception:
                self._results.put(
                    _PdfWorkerResult(
                        callback,
                        error_message="Não foi possível concluir a operação PDF.",
                    )
                )

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-pdf-worker",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._busy = False
            self._reset_pdf_progress_bar()
            self._refresh_controls()
            message = "Não foi possível iniciar a operação. Tente novamente."
            self._status.set(message)
            self._working_tool = None
            self._actions.show_error(message)
            return
        self.after(80, self._poll_worker)

    def _poll_worker(self) -> None:
        if self._closed:
            return
        self._apply_latest_images_progress()
        self._apply_latest_operation_progress()
        try:
            result = self._results.get_nowait()
        except Empty:
            self.after(80, self._poll_worker)
            return
        try:
            if result.operation == "images":
                self._complete_images_worker(result)
            elif result.operation in {
                "merge",
                "extract",
                "pdf_images",
                "poster",
                "word",
            }:
                self._complete_pdf_operation_worker(result)
            else:
                self._complete_pdf_inspection_worker(result)
        finally:
            if not self._busy:
                self._working_tool = None

    def _complete_pdf_inspection_worker(self, result: _PdfWorkerResult) -> None:
        self._busy = False
        self._reset_pdf_progress_bar()
        self._refresh_controls()
        if result.error_message is not None:
            self._status.set(
                "Operação PDF não concluída. Confira os arquivos e tente novamente."
            )
            if not self._shutdown_requested:
                self._actions.show_error(result.error_message)
            return
        if self._shutdown_requested:
            self._status.set("Operação PDF concluída com segurança.")
            return
        result.callback(result.value)

    def _apply_latest_operation_progress(self) -> None:
        latest: tuple[int, PdfOperationProgress] | None = None
        for _ in range(64):
            try:
                event = self._operation_progress_results.get_nowait()
                if event[0] == self._operation_generation:
                    latest = event
            except Empty:
                break
        if latest is None or self._operation_name is None:
            return
        generation, progress = latest
        if (
            generation != self._operation_generation
            or self._operation_state is not _PdfOperationUiState.PROCESSING
            or progress.total_items < 1
        ):
            return
        fraction = progress.completed_items / progress.total_items
        self.progress_bar.set(max(0.0, min(1.0, fraction)))
        if self._operation_name == "word":
            self.word_progress_bar.set(self.progress_bar.get())
            phase = getattr(progress, "phase", "")
            if phase:
                self._operation_progress_text("word").set(
                    f"{phase}: página {progress.completed_items + 1} de {progress.total_items}."
                )
                return
        if self._operation_name == "poster":
            self._operation_progress_text(self._operation_name).set(
                f"Página {progress.completed_items} de {progress.total_items}."
            )
        else:
            unit = "documentos" if self._operation_name == "merge" else "páginas"
            adjective = (
                "concluídos" if self._operation_name == "merge" else "concluídas"
            )
            self._operation_progress_text(self._operation_name).set(
                f"{progress.completed_items} de {progress.total_items} "
                f"{unit} {adjective}."
            )

    def _complete_pdf_operation_worker(self, result: _PdfWorkerResult) -> None:
        if (
            result.generation != self._operation_generation
            or result.operation != self._operation_name
        ):
            return
        name = result.operation
        self._busy = False
        self._operation_cancel_event = None
        self._operation_name = None
        self._reset_pdf_progress_bar()
        cancel_wins = (
            result.cancelled or self._operation_state is _PdfOperationUiState.CANCELLING
        )
        if cancel_wins:
            self._operation_state = _PdfOperationUiState.CANCELLED
            self._status.set("Operação PDF cancelada.")
            self._operation_progress_text(name).set("Operação cancelada.")
            self._refresh_controls()
            return
        if result.error_message is not None:
            self._operation_state = _PdfOperationUiState.ERROR
            self._status.set(
                "Operação PDF não concluída. Confira os arquivos e tente novamente."
            )
            self._operation_progress_text(name).set("")
            self._refresh_controls()
            if not self._shutdown_requested:
                self._actions.show_error(result.error_message)
            return
        self._operation_state = _PdfOperationUiState.COMPLETED
        self._operation_progress_text(name).set("")
        self._refresh_controls()
        if self._shutdown_requested:
            self._status.set("Operação PDF concluída com segurança.")
            return
        result.callback(result.value)

    def _apply_latest_images_progress(self) -> None:
        latest: tuple[int, ImagesToPdfProgress] | None = None
        for _ in range(64):
            try:
                event = self._images_progress_results.get_nowait()
                if event[0] == self._images_generation:
                    latest = event
            except Empty:
                break
        if latest is None:
            return
        generation, progress = latest
        if (
            generation != self._images_generation
            or self._images_state is not _ImagesPdfUiState.PROCESSING
        ):
            return
        fraction = progress.completed_pages / progress.total_pages
        self.progress_bar.set(max(0.0, min(1.0, fraction)))
        self._images_progress_text.set(
            f"{progress.completed_pages} de {progress.total_pages} páginas concluídas."
        )

    def _complete_images_worker(self, result: _PdfWorkerResult) -> None:
        if result.generation != self._images_generation:
            return
        cancel_wins = (
            result.cancelled or self._images_state is _ImagesPdfUiState.CANCELLING
        )
        self._busy = False
        self._images_cancel_event = None
        self._reset_pdf_progress_bar()
        if cancel_wins:
            self._images_state = _ImagesPdfUiState.CANCELLED
            self._status.set("Criação do PDF cancelada.")
            self._images_progress_text.set("Operação cancelada.")
            self._refresh_controls()
            return
        if result.error_message is not None:
            self._images_state = _ImagesPdfUiState.ERROR
            self._status.set(
                "Operação PDF não concluída. Confira os arquivos e tente novamente."
            )
            self._images_progress_text.set("")
            self._refresh_controls()
            if not self._shutdown_requested:
                self._actions.show_error(result.error_message)
            return
        self._images_state = _ImagesPdfUiState.COMPLETED
        self._images_progress_text.set("")
        self._refresh_controls()
        if self._shutdown_requested:
            self._status.set("Operação PDF concluída com segurança.")
            return
        result.callback(result.value)

    def _reset_pdf_progress_bar(self) -> None:
        self.progress_bar.stop()
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.set(0)

    def _refresh_controls(self) -> None:
        self._sync_extract_preview_selection()
        available = not self._busy and not self._shutdown_requested
        self._refresh_result_actions()
        normal = "normal" if available else "disabled"
        _configure_if_changed(
            self.tool_back_button,
            state="disabled" if self._shutdown_requested else "normal",
        )
        _configure_if_changed(self.word_select_button, state=normal)
        _configure_if_changed(
            self.word_destination_button,
            state=normal if self._word_source else "disabled",
        )
        _configure_if_changed(
            self.word_convert_button,
            state=normal
            if self._word_source and self._word_destination
            else "disabled",
        )
        _configure_if_changed(
            self.word_cancel_button,
            state="normal"
            if self._operation_name == "word"
            and self._operation_state is _PdfOperationUiState.PROCESSING
            else "disabled",
        )
        _configure_if_changed(self.merge_select_button, state=normal)
        _configure_if_changed(self.extract_select_button, state=normal)
        _configure_if_changed(self.images_select_button, state=normal)
        _configure_if_changed(self.images_paper_menu, state=normal)
        _configure_if_changed(self.images_orientation_menu, state=normal)
        _configure_if_changed(self.images_margin_menu, state=normal)
        _configure_if_changed(self.images_per_page_menu, state=normal)
        _configure_if_changed(self.pdf_images_select_button, state=normal)
        _configure_if_changed(self.pdf_images_destination_button, state=normal)
        _configure_if_changed(self.pdf_images_format_menu, state=normal)
        _configure_if_changed(self.pdf_images_quality_menu, state=normal)
        _configure_if_changed(self.poster_select_button, state=normal)
        _configure_if_changed(self.poster_grid_menu, state=normal)
        _configure_if_changed(self.poster_paper_menu, state=normal)
        _configure_if_changed(self.poster_orientation_menu, state=normal)
        _configure_if_changed(self.poster_overlap_menu, state=normal)
        _configure_if_changed(self.poster_crop_marks_check, state=normal)
        _configure_if_changed(self.pdf_images_all_radio, state=normal)
        _configure_if_changed(self.pdf_images_specific_radio, state=normal)
        _configure_if_changed(self.extract_entry, state=normal)
        _configure_if_changed(
            self.pdf_images_entry,
            state=(
                "normal"
                if available and self._pdf_images_scope.get() == "Páginas específicas"
                else "disabled"
            ),
        )
        self.merge_files.set_enabled(available)
        self.image_files.set_enabled(available)

        merge_index = self.merge_files.selected_index
        image_index = self.image_files.selected_index
        _configure_if_changed(
            self.merge_remove_button,
            state="normal" if available and merge_index >= 0 else "disabled",
        )
        _configure_if_changed(
            self.images_up_button,
            state="normal" if available and image_index > 0 else "disabled",
        )
        _configure_if_changed(
            self.images_down_button,
            state=(
                "normal"
                if available and 0 <= image_index < len(self.image_files.paths) - 1
                else "disabled"
            ),
        )
        _configure_if_changed(
            self.images_remove_button,
            state="normal" if available and image_index >= 0 else "disabled",
        )
        for button in (self.images_rotate_left, self.images_rotate_right):
            _configure_if_changed(
                button, state="normal" if available and image_index >= 0 else "disabled"
            )
        _configure_if_changed(
            self.merge_run_button,
            state="normal"
            if available and len(self.merge_files.paths) >= 2
            else "disabled",
        )
        _configure_if_changed(
            self.merge_cancel_button,
            state=(
                "normal"
                if self._operation_name == "merge"
                and self._operation_state is _PdfOperationUiState.PROCESSING
                and not self._shutdown_requested
                else "disabled"
            ),
        )
        _configure_if_changed(
            self.extract_run_button,
            state=(
                "normal"
                if available and self._extract_selection_is_valid()
                else "disabled"
            ),
        )
        _configure_if_changed(
            self.extract_cancel_button,
            state=(
                "normal"
                if self._operation_name == "extract"
                and self._operation_state is _PdfOperationUiState.PROCESSING
                and not self._shutdown_requested
                else "disabled"
            ),
        )
        _configure_if_changed(
            self.images_run_button,
            state="normal"
            if available and bool(self.image_files.paths)
            else "disabled",
        )
        _configure_if_changed(
            self.images_cancel_button,
            state=(
                "normal"
                if self._busy
                and self._images_state is _ImagesPdfUiState.PROCESSING
                and not self._shutdown_requested
                else "disabled"
            ),
        )
        _configure_if_changed(
            self.pdf_images_run_button,
            state=(
                "normal"
                if available and self._pdf_images_selection_is_valid()
                else "disabled"
            ),
        )
        _configure_if_changed(
            self.pdf_images_cancel_button,
            state=(
                "normal"
                if self._operation_name == "pdf_images"
                and self._operation_state is _PdfOperationUiState.PROCESSING
                and not self._shutdown_requested
                else "disabled"
            ),
        )
        _configure_if_changed(
            self.poster_run_button,
            state=(
                "normal"
                if available
                and self._poster_source is not None
                and self._poster_preview is not None
                and not self._poster_preview_failed
                else "disabled"
            ),
        )
        _configure_if_changed(
            self.poster_cancel_button,
            state=(
                "normal"
                if self._operation_name == "poster"
                and self._operation_state is _PdfOperationUiState.PROCESSING
                and not self._shutdown_requested
                else "disabled"
            ),
        )

    def _extract_selection_is_valid(self) -> bool:
        if self._extract_source is None or self._extract_page_count is None:
            return False
        try:
            parse_page_selection(
                self._extract_selection.get(),
                self._extract_page_count,
            )
        except InvalidPageSelectionError:
            return False
        return True

    def _pdf_images_selected_specification(self) -> str | None:
        if self._pdf_images_scope.get() == "Todas as páginas":
            return None
        return self._pdf_images_selection.get()

    def _pdf_images_selection_is_valid(self) -> bool:
        if (
            self._pdf_images_source is None
            or self._pdf_images_page_count is None
            or self._pdf_images_destination is None
        ):
            return False
        selection = self._pdf_images_selected_specification()
        if selection is None:
            return True
        try:
            pages = parse_page_selection(selection, self._pdf_images_page_count)
        except InvalidPageSelectionError:
            return False
        return len(set(pages)) == len(pages)


class DocumentsPage(ScrollableFrame):
    """Página persistente para conversões documentais locais em PDF."""

    is_placeholder = False
    tool_names = ("Word para PDF", "Texto para PDF", "OpenDocument para PDF")

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        component_service: DocumentsComponentService,
        conversion_service: DocumentsConversionService,
        configured_component_path: Path | str | None = None,
        actions: DocumentsPageActions,
        design: Design | None = None,
        component_resolver: Callable[[], Path | None] | None = None,
        dialog_preferences: DialogFolderPreferences | None = None,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        super().__init__(
            master, corner_radius=0, fg_color=CANVAS, scrollbar_fg_color=CANVAS
        )
        design = design or Design(self.winfo_toplevel())
        self.grid_columnconfigure(0, weight=1)
        self._component_service = component_service
        self._component_resolver = component_resolver
        self._dialog_preferences = dialog_preferences or DialogFolderPreferences()
        self._conversion_service = conversion_service
        self._configured_component_path = (
            Path(configured_component_path) if configured_component_path else None
        )
        self._actions = actions
        self._thread_factory = thread_factory
        self._component_results: Queue[_DocumentsComponentWorkerResult] = Queue()
        self._conversion_results: Queue[_DocumentsWorkerResult] = Queue()
        self._component_generation = 0
        self._operation_generation = 0
        self._component_check_active = False
        self._component_known = False
        self._component_available = False
        self._active_component_root: Path | None = None
        self._operation = DocumentInputFormat.DOCX
        self._source: Path | None = None
        self._result_path: Path | None = None
        self._cancel_event: threading.Event | None = None
        self._cancelled_generation: int | None = None
        self._busy = False
        self._closed = False
        self._shutdown_requested = False
        self._state = DocumentsUiState.COMPONENT_UNAVAILABLE
        self._component_status = tk.StringVar(
            value="Componente de documentos ainda não verificado."
        )
        self._source_text = tk.StringVar(value="Nenhum documento selecionado")
        self._status = tk.StringVar(
            value="Abra esta página para verificar o componente."
        )

        title = tk.StringVar(value="Converter documentos em PDF")
        subtitle = tk.StringVar(
            value="Converta arquivos Word, ODT ou TXT no seu computador."
        )
        design.tool_header(self, title, subtitle).grid(
            row=0,
            column=0,
            padx=PAGE_INSET,
            pady=(PAGE_INSET, 16),
            sticky="ew",
        )

        self.tool_picker = ctk.CTkFrame(self, fg_color="transparent")
        self.tool_picker.grid(
            row=1, column=0, padx=PAGE_INSET, pady=(0, 14), sticky="ew"
        )
        self.tool_picker.grid_columnconfigure(
            (0, 1, 2), weight=1, uniform="document_tool"
        )
        self.tool_cards: dict[str, ctk.CTkButton] = {}
        for column, (name, description) in enumerate(
            (
                ("Word/DOCX → PDF", "Documentos do Word."),
                ("ODT → PDF", "Documentos OpenDocument."),
                ("TXT → PDF", "Arquivos de texto."),
            )
        ):
            tile = _card(self.tool_picker)
            tile.grid(
                row=0,
                column=column,
                padx=(0, 10) if column < 2 else 0,
                sticky="nsew",
            )
            tile.grid_columnconfigure(0, weight=1)
            design.form_label(
                tile,
                text=name,
                font=ctk.CTkFont(size=16, weight="bold"),
                wraplength=165,
            ).grid(row=0, column=0, padx=14, pady=(18, 6), sticky="w")
            design.form_label(tile, text=description, text_color=MUTED).grid(
                row=1, column=0, padx=14, pady=(0, 12), sticky="w"
            )
            button = design.button(
                tile,
                text="Abrir ferramenta",
                height=CONTROL_HEIGHT,
                command=lambda selected=name: self._choose_tool_card(selected),
                kind="secondary",
                keyboard=True,
            )
            button.grid(row=2, column=0, padx=14, pady=(0, 18), sticky="ew")
            design.interactive_card(tile, button)
            self.tool_cards[name] = button

        self.tool_back_button = design.button(
            self,
            text="Voltar às ferramentas",
            height=CONTROL_HEIGHT,
            width=190,
            command=self._show_tool_picker,
            kind="secondary",
            keyboard=True,
        )
        self.tool_back_button.grid(
            row=1, column=0, padx=PAGE_INSET, pady=(0, 14), sticky="w"
        )
        self.tool_back_button.grid_remove()

        self.component_card = _card(self)
        component_card = self.component_card
        component_card.grid(row=5, column=0, padx=PAGE_INSET, pady=(0, 14), sticky="ew")
        component_card.grid_columnconfigure(0, weight=1)
        design.form_label(
            component_card,
            text="LibreOffice local (opcional)",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(18, 5), sticky="w")
        self.component_guidance_label = design.form_label(
            component_card,
            text=(
                "DOCX e ODT precisam do LibreOffice, software de "
                "terceiros não incluído no EduDownloader. TXT funciona sem ele. "
                "A instalação existente é detectada automaticamente. Se necessário, configure agora."
            ),
            anchor="w",
            justify="left",
            wraplength=620,
            text_color=("gray35", "gray70"),
        )
        self.component_guidance_label.grid(
            row=1, column=0, padx=20, pady=(0, 8), sticky="ew"
        )
        design.form_label(
            component_card,
            textvariable=self._component_status,
            anchor="w",
            justify="left",
            wraplength=620,
        ).grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")
        component_actions = ctk.CTkFrame(component_card, fg_color="transparent")
        component_actions.grid(row=3, column=0, padx=20, pady=(0, 18), sticky="w")
        if actions.start_component_install is not None:
            self.install_component_button = design.button(
                component_actions,
                text="Configurar agora",
                command=actions.start_component_install,
                width=165,
                kind="primary",
                keyboard=True,
            )
            self.install_component_button.grid(row=0, column=0, padx=(0, 8))
        self.configure_component_button = design.button(
            component_actions,
            text="Localizar LibreOffice",
            command=self._choose_component,
            width=190,
            kind="secondary",
            keyboard=True,
        )
        self.configure_component_button.grid(row=0, column=1, padx=(0, 8))
        self.recheck_component_button = design.button(
            component_actions,
            text="Verificar novamente",
            command=self._request_component_check,
            width=170,
            kind="secondary",
            keyboard=True,
        )
        self.recheck_component_button.grid(
            row=1, column=0, columnspan=2, pady=(8, 0), sticky="w"
        )

        self.conversion_card = _card(self)
        conversion_card = self.conversion_card
        conversion_card.grid(
            row=3, column=0, padx=PAGE_INSET, pady=(0, 14), sticky="ew"
        )
        conversion_card.grid_columnconfigure(0, weight=1)
        operation_row = ctk.CTkFrame(conversion_card, fg_color="transparent")
        operation_row.grid_columnconfigure(0, weight=1)
        self.operation_control = ctk.CTkSegmentedButton(
            operation_row,
            values=list(_DOCUMENT_OPERATION_BY_LABEL),
            command=self._change_operation,
        )
        self.operation_control.set(_DOCUMENT_OPERATION_LABELS[self._operation])
        self.operation_title = design.form_label(
            conversion_card,
            text="Word para PDF",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.operation_title.grid(row=1, column=0, padx=20, pady=(20, 6), sticky="w")
        self.operation_description = design.form_label(
            conversion_card,
            text="Selecione um documento DOCX e escolha onde salvar o PDF.",
            justify="left",
            wraplength=620,
        )
        self.operation_description.grid(
            row=2, column=0, padx=20, pady=(0, 14), sticky="w"
        )
        input_row = ctk.CTkFrame(conversion_card, fg_color="transparent")
        input_row.grid(row=3, column=0, padx=20, pady=(0, 14), sticky="ew")
        input_row.grid_columnconfigure(0, weight=1)
        source_label = design.form_label(
            input_row,
            textvariable=self._source_text,
            wraplength=250,
            fg_color=SOFT,
            corner_radius=CONTROL_RADIUS,
            padx=10,
            pady=8,
            text_color=MUTED,
        )
        source_label.grid(row=0, column=0, padx=(0, 10), sticky="ew")
        wrap_to_frame(input_row, source_label, reserved=172)
        self.select_button = design.button(
            input_row,
            text="Selecionar DOCX",
            command=self._select_document,
            width=140,
            kind="primary",
            keyboard=True,
        )
        self.select_button.grid(row=0, column=1)
        self.output_folder = ToolOutputFolder(
            conversion_card,
            design,
            self._dialog_preferences,
            "documents.output",
        )
        self.output_folder.grid(
            row=4, column=0, padx=CARD_INSET, pady=(0, 12), sticky="ew"
        )
        self._engine_text = tk.StringVar()
        engine = design.form_label(
            conversion_card,
            textvariable=self._engine_text,
            text_color=MUTED,
            fg_color=SOFT,
            corner_radius=CONTROL_RADIUS,
            padx=12,
            pady=8,
            wraplength=360,
        )
        engine.grid(row=5, column=0, padx=CARD_INSET, pady=(0, 14), sticky="ew")
        wrap_to_frame(conversion_card, engine, reserved=2 * CARD_INSET + 24)
        action_row = ctk.CTkFrame(conversion_card, fg_color="transparent")
        action_row.grid(row=6, column=0, padx=CARD_INSET, pady=(0, 20), sticky="ew")
        action_row.grid_columnconfigure(0, weight=1)
        self.convert_button = design.button(
            action_row,
            text="Converter para PDF",
            height=40,
            command=self._start_conversion,
            kind="primary",
            keyboard=True,
        )
        self.convert_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.cancel_button = design.button(
            action_row,
            text="Cancelar",
            width=110,
            command=self._cancel_conversion,
            kind="danger",
            keyboard=True,
        )
        self.cancel_button.grid(row=0, column=1)

        self.status_card = _card(self)
        status_card = self.status_card
        status_card.grid(row=4, column=0, padx=PAGE_INSET, pady=(0, 28), sticky="ew")
        status_card.grid_columnconfigure(1, weight=1)
        status_label = design.form_label(
            status_card, textvariable=self._status, wraplength=420
        )
        status_label.grid(
            row=0, column=0, columnspan=2, padx=16, pady=(12, 6), sticky="ew"
        )
        wrap_to_frame(status_card, status_label, reserved=32)
        self.progress_bar = ProgressBar(
            status_card, mode="indeterminate", fg_color=SOFT, progress_color=PRIMARY
        )
        self.progress_bar.grid(
            row=1, column=0, columnspan=2, padx=16, pady=(0, 10), sticky="ew"
        )
        self.progress_bar.set(0)
        self.open_file_button = design.button(
            status_card,
            text="Abrir arquivo",
            command=self._open_result_file,
            width=130,
            kind="secondary",
            keyboard=True,
        )
        self.open_file_button.grid(
            row=2, column=0, padx=(16, 4), pady=(0, 14), sticky="w"
        )
        self.open_folder_button = design.button(
            status_card,
            text="Abrir pasta",
            command=self._open_result_folder,
            width=130,
            kind="secondary",
            keyboard=True,
        )
        self.open_folder_button.grid(
            row=2, column=1, padx=(4, 16), pady=(0, 14), sticky="w"
        )
        self.conversion_card.grid_remove()
        self.status_card.grid_remove()
        self._refresh_controls()

    def _choose_tool_card(self, name: str) -> None:
        operation = {
            "Word/DOCX → PDF": "Word para PDF",
            "ODT → PDF": "OpenDocument para PDF",
            "TXT → PDF": "Texto para PDF",
        }[name]
        self._change_operation(operation)
        self.operation_control.set(_DOCUMENT_OPERATION_LABELS[self._operation])
        self._show_document_tool()

    def _show_document_tool(self) -> None:
        self.tool_picker.grid_remove()
        self.component_card.grid_remove()
        self.tool_back_button.grid()
        self.conversion_card.grid()
        self.status_card.grid()
        self._refresh_controls()
        self._parent_canvas.yview_moveto(0.0)

    def _show_tool_picker(self) -> None:
        if self._busy or self._shutdown_requested:
            return
        self.conversion_card.grid_remove()
        self.status_card.grid_remove()
        self.tool_back_button.grid_remove()
        self.tool_picker.grid()
        self.component_card.grid()
        self._parent_canvas.yview_moveto(0.0)

    @property
    def state(self) -> DocumentsUiState:
        return self._state

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def operation(self) -> DocumentInputFormat:
        return self._operation

    @property
    def is_shutdown_ready(self) -> bool:
        return self._shutdown_requested and not self._busy

    @property
    def shutdown_error(self) -> None:
        return None

    def on_show(self) -> None:
        """Dispara a checagem opcional somente quando a página é aberta."""

        if (
            self._component_resolver is not None or not self._component_known
        ) and not self._component_check_active:
            self._request_component_check()

    def begin_shutdown(self) -> None:
        self._shutdown_requested = True
        if self._busy:
            self._cancel_conversion()
        self._refresh_controls()

    def cancel_shutdown(self) -> None:
        self._shutdown_requested = False
        self._refresh_controls()

    def close(self) -> None:
        self._closed = True
        self._component_generation += 1
        self._operation_generation += 1
        if self._cancel_event is not None:
            self._cancel_event.set()

    def prepare_docx_to_pdf(self, path: Path | str) -> bool:
        """Prepara DOCX → PDF sem iniciar conversão ou expor widgets internos."""

        return self._prepare_document(path, DocumentInputFormat.DOCX)

    def prepare_odt_to_pdf(self, path: Path | str) -> bool:
        """Prepara ODT → PDF sem iniciar conversão ou expor widgets internos."""

        return self._prepare_document(path, DocumentInputFormat.ODT)

    def prepare_txt_to_pdf(self, path: Path | str) -> bool:
        """Prepara TXT → PDF sem iniciar conversão ou expor widgets internos."""

        return self._prepare_document(path, DocumentInputFormat.TXT)

    def _prepare_document(
        self, path: Path | str, operation: DocumentInputFormat
    ) -> bool:
        """Aplica um handoff fortemente tipado sem iniciar trabalho em background."""

        if self._busy or self._shutdown_requested or self._closed:
            return False
        try:
            source = validate_local_regular_file(path)
        except LocalFilesError:
            return False
        if source.suffix.casefold() != f".{operation.value.casefold()}":
            return False
        self._operation = operation
        self.operation_control.set(_DOCUMENT_OPERATION_LABELS[operation])
        self._apply_operation_labels()
        self._source = source
        self._result_path = None
        self._source_text.set(source.name)
        self._set_state(
            DocumentsUiState.READY
            if operation is DocumentInputFormat.TXT or self._component_available
            else DocumentsUiState.COMPONENT_UNAVAILABLE
        )
        self._show_document_tool()
        self._refresh_controls()
        return True

    def _change_operation(self, label: str) -> None:
        if self._busy or self._shutdown_requested or self._closed:
            self.operation_control.set(_DOCUMENT_OPERATION_LABELS[self._operation])
            return
        operation = _DOCUMENT_OPERATION_BY_LABEL.get(label)
        if operation is None or operation is self._operation:
            return
        self._operation = operation
        self._source = None
        self._result_path = None
        self._source_text.set("Nenhum documento selecionado")
        self._apply_operation_labels()
        self._set_state(
            DocumentsUiState.READY
            if operation is DocumentInputFormat.TXT or self._component_available
            else DocumentsUiState.COMPONENT_UNAVAILABLE
        )
        self._refresh_controls()

    def _apply_operation_labels(self) -> None:
        description, button, _title, _filetype, _warning = _DOCUMENT_OPERATION_DETAILS[
            self._operation
        ]
        self.operation_title.configure(text=_DOCUMENT_OPERATION_LABELS[self._operation])
        self.operation_description.configure(text=description)
        self.select_button.configure(text=button)

    def _set_state(self, state: DocumentsUiState) -> None:
        self._state = state
        self._status.set(_DOCUMENTS_STATE_TEXT[state])

    def _choose_component(self) -> None:
        if self._busy or self._component_check_active or self._shutdown_requested:
            return
        selected = filedialog.askdirectory(
            title="Selecione a pasta do LibreOffice",
            parent=self.winfo_toplevel(),
            mustexist=True,
        )
        if selected:
            self._start_component_check(Path(selected), persist_choice=True)

    def use_managed_component(self, root: Path) -> None:
        """Atualiza a página persistente depois da ativação explícita."""

        self._configured_component_path = root
        self._start_component_check(root, persist_choice=False)

    def _request_component_check(self) -> None:
        if self._busy or self._component_check_active or self._shutdown_requested:
            return
        self._start_component_check(None, persist_choice=False)

    def _start_component_check(
        self, candidate: Path | None, *, persist_choice: bool
    ) -> None:
        self._component_generation += 1
        generation = self._component_generation
        self._component_check_active = True
        self._component_status.set("Verificando LibreOffice...")
        self._refresh_controls()

        def run() -> None:
            component_root = candidate
            try:
                if candidate is None:
                    if self._component_resolver is not None:
                        component_root = self._component_resolver()
                        check = self._component_service.fast_check(component_root)
                    else:
                        check = self._component_service.fast_check()
                    if (
                        self._component_resolver is None
                        and check.status is DocumentsComponentStatus.NOT_CONFIGURED
                        and self._configured_component_path is not None
                    ):
                        component_root = self._configured_component_path
                        check = self._component_service.fast_check(component_root)
                else:
                    check = self._component_service.fast_check(candidate)
                    if (
                        persist_choice
                        and check.status is DocumentsComponentStatus.AVAILABLE
                    ):
                        default_check = self._component_service.fast_check()
                        if (
                            default_check.status is DocumentsComponentStatus.AVAILABLE
                            and default_check.component is not None
                            and check.component is not None
                            and default_check.component.root == check.component.root
                        ):
                            component_root = None
            except Exception:
                check = DocumentsComponentCheck(
                    DocumentsComponentStatus.INVALID,
                    None,
                    "documents_component_ui_check_failed",
                )
            self._component_results.put(
                _DocumentsComponentWorkerResult(
                    generation,
                    check,
                    component_root,
                    persist_choice,
                )
            )

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-documents-component-check",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._component_check_active = False
            self._component_known = True
            self._apply_component_status(DocumentsComponentStatus.INVALID)
            return
        self.after(80, self._poll_component_check)

    def _poll_component_check(self) -> None:
        if self._closed:
            return
        try:
            result = self._component_results.get_nowait()
        except Empty:
            self.after(80, self._poll_component_check)
            return
        if result.generation != self._component_generation:
            self.after(0, self._poll_component_check)
            return
        self._component_check_active = False
        self._component_known = True
        self._component_available = (
            result.check.status is DocumentsComponentStatus.AVAILABLE
        )
        self._active_component_root = (
            result.component_root if self._component_available else None
        )
        if self._component_available and result.persist_choice:
            persist_path = result.component_root
            if self._actions.persist_component_path(persist_path):
                self._configured_component_path = persist_path
            else:
                self._actions.show_warning(
                    "O componente está disponível nesta sessão, mas a configuração "
                    "não pôde ser salva."
                )
        self._apply_component_status(result.check.status)

    def _apply_component_status(self, status: DocumentsComponentStatus) -> None:
        messages = {
            DocumentsComponentStatus.AVAILABLE: ("LibreOffice pronto para uso."),
            DocumentsComponentStatus.NOT_CONFIGURED: (
                "LibreOffice não encontrado. Configure para converter Word e OpenDocument. Texto para PDF continua disponível."
            ),
            DocumentsComponentStatus.INVALID: (
                "Não foi possível validar o LibreOffice. Localize uma instalação existente ou configure novamente."
            ),
            DocumentsComponentStatus.CORRUPTED: (
                "A instalação selecionada do LibreOffice está incompleta."
            ),
            DocumentsComponentStatus.VERSION_MISMATCH: (
                "Esta versão do LibreOffice não é compatível."
            ),
        }
        self._component_available = status is DocumentsComponentStatus.AVAILABLE
        self._component_status.set(messages[status])
        self.configure_component_button.configure(
            text=(
                "Alterar configuração"
                if self._component_available
                else "Localizar LibreOffice"
            )
        )
        if (
            self._operation is DocumentInputFormat.TXT or self._component_available
        ) and not self._busy:
            self._set_state(DocumentsUiState.READY)
        elif not self._busy:
            self._set_state(DocumentsUiState.COMPONENT_UNAVAILABLE)
        self._refresh_controls()

    def _select_docx(self) -> None:
        """Compatibilidade interna: seleciona DOCX na operação padrão."""

        if self._operation is not DocumentInputFormat.DOCX:
            self._change_operation(_DOCUMENT_OPERATION_LABELS[DocumentInputFormat.DOCX])
        self._select_document()

    def _select_document(self) -> None:
        if self._busy or self._shutdown_requested:
            return
        _description, _button, title, filetype, warning = _DOCUMENT_OPERATION_DETAILS[
            self._operation
        ]
        selected = self._dialog_preferences.choose(
            filedialog.askopenfilename,
            "documents.input",
            title=title,
            parent=self.winfo_toplevel(),
            filetypes=(filetype,),
        )
        if not selected:
            return
        suffix = f".{self._operation.value.casefold()}"
        source = _validated_handoff_file(Path(selected), frozenset({suffix}))
        if source is None:
            self._actions.show_warning(warning)
            return
        self._source = source
        self._result_path = None
        self._source_text.set(source.name)
        if self._operation is DocumentInputFormat.TXT or self._component_available:
            self._set_state(DocumentsUiState.READY)
        self._refresh_controls()

    def _start_conversion(self) -> None:
        source = self._source
        component_required = self._operation is not DocumentInputFormat.TXT
        if (
            source is None
            or (component_required and not self._component_available)
            or self._busy
            or self._shutdown_requested
        ):
            return
        selected = self._dialog_preferences.choose(
            filedialog.asksaveasfilename,
            "documents.output",
            title="Salvar documento PDF",
            parent=self.winfo_toplevel(),
            defaultextension=".pdf",
            initialfile=f"{source.stem}.pdf",
            filetypes=(("Documento PDF", "*.pdf"),),
            confirmoverwrite=False,
        )
        if not selected:
            return
        output = Path(selected)
        self.output_folder.show_folder(output.parent)
        overwrite = output.exists()
        if overwrite and not self._actions.confirm_overwrite(
            f'O arquivo "{output.name}" já existe. Deseja substituí-lo?'
        ):
            return
        self._operation_generation += 1
        generation = self._operation_generation
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._cancelled_generation = None
        self._busy = True
        self._result_path = None
        self._set_state(DocumentsUiState.PREPARING)
        self.progress_bar.start()
        self._refresh_controls()
        request = DocumentConversionRequest(
            input_path=source,
            output_path=output,
            component_root=self._active_component_root,
            overwrite=overwrite,
            cancel_event=cancel_event,
            input_format=self._operation,
        )

        def run() -> None:
            try:
                result = self._conversion_service.convert(request)
            except Exception:
                result = DocumentConversionResult(
                    DocumentConversionStatus.ERROR,
                    None,
                    None,
                    _DOCUMENTS_STATE_TEXT[DocumentsUiState.ERROR],
                    "documents_ui_worker_error",
                )
            self._conversion_results.put(_DocumentsWorkerResult(generation, result))

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-documents-worker",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._busy = False
            self.progress_bar.stop()
            self.progress_bar.set(0)
            self._set_state(DocumentsUiState.ERROR)
            self._refresh_controls()
            self._actions.show_error(_DOCUMENTS_STATE_TEXT[DocumentsUiState.ERROR])
            return
        self.after(0, lambda: self._mark_converting(generation))
        self.after(80, self._poll_conversion)

    def _mark_converting(self, generation: int) -> None:
        if (
            not self._closed
            and self._busy
            and generation == self._operation_generation
            and self._state is DocumentsUiState.PREPARING
        ):
            self._set_state(DocumentsUiState.CONVERTING)
            self._refresh_controls()

    def _cancel_conversion(self) -> None:
        if not self._busy or self._cancel_event is None:
            return
        self._cancelled_generation = self._operation_generation
        self._cancel_event.set()
        self._set_state(DocumentsUiState.CANCELLING)
        self._refresh_controls()

    def _poll_conversion(self) -> None:
        if self._closed:
            return
        try:
            worker_result = self._conversion_results.get_nowait()
        except Empty:
            self.after(80, self._poll_conversion)
            return
        if worker_result.generation != self._operation_generation:
            self.after(0, self._poll_conversion)
            return
        self._busy = False
        self._cancel_event = None
        self.progress_bar.stop()
        self.progress_bar.set(0)
        if self._cancelled_generation == worker_result.generation:
            self._set_state(DocumentsUiState.CANCELLED)
        else:
            self._apply_conversion_result(worker_result.result)
        self._refresh_controls()

    def _apply_conversion_result(self, result: DocumentConversionResult) -> None:
        if result.status is DocumentConversionStatus.COMPLETED:
            self._result_path = result.output_path
            self._set_state(DocumentsUiState.COMPLETED)
            if result.output_path is not None:
                self._status.set(f'PDF criado: "{result.output_path.name}".')
            if not self._shutdown_requested:
                if self._actions.notify is None:
                    self._actions.show_info(self._status.get())
                elif result.output_path is not None:
                    self._actions.notify("success", "Documento convertido com sucesso.")
            return
        if result.status is DocumentConversionStatus.CANCELLED:
            self._set_state(DocumentsUiState.CANCELLED)
            return
        if result.status is DocumentConversionStatus.COMPONENT_UNAVAILABLE:
            self._component_available = False
            self._active_component_root = None
            self._component_status.set(
                "LibreOffice local não configurado. TXT para PDF continua disponível."
            )
            self._set_state(
                DocumentsUiState.READY
                if self._operation is DocumentInputFormat.TXT
                else DocumentsUiState.COMPONENT_UNAVAILABLE
            )
            return
        if result.status is DocumentConversionStatus.INVALID_INPUT:
            message = {
                DocumentInputFormat.DOCX: (
                    "Este arquivo do Word não pôde ser processado."
                ),
                DocumentInputFormat.ODT: (
                    "Este arquivo OpenDocument não pôde ser processado."
                ),
                DocumentInputFormat.TXT: (
                    "Não foi possível ler este arquivo de texto."
                ),
            }[self._operation]
        elif result.status is DocumentConversionStatus.OUTPUT_EXISTS:
            message = "O arquivo PDF de destino já existe."
        else:
            message = _DOCUMENTS_STATE_TEXT[DocumentsUiState.ERROR]
        self._set_state(DocumentsUiState.ERROR)
        if not self._shutdown_requested:
            self._actions.show_error(message)

    def _open_result_file(self) -> None:
        if self._result_path is not None and not self._actions.open_result_file(
            self._result_path
        ):
            self._result_path = None
            self._refresh_controls()

    def _open_result_folder(self) -> None:
        if self._result_path is not None and not self._actions.open_result_folder(
            self._result_path
        ):
            self._result_path = None
            self._refresh_controls()

    def _refresh_controls(self) -> None:
        available = not self._busy and not self._shutdown_requested
        self.tool_back_button.configure(state="normal" if available else "disabled")
        component_controls = (
            "normal" if available and not self._component_check_active else "disabled"
        )
        self.configure_component_button.configure(state=component_controls)
        if hasattr(self, "install_component_button"):
            self.install_component_button.configure(state=component_controls)
        self.recheck_component_button.configure(state=component_controls)
        self.operation_control.configure(state="normal" if available else "disabled")
        for button in self.tool_cards.values():
            button.configure(
                state="normal" if available else "disabled",
                text="Abrir ferramenta",
            )
        self.select_button.configure(state="normal" if available else "disabled")
        component_ready = (
            self._operation is DocumentInputFormat.TXT or self._component_available
        )
        is_text = self._operation is DocumentInputFormat.TXT
        engine_text = (
            "O TXT é convertido localmente sem LibreOffice."
            if is_text
            else self._component_status.get()
        )
        if self._engine_text.get() != engine_text:
            self._engine_text.set(engine_text)
        self.output_folder.set_enabled(available)
        if self.conversion_card.grid_info():
            show_component = not is_text and not self._component_available
            if bool(self.component_card.grid_info()) != show_component:
                if show_component:
                    self.component_card.grid()
                else:
                    self.component_card.grid_remove()
        self.convert_button.configure(
            state=(
                "normal"
                if available and component_ready and self._source is not None
                else "disabled"
            )
        )
        self.cancel_button.configure(
            state=(
                "normal"
                if self._busy
                and self._state
                in {DocumentsUiState.PREPARING, DocumentsUiState.CONVERTING}
                and not self._shutdown_requested
                else "disabled"
            )
        )
        result_available = (
            available
            and self._state is DocumentsUiState.COMPLETED
            and self._result_path is not None
        )
        result_state = "normal" if result_available else "disabled"
        self.open_file_button.configure(state=result_state)
        self.open_folder_button.configure(state=result_state)
        _set_grid_visible(self.progress_bar, self._busy)
        _set_grid_visible(self.cancel_button, self._busy)
        _set_grid_visible(self.open_file_button, result_available)
        _set_grid_visible(self.open_folder_button, result_available)


class MediaToolsPage(ScrollableFrame):
    """Página persistente para conversões locais simples de mídia."""

    is_placeholder = False
    tool_names = ("Extrair áudio do vídeo",)

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        service: MediaToolsService,
        actions: MediaPageActions,
        design: Design | None = None,
        back_to_tools: Callable[[], None] | None = None,
        dialog_preferences: DialogFolderPreferences | None = None,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
        shutdown_thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        super().__init__(
            master, corner_radius=0, fg_color=CANVAS, scrollbar_fg_color=CANVAS
        )
        self._media_design = design or Design(self.winfo_toplevel())
        self.grid_columnconfigure(0, weight=1)
        self._service = service
        self._actions = actions
        self._thread_factory = thread_factory
        self._shutdown_thread_factory = shutdown_thread_factory
        self._dialog_preferences = dialog_preferences or DialogFolderPreferences()
        self._results: Queue[_MediaWorkerResult] = Queue()
        self._progress_results: CoalescingQueue[tuple[int, MediaConversionProgress]] = (
            CoalescingQueue(lambda event: event[0])
        )
        self._cancel_results: Queue[_MediaCancelResult] = Queue()
        self._shutdown_results: Queue[_MediaShutdownResult] = Queue()
        self._source: Path | None = None
        self._result_path: Path | None = None
        self._state = MediaUiState.IDLE
        self._operation_generation = 0
        self._cancel_requested = False
        self._cancel_ack_pending = False
        self._operation_cancel_event: threading.Event | None = None
        self._pending_worker_result: _MediaWorkerResult | None = None
        self._busy = False
        self._closed = False
        self._shutdown_requested = False
        self._shutdown_cancel_pending = False
        self._shutdown_error: str | None = None
        self._shutdown_generation = 0
        self._source_text = tk.StringVar(value="Nenhum vídeo selecionado")
        self._quality = tk.StringVar(value=DEFAULT_MP3_QUALITY.display_label)
        self._extraction_mode = tk.StringVar(value="Áudio completo")
        self._mode_trace: str | None = None
        self._segment_start = tk.StringVar(value="00:00")
        self._segment_end = tk.StringVar(value="")
        self._status = tk.StringVar(
            value="Selecione um vídeo para começar. A conversão é local."
        )

        self._build_conversion_panel(back_to_tools)
        self._mode_trace = self._extraction_mode.trace_add(
            "write", self._show_extraction_mode
        )
        self._show_extraction_mode()

    def _build_conversion_panel(self, back_to_tools):
        design = self._media_design
        self._media_title = tk.StringVar()
        subtitle = tk.StringVar(
            value="Escolha o áudio que deseja salvar a partir de um vídeo local."
        )
        design.tool_header(self, self._media_title, subtitle).grid(
            row=0,
            column=0,
            padx=PAGE_INSET,
            pady=(PAGE_INSET, 16),
            sticky="ew",
        )
        if back_to_tools is not None:
            design.button(
                self,
                "Voltar às ferramentas",
                back_to_tools,
                kind="secondary",
                width=190,
                keyboard=True,
            ).grid(row=1, column=0, padx=PAGE_INSET, pady=(0, 14), sticky="w")

        card = surface(self)
        card.grid(row=2, column=0, padx=PAGE_INSET, pady=(0, 14), sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        source = ctk.CTkFrame(card, fg_color="transparent")
        source.grid(row=0, column=0, padx=CARD_INSET, pady=(18, 12), sticky="ew")
        source.grid_columnconfigure(0, weight=1)
        design.form_label(source, text="Arquivo de vídeo", font=design.heading).grid(
            row=0,
            column=0,
            sticky="w",
        )
        source_label = design.form_label(
            source,
            textvariable=self._source_text,
            text_color=MUTED,
            wraplength=220,
            fg_color=SOFT,
            corner_radius=CONTROL_RADIUS,
            padx=10,
            pady=8,
        )
        source_label.grid(row=1, column=0, sticky="ew")
        self.select_button = design.button(
            source, "Selecionar vídeo", self._select_video, width=148, keyboard=True
        )
        self.select_button.grid(row=0, column=1, rowspan=2, padx=(10, 0))
        wrap_to_frame(source, source_label, reserved=182)
        self.description_label = design.form_label(
            card,
            text="Aceita MP4, MKV, WEBM, AVI, MOV e M4V. O vídeo original fica intacto.",
            text_color=MUTED,
            font=design.small,
            wraplength=420,
        )
        self.description_label.grid(
            row=1, column=0, padx=CARD_INSET, pady=(0, 12), sticky="ew"
        )
        wrap_to_frame(card, self.description_label, reserved=2 * CARD_INSET)
        design.form_label(card, text="O que deseja extrair?", font=design.control).grid(
            row=2,
            column=0,
            padx=CARD_INSET,
            sticky="w",
        )
        self.extraction_mode_menu = ctk.CTkSegmentedButton(
            card,
            values=["Áudio completo", "Trecho específico"],
            font=design.control,
            height=40,
            corner_radius=CONTROL_RADIUS,
            fg_color=SURFACE,
            selected_color=("#CDE6FB", "#314F6D"),
            selected_hover_color=SOFT_HOVER,
            unselected_color=SOFT,
            unselected_hover_color=SOFT_HOVER,
            text_color=TEXT,
            command=lambda choice: self._extraction_mode.set(
                "Somente um trecho"
                if choice == "Trecho específico"
                else "Áudio completo"
            ),
        )
        self.extraction_mode_menu.grid(
            row=3, column=0, padx=CARD_INSET, pady=(4, 14), sticky="w"
        )
        for button in self.extraction_mode_menu._buttons_dict.values():
            keyboard_control(
                button,
                button.invoke,
                show_focus=lambda focused, segment=button: segment.configure(
                    border_color=LINK,
                    border_width=2 if focused else 0,
                ),
            )

        self.segment_fields = ctk.CTkFrame(card, fg_color="transparent")
        self.segment_fields.grid(
            row=4, column=0, padx=CARD_INSET, pady=(0, 14), sticky="ew"
        )
        self.segment_fields.grid_columnconfigure((0, 1), weight=1, uniform="segment")
        design.form_label(
            self.segment_fields, text="Início do trecho", font=design.control
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )
        design.form_label(
            self.segment_fields, text="Fim do trecho", font=design.control
        ).grid(
            row=0,
            column=1,
            sticky="w",
        )
        self.segment_start_entry = design.form_entry(
            self.segment_fields, textvariable=self._segment_start, width=120
        )
        self.segment_start_entry.grid(
            row=1, column=0, padx=(0, 8), pady=(4, 0), sticky="ew"
        )
        self.segment_end_entry = design.form_entry(
            self.segment_fields, textvariable=self._segment_end, width=120
        )
        self.segment_end_entry.grid(row=1, column=1, pady=(4, 0), sticky="ew")
        design.form_label(
            self.segment_fields,
            text="Use MM:SS ou HH:MM:SS.",
            text_color=MUTED,
        ).grid(row=2, column=0, columnspan=2, pady=(4, 0), sticky="w")

        design.form_label(card, text="Qualidade do MP3", font=design.control).grid(
            row=5,
            column=0,
            padx=CARD_INSET,
            sticky="w",
        )
        self.quality_menu = design.form_menu(
            card,
            values=[profile.display_label for profile in MP3_QUALITY_OPTIONS],
            variable=self._quality,
            width=205,
        )
        self.quality_menu.grid(
            row=6, column=0, padx=CARD_INSET, pady=(4, 12), sticky="w"
        )
        self.output_folder = ToolOutputFolder(
            card, design, self._dialog_preferences, "media.output"
        )
        self.output_folder.grid(
            row=7, column=0, padx=CARD_INSET, pady=(0, 14), sticky="ew"
        )
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=8, column=0, padx=CARD_INSET, pady=(0, 18), sticky="w")
        self.convert_button = design.button(
            row,
            "Extrair MP3",
            self._start_conversion,
            width=212,
            keyboard=True,
        )
        self.convert_button.grid(row=0, column=0, padx=(0, 8))
        self.cancel_button = design.button(
            row,
            "Cancelar",
            self._cancel_conversion,
            kind="danger",
            width=108,
            keyboard=True,
        )
        self.cancel_button.grid(row=0, column=1)

        status = surface(self)
        status.grid(row=3, column=0, padx=PAGE_INSET, pady=(0, 28), sticky="ew")
        status.grid_columnconfigure(1, weight=1)
        label = design.form_label(status, textvariable=self._status, wraplength=414)
        label.grid(
            row=0, column=0, columnspan=2, padx=CARD_INSET, pady=(12, 6), sticky="ew"
        )
        wrap_to_frame(status, label, reserved=2 * CARD_INSET)
        self.progress_bar = ProgressBar(
            status, mode="indeterminate", fg_color=SOFT, progress_color=PRIMARY
        )
        self.progress_bar.grid(
            row=1, column=0, columnspan=2, padx=CARD_INSET, pady=(0, 12), sticky="ew"
        )
        self.progress_bar.set(0)
        self.open_file_button = design.button(
            status,
            "Abrir arquivo",
            self._open_result_file,
            kind="secondary",
            width=128,
            keyboard=True,
        )
        self.open_folder_button = design.button(
            status,
            "Abrir pasta",
            self._open_result_folder,
            kind="secondary",
            width=128,
            keyboard=True,
        )
        self.open_file_button.grid(
            row=2, column=0, padx=(CARD_INSET, 8), pady=(0, 14), sticky="w"
        )
        self.open_folder_button.grid(row=2, column=1, pady=(0, 14), sticky="w")

    def _show_extraction_mode(self, *_args):
        segment = self._extraction_mode.get() == "Somente um trecho"
        self._media_title.set(
            "Extrair trecho de áudio" if segment else "Extrair áudio de vídeo"
        )
        self.extraction_mode_menu.set(
            "Trecho específico" if segment else "Áudio completo"
        )
        if bool(self.segment_fields.grid_info()) != segment:
            if segment:
                self.segment_fields.grid()
            else:
                self.segment_fields.grid_remove()
        self.convert_button.configure(
            text="Extrair trecho MP3" if segment else "Extrair MP3"
        )
        self._refresh_controls()

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def is_shutdown_ready(self) -> bool:
        self._consume_shutdown_result()
        return (
            self._shutdown_requested
            and not self._busy
            and not self._shutdown_cancel_pending
            and self._shutdown_error is None
        )

    @property
    def shutdown_error(self) -> str | None:
        self._consume_shutdown_result()
        return self._shutdown_error

    def begin_shutdown(self) -> None:
        """Impede novas conversões e cancela a operação corrente fora do Tk."""

        if self._shutdown_requested:
            return
        self._shutdown_generation += 1
        self._shutdown_requested = True
        self._shutdown_error = None
        if self._busy:
            self._status.set("Cancelando...")
            self._start_shutdown_cancel()
        self._refresh_controls()

    def cancel_shutdown(self) -> None:
        """Permite nova tentativa depois de uma falha segura de cancelamento."""

        self._shutdown_generation += 1
        self._shutdown_requested = False
        self._shutdown_cancel_pending = False
        self._shutdown_error = None
        self._refresh_controls()

    def close(self) -> None:
        if self._closed:
            return
        self._shutdown_generation += 1
        self._closed = True
        if self._mode_trace is not None:
            self._extraction_mode.trace_remove("write", self._mode_trace)
            self._mode_trace = None

    def destroy(self):
        if not getattr(self, "_closed", True):
            self.close()
        super().destroy()

    def prepare_video_to_mp3_source(self, path: Path | str) -> bool:
        """Prepara um vídeo para conversão sem iniciar o FFmpeg."""

        if self._shutdown_requested:
            return False
        if self._busy:
            self._actions.show_warning("Aguarde a conversão de mídia atual terminar.")
            return False
        source = _validated_handoff_file(path, SUPPORTED_VIDEO_SUFFIXES)
        if source is None:
            self._actions.show_warning("Selecione um arquivo de vídeo válido.")
            return False
        self._prepare_video_source(source)
        return True

    def _select_video(self) -> None:
        if self._busy or self._shutdown_requested:
            return
        selected = self._dialog_preferences.choose(
            filedialog.askopenfilename,
            "media.input",
            title="Selecione o vídeo",
            parent=self.winfo_toplevel(),
            filetypes=(
                ("Vídeos compatíveis", "*.mp4 *.mkv *.webm *.avi *.mov *.m4v"),
                ("MP4", "*.mp4 *.m4v"),
                ("MKV", "*.mkv"),
                ("WEBM", "*.webm"),
                ("AVI", "*.avi"),
                ("MOV", "*.mov"),
            ),
        )
        if selected:
            self._prepare_video_source(Path(selected))

    def _prepare_video_source(self, source: Path) -> None:
        self._source = source
        self._result_path = None
        self._state = MediaUiState.READY
        self._quality.set(DEFAULT_MP3_QUALITY.display_label)
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.set(0)
        self._source_text.set(self._source.name)
        self._status.set(
            "Vídeo selecionado. Escolha o formato de extração e salve o MP3."
        )
        self._refresh_controls()

    def _start_conversion(self) -> None:
        source = self._source
        if source is None or self._busy or self._shutdown_requested:
            return
        quality = next(
            (
                profile
                for profile in MP3_QUALITY_OPTIONS
                if profile.display_label == self._quality.get()
            ),
            None,
        )
        if quality is None:
            self._actions.show_warning("Selecione uma qualidade MP3 válida.")
            return
        segment = None
        if self._extraction_mode.get() == "Somente um trecho":
            try:
                segment = parse_media_segment(
                    self._segment_start.get(), self._segment_end.get()
                )
            except ValueError as error:
                self._actions.show_warning(str(error))
                return
        selected = self._dialog_preferences.choose(
            filedialog.asksaveasfilename,
            "media.output",
            title="Salvar áudio MP3",
            parent=self.winfo_toplevel(),
            defaultextension=".mp3",
            initialfile=f"{source.stem}.mp3",
            filetypes=(("Áudio MP3", "*.mp3"),),
            confirmoverwrite=False,
        )
        if not selected:
            return
        output = Path(selected)
        self.output_folder.show_folder(output.parent)
        overwrite = output.exists()
        if overwrite and not self._actions.confirm_overwrite(
            f'O arquivo "{output.name}" já existe. Deseja substituí-lo?'
        ):
            self._status.set("Conversão não iniciada; o arquivo existente foi mantido.")
            return
        self._result_path = None
        self._busy = True
        self._operation_generation += 1
        generation = self._operation_generation
        self._cancel_requested = False
        self._cancel_ack_pending = False
        self._operation_cancel_event = threading.Event()
        self._pending_worker_result = None
        self._state = MediaUiState.PREPARING
        self._status.set("Preparando a conversão local...")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.set(0)
        self.progress_bar.start()
        self._refresh_controls()

        def report_progress(progress: MediaConversionProgress) -> None:
            self._progress_results.put((generation, progress))

        def run() -> None:
            try:
                convert = (
                    self._service.video_to_mp3
                    if segment is None
                    else self._service.video_segment_to_mp3
                )
                segment_options = (
                    {}
                    if segment is None
                    else {"start_seconds": segment[0], "end_seconds": segment[1]}
                )
                result = convert(
                    source,
                    output,
                    overwrite=overwrite,
                    quality=quality,
                    on_progress=report_progress,
                    cancel_event=self._operation_cancel_event,
                    **segment_options,
                )
                self._results.put(_MediaWorkerResult(value=result))
            except MediaOperationCancelled:
                self._results.put(_MediaWorkerResult(cancelled=True))
            except MediaToolsError as error:
                self._results.put(_MediaWorkerResult(error_message=str(error)))
            except Exception:
                self._results.put(
                    _MediaWorkerResult(
                        error_message="Não foi possível concluir a conversão de mídia."
                    )
                )

        worker = self._thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-media-worker",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._busy = False
            self._state = MediaUiState.ERROR
            self.progress_bar.stop()
            self.progress_bar.set(0)
            self._refresh_controls()
            message = "Não foi possível iniciar a operação. Tente novamente."
            self._status.set(message)
            self._actions.show_error(message)
            return
        self.after(80, self._poll_worker)

    def _cancel_conversion(self) -> None:
        """Solicita encerramento fora da thread gráfica, sem bloquear o Tk."""

        if not self._busy or self._cancel_requested or self._shutdown_requested:
            return
        if self._operation_cancel_event is not None:
            self._operation_cancel_event.set()
        self._cancel_requested = True
        self._cancel_ack_pending = True
        self._state = MediaUiState.CANCELLING
        self._status.set("Cancelando...")
        self._refresh_controls()

        def run() -> None:
            try:
                accepted = self._service.request_cancel()
                self._cancel_results.put(_MediaCancelResult(accepted=accepted))
            except Exception:
                self._cancel_results.put(
                    _MediaCancelResult(
                        error_message="Não foi possível confirmar o cancelamento da conversão."
                    )
                )

        try:
            self._shutdown_thread_factory(
                target=run,
                daemon=True,
                name="edudownloader-media-cancel",
            ).start()
        except (OSError, RuntimeError):
            self._cancel_ack_pending = False
            self._cancel_requested = False
            if self._operation_cancel_event is not None:
                self._operation_cancel_event.clear()
            self._state = MediaUiState.CONVERTING
            self._actions.show_error("Não foi possível solicitar o cancelamento.")
            self._refresh_controls()

    def _consume_cancel_result(self) -> None:
        try:
            result = self._cancel_results.get_nowait()
        except Empty:
            return
        self._cancel_ack_pending = False
        if result.error_message is not None:
            self._actions.show_error(result.error_message)
            self._cancel_requested = False
            return
        if not result.accepted:
            self._cancel_requested = False

    def _consume_progress(self) -> None:
        latest: MediaConversionProgress | None = None
        for _ in range(64):
            try:
                generation, progress = self._progress_results.get_nowait()
            except Empty:
                break
            if generation == self._operation_generation:
                latest = progress
        if latest is None or self._cancel_requested or not self._busy:
            return
        self._state = MediaUiState.CONVERTING
        fraction = latest.fraction
        if fraction is None:
            self._status.set("Convertendo o vídeo localmente...")
            return
        if self.progress_bar.cget("mode") != "determinate":
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(fraction)
        self._status.set(f"Convertendo o vídeo localmente... {fraction * 100:.0f}%")

    def _poll_worker(self) -> None:
        if self._closed:
            return
        self._consume_cancel_result()
        self._consume_progress()
        result = self._pending_worker_result
        if result is None:
            try:
                result = self._results.get_nowait()
            except Empty:
                self.after(80, self._poll_worker)
                return
        if self._cancel_ack_pending:
            self._pending_worker_result = result
            self.after(80, self._poll_worker)
            return
        self._pending_worker_result = None
        self._busy = False
        self.progress_bar.stop()
        self.progress_bar.set(0)
        if result.cancelled or self._cancel_requested:
            self._state = MediaUiState.CANCELLED
            self._status.set("Conversão de mídia cancelada.")
            self._refresh_controls()
            return
        if result.error_message is not None:
            self._state = MediaUiState.ERROR
            self._status.set(
                "Não foi possível criar o MP3. Verifique o vídeo e tente novamente."
            )
            self._refresh_controls()
            if not self._shutdown_requested:
                self._actions.show_error(result.error_message)
            return
        if result.value is None:
            self._state = MediaUiState.ERROR
            self._status.set(
                "Não foi possível criar o MP3. Verifique o vídeo e tente novamente."
            )
            self._refresh_controls()
            if not self._shutdown_requested:
                self._actions.show_error(
                    "O resultado da conversão não pôde ser validado."
                )
            return
        self._state = MediaUiState.COMPLETED
        self._result_path = result.value.output_path
        self.progress_bar.set(1)
        message = f'MP3 criado: "{result.value.output_path.name}".'
        self._status.set(message)
        self._refresh_controls()
        if not self._shutdown_requested:
            if self._actions.notify is None:
                self._actions.show_info(message)
            else:
                self._actions.notify("success", "Áudio extraído com sucesso.")

    def _open_result_file(self) -> None:
        path = self._result_path
        callback = self._actions.open_result_file
        if path is not None and callback is not None and not callback(path):
            self._result_path = None
            self._refresh_controls()

    def _open_result_folder(self) -> None:
        path = self._result_path
        callback = self._actions.open_result_folder
        if path is not None and callback is not None and not callback(path):
            self._result_path = None
            self._refresh_controls()

    def _start_shutdown_cancel(self) -> None:
        if self._shutdown_cancel_pending or not self._shutdown_requested:
            return
        generation = self._shutdown_generation
        self._shutdown_cancel_pending = True

        def run() -> None:
            try:
                accepted = self._service.request_cancel()
                result = _MediaShutdownResult(generation, accepted=accepted)
            except MediaToolsError:
                result = _MediaShutdownResult(
                    generation,
                    error_message=(
                        "Não foi possível encerrar a conversão com segurança. "
                        "O aplicativo permanecerá aberto."
                    ),
                )
            self._shutdown_results.put(result)

        worker = self._shutdown_thread_factory(
            target=run,
            daemon=True,
            name="edudownloader-media-shutdown",
        )
        try:
            worker.start()
        except (OSError, RuntimeError):
            self._shutdown_cancel_pending = False
            self._shutdown_error = (
                "Não foi possível encerrar a conversão com segurança. "
                "O aplicativo permanecerá aberto."
            )

    def _consume_shutdown_result(self) -> None:
        while True:
            try:
                result = self._shutdown_results.get_nowait()
            except Empty:
                return
            if result.generation != self._shutdown_generation:
                continue
            self._shutdown_cancel_pending = False
            if result.error_message is not None:
                self._shutdown_error = result.error_message
                return
            if not result.accepted and self._shutdown_requested and self._busy:
                self._start_shutdown_cancel()
            return

    def _refresh_controls(self) -> None:
        available = not self._busy and not self._shutdown_requested
        self.select_button.configure(state="normal" if available else "disabled")
        self.quality_menu.configure(state="normal" if available else "disabled")
        self.extraction_mode_menu.configure(state="normal" if available else "disabled")
        self.output_folder.set_enabled(available)
        segment_state = (
            "normal"
            if available and self._extraction_mode.get() == "Somente um trecho"
            else "disabled"
        )
        self.segment_start_entry.configure(state=segment_state)
        self.segment_end_entry.configure(state=segment_state)
        self.convert_button.configure(
            state="normal" if self._source is not None and available else "disabled"
        )
        self.cancel_button.configure(
            state=(
                "normal"
                if self._busy
                and not self._cancel_requested
                and not self._shutdown_requested
                else "disabled"
            )
        )
        result_available = (
            available
            and self._result_path is not None
            and self._actions.open_result_file is not None
            and self._actions.open_result_folder is not None
        )
        result_state = "normal" if result_available else "disabled"
        self.open_file_button.configure(state=result_state)
        self.open_folder_button.configure(state=result_state)
        _set_grid_visible(self.progress_bar, self._busy)
        _set_grid_visible(self.cancel_button, self._busy)
        _set_grid_visible(self.open_file_button, result_available)
        _set_grid_visible(self.open_folder_button, result_available)


@dataclass(frozen=True)
class _ComponentRefreshResult:
    snapshots: tuple[ComponentSnapshot, ...]
    managed_issue: str | None = None


@dataclass(frozen=True)
class _YtDlpCheckResult:
    check: UpdateCheck
    storage: ManagedRootCheck | None = None


class SettingsPage(SettingsLayout, ScrollableFrame):
    """Coordena as preferências e as operações locais de componentes."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        theme_value: str,
        change_theme: Callable[[str], None],
        notify: Callable[[str, str], None] | None = None,
        design: Design | None = None,
        text_scale: int = DEFAULT_TEXT_SCALE,
        change_text_scale: Callable[[int], None] | None = None,
        choose_download_folder: Callable[[], None] | None = None,
        component_manager: ComponentManager | None = None,
        component_updater: YtDlpUpdateService | None = None,
        component_release_observer: ComponentReleaseObserver | None = None,
        managed_updater: ComponentUpdateService | None = None,
        confirm_component_update: Callable[[str], bool] | None = None,
        component_installer: LibreOfficeAcquisitionService | None = None,
        confirm_component_install: Callable[[str], bool] | None = None,
        activate_managed_component: Callable[[Path], bool] | None = None,
        select_existing_component: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, corner_radius=0, fg_color=PAGE_BACKGROUND)
        self._notify = notify
        self._component_manager = component_manager
        self._component_results: Queue[_ComponentRefreshResult | None] = Queue()
        self._component_worker: threading.Thread | None = None
        self._component_command_pending = False
        self._component_poll_ids: dict[str, str] = {}
        self._settings_closing = False
        self._next_shutdown_install_check = 0.0
        self.component_status_labels: dict[ComponentId, ctk.CTkLabel] = {}
        self.component_state_labels: dict[ComponentId, ctk.CTkLabel] = {}
        self._component_updater = component_updater
        self._release_observer = component_release_observer
        self._managed_updater = managed_updater
        self.release_check_buttons: dict[ComponentId, ctk.CTkButton] = {}
        self.release_update_buttons: dict[ComponentId, ctk.CTkButton] = {}
        self.release_cancel_buttons: dict[ComponentId, ctk.CTkButton] = {}
        self.release_status_labels: dict[ComponentId, ctk.CTkLabel] = {}
        self._managed_offers: dict[ComponentId, Approval] = {}
        self._confirm_component_update = confirm_component_update
        self._update_events: CoalescingQueue[tuple[str, object]] = CoalescingQueue(
            lambda event: "progress" if event[0] == "progress" else None
        )
        self._update_worker: threading.Thread | None = None
        self._update_cancel = threading.Event()
        self._available_release: OfficialRelease | None = None
        self._current_yt_dlp_version: str | None = None
        self._component_installer = component_installer
        self._confirm_component_install = confirm_component_install
        self._activate_managed_component = activate_managed_component
        self._install_events: CoalescingQueue[tuple[str, object]] = CoalescingQueue(
            lambda event: "progress" if event[0] == "progress" else None
        )
        self._install_worker: threading.Thread | None = None
        self._install_cancel = threading.Event()
        self._install_launch = threading.Event()
        self._install_ready_parent: Path | None = None
        self._install_chosen_parent: Path | None = None
        self._install_opened = False
        self._mount_settings(
            design or Design(self.winfo_toplevel()),
            theme_value=theme_value,
            change_theme=change_theme,
            text_scale=text_scale,
            change_text_scale=change_text_scale,
            choose_download_folder=choose_download_folder,
            snapshots=component_manager.list_components() if component_manager else (),
            select_existing_component=select_existing_component,
        )

    def _schedule_settings_poll(self, callback) -> None:
        key = callback.__name__
        if key in self._component_poll_ids:
            return

        def dispatch():
            self._component_poll_ids.pop(key, None)
            callback()

        self._component_poll_ids[key] = self.after(80, dispatch)

    def _start_settings_worker(self, worker, poll, *, on_start_failure) -> None:
        """Deliver startup errors through the same terminal path as worker errors."""
        try:
            worker.start()
        except (OSError, RuntimeError):
            on_start_failure()
        self._schedule_settings_poll(poll)

    def destroy(self):
        self.begin_shutdown()
        for callback_id in self._component_poll_ids.values():
            self.after_cancel(callback_id)
        self._component_poll_ids.clear()
        for name in ("update_progress", "libreoffice_progress"):
            progress = getattr(self, name, None)
            if progress is not None:
                progress.stop()
        super().destroy()

    def _set_diagnostic_controls_busy(self, busy: bool) -> None:
        buttons = (
            *getattr(self, "release_check_buttons", {}).values(),
            *getattr(self, "release_update_buttons", {}).values(),
        )
        for button in buttons:
            _configure_if_changed(
                button, state="disabled" if busy or self._settings_closing else "normal"
            )
        for name in (
            "components_refresh_button",
            "update_check_button",
            "update_action_button",
            "update_repair_button",
            "libreoffice_install_button",
            "libreoffice_existing_button",
            "libreoffice_verify_button",
        ):
            button = getattr(self, name, None)
            if button is not None:
                pending_verification = (
                    name == "libreoffice_verify_button"
                    and not self._component_work_pending
                    and getattr(
                        self._component_installer, "has_pending_installer", False
                    )
                )
                _configure_if_changed(
                    button,
                    state=(
                        "disabled"
                        if (busy or self._settings_closing) and not pending_verification
                        else "normal"
                    ),
                )

    def _run_component_command(
        self, run, present, *, failure, during_shutdown=False
    ) -> None:
        """Passa um resultado terminal para a thread Tk sem expor widgets ao worker."""
        results = Queue(maxsize=1)
        self._component_command_pending = True
        self._set_diagnostic_controls_busy(True)

        def worker():
            try:
                result = run()
            except Exception:
                result = failure
            results.put(result)

        def poll_command():
            try:
                result = results.get_nowait()
            except Empty:
                self._schedule_settings_poll(poll_command)
                return
            self._component_command_pending = False
            self._set_diagnostic_controls_busy(False)
            if during_shutdown or not self._settings_closing:
                present(result)

        thread = threading.Thread(
            target=worker, daemon=True, name="edudownloader-component"
        )
        self._start_settings_worker(
            thread, poll_command, on_start_failure=lambda: results.put(failure)
        )

    def _check_component_release(self, component_id: ComponentId) -> None:
        if (
            self._release_observer is None
            or self._component_manager is None
            or self.is_component_operation_active
            or self._settings_closing
        ):
            return
        status = self.release_status_labels[component_id]
        action = getattr(self, "release_update_buttons", {}).get(component_id)
        if action is not None:
            self._managed_offers.pop(component_id, None)
            action.grid_remove()
        status.configure(text="Consultando versões…")
        status.grid()

        def check():
            local = self._component_manager.refresh(component_id)
            managed = getattr(self, "_managed_updater", None)
            observation = self._release_observer.check(component_id, local.version)
            self._refresh_component_catalogue()
            offer = (
                managed.available(component_id, local.version)
                if managed is not None
                and action is not None
                and (
                    component_id is not ComponentId.LIBREOFFICE
                    or local.origin is ComponentOrigin.MANAGED
                )
                else None
            )
            return local, observation, offer

        def display(result):
            local, observation, offer = result
            if local is not None:
                self.show_component_indicator(component_id, local.state)
                self.component_status_labels[component_id].configure(
                    text=f"Versão {local.version} • {local.detail}"
                    if local.version
                    else local.detail,
                    text_color=SUCCESS_GREEN
                    if local.state is ComponentState.READY
                    else MUTED_TEXT_COLOR,
                )
            if offer is not None:
                self._managed_offers[component_id] = offer
                status.configure(text=f"Versão homologada disponível: {offer.version}.")
                action.grid()
                return
            status.configure(
                text={
                    "current": "Sua versão é a mais recente desta linha.",
                    "not-approved": f"Versão publicada: {observation.available_version}. Sem pacote homologado para instalar aqui.",
                    "offline": "Conexão indisponível para consultar atualizações.",
                    "failed": "Não foi possível consultar atualizações agora.",
                    "unsupported": "Consulta online indisponível para este componente.",
                }[observation.status]
            )

        self._run_component_command(
            check, display, failure=(None, ReleaseObservation(None, "failed"), None)
        )

    def _refresh_component_catalogue(self) -> None:
        updater = getattr(self, "_managed_updater", None)
        if updater is not None:
            try:
                updater.refresh_catalogue()
            except (OSError, ValueError, UpdateError):
                # A consulta informativa pode falhar com o cache ainda válido.
                pass

    def _start_managed_update(self, component_id: ComponentId) -> None:
        approval = self._managed_offers.get(component_id)
        if (
            approval is None
            or self._managed_updater is None
            or self._settings_closing
            or self.is_component_operation_active
            or self._confirm_component_update is None
        ):
            return
        if not self._confirm_component_update(
            f"Preparar a versão homologada {approval.version}?"
        ):
            return
        if self._settings_closing or self.is_component_operation_active:
            return
        status = self.release_status_labels[component_id]
        self.release_update_buttons[component_id].grid_remove()
        self.release_cancel_buttons[component_id].grid()
        self._update_cancel.clear()
        status.configure(text="Preparando atualização…")
        updates = CoalescingQueue(
            lambda event: "progress" if event[0] == "progress" else None
        )

        def worker():
            try:
                result = self._managed_updater.update(
                    approval,
                    cancel=self._update_cancel,
                    progress=lambda done, total: updates.put(
                        ("progress", (done, total))
                    ),
                )
                snapshot = self._component_manager.refresh(component_id)
            except Exception:
                result, snapshot = (UpdateStatus.FAILED, "worker_failure"), None
            updates.put(("result", (result, snapshot)))

        def display():
            for _ in range(32):
                try:
                    kind, value = updates.get_nowait()
                except Empty:
                    self._schedule_settings_poll(display)
                    return
                if kind == "progress":
                    done, total = value
                    if done < total:
                        status.configure(
                            text=f"Baixando {done / 1048576:.1f} de {total / 1048576:.1f} MiB…"
                        )
                    else:
                        status.configure(text="Verificando o pacote e o funcionamento…")
                    continue
                self._update_worker = None
                self._set_diagnostic_controls_busy(False)
                self.release_cancel_buttons[component_id].grid_remove()
                result, snapshot = value
                outcome, code = result
                if snapshot is not None:
                    self.show_component_indicator(component_id, snapshot.state)
                    self.component_status_labels[component_id].configure(
                        text=f"Versão {snapshot.version} • {snapshot.detail}"
                        if snapshot.version
                        else snapshot.detail,
                        text_color=SUCCESS_GREEN
                        if snapshot.state is ComponentState.READY
                        else MUTED_TEXT_COLOR,
                    )
                if outcome is UpdateStatus.UPDATED:
                    if (
                        component_id is ComponentId.LIBREOFFICE
                        and self._activate_managed_component is not None
                    ):
                        from libreoffice_managed import (
                            documents_data_root,
                            resolve_managed_component,
                        )

                        office = resolve_managed_component(documents_data_root())
                        if office is not None:
                            self._activate_managed_component(office)
                    self._managed_offers.pop(component_id, None)
                    status.configure(
                        text=f"Atualização concluída. Versão {approval.version}."
                    )
                else:
                    status.configure(
                        text={
                            "component_busy": "Componente em uso. Tente novamente em instantes.",
                            "insufficient_space": "Espaço insuficiente para preparar o componente.",
                            "cancelled": "Atualização cancelada. A versão anterior foi preservada.",
                        }.get(
                            code,
                            "Falha na atualização. A versão anterior foi preservada.",
                        )
                    )
                    self.release_update_buttons[component_id].grid()
                return
            self._schedule_settings_poll(display)

        self._set_diagnostic_controls_busy(True)
        self._update_worker = threading.Thread(
            target=worker, daemon=True, name="component-update"
        )
        self._start_settings_worker(
            self._update_worker,
            display,
            on_start_failure=lambda: updates.put(
                ("result", ((UpdateStatus.FAILED, "worker_failure"), None))
            ),
        )

    def _set_libreoffice_actions(self, state: ComponentState | str) -> None:
        """Mostra somente ações úteis para o estado visual atual do LibreOffice."""
        if self._component_installer is None:
            return
        self._libreoffice_action_state = state
        missing = state in (ComponentState.NOT_CONFIGURED, ComponentState.MISSING)
        failed = state in (
            ComponentState.INVALID,
            ComponentState.VERSION_MISMATCH,
            ComponentState.CORRUPTED,
            ComponentState.FAILED,
        )
        for button, visible in (
            (self.libreoffice_install_button, missing or failed),
            (self.libreoffice_existing_button, missing or failed),
            (self.libreoffice_verify_button, failed or state == "installer_pending"),
        ):
            if visible:
                button.grid()
            else:
                button.grid_remove()
        for button in (
            self.libreoffice_choose_button,
            self.libreoffice_copy_button,
            self.libreoffice_open_button,
        ):
            button.grid_remove()
        if state is ComponentState.READY:
            component = (
                self._component_manager.get_component(ComponentId.LIBREOFFICE)
                if isinstance(self._component_manager, ComponentManager)
                else None
            )
            self.show_component_indicator(ComponentId.LIBREOFFICE, state)
            self.component_status_labels[ComponentId.LIBREOFFICE].configure(
                text=(
                    f"Versão {component.version} • Pronto para uso"
                    if component is not None and component.version
                    else "Pronto para uso"
                ),
                text_color=SUCCESS_GREEN,
            )
            self.libreoffice_status.configure(text="")
            self.libreoffice_path.configure(text="")

    def _sync_libreoffice_actions(self, state: ComponentState) -> None:
        # Um refresh paralelo não deve reabrir ações durante download/instalador.
        if getattr(self, "_libreoffice_action_state", None) not in (
            "download",
            "installer",
            "verify",
            "installer_pending",
        ):
            self._set_libreoffice_actions(state)

    def _refresh_components(self) -> None:
        if (
            self._component_manager is None
            or self.is_component_operation_active
            or self._settings_closing
        ):
            return
        self._set_diagnostic_controls_busy(True)
        self.components_refresh_button.configure(text="Verificando...")
        for component_id in self.component_state_labels:
            self.show_component_indicator(component_id, checking=True)

        def worker() -> None:
            try:
                snapshots = self._component_manager.refresh_all()
                managed_issue = (
                    resolve_active_yt_dlp(
                        self._component_updater.base_dir
                    ).managed_issue
                    if self._component_updater is not None
                    else None
                )
                result = _ComponentRefreshResult(tuple(snapshots), managed_issue)
            except Exception:
                result = None
            self._component_results.put(result)

        self._component_worker = threading.Thread(target=worker, daemon=True)
        self._start_settings_worker(
            self._component_worker,
            self._poll_component_results,
            on_start_failure=lambda: self._component_results.put(None),
        )

    def _poll_component_results(self) -> None:
        if not self.winfo_exists():
            return
        try:
            results = self._component_results.get_nowait()
        except Empty:
            self._schedule_settings_poll(self._poll_component_results)
            return
        self._component_worker = None
        self._set_diagnostic_controls_busy(False)
        if results is None:
            for component_id, label in self.component_status_labels.items():
                self.show_component_indicator(component_id, ComponentState.FAILED)
                label.configure(
                    text="Não foi possível verificar. Tente novamente.",
                    text_color=MUTED_TEXT_COLOR,
                )
            self._sync_libreoffice_actions(ComponentState.FAILED)
            self._invalidate_yt_dlp_offer()
            if self._notify is not None:
                self._notify("error", "Não foi possível verificar os componentes.")
        else:
            for snapshot in results.snapshots:
                self.show_component_indicator(snapshot.component_id, snapshot.state)
                self.component_status_labels[snapshot.component_id].configure(
                    text=(
                        f"Versão {snapshot.version} • {snapshot.detail}"
                        if snapshot.version
                        else snapshot.detail
                    ),
                    text_color=(
                        SUCCESS_GREEN
                        if snapshot.state is ComponentState.READY
                        else MUTED_TEXT_COLOR
                    ),
                )
                if snapshot.component_id is ComponentId.LIBREOFFICE:
                    self._sync_libreoffice_actions(snapshot.state)
                elif snapshot.component_id is ComponentId.YT_DLP and (
                    snapshot.state is not ComponentState.READY
                    or snapshot.version != self._current_yt_dlp_version
                ):
                    self._invalidate_yt_dlp_offer()
            if self._component_updater is not None:
                if results.managed_issue is None:
                    self.update_repair_button.grid_remove()
                else:
                    self.update_repair_button.grid()
        self.components_refresh_button.configure(text="Verificar componentes")

    def _repair_yt_dlp(self) -> None:
        if (
            self.is_component_operation_active
            or self._component_updater is None
            or self._settings_closing
        ):
            return
        self.update_status.grid()
        self.update_status.configure(text="Verificando a versão original do yt-dlp...")
        self._run_component_command(
            self._component_updater.repair_invalid,
            self._show_yt_dlp_repair,
            failure=UpdateResult(UpdateStatus.FAILED, None, "worker_failure"),
        )

    def _show_yt_dlp_repair(self, result: UpdateResult) -> None:
        if result.status is UpdateStatus.REPAIRED:
            self.update_status.configure(
                text="Atualização com problema desativada; versão original disponível."
            )
            self._refresh_components()
        else:
            self.update_status.configure(
                text="Não foi possível desativar a atualização."
            )

    @property
    def _component_work_pending(self) -> bool:
        return (
            self._component_worker is not None
            or self._component_command_pending
            or (self._update_worker is not None and self._update_worker.is_alive())
            or (self._install_worker is not None and self._install_worker.is_alive())
            or not self._update_events.empty()
            or not self._install_events.empty()
        )

    @property
    def is_component_operation_active(self) -> bool:
        return self._component_work_pending or bool(
            getattr(self._component_installer, "has_pending_installer", False)
        )

    @property
    def is_shutdown_ready(self) -> bool:
        if (
            self._settings_closing
            and not self._component_work_pending
            and getattr(self._component_installer, "has_pending_installer", False)
            and time.monotonic() >= self._next_shutdown_install_check
        ):
            self._next_shutdown_install_check = time.monotonic() + 0.5
            self._recheck_libreoffice()
        return not self.is_component_operation_active

    def begin_shutdown(self) -> None:
        self._settings_closing = True
        self._set_diagnostic_controls_busy(True)
        self._update_cancel.set()
        if not self._install_opened:
            self._install_cancel.set()
            self._install_launch.set()

    def cancel_shutdown(self) -> None:
        self._settings_closing = False
        self._set_diagnostic_controls_busy(self.is_component_operation_active)

    def _recheck_libreoffice(self) -> None:
        pending = getattr(self._component_installer, "has_pending_installer", False)
        if self._component_work_pending or (self._settings_closing and not pending):
            return
        finish = getattr(self._component_installer, "finish_pending_installation", None)
        if pending and finish:
            self._run_component_command(
                finish,
                self._show_libreoffice_verification,
                failure=AcquisitionResult(
                    AcquisitionStatus.FAILED, None, "verification_failed"
                ),
                during_shutdown=True,
            )
        elif self._install_ready_parent is not None:
            self._verify_libreoffice_installation()
        else:
            self._refresh_components()

    def _show_libreoffice_verification(self, result: AcquisitionResult | None) -> None:
        if result is not None:
            self._display_libreoffice_result(result)
        if not self.is_component_operation_active and result is None:
            self._refresh_components()

    def _choose_libreoffice_destination(self) -> None:
        if self._install_opened:
            return
        selected = filedialog.askdirectory(
            title="Escolha uma pasta curta e vazia para o LibreOffice",
            parent=self.winfo_toplevel(),
            mustexist=True,
        )
        if not selected:
            return
        candidate = Path(selected)
        try:
            self._component_installer.destination_parent(candidate)
        except AcquisitionError as error:
            self.libreoffice_status.configure(
                text=(
                    "Escolha uma pasta mais curta."
                    if error.code == "managed_path_too_long"
                    else "Esta pasta não pode ser usada."
                )
            )
            return
        self._install_chosen_parent = candidate
        self._install_ready_parent = candidate
        self.libreoffice_path.configure(text=f"Destino esperado: {candidate}")
        if not self.is_component_operation_active:
            self.libreoffice_verify_button.grid()

    def _copy_libreoffice_destination(self) -> None:
        if self._install_ready_parent is None:
            return
        self.clipboard_clear()
        self.clipboard_append(str(self._install_ready_parent))
        self.libreoffice_status.configure(
            text="Caminho copiado. Cole-o no instalador oficial."
        )

    def _open_libreoffice_installer(self) -> None:
        if self._install_ready_parent is None or self._install_opened:
            return
        self.libreoffice_open_button.grid_remove()
        self.libreoffice_choose_button.configure(state="disabled")
        self._install_launch.set()

    def _cancel_libreoffice_install(self) -> None:
        if self._install_opened:
            self.libreoffice_status.configure(
                text="Conclua ou cancele primeiro na janela oficial do instalador."
            )
            return
        self._install_cancel.set()
        self._install_launch.set()

    def _verify_libreoffice_installation(self) -> None:
        if (
            self._install_ready_parent is None
            or self.is_component_operation_active
            or self._settings_closing
        ):
            self.libreoffice_status.configure(
                text="Aguarde o fechamento do instalador antes de verificar."
            )
            return
        destination = self._install_ready_parent
        options = {"repair": True} if getattr(self, "_install_repair", False) else {}
        self.libreoffice_status.configure(text="Verificando LibreOffice...")
        self._run_component_command(
            partial(
                self._component_installer.verify_installation, destination, **options
            ),
            self._display_libreoffice_result,
            failure=AcquisitionResult(
                AcquisitionStatus.FAILED, None, "verification_failed"
            ),
        )

    def start_libreoffice_install(self) -> None:
        """Inicia só após clique e consentimento; preserva a escolha manual."""

        if (
            self._component_installer is None
            or self._component_manager is None
            or self._activate_managed_component is None
            or self._confirm_component_install is None
            or self.is_component_operation_active
            or self._settings_closing
        ):
            return
        self.libreoffice_status.configure(text="Verificando LibreOffice...")
        self._run_component_command(
            partial(self._component_manager.refresh, ComponentId.LIBREOFFICE),
            self._confirm_libreoffice_install,
            failure=None,
        )

    def _confirm_libreoffice_install(self, snapshot: ComponentSnapshot | None) -> None:
        if snapshot is None or snapshot.state is ComponentState.FAILED:
            self._set_libreoffice_actions(ComponentState.FAILED)
            self.show_component_indicator(
                ComponentId.LIBREOFFICE, ComponentState.FAILED
            )
            self.libreoffice_status.configure(
                text="Não foi possível verificar o LibreOffice."
            )
            return
        self.show_component_indicator(ComponentId.LIBREOFFICE, snapshot.state)
        self.component_status_labels[ComponentId.LIBREOFFICE].configure(
            text=snapshot.detail
        )
        if snapshot.state is ComponentState.READY:
            self._set_libreoffice_actions(ComponentState.READY)
            return
        repair = snapshot.origin.value == "managed"
        self._install_repair = repair
        message = (
            "LibreOffice é um componente de terceiros. O EduDownloader baixará "
            "o MSI oficial verificado (376 MB) e abrirá o assistente. "
            "Confirme nele o destino escolhido para preparar uma cópia local "
            "do LibreOffice sem instalar no sistema. Continuar?"
        )
        if repair:
            message = (
                "O LibreOffice gerenciado está com problema. A reinstalação guiada "
                "usará a mesma versão aprovada, em um destino novo. A instalação "
                "anterior será preservada até a nova passar na verificação.\n\n"
                + message
            )
        if not self._confirm_component_install(message):
            self.libreoffice_status.configure(text="")
            return
        if self._settings_closing or self.is_component_operation_active:
            return
        self._install_cancel.clear()
        self._install_launch.clear()
        self._install_opened = False
        self._install_ready_parent = None
        self._install_chosen_parent = None
        self.libreoffice_copy_button.grid_remove()
        self.libreoffice_open_button.grid_remove()
        self.libreoffice_verify_button.grid_remove()
        self.libreoffice_choose_button.configure(state="normal")
        self.libreoffice_install_button.configure(state="disabled")
        self._set_libreoffice_actions("download")
        self._set_diagnostic_controls_busy(True)
        self.libreoffice_cancel_button.grid()
        self.libreoffice_progress.configure(mode="indeterminate")
        self.libreoffice_progress.grid()
        self.libreoffice_progress.start()
        self.libreoffice_status.configure(
            text="Preparando instalação do LibreOffice..."
        )

        def phase(value: str) -> None:
            self._install_events.put(("phase", value))

        def progress(done: int, total: int | None) -> None:
            self._install_events.put(("progress", (done, total)))

        failure = AcquisitionResult(
            AcquisitionStatus.FAILED, None, "install_worker_failed"
        )

        def worker() -> None:
            try:
                options = {"repair": True} if repair else {}
                result = self._component_installer.install(
                    cancel=self._install_cancel,
                    phase=phase,
                    progress=progress,
                    **options,
                )
            except Exception:
                result = failure
            self._install_events.put(("result", result))

        self._install_worker = threading.Thread(
            target=worker, daemon=True, name="edudownloader-libreoffice-install"
        )
        self._start_settings_worker(
            self._install_worker,
            self._poll_libreoffice_install,
            on_start_failure=lambda: self._install_events.put(("result", failure)),
        )

    def _poll_libreoffice_install(self) -> None:
        if not self.winfo_exists():
            return
        for _ in range(64):
            try:
                kind, value = self._install_events.get_nowait()
            except Empty:
                break
            if kind == "phase":
                self._display_libreoffice_phase(value)
            elif kind == "progress":
                done, total = value
                if total is not None and total > 0:
                    self.libreoffice_progress.stop()
                    self.libreoffice_progress.configure(mode="determinate")
                    self.libreoffice_progress.set(min(1.0, done / total))
                self.libreoffice_status.configure(text="Baixando LibreOffice...")
            elif kind == "ready":
                self._install_ready_parent = self._install_chosen_parent or value
                self.libreoffice_path.configure(
                    text=f"Quando o instalador perguntar onde instalar, use: {self._install_ready_parent}"
                )
                self.libreoffice_progress.stop()
                self.libreoffice_progress.grid_remove()
                self.libreoffice_copy_button.grid()
                self.libreoffice_open_button.grid()
                self.libreoffice_status.configure(
                    text="LibreOffice pronto para instalar. Copie o caminho e abra o instalador oficial."
                )
            elif kind == "result":
                self._install_worker = None
                self._display_libreoffice_result(value)
        if (
            self._install_worker is not None and self._install_worker.is_alive()
        ) or not self._install_events.empty():
            self._schedule_settings_poll(self._poll_libreoffice_install)

    def _display_libreoffice_phase(self, phase: str) -> None:
        self._set_libreoffice_actions(
            "installer" if phase == "installer_opened" else phase
        )
        if phase == "download":
            self.libreoffice_status.configure(text="Baixando LibreOffice...")
        elif phase == "installer":
            self.libreoffice_progress.stop()
            self.libreoffice_progress.configure(mode="indeterminate")
            self.libreoffice_progress.start()
            self.libreoffice_status.configure(text="Abrindo instalador oficial...")
        elif phase == "installer_opened":
            self._install_opened = True
            self.libreoffice_status.configure(
                text="Aguardando a instalação. Conclua na janela oficial do LibreOffice."
            )
        elif phase == "verify":
            self.libreoffice_status.configure(text="Verificando LibreOffice...")

    def _display_libreoffice_result(self, result: AcquisitionResult) -> None:
        self._set_diagnostic_controls_busy(
            result.diagnostic_code == "installer_pending"
        )
        self.libreoffice_progress.stop()
        self.libreoffice_progress.grid_remove()
        self.libreoffice_cancel_button.grid_remove()
        self.libreoffice_open_button.grid_remove()
        self.libreoffice_choose_button.configure(state="normal")
        was_opened = self._install_opened
        self._install_opened = False
        if result.diagnostic_code == "installer_pending":
            self._install_opened = True
            self.libreoffice_install_button.configure(state="disabled")
            self._set_libreoffice_actions("installer_pending")
            self.libreoffice_status.configure(
                text="O instalador ainda está aberto. Conclua na janela oficial e clique em Verificar instalação."
            )
            return
        if result.status is AcquisitionStatus.INSTALLED and result.component_root:
            self.libreoffice_verify_button.grid_remove()
            self.libreoffice_copy_button.grid_remove()
            self.libreoffice_path.configure(text="")
            if self._activate_managed_component(result.component_root):
                self.libreoffice_status.configure(
                    text="LibreOffice pronto para DOCX e ODT."
                )
                self._set_libreoffice_actions(ComponentState.READY)
                if self._notify is not None:
                    self._notify("success", "LibreOffice pronto para uso.")
            else:
                self._set_libreoffice_actions(ComponentState.FAILED)
                self.libreoffice_status.configure(
                    text="Instalado, mas não foi possível salvar a configuração."
                )
            return
        if result.status is AcquisitionStatus.CANCELLED:
            message = "Instalação não concluída; configuração anterior preservada."
            self.libreoffice_copy_button.grid_remove()
            self.libreoffice_verify_button.grid_remove()
        elif result.diagnostic_code == "managed_path_too_long":
            message = "O destino automático é longo demais para este LibreOffice. Use Localizar LibreOffice para uma instalação existente."
        elif result.diagnostic_code == "insufficient_disk_space":
            message = "Não há espaço livre suficiente para instalar LibreOffice."
        elif result.diagnostic_code == "managed_root_unavailable":
            message = "Esta pasta não permite instalar componentes adicionais."
        elif result.diagnostic_code == "hash_mismatch":
            message = "O pacote baixado não passou na verificação de integridade."
        elif result.diagnostic_code == "installed_structure_invalid":
            message = (
                "Não foi possível encontrar o LibreOffice após a instalação. "
                "Verifique novamente, tente instalar outra vez ou use Localizar LibreOffice."
            )
            self.libreoffice_verify_button.grid()
        elif result.diagnostic_code == "network_failure":
            message = "É necessária conexão para baixar o LibreOffice. Verifique a rede e tente novamente."
        elif result.diagnostic_code == "installer_cancelled_or_failed":
            message = "Instalação não concluída na janela oficial."
            if was_opened:
                self.libreoffice_verify_button.grid()
        else:
            message = "Não foi possível instalar LibreOffice. A configuração anterior permanece disponível."
        if not was_opened:
            self.libreoffice_copy_button.grid_remove()
            self.libreoffice_verify_button.grid_remove()
        self.libreoffice_status.configure(text=message)
        self._set_libreoffice_actions(
            ComponentState.NOT_CONFIGURED
            if result.status is AcquisitionStatus.CANCELLED
            else ComponentState.FAILED
        )

    def _check_yt_dlp_update(self) -> None:
        if (
            self._component_updater is None
            or self.is_component_operation_active
            or self._settings_closing
        ):
            return
        self.update_status.grid()
        self._invalidate_yt_dlp_offer(clear_status=False)
        self._set_diagnostic_controls_busy(True)
        self.update_status.configure(text="Verificando atualização...")
        failure = _YtDlpCheckResult(
            UpdateCheck(UpdateCheckStatus.CHECK_FAILED, None, None), None
        )

        def worker() -> None:
            try:
                self._refresh_component_catalogue()
                result = self._component_updater.check()
                storage = (
                    probe_managed_root(self._component_updater.base_dir)
                    if result.status is UpdateCheckStatus.UPDATE_AVAILABLE
                    and result.release is not None
                    else None
                )
                outcome = _YtDlpCheckResult(result, storage)
            except Exception:
                outcome = failure
            self._update_events.put(("check", outcome))

        self._update_worker = threading.Thread(target=worker, daemon=True)
        self._start_settings_worker(
            self._update_worker,
            self._poll_yt_dlp_update,
            on_start_failure=lambda: self._update_events.put(("check", failure)),
        )

    def _start_yt_dlp_update(self) -> None:
        release = self._available_release
        if (
            self._component_updater is None
            or release is None
            or self.is_component_operation_active
            or self._confirm_component_update is None
            or self._settings_closing
        ):
            return
        current = self._current_yt_dlp_version or "atual"
        if not self._confirm_component_update(
            f"Atualizar yt-dlp de {current} para {release.version}?"
        ):
            return
        if self._settings_closing or self.is_component_operation_active:
            return
        self.update_status.grid()
        self._update_cancel.clear()
        self.update_action_button.grid_remove()
        self._set_diagnostic_controls_busy(True)
        self.update_cancel_button.grid()
        self.update_progress.configure(mode="indeterminate")
        self.update_progress.grid()
        self.update_progress.start()
        self.update_status.configure(text="Preparando atualização...")

        def progress(done: int, total: int | None) -> None:
            self._update_events.put(("progress", (done, total)))

        failure = UpdateResult(UpdateStatus.FAILED, None, "worker_failure")

        def worker() -> None:
            try:
                result = self._component_updater.update(
                    release, cancel=self._update_cancel, progress=progress
                )
            except Exception:
                result = failure
            try:
                snapshot = (
                    self._component_manager.refresh(ComponentId.YT_DLP)
                    if self._component_manager is not None
                    else None
                )
            except Exception:
                snapshot = None
            self._update_events.put(("result", (result, snapshot)))

        self._update_worker = threading.Thread(target=worker, daemon=True)
        self._start_settings_worker(
            self._update_worker,
            self._poll_yt_dlp_update,
            on_start_failure=lambda: self._update_events.put(
                ("result", (failure, None))
            ),
        )

    def _poll_yt_dlp_update(self) -> None:
        if not self.winfo_exists():
            return
        for _ in range(64):
            try:
                kind, value = self._update_events.get_nowait()
            except Empty:
                break
            if kind == "check":
                self._update_worker = None
                self._display_yt_dlp_check(value.check, storage=value.storage)
            elif kind == "progress":
                done, total = value
                if total is not None and total > 0:
                    self.update_progress.stop()
                    self.update_progress.configure(mode="determinate")
                    self.update_progress.set(min(1.0, done / total))
                self.update_status.configure(text="Baixando atualização...")
            elif kind == "result":
                result, snapshot = value
                self._update_worker = None
                self._display_yt_dlp_result(result, snapshot)
        if (
            self._update_worker is not None and self._update_worker.is_alive()
        ) or not self._update_events.empty():
            self._schedule_settings_poll(self._poll_yt_dlp_update)

    def _display_yt_dlp_check(
        self, result: UpdateCheck, *, storage: ManagedRootCheck | None
    ) -> None:
        self._set_diagnostic_controls_busy(False)
        self._invalidate_yt_dlp_offer(clear_status=False)
        if result.current_version is not None:
            self._current_yt_dlp_version = result.current_version
            if self._component_states[ComponentId.YT_DLP] is not ComponentState.READY:
                self.show_component_indicator(ComponentId.YT_DLP, ComponentState.READY)
                self.component_status_labels[ComponentId.YT_DLP].configure(
                    text=f"Versão {result.current_version} • Pronto",
                    text_color=SUCCESS_GREEN,
                )
        if result.status is UpdateCheckStatus.CHECK_FAILED:
            self.update_status.configure(
                text=(
                    "Conexão indisponível para consultar atualizações."
                    if result.diagnostic_code == "connection_unavailable"
                    else "Não foi possível verificar atualizações agora."
                )
            )
            return
        if result.status is UpdateCheckStatus.UP_TO_DATE:
            self.update_status.configure(text="yt-dlp atualizado.")
            return
        if (
            result.status is UpdateCheckStatus.NOT_APPROVED
            and result.release is not None
        ):
            self.update_status.configure(
                text=f"Versão publicada: {result.release.version}. Aguardando validação de compatibilidade."
            )
            return
        if result.release is None or result.current_version is None:
            self.update_status.configure(
                text="Não foi possível confirmar uma atualização compatível."
            )
            return
        if storage is not None and storage.state is ManagedRootState.AVAILABLE:
            self._available_release = result.release
            self.update_status.configure(
                text=f"Nova versão disponível: {result.release.version}"
            )
            self.update_action_button.grid()
        else:
            self.update_status.configure(
                text="Nova versão disponível, mas esta pasta não permite instalar componentes."
            )

    def _invalidate_yt_dlp_offer(self, *, clear_status=True) -> None:
        if self._component_updater is None:
            return
        if self._available_release is not None and clear_status:
            self.update_status.configure(text="")
        self._available_release = None
        self.update_action_button.grid_remove()

    def _display_yt_dlp_result(
        self, result: UpdateResult, snapshot: ComponentSnapshot | None
    ) -> None:
        self.update_progress.stop()
        self.update_progress.grid_remove()
        self.update_cancel_button.grid_remove()
        self._set_diagnostic_controls_busy(False)
        self._available_release = None
        if snapshot is not None:
            self.show_component_indicator(snapshot.component_id, snapshot.state)
            self.component_status_labels[ComponentId.YT_DLP].configure(
                text=(
                    f"Versão {snapshot.version} • {snapshot.detail}"
                    if snapshot.version
                    else snapshot.detail
                )
            )
        messages = {
            UpdateStatus.UPDATED: "Atualização concluída.",
            UpdateStatus.CANCELLED: "Atualização cancelada; versão anterior preservada.",
            UpdateStatus.STORAGE_UNAVAILABLE: "Esta pasta não permite instalar componentes.",
            UpdateStatus.BUSY: "Aguarde o download ou atualização em andamento.",
            UpdateStatus.FAILED: "A atualização não foi aplicada. A versão anterior continua disponível.",
        }
        message = messages[result.status]
        if result.diagnostic_code == "rollback_failed":
            message = "Não foi possível confirmar o componente ativo. Reinicie o aplicativo antes de baixar."
        self.update_status.configure(text=message)
        if self._notify is not None and result.status is UpdateStatus.UPDATED:
            self._notify("success", "yt-dlp atualizado com sucesso.")

    def show_persistence_error(self, message: str) -> None:
        """Exibe na própria página uma falha ao persistir a preferência."""

        self._persistence_status.set(message)
        self.persistence_label.grid()

    def clear_persistence_feedback(self) -> None:
        """Remove aviso anterior depois de uma persistência bem-sucedida."""

        self._persistence_status.set("")
        self.persistence_label.grid_remove()
