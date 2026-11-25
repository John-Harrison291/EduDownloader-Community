"""Testes da conversão local e segura de vídeo para MP3."""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from media_tools import (
    FFPROBE_TIMEOUT_SECONDS,
    MP3_SEGMENT_DURATION_TOLERANCE_SECONDS,
    MediaConversionProgress,
    MediaOperationCancelled,
    MediaToolPaths,
    MediaToolsError,
    MediaToolsService,
    build_mp3_probe_command,
    build_video_probe_command,
    build_video_to_mp3_command,
    locate_media_tools,
    _progress_seconds,
    _validate_video_probe,
)
from mp3_quality import DEFAULT_MP3_QUALITY, MP3_QUALITY_OPTIONS, Mp3Quality


class ControlledProcess:
    """Popen determinístico para testar ownership sem executar binários reais."""

    def __init__(
        self,
        command: list[str],
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        block: bool = False,
        finish_on_terminate: bool = True,
        finish_on_kill: bool = True,
        wait_timeouts: int = 0,
        before_finish: Callable[[ControlledProcess], None] | None = None,
        terminate_hook: Callable[[ControlledProcess], None] | None = None,
    ) -> None:
        self.command = command
        self.stdout_text = stdout
        self.stderr_text = stderr
        self.completed_returncode = returncode
        self.block = block
        self.finish_on_terminate = finish_on_terminate
        self.finish_on_kill = finish_on_kill
        self.wait_timeouts = wait_timeouts
        self.before_finish = before_finish
        self.terminate_hook = terminate_hook
        self.returncode: int | None = None
        self.communicate_started = threading.Event()
        self.release_communicate = threading.Event()
        self.communicate_timeouts: list[float | None] = []
        self.wait_calls: list[float | None] = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.communicate_timeouts.append(timeout)
        self.communicate_started.set()
        if self.before_finish is not None:
            self.before_finish(self)
        if self.block and not self.release_communicate.wait(5):
            raise AssertionError("O teste não liberou o processo controlado.")
        if self.returncode is None:
            self.returncode = self.completed_returncode
        return self.stdout_text, self.stderr_text

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.terminate_hook is not None:
            self.terminate_hook(self)
        elif self.finish_on_terminate:
            self.force_finish(-15)

    def kill(self) -> None:
        self.kill_calls += 1
        if self.finish_on_kill:
            self.force_finish(-9)

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.wait_timeouts:
            self.wait_timeouts -= 1
            raise subprocess.TimeoutExpired(self.command, timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.command, timeout)
        return self.returncode

    def force_finish(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.release_communicate.set()


class MediaCommandTests(unittest.TestCase):
    def test_tool_discovery_reuses_portable_application_directory(self) -> None:
        base = Path("C:/Programa Portátil")

        tools = locate_media_tools(base)

        self.assertEqual(tools.ffmpeg, base / "ffmpeg.exe")
        self.assertEqual(tools.ffprobe, base / "ffprobe.exe")

    def test_ffmpeg_command_extracts_only_audio_at_192_kbps(self) -> None:
        tools = MediaToolPaths(Path("C:/App/ffmpeg.exe"), Path("C:/App/ffprobe.exe"))
        source = Path("C:/Aulas com espaço/vídeo ção.mp4")
        output = Path("C:/Saída com espaço/.vídeo.tmp.mp3")

        command = build_video_to_mp3_command(tools, source, output)

        self.assertEqual(command[0], str(tools.ffmpeg))
        self.assertEqual(command[command.index("-i") + 1], str(source))
        self.assertEqual(command[command.index("-map") + 1], "0:a:0")
        self.assertIn("-vn", command)
        self.assertEqual(command[command.index("-c:a") + 1], "libmp3lame")
        self.assertEqual(
            command[command.index("-b:a") + 1],
            DEFAULT_MP3_QUALITY.bitrate_argument,
        )
        self.assertEqual(command[-1], str(output))
        self.assertNotIn(str(source), " ".join(command[: command.index("-i")]))

    def test_ffprobe_command_requests_structured_stream_and_duration_data(self) -> None:
        tools = MediaToolPaths(Path("ffmpeg.exe"), Path("ffprobe.exe"))

        command = build_mp3_probe_command(tools, Path("resultado.mp3"))

        self.assertEqual(command[0], str(tools.ffprobe))
        self.assertEqual(command[command.index("-of") + 1], "json")
        self.assertIn("stream=codec_type,duration:format=duration", command)

    def test_each_canonical_profile_controls_only_final_ffmpeg_bitrate(self) -> None:
        tools = MediaToolPaths(Path("ffmpeg.exe"), Path("ffprobe.exe"))
        source = Path("C:/Aulas com espaço/vídeo ção.mp4")
        output = Path("C:/Saída com espaço/áudio.tmp.mp3")
        for profile in MP3_QUALITY_OPTIONS:
            with self.subTest(profile=profile):
                command = build_video_to_mp3_command(
                    tools, source, output, profile, report_progress=True
                )
                self.assertEqual(
                    command[command.index("-b:a") + 1], profile.bitrate_argument
                )
                self.assertEqual(command[command.index("-map") + 1], "0:a:0")
                self.assertEqual(command[command.index("-c:a") + 1], "libmp3lame")
                self.assertIn("-vn", command)
                self.assertEqual(command[command.index("-progress") + 1], "pipe:1")
                self.assertEqual(command.count("-b:a"), 1)
        with self.assertRaises(ValueError):
            build_video_to_mp3_command(tools, source, output, "500k")

    def test_source_probe_and_stable_progress_protocol(self) -> None:
        tools = MediaToolPaths(Path("ffmpeg.exe"), Path("ffprobe.exe"))
        self.assertEqual(build_video_probe_command(tools, Path("a.mp4"))[-1], "a.mp4")
        payload = json.dumps(
            {"streams": [{"codec_type": "audio"}], "format": {"duration": "2.5"}}
        )
        probe = subprocess.CompletedProcess([], 0, payload, "")
        self.assertEqual(_validate_video_probe(probe), 2.5)
        self.assertIsNone(
            _validate_video_probe(
                subprocess.CompletedProcess(
                    [], 0, '{"streams":[{"codec_type":"audio"}]}', ""
                )
            )
        )
        with self.assertRaisesRegex(MediaToolsError, "não possui uma faixa"):
            _validate_video_probe(
                subprocess.CompletedProcess(
                    [], 0, '{"streams":[{"codec_type":"video"}]}', ""
                )
            )
        self.assertEqual(_progress_seconds({"out_time_us": "1250000"}), 1.25)
        self.assertEqual(_progress_seconds({"out_time": "00:00:01.500000"}), 1.5)
        self.assertIsNone(_progress_seconds({"out_time_us": "N/A"}))
        self.assertEqual(MediaConversionProgress(4.0, 2.5).fraction, 0.99)
        self.assertIsNone(MediaConversionProgress(1.0, None).fraction)


class MediaServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ffmpeg.exe").write_bytes(b"tool")
        (self.root / "ffprobe.exe").write_bytes(b"tool")
        self.source = self.root / "vídeo de aula ção.mp4"
        self.original = b"synthetic-video-data"
        self.source.write_bytes(self.original)
        self.output = self.root / "áudio final ção.mp3"
        self.service = MediaToolsService(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _valid_probe_payload() -> str:
        return json.dumps(
            {
                "streams": [{"codec_type": "audio", "duration": "2.5"}],
                "format": {"duration": "2.5"},
            }
        )

    def _successful_runner(self, calls: list[tuple[list[str], dict[str, object]]]):
        def run(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            calls.append((command, kwargs))
            if Path(command[0]).name.casefold() == "ffmpeg.exe":
                Path(command[-1]).write_bytes(b"synthetic-mp3")
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(
                command,
                0,
                self._valid_probe_payload(),
                "",
            )

        return run

    @staticmethod
    def _start_worker(
        operation: Callable[[], object],
    ) -> tuple[threading.Thread, list[object], list[BaseException]]:
        results: list[object] = []
        errors: list[BaseException] = []

        def run() -> None:
            try:
                results.append(operation())
            except BaseException as error:  # noqa: BLE001 - captura para a thread de teste
                errors.append(error)

        worker = threading.Thread(target=run, name="media-tools-test-worker")
        worker.start()
        return worker, results, errors

    def _assert_worker_finished(self, worker: threading.Thread) -> None:
        worker.join(5)
        self.assertFalse(worker.is_alive(), "O worker de teste não foi encerrado.")


class MediaToolsServiceTests(MediaServiceTestCase):
    def test_ui_path_probes_before_conversion_and_reports_real_timing(self) -> None:
        for profile in MP3_QUALITY_OPTIONS:
            with self.subTest(profile=profile):
                output = self.root / f"resultado-{profile.value}.mp3"
                calls: list[list[str]] = []
                samples: list[MediaConversionProgress] = []

                def run(command: list[str], **kwargs: object):
                    calls.append(command)
                    if Path(command[0]).name.casefold() == "ffmpeg.exe":
                        self.assertEqual(
                            command[command.index("-b:a") + 1],
                            profile.bitrate_argument,
                        )
                        callback = kwargs["on_progress"]
                        self.assertTrue(callable(callback))
                        callback(
                            MediaConversionProgress(1.25, kwargs["total_duration"])
                        )
                        Path(command[-1]).write_bytes(b"synthetic-mp3")
                        return subprocess.CompletedProcess(command, 0, "", "")
                    return subprocess.CompletedProcess(
                        command, 0, self._valid_probe_payload(), ""
                    )

                with patch.object(self.service, "_run_command", side_effect=run):
                    result = self.service.video_to_mp3(
                        self.source, output, quality=profile, on_progress=samples.append
                    )

                self.assertEqual(result.output_path, output)
                self.assertEqual(result.duration_seconds, 2.5)
                self.assertEqual(
                    [Path(item[0]).name for item in calls],
                    ["ffprobe.exe", "ffmpeg.exe", "ffprobe.exe"],
                )
                self.assertEqual(calls[0][-1], str(self.source))
                self.assertEqual(samples[0], MediaConversionProgress(0.0, 2.5))
                self.assertEqual(samples[1].fraction, 0.5)
                self.assertEqual(self.source.read_bytes(), self.original)
                self.assertEqual(list(self.root.glob(".*.tmp.mp3")), [])

    def test_preprobe_rejects_no_audio_and_failures_before_ffmpeg(self) -> None:
        cases = (
            (0, '{"streams":[{"codec_type":"video"}]}', "não possui"),
            (1, "", "não pôde ser analisado"),
            (0, "not-json", "informações inválidas"),
        )
        for returncode, payload, expected in cases:
            with self.subTest(payload=payload):
                calls: list[list[str]] = []

                def run(command: list[str], **_kwargs: object):
                    calls.append(command)
                    return subprocess.CompletedProcess(command, returncode, payload, "")

                with (
                    patch.object(self.service, "_run_command", side_effect=run),
                    self.assertRaises(MediaToolsError) as context,
                ):
                    self.service.video_to_mp3(
                        self.source, self.output, on_progress=lambda _sample: None
                    )
                self.assertIn(expected, str(context.exception))
                self.assertEqual(len(calls), 1)
                self.assertEqual(Path(calls[0][0]).name, "ffprobe.exe")
                self.assertFalse(self.output.exists())

    def test_cancel_token_set_before_worker_start_prevents_any_process(self) -> None:
        cancellation = threading.Event()
        cancellation.set()
        with (
            patch.object(self.service, "_run_command") as run,
            self.assertRaises(MediaOperationCancelled),
        ):
            self.service.video_to_mp3(
                self.source,
                self.output,
                quality=Mp3Quality.HIGH,
                on_progress=lambda _sample: None,
                cancel_event=cancellation,
            )
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_conversion_uses_temp_validates_and_publishes_without_touching_input(
        self,
    ) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        with patch(
            "media_tools.MediaToolsService._run_command",
            side_effect=self._successful_runner(calls),
        ):
            result = self.service.video_to_mp3(self.source, self.output)

        self.assertEqual(result.output_path, self.output)
        self.assertEqual(result.duration_seconds, 2.5)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.output.read_bytes(), b"synthetic-mp3")
        self.assertEqual(len(calls), 2)
        temporary_output = Path(calls[0][0][-1])
        self.assertEqual(temporary_output.parent, self.output.parent)
        self.assertTrue(temporary_output.name.endswith(".tmp.mp3"))
        self.assertFalse(temporary_output.exists())
        self.assertEqual(calls[1][0][-1], str(temporary_output))
        self.assertEqual(calls[0][1], {})
        self.assertEqual(calls[1][1], {"timeout": FFPROBE_TIMEOUT_SECONDS})

    def test_popen_is_owned_with_safe_arguments_and_cleared_after_success(
        self,
    ) -> None:
        popen_calls: list[tuple[list[str], dict[str, object]]] = []
        processes: list[ControlledProcess] = []
        ownership_snapshots: list[bool] = []

        def factory(command: list[str], **kwargs: object) -> ControlledProcess:
            popen_calls.append((command, kwargs))

            def observe_ownership(process: ControlledProcess) -> None:
                ownership_snapshots.append(self.service._active_process is process)
                if Path(command[0]).name.casefold() == "ffmpeg.exe":
                    Path(command[-1]).write_bytes(b"synthetic-mp3")

            process = ControlledProcess(
                command,
                stdout=(
                    self._valid_probe_payload()
                    if Path(command[0]).name.casefold() == "ffprobe.exe"
                    else ""
                ),
                before_finish=observe_ownership,
            )
            processes.append(process)
            return process

        with patch("media_tools.subprocess.Popen", side_effect=factory):
            result = self.service.video_to_mp3(self.source, self.output)

        self.assertEqual(result.duration_seconds, 2.5)
        self.assertEqual(ownership_snapshots, [True, True])
        self.assertIsNone(self.service._active_process)
        self.assertFalse(self.service._operation_active)
        self.assertEqual(len(popen_calls), 2)
        self.assertEqual(Path(popen_calls[0][0][0]).name, "ffmpeg.exe")
        self.assertEqual(Path(popen_calls[1][0][0]).name, "ffprobe.exe")
        for _command, kwargs in popen_calls:
            self.assertIs(kwargs["shell"], False)
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            self.assertIs(kwargs["stdout"], subprocess.PIPE)
            self.assertIs(kwargs["stderr"], subprocess.PIPE)
            self.assertIs(kwargs["text"], True)
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertEqual(kwargs["errors"], "replace")
            self.assertEqual(
                kwargs["creationflags"],
                getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        self.assertEqual(processes[0].communicate_timeouts, [None])
        self.assertEqual(
            processes[1].communicate_timeouts,
            [FFPROBE_TIMEOUT_SECONDS],
        )

    def test_cancel_before_ffmpeg_starts_and_service_is_reusable(self) -> None:
        validation_entered = threading.Event()
        release_validation = threading.Event()
        tools = MediaToolPaths(self.root / "ffmpeg.exe", self.root / "ffprobe.exe")

        def paused_validation(_base_dir: Path | None) -> MediaToolPaths:
            validation_entered.set()
            if not release_validation.wait(5):
                raise AssertionError("A validação controlada não foi liberada.")
            return tools

        with (
            patch("media_tools._validate_media_tools", side_effect=paused_validation),
            patch("media_tools.subprocess.Popen") as popen,
        ):
            worker, _results, errors = self._start_worker(
                lambda: self.service.video_to_mp3(self.source, self.output)
            )
            self.assertTrue(validation_entered.wait(5))
            self.assertTrue(self.service.request_cancel())
            release_validation.set()
            self._assert_worker_finished(worker)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaOperationCancelled)
        popen.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.mp3")), [])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertIsNone(self.service._active_process)
        self.assertFalse(self.service.request_cancel())

        calls: list[tuple[list[str], dict[str, object]]] = []
        with patch(
            "media_tools.MediaToolsService._run_command",
            side_effect=self._successful_runner(calls),
        ):
            result = self.service.video_to_mp3(self.source, self.output)
        self.assertEqual(result.output_path, self.output)
        self.assertEqual(self.output.read_bytes(), b"synthetic-mp3")

    def test_cancel_during_ffmpeg_terminates_only_owned_process(self) -> None:
        processes: list[ControlledProcess] = []
        process_created = threading.Event()

        def factory(command: list[str], **_kwargs: object) -> ControlledProcess:
            if processes:
                raise AssertionError("ffprobe não deve iniciar após cancelamento.")

            def write_partial(_process: ControlledProcess) -> None:
                Path(command[-1]).write_bytes(b"partial-mp3")

            process = ControlledProcess(
                command,
                block=True,
                before_finish=write_partial,
            )
            processes.append(process)
            process_created.set()
            return process

        with patch("media_tools.subprocess.Popen", side_effect=factory):
            worker, _results, errors = self._start_worker(
                lambda: self.service.video_to_mp3(
                    self.source, self.output, quality=Mp3Quality.HIGH
                )
            )
            self.assertTrue(process_created.wait(5))
            process = processes[0]
            self.assertTrue(process.communicate_started.wait(5))
            self.assertIs(self.service._active_process, process)
            self.assertTrue(self.service.request_cancel())
            self._assert_worker_finished(worker)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaOperationCancelled)
        self.assertEqual(
            process.command[process.command.index("-b:a") + 1],
            Mp3Quality.HIGH.bitrate_argument,
        )
        self.assertTrue(self.service._cancel_event.is_set())
        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 0)
        self.assertEqual(process.wait_calls, [1.0])
        self.assertIsNone(self.service._active_process)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.mp3")), [])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_cancel_escalates_to_kill_after_bounded_terminate_wait(self) -> None:
        process_holder: list[ControlledProcess] = []
        process_created = threading.Event()

        def factory(command: list[str], **_kwargs: object) -> ControlledProcess:
            process = ControlledProcess(
                command,
                block=True,
                finish_on_terminate=False,
                wait_timeouts=1,
            )
            process_holder.append(process)
            process_created.set()
            return process

        with patch("media_tools.subprocess.Popen", side_effect=factory):
            worker, _results, errors = self._start_worker(
                lambda: self.service.video_to_mp3(self.source, self.output)
            )
            self.assertTrue(process_created.wait(5))
            process = process_holder[0]
            self.assertTrue(process.communicate_started.wait(5))
            self.assertTrue(self.service.request_cancel())
            self._assert_worker_finished(worker)

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, [1.0, 1.0])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaOperationCancelled)
        self.assertFalse(self.output.exists())

    def test_cancel_reports_when_process_shutdown_cannot_be_confirmed(self) -> None:
        process_holder: list[ControlledProcess] = []
        process_created = threading.Event()

        def factory(command: list[str], **_kwargs: object) -> ControlledProcess:
            process = ControlledProcess(
                command,
                block=True,
                finish_on_terminate=False,
                finish_on_kill=False,
                wait_timeouts=2,
            )
            process_holder.append(process)
            process_created.set()
            return process

        with patch("media_tools.subprocess.Popen", side_effect=factory):
            worker, _results, errors = self._start_worker(
                lambda: self.service.video_to_mp3(self.source, self.output)
            )
            self.assertTrue(process_created.wait(5))
            process = process_holder[0]
            self.assertTrue(process.communicate_started.wait(5))
            with self.assertRaises(MediaToolsError) as context:
                self.service.request_cancel()
            self.assertIn("confirmar o encerramento", str(context.exception))
            process.force_finish(-9)
            self._assert_worker_finished(worker)

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, [1.0, 1.0])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaOperationCancelled)
        self.assertFalse(self.output.exists())

    def test_natural_process_finish_during_cancel_is_safe(self) -> None:
        process_holder: list[ControlledProcess] = []
        process_created = threading.Event()

        def finish_then_disappear(process: ControlledProcess) -> None:
            process.force_finish(0)
            raise ProcessLookupError()

        def factory(command: list[str], **_kwargs: object) -> ControlledProcess:
            process = ControlledProcess(
                command,
                block=True,
                terminate_hook=finish_then_disappear,
            )
            process_holder.append(process)
            process_created.set()
            return process

        with patch("media_tools.subprocess.Popen", side_effect=factory):
            worker, _results, errors = self._start_worker(
                lambda: self.service.video_to_mp3(self.source, self.output)
            )
            self.assertTrue(process_created.wait(5))
            process = process_holder[0]
            self.assertTrue(process.communicate_started.wait(5))
            self.assertTrue(self.service.request_cancel())
            self._assert_worker_finished(worker)

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 0)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaOperationCancelled)
        self.assertIsNone(self.service._active_process)

    def test_cancel_between_ffmpeg_and_ffprobe_does_not_start_probe(self) -> None:
        validation_entered = threading.Event()
        release_validation = threading.Event()
        original_validate = self.service._validate_mp3
        popen_calls: list[str] = []

        def factory(command: list[str], **_kwargs: object) -> ControlledProcess:
            popen_calls.append(Path(command[0]).name.casefold())

            def write_result(_process: ControlledProcess) -> None:
                Path(command[-1]).write_bytes(b"synthetic-mp3")

            return ControlledProcess(command, before_finish=write_result)

        def paused_validate(path: Path, tools: MediaToolPaths) -> float:
            validation_entered.set()
            if not release_validation.wait(5):
                raise AssertionError("A validação controlada não foi liberada.")
            return original_validate(path, tools)

        with (
            patch("media_tools.subprocess.Popen", side_effect=factory),
            patch.object(self.service, "_validate_mp3", side_effect=paused_validate),
        ):
            worker, _results, errors = self._start_worker(
                lambda: self.service.video_to_mp3(self.source, self.output)
            )
            self.assertTrue(validation_entered.wait(5))
            self.assertTrue(self.service.request_cancel())
            release_validation.set()
            self._assert_worker_finished(worker)

        self.assertEqual(popen_calls, ["ffmpeg.exe"])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaOperationCancelled)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.mp3")), [])

    def test_cancel_during_ffprobe_stops_probe_and_does_not_publish(self) -> None:
        processes: list[ControlledProcess] = []
        probe_created = threading.Event()

        def factory(command: list[str], **_kwargs: object) -> ControlledProcess:
            is_probe = Path(command[0]).name.casefold() == "ffprobe.exe"
            if not is_probe:

                def write_result(_process: ControlledProcess) -> None:
                    Path(command[-1]).write_bytes(b"synthetic-mp3")

                process = ControlledProcess(command, before_finish=write_result)
            else:
                process = ControlledProcess(
                    command,
                    stdout=self._valid_probe_payload(),
                    block=True,
                )
            processes.append(process)
            if is_probe:
                probe_created.set()
            return process

        with patch("media_tools.subprocess.Popen", side_effect=factory):
            worker, _results, errors = self._start_worker(
                lambda: self.service.video_to_mp3(self.source, self.output)
            )
            self.assertTrue(probe_created.wait(5))
            probe = processes[1]
            self.assertTrue(probe.communicate_started.wait(5))
            self.assertIs(self.service._active_process, probe)
            self.assertTrue(self.service.request_cancel())
            self._assert_worker_finished(worker)

        self.assertEqual(probe.terminate_calls, 1)
        self.assertEqual(probe.kill_calls, 0)
        self.assertEqual(probe.wait_calls, [1.0])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaOperationCancelled)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.mp3")), [])

    def test_cancel_before_publication_prevents_final_output(self) -> None:
        publish_entered = threading.Event()
        release_publish = threading.Event()
        original_publish = self.service._publish_output
        calls: list[tuple[list[str], dict[str, object]]] = []

        def paused_publish(
            temporary_path: Path,
            output_path: Path,
            *,
            overwrite: bool,
        ) -> None:
            publish_entered.set()
            if not release_publish.wait(5):
                raise AssertionError("A publicação controlada não foi liberada.")
            original_publish(temporary_path, output_path, overwrite=overwrite)

        with (
            patch(
                "media_tools.MediaToolsService._run_command",
                side_effect=self._successful_runner(calls),
            ),
            patch.object(self.service, "_publish_output", side_effect=paused_publish),
        ):
            worker, _results, errors = self._start_worker(
                lambda: self.service.video_to_mp3(self.source, self.output)
            )
            self.assertTrue(publish_entered.wait(5))
            self.assertTrue(self.service.request_cancel())
            release_publish.set()
            self._assert_worker_finished(worker)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MediaOperationCancelled)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.mp3")), [])

    def test_late_cancel_after_atomic_publication_does_not_remove_output(self) -> None:
        published = threading.Event()
        release_worker = threading.Event()
        original_publish = self.service._publish_output
        calls: list[tuple[list[str], dict[str, object]]] = []

        def paused_after_publish(
            temporary_path: Path,
            output_path: Path,
            *,
            overwrite: bool,
        ) -> None:
            original_publish(temporary_path, output_path, overwrite=overwrite)
            published.set()
            if not release_worker.wait(5):
                raise AssertionError("O worker publicado não foi liberado.")

        with (
            patch(
                "media_tools.MediaToolsService._run_command",
                side_effect=self._successful_runner(calls),
            ),
            patch.object(
                self.service,
                "_publish_output",
                side_effect=paused_after_publish,
            ),
        ):
            worker, results, errors = self._start_worker(
                lambda: self.service.video_to_mp3(self.source, self.output)
            )
            self.assertTrue(published.wait(5))
            self.assertTrue(self.output.exists())
            self.assertFalse(self.service.request_cancel())
            release_worker.set()
            self._assert_worker_finished(worker)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(self.output.read_bytes(), b"synthetic-mp3")
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(self.service.request_cancel())

    def test_existing_output_is_rejected_without_explicit_authorization(self) -> None:
        self.output.write_bytes(b"old-result")

        with (
            patch("media_tools.MediaToolsService._run_command") as run,
            self.assertRaises(MediaToolsError) as context,
        ):
            self.service.video_to_mp3(self.source, self.output)

        self.assertIn("já existe", str(context.exception))
        self.assertEqual(self.output.read_bytes(), b"old-result")
        run.assert_not_called()

    def test_authorized_overwrite_replaces_only_the_output(self) -> None:
        self.output.write_bytes(b"old-result")
        calls: list[tuple[list[str], dict[str, object]]] = []

        with patch(
            "media_tools.MediaToolsService._run_command",
            side_effect=self._successful_runner(calls),
        ):
            self.service.video_to_mp3(self.source, self.output, overwrite=True)

        self.assertEqual(self.output.read_bytes(), b"synthetic-mp3")
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_ffmpeg_failure_removes_temporary_and_does_not_publish(self) -> None:
        def fail(
            command: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            Path(command[-1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1, "", "invalid data")

        with (
            patch("media_tools.MediaToolsService._run_command", side_effect=fail),
            self.assertRaises(MediaToolsError) as context,
        ):
            self.service.video_to_mp3(self.source, self.output)

        self.assertIn("incompatível", str(context.exception))
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.mp3")), [])

    def test_video_without_audio_has_specific_safe_error(self) -> None:
        completed = subprocess.CompletedProcess(
            ["ffmpeg"],
            1,
            "",
            "Stream map '0:a:0' matches no streams.",
        )
        with (
            patch("media_tools.MediaToolsService._run_command", return_value=completed),
            self.assertRaises(MediaToolsError) as context,
        ):
            self.service.video_to_mp3(self.source, self.output)

        self.assertIn("não possui uma faixa de áudio", str(context.exception))
        self.assertNotIn(str(self.source), str(context.exception))

    def test_invalid_probe_output_is_rejected_and_cleaned(self) -> None:
        calls = 0

        def run(
            command: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            nonlocal calls
            calls += 1
            if calls == 1:
                Path(command[-1]).write_bytes(b"synthetic-mp3")
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 0, "not-json", "")

        with (
            patch("media_tools.MediaToolsService._run_command", side_effect=run),
            self.assertRaises(MediaToolsError) as context,
        ):
            self.service.video_to_mp3(self.source, self.output)

        self.assertIn("informações inválidas", str(context.exception))
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".*.tmp.mp3")), [])

    def test_ffprobe_failure_is_rejected_without_exposing_technical_output(
        self,
    ) -> None:
        calls = 0

        def run(
            command: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            nonlocal calls
            calls += 1
            if calls == 1:
                Path(command[-1]).write_bytes(b"synthetic-mp3")
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                f"private technical path: {self.source}",
            )

        with (
            patch("media_tools.MediaToolsService._run_command", side_effect=run),
            self.assertRaises(MediaToolsError) as context,
        ):
            self.service.video_to_mp3(self.source, self.output)

        self.assertIn("ffprobe", str(context.exception))
        self.assertNotIn(str(self.source), str(context.exception))
        self.assertFalse(self.output.exists())

    def test_atomic_replace_failure_preserves_existing_output_and_cleans_temp(
        self,
    ) -> None:
        self.output.write_bytes(b"old-result")
        calls: list[tuple[list[str], dict[str, object]]] = []

        with (
            patch(
                "media_tools.MediaToolsService._run_command",
                side_effect=self._successful_runner(calls),
            ),
            patch("media_tools.os.replace", side_effect=PermissionError()),
            self.assertRaises(MediaToolsError),
        ):
            self.service.video_to_mp3(self.source, self.output, overwrite=True)

        self.assertEqual(self.output.read_bytes(), b"old-result")
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.root.glob(".*.tmp.mp3")), [])

    def test_probe_rejects_video_stream_or_missing_audio(self) -> None:
        for streams, expected in (
            ([{"codec_type": "video"}], "não contém uma faixa de áudio"),
            (
                [{"codec_type": "audio"}, {"codec_type": "video"}],
                "contém vídeo",
            ),
        ):
            with self.subTest(streams=streams):
                calls = 0

                def run(
                    command: list[str], **_kwargs: object
                ) -> subprocess.CompletedProcess[str]:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        Path(command[-1]).write_bytes(b"synthetic-mp3")
                        return subprocess.CompletedProcess(command, 0, "", "")
                    payload = json.dumps(
                        {"streams": streams, "format": {"duration": "1.0"}}
                    )
                    return subprocess.CompletedProcess(command, 0, payload, "")

                with (
                    patch(
                        "media_tools.MediaToolsService._run_command",
                        side_effect=run,
                    ),
                    self.assertRaises(MediaToolsError) as context,
                ):
                    self.service.video_to_mp3(self.source, self.output)
                self.assertIn(expected, str(context.exception))
                self.assertFalse(self.output.exists())

    def test_missing_ffmpeg_or_ffprobe_fails_before_subprocess(self) -> None:
        for missing_name in ("ffmpeg.exe", "ffprobe.exe"):
            with self.subTest(missing_name=missing_name):
                tool = self.root / missing_name
                tool.unlink()
                with (
                    patch("media_tools.MediaToolsService._run_command") as run,
                    self.assertRaises(MediaToolsError) as context,
                ):
                    self.service.video_to_mp3(self.source, self.output)
                self.assertIn(missing_name, str(context.exception))
                run.assert_not_called()
                tool.write_bytes(b"tool")

    def test_corrupt_executable_has_safe_specific_error(self) -> None:
        private_detail = str(self.root / "perfil privado" / "ffmpeg.exe")
        error = OSError(8, private_detail)

        with (
            patch("media_tools.subprocess.Popen", side_effect=error),
            self.assertRaises(MediaToolsError) as context,
        ):
            self.service.video_to_mp3(self.source, self.output)

        self.assertIn("ffmpeg.exe", str(context.exception))
        self.assertIn("corrompido", str(context.exception))
        self.assertNotIn(private_detail, str(context.exception))
        self.assertFalse(self.output.exists())

    def test_unsupported_or_missing_input_and_invalid_destination_are_rejected(
        self,
    ) -> None:
        cases = (
            (self.root / "arquivo.txt", self.output),
            (self.root / "ausente.mp4", self.output),
            (self.source, self.root / "resultado.wav"),
            (self.source, self.root / "ausente" / "resultado.mp3"),
        )
        for source, output in cases:
            with self.subTest(source=source, output=output):
                with self.assertRaises(MediaToolsError):
                    self.service.video_to_mp3(source, output)


