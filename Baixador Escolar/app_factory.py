"""Composição da janela para execução a partir do código e para o portátil."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from tkinter import messagebox

from app import EduDownloaderApp
from constants import APP_NAME
from downloader import DownloadService


class ApplicationSetupError(RuntimeError):
    """A janela ou o serviço de downloads não puderam ser inicializados."""


class MainApplication(Protocol):
    def mainloop(self) -> None: ...

    def close(self) -> None: ...


class ApplicationFactory:
    """Crie uma única instância do aplicativo."""

    def __init__(
        self,
        *,
        application_builder: Callable[[DownloadService], MainApplication] = (
            EduDownloaderApp
        ),
        download_service_factory: Callable[[], DownloadService] = DownloadService,
    ) -> None:
        if not callable(application_builder) or not callable(download_service_factory):
            raise ApplicationSetupError
        self._application_builder = application_builder
        self._download_service_factory = download_service_factory
        self._lock = threading.Lock()
        self._creating = False
        self._application: MainApplication | None = None
        self._download_service: DownloadService | None = None

    @property
    def application(self) -> MainApplication | None:
        with self._lock:
            return self._application

    def create(self) -> MainApplication:
        with self._lock:
            if self._application is not None:
                return self._application
            if self._creating:
                raise ApplicationSetupError
            self._creating = True

        download_service: DownloadService | None = None
        try:
            download_service = self._download_service_factory()
            if not callable(getattr(download_service, "close", None)):
                raise ApplicationSetupError
            application = self._application_builder(download_service)
            if not all(
                callable(getattr(application, method, None))
                for method in ("mainloop", "close")
            ):
                raise ApplicationSetupError
        except Exception:
            _safe_close(download_service)
            with self._lock:
                self._creating = False
            raise ApplicationSetupError from None

        with self._lock:
            self._application = application
            self._download_service = download_service
            self._creating = False
            return application

    def shutdown(self) -> None:
        with self._lock:
            application = self._application
            download_service = self._download_service
            self._application = None
            self._download_service = None
        if application is not None:
            try:
                application.close()
                return
            except Exception:
                pass
        _safe_close(download_service)

    def __str__(self) -> str:
        with self._lock:
            state = "created" if self._application is not None else "pending"
        return f"{type(self).__name__}(state={state!r}, collaborators=<redacted>)"

    def __repr__(self) -> str:
        return str(self)


def _safe_close(value: object) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def run_shared_shell() -> None:
    """Abra a janela principal da Community."""
    factory = ApplicationFactory()
    try:
        factory.create().mainloop()
    except Exception:
        factory.shutdown()
        messagebox.showerror(
            APP_NAME, "Não foi possível iniciar o aplicativo com segurança."
        )
