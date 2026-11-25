"""Testes da camada de download sem acessar a internet."""

import io
import errno
import ctypes
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import FrozenInstanceError
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import Mock, patch

from constants import CONTENT_TYPE_AUDIO, CONTENT_TYPE_VIDEO, REQUIRED_EXECUTABLES
from downloader import (
    DownloadEvent,
    DownloadEventBuffer,
    DownloadEventKind,
    DownloadCancelledError,
    DownloadBusyError,
    DownloadPhase,
    DownloadProgress,
    DownloadRequest,
    DownloadResult,
    DownloadService,
    DownloadServiceError,
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    MissingToolsError,
    TASK_TEMP_ROOT_NAME,
    build_download_command,
    build_video_format,
    classify_download_error,
    classify_os_error,
    locate_tools,
    parse_progress_line,
    validate_external_tools,
    _probe_destination_writable,
    _redact_sensitive_text,
    _resolve_download_destination,
    _phase_from_output,
    _validate_final_output_path,
)
from mp3_quality import DEFAULT_MP3_QUALITY, MP3_QUALITY_OPTIONS, Mp3Quality


def make_silent_logger() -> logging.Logger:
    """Cria um logger sem arquivo para os testes do serviço."""
    logger = logging.getLogger("edudownloader.tests")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


class FailingStream:
    """Fluxo que simula uma falha inesperada ao ler a saída do processo."""

    def __iter__(self) -> "FailingStream":
        return self

    def __next__(self) -> str:
        raise OSError("falha de leitura simulada")

    def close(self) -> None:
        """Imita o método disponível em um pipe real."""


