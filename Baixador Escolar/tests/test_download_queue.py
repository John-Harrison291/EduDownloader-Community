"""Fila sem Tk/rede: barreiras e condições controlam as corridas relevantes."""

import logging
import sys
import tempfile
import threading
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import Mock, patch

from constants import CONTENT_TYPE_AUDIO, CONTENT_TYPE_VIDEO
from download_queue import DownloadQueue, DownloadQueueError, QueueState
from downloader import (
    DownloadBusyError,
    DownloadCancelledError,
    DownloadEvent,
    DownloadEventBuffer,
    DownloadEventKind,
    DownloadPhase,
    DownloadProgress,
    DownloadRequest,
    DownloadResult,
    DownloadService,
    DownloadServiceError,
    ToolPaths,
)
from mp3_quality import Mp3Quality


REQUEST = DownloadRequest("https://example.org/lesson", CONTENT_TYPE_VIDEO, "720p")
RESULT = DownloadResult(Path(tempfile.gettempdir()) / "synthetic/lesson.mp4", False)
TERMINAL = {QueueState.COMPLETED, QueueState.ERROR, QueueState.CANCELLED}


class FakeService:
    """Mesmo contrato público; publicação terminal e liberação são independentes."""

    def __init__(self):
        self.base_dir = Path(tempfile.gettempdir()) / "synthetic"
        self.events = DownloadEventBuffer()
        self.condition = threading.Condition()
        self.running = False
        self.started = []
        self.failures = []
        self.cancel_calls = 0
        self.closed = False
        self.max_active = 0
        self.start_entered = threading.Event()
        self.start_release = threading.Event()
        self.start_release.set()

    @property
    def is_running(self):
        with self.condition:
            return self.running

    def start(self, request):
        self.start_entered.set()
        if not self.start_release.wait(3):
            raise AssertionError("preparação não liberada")
        with self.condition:
            if self.failures:
                raise self.failures.pop(0)
            if self.running:
                raise AssertionError("downloads concorrentes")
            self.running = True
            self.max_active = max(self.max_active, int(self.running))
            self.started.append(request)
            self.condition.notify_all()

    def publish(self, kind, payload=None):
        self.events.put(DownloadEvent(kind, payload))

    def finish(self, kind=DownloadEventKind.COMPLETED, payload=RESULT, *, release=True):
        self.publish(kind, payload)
        if release:
            self.release()

    def release(self):
        with self.condition:
            self.running = False
            self.condition.notify_all()

    def wait_started(self, count):
        with self.condition:
            if not self.condition.wait_for(lambda: len(self.started) >= count, 3):
                raise AssertionError("download não iniciado")

    def cancel(self):
        with self.condition:
            self.cancel_calls += 1
            self.condition.notify_all()
            return self.running

    def wait_cancel(self):
        with self.condition:
            if not self.condition.wait_for(lambda: self.cancel_calls > 0, 3):
                raise AssertionError("cancelamento não enviado")

    def close(self):
        if self.running:
            raise AssertionError("fechamento antes da liberação")
        self.closed = True


