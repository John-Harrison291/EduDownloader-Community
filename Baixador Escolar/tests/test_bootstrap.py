"""Regressões de inicialização e composição da janela Community."""

import os
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

import bootstrap
from app_factory import ApplicationFactory, ApplicationSetupError
from constants import APP_VERSION, PRODUCT_EDITION, ProductEdition

INTERNAL_DETAIL = "fixture exception detail"


class FakeDownloadService:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeMainApplication:
    def __init__(
        self,
        download_service: FakeDownloadService,
    ) -> None:
        self.download_service = download_service
        self.mainloop_calls = 0
        self.close_calls = 0

    def mainloop(self) -> None:
        self.mainloop_calls += 1

    def close(self) -> None:
        self.close_calls += 1
        self.download_service.close()


class RecordingApplicationBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, int]] = []

    def __call__(self, download_service) -> FakeMainApplication:
        self.calls.append((download_service, threading.get_ident()))
        return FakeMainApplication(download_service)


class ApplicationFactoryTests(unittest.TestCase):
    def test_download_service_and_application_are_created_once_on_request(
        self,
    ) -> None:
        services: list[FakeDownloadService] = []
        builder = RecordingApplicationBuilder()

        def create_service() -> FakeDownloadService:
            service = FakeDownloadService()
            services.append(service)
            return service

        factory = ApplicationFactory(
            application_builder=builder,  # type: ignore[arg-type]
            download_service_factory=create_service,  # type: ignore[arg-type]
        )

        self.assertEqual(services, [])
        application = factory.create()
        repeated = factory.create()

        self.assertIs(application, repeated)
        self.assertEqual(len(services), 1)
        self.assertEqual(len(builder.calls), 1)
        self.assertIs(builder.calls[0][0], services[0])

    def test_builder_failure_closes_the_new_download_service(self) -> None:
        download_service = FakeDownloadService()
        factory = ApplicationFactory(
            application_builder=Mock(side_effect=RuntimeError(INTERNAL_DETAIL)),
            download_service_factory=lambda: download_service,  # type: ignore[arg-type]
        )

        with self.assertRaises(ApplicationSetupError) as raised:
            factory.create()

        self.assertEqual(download_service.close_calls, 1)
        self.assertNotIn(INTERNAL_DETAIL, str(raised.exception))


class CommunityStartupTests(unittest.TestCase):
    def test_main_opens_one_community_window(self):
        import main

        factory = Mock()
        window = factory.create.return_value
        with patch.object(bootstrap, "ApplicationFactory", return_value=factory):
            main.main()
        factory.create.assert_called_once_with()
        window.mainloop.assert_called_once_with()

    def test_failed_window_launch_reports_only_known_message(self):
        factory = Mock()
        factory.create.return_value.mainloop.side_effect = RuntimeError(
            "internal detail"
        )
        with patch.object(bootstrap, "_show_public_bootstrap_error") as report:
            bootstrap._run_community_application(factory)
        report.assert_called_once_with(bootstrap.PUBLIC_BOOTSTRAP_ERROR)
        factory.shutdown.assert_called_once_with()

    def test_community_identity_ignores_unrelated_environment_and_arguments(self):
        code = (
            "import constants; "
            "assert constants.PRODUCT_EDITION.value == 'community'; "
            "assert constants.APP_VERSION == '3.0.0'"
        )
        env = dict(os.environ, PRODUCT_EDITION="other", EDUDOWNLOADER_EDITION="other")
        subprocess.run(
            [sys.executable, "-c", code, "--edition", "other"], env=env, check=True
        )
        self.assertIs(PRODUCT_EDITION, ProductEdition.COMMUNITY)
        self.assertEqual(APP_VERSION, "3.0.0")
        self.assertEqual(list(ProductEdition), [ProductEdition.COMMUNITY])

    def test_main_import_does_not_create_window_or_connect(self):
        code = """
import socket
import threading
from unittest.mock import patch
with (
    patch("customtkinter.CTk.__init__", side_effect=AssertionError("Tk creation")),
    patch.object(threading.Thread, "start", side_effect=AssertionError("worker")),
    patch.object(socket.socket, "connect", side_effect=AssertionError("network")),
):
    import main
    assert callable(main.main)
"""
        subprocess.run([sys.executable, "-c", code], check=True)
