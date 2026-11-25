import hashlib
from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from component_catalog import parse_catalogue
from component_updates import (
    ComponentUpdateService,
    active_component,
    component_use,
    remove_owned_components,
)
from component_transactions import ManagedStage
from tests.test_component_catalog import catalogue
from yt_dlp_update import UpdateStatus


def _exe():
    value = bytearray(96)
    value[:2] = b"MZ"
    struct.pack_into("<I", value, 60, 64)
    value[64:70] = b"PE\0\0\x64\x86"
    return bytes(value)


def _manifest(archive, binary, version="2.9.8"):
    def field(name, data):
        return {
            "source": name,
            "target": name,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    return {
        "component": "deno",
        "version": version,
        "architecture": "windows-x64",
        "minimum_app": "3.0.0",
        "maximum_app": "3.0.0",
        "provenance": "https://github.com/example/fixture",
        "notices": ["LICENSE.txt"],
        "assets": [
            {
                "url": "https://github.com/example/fixture.zip",
                "kind": "zip",
                "size": len(archive),
                "sha256": hashlib.sha256(archive).hexdigest(),
                "signer": None,
                "files": [field("deno.exe", binary), field("LICENSE.txt", b"Fixture")],
            }
        ],
    }


class _Transport:
    def __init__(self, payload):
        self.payload = payload
        self.attempts = 0

    def download(self, _url, destination, **kwargs):
        self.attempts += 1
        destination.write_bytes(self.payload)
        return hashlib.sha256(self.payload).hexdigest()


class ManagedUpdatesTests(unittest.TestCase):
    def test_updates_lock_and_activate_and_cleanup_only_owned_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = _exe()
            archive = root / "fixture.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("deno.exe", executable)
                output.writestr("LICENSE.txt", b"Fixture")
            payload = archive.read_bytes()
            approved = parse_catalogue(
                catalogue(assets=[_manifest(payload, executable)])
            )
            release = approved.available("deno")
            transport = _Transport(payload)
            service = ComponentUpdateService(root, transport=transport)
            cancel = threading.Event()
            with (
                patch("component_updates.effective_catalogue", return_value=approved),
                patch("component_updates.verify_component") as smoke,
            ):
                with component_use(root, "deno"), component_use(root, "deno"):
                    self.assertEqual(
                        service.update(release, cancel=cancel)[1], "component_busy"
                    )
                self.assertEqual(transport.attempts, 0)
                cancel.set()
                self.assertEqual(
                    service.update(release, cancel=cancel)[0], UpdateStatus.CANCELLED
                )
                cancel.clear()
                self.assertEqual(
                    service.update(release, cancel=cancel)[0], UpdateStatus.UPDATED
                )
                smoke.assert_called_once()
                folder, version = active_component(root, "deno")
                self.assertEqual(version, "2.9.8")
                additional = folder / "documento.txt"
                additional.write_bytes(b"Arquivo do usuario")
                transport.payload = b"wrong data"
                self.assertEqual(
                    service.update(release, cancel=cancel)[1],
                    "component_sha256_mismatch",
                )
                self.assertEqual(active_component(root, "deno"), (folder, version))
                remove_owned_components(root)
                self.assertEqual(additional.read_bytes(), b"Arquivo do usuario")
                self.assertIsNone(active_component(root, "deno"))

    def test_cleanup_failure_leaves_previous_active_and_prevents_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "fixture.zip"
            binary = _exe()
            with zipfile.ZipFile(archive, "x") as output:
                output.writestr("deno.exe", binary)
                output.writestr("LICENSE.txt", b"Fixture")
            payload = archive.read_bytes()
            approved = parse_catalogue(catalogue(assets=[_manifest(payload, binary)]))
            service = ComponentUpdateService(root, transport=_Transport(payload))

            def leave_stage_for_recovery(stage):
                stage.close()
                return False

            with (
                patch("component_updates.effective_catalogue", return_value=approved),
                patch("component_updates.verify_component"),
                patch.object(
                    ManagedStage,
                    "cleanup",
                    autospec=True,
                    side_effect=leave_stage_for_recovery,
                ) as cleanup,
            ):
                release = approved.available("deno")
                result = service.update(release, cancel=threading.Event())
            self.assertEqual(result, (UpdateStatus.FAILED, "component_cleanup_pending"))
            self.assertEqual(cleanup.call_count, 1)
            self.assertFalse((service.root / "deno/active.json").exists())

    def test_space_failure_never_downloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = _exe()
            approved = parse_catalogue(
                catalogue(assets=[_manifest(b"fixture", binary)])
            )
            backend = _Transport(b"fixture")
            service = ComponentUpdateService(root, transport=backend)
            with (
                patch("component_updates.effective_catalogue", return_value=approved),
                patch(
                    "component_updates.shutil.disk_usage",
                    return_value=SimpleNamespace(free=0),
                ),
            ):
                result = service.update(
                    approved.available("deno"), cancel=threading.Event()
                )
            self.assertEqual(result[1], "insufficient_space")
            self.assertEqual(backend.attempts, 0)
