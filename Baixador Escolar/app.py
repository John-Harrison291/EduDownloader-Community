"""Interface gráfica do EduDownloader."""

from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Callable
from contextlib import nullcontext
from enum import Enum
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from constants import (
    APP_NAME,
    CONTENT_TYPE_AUDIO,
    DEFAULT_TEXT_SCALE,
    TEXT_SCALE_LEVELS,
    THEME_DARK,
    THEME_LIGHT,
    VIDEO_QUALITIES,
)
from component_manager import ComponentManager
from component_release_policy import ComponentReleaseObserver
from downloader import (
    DownloadEvent,
    DownloadEventKind,
    DownloadPhase,
    DownloadProgress,
    DownloadRequest,
    DownloadResult,
    DownloadService,
    DownloadServiceError,
)
from download_queue import DownloadQueue, DownloadQueueError, QueueState
from documents_component import DocumentsComponentService
from libreoffice_managed import (
    LibreOfficeAcquisitionService,
    detected_component_path,
)
from documents_tools import DocumentsConversionService
from file_preview import FilePreviewService
from media_tools import MediaToolsService
from mp3_quality import DEFAULT_MP3_QUALITY, MP3_QUALITY_OPTIONS
from paths import get_downloads_dir, open_downloads_dir
from pdf_tools import PdfToolsService
from pdf_results import open_pdf_result_file, open_pdf_result_folder
from settings import (
    DialogFolderPreferences,
    favorite_folder_comparison_key,
    load_settings,
    save_settings,
)
from ui_design import (
    CANVAS,
    NAV_HOVER,
    ON_PRIMARY,
    PRIMARY,
    PRIMARY_HOVER,
    SIDEBAR_TEXT,
    SIDEBAR_WIDTH,
    SURFACE,
    TEXT,
    Design,
    NavigationRail,
    apply_window_icon,
    load_brand_image,
    reveal_scrollable_focus,
)
from ui_pages import (
    _configure_if_changed,
    DownloadsPage,
    DownloadsPageActions,
    DocumentsPage,
    DocumentsPageActions,
    FilesPage,
    FilesPageActions,
    MediaPageActions,
    MediaToolsPage,
    PdfPageActions,
    PdfToolsPage,
    SettingsPage,
)
from ui_lifecycle import AppRoot
from ui_motion import MotionClock
from ui_notifications import NotificationCenter
from ui_resize_cover import ContentPresentation, ResizePresentation
from ui_transitions import PagePresentation, PageStack
from ui_start import HomePage, ToolsPage
from yt_dlp_update import YtDlpUpdateService
from utils import format_duration, format_size, is_empty, is_valid_url


PAGE_HOME = "Início"
PAGE_DOWNLOADS = "Downloads"
PAGE_FILES = "Arquivos"
PAGE_TOOLS = "Ferramentas"
PAGE_PDF = "PDF"
PAGE_DOCUMENTS = "Documentos"
PAGE_MEDIA = "Mídia"
PAGE_SETTINGS = "Configurações"
NAVIGATION_PAGES = (
    PAGE_HOME,
    PAGE_DOWNLOADS,
    PAGE_FILES,
    PAGE_TOOLS,
    PAGE_SETTINGS,
)
_NAVIGATION_SELECTED_COLOR = PRIMARY
_TOOL_PAGES = frozenset({PAGE_PDF, PAGE_DOCUMENTS, PAGE_MEDIA})
_DOWNLOAD_EVENT_POLL_DELAY_MS = 100
_DOWNLOAD_EVENT_CONTINUE_DELAY_MS = 1
_DOWNLOAD_EVENT_MAX_PER_TICK = 32
_DOWNLOAD_EVENT_DISPATCH_BUDGET_SECONDS = 0.008


class DownloadUiState(str, Enum):
    """Estados públicos e mutuamente exclusivos da experiência de download."""

    READY = "ready"
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


_ACTIVE_DOWNLOAD_STATES = frozenset(
    {
        DownloadUiState.PREPARING,
        DownloadUiState.DOWNLOADING,
        DownloadUiState.PROCESSING,
        DownloadUiState.VERIFYING,
    }
)
_DOWNLOAD_STATE_TEXT = {
    DownloadUiState.READY: "Pronto para baixar",
    DownloadUiState.PREPARING: "Preparando o download...",
    DownloadUiState.DOWNLOADING: "Baixando...",
    DownloadUiState.PROCESSING: "Processando o arquivo...",
    DownloadUiState.VERIFYING: "Verificando arquivo...",
    DownloadUiState.COMPLETED: "Download concluído",
    DownloadUiState.CANCELLED: "Download cancelado",
    DownloadUiState.ERROR: "Não foi possível concluir o download",
}
_DOWNLOAD_BUTTON_TEXT = {
    DownloadUiState.PREPARING: "Preparando...",
    DownloadUiState.DOWNLOADING: "Baixando...",
    DownloadUiState.PROCESSING: "Processando...",
    DownloadUiState.VERIFYING: "Verificando...",
}
_STATES_WITHOUT_PROGRESS_METRICS = frozenset(
    {
        DownloadUiState.READY,
        DownloadUiState.PREPARING,
        DownloadUiState.PROCESSING,
        DownloadUiState.VERIFYING,
        DownloadUiState.CANCELLED,
        DownloadUiState.ERROR,
    }
)


def format_progress_details(progress: DownloadProgress) -> str:
    """Monta somente os detalhes de progresso realmente disponíveis."""
    details: list[str] = []
    if progress.downloaded_bytes is not None:
        downloaded = format_size(progress.downloaded_bytes)
        if progress.total_bytes is not None:
            details.append(f"{downloaded} de {format_size(progress.total_bytes)}")
        else:
            details.append(f"{downloaded} baixados")
    if progress.speed is not None:
        details.append(f"{format_size(progress.speed)}/s")
    if progress.eta is not None:
        eta = (
            f"{int(progress.eta)} s"
            if progress.eta < 60
            else format_duration(progress.eta)
        )
        details.append(f"cerca de {eta} restantes")
    return " • ".join(details)


