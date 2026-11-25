"""Composição de fontes em temporário; não executa build ou empacotamento."""

from pathlib import Path
import tempfile
import unittest

from edition_profiles import select_build_profile
from edition_staging import stage_sources


class IntegrationStagingTests(unittest.TestCase):
    def test_runtime_modules_are_staged_for_community(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="edu-source-staging-") as temporary:
            for edition in ("community",):
                target = Path(temporary) / edition
                stage_sources(root, target, select_build_profile(edition))
                for module in ("download_queue.py", "media_time.py", "ui_events.py"):
                    self.assertEqual(
                        (target / module).read_bytes(), (root / module).read_bytes()
                    )
                self.assertFalse((target / "tests").exists())
