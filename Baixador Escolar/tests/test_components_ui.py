"""Smoke da seção local de Componentes em Configurações."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class ComponentsSettingsRealTkTests(unittest.TestCase):
    def test_libreoffice_actions_follow_state_and_ready_hides_setup(self) -> None:
        script = r"""
            import json
            import tkinter as tk
            from dataclasses import replace
            from pathlib import Path
            import customtkinter as ctk
            from component_manager import ComponentManager, ComponentId, ComponentState
            from libreoffice_managed import AcquisitionResult, AcquisitionStatus
            from ui_pages import SettingsPage, _ComponentRefreshResult

            class Manager:
                def list_components(self):
                    return ComponentManager().list_components()
                def refresh(self, _component):
                    return replace(ComponentManager().get_component(ComponentId.LIBREOFFICE), state=ComponentState.READY)
            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print("SKIP_TK:" + type(error).__name__)
                raise SystemExit(0)
            root.withdraw()
            page = SettingsPage(root, theme_value="Claro", change_theme=lambda _: None,
                component_manager=Manager(),
                component_installer=object(), activate_managed_component=lambda _: True)
            page.pack()
            def actions():
                return [bool(button.grid_info()) for button in (
                    page.libreoffice_install_button, page.libreoffice_existing_button,
                    page.libreoffice_verify_button)]
            def refresh(state):
                snapshot = replace(Manager().refresh(ComponentId.LIBREOFFICE), state=state)
                page._component_results.put(_ComponentRefreshResult((snapshot,)))
                page._poll_component_results()
            results = {"initial": actions()}
            for theme in ("Light", "Dark"):
                ctk.set_appearance_mode(theme)
                refresh(ComponentState.NOT_CONFIGURED)
                results[theme + "_missing"] = actions()
                refresh(ComponentState.READY)
                results[theme + "_ready"] = actions()
                results[theme + "_text"] = page.component_status_labels[ComponentId.LIBREOFFICE].cget("text")
                results[theme + "_extra_text"] = page.libreoffice_status.cget("text")
                refresh(ComponentState.CORRUPTED)
                results[theme + "_invalid"] = actions()
            page._display_libreoffice_phase("download")
            results["download"] = actions()
            refresh(ComponentState.NOT_CONFIGURED)
            results["concurrent_refresh"] = actions()
            page._display_libreoffice_phase("installer_opened")
            results["installer"] = actions()
            page._display_libreoffice_result(AcquisitionResult(AcquisitionStatus.BUSY, None, "installer_pending"))
            results["pending"] = actions()
            page._display_libreoffice_result(AcquisitionResult(AcquisitionStatus.CANCELLED, None, "cancelled"))
            results["cancelled"] = actions()
            page._display_libreoffice_result(AcquisitionResult(AcquisitionStatus.FAILED, None, "network_failure"))
            results["failure"] = actions()
            page._display_libreoffice_result(AcquisitionResult(AcquisitionStatus.INSTALLED, Path.cwd(), "installed"))
            results["installed"] = actions()
            results["installed_text"] = page.component_status_labels[ComponentId.LIBREOFFICE].cget("text")
            root.destroy()
            print(json.dumps(results))
        """
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if result.stdout.strip().startswith("SKIP_TK:"):
            self.skipTest(result.stdout.strip())
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout.strip().splitlines()[-1])
        for theme in ("Light", "Dark"):
            self.assertEqual(values[theme + "_missing"], [True, True, False])
            self.assertEqual(values[theme + "_ready"], [False, False, False])
            self.assertEqual(values[theme + "_text"], "Pronto para uso")
            self.assertEqual(values[theme + "_extra_text"], "")
            self.assertEqual(values[theme + "_invalid"], [True, True, True])
        for state in (
            "initial",
            "download",
            "concurrent_refresh",
            "installer",
            "installed",
        ):
            self.assertEqual(values[state], [False, False, False], state)
        self.assertEqual(values["pending"], [False, False, True])
        self.assertEqual(values["cancelled"], [True, True, False])
        self.assertEqual(values["failure"], [True, True, True])
        self.assertEqual(values["installed_text"], "Pronto para uso")

    def test_settings_remain_reachable_after_resize_and_dynamic_status(self) -> None:
        script = r"""
            import json
            import tkinter as tk

            import customtkinter as ctk

            from component_manager import ComponentManager, ComponentState
            from ui_pages import SettingsPage

            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print("SKIP_TK:" + type(error).__name__)
                raise SystemExit(0)
            root.grid_columnconfigure(1, weight=1)
            root.grid_rowconfigure(0, weight=1)
            sidebar = ctk.CTkFrame(root, width=200)
            sidebar.grid(row=0, column=0, sticky="ns")
            sidebar.grid_propagate(False)
            page = SettingsPage(
                root,
                theme_value="Claro",
                change_theme=lambda _value: None,
                component_manager=ComponentManager(),
                component_updater=object(),
                component_installer=object(),
                select_existing_component=lambda: None,
            )
            page.grid(row=0, column=1, sticky="nsew")
            page.diagnostics_button.invoke()
            page._set_libreoffice_actions(ComponentState.FAILED)
            canvas = page._parent_canvas

            def inspect(height):
                root.geometry(f"1040x{height}")
                root.update()
                initial_view = canvas.yview()
                canvas.yview_moveto(1.0)
                root.update()
                bottom = (
                    page.libreoffice_existing_button.winfo_rooty()
                    + page.libreoffice_existing_button.winfo_height()
                )
                viewport_bottom = canvas.winfo_rooty() + canvas.winfo_height()
                result = {
                    "scroll_needed": initial_view[1] < 0.99,
                    "bottom_reached": canvas.yview()[1] >= 0.99,
                    "last_control_visible": bottom <= viewport_bottom + 2,
                    "sidebar_fixed": sidebar.winfo_width() == 200,
                }
                canvas.yview_moveto(0.0)
                return result

            results = {}
            for theme in ("Light", "Dark"):
                ctk.set_appearance_mode(theme)
                results[theme] = {
                    "large": inspect(900),
                    "regular": inspect(800),
                    "notebook": inspect(650),
                    "minimum": inspect(600),
                }
            page.libreoffice_status.configure(text="\n".join(["Status dinâmico"] * 10))
            results["dynamic"] = inspect(600)
            results["controls"] = {
                "appearance": all(button.winfo_exists() for button in page.theme_buttons.values()),
                "components": len(page.component_status_labels),
                "refresh": page.components_refresh_button.winfo_exists(),
                "yt_dlp_update": page.update_check_button.winfo_exists(),
                "libreoffice_install": page.libreoffice_install_button.winfo_exists(),
                "libreoffice_existing": page.libreoffice_existing_button.winfo_exists(),
            }
            root.destroy()
            print(json.dumps(results))
        """
        completed = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if completed.stdout.strip().startswith("SKIP_TK:"):
            self.skipTest(completed.stdout.strip())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        results = json.loads(completed.stdout.strip().splitlines()[-1])
        for theme in ("Light", "Dark"):
            for size in ("large", "regular", "notebook", "minimum"):
                self.assertTrue(
                    all(
                        results[theme][size][check]
                        for check in (
                            "bottom_reached",
                            "last_control_visible",
                            "sidebar_fixed",
                        )
                    ),
                    (theme, size, results),
                )
            self.assertTrue(results[theme]["notebook"]["scroll_needed"])
            self.assertTrue(results[theme]["minimum"]["scroll_needed"])
        self.assertTrue(all(results["dynamic"].values()), results)
        self.assertEqual(results["controls"]["components"], 5)
        self.assertTrue(
            all(
                value
                for key, value in results["controls"].items()
                if key != "components"
            ),
            results,
        )

    def test_invalid_managed_libreoffice_offers_explicit_guided_repair(self) -> None:
        script = r"""
            import json
            import time
            import tkinter as tk
            from dataclasses import replace

            import customtkinter as ctk
            from component_manager import ComponentId, ComponentManager, ComponentOrigin, ComponentState
            from libreoffice_managed import AcquisitionResult, AcquisitionStatus
            from ui_pages import SettingsPage

            class Manager:
                def list_components(self):
                    return ComponentManager().list_components()
                def refresh(self, component_id):
                    assert component_id is ComponentId.LIBREOFFICE
                    return replace(
                        ComponentManager().get_component(component_id),
                        origin=ComponentOrigin.MANAGED,
                        state=ComponentState.INVALID,
                    )

            class Installer:
                def __init__(self):
                    self.repair = None
                def install(self, **kwargs):
                    self.repair = kwargs.get("repair")
                    return AcquisitionResult(AcquisitionStatus.CANCELLED, None, "cancelled")

            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print("SKIP_TK:" + type(error).__name__)
                raise SystemExit(0)
            root.withdraw()
            installer = Installer()
            confirmations = []
            page = SettingsPage(
                root, theme_value="Escuro", change_theme=lambda _value: None,
                component_manager=Manager(),
                component_installer=installer,
                confirm_component_install=lambda message: confirmations.append(message) or True,
                activate_managed_component=lambda _path: True,
            )
            page.pack()
            page.start_libreoffice_install()
            deadline = time.monotonic() + 3
            while installer.repair is None and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            print(json.dumps({"repair": installer.repair, "message": confirmations[0]}))
            page.destroy()
            root.destroy()
        """
        completed = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if completed.stdout.strip().startswith("SKIP_TK:"):
            self.skipTest(completed.stdout.strip())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertTrue(result["repair"])
        self.assertIn("instalação anterior será preservada", result["message"])

    def test_libreoffice_install_is_opt_in_and_updates_status_after_validation(
        self,
    ) -> None:
        script = r"""
            import json
            import tempfile
            import time
            import tkinter as tk
            from dataclasses import replace
            from pathlib import Path
            from unittest.mock import patch

            import customtkinter as ctk

            from component_manager import ComponentId, ComponentManager, ComponentState
            from libreoffice_managed import AcquisitionResult, AcquisitionStatus
            from ui_pages import SettingsPage

            class Manager:
                def __init__(self):
                    self.items = ComponentManager().list_components()
                    self.installed = False
                def list_components(self):
                    return self.items
                def refresh(self, component):
                    assert component is ComponentId.LIBREOFFICE
                    item = next(item for item in self.items if item.component_id is component)
                    if self.installed:
                        return replace(item, state=ComponentState.READY, detail="Pronto")
                    return replace(item, state=ComponentState.NOT_CONFIGURED, detail="Não encontrado")

            class Installer:
                def __init__(self, base):
                    self.base = base
                    self.calls = 0
                def install(self, *, cancel, phase, progress):
                    self.calls += 1
                    phase("download")
                    progress(1, 2)
                    phase("installer")
                    phase("installer_opened")
                    phase("verify")
                    return AcquisitionResult(AcquisitionStatus.INSTALLED, self.base, "installed")
                def destination_parent(self, path):
                    return path
                def verify_installation(self, path):
                    return AcquisitionResult(AcquisitionStatus.INSTALLED, path, "installed")

            class CancellableInstaller:
                def __init__(self):
                    self.calls = 0
                def install(self, *, cancel, phase, progress):
                    self.calls += 1
                    phase("download")
                    cancel.wait(2)
                    return AcquisitionResult(AcquisitionStatus.CANCELLED, None, "cancelled")

            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print("SKIP_TK:" + type(error).__name__)
                raise SystemExit(0)
            root.withdraw()
            with tempfile.TemporaryDirectory() as directory:
                manager = Manager()
                installer = Installer(Path(directory))
                confirmations = []
                activated = []
                def confirm(message):
                    confirmations.append(message)
                    return len(confirmations) > 1
                def activate(path):
                    activated.append(path)
                    manager.installed = True
                    return True
                page = SettingsPage(
                    root, theme_value="Escuro", change_theme=lambda value: None,
                    component_manager=manager,
                    component_installer=installer, confirm_component_install=confirm,
                    activate_managed_component=activate,
                )
                page.pack()
                opened_messages = []
                display_phase = page._display_libreoffice_phase
                def observe_phase(phase):
                    display_phase(phase)
                    if phase == "installer_opened":
                        opened_messages.append(page.libreoffice_status.cget("text"))
                page._display_libreoffice_phase = observe_phase
                initial = installer.calls
                page.libreoffice_install_button.invoke()
                deadline = time.monotonic() + 3
                while not confirmations and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                declined = installer.calls == 0
                page.libreoffice_install_button.invoke()
                deadline = time.monotonic() + 3
                while installer.calls == 0 and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                ready = page._install_ready_parent is None
                copied = not page.libreoffice_copy_button.winfo_ismapped()
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    root.update()
                    if "pronto" in page.component_status_labels[ComponentId.LIBREOFFICE].cget("text").lower():
                        break
                    time.sleep(0.01)
                page.libreoffice_install_button.invoke()
                result = dict(
                    initial=initial, declined=declined, calls=installer.calls,
                    confirmations=confirmations, activated=len(activated),
                    status=page.component_status_labels[ComponentId.LIBREOFFICE].cget("text"),
                    opened_message=opened_messages[0],
                    cancel_hidden=not page.libreoffice_cancel_button.winfo_ismapped(),
                    ready=ready, copied=copied,
                )
                page.destroy()

                cancel_installer = CancellableInstaller()
                cancel_page = SettingsPage(
                    root, theme_value="Escuro", change_theme=lambda value: None,
                    component_manager=Manager(),
                    component_installer=cancel_installer,
                    confirm_component_install=lambda _message: True,
                    activate_managed_component=lambda _path: False,
                )
                cancel_page.pack()
                cancel_page.libreoffice_install_button.invoke()
                deadline = time.monotonic() + 3
                while cancel_installer.calls == 0 and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                cancel_page.libreoffice_cancel_button.invoke()
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    root.update()
                    if "não concluída" in cancel_page.libreoffice_status.cget("text"):
                        break
                    time.sleep(0.01)
                result["cancel_calls"] = cancel_installer.calls
                result["cancel_message"] = cancel_page.libreoffice_status.cget("text")
                cancel_page.destroy()

                recovery_installer = Installer(Path(directory))
                recovery_manager = Manager()
                recovered = []
                recovery_page = SettingsPage(
                    root, theme_value="Escuro", change_theme=lambda _value: None,
                    component_manager=recovery_manager,
                    component_installer=recovery_installer,
                    confirm_component_install=lambda _message: True,
                    activate_managed_component=lambda path: recovered.append(path) or True,
                )
                recovery_page.pack()
                with patch("ui_pages.filedialog.askdirectory", return_value=directory):
                    recovery_page._choose_libreoffice_destination()
                recovery_page._display_libreoffice_result(
                    AcquisitionResult(AcquisitionStatus.FAILED, None, "installed_structure_invalid")
                )
                result["missing_destination_message"] = recovery_page.libreoffice_status.cget("text")
                recovery_page._verify_libreoffice_installation()
                deadline = time.monotonic() + 3
                while not recovered and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                result["manual_verify_recovered"] = recovered == [Path(directory)]
                recovery_page.destroy()
            root.destroy()
            print(json.dumps(result))
        """
        completed = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertEqual(result["initial"], 0)
        self.assertTrue(result["declined"])
        self.assertEqual(result["calls"], 1)
        self.assertEqual(result["activated"], 1)
        self.assertTrue(result["ready"] and result["copied"])
        self.assertEqual(len(result["confirmations"]), 2)
        self.assertIn("MSI oficial verificado", result["confirmations"][0])
        self.assertIn("sem instalar no sistema", result["confirmations"][0])
        self.assertIn("pronto", result["status"].lower())
        self.assertIn("janela oficial", result["opened_message"])
        self.assertTrue(result["cancel_hidden"])
        self.assertEqual(result["cancel_calls"], 1)
        self.assertIn("não concluída", result["cancel_message"])
        self.assertIn(
            "Não foi possível encontrar", result["missing_destination_message"]
        )
        self.assertTrue(result["manual_verify_recovered"])

    def test_yt_dlp_update_requires_check_and_confirmation_and_reports_result(
        self,
    ) -> None:
        script = r"""
            import json
            import tempfile
            import time
            import tkinter as tk
            from dataclasses import replace
            from pathlib import Path
            from unittest.mock import patch

            import customtkinter as ctk

            from component_manager import ComponentManager, ComponentId, ComponentState
            from paths import ManagedRootCheck, ManagedRootState
            from ui_pages import SettingsPage
            from yt_dlp_update import (
                OfficialRelease, UpdateCheck, UpdateCheckStatus,
                UpdateResult, UpdateStatus,
            )

            class Manager:
                def __init__(self):
                    self.items = ComponentManager().list_components()
                    self.refreshes = 0
                def list_components(self):
                    return self.items
                def refresh(self, component):
                    assert component is ComponentId.YT_DLP
                    self.refreshes += 1
                    return replace(
                        self.items[0], state=ComponentState.READY,
                        version="2026.09.01", detail="Pronto"
                    )

            class Updater:
                def __init__(self, base):
                    self.base_dir = base
                    self.checks = 0
                    self.updates = 0
                    self.available = False
                    self.mode = "success"
                    self.release = OfficialRelease(
                        "2026.09.01", "", 1, "0" * 64, "", "0" * 64, "", ""
                    )
                def check(self):
                    self.checks += 1
                    status = (
                        UpdateCheckStatus.UPDATE_AVAILABLE if self.available
                        else UpdateCheckStatus.UP_TO_DATE
                    )
                    return UpdateCheck(status, "2026.08.19", self.release)
                def update(self, release, *, cancel, progress):
                    self.updates += 1
                    if self.mode == "cancel":
                        if cancel.wait(2):
                            return UpdateResult(UpdateStatus.CANCELLED, None, "cancelled")
                        return UpdateResult(UpdateStatus.FAILED, None, "cancel_not_received")
                    progress(1, 2)
                    return UpdateResult(UpdateStatus.UPDATED, release.version, "updated")

            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print("SKIP_TK:" + type(error).__name__)
                raise SystemExit(0)
            root.withdraw()
            with tempfile.TemporaryDirectory() as directory:
                updater = Updater(Path(directory))
                manager = Manager()
                confirmations = []
                def confirm(message):
                    confirmations.append(message)
                    return len(confirmations) > 1
                page = SettingsPage(
                    root, theme_value="Escuro", change_theme=lambda value: None,
                    component_manager=manager,
                    component_updater=updater, confirm_component_update=confirm,
                )
                page.pack()
                def wait_for(value):
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        root.update()
                        if page.update_status.cget("text") == value:
                            return True
                        time.sleep(0.01)
                    return False
                initial_calls = (updater.checks, updater.updates)
                page.update_check_button.invoke()
                current = wait_for("yt-dlp atualizado.")
                updater.available = True
                page.update_check_button.invoke()
                available = wait_for("Nova versão disponível: 2026.09.01")
                page._display_yt_dlp_check(
                    UpdateCheck(
                        UpdateCheckStatus.CHECK_FAILED,
                        "2026.08.19",
                        None,
                        "connection_unavailable",
                    ),
                    storage=None,
                )
                offline_keeps_local_ready = (
                    page._component_states[ComponentId.YT_DLP] is ComponentState.READY
                    and "Conexão indisponível" in page.update_status.cget("text")
                    and not page.update_action_button.winfo_ismapped()
                    and page._available_release is None
                )
                page._display_yt_dlp_check(
                    UpdateCheck(UpdateCheckStatus.UPDATE_AVAILABLE, "2026.08.19", updater.release),
                    storage=ManagedRootCheck(Path(directory), ManagedRootState.AVAILABLE),
                )
                page.update_action_button.invoke()
                declined = updater.updates == 0
                page.update_action_button.invoke()
                updated = wait_for("Atualização concluída.")
                page.update_check_button.invoke()
                wait_for("Nova versão disponível: 2026.09.01")
                updater.mode = "cancel"
                page.update_action_button.invoke()
                deadline = time.monotonic() + 2
                while updater.updates < 2 and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                disabled_while_running = page.update_check_button.cget("state") == "disabled"
                page.update_cancel_button.invoke()
                cancelled = wait_for("Atualização cancelada; versão anterior preservada.")
                page._display_yt_dlp_check(
                    UpdateCheck(UpdateCheckStatus.UPDATE_AVAILABLE, "2026.08.19", updater.release),
                    storage=ManagedRootCheck(
                        Path(directory) / "Componentes", ManagedRootState.READ_ONLY
                    ),
                )
                storage_blocked = (
                    "não permite instalar" in page.update_status.cget("text")
                    and not page.update_action_button.winfo_ismapped()
                )
                result = dict(
                    initial_calls=initial_calls, current=current,
                    available=available, declined=declined, updated=updated,
                    checks=updater.checks, updates=updater.updates,
                    cancelled=cancelled,
                    disabled_while_running=disabled_while_running,
                    storage_blocked=storage_blocked,
                    offline_keeps_local_ready=offline_keeps_local_ready,
                    version_visible="Versão 2026.09.01" in page.component_status_labels[ComponentId.YT_DLP].cget("text"),
                    confirmations=confirmations, refreshes=manager.refreshes,
                    action_hidden=not page.update_action_button.winfo_ismapped(),
                    cancel_hidden=not page.update_cancel_button.winfo_ismapped(),
                )
            root.destroy()
            print(json.dumps(result))
        """
        completed = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertEqual(result["initial_calls"], [0, 0])
        self.assertTrue(
            all(
                result[key]
                for key in (
                    "current",
                    "available",
                    "declined",
                    "updated",
                    "cancelled",
                    "disabled_while_running",
                    "storage_blocked",
                    "offline_keeps_local_ready",
                    "version_visible",
                    "action_hidden",
                    "cancel_hidden",
                )
            )
        )
        self.assertEqual((result["checks"], result["updates"]), (3, 2))
        self.assertEqual(result["refreshes"], 2)
        self.assertEqual(len(result["confirmations"]), 3)

    def test_rows_local_refresh_error_and_theme(self) -> None:
        script = r"""
            import json
            import time
            import tkinter as tk
            from dataclasses import replace

            import customtkinter as ctk

            from component_manager import ComponentManager, ComponentState
            from ui_pages import SettingsPage

            class StubManager:
                def __init__(self):
                    self.items = ComponentManager().list_components()
                    self.calls = 0
                def list_components(self):
                    return self.items
                def refresh_all(self):
                    self.calls += 1
                    if self.calls == 2:
                        raise RuntimeError("synthetic error")
                    self.items = tuple(
                        replace(item, state=ComponentState.READY, detail="Pronto")
                        if item.required else
                        replace(item, state=ComponentState.NOT_CONFIGURED, detail="Não configurado")
                        for item in self.items
                    )
                    return self.items

            try:
                root = ctk.CTk()
            except tk.TclError as error:
                print("SKIP_TK:" + type(error).__name__)
                raise SystemExit(0)
            root.withdraw()
            manager = StubManager()
            page = SettingsPage(
                root,
                theme_value="Escuro",
                change_theme=lambda value: None,
                component_manager=manager,
            )
            page.pack()
            initial = [label.cget("text") for label in page.component_status_labels.values()]
            def complete():
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    root.update()
                    if page.components_refresh_button.cget("state") == "normal":
                        return True
                    time.sleep(0.01)
                return False
            ctk.set_appearance_mode("Dark")
            page.components_refresh_button.invoke()
            refreshing = (
                page.components_refresh_button.cget("state"),
                page.components_refresh_button.cget("text"),
            )
            first_done = complete()
            first = [label.cget("text") for label in page.component_status_labels.values()]
            ctk.set_appearance_mode("Light")
            page.components_refresh_button.invoke()
            second_done = complete()
            second = [label.cget("text") for label in page.component_status_labels.values()]
            failed_colors = [
                label.cget("text_color") for label in page.component_status_labels.values()
            ]
            result = dict(
                labels=[item.display_name for item in manager.items],
                initial=initial,
                refreshing=refreshing,
                first=first,
                second=second,
                failed_colors=failed_colors,
                first_done=first_done,
                second_done=second_done,
                calls=manager.calls,
                button=page.components_refresh_button.cget("text"),
                theme=ctk.get_appearance_mode(),
            )
            root.destroy()
            print(json.dumps(result))
        """
        completed = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        stdout = completed.stdout.strip()
        if stdout.startswith("SKIP_TK:"):
            self.skipTest(stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(stdout.splitlines()[-1])
        self.assertEqual(
            result["labels"],
            [
                "yt-dlp",
                "Deno",
                "FFmpeg / FFprobe",
                "LibreOffice",
                "OCR e modelos de idioma",
            ],
        )
        self.assertEqual(result["initial"], ["Ainda não verificado"] * 5)
        self.assertEqual(result["refreshing"], ["disabled", "Verificando..."])
        self.assertEqual(result["first"], ["Pronto"] * 3 + ["Não configurado"] * 2)
        self.assertEqual(
            result["second"], ["Não foi possível verificar. Tente novamente."] * 5
        )
        self.assertEqual(result["failed_colors"], [["#53687B", "#ADBED0"]] * 5)
        self.assertTrue(result["first_done"] and result["second_done"])
        self.assertEqual(result["calls"], 2)
        self.assertEqual(result["button"], "Verificar componentes")
        self.assertEqual(result["theme"], "Light")
