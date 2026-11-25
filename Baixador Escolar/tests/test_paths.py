"""Testes dos caminhos portáteis."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paths
from constants import (
    DENO_FILENAME,
    FFMPEG_FILENAME,
    FFPROBE_FILENAME,
    YTDLP_FILENAME,
    ProductEdition,
)
from paths import LocalDataPathUnavailable


class PathsTests(unittest.TestCase):
    def test_frozen_state_is_user_edition_scoped_and_independent_of_app_location(self):
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp) / "profile"
            for edition in ProductEdition:
                with (
                    patch.object(sys, "frozen", True, create=True),
                    patch.object(
                        sys, "executable", str(Path(temp) / "read-only/app.exe")
                    ),
                    patch.dict(os.environ, {"LOCALAPPDATA": str(local)}),
                ):
                    expected = (
                        local
                        / "EduDownloader"
                        / (edition.value.title() + "2")
                        / "Runtime"
                    )
                    self.assertEqual(
                        paths.get_settings_path(), expected / "settings.json"
                    )
                    self.assertEqual(
                        paths.get_logs_dir(paths.get_app_dir()), expected / "Logs"
                    )
                    self.assertFalse(local.exists())
                    with patch.object(
                        sys, "executable", str(Path(temp) / "moved/app.exe")
                    ):
                        self.assertEqual(paths.get_runtime_state_dir(), expected)

    def test_frozen_state_has_no_app_root_fallback_without_user_profile(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.dict(os.environ, {"LOCALAPPDATA": ""}),
            self.assertRaises(LocalDataPathUnavailable),
        ):
            paths.get_runtime_state_dir()

    def test_installed_community_separates_ocr_from_writable_components(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Aplicação com espaço"
            package = root / "Programa" / "revision"
            package.mkdir(parents=True)
            local = Path(temp) / "profile"
            local.mkdir()
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(package / "EduDownloader.exe")),
                patch.dict(os.environ, {"LOCALAPPDATA": str(local)}),
            ):
                self.assertIsNone(paths.get_community_install_root())
                self.assertEqual(
                    paths.get_managed_components_dir(), package / "Componentes"
                )
                (package / paths.COMMUNITY_INSTALL_MARKER).touch()
                self.assertEqual(paths.get_community_install_root(), root)
                self.assertEqual(
                    paths.get_bundled_components_dir(), package / "Componentes"
                )
                expected = local / "EduDownloader/Community2/Runtime/Componentes"
                self.assertEqual(paths.get_managed_components_dir(package), expected)
                self.assertEqual(
                    paths.probe_managed_root(),
                    paths.ManagedRootCheck(expected, paths.ManagedRootState.AVAILABLE),
                )
                self.assertFalse(expected.parent.exists())
                self.assertEqual(
                    paths.get_managed_components_dir(root), root / "Componentes"
                )

    def test_documents_temporary_parent_ignores_long_os_temp(self):
        local = Path(__file__).resolve().parents[2]
        long_temp = str(local / ("d" * 165))
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local), "TEMP": long_temp}):
            self.assertEqual(paths.documents_conversion_temp_parent(), local)
            self.assertEqual(os.environ["TEMP"], long_temp)

    def test_development_path_is_module_folder(self) -> None:
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(paths.get_app_dir(), Path(paths.__file__).resolve().parent)

    def test_frozen_path_uses_executable_folder(self) -> None:
        fake_executable = str(Path("C:/Portable/EduDownloader/app.exe"))
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", fake_executable),
        ):
            self.assertEqual(
                paths.get_app_dir(), Path(fake_executable).resolve().parent
            )

    def test_frozen_paths_support_spaces_accents_and_external_tools(self) -> None:
        fake_executable = str(
            Path("D:/Materiais da Educação/EduDownloader/EduDownloader.exe")
        )
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", fake_executable),
        ):
            base_dir = Path(fake_executable).resolve().parent
            self.assertEqual(paths.get_app_dir(), base_dir)
            self.assertEqual(
                paths.get_tool_path(YTDLP_FILENAME), base_dir / YTDLP_FILENAME
            )
            self.assertEqual(
                paths.get_tool_path(FFMPEG_FILENAME), base_dir / FFMPEG_FILENAME
            )
            self.assertEqual(
                paths.get_tool_path(FFPROBE_FILENAME), base_dir / FFPROBE_FILENAME
            )
            self.assertEqual(
                paths.get_tool_path(DENO_FILENAME), base_dir / DENO_FILENAME
            )

    def test_downloads_folder_is_created_inside_base_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            result = paths.ensure_downloads_dir(base_dir)
            self.assertEqual(result, base_dir / "Downloads")
            self.assertTrue(result.is_dir())

    def test_settings_file_is_located_inside_base_folder(self) -> None:
        base_dir = Path("unidade-portatil")
        self.assertEqual(paths.get_settings_path(base_dir), base_dir / "settings.json")

    def test_external_tool_and_log_are_relative_to_base_folder(self) -> None:
        base_dir = Path("unidade com espaços")
        self.assertEqual(
            paths.get_tool_path(YTDLP_FILENAME, base_dir),
            base_dir / YTDLP_FILENAME,
        )
        self.assertEqual(
            paths.get_log_path(base_dir),
            base_dir / "Logs" / "edudownloader.log",
        )

    @unittest.skipUnless(os.name == "nt", "Recurso específico do Windows")
    def test_open_downloads_creates_and_opens_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            with patch.object(paths.os, "startfile") as startfile:
                result = paths.open_downloads_dir(Path(temporary_dir))
            startfile.assert_called_once_with(result)
            self.assertTrue(result.is_dir())


if __name__ == "__main__":
    unittest.main()