class MediaSegmentTests(MediaServiceTestCase):
    def extract(self, start=10, end=12.5, **kwargs):
        return self.service.video_segment_to_mp3(
            self.source, self.output, start_seconds=start, end_seconds=end, **kwargs
        )

    @staticmethod
    def payload(duration=40):
        return json.dumps(
            {"streams": [{"codec_type": "audio"}], "format": {"duration": duration}}
        )

    def runner(self, calls, *, source_payload=None, output_payload=None, fail=False):
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if Path(command[0]).name == "ffmpeg.exe":
                Path(command[-1]).write_bytes(b"partial" if fail else b"synthetic-mp3")
                if "on_progress" in kwargs:
                    kwargs["on_progress"](
                        MediaConversionProgress(1.25, kwargs["total_duration"])
                    )
                return subprocess.CompletedProcess(command, int(fail), "", "bad data")
            return subprocess.CompletedProcess(
                command,
                0,
                (source_payload if source_payload is not None else self.payload())
                if Path(command[-1]) == self.source
                else (
                    output_payload if output_payload is not None else self.payload(2.5)
                ),
                "",
            )

        return run

    def assert_clean(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.root.glob(".*.tmp.mp3")), [])
        self.assertFalse(self.service._operation_active)
        self.assertIsNone(self.service._active_process)

    def test_intervals_profiles_seek_and_publication(self):
        for start, end in ((0, 2.5), (10, 12.5), (37.5, 40)):
            for quality in MP3_QUALITY_OPTIONS:
                with self.subTest(start=start, end=end, quality=quality):
                    calls = []
                    with patch.object(
                        self.service, "_run_command", side_effect=self.runner(calls)
                    ):
                        result = self.extract(start, end, quality=quality)
                    self.assertEqual(result.duration_seconds, 2.5)
                    self.assertEqual(result.output_path, self.output)
                    self.assertEqual(self.output.read_bytes(), b"synthetic-mp3")
                    self.assertEqual(len(calls), 3)
                    command, kwargs = calls[1]
                    self.assertEqual(kwargs, {})
                    self.assertLess(command.index("-ss"), command.index("-i"))
                    self.assertEqual(float(command[command.index("-ss") + 1]), start)
                    self.assertGreater(command.index("-t"), command.index("-i"))
                    self.assertEqual(
                        float(command[command.index("-t") + 1]), end - start
                    )
                    self.assertNotIn("-to", command)
                    self.assertEqual(command[command.index("-map") + 1], "0:a:0")
                    self.assertEqual(
                        command[command.index("-b:a") + 1], quality.bitrate_argument
                    )
                    self.assertIn("-vn", command)
                    self.assertEqual(command[command.index("-c:a") + 1], "libmp3lame")
                    for index in (0, 2):
                        self.assertEqual(
                            calls[index][1], {"timeout": FFPROBE_TIMEOUT_SECONDS}
                        )
                    self.assert_clean()
                    self.output.unlink()

    def test_invalid_times_rejected_before_process_or_temporary(self):
        cases = [(-1, 2), (1, 1), (2, 1), (0, -1)]
        for invalid in (
            float("nan"),
            float("inf"),
            -float("inf"),
            "1",
            "00:01",
            None,
            True,
            False,
            [],
            {},
            object(),
            10**400,
        ):
            cases.extend(((invalid, 2), (0, invalid)))
        for start, end in cases:
            with self.subTest(start=start, end=end):
                with (
                    patch.object(self.service, "_run_command") as run,
                    self.assertRaises(MediaToolsError),
                ):
                    self.extract(start, end)
                run.assert_not_called()
                self.assertFalse(self.output.exists())
                self.assert_clean()

    def test_end_beyond_source_has_no_boundary_tolerance(self):
        for start, end in ((39, 41), (40, 41), (39, 40.000001)):
            calls = []
            with (
                self.subTest(start=start, end=end),
                patch.object(
                    self.service, "_run_command", side_effect=self.runner(calls)
                ),
                self.assertRaisesRegex(MediaToolsError, "duração do vídeo"),
            ):
                self.extract(start, end)
            self.assertEqual(len(calls), 1)
            self.assertFalse(self.output.exists())
            self.assert_clean()

    def test_source_must_have_audio_and_valid_duration_even_without_progress(self):
        payloads = [
            "invalid",
            "[]",
            "null",
            '{"streams":[null]}',
            '{"streams":[{"codec_type":"video"}],"format":{"duration":40}}',
        ]
        payloads += [
            self.payload(value)
            for value in (None, "N/A", 0, -1, "NaN", "inf", [], {}, True, 10**400)
        ]
        for payload in payloads:
            calls = []
            with (
                self.subTest(payload=payload),
                patch.object(
                    self.service,
                    "_run_command",
                    side_effect=self.runner(calls, source_payload=payload),
                ),
                self.assertRaises(MediaToolsError),
            ):
                self.extract()
            self.assertEqual(len(calls), 1)
            self.assertFalse(self.output.exists())
            self.assert_clean()

    def test_probe_failure_is_friendly_and_creates_no_output(self):
        with (
            patch.object(
                self.service,
                "_run_command",
                return_value=subprocess.CompletedProcess([], 1, "", str(self.source)),
            ),
            self.assertRaisesRegex(MediaToolsError, "não pôde ser analisado") as error,
        ):
            self.extract()
        self.assertNotIn(str(self.source), str(error.exception))
        self.assertFalse(self.output.exists())
        self.assert_clean()

    def test_output_duration_tolerance_and_validation_before_publication(self):
        for duration, accepted in (
            (2.45, True),
            (2.55, True),
            (2.5 + MP3_SEGMENT_DURATION_TOLERANCE_SECONDS, True),
            (0.1, False),
            (2.8, False),
            (40, False),
        ):
            calls = []
            self.output.write_bytes(b"previous")
            with (
                self.subTest(duration=duration),
                patch.object(
                    self.service,
                    "_run_command",
                    side_effect=self.runner(
                        calls, output_payload=self.payload(duration)
                    ),
                ),
            ):
                if accepted:
                    self.assertEqual(
                        self.extract(overwrite=True).duration_seconds, duration
                    )
                    self.assertEqual(self.output.read_bytes(), b"synthetic-mp3")
                else:
                    with self.assertRaisesRegex(MediaToolsError, "não corresponde"):
                        self.extract(overwrite=True)
                    self.assertEqual(self.output.read_bytes(), b"previous")
            self.assert_clean()

    def test_ffmpeg_and_output_probe_failures_preserve_old_output(self):
        for options in (
            {"fail": True},
            {"output_payload": "invalid"},
            {"output_payload": self.payload(0)},
            {"output_payload": self.payload(True)},
            {"output_payload": self.payload(10**400)},
            {
                "output_payload": '{"streams":[{"codec_type":"video"}],"format":{"duration":2.5}}'
            },
        ):
            calls = []
            self.output.write_bytes(b"previous")
            with (
                self.subTest(options=options),
                patch.object(
                    self.service,
                    "_run_command",
                    side_effect=self.runner(calls, **options),
                ),
                self.assertRaises(MediaToolsError),
            ):
                self.extract(overwrite=True)
            self.assertEqual(self.output.read_bytes(), b"previous")
            self.assert_clean()

    def test_progress_uses_segment_and_never_claims_published_result(self):
        calls, samples = [], []

        def progress(sample):
            self.assertFalse(self.output.exists())
            self.assertLess(sample.fraction, 1)
            samples.append(sample)

        with patch.object(self.service, "_run_command", side_effect=self.runner(calls)):
            self.extract(on_progress=progress)
        self.assertEqual(
            samples,
            [MediaConversionProgress(0, 2.5), MediaConversionProgress(1.25, 2.5)],
        )
        self.assertEqual(samples[1].fraction, 0.5)
        self.assertEqual(calls[1][1]["total_duration"], 2.5)
        self.assert_clean()

    def test_existing_output_invalid_profile_and_missing_tools_before_process(self):
        self.output.write_bytes(b"previous")
        with (
            patch.object(self.service, "_run_command") as run,
            self.assertRaisesRegex(MediaToolsError, "já existe"),
        ):
            self.extract()
        run.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b"previous")
        self.output.unlink()
        with (
            patch.object(self.service, "_run_command") as run,
            self.assertRaisesRegex(MediaToolsError, "qualidade"),
        ):
            self.extract(quality="320k")
        run.assert_not_called()
        (self.root / "ffprobe.exe").unlink()
        with (
            patch.object(self.service, "_run_command") as run,
            self.assertRaisesRegex(MediaToolsError, "ffprobe.exe"),
        ):
            self.extract()
        run.assert_not_called()
        self.assert_clean()

    def test_invalid_input_and_destination_reuse_full_conversion_contract(self):
        for source, output in (
            (self.root / "missing.mp4", self.output),
            (self.source, self.root / "x.wav"),
            (self.source, self.root / "missing" / "x.mp3"),
        ):
            with (
                self.subTest(source=source, output=output),
                patch.object(self.service, "_run_command") as run,
                self.assertRaises(MediaToolsError),
            ):
                self.service.video_segment_to_mp3(
                    source, output, start_seconds=0, end_seconds=2.5
                )
            run.assert_not_called()
            self.assert_clean()

    def test_pre_cancelled_token_starts_no_process(self):
        event = threading.Event()
        event.set()
        with (
            patch.object(self.service, "_run_command") as run,
            self.assertRaises(MediaOperationCancelled),
        ):
            self.extract(cancel_event=event)
        run.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assert_clean()

    def test_cancellation_in_each_process_stops_only_owned_process(self):
        for cancel_stage in (0, 1, 2):
            processes = []
            created = threading.Event()
            unrelated = ControlledProcess(["other-application"])
            self.output.write_bytes(b"previous")

            def factory(command, **kwargs):
                stage = len(processes)

                def before_finish(_process):
                    if stage == 1:
                        Path(command[-1]).write_bytes(b"partial")

                process = ControlledProcess(
                    command,
                    stdout=self.payload(40 if stage == 0 else 2.5),
                    block=stage == cancel_stage,
                    before_finish=before_finish,
                )
                processes.append(process)
                if stage == cancel_stage:
                    created.set()
                self.assertFalse(kwargs["shell"])
                return process

            with (
                self.subTest(stage=cancel_stage),
                patch("media_tools.subprocess.Popen", side_effect=factory),
            ):
                worker, results, errors = self._start_worker(
                    lambda: self.extract(overwrite=True)
                )
                try:
                    self.assertTrue(created.wait(5))
                    owned = processes[cancel_stage]
                    self.assertTrue(owned.communicate_started.wait(5))
                    self.assertTrue(self.service.request_cancel())
                finally:
                    for process in processes:
                        process.release_communicate.set()
                    self._assert_worker_finished(worker)
            self.assertEqual(results, [])
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], MediaOperationCancelled)
            self.assertEqual(len(processes), cancel_stage + 1)
            self.assertEqual(owned.terminate_calls, 1)
            self.assertEqual(unrelated.terminate_calls, 0)
            self.assertEqual(unrelated.kill_calls, 0)
            self.assertEqual(self.output.read_bytes(), b"previous")
            self.assert_clean()

    def test_cancel_before_publish_and_concurrent_full_conversion(self):
        calls = []

        def validate(_path, _tools):
            with self.assertRaisesRegex(MediaToolsError, "em andamento"):
                self.service.video_to_mp3(self.source, self.root / "other.mp3")
            self.assertTrue(self.service.request_cancel())
            return 2.5

        with (
            patch.object(self.service, "_run_command", side_effect=self.runner(calls)),
            patch.object(self.service, "_validate_mp3", side_effect=validate),
            self.assertRaises(MediaOperationCancelled),
        ):
            self.extract()
        self.assertFalse(self.output.exists())
        self.assert_clean()
        with patch.object(self.service, "_run_command", side_effect=self.runner([])):
            self.extract()
        self.assert_clean()

    @unittest.skipIf(os.name == "nt", "Corrida de rename específica do POSIX")
    def test_publication_does_not_overwrite_competing_destination(self):
        original_link = os.link

        def competing_link(source, destination):
            Path(destination).write_bytes(b"competing-result")
            return original_link(source, destination)

        with (
            patch.object(self.service, "_run_command", side_effect=self.runner([])),
            patch("media_tools.os.link", side_effect=competing_link),
            self.assertRaises(MediaToolsError),
        ):
            self.extract()
        self.assertEqual(self.output.read_bytes(), b"competing-result")
        self.assert_clean()