class DownloadQueueTests(unittest.TestCase):
    def test_coordinator_start_failure_restores_service_stream(self):
        service = FakeService()
        original_events = service.events
        with patch.object(
            threading.Thread, "start", side_effect=RuntimeError("sensitive")
        ):
            with self.assertRaises(DownloadQueueError) as context:
                DownloadQueue(service)
        self.assertNotIn("sensitive", str(context.exception))
        self.assertIs(service.events, original_events)
        self.assertEqual(service.started, [])

    def make_queue(self, *, max_items=100, service=None):
        service = service or FakeService()
        engine = DownloadQueue(service, max_items=max_items)

        def cleanup():
            engine.shutdown(0)
            service.start_release.set()
            service.finish(DownloadEventKind.CANCELLED, None)
            self.assertTrue(engine.shutdown(3), "worker órfão")

        self.addCleanup(cleanup)
        return engine, service

    def wait_item(self, engine, item_id, predicate):
        with engine._condition:
            self.assertTrue(
                engine._condition.wait_for(lambda: predicate(engine.get(item_id)), 3),
                "transição não confirmada",
            )
        return engine.get(item_id)

    def wait_state(self, engine, item_id, state):
        return self.wait_item(engine, item_id, lambda item: item.state == state)

    def wait_released(self, engine):
        with engine._condition:
            self.assertTrue(
                engine._condition.wait_for(lambda: engine._active is None, 3)
            )

    def test_fifo_settings_ids_and_single_active_download(self):
        engine, service = self.make_queue()
        requests = [
            REQUEST,
            DownloadRequest(
                "https://example.org/audio?token=synthetic",
                CONTENT_TYPE_AUDIO,
                "ignorada",
                Path(tempfile.gettempdir()) / "synthetic/pasta com espaços",
                Mp3Quality.HIGH,
            ),
            replace(REQUEST, url="https://example.org/third", quality="1080p"),
        ]
        ids = [engine.add(request) for request in requests]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual([item.id for item in engine.items()], ids)
        for index, item_id in enumerate(ids):
            service.wait_started(index + 1)
            self.assertEqual(service.started, requests[: index + 1])
            self.assertEqual(engine.get(item_id).request, requests[index])
            self.assertEqual(len(service.started), index + 1)
            service.finish()
            self.wait_state(engine, item_id, QueueState.COMPLETED)
        self.assertEqual(service.max_active, 1)
        self.wait_released(engine)

    def test_error_then_next_and_start_failure_then_next(self):
        for start_failure in (False, True):
            with self.subTest(start_failure=start_failure):
                engine, service = self.make_queue()
                if start_failure:
                    service.failures.append(
                        DownloadServiceError("Falha de preparação.")
                    )
                first, second = engine.add(REQUEST), engine.add(REQUEST)
                if not start_failure:
                    service.wait_started(1)
                    service.finish(
                        DownloadEventKind.ERROR,
                        DownloadServiceError("Conteúdo indisponível."),
                    )
                item = self.wait_state(engine, first, QueueState.ERROR)
                self.assertIsInstance(item.error, str)
                service.wait_started(1 if start_failure else 2)
                service.finish()
                self.wait_state(engine, second, QueueState.COMPLETED)

    def test_retry_waits_for_release_and_goes_to_end_of_existing_fifo(self):
        engine, service = self.make_queue(max_items=3)
        first = engine.add(REQUEST)
        other_request = replace(REQUEST, url="https://example.org/next")
        second, third = [engine.add(other_request) for _ in range(2)]
        service.wait_started(1)
        service.finish(
            DownloadEventKind.ERROR,
            DownloadServiceError("Erro sintético."),
            release=False,
        )
        self.wait_state(engine, first, QueueState.ERROR)
        with self.assertRaises(DownloadQueueError):
            engine.retry_item(first)
        service.release()
        service.wait_started(2)
        engine.retry_item(first)
        self.assertEqual([item.id for item in engine.items()], [second, third, first])
        retried = engine.get(first)
        self.assertIs(retried.request, REQUEST)
        self.assertEqual(retried.state, QueueState.WAITING)
        self.assertIsNone(retried.error)
        self.assertIsNone(retried.progress)
        with self.assertRaises(DownloadQueueError):
            engine.retry_item(first)
        for count, item_id in enumerate((second, third, first), 2):
            service.wait_started(count)
            service.finish()
            self.wait_state(engine, item_id, QueueState.COMPLETED)
        self.assertEqual(
            service.started, [REQUEST, other_request, other_request, REQUEST]
        )

    def test_unexpected_start_failure_does_not_expose_exception(self):
        engine, service = self.make_queue()
        service.failures.append(RuntimeError("token=synthetic-secret /home/person"))
        item_id = engine.add(REQUEST)
        item = self.wait_state(engine, item_id, QueueState.ERROR)
        self.assertNotIn("synthetic-secret", item.error)
        self.assertNotIn("/home/person", repr(item))

    def test_waiting_cancel_never_starts_and_does_not_cancel_other_items(self):
        engine, service = self.make_queue()
        first, second, third = [engine.add(REQUEST) for _ in range(3)]
        service.wait_started(1)
        self.assertTrue(engine.cancel(second))
        self.assertFalse(engine.cancel(second))
        self.assertEqual(engine.get(second).state, QueueState.CANCELLED)
        self.assertEqual(service.cancel_calls, 0)
        service.finish()
        self.wait_state(engine, first, QueueState.COMPLETED)
        service.wait_started(2)
        service.finish()
        self.wait_state(engine, third, QueueState.COMPLETED)
        self.assertEqual(len(service.started), 2)

    def test_active_cancel_requires_confirmation_and_continues(self):
        engine, service = self.make_queue()
        first, second = engine.add(REQUEST), engine.add(REQUEST)
        service.wait_started(1)
        self.assertTrue(engine.cancel(first))
        service.wait_cancel()
        self.assertTrue(engine.get(first).cancel_requested)
        self.assertNotIn(engine.get(first).state, TERMINAL)
        self.assertFalse(engine.cancel(first))
        self.assertEqual(len(service.started), 1)
        service.finish(DownloadEventKind.CANCELLED, None)
        self.wait_state(engine, first, QueueState.CANCELLED)
        service.wait_started(2)
        self.assertFalse(engine.get(second).cancel_requested)
        service.finish()
        self.wait_state(engine, second, QueueState.COMPLETED)
        self.assertEqual(service.cancel_calls, 1)

    def test_cancel_during_start_is_delivered_after_preparation(self):
        engine, service = self.make_queue()
        service.start_release.clear()
        first, second = engine.add(REQUEST), engine.add(REQUEST)
        self.assertTrue(service.start_entered.wait(3))
        self.assertTrue(engine.cancel(first))
        self.assertEqual(service.cancel_calls, 0)
        service.start_release.set()
        service.wait_cancel()
        self.assertNotIn(engine.get(first).state, TERMINAL)
        service.finish(DownloadEventKind.CANCELLED, None)
        self.wait_state(engine, first, QueueState.CANCELLED)
        service.wait_started(2)
        self.assertFalse(engine.get(second).cancel_requested)

    def test_terminal_before_release_does_not_start_next_or_misroute_cancel(self):
        engine, service = self.make_queue()
        first, second, third = [engine.add(REQUEST) for _ in range(3)]
        service.wait_started(1)
        service.finish(release=False)
        self.wait_state(engine, first, QueueState.COMPLETED)
        self.assertEqual(len(service.started), 1)
        self.assertFalse(engine.cancel(first))
        self.assertTrue(engine.cancel(second))
        self.assertEqual(service.cancel_calls, 0)
        service.release()
        service.wait_started(2)
        self.assertEqual(engine.get(second).state, QueueState.CANCELLED)
        self.assertEqual(engine.get(third).state, QueueState.PREPARING)

    def test_success_wins_cancellation_boundary(self):
        engine, service = self.make_queue()
        item_id = engine.add(REQUEST)
        service.wait_started(1)
        engine.cancel(item_id)
        service.wait_cancel()
        service.finish()
        item = self.wait_state(engine, item_id, QueueState.COMPLETED)
        self.assertEqual(item.result, RESULT)

    def test_phase_progress_and_result_stay_with_correct_id(self):
        engine, service = self.make_queue()
        first, second = engine.add(REQUEST), engine.add(REQUEST)
        service.wait_started(1)
        progress = DownloadProgress(42, 42, 100, 10, None)
        service.publish(DownloadEventKind.PROGRESS, progress)
        self.wait_item(engine, first, lambda item: item.progress == progress)
        service.publish(DownloadEventKind.PHASE, DownloadPhase.PROCESSING)
        self.wait_state(engine, first, QueueState.PROCESSING)
        service.finish(release=False)
        self.wait_state(engine, first, QueueState.COMPLETED)
        # Mesmo uma amostra tardia não atravessa a liberação para o próximo ID.
        service.publish(DownloadEventKind.PROGRESS, DownloadProgress(99, 99, 100, 2, 0))
        service.release()
        service.wait_started(2)
        self.assertIsNone(engine.get(second).progress)
        self.assertEqual(engine.get(first).progress, progress)
        service.publish(DownloadEventKind.PHASE, DownloadPhase.DOWNLOADING)
        self.wait_state(engine, second, QueueState.DOWNLOADING)
        service.finish(payload=replace(RESULT, already_existed=True))
        item = self.wait_state(engine, second, QueueState.COMPLETED)
        self.assertTrue(item.result.already_existed)

    def test_idle_without_terminal_is_explicit_error(self):
        engine, service = self.make_queue()
        first, second = engine.add(REQUEST), engine.add(REQUEST)
        service.wait_started(1)
        service.release()
        self.wait_state(engine, first, QueueState.ERROR)
        service.wait_started(2)
        service.finish(payload="resultado inválido")
        self.wait_state(engine, second, QueueState.ERROR)

    def test_busy_preserves_fifo_and_requires_explicit_retry(self):
        engine, service = self.make_queue()
        service.failures.extend(
            [DownloadBusyError("update"), DownloadBusyError("update")]
        )
        first, second = engine.add(REQUEST), engine.add(REQUEST)
        with engine._condition:
            self.assertTrue(engine._condition.wait_for(lambda: engine.blocked, 3))
        self.assertEqual(engine.get(first).state, QueueState.WAITING)
        self.assertEqual(service.started, [])
        self.assertEqual(len(service.failures), 1)
        self.assertTrue(engine.retry())
        with engine._condition:
            self.assertTrue(engine._condition.wait_for(lambda: engine.blocked, 3))
        self.assertEqual(len(service.failures), 0)
        self.assertEqual(service.started, [])
        engine.retry()
        service.wait_started(1)
        service.finish()
        self.wait_state(engine, first, QueueState.COMPLETED)
        service.wait_started(2)
        service.finish()
        self.wait_state(engine, second, QueueState.COMPLETED)

    def test_shutdown_active_and_waiting_is_bounded_and_idempotent(self):
        engine, service = self.make_queue()
        first, second = engine.add(REQUEST), engine.add(REQUEST)
        service.wait_started(1)
        self.assertFalse(engine.shutdown(0))
        self.assertFalse(engine.is_closed)
        service.wait_cancel()
        self.assertNotIn(engine.get(first).state, TERMINAL)
        self.assertEqual(engine.get(second).state, QueueState.CANCELLED)
        with self.assertRaises(DownloadQueueError):
            engine.add(REQUEST)
        self.assertFalse(engine.retry())
        service.finish(DownloadEventKind.CANCELLED, None)
        self.assertTrue(engine.shutdown(3))
        self.assertTrue(engine.shutdown(0))
        self.assertTrue(service.closed)
        self.assertEqual(len(service.started), 1)
        self.assertEqual(engine.get(first).state, QueueState.CANCELLED)
        self.assertFalse(engine._worker.is_alive())

    def test_shutdown_during_preparation_does_not_block_caller(self):
        engine, service = self.make_queue()
        service.start_release.clear()
        first, second = engine.add(REQUEST), engine.add(REQUEST)
        self.assertTrue(service.start_entered.wait(3))
        self.assertFalse(engine.shutdown(0))
        self.assertEqual(engine.get(second).state, QueueState.CANCELLED)
        service.start_release.set()
        service.wait_cancel()
        service.finish(DownloadEventKind.CANCELLED, None)
        self.assertTrue(engine.shutdown(3))
        self.assertEqual(engine.get(first).state, QueueState.CANCELLED)
        self.assertEqual(len(service.started), 1)

    def test_shutdown_between_terminal_and_release_preserves_result(self):
        engine, service = self.make_queue()
        first, second = engine.add(REQUEST), engine.add(REQUEST)
        service.wait_started(1)
        service.finish(release=False)
        self.wait_state(engine, first, QueueState.COMPLETED)
        self.assertFalse(engine.shutdown(0))
        service.release()
        self.assertTrue(engine.shutdown(3))
        self.assertEqual(engine.get(first).result, RESULT)
        self.assertEqual(engine.get(second).state, QueueState.CANCELLED)
        self.assertEqual(len(service.started), 1)

    def test_empty_and_busy_shutdown_never_starts_waiting(self):
        engine, service = self.make_queue()
        self.assertTrue(engine.shutdown(3))
        self.assertEqual(service.started, [])
        engine, service = self.make_queue()
        service.failures.append(DownloadBusyError("update"))
        item_id = engine.add(REQUEST)
        with engine._condition:
            self.assertTrue(engine._condition.wait_for(lambda: engine.blocked, 3))
        self.assertTrue(engine.shutdown(3))
        self.assertEqual(engine.get(item_id).state, QueueState.CANCELLED)
        self.assertEqual(service.started, [])

    def test_limit_counts_retained_terminals_and_remove_frees_capacity(self):
        engine, service = self.make_queue(max_items=2)
        first, second = engine.add(REQUEST), engine.add(REQUEST)
        service.wait_started(1)
        with self.assertRaises(DownloadQueueError):
            engine.add(REQUEST)
        with self.assertRaises(DownloadQueueError):
            engine.remove(first)
        engine.cancel(second)
        with self.assertRaises(DownloadQueueError):
            engine.add(REQUEST)
        engine.remove(second)
        third = engine.add(REQUEST)
        self.assertNotEqual(third, second)
        self.assertEqual(len(engine.items()), 2)
        service.finish()
        self.wait_state(engine, first, QueueState.COMPLETED)
        service.wait_started(2)
        engine.remove(first)
        self.assertEqual([item.id for item in engine.items()], [third])

    def test_snapshot_immutable_and_repr_hides_request_result_and_details(self):
        engine, service = self.make_queue()
        item_id = engine.add(
            replace(REQUEST, url=REQUEST.url + "?token=synthetic-secret")
        )
        service.wait_started(1)
        before = engine.get(item_id)
        with self.assertRaises(FrozenInstanceError):
            before.state = QueueState.ERROR
        service.finish()
        after = self.wait_state(engine, item_id, QueueState.COMPLETED)
        self.assertEqual(before.state, QueueState.PREPARING)
        self.assertNotIn("synthetic-secret", repr(after))
        self.assertNotIn("/synthetic", repr(after))

    def test_invalid_requests_limits_timeouts_and_nonempty_service(self):
        engine, service = self.make_queue()
        for request in (
            None,
            "bad",
            replace(REQUEST, url=""),
            replace(REQUEST, url=42),
            replace(REQUEST, url="--exec"),
            replace(REQUEST, quality="8k"),
            replace(REQUEST, content_type=[]),
            replace(REQUEST, destination_dir=Path("relative")),
            replace(REQUEST, mp3_quality="high"),
            replace(REQUEST, url="http://[invalid"),
        ):
            with self.subTest(request_type=type(request).__name__):
                with self.assertRaises(DownloadQueueError):
                    engine.add(request)
        for limit in (0, -1, 101, True, 1.5):
            with self.assertRaises(DownloadQueueError):
                DownloadQueue(FakeService(), max_items=limit)
        for timeout in (-1, float("inf"), float("nan")):
            with self.assertRaises(DownloadQueueError):
                engine.shutdown(timeout)
        self.assertEqual(engine.items(), ())
        service.publish(DownloadEventKind.CANCELLED)
        with self.assertRaises(DownloadQueueError):
            DownloadQueue(service)
        other = FakeService()
        other.running = True
        with self.assertRaises(DownloadQueueError):
            DownloadQueue(other)

    def test_progress_storm_keeps_one_snapshot_and_all_terminal_results(self):
        engine, service = self.make_queue()
        ids = [engine.add(REQUEST) for _ in range(3)]
        for index, kind in enumerate(
            (
                DownloadEventKind.COMPLETED,
                DownloadEventKind.ERROR,
                DownloadEventKind.CANCELLED,
            )
        ):
            service.wait_started(index + 1)
            for count in range(20_000):
                service.publish(
                    DownloadEventKind.PROGRESS,
                    DownloadProgress(count % 100, count, None, None, None),
                )
            self.assertLessEqual(service.events.qsize(), 1)
            payload = RESULT if index == 0 else DownloadServiceError("Falha segura.")
            service.finish(kind, payload)
            self.wait_item(engine, ids[index], lambda item: item.state in TERMINAL)
        self.assertEqual(
            [item.state for item in engine.items()],
            [QueueState.COMPLETED, QueueState.ERROR, QueueState.CANCELLED],
        )
        self.assertEqual(len(engine.items()), 3)
        self.wait_released(engine)
        self.assertTrue(service.events.empty())

    def test_phase_and_progress_storm_has_bounded_service_stream(self):
        engine, service = self.make_queue()
        item_id = engine.add(REQUEST)
        service.wait_started(1)
        for count in range(20_000):
            service.publish(DownloadEventKind.PHASE, DownloadPhase.PROCESSING)
            service.publish(
                DownloadEventKind.PROGRESS,
                DownloadProgress(count % 100, count, None, None, None),
            )
        self.assertLessEqual(service.events.qsize(), 2)
        service.finish(DownloadEventKind.ERROR, DownloadServiceError("Falha segura."))
        self.assertLessEqual(service.events.qsize(), 3)
        self.wait_state(engine, item_id, QueueState.ERROR)
        self.wait_released(engine)
        self.assertTrue(service.events.empty())

    def test_cancel_failure_keeps_worker_responsible_and_can_retry_shutdown(self):
        engine, service = self.make_queue()
        item_id = engine.add(REQUEST)
        service.wait_started(1)
        with (
            patch.object(service, "cancel", side_effect=RuntimeError("sensitive")),
            patch.object(
                service, "shutdown", side_effect=RuntimeError("sensitive"), create=True
            ) as fallback,
        ):
            self.assertTrue(engine.cancel(item_id))
            with engine._condition:
                self.assertTrue(
                    engine._condition.wait_for(
                        lambda: engine.control_error is not None, 3
                    )
                )
            self.assertFalse(engine.is_closed)
            self.assertTrue(engine._worker.is_alive())
            self.assertNotIn(engine.get(item_id).state, TERMINAL)
            self.assertNotIn("sensitive", engine.control_error)
            self.assertFalse(engine.shutdown(0))
        # Uma chamada posterior de shutdown permite tentar novamente.
        self.assertFalse(engine.shutdown(0))
        service.wait_cancel()
        self.assertGreaterEqual(fallback.call_count, 1)
        service.finish(DownloadEventKind.CANCELLED, None)
        self.assertTrue(engine.shutdown(3))
        self.assertEqual(engine.get(item_id).state, QueueState.CANCELLED)

    def test_close_failure_is_observable_and_shutdown_can_retry(self):
        engine, service = self.make_queue()
        with patch.object(service, "close", side_effect=RuntimeError("sensitive")):
            self.assertFalse(engine.shutdown(0))
            with engine._condition:
                self.assertTrue(
                    engine._condition.wait_for(
                        lambda: engine.control_error is not None, 3
                    )
                )
            self.assertFalse(engine.is_closed)
            self.assertTrue(engine._worker.is_alive())
            self.assertNotIn("sensitive", engine.control_error)
        self.assertTrue(engine.shutdown(3))
        self.assertTrue(service.closed)

    def test_error_redacts_sensitive_request_artifacts(self):
        engine, service = self.make_queue()
        destination = service.base_dir / "personal-destination"
        request = replace(
            REQUEST,
            url=REQUEST.url + "?token=synthetic-secret",
            destination_dir=destination,
        )
        item_id = engine.add(request)
        service.wait_started(1)
        service.finish(
            DownloadEventKind.ERROR,
            DownloadServiceError(
                f"Falha {request.url} {destination}", "private details"
            ),
        )
        item = self.wait_state(engine, item_id, QueueState.ERROR)
        self.assertNotIn("synthetic-secret", item.error)
        self.assertNotIn(str(destination), item.error)
        self.assertNotIn("private details", repr(item))


