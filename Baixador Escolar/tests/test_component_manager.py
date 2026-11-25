"""Contratos locais do inventário de componentes externos."""

from __future__ import annotations

import socket
import hashlib
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from component_manager import (
    COMPONENT_REGISTRY,
    ComponentCapability,
    ComponentId,
    ComponentManager,
    ComponentOrigin,
    ComponentState,
    ManagedRootState,
    _local_version,
    probe_managed_root,
)
from documents_component import DocumentsComponentCheck, DocumentsComponentStatus
from paths import get_managed_components_dir


class ComponentManagerTests(unittest.TestCase):
    def test_registry_order_identities_origins_and_capabilities(self) -> None:
        self.assertEqual(
            tuple(item.component_id for item in COMPONENT_REGISTRY),
            (
                ComponentId.YT_DLP,
                ComponentId.DENO,
                ComponentId.FFMPEG_FFPROBE,
                ComponentId.LIBREOFFICE,
                ComponentId.OCR,
            ),
        )
        self.assertEqual(
            COMPONENT_REGISTRY[2].executable_ids,
            (ComponentId.FFMPEG, ComponentId.FFPROBE),
        )
        self.assertTrue(all(item.required for item in COMPONENT_REGISTRY[:3]))
        self.assertFalse(COMPONENT_REGISTRY[3].required)
        self.assertTrue(
            all(
                item.origin is ComponentOrigin.BUNDLED
                for item in COMPONENT_REGISTRY[:3]
            )
        )
        self.assertIs(COMPONENT_REGISTRY[3].origin, ComponentOrigin.USER_PROVIDED)
        self.assertEqual(
            COMPONENT_REGISTRY[0].capabilities,
            frozenset(
                {
                    ComponentCapability.DETECT,
                    ComponentCapability.VERIFY,
                    ComponentCapability.CHECK_UPDATE,
                    ComponentCapability.UPDATE,
                }
            ),
        )
        self.assertTrue(
            all(
                ComponentCapability.UPDATE not in definition.capabilities
                for definition in COMPONENT_REGISTRY[1:]
            )
        )

    def test_cached_snapshots_lookup_and_invalid_id(self) -> None:
        manager = ComponentManager()
        snapshots = manager.list_components()
        self.assertEqual(len(snapshots), 5)
        self.assertTrue(
            all(snapshot.state is ComponentState.NOT_CHECKED for snapshot in snapshots)
        )
        self.assertEqual(manager.get_component("ffprobe"), snapshots[2])
        self.assertEqual(manager.get_component("ffmpeg"), snapshots[2])
        with self.assertRaises(FrozenInstanceError):
            snapshots[0].detail = "changed"
        with self.assertRaises(ValueError):
            manager.get_component("unknown")

    def test_version_probe_is_bounded_local_and_without_shell(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="deno 2.9.5\n")
        with patch("component_manager.subprocess.run", return_value=completed) as run:
            self.assertEqual(
                _local_version(Path("C:/portable/deno.exe"), "--version"), "2.9.5"
            )
        args, kwargs = run.call_args
        self.assertEqual(args[0], [str(Path("C:/portable/deno.exe")), "--version"])
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 3)

    def test_yt_dlp_present_and_version_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            (base / "yt-dlp.exe").write_bytes(b"synthetic")
            manager = ComponentManager(base_dir=base)
            with patch("component_manager._local_version", return_value="2026.07.04"):
                snapshot = manager.refresh(ComponentId.YT_DLP)
        self.assertIs(snapshot.state, ComponentState.READY)
        self.assertEqual(snapshot.version, "2026.07.04")

    def test_managed_yt_dlp_origin_and_corrupt_fallback_are_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            (base / "yt-dlp.exe").write_bytes(b"bundled")
            component = base / "Componentes" / "yt-dlp"
            version_dir = component / "2026.09.01"
            version_dir.mkdir(parents=True)
            binary = version_dir / "yt-dlp.exe"
            binary.write_bytes(b"managed")
            pointer = {
                "component": "yt-dlp",
                "version": "2026.09.01",
                "relative_path": "2026.09.01/yt-dlp.exe",
                "sha256": hashlib.sha256(b"managed").hexdigest(),
            }
            (component / "active.json").write_text(
                json.dumps(pointer), encoding="utf-8"
            )
            (version_dir / "metadata.json").write_text(
                json.dumps(pointer), encoding="utf-8"
            )
            manager = ComponentManager(base_dir=base)
            with patch(
                "component_manager._local_version",
                side_effect=lambda path, *args: (
                    "2026.09.01" if path == binary else "2026.08.19"
                ),
            ):
                managed = manager.refresh(ComponentId.YT_DLP)
                binary.write_bytes(b"tampered")
                bundled = manager.refresh(ComponentId.YT_DLP)
            self.assertIs(managed.origin, ComponentOrigin.MANAGED)
            self.assertEqual(managed.path, binary)
            self.assertEqual(managed.version, "2026.09.01")
            self.assertIs(bundled.origin, ComponentOrigin.BUNDLED)
            self.assertEqual(bundled.path, base / "yt-dlp.exe")
            self.assertIn("indisponível", bundled.detail)

    def test_bundled_present_missing_invalid_and_group_atomicity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            manager = ComponentManager(base_dir=base)
            self.assertIs(
                manager.refresh(ComponentId.YT_DLP).state, ComponentState.MISSING
            )
            self.assertIs(
                manager.refresh(ComponentId.DENO).state, ComponentState.MISSING
            )
            self.assertIs(
                manager.refresh(ComponentId.FFMPEG_FFPROBE).state,
                ComponentState.MISSING,
            )
            (base / "yt-dlp.exe").mkdir()
            self.assertIs(
                manager.refresh(ComponentId.YT_DLP).state, ComponentState.INVALID
            )
            (base / "ffmpeg.exe").write_bytes(b"synthetic")
            self.assertIs(
                manager.refresh(ComponentId.FFPROBE).state, ComponentState.MISSING
            )
            (base / "ffprobe.exe").mkdir()
            self.assertIs(
                manager.refresh(ComponentId.FFMPEG).state, ComponentState.INVALID
            )
            (base / "ffprobe.exe").rmdir()
            (base / "ffprobe.exe").write_bytes(b"synthetic")
            (base / "deno.exe").write_bytes(b"synthetic")
            with patch(
                "component_manager._local_version", return_value="1.2.3"
            ) as probe:
                self.assertIs(
                    manager.refresh(ComponentId.DENO).state, ComponentState.READY
                )
                group = manager.refresh(ComponentId.FFMPEG_FFPROBE)
            self.assertIs(group.state, ComponentState.READY)
            self.assertEqual(group.version, "1.2.3")
            self.assertEqual(len(group.executable_paths), 2)
            self.assertEqual(probe.call_count, 3)
            with patch("component_manager._local_version", side_effect=["1.2", "2.0"]):
                self.assertIs(
                    manager.refresh(ComponentId.FFMPEG_FFPROBE).state,
                    ComponentState.VERSION_MISMATCH,
                )

    def test_adapter_failure_is_safe_and_does_not_break_other_components(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            (base / "deno.exe").write_bytes(b"synthetic")
            manager = ComponentManager(base_dir=base)
            with patch(
                "component_manager._local_version", side_effect=OSError("secret")
            ):
                failed = manager.refresh(ComponentId.DENO)
            self.assertIs(failed.state, ComponentState.FAILED)
            self.assertNotIn("secret", failed.detail)
            self.assertIs(
                manager.refresh(ComponentId.YT_DLP).state, ComponentState.MISSING
            )

    def test_documents_status_mapping_reuses_service_and_current_path(self) -> None:
        root = Path("C:/component test")
        holder: dict[str, Path | None] = {"path": None}
        checks = [
            (DocumentsComponentStatus.NOT_CONFIGURED, ComponentState.NOT_CONFIGURED),
            (DocumentsComponentStatus.AVAILABLE, ComponentState.READY),
            (DocumentsComponentStatus.INVALID, ComponentState.INVALID),
            (
                DocumentsComponentStatus.VERSION_MISMATCH,
                ComponentState.VERSION_MISMATCH,
            ),
            (DocumentsComponentStatus.CORRUPTED, ComponentState.CORRUPTED),
        ]
        for document_state, expected in checks:
            with self.subTest(status=document_state):
                component = (
                    SimpleNamespace(root=root, engine_version="26.2.4.2")
                    if document_state is DocumentsComponentStatus.AVAILABLE
                    else None
                )
                service = SimpleNamespace(
                    fast_check=lambda configured: DocumentsComponentCheck(
                        document_state, component, "existing_diagnostic"
                    )
                )
                manager = ComponentManager(
                    documents_service=service,
                    documents_path=lambda: holder["path"],
                )
                holder["path"] = root
                snapshot = manager.refresh(ComponentId.LIBREOFFICE)
                self.assertIs(snapshot.state, expected)
                self.assertIs(snapshot.origin, ComponentOrigin.USER_PROVIDED)
                self.assertFalse(snapshot.required)
                if component is not None:
                    self.assertEqual(snapshot.version, "26.2.4.2")
                    self.assertEqual(snapshot.path, root)
                holder["path"] = None

    def test_refresh_all_does_not_use_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            manager = ComponentManager(base_dir=Path(temporary_dir))
            with patch.object(socket, "create_connection", side_effect=AssertionError):
                snapshots = manager.refresh_all()
        self.assertEqual(len(snapshots), 5)
        self.assertIs(
            manager.get_component(ComponentId.LIBREOFFICE).state,
            ComponentState.NOT_CONFIGURED,
        )
        self.assertIs(
            manager.get_component(ComponentId.OCR).state, ComponentState.MISSING
        )


class ManagedRootTests(unittest.TestCase):
    def test_portable_derivation_spaces_unicode_and_relocation(self) -> None:
        first = Path("D:/Escola João/Meu Aplicativo")
        second = Path("E:/Escola João/Meu Aplicativo")
        self.assertEqual(get_managed_components_dir(first), first / "Componentes")
        self.assertEqual(get_managed_components_dir(second), second / "Componentes")
        self.assertNotEqual(
            get_managed_components_dir(first), get_managed_components_dir(second)
        )

    def test_query_does_not_create_directory_and_probe_removes_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = get_managed_components_dir(base)
            self.assertFalse(root.exists())
            self.assertIs(probe_managed_root(base).state, ManagedRootState.AVAILABLE)
            self.assertFalse(root.exists())
            self.assertEqual(tuple(base.iterdir()), ())

    def test_read_only_and_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            with patch("paths.tempfile.TemporaryFile", side_effect=PermissionError):
                self.assertIs(
                    probe_managed_root(base).state, ManagedRootState.READ_ONLY
                )
            (base / "Componentes").write_text("not a directory", encoding="utf-8")
            self.assertIs(probe_managed_root(base).state, ManagedRootState.UNAVAILABLE)
            self.assertIs(
                probe_managed_root(base / "does-not-exist").state,
                ManagedRootState.UNAVAILABLE,
            )
