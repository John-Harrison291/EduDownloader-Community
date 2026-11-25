"""Inicialização do EduDownloader Community a partir do código-fonte."""

from tkinter import messagebox

from app_factory import ApplicationFactory
from constants import APP_NAME

PUBLIC_BOOTSTRAP_ERROR = (
    "Não foi possível iniciar o aplicativo com segurança. "
    "Feche o programa e tente novamente; se o problema continuar, procure o suporte."
)


def run_application() -> None:
    _run_community_application(ApplicationFactory())


def _run_community_application(application_factory: ApplicationFactory) -> None:
    """Abra a janela da Community e trate falhas de inicialização."""

    try:
        application = application_factory.create()
    except Exception:
        _show_public_bootstrap_error(PUBLIC_BOOTSTRAP_ERROR)
        return
    try:
        application.mainloop()
    except Exception:
        application_factory.shutdown()
        _show_public_bootstrap_error(PUBLIC_BOOTSTRAP_ERROR)


def _show_public_bootstrap_error(message: str) -> None:
    messagebox.showerror(APP_NAME, message)
