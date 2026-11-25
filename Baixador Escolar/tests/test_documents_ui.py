"""Testes da página Documentos sem depender do motor documental real."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class DocumentsPageRealTkTests(unittest.TestCase):
    def _run_tk_script(self, body: str, *, timeout: int = 30) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(body)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(stdout.splitlines()[-1])

    def test_component_states_selection_overwrite_success_and_open_actions(
        self,
    ) -> None:
        result = self._run_tk_script(
            r"""
            import json
            import tempfile
            import tkinter as tk
            from pathlib import Path
            from unittest.mock import patch

            import customtkinter as ctk

            from documents_component import (
                DocumentsComponentCheck,
                DocumentsComponentStatus,
            )
            from documents_tools import (
                DocumentConversionResult,
                DocumentConversionStatus,
            )
            from ui_pages import DocumentsPage, DocumentsPageActions

            class ImmediateThread:
                def __init__(self, *, target, name, daemon):
                    self.target = target
                    self.name = name
                def start(self):
                    self.target()

            class ComponentService:
                def __init__(self):
                    self.status = DocumentsComponentStatus.NOT_CONFIGURED
                    self.calls = []
                def fast_check(self, root=None):
                    self.calls.append(None if root is None else str(root))
                    return DocumentsComponentCheck(self.status, None, "test")

            class ConversionService:
                def __init__(self):
                    self.calls = []
                    self.status = DocumentConversionStatus.COMPLETED
                def convert(self, request):
                    self.calls.append(request)
                    if self.status is DocumentConversionStatus.COMPLETED:
                        request.output_path.write_bytes(b"%PDF-1.4\n%%EOF")
                        output = request.output_path
                    else:
                        output = None
                    return DocumentConversionResult(
                        self.status, output, "test", "safe", "test"
                    )

            component = ComponentService()
            conversion = ConversionService()
            messages = []
            persisted = []
            opened = []
            install_requests = []
            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print(f"SKIP_TK:{type(error).__name__}")
                raise SystemExit(0)
            root.withdraw()
            actions = DocumentsPageActions(
                show_info=lambda message: messages.append(("info", message)),
                show_warning=lambda message: messages.append(("warning", message)),
                show_error=lambda message: messages.append(("error", message)),
                confirm_overwrite=lambda _message: True,
                persist_component_path=lambda path: persisted.append(
                    None if path is None else str(path)
                ) or True,
                open_result_file=lambda path: opened.append(("file", path.name)) or True,
                open_result_folder=lambda path: opened.append(("folder", path.name)) or True,
                start_component_install=lambda: install_requests.append(True),
            )
            page = DocumentsPage(
                root,
                component_service=component,
                conversion_service=conversion,
                configured_component_path=None,
                actions=actions,
                thread_factory=ImmediateThread,
            )
            page.pack(fill="both", expand=True)
            page.on_show()
            page._poll_component_check()
            initial = (
                page._component_status.get(),
                page.convert_button.cget("state"),
                page.progress_bar.cget("mode"),
            )
            guidance = page.component_guidance_label.cget("text")
            configure_label = page.configure_component_button.cget("text")
            page.install_component_button.invoke()
            component.status = DocumentsComponentStatus.INVALID
            page._request_component_check()
            page._poll_component_check()
            invalid = page._component_status.get()
            component.status = DocumentsComponentStatus.VERSION_MISMATCH
            page._request_component_check()
            page._poll_component_check()
            mismatch = page._component_status.get()
            component.status = DocumentsComponentStatus.AVAILABLE
            with patch("ui_pages.filedialog.askdirectory", return_value="C:/Componente Ação"):
                page._choose_component()
            page._poll_component_check()
            available = page._component_status.get()

            with tempfile.TemporaryDirectory() as temporary_dir:
                base = Path(temporary_dir)
                wrong = base / "errado.txt"
                wrong.write_text("x", encoding="utf-8")
                source = base / "Planejamento Ação 你好.docx"
                source.write_bytes(b"fixture")
                output = base / "Planejamento Ação 你好.pdf"
                output.write_bytes(b"old")
                with patch("ui_pages.filedialog.askopenfilename", return_value=str(wrong)):
                    page._select_docx()
                wrong_warning = messages[-1]
                with patch("ui_pages.filedialog.askopenfilename", return_value=str(source)):
                    page._select_docx()
                selected = page._source_text.get()
                with patch("ui_pages.filedialog.asksaveasfilename", return_value=str(output)):
                    page._start_conversion()
                preparing = page.state.value
                page._mark_converting(page._operation_generation)
                converting = page.state.value
                page._poll_conversion()
                completed = page.state.value
                page._open_result_file()
                page._open_result_folder()
                request = conversion.calls[-1]
                output_valid = output.read_bytes().startswith(b"%PDF")

            page.close()
            root.destroy()
            print(json.dumps({
                "initial": initial,
                "guidance": guidance,
                "configure_label": configure_label,
                "install_requests": install_requests,
                "invalid": invalid,
                "mismatch": mismatch,
                "available": available,
                "persisted": persisted,
                "wrong_warning": wrong_warning,
                "selected": selected,
                "preparing": preparing,
                "converting": converting,
                "completed": completed,
                "overwrite": request.overwrite,
                "component_root": str(request.component_root),
                "opened": opened,
                "output_valid": output_valid,
                "messages": messages,
            }, ensure_ascii=True))
            """
        )
        self.assertEqual(
            result["initial"],
            [
                "LibreOffice não encontrado. Configure para converter Word e OpenDocument. Texto para PDF continua disponível.",
                "disabled",
                "indeterminate",
            ],
        )
        self.assertIn("não incluído no EduDownloader", result["guidance"])
        self.assertIn("detectada automaticamente", result["guidance"])
        self.assertEqual(result["configure_label"], "Localizar LibreOffice")
        self.assertEqual(result["install_requests"], [True])
        self.assertEqual(
            result["invalid"],
            "Não foi possível validar o LibreOffice. Localize uma instalação existente ou configure novamente.",
        )
        self.assertEqual(
            result["mismatch"],
            "Esta versão do LibreOffice não é compatível.",
        )
        self.assertEqual(result["available"], "LibreOffice pronto para uso.")
        self.assertEqual(result["persisted"], ["C:\\Componente Ação"])
        self.assertEqual(result["wrong_warning"][0], "warning")
        self.assertEqual(result["selected"], "Planejamento Ação 你好.docx")
        self.assertEqual(result["preparing"], "PREPARING")
        self.assertEqual(result["converting"], "CONVERTING")
        self.assertEqual(result["completed"], "COMPLETED")
        self.assertIn(
            ["info", 'PDF criado: "Planejamento Ação 你好.pdf".'],
            result["messages"],
        )
        self.assertTrue(result["overwrite"])
        self.assertTrue(result["output_valid"])
        self.assertEqual(
            result["opened"],
            [
                ["file", "Planejamento Ação 你好.pdf"],
                ["folder", "Planejamento Ação 你好.pdf"],
            ],
        )

    def test_public_handoff_prepares_only_and_preserves_busy_operation(self) -> None:
        result = self._run_tk_script(
            r"""
            import json
            import tempfile
            import tkinter as tk
            from pathlib import Path

            import customtkinter as ctk

            from documents_component import (
                COMPONENT_VERSION,
                ENGINE_VERSION,
                DocumentsComponent,
                DocumentsComponentCheck,
                DocumentsComponentStatus,
            )
            from documents_tools import (
                DocumentConversionRequest,
                DocumentConversionStatus,
                DocumentsConversionService,
            )
            from ui_pages import DocumentsPage, DocumentsPageActions

            class ImmediateThread:
                def __init__(self, *, target, **_kwargs): self.target = target
                def start(self): self.target()

            class MissingComponentService:
                def fast_check(self, root=None):
                    return DocumentsComponentCheck(
                        DocumentsComponentStatus.NOT_CONFIGURED, None, "test"
                    )

            class ConversionMustNotRun:
                def __init__(self): self.calls = 0
                def convert(self, _request):
                    self.calls += 1
                    raise AssertionError("handoff must not start conversion")

            class AvailableComponentService:
                def __init__(self, component): self.component = component
                def fast_check(self, root=None):
                    return DocumentsComponentCheck(
                        DocumentsComponentStatus.AVAILABLE, self.component, "test"
                    )

            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print(f"SKIP_TK:{type(error).__name__}")
                raise SystemExit(0)
            root.withdraw()
            conversion = ConversionMustNotRun()
            page = DocumentsPage(
                root,
                component_service=MissingComponentService(),
                conversion_service=conversion,
                configured_component_path=None,
                actions=DocumentsPageActions(
                    show_info=lambda _message: None,
                    show_warning=lambda _message: None,
                    show_error=lambda _message: None,
                    confirm_overwrite=lambda _message: True,
                    persist_component_path=lambda _path: True,
                    open_result_file=lambda _path: True,
                    open_result_folder=lambda _path: True,
                ),
                thread_factory=ImmediateThread,
            )
            page.pack(fill="both", expand=True)
            with tempfile.TemporaryDirectory() as temporary_dir:
                base = Path(temporary_dir)
                first = base / "Plano ação 你好.DOCX"
                first.write_bytes(b"not-a-real-docx")
                second = base / "Segundo.docx"
                second.write_bytes(b"not-a-real-docx")
                wrong = base / "legado.doc"
                wrong.write_bytes(b"legacy")

                accepted_missing_component = page.prepare_docx_to_pdf(first)
                missing_state = {
                    "source": page._source_text.get(),
                    "state": page.state.value,
                    "convert": page.convert_button.cget("state"),
                    "status": page._status.get(),
                }
                page.on_show(); page._poll_component_check()
                checked_status = page._component_status.get()

                page._busy = True
                busy_refused = not page.prepare_docx_to_pdf(second)
                busy_source = page._source_text.get()
                page._busy = False
                wrong_refused = not page.prepare_docx_to_pdf(wrong)
                missing_refused = not page.prepare_docx_to_pdf(base / "missing.docx")
                relative_refused = not page.prepare_docx_to_pdf(Path(first.name))
                unc_refused = not page.prepare_docx_to_pdf(
                    r"\\servidor\compartilhamento\aula.docx"
                )

                page._component_available = True
                available_accepted = page.prepare_docx_to_pdf(second)
                available_state = (page.state.value, page.convert_button.cget("state"))

                component_root = base / "component"
                program = component_root / "engine/App/libreoffice/program"
                python_home = program / "python-core-3.12.13"
                python_home.mkdir(parents=True)
                component = DocumentsComponent(
                    root=component_root,
                    engine_root=component_root / "engine",
                    soffice_entrypoint=program / "soffice.com",
                    soffice_bin=program / "soffice.bin",
                    launcher=component_root / "engine/LibreOfficePortable.exe",
                    python_home=python_home,
                    python_runtime=python_home / "bin/python.exe",
                    component_version=COMPONENT_VERSION,
                    engine_version=ENGINE_VERSION,
                )
                malformed_prepared = page.prepare_docx_to_pdf(first)
                malformed_result = DocumentsConversionService(
                    component_service=AvailableComponentService(component)
                ).convert(DocumentConversionRequest(
                    input_path=first,
                    output_path=base / "resultado.pdf",
                    component_root=component_root,
                ))

            page.close(); root.destroy()
            print(json.dumps({
                "accepted_missing_component": accepted_missing_component,
                "missing_state": missing_state,
                "checked_status": checked_status,
                "busy_refused": busy_refused,
                "busy_source": busy_source,
                "wrong_refused": wrong_refused,
                "missing_refused": missing_refused,
                "relative_refused": relative_refused,
                "unc_refused": unc_refused,
                "available_accepted": available_accepted,
                "available_state": available_state,
                "malformed_prepared": malformed_prepared,
                "malformed_status": malformed_result.status.value,
                "conversion_calls": conversion.calls,
            }, ensure_ascii=True))
            """
        )
        self.assertTrue(result["accepted_missing_component"])
        self.assertEqual(result["missing_state"]["source"], "Plano ação 你好.DOCX")
        self.assertEqual(result["missing_state"]["state"], "COMPONENT_UNAVAILABLE")
        self.assertEqual(result["missing_state"]["convert"], "disabled")
        self.assertEqual(
            result["missing_state"]["status"],
            "LibreOffice indisponível. Verifique a configuração; TXT para PDF funciona sem ele.",
        )
        self.assertEqual(
            result["checked_status"],
            "LibreOffice não encontrado. Configure para converter Word e OpenDocument. Texto para PDF continua disponível.",
        )
        self.assertTrue(result["busy_refused"])
        self.assertEqual(result["busy_source"], "Plano ação 你好.DOCX")
        self.assertTrue(result["wrong_refused"])
        self.assertTrue(result["missing_refused"])
        self.assertTrue(result["relative_refused"])
        self.assertTrue(result["unc_refused"])
        self.assertTrue(result["available_accepted"])
        self.assertEqual(result["available_state"], ["READY", "normal"])
        self.assertTrue(result["malformed_prepared"])
        self.assertEqual(result["malformed_status"], "INVALID_INPUT")
        self.assertEqual(result["conversion_calls"], 0)

    def test_cancellation_is_responsive_and_late_completion_is_discarded(self) -> None:
        result = self._run_tk_script(
            r"""
            import json
            import tempfile
            import threading
            import time
            import tkinter as tk
            from pathlib import Path
            from unittest.mock import patch

            import customtkinter as ctk

            from documents_component import DocumentsComponentCheck, DocumentsComponentStatus
            from documents_tools import DocumentConversionResult, DocumentConversionStatus
            from ui_pages import DocumentsPage, DocumentsPageActions

            main_thread = threading.get_ident()
            worker_threads = []

            class ComponentService:
                def fast_check(self, root=None):
                    return DocumentsComponentCheck(
                        DocumentsComponentStatus.AVAILABLE, None, "test"
                    )

            class SlowService:
                def convert(self, request):
                    worker_threads.append(threading.get_ident())
                    request.cancel_event.wait(2)
                    return DocumentConversionResult(
                        DocumentConversionStatus.COMPLETED,
                        request.output_path,
                        "test",
                        "late",
                        "late",
                    )

            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print(f"SKIP_TK:{type(error).__name__}")
                raise SystemExit(0)
            root.withdraw()
            page = DocumentsPage(
                root,
                component_service=ComponentService(),
                conversion_service=SlowService(),
                configured_component_path=None,
                actions=DocumentsPageActions(
                    show_info=lambda _message: None,
                    show_warning=lambda _message: None,
                    show_error=lambda _message: None,
                    confirm_overwrite=lambda _message: True,
                    persist_component_path=lambda _path: True,
                    open_result_file=lambda _path: True,
                    open_result_folder=lambda _path: True,
                ),
            )
            page.pack(fill="both", expand=True)
            page.on_show()
            deadline = time.monotonic() + 3
            while page._component_check_active and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            with tempfile.TemporaryDirectory() as temporary_dir:
                source = Path(temporary_dir) / "lento.docx"
                source.write_bytes(b"fixture")
                output = Path(temporary_dir) / "lento.pdf"
                page._source = source
                page._source_text.set(source.name)
                page._refresh_controls()
                with patch("ui_pages.filedialog.asksaveasfilename", return_value=str(output)):
                    page._start_conversion()
                heartbeats = []
                root.after(10, lambda: heartbeats.append("alive"))
                root.after(20, page._cancel_conversion)
                deadline = time.monotonic() + 3
                while page.is_busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                state = page.state.value
                result_path = page._result_path
                responsive = bool(heartbeats)
            shutdown_before = page.is_shutdown_ready
            page.begin_shutdown()
            shutdown_after = page.is_shutdown_ready
            page.close()
            root.destroy()
            print(json.dumps({
                "state": state,
                "result_path": result_path is None,
                "responsive": responsive,
                "main_thread": main_thread,
                "worker_threads": worker_threads,
                "shutdown_before": shutdown_before,
                "shutdown_after": shutdown_after,
            }))
            """
        )
        self.assertEqual(result["state"], "CANCELLED")
        self.assertTrue(result["result_path"])
        self.assertTrue(result["responsive"])
        self.assertTrue(
            all(thread != result["main_thread"] for thread in result["worker_threads"])
        )
        self.assertFalse(result["shutdown_before"])
        self.assertTrue(result["shutdown_after"])

    def test_runtime_unavailable_error_stale_result_and_layout(self) -> None:
        result = self._run_tk_script(
            r"""
            import json
            import tempfile
            import tkinter as tk
            from pathlib import Path
            from unittest.mock import patch

            import customtkinter as ctk

            from documents_component import DocumentsComponentCheck, DocumentsComponentStatus
            from documents_tools import DocumentConversionResult, DocumentConversionStatus
            from ui_pages import (
                DocumentsPage,
                DocumentsPageActions,
                _DocumentsWorkerResult,
            )

            class ImmediateThread:
                def __init__(self, *, target, **_kwargs): self.target = target
                def start(self): self.target()

            class ComponentService:
                def fast_check(self, root=None):
                    return DocumentsComponentCheck(
                        DocumentsComponentStatus.AVAILABLE, None, "test"
                    )

            class Service:
                def __init__(self): self.status = DocumentConversionStatus.COMPONENT_UNAVAILABLE
                def convert(self, request):
                    return DocumentConversionResult(
                        self.status,
                        request.output_path if self.status is DocumentConversionStatus.COMPLETED else None,
                        None,
                        "safe",
                        "safe",
                    )

            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print(f"SKIP_TK:{type(error).__name__}")
                raise SystemExit(0)
            root.withdraw()
            root.geometry("660x600")
            errors = []
            service = Service()
            page = DocumentsPage(
                root,
                component_service=ComponentService(),
                conversion_service=service,
                configured_component_path=None,
                actions=DocumentsPageActions(
                    show_info=lambda _message: None,
                    show_warning=lambda _message: None,
                    show_error=errors.append,
                    confirm_overwrite=lambda _message: True,
                    persist_component_path=lambda _path: True,
                    open_result_file=lambda _path: True,
                    open_result_folder=lambda _path: True,
                ),
                thread_factory=ImmediateThread,
            )
            page.pack(fill="both", expand=True)
            page.on_show(); page._poll_component_check()
            root.update_idletasks()
            with tempfile.TemporaryDirectory() as temporary_dir:
                source = Path(temporary_dir) / "nome muito longo" / "documento.docx"
                source.parent.mkdir()
                source.write_bytes(b"fixture")
                output = Path(temporary_dir) / "documento.pdf"
                page._source = source
                page._source_text.set(source.name)
                page._refresh_controls()
                with patch("ui_pages.filedialog.asksaveasfilename", return_value=str(output)):
                    page._start_conversion()
                page._poll_conversion()
                unavailable = (page.state.value, page._status.get())

                page._component_available = True
                page._operation_generation += 1
                current = page._operation_generation
                page._busy = True
                page._conversion_results.put(_DocumentsWorkerResult(
                    current - 1,
                    DocumentConversionResult(
                        DocumentConversionStatus.COMPLETED, output, None, "old", "old"
                    ),
                ))
                page._conversion_results.put(_DocumentsWorkerResult(
                    current,
                    DocumentConversionResult(
                        DocumentConversionStatus.ERROR, None, None, "safe", "safe"
                    ),
                ))
                page._poll_conversion()
                root.update()
                stale_final = page.state.value
            layout = {
                "hub_visible": page.tool_picker.winfo_manager() == "grid",
                "component_visible": page.component_card.winfo_manager() == "grid",
                "conversion_hidden": page.conversion_card.winfo_manager() == "",
                "source_text": page._source_text.get(),
            }
            page.close(); root.destroy()
            print(json.dumps({
                "unavailable": unavailable,
                "stale_final": stale_final,
                "errors": errors,
                "layout": layout,
            }, ensure_ascii=True))
            """
        )
        self.assertEqual(result["unavailable"][0], "COMPONENT_UNAVAILABLE")
        self.assertIn("LibreOffice indisponível", result["unavailable"][1])
        self.assertIn("TXT para PDF funciona sem ele", result["unavailable"][1])
        self.assertEqual(result["stale_final"], "ERROR")
        self.assertTrue(result["errors"])
        self.assertTrue(result["layout"]["hub_visible"])
        self.assertTrue(result["layout"]["component_visible"])
        self.assertTrue(result["layout"]["conversion_hidden"])
        self.assertEqual(result["layout"]["source_text"], "documento.docx")

    def test_three_operations_txt_without_component_pickers_and_handoffs(self) -> None:
        result = self._run_tk_script(
            r"""
            import json
            import tempfile
            import tkinter as tk
            from pathlib import Path
            from unittest.mock import patch

            import customtkinter as ctk

            from documents_component import DocumentsComponentCheck, DocumentsComponentStatus
            from documents_tools import (
                DocumentConversionResult,
                DocumentConversionStatus,
            )
            from ui_pages import DocumentsPage, DocumentsPageActions

            class ImmediateThread:
                def __init__(self, *, target, **_kwargs): self.target = target
                def start(self): self.target()

            class MissingComponentService:
                def fast_check(self, root=None):
                    return DocumentsComponentCheck(
                        DocumentsComponentStatus.NOT_CONFIGURED, None, "test"
                    )

            class Conversion:
                def __init__(self): self.calls = []
                def convert(self, request):
                    self.calls.append(request)
                    request.output_path.write_bytes(b"%PDF fixture")
                    return DocumentConversionResult(
                        DocumentConversionStatus.COMPLETED,
                        request.output_path,
                        None,
                        "ok",
                        "ok",
                    )

            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print(f"SKIP_TK:{type(error).__name__}")
                raise SystemExit(0)
            root.geometry("860x600")
            root.withdraw()
            messages = []
            conversion = Conversion()
            page = DocumentsPage(
                root,
                component_service=MissingComponentService(),
                conversion_service=conversion,
                configured_component_path=None,
                actions=DocumentsPageActions(
                    show_info=lambda message: messages.append(["info", message]),
                    show_warning=lambda message: messages.append(["warning", message]),
                    show_error=lambda message: messages.append(["error", message]),
                    confirm_overwrite=lambda _message: True,
                    persist_component_path=lambda _path: True,
                    open_result_file=lambda _path: True,
                    open_result_folder=lambda _path: True,
                ),
                thread_factory=ImmediateThread,
            )
            page.pack(fill="both", expand=True)
            root.deiconify()
            page.on_show(); page._poll_component_check()
            root.update_idletasks()
            with tempfile.TemporaryDirectory() as temporary_dir:
                base = Path(temporary_dir)
                docx = base / "Plano.docx"; docx.write_bytes(b"fixture")
                odt = base / "Atividade 你好.odt"; odt.write_bytes(b"fixture")
                txt = base / "Anotações 你好.txt"; txt.write_text("olá", encoding="utf-8")
                output = base / "Anotações 你好.pdf"

                initial = [page.operation.value, page.convert_button.cget("state")]
                txt_handoff = page.prepare_txt_to_pdf(txt)
                txt_ready = [
                    page.operation.value,
                    page._source_text.get(),
                    page.convert_button.cget("state"),
                    len(conversion.calls),
                ]
                page._result_path = output
                page._change_operation("OpenDocument para PDF")
                switched = [
                    page.operation.value,
                    page._source is None,
                    page._result_path is None,
                    page.convert_button.cget("state"),
                ]
                odt_handoff = page.prepare_odt_to_pdf(odt)
                odt_missing = [page.operation.value, page.convert_button.cget("state")]
                page._apply_component_status(DocumentsComponentStatus.AVAILABLE)
                odt_available = page.convert_button.cget("state")

                picker_filters = []
                for label, selected in (
                    ("Word para PDF", docx),
                    ("Texto para PDF", txt),
                    ("OpenDocument para PDF", odt),
                ):
                    page._change_operation(label)
                    with patch("ui_pages.filedialog.askopenfilename", return_value=str(selected)) as dialog:
                        page._select_document()
                    picker_filters.append(dialog.call_args.kwargs["filetypes"][0][1])

                page._component_available = False
                page.prepare_txt_to_pdf(txt)
                with patch("ui_pages.filedialog.asksaveasfilename", return_value=str(output)) as save:
                    page._start_conversion()
                page._poll_conversion()
                converted = [
                    conversion.calls[-1].input_format.value,
                    save.call_args.kwargs["initialfile"],
                    page.state.value,
                    page._result_path.name,
                ]
                wrong_doc = page.prepare_odt_to_pdf(docx)
                ctk.set_appearance_mode("Light"); root.update_idletasks()
                light_width = page.winfo_width()
                ctk.set_appearance_mode("Dark"); root.update_idletasks()
                dark_width = page.winfo_width()
                operation_width = page.operation_control.winfo_width()

            page.close(); root.destroy()
            print(json.dumps({
                "tools": list(page.tool_names),
                "initial": initial,
                "txt_handoff": txt_handoff,
                "txt_ready": txt_ready,
                "switched": switched,
                "odt_handoff": odt_handoff,
                "odt_missing": odt_missing,
                "odt_available": odt_available,
                "picker_filters": picker_filters,
                "converted": converted,
                "wrong_doc": wrong_doc,
                "widths": [light_width, dark_width],
                "operation_width": operation_width,
                "messages": messages,
            }, ensure_ascii=True))
            """
        )
        self.assertEqual(
            result["tools"],
            ["Word para PDF", "Texto para PDF", "OpenDocument para PDF"],
        )
        self.assertEqual(result["initial"], ["DOCX", "disabled"])
        self.assertTrue(result["txt_handoff"])
        self.assertEqual(
            result["txt_ready"], ["TXT", "Anotações 你好.txt", "normal", 0]
        )
        self.assertEqual(result["switched"], ["ODT", True, True, "disabled"])
        self.assertTrue(result["odt_handoff"])
        self.assertEqual(result["odt_missing"], ["ODT", "disabled"])
        self.assertEqual(result["odt_available"], "normal")
        self.assertEqual(result["picker_filters"], ["*.docx", "*.txt", "*.odt"])
        self.assertEqual(
            result["converted"],
            ["TXT", "Anotações 你好.pdf", "COMPLETED", "Anotações 你好.pdf"],
        )
        self.assertFalse(result["wrong_doc"])
        self.assertTrue(all(width > 0 for width in result["widths"]))
        self.assertLess(result["operation_width"], min(result["widths"]))


if __name__ == "__main__":
    unittest.main()