class RealServiceQueueTests(unittest.TestCase):
    def test_shutdown_stops_synthetic_process_pipe_and_workers(self):
        # Processo Python próprio, sem rede; a fase publicada no pipe é a
        # barreira de prontidão. O wait simula trabalho, não sincroniza o teste.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            logger = logging.getLogger("queue-synthetic-process-tests")
            logger.addHandler(logging.NullHandler())
            service = DownloadService(base, logger)
            tools = ToolPaths(
                *(base / name for name in ("yt-dlp", "ffmpeg", "ffprobe", "deno"))
            )
            code = "import threading; print('[download] synthetic ready', flush=True); threading.Event().wait(30)"
            with (
                patch("downloader.validate_external_tools", return_value=tools),
                patch(
                    "downloader.build_download_command",
                    return_value=[
                        sys.executable,
                        "-u",
                        "-c",
                        code,
                        "--paths",
                        str(base),
                        "--format",
                        "b",
                        "synthetic",
                    ],
                ),
            ):
                engine = DownloadQueue(service)
                process = None
                try:
                    item_id = engine.add(REQUEST)
                    with engine._condition:
                        self.assertTrue(
                            engine._condition.wait_for(
                                lambda: (
                                    engine.get(item_id).state == QueueState.DOWNLOADING
                                ),
                                5,
                            )
                        )
                    process = service._process
                    worker = service._worker
                    self.assertIsNotNone(process)
                    self.assertIsNone(process.poll())
                    self.assertTrue(engine.shutdown(5))
                    self.assertIsNotNone(process.poll())
                    self.assertTrue(process.stdout.closed)
                    self.assertFalse(worker.is_alive())
                    self.assertFalse(engine._worker.is_alive())
                    self.assertIsNone(service._termination_thread)
                    self.assertEqual(engine.get(item_id).state, QueueState.CANCELLED)
                finally:
                    engine.shutdown(5)
                    if process is not None and process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)

    def test_canceller_must_exit_before_next_job_can_start(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            logger = logging.getLogger("queue-canceller-tests")
            logger.addHandler(logging.NullHandler())
            service = DownloadService(base, logger)
            tools = ToolPaths(
                *(base / name for name in ("yt-dlp", "ffmpeg", "ffprobe", "deno"))
            )
            entered = threading.Event()
            finish_first = threading.Event()
            cancel_entered = threading.Event()
            release_cancel = threading.Event()
            entered_second = threading.Event()
            jobs = [Mock(), Mock()]
            jobs[0].terminate.return_value = True
            jobs[1].terminate.return_value = True
            workers = []
            cancellers = []
            original_terminate = service._terminate_process_tree_and_signal

            def terminate(process):
                cancellers.append(threading.current_thread())
                cancel_entered.set()
                if not release_cancel.wait(3):
                    raise AssertionError("canceller não liberado")
                original_terminate(process)

            def execute(*_):
                index = len(workers)
                workers.append(threading.current_thread())
                with service._lock:
                    service._process = Mock()
                    service._job = jobs[index]
                if index == 0:
                    entered.set()
                    if not finish_first.wait(3):
                        raise AssertionError("conclusão não liberada")
                    return RESULT
                entered_second.set()
                if not service._cancel_event.wait(3):
                    raise AssertionError("segundo download não cancelado")
                raise DownloadCancelledError("Cancelado.")

            with (
                patch("downloader.validate_external_tools", return_value=tools),
                patch.object(service, "_secure_execute", side_effect=execute),
                patch.object(
                    service, "_terminate_process_tree_and_signal", side_effect=terminate
                ),
            ):
                engine = DownloadQueue(service)
                try:
                    first, second = engine.add(REQUEST), engine.add(REQUEST)
                    self.assertTrue(entered.wait(3))
                    engine.cancel(first)
                    self.assertTrue(cancel_entered.wait(3))
                    finish_first.set()
                    with engine._condition:
                        self.assertTrue(
                            engine._condition.wait_for(
                                lambda: engine.get(first).state == QueueState.COMPLETED,
                                3,
                            )
                        )
                    self.assertTrue(service.is_running)
                    self.assertFalse(entered_second.is_set())
                    self.assertFalse(service.begin_yt_dlp_update())
                    release_cancel.set()
                    self.assertTrue(entered_second.wait(3))
                    jobs[0].terminate.assert_called_once_with()
                    jobs[1].terminate.assert_not_called()
                    self.assertTrue(engine.shutdown(3))
                    self.assertEqual(engine.get(first).state, QueueState.COMPLETED)
                    self.assertEqual(engine.get(second).state, QueueState.CANCELLED)
                    self.assertTrue(
                        all(not worker.is_alive() for worker in workers + cancellers)
                    )
                finally:
                    finish_first.set()
                    release_cancel.set()
                    engine.shutdown(3)

    def test_canceller_thread_start_failure_uses_service_shutdown_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            logger = logging.getLogger("queue-thread-failure-tests")
            logger.addHandler(logging.NullHandler())
            service = DownloadService(base, logger)
            tools = ToolPaths(
                *(base / name for name in ("yt-dlp", "ffmpeg", "ffprobe", "deno"))
            )
            entered = threading.Event()
            tree_stopped = threading.Event()
            job = Mock()
            job.terminate.side_effect = lambda: tree_stopped.set() or True
            workers = []
            original_start = threading.Thread.start

            def start(worker):
                if worker.name == "download-canceller":
                    raise RuntimeError("synthetic secret")
                return original_start(worker)

            def execute(*_):
                workers.append(threading.current_thread())
                with service._lock:
                    service._process = Mock()
                    service._job = job
                entered.set()
                if not tree_stopped.wait(3):
                    raise AssertionError("árvore não encerrada")
                raise DownloadCancelledError("Cancelado.")

            with (
                patch("downloader.validate_external_tools", return_value=tools),
                patch.object(service, "_secure_execute", side_effect=execute),
                patch.object(threading.Thread, "start", start),
            ):
                engine = DownloadQueue(service)
                try:
                    item_id = engine.add(REQUEST)
                    self.assertTrue(entered.wait(3))
                    engine.cancel(item_id)
                    with engine._condition:
                        self.assertTrue(
                            engine._condition.wait_for(
                                lambda: (
                                    engine.get(item_id).state == QueueState.CANCELLED
                                ),
                                3,
                            )
                        )
                    self.assertIsNotNone(engine.control_error)
                    self.assertNotIn("synthetic secret", engine.control_error)
                    self.assertTrue(engine.shutdown(3))
                    self.assertFalse(service.is_running)
                    self.assertTrue(service._process_tree_stopped.is_set())
                    self.assertIsNone(service._termination_thread)
                    self.assertTrue(all(not worker.is_alive() for worker in workers))
                finally:
                    tree_stopped.set()
                    engine.shutdown(3)

    def test_real_service_update_reservation_and_worker_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            logger = logging.getLogger("queue-tests")
            logger.addHandler(logging.NullHandler())
            service = DownloadService(base, logger)
            tools = ToolPaths(
                *(base / name for name in ("yt-dlp", "ffmpeg", "ffprobe", "deno"))
            )
            entered = threading.Event()
            workers = []

            def execute(*_):
                workers.append(threading.current_thread())
                entered.set()
                if not service._cancel_event.wait(3):
                    raise AssertionError("cancelamento não recebido")
                raise DownloadCancelledError("Cancelado.")

            with (
                patch("downloader.validate_external_tools", return_value=tools),
                patch.object(service, "_secure_execute", side_effect=execute),
            ):
                self.assertTrue(service.begin_yt_dlp_update())
                engine = DownloadQueue(service)
                try:
                    first, second = engine.add(REQUEST), engine.add(REQUEST)
                    with engine._condition:
                        self.assertTrue(
                            engine._condition.wait_for(lambda: engine.blocked, 3)
                        )
                    self.assertFalse(service.is_running)
                    self.assertEqual(engine.get(first).state, QueueState.WAITING)
                    service.end_yt_dlp_update()
                    engine.retry()
                    self.assertTrue(entered.wait(3))
                    self.assertTrue(engine.shutdown(3))
                    self.assertEqual(engine.get(first).state, QueueState.CANCELLED)
                    self.assertEqual(engine.get(second).state, QueueState.CANCELLED)
                    self.assertFalse(service.is_running)
                    self.assertFalse(engine._worker.is_alive())
                    self.assertEqual(len(workers), 1)
                    self.assertFalse(workers[0].is_alive())
                    self.assertIsNone(service._termination_thread)
                    self.assertIsNone(service._process)
                finally:
                    service.end_yt_dlp_update()
                    engine.shutdown(3)


if __name__ == "__main__":
    unittest.main()
