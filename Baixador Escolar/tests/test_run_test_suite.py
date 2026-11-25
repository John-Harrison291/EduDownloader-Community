"""Regressões do runner oficial em processos frescos."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import run_test_suite


class RunTestSuiteTests(unittest.TestCase):
    def test_cp1252_console_preserves_unicode_failure_output(self) -> None:
        environment = dict(os.environ, PYTHONIOENCODING="cp1252")
        probe = """
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import run_test_suite as runner

output = runner._run(
    [sys.executable, '-c', "print('João — Educação 你好')"],
    cwd=runner.PROJECT_DIR,
).stdout
fake = subprocess.CompletedProcess(
    [], 7, b'Ran 1 test in 0.001s\\nFAILED\\n' + output
)
with (
    patch.object(runner, '_test_modules', return_value=['test_unicode']),
    patch.object(runner, '_run', return_value=fake),
):
    raise SystemExit(runner.main())
"""
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                probe,
            ],
            cwd=run_test_suite.PROJECT_DIR,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn("João — Educação 你好", completed.stdout.decode("utf-8"))
        self.assertIn("FAIL tests.test_unicode", completed.stdout.decode("utf-8"))


class RunTestSuiteDiscoveryTests(unittest.TestCase):
    def test_each_discovered_module_runs_in_fresh_process_from_project(self):
        passed = subprocess.CompletedProcess(
            [], 0, b"Ran 3 tests in 0.001s\nOK (skipped=1)\n"
        )
        with (
            patch.object(
                run_test_suite, "_test_modules", return_value=["test_one", "test_two"]
            ),
            patch.object(run_test_suite, "_run", return_value=passed) as worker,
            patch("builtins.print") as printed,
        ):
            self.assertEqual(run_test_suite.main(), 0)
        self.assertEqual(
            [call.args[0][-2] for call in worker.call_args_list],
            ["tests.test_one", "tests.test_two"],
        )
        self.assertTrue(
            all(
                call.kwargs["cwd"] == run_test_suite.PROJECT_DIR
                for call in worker.call_args_list
            )
        )
        printed.assert_any_call("FRESH_PROCESS_TOTAL tests=6 skips=2 failed_modules=0")


if __name__ == "__main__":
    unittest.main()