class EduDownloaderApp(AppRoot):
    """Janela principal e integração segura com o serviço de download."""

    def __init__(
        self,
        download_service: DownloadService,
    ) -> None:
        if not isinstance(download_service, DownloadService):
            raise TypeError("download_service must be a DownloadService")
        self.settings = load_settings()
        appearance = "Dark" if self.settings["tema"] == THEME_DARK else "Light"
        ctk.set_appearance_mode(appearance)
        ctk.set_default_color_theme("blue")
        super().__init__()
        self._initial_map_after_id: str | None = None
        if os.name == "nt":
            self.withdraw()
        self.configure(fg_color=CANVAS)
        self._motion = MotionClock(self)
        self._brand_image = self._load_brand_image()
        self._window_icons = ()
        self._window_icon_applied = False

        self.title(APP_NAME)
        self.geometry("1280x820")
        self.minsize(860, 600)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._apply_window_icon()

        self.content_type = tk.StringVar(self, value=self.settings["ultimo_tipo"])
        self.quality = tk.StringVar(self, value=self.settings["ultima_qualidade"])
        self.mp3_quality = tk.StringVar(self, value=DEFAULT_MP3_QUALITY.display_label)
        self.status = tk.StringVar(
            self, value=_DOWNLOAD_STATE_TEXT[DownloadUiState.READY]
        )
        self.percentage = tk.StringVar(self, value="—")
        self.download_details = tk.StringVar(self, value="")
        self.download_service = download_service
        self.dialog_preferences = DialogFolderPreferences(
            self.settings.get("dialog_folders"), self._persist_dialog_folders
        )
        self._download_destination_dir = self.dialog_preferences.available(
            "downloads.output"
        )
        self._last_download_result: DownloadResult | None = None
        self._download_ui_state = DownloadUiState.READY
        self._cancel_requested = False
        self._modal_open = False
        self._close_requested = False
        self._close_finalized = False
        self._close_poll_after_id: str | None = None
        self._focus_link_after_id: str | None = None
        self._settings_scroll_after_id: str | None = None
        self._current_page: str | None = None
        self._navigation_in_progress = False
        self._pending_page: str | None = None
        self._pages: dict[str, ctk.CTkBaseClass] = {}
        self._navigation_buttons: dict[str, ctk.CTkButton] = {}
        self.download_queue = DownloadQueue(download_service)
        self._queue_poll_after_id: str | None = None
        self._queue_shutdown_started = False
        self._queue_last_snapshot = None

        self._build_interface()
        self._design.set_text_scale(self.settings.get("text_scale", DEFAULT_TEXT_SCALE))
        tk.Misc.bind(self, "<Map>", self._sync_window_motion, add="+")
        tk.Misc.bind(self, "<FocusIn>", self._sync_window_motion, add="+")
        tk.Misc.bind(self, "<Unmap>", self._window_motion_hidden, add="+")
        self._motion_destroy_binding = tk.Misc.bind(
            self, "<Destroy>", self._forget_motion_widget, add="+"
        )
        tk.Misc.bind(self, "<Configure>", self._resize_window_motion, add="+")
        tk.Misc.bind(self, "<ButtonPress>", self._skip_startup, add="+")
        tk.Misc.bind(self, "<KeyPress>", self._skip_startup, add="+")
        self.bind("<Tab>", self._focus_visible_navigation_widget, add="+")
        self.bind("<Shift-Tab>", self._focus_previous_navigation_widget, add="+")
        self.bind("<ISO_Left_Tab>", self._focus_previous_navigation_widget, add="+")
        self.downloads_page.show_download_destination(self._download_destination_dir)
        self._show_settings_download_destination()
        self._adapt_quality_controls(save=False)
        self._show_page(PAGE_HOME)
        self._page_stack = PageStack(
            self,
            self._page_host,
            self.home_page,
            pages=self._pages.values(),
        )
        self._motion.is_presented = self._page_stack.widget_is_presented
        self._presentation.arm_startup(self.home_page)
        self._resize_presentation = (
            ResizePresentation(self) if os.name == "nt" else None
        )
        self._content_presentation = None
        if os.name == "nt":
            content = self._content_presentation = ContentPresentation(self)
            for page in (self.files_page, self.pdf_page):
                page._viewport_change = partial(content.change, page, layout=True)
        self._poll_download_events()
        if os.name == "nt":
            self._initial_map_after_id = self.after_idle(self._show_initial_window)

    def _windows_set_titlebar_color(self, color_mode: str) -> None:
        if getattr(self, "_window_exists", False) and self.winfo_ismapped():
            # CustomTkinter oculta a janela para atualizar o mesmo atributo do DWM.
            # Na troca em uso, mantenha janela, foco e geometria mapeados.
            import ctypes as native

            hwnd = native.windll.user32.GetParent(self.winfo_id())
            dark = native.c_int(int(color_mode.lower() == "dark"))
            for attribute in (20, 19):
                if (
                    native.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attribute, native.byref(dark), native.sizeof(dark)
                    )
                    == 0
                ):
                    break
            return
        pending = getattr(self, "_initial_map_after_id", None)
        if pending is None:
            super()._windows_set_titlebar_color(color_mode)
            return
        # O preparo inicial do CustomTkinter processa eventos antes de retornar.
        # A janela principal só deve aparecer depois dessa etapa.
        self.after_cancel(pending)
        self._initial_map_after_id = None
        super()._windows_set_titlebar_color(color_mode)
        if not self._close_requested:
            self._initial_map_after_id = self.after_idle(self._show_initial_window)

    def _show_initial_window(self) -> None:
        self._initial_map_after_id = None
        if self._close_requested or self.state() != "withdrawn":
            return
        try:
            self.state("zoomed")
        except tk.TclError:
            self.deiconify()

    @staticmethod
    def _load_brand_image() -> Image.Image | None:
        """Recorta um quadrado do símbolo em memória, sem alterar o PNG original."""

        return load_brand_image(Path(__file__).resolve().parent)

    def _apply_window_icon(self) -> None:
        """Usa o símbolo também na janela e, quando suportado, na barra de tarefas."""

        self._window_icons = apply_window_icon(self, self._brand_image)
        self._window_icon_applied = bool(self._window_icons)

    def _build_interface(self) -> None:
        """Monta o shell e cria cada página exatamente uma vez."""
        self.grid_columnconfigure(0, weight=0, minsize=SIDEBAR_WIDTH)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        design = self._design = Design(self, motion=self._motion)
        sidebar = NavigationRail(
            self,
            design,
            NAVIGATION_PAGES,
            self._show_page,
            brand_image=self._brand_image,
        )
        self.sidebar = sidebar
        sidebar.grid(row=0, column=0, sticky="nsew")
        self._navigation_buttons = sidebar.buttons

        self._content_area = ctk.CTkFrame(self, corner_radius=0, fg_color=CANVAS)
        self._content_area.grid(row=0, column=1, sticky="nsew")
        self._content_area.grid_columnconfigure(0, weight=1)
        self._content_area.grid_rowconfigure(0, weight=1)
        viewport = ctk.CTkFrame(self._content_area, corner_radius=0, fg_color=CANVAS)
        viewport.grid(row=0, column=0, sticky="nsew")
        page_host = ctk.CTkFrame(viewport, corner_radius=0, fg_color=CANVAS)
        page_host.place(x=0, y=0, relwidth=1, relheight=1)
        page_host.grid_columnconfigure(0, weight=1)
        page_host.grid_rowconfigure(0, weight=1)
        # A página em preparação não deve redimensionar a superfície visível.
        page_host.grid_propagate(False)
        self._page_host = page_host
        self._presentation = PagePresentation(
            self,
            getattr(sidebar, "brand_symbol", None),
            self._brand_image,
            self._motion,
        )
        self._notifications = NotificationCenter(
            self._content_area,
            design,
        )
        self._close_feedback = design.label(
            self._content_area,
            "",
            color=TEXT,
            font=design.small,
            fg_color=SURFACE,
            corner_radius=12,
            padx=14,
            pady=8,
            wraplength=345,
        )

        home_page = HomePage(
            page_host,
            design,
            open_module=self._show_page,
            analyze_link=self._analyze_home_link,
            choose_format=self._select_home_format,
        )
        tools_page = ToolsPage(
            page_host,
            design,
            open_pdf=self._open_catalog_pdf,
            open_module=self._show_page,
        )
        download_actions = DownloadsPageActions(
            on_link_enter=self._on_link_enter,
            paste_link=self._paste_link,
            clear_link=self._clear_link,
            adapt_quality=self._adapt_quality_controls,
            change_quality=self._on_quality_change,
            start_download=self._download,
            cancel_download=self._cancel_download,
            open_downloads=self._open_downloads,
            choose_destination=self._choose_download_destination,
            open_result_file=self._open_last_download_file,
            open_result_folder=self._open_last_download_folder,
            cancel_item=self._cancel_queue_item,
            remove_item=self._remove_queue_item,
            open_item_file=lambda item_id: self._open_queue_result(
                item_id, folder=False
            ),
            open_item_folder=lambda item_id: self._open_queue_result(
                item_id, folder=True
            ),
            retry_queue=self._retry_download_queue,
            retry_item=self._retry_queue_item,
            review_item=self._review_queue_item,
            recent_result_path=lambda: (
                self._last_download_result.final_output_path
                if self._last_download_result is not None
                else None
            ),
        )
        downloads_page = DownloadsPage(
            page_host,
            design,
            content_type=self.content_type,
            quality=self.quality,
            status=self.status,
            actions=download_actions,
        )
        pdf_page = PdfToolsPage(
            page_host,
            design=design,
            dialog_preferences=self.dialog_preferences,
            service=PdfToolsService(),
            preferences=self.settings.get("pdf_preferences"),
            persist_preferences=self._persist_pdf_preferences,
            actions=PdfPageActions(
                show_info=self._show_info,
                show_warning=self._show_warning,
                show_error=self._show_error,
                confirm_overwrite=self._ask_confirmation,
                notify=self._notify,
                open_result_file=open_pdf_result_file,
                open_result_folder=open_pdf_result_folder,
            ),
        )
        documents_component_service = DocumentsComponentService()
        documents_page = DocumentsPage(
            page_host,
            design=design,
            dialog_preferences=self.dialog_preferences,
            component_service=documents_component_service,
            conversion_service=DocumentsConversionService(
                component_service=documents_component_service
            ),
            component_resolver=lambda: detected_component_path(
                self.settings,
                self.download_service.base_dir,
                documents_component_service,
            ),
            actions=DocumentsPageActions(
                show_info=self._show_info,
                show_warning=self._show_warning,
                show_error=self._show_error,
                confirm_overwrite=self._ask_confirmation,
                notify=self._notify,
                persist_component_path=self._persist_documents_component_path,
                open_result_file=self._open_documents_result_file,
                open_result_folder=self._open_documents_result_folder,
                start_component_install=self._start_documents_component_install,
            ),
        )
        media_page = MediaToolsPage(
            page_host,
            design=design,
            back_to_tools=lambda: self._show_page(PAGE_TOOLS),
            dialog_preferences=self.dialog_preferences,
            service=MediaToolsService(),
            actions=MediaPageActions(
                show_info=self._show_info,
                show_warning=self._show_warning,
                show_error=self._show_error,
                confirm_overwrite=self._ask_confirmation,
                notify=self._notify,
                open_result_file=self._open_documents_result_file,
                open_result_folder=self._open_documents_result_folder,
            ),
        )
        files_page = FilesPage(
            page_host,
            design=design,
            preview_service=FilePreviewService(
                media_dir=self.download_service.base_dir,
                document_component=lambda: detected_component_path(
                    dict(self.settings),
                    self.download_service.base_dir,
                    documents_component_service,
                ),
            ),
            actions=FilesPageActions(
                show_warning=self._show_warning,
                show_error=self._show_error,
                extract_pages=self._route_file_to_extract_pages,
                pdf_to_images=self._route_file_to_pdf_images,
                pdf_to_docx=self._route_file_to_pdf_word,
                image_to_pdf=self._route_file_to_image_pdf,
                video_to_mp3=self._route_file_to_video_mp3,
                create_poster=self._route_file_to_poster,
                docx_to_pdf=self._route_file_to_docx_pdf,
                odt_to_pdf=self._route_file_to_odt_pdf,
                txt_to_pdf=self._route_file_to_txt_pdf,
            ),
        )
        from component_updates import ComponentUpdateService

        managed_updater = ComponentUpdateService(self.download_service.base_dir)
        settings_page = SettingsPage(
            page_host,
            theme_value=("Escuro" if self.settings["tema"] == THEME_DARK else "Claro"),
            change_theme=self._change_theme,
            notify=self._notify,
            design=design,
            text_scale=self.settings.get("text_scale", DEFAULT_TEXT_SCALE),
            change_text_scale=self._change_text_scale,
            choose_download_folder=self._choose_download_destination,
            component_manager=ComponentManager(
                base_dir=self.download_service.base_dir,
                documents_service=documents_component_service,
                documents_path=lambda: detected_component_path(
                    self.settings,
                    self.download_service.base_dir,
                    documents_component_service,
                ),
                documents_managed=lambda: (
                    self.settings.get("documents_component_origin") == "MANAGED"
                ),
            ),
            component_updater=YtDlpUpdateService(
                self.download_service.base_dir,
                usage_gate=self.download_service,
                approval=managed_updater.approve_yt_dlp,
                notices_provider=managed_updater.yt_dlp_notices,
            ),
            component_release_observer=ComponentReleaseObserver(),
            managed_updater=managed_updater,
            confirm_component_update=self._ask_confirmation,
            component_installer=LibreOfficeAcquisitionService(
                self.download_service.base_dir,
                component_service=documents_component_service,
                user_data=True,
            ),
            confirm_component_install=self._ask_confirmation,
            activate_managed_component=self._activate_managed_documents_component,
            select_existing_component=self._select_existing_documents_component,
        )
        self._pages = {
            PAGE_HOME: home_page,
            PAGE_DOWNLOADS: downloads_page,
            PAGE_FILES: files_page,
            PAGE_TOOLS: tools_page,
            PAGE_PDF: pdf_page,
            PAGE_DOCUMENTS: documents_page,
            PAGE_MEDIA: media_page,
            PAGE_SETTINGS: settings_page,
        }
        # As páginas são persistentes, mas só a ativa é gerenciada pelo grid.
        # CTkScrollableFrame inclui um frame externo, canvas e scrollbar:
        # cobrir uma página com lift não equivale a ocultar essa árvore.

        self.downloads_page = downloads_page
        self.home_page = home_page
        self.files_page = files_page
        self.pdf_page = pdf_page
        self.documents_page = documents_page
        self.media_page = media_page
        self.settings_page = settings_page
        self.link_entry = downloads_page.link_entry
        self.paste_button = downloads_page.paste_button
        self.clear_button = downloads_page.clear_button
        self.content_type_buttons = downloads_page.content_type_buttons
        self.quality_label = downloads_page.quality_label
        self.quality_menu = downloads_page.quality_menu
        self.quality_hint = downloads_page.quality_hint
        self.download_button = downloads_page.download_button
        self.cancel_button = downloads_page.cancel_button
        self.open_downloads_button = downloads_page.open_downloads_button
        self.change_destination_button = downloads_page.change_destination_button
        self.open_result_file_button = downloads_page.open_result_file_button
        self.open_result_folder_button = downloads_page.open_result_folder_button
        self.progress_bar = downloads_page.progress_bar

    def _route_file_to_extract_pages(self, path: Path) -> bool:
        """Prepara o PDF existente e navega somente após handoff aceito."""
        if getattr(self, "_close_requested", False):
            return False
        if not self.pdf_page.prepare_extract_source(path):
            return False
        self._show_page(PAGE_PDF)
        return True

    def _route_file_to_pdf_word(self, path: Path) -> bool:
        if getattr(self, "_close_requested", False):
            return False
        if not self.pdf_page.prepare_pdf_to_docx_source(path):
            return False
        self._show_page(PAGE_PDF)
        return True

    def _route_file_to_pdf_images(self, path: Path) -> bool:
        """Prepara PDF → Imagens na página persistente existente."""
        if getattr(self, "_close_requested", False):
            return False
        if not self.pdf_page.prepare_pdf_to_images_source(path):
            return False
        self._show_page(PAGE_PDF)
        return True

    def _route_file_to_image_pdf(self, path: Path) -> bool:
        """Acrescenta imagem à lista PDF existente e navega se aceita."""
        if getattr(self, "_close_requested", False):
            return False
        if not self.pdf_page.add_image_to_pdf(path):
            return False
        self._show_page(PAGE_PDF)
        return True

    def _route_file_to_poster(self, path: Path) -> bool:
        """Prepara a imagem no pôster sem iniciar a geração."""
        if getattr(self, "_close_requested", False):
            return False
        if not self.pdf_page.prepare_poster_source(path):
            return False
        self._show_page(PAGE_PDF)
        return True

    def _route_file_to_video_mp3(self, path: Path) -> bool:
        """Prepara a extração de áudio na página persistente existente."""
        if getattr(self, "_close_requested", False):
            return False
        if not self.media_page.prepare_video_to_mp3_source(path):
            return False
        self._show_page(PAGE_MEDIA)
        return True

    def _route_file_to_docx_pdf(self, path: Path) -> bool:
        """Prepara DOCX → PDF na página Documentos sem iniciar a conversão."""
        if getattr(self, "_close_requested", False):
            return False
        if not self.documents_page.prepare_docx_to_pdf(path):
            return False
        self._show_page(PAGE_DOCUMENTS)
        return True

    def _route_file_to_odt_pdf(self, path: Path) -> bool:
        """Prepara ODT → PDF na página Documentos sem iniciar a conversão."""
        if getattr(self, "_close_requested", False):
            return False
        if not self.documents_page.prepare_odt_to_pdf(path):
            return False
        self._show_page(PAGE_DOCUMENTS)
        return True

    def _route_file_to_txt_pdf(self, path: Path) -> bool:
        """Prepara TXT → PDF na página Documentos sem iniciar a conversão."""
        if getattr(self, "_close_requested", False):
            return False
        if not self.documents_page.prepare_txt_to_pdf(path):
            return False
        self._show_page(PAGE_DOCUMENTS)
        return True

    def _open_catalog_pdf(self, tool: str) -> None:
        if self._close_requested:
            return
        if not self.pdf_page.is_busy:
            self.pdf_page.tool_cards[tool].invoke()
        self._show_page(PAGE_PDF)

    def _show_page(self, page_name: str) -> None:
        """Seleciona a página persistente antes de iniciar a apresentação."""
        EduDownloaderApp._swap_page(self, page_name)

    def _swap_page(self, page_name: str) -> None:
        """Confirma apenas o último destino e apresenta sua página persistente."""
        if page_name not in self._pages:
            raise ValueError(f"Página desconhecida: {page_name}")
        if getattr(self, "_close_requested", False):
            return
        self._pending_page = page_name
        if getattr(self, "_navigation_in_progress", False):
            return
        self._navigation_in_progress = True
        try:
            while self._pending_page is not None:
                selected = self._pending_page
                self._pending_page = None
                if selected == self._current_page:
                    continue
                EduDownloaderApp._cancel_page_idle_callbacks(self)
                previous_name = self._current_page
                previous = self._pages.get(previous_name)
                page = self._pages[selected]
                presentation = getattr(self, "_presentation", None)
                stack = getattr(self, "_page_stack", None)
                if previous is not None:
                    if presentation is not None:
                        presentation.before_swap(previous)
                    if stack is None:
                        previous.grid_forget()
                self._current_page = None
                try:
                    while True:
                        page = self._pages[selected]
                        if selected == PAGE_DOCUMENTS:
                            self.documents_page.on_show()
                        requested = self._pending_page
                        self._pending_page = None
                        if requested is None or requested == selected:
                            break
                        selected = requested

                    if stack is None:
                        page.grid(row=0, column=0, sticky="nsew")
                    else:
                        content = getattr(self, "_content_presentation", None)
                        with (
                            content.change(page)
                            if content is not None
                            else nullcontext()
                        ):
                            stack.show(page)
                        self._motion.refresh_activity()
                    EduDownloaderApp._select_navigation_page(self, selected)
                    resize_presentation = getattr(self, "_resize_presentation", None)
                    if resize_presentation is not None:
                        resize_presentation.changed()
                    EduDownloaderApp._focus_active_page(self)
                    if presentation is not None and previous is not None:
                        presentation.present(page)
                        previous_rail = (
                            PAGE_TOOLS
                            if previous_name in _TOOL_PAGES
                            else previous_name
                        )
                        active_rail = (
                            PAGE_TOOLS if selected in _TOOL_PAGES else selected
                        )
                        if active_rail != previous_rail:
                            self._navigation_buttons[active_rail].highlight_selection()
                except Exception:
                    if stack is not None and previous is not None:
                        stack.show(previous)
                        self._motion.refresh_activity()
                    else:
                        page.grid_forget()
                        if previous is not None:
                            previous.grid(row=0, column=0, sticky="nsew")
                    EduDownloaderApp._select_navigation_page(self, previous_name)
                    raise
        finally:
            self._navigation_in_progress = False
            self._pending_page = None

    def _focus_active_page(self) -> None:
        page = self._pages.get(self._current_page)
        if page is not None:
            page.focus_set()
            if self._current_page == PAGE_DOWNLOADS and not self._download_active:
                self.link_entry.focus_set()

    def _select_navigation_page(self, page_name: str | None) -> None:
        """Confirma o destino e aplica somente as cores da seleção final."""
        self._current_page = page_name
        selected = PAGE_TOOLS if page_name in _TOOL_PAGES else page_name
        for name, button in self._navigation_buttons.items():
            _configure_if_changed(
                button,
                fg_color=(
                    _NAVIGATION_SELECTED_COLOR if name == selected else "transparent"
                ),
                text_color=ON_PRIMARY if name == selected else SIDEBAR_TEXT,
                hover_color=PRIMARY_HOVER if name == selected else NAV_HOVER,
            )

    def _focus_previous_navigation_widget(self, event: tk.Event) -> str:
        return self._focus_visible_navigation_widget(event, backwards=True)

    def _focus_visible_navigation_widget(
        self, _event: tk.Event, *, backwards: bool = False
    ) -> str:
        """Tab percorre só sidebar/página ativa, não as camadas encobertas."""
        presentation = getattr(self, "_presentation", None)
        if presentation is not None:
            presentation.cancel_startup()
        candidate = self.focus_get() or self
        hidden = {
            page._parent_frame
            for name, page in self._pages.items()
            if name != self._current_page
        }
        visited: set[str] = set()
        while True:
            candidate = (
                candidate.tk_focusPrev() if backwards else candidate.tk_focusNext()
            )
            if str(candidate) in visited:
                return "break"
            visited.add(str(candidate))
            ancestor = candidate
            while ancestor is not None and ancestor not in hidden:
                ancestor = ancestor.master
            if ancestor is None:
                page = self._pages.get(self._current_page)
                if page is not None:
                    if self._current_page == PAGE_SETTINGS:
                        page.reveal_diagnostics_focus(candidate)
                    # CTkButton.focus_set redireciona ao rótulo interno.
                    tk.Misc.focus_set(candidate)
                    reveal_scrollable_focus(page, candidate)
                else:
                    candidate.focus_set()
                return "break"

    def _paste_link(self) -> None:
        """Substitui o campo pelo texto disponível na área de transferência."""
        try:
            clipboard_text = self.clipboard_get()
        except tk.TclError:
            self._show_warning(
                "A área de transferência não contém texto. Copie um link e tente novamente."
            )
            self._focus_link_entry()
            return
        self.link_entry.delete(0, "end")
        self.link_entry.insert(0, clipboard_text.strip())
        self.link_entry.icursor("end")
        self._focus_link_entry()

    def _clear_link(self) -> None:
        """Limpa o campo de link e restaura o status inicial."""
        self.link_entry.delete(0, "end")
        if (
            not self._download_active
            and self._download_ui_state != DownloadUiState.COMPLETED
        ):
            self._set_download_state(DownloadUiState.READY)
        self._focus_link_entry()

    def _on_link_enter(self, _event: tk.Event[tk.Misc]) -> str:
        """Usa a ação principal somente para Enter recebido pelo campo de link."""
        if self._modal_open or getattr(self, "_close_requested", False):
            return "break"
        self._download()
        return "break"

    def _select_home_format(self, value: str) -> None:
        if not self._close_requested and value != self.content_type.get():
            self.content_type.set(value)
            self._adapt_quality_controls()

    def _analyze_home_link(self) -> None:
        if self._close_requested or self._modal_open:
            return
        url = self.home_page.link_entry.get().strip()
        if not is_valid_url(url):
            self.home_page.show_link_error(
                "Insira um link que comece com http:// ou https://."
            )
            return
        self.home_page.show_link_error("")
        self._review_download_link(url)

    def _review_download_link(self, url: str) -> None:
        self.link_entry.delete(0, "end")
        self.link_entry.insert(0, url)
        self._show_page(PAGE_DOWNLOADS)
        self._focus_link_entry(reveal=True)

    def _download(self) -> None:
        """Captura as opções atuais e adiciona uma solicitação imutável à fila."""
        if getattr(self, "_close_requested", False):
            return

        url = self.link_entry.get().strip()
        if is_empty(url):
            self._show_warning("Cole ou digite um link antes de iniciar o download.")
            self._focus_link_entry()
            return
        if not is_valid_url(url):
            self._show_warning(
                "O link informado não é válido. Verifique se ele começa com http:// ou https://."
            )
            self._focus_link_entry()
            return

        mp3_profile = DEFAULT_MP3_QUALITY
        if self.content_type.get() == CONTENT_TYPE_AUDIO:
            mp3_profile = next(
                (
                    profile
                    for profile in MP3_QUALITY_OPTIONS
                    if profile.display_label == self.mp3_quality.get()
                ),
                None,
            )
            if mp3_profile is None:
                self._show_warning("Selecione uma qualidade MP3 válida.")
                return

        request = DownloadRequest(
            url=url,
            content_type=self.content_type.get(),
            quality=self.quality.get(),
            destination_dir=self._download_destination_dir,
            mp3_quality=mp3_profile,
        )
        try:
            self.download_queue.add(request)
        except DownloadQueueError as error:
            self._show_warning(str(error))
            return
        self.link_entry.delete(0, "end")
        self._focus_link_entry()

    def _cancel_download(self) -> None:
        """Cancela o item ativo exclusivamente pelo coordenador."""
        for item in self.download_queue.items():
            if item.state in {
                QueueState.PREPARING,
                QueueState.DOWNLOADING,
                QueueState.PROCESSING,
                QueueState.VERIFYING,
            }:
                self.download_queue.cancel(item.id)
                return

    def _cancel_queue_item(self, item_id: str) -> None:
        if not self._close_requested:
            try:
                self.download_queue.cancel(item_id)
            except KeyError:
                return

    def _remove_queue_item(self, item_id: str) -> None:
        try:
            self.download_queue.remove(item_id)
        except KeyError:
            return
        except DownloadQueueError:
            self._show_warning("Aguarde a liberação dos recursos deste download.")
        else:
            self.downloads_page.forget_queue_item(item_id)

    def _retry_download_queue(self) -> None:
        if not self._close_requested:
            self.download_queue.retry()

    def _retry_queue_item(self, item_id: str) -> None:
        if self._close_requested:
            return
        try:
            self.download_queue.retry_item(item_id)
        except KeyError:
            return
        except DownloadQueueError as error:
            self._show_warning(str(error))

    def _review_queue_item(self, item_id: str) -> None:
        if self._close_requested or self._modal_open:
            return
        try:
            item = self.download_queue.get(item_id)
        except KeyError:
            return
        if item.state == QueueState.ERROR:
            self._review_download_link(item.request.url)

    def _open_queue_result(self, item_id: str, *, folder: bool) -> None:
        try:
            result = self.download_queue.get(item_id).result
        except KeyError:
            return
        if result is not None:
            self._set_last_download_result(result)
            if folder:
                self._open_last_download_folder()
            else:
                self._open_last_download_file()

    def _poll_download_events(self) -> None:
        """Observa snapshots; somente DownloadQueue consome eventos do serviço."""
        self._queue_poll_after_id = None
        if self._close_finalized:
            return
        items = self.download_queue.items()
        snapshot = (items, self.download_queue.blocked, self._close_requested)
        if snapshot != self._queue_last_snapshot:
            previous = self._queue_last_snapshot
            self._queue_last_snapshot = snapshot
            self.downloads_page.show_queue_items(
                items, blocked=snapshot[1], closing=snapshot[2]
            )
            active = next(
                (
                    item
                    for item in items
                    if item.state
                    in {
                        QueueState.PREPARING,
                        QueueState.DOWNLOADING,
                        QueueState.PROCESSING,
                        QueueState.VERIFYING,
                    }
                ),
                None,
            )
            self._cancel_requested = (
                active.cancel_requested if active is not None else False
            )
            if active is not None:
                self._set_download_state(DownloadUiState(active.state.value))
                if (
                    active.progress is not None
                    and active.state == QueueState.DOWNLOADING
                ):
                    self._show_progress(active.progress)
                if active.cancel_requested:
                    self.status.set("Cancelando...")
                    _configure_if_changed(self.cancel_button, state="disabled")
            else:
                self._set_download_state(DownloadUiState.READY)
                waiting = sum(item.state == QueueState.WAITING for item in items)
                self.status.set(
                    f"Fila: {waiting} aguardando • {len(items) - waiting} finalizados"
                )
            results = [item.result for item in items if item.result is not None]
            self._set_last_download_result(results[-1] if results else None)
            if (
                getattr(self, "_notifications", None) is not None
                and not self._close_requested
            ):
                self._notify_download_terminals(previous[0] if previous else (), items)
        self._queue_poll_after_id = self.after(
            _DOWNLOAD_EVENT_POLL_DELAY_MS, self._poll_download_events
        )

    def _notify_download_terminals(self, previous, items) -> None:
        states = {item.id: item.state for item in previous}
        for item in items:
            if states.get(item.id) == item.state:
                continue
            if item.state == QueueState.COMPLETED and isinstance(
                item.result, DownloadResult
            ):
                if item.result.already_existed:
                    self._notify("info", "O arquivo já está na pasta de destino.")
                else:
                    self._notify("success", "Download concluído com sucesso.")
            elif item.state == QueueState.ERROR:
                self._notify(
                    "error", "Não foi possível concluir o download. Confira a fila."
                )

    def _handle_download_event(self, event: DownloadEvent) -> None:
        """Atualiza widgets somente na thread principal do Tkinter."""
        if not self._download_active:
            return
        if self._cancel_requested and event.kind in {
            DownloadEventKind.PHASE,
            DownloadEventKind.PROGRESS,
        }:
            return
        if event.kind == DownloadEventKind.PHASE and isinstance(
            event.payload, DownloadPhase
        ):
            self._show_download_phase(event.payload)
            return
        if event.kind == DownloadEventKind.PROGRESS and isinstance(
            event.payload, DownloadProgress
        ):
            self._show_progress(event.payload)
            return
        if event.kind == DownloadEventKind.COMPLETED:
            self._finish_download_success(event.payload)
            return
        if event.kind == DownloadEventKind.CANCELLED:
            self._finish_download_cancelled()
            return
        if event.kind == DownloadEventKind.ERROR:
            self._finish_download_error(event.payload)

    def _show_progress(self, progress: DownloadProgress) -> None:
        """Apresenta somente medições reais recebidas do yt-dlp."""
        self._set_download_state(DownloadUiState.DOWNLOADING)
        if progress.percent is not None and progress.percent < 100:
            formatted_percent = f"{progress.percent:.1f}".rstrip("0").rstrip(".")
            self.percentage.set(f"{formatted_percent}%")
            self.progress_bar.set(progress.percent / 100)
        else:
            self.percentage.set("—")
            self.progress_bar.set(0)
        self.download_details.set(format_progress_details(progress))

    def _show_download_phase(self, phase: DownloadPhase) -> None:
        """Traduz uma fase interna válida para o estado visual correspondente."""
        if phase in {DownloadPhase.PROCESSING, DownloadPhase.VERIFYING}:
            self._set_download_state(DownloadUiState(phase.value))
        elif phase == DownloadPhase.DOWNLOADING and self._download_ui_state in {
            DownloadUiState.PREPARING,
            DownloadUiState.DOWNLOADING,
        }:
            self._set_download_state(DownloadUiState.DOWNLOADING)
        elif (
            phase == DownloadPhase.PREPARING
            and self._download_ui_state == DownloadUiState.PREPARING
        ):
            self._set_download_state(DownloadUiState.PREPARING)

    def _finish_download_success(self, payload: object) -> None:
        """Restaura controles e informa a conclusão real da operação."""
        if not isinstance(payload, DownloadResult):
            self._finish_download_error(
                DownloadServiceError(
                    "O resultado do download não pôde ser confirmado. Consulte o arquivo de log."
                )
            )
            return

        self._set_last_download_result(payload)
        self._cancel_requested = False
        self._set_download_state(DownloadUiState.COMPLETED)
        self.download_details.set(f"Arquivo: {payload.file_path.name}")
        if payload.already_existed:
            self.progress_bar.set(0)
            self.percentage.set("—")
            self.status.set("Arquivo já existente")
            if not getattr(self, "_close_requested", False):
                self._show_info(
                    f'O arquivo "{payload.file_path.name}" já está na pasta de destino.',
                )
                self._focus_link_entry()
            return

        self.progress_bar.set(1)
        self.percentage.set("100%")
        if not getattr(self, "_close_requested", False):
            self._show_info(f'Download concluído: "{payload.file_path.name}".')
            self._focus_link_entry()

    def _finish_download_cancelled(self) -> None:
        """Limpa o progresso e comunica um cancelamento confirmado."""
        self._set_last_download_result(None)
        self._cancel_requested = False
        self._set_download_state(DownloadUiState.CANCELLED)
        if not getattr(self, "_close_requested", False):
            self._show_info("O download foi cancelado.")
            self._focus_link_entry()

    def _finish_download_error(self, payload: object) -> None:
        """Exibe uma mensagem amigável e mantém detalhes somente no log."""
        self._set_last_download_result(None)
        self._cancel_requested = False
        self._set_download_state(DownloadUiState.ERROR)
        if isinstance(payload, DownloadServiceError):
            message = payload.user_message
        else:
            message = (
                "Não foi possível concluir o download. Verifique sua conexão e "
                "se o conteúdo está disponível."
            )
        if not getattr(self, "_close_requested", False):
            self._show_error(message)
            self._focus_link_entry()

    @property
    def _download_active(self) -> bool:
        """Deriva atividade exclusivamente do estado visual tipado."""
        return self._download_ui_state in _ACTIVE_DOWNLOAD_STATES

    def _set_download_state(self, state: DownloadUiState) -> None:
        """Aplica de forma centralizada texto, métricas, controles e ações."""
        if not isinstance(state, DownloadUiState):
            raise TypeError("state must be a DownloadUiState")
        self._download_ui_state = state
        text = _DOWNLOAD_STATE_TEXT[state]
        if self.status.get() != text:
            self.status.set(text)
        if state in _STATES_WITHOUT_PROGRESS_METRICS:
            self.percentage.set("—")
            self.download_details.set("")
            self.progress_bar.set(0)
        self._set_download_controls()

    def _set_download_controls(self) -> None:
        """Deriva todos os controles do estado tipado e do fechamento."""
        active = self._download_active
        closing = getattr(self, "_close_requested", False)
        unavailable = closing
        interaction_state = "disabled" if unavailable else "normal"
        _configure_if_changed(self.link_entry, state=interaction_state)
        _configure_if_changed(self.paste_button, state=interaction_state)
        _configure_if_changed(self.clear_button, state=interaction_state)
        _configure_if_changed(self.change_destination_button, state=interaction_state)
        for button in self.content_type_buttons:
            _configure_if_changed(button, state=interaction_state)

        quality_state = "disabled" if unavailable else "normal"
        _configure_if_changed(self.quality_menu, state=quality_state)
        _configure_if_changed(
            self.download_button,
            state="disabled" if unavailable else "normal",
            text="Adicionar à fila",
        )
        _configure_if_changed(
            self.cancel_button,
            state="normal"
            if active and not closing and not self._cancel_requested
            else "disabled",
        )
        result_actions_enabled = (
            isinstance(self._last_download_result, DownloadResult) and not closing
        )
        self.downloads_page.set_result_actions_enabled(result_actions_enabled)

    def _focus_link_entry(self, *, reveal: bool = False) -> None:
        """Agenda o foco depois que o Tkinter concluir a atualização atual."""
        if (
            getattr(self, "_close_requested", False)
            or self._current_page != PAGE_DOWNLOADS
        ):
            return
        previous = getattr(self, "_focus_link_after_id", None)
        if previous is not None:
            self.after_cancel(previous)

        def focus():
            self._focus_link_after_id = None
            if (
                not self._close_requested
                and self._current_page == PAGE_DOWNLOADS
                and self.link_entry.winfo_exists()
            ):
                self.link_entry.focus_set()
                if reveal:
                    self.downloads_page.reveal_keyboard_focus(self.link_entry)

        self._focus_link_after_id = self.after_idle(focus)

    def _cancel_page_idle_callbacks(self) -> None:
        """Cancela apenas foco/rolagem de apresentação, nunca polls funcionais."""
        for attribute in ("_focus_link_after_id", "_settings_scroll_after_id"):
            after_id = getattr(self, attribute, None)
            setattr(self, attribute, None)
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass

    def _open_downloads(self) -> None:
        """Solicita a criação e abertura da pasta portátil de downloads."""
        try:
            open_downloads_dir()
        except OSError:
            self._show_error(
                "Não foi possível abrir a pasta Downloads. Verifique se a pasta do aplicativo está acessível."
            )

    def _set_last_download_result(self, result: DownloadResult | None) -> None:
        """Mantém somente o último resultado confirmado durante a sessão atual."""
        self._last_download_result = result
        home_page = getattr(self, "home_page", None)
        if home_page is not None:
            home_page.show_recent(result.final_output_path.name if result else None)
        self._set_download_controls()

    def _open_last_download_file(self) -> None:
        """Abre manualmente o arquivo confirmado, se ele ainda estiver disponível."""
        result = self._last_download_result
        if result is None:
            return
        output_path = result.final_output_path
        if not output_path.is_file():
            self._set_last_download_result(None)
            self._show_warning("O arquivo concluído não está mais disponível.")
            return
        try:
            os.startfile(output_path)
        except OSError:
            self._show_error("Não foi possível abrir o arquivo concluído.")

    def _open_last_download_folder(self) -> None:
        """Abre manualmente a pasta do resultado confirmado, sem selecionar o arquivo."""
        result = self._last_download_result
        if result is None:
            return
        output_path = result.final_output_path
        output_directory = output_path.parent
        if not output_path.is_file() or not output_directory.is_dir():
            self._set_last_download_result(None)
            self._show_warning("A pasta do arquivo concluído não está mais disponível.")
            return
        try:
            os.startfile(output_directory)
        except OSError:
            self._show_error("Não foi possível abrir a pasta do arquivo concluído.")

    def _persist_documents_component_path(self, path: Path | None) -> bool:
        """Persiste somente a localização opcional escolhida pelo usuário."""

        previous = self.settings.get("documents_component_path")
        previous_origin = self.settings.pop("documents_component_origin", None)
        self.settings["documents_component_path"] = str(path) if path else None
        if self._save_preferences():
            return True
        self.settings["documents_component_path"] = previous
        if previous_origin is not None:
            self.settings["documents_component_origin"] = previous_origin
        return False

    def _start_documents_component_install(self) -> None:
        """Leva o usuário ao progresso compartilhado sem iniciar ao abrir a página."""

        self._show_page(PAGE_SETTINGS)
        self.settings_page.set_diagnostics_open(True)
        previous = getattr(self, "_settings_scroll_after_id", None)
        if previous is not None:
            self.after_cancel(previous)

        def scroll():
            self._settings_scroll_after_id = None
            if (
                not self._close_requested
                and self._current_page == PAGE_SETTINGS
                and self.settings_page.winfo_exists()
            ):
                self.settings_page._parent_canvas.yview_moveto(1.0)

        self._settings_scroll_after_id = self.after_idle(scroll)
        self.settings_page.start_libreoffice_install()

    def _select_existing_documents_component(self) -> None:
        """Reutiliza a seleção manual existente, sem busca global."""

        self._show_page(PAGE_DOCUMENTS)
        self.documents_page._choose_component()

    def _activate_managed_documents_component(self, root: Path) -> bool:
        """Usa o ponteiro já validado/persistido pelo setup fora do app root."""

        # A authority já foi persistida no data root do usuário pelo serviço.
        # Não exigir escrita no diretório portátil para habilitar documentos.
        self.settings["documents_component_origin"] = "MANAGED"
        if not getattr(self, "_close_requested", False):
            self.documents_page.use_managed_component(root)
        return True

    def _open_documents_result_file(self, output_path: Path) -> bool:
        """Abre o resultado pela associação padrão do Windows, sem escolher um app."""

        if not output_path.is_file():
            self._show_warning("O arquivo convertido não está mais disponível.")
            return False
        try:
            os.startfile(output_path)
        except OSError:
            self._show_error("Não foi possível abrir o arquivo convertido.")
            return False
        return True

    def _open_documents_result_folder(self, output_path: Path) -> bool:
        """Abre a pasta do PDF confirmado sem expor comandos ao shell."""

        output_directory = output_path.parent
        if not output_path.is_file() or not output_directory.is_dir():
            self._show_warning(
                "A pasta do arquivo convertido não está mais disponível."
            )
            return False
        try:
            os.startfile(output_directory)
        except OSError:
            self._show_error("Não foi possível abrir a pasta do arquivo convertido.")
            return False
        return True

    def _choose_download_destination(self) -> None:
        """Lembra somente a pasta escolhida; nunca cria ou abre o destino."""
        if self._modal_open or getattr(self, "_close_requested", False):
            return

        initial_directory = self._download_destination_dir
        if initial_directory is None or not initial_directory.is_dir():
            try:
                default_directory = get_downloads_dir(self.download_service.base_dir)
                initial_directory = (
                    default_directory
                    if default_directory.is_dir()
                    else self.download_service.base_dir
                )
            except OSError:
                initial_directory = self.download_service.base_dir

        self._modal_open = True
        try:
            selected = filedialog.askdirectory(
                title="Escolha a pasta para os downloads",
                parent=self,
                initialdir=str(initial_directory),
                mustexist=True,
            )
        finally:
            self._modal_open = False

        if not selected:
            return
        destination = Path(selected)
        try:
            available = (
                favorite_folder_comparison_key(destination) and destination.is_dir()
            )
        except OSError:
            available = False
        if not available:
            self._show_warning(
                "A pasta selecionada não está disponível. Escolha outra pasta."
            )
            return
        self._download_destination_dir = destination
        self.dialog_preferences.remember("downloads.output", destination)
        self.downloads_page.show_download_destination(destination)
        EduDownloaderApp._show_settings_download_destination(self)

    def _show_settings_download_destination(self) -> None:
        page = getattr(self, "settings_page", None)
        if page is None:
            return
        selected = self._download_destination_dir
        try:
            path = selected or get_downloads_dir(self.download_service.base_dir)
        except OSError:
            path = None
        page.show_download_destination(path, default=selected is None)

    def _persist_dialog_folders(self, folders: dict[str, str]) -> None:
        previous = self.settings.get("dialog_folders", {})
        download_changed = previous.get("downloads.output") != folders.get(
            "downloads.output"
        )
        self.settings["dialog_folders"] = folders
        if download_changed and self._current_page == PAGE_SETTINGS:
            self._save_preferences(
                from_settings=True,
                failure_message="A pasta vale nesta sessão, mas a preferência não foi salva.",
            )
        else:
            self._save_preferences()

    def _persist_pdf_preferences(self, values):
        self.settings["pdf_preferences"] = values
        return self._save_preferences()

    def _adapt_quality_controls(self, save: bool = True) -> None:
        """Apresenta somente os perfis pertinentes ao tipo selecionado."""
        is_audio = self.content_type.get() == CONTENT_TYPE_AUDIO
        for page_name in ("home_page", "downloads_page"):
            page = getattr(self, page_name, None)
            if page is not None:
                page.show_format(self.content_type.get())
        self.quality_menu.configure(
            values=(
                [profile.display_label for profile in MP3_QUALITY_OPTIONS]
                if is_audio
                else list(VIDEO_QUALITIES)
            ),
            variable=self.mp3_quality if is_audio else self.quality,
            state=(
                "disabled" if getattr(self, "_close_requested", False) else "normal"
            ),
        )
        if is_audio:
            self.quality_label.configure(text="Qualidade do MP3")
            self.quality_hint.configure(text="Taxa de bits do áudio.")
        else:
            self.quality_label.configure(text="Qualidade de vídeo")
            self.quality_hint.configure(text="Resolução máxima do vídeo.")
        if save:
            self._save_preferences()

    def _on_quality_change(self, _selected_value: str) -> None:
        """Persiste somente a qualidade de vídeo, nunca o perfil MP3."""
        if self.content_type.get() != CONTENT_TYPE_AUDIO:
            self._save_preferences()

    def _change_theme(self, selected_theme: str) -> None:
        """Propaga as cores mantendo a página ativa e seu estado."""
        theme = THEME_DARK if selected_theme == "Escuro" else THEME_LIGHT
        if getattr(self, "_close_requested", False) or theme == self.settings["tema"]:
            return
        presentation = getattr(self, "_presentation", None)
        if presentation is not None:
            presentation.settle()
        dark = theme == THEME_DARK
        content = getattr(self, "_content_presentation", None)
        with (
            content.change(self._page_stack.current, dark=dark)
            if content is not None
            else nullcontext()
        ):
            self.settings["tema"] = theme
            ctk.set_appearance_mode("Dark" if dark else "Light")
            cover = getattr(self, "_resize_presentation", None)
            if cover is not None:
                cover.refresh_theme()
            files = getattr(self, "files_page", None)
            if files is not None:
                files.apply_theme(selected_theme)
        self._save_preferences(from_settings=True)

    def _change_text_scale(self, scale: int) -> None:
        previous = self.settings.get("text_scale", DEFAULT_TEXT_SCALE)
        if (
            self._close_requested
            or type(scale) is not int
            or scale not in TEXT_SCALE_LEVELS
            or scale == previous
        ):
            return
        self._presentation.settle()
        cover = self._resize_presentation
        try:
            if cover is not None:
                cover.begin_layout()
            self._design.set_text_scale(scale)
            self.files_page.apply_theme()
            self.files_page._schedule_file_columns()
            self.settings_page.show_text_scale(scale)
        except Exception:
            try:
                self._design.set_text_scale(previous)
                self.settings_page.show_text_scale(previous)
            except (tk.TclError, RuntimeError):
                pass
            finally:
                if cover is not None:
                    cover.dismiss()
            raise
        else:
            if cover is not None:
                cover.finish_layout()
        self.settings["text_scale"] = scale
        self._save_preferences(
            from_settings=True,
            failure_message="O tamanho do texto foi aplicado, mas a preferência não foi salva.",
        )

    def _sync_window_motion(self, event: tk.Event) -> None:
        if event.widget is self and not self._close_requested:
            self._motion.configure(self._motion.preference)
            if self._motion.system_reduced:
                self._presentation.cancel_startup()
            if event.type == tk.EventType.Map:
                self._presentation.on_map()

    def _window_motion_hidden(self, event: tk.Event) -> None:
        if event.widget is self and not self._close_finalized:
            self._notifications.clear()
            self._presentation.settle()

    def _resize_window_motion(self, event: tk.Event) -> None:
        if event.widget is self:
            self._presentation.on_resize()

    def _skip_startup(self, _event: tk.Event) -> None:
        self._presentation.cancel_startup()

    def _forget_motion_widget(self, event: tk.Event) -> None:
        if event.widget is self:
            self._motion.close()
        else:
            self._motion.forget_widget(event.widget)

    def _save_preferences(
        self, *, from_settings: bool = False, failure_message: str | None = None
    ) -> bool:
        """Atualiza somente preferências locais reconhecidas no arquivo JSON."""
        self.settings["ultimo_tipo"] = self.content_type.get()
        self.settings["ultima_qualidade"] = self.quality.get()
        try:
            self.settings = save_settings(self.settings)
        except OSError:
            if from_settings:
                self.settings_page.show_persistence_error(
                    failure_message
                    or "O tema foi aplicado, mas não foi possível salvar a preferência "
                    "para o próximo início."
                )
            else:
                self.status.set(
                    "As preferências não foram salvas; verifique a permissão da pasta."
                )
            return False
        if from_settings:
            self.settings_page.clear_persistence_feedback()
        return True

    def _show_dialog(
        self,
        dialog: Callable[..., object],
        message: str,
        title: str = APP_NAME,
    ) -> object | None:
        """Abre uma única janela modal e registra esse estado para os atalhos."""
        if self._modal_open:
            return None
        presentation = getattr(self, "_presentation", None)
        if presentation is not None:
            presentation.cancel_startup()
        self._modal_open = True
        try:
            return dialog(title, message, parent=self)
        finally:
            self._modal_open = False

    def _show_info(self, message: str) -> None:
        """Exibe uma informação padronizada."""
        self._show_dialog(messagebox.showinfo, message)

    def _show_warning(self, message: str) -> None:
        """Exibe um aviso padronizado."""
        self._show_dialog(messagebox.showwarning, message)

    def _show_error(self, message: str) -> None:
        """Exibe um erro sem detalhes técnicos."""
        self._show_dialog(messagebox.showerror, message)
        self._notify("error", "Não foi possível concluir a ação.")

    def _notify(self, kind: str, message: str) -> None:
        center = getattr(self, "_notifications", None)
        if center is not None and not self._close_requested and self.winfo_viewable():
            center.post(kind, message)

    def _ask_confirmation(self, message: str) -> bool:
        """Solicita confirmação usando o mesmo controle de janela modal."""
        return bool(self._show_dialog(messagebox.askyesno, message))

    @staticmethod
    def _close_confirmation_message(
        *,
        pdf_active: bool,
        documents_active: bool = False,
        media_active: bool,
        download_active: bool,
        component_active: bool = False,
    ) -> str:
        actions: list[str] = []
        if download_active:
            actions.append("O download será cancelado.")
        if media_active:
            actions.append("A conversão de mídia será cancelada.")
        if documents_active:
            actions.append("A conversão de documento será cancelada.")
        if pdf_active:
            actions.append("A operação PDF terminará antes do fechamento.")
        if component_active:
            actions.append("A atualização do componente será cancelada ou aguardada.")
        return (
            "Há operações em andamento.\n\n"
            f"{' '.join(actions)}\n\n"
            "Deseja fechar o EduDownloader?"
        )

    def _request_close(self) -> None:
        """Confirma uma vez e inicia o fechamento coordenado não bloqueante."""

        if self._close_finalized:
            return
        if self._close_requested:
            if self._queue_shutdown_started:
                self.download_queue.shutdown(timeout=0)
            return
        content = getattr(self, "_content_presentation", None)
        if content is not None:
            content.dismiss()
        resize_presentation = getattr(self, "_resize_presentation", None)
        if resize_presentation is not None:
            resize_presentation.dismiss()
        pdf_active = self.pdf_page.is_busy
        documents_page = getattr(self, "documents_page", None)
        documents_active = bool(documents_page is not None and documents_page.is_busy)
        media_active = self.media_page.is_busy
        download_active = any(
            item.state
            in {
                QueueState.WAITING,
                QueueState.PREPARING,
                QueueState.DOWNLOADING,
                QueueState.PROCESSING,
                QueueState.VERIFYING,
            }
            for item in self.download_queue.items()
        )
        component_active = self.settings_page.is_component_operation_active
        if (
            pdf_active
            or documents_active
            or media_active
            or download_active
            or component_active
        ):
            message = EduDownloaderApp._close_confirmation_message(
                pdf_active=pdf_active,
                documents_active=documents_active,
                media_active=media_active,
                download_active=download_active,
                component_active=component_active,
            )
            if not self._ask_confirmation(message):
                return

        self._close_requested = True
        notifications = getattr(self, "_notifications", None)
        if notifications is not None:
            notifications.clear()
        presentation = getattr(self, "_presentation", None)
        if presentation is not None:
            presentation.settle()
        EduDownloaderApp._cancel_page_idle_callbacks(self)
        if media_active:
            EduDownloaderApp._show_close_feedback(
                self,
                "Cancelando a conversão de mídia e aguardando as operações restantes...",
            )
        elif pdf_active or documents_active or download_active or component_active:
            EduDownloaderApp._show_close_feedback(
                self, "Aguardando as operações terminarem com segurança..."
            )
        self.pdf_page.begin_shutdown()
        if documents_page is not None:
            documents_page.begin_shutdown()
        self.media_page.begin_shutdown()
        self.settings_page.begin_shutdown()
        for item in self.download_queue.items():
            self.download_queue.cancel(item.id)
        self._set_download_controls()
        EduDownloaderApp._poll_close_readiness(self)

    def _show_close_feedback(self, message: str) -> None:
        self.status.set(message)
        feedback = getattr(self, "_close_feedback", None)
        if feedback is not None:
            _configure_if_changed(feedback, text=message)
            if not feedback.place_info():
                feedback.place(relx=1, rely=1, x=-24, y=-24, anchor="se")

    def _schedule_close_poll(self) -> None:
        if self._close_poll_after_id is None and self._close_requested:
            self._close_poll_after_id = self.after(
                80,
                lambda: EduDownloaderApp._poll_close_readiness(self),
            )

    def _poll_close_readiness(self) -> None:
        """Finaliza somente quando páginas e serviço confirmarem estado seguro."""

        self._close_poll_after_id = None
        if self._close_finalized or not self._close_requested:
            return
        media_error = self.media_page.shutdown_error
        if media_error is not None:
            EduDownloaderApp._abort_close_after_media_failure(self, media_error)
            return
        if (
            self.pdf_page.is_shutdown_ready
            and (
                getattr(self, "documents_page", None) is None
                or self.documents_page.is_shutdown_ready
            )
            and self.media_page.is_shutdown_ready
            and self.settings_page.is_shutdown_ready
        ):
            if not self._queue_shutdown_started:
                self._queue_shutdown_started = True
                self.download_queue.shutdown(timeout=0)
            if self.download_queue.is_closed:
                EduDownloaderApp._finalize_close(self)
                return
            if self.download_queue.control_error:
                EduDownloaderApp._show_close_feedback(
                    self, self.download_queue.control_error + " Tente fechar novamente."
                )
        EduDownloaderApp._schedule_close_poll(self)

    def _abort_close_after_media_failure(self, message: str) -> None:
        """Mantém a janela viva e restaura uma nova tentativa consciente."""

        self._close_requested = False
        feedback = getattr(self, "_close_feedback", None)
        if feedback is not None:
            feedback.place_forget()
        stack = getattr(self, "_page_stack", None)
        if stack is not None:
            stack.start()
        self.pdf_page.cancel_shutdown()
        documents_page = getattr(self, "documents_page", None)
        if documents_page is not None:
            documents_page.cancel_shutdown()
        self.media_page.cancel_shutdown()
        settings_page = getattr(self, "settings_page", None)
        if settings_page is not None:
            settings_page.cancel_shutdown()
        self._set_download_controls()
        self.status.set(message)
        self._show_error(message)

    def _finalize_close(self) -> None:
        """Executa uma única vez o teardown depois da confirmação de segurança."""

        if self._close_finalized or not self.download_queue.is_closed:
            return
        self._close_finalized = True
        self._close_requested = True
        # Após a confirmação de todas as operações, o Tk pode desmontar a
        # hierarquia sem expor as páginas que estavam atrás da página ativa.
        self.withdraw()
        after_id = self._close_poll_after_id
        self._close_poll_after_id = None
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
        self.files_page.close()
        self.pdf_page.close()
        documents_page = getattr(self, "documents_page", None)
        if documents_page is not None:
            documents_page.close()
        self.media_page.close()
        after_id = self._queue_poll_after_id
        self._queue_poll_after_id = None
        if after_id is not None:
            self.after_cancel(after_id)
        self.downloads_page.close_queue_view()
        self._save_preferences()
        self.destroy()

    def _on_close(self) -> None:
        """Mantém o callback histórico como porta para o fluxo coordenado."""

        EduDownloaderApp._request_close(self)

    def close(self) -> None:
        """Run the existing application cleanup through a public lifecycle port."""

        EduDownloaderApp._request_close(self)

    def destroy(self) -> None:
        if getattr(self, "_content_presentation", None) is not None:
            self._content_presentation.close()
        if getattr(self, "_resize_presentation", None) is not None:
            self._resize_presentation.close()
        if self._initial_map_after_id is not None:
            self.after_cancel(self._initial_map_after_id)
            self._initial_map_after_id = None
        if hasattr(self, "_notifications"):
            self._notifications.clear()
        if hasattr(self, "_presentation"):
            self._presentation.settle()
        self._motion.close()
        self.unbind("<Destroy>", self._motion_destroy_binding)
        super().destroy()