class ToolValidationTests(unittest.TestCase):
    def test_yt_dlp_update_reservation_blocks_new_download_without_side_effects(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            service = DownloadService(base, make_silent_logger())
            self.assertTrue(service.begin_yt_dlp_update())
            self.assertFalse(service.begin_yt_dlp_update())
            with self.assertRaises(DownloadBusyError):
                service.start(
                    DownloadRequest(
                        "https://example.com/aula", CONTENT_TYPE_VIDEO, "720p"
                    )
                )
            self.assertFalse(service.is_running)
            service.end_yt_dlp_update()
            with service._lock:
                service._running = True
            self.assertFalse(service.begin_yt_dlp_update())
            with service._lock:
                service._running = False
            self.assertTrue(service.begin_yt_dlp_update())
            service.end_yt_dlp_update()

    def test_locate_tools_uses_the_portable_base_folder(self) -> None:
        base_dir = Path("C:/Pasta com espaços/EduDownloader")
        tools = locate_tools(base_dir)
        self.assertEqual(tools.yt_dlp, base_dir / "yt-dlp.exe")
        self.assertEqual(tools.ffmpeg, base_dir / "ffmpeg.exe")
        self.assertEqual(tools.ffprobe, base_dir / "ffprobe.exe")
        self.assertEqual(tools.deno, base_dir / "deno.exe")

    def test_validate_tools_accepts_all_four_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            for filename in REQUIRED_EXECUTABLES:
                (base_dir / filename).touch()
            tools = validate_external_tools(base_dir)
            self.assertEqual(tools.yt_dlp.name, "yt-dlp.exe")

    def test_validate_tools_lists_missing_files_in_portuguese(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            (base_dir / "yt-dlp.exe").touch()
            with self.assertRaises(MissingToolsError) as context:
                validate_external_tools(base_dir)
            self.assertNotIn(
                "yt-dlp.exe não foi encontrado", context.exception.user_message
            )
            self.assertIn(
                "ffmpeg.exe não foi encontrado", context.exception.user_message
            )
            self.assertIn(
                "ffprobe.exe não foi encontrado", context.exception.user_message
            )
            self.assertIn("deno.exe não foi encontrado", context.exception.user_message)


class CommandBuildingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_dir = Path("C:/Pasta com espaços/EduDownloader")
        self.tools = locate_tools(self.base_dir)
        self.downloads_dir = self.base_dir / "Downloads"

    def test_video_command_preserves_quality_and_requests_mp4_output(self) -> None:
        request = DownloadRequest(
            "https://example.com/aula",
            CONTENT_TYPE_VIDEO,
            "720p",
        )
        command = build_download_command(request, self.tools, self.downloads_dir)
        format_selector = command[command.index("--format") + 1]

        self.assertEqual(command[0], str(self.tools.yt_dlp))
        self.assertIn("[height<=720]", format_selector)
        preferred_format = format_selector.split("/", maxsplit=1)[0]
        self.assertIn("[vcodec^=avc1]", preferred_format)
        self.assertIn("[acodec^=mp4a]", preferred_format)
        self.assertNotIn("[ext=mp4]", format_selector)
        self.assertIn("--merge-output-format", command)
        self.assertIn("--remux-video", command)
        self.assertIn("--windows-filenames", command)
        self.assertIn("--no-overwrites", command)
        self.assertIn(str(self.downloads_dir), command)
        output_template = command[command.index("--output") + 1]
        self.assertIn("%(height)sp", output_template)
        self.assertEqual(command[-1], request.url)

    def test_command_uses_only_packaged_deno_without_remote_components(self) -> None:
        request = DownloadRequest(
            "https://example.com/aula",
            CONTENT_TYPE_VIDEO,
            "720p",
        )

        command = build_download_command(request, self.tools, self.downloads_dir)

        runtime_index = command.index("--js-runtimes")
        self.assertIn("--no-js-runtimes", command)
        self.assertEqual(
            command[runtime_index + 1], f"deno:{self.tools.deno.resolve()}"
        )
        self.assertIn("--no-remote-components", command)
        self.assertNotIn("--remote-components", command)
        self.assertNotIn("node", command)
        self.assertNotIn("bun", command)
        self.assertNotIn("quickjs", command)

    def test_deno_argument_preserves_spaces_and_unicode_as_one_item(self) -> None:
        base_dir = Path("D:/Materiais da Educação/EduDownloader Portátil")
        tools = locate_tools(base_dir)
        request = DownloadRequest(
            "https://example.com/aula",
            CONTENT_TYPE_AUDIO,
            "Melhor qualidade",
        )

        command = build_download_command(request, tools, base_dir / "Downloads")

        runtime_index = command.index("--js-runtimes")
        self.assertEqual(command[runtime_index + 1], f"deno:{tools.deno.resolve()}")
        self.assertIn("Educação", command[runtime_index + 1])
        self.assertIn("Portátil", command[runtime_index + 1])

    def test_all_visual_video_qualities_have_a_selector(self) -> None:
        expected_limits = {
            "Melhor qualidade": None,
            "1080p": 1080,
            "720p": 720,
            "480p": 480,
            "360p": 360,
        }
        for quality, height in expected_limits.items():
            with self.subTest(quality=quality):
                selector = build_video_format(quality)
                if height is None:
                    self.assertNotIn("height<=", selector)
                    height_filter = ""
                else:
                    self.assertIn(f"height<={height}", selector)
                    height_filter = f"[height<={height}]"
                self.assertIn("[vcodec^=avc1]", selector)
                self.assertTrue(
                    selector.endswith(f"bv*{height_filter}+ba/b{height_filter}")
                )

    def test_audio_command_extracts_mp3_with_ffmpeg(self) -> None:
        request = DownloadRequest(
            "https://example.com/audio",
            CONTENT_TYPE_AUDIO,
            "Melhor qualidade",
        )
        command = build_download_command(request, self.tools, self.downloads_dir)
        self.assertIn("--extract-audio", command)
        self.assertEqual(command[command.index("--audio-format") + 1], "mp3")
        self.assertEqual(command[command.index("--audio-quality") + 1], "192K")
        self.assertIn("--ffmpeg-location", command)
        output_template = command[command.index("--output") + 1]
        self.assertIn("[audio]", output_template)
        self.assertNotIn("%(height)", output_template)

    def test_audio_profiles_change_only_final_bitrate_not_source_selection(
        self,
    ) -> None:
        for profile in MP3_QUALITY_OPTIONS:
            with self.subTest(profile=profile):
                request = DownloadRequest(
                    "https://example.com/audio",
                    CONTENT_TYPE_AUDIO,
                    "720p",
                    mp3_quality=profile,
                )
                command = build_download_command(
                    request, self.tools, self.downloads_dir
                )

                self.assertEqual(
                    command[command.index("--format") + 1], "bestaudio/best"
                )
                self.assertEqual(
                    command[command.index("--audio-quality") + 1],
                    profile.bitrate_argument.upper(),
                )
                self.assertEqual(command.count("--format"), 1)
                self.assertEqual(command.count("--audio-quality"), 1)
                self.assertEqual(command.count("--extract-audio"), 1)
                self.assertEqual(command[command.index("--audio-format") + 1], "mp3")
                self.assertEqual(command.count("--ffmpeg-location"), 1)
                self.assertIn("--no-overwrites", command)
                self.assertEqual(command[-1], request.url)

    def test_audio_profile_defaults_to_shared_standard_and_rejects_custom_values(
        self,
    ) -> None:
        request = DownloadRequest(
            "https://example.com/audio", CONTENT_TYPE_AUDIO, "Melhor qualidade"
        )
        self.assertIs(request.mp3_quality, DEFAULT_MP3_QUALITY)
        command = build_download_command(request, self.tools, self.downloads_dir)
        self.assertEqual(
            command[command.index("--audio-quality") + 1],
            "192K",
        )
        invalid = DownloadRequest(
            request.url,
            CONTENT_TYPE_AUDIO,
            request.quality,
            mp3_quality="500K",
        )
        with self.assertRaises(ValueError):
            build_download_command(invalid, self.tools, self.downloads_dir)

    def test_video_command_ignores_mp3_profile(self) -> None:
        for profile in (Mp3Quality.ECONOMY, Mp3Quality.HIGH):
            with self.subTest(profile=profile):
                command = build_download_command(
                    DownloadRequest(
                        "https://example.com/video",
                        CONTENT_TYPE_VIDEO,
                        "720p",
                        mp3_quality=profile,
                    ),
                    self.tools,
                    self.downloads_dir,
                )
                self.assertNotIn("--audio-quality", command)
                self.assertIn("[height<=720]", command[command.index("--format") + 1])


class DownloadDestinationContractTests(unittest.TestCase):
    def _create_tools(self, base_dir: Path) -> None:
        for filename in REQUIRED_EXECUTABLES:
            (base_dir / filename).touch()

    def test_request_destination_is_immutable(self) -> None:
        request = DownloadRequest(
            "https://example.com/aula",
            CONTENT_TYPE_VIDEO,
            "720p",
            Path("C:/Destino"),
        )

        with self.assertRaises(FrozenInstanceError):
            request.destination_dir = Path("C:/Outro")  # type: ignore[misc]

    def test_missing_destination_preserves_downloads_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            self._create_tools(base_dir)
            service = DownloadService(base_dir, make_silent_logger())
            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_VIDEO,
                "720p",
            )

            with patch("downloader.threading.Thread") as thread:
                service.start(request)

            worker_args = thread.call_args.kwargs["args"]
            effective_destination = worker_args[3]
            command = worker_args[1]
            self.assertEqual(effective_destination, (base_dir / "Downloads").resolve())
            self.assertEqual(
                command[command.index("--paths") + 1],
                str(effective_destination),
            )

    def test_explicit_destinations_with_spaces_and_unicode_are_preserved(self) -> None:
        names = ("Materiais com espaços", "Educação João 你好")
        for name in names:
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory() as temporary_dir,
            ):
                base_dir = Path(temporary_dir)
                destination_dir = base_dir / name
                destination_dir.mkdir()
                self._create_tools(base_dir)
                service = DownloadService(base_dir, make_silent_logger())
                request = DownloadRequest(
                    "https://example.com/aula",
                    CONTENT_TYPE_VIDEO,
                    "720p",
                    destination_dir,
                )

                with patch("downloader.threading.Thread") as thread:
                    service.start(request)

                worker_args = thread.call_args.kwargs["args"]
                effective_destination = worker_args[3]
                command = worker_args[1]
                self.assertEqual(effective_destination, destination_dir.resolve())
                self.assertEqual(
                    command[command.index("--paths") + 1],
                    str(destination_dir.resolve()),
                )

    def test_community_worker_uses_destination_without_indexing_personal_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            destination_dir = base_dir / "Destino"
            destination_dir.mkdir()
            existing_file = destination_dir / "Aula existente.mp4"
            existing_file.write_bytes(b"fixture pessoal")
            self._create_tools(base_dir)
            service = DownloadService(base_dir, make_silent_logger())
            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_VIDEO,
                "720p",
                destination_dir,
            )

            with patch("downloader.threading.Thread") as thread:
                service.start(request)

            worker_args = thread.call_args.kwargs["args"]
            self.assertEqual(worker_args[3], destination_dir.resolve())
            self.assertEqual(worker_args[2], frozenset())
            self.assertTrue(thread.call_args.kwargs["kwargs"]["protected"])
            self.assertEqual(existing_file.read_bytes(), b"fixture pessoal")

    def test_explicit_nonexistent_destination_fails_without_starting_worker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            destination_dir = base_dir / "Inexistente"
            self._create_tools(base_dir)
            service = DownloadService(base_dir, make_silent_logger())
            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_VIDEO,
                "720p",
                destination_dir,
            )

            with (
                patch("downloader.threading.Thread") as thread,
                patch("downloader.subprocess.Popen") as popen,
                self.assertRaises(DownloadServiceError) as context,
            ):
                service.start(request)

            self.assertIn("destino selecionada", context.exception.user_message)
            self.assertFalse((base_dir / "Downloads").exists())
            thread.assert_not_called()
            popen.assert_not_called()

    def test_explicit_file_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            destination_file = base_dir / "arquivo.txt"
            destination_file.touch()
            self._create_tools(base_dir)
            service = DownloadService(base_dir, make_silent_logger())
            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_VIDEO,
                "720p",
                destination_file,
            )

            with (
                patch("downloader.threading.Thread") as thread,
                self.assertRaises(DownloadServiceError),
            ):
                service.start(request)

            thread.assert_not_called()

    def test_explicit_unwritable_destination_is_rejected_deterministically(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            destination_dir = base_dir / "Destino"
            destination_dir.mkdir()
            self._create_tools(base_dir)
            service = DownloadService(base_dir, make_silent_logger())
            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_VIDEO,
                "720p",
                destination_dir,
            )

            with (
                patch(
                    "downloader._probe_destination_writable",
                    side_effect=PermissionError(errno.EACCES, "negado"),
                ),
                patch("downloader.threading.Thread") as thread,
                self.assertRaises(DownloadServiceError) as context,
            ):
                service.start(request)

            self.assertIn("permite gravação", context.exception.user_message)
            thread.assert_not_called()

    def test_destination_write_probe_leaves_no_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            destination_dir = Path(temporary_dir)
            before = set(destination_dir.iterdir())

            _probe_destination_writable(destination_dir)

            self.assertEqual(set(destination_dir.iterdir()), before)

    def test_relative_explicit_destination_is_rejected(self) -> None:
        with self.assertRaises(DownloadServiceError):
            _resolve_download_destination(Path("Destino relativo"), Path.cwd())

    def test_task_temporary_directory_is_created_under_effective_destination(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            destination_dir = base_dir / "Destino externo"
            destination_dir.mkdir()
            service = DownloadService(base_dir, make_silent_logger())

            task_temp_dir = service._create_task_temp_dir(destination_dir.resolve())

            self.assertEqual(
                task_temp_dir.parent,
                destination_dir.resolve() / TASK_TEMP_ROOT_NAME,
            )
            self.assertTrue(task_temp_dir.name.startswith("tarefa-"))

    def test_cleanup_rejects_task_directory_outside_effective_destination(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            destination_dir = base_dir / "Destino"
            destination_dir.mkdir()
            unrelated_dir = base_dir / TASK_TEMP_ROOT_NAME / "tarefa-alheia"
            unrelated_dir.mkdir(parents=True)
            unrelated_file = unrelated_dir / "preservar.part"
            unrelated_file.touch()
            service = DownloadService(base_dir, make_silent_logger())

            result = service._cleanup_cancelled_task_temp(
                unrelated_dir,
                destination_dir.resolve(),
            )

            self.assertEqual(result, (0, 1))
            self.assertTrue(unrelated_file.is_file())

    def test_cleanup_in_custom_destination_removes_only_current_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            destination_dir = base_dir / "Destino"
            task_root = destination_dir / TASK_TEMP_ROOT_NAME
            task_temp_dir = task_root / "tarefa-atual"
            other_task_dir = task_root / "tarefa-outra"
            task_temp_dir.mkdir(parents=True)
            other_task_dir.mkdir()
            (task_temp_dir / "remover.part").touch()
            other_task_file = other_task_dir / "preservar.part"
            destination_file = destination_dir / "preservar.mp4"
            other_task_file.touch()
            destination_file.touch()
            service = DownloadService(base_dir, make_silent_logger())

            result = service._cleanup_cancelled_task_temp(
                task_temp_dir,
                destination_dir.resolve(),
            )

            self.assertEqual(result, (1, 0))
            self.assertFalse(task_temp_dir.exists())
            self.assertTrue(other_task_file.is_file())
            self.assertTrue(destination_file.is_file())

    def test_custom_destination_is_redacted_with_derived_paths(self) -> None:
        base_dir = Path("C:/Aplicativo/EduDownloader")
        destination_dir = Path("D:/Perfil João/Materiais da Educação")
        details = f"falha em {destination_dir / 'temporários' / 'aula.part'}"

        redacted = _redact_sensitive_text(
            details,
            base_dir,
            destination_dir=destination_dir,
        )

        self.assertNotIn(str(destination_dir), redacted)
        self.assertNotIn("Perfil João", redacted)
        self.assertIn("[PASTA DE DESTINO]", redacted)


class FinalOutputContractTests(unittest.TestCase):
    def test_execute_uses_custom_destination_for_relative_output_and_temp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            destination_dir = base_dir / "Destino João"
            destination_dir.mkdir()
            output_file = destination_dir / "Aula final.mp4"
            output_file.touch()
            fake_process = Mock()
            fake_process.stdout = io.StringIO(f"BAIXADOR_ARQUIVO|{output_file.name}\n")
            fake_process.wait.return_value = 0
            service = DownloadService(base_dir, make_silent_logger())

            with patch(
                "downloader.subprocess.Popen",
                return_value=fake_process,
            ) as popen:
                result = service._execute(
                    ["yt-dlp.exe", "URL-de-teste"],
                    destination_dir=destination_dir.resolve(),
                )

            execution_command = popen.call_args.args[0]
            temporary_path = execution_command[
                execution_command.index("--paths") + 1
            ].removeprefix("temp:")
            self.assertEqual(result.final_output_path, output_file.resolve())
            self.assertEqual(result.file_path, result.final_output_path)
            self.assertFalse(popen.call_args.kwargs["shell"])
            self.assertEqual(
                Path(temporary_path).parent,
                destination_dir.resolve() / TASK_TEMP_ROOT_NAME,
            )

    def test_relative_final_path_resolves_against_effective_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            destination_dir = Path(temporary_dir).resolve()
            output_file = destination_dir / "Aula final.mp4"
            output_file.touch()

            final_path = _validate_final_output_path(
                Path(output_file.name),
                destination_dir,
                "saída simulada",
            )

            self.assertEqual(final_path, output_file.resolve())

    def test_absolute_final_path_inside_destination_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            destination_dir = Path(temporary_dir).resolve()
            output_file = destination_dir / "Aula final.mp3"
            output_file.touch()

            final_path = _validate_final_output_path(
                output_file,
                destination_dir,
                "saída simulada",
            )

            self.assertEqual(final_path, output_file.resolve())

    def test_absolute_final_path_outside_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            destination_dir = root / "Destino"
            destination_dir.mkdir()
            outside_file = root / "fora.mp4"
            outside_file.touch()

            with self.assertRaises(DownloadServiceError) as context:
                _validate_final_output_path(
                    outside_file,
                    destination_dir.resolve(),
                    "saída simulada",
                )

            self.assertIn("fora da pasta", context.exception.user_message)

    def test_material_parent_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            destination_dir = root / "Destino"
            destination_dir.mkdir()
            outside_file = root / "fora.mp4"
            outside_file.touch()

            with self.assertRaises(DownloadServiceError):
                _validate_final_output_path(
                    Path("..") / outside_file.name,
                    destination_dir.resolve(),
                    "saída simulada",
                )

    def test_reparse_point_final_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            destination_dir = Path(temporary_dir).resolve()
            output_file = destination_dir / "Aula final.mp4"
            output_file.touch()
            real_stat = os.lstat(output_file)
            reparse_stat = Mock(
                st_mode=real_stat.st_mode,
                st_file_attributes=0x400,
            )

            with (
                patch("downloader.os.lstat", return_value=reparse_stat),
                self.assertRaises(DownloadServiceError) as context,
            ):
                _validate_final_output_path(
                    output_file,
                    destination_dir,
                    "saída simulada",
                )

            self.assertIn("inválido", context.exception.user_message)

    def test_final_output_path_is_authoritative_with_compatibility_alias(self) -> None:
        final_path = Path("C:/Downloads/Aula.mp4")

        result = DownloadResult(final_path, already_existed=False)

        self.assertEqual(result.final_output_path, final_path)
        self.assertIs(result.file_path, result.final_output_path)


class DownloadEventBufferTests(unittest.TestCase):
    def test_progress_storm_keeps_latest_samples_and_all_structural_events(
        self,
    ) -> None:
        events = DownloadEventBuffer()
        for index in range(10_000):
            events.put(
                DownloadEvent(
                    DownloadEventKind.PROGRESS,
                    DownloadProgress(index / 100, index, 10_000, index + 1, None),
                )
            )
        events.put(DownloadEvent(DownloadEventKind.PHASE, DownloadPhase.PROCESSING))
        for index in range(10_000, 20_000):
            events.put(
                DownloadEvent(
                    DownloadEventKind.PROGRESS,
                    DownloadProgress(index / 200, index, 20_000, None, index),
                )
            )
        events.put(DownloadEvent(DownloadEventKind.CANCELLED))

        self.assertEqual(events.qsize(), 4)
        self.assertTrue(events.has_structural_event())
        drained = []
        while not events.empty():
            drained.append(events.get_nowait())

        self.assertEqual(
            [event.kind for event in drained],
            [
                DownloadEventKind.PROGRESS,
                DownloadEventKind.PHASE,
                DownloadEventKind.PROGRESS,
                DownloadEventKind.CANCELLED,
            ],
        )
        self.assertEqual(drained[0].payload.downloaded_bytes, 9_999)
        self.assertEqual(drained[2].payload.downloaded_bytes, 19_999)

    def test_latest_partial_progress_does_not_invent_missing_metrics(self) -> None:
        events = DownloadEventBuffer()
        events.put(
            DownloadEvent(
                DownloadEventKind.PROGRESS,
                DownloadProgress(40, 400, 1_000, 50, 12),
            )
        )
        latest = DownloadProgress(41, 410, None, None, None)
        events.put(DownloadEvent(DownloadEventKind.PROGRESS, latest))

        event = events.get_nowait()

        self.assertIs(event.payload, latest)
        self.assertTrue(events.empty())
        self.assertFalse(events.has_structural_event())

    def test_worker_thread_can_publish_bounded_progress_without_losing_terminal(
        self,
    ) -> None:
        events = DownloadEventBuffer()

        def publish() -> None:
            events.put(DownloadEvent(DownloadEventKind.PHASE, DownloadPhase.PREPARING))
            for index in range(50_000):
                events.put(
                    DownloadEvent(
                        DownloadEventKind.PROGRESS,
                        DownloadProgress(None, index, None, None, None),
                    )
                )
            events.put(DownloadEvent(DownloadEventKind.COMPLETED, "resultado"))

        worker = threading.Thread(target=publish, name="progress-producer")
        worker.start()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(events.qsize(), 3)
        drained = [events.get_nowait() for _ in range(3)]
        self.assertEqual(
            [event.kind for event in drained],
            [
                DownloadEventKind.PHASE,
                DownloadEventKind.PROGRESS,
                DownloadEventKind.COMPLETED,
            ],
        )
        self.assertEqual(drained[1].payload.downloaded_bytes, 49_999)
        self.assertEqual(drained[2].payload, "resultado")


class ProgressAndErrorTests(unittest.TestCase):
    def test_parse_complete_progress_line(self) -> None:
        progress = parse_progress_line("BAIXADOR_PROGRESSO| 25.5%|255|1000|NA|50|15")
        self.assertIsNotNone(progress)
        assert progress is not None
        self.assertEqual(progress.percent, 25.5)
        self.assertEqual(progress.downloaded_bytes, 255)
        self.assertEqual(progress.total_bytes, 1000)
        self.assertEqual(progress.speed, 50)
        self.assertEqual(progress.eta, 15)

    def test_progress_uses_estimated_total_and_rejects_invalid_line(self) -> None:
        progress = parse_progress_line("BAIXADOR_PROGRESSO|NA|250|NA|1000|NA|NA")
        self.assertIsNotNone(progress)
        assert progress is not None
        self.assertEqual(progress.percent, 25)
        self.assertEqual(progress.total_bytes, 1000)
        self.assertIsNone(parse_progress_line("[download] 20%"))
        self.assertIsNone(
            parse_progress_line("BAIXADOR_PROGRESSO|campos|insuficientes")
        )

    def test_error_classification(self) -> None:
        self.assertIn(
            "internet",
            classify_download_error("Unable to download webpage: timed out"),
        )
        self.assertIn(
            "indisponível",
            classify_download_error("ERROR: This video is unavailable"),
        )
        self.assertIn(
            "não é compatível",
            classify_download_error("ERROR: Unsupported URL"),
        )
        self.assertIn("arquivo de log", classify_download_error("falha inesperada"))

    def test_error_classification_includes_permission_space_and_format(self) -> None:
        self.assertIn(
            "espaço livre",
            classify_download_error("ERROR: No space left on device"),
        )
        self.assertIn(
            "permissão",
            classify_download_error("ERROR: Permission denied"),
        )
        self.assertIn(
            "outra qualidade",
            classify_download_error("Requested format is not available"),
        )
        self.assertIn(
            "permissão",
            classify_os_error(PermissionError(errno.EACCES, "negado")),
        )
        self.assertIn(
            "espaço livre",
            classify_os_error(OSError(errno.ENOSPC, "cheio")),
        )

    def test_phases_are_typed_and_based_on_real_tool_output(self) -> None:
        self.assertEqual(
            _phase_from_output("[youtube] Downloading webpage"),
            DownloadPhase.PREPARING,
        )
        self.assertEqual(
            _phase_from_output("[download] 25%"),
            DownloadPhase.DOWNLOADING,
        )
        self.assertEqual(
            _phase_from_output("[Merger] Merging formats"),
            DownloadPhase.PROCESSING,
        )
        for prefix in (
            "[ExtractAudio]",
            "[VideoRemuxer]",
            "[RemuxVideo]",
            "[MoveFiles]",
        ):
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    _phase_from_output(f"{prefix} trabalho simulado"),
                    DownloadPhase.PROCESSING,
                )
        self.assertIsNone(_phase_from_output("linha sem etapa conhecida"))

    def test_execute_reads_progress_without_real_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            output_file = base_dir / "Downloads" / "Aula [id] [720p].mp4"
            output_file.parent.mkdir()
            output_file.touch()
            fake_process = Mock()
            fake_process.stdout = io.StringIO(
                "BAIXADOR_PROGRESSO|50%|500|1000|NA|100|5\n"
                f"BAIXADOR_ARQUIVO|{output_file}\n"
            )
            fake_process.wait.return_value = 0
            service = DownloadService(base_dir, make_silent_logger())
            with patch(
                "downloader.subprocess.Popen", return_value=fake_process
            ) as popen:
                result = service._execute(["yt-dlp.exe", "URL-de-teste"])

        self.assertEqual(result.file_path, output_file.resolve())
        self.assertFalse(result.already_existed)
        self.assertFalse(popen.call_args.kwargs["shell"])
        event = service.events.get_nowait()
        self.assertEqual(event.kind, DownloadEventKind.PROGRESS)

    def test_execute_reports_when_confirmed_file_already_existed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            output_file = base_dir / "Downloads" / "Aula [id] [720p].mp4"
            output_file.parent.mkdir()
            output_file.touch()
            fake_process = Mock()
            fake_process.stdout = io.StringIO(f"BAIXADOR_ARQUIVO|{output_file}\n")
            fake_process.wait.return_value = 0
            service = DownloadService(base_dir, make_silent_logger())

            with patch("downloader.subprocess.Popen", return_value=fake_process):
                result = service._execute(
                    ["yt-dlp.exe", "URL-de-teste"],
                    frozenset({output_file.resolve()}),
                )

        self.assertTrue(result.already_existed)

    def test_zero_exit_without_final_path_is_not_success(self) -> None:
        fake_process = Mock()
        fake_process.stdout = io.StringIO("[download] operação encerrada\n")
        fake_process.wait.return_value = 0

        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            service = DownloadService(base_dir, make_silent_logger())
            with patch("downloader.subprocess.Popen", return_value=fake_process):
                with self.assertRaises(DownloadServiceError) as context:
                    service._execute(["yt-dlp.exe", "URL-de-teste"])
            self.assertFalse((base_dir / "Downloads" / TASK_TEMP_ROOT_NAME).exists())

        self.assertIn("sem informar", context.exception.user_message)

    def test_zero_exit_with_missing_final_file_is_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            missing_file = Path(temporary_dir) / "Downloads" / "ausente.mp4"
            fake_process = Mock()
            fake_process.stdout = io.StringIO(f"BAIXADOR_ARQUIVO|{missing_file}\n")
            fake_process.wait.return_value = 0
            service = DownloadService(Path(temporary_dir), make_silent_logger())

            with patch("downloader.subprocess.Popen", return_value=fake_process):
                with self.assertRaises(DownloadServiceError) as context:
                    service._execute(["yt-dlp.exe", "URL-de-teste"])

        self.assertIn("não foi encontrado", context.exception.user_message)

    def test_execute_turns_process_failure_into_friendly_error(self) -> None:
        fake_process = Mock()
        fake_process.stdout = io.StringIO(
            "ERROR: Unable to download webpage: connection refused\n"
        )
        fake_process.wait.return_value = 1

        with tempfile.TemporaryDirectory() as temporary_dir:
            service = DownloadService(Path(temporary_dir), make_silent_logger())
            with patch("downloader.subprocess.Popen", return_value=fake_process):
                with self.assertRaises(DownloadServiceError) as context:
                    service._execute(["yt-dlp.exe", "URL-de-teste"])

        self.assertIn("internet", context.exception.user_message)

    def test_failed_process_removes_only_empty_task_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            downloads = base_dir / "Downloads"
            other_task = downloads / TASK_TEMP_ROOT_NAME / "tarefa-outra"
            other_task.mkdir(parents=True)
            (other_task / "parcial.part").write_text("preservar", encoding="utf-8")
            fake_process = Mock()
            fake_process.stdout = io.StringIO("ERROR: connection refused\n")
            fake_process.wait.return_value = 1
            service = DownloadService(base_dir, make_silent_logger())

            with patch("downloader.subprocess.Popen", return_value=fake_process):
                with self.assertRaises(DownloadServiceError):
                    service._execute(["yt-dlp.exe", "URL-de-teste"])

            self.assertEqual(
                list((downloads / TASK_TEMP_ROOT_NAME).iterdir()), [other_task]
            )
            self.assertTrue((other_task / "parcial.part").exists())

    def test_start_uses_worker_thread_and_event_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            for filename in REQUIRED_EXECUTABLES:
                (base_dir / filename).touch()
            output_file = base_dir / "Downloads" / "Aula [id] [720p].mp4"
            service = DownloadService(base_dir, make_silent_logger())
            verified = []

            def launch(command, **_kwargs):
                staging = Path(command[command.index("--paths") + 1])
                path = staging / output_file.name
                self.assertEqual(staging.parent.name, TASK_TEMP_ROOT_NAME)
                process = Mock()
                process.stdout = io.StringIO(
                    "BAIXADOR_PROGRESSO|100%|1000|1000|NA|100|0\n"
                    f"BAIXADOR_ARQUIVO|{path}\n"
                )

                def finish():
                    path.write_bytes(b"amostra sintetica de midia")
                    return 0

                process.wait.side_effect = finish
                return process

            def verify(path, _kind):
                self.assertFalse(output_file.exists())
                self.assertTrue(path.is_file())
                verified.append(path)

            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_VIDEO,
                "720p",
            )
            with (
                patch("downloader.subprocess.Popen", side_effect=launch),
                patch.object(service, "_verify_media", side_effect=verify),
                patch.object(service, "_verify_attachment", side_effect=verify),
            ):
                service.start(request)
                deadline = time.monotonic() + 2
                while service.is_running and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(output_file.is_file())
                self.assertEqual(len(verified), 2)
                self.assertEqual(verified[0], verified[1])

        kinds = []
        while not service.events.empty():
            event = service.events.get_nowait()
            kinds.append(event.kind)
            if event.kind == DownloadEventKind.PHASE:
                self.assertIsInstance(event.payload, DownloadPhase)
        self.assertFalse(service.is_running)
        self.assertIn(DownloadEventKind.PHASE, kinds)
        self.assertIn(DownloadEventKind.PROGRESS, kinds)
        self.assertIn(DownloadEventKind.COMPLETED, kinds)

    def test_start_reports_missing_tools_before_creating_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            service = DownloadService(Path(temporary_dir), make_silent_logger())
            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_VIDEO,
                "720p",
            )
            with patch("downloader.threading.Thread") as thread:
                with self.assertRaises(MissingToolsError):
                    service.start(request)
        thread.assert_not_called()

    def test_missing_deno_fails_before_download_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            for filename in REQUIRED_EXECUTABLES:
                if filename != "deno.exe":
                    (base_dir / filename).touch()
            service = DownloadService(base_dir, make_silent_logger())
            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_VIDEO,
                "720p",
            )
            with (
                patch("downloader.threading.Thread") as thread,
                patch("downloader.subprocess.Popen") as popen,
                self.assertRaises(MissingToolsError) as context,
            ):
                service.start(request)

        self.assertIn("deno.exe não foi encontrado", context.exception.user_message)
        thread.assert_not_called()
        popen.assert_not_called()

    def test_thread_start_failure_becomes_friendly_error(self) -> None:
        failed_thread = Mock()
        failed_thread.start.side_effect = RuntimeError("thread indisponível")

        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            for filename in REQUIRED_EXECUTABLES:
                (base_dir / filename).touch()
            service = DownloadService(base_dir, make_silent_logger())
            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_VIDEO,
                "720p",
            )
            with patch("downloader.threading.Thread", return_value=failed_thread):
                with self.assertRaises(DownloadServiceError) as context:
                    service.start(request)

        self.assertIn("processamento", context.exception.user_message)
        self.assertFalse(service.is_running)

    def test_unexpected_read_error_terminates_running_process(self) -> None:
        fake_process = Mock()
        fake_process.stdout = FailingStream()
        fake_process.poll.return_value = None

        with tempfile.TemporaryDirectory() as temporary_dir:
            service = DownloadService(Path(temporary_dir), make_silent_logger())
            with (
                patch("downloader.subprocess.Popen", return_value=fake_process),
                patch.object(service, "_terminate_process_tree") as terminate,
            ):
                with self.assertRaises(OSError):
                    service._execute(["yt-dlp.exe", "URL-de-teste"])

        terminate.assert_called_once_with(fake_process)

    def test_success_at_cancel_boundary_remains_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            service = DownloadService(Path(temporary_dir), make_silent_logger())
            service._cancel_event.set()
            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_VIDEO,
                "720p",
            )
            with patch.object(
                service,
                "_execute",
                return_value=DownloadResult(Path("C:/Downloads/Aula.mp4"), False),
            ):
                service._worker_main(request, ["comando-simulado"])

        kinds = []
        while not service.events.empty():
            kinds.append(service.events.get_nowait().kind)
        self.assertIn(DownloadEventKind.COMPLETED, kinds)
        self.assertNotIn(DownloadEventKind.CANCELLED, kinds)

    def test_zero_exit_code_wins_if_cancel_arrives_after_process_completion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            output_file = base_dir / "Downloads" / "Aula.mp4"
            output_file.parent.mkdir()
            output_file.touch()
            fake_process = Mock()
            fake_process.stdout = io.StringIO(f"BAIXADOR_ARQUIVO|{output_file}\n")
            service = DownloadService(base_dir, make_silent_logger())

            def finish_successfully() -> int:
                service._cancel_event.set()
                return 0

            fake_process.wait.side_effect = finish_successfully
            with patch("downloader.subprocess.Popen", return_value=fake_process):
                result = service._execute(["yt-dlp.exe", "URL-de-teste"])

        self.assertEqual(result.file_path, output_file.resolve())

    def test_cancel_uses_windows_process_tree(self) -> None:
        fake_process = Mock()
        fake_process.pid = 4321
        fake_process.poll.side_effect = [None, None]

        with (
            patch("downloader.os.name", "nt"),
            patch("downloader.subprocess.run") as run,
        ):
            DownloadService._terminate_process_tree(fake_process)

        command = run.call_args.args[0]
        self.assertEqual(command, ["taskkill", "/PID", "4321", "/T", "/F"])
        fake_process.kill.assert_called_once()

    def test_taskkill_failure_falls_back_to_owned_parent(self) -> None:
        fake_process = Mock()
        fake_process.pid = 4321
        fake_process.poll.side_effect = [None, None]
        with (
            patch("downloader.os.name", "nt"),
            patch("downloader.subprocess.run", side_effect=OSError("falha")) as run,
        ):
            DownloadService._terminate_process_tree(fake_process)

        self.assertEqual(
            run.call_args.args[0], ["taskkill", "/PID", "4321", "/T", "/F"]
        )
        fake_process.kill.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows process ownership")
    def test_failed_parent_does_not_leave_its_child_running(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            pid_file = base_dir / "owned-child.pid"
            parent_code = (
                "import pathlib,subprocess,sys;"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],"
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL,close_fds=True);"
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid));"
                "print('ERROR: controlled failure')"
            )
            service = DownloadService(base_dir, make_silent_logger())
            child_pid: int | None = None
            try:
                with self.assertRaises(DownloadServiceError):
                    service._execute(
                        [sys.executable, "-c", parent_code, str(pid_file), "test-url"]
                    )
                child_pid = int(pid_file.read_text(encoding="utf-8"))
                handle = ctypes.windll.kernel32.OpenProcess(
                    0x00100000, False, child_pid
                )
                if handle:
                    try:
                        self.assertEqual(
                            ctypes.windll.kernel32.WaitForSingleObject(handle, 2000), 0
                        )
                    finally:
                        ctypes.windll.kernel32.CloseHandle(handle)
            finally:
                if child_pid is not None:
                    subprocess.run(
                        ["taskkill", "/PID", str(child_pid), "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )

    @unittest.skipUnless(os.name == "nt", "Windows process ownership")
    def test_zero_exit_with_owned_child_is_not_download_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            output = base_dir / "Downloads" / "ready.mp4"
            output.parent.mkdir()
            output.write_bytes(b"fixture")
            pid_file = base_dir / "owned-child.pid"
            parent_code = (
                "import pathlib,subprocess,sys;"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],"
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL,close_fds=True);"
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid));"
                "print('BAIXADOR_ARQUIVO|'+sys.argv[2])"
            )
            service = DownloadService(base_dir, make_silent_logger())
            child_pid: int | None = None
            try:
                with self.assertRaises(DownloadServiceError) as context:
                    service._execute(
                        [
                            sys.executable,
                            "-c",
                            parent_code,
                            str(pid_file),
                            str(output),
                            "test-url",
                        ]
                    )
                self.assertIn("processos auxiliares", context.exception.user_message)
                child_pid = int(pid_file.read_text(encoding="utf-8"))
                handle = ctypes.windll.kernel32.OpenProcess(
                    0x00100000, False, child_pid
                )
                if handle:
                    try:
                        self.assertEqual(
                            ctypes.windll.kernel32.WaitForSingleObject(handle, 2000), 0
                        )
                    finally:
                        ctypes.windll.kernel32.CloseHandle(handle)
                self.assertEqual(output.read_bytes(), b"fixture")
            finally:
                if child_pid is not None:
                    subprocess.run(
                        ["taskkill", "/PID", str(child_pid), "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )

    @unittest.skipUnless(os.name == "nt", "Windows process ownership")
    def test_cancel_stops_owned_tree_without_stopping_unrelated_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            pid_file = base_dir / "owned-child.pid"
            parent_code = (
                "import pathlib,subprocess,sys,time;"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],"
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL,close_fds=True);"
                "pid_path=pathlib.Path(sys.argv[1]);"
                "pending=pid_path.with_suffix('.pending');"
                "pending.write_text(str(child.pid));pending.replace(pid_path);"
                "print('READY',flush=True);time.sleep(20)"
            )
            unrelated = subprocess.Popen(
                [sys.executable, "-c", "import time;time.sleep(20)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            service = DownloadService(base_dir, make_silent_logger())
            child_pid: int | None = None
            worker = threading.Thread(
                target=service._worker_main,
                args=(
                    DownloadRequest("test-url", CONTENT_TYPE_VIDEO, "Melhor qualidade"),
                    [sys.executable, "-c", parent_code, str(pid_file), "test-url"],
                ),
            )
            try:
                with service._lock:
                    service._worker = worker
                    service._running = True
                worker.start()
                deadline = time.monotonic() + 5
                while not pid_file.exists() and time.monotonic() < deadline:
                    threading.Event().wait(0.02)
                self.assertTrue(pid_file.exists())
                child_pid = int(pid_file.read_text(encoding="utf-8"))
                self.assertTrue(service.cancel())
                self.assertTrue(service.cancel())
                service.shutdown(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertIsNone(unrelated.poll())
                handle = ctypes.windll.kernel32.OpenProcess(
                    0x00100000, False, child_pid
                )
                if handle:
                    try:
                        self.assertEqual(
                            ctypes.windll.kernel32.WaitForSingleObject(handle, 2000), 0
                        )
                    finally:
                        ctypes.windll.kernel32.CloseHandle(handle)
                self.assertFalse(
                    (base_dir / "Downloads" / TASK_TEMP_ROOT_NAME).exists()
                )
            finally:
                if child_pid is not None:
                    subprocess.run(
                        ["taskkill", "/PID", str(child_pid), "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                with service._lock:
                    owned = service._process
                if owned is not None and owned.poll() is None:
                    DownloadService._terminate_process_tree(owned)
                unrelated.terminate()
                unrelated.wait(timeout=5)

    def test_cancel_removes_only_new_task_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            downloads_dir = base_dir / "Downloads"
            task_temp_dir = downloads_dir / TASK_TEMP_ROOT_NAME / "tarefa-atual"
            fragment_dir = task_temp_dir / "fragmentos"
            fragment_dir.mkdir(parents=True)
            temporary_names = (
                "Aula.mp4.part",
                "Aula.mp4.ytdl",
                "Aula.f137.mp4.part-Frag12",
            )
            for name in temporary_names:
                (task_temp_dir / name).write_text("temporário", encoding="utf-8")
            (fragment_dir / "fragmento.tmp").write_text("fragmento", encoding="utf-8")

            service = DownloadService(base_dir, make_silent_logger())
            fake_process = Mock()
            fake_process.stdout = io.StringIO("[download] cancelado\n")

            def finish_cancelled() -> int:
                service._cancel_event.set()
                return 1

            fake_process.wait.side_effect = finish_cancelled
            with (
                patch(
                    "downloader.subprocess.Popen", return_value=fake_process
                ) as popen,
                patch.object(
                    service, "_create_task_temp_dir", return_value=task_temp_dir
                ),
            ):
                with self.assertRaises(DownloadCancelledError):
                    service._execute(["yt-dlp.exe", "URL-de-teste"])

            executed_command = popen.call_args.args[0]
            self.assertIn("--paths", executed_command)
            self.assertIn(f"temp:{task_temp_dir}", executed_command)
            self.assertFalse(task_temp_dir.exists())

    def test_cancel_preserves_preexisting_and_other_download_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            downloads_dir = base_dir / "Downloads"
            temp_root = downloads_dir / TASK_TEMP_ROOT_NAME
            task_temp_dir = temp_root / "tarefa-atual"
            other_task_dir = temp_root / "tarefa-outra"
            task_temp_dir.mkdir(parents=True)
            other_task_dir.mkdir()

            preexisting_part = downloads_dir / "Aula antiga.mp4.part"
            unrelated_part = downloads_dir / "Outro download.mp4.part"
            other_task_part = other_task_dir / "Outro download.mp4.part"
            final_mp4 = downloads_dir / "Aula pronta.mp4"
            final_mp3 = downloads_dir / "Áudio pronto.mp3"
            for path in (preexisting_part, final_mp4, final_mp3, other_task_part):
                path.write_text("preservar", encoding="utf-8")
            (task_temp_dir / "Aula atual.mp4.part").write_text(
                "remover", encoding="utf-8"
            )

            service = DownloadService(base_dir, make_silent_logger())
            fake_process = Mock()
            fake_process.stdout = io.StringIO("[download] cancelado\n")

            def finish_cancelled() -> int:
                unrelated_part.write_text("outro processo", encoding="utf-8")
                service._cancel_event.set()
                return 1

            fake_process.wait.side_effect = finish_cancelled
            with (
                patch("downloader.subprocess.Popen", return_value=fake_process),
                patch.object(
                    service, "_create_task_temp_dir", return_value=task_temp_dir
                ),
            ):
                with self.assertRaises(DownloadCancelledError):
                    service._execute(
                        ["yt-dlp.exe", "URL-de-teste"],
                        frozenset({preexisting_part.resolve()}),
                    )

            self.assertTrue(preexisting_part.is_file())
            self.assertTrue(unrelated_part.is_file())
            self.assertTrue(other_task_part.is_file())
            self.assertTrue(final_mp4.is_file())
            self.assertTrue(final_mp3.is_file())
            self.assertFalse(task_temp_dir.exists())

    def test_cancel_waits_for_process_tree_before_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            task_temp_dir = (
                base_dir / "Downloads" / TASK_TEMP_ROOT_NAME / "tarefa-atual"
            )
            task_temp_dir.mkdir(parents=True)
            (task_temp_dir / "Aula.mp4.part").touch()
            service = DownloadService(base_dir, make_silent_logger())
            fake_process = Mock()
            fake_process.stdout = io.StringIO("[download] cancelado\n")

            def finish_cancelled() -> int:
                service._cancel_event.set()
                return 1

            fake_process.wait.side_effect = finish_cancelled
            order: list[str] = []
            with (
                patch("downloader.subprocess.Popen", return_value=fake_process),
                patch.object(
                    service, "_create_task_temp_dir", return_value=task_temp_dir
                ),
                patch.object(
                    service,
                    "_wait_for_process_tree_shutdown",
                    side_effect=lambda: order.append("encerramento") or True,
                ),
                patch.object(
                    service,
                    "_cleanup_cancelled_task_temp",
                    side_effect=lambda path, destination=None: (
                        order.append("limpeza") or (1, 0)
                    ),
                ),
            ):
                with self.assertRaises(DownloadCancelledError):
                    service._execute(["yt-dlp.exe", "URL-de-teste"])

            self.assertEqual(order, ["encerramento", "limpeza"])

    def test_cleanup_failure_keeps_cancelled_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            task_temp_dir = (
                base_dir / "Downloads" / TASK_TEMP_ROOT_NAME / "tarefa-atual"
            )
            task_temp_dir.mkdir(parents=True)
            service = DownloadService(base_dir, make_silent_logger())
            fake_process = Mock()
            fake_process.stdout = io.StringIO("[download] cancelado\n")

            def finish_cancelled() -> int:
                service._cancel_event.set()
                return 1

            fake_process.wait.side_effect = finish_cancelled
            with (
                patch("downloader.subprocess.Popen", return_value=fake_process),
                patch.object(
                    service, "_create_task_temp_dir", return_value=task_temp_dir
                ),
                patch.object(
                    service,
                    "_cleanup_cancelled_task_temp",
                    return_value=(0, 1),
                ),
            ):
                with self.assertRaises(DownloadCancelledError):
                    service._execute(["yt-dlp.exe", "URL-de-teste"])

    def test_cleanup_log_does_not_expose_paths_or_filenames(self) -> None:
        stream = io.StringIO()
        logger = logging.getLogger("edudownloader.tests.cancel.cleanup")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.addHandler(logging.StreamHandler(stream))
        logger.propagate = False

        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            task_temp_dir = (
                base_dir / "Downloads" / TASK_TEMP_ROOT_NAME / "tarefa-atual"
            )
            task_temp_dir.mkdir(parents=True)
            private_name = "Nome privado de aula.mp4.part"
            (task_temp_dir / private_name).touch()
            service = DownloadService(base_dir, logger)

            removed, failures = service._cleanup_cancelled_task_temp(task_temp_dir)

        log_content = stream.getvalue()
        self.assertEqual((removed, failures), (1, 0))
        self.assertIn("temporários removidos=1", log_content)
        self.assertIn("falhas=0", log_content)
        self.assertNotIn(private_name, log_content)
        self.assertNotIn(str(base_dir), log_content)

    def test_completed_mp4_and_mp3_outputs_remain_intact(self) -> None:
        for extension in ("mp4", "mp3"):
            with self.subTest(extension=extension):
                with tempfile.TemporaryDirectory() as temporary_dir:
                    base_dir = Path(temporary_dir)
                    downloads_dir = base_dir / "Downloads"
                    downloads_dir.mkdir()
                    output_file = downloads_dir / f"Aula concluída.{extension}"
                    output_file.write_text("arquivo final", encoding="utf-8")
                    task_temp_dir = downloads_dir / TASK_TEMP_ROOT_NAME / "tarefa-atual"
                    task_temp_dir.mkdir(parents=True)
                    fake_process = Mock()
                    fake_process.stdout = io.StringIO(
                        f"BAIXADOR_ARQUIVO|{output_file}\n"
                    )
                    fake_process.wait.return_value = 0
                    service = DownloadService(base_dir, make_silent_logger())

                    with (
                        patch("downloader.subprocess.Popen", return_value=fake_process),
                        patch.object(
                            service,
                            "_create_task_temp_dir",
                            return_value=task_temp_dir,
                        ),
                    ):
                        result = service._execute(["yt-dlp.exe", "URL-de-teste"])

                    self.assertEqual(result.file_path, output_file.resolve())
                    self.assertTrue(output_file.is_file())
                    self.assertFalse(task_temp_dir.exists())

    def test_log_redaction_removes_urls(self) -> None:
        base_dir = Path("C:/Users/Professora/EduDownloader")
        details = (
            "Erro em C:/Users/Professora/EduDownloader/Downloads ao acessar "
            "https://example.com/aula?token=segredo"
        )
        redacted = _redact_sensitive_text(details, base_dir)
        self.assertNotIn("https://", redacted)
        self.assertNotIn("segredo", redacted)
        self.assertNotIn("Professora", redacted)
        self.assertIn("[URL removida]", redacted)
        self.assertIn("[PASTA DO APLICATIVO]", redacted)

    def test_worker_log_redacts_original_url_derivatives_and_personal_paths(
        self,
    ) -> None:
        stream = io.StringIO()
        logger = logging.getLogger("edudownloader.tests.privacy.derivatives")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.addHandler(logging.StreamHandler(stream))
        logger.propagate = False
        source_url = "https://127.0.0.1:1/aula?token=MARCADOR-PRIVACIDADE-09&modo=teste"

        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            details = "\n".join(
                (
                    f"[generic] Extracting URL: {source_url}",
                    "ERROR: Unable to download webpage: aula?"
                    "token=MARCADOR-PRIVACIDADE-09&modo=teste",
                    "HTTPSConnection(host='127.0.0.1', port=1): Max retries "
                    "exceeded with url: /aula?token=MARCADOR-PRIVACIDADE-09"
                    "&modo=teste (Caused by NewConnectionError("
                    "'[WinError 10061] connection refused; timed out'))",
                    "retry metadata: token=MARCADOR-PRIVACIDADE-09; modo=teste",
                    f"temporario em {base_dir / 'Downloads' / 'aula.part'}",
                    "cache em C:\\Users\\Professora Particular\\Documents\\aula.tmp",
                )
            )
            service = DownloadService(base_dir, logger)
            request = DownloadRequest(
                source_url,
                CONTENT_TYPE_VIDEO,
                "720p",
            )
            with (
                patch.object(
                    service,
                    "_execute",
                    side_effect=DownloadServiceError(
                        "Não foi possível acessar a internet.", details
                    ),
                ),
                patch("downloader.time.monotonic", side_effect=[10.0, 12.0]),
            ):
                service._worker_main(request, ["comando-simulado"])

        log_content = stream.getvalue()
        for sensitive in (
            source_url,
            "127.0.0.1",
            "aula?",
            "token=",
            "modo=teste",
            "MARCADOR-PRIVACIDADE-09",
            str(base_dir),
            "C:\\Users\\Professora Particular",
        ):
            self.assertNotIn(sensitive, log_content)
        for diagnostic in (
            "HTTPSConnection",
            "NewConnectionError",
            "WinError 10061",
            "connection refused",
            "timed out",
        ):
            self.assertIn(diagnostic, log_content)
        for replacement in (
            "[URL removida]",
            "[ENDPOINT DA URL removido]",
            "[DADOS DA URL removidos]",
            "[PORTA removida]",
            "[PASTA DO APLICATIVO]",
            "[PERFIL DO USUÁRIO]",
        ):
            self.assertIn(replacement, log_content)

    def test_log_redaction_removes_decoded_unicode_url_artifacts(self) -> None:
        source_url = (
            "https://example.test/aula%20de%20matem%C3%A1tica?"
            "token=segredo%20%C3%A1&tema=revis%C3%A3o"
        )
        details = (
            "ConnectionError para host='example.test' em aula de matemática?"
            "token=segredo á&tema=revisão; UnicodeDecodeError preservado"
        )

        redacted = _redact_sensitive_text(details, source_url=source_url)

        for sensitive in (
            "example.test",
            "aula de matemática",
            "segredo á",
            "revisão",
        ):
            self.assertNotIn(sensitive, redacted)
        self.assertIn("ConnectionError", redacted)
        self.assertIn("UnicodeDecodeError preservado", redacted)

    def test_worker_log_uses_filename_only_and_audio_quality(self) -> None:
        stream = io.StringIO()
        logger = logging.getLogger("edudownloader.tests.privacy")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.addHandler(logging.StreamHandler(stream))
        logger.propagate = False

        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            service = DownloadService(base_dir, logger)
            request = DownloadRequest(
                "https://example.com/audio",
                CONTENT_TYPE_AUDIO,
                "720p",
            )
            file_path = base_dir / "Downloads" / "Aula.mp3"
            result = DownloadResult(file_path, False)
            with (
                patch.object(service, "_execute", return_value=result),
                patch("downloader.time.monotonic", side_effect=[10.0, 12.5]),
            ):
                service._worker_main(request, ["comando-simulado"])

        log_content = stream.getvalue()
        self.assertIn("MP3 Padrão — 192 kbps", log_content)
        self.assertIn("Aula.mp3", log_content)
        self.assertIn("duração=2.50s", log_content)
        self.assertNotIn(str(base_dir), log_content)

    def test_cancelled_worker_logs_duration(self) -> None:
        stream = io.StringIO()
        logger = logging.getLogger("edudownloader.tests.cancel.duration")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.addHandler(logging.StreamHandler(stream))
        logger.propagate = False

        with tempfile.TemporaryDirectory() as temporary_dir:
            service = DownloadService(Path(temporary_dir), logger)
            request = DownloadRequest(
                "https://example.com/aula",
                CONTENT_TYPE_AUDIO,
                "720p",
                mp3_quality=Mp3Quality.HIGH,
            )
            with (
                patch.object(
                    service,
                    "_execute",
                    side_effect=DownloadCancelledError("cancelado"),
                ),
                patch("downloader.time.monotonic", side_effect=[20.0, 21.25]),
            ):
                service._worker_main(request, ["comando-simulado"])

        log_content = stream.getvalue()
        self.assertIn("MP3 Alta — 320 kbps", log_content)
        self.assertIn("resultado=cancelado", log_content)
        self.assertIn("duração=1.25s", log_content)

    def test_logger_failure_does_not_prevent_service_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            with patch(
                "downloader.RotatingFileHandler",
                side_effect=PermissionError("sem permissão"),
            ):
                service = DownloadService(Path(temporary_dir))
            self.assertTrue(
                any(
                    isinstance(handler, logging.NullHandler)
                    for handler in service._logger.handlers
                )
            )
            service.close()

    def test_logger_uses_bounded_utf8_rotation_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            service = DownloadService(Path(temporary_dir))
            handlers = [
                handler
                for handler in service._logger.handlers
                if isinstance(handler, RotatingFileHandler)
            ]
            self.assertEqual(len(handlers), 1)
            handler = handlers[0]
            self.assertEqual(handler.maxBytes, LOG_MAX_BYTES)
            self.assertEqual(handler.backupCount, LOG_BACKUP_COUNT)
            self.assertEqual(handler.encoding.lower().replace("-", ""), "utf8")
            self.assertEqual(
                handler.formatter._fmt,
                "%(asctime)s | %(levelname)s | %(message)s",
            )
            service.close()

    def test_rotation_limits_backups_without_weakening_redaction(self) -> None:
        source_url = "https://127.0.0.1:1/aula?token=MARCADOR-RETENCAO-095&modo=privado"
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_dir = Path(temporary_dir)
            service = DownloadService(base_dir)
            handler = next(
                handler
                for handler in service._logger.handlers
                if isinstance(handler, RotatingFileHandler)
            )
            handler.maxBytes = 512
            details = (
                f"Erro em {base_dir / 'Downloads' / 'aula.part'}; "
                f"URL={source_url}; host='127.0.0.1'; "
                "aula?token=MARCADOR-RETENCAO-095&modo=privado; "
                "perfil=C:\\Users\\Professora Particular\\Documents"
            )
            safe_details = _redact_sensitive_text(
                details,
                base_dir,
                source_url,
            )
            for index in range(24):
                service._logger.error(
                    "Falha sintética %02d | detalhes=%s",
                    index,
                    safe_details,
                )
            handler.flush()
            log_files = sorted((base_dir / "Logs").glob("edudownloader.log*"))
            combined = "\n".join(path.read_text(encoding="utf-8") for path in log_files)
            total_size = sum(path.stat().st_size for path in log_files)
            service.close()

        self.assertEqual(
            {path.name for path in log_files},
            {"edudownloader.log", "edudownloader.log.1", "edudownloader.log.2"},
        )
        self.assertLess(total_size, 4096)
        for sensitive in (
            source_url,
            "127.0.0.1",
            "aula?",
            "token=",
            "modo=privado",
            "MARCADOR-RETENCAO-095",
            str(base_dir),
            "C:\\Users\\Professora Particular",
            "activation.dat",
            ".edulic",
        ):
            self.assertNotIn(sensitive, combined)
        for replacement in (
            "[URL removida]",
            "[ENDPOINT DA URL removido]",
            "[DADOS DA URL removidos]",
            "[PASTA DO APLICATIVO]",
            "[PERFIL DO USUÁRIO]",
        ):
            self.assertIn(replacement, combined)

    def test_close_releases_owned_log_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            service = DownloadService(Path(temporary_dir))
            self.assertTrue(service._logger.handlers)
            service.close()
            self.assertFalse(service._logger.handlers)

    def test_close_releases_handler_even_if_flush_fails(self) -> None:
        logger = Mock()
        handler = Mock()
        handler.flush.side_effect = OSError("pendrive removido")
        logger.handlers = [handler]

        with tempfile.TemporaryDirectory() as temporary_dir:
            service = DownloadService(Path(temporary_dir), make_silent_logger())
            service._owns_logger = True
            service._logger = logger
            with patch.object(service, "shutdown"):
                service.close()

        handler.close.assert_called_once()
        logger.removeHandler.assert_called_once_with(handler)


class SensitiveTextCollisionTests(unittest.TestCase):
    def test_nested_paths_are_protected_before_url_fragments_in_all_spellings(self):
        parent = Path("C:/Users/Professora São/testes-publicacao")
        child = parent / "PrivateApp"
        url = "https://example.test/aula?modo=teste&token=PrivateApp&nome=Professora"
        for base, destination in ((parent, child), (child, parent)):
            for spelling in ("native", "forward", "mixed", "escaped", "lowercase"):
                with self.subTest(base=base, spelling=spelling):

                    def render(path):
                        value = str(path)
                        if spelling == "forward":
                            return value.replace("\\", "/")
                        if spelling == "mixed":
                            return value.replace("\\", "/", 2)
                        if spelling == "escaped":
                            return value.replace("\\", "\\\\")
                        return value.lower() if spelling == "lowercase" else value

                    text = f"app={render(base)}/settings.json\ndest={render(destination)}/output.mp3\n{url}"
                    result = _redact_sensitive_text(text, base, url, destination)
                    for secret in (
                        "Professora",
                        "testes-publicacao",
                        "PrivateApp",
                        "example.test",
                        "modo=teste",
                    ):
                        self.assertNotIn(secret.casefold(), result.casefold())
                    self.assertIn("[PASTA DO APLICATIVO]", result)
                    self.assertIn("[PASTA DE DESTINO]", result)
                    self.assertIn("[URL removida]", result)

    def test_unknown_personal_profile_survives_colliding_user_and_users_tokens(self):
        for separator in ("\\", "/", "\\\\"):
            with self.subTest(separator=separator):
                path = separator.join(
                    ("C:", "Users", "Usuário com Espaços", "Documents", "arquivo.tmp")
                )
                url = "https://example.test/aula?token=Users&nome=Usu%C3%A1rio%20com%20Espa%C3%A7os"
                result = _redact_sensitive_text(path, source_url=url)
                self.assertIn("[PERFIL DO USUÁRIO]", result)
                self.assertNotIn("Usuário", result)
                self.assertNotIn("C:", result)

    def test_unknown_windows_profiles_allow_apostrophes_and_unicode(self):
        from urllib.parse import quote

        for name in ("O'ConnorPrivate", "Usuário d'Ávila com Espaços"):
            for separator in ("/", "\\", "\\\\"):
                with self.subTest(name=name, separator=separator):
                    path = separator.join(
                        ("C:", "Users", name, "Documents", "fixture.tmp")
                    )
                    url = "https://example.test/a?token=Users&name=" + quote(
                        name, safe=""
                    )
                    result = _redact_sensitive_text(f'cache "{path}"', source_url=url)
                    self.assertIn("[PERFIL DO USUÁRIO]", result)
                    self.assertNotIn(name, result)
                    self.assertNotIn("C:", result)

    def test_url_values_cannot_reprocess_inserted_path_or_endpoint_markers(self):
        base = Path("C:/Users/Synthetic/app")
        url = "https://URL/aula?token=PASTA&other=ENDPOINT&x=removidos"
        result = _redact_sensitive_text(
            f"{base}/log.txt {url} host='URL' token=PASTA", base, url
        )
        for marker in (
            "[PASTA DO APLICATIVO]",
            "[URL removida]",
            "[ENDPOINT DA URL removido]",
            "[DADOS DA URL removidos]",
        ):
            self.assertIn(marker, result)
        self.assertNotIn("token=", result)

    def test_encoded_and_decoded_url_credentials_and_parameters_are_redacted(self):
        url = "https://Usu%C3%A1rio:Senha%20Privada@example.test/aula?token=MARCADOR"
        text = f"ConnectionError {url} username=Usuário password=Senha Privada encoded=Senha%20Privada token=MARCADOR"
        result = _redact_sensitive_text(text, source_url=url)
        for secret in (
            "Usuário",
            "Usu%C3%A1rio",
            "Senha Privada",
            "Senha%20Privada",
            "MARCADOR",
            "example.test",
        ):
            self.assertNotIn(secret, result)
        self.assertIn("ConnectionError", result)

    def test_detached_encoded_query_names_and_values_are_redacted(self):
        raw_name = "Chave%2BPrivada+Nome"
        raw_value = "Valor%2BSecreto+Exclusivo"
        url = f"https://example.test/aula?{raw_name}={raw_value}"
        fragments = (
            raw_name,
            raw_value,
            "Chave+Privada+Nome",
            "Valor+Secreto+Exclusivo",
            "Chave+Privada Nome",
            "Valor+Secreto Exclusivo",
        )
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertEqual(
                    _redact_sensitive_text(
                        f"ConnectionError {fragment}", source_url=url
                    ),
                    "ConnectionError [DADOS DA URL removidos]",
                )

    def test_url_tokens_and_credentials_crossing_paths_are_removed_in_full(self):
        from urllib.parse import quote

        base = Path("C:/Users/Synthetic/App")
        secret = "PREFIX-SECRET-" + base.as_posix() + "-SUFFIX-SECRET"
        for kind in ("token", "password", "parameter-name"):
            encoded = quote(secret, safe="")
            if kind == "password":
                url = f"https://synthetic:{encoded}@example.test/a"
            elif kind == "parameter-name":
                url = f"https://example.test/a?{encoded}=value"
            else:
                url = f"https://example.test/a?token={encoded}"
            with self.subTest(kind=kind):
                result = _redact_sensitive_text(secret, base, url)
                for fragment in ("PREFIX-SECRET", "SUFFIX-SECRET", "Synthetic", "App"):
                    self.assertNotIn(fragment, result)
                self.assertIn("[PASTA DO APLICATIVO]", result)
                full_url = _redact_sensitive_text(url, base, url)
                self.assertEqual(full_url, "[URL removida]")

    def test_intersecting_matches_and_repeated_token_overlaps_are_unioned(self):
        from urllib.parse import quote

        base = Path("C:/Users/Synthetic/LEFT")
        secret = "LEFT/MIDDLE/RIGHT"
        url = "https://example.test/a?token=" + quote(secret, safe="")
        result = _redact_sensitive_text(base.as_posix() + "/MIDDLE/RIGHT", base, url)
        self.assertEqual(result, "[PASTA DO APLICATIVO]")
        result = _redact_sensitive_text(
            "AAAAAA", source_url="https://example.test/a?token=AAAA"
        )
        self.assertEqual(result, "[DADOS DA URL removidos]")

    def test_real_temporary_names_do_not_change_path_redaction(self):
        for name in ("testes-publicacao", "ação com espaços", "Professora", "PASTA"):
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory(prefix=name) as temp,
            ):
                base = Path(temp)
                url = "https://example.test/aula?modo=teste&nome=Professora&token=PASTA"
                result = _redact_sensitive_text(
                    f"temporary={base}/Downloads/aula.part {url}", base, url
                )
                self.assertIn("[PASTA DO APLICATIVO]", result)
                self.assertNotIn(str(base), result)
                self.assertNotIn(str(base.name), result)


if __name__ == "__main__":
    unittest.main()
