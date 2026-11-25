"""Synthetic UX regression; no personal files, external network or activation."""

from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk
from pypdf import PdfWriter

from app import EduDownloaderApp
from documents_tools import DocumentInputFormat
from mp3_quality import DEFAULT_MP3_QUALITY
from pdf_tools import (
    PdfImageExportResult,
    PdfOperationCancelled,
    PdfOperationProgress,
    PdfOperationResult,
    PdfToolsError,
    PdfToolsService,
)
from settings import (
    DialogFolderPreferences,
    default_settings,
    load_settings,
    normalize_settings,
    save_settings,
)
from ui_pages import (
    DocumentsPage,
    FilesPage,
    MediaToolsPage,
    PdfPageActions,
    PdfToolsPage,
)


class FolderPreferenceTests(unittest.TestCase):
    def test_files_reveal_feedback_describes_the_user_action(self):
        fake = SimpleNamespace(_reveal_file=Mock(), _run_general_action=Mock())
        FilesPage._reveal_selected(fake)
        fake._run_general_action.assert_called_once_with(
            fake._reveal_file, "Pasta aberta no Explorador de Arquivos."
        )

    def test_allowlist_rejects_network_relative_invalid_and_unknown(self):
        invalid = {
            "unknown": "C:/private",
            "pdf.input": r"\\server\share",
            "pdf.output": "relative",
            "media.input": 4,
            "media.output": "C:/bad\0folder",
            "documents.input": "https://example.com",
        }
        self.assertNotIn(
            "dialog_folders", normalize_settings({"dialog_folders": invalid})
        )
        self.assertNotIn("dialog_folders", default_settings())

    def test_load_does_not_probe_remembered_paths(self):
        with patch.object(Path, "is_dir", side_effect=AssertionError):
            result = normalize_settings(
                {"dialog_folders": {"pdf.input": "C:/Aula João"}}
            )
        self.assertEqual(result["dialog_folders"], {"pdf.input": "C:/Aula João"})

    def test_unicode_roundtrip_categories_and_input_output_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folders = [
                root / name
                for name in ("Entrada João 你好", "Saída PDF", "Saída mídia")
            ]
            for folder in folders:
                folder.mkdir()
            settings_path = root / "settings.json"
            prefs = DialogFolderPreferences(
                persist=lambda values: save_settings(
                    {"dialog_folders": values}, settings_path
                )
            )
            for key, folder in zip(
                ("pdf.input", "pdf.output", "media.output"), folders
            ):
                prefs.remember(key, folder)
            restored = DialogFolderPreferences(
                load_settings(settings_path)["dialog_folders"]
            )
            self.assertEqual(restored.available("pdf.input"), folders[0])
            self.assertEqual(restored.available("pdf.output"), folders[1])
            self.assertEqual(restored.available("media.output"), folders[2])
            self.assertIsNone(restored.available("documents.output"))

    def test_missing_or_inaccessible_folder_falls_back_without_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "removed"
            prefs = DialogFolderPreferences({"pdf.output": str(missing)})
            dialog = Mock(return_value="")
            prefs.choose(dialog, "pdf.output", initialfile="aula.pdf")
            self.assertNotIn("initialdir", dialog.call_args.kwargs)
            self.assertFalse(missing.exists())
            with patch.object(Path, "is_dir", side_effect=PermissionError):
                self.assertIsNone(prefs.available("pdf.output"))

    def test_dialog_cancel_keeps_preference_and_does_not_save(self):
        persist = Mock()
        prefs = DialogFolderPreferences(persist=persist)
        self.assertEqual(prefs.choose(Mock(return_value=""), "pdf.input"), "")
        self.assertEqual(prefs.choose(Mock(return_value=()), "pdf.input"), ())
        persist.assert_not_called()

    def test_multiselection_and_directory_choices_remember_only_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            persist = Mock()
            prefs = DialogFolderPreferences(persist=persist)
            selected = (str(root / "a.pdf"), str(root / "b.pdf"))
            self.assertEqual(
                prefs.choose(Mock(return_value=selected), "pdf.input"), selected
            )
            prefs.choose(Mock(return_value=str(root)), "pdf.output", directory=True)
            self.assertEqual(
                persist.call_args.args[0],
                {"pdf.input": str(root), "pdf.output": str(root)},
            )
            self.assertEqual(list(root.iterdir()), [])

    def test_shell_reports_save_failure_without_blocking_session_choice(self):
        fake = SimpleNamespace(
            settings=default_settings(), _save_preferences=Mock(return_value=False)
        )
        EduDownloaderApp._persist_dialog_folders(fake, {"pdf.output": "C:/Aula"})
        self.assertEqual(fake.settings["dialog_folders"], {"pdf.output": "C:/Aula"})
        fake._save_preferences.assert_called_once()

    def test_document_and_media_dialogs_use_separate_input_output_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folders = {}
            for key in (
                "documents.input",
                "documents.output",
                "media.input",
                "media.output",
            ):
                folder = root / key
                folder.mkdir()
                folders[key] = str(folder)
            fake = SimpleNamespace(
                _busy=False,
                _shutdown_requested=False,
                _source=root / "aula.txt",
                _operation=DocumentInputFormat.TXT,
                _quality=SimpleNamespace(get=lambda: DEFAULT_MP3_QUALITY.display_label),
                _extraction_mode=SimpleNamespace(get=lambda: "Áudio completo"),
                _dialog_preferences=DialogFolderPreferences(folders),
                winfo_toplevel=Mock(return_value=None),
            )
            cases = (
                (DocumentsPage._select_document, "askopenfilename", "documents.input"),
                (
                    DocumentsPage._start_conversion,
                    "asksaveasfilename",
                    "documents.output",
                ),
                (MediaToolsPage._select_video, "askopenfilename", "media.input"),
                (MediaToolsPage._start_conversion, "asksaveasfilename", "media.output"),
            )
            for method, dialog_name, key in cases:
                with (
                    self.subTest(key=key),
                    patch(
                        "ui_pages.filedialog." + dialog_name, return_value=""
                    ) as dialog,
                ):
                    method(fake)
                    self.assertEqual(
                        dialog.call_args.kwargs["initialdir"], folders[key]
                    )


