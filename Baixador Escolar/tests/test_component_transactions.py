"""Recuperação conservadora e exclusão interprocesso do staging managed."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from component_manager import ComponentId, ComponentManager
from component_transactions import (
    cleanup_owned_stage,
    component_lock,
    create_stage,
    recover_staging,
)


class ComponentTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "Componentes"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_live_stage_survives_other_instance_and_orphan_is_cleaned(self) -> None:
        stage = create_stage(self.root, "yt-dlp", "2026.09.01")
        (stage.path / "yt-dlp.exe.part").write_bytes(b"partial")
        unknown = stage.path.parent / "foreign-dir"
        unknown.mkdir()
        (unknown / "user-file").write_bytes(b"preserve")
        now = time.time() + 3
        report = recover_staging(self.root, "yt-dlp", now=now)
        self.assertEqual((report.cleaned, report.active, report.unknown), (0, 1, 1))
        self.assertTrue(stage.path.exists())
        stage.close()  # simula encerramento/crash sem cleanup
        report = recover_staging(self.root, "yt-dlp", now=now)
        self.assertEqual((report.cleaned, report.active, report.unknown), (1, 0, 1))
        self.assertFalse(stage.path.exists())
        self.assertEqual((unknown / "user-file").read_bytes(), b"preserve")
        self.assertEqual(recover_staging(self.root, "yt-dlp", now=now).cleaned, 0)

    def test_component_lock_prevents_second_mutation_and_refresh_cleanup(self) -> None:
        stage = create_stage(self.root, "libreoffice", "26.2.4")
        first = component_lock(self.root, "libreoffice")
        second = component_lock(self.root, "libreoffice")
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        stage.close()
        self.assertEqual(
            recover_staging(self.root, "libreoffice", now=time.time() + 3).active,
            1,
        )
        self.assertTrue(stage.path.exists())
        first.close()
        self.assertEqual(
            recover_staging(self.root, "libreoffice", now=time.time() + 3).cleaned,
            1,
        )

    def test_component_lock_is_cross_process(self) -> None:
        script = (
            "from pathlib import Path; from component_transactions import component_lock; "
            "lock = component_lock(Path(__import__('sys').argv[1]), 'yt-dlp'); "
            "print('ACQUIRED' if lock.acquire() else 'BUSY'); lock.close()"
        )
        with component_lock(self.root, "yt-dlp"):
            child = subprocess.run(
                [sys.executable, "-c", script, str(self.root)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(child.stdout.strip(), "BUSY")
        child = subprocess.run(
            [sys.executable, "-c", script, str(self.root)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), "ACQUIRED")

    def test_corrupt_marker_and_traversal_like_stage_are_preserved(self) -> None:
        stage = create_stage(self.root, "yt-dlp", "2026.09.01")
        stage.close()
        marker = stage.path / "operation.json"
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["owned_paths"] = ["../../Downloads"]
        marker.write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(cleanup_owned_stage(stage.path, self.root, "yt-dlp"))
        self.assertEqual(
            recover_staging(self.root, "yt-dlp", now=time.time() + 3).unknown,
            1,
        )
        self.assertTrue(stage.path.exists())

    def test_new_stage_is_not_cleaned_on_immediate_refresh(self) -> None:
        stage = create_stage(self.root, "yt-dlp", "2026.09.01")
        stage.close()
        self.assertEqual(recover_staging(self.root, "yt-dlp").unknown, 1)
        self.assertTrue(stage.path.exists())

    def test_crash_boundaries_never_promote_partial_stage(self) -> None:
        for component, target, steps in (
            ("yt-dlp", "2026.09.01", ("download", "verified", "prepared")),
            ("libreoffice", "26.2.4", ("download", "verified", "installer", "verify")),
        ):
            for step in steps:
                with self.subTest(component=component, step=step):
                    stage = create_stage(self.root, component, target)
                    stage.set_stage(step)
                    (stage.path / "partial.bin").write_bytes(b"incomplete")
                    stage.close()  # queda lógica antes de qualquer ativação
                    self.assertEqual(
                        recover_staging(
                            self.root, component, now=time.time() + 3
                        ).cleaned,
                        1,
                    )
                    self.assertFalse(stage.path.exists())
        self.assertFalse((self.root / "yt-dlp" / "active.json").exists())
        self.assertFalse((self.root / "active.json").exists())

    def test_refresh_recovers_only_owned_stale_stage(self) -> None:
        stage = create_stage(self.root, "libreoffice", "26.2.4")
        stage.close()
        unknown = stage.path.parent / "operator-folder"
        unknown.mkdir()
        manager = ComponentManager(base_dir=self.root.parent)
        with patch("component_transactions.time.time", return_value=time.time() + 3):
            manager.refresh(ComponentId.LIBREOFFICE)
        self.assertFalse(stage.path.exists())
        self.assertTrue(unknown.exists())