class MediaSegmentRealFfmpegTests(unittest.TestCase):
    def test_synthetic_intervals_duration_content_profiles_and_full_conversion(self):
        project = Path(__file__).resolve().parents[1]
        ffmpeg = project / "ffmpeg.exe"
        ffprobe = project / "ffprobe.exe"
        if not ffmpeg.is_file() or not ffprobe.is_file():
            system_ffmpeg, system_ffprobe = (
                shutil.which("ffmpeg"),
                shutil.which("ffprobe"),
            )
            if not system_ffmpeg or not system_ffprobe:
                self.skipTest("FFmpeg e FFprobe locais indisponíveis")
            ffmpeg, ffprobe = Path(system_ffmpeg), Path(system_ffprobe)
        tools = MediaToolPaths(ffmpeg, ffprobe)

        def execute(command):
            return subprocess.run(command, capture_output=True, check=True, timeout=30)

        with tempfile.TemporaryDirectory(prefix="trecho de mídia ção ") as directory:
            root = Path(directory)
            source = root / "vídeo original ção.mkv"
            execute(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=160x90:r=10",
                    "-f",
                    "lavfi",
                    "-i",
                    "aevalsrc=sin(2*PI*if(lt(t\\,2)\\,440\\,if(lt(t\\,6)\\,880\\,1320))*t):s=44100",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=1800:sample_rate=44100",
                    "-map",
                    "0:v",
                    "-map",
                    "1:a",
                    "-map",
                    "2:a",
                    "-t",
                    "8",
                    "-c:v",
                    "mpeg4",
                    "-c:a",
                    "pcm_s16le",
                    str(source),
                ]
            )
            original = source.read_bytes()
            service = MediaToolsService()
            with patch("media_tools.locate_media_tools", return_value=tools):
                for start, end, frequency in ((0, 1, 440), (3, 5.5, 880), (7, 8, 1320)):
                    for quality in MP3_QUALITY_OPTIONS:
                        with self.subTest(start=start, end=end, quality=quality):
                            output = root / f"trecho {start} {quality.value}.mp3"
                            samples = []
                            result = service.video_segment_to_mp3(
                                source,
                                output,
                                start_seconds=start,
                                end_seconds=end,
                                quality=quality,
                                on_progress=samples.append,
                            )
                            metadata = json.loads(
                                execute(
                                    [
                                        str(ffprobe),
                                        "-v",
                                        "error",
                                        "-show_entries",
                                        "stream=codec_type,codec_name,bit_rate:format=duration",
                                        "-of",
                                        "json",
                                        str(output),
                                    ]
                                ).stdout
                            )
                            actual = float(metadata["format"]["duration"])
                            self.assertLess(
                                abs(actual - (end - start)),
                                MP3_SEGMENT_DURATION_TOLERANCE_SECONDS,
                            )
                            self.assertAlmostEqual(result.duration_seconds, actual)
                            self.assertEqual(len(metadata["streams"]), 1)
                            self.assertEqual(
                                metadata["streams"][0]["codec_name"], "mp3"
                            )
                            self.assertLess(
                                abs(
                                    int(metadata["streams"][0]["bit_rate"])
                                    - quality.kbps * 1000
                                ),
                                8000,
                            )
                            # Conteúdo prova o seek e a escolha do primeiro áudio,
                            # além de simplesmente produzir a duração correta.
                            pcm = execute(
                                [
                                    str(ffmpeg),
                                    "-v",
                                    "error",
                                    "-i",
                                    str(output),
                                    "-ss",
                                    "0.2",
                                    "-t",
                                    "0.2",
                                    "-ac",
                                    "1",
                                    "-ar",
                                    "44100",
                                    "-f",
                                    "f32le",
                                    "pipe:1",
                                ]
                            ).stdout
                            values = struct.unpack(f"<{len(pcm) // 4}f", pcm)
                            crossings = sum(
                                a < 0 <= b for a, b in zip(values, values[1:])
                            )
                            measured_frequency = crossings * 44100 / len(values)
                            self.assertLess(abs(measured_frequency - frequency), 15)
                            self.assertTrue(samples)
                            self.assertTrue(
                                any(sample.processed_seconds > 0 for sample in samples)
                            )
                            self.assertTrue(
                                all(
                                    sample.total_seconds == end - start
                                    and sample.fraction < 1
                                    for sample in samples
                                )
                            )
                            self.assertEqual(source.read_bytes(), original)
                            self.assertEqual(list(root.glob(".*.tmp.mp3")), [])
                full = service.video_to_mp3(source, root / "completo.mp3")
                self.assertLess(abs(full.duration_seconds - 8), 0.25)
                preserved = root / "cancelado.mp3"
                preserved.write_bytes(b"previous")
                cancelled = []

                def cancel(sample):
                    if sample.processed_seconds > 0 and not cancelled:
                        cancelled.append(service.request_cancel())

                with self.assertRaises(MediaOperationCancelled):
                    service.video_segment_to_mp3(
                        source,
                        preserved,
                        start_seconds=3,
                        end_seconds=5.5,
                        overwrite=True,
                        on_progress=cancel,
                    )
                self.assertEqual(cancelled, [True])
                self.assertEqual(preserved.read_bytes(), b"previous")
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(list(root.glob(".*.tmp.mp3")), [])
                self.assertIsNone(service._active_process)
                self.assertFalse(service._operation_active)


