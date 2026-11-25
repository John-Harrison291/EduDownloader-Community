"""Contrato central de apresentação das páginas persistentes do shell."""

import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import (
    DownloadUiState,
    EduDownloaderApp,
    NAVIGATION_PAGES,
    PAGE_DOCUMENTS,
    PAGE_DOWNLOADS,
    PAGE_FILES,
    PAGE_HOME,
    PAGE_MEDIA,
    PAGE_PDF,
    PAGE_SETTINGS,
    PAGE_TOOLS,
    _NAVIGATION_SELECTED_COLOR,
)
from ui_design import NAV_HOVER, ON_PRIMARY, PRIMARY_HOVER, SIDEBAR_TEXT


class NavigationTests(unittest.TestCase):
    def shell(self):
        events = []
        pages = {}
        mapped = {PAGE_HOME}
        for name in (*NAVIGATION_PAGES, PAGE_PDF, PAGE_DOCUMENTS, PAGE_MEDIA):
            page = Mock()

            def show(n=name, **_options):
                self.assertFalse(mapped, "old page must be unmapped BEFORE grid")
                mapped.add(n)
                events.append((n, "grid"))

            def hide(n=name):
                mapped.discard(n)
                events.append((n, "grid_forget"))

            page.grid.side_effect = show
            page.grid_forget.side_effect = hide
            pages[name] = page
        shell = SimpleNamespace(
            _pages=pages,
            _navigation_buttons={name: Mock() for name in NAVIGATION_PAGES},
            _current_page=PAGE_HOME,
            documents_page=pages[PAGE_DOCUMENTS],
            _download_active=False,
            link_entry=Mock(),
            after=Mock(
                side_effect=AssertionError("navigation must not schedule timers")
            ),
            after_idle=Mock(
                side_effect=AssertionError("navigation must not defer work")
            ),
            update=Mock(side_effect=AssertionError("navigation must not pump events")),
            update_idletasks=Mock(
                side_effect=AssertionError("navigation must not pump idle events")
            ),
            mapped=mapped,
        )
        return shell, events

    def test_unmap_before_map_without_pumping_events_or_scheduling_navigation(self):
        shell, events = self.shell()
        EduDownloaderApp._show_page(shell, PAGE_DOWNLOADS)
        self.assertEqual(
            events,
            [
                (PAGE_HOME, "grid_forget"),
                (PAGE_DOWNLOADS, "grid"),
            ],
        )
        self.assertEqual(shell._current_page, PAGE_DOWNLOADS)
        for name, button in shell._navigation_buttons.items():
            button.configure.assert_called_with(
                fg_color=(
                    _NAVIGATION_SELECTED_COLOR
                    if name == PAGE_DOWNLOADS
                    else "transparent"
                ),
                text_color=ON_PRIMARY if name == PAGE_DOWNLOADS else SIDEBAR_TEXT,
                hover_color=PRIMARY_HOVER if name == PAGE_DOWNLOADS else NAV_HOVER,
            )
        shell._pages[PAGE_DOWNLOADS].tkraise.assert_not_called()
        for page in shell._pages.values():
            for method in (
                "lift",
                "lower",
                "update",
                "update_idletasks",
                "after",
                "after_idle",
            ):
                getattr(page, method).assert_not_called()
        self.assertEqual(shell.mapped, {PAGE_DOWNLOADS})
        shell.link_entry.focus_set.assert_called_once()

    def test_reentrant_preparation_presents_only_latest_destination(self):
        shell, _ = self.shell()

        def redirect():
            self.assertFalse(shell.mapped)
            self.assertIsNone(shell._current_page)
            for button in shell._navigation_buttons.values():
                button.configure.assert_not_called()
            EduDownloaderApp._show_page(shell, PAGE_PDF)
            EduDownloaderApp._show_page(shell, PAGE_DOWNLOADS)

        shell.documents_page.on_show.side_effect = redirect
        EduDownloaderApp._show_page(shell, PAGE_DOCUMENTS)
        shell._pages[PAGE_DOCUMENTS].grid.assert_not_called()
        shell._pages[PAGE_PDF].grid.assert_not_called()
        shell.documents_page.on_show.assert_called_once()
        self.assertEqual(shell._current_page, PAGE_DOWNLOADS)
        self.assertEqual(shell.mapped, {PAGE_DOWNLOADS})
        self.assertFalse(shell._navigation_in_progress)
        self.assertIsNone(shell._pending_page)

    def test_preparation_error_restores_previous_page_and_sidebar(self):
        shell, _ = self.shell()
        shell.documents_page.on_show.side_effect = RuntimeError("layout")
        with self.assertRaisesRegex(RuntimeError, "layout"):
            EduDownloaderApp._show_page(shell, PAGE_DOCUMENTS)
        self.assertEqual(shell._current_page, PAGE_HOME)
        self.assertEqual(shell.mapped, {PAGE_HOME})
        self.assertFalse(shell._navigation_in_progress)
        self.assertIsNone(shell._pending_page)
        shell._navigation_buttons[PAGE_HOME].configure.assert_called_with(
            fg_color=_NAVIGATION_SELECTED_COLOR,
            text_color=ON_PRIMARY,
            hover_color=PRIMARY_HOVER,
        )
        EduDownloaderApp._show_page(shell, PAGE_PDF)
        self.assertEqual(shell.mapped, {PAGE_PDF})

    def test_grid_error_restores_previous_page(self):
        shell, _ = self.shell()
        shell._pages[PAGE_PDF].grid.side_effect = RuntimeError("grid")
        with self.assertRaisesRegex(RuntimeError, "grid"):
            EduDownloaderApp._show_page(shell, PAGE_PDF)
        self.assertEqual(shell.mapped, {PAGE_HOME})
        self.assertEqual(shell._current_page, PAGE_HOME)
        self.assertFalse(shell._navigation_in_progress)

    def test_same_page_does_not_unmap_or_relayout(self):
        shell, events = self.shell()
        EduDownloaderApp._show_page(shell, PAGE_HOME)
        self.assertEqual(events, [])

    def test_duplicate_documents_does_not_restart_preparation(self):
        shell, events = self.shell()
        EduDownloaderApp._show_page(shell, PAGE_DOCUMENTS)
        events.clear()
        EduDownloaderApp._show_page(shell, PAGE_DOCUMENTS)
        self.assertEqual(events, [])
        shell.documents_page.on_show.assert_called_once()

    def test_duplicate_reentrant_request_does_not_loop(self):
        shell, _ = self.shell()
        shell.documents_page.on_show.side_effect = lambda: EduDownloaderApp._show_page(
            shell, PAGE_DOCUMENTS
        )
        EduDownloaderApp._show_page(shell, PAGE_DOCUMENTS)
        shell.documents_page.on_show.assert_called_once()
        self.assertEqual(shell.mapped, {PAGE_DOCUMENTS})

    def test_shutdown_rejects_navigation(self):
        shell, events = self.shell()
        shell._close_requested = True
        EduDownloaderApp._show_page(shell, PAGE_DOWNLOADS)
        self.assertEqual(events, [])
        self.assertEqual(shell._current_page, PAGE_HOME)

    def test_first_page_is_presented_immediately(self):
        shell, events = self.shell()
        shell._current_page = None
        shell.mapped.clear()
        EduDownloaderApp._show_page(shell, PAGE_HOME)
        self.assertEqual(events, [(PAGE_HOME, "grid")])
        self.assertEqual(shell._current_page, PAGE_HOME)
        self.assertEqual(shell.mapped, {PAGE_HOME})

    def test_rapid_navigation_finishes_each_request_without_timers(self):
        shell, _ = self.shell()
        pages = dict(shell._pages)
        shell.download_service = object()
        service = shell.download_service
        shell._download_active = True
        shell.status = "Baixando..."
        for _ in range(20):
            for name in NAVIGATION_PAGES:
                EduDownloaderApp._show_page(shell, name)
                self.assertEqual(shell._current_page, name)
                self.assertEqual(shell.mapped, {name})
                self.assertFalse(shell._navigation_in_progress)
                self.assertIsNone(shell._pending_page)
                self.assertIs(shell._pages[name], pages[name])
        self.assertIs(shell.download_service, service)
        self.assertTrue(shell._download_active)
        self.assertEqual(shell.status, "Baixando...")
        shell.link_entry.focus_set.assert_not_called()
        for method in ("after", "after_idle", "update", "update_idletasks"):
            getattr(shell, method).assert_not_called()

    def test_real_scrollable_shell_all_routes_themes_and_subtools(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from tests.test_navigation import real_navigation_probe; "
                "import json; print(json.dumps(real_navigation_probe()))",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        if "skip" in report:
            self.skipTest(report["skip"])
        self.assertEqual(report["swaps"], 60)
        self.assertEqual(report["themes"], ["Light", "Dark"])
        self.assertTrue(report["scroll_preserved"])
        self.assertTrue(report["subtool_preserved"])
        self.assertEqual(report["max_mapped_pages"], 1)
        self.assertGreater(report["mapping_observations"], 60)
        self.assertTrue(report["fast_routes"])
        self.assertTrue(report["scaling_preserved"])
        self.assertTrue(report["close_passed"])
        self.assertTrue(report["no_transition_callbacks"])
        self.assertTrue(report["fields_preserved"])
        self.assertTrue(report["background_progress_preserved"])
        self.assertEqual(report["download_layout_variants"], 4)
        self.assertEqual(report["tool_swaps"], 48)
        self.assertTrue(report["tool_layout_preserved"])


def real_navigation_probe():
    """Testa também a superfície externa real, não só o frame dentro do canvas."""
    import tkinter as tk

    import customtkinter as ctk

    from constants import CONTENT_TYPE_AUDIO, CONTENT_TYPE_VIDEO, VIDEO_QUALITIES
    from dataclasses import replace
    from download_queue import QueueItem, QueueState
    from downloader import DownloadProgress, DownloadRequest, DownloadService
    from mp3_quality import MP3_QUALITY_OPTIONS
    from settings import default_settings

    logger = logging.getLogger("navigation-regression")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    with tempfile.TemporaryDirectory() as directory:
        service = DownloadService(Path(directory), logger)
        try:
            with (
                patch("app.load_settings", return_value=default_settings()),
                patch("app.save_settings", side_effect=lambda data: data),
            ):
                window = EduDownloaderApp(service)
            # The scenario changes PDF preferences after construction. Keep its
            # persistence inside the fixture throughout navigation as well.
            window.pdf_page._persist_pdf_callback = lambda values: True
        except tk.TclError as error:
            service.close()
            return {"skip": str(error)}
        try:
            window.update()
            if window.state() == "zoomed":
                window.state("normal")
            window.geometry("860x600")
            window.documents_page.on_show = Mock()
            window.update()
            link = "https://example.org/material-de-aula"
            window.link_entry.insert(0, link)
            identities = {name: id(page) for name, page in window._pages.items()}
            swaps = 0
            observations = []
            assert not hasattr(window, "_page_transition")
            assert not hasattr(window, "_transition_overlay")
            callback_errors = []
            window.report_callback_exception = lambda *error: callback_errors.append(
                error
            )

            def settle():
                # Apenas processar a pintura real; a seleção já deve estar pronta.
                window.update()
                assert not window._navigation_in_progress
                assert window._pending_page is None
                assert not callback_errors, callback_errors

            def visible_owner():
                page = window._pages[window._current_page]
                outer = page._parent_frame
                frames = {page._parent_frame for page in window._pages.values()}
                mapped = [
                    frame
                    for frame in window._page_host.winfo_children()
                    if frame in frames and frame.winfo_ismapped()
                ]
                observations.append(len(mapped))
                return (
                    bool(mapped)
                    and mapped[-1] is outer
                    and outer.winfo_x() == 0
                    and outer.winfo_y() == 0
                    and outer.winfo_width() == window._page_host.winfo_width()
                    and outer.winfo_height() == window._page_host.winfo_height()
                )

            def check_active(name):
                assert window._current_page == name
                for key, page in window._pages.items():
                    assert window._page_stack.widget_is_presented(page) == (key == name)
                    if key != name:
                        assert not page._parent_frame.winfo_ismapped()
                selected = (
                    PAGE_TOOLS
                    if name in {PAGE_PDF, PAGE_DOCUMENTS, PAGE_MEDIA}
                    else name
                )
                for key, button in window._navigation_buttons.items():
                    expected = (
                        _NAVIGATION_SELECTED_COLOR if key == selected else "transparent"
                    )
                    assert window._navigation_buttons[key].cget("fg_color") == expected
                    assert button.cget("text_color") == (
                        ON_PRIMARY if key == selected else SIDEBAR_TEXT
                    )
                    assert button.cget("hover_color") == (
                        PRIMARY_HOVER if key == selected else NAV_HOVER
                    )
                assert visible_owner()

            def check_keyboard():
                window.focus_force()
                for backwards in (False, True):
                    for _ in range(8):
                        window._focus_visible_navigation_widget(
                            None, backwards=backwards
                        )
                        window.update_idletasks()
                        focused = window.focus_get()
                        ancestor = focused
                        while ancestor is not None:
                            for name, page in window._pages.items():
                                if ancestor == page._parent_frame:
                                    assert name == window._current_page
                            ancestor = ancestor.master

            themes = ["Light", "Dark"]
            order = tuple(NAVIGATION_PAGES)
            shuffled = (
                PAGE_TOOLS,
                PAGE_HOME,
                PAGE_SETTINGS,
                PAGE_DOWNLOADS,
                PAGE_FILES,
            )
            tool_swaps = 0
            pdf = window.pdf_page
            tabs = {name: pdf.tab_view.tab(name) for name in pdf.tool_names}
            controls = {name: tuple(tab.winfo_children()) for name, tab in tabs.items()}
            for theme in themes:
                ctk.set_appearance_mode(theme)
                window.update_idletasks()
                window._show_page(PAGE_PDF)
                # CTkTabview.set agendava a remoção das outras abas para 100 ms
                # depois. Testar antes de pintar revela sobreposição e callbacks
                # obsoletos que podem deixar a ferramenta mais recente vazia.
                with (
                    patch.object(pdf.tab_view, "after") as tab_after,
                    patch.object(pdf.tab_view, "after_idle") as tab_idle,
                    patch.object(pdf.tab_view, "update") as tab_update,
                    patch.object(pdf.tab_view, "update_idletasks") as tab_update_idle,
                ):
                    for _ in range(2):
                        for route in (pdf.tool_names, tuple(reversed(pdf.tool_names))):
                            for name in route:
                                pdf.tool_cards[name].invoke()
                                assert pdf.tab_view.get() == name
                                assert [
                                    key
                                    for key, tab in tabs.items()
                                    if tab.winfo_manager()
                                ] == [name]
                                assert all(
                                    tuple(tab.winfo_children()) == controls[key]
                                    for key, tab in tabs.items()
                                )
                                tool_swaps += 1
                        settle()
                        assert tabs[pdf.tab_view.get()].winfo_ismapped()
                    for method in (tab_after, tab_idle, tab_update, tab_update_idle):
                        method.assert_not_called()
                for name in pdf.tool_names:
                    pdf._open_tool(name)
                    settle()
                    if name == "PDF para Word":
                        assert pdf.word_card.winfo_ismapped()
                        assert not pdf.tab_view.winfo_ismapped()
                    else:
                        assert tabs[name].winfo_ismapped()
                        assert tabs[name].winfo_width() > 1
                        assert tabs[name].winfo_height() > 1
                        assert not pdf.word_card.winfo_ismapped()
                    assert all(
                        not tab.winfo_ismapped()
                        for key, tab in tabs.items()
                        if key != name
                    )
                pdf._poster_crop_marks.set(True)
                pdf._poster_grid.set("3 × 3")
                pdf._open_tool("Pôster/Painel")
                settle()
                assert pdf.poster_select_button.winfo_ismapped()
                assert pdf.poster_preview_canvas.winfo_ismapped()
                assert pdf.poster_preview_canvas.find_all()
                window.focus_force()
                pdf.poster_select_button.focus_set()
                window.update_idletasks()
                focus = window.focus_get()
                assert focus is not None
                pdf.tab_view.set("Pôster/Painel")
                assert window.focus_get() == focus
                pdf._show_tool_picker()
                pdf.tool_cards["Pôster/Painel"].invoke()
                settle()
                assert pdf._poster_crop_marks.get()
                assert pdf._poster_grid.get() == "3 × 3"
                with unittest.TestCase().assertRaises(ValueError):
                    pdf.tab_view.set("Ferramenta inexistente")
                assert pdf.tab_view.get() == "Pôster/Painel"
                assert tabs["Pôster/Painel"].winfo_ismapped()
                pdf._show_tool_picker()
                for _ in range(2):
                    for route in (order, tuple(reversed(order)), shuffled):
                        for name in route:
                            window._navigation_buttons[name].invoke()
                            assert window._current_page == name
                            # O loop real entrega também Expose/Visibility do canvas.
                            settle()
                            check_active(name)
                            swaps += 1
                    check_keyboard()
                # Estado de uma subtela permanece intacto ao sair/voltar pelo shell.
                window._show_page(PAGE_PDF)
                window.pdf_page._open_tool("PDF para Word")
                settle()
                window._show_page(PAGE_HOME)
                window._show_page(PAGE_PDF)
                settle()
                assert window.pdf_page.word_card.winfo_ismapped(), [
                    (str(w), w.winfo_ismapped(), w.winfo_manager(), w.winfo_geometry())
                    for w in (
                        window.pdf_page.word_card,
                        window.pdf_page,
                        window.pdf_page._parent_canvas,
                        window.pdf_page._parent_frame,
                    )
                ]
                assert not window.pdf_page.tool_picker.winfo_ismapped()
                check_active(PAGE_PDF)
                canvas = window.pdf_page._parent_canvas
                canvas.yview_moveto(0.5)
                window.update_idletasks()
                scroll = canvas.yview()
                window._show_page(PAGE_DOWNLOADS)
                window._show_page(PAGE_PDF)
                settle()
                assert canvas.yview() == scroll
                window.pdf_page._show_tool_picker()
                window.update()
                assert window.pdf_page.tool_picker.winfo_ismapped()
                window._show_page(PAGE_DOCUMENTS)
                window.documents_page._choose_tool_card("TXT → PDF")
                settle()
                window._show_page(PAGE_HOME)
                window._show_page(PAGE_DOCUMENTS)
                settle()
                assert window.documents_page.conversion_card.winfo_ismapped()
                assert not window.documents_page.tool_picker.winfo_ismapped()
                check_active(PAGE_DOCUMENTS)
                window.documents_page._show_tool_picker()
                # Não processar idle entre os cliques: o último destino vence.
                for rapid in (
                    ("Downloads", "Ferramentas", "Arquivos"),
                    ("Ferramentas", "Arquivos", "Configurações"),
                    ("Início", "Downloads", "Início"),
                ):
                    for name in rapid:
                        window._navigation_buttons[name].invoke()
                        assert window._current_page == name
                        assert not window._navigation_in_progress
                        assert window._pending_page is None
                    settle()
                    check_active(rapid[-1])
                    # Um novo giro do event loop não deve mudar o destino/foco.
                    window.update()
                    check_active(rapid[-1])
                # CTk reaplica geometria lembrada quando muda o DPI. Páginas
                # esquecidas não podem reaparecer nessa atualização global.
                for scaling in (1.1, 1.0):
                    destination = (
                        PAGE_PDF if window._current_page != PAGE_PDF else PAGE_HOME
                    )
                    window._show_page(destination)
                    ctk.set_widget_scaling(scaling)
                    settle()
                    check_active(destination)
            assert identities == {
                name: id(page) for name, page in window._pages.items()
            }
            assert window.link_entry.get() == link
            home = window.home_page
            with (
                patch("app.save_settings", side_effect=lambda data: data.copy()),
                patch.object(window.download_queue, "add") as enqueue,
            ):
                window._show_page(PAGE_HOME)
                home.link_entry.insert(0, "link inválido")
                home.analyze_button.invoke()
                assert home.link_feedback.winfo_manager() == "grid"
                assert (
                    window._current_page == PAGE_HOME
                    and window.link_entry.get() == link
                )
                home.link_entry.delete(0, "end")
                home.link_entry.insert(0, link)
                home.format_buttons[CONTENT_TYPE_AUDIO].invoke()
                home.analyze_button.invoke()
                assert not home.link_feedback.winfo_manager()
                assert window._current_page == PAGE_DOWNLOADS
                assert (
                    window.link_entry.get() == link
                    and window.content_type.get() == CONTENT_TYPE_AUDIO
                )
                assert window.quality_label.cget("text") == "Qualidade do MP3"
                enqueue.assert_not_called()
                window.download_button.invoke()
                request = enqueue.call_args.args[0]
                assert (
                    request.url == link and request.content_type == CONTENT_TYPE_AUDIO
                )
                assert window.downloads_page.link_entry.get() == ""
                window.content_type_buttons[0].invoke()
                assert window.content_type.get() == CONTENT_TYPE_VIDEO
                assert (
                    home.format_buttons[CONTENT_TYPE_VIDEO].cget("fg_color")
                    == _NAVIGATION_SELECTED_COLOR
                )
                window.link_entry.insert(0, link)

            page = window.downloads_page
            layout_variants = 0
            destination = Path(directory) / ("pasta longa com acentos áéí" * 8)
            page.show_download_destination(destination)
            assert page.destination_text.get() == str(destination)
            buttons = page.content_type_buttons
            controls = (*buttons, page.quality_menu)

            def control_bounds():
                return tuple(
                    (
                        widget.winfo_rootx(),
                        widget.winfo_rooty(),
                        widget.winfo_width(),
                        widget.winfo_height(),
                    )
                    for widget in controls
                )

            with patch("app.save_settings", side_effect=lambda data: data.copy()):
                window.update()
                if window.state() == "zoomed":
                    window.state("normal")
                for geometry in ("1280x820", "860x600"):
                    window.geometry(geometry)
                    for theme in ("Light", "Dark"):
                        ctk.set_appearance_mode(theme)
                        settle()
                        bounds = control_bounds()
                        assert bounds[0][2] == bounds[1][2]
                        assert len({(y, h) for _, y, _, h in bounds}) == 1
                        for index in (1, 0, 1, 0):
                            buttons[index].invoke()
                            settle()
                            assert control_bounds() == bounds
                            assert window.quality_menu.cget("values") == (
                                [option.display_label for option in MP3_QUALITY_OPTIONS]
                                if index
                                else list(VIDEO_QUALITIES)
                            )
                            assert (
                                buttons[index].cget("fg_color")
                                == _NAVIGATION_SELECTED_COLOR
                            )
                            assert (
                                buttons[1 - index].cget("fg_color")
                                != _NAVIGATION_SELECTED_COLOR
                            )
                        label = page.destination_label
                        assert label.cget("wraplength") <= label.winfo_width()
                        assert label.winfo_rootx() + label.winfo_width() < (
                            page.change_destination_button.winfo_rootx()
                        )
                        layout_variants += 1
            page.show_download_destination(None)

            catalog_routes = (
                ("merge", PAGE_PDF, "Juntar PDFs"),
                ("extract", PAGE_PDF, "Extrair páginas"),
                ("poster", PAGE_PDF, "Pôster/Painel"),
                ("images", PAGE_PDF, "Imagens → PDF"),
                ("pdf_images", PAGE_PDF, "PDF → Imagens"),
                ("word", PAGE_PDF, "PDF para Word"),
                ("documents", PAGE_DOCUMENTS, None),
                ("media", PAGE_MEDIA, None),
            )
            catalog = window._pages[PAGE_TOOLS]
            for key, target, tool in catalog_routes:
                window._navigation_buttons[PAGE_TOOLS].invoke()
                catalog.tool_buttons[key].invoke()
                settle()
                check_active(target)
                if tool:
                    assert pdf.tab_view.get() == tool
            with patch.object(pdf, "_busy", True):
                window._navigation_buttons[PAGE_TOOLS].invoke()
                catalog.tool_buttons["merge"].invoke()
                assert window._current_page == PAGE_PDF
                assert pdf.tab_view.get() == "PDF para Word"
            # Snapshots da fila atualizam a pagina oculta sem consumir eventos.
            window._show_page(PAGE_PDF)
            active_item = QueueItem(
                "navigation-active",
                DownloadRequest(link, CONTENT_TYPE_VIDEO, "720p"),
                state=QueueState.DOWNLOADING,
                progress=DownloadProgress(50, 500, 1000, 100, 5),
            )
            with patch.object(
                window.download_queue, "items", return_value=(active_item,)
            ):
                window.after_cancel(window._queue_poll_after_id)
                window._poll_download_events()
                assert window._current_page == PAGE_PDF
                window._show_page(PAGE_DOWNLOADS)
                settle()
                assert window._download_active
                assert window.status.get() == "Baixando..."
                assert window.percentage.get() == "50%"
                assert window.progress_bar.get() == 0.5
                assert window.link_entry.get() == link
                row = window.downloads_page._queue_rows[active_item.id]
                assert row.percentage.cget("text") == "50.0%"
                assert row.progress.get() == 0.5
                assert row.open_file.cget("state") == "disabled"
                finished_transfer = replace(
                    active_item, progress=DownloadProgress(100, 1000, 1000, None, None)
                )
                window.downloads_page.show_queue_items(
                    (finished_transfer,), blocked=False, closing=False
                )
                settle()
                assert not row.percentage.winfo_manager()
                assert row.progress.get() == 0
                assert row.open_file.cget("state") == "disabled"
            window._set_download_state(DownloadUiState.READY)
            with patch("app.save_settings", side_effect=lambda data: data):
                window._show_page(PAGE_SETTINGS)
                assert window._current_page == PAGE_SETTINGS
                # Aguarda o encerramento assincrono pelo scheduler real.
                window.after(2000, window.quit)
                window.close()
                if not window._close_finalized:
                    window.mainloop()
            assert window._close_finalized
            assert not callback_errors, callback_errors
            return dict(
                swaps=swaps,
                themes=themes,
                scroll_preserved=True,
                subtool_preserved=True,
                max_mapped_pages=max(observations),
                mapping_observations=len(observations),
                fast_routes=True,
                scaling_preserved=True,
                close_passed=True,
                no_transition_callbacks=True,
                fields_preserved=True,
                background_progress_preserved=True,
                download_layout_variants=layout_variants,
                tool_swaps=tool_swaps,
                tool_layout_preserved=True,
            )
        finally:
            assert window.download_queue.shutdown(timeout=2)
            service.close()
            if not window._close_finalized:
                window.destroy()


if __name__ == "__main__":
    unittest.main()
