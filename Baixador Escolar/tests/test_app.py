"""Testes da interação e do shell modular da interface."""

import json
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import tkinter as tk
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import app
from app import (
    DownloadUiState,
    NAVIGATION_PAGES,
    PAGE_DOWNLOADS,
    PAGE_FILES,
    PAGE_HOME,
    PAGE_DOCUMENTS,
    PAGE_MEDIA,
    PAGE_PDF,
    PAGE_SETTINGS,
    PAGE_TOOLS,
    EduDownloaderApp,
    format_progress_details,
)
from constants import APP_VERSION, CONTENT_TYPE_AUDIO, CONTENT_TYPE_VIDEO, THEME_DARK
from downloader import (
    DownloadEvent,
    DownloadEventKind,
    DownloadPhase,
    DownloadProgress,
    DownloadRequest,
    DownloadResult,
    DownloadServiceError,
)
from mp3_quality import DEFAULT_MP3_QUALITY, MP3_QUALITY_OPTIONS, Mp3Quality
from download_queue import QueueItem, QueueState
from ui_pages import DownloadsPage


class FakeVariable:
    """Substitui StringVar nos testes que não podem criar uma janela Tk."""

    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class DownloadUiDouble:
    """Executa a máquina de estados sem depender de uma janela Tk real."""

    _download_active = EduDownloaderApp._download_active
    _set_download_controls = EduDownloaderApp._set_download_controls
    _set_download_state = EduDownloaderApp._set_download_state
    _show_download_phase = EduDownloaderApp._show_download_phase
    _show_progress = EduDownloaderApp._show_progress
    _handle_download_event = EduDownloaderApp._handle_download_event
    _set_last_download_result = EduDownloaderApp._set_last_download_result
    _finish_download_error = EduDownloaderApp._finish_download_error

    def __init__(self, state: DownloadUiState = DownloadUiState.READY) -> None:
        self._download_ui_state = state
        self._last_download_result: DownloadResult | None = None
        self._cancel_requested = False
        self._close_requested = False
        self.status = FakeVariable()
        self.percentage = FakeVariable("—")
        self.download_details = FakeVariable()
        self.progress_bar = Mock()
        self.link_entry = Mock()
        self.paste_button = Mock()
        self.clear_button = Mock()
        self.change_destination_button = Mock()
        self.content_type_buttons = [Mock(), Mock()]
        self.quality_menu = Mock()
        self.mp3_quality = FakeVariable(DEFAULT_MP3_QUALITY.display_label)
        self.download_button = Mock()
        self.cancel_button = Mock()
        self.content_type = FakeVariable(CONTENT_TYPE_VIDEO)
        self.download_queue = SimpleNamespace(add=Mock())
        self._focus_link_entry = Mock()
        self.downloads_page = SimpleNamespace(set_result_actions_enabled=Mock())


class ShutdownPageDouble:
    def __init__(
        self,
        *,
        busy: bool = False,
        cancellable: bool = False,
        shutdown_error: str | None = None,
    ):
        self.busy = busy
        self.cancellable = cancellable
        self.requested = False
        self.ready = False
        self.error = shutdown_error
        self.begin_calls = 0
        self.cancel_calls = 0
        self.close_calls = 0
        self.cancel_requests = 0

    @property
    def is_busy(self) -> bool:
        return self.busy

    @property
    def is_shutdown_ready(self) -> bool:
        return self.ready

    @property
    def shutdown_error(self) -> str | None:
        return self.error

    def begin_shutdown(self) -> None:
        if self.requested:
            return
        self.begin_calls += 1
        self.requested = True
        self.ready = not self.busy and self.error is None
        if self.busy and self.cancellable:
            self.cancel_requests += 1

    def cancel_shutdown(self) -> None:
        self.cancel_calls += 1
        self.requested = False
        self.ready = False

    def finish(self) -> None:
        self.busy = False
        self.ready = self.requested and self.error is None

    def close(self) -> None:
        self.close_calls += 1


class DownloadShutdownDouble:
    def __init__(self, *, running: bool = False):
        self.running = running
        self.cancel_calls = 0
        self.close_calls = 0

    @property
    def is_running(self) -> bool:
        return self.running

    def items(self):
        return (
            (SimpleNamespace(id="active", state=QueueState.DOWNLOADING),)
            if self.running
            else ()
        )

    def cancel(self, item_id):
        self.cancel_calls += 1
        return self.running

    @property
    def is_closed(self):
        return self.close_calls > 0

    control_error = None

    def shutdown(self, timeout=0):
        if not self.running and not self.is_closed:
            self.close()
        return self.is_closed

    def finish(self) -> None:
        self.running = False

    def close(self) -> None:
        self.close_calls += 1


class AfterScheduler:
    def __init__(self) -> None:
        self.callbacks: dict[str, Callable[[], None]] = {}
        self.cancelled: list[str] = []
        self.delays: list[int] = []
        self.created = 0

    def after(self, delay: int, callback: Callable[[], None]) -> str:
        self.created += 1
        identifier = f"after-{self.created}"
        self.callbacks[identifier] = callback
        self.delays.append(delay)
        return identifier

    def after_cancel(self, identifier: str) -> None:
        self.cancelled.append(identifier)
        self.callbacks.pop(identifier, None)

    def run(self, identifier: str) -> None:
        callback = self.callbacks.pop(identifier)
        callback()


class DownloadSnapshotDouble(DownloadUiDouble):
    _poll_download_events = EduDownloaderApp._poll_download_events
    _cancel_download = EduDownloaderApp._cancel_download

    def __init__(self, items=(), after=None):
        super().__init__()
        self._close_finalized = False
        self._queue_last_snapshot = None
        self._queue_poll_after_id = None
        self.download_queue = SimpleNamespace(
            items=Mock(return_value=items), blocked=False, cancel=Mock()
        )
        self.download_service = SimpleNamespace(events=Mock())
        self.downloads_page.show_queue_items = Mock()
        self.after = after or Mock()


