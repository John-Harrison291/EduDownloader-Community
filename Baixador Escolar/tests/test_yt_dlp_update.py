"""Atualização do yt-dlp com authority e transporte sintéticos, sem internet."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
import shutil
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from downloader import locate_tools
from component_transactions import component_lock
from yt_dlp_update import (
    LATEST_RELEASE_URL,
    MAX_BINARY_BYTES,
    OfficialTransport,
    UpdateCancelled,
    UpdateCheckStatus,
    UpdateError,
    UpdateStatus,
    YtDlpUpdateService,
    _SafeRedirects,
    parse_official_release,
    parse_official_sums,
    recover_pending_activation,
    resolve_active_yt_dlp,
)


def release_fixture(version: str = "2026.09.01", payload: bytes = b"new-yt-dlp"):
    digest = hashlib.sha256(payload).hexdigest()
    sums = f"{digest}  yt-dlp.exe\n".encode("ascii")
    sums_digest = hashlib.sha256(sums).hexdigest()
    assets = []
    for name, size, asset_digest in (
        ("yt-dlp.exe", len(payload), digest),
        ("SHA2-256SUMS", len(sums), sums_digest),
        ("yt-dlp.tar.gz", 123, "0" * 64),
    ):
        assets.append(
            {
                "name": name,
                "size": size,
                "digest": f"sha256:{asset_digest}",
                "browser_download_url": (
                    f"https://github.com/yt-dlp/yt-dlp/releases/download/{version}/{name}"
                ),
            }
        )
    data = {
        "tag_name": version,
        "draft": False,
        "prerelease": False,
        "assets": assets,
    }
    return data, sums, payload


class FakeGate:
    def __init__(self) -> None:
        self.download_active = False
        self.update_active = False

    def begin_yt_dlp_update(self) -> bool:
        if self.download_active or self.update_active:
            return False
        self.update_active = True
        return True

    def end_yt_dlp_update(self) -> None:
        self.update_active = False


class FakeTransport:
    def __init__(self, version="2026.09.01", payload=b"new-yt-dlp") -> None:
        self.data, self.sums, self.payload = release_fixture(version, payload)
        self.calls: list[str] = []
        self.fail: str | None = None
        self.cancel_during_download = False

    @property
    def release(self):
        return parse_official_release(json.dumps(self.data).encode("utf-8"))

    def read_bytes(self, url, *, limit, allowed_hosts):
        self.calls.append(url)
        if self.fail == "network":
            raise UpdateError("network_failure")
        if url == LATEST_RELEASE_URL:
            return json.dumps(self.data).encode("utf-8")
        if self.fail == "sums":
            return b"0" * 64 + b"  yt-dlp.exe\n"
        return self.sums

    def download(self, url, destination, *, expected_size, cancel, progress=None):
        self.calls.append(url)
        if self.cancel_during_download:
            destination.write_bytes(self.payload[:2])
            cancel.set()
            raise UpdateCancelled
        destination.write_bytes(self.payload)
        if progress:
            progress(len(self.payload), len(self.payload))
        return hashlib.sha256(self.payload).hexdigest()


def fake_version(path: Path) -> str:
    return (
        "2026.09.01"
        if path.parent.name == "2026.09.01"
        or path.parent.parent.name == "yt-dlp"
        and path.parent.parent.parent.name == ".staging"
        else "2026.08.19"
    )


class ReleaseAuthorityTests(unittest.TestCase):
    def test_exact_official_release_assets_and_sums(self) -> None:
        data, sums, payload = release_fixture()
        release = parse_official_release(json.dumps(data).encode())
        self.assertEqual(release.version, "2026.09.01")
        self.assertEqual(release.binary_size, len(payload))
        self.assertEqual(parse_official_sums(sums), release.binary_digest)
        self.assertIn("yt-dlp.tar.gz", release.source_url)

    def test_prerelease_draft_malformed_and_wrong_authority_rejected(self) -> None:
        data, _, _ = release_fixture()
        for mutation in (
            {"prerelease": True},
            {"draft": True},
            {"tag_name": "nightly"},
            {"assets": []},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(UpdateError):
                parse_official_release(json.dumps(data | mutation).encode())
        data["assets"][0]["browser_download_url"] = "https://example.org/yt-dlp.exe"
        with self.assertRaises(UpdateError):
            parse_official_release(json.dumps(data).encode())

    def test_missing_malformed_duplicate_and_conflicting_checksum(self) -> None:
        digest = b"a" * 64
        valid = digest + b"  yt-dlp.exe\n"
        for sums in (
            b"",
            b"bad\n",
            digest + b"  another.exe\n",
            valid + valid,
            valid + b"b" * 64 + b"  yt-dlp.exe\n",
        ):
            with self.subTest(sums=sums), self.assertRaises(UpdateError):
                parse_official_sums(sums)

    def test_redirect_guard_accepts_official_cdn_only(self) -> None:
        handler = _SafeRedirects(
            frozenset({"github.com", "release-assets.githubusercontent.com"})
        )
        with patch(
            "urllib.request.HTTPRedirectHandler.redirect_request", return_value="safe"
        ):
            self.assertEqual(
                handler.redirect_request(
                    None,
                    None,
                    302,
                    "Found",
                    {},
                    "https://release-assets.githubusercontent.com/object?token=redacted",
                ),
                "safe",
            )
        for url in (
            "http://github.com/asset",
            "file:///tmp/asset",
            "https://github.com.evil.test/asset",
            "https://127.0.0.1/asset",
        ):
            with self.subTest(url=url), self.assertRaises(UpdateError):
                handler.redirect_request(None, None, 302, "Found", {}, url)

    def test_transport_rejects_oversized_and_truncated_response(self) -> None:
        class Response:
            status = 200

            def __init__(self, data, length):
                self.data = data
                self.headers = {"Content-Length": length}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, size):
                return self.data[:size]

        transport = OfficialTransport()
        with patch.object(transport, "_open", return_value=Response(b"12345", "5")):
            with self.assertRaises(UpdateError):
                transport.read_bytes(
                    LATEST_RELEASE_URL,
                    limit=4,
                    allowed_hosts=frozenset({"api.github.com"}),
                )
        with patch.object(transport, "_open", return_value=Response(b"123", "5")):
            with self.assertRaises(UpdateError):
                transport.read_bytes(
                    LATEST_RELEASE_URL,
                    limit=8,
                    allowed_hosts=frozenset({"api.github.com"}),
                )

    def test_binary_transport_rejects_truncation_and_excess(self) -> None:
        class BinaryResponse(io.BytesIO):
            def __init__(self, payload: bytes, length: str | None):
                super().__init__(payload)
                self.headers = {} if length is None else {"Content-Length": length}

        transport = OfficialTransport()
        with tempfile.TemporaryDirectory() as directory:
            for payload, expected in ((b"ab", 3), (b"abcd", 3)):
                destination = Path(directory) / f"case-{len(payload)}.part"
                with patch.object(
                    transport, "_open", return_value=BinaryResponse(payload, None)
                ):
                    with self.assertRaises(UpdateError):
                        transport.download(
                            "https://github.com/yt-dlp/yt-dlp/releases/download/2026.09.01/yt-dlp.exe",
                            destination,
                            expected_size=expected,
                            cancel=threading.Event(),
                        )

    def test_http_failure_and_timeout_fail_closed(self) -> None:
        transport = OfficialTransport()
        for failure in (
            TimeoutError("synthetic timeout"),
            urllib.error.HTTPError(LATEST_RELEASE_URL, 503, "unavailable", {}, None),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                patch(
                    "urllib.request.build_opener",
                    return_value=Mock(open=Mock(side_effect=failure)),
                ),
                self.assertRaises(UpdateError),
            ):
                transport.read_bytes(
                    LATEST_RELEASE_URL,
                    limit=1024,
                    allowed_hosts=frozenset({"api.github.com"}),
                )


class YtDlpTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        (self.base / "yt-dlp.exe").write_bytes(b"bundled-unchanged")
        for name in ("deno.exe", "ffmpeg.exe", "ffprobe.exe"):
            (self.base / name).write_bytes(b"synthetic")
        self.baseline_hash = hashlib.sha256(
            (self.base / "yt-dlp.exe").read_bytes()
        ).hexdigest()
        self.gate = FakeGate()
        self.transport = FakeTransport()
        self.service = YtDlpUpdateService(
            self.base, usage_gate=self.gate, transport=self.transport
        )

    def _update(self, transport=None, cancel=None):
        with patch("yt_dlp_update._probe_version", side_effect=fake_version):
            return self.service.update(
                (transport or self.transport).release,
                cancel=cancel or threading.Event(),
            )

    def _assert_baseline(self) -> None:
        self.assertEqual(
            hashlib.sha256((self.base / "yt-dlp.exe").read_bytes()).hexdigest(),
            self.baseline_hash,
        )

    def test_repair_invalid_pointer_preserves_bundled_and_allows_update(self) -> None:
        self.assertIs(self._update().status, UpdateStatus.UPDATED)
        pointer = self.base / "Componentes" / "yt-dlp" / "active.json"
        pointer.write_text("{broken", encoding="utf-8")
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        self.assertIs(self.service.repair_invalid().status, UpdateStatus.REPAIRED)
        self.assertFalse(pointer.exists())
        self.assertEqual(locate_tools(self.base).yt_dlp, self.base / "yt-dlp.exe")
        self.assertIs(self.service.repair_invalid().status, UpdateStatus.FAILED)
        self.assertIs(self._update().status, UpdateStatus.UPDATED)
        self.assertTrue(resolve_active_yt_dlp(self.base).managed)
        self._assert_baseline()

    def test_crash_after_active_write_recovers_previous_pointer(self) -> None:
        self.assertIs(self._update().status, UpdateStatus.UPDATED)
        pointer = self.base / "Componentes" / "yt-dlp" / "active.json"
        previous = pointer.read_bytes()
        next_transport = FakeTransport("2026.09.02", b"third-yt-dlp")
        self.service.transport = next_transport
        with (
            patch(
                "yt_dlp_update._probe_version",
                side_effect=lambda path: (
                    "2026.09.02"
                    if path.parent.name == "2026.09.02"
                    or path.parent.parent.name == "yt-dlp"
                    and path.parent.parent.parent.name == ".staging"
                    else "2026.09.01"
                ),
            ),
            patch("downloader.locate_tools", side_effect=SystemExit),
        ):
            with self.assertRaises(SystemExit):
                self.service.update(next_transport.release, cancel=threading.Event())
        self.assertTrue((pointer.parent / "activation-pending.json").is_file())
        self.assertEqual(locate_tools(self.base).yt_dlp, self.base / "yt-dlp.exe")
        self.assertTrue(recover_pending_activation(self.base))
        self.assertEqual(pointer.read_bytes(), previous)
        self.assertFalse((pointer.parent / "activation-pending.json").exists())
        self.assertTrue(resolve_active_yt_dlp(self.base).managed)
        self.assertFalse(recover_pending_activation(self.base))

    def test_crash_on_first_activation_recovers_bundled(self) -> None:
        with patch("downloader.locate_tools", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self._update()
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        self.assertTrue(recover_pending_activation(self.base))
        self.assertFalse(
            (self.base / "Componentes" / "yt-dlp" / "active.json").exists()
        )
        self._assert_baseline()

    def test_corrupt_pending_journal_fails_closed_until_explicit_repair(self) -> None:
        self.assertIs(self._update().status, UpdateStatus.UPDATED)
        component = self.base / "Componentes" / "yt-dlp"
        journal = component / "activation-pending.json"
        journal.write_text("{broken", encoding="utf-8")
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        self.assertFalse(recover_pending_activation(self.base))
        self.assertIs(self.service.repair_invalid().status, UpdateStatus.REPAIRED)
        self.assertFalse(journal.exists())
        self.assertEqual(locate_tools(self.base).yt_dlp, self.base / "yt-dlp.exe")

    def test_other_instance_lock_blocks_update_and_repair(self) -> None:
        root = self.base / "Componentes"
        with component_lock(root, "yt-dlp"):
            self.assertIs(self._update().status, UpdateStatus.BUSY)
            self.assertEqual(self.transport.calls, [])

    def test_check_same_newer_network_failure_and_no_mutation(self) -> None:
        with patch("yt_dlp_update._probe_version", return_value="2026.08.19"):
            self.assertIs(
                self.service.check().status, UpdateCheckStatus.UPDATE_AVAILABLE
            )
            self.transport.data["tag_name"] = "2026.08.19"
            self.assertIs(self.service.check().status, UpdateCheckStatus.CHECK_FAILED)
            self.transport = FakeTransport("2026.08.19")
            self.service.transport = self.transport
            self.assertIs(self.service.check().status, UpdateCheckStatus.UP_TO_DATE)
            self.transport.fail = "network"
            interrupted = self.service.check()
            self.assertIs(interrupted.status, UpdateCheckStatus.CHECK_FAILED)
            self.assertEqual(interrupted.diagnostic_code, "network_failure")
            self.assertEqual(interrupted.current_version, "2026.08.19")
            self.assertIsNone(interrupted.release)
        self.assertFalse((self.base / "Componentes").exists())
        self._assert_baseline()

    def test_concurrent_checks_share_single_operation_lock(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        original_read = self.transport.read_bytes
        results = []

        def blocking_read(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise TimeoutError("synthetic timeout")
            return original_read(*args, **kwargs)

        with (
            patch("yt_dlp_update._probe_version", return_value="2026.08.19"),
            patch.object(self.transport, "read_bytes", side_effect=blocking_read),
        ):
            thread = threading.Thread(
                target=lambda: results.append(self.service.check())
            )
            thread.start()
            self.assertTrue(entered.wait(2))
            self.assertIs(self.service.check().status, UpdateCheckStatus.CHECK_FAILED)
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertIs(results[0].status, UpdateCheckStatus.UPDATE_AVAILABLE)
        self.assertEqual(self.transport.calls.count(LATEST_RELEASE_URL), 1)

    def test_success_managed_discovery_relative_path_and_no_staging(self) -> None:
        result = self._update()
        self.assertIs(result.status, UpdateStatus.UPDATED)
        active = resolve_active_yt_dlp(self.base)
        self.assertTrue(active.managed)
        self.assertEqual(active.version, "2026.09.01")
        self.assertEqual(locate_tools(self.base).yt_dlp, active.path)
        self.assertEqual(locate_tools(self.base).deno, self.base / "deno.exe")
        self.assertEqual(locate_tools(self.base).ffmpeg, self.base / "ffmpeg.exe")
        self.assertFalse(
            any(
                path.name.startswith(".stage-")
                for path in active.path.parent.parent.iterdir()
            )
        )
        metadata = json.loads(
            (active.path.parent / "metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["relative_path"], "2026.09.01/yt-dlp.exe")
        self.assertEqual(metadata["source_url"], self.transport.release.source_url)
        self._assert_baseline()
        relocated = self.base / "moved folder João"
        relocated.mkdir()
        shutil.copytree(self.base / "Componentes", relocated / "Componentes")
        (relocated / "yt-dlp.exe").write_bytes(b"bundled-unchanged")
        self.assertTrue(resolve_active_yt_dlp(relocated).managed)
        pointer_path = self.base / "Componentes" / "yt-dlp" / "active.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["component"] = "other"
        pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        self.assertEqual(locate_tools(self.base).yt_dlp, self.base / "yt-dlp.exe")

    def test_integrity_failure_cancel_and_version_mismatch_never_activate(self) -> None:
        self.transport.fail = "sums"
        self.assertIs(self._update().status, UpdateStatus.FAILED)
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        self.transport.fail = None
        self.transport.cancel_during_download = True
        self.assertIs(self._update().status, UpdateStatus.CANCELLED)
        self.transport.cancel_during_download = False
        with patch("yt_dlp_update._probe_version", return_value="2026.08.19"):
            result = self.service.update(
                self.transport.release, cancel=threading.Event()
            )
        self.assertIs(result.status, UpdateStatus.FAILED)
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        self.assertFalse(
            any(
                path.name.startswith(".stage-")
                for path in (self.base / "Componentes" / "yt-dlp").iterdir()
            )
        )
        self._assert_baseline()

    def test_wrong_binary_digest_never_executes_or_activates(self) -> None:
        release = self.transport.release
        self.transport.payload = b"tampered-payload"
        with patch("yt_dlp_update._probe_version", side_effect=fake_version) as probe:
            result = self.service.update(release, cancel=threading.Event())
        self.assertIs(result.status, UpdateStatus.FAILED)
        self.assertEqual(probe.call_count, 1)  # versão corrente; payload não executado
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        self._assert_baseline()

    def test_stage_and_activation_failures_leave_bundled_active(self) -> None:
        import yt_dlp_update

        original_replace = yt_dlp_update.os.replace

        def reject_stage(source, target):
            if str(source).endswith(".part"):
                raise OSError("simulated stage failure")
            return original_replace(source, target)

        with (
            patch("yt_dlp_update._probe_version", side_effect=fake_version),
            patch("yt_dlp_update.os.replace", side_effect=reject_stage),
        ):
            result = self.service.update(
                self.transport.release, cancel=threading.Event()
            )
        self.assertIs(result.status, UpdateStatus.FAILED)
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)

        with (
            patch("yt_dlp_update._probe_version", side_effect=fake_version),
            patch(
                "yt_dlp_update._atomic_bytes",
                side_effect=OSError("simulated pointer failure"),
            ),
        ):
            result = self.service.update(
                self.transport.release, cancel=threading.Event()
            )
        self.assertIs(result.status, UpdateStatus.FAILED)
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        component = self.base / "Componentes" / "yt-dlp"
        self.assertFalse((component / "active.json").exists())
        self.assertFalse(
            any(path.name.startswith(".stage-") for path in component.iterdir())
        )
        self._assert_baseline()

    def test_post_activation_failure_rolls_back_to_bundled(self) -> None:
        import downloader

        original_locate = downloader.locate_tools
        with (
            patch("yt_dlp_update._probe_version", side_effect=fake_version),
            patch(
                "downloader.locate_tools",
                side_effect=lambda base: replace(
                    original_locate(base), yt_dlp=self.base / "wrong.exe"
                ),
            ),
        ):
            result = self.service.update(
                self.transport.release, cancel=threading.Event()
            )
        self.assertIs(result.status, UpdateStatus.FAILED)
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        self.assertEqual(locate_tools(self.base).yt_dlp, self.base / "yt-dlp.exe")
        self._assert_baseline()

    def test_failed_managed_pointer_restore_falls_back_to_bundled(self) -> None:
        import downloader
        import yt_dlp_update

        self.assertIs(self._update().status, UpdateStatus.UPDATED)
        next_transport = FakeTransport("2026.09.02", b"third-yt-dlp")
        self.service.transport = next_transport
        original_locate = downloader.locate_tools
        original_atomic = yt_dlp_update._atomic_bytes
        pointer_writes = 0

        def fail_restore(path, payload):
            nonlocal pointer_writes
            if path.name == "active.json":
                pointer_writes += 1
                if pointer_writes == 2:
                    raise OSError("simulated restore failure")
            return original_atomic(path, payload)

        with (
            patch(
                "yt_dlp_update._probe_version",
                side_effect=lambda path: (
                    "2026.09.02"
                    if path.parent.name == "2026.09.02"
                    or path.parent.parent.name == "yt-dlp"
                    and path.parent.parent.parent.name == ".staging"
                    else "2026.09.01"
                ),
            ),
            patch("yt_dlp_update._atomic_bytes", side_effect=fail_restore),
            patch(
                "downloader.locate_tools",
                side_effect=lambda base: replace(
                    original_locate(base), yt_dlp=self.base / "wrong.exe"
                ),
            ),
        ):
            result = self.service.update(
                next_transport.release, cancel=threading.Event()
            )
        self.assertIs(result.status, UpdateStatus.FAILED)
        self.assertEqual(pointer_writes, 2)
        self.assertEqual(locate_tools(self.base).yt_dlp, self.base / "yt-dlp.exe")
        self._assert_baseline()

    def test_download_active_blocks_update_before_network(self) -> None:
        self.gate.download_active = True
        result = self._update()
        self.assertIs(result.status, UpdateStatus.BUSY)
        self.assertEqual(self.transport.calls, [])
        self.assertFalse(self.gate.update_active)

    def test_storage_unavailable_refuses_before_network(self) -> None:
        (self.base / "Componentes").write_text("not a directory", encoding="utf-8")
        result = self._update()
        self.assertIs(result.status, UpdateStatus.STORAGE_UNAVAILABLE)
        self.assertEqual(self.transport.calls, [])

    def test_corrupt_metadata_missing_exe_hash_version_and_stale_stage_fallback(
        self,
    ) -> None:
        component = self.base / "Componentes" / "yt-dlp"
        component.mkdir(parents=True)
        (component / ".stage-abandoned").mkdir()
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        active = component / "active.json"
        active.write_text("not json", encoding="utf-8")
        self.assertIsNotNone(resolve_active_yt_dlp(self.base).managed_issue)
        pointer = {
            "version": "2026.09.01",
            "sha256": "0" * 64,
            "relative_path": "2026.09.01/yt-dlp.exe",
        }
        active.write_text(json.dumps(pointer), encoding="utf-8")
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        version_dir = component / "2026.09.01"
        version_dir.mkdir()
        binary = version_dir / "yt-dlp.exe"
        binary.write_bytes(b"tampered")
        (version_dir / "metadata.json").write_text(
            json.dumps(pointer | {"component": "yt-dlp"}), encoding="utf-8"
        )
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        pointer["version"] = "nightly"
        active.write_text(json.dumps(pointer), encoding="utf-8")
        self.assertFalse(resolve_active_yt_dlp(self.base).managed)
        self.assertEqual(locate_tools(self.base).yt_dlp, self.base / "yt-dlp.exe")

    def test_post_activation_failure_rolls_back_bundled_and_previous_managed(
        self,
    ) -> None:
        self.assertIs(self._update().status, UpdateStatus.UPDATED)
        component = self.base / "Componentes" / "yt-dlp"
        old_pointer = (component / "active.json").read_bytes()
        next_transport = FakeTransport("2026.09.02", b"third-yt-dlp")
        self.service.transport = next_transport
        import downloader

        original_locate = downloader.locate_tools
        with (
            patch(
                "yt_dlp_update._probe_version",
                side_effect=lambda path: (
                    "2026.09.02"
                    if path.parent.name == "2026.09.02"
                    or path.parent.parent.name == "yt-dlp"
                    and path.parent.parent.parent.name == ".staging"
                    else "2026.09.01"
                ),
            ),
            patch(
                "downloader.locate_tools",
                side_effect=lambda base: replace(
                    original_locate(base), yt_dlp=self.base / "yt-dlp.exe"
                ),
            ),
        ):
            result = self.service.update(
                next_transport.release, cancel=threading.Event()
            )
        self.assertIs(result.status, UpdateStatus.FAILED)
        self.assertEqual((component / "active.json").read_bytes(), old_pointer)
        self.assertEqual(resolve_active_yt_dlp(self.base).version, "2026.09.01")
        self._assert_baseline()

    def test_size_limit_and_no_downgrade(self) -> None:
        release = self.transport.release
        oversized = replace(release, binary_size=MAX_BINARY_BYTES + 1)
        with patch("yt_dlp_update._probe_version", return_value="2026.08.19"):
            self.assertIs(
                self.service.update(oversized, cancel=threading.Event()).status,
                UpdateStatus.FAILED,
            )
        self.assertEqual(self.transport.calls, [])
