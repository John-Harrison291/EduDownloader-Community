"""Fluxo de trecho via worker real e controles fake, sem display ou downloads."""

from pathlib import Path
from queue import Queue
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock

from media_tools import (
    MediaConversionProgress,
    MediaConversionResult,
    MediaOperationCancelled,
    MediaToolsError,
)
from mp3_quality import Mp3Quality
from tests.test_app import FakeVariable
from ui_events import CoalescingQueue
from ui_pages import MediaToolsPage, MediaUiState


class TkValue(FakeVariable):
    def __init__(self, value):
        super().__init__(value)
        self.owner = threading.get_ident()

    def get(self):
        if threading.get_ident() != self.owner:
            raise AssertionError("variável Tk lida pelo worker")
        return super().get()

    def set(self, value):
        if threading.get_ident() != self.owner:
            raise AssertionError("variável Tk atualizada pelo worker")
        super().set(value)


class MediaSegmentUiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="edu-media-ui-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "trecho.mp3"
        self.targets = []

        def factory(*, target, **kwargs):
            self.targets.append(target)
            return SimpleNamespace(start=lambda: None)

        def convert(source, output, **kwargs):
            if kwargs["cancel_event"].is_set():
                raise MediaOperationCancelled("cancelada")
            kwargs["on_progress"](MediaConversionProgress(195, 195))
            Path(output).write_bytes(b"synthetic-published")
            return MediaConversionResult(Path(output), 195)

        self.page = SimpleNamespace(
            _source=self.root / "synthetic.mp4",
            _result_path=None,
            _busy=False,
            _closed=False,
            _shutdown_requested=False,
            _operation_generation=0,
            _cancel_requested=False,
            _cancel_ack_pending=False,
            _pending_worker_result=None,
            _state=MediaUiState.READY,
            _extraction_mode=TkValue("Somente um trecho"),
            _segment_start=TkValue("02:30"),
            _segment_end=TkValue("05:45"),
            _quality=TkValue(Mp3Quality.HIGH.display_label),
            _status=TkValue("Pronto"),
            _actions=Mock(),
            _dialog_preferences=Mock(),
            _thread_factory=factory,
            _results=Queue(),
            _cancel_results=Queue(),
            _progress_results=CoalescingQueue(lambda item: item[0]),
            _service=SimpleNamespace(
                video_to_mp3=Mock(side_effect=convert),
                video_segment_to_mp3=Mock(side_effect=convert),
                request_cancel=Mock(return_value=True),
            ),
            _shutdown_thread_factory=factory,
            winfo_toplevel=Mock(),
            after=Mock(),
            progress_bar=Mock(),
            select_button=Mock(),
            quality_menu=Mock(),
            extraction_mode_menu=Mock(),
            output_folder=Mock(),
            segment_start_entry=Mock(),
            segment_end_entry=Mock(),
            convert_button=Mock(),
            cancel_button=Mock(),
            open_file_button=Mock(),
            open_folder_button=Mock(),
        )
        self.page._dialog_preferences.choose.return_value = str(self.output)
        self.page.progress_bar.cget.return_value = "indeterminate"
        self.page._refresh_controls = lambda: MediaToolsPage._refresh_controls(
            self.page
        )
        self.page._consume_cancel_result = lambda: (
            MediaToolsPage._consume_cancel_result(self.page)
        )
        self.page._consume_progress = lambda: MediaToolsPage._consume_progress(
            self.page
        )
        self.page._poll_worker = lambda: MediaToolsPage._poll_worker(self.page)

    def run_worker(self, index=0):
        errors = []

        def run():
            try:
                self.targets[index]()
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=run)
        worker.start()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)

    def test_segment_captures_seconds_profile_and_only_completes_after_publication(
        self,
    ):
        MediaToolsPage._start_conversion(self.page)
        self.assertEqual(self.page._state, MediaUiState.PREPARING)
        self.assertFalse(self.output.exists())
        self.page._segment_start.set("99:00")
        self.page._segment_end.set("99:59")
        self.run_worker()
        args = self.page._service.video_segment_to_mp3.call_args.kwargs
        self.assertEqual((args["start_seconds"], args["end_seconds"]), (150, 345))
        self.assertIs(args["quality"], Mp3Quality.HIGH)
        self.page._service.video_to_mp3.assert_not_called()
        self.assertTrue(self.output.exists())
        self.assertEqual(self.page._state, MediaUiState.PREPARING)
        self.page._poll_worker()
        self.assertEqual(self.page._state, MediaUiState.COMPLETED)
        self.assertEqual(self.page._result_path, self.output)
        self.page.open_file_button.configure.assert_called_with(state="normal")

    def test_complete_mode_ignores_segment_fields_and_preserves_original_api(self):
        self.page._extraction_mode.set("Áudio completo")
        self.page._segment_start.set("inválido")
        self.page._segment_end.set("")
        MediaToolsPage._start_conversion(self.page)
        self.run_worker()
        self.page._poll_worker()
        self.page._service.video_to_mp3.assert_called_once()
        self.page._service.video_segment_to_mp3.assert_not_called()
        self.assertNotIn(
            "start_seconds", self.page._service.video_to_mp3.call_args.kwargs
        )
        self.assertEqual(self.page._state, MediaUiState.COMPLETED)

    def test_invalid_fields_reject_before_destination_or_worker(self):
        for start, end in (
            ("", "05:45"),
            ("00:00", ""),
            ("-01:00", "05:45"),
            ("00:60", "05:45"),
            ("05:45", "02:30"),
            ("02:30", "02:30"),
        ):
            with self.subTest(start=start, end=end):
                self.page._segment_start.set(start)
                self.page._segment_end.set(end)
                MediaToolsPage._start_conversion(self.page)
                self.assertFalse(self.page._busy)
        self.page._dialog_preferences.choose.assert_not_called()
        self.assertFalse(self.targets)
        self.assertEqual(self.page._actions.show_warning.call_count, 6)

    def test_ffprobe_duration_rejection_stays_error_without_result(self):
        self.page._service.video_segment_to_mp3.side_effect = MediaToolsError(
            "O fim excede a duração do vídeo."
        )
        MediaToolsPage._start_conversion(self.page)
        self.run_worker()
        self.page._poll_worker()
        self.assertEqual(self.page._state, MediaUiState.ERROR)
        self.assertIsNone(self.page._result_path)
        self.assertFalse(self.output.exists())
        self.page._actions.show_error.assert_called_once()
        self.page.open_file_button.configure.assert_called_with(state="disabled")

    def test_cancel_before_worker_never_publishes_and_disables_timing_fields(self):
        MediaToolsPage._start_conversion(self.page)
        self.page.segment_start_entry.configure.assert_called_with(state="disabled")
        self.page.extraction_mode_menu.configure.assert_called_with(state="disabled")
        MediaToolsPage._cancel_conversion(self.page)
        self.assertEqual(self.page._state, MediaUiState.CANCELLING)
        self.run_worker(0)
        self.run_worker(1)
        self.page._poll_worker()
        self.assertEqual(self.page._state, MediaUiState.CANCELLED)
        self.assertFalse(self.output.exists())
        self.page._service.request_cancel.assert_called_once()
        self.page.segment_start_entry.configure.assert_called_with(state="normal")

    def test_overwrite_refusal_preserves_output_and_never_starts_worker(self):
        self.output.write_bytes(b"previous")
        self.page._actions.confirm_overwrite.return_value = False
        MediaToolsPage._start_conversion(self.page)
        self.assertFalse(self.targets)
        self.assertEqual(self.output.read_bytes(), b"previous")
        self.assertFalse(self.page._busy)