class MediaRealFfmpegTests(unittest.TestCase):
    def test_three_profiles_progress_duration_and_no_audio_with_local_fixtures(
        self,
    ) -> None:
        project = Path(__file__).resolve().parents[1]
        ffmpeg = project / "ffmpeg.exe"
        ffprobe = project / "ffprobe.exe"
        if not ffmpeg.is_file() or not ffprobe.is_file():
            system_ffmpeg, system_ffprobe = (
                shutil.which("ffmpeg"),
                shutil.which("ffprobe"),
            )
            if not system_ffmpeg or not system_ffprobe:
                self.skipTest("FFmpeg e FFprobe locais indisponíveis")
            ffmpeg, ffprobe = Path(system_ffmpeg), Path(system_ffprobe)
            self.enterContext(
                patch(
                    "media_tools.locate_media_tools",
                    return_value=MediaToolPaths(ffmpeg, ffprobe),
                )
            )

        with tempfile.TemporaryDirectory(prefix="mídia com espaços ") as directory:
            root = Path(directory)
            source = root / "vídeo ção.mp4"
            created = subprocess.run(
                [
                    str(ffmpeg),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=160x90:r=10",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=44100",
                    "-t",
                    "3",
                    "-c:v",
                    "mpeg4",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(source),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            original = source.read_bytes()
            service = MediaToolsService(project)
            for profile in MP3_QUALITY_OPTIONS:
                with self.subTest(profile=profile):
                    output = root / f"saída {profile.value} ção.mp3"
                    samples: list[MediaConversionProgress] = []
                    result = service.video_to_mp3(
                        source, output, quality=profile, on_progress=samples.append
                    )
                    inspected = subprocess.run(
                        [
                            str(ffprobe),
                            "-v",
                            "error",
                            "-show_entries",
                            "stream=codec_type,bit_rate:format=duration",
                            "-of",
                            "json",
                            str(output),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                    )
                    self.assertEqual(inspected.returncode, 0, inspected.stderr)
                    metadata = json.loads(inspected.stdout)
                    audio = next(
                        stream
                        for stream in metadata["streams"]
                        if stream["codec_type"] == "audio"
                    )
                    bitrate = int(audio["bit_rate"])
                    self.assertLess(abs(bitrate - profile.kbps * 1000), 8000)
                    self.assertLess(abs(result.duration_seconds - 3), 0.3)
                    self.assertTrue(samples)
                    self.assertEqual(samples[0].processed_seconds, 0)
                    self.assertIsNotNone(samples[0].total_seconds)
                    self.assertTrue(
                        any(sample.processed_seconds > 0 for sample in samples)
                    )
                    self.assertEqual(source.read_bytes(), original)
                    self.assertEqual(list(root.glob(".*.tmp.mp3")), [])

            preserved = root / "sobrescrita protegida.mp3"
            preserved.write_bytes(b"old-result")
            cancelled: list[bool] = []

            def cancel_during_progress(sample: MediaConversionProgress) -> None:
                if sample.processed_seconds > 0 and not cancelled:
                    cancelled.append(service.request_cancel())

            with self.assertRaises(MediaOperationCancelled):
                service.video_to_mp3(
                    source,
                    preserved,
                    overwrite=True,
                    quality=Mp3Quality.HIGH,
                    on_progress=cancel_during_progress,
                )
            self.assertEqual(cancelled, [True])
            self.assertEqual(preserved.read_bytes(), b"old-result")
            self.assertEqual(list(root.glob(".*.tmp.mp3")), [])
            self.assertIsNone(service._active_process)
            self.assertFalse(service._operation_active)

            silent = root / "sem áudio.mp4"
            created = subprocess.run(
                [
                    str(ffmpeg),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=160x90:r=10",
                    "-t",
                    "1",
                    "-c:v",
                    "mpeg4",
                    str(silent),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            with self.assertRaisesRegex(MediaToolsError, "não possui uma faixa"):
                service.video_to_mp3(
                    silent,
                    root / "sem áudio.mp3",
                    on_progress=lambda _sample: None,
                )
            self.assertFalse((root / "sem áudio.mp3").exists())


if __name__ == "__main__":
    unittest.main()
