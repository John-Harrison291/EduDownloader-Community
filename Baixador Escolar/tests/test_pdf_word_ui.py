"""PDF-to-Word handoff, async lifecycle and preferences on real Tk widgets."""

from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace


class WordUiTests(unittest.TestCase):
    def test_docx_open_uses_only_windows_default_association(self):
        from app import EduDownloaderApp

        feedback = SimpleNamespace(_show_warning=Mock(), _show_error=Mock())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "Documento ação 你好.docx"
            output.touch()
            with (
                patch("app.os.startfile") as startfile,
                patch("subprocess.Popen") as popen,
                patch("subprocess.run") as run,
                patch("os.system") as system,
            ):
                self.assertTrue(
                    EduDownloaderApp._open_documents_result_file(feedback, output)
                )
                startfile.assert_called_once_with(output)
                popen.assert_not_called()
                run.assert_not_called()
                system.assert_not_called()
                feedback._show_error.assert_not_called()
                feedback._show_warning.assert_not_called()

                # No app-specific fallback if no association can open the file.
                startfile.reset_mock()
                startfile.side_effect = OSError("No associated application")
                self.assertFalse(
                    EduDownloaderApp._open_documents_result_file(feedback, output)
                )
                startfile.assert_called_once_with(output)
                feedback._show_error.assert_called_once()
                popen.assert_not_called()
                run.assert_not_called()
                system.assert_not_called()

                output.unlink()
                startfile.reset_mock()
                self.assertFalse(
                    EduDownloaderApp._open_documents_result_file(feedback, output)
                )
                startfile.assert_not_called()
                feedback._show_warning.assert_called_once()

    def test_shell_route_has_same_contract_for_both_editions(self):
        from app import EduDownloaderApp, PAGE_PDF
        from constants import ProductEdition

        for edition in ProductEdition:
            page = SimpleNamespace(prepare_pdf_to_docx_source=Mock(return_value=True))
            shell = SimpleNamespace(
                product_edition=edition,
                pdf_page=page,
                _show_page=Mock(),
                _close_requested=False,
            )
            path = Path("synthetic.pdf")
            self.assertTrue(EduDownloaderApp._route_file_to_pdf_word(shell, path))
            page.prepare_pdf_to_docx_source.assert_called_once_with(path)
            shell._show_page.assert_called_once_with(PAGE_PDF)
            shell._show_page.reset_mock()
            page.prepare_pdf_to_docx_source.return_value = False
            self.assertFalse(EduDownloaderApp._route_file_to_pdf_word(shell, path))
            shell._show_page.assert_not_called()
            shell._close_requested = True
            page.prepare_pdf_to_docx_source.reset_mock()
            self.assertFalse(EduDownloaderApp._route_file_to_pdf_word(shell, path))
            page.prepare_pdf_to_docx_source.assert_not_called()

    def test_handoff_conversion_actions_cancel_and_shutdown(self):
        script = r"""
import tempfile
from pathlib import Path
import tkinter as tk
import customtkinter as ctk
import time
from pdf_tools import PdfToolsService, PdfOperationProgress
from pdf_to_docx import PdfToDocxService, PdfToDocxError, DocxErrorCode
from settings import DialogFolderPreferences
from tests.pdf_word_fixtures import make_pdf
from ui_pages import PdfToolsPage, PdfPageActions

class DeferredThread:
    pending = []
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.pending.append(self)

try:
    root = ctk.CTk()
except tk.TclError:
    print("SKIP_TK")
    raise SystemExit(0)
root.withdraw()
root.geometry("680x560")
with tempfile.TemporaryDirectory(prefix="word-ui-") as folder:
    folder = Path(folder)
    source = folder / "Atividade ação.pdf"
    make_pdf(source, count=3, scanned=(1,))
    output = folder / "saída"
    output.mkdir()
    preferences = DialogFolderPreferences({"pdf_word.output": str(output)})
    messages, opened = [], []
    actions = PdfPageActions(
        show_info=lambda m: messages.append(("info", m)),
        show_error=lambda m: messages.append(("error", m)),
        show_warning=lambda m: messages.append(("warning", m)),
        confirm_overwrite=lambda m: False,
        open_result_file=lambda p: not opened.append(("file", p)),
        open_result_folder=lambda p: not opened.append(("folder", p)),
    )
    page = PdfToolsPage(root, service=PdfToolsService(), actions=actions,
                        dialog_preferences=preferences, thread_factory=DeferredThread)
    page.pack(fill="both", expand=True)
    root.update_idletasks()
    def wait_result(predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            root.update()
            if predicate():
                return
            time.sleep(0.005)
        raise AssertionError("Result validation/opening did not finish")
    assert "PDF para Word" in page.tool_names
    page._open_tool("PDF para Word")
    root.update_idletasks()
    assert page.word_card.winfo_manager() == "grid"
    assert not page.tab_view.winfo_manager()
    assert not page._pdf_status_frame.winfo_manager()
    assert not page.word_cancel_button.winfo_manager()
    assert not page.word_feedback.winfo_manager()
    assert not page.word_result_actions.winfo_manager()
    assert page.word_open_file_button.cget("state") == "disabled"
    assert page.word_open_folder_button.cget("state") == "disabled"
    assert page.word_card.winfo_reqheight() < 500
    assert page.word_convert_button.grid_info()["sticky"] == "w"
    assert page.word_convert_button.cget("width") == 190
    assert "digitalizados" not in page.word_hint_label.cget("text")
    page._show_tool_picker()
    assert not page.word_card.winfo_manager()
    assert not page._pdf_status_frame.winfo_manager()
    page._open_tool("Juntar PDFs")
    assert page.tab_view.winfo_manager() == "grid"
    assert page._pdf_status_frame.winfo_manager() == "grid"
    assert page.prepare_pdf_to_docx_source(source)
    assert not DeferredThread.pending  # Never autostart handoff.
    assert page._word_destination == output / "Atividade ação.docx"
    assert preferences.available("pdf_word.input") == folder
    for theme in ("Light", "Dark"):
        ctk.set_appearance_mode(theme)
        root.update_idletasks()
        for width in (420, 900):
            from types import SimpleNamespace
            page._resize_word_card(SimpleNamespace(width=width))
            assert page.word_hint_label.cget("wraplength") < page.word_status_label.cget("wraplength")
            assert page.word_destination_label.master is page.word_destination_button.master
            assert int(page.word_new_button.grid_info()["row"]) == (1 if width < 500 else 0)
    page._convert_word()
    assert page._busy
    assert page.word_select_button.cget("state") == "disabled"
    assert not page.prepare_pdf_to_docx_source(source)
    assert page.word_cancel_button.cget("state") == "normal"
    assert page.word_cancel_button.winfo_manager() == "grid"
    assert page.word_feedback.winfo_manager() == "grid"
    assert page.word_progress.winfo_manager() == "grid"
    assert not page.word_result_actions.winfo_manager()
    page._operation_progress_results.put((page._operation_generation, PdfOperationProgress(1, 3)))
    page._apply_latest_operation_progress()
    assert abs(page.progress_bar.get() - 1 / 3) < 0.001
    assert abs(page.word_progress_bar.get() - 1 / 3) < 0.001
    DeferredThread.pending.pop().target()
    page._poll_worker()
    assert not page._busy
    assert page._word_destination.is_file()
    assert "imagens" in messages[-1][1]
    wait_result(lambda: page._feedback_for().info is not None)
    assert page.word_result_actions.winfo_manager() == "grid"
    assert page.word_open_file_button.cget("state") == "normal"
    assert page.word_open_folder_button.cget("state") == "normal"
    assert not page.word_cancel_button.winfo_manager()
    assert not page.word_progress.winfo_manager()
    page.tool_back_button.invoke()
    page.tool_cards["Juntar PDFs"].invoke()
    assert page.open_file_button.cget("state") == "disabled"
    page.tool_back_button.invoke()
    page.tool_cards["PDF para Word"].invoke()
    assert page.word_result_actions.winfo_manager() == "grid"
    assert page.word_open_file_button.cget("state") == "normal"
    page._open_result(False)
    wait_result(lambda: not page._feedback_for().pending)
    page._open_result(True)
    wait_result(lambda: not page._feedback_for().pending)
    assert [x[0] for x in opened] == ["file", "folder"]
    assert preferences.available("pdf_word.output") == output
    page._convert_word()  # Existing output; operator declined overwrite.
    assert not DeferredThread.pending
    page._new_word_conversion()
    assert page._word_source is None and page._word_destination is None
    assert page._feedback_for().path is None
    assert not page.word_feedback.winfo_manager()
    assert not page.word_result_actions.winfo_manager()
    assert page.word_convert_button.cget("state") == "disabled"
    assert preferences.available("pdf_word.output") == output
    assert page.prepare_pdf_to_docx_source(source)
    assert page.open_file_button.cget("state") == "disabled"
    page._word_destination = output / "cancelled.docx"
    page._convert_word()
    page._cancel_pdf_operation("word")
    DeferredThread.pending.pop().target()
    page._poll_worker()
    assert not page._busy
    assert not page._word_destination.exists()
    assert page._word_progress_text.get() == "Operação cancelada."
    assert not page.word_cancel_button.winfo_manager()
    assert not page.word_result_actions.winfo_manager()
    page._convert_word()
    page.begin_shutdown()
    assert not page.is_shutdown_ready
    assert page._operation_cancel_event.is_set()
    DeferredThread.pending.pop().target()
    page._poll_worker()
    assert page.is_shutdown_ready
    assert not page.prepare_pdf_to_docx_source(source)
    page.cancel_shutdown()
    class FailedService:
        def convert(self, *args, **kwargs):
            raise PdfToDocxError(DocxErrorCode.SCANNED_OR_IMAGE_ONLY)
    page._docx_service = FailedService()
    page._word_destination = output / "failed.docx"
    page._convert_word()
    DeferredThread.pending.pop().target()
    page._poll_worker()
    assert messages[-1][0] == "error"
    assert "digitalizado" in messages[-1][1]
    assert page.word_feedback.winfo_manager() == "grid"
    assert not page.word_result_actions.winfo_manager()
    assert not page.word_cancel_button.winfo_manager()
    page.close()
    for worker in (page._page_preview_worker, page._analysis_worker, page._result_worker):
        if worker.thread:
            worker.thread.join(5)
            assert not worker.thread.is_alive()
    page.destroy()
root.destroy()
print("PASS")
"""
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if "SKIP_TK" in result.stdout:
            self.skipTest("Tk unavailable")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
