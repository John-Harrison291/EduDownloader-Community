"""Término natural limitado do Job, sem confundir saída do pai com da árvore."""

import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from constants import CONTENT_TYPE_VIDEO
from downloader import (
    DownloadEventKind,
    DownloadRequest,
    DownloadService,
    _WindowsDownloadJob,
)


class JobFinishTests(unittest.TestCase):
    def make_job(self, active):
        job = _WindowsDownloadJob.__new__(_WindowsDownloadJob)
        job._handle = 1
        job._lock = threading.Lock()
        job._active_processes = Mock(side_effect=active)
        job.terminate = Mock(return_value=True)
        return job

    def test_no_child_returns_immediately(self):
        job = self.make_job([0])
        with patch("downloader.time.sleep") as sleep:
            self.assertEqual(job.finish(), (True, True))
        sleep.assert_not_called()
        job.terminate.assert_not_called()

    def test_child_shutdown_race_waits_for_zero_without_termination(self):
        job = self.make_job([1, 1, 0])
        with patch("downloader.time.sleep") as sleep:
            self.assertEqual(job.finish(), (True, True))
        self.assertEqual(sleep.call_count, 2)
        job.terminate.assert_not_called()

    def test_timeout_is_not_success_even_when_owned_cleanup_succeeds(self):
        job = self.make_job([1, 1])
        with (
            patch("downloader.time.monotonic", side_effect=[0, 0.1, 0.5]),
            patch("downloader.time.sleep") as sleep,
        ):
            self.assertEqual(job.finish(), (False, True))
        sleep.assert_called_once_with(0.01)
        job.terminate.assert_called_once_with()

    def test_timeout_cleanup_failure_remains_fail_closed(self):
        job = self.make_job([1])
        job.terminate.return_value = False
        with patch("downloader.time.monotonic", side_effect=[0, 0.5]):
            self.assertEqual(job.finish(), (False, False))

    def test_cancel_can_acquire_lock_during_grace(self):
        job = self.make_job([1, 0])

        def cancellation(_):
            self.assertTrue(job._lock.acquire(blocking=False))
            job._lock.release()

        with patch("downloader.time.sleep", side_effect=cancellation):
            self.assertEqual(job.finish(), (True, True))

    def test_closed_job_is_not_success(self):
        job = self.make_job([])
        job._handle = 0
        self.assertEqual(job.finish(), (False, False))


@unittest.skipUnless(os.name == "nt", "Windows Job ownership")
class RealJobLifecycleTests(unittest.TestCase):
    def test_short_owned_child_can_exit_after_parent(self):
        # Parent exit is proven before the child is released. This reproduces
        # the observed conhost lifecycle ordering without scheduler guesswork.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            pid_file = root / "child.pid"
            child_code = (
                "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
                "deadline=time.monotonic()+10\n"
                "while not p.exists() and time.monotonic()<deadline: time.sleep(.01)"
            )
            parent_code = (
                "import subprocess,sys,pathlib; "
                "p=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],"
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL); "
                "pathlib.Path(sys.argv[3]).write_text(str(p.pid))"
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    parent_code,
                    child_code,
                    str(release),
                    str(pid_file),
                ],
                creationflags=subprocess.CREATE_NO_WINDOW | 0x4,
            )
            job = _WindowsDownloadJob.attach(int(process._handle))
            timer = None
            try:
                job.resume(process.pid)
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertGreater(job._active_processes(), 0)
                timer = threading.Timer(0.05, release.touch)
                timer.start()
                self.assertEqual(job.finish(), (True, True))
                self.assertEqual(job._active_processes(), 0)
            finally:
                if timer is not None:
                    timer.join()
                job.terminate()
                job.close()
                process.wait(timeout=5)

    def test_window_close_stops_owned_worker_and_pipe_not_external_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root / "ready"
            logger = logging.getLogger("job-lifecycle-test")
            logger.addHandler(logging.NullHandler())
            service = DownloadService(root, logger=logger)
            code = (
                "import pathlib,sys,time;pathlib.Path(sys.argv[1]).touch();"
                "print('READY',flush=True);time.sleep(20)"
            )
            external = subprocess.Popen(
                [sys.executable, "-c", "import time;time.sleep(30)"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            worker = threading.Thread(
                target=service._worker_main,
                args=(
                    DownloadRequest("synthetic", CONTENT_TYPE_VIDEO, "720p"),
                    [sys.executable, "-c", code, str(ready), "synthetic"],
                ),
            )
            service._worker = worker
            service._running = True
            worker.start()
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                process = service._process
                self.assertIsNotNone(process)
                service.close()
                self.assertFalse(worker.is_alive())
                self.assertIsNotNone(process.poll())
                self.assertTrue(process.stdout.closed)
                self.assertTrue(service._process_tree_stopped.is_set())
                self.assertIsNone(service._job)
                self.assertIsNone(service._termination_thread)
                self.assertIsNone(external.poll())
                events = []
                while not service.events.empty():
                    events.append(service.events.get_nowait().kind)
                self.assertIn(DownloadEventKind.CANCELLED, events)
            finally:
                service.close()
                external.terminate()
                external.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