class ShellFolderRestoreTests(unittest.TestCase):
    def test_shell_restores_download_destination_and_shares_dialog_preferences(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent("""
                import logging
                import tempfile
                from pathlib import Path
                from unittest.mock import patch
                from app import EduDownloaderApp, PAGE_PDF, PAGE_DOCUMENTS, PAGE_MEDIA
                from downloader import DownloadService
                from settings import save_settings, load_settings

                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    destination = root / "Aula João 你好"
                    destination.mkdir()
                    settings_path = root / "settings.json"
                    save_settings({"dialog_folders": {"downloads.output": str(destination)}}, settings_path)
                    logger = logging.getLogger("synthetic-folders")
                    logger.handlers = [logging.NullHandler()]
                    logger.propagate = False
                    service = DownloadService(root / "downloads", logger)
                    with patch("app.load_settings", side_effect=lambda: load_settings(settings_path)):
                        window = EduDownloaderApp(service)
                    window.withdraw()
                    assert window._download_destination_dir == destination
                    assert destination.name in window.downloads_page.destination_text.get()
                    assert window.settings_page.download_folder_path.get() == str(destination)
                    for name in (PAGE_PDF, PAGE_DOCUMENTS, PAGE_MEDIA):
                        assert window._pages[name]._dialog_preferences is window.dialog_preferences
                    with patch("app.save_settings", side_effect=lambda data: save_settings(data, settings_path)):
                        window.dialog_preferences.remember("pdf.output", root)
                    assert load_settings(settings_path)["dialog_folders"] == {
                        "downloads.output": str(destination), "pdf.output": str(root)
                    }
                    window.destroy()
                    service.close()
            """),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class PdfResultUxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="edu-tools-ux-")
        self.addCleanup(self.temp.cleanup)
        self.root_path = Path(self.temp.name)
        self.root = ctk.CTk()
        self.root.withdraw()
        self.info, self.open_file, self.open_folder = (
            Mock(),
            Mock(return_value=True),
            Mock(return_value=True),
        )
        self.page = PdfToolsPage(
            self.root,
            service=PdfToolsService(),
            actions=PdfPageActions(
                show_info=self.info,
                show_warning=Mock(),
                show_error=Mock(),
                confirm_overwrite=Mock(return_value=False),
                open_result_file=self.open_file,
                open_result_folder=self.open_folder,
            ),
        )
        self.assertFalse(self.page._pdf_status_frame.winfo_manager())
        self.page.tool_cards["Juntar PDFs"].invoke()

    def tearDown(self):
        self.page.begin_shutdown()
        deadline = time.monotonic() + 5
        while not self.page.is_shutdown_ready and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        # A fresh Tk interpreter per test must not inherit CTk timer callbacks.
        for identifier in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", identifier)
        self.root.destroy()

    def wait_result(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.assertTrue(predicate())

    def test_result_actions_no_modal_and_failure_invalidates_result(self):
        output = self.root_path / "Aula João.pdf"
        output.touch()
        self.assertEqual(self.page.open_file_button.cget("state"), "disabled")
        self.page._complete_operation("PDFs unidos", PdfOperationResult(output, 2))
        self.info.assert_not_called()
        self.assertIn(output.name, self.page._status.get())
        self.wait_result(lambda: self.page._feedback_for().info is not None)
        self.page.open_file_button.invoke()
        self.wait_result(lambda: not self.page._feedback_for().pending)
        self.page.open_folder_button.invoke()
        self.wait_result(lambda: not self.page._feedback_for().pending)
        self.open_file.assert_called_once_with(output)
        self.open_folder.assert_called_once_with(output)
        self.open_file.return_value = False
        self.page.open_file_button.invoke()
        self.wait_result(lambda: self.page._feedback_for().path is None)
        self.assertIsNone(self.page._feedback_for().path)
        self.assertEqual(self.page.open_folder_button.cget("state"), "disabled")

    def test_new_input_invalidates_only_its_own_result_and_shutdown_disables_actions(
        self,
    ):
        merged = self.root_path / "unido.pdf"
        extracted = self.root_path / "extraido.pdf"
        for output in (merged, extracted):
            output.touch()
        self.page._complete_operation("PDFs unidos", PdfOperationResult(merged, 2))
        self.wait_result(lambda: self.page.open_file_button.cget("state") == "normal")
        self.page._show_tool_picker()
        self.page.tool_cards["Extrair páginas"].invoke()
        self.assertIsNone(self.page._feedback_for().path)
        self.assertNotIn("PDFs unidos", self.page._status.get())
        self.page._complete_operation(
            "Páginas extraídas", PdfOperationResult(extracted, 1)
        )
        self.wait_result(lambda: self.page.open_file_button.cget("state") == "normal")
        self.page._show_tool_picker()
        self.page.tool_cards["Juntar PDFs"].invoke()
        self.assertEqual(self.page._feedback_for().path, merged)
        self.assertEqual(self.page.open_file_button.cget("state"), "normal")
        self.page._on_merge_list_changed()
        self.assertIsNone(self.page._feedback_for().path)
        self.assertNotIn("PDFs unidos", self.page._status.get())
        self.page._show_tool_picker()
        self.page.tool_cards["Extrair páginas"].invoke()
        self.assertEqual(self.page._feedback_for().path, extracted)
        self.page.begin_shutdown()
        self.page.open_file_button.invoke()
        self.open_file.assert_not_called()

    def test_catalogue_hides_status_while_worker_completes_and_retains_its_result(self):
        page = self.page
        output = self.root_path / "unido.pdf"
        output.touch()
        previous = self.root_path / "extraido.pdf"
        previous.touch()
        page._open_tool("Extrair páginas")
        page._complete_operation("Páginas extraídas", PdfOperationResult(previous, 1))
        self.wait_result(lambda: page.open_file_button.cget("state") == "normal")
        page._open_tool("Juntar PDFs")
        release = threading.Event()

        def merge(cancel, progress):
            progress(PdfOperationProgress(1, 2))
            if not release.wait(5) or cancel.is_set():
                raise RuntimeError("QA operation interrupted")
            return PdfOperationResult(output, 2)

        try:
            self.assertFalse(page.progress_bar.winfo_manager())
            page._start_pdf_operation_worker(
                "merge",
                merge,
                lambda result: page._complete_operation("PDFs unidos", result),
                "Juntando PDFs localmente...",
            )
            self.wait_result(lambda: page.progress_bar.get() == 0.5)
            self.assertEqual(page.progress_bar.winfo_manager(), "grid")
            page.tool_back_button.invoke()
            self.assertEqual(page.tool_picker.winfo_manager(), "grid")
            self.assertFalse(page._pdf_status_frame.winfo_manager())
            self.assertTrue(page.is_busy)
            page.tool_cards["Extrair páginas"].invoke()
            self.assertEqual(page._pdf_status_frame.winfo_manager(), "grid")
            self.assertFalse(page.progress_bar.winfo_manager())
            self.assertEqual(page.extract_select_button.cget("state"), "disabled")
            competing_operation = Mock()
            page._start_pdf_operation_worker(
                "extract", competing_operation, Mock(), "Extraindo..."
            )
            competing_operation.assert_not_called()
            page._actions.show_warning.assert_called_once()
            self.assertNotIn(
                "Juntando",
                page.getvar(str(page._pdf_status_label.cget("textvariable"))),
            )
            self.assertEqual(page.open_file_button.cget("state"), "normal")
            page.open_file_button.invoke()
            self.wait_result(lambda: self.open_file.called)
            self.open_file.assert_called_once_with(previous)
            page.tool_back_button.invoke()
            page.tool_cards["Juntar PDFs"].invoke()
            self.assertEqual(page.progress_bar.winfo_manager(), "grid")
            self.assertEqual(page.progress_bar.get(), 0.5)
            page.tool_back_button.invoke()
            release.set()
            self.wait_result(
                lambda: not page.is_busy and page._feedback_for().info is not None
            )
            self.assertFalse(page._pdf_status_frame.winfo_manager())
            page.tool_cards["Juntar PDFs"].invoke()
            self.assertFalse(page.progress_bar.winfo_manager())
            self.assertEqual(page.open_file_button.cget("state"), "normal")
            self.assertEqual(page.open_folder_button.cget("state"), "normal")
            self.assertEqual(page._feedback_for().path, output)
        finally:
            release.set()

    def test_pdf_terminal_status_after_navigation_belongs_to_its_tool(self):
        page = self.page
        self.assertEqual(page.tab_view.get(), "Juntar PDFs")
        for cancel in (True, False):
            with self.subTest(cancel=cancel):
                started = threading.Event()
                release = threading.Event()
                completed = Mock()

                def merge(cancel_event, _progress):
                    started.set()
                    if not release.wait(5):
                        raise AssertionError("QA did not release the PDF worker")
                    if cancel_event.is_set():
                        raise PdfOperationCancelled()
                    raise PdfToolsError("Falha sintética de junção.")

                try:
                    page._start_pdf_operation_worker(
                        "merge", merge, completed, "Juntando PDFs..."
                    )
                    self.assertTrue(started.wait(2))
                    page.tool_back_button.invoke()
                    page.tool_cards["Extrair páginas"].invoke()
                    self.assertFalse(page.progress_bar.winfo_manager())
                    self.assertEqual(page.merge_cancel_button.cget("state"), "normal")
                    if cancel:
                        page.tool_back_button.invoke()
                        page.tool_cards["Juntar PDFs"].invoke()
                        page.merge_cancel_button.invoke()
                        page.tool_back_button.invoke()
                        page.tool_cards["Extrair páginas"].invoke()
                    release.set()
                    self.wait_result(lambda: not page.is_busy)
                    self.assertFalse(page._feedback_for("Extrair páginas").paths)
                    self.assertFalse(page.progress_bar.winfo_manager())
                    self.assertNotIn(
                        "Operação PDF",
                        page._feedback_for("Extrair páginas").status.get(),
                    )
                    page.tool_back_button.invoke()
                    page.tool_cards["Juntar PDFs"].invoke()
                    self.assertIn(
                        "cancelada" if cancel else "não concluída", page._status.get()
                    )
                    self.assertEqual(page.open_file_button.cget("state"), "disabled")
                    completed.assert_not_called()
                finally:
                    release.set()

    def test_image_export_opens_first_result_and_output_conflict_still_confirms(self):
        self.page._open_tool("PDF → Imagens")
        first = self.root_path / "página-1.png"
        first.write_bytes(b"controlled-output")
        self.page._complete_pdf_images_export(
            PdfImageExportResult(self.root_path, (first,), (1,))
        )
        self.wait_result(lambda: self.page._feedback_for().info is not None)
        self.page.open_folder_button.invoke()
        self.wait_result(lambda: not self.page._feedback_for().pending)
        self.open_folder.assert_called_once_with(first)
        existing = self.root_path / "existente.pdf"
        existing.write_bytes(b"original")
        with patch("ui_pages.filedialog.asksaveasfilename", return_value=str(existing)):
            self.assertIsNone(self.page._choose_output("aula.pdf"))
        self.page._actions.confirm_overwrite.assert_called_once()
        self.assertEqual(existing.read_bytes(), b"original")

    def test_suggested_names_use_source_without_changing_originals(self):
        pdf = self.root_path / "Aula João.pdf"
        image = self.root_path / "Cartaz 你好.png"
        self.page.merge_files.add_paths([pdf, self.root_path / "b.pdf"])
        with patch.object(self.page, "_choose_output", return_value=None) as choose:
            self.page._start_merge()
        choose.assert_called_once_with("Aula João-unidos.pdf")
        self.page.image_files.add_paths([image])
        with patch.object(self.page, "_choose_output", return_value=None) as choose:
            self.page._start_images()
        choose.assert_called_once_with("Cartaz 你好-imagens.pdf")
        self.page._poster_source = image
        with patch.object(self.page, "_choose_output", return_value=None) as choose:
            self.page._start_poster()
        choose.assert_called_once_with("Cartaz 你好-poster.pdf")

    def test_real_synthetic_merge_keeps_originals_and_enables_result(self):
        inputs = [self.root_path / name for name in ("A.pdf", "B.pdf")]
        for source in inputs:
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.write(source)
            writer.close()
        originals = [source.read_bytes() for source in inputs]
        self.page.merge_files.add_paths(inputs)
        deadline = time.monotonic() + 5
        while (
            self.page._merge_metadata_after_id is not None
            or self.page._merge_metadata_worker_active
        ):
            self.root.update()
            time.sleep(0.01)
            self.assertLess(time.monotonic(), deadline)
        output = self.root_path / "unido.pdf"
        with patch("ui_pages.filedialog.asksaveasfilename", return_value=str(output)):
            self.page._start_merge()
        deadline = time.monotonic() + 5
        while self.page.is_busy:
            self.root.update()
            time.sleep(0.01)
            self.assertLess(time.monotonic(), deadline)
        self.assertEqual(PdfToolsService().page_count(output), 2)
        self.assertEqual([source.read_bytes() for source in inputs], originals)
        self.wait_result(lambda: self.page._feedback_for().info is not None)
        self.assertEqual(self.page.open_file_button.cget("state"), "normal")
        self.assertEqual(set(self.root_path.iterdir()), {*inputs, output})


if __name__ == "__main__":
    unittest.main()
