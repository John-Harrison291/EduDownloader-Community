"""Testes do fluxo da página Mídia sem depender de coordenadas de tela."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

from mp3_quality import DEFAULT_MP3_QUALITY, MP3_QUALITY_OPTIONS


class MediaToolsPageRealTkTests(unittest.TestCase):
    def test_quality_progress_result_actions_and_immediate_cancel(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    import customtkinter as ctk
                    from media_tools import MediaConversionProgress, MediaConversionResult, MediaOperationCancelled
                    from mp3_quality import DEFAULT_MP3_QUALITY, MP3_QUALITY_OPTIONS, Mp3Quality
                    from ui_pages import MediaPageActions, MediaToolsPage, MediaUiState

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target
                        def start(self):
                            self.target()

                    class DeferredFactory:
                        def __init__(self):
                            self.threads = []
                        def __call__(self, *, target, **_kwargs):
                            class DeferredThread:
                                def start(self_inner):
                                    return None
                            result = DeferredThread()
                            result.target = target
                            self.threads.append(result)
                            return result

                    class Service:
                        def __init__(self):
                            self.profiles = []
                            self.cancel_calls = 0
                        def video_to_mp3(self, source, output, *, overwrite=False, quality=None, on_progress=None, cancel_event=None):
                            self.profiles.append(quality.value)
                            if cancel_event.is_set():
                                raise MediaOperationCancelled("cancelada")
                            on_progress(MediaConversionProgress(0.0, 2.0))
                            on_progress(MediaConversionProgress(1.0, 2.0))
                            Path(output).write_bytes(b"synthetic-result")
                            return MediaConversionResult(Path(output), 2.0)
                        def request_cancel(self):
                            self.cancel_calls += 1
                            return True

                    opened = []
                    def open_result(path):
                        opened.append(("file", path.name))
                        return path.is_file()
                    def open_folder(path):
                        opened.append(("folder", path.name))
                        return path.is_file()

                    actions = MediaPageActions(
                        show_info=lambda _message: None,
                        show_warning=lambda _message: None,
                        show_error=lambda _message: None,
                        confirm_overwrite=lambda _message: True,
                        open_result_file=open_result,
                        open_result_folder=open_folder,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    with tempfile.TemporaryDirectory() as directory:
                        folder = Path(directory)
                        source = folder / "vídeo ção.mp4"
                        source.write_bytes(b"fixture")
                        output = folder / "áudio ção.mp3"
                        service = Service()
                        page = MediaToolsPage(root, service=service, actions=actions, thread_factory=ImmediateThread)
                        page.pack()
                        root.update_idletasks()
                        initial = {
                            "labels": page.quality_menu.cget("values"),
                            "default": page.quality_menu.get(),
                            "cancel": page.cancel_button.cget("state"),
                            "open": page.open_file_button.cget("state"),
                        }
                        page._prepare_video_source(source)
                        page.quality_menu.set(Mp3Quality.HIGH.display_label)
                        with patch("ui_pages.filedialog.asksaveasfilename", return_value=str(output)):
                            page._start_conversion()
                        active = {
                            "quality": page.quality_menu.cget("state"),
                            "cancel": page.cancel_button.cget("state"),
                            "open": page.open_file_button.cget("state"),
                        }
                        page._consume_progress()
                        progress = {
                            "mode": page.progress_bar.cget("mode"),
                            "value": page.progress_bar.get(),
                            "state": page._state.value,
                        }
                        page._poll_worker()
                        completed_state = {
                            "state": page._state.value,
                            "open": page.open_file_button.cget("state"),
                            "folder": page.open_folder_button.cget("state"),
                            "quality": page.quality_menu.cget("state"),
                        }
                        page._open_result_file()
                        page._open_result_folder()
                        output.unlink()
                        page._open_result_file()
                        missing_state = page.open_file_button.cget("state")
                        page._prepare_video_source(source)
                        new_source_state = page.open_file_button.cget("state")
                        page.close()

                        deferred = DeferredFactory()
                        cancelled = MediaToolsPage(
                            root, service=service, actions=actions,
                            thread_factory=deferred,
                            shutdown_thread_factory=ImmediateThread,
                        )
                        cancelled.pack()
                        cancelled._prepare_video_source(source)
                        with patch("ui_pages.filedialog.asksaveasfilename", return_value=str(folder / "cancelado.mp3")):
                            cancelled._start_conversion()
                        cancelled._cancel_conversion()
                        cancel_state = cancelled._state.value
                        cancel_text = cancelled._status.get()
                        cancel_button_state = cancelled.cancel_button.cget("state")
                        cancelled._progress_results.put((cancelled._operation_generation, MediaConversionProgress(1.5, 2.0)))
                        cancelled._consume_progress()
                        late_progress_state = cancelled._state.value
                        deferred.threads[0].target()
                        cancelled._poll_worker()
                        final_cancel_state = cancelled._state.value
                        cancel_output = (folder / "cancelado.mp3").exists()
                        cancelled.close()

                        fallback = MediaToolsPage(root, service=service, actions=actions)
                        fallback._busy = True
                        fallback._progress_results.put((fallback._operation_generation, MediaConversionProgress(1.0, None)))
                        fallback._consume_progress()
                        fallback_mode = fallback.progress_bar.cget("mode")
                        fallback._progress_results.put((fallback._operation_generation - 1, MediaConversionProgress(1.0, 2.0)))
                        fallback._consume_progress()
                        stale_mode = fallback.progress_bar.cget("mode")
                        fallback.close()

                    root.destroy()
                    print(json.dumps({
                        "initial": initial, "active": active, "progress": progress,
                        "completed": completed_state, "profiles": service.profiles,
                        "opened": opened, "missing": missing_state,
                        "new_source": new_source_state, "cancel_state": cancel_state,
                        "cancel_text": cancel_text,
                        "cancel_button_state": cancel_button_state,
                        "final_cancel_state": final_cancel_state,
                        "cancel_output": cancel_output, "cancel_calls": service.cancel_calls,
                        "late_progress_state": late_progress_state,
                        "fallback_mode": fallback_mode,
                        "stale_mode": stale_mode,
                    }, ensure_ascii=True))
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
            result["initial"]["labels"],
            [profile.display_label for profile in MP3_QUALITY_OPTIONS],
        )
        self.assertEqual(
            result["initial"]["default"], DEFAULT_MP3_QUALITY.display_label
        )
        self.assertEqual(result["initial"]["cancel"], "disabled")
        self.assertEqual(result["initial"]["open"], "disabled")
        self.assertEqual(
            result["active"],
            {"quality": "disabled", "cancel": "normal", "open": "disabled"},
        )
        self.assertEqual(result["progress"]["mode"], "determinate")
        self.assertAlmostEqual(result["progress"]["value"], 0.5)
        self.assertEqual(result["progress"]["state"], "CONVERTING")
        self.assertEqual(
            result["completed"],
            {
                "state": "COMPLETED",
                "open": "normal",
                "folder": "normal",
                "quality": "normal",
            },
        )
        self.assertEqual(result["profiles"], ["high", "standard"])
        self.assertEqual(
            result["opened"],
            [
                ["file", "áudio ção.mp3"],
                ["folder", "áudio ção.mp3"],
                ["file", "áudio ção.mp3"],
            ],
        )
        self.assertEqual(result["missing"], "disabled")
        self.assertEqual(result["new_source"], "disabled")
        self.assertEqual(result["cancel_state"], "CANCELLING")
        self.assertEqual(result["cancel_text"], "Cancelando...")
        self.assertEqual(result["cancel_button_state"], "disabled")
        self.assertEqual(result["late_progress_state"], "CANCELLING")
        self.assertEqual(result["final_cancel_state"], "CANCELLED")
        self.assertFalse(result["cancel_output"])
        self.assertEqual(result["cancel_calls"], 1)
        self.assertEqual(result["fallback_mode"], "indeterminate")
        self.assertEqual(result["stale_mode"], "indeterminate")

    def test_video_selection_worker_conflict_and_persistent_page_state(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import threading
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    import customtkinter as ctk

                    from media_tools import MediaConversionResult
                    from ui_pages import MediaPageActions, MediaToolsPage

                    main_thread = threading.get_ident()
                    worker_names = []
                    worker_threads = []

                    class JoinedThread:
                        def __init__(self, *, target, name, daemon):
                            self.target = target
                            self.name = name
                            self.daemon = daemon
                            worker_names.append(name)

                        def start(self):
                            def run():
                                worker_threads.append(threading.get_ident())
                                self.target()

                            thread = threading.Thread(
                                target=run,
                                name=self.name,
                                daemon=self.daemon,
                            )
                            thread.start()
                            thread.join()

                    class Service:
                        def __init__(self):
                            self.calls = []

                        def video_to_mp3(self, source, output, *, overwrite=False, quality=None, on_progress=None, cancel_event=None):
                            self.calls.append((
                                Path(source).name,
                                Path(output).name,
                                overwrite,
                                threading.get_ident(),
                            ))
                            return MediaConversionResult(Path(output), 3.5)

                    service = Service()
                    messages = []
                    confirmations = []
                    allow_overwrite = [True]

                    def confirm(message):
                        confirmations.append(message)
                        return allow_overwrite[0]

                    actions = MediaPageActions(
                        show_info=lambda message: messages.append((
                            "info", message, threading.get_ident()
                        )),
                        show_warning=lambda message: messages.append((
                            "warning", message, threading.get_ident()
                        )),
                        show_error=lambda message: messages.append((
                            "error", message, threading.get_ident()
                        )),
                        confirm_overwrite=confirm,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    root.geometry("660x600")
                    page = MediaToolsPage(
                        root,
                        service=service,
                        actions=actions,
                        thread_factory=JoinedThread,
                    )
                    page.pack(fill="both", expand=True)
                    root.update_idletasks()
                    assert not page.segment_fields.grid_info()
                    assert not page.progress_bar.grid_info()
                    assert not page.cancel_button.grid_info()
                    page._extraction_mode.set("Somente um trecho")
                    assert page.segment_fields.grid_info()
                    assert page.extraction_mode_menu.get() == "Trecho específico"
                    page._extraction_mode.set("Áudio completo")
                    assert not page.segment_fields.grid_info()
                    initial = {
                        "placeholder": page.is_placeholder,
                        "tools": list(page.tool_names),
                        "select_text": page.select_button.cget("text"),
                        "convert_text": page.convert_button.cget("text"),
                        "convert_state": page.convert_button.cget("state"),
                        "progress_mode": page.progress_bar.cget("mode"),
                        "description_width": page.description_label.winfo_width(),
                        "page_width": page.winfo_width(),
                    }

                    with patch(
                        "ui_pages.filedialog.askopenfilename",
                        return_value="C:/Aulas com espaço/vídeo ção.mp4",
                    ):
                        page._select_video()
                    selected_name = page._source_text.get()
                    enabled_after_selection = page.convert_button.cget("state")
                    page.pack_forget()
                    page.pack()
                    persistent_name = page._source_text.get()

                    with tempfile.TemporaryDirectory() as output_dir:
                        output = Path(output_dir) / "vídeo ção.mp3"
                        output.write_bytes(b"existing")
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(output),
                        ):
                            page._start_conversion()
                        busy_before_delivery = page.is_busy
                        disabled_during_worker = page.convert_button.cget("state")
                        page.pack_forget()
                        page.pack()
                        persistent_during_worker = page._source_text.get()
                        page._poll_worker()

                        allow_overwrite[0] = False
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(output),
                        ):
                            page._start_conversion()

                    result = {
                        "initial": initial,
                        "selected_name": selected_name,
                        "enabled_after_selection": enabled_after_selection,
                        "persistent_name": persistent_name,
                        "busy_before_delivery": busy_before_delivery,
                        "disabled_during_worker": disabled_during_worker,
                        "persistent_during_worker": persistent_during_worker,
                        "busy_after_delivery": page.is_busy,
                        "calls": service.calls,
                        "messages": messages,
                        "confirmations": confirmations,
                        "worker_names": worker_names,
                        "worker_threads": worker_threads,
                        "main_thread": main_thread,
                        "status": page._status.get(),
                    }
                    page.close()
                    root.destroy()
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
        self.assertFalse(result["initial"]["placeholder"])
        self.assertEqual(result["initial"]["tools"], ["Extrair áudio do vídeo"])
        self.assertEqual(result["initial"]["select_text"], "Selecionar vídeo")
        self.assertEqual(result["initial"]["convert_text"], "Extrair MP3")
        self.assertEqual(result["initial"]["convert_state"], "disabled")
        self.assertEqual(result["initial"]["progress_mode"], "indeterminate")
        self.assertLess(
            result["initial"]["description_width"], result["initial"]["page_width"]
        )
        self.assertEqual(result["selected_name"], "vídeo ção.mp4")
        self.assertEqual(result["persistent_name"], "vídeo ção.mp4")
        self.assertEqual(result["enabled_after_selection"], "normal")
        self.assertTrue(result["busy_before_delivery"])
        self.assertEqual(result["disabled_during_worker"], "disabled")
        self.assertEqual(result["persistent_during_worker"], "vídeo ção.mp4")
        self.assertFalse(result["busy_after_delivery"])
        self.assertEqual(len(result["calls"]), 1)
        self.assertEqual(
            result["calls"][0][:3], ["vídeo ção.mp4", "vídeo ção.mp3", True]
        )
        self.assertEqual(len(result["confirmations"]), 2)
        self.assertIn("vídeo ção.mp3", result["confirmations"][0])
        self.assertEqual(result["worker_names"], ["edudownloader-media-worker"])
        self.assertTrue(
            all(
                thread_id != result["main_thread"]
                for thread_id in result["worker_threads"]
            )
        )
        self.assertEqual(result["calls"][0][3], result["worker_threads"][0])
        self.assertEqual(result["messages"][0][0], "info")
        self.assertEqual(result["messages"][0][1], 'MP3 criado: "vídeo ção.mp3".')
        self.assertEqual(result["messages"][0][2], result["main_thread"])
        self.assertIn("não iniciada", result["status"])

    def test_public_video_handoff_validates_replaces_and_rejects_busy(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    import customtkinter as ctk

                    from media_tools import MediaConversionResult
                    from mp3_quality import Mp3Quality
                    from ui_pages import MediaPageActions, MediaToolsPage, MediaUiState

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            self.target()

                    class Service:
                        def __init__(self):
                            self.calls = []

                        def video_to_mp3(self, source, output, *, overwrite=False, quality=None, on_progress=None, cancel_event=None):
                            self.calls.append((
                                Path(source).name,
                                Path(output).name,
                                overwrite,
                            ))
                            Path(output).write_bytes(b"synthetic-result")
                            return MediaConversionResult(Path(output), 2.0)

                    warnings = []
                    actions = MediaPageActions(
                        show_info=lambda _message: None,
                        show_warning=warnings.append,
                        show_error=lambda _message: None,
                        confirm_overwrite=lambda _message: False,
                        open_result_file=lambda _path: True,
                        open_result_folder=lambda _path: True,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    service = Service()
                    page = MediaToolsPage(
                        root,
                        service=service,
                        actions=actions,
                        thread_factory=ImmediateThread,
                    )
                    page.pack()
                    root.update_idletasks()

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        first_video = directory / "primeiro.mp4"
                        source_folder = directory / "Pasta com espaços — ação de Mídia"
                        source_folder.mkdir()
                        second_video = source_folder / "vídeo ação.MKV"
                        wrong_file = directory / "incompatível.txt"
                        video_directory = directory / "pasta.mp4"
                        for path in (first_video, second_video, wrong_file):
                            path.write_bytes(b"fixture")
                        video_directory.mkdir()

                        invalid_results = {
                            "missing": page.prepare_video_to_mp3_source(
                                directory / "ausente.mp4"
                            ),
                            "wrong": page.prepare_video_to_mp3_source(wrong_file),
                            "directory": page.prepare_video_to_mp3_source(
                                video_directory
                            ),
                        }
                        first_result = page.prepare_video_to_mp3_source(first_video)
                        first_state = {
                            "source": page._source.name,
                            "text": page._source_text.get(),
                            "status": page._status.get(),
                            "button": page.convert_button.cget("state"),
                        }
                        second_result = page.prepare_video_to_mp3_source(second_video)
                        second_state = {
                            "source": page._source.name,
                            "path": str(page._source),
                            "text": page._source_text.get(),
                            "status": page._status.get(),
                        }
                        calls_before_explicit_conversion = list(service.calls)
                        output = directory / "resultado.mp3"
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(output),
                        ):
                            page._start_conversion()
                        busy_snapshot = {
                            "source": page._source.name,
                            "text": page._source_text.get(),
                            "status": page._status.get(),
                            "button": page.convert_button.cget("state"),
                        }
                        busy_result = page.prepare_video_to_mp3_source(first_video)
                        busy_unchanged = busy_snapshot == {
                            "source": page._source.name,
                            "text": page._source_text.get(),
                            "status": page._status.get(),
                            "button": page.convert_button.cget("state"),
                        }
                        busy_states = {}
                        for state in (MediaUiState.CONVERTING, MediaUiState.CANCELLING):
                            page._state = state
                            busy_states[state.value] = (
                                not page.prepare_video_to_mp3_source(first_video)
                                and page._source == second_video
                            )
                        page._poll_worker()
                        busy_after_delivery = page.is_busy
                        completed_state = {
                            "state": page._state.value,
                            "progress": page.progress_bar.get(),
                            "open": page.open_file_button.cget("state"),
                            "folder": page.open_folder_button.cget("state"),
                        }
                        page.quality_menu.set(Mp3Quality.HIGH.display_label)
                        next_result = page.prepare_video_to_mp3_source(first_video)
                        next_state = {
                            "source": page._source.name,
                            "state": page._state.value,
                            "quality": page.quality_menu.get(),
                            "progress_mode": page.progress_bar.cget("mode"),
                            "progress": page.progress_bar.get(),
                            "result": page._result_path,
                            "open": page.open_file_button.cget("state"),
                            "folder": page.open_folder_button.cget("state"),
                            "old_output_exists": output.is_file(),
                        }
                        terminal_recovery = {}
                        for state in (MediaUiState.ERROR, MediaUiState.CANCELLED):
                            page._state = state
                            page.quality_menu.set(Mp3Quality.HIGH.display_label)
                            page.progress_bar.set(0.75)
                            accepted = page.prepare_video_to_mp3_source(second_video)
                            terminal_recovery[state.value] = {
                                "accepted": accepted,
                                "state": page._state.value,
                                "source": str(page._source),
                                "quality": page.quality_menu.get(),
                                "progress": page.progress_bar.get(),
                            }

                    result = {
                        "invalid_results": invalid_results,
                        "first_result": first_result,
                        "first_state": first_state,
                        "second_result": second_result,
                        "second_state": second_state,
                        "busy_result": busy_result,
                        "busy_unchanged": busy_unchanged,
                        "busy_states": busy_states,
                        "busy_after_delivery": busy_after_delivery,
                        "completed_state": completed_state,
                        "next_result": next_result,
                        "next_state": next_state,
                        "terminal_recovery": terminal_recovery,
                        "calls_before_explicit_conversion": (
                            calls_before_explicit_conversion
                        ),
                        "calls": service.calls,
                        "warnings": warnings,
                    }
                    page.close()
                    root.destroy()
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
        self.assertFalse(any(result["invalid_results"].values()))
        self.assertTrue(result["first_result"])
        self.assertEqual(result["first_state"]["source"], "primeiro.mp4")
        self.assertEqual(result["first_state"]["text"], "primeiro.mp4")
        self.assertEqual(result["first_state"]["button"], "normal")
        self.assertTrue(result["second_result"])
        self.assertEqual(result["second_state"]["source"], "vídeo ação.MKV")
        self.assertIn("Pasta com espaços", result["second_state"]["path"])
        self.assertEqual(result["second_state"]["text"], "vídeo ação.MKV")
        self.assertIn("selecionado", result["second_state"]["status"].casefold())
        self.assertFalse(result["busy_result"])
        self.assertTrue(result["busy_unchanged"])
        self.assertEqual(
            result["busy_states"], {"CONVERTING": True, "CANCELLING": True}
        )
        self.assertFalse(result["busy_after_delivery"])
        self.assertEqual(result["completed_state"]["state"], "COMPLETED")
        self.assertEqual(result["completed_state"]["progress"], 1)
        self.assertEqual(result["completed_state"]["open"], "normal")
        self.assertEqual(result["completed_state"]["folder"], "normal")
        self.assertTrue(result["next_result"])
        self.assertEqual(result["next_state"]["source"], "primeiro.mp4")
        self.assertEqual(result["next_state"]["state"], "READY")
        self.assertEqual(
            result["next_state"]["quality"], DEFAULT_MP3_QUALITY.display_label
        )
        self.assertEqual(result["next_state"]["progress"], 0)
        self.assertEqual(result["next_state"]["progress_mode"], "indeterminate")
        self.assertIsNone(result["next_state"]["result"])
        self.assertEqual(result["next_state"]["open"], "disabled")
        self.assertEqual(result["next_state"]["folder"], "disabled")
        self.assertTrue(result["next_state"]["old_output_exists"])
        for state in ("ERROR", "CANCELLED"):
            recovered = result["terminal_recovery"][state]
            self.assertTrue(recovered["accepted"])
            self.assertEqual(recovered["state"], "READY")
            self.assertEqual(recovered["source"], result["second_state"]["path"])
            self.assertEqual(recovered["quality"], DEFAULT_MP3_QUALITY.display_label)
            self.assertEqual(recovered["progress"], 0)
        self.assertEqual(result["calls_before_explicit_conversion"], [])
        self.assertEqual(result["calls"], [["vídeo ação.MKV", "resultado.mp3", False]])
        self.assertGreaterEqual(len(result["warnings"]), 4)

    def test_worker_start_failure_restores_video_selection_and_allows_retry(
        self,
    ) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import Mock, patch

                    import customtkinter as ctk

                    from media_tools import MediaConversionResult
                    from ui_pages import MediaPageActions, MediaToolsPage

                    class ControlledThread:
                        fail_next = True

                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            if type(self).fail_next:
                                type(self).fail_next = False
                                raise OSError(
                                    "detalhe interno C:/Usuário/vídeo privado.mp4"
                                )
                            self.target()

                    class Service:
                        def __init__(self):
                            self.calls = []

                        def video_to_mp3(self, source, output, *, overwrite=False, quality=None, on_progress=None, cancel_event=None):
                            self.calls.append((
                                Path(source).name,
                                Path(output).name,
                                overwrite,
                            ))
                            return MediaConversionResult(Path(output), 2.0)

                    messages = []
                    actions = MediaPageActions(
                        show_info=lambda message: messages.append(("info", message)),
                        show_warning=lambda message: messages.append(
                            ("warning", message)
                        ),
                        show_error=lambda message: messages.append(("error", message)),
                        confirm_overwrite=lambda _message: True,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    service = Service()
                    page = MediaToolsPage(
                        root,
                        service=service,
                        actions=actions,
                        thread_factory=ControlledThread,
                    )
                    page.pack()
                    root.update_idletasks()
                    after_calls = []
                    page.after = lambda delay, callback: after_calls.append(
                        (delay, callback.__name__)
                    )
                    page.progress_bar.start = Mock(wraps=page.progress_bar.start)
                    page.progress_bar.stop = Mock(wraps=page.progress_bar.stop)

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        source = directory / "vídeo ação.mp4"
                        output = directory / "áudio ação.mp3"
                        source.write_bytes(b"synthetic-fixture")
                        page._prepare_video_source(source)

                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(output),
                        ):
                            page._start_conversion()
                            failure = {
                                "busy": page.is_busy,
                                "source": page._source.name,
                                "source_text": page._source_text.get(),
                                "select_button": page.select_button.cget("state"),
                                "convert_button": page.convert_button.cget("state"),
                                "progress": page.progress_bar.get(),
                                "queue_empty": page._results.empty(),
                                "polls": len(after_calls),
                                "calls": list(service.calls),
                                "output_exists": output.exists(),
                                "status": page._status.get(),
                            }
                            page.pack_forget()
                            page.pack()
                            selection_after_navigation = page._source_text.get()
                            page._start_conversion()
                            busy_on_retry = page.is_busy
                            polls_on_retry = len(after_calls)
                            page._poll_worker()

                        retry = {
                            "busy": page.is_busy,
                            "source": page._source.name,
                            "source_text": page._source_text.get(),
                            "convert_button": page.convert_button.cget("state"),
                            "calls": service.calls,
                            "output_exists": output.exists(),
                        }

                    result = {
                        "failure": failure,
                        "selection_after_navigation": selection_after_navigation,
                        "busy_on_retry": busy_on_retry,
                        "polls_on_retry": polls_on_retry,
                        "retry": retry,
                        "messages": messages,
                        "progress_starts": page.progress_bar.start.call_count,
                        "progress_stops": page.progress_bar.stop.call_count,
                        "closed_before": page._closed,
                    }
                    page.close()
                    result["closed_after"] = page._closed
                    root.destroy()
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
        failure = result["failure"]
        self.assertFalse(failure["busy"])
        self.assertEqual(failure["source"], "vídeo ação.mp4")
        self.assertEqual(failure["source_text"], "vídeo ação.mp4")
        self.assertEqual(failure["select_button"], "normal")
        self.assertEqual(failure["convert_button"], "normal")
        self.assertEqual(failure["progress"], 0)
        self.assertTrue(failure["queue_empty"])
        self.assertEqual(failure["polls"], 0)
        self.assertEqual(failure["calls"], [])
        self.assertFalse(failure["output_exists"])
        self.assertEqual(
            failure["status"],
            "Não foi possível iniciar a operação. Tente novamente.",
        )
        self.assertEqual(result["selection_after_navigation"], "vídeo ação.mp4")
        self.assertTrue(result["busy_on_retry"])
        self.assertEqual(result["polls_on_retry"], 1)
        self.assertFalse(result["retry"]["busy"])
        self.assertEqual(result["retry"]["source"], "vídeo ação.mp4")
        self.assertEqual(result["retry"]["source_text"], "vídeo ação.mp4")
        self.assertEqual(result["retry"]["convert_button"], "normal")
        self.assertEqual(
            result["retry"]["calls"],
            [["vídeo ação.mp4", "áudio ação.mp3", False]],
        )
        self.assertFalse(result["retry"]["output_exists"])
        error_messages = [
            message for kind, message in result["messages"] if kind == "error"
        ]
        self.assertEqual(
            error_messages,
            ["Não foi possível iniciar a operação. Tente novamente."],
        )
        self.assertEqual(result["progress_starts"], result["progress_stops"])
        self.assertFalse(result["closed_before"])
        self.assertTrue(result["closed_after"])

    def test_cancelled_media_worker_is_delivered_without_error_dialog(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    import customtkinter as ctk

                    from media_tools import MediaOperationCancelled
                    from ui_pages import MediaPageActions, MediaToolsPage

                    class ImmediateThread:
                        def __init__(self, *, target, **_kwargs):
                            self.target = target

                        def start(self):
                            self.target()

                    class Service:
                        def video_to_mp3(self, source, output, *, overwrite=False, quality=None, on_progress=None, cancel_event=None):
                            raise MediaOperationCancelled(
                                "A operação de mídia foi cancelada."
                            )

                    messages = []
                    actions = MediaPageActions(
                        show_info=lambda message: messages.append(("info", message)),
                        show_warning=lambda message: messages.append(
                            ("warning", message)
                        ),
                        show_error=lambda message: messages.append(("error", message)),
                        confirm_overwrite=lambda _message: True,
                    )
                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    page = MediaToolsPage(
                        root,
                        service=Service(),
                        actions=actions,
                        thread_factory=ImmediateThread,
                    )
                    page.pack()
                    root.update_idletasks()
                    page.after = lambda _delay, _callback: None

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        source = directory / "vídeo ação.mp4"
                        output = directory / "áudio ação.mp3"
                        source.write_bytes(b"synthetic-fixture")
                        page._prepare_video_source(source)
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(output),
                        ):
                            page._start_conversion()
                        busy_before_delivery = page.is_busy
                        page._poll_worker()
                        result = {
                            "busy_before_delivery": busy_before_delivery,
                            "busy_after_delivery": page.is_busy,
                            "status": page._status.get(),
                            "messages": messages,
                            "output_exists": output.exists(),
                            "convert_button": page.convert_button.cget("state"),
                        }

                    page.close()
                    root.destroy()
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
        self.assertTrue(result["busy_before_delivery"])
        self.assertFalse(result["busy_after_delivery"])
        self.assertEqual(result["status"], "Conversão de mídia cancelada.")
        self.assertEqual(result["messages"], [])
        self.assertFalse(result["output_exists"])
        self.assertEqual(result["convert_button"], "normal")

    def test_shutdown_cancels_media_worker_and_allows_retry_after_safe_failure(
        self,
    ) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import json
                    import tempfile
                    import threading
                    import tkinter as tk
                    from pathlib import Path
                    from unittest.mock import patch

                    import customtkinter as ctk

                    from media_tools import MediaOperationCancelled, MediaToolsError
                    from ui_pages import MediaPageActions, MediaToolsPage

                    class DeferredThread:
                        def __init__(self, *, target, name, daemon):
                            self.target = target
                            self.name = name
                            self.daemon = daemon

                        def start(self):
                            return None

                    class DeferredFactory:
                        def __init__(self):
                            self.threads = []

                        def __call__(self, **kwargs):
                            thread = DeferredThread(**kwargs)
                            self.threads.append(thread)
                            return thread

                    main_thread = threading.get_ident()
                    shutdown_thread_names = []
                    shutdown_thread_ids = []

                    class JoinedShutdownThread:
                        def __init__(self, *, target, name, daemon):
                            self.target = target
                            self.name = name
                            self.daemon = daemon
                            shutdown_thread_names.append(name)

                        def start(self):
                            def run():
                                shutdown_thread_ids.append(threading.get_ident())
                                self.target()

                            thread = threading.Thread(
                                target=run,
                                name=self.name,
                                daemon=self.daemon,
                            )
                            thread.start()
                            thread.join()

                    class Service:
                        def __init__(self, *, fail_cancel=False):
                            self.fail_cancel = fail_cancel
                            self.cancel_requested = False
                            self.cancel_calls = 0
                            self.conversion_calls = 0

                        def request_cancel(self):
                            self.cancel_calls += 1
                            if self.fail_cancel:
                                raise MediaToolsError("detalhe privado do subprocesso")
                            self.cancel_requested = True
                            return True

                        def video_to_mp3(self, _source, _output, *, overwrite=False, quality=None, on_progress=None, cancel_event=None):
                            self.conversion_calls += 1
                            if self.cancel_requested:
                                raise MediaOperationCancelled(
                                    "A operação de mídia foi cancelada."
                                )
                            raise AssertionError("worker entregue sem cancelamento")

                    def button_texts(widget):
                        texts = []
                        for child in widget.winfo_children():
                            if isinstance(child, ctk.CTkButton):
                                texts.append(child.cget("text"))
                            texts.extend(button_texts(child))
                        return texts

                    def make_page(root, service, messages):
                        factory = DeferredFactory()
                        page = MediaToolsPage(
                            root,
                            service=service,
                            actions=MediaPageActions(
                                show_info=lambda message: messages.append(
                                    ("info", message)
                                ),
                                show_warning=lambda message: messages.append(
                                    ("warning", message)
                                ),
                                show_error=lambda message: messages.append(
                                    ("error", message)
                                ),
                                confirm_overwrite=lambda _message: True,
                            ),
                            thread_factory=factory,
                            shutdown_thread_factory=JoinedShutdownThread,
                        )
                        page.pack()
                        page.after = lambda _delay, _callback: None
                        root.update_idletasks()
                        return page, factory

                    try:
                        root = ctk.CTk()
                    except tk.TclError as error:
                        print(f"SKIP_TK:{type(error).__name__}")
                        raise SystemExit(0)
                    root.withdraw()
                    messages = []

                    with tempfile.TemporaryDirectory() as temporary_dir:
                        directory = Path(temporary_dir)
                        source = directory / "vídeo ação.mp4"
                        output = directory / "áudio ação.mp3"
                        source.write_bytes(b"synthetic-fixture")

                        idle_service = Service()
                        idle, idle_factory = make_page(
                            root, idle_service, messages
                        )
                        idle._prepare_video_source(source)
                        idle.begin_shutdown()
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename"
                        ) as save_dialog:
                            idle._start_conversion()
                        idle_snapshot = {
                            "ready": idle.is_shutdown_ready,
                            "cancel_calls": idle_service.cancel_calls,
                            "workers": len(idle_factory.threads),
                            "dialog_calls": save_dialog.call_count,
                            "select_button": idle.select_button.cget("state"),
                            "convert_button": idle.convert_button.cget("state"),
                            "has_cancel_button": any(
                                "cancel" in str(text).casefold()
                                for text in button_texts(idle)
                            ),
                        }
                        idle.cancel_shutdown()
                        idle_snapshot["restored_button"] = (
                            idle.convert_button.cget("state")
                        )

                        service = Service()
                        active, active_factory = make_page(
                            root, service, messages
                        )
                        active._prepare_video_source(source)
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(output),
                        ):
                            active._start_conversion()
                        active.begin_shutdown()
                        active_before = {
                            "busy": active.is_busy,
                            "ready": active.is_shutdown_ready,
                            "cancel_calls": service.cancel_calls,
                            "convert_button": active.convert_button.cget("state"),
                            "shutdown_worker_names": list(shutdown_thread_names),
                            "shutdown_off_main": all(
                                thread_id != main_thread
                                for thread_id in shutdown_thread_ids
                            ),
                        }
                        active_factory.threads[0].target()
                        active._poll_worker()
                        active_after = {
                            "busy": active.is_busy,
                            "ready": active.is_shutdown_ready,
                            "status": active._status.get(),
                            "conversion_calls": service.conversion_calls,
                            "source_exists": source.exists(),
                            "output_exists": output.exists(),
                        }

                        failing_service = Service(fail_cancel=True)
                        failing, failing_factory = make_page(
                            root, failing_service, messages
                        )
                        failing._prepare_video_source(source)
                        with patch(
                            "ui_pages.filedialog.asksaveasfilename",
                            return_value=str(output),
                        ):
                            failing._start_conversion()
                        failing.begin_shutdown()
                        first_error = failing.shutdown_error
                        failure_snapshot = {
                            "ready": failing.is_shutdown_ready,
                            "cancel_calls": failing_service.cancel_calls,
                            "error": first_error,
                            "busy": failing.is_busy,
                        }
                        failing.cancel_shutdown()
                        failing_service.fail_cancel = False
                        failing.begin_shutdown()
                        retry_before = {
                            "ready": failing.is_shutdown_ready,
                            "cancel_calls": failing_service.cancel_calls,
                            "error": failing.shutdown_error,
                        }
                        failing_factory.threads[0].target()
                        failing._poll_worker()
                        retry_after = {
                            "ready": failing.is_shutdown_ready,
                            "busy": failing.is_busy,
                            "status": failing._status.get(),
                            "conversion_calls": failing_service.conversion_calls,
                        }

                    result = {
                        "idle": idle_snapshot,
                        "active_before": active_before,
                        "active_after": active_after,
                        "failure": failure_snapshot,
                        "retry_before": retry_before,
                        "retry_after": retry_after,
                        "messages": messages,
                    }
                    for page in (idle, active, failing):
                        page.close()
                    root.destroy()
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
            result["idle"],
            {
                "ready": True,
                "cancel_calls": 0,
                "workers": 0,
                "dialog_calls": 0,
                "select_button": "disabled",
                "convert_button": "disabled",
                "has_cancel_button": True,
                "restored_button": "normal",
            },
        )
        self.assertEqual(
            result["active_before"],
            {
                "busy": True,
                "ready": False,
                "cancel_calls": 1,
                "convert_button": "disabled",
                "shutdown_worker_names": ["edudownloader-media-shutdown"],
                "shutdown_off_main": True,
            },
        )
        self.assertFalse(result["active_after"]["busy"])
        self.assertTrue(result["active_after"]["ready"])
        self.assertEqual(
            result["active_after"]["status"], "Conversão de mídia cancelada."
        )
        self.assertEqual(result["active_after"]["conversion_calls"], 1)
        self.assertTrue(result["active_after"]["source_exists"])
        self.assertFalse(result["active_after"]["output_exists"])
        self.assertFalse(result["failure"]["ready"])
        self.assertTrue(result["failure"]["busy"])
        self.assertEqual(result["failure"]["cancel_calls"], 1)
        self.assertEqual(
            result["failure"]["error"],
            "Não foi possível encerrar a conversão com segurança. "
            "O aplicativo permanecerá aberto.",
        )
        self.assertFalse(result["retry_before"]["ready"])
        self.assertEqual(result["retry_before"]["cancel_calls"], 2)
        self.assertIsNone(result["retry_before"]["error"])
        self.assertTrue(result["retry_after"]["ready"])
        self.assertFalse(result["retry_after"]["busy"])
        self.assertEqual(result["retry_after"]["conversion_calls"], 1)
        self.assertEqual(result["messages"], [])


if __name__ == "__main__":
    unittest.main()
