"""Shell + motor real e projeção incremental, sem rede nem janela gráfica."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from app import EduDownloaderApp, DownloadUiState
from constants import CONTENT_TYPE_AUDIO, CONTENT_TYPE_VIDEO
from download_queue import DownloadQueue, QueueItem, QueueState
from downloader import DownloadBusyError, DownloadEventKind, DownloadRequest
from mp3_quality import Mp3Quality
from tests.test_app import DownloadSnapshotDouble, FakeVariable, AfterScheduler
from tests.test_download_queue import FakeService, RESULT
from ui_pages import DownloadsPage, _DownloadRow


REQUEST = DownloadRequest("https://example.org/lesson", CONTENT_TYPE_VIDEO, "720p")


class QueueShellIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeService()
        self.engine = DownloadQueue(self.service)
        self.app = DownloadSnapshotDouble()
        self.app.download_queue = self.engine
        self.app._download_destination_dir = None
        self.app.quality = FakeVariable("720p")
        self.app._show_warning = Mock()
        self.app.downloads_page.forget_queue_item = Mock()

    def tearDown(self):
        self.engine.shutdown(0)
        self.service.start_release.set()
        self.service.finish(DownloadEventKind.CANCELLED, None)
        self.assertTrue(self.engine.shutdown(3), "coordenador não encerrado")

    def wait(self, predicate):
        with self.engine._condition:
            self.assertTrue(self.engine._condition.wait_for(predicate, 3))

    def add(self, url):
        self.app.link_entry.get.return_value = url
        EduDownloaderApp._download(self.app)
        return self.engine.items()[-1].id

    def test_add_while_active_captures_options_and_cancel_waiting_then_continue(self):
        first = self.add("https://example.org/first")
        self.service.wait_started(1)
        self.app.content_type.set(CONTENT_TYPE_AUDIO)
        self.app.mp3_quality.set(Mp3Quality.HIGH.display_label)
        self.app._download_destination_dir = (
            Path(tempfile.gettempdir()) / "synthetic-output"
        )
        second = self.add("https://example.org/second")
        second_request = self.engine.get(second).request
        self.assertIs(second_request.mp3_quality, Mp3Quality.HIGH)
        self.assertEqual(
            second_request.destination_dir, self.app._download_destination_dir
        )
        self.app.mp3_quality.set(Mp3Quality.ECONOMY.display_label)
        self.app._download_destination_dir = None
        third = self.add("https://example.org/third")
        EduDownloaderApp._cancel_queue_item(self.app, second)
        self.assertEqual(self.engine.get(second).state, QueueState.CANCELLED)
        self.service.finish(DownloadEventKind.ERROR, None)
        self.service.wait_started(2)
        self.assertEqual(
            self.service.started[-1].url, self.engine.get(third).request.url
        )
        self.assertEqual(self.engine.get(first).state, QueueState.ERROR)
        self.assertEqual(self.service.max_active, 1)
        self.app._poll_download_events()
        self.assertEqual(
            len(self.app.downloads_page.show_queue_items.call_args.args[0]), 3
        )
        self.assertEqual(second_request.mp3_quality, Mp3Quality.HIGH)

    def test_active_cancel_is_confirmed_by_motor_not_optimistic_ui(self):
        item_id = self.add("https://example.org/active")
        self.service.wait_started(1)
        EduDownloaderApp._cancel_queue_item(self.app, item_id)
        self.service.wait_cancel()
        self.app._poll_download_events()
        self.assertEqual(self.app._download_ui_state, DownloadUiState.PREPARING)
        self.assertTrue(self.engine.get(item_id).cancel_requested)
        self.service.finish(DownloadEventKind.CANCELLED, None)
        self.wait(lambda: self.engine.get(item_id).state == QueueState.CANCELLED)
        self.app._poll_download_events()
        self.assertIsNone(self.app._last_download_result)

    def test_busy_retry_does_not_restart_failed_items(self):
        self.service.failures = [DownloadBusyError("ocupado")]
        item_id = self.add("https://example.org/retry")
        self.wait(lambda: self.engine.blocked)
        self.app._poll_download_events()
        self.assertTrue(
            self.app.downloads_page.show_queue_items.call_args.kwargs["blocked"]
        )
        EduDownloaderApp._retry_download_queue(self.app)
        self.service.wait_started(1)
        self.assertFalse(self.engine.blocked)
        self.assertEqual(
            self.engine.get(item_id).request.url, "https://example.org/retry"
        )

    def test_double_remove_open_and_cancel_of_stale_id_are_idempotent(self):
        item_id = self.add("https://example.org/result")
        self.service.wait_started(1)
        self.service.finish(payload=RESULT)
        self.wait(lambda: self.engine._active is None)
        EduDownloaderApp._remove_queue_item(self.app, item_id)
        EduDownloaderApp._remove_queue_item(self.app, item_id)
        EduDownloaderApp._open_queue_result(self.app, item_id, folder=False)
        EduDownloaderApp._open_queue_result(self.app, item_id, folder=True)
        EduDownloaderApp._cancel_queue_item(self.app, item_id)
        self.assertEqual(self.engine.items(), ())
        self.app.downloads_page.forget_queue_item.assert_called_once_with(item_id)

    def test_terminal_remove_waits_for_service_release(self):
        item_id = self.add("https://example.org/result")
        self.service.wait_started(1)
        self.service.finish(payload=RESULT, release=False)
        self.wait(lambda: self.engine.get(item_id).state == QueueState.COMPLETED)
        EduDownloaderApp._remove_queue_item(self.app, item_id)
        self.app._show_warning.assert_called_once()
        self.assertEqual(len(self.engine.items()), 1)
        self.service.release()

    def test_finalize_refuses_to_detach_live_coordinator(self):
        self.app._close_finalized = False
        EduDownloaderApp._finalize_close(self.app)
        self.assertFalse(self.app._close_finalized)


class QueueViewTests(unittest.TestCase):
    def make_page(self):
        scheduler = AfterScheduler()
        page = SimpleNamespace(
            _queue_rows={},
            _queue_positions={},
            _queue_displayed={},
            _queue_pending={},
            _queue_render_after_id=None,
            _queue_closing=False,
            retry_queue_button=Mock(),
            _show_activity=Mock(),
            after=scheduler.after,
            after_cancel=scheduler.after_cancel,
            after_idle=lambda cb: scheduler.after(0, cb),
            created=0,
            updated=[],
            _queue_actions=SimpleNamespace(cancel_item=Mock(), remove_item=Mock()),
        )
        page._render_queue_batch = lambda: DownloadsPage._render_queue_batch(page)

        def make(item_id):
            page.created += 1
            properties = {"row": page._queue_positions[item_id]}
            frame = Mock()
            frame.grid_info.side_effect = lambda: properties.copy()
            frame.grid_configure.side_effect = lambda **values: properties.update(
                values
            )
            return _DownloadRow(frame, *(Mock() for _ in range(11)))

        page._make_queue_row = make
        page._place_queue_row = lambda frame, position: frame.grid_configure(
            row=position
        )
        page._update_queue_row = lambda row, item: page.updated.append(item)
        return page, scheduler

    def drain(self, scheduler):
        while scheduler.callbacks:
            scheduler.run(next(iter(scheduler.callbacks)))

    def show(self, page, items):
        DownloadsPage.show_queue_items(page, tuple(items), blocked=False, closing=False)

    def test_hundred_rows_are_batched_and_identical_polls_do_no_work(self):
        page, scheduler = self.make_page()
        items = [QueueItem(str(i), REQUEST) for i in range(100)]
        self.show(page, items)
        scheduler.run(next(iter(scheduler.callbacks)))
        self.assertLessEqual(page.created, 4)
        self.assertTrue(scheduler.callbacks)
        self.drain(scheduler)
        rows = dict(page._queue_rows)
        for _ in range(1000):
            self.show(page, items)
        self.assertEqual(page.created, 100)
        self.assertEqual(len(page.updated), 100)
        self.assertFalse(scheduler.callbacks)
        changed = replace(items[50], state=QueueState.PROCESSING)
        items[50] = changed
        self.show(page, items)
        self.drain(scheduler)
        self.assertEqual(len(page.updated), 101)
        self.assertEqual(page._queue_rows, rows)
        self.assertEqual(page._queue_positions[changed.id], 1)
        self.assertEqual(page._queue_positions[items[0].id], 2)
        self.assertEqual(page._queue_positions[items[49].id], 51)

    def test_pending_newer_snapshot_can_return_to_displayed_state(self):
        page, scheduler = self.make_page()
        waiting = QueueItem("a", REQUEST)
        self.show(page, [waiting])
        self.drain(scheduler)
        self.show(page, [replace(waiting, state=QueueState.PREPARING)])
        self.show(page, [waiting])
        self.drain(scheduler)
        self.assertEqual(page._queue_displayed["a"].state, QueueState.WAITING)

    def test_repeated_removal_keeps_grid_positions_bounded_and_ordered(self):
        page, scheduler = self.make_page()
        items = [QueueItem("first", REQUEST)]
        self.show(page, items)
        self.drain(scheduler)
        first_frame = page._queue_rows["first"][0]
        for i in range(1500):
            items.append(QueueItem(str(i), REQUEST))
            self.show(page, items)
            self.drain(scheduler)
            items.pop(0)
            self.show(page, items)
            self.drain(scheduler)
            self.assertEqual(list(page._queue_positions.values()), [1])
            self.assertEqual(page._queue_rows[items[0].id][0].grid_info()["row"], 1)
        first_frame.destroy.assert_called_once()
        self.assertEqual(len(page._queue_rows), 1)
        self.assertEqual(len(page._queue_displayed), 1)
        self.assertFalse(page._queue_pending)

    def test_forget_disables_stale_buttons_before_render_and_cancels_callback(self):
        page, scheduler = self.make_page()
        item = QueueItem("done", REQUEST, state=QueueState.COMPLETED, result=RESULT)
        self.show(page, [item])
        self.drain(scheduler)
        row = page._queue_rows["done"]
        DownloadsPage.forget_queue_item(page, "done")
        for button in (
            row.action,
            row.open_file,
            row.open_folder,
            row.retry,
            row.review,
        ):
            button.configure.assert_called_with(state="disabled")
        DownloadsPage._queue_row_action(page, "done")
        page._queue_actions.remove_item.assert_not_called()
        self.drain(scheduler)
        self.assertFalse(page._queue_rows)
        self.show(page, [QueueItem("other", REQUEST)])
        DownloadsPage.close_queue_view(page)
        self.assertFalse(scheduler.callbacks)
