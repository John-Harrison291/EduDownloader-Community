import json
import unittest
from dataclasses import replace
from unittest.mock import Mock

from component_release_policy import (
    ComponentReleaseObserver,
    approve_yt_dlp,
    reported_version,
)
from yt_dlp_update import OfficialRelease, UpdateError


class ComponentReleasePolicyTests(unittest.TestCase):
    def test_nightly_or_beta_are_not_displayed_as_stable(self):
        for tag, prerelease in (("v2.9.9-rc.1", True), ("v2.9.9-nightly", False)):
            raw = json.dumps(
                {"draft": False, "prerelease": prerelease, "tag_name": tag}
            )
            with self.assertRaises(ValueError):
                reported_version("deno", raw.encode())

    def test_media_is_observed_as_one_stable_pair(self):
        page = (
            b'<a href="/releases/ffmpeg-8.1.3.tar.xz">Stable</a>'
            b'<a href="/releases/ffmpeg-9.1.tar.xz">Stable</a>'
            b'<a href="/releases/ffmpeg-9.3-dev.tar.xz">Preview</a>'
        )
        self.assertEqual(reported_version("ffmpeg-ffprobe", page), "9.1")

    def test_metadata_does_not_authorize_updates_and_is_cached(self):
        transport = Mock()
        transport.read_bytes.return_value = (
            b'{"draft":false,"prerelease":false,"tag_name":"v2.9.8"}'
        )
        observer = ComponentReleaseObserver(transport)
        self.assertEqual(observer.check("deno", "2.9.5").status, "not-approved")
        self.assertEqual(observer.check("deno", "2.9.8").status, "current")
        transport.read_bytes.assert_called_once()
        transport.read_bytes.side_effect = UpdateError("connection_unavailable")
        offline = observer.check("ocr", "5.5.4")
        self.assertEqual(offline.status, "offline")
        self.assertIsNone(offline.available_version)

    def test_reviewed_yt_dlp_release_requires_all_pins(self):
        release = OfficialRelease(
            "2026.11.23",
            "",
            23_627_865,
            "622ed48023cac1daa52a3bf3a6ac38f03514de214b5f0fa069389fd0f6d17e5c",
            "",
            "40cbeef6bd7c0377479fe87e41add10488a511a1001519b7d4ba2ff67fba618c",
            "",
            "",
        )
        self.assertTrue(approve_yt_dlp(release))
        self.assertFalse(approve_yt_dlp(replace(release, version="2026.11.24")))
        self.assertFalse(approve_yt_dlp(replace(release, binary_digest="0" * 64)))
        self.assertFalse(approve_yt_dlp(replace(release, sums_digest="0" * 64)))