class AppInteractionTests(unittest.TestCase):
    def test_download_quality_control_switches_between_audio_and_video(self) -> None:
        fake_app = SimpleNamespace(
            content_type=FakeVariable(CONTENT_TYPE_AUDIO),
            quality=FakeVariable("720p"),
            mp3_quality=FakeVariable(DEFAULT_MP3_QUALITY.display_label),
            quality_menu=Mock(),
            quality_label=Mock(),
            quality_hint=Mock(),
            _download_active=False,
            _close_requested=False,
            _save_preferences=Mock(),
        )

        EduDownloaderApp._adapt_quality_controls(fake_app, save=False)
        self.assertEqual(
            fake_app.quality_menu.configure.call_args.kwargs["values"],
            [profile.display_label for profile in MP3_QUALITY_OPTIONS],
        )
        self.assertIs(
            fake_app.quality_menu.configure.call_args.kwargs["variable"],
            fake_app.mp3_quality,
        )
        self.assertEqual(fake_app.quality.get(), "720p")
        self.assertEqual(fake_app.mp3_quality.get(), "Padrão — 192 kbps")
        EduDownloaderApp._on_quality_change(fake_app, "Alta — 320 kbps")
        fake_app._save_preferences.assert_not_called()

        fake_app.mp3_quality.set(Mp3Quality.HIGH.display_label)
        for _ in range(3):
            fake_app.content_type.set(CONTENT_TYPE_VIDEO)
            EduDownloaderApp._adapt_quality_controls(fake_app, save=False)
            self.assertEqual(
                fake_app.quality_menu.configure.call_args.kwargs["values"],
                list(app.VIDEO_QUALITIES),
            )
            self.assertIs(
                fake_app.quality_menu.configure.call_args.kwargs["variable"],
                fake_app.quality,
            )
            self.assertEqual(fake_app.quality.get(), "720p")
            fake_app.content_type.set(CONTENT_TYPE_AUDIO)
            EduDownloaderApp._adapt_quality_controls(fake_app, save=False)
            self.assertEqual(fake_app.mp3_quality.get(), "Alta — 320 kbps")

    def test_audio_download_snapshots_visible_profile_without_persisting_it(
        self,
    ) -> None:
        fake_app = DownloadUiDouble()
        fake_app.content_type.set(CONTENT_TYPE_AUDIO)
        fake_app.quality = FakeVariable("720p")
        fake_app.mp3_quality.set(Mp3Quality.ECONOMY.display_label)
        fake_app.download_service = SimpleNamespace(is_running=False, start=Mock())
        fake_app.link_entry.get.return_value = "https://example.com/aula"
        fake_app._download_destination_dir = None
        fake_app._poll_download_events = Mock()
        fake_app._show_warning = Mock()
        fake_app.after = Mock()

        EduDownloaderApp._download(fake_app)

        request = fake_app.download_queue.add.call_args.args[0]
        self.assertIs(request.mp3_quality, Mp3Quality.ECONOMY)
        self.assertEqual(request.quality, "720p")
        self.assertEqual(fake_app.mp3_quality.get(), Mp3Quality.ECONOMY.display_label)
        fake_app._show_warning.assert_not_called()

    def test_invalid_audio_profile_is_rejected_before_starting_worker(self) -> None:
        fake_app = DownloadUiDouble()
        fake_app.content_type.set(CONTENT_TYPE_AUDIO)
        fake_app.mp3_quality.set("Personalizada — 500 kbps")
        fake_app.download_service = SimpleNamespace(is_running=False, start=Mock())
        fake_app.link_entry.get.return_value = "https://example.com/aula"
        fake_app._show_warning = Mock()

        EduDownloaderApp._download(fake_app)

        fake_app.download_service.start.assert_not_called()
        fake_app._show_warning.assert_called_once_with(
            "Selecione uma qualidade MP3 válida."
        )

    def test_audio_profile_remains_available_for_next_queued_item(self) -> None:
        fake_app = DownloadUiDouble()
        fake_app.content_type.set(CONTENT_TYPE_AUDIO)
        for state in (
            DownloadUiState.PREPARING,
            DownloadUiState.DOWNLOADING,
            DownloadUiState.PROCESSING,
        ):
            with self.subTest(state=state):
                fake_app._set_download_state(state)
                fake_app.quality_menu.configure.assert_called_with(state="normal")
        fake_app._cancel_requested = True
        fake_app._set_download_controls()
        fake_app.quality_menu.configure.assert_called_with(state="normal")
        for state in (
            DownloadUiState.COMPLETED,
            DownloadUiState.CANCELLED,
            DownloadUiState.ERROR,
        ):
            with self.subTest(state=state):
                fake_app._set_download_state(state)
                fake_app.quality_menu.configure.assert_called_with(state="normal")

    def test_snapshot_poll_does_not_consume_service_events(self) -> None:
        scheduler = AfterScheduler()
        items = tuple(
            QueueItem(
                str(i),
                DownloadRequest("https://example.com/a", CONTENT_TYPE_VIDEO, "720p"),
            )
            for i in range(100)
        )
        fake_app = DownloadSnapshotDouble(items, scheduler.after)
        fake_app._poll_download_events()
        fake_app.downloads_page.show_queue_items.assert_called_once_with(
            items, blocked=False, closing=False
        )
        fake_app.download_service.events.get_nowait.assert_not_called()
        self.assertEqual(scheduler.delays, [app._DOWNLOAD_EVENT_POLL_DELAY_MS])

    def test_snapshot_poll_keeps_human_cadence_when_idle(self) -> None:
        scheduler = AfterScheduler()
        fake_app = DownloadSnapshotDouble(after=scheduler.after)
        fake_app._poll_download_events()
        self.assertEqual(scheduler.delays, [app._DOWNLOAD_EVENT_POLL_DELAY_MS])

    def test_snapshot_progress_uses_human_visual_cadence(self) -> None:
        scheduler = AfterScheduler()
        item = QueueItem(
            "active",
            DownloadRequest("https://example.com/a", CONTENT_TYPE_VIDEO, "720p"),
            state=QueueState.DOWNLOADING,
            progress=DownloadProgress(50, 500, 1000, 100, 5),
        )
        fake_app = DownloadSnapshotDouble((item,), scheduler.after)
        fake_app._poll_download_events()
        self.assertEqual(fake_app.percentage.get(), "50%")
        self.assertEqual(scheduler.delays, [app._DOWNLOAD_EVENT_POLL_DELAY_MS])

    def test_identical_snapshots_do_not_reconfigure_queue_rows(self) -> None:
        fake_app = DownloadSnapshotDouble()
        fake_app._poll_download_events()
        fake_app._poll_download_events()
        fake_app.downloads_page.show_queue_items.assert_called_once()
        self.assertEqual(fake_app.after.call_count, 2)

    def test_terminal_snapshot_is_retained_without_visual_completion_from_progress(
        self,
    ) -> None:
        request = DownloadRequest("https://example.com/a", CONTENT_TYPE_VIDEO, "720p")
        item = QueueItem(
            "active",
            request,
            state=QueueState.DOWNLOADING,
            progress=DownloadProgress(100, 1000, 1000, None, 0),
        )
        fake_app = DownloadSnapshotDouble((item,))
        fake_app._poll_download_events()
        self.assertNotEqual(fake_app.percentage.get(), "100%")
        result = DownloadResult(Path("synthetic/result.mp4"), False)
        terminal = QueueItem(
            "active", request, state=QueueState.COMPLETED, result=result
        )
        fake_app.download_queue.items.return_value = (terminal,)
        fake_app._poll_download_events()
        self.assertIs(fake_app._last_download_result, result)
        self.assertEqual(
            fake_app.downloads_page.show_queue_items.call_args.args[0], (terminal,)
        )

    def test_real_tcl_scheduler_keeps_snapshot_cancel_responsive(self) -> None:
        root = tk.Tcl()
        request = DownloadRequest("https://example.com/a", CONTENT_TYPE_VIDEO, "720p")
        items = tuple(
            QueueItem(
                str(i),
                request,
                state=QueueState.DOWNLOADING if i == 0 else QueueState.WAITING,
            )
            for i in range(100)
        )
        fake_app = DownloadSnapshotDouble(items, root.after)
        main_thread = threading.get_ident()
        threads = []
        fake_app.downloads_page.show_queue_items.side_effect = lambda *args, **kwargs: (
            threads.append(threading.get_ident())
        )
        started = time.monotonic()
        root.after(0, fake_app._poll_download_events)

        def cancel():
            fake_app._cancel_download()
            root.setvar("dispatch_done", "cancelled")

        root.after(0, cancel)
        root.after(2000, lambda: root.setvar("dispatch_done", "timeout"))
        root.eval("vwait dispatch_done")
        self.assertEqual(root.getvar("dispatch_done"), "cancelled")
        self.assertLess(time.monotonic() - started, 0.5)
        fake_app.download_queue.cancel.assert_called_once_with("0")
        fake_app.download_service.events.get_nowait.assert_not_called()
        self.assertEqual(threads, [main_thread])
        for identifier in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(identifier)

    def _shutdown_app(
        self,
        *,
        pdf_busy: bool = False,
        documents_busy: bool = False,
        media_busy: bool = False,
        download_busy: bool = False,
        confirmed: bool = True,
    ) -> tuple[SimpleNamespace, AfterScheduler]:
        scheduler = AfterScheduler()
        fake_app = SimpleNamespace(
            _close_requested=False,
            _close_finalized=False,
            _close_poll_after_id=None,
            _download_active=download_busy,
            _cancel_requested=False,
            pdf_page=ShutdownPageDouble(busy=pdf_busy),
            documents_page=ShutdownPageDouble(
                busy=documents_busy,
                cancellable=True,
            ),
            media_page=ShutdownPageDouble(
                busy=media_busy,
                cancellable=True,
            ),
            settings_page=SimpleNamespace(
                is_component_operation_active=False,
                is_shutdown_ready=True,
                begin_shutdown=Mock(),
                cancel_shutdown=Mock(),
            ),
            files_page=SimpleNamespace(close=Mock()),
            download_service=DownloadShutdownDouble(running=download_busy),
            _ask_confirmation=Mock(return_value=confirmed),
            _set_download_controls=Mock(),
            _show_error=Mock(),
            _save_preferences=Mock(),
            status=FakeVariable(),
            withdraw=Mock(),
            destroy=Mock(),
            after=scheduler.after,
            after_cancel=scheduler.after_cancel,
        )
        fake_app.download_queue = fake_app.download_service
        fake_app._queue_shutdown_started = False
        fake_app._queue_poll_after_id = None
        fake_app.downloads_page = SimpleNamespace(close_queue_view=Mock())
        return fake_app, scheduler

    def test_current_application_version_is_2_5_0(self) -> None:
        self.assertEqual(APP_VERSION, "3.0.0")

    def test_internal_version_and_license_remain_in_windows_metadata(self) -> None:
        from windows_metadata import metadata

        resource = metadata()
        self.assertEqual(resource["FileVersion"], APP_VERSION)
        self.assertEqual(resource["ProductVersion"], APP_VERSION)
        self.assertIn("LICENSE", resource["LegalCopyright"])

    def test_navigation_has_home_downloads_files_tools_and_settings(self) -> None:
        self.assertEqual(
            NAVIGATION_PAGES,
            (
                PAGE_HOME,
                PAGE_DOWNLOADS,
                PAGE_FILES,
                PAGE_TOOLS,
                PAGE_SETTINGS,
            ),
        )

    def test_page_navigation_reuses_pages_service_and_download_state(self) -> None:
        class FakePage:
            def __init__(self) -> None:
                self.grid_calls = 0
                self.remove_calls = 0
                self.raise_calls = 0

            def grid(self, **_options) -> None:
                self.grid_calls += 1

            def grid_forget(self) -> None:
                self.remove_calls += 1

            def lower(self) -> None:
                pass

            def focus_set(self) -> None:
                pass

            def update_idletasks(self) -> None:
                pass

            def lift(self) -> None:
                self.raise_calls += 1

        service = object()
        downloads_page = FakePage()
        status = FakeVariable("Baixando...")
        fake_app = SimpleNamespace(
            _pages={
                PAGE_HOME: FakePage(),
                PAGE_DOWNLOADS: downloads_page,
            },
            _navigation_buttons={PAGE_HOME: Mock(), PAGE_DOWNLOADS: Mock()},
            _current_page=None,
            _focus_link_entry=Mock(),
            download_service=service,
            status=status,
            _download_active=True,
        )

        EduDownloaderApp._show_page(fake_app, PAGE_DOWNLOADS)
        EduDownloaderApp._show_page(fake_app, PAGE_HOME)
        EduDownloaderApp._show_page(fake_app, PAGE_DOWNLOADS)

        self.assertIs(fake_app.download_service, service)
        self.assertIs(fake_app._pages[PAGE_DOWNLOADS], downloads_page)
        self.assertEqual(fake_app.status.get(), "Baixando...")
        self.assertTrue(fake_app._download_active)
        self.assertEqual(downloads_page.grid_calls, 2)
        self.assertEqual(downloads_page.remove_calls, 1)
        self.assertEqual(downloads_page.raise_calls, 0)
        self.assertEqual(fake_app._current_page, PAGE_DOWNLOADS)
        fake_app._focus_link_entry.assert_not_called()

    def test_unknown_page_is_rejected_without_changing_state(self) -> None:
        fake_app = SimpleNamespace(
            _pages={PAGE_HOME: Mock()},
            _current_page=PAGE_HOME,
        )

        with self.assertRaises(ValueError):
            EduDownloaderApp._show_page(fake_app, "Ferramenta inexistente")

        self.assertEqual(fake_app._current_page, PAGE_HOME)

    def test_theme_setting_uses_the_existing_preference_key(self) -> None:
        fake_app = SimpleNamespace(
            settings={"tema": "claro"},
            files_page=SimpleNamespace(apply_theme=Mock()),
            _save_preferences=Mock(),
        )
        with patch("app.ctk.set_appearance_mode") as set_appearance:
            EduDownloaderApp._change_theme(fake_app, "Escuro")

        self.assertEqual(fake_app.settings, {"tema": THEME_DARK})
        set_appearance.assert_called_once_with("Dark")
        fake_app.files_page.apply_theme.assert_called_once_with("Escuro")
        fake_app._save_preferences.assert_called_once_with(from_settings=True)

    def test_theme_save_failure_stays_in_settings_and_retry_clears_feedback(
        self,
    ) -> None:
        settings_page = SimpleNamespace(
            show_persistence_error=Mock(),
            clear_persistence_feedback=Mock(),
        )
        fake_app = SimpleNamespace(
            settings={"tema": "claro"},
            content_type=FakeVariable(CONTENT_TYPE_VIDEO),
            quality=FakeVariable("720p"),
            files_page=SimpleNamespace(apply_theme=Mock()),
            settings_page=settings_page,
            status=FakeVariable("Status de Downloads preservado"),
        )
        fake_app._save_preferences = lambda **kwargs: (
            EduDownloaderApp._save_preferences(fake_app, **kwargs)
        )

        with (
            patch("app.ctk.set_appearance_mode") as set_appearance,
            patch("app.save_settings", side_effect=OSError("somente leitura")),
        ):
            EduDownloaderApp._change_theme(fake_app, "Escuro")

        self.assertEqual(fake_app.settings["tema"], THEME_DARK)
        self.assertEqual(fake_app.status.get(), "Status de Downloads preservado")
        set_appearance.assert_called_once_with("Dark")
        fake_app.files_page.apply_theme.assert_called_once_with("Escuro")
        settings_page.show_persistence_error.assert_called_once_with(
            "O tema foi aplicado, mas não foi possível salvar a preferência "
            "para o próximo início."
        )
        settings_page.clear_persistence_feedback.assert_not_called()

        with (
            patch("app.ctk.set_appearance_mode") as set_appearance,
            patch("app.save_settings", side_effect=lambda data: data.copy()),
        ):
            EduDownloaderApp._change_theme(fake_app, "Claro")

        self.assertEqual(fake_app.settings["tema"], "claro")
        self.assertEqual(fake_app.status.get(), "Status de Downloads preservado")
        set_appearance.assert_called_once_with("Light")
        settings_page.clear_persistence_feedback.assert_called_once_with()

    def test_cancel_feedback_is_confirmed_without_absolute_process_claim(self) -> None:
        fake_app = SimpleNamespace(
            _close_requested=False,
            _set_last_download_result=Mock(),
            _set_download_state=Mock(),
            _show_info=Mock(),
            _focus_link_entry=Mock(),
        )

        EduDownloaderApp._finish_download_cancelled(fake_app)

        fake_app._set_download_state.assert_called_once_with(DownloadUiState.CANCELLED)
        fake_app._set_last_download_result.assert_called_once_with(None)
        fake_app._show_info.assert_called_once_with("O download foi cancelado.")
        self.assertNotIn(
            "processo",
            fake_app._show_info.call_args.args[0].casefold(),
        )

    def test_file_routes_reuse_pages_and_navigate_only_after_acceptance(self) -> None:
        pdf_page = SimpleNamespace(
            prepare_extract_source=Mock(return_value=True),
            prepare_pdf_to_images_source=Mock(return_value=True),
            add_image_to_pdf=Mock(return_value=True),
            prepare_poster_source=Mock(return_value=True),
        )
        media_page = SimpleNamespace(
            prepare_video_to_mp3_source=Mock(return_value=True)
        )
        documents_page = SimpleNamespace(
            prepare_docx_to_pdf=Mock(return_value=True),
            prepare_odt_to_pdf=Mock(return_value=True),
            prepare_txt_to_pdf=Mock(return_value=True),
        )
        fake_app = SimpleNamespace(
            pdf_page=pdf_page,
            media_page=media_page,
            documents_page=documents_page,
            _show_page=Mock(),
        )
        paths = {
            "extract": Path("atividade.pdf"),
            "pdf_images": Path("apostila.pdf"),
            "image_pdf": Path("foto.png"),
            "poster": Path("cartaz.png"),
            "video_mp3": Path("aula.mp4"),
            "docx_pdf": Path("plano.docx"),
            "odt_pdf": Path("atividade.odt"),
            "txt_pdf": Path("anotacoes.txt"),
        }

        self.assertTrue(
            EduDownloaderApp._route_file_to_extract_pages(fake_app, paths["extract"])
        )
        self.assertTrue(
            EduDownloaderApp._route_file_to_pdf_images(fake_app, paths["pdf_images"])
        )
        self.assertTrue(
            EduDownloaderApp._route_file_to_image_pdf(fake_app, paths["image_pdf"])
        )
        self.assertTrue(
            EduDownloaderApp._route_file_to_poster(fake_app, paths["poster"])
        )
        self.assertTrue(
            EduDownloaderApp._route_file_to_video_mp3(fake_app, paths["video_mp3"])
        )
        self.assertTrue(
            EduDownloaderApp._route_file_to_docx_pdf(fake_app, paths["docx_pdf"])
        )
        self.assertTrue(
            EduDownloaderApp._route_file_to_odt_pdf(fake_app, paths["odt_pdf"])
        )
        self.assertTrue(
            EduDownloaderApp._route_file_to_txt_pdf(fake_app, paths["txt_pdf"])
        )
        pdf_page.prepare_extract_source.assert_called_once_with(paths["extract"])
        pdf_page.prepare_pdf_to_images_source.assert_called_once_with(
            paths["pdf_images"]
        )
        pdf_page.add_image_to_pdf.assert_called_once_with(paths["image_pdf"])
        pdf_page.prepare_poster_source.assert_called_once_with(paths["poster"])
        media_page.prepare_video_to_mp3_source.assert_called_once_with(
            paths["video_mp3"]
        )
        documents_page.prepare_docx_to_pdf.assert_called_once_with(paths["docx_pdf"])
        documents_page.prepare_odt_to_pdf.assert_called_once_with(paths["odt_pdf"])
        documents_page.prepare_txt_to_pdf.assert_called_once_with(paths["txt_pdf"])
        self.assertEqual(
            [call.args[0] for call in fake_app._show_page.call_args_list],
            [
                PAGE_PDF,
                PAGE_PDF,
                PAGE_PDF,
                PAGE_PDF,
                PAGE_MEDIA,
                PAGE_DOCUMENTS,
                PAGE_DOCUMENTS,
                PAGE_DOCUMENTS,
            ],
        )

        fake_app._show_page.reset_mock()
        pdf_page.prepare_extract_source.return_value = False
        pdf_page.prepare_pdf_to_images_source.return_value = False
        pdf_page.add_image_to_pdf.return_value = False
        pdf_page.prepare_poster_source.return_value = False
        media_page.prepare_video_to_mp3_source.return_value = False
        documents_page.prepare_docx_to_pdf.return_value = False
        documents_page.prepare_odt_to_pdf.return_value = False
        documents_page.prepare_txt_to_pdf.return_value = False
        self.assertFalse(
            EduDownloaderApp._route_file_to_extract_pages(fake_app, paths["extract"])
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_pdf_images(fake_app, paths["pdf_images"])
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_image_pdf(fake_app, paths["image_pdf"])
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_poster(fake_app, paths["poster"])
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_video_mp3(fake_app, paths["video_mp3"])
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_docx_pdf(fake_app, paths["docx_pdf"])
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_odt_pdf(fake_app, paths["odt_pdf"])
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_txt_pdf(fake_app, paths["txt_pdf"])
        )
        fake_app._show_page.assert_not_called()

    def test_idle_close_is_immediate_without_confirmation_and_tears_down_once(
        self,
    ) -> None:
        fake_app, scheduler = self._shutdown_app()

        EduDownloaderApp._on_close(fake_app)
        EduDownloaderApp._on_close(fake_app)
        EduDownloaderApp._poll_close_readiness(fake_app)

        fake_app._ask_confirmation.assert_not_called()
        self.assertTrue(fake_app._close_requested)
        self.assertTrue(fake_app._close_finalized)
        self.assertEqual(fake_app.pdf_page.begin_calls, 1)
        self.assertEqual(fake_app.documents_page.begin_calls, 1)
        self.assertEqual(fake_app.media_page.begin_calls, 1)
        self.assertEqual(fake_app.download_service.cancel_calls, 0)
        self.assertEqual(fake_app.download_service.close_calls, 1)
        self.assertEqual(fake_app.pdf_page.close_calls, 1)
        self.assertEqual(fake_app.documents_page.close_calls, 1)
        self.assertEqual(fake_app.media_page.close_calls, 1)
        fake_app.files_page.close.assert_called_once_with()
        fake_app._save_preferences.assert_called_once_with()
        fake_app.destroy.assert_called_once_with()
        self.assertEqual(scheduler.created, 0)

    def test_component_update_is_cancelled_and_awaited_on_close(self) -> None:
        fake_app, scheduler = self._shutdown_app()
        fake_app.settings_page.is_component_operation_active = True
        fake_app.settings_page.is_shutdown_ready = False

        EduDownloaderApp._on_close(fake_app)

        message = fake_app._ask_confirmation.call_args.args[0]
        self.assertIn("atualização do componente", message)
        fake_app.settings_page.begin_shutdown.assert_called_once_with()
        self.assertFalse(fake_app._close_finalized)
        self.assertEqual(len(scheduler.callbacks), 1)

        fake_app.settings_page.is_shutdown_ready = True
        scheduler.run(fake_app._close_poll_after_id)
        self.assertTrue(fake_app._close_finalized)
        fake_app.destroy.assert_called_once_with()

    def test_refused_close_changes_no_module_or_shutdown_state(self) -> None:
        fake_app, scheduler = self._shutdown_app(
            pdf_busy=True,
            media_busy=True,
            download_busy=True,
            confirmed=False,
        )

        EduDownloaderApp._on_close(fake_app)

        self.assertFalse(fake_app._close_requested)
        self.assertFalse(fake_app._close_finalized)
        self.assertEqual(fake_app.pdf_page.begin_calls, 0)
        self.assertEqual(fake_app.media_page.begin_calls, 0)
        self.assertEqual(fake_app.download_service.cancel_calls, 0)
        fake_app._set_download_controls.assert_not_called()
        fake_app.withdraw.assert_not_called()
        fake_app.destroy.assert_not_called()
        self.assertEqual(scheduler.created, 0)

    def test_close_keeps_the_page_visible_until_safe_then_hides_before_teardown(
        self,
    ) -> None:
        fake_app, scheduler = self._shutdown_app(pdf_busy=True)
        feedback = fake_app._close_feedback = Mock()
        feedback.place_info.return_value = {}
        teardown = Mock()
        teardown.attach_mock(fake_app.withdraw, "hide")
        teardown.attach_mock(fake_app.files_page.close, "close_files")
        teardown.attach_mock(fake_app._save_preferences, "save")
        teardown.attach_mock(fake_app.destroy, "destroy")

        EduDownloaderApp._request_close(fake_app)

        feedback.place.assert_called_once()
        self.assertEqual(teardown.mock_calls, [])
        fake_app.pdf_page.finish()
        scheduler.run(fake_app._close_poll_after_id)

        self.assertEqual(
            teardown.mock_calls,
            [call.hide(), call.close_files(), call.save(), call.destroy()],
        )

    def test_every_active_module_combination_uses_one_coordinated_flow(self) -> None:
        combinations = (
            (True, False, False, False),
            (False, True, False, False),
            (False, False, True, False),
            (False, False, False, True),
            (True, True, True, True),
        )
        for pdf_busy, documents_busy, media_busy, download_busy in combinations:
            with self.subTest(
                pdf=pdf_busy,
                documents=documents_busy,
                media=media_busy,
                download=download_busy,
            ):
                fake_app, scheduler = self._shutdown_app(
                    pdf_busy=pdf_busy,
                    documents_busy=documents_busy,
                    media_busy=media_busy,
                    download_busy=download_busy,
                )

                EduDownloaderApp._on_close(fake_app)
                EduDownloaderApp._on_close(fake_app)
                EduDownloaderApp._on_close(fake_app)

                fake_app._ask_confirmation.assert_called_once()
                message = fake_app._ask_confirmation.call_args.args[0]
                self.assertEqual("operação PDF" in message, pdf_busy)
                self.assertEqual("conversão de documento" in message, documents_busy)
                self.assertEqual("conversão de mídia" in message, media_busy)
                self.assertEqual(
                    "O download será cancelado." in message,
                    download_busy,
                )
                self.assertEqual(fake_app.pdf_page.begin_calls, 1)
                self.assertEqual(fake_app.documents_page.begin_calls, 1)
                self.assertEqual(fake_app.media_page.begin_calls, 1)
                self.assertEqual(
                    fake_app.download_service.cancel_calls,
                    1 if download_busy else 0,
                )
                self.assertEqual(scheduler.created, 1)
                self.assertEqual(len(scheduler.callbacks), 1)
                fake_app.destroy.assert_not_called()

    def test_pdf_media_and_download_finish_then_finalize_automatically(self) -> None:
        fake_app, scheduler = self._shutdown_app(
            pdf_busy=True,
            documents_busy=True,
            media_busy=True,
            download_busy=True,
        )

        EduDownloaderApp._on_close(fake_app)
        first_after = fake_app._close_poll_after_id
        self.assertIsNotNone(first_after)
        fake_app.media_page.finish()
        fake_app.documents_page.finish()
        fake_app.pdf_page.finish()
        fake_app.download_service.finish()
        scheduler.run(first_after)

        self.assertTrue(fake_app._close_finalized)
        self.assertEqual(fake_app.pdf_page.cancel_requests, 0)
        self.assertEqual(fake_app.media_page.cancel_requests, 1)
        self.assertEqual(fake_app.documents_page.cancel_requests, 1)
        self.assertEqual(fake_app.download_service.cancel_calls, 1)
        self.assertEqual(fake_app.download_service.close_calls, 1)
        fake_app._save_preferences.assert_called_once_with()
        fake_app.destroy.assert_called_once_with()
        self.assertEqual(scheduler.callbacks, {})

    def test_pending_poll_and_late_callback_cannot_finalize_twice(self) -> None:
        fake_app, scheduler = self._shutdown_app(pdf_busy=True)

        EduDownloaderApp._on_close(fake_app)
        after_id = fake_app._close_poll_after_id
        callback = scheduler.callbacks[after_id]
        fake_app.pdf_page.finish()
        fake_app.download_queue.shutdown(0)
        EduDownloaderApp._finalize_close(fake_app)
        callback()
        EduDownloaderApp._finalize_close(fake_app)

        self.assertEqual(scheduler.cancelled, [after_id])
        self.assertEqual(fake_app.download_service.close_calls, 1)
        fake_app._save_preferences.assert_called_once_with()
        fake_app.destroy.assert_called_once_with()

    def test_media_shutdown_failure_keeps_window_open_and_allows_retry(self) -> None:
        fake_app, scheduler = self._shutdown_app(media_busy=True)

        EduDownloaderApp._on_close(fake_app)
        first_after = fake_app._close_poll_after_id
        failure_message = (
            "Não foi possível encerrar a conversão com segurança. "
            "O aplicativo permanecerá aberto."
        )
        fake_app.media_page.error = failure_message
        scheduler.run(first_after)

        self.assertFalse(fake_app._close_requested)
        self.assertFalse(fake_app._close_finalized)
        self.assertEqual(fake_app.pdf_page.cancel_calls, 1)
        self.assertEqual(fake_app.documents_page.cancel_calls, 1)
        self.assertEqual(fake_app.media_page.cancel_calls, 1)
        fake_app.settings_page.cancel_shutdown.assert_called_once_with()
        fake_app._show_error.assert_called_once_with(failure_message)
        fake_app.destroy.assert_not_called()

        fake_app.media_page.error = None
        fake_app.media_page.busy = False
        EduDownloaderApp._on_close(fake_app)

        self.assertTrue(fake_app._close_finalized)
        self.assertEqual(fake_app.media_page.begin_calls, 2)
        self.assertEqual(fake_app._ask_confirmation.call_count, 1)
        fake_app.destroy.assert_called_once_with()

    def test_close_requested_blocks_new_download_and_file_handoffs(self) -> None:
        pdf_page = SimpleNamespace(
            prepare_extract_source=Mock(return_value=True),
            prepare_pdf_to_images_source=Mock(return_value=True),
            add_image_to_pdf=Mock(return_value=True),
        )
        media_page = SimpleNamespace(
            prepare_video_to_mp3_source=Mock(return_value=True)
        )
        documents_page = SimpleNamespace(prepare_docx_to_pdf=Mock(return_value=True))
        fake_app = SimpleNamespace(
            _close_requested=True,
            _modal_open=False,
            _download_active=False,
            download_service=SimpleNamespace(is_running=False, start=Mock()),
            pdf_page=pdf_page,
            media_page=media_page,
            documents_page=documents_page,
            _show_page=Mock(),
            _download=Mock(),
        )

        self.assertEqual(EduDownloaderApp._on_link_enter(fake_app, Mock()), "break")
        EduDownloaderApp._download(fake_app)
        self.assertFalse(
            EduDownloaderApp._route_file_to_extract_pages(
                fake_app, Path("atividade.pdf")
            )
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_pdf_images(fake_app, Path("apostila.pdf"))
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_image_pdf(fake_app, Path("foto.png"))
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_video_mp3(fake_app, Path("aula.mp4"))
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_docx_pdf(fake_app, Path("plano.docx"))
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_odt_pdf(fake_app, Path("plano.odt"))
        )
        self.assertFalse(
            EduDownloaderApp._route_file_to_txt_pdf(fake_app, Path("notas.txt"))
        )

        fake_app._download.assert_not_called()
        fake_app.download_service.start.assert_not_called()
        pdf_page.prepare_extract_source.assert_not_called()
        pdf_page.prepare_pdf_to_images_source.assert_not_called()
        pdf_page.add_image_to_pdf.assert_not_called()
        media_page.prepare_video_to_mp3_source.assert_not_called()
        documents_page.prepare_docx_to_pdf.assert_not_called()
        fake_app._show_page.assert_not_called()

    def test_download_terminal_events_show_no_modal_during_shutdown(self) -> None:
        fake_app = SimpleNamespace(
            _close_requested=True,
            progress_bar=Mock(),
            percentage=FakeVariable(),
            download_details=FakeVariable(),
            status=FakeVariable(),
            _set_last_download_result=Mock(),
            _set_download_state=Mock(),
            _show_info=Mock(),
            _show_error=Mock(),
            _focus_link_entry=Mock(),
        )

        EduDownloaderApp._finish_download_success(
            fake_app,
            DownloadResult(Path("Downloads/aula.mp4"), already_existed=False),
        )
        EduDownloaderApp._finish_download_cancelled(fake_app)
        EduDownloaderApp._finish_download_error(fake_app, object())

        self.assertEqual(fake_app._set_last_download_result.call_count, 3)
        self.assertEqual(fake_app._set_download_state.call_count, 3)
        fake_app._show_info.assert_not_called()
        fake_app._show_error.assert_not_called()
        fake_app._focus_link_entry.assert_not_called()

    def test_enter_on_link_field_delegates_to_download_action(self) -> None:
        fake_app = SimpleNamespace(
            _modal_open=False,
            _download_active=False,
            download_service=SimpleNamespace(is_running=False),
            _download=Mock(),
        )

        result = EduDownloaderApp._on_link_enter(fake_app, Mock())

        self.assertEqual(result, "break")
        fake_app._download.assert_called_once_with()

    def test_enter_blocks_modal_but_allows_adding_during_download(self) -> None:
        for modal_open, download_active, service_running in (
            (True, False, False),
            (False, True, False),
            (False, False, True),
        ):
            with self.subTest(
                modal=modal_open,
                active=download_active,
                service=service_running,
            ):
                fake_app = SimpleNamespace(
                    _modal_open=modal_open,
                    _download_active=download_active,
                    download_service=SimpleNamespace(is_running=service_running),
                    _download=Mock(),
                )

                result = EduDownloaderApp._on_link_enter(fake_app, Mock())

                self.assertEqual(result, "break")
                if modal_open:
                    fake_app._download.assert_not_called()
                else:
                    fake_app._download.assert_called_once_with()

    def test_empty_link_uses_same_validation_and_does_not_start_service(self) -> None:
        service = SimpleNamespace(is_running=False, start=Mock())
        fake_app = SimpleNamespace(
            _download_active=False,
            download_service=service,
            link_entry=Mock(get=Mock(return_value="   ")),
            _show_warning=Mock(),
            _focus_link_entry=Mock(),
        )

        EduDownloaderApp._download(fake_app)

        service.start.assert_not_called()
        fake_app._show_warning.assert_called_once()
        fake_app._focus_link_entry.assert_called_once_with()

    def test_active_operation_accepts_next_queue_request(self) -> None:
        fake_app = DownloadUiDouble(DownloadUiState.DOWNLOADING)
        fake_app.link_entry.get.return_value = "https://example.com/next"
        fake_app.quality = FakeVariable("720p")
        fake_app._download_destination_dir = None
        EduDownloaderApp._download(fake_app)
        fake_app.download_queue.add.assert_called_once()
        self.assertEqual(
            fake_app.download_queue.add.call_args.args[0].url,
            "https://example.com/next",
        )
        self.assertTrue(fake_app._download_active)

    def test_adding_download_preserves_active_progress(self) -> None:
        fake_app = DownloadUiDouble(DownloadUiState.DOWNLOADING)
        fake_app.link_entry.get.return_value = "https://example.com/next"
        fake_app.quality = FakeVariable("720p")
        fake_app._download_destination_dir = None
        fake_app.percentage.set("55%")
        EduDownloaderApp._download(fake_app)
        fake_app.download_queue.add.assert_called_once_with(
            DownloadRequest("https://example.com/next", CONTENT_TYPE_VIDEO, "720p")
        )
        self.assertEqual(fake_app.percentage.get(), "55%")
        self.assertEqual(fake_app._download_ui_state, DownloadUiState.DOWNLOADING)

    def test_active_state_allows_preparing_next_request(self) -> None:
        fake_app = SimpleNamespace(
            _download_active=True,
            _cancel_requested=False,
            _download_ui_state=DownloadUiState.DOWNLOADING,
            _last_download_result=None,
            _close_requested=False,
            link_entry=Mock(),
            paste_button=Mock(),
            clear_button=Mock(),
            change_destination_button=Mock(),
            content_type_buttons=[Mock(), Mock()],
            quality_menu=Mock(),
            download_button=Mock(),
            cancel_button=Mock(),
            content_type=FakeVariable(CONTENT_TYPE_VIDEO),
            downloads_page=SimpleNamespace(set_result_actions_enabled=Mock()),
        )

        EduDownloaderApp._set_download_controls(fake_app)

        fake_app.link_entry.configure.assert_called_once_with(state="normal")
        fake_app.paste_button.configure.assert_called_once_with(state="normal")
        fake_app.clear_button.configure.assert_called_once_with(state="normal")
        fake_app.change_destination_button.configure.assert_called_once_with(
            state="normal"
        )
        for button in fake_app.content_type_buttons:
            button.configure.assert_called_once_with(state="normal")
        fake_app.quality_menu.configure.assert_called_once_with(state="normal")
        fake_app.download_button.configure.assert_called_once_with(
            state="normal", text="Adicionar à fila"
        )
        fake_app.cancel_button.configure.assert_called_once_with(state="normal")

    def test_destination_selection_remembers_folder_and_preserves_unicode(self) -> None:
        destination = Path("C:/Materiais João/Pasta com espaços")
        base_dir = Path("C:/EduDownloader")
        fake_app = SimpleNamespace(
            _modal_open=False,
            _download_active=False,
            _close_requested=False,
            _download_destination_dir=None,
            download_service=SimpleNamespace(is_running=False, base_dir=base_dir),
            downloads_page=SimpleNamespace(show_download_destination=Mock()),
            dialog_preferences=Mock(),
        )

        with (
            patch(
                "app.filedialog.askdirectory", return_value=str(destination)
            ) as dialog,
            patch.object(
                Path,
                "is_dir",
                autospec=True,
                side_effect=lambda path: path == destination,
            ),
            patch("app.save_settings") as save,
            patch("app.open_downloads_dir") as open_downloads,
        ):
            EduDownloaderApp._choose_download_destination(fake_app)

        self.assertEqual(fake_app._download_destination_dir, destination)
        fake_app.downloads_page.show_download_destination.assert_called_once_with(
            destination
        )
        self.assertFalse(fake_app._modal_open)
        self.assertEqual(dialog.call_args.kwargs["parent"], fake_app)
        save.assert_not_called()
        fake_app.dialog_preferences.remember.assert_called_once_with(
            "downloads.output", destination
        )
        open_downloads.assert_not_called()

    def test_cancelled_destination_selection_preserves_current_session_value(
        self,
    ) -> None:
        current = Path.cwd()
        fake_app = SimpleNamespace(
            _modal_open=False,
            _download_active=False,
            _close_requested=False,
            _download_destination_dir=current,
            download_service=SimpleNamespace(
                is_running=False,
                base_dir=Path("C:/EduDownloader"),
                start=Mock(),
            ),
            downloads_page=SimpleNamespace(show_download_destination=Mock()),
        )

        with patch("app.filedialog.askdirectory", return_value="") as dialog:
            EduDownloaderApp._choose_download_destination(fake_app)

        self.assertEqual(fake_app._download_destination_dir, current)
        self.assertEqual(dialog.call_args.kwargs["initialdir"], str(current))
        fake_app.downloads_page.show_download_destination.assert_not_called()
        fake_app.download_service.start.assert_not_called()

    def test_active_download_allows_selecting_next_destination(self) -> None:
        fake_app = SimpleNamespace(
            _modal_open=False,
            _close_requested=False,
            _download_active=True,
            download_service=SimpleNamespace(base_dir=Path(tempfile.gettempdir())),
            _download_destination_dir=None,
            dialog_preferences=Mock(),
            downloads_page=Mock(),
        )
        with patch(
            "app.filedialog.askdirectory", return_value=tempfile.gettempdir()
        ) as dialog:
            EduDownloaderApp._choose_download_destination(fake_app)
        dialog.assert_called_once()
        self.assertEqual(
            fake_app._download_destination_dir, Path(tempfile.gettempdir())
        )
        fake_app.dialog_preferences.remember.assert_called_once()

    def test_download_snapshots_selected_destination_in_immutable_request(self) -> None:
        selected = Path("C:/Destino João/Material com espaços")
        replacement = Path("D:/Outro destino")
        service = SimpleNamespace(is_running=False, start=Mock())
        fake_app = SimpleNamespace(
            _download_active=False,
            _cancel_requested=False,
            _download_destination_dir=selected,
            download_service=service,
            link_entry=Mock(get=Mock(return_value="https://example.com/aula")),
            content_type=FakeVariable(CONTENT_TYPE_VIDEO),
            quality=FakeVariable("720p"),
            status=FakeVariable(),
            download_details=FakeVariable(),
            percentage=FakeVariable(),
            progress_bar=Mock(),
            _set_download_controls=Mock(),
            _set_download_state=Mock(),
            _set_last_download_result=Mock(),
            _poll_download_events=Mock(),
            download_queue=SimpleNamespace(add=Mock()),
            _focus_link_entry=Mock(),
            after=Mock(),
        )

        EduDownloaderApp._download(fake_app)
        request = fake_app.download_queue.add.call_args.args[0]
        fake_app._download_destination_dir = replacement

        self.assertEqual(request.destination_dir, selected)
        self.assertNotEqual(request.destination_dir, fake_app._download_destination_dir)

    def test_destination_control_is_reenabled_after_terminal_state(self) -> None:
        fake_app = SimpleNamespace(
            _download_active=False,
            _download_ui_state=DownloadUiState.CANCELLED,
            _last_download_result=None,
            _close_requested=False,
            link_entry=Mock(),
            paste_button=Mock(),
            clear_button=Mock(),
            change_destination_button=Mock(),
            content_type_buttons=[Mock(), Mock()],
            quality_menu=Mock(),
            download_button=Mock(),
            cancel_button=Mock(),
            content_type=FakeVariable(CONTENT_TYPE_VIDEO),
            downloads_page=SimpleNamespace(set_result_actions_enabled=Mock()),
        )

        EduDownloaderApp._set_download_controls(fake_app)

        fake_app.change_destination_button.configure.assert_called_once_with(
            state="normal"
        )

    def test_destination_presentation_wraps_without_changing_full_path(self) -> None:
        destination = Path(
            "C:/Materiais da Educação/"
            + "pasta muito longa com espaços e Unicode 你好/" * 4
        )
        fake_page = SimpleNamespace(destination_text=FakeVariable())

        DownloadsPage.show_download_destination(fake_page, destination)

        self.assertEqual(fake_page.destination_text.get(), str(destination))

    def test_result_action_buttons_follow_explicit_session_state(self) -> None:
        fake_app = SimpleNamespace(
            _last_download_result=None,
            _set_download_controls=Mock(),
        )
        result = DownloadResult(Path("C:/Saída João/aula final.mp4"), False)

        EduDownloaderApp._set_last_download_result(fake_app, result)

        self.assertIs(fake_app._last_download_result, result)
        fake_app._set_download_controls.assert_called_once_with()

        EduDownloaderApp._set_last_download_result(fake_app, None)

        self.assertIsNone(fake_app._last_download_result)
        self.assertEqual(fake_app._set_download_controls.call_count, 2)

    def test_download_success_enables_actions_without_opening_anything(self) -> None:
        result = DownloadResult(Path("C:/Saída João/aula final.mp4"), False)
        fake_app = SimpleNamespace(
            _close_requested=False,
            _set_last_download_result=Mock(),
            _set_download_state=Mock(),
            download_details=FakeVariable(),
            progress_bar=Mock(),
            percentage=FakeVariable(),
            status=FakeVariable(),
            _show_info=Mock(),
            _focus_link_entry=Mock(),
        )

        with patch("app.os.startfile") as startfile:
            EduDownloaderApp._finish_download_success(fake_app, result)

        fake_app._set_last_download_result.assert_called_once_with(result)
        fake_app._set_download_state.assert_called_once_with(DownloadUiState.COMPLETED)
        fake_app._show_info.assert_called_once_with(
            'Download concluído: "aula final.mp4".'
        )
        startfile.assert_not_called()

    def test_cancel_and_error_clear_post_download_actions(self) -> None:
        for finish, payload in (
            (EduDownloaderApp._finish_download_cancelled, None),
            (EduDownloaderApp._finish_download_error, object()),
        ):
            with self.subTest(finish=finish.__name__):
                fake_app = SimpleNamespace(
                    _close_requested=True,
                    _set_last_download_result=Mock(),
                    _set_download_state=Mock(),
                    progress_bar=Mock(),
                    percentage=FakeVariable(),
                    download_details=FakeVariable(),
                    status=FakeVariable(),
                    _show_info=Mock(),
                    _show_error=Mock(),
                    _focus_link_entry=Mock(),
                )

                if payload is None:
                    finish(fake_app)
                else:
                    finish(fake_app, payload)

                fake_app._set_last_download_result.assert_called_once_with(None)

    def test_open_actions_use_exact_unicode_result_and_parent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="EduDownloader ações ") as directory:
            output_dir = Path(directory) / "Saída João 你好 com espaços"
            output_dir.mkdir()
            output_path = output_dir / "aula final [720p].mp4"
            output_path.write_bytes(b"fixture")
            result = DownloadResult(output_path, False)
            fake_app = SimpleNamespace(
                _last_download_result=result,
                _set_last_download_result=Mock(),
                _show_warning=Mock(),
                _show_error=Mock(),
            )

            with patch("app.os.startfile") as startfile:
                EduDownloaderApp._open_last_download_file(fake_app)
                EduDownloaderApp._open_last_download_folder(fake_app)

        self.assertEqual(
            startfile.call_args_list,
            [call(output_path), call(output_path.parent)],
        )
        fake_app._set_last_download_result.assert_not_called()
        fake_app._show_warning.assert_not_called()
        fake_app._show_error.assert_not_called()

    def test_removed_result_is_cleared_with_path_free_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            removed_path = Path(directory) / "segredo pessoal" / "aula.mp3"
            result = DownloadResult(removed_path, False)
            for action in (
                EduDownloaderApp._open_last_download_file,
                EduDownloaderApp._open_last_download_folder,
            ):
                with self.subTest(action=action.__name__):
                    fake_app = SimpleNamespace(
                        _last_download_result=result,
                        _set_last_download_result=Mock(),
                        _show_warning=Mock(),
                        _show_error=Mock(),
                    )

                    with patch("app.os.startfile") as startfile:
                        action(fake_app)

                    startfile.assert_not_called()
                    fake_app._set_last_download_result.assert_called_once_with(None)
                    message = fake_app._show_warning.call_args.args[0]
                    self.assertNotIn(str(removed_path), message)
                    self.assertNotIn("segredo pessoal", message)
                    fake_app._show_error.assert_not_called()

    def test_open_failure_preserves_diagnostic_privacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "pasta pessoal" / "arquivo.mp4"
            output_path.parent.mkdir()
            output_path.write_bytes(b"fixture")
            fake_app = SimpleNamespace(
                _last_download_result=DownloadResult(output_path, False),
                _set_last_download_result=Mock(),
                _show_warning=Mock(),
                _show_error=Mock(),
            )

            with patch("app.os.startfile", side_effect=OSError("falha")):
                EduDownloaderApp._open_last_download_file(fake_app)

        message = fake_app._show_error.call_args.args[0]
        self.assertNotIn(str(output_path), message)
        self.assertNotIn("pasta pessoal", message)
        fake_app._set_last_download_result.assert_not_called()

    def test_dialog_state_is_restored_after_modal_closes(self) -> None:
        fake_app = SimpleNamespace(_modal_open=False)
        dialog = Mock(return_value=True)

        result = EduDownloaderApp._show_dialog(
            fake_app, dialog, "Mensagem", title="Título"
        )

        self.assertTrue(result)
        self.assertFalse(fake_app._modal_open)
        dialog.assert_called_once_with("Título", "Mensagem", parent=fake_app)

    def test_late_status_and_progress_are_ignored_after_cancellation(self) -> None:
        fake_app = SimpleNamespace(
            _download_active=True,
            _cancel_requested=True,
            _last_download_result=DownloadResult(Path("Downloads/aula.mp4"), False),
            status=FakeVariable("Cancelando..."),
            _show_progress=Mock(),
        )
        preserved_result = fake_app._last_download_result

        EduDownloaderApp._handle_download_event(
            fake_app,
            DownloadEvent(DownloadEventKind.PHASE, DownloadPhase.DOWNLOADING),
        )
        EduDownloaderApp._handle_download_event(
            fake_app,
            DownloadEvent(
                DownloadEventKind.PROGRESS,
                DownloadProgress(50, 500, 1000, 100, 5),
            ),
        )

        self.assertEqual(fake_app.status.get(), "Cancelando...")
        self.assertIs(fake_app._last_download_result, preserved_result)
        fake_app._show_progress.assert_not_called()

    def test_existing_file_never_sets_progress_to_one_hundred(self) -> None:
        fake_app = SimpleNamespace(
            _set_last_download_result=Mock(),
            _set_download_state=Mock(),
            download_details=FakeVariable(),
            progress_bar=Mock(),
            percentage=FakeVariable(),
            status=FakeVariable(),
            _show_info=Mock(),
            _focus_link_entry=Mock(),
        )

        result = DownloadResult(Path("Downloads/Aula [720p].mp4"), True)
        EduDownloaderApp._finish_download_success(fake_app, result)

        fake_app._set_last_download_result.assert_called_once_with(result)
        fake_app._set_download_state.assert_called_once_with(DownloadUiState.COMPLETED)
        fake_app.progress_bar.set.assert_called_once_with(0)
        self.assertEqual(fake_app.percentage.get(), "—")
        self.assertEqual(fake_app.status.get(), "Arquivo já existente")

    def test_progress_details_omit_unavailable_information(self) -> None:
        self.assertEqual(
            format_progress_details(DownloadProgress(None, None, None, None, None)),
            "",
        )
        self.assertEqual(
            format_progress_details(DownloadProgress(25, 1024, 4096, 512, 10)),
            "1.0 KB de 4.0 KB • 512 B/s • cerca de 10 s restantes",
        )

    def test_download_ui_state_includes_security_verification(self) -> None:
        self.assertEqual(
            list(DownloadUiState),
            [
                DownloadUiState.READY,
                DownloadUiState.PREPARING,
                DownloadUiState.DOWNLOADING,
                DownloadUiState.PROCESSING,
                DownloadUiState.VERIFYING,
                DownloadUiState.COMPLETED,
                DownloadUiState.CANCELLED,
                DownloadUiState.ERROR,
            ],
        )

    def test_each_download_state_has_clear_public_copy(self) -> None:
        expected = {
            DownloadUiState.READY: "Pronto para baixar",
            DownloadUiState.PREPARING: "Preparando o download...",
            DownloadUiState.DOWNLOADING: "Baixando...",
            DownloadUiState.PROCESSING: "Processando o arquivo...",
            DownloadUiState.VERIFYING: "Verificando arquivo...",
            DownloadUiState.COMPLETED: "Download concluído",
            DownloadUiState.CANCELLED: "Download cancelado",
            DownloadUiState.ERROR: "Não foi possível concluir o download",
        }
        fake_app = DownloadUiDouble()

        for state, copy in expected.items():
            with self.subTest(state=state):
                fake_app._set_download_state(state)
                self.assertEqual(fake_app.status.get(), copy)

    def test_active_states_allow_new_requests_and_cancellation(self) -> None:
        for state in (
            DownloadUiState.PREPARING,
            DownloadUiState.DOWNLOADING,
            DownloadUiState.PROCESSING,
        ):
            with self.subTest(state=state):
                fake_app = DownloadUiDouble()
                fake_app._set_download_state(state)

                self.assertTrue(fake_app._download_active)
                fake_app.link_entry.configure.assert_called_with(state="normal")
                fake_app.change_destination_button.configure.assert_called_with(
                    state="normal"
                )
                fake_app.cancel_button.configure.assert_called_with(state="normal")
                fake_app.download_button.configure.assert_called_with(
                    state="normal",
                    text="Adicionar à fila",
                )
                fake_app.downloads_page.set_result_actions_enabled.assert_called_with(
                    False
                )

    def test_terminal_states_restore_controls_and_only_completion_has_actions(
        self,
    ) -> None:
        result = DownloadResult(Path("Downloads/aula.mp4"), False)
        for state in (
            DownloadUiState.READY,
            DownloadUiState.COMPLETED,
            DownloadUiState.CANCELLED,
            DownloadUiState.ERROR,
        ):
            with self.subTest(state=state):
                fake_app = DownloadUiDouble()
                fake_app._last_download_result = result
                fake_app._set_download_state(state)

                self.assertFalse(fake_app._download_active)
                fake_app.link_entry.configure.assert_called_with(state="normal")
                fake_app.change_destination_button.configure.assert_called_with(
                    state="normal"
                )
                fake_app.cancel_button.configure.assert_called_with(state="disabled")
                fake_app.downloads_page.set_result_actions_enabled.assert_called_with(
                    True
                )

    def test_download_and_processing_transitions_work_for_audio_and_video(self) -> None:
        for content_type in (CONTENT_TYPE_AUDIO, CONTENT_TYPE_VIDEO):
            with self.subTest(content_type=content_type):
                fake_app = DownloadUiDouble(DownloadUiState.PREPARING)
                fake_app.content_type.set(content_type)

                fake_app._show_download_phase(DownloadPhase.DOWNLOADING)
                self.assertEqual(
                    fake_app._download_ui_state, DownloadUiState.DOWNLOADING
                )
                fake_app._show_progress(DownloadProgress(72, 34, 48, 12, 30))
                fake_app._show_download_phase(DownloadPhase.PROCESSING)

                self.assertEqual(
                    fake_app._download_ui_state, DownloadUiState.PROCESSING
                )
                self.assertEqual(fake_app.percentage.get(), "—")
                self.assertEqual(fake_app.download_details.get(), "")
                fake_app.progress_bar.set.assert_called_with(0)

    def test_progress_uses_only_metrics_that_are_present(self) -> None:
        cases = (
            (
                DownloadProgress(72, 34 * 1024**2, 48 * 1024**2, 12 * 1024**2, 30),
                "72%",
                "34.0 MB de 48.0 MB • 12.0 MB/s • cerca de 30 s restantes",
                0.72,
            ),
            (
                DownloadProgress(None, 34 * 1024**2, None, None, None),
                "—",
                "34.0 MB baixados",
                0,
            ),
            (DownloadProgress(None, None, None, None, None), "—", "", 0),
        )
        for progress, percent, details, bar_value in cases:
            with self.subTest(progress=progress):
                fake_app = DownloadUiDouble(DownloadUiState.PREPARING)
                fake_app._show_progress(progress)

                self.assertEqual(fake_app.status.get(), "Baixando...")
                self.assertEqual(fake_app.percentage.get(), percent)
                self.assertEqual(fake_app.download_details.get(), details)
                fake_app.progress_bar.set.assert_called_with(bar_value)

    def test_new_preparing_processing_cancel_and_error_clear_old_metrics(self) -> None:
        for state in (
            DownloadUiState.PREPARING,
            DownloadUiState.PROCESSING,
            DownloadUiState.CANCELLED,
            DownloadUiState.ERROR,
        ):
            with self.subTest(state=state):
                fake_app = DownloadUiDouble(DownloadUiState.COMPLETED)
                fake_app.percentage.set("100%")
                fake_app.download_details.set("42 MB de 42 MB")

                fake_app._set_download_state(state)

                self.assertEqual(fake_app.percentage.get(), "—")
                self.assertEqual(fake_app.download_details.get(), "")
                fake_app.progress_bar.set.assert_called_with(0)

    def test_each_terminal_state_allows_adding_next_request(self) -> None:
        for terminal_state in (
            DownloadUiState.COMPLETED,
            DownloadUiState.CANCELLED,
            DownloadUiState.ERROR,
        ):
            with self.subTest(state=terminal_state):
                fake_app = DownloadUiDouble(terminal_state)
                fake_app._last_download_result = DownloadResult(
                    Path("Downloads/anterior.mp4"), False
                )
                fake_app.download_service = SimpleNamespace(
                    is_running=False, start=Mock()
                )
                fake_app.link_entry.get.return_value = "https://example.com/aula"
                fake_app.quality = FakeVariable("720p")
                fake_app._download_destination_dir = None
                fake_app._poll_download_events = Mock()
                fake_app.after = Mock()

                EduDownloaderApp._download(fake_app)

                self.assertEqual(fake_app._download_ui_state, terminal_state)
                self.assertIsNotNone(fake_app._last_download_result)
                self.assertFalse(fake_app._download_active)
                fake_app.download_queue.add.assert_called_once()

    def test_confirmed_completion_is_the_only_path_to_one_hundred_percent(self) -> None:
        progress_app = DownloadUiDouble(DownloadUiState.DOWNLOADING)
        progress_app._show_progress(
            DownloadProgress(100, 48 * 1024**2, 48 * 1024**2, None, 0)
        )
        self.assertEqual(progress_app.percentage.get(), "—")
        progress_app.progress_bar.set.assert_called_with(0)

        fake_app = DownloadUiDouble(DownloadUiState.DOWNLOADING)
        fake_app._show_info = Mock()
        fake_app._focus_link_entry = Mock()
        result = DownloadResult(Path("Downloads/aula.mp4"), False)

        EduDownloaderApp._finish_download_success(fake_app, result)

        self.assertEqual(fake_app._download_ui_state, DownloadUiState.COMPLETED)
        self.assertEqual(fake_app.status.get(), "Download concluído")
        self.assertEqual(fake_app.percentage.get(), "100%")
        fake_app.progress_bar.set.assert_called_with(1)
        fake_app.downloads_page.set_result_actions_enabled.assert_called_with(True)

    def test_existing_file_uses_completed_state_without_fabricated_progress(
        self,
    ) -> None:
        fake_app = DownloadUiDouble(DownloadUiState.PREPARING)
        fake_app._show_info = Mock()
        fake_app._focus_link_entry = Mock()

        EduDownloaderApp._finish_download_success(
            fake_app,
            DownloadResult(Path("Downloads/aula.mp4"), True),
        )

        self.assertEqual(fake_app._download_ui_state, DownloadUiState.COMPLETED)
        self.assertEqual(fake_app.status.get(), "Arquivo já existente")
        self.assertEqual(fake_app.percentage.get(), "—")
        fake_app.progress_bar.set.assert_called_with(0)
        fake_app._show_info.assert_called_once_with(
            'O arquivo "aula.mp4" já está na pasta de destino.'
        )

    def test_cancel_and_error_finish_in_typed_terminal_states(self) -> None:
        cases = (
            (
                DownloadUiState.CANCELLED,
                lambda fake_app: EduDownloaderApp._finish_download_cancelled(fake_app),
            ),
            (
                DownloadUiState.ERROR,
                lambda fake_app: EduDownloaderApp._finish_download_error(
                    fake_app, object()
                ),
            ),
        )
        for expected_state, finish in cases:
            with self.subTest(state=expected_state):
                fake_app = DownloadUiDouble(DownloadUiState.DOWNLOADING)
                fake_app.percentage.set("87%")
                fake_app.download_details.set("dados antigos")
                fake_app._show_info = Mock()
                fake_app._show_error = Mock()
                fake_app._focus_link_entry = Mock()

                finish(fake_app)

                self.assertEqual(fake_app._download_ui_state, expected_state)
                self.assertEqual(fake_app.percentage.get(), "—")
                self.assertEqual(fake_app.download_details.get(), "")
                fake_app.downloads_page.set_result_actions_enabled.assert_called_with(
                    False
                )

    def test_untyped_completion_payload_becomes_error_without_actions(self) -> None:
        fake_app = DownloadUiDouble(DownloadUiState.DOWNLOADING)
        fake_app._show_error = Mock()
        fake_app._focus_link_entry = Mock()

        EduDownloaderApp._finish_download_success(fake_app, object())

        self.assertEqual(fake_app._download_ui_state, DownloadUiState.ERROR)
        self.assertIsNone(fake_app._last_download_result)
        self.assertEqual(fake_app.percentage.get(), "—")
        fake_app.downloads_page.set_result_actions_enabled.assert_called_with(False)

    def test_clear_preserves_completed_result_actions(self) -> None:
        fake_app = DownloadUiDouble(DownloadUiState.COMPLETED)
        result = DownloadResult(Path("Downloads/aula.mp4"), False)
        fake_app._last_download_result = result
        fake_app.status.set("Download concluído")
        fake_app.link_entry = Mock()
        fake_app._focus_link_entry = Mock()

        EduDownloaderApp._clear_link(fake_app)

        self.assertEqual(fake_app._download_ui_state, DownloadUiState.COMPLETED)
        self.assertIs(fake_app._last_download_result, result)
        self.assertEqual(fake_app.status.get(), "Download concluído")

    def test_late_events_cannot_resurrect_a_terminal_state(self) -> None:
        for terminal_state in (
            DownloadUiState.READY,
            DownloadUiState.CANCELLED,
            DownloadUiState.ERROR,
        ):
            with self.subTest(state=terminal_state):
                fake_app = DownloadUiDouble(terminal_state)
                fake_app.status.set("estado terminal preservado")
                fake_app._handle_download_event(
                    DownloadEvent(
                        DownloadEventKind.PHASE,
                        DownloadPhase.DOWNLOADING,
                    )
                )
                fake_app._handle_download_event(
                    DownloadEvent(
                        DownloadEventKind.COMPLETED,
                        DownloadResult(Path("Downloads/antigo.mp4"), False),
                    )
                )

                self.assertEqual(fake_app._download_ui_state, terminal_state)
                self.assertEqual(fake_app.status.get(), "estado terminal preservado")
                self.assertIsNone(fake_app._last_download_result)

    def test_error_feedback_never_uses_private_details(self) -> None:
        marker = "TOKEN-PRIVADO-NAO-EXIBIR"
        fake_app = DownloadUiDouble(DownloadUiState.DOWNLOADING)
        fake_app._set_last_download_result = Mock()
        fake_app._show_error = Mock()
        fake_app._focus_link_entry = Mock()
        error = DownloadServiceError(
            "Não foi possível acessar o conteúdo.",
            f"--flag https://example.invalid/aula?token={marker} C:/Users/Pessoa/arquivo",
        )

        EduDownloaderApp._finish_download_error(fake_app, error)

        public_text = " ".join(
            (
                fake_app.status.get(),
                fake_app.percentage.get(),
                fake_app.download_details.get(),
                fake_app._show_error.call_args.args[0],
            )
        )
        self.assertNotIn(marker, public_text)
        self.assertNotIn("example.invalid", public_text)
        self.assertNotIn("C:/Users", public_text)
        self.assertNotIn("--flag", public_text)
        self.assertEqual(fake_app._download_ui_state, DownloadUiState.ERROR)

    def test_documents_result_actions_are_safe_and_missing_output_is_controlled(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            output = Path(temporary_dir) / "Ação 你好.pdf"
            output.write_bytes(b"%PDF")
            fake_app = SimpleNamespace(
                _show_warning=Mock(),
                _show_error=Mock(),
            )
            with patch("app.os.startfile") as startfile:
                self.assertTrue(
                    EduDownloaderApp._open_documents_result_file(fake_app, output)
                )
                self.assertTrue(
                    EduDownloaderApp._open_documents_result_folder(fake_app, output)
                )
            self.assertEqual(
                [call.args[0] for call in startfile.call_args_list],
                [output, output.parent],
            )

            output.unlink()
            self.assertFalse(
                EduDownloaderApp._open_documents_result_file(fake_app, output)
            )
            self.assertFalse(
                EduDownloaderApp._open_documents_result_folder(fake_app, output)
            )
            self.assertEqual(fake_app._show_warning.call_count, 2)

    def test_documents_component_path_persistence_is_explicit_and_reversible(
        self,
    ) -> None:
        fake_app = SimpleNamespace(
            settings={"documents_component_path": None},
            _save_preferences=Mock(return_value=True),
        )
        selected = Path(r"C:\Componente Documentos\Ação 你好")

        self.assertTrue(
            EduDownloaderApp._persist_documents_component_path(fake_app, selected)
        )
        self.assertEqual(fake_app.settings["documents_component_path"], str(selected))
        self.assertTrue(
            EduDownloaderApp._persist_documents_component_path(fake_app, None)
        )
        self.assertIsNone(fake_app.settings["documents_component_path"])


class AppShellRealTkTests(unittest.TestCase):
    def test_real_download_quality_menu_switches_without_using_video_setting(
        self,
    ) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import logging
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    from app import DownloadUiState, EduDownloaderApp
                    from constants import CONTENT_TYPE_AUDIO, CONTENT_TYPE_VIDEO, VIDEO_QUALITIES
                    from downloader import DownloadService
                    from mp3_quality import MP3_QUALITY_OPTIONS, Mp3Quality
                    from settings import default_settings

                    logger = logging.getLogger("real-mp3-quality-test")
                    logger.handlers = [logging.NullHandler()]
                    logger.propagate = False
                    settings = default_settings()
                    settings["ultimo_tipo"] = CONTENT_TYPE_AUDIO
                    settings["ultima_qualidade"] = "720p"
                    with tempfile.TemporaryDirectory() as directory:
                        service = DownloadService(Path(directory), logger)
                        try:
                            with (
                                patch("app.load_settings", return_value=settings),
                                patch("app.save_settings", side_effect=lambda data: data),
                            ):
                                window = EduDownloaderApp(service)
                        except tk.TclError as error:
                            service.close()
                            print(f"SKIP_TK:{type(error).__name__}")
                            raise SystemExit(0)
                        window.withdraw()
                        window.update_idletasks()
                        result = {
                            "audio_values": window.quality_menu.cget("values"),
                            "audio_default": window.quality_menu.get(),
                            "video_preference": window.quality.get(),
                            "audio_enabled": window.quality_menu.cget("state"),
                        }
                        window.quality_menu.set(Mp3Quality.HIGH.display_label)
                        window.content_type.set(CONTENT_TYPE_VIDEO)
                        window._adapt_quality_controls(save=False)
                        result["video_values"] = window.quality_menu.cget("values")
                        result["video_selected"] = window.quality_menu.get()
                        window.content_type.set(CONTENT_TYPE_AUDIO)
                        window._adapt_quality_controls(save=False)
                        result["audio_restored"] = window.quality_menu.get()
                        window._set_download_state(DownloadUiState.PREPARING)
                        result["active_state"] = window.quality_menu.cget("state")
                        window._set_download_state(DownloadUiState.CANCELLED)
                        result["terminal_state"] = window.quality_menu.cget("state")
                        result["video_preference_final"] = window.quality.get()
                        window._close_requested = True
                        window._adapt_quality_controls(save=False)
                        result["closing_state"] = window.quality_menu.cget("state")
                        assert window.download_queue.shutdown(timeout=2)
                        window.destroy()
                        service.close()
                        print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertEqual(
            result["audio_values"],
            [profile.display_label for profile in MP3_QUALITY_OPTIONS],
        )
        self.assertEqual(result["audio_default"], "Padrão — 192 kbps")
        self.assertEqual(result["video_preference"], "720p")
        self.assertEqual(result["audio_enabled"], "normal")
        self.assertEqual(result["video_values"], list(app.VIDEO_QUALITIES))
        self.assertEqual(result["video_selected"], "720p")
        self.assertEqual(result["audio_restored"], "Alta — 320 kbps")
        self.assertEqual(result["active_state"], "normal")
        self.assertEqual(result["terminal_state"], "normal")
        self.assertEqual(result["closing_state"], "disabled")
        self.assertEqual(result["video_preference_final"], "720p")

    def test_real_shell_opens_and_keeps_one_download_page_and_service(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import logging
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    import customtkinter as ctk

                    from app import (
                        DownloadUiState,
                        NAVIGATION_PAGES,
                        PAGE_DOWNLOADS,
                        PAGE_FILES,
                        PAGE_HOME,
                        PAGE_DOCUMENTS,
                        PAGE_MEDIA,
                        PAGE_PDF,
                        PAGE_SETTINGS,
                        EduDownloaderApp,
                    )
                    from downloader import DownloadService
                    from settings import default_settings

                    logger = logging.getLogger("real-shell-test")
                    logger.handlers = [logging.NullHandler()]
                    logger.propagate = False
                    with tempfile.TemporaryDirectory() as temporary_dir:
                        service = DownloadService(Path(temporary_dir), logger)
                        try:
                            with (
                                patch("app.load_settings", return_value=default_settings()),
                                patch("app.save_settings", side_effect=lambda data: data),
                            ):
                                window = EduDownloaderApp(service)
                        except tk.TclError as error:
                            service.close()
                            print(f"SKIP_TK:{type(error).__name__}")
                            raise SystemExit(0)
                        window.withdraw()
                        window.update_idletasks()
                        service_id = id(window.download_service)
                        home_page = window._pages[PAGE_HOME]
                        page_id = id(window._pages[PAGE_DOWNLOADS])
                        files_page_id = id(window._pages[PAGE_FILES])
                        pdf_page_id = id(window._pages[PAGE_PDF])
                        documents_page_id = id(window._pages[PAGE_DOCUMENTS])
                        media_page_id = id(window._pages[PAGE_MEDIA])
                        window._pages[PAGE_PDF].merge_files.set_paths(
                            [Path("primeiro.pdf"), Path("segundo.pdf")]
                        )
                        window._pages[PAGE_FILES]._query.set("prova")
                        initial_page = window._current_page
                        initial_download_state = window._download_ui_state.value
                        initial_download_status = window.status.get()
                        home_shortcuts = list(home_page.module_buttons)
                        shortcut_pages = []
                        for button in home_page.module_buttons.values():
                            button.invoke()
                            shortcut_pages.append(window._current_page)
                        window._set_download_state(DownloadUiState.DOWNLOADING)
                        window._show_page(PAGE_DOWNLOADS)
                        window._show_page(PAGE_HOME)
                        window._show_page(PAGE_DOWNLOADS)

                        def descendants(widget):
                            result = []
                            for child in widget.winfo_children():
                                result.append(child)
                                result.extend(descendants(child))
                            return result

                        selected_pages = []
                        for page_name in NAVIGATION_PAGES:
                            window._show_page(page_name)
                            selected_pages.append(window._current_page)
                        settings_page = window._pages[PAGE_SETTINGS]
                        settings_page.show_persistence_error(
                            "Preferência não persistida."
                        )
                        settings_feedback = settings_page._persistence_status.get()
                        settings_page.clear_persistence_feedback()
                        settings_feedback_cleared = (
                            settings_page._persistence_status.get()
                        )
                        pdf_page = window._pages[PAGE_PDF]
                        pdf_landing = (
                            pdf_page.tool_picker.winfo_manager() == "grid"
                            and pdf_page.tab_view.winfo_manager() == ""
                            and len(pdf_page.tool_cards) == 6
                        )
                        pdf_page.tool_cards["Juntar PDFs"].invoke()
                        pdf_tool_opened = (
                            pdf_page.tab_view.winfo_manager() == "grid"
                            and pdf_page.tab_view.get() == "Juntar PDFs"
                            and pdf_page.tab_view._segmented_button.winfo_manager() == ""
                        )
                        pdf_page._busy = True
                        pdf_page._working_tool = "Juntar PDFs"
                        pdf_page._refresh_controls()
                        pdf_back_enabled_during_work = (
                            pdf_page.tool_back_button.cget("state") == "normal"
                        )
                        pdf_page.tool_back_button.invoke()
                        pdf_returned_during_work = (
                            pdf_page.is_busy
                            and pdf_page.tool_picker.winfo_manager() == "grid"
                            and pdf_page.tab_view.winfo_manager() == ""
                            and pdf_page._pdf_status_frame.winfo_manager() == ""
                        )
                        pdf_page.tool_cards["Juntar PDFs"].invoke()
                        pdf_reopened_during_work = (
                            pdf_page.is_busy
                            and pdf_page.progress_bar.winfo_manager() == "grid"
                            and pdf_page.merge_select_button.cget("state") == "disabled"
                        )
                        pdf_page._busy = False
                        pdf_page._working_tool = None
                        pdf_page._refresh_controls()
                        pdf_page.tool_back_button.invoke()
                        pdf_returned = pdf_page.tool_picker.winfo_manager() == "grid"
                        documents_page = window._pages[PAGE_DOCUMENTS]
                        documents_hub = (
                            documents_page.tool_picker.winfo_manager() == "grid"
                            and documents_page.component_card.winfo_manager() == "grid"
                            and documents_page.conversion_card.winfo_manager() == ""
                        )
                        document_hub_labels = [
                            button.cget("text")
                            for button in documents_page.tool_cards.values()
                        ]
                        documents_page.tool_cards["TXT → PDF"].invoke()
                        document_card_selected = (
                            documents_page.operation.value == "TXT"
                            and len(documents_page.tool_cards) == 3
                            and documents_page.conversion_card.winfo_manager() == "grid"
                            and documents_page.tool_picker.winfo_manager() == ""
                        )
                        documents_page.tool_back_button.invoke()
                        documents_returned = (
                            documents_page.tool_picker.winfo_manager() == "grid"
                            and documents_page.conversion_card.winfo_manager() == ""
                        )
                        window._show_page(PAGE_DOWNLOADS)
                        result = {
                            "initial_page": initial_page,
                            "initial_download_state": initial_download_state,
                            "initial_download_status": initial_download_status,
                            "current_page": window._current_page,
                            "page_count": len(window._pages),
                            "navigation_count": len(NAVIGATION_PAGES),
                            "home_recent": home_page.recent.cget("text"),
                            "home_shortcuts": home_shortcuts,
                            "shortcut_pages": shortcut_pages,
                            "brand_fits_sidebar": (
                                window.sidebar.branding.winfo_reqwidth() + 24 <= 232
                            ),
                            "window_icon_applied": window._window_icon_applied,
                            "window_icon_sizes": len(window._window_icons),
                            "sidebar_color": window.sidebar.cget("fg_color"),
                            "pdf_landing": pdf_landing,
                            "pdf_tool_opened": pdf_tool_opened,
                            "pdf_back_enabled_during_work": pdf_back_enabled_during_work,
                            "pdf_returned_during_work": pdf_returned_during_work,
                            "pdf_reopened_during_work": pdf_reopened_during_work,
                            "pdf_returned": pdf_returned,
                            "document_card_selected": document_card_selected,
                            "documents_hub": documents_hub,
                            "document_hub_labels": document_hub_labels,
                            "document_hub_labels_after_return": [
                                button.cget("text")
                                for button in documents_page.tool_cards.values()
                            ],
                            "documents_returned": documents_returned,
                            "settings_components_grouped": (
                                settings_page.update_check_button.master.master
                                is settings_page.component_status_labels["yt-dlp"].master
                                and settings_page.libreoffice_install_button.master.master
                                is settings_page.component_status_labels["libreoffice"].master
                            ),
                            "files_scrollable": hasattr(
                                window._pages[PAGE_FILES], "_parent_canvas"
                            ),
                            "all_pages_scrollable": all(
                                hasattr(page, "_parent_canvas")
                                for page in window._pages.values()
                            ),
                            "download_status_separate": (
                                window.downloads_page.progress_bar.master.master
                                is window.downloads_page
                            ),
                            "same_service": id(window.download_service) == service_id,
                            "same_download_page": (
                                id(window._pages[PAGE_DOWNLOADS]) == page_id
                            ),
                            "same_files_page": (
                                id(window._pages[PAGE_FILES]) == files_page_id
                            ),
                            "same_pdf_page": id(window._pages[PAGE_PDF]) == pdf_page_id,
                            "same_documents_page": (
                                id(window._pages[PAGE_DOCUMENTS])
                                == documents_page_id
                            ),
                            "same_media_page": (
                                id(window._pages[PAGE_MEDIA]) == media_page_id
                            ),
                            "pdf_selection": [
                                path.name
                                for path in window._pages[PAGE_PDF].merge_files.paths
                            ],
                            "status": window.status.get(),
                            "link_exists": bool(window.link_entry.winfo_exists()),
                            "destination_is_default": (
                                window.downloads_page.destination_text.get()
                                == "Downloads (padrão)"
                            ),
                            "destination_state_is_none": (
                                window._download_destination_dir is None
                            ),
                            "destination_button_text": (
                                window.change_destination_button.cget("text")
                            ),
                            "open_file_button_text": (
                                window.open_result_file_button.cget("text")
                            ),
                            "open_folder_button_text": (
                                window.open_result_folder_button.cget("text")
                            ),
                            "result_actions_initially_disabled": (
                                window.open_result_file_button.cget("state")
                                == "disabled"
                                and window.open_result_folder_button.cget("state")
                                == "disabled"
                            ),
                            "destination_wraplength": (
                                window.downloads_page.destination_label.cget(
                                    "wraplength"
                                )
                            ),
                            "title_has_version": "2.0.0" in window.title(),
                            "title": window.title(),
                            "pdf_is_functional": not window._pages[
                                PAGE_PDF
                            ].is_placeholder,
                            "pdf_tool_names": list(
                                window._pages[PAGE_PDF].tool_names
                            ),
                            "media_is_functional": not window._pages[
                                PAGE_MEDIA
                            ].is_placeholder,
                            "media_tool_names": list(
                                window._pages[PAGE_MEDIA].tool_names
                            ),
                            "documents_is_functional": not window._pages[
                                PAGE_DOCUMENTS
                            ].is_placeholder,
                            "documents_tool_names": list(
                                window._pages[PAGE_DOCUMENTS].tool_names
                            ),
                            "files_is_functional": not window._pages[
                                PAGE_FILES
                            ].is_placeholder,
                            "files_choose_text": window._pages[
                                PAGE_FILES
                            ].choose_button.cget("text"),
                            "files_query": window._pages[PAGE_FILES]._query.get(),
                            "selected_pages": selected_pages,
                            "settings_feedback": settings_feedback,
                            "settings_feedback_cleared": settings_feedback_cleared,
                            "settings_has_version_label": hasattr(
                                settings_page, "version_label"
                            ),
                        }
                        window._download_destination_dir = Path(
                            "C:/Destino temporário da sessão"
                        )
                        window._set_download_state(DownloadUiState.READY)
                        assert window.download_queue.shutdown(timeout=2)
                        window.destroy()
                        service.close()
                        restart_service = DownloadService(Path(temporary_dir), logger)
                        restart_window = EduDownloaderApp(restart_service)
                        result["restart_destination_is_default"] = (
                            restart_window._download_destination_dir is None
                            and restart_window.downloads_page.destination_text.get()
                            == "Downloads (padrão)"
                        )
                        assert restart_window.download_queue.shutdown(timeout=2)
                        restart_window.destroy()
                        restart_service.close()
                        print(json.dumps(result, ensure_ascii=True))
                    """
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertEqual(result["initial_page"], PAGE_HOME)
        self.assertEqual(result["initial_download_state"], "ready")
        self.assertEqual(
            result["initial_download_status"], "Fila: 0 aguardando • 0 finalizados"
        )
        self.assertEqual(result["current_page"], PAGE_DOWNLOADS)
        self.assertEqual(result["page_count"], 8)
        self.assertEqual(result["navigation_count"], 5)
        self.assertIn("pasta que você escolher", result["home_recent"])
        self.assertEqual(
            result["home_shortcuts"],
            [
                PAGE_DOWNLOADS,
                PAGE_PDF,
                PAGE_DOCUMENTS,
                PAGE_MEDIA,
                PAGE_FILES,
            ],
        )
        self.assertEqual(result["shortcut_pages"], result["home_shortcuts"])
        self.assertTrue(result["brand_fits_sidebar"])
        self.assertTrue(result["window_icon_applied"])
        self.assertEqual(result["window_icon_sizes"], 3)
        self.assertEqual(result["sidebar_color"], ["#153651", "#0B2234"])
        self.assertTrue(result["pdf_landing"])
        self.assertTrue(result["pdf_tool_opened"])
        self.assertTrue(result["pdf_back_enabled_during_work"])
        self.assertTrue(result["pdf_returned_during_work"])
        self.assertTrue(result["pdf_reopened_during_work"])
        self.assertTrue(result["pdf_returned"])
        self.assertTrue(result["document_card_selected"])
        self.assertTrue(result["documents_hub"])
        self.assertEqual(result["document_hub_labels"], ["Abrir ferramenta"] * 3)
        self.assertEqual(
            result["document_hub_labels_after_return"], ["Abrir ferramenta"] * 3
        )
        self.assertTrue(result["documents_returned"])
        self.assertTrue(result["settings_components_grouped"])
        self.assertTrue(result["files_scrollable"])
        self.assertTrue(result["all_pages_scrollable"])
        self.assertTrue(result["download_status_separate"])
        self.assertTrue(result["same_service"])
        self.assertTrue(result["same_download_page"])
        self.assertTrue(result["same_files_page"])
        self.assertTrue(result["same_pdf_page"])
        self.assertTrue(result["same_documents_page"])
        self.assertTrue(result["same_media_page"])
        self.assertEqual(result["pdf_selection"], ["primeiro.pdf", "segundo.pdf"])
        self.assertEqual(result["status"], "Baixando...")
        self.assertTrue(result["link_exists"])
        self.assertTrue(result["destination_is_default"])
        self.assertTrue(result["destination_state_is_none"])
        self.assertTrue(result["restart_destination_is_default"])
        self.assertEqual(result["destination_button_text"], "Alterar pasta")
        self.assertEqual(result["open_file_button_text"], "Abrir arquivo")
        self.assertEqual(result["open_folder_button_text"], "Abrir pasta")
        self.assertTrue(result["result_actions_initially_disabled"])
        self.assertGreater(result["destination_wraplength"], 0)
        self.assertFalse(result["title_has_version"])
        self.assertEqual(result["title"], "EduDownloader")
        self.assertTrue(result["pdf_is_functional"])
        self.assertEqual(
            result["pdf_tool_names"],
            [
                "Juntar PDFs",
                "Extrair páginas",
                "Imagens → PDF",
                "PDF → Imagens",
                "Pôster/Painel",
                "PDF para Word",
            ],
        )
        self.assertTrue(result["media_is_functional"])
        self.assertEqual(result["media_tool_names"], ["Extrair áudio do vídeo"])
        self.assertTrue(result["documents_is_functional"])
        self.assertEqual(
            result["documents_tool_names"],
            ["Word para PDF", "Texto para PDF", "OpenDocument para PDF"],
        )
        self.assertTrue(result["files_is_functional"])
        self.assertEqual(result["files_choose_text"], "Escolher pasta")
        self.assertEqual(result["files_query"], "prova")
        self.assertEqual(result["selected_pages"], list(NAVIGATION_PAGES))
        self.assertEqual(result["settings_feedback"], "Preferência não persistida.")
        self.assertEqual(result["settings_feedback_cleared"], "")
        self.assertFalse(result["settings_has_version_label"])


if __name__ == "__main__":
    unittest.main()
