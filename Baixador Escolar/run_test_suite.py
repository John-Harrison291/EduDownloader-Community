"""Executa os módulos de teste Community em processos separados."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
TEST_DIR = PROJECT_DIR / "tests"
TEST_SUMMARY_PATTERN = re.compile(r"Ran (\d+) tests?")
SKIP_SUMMARY_PATTERN = re.compile(r"skipped=(\d+)")


def _run(
    arguments: list[str],
    *,
    cwd: Path,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )


def _test_modules() -> list[str]:
    return sorted(path.stem for path in TEST_DIR.glob("test_*.py"))


def _configure_output_encoding() -> None:
    """Keep captured Unicode failures printable on legacy Windows consoles."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    _configure_output_encoding()
    total = 0
    skips = 0
    failures: list[str] = []
    try:
        for module in _test_modules():
            print(f"RUN tests.{module}", flush=True)
            completed = _run(
                [sys.executable, "-m", "unittest", f"tests.{module}", "-q"],
                cwd=PROJECT_DIR,
            )
            output = completed.stdout.decode(errors="replace")
            count_match = TEST_SUMMARY_PATTERN.search(output)
            skip_match = SKIP_SUMMARY_PATTERN.search(output)
            count = int(count_match.group(1)) if count_match else 0
            skipped = int(skip_match.group(1)) if skip_match else 0
            total += count
            skips += skipped
            if completed.returncode:
                failures.append(module)
                print(output, end="")
                print(f"FAIL tests.{module}", flush=True)
            else:
                print(
                    f"PASS tests.{module} tests={count} skips={skipped}",
                    flush=True,
                )
    except (OSError, RuntimeError) as error:
        print(f"Test suite preparation failed: {error}")
        return 1
    print(
        f"FRESH_PROCESS_TOTAL tests={total} skips={skips} "
        f"failed_modules={len(failures)}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
