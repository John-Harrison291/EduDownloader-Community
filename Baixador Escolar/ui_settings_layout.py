"""Composição visual de Configurações. Os serviços pertencem ao controlador."""

import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from component_manager import ComponentId, ComponentState
from constants import DEFAULT_TEXT_SCALE, TEXT_SCALE_LEVELS
from ui_feedback import PanelReveal, ProgressBar
from ui_design import (
    CARD_INSET,
    ERROR_TEXT,
    ITEM_GAP,
    LINK,
    MUTED,
    ON_PRIMARY,
    PAGE_INSET,
    PRIMARY,
    PRIMARY_HOVER,
    SECTION_GAP,
    SOFT,
    SOFT_HOVER,
    SURFACE,
    TEXT,
    surface,
    wrap_to_frame,
)


_SUCCESS = ("#18794E", "#55CC91")
_WARNING = ("#845000", "#F0B35A")
_COMPONENT_STATES = {
    ComponentState.NOT_CHECKED: ("Não verificado", MUTED),
    ComponentState.NOT_CONFIGURED: ("Não configurado", MUTED),
    ComponentState.READY: ("Pronto", _SUCCESS),
    ComponentState.MISSING: ("Ausente", _WARNING),
    ComponentState.INVALID: ("Inválido", ERROR_TEXT),
    ComponentState.VERSION_MISMATCH: ("Versão incompatível", _WARNING),
    ComponentState.CORRUPTED: ("Corrompido", ERROR_TEXT),
    ComponentState.FAILED: ("Erro de verificação", ERROR_TEXT),
}


class SettingsLayout:
    """Organiza as preferências e mantém os controles de diagnóstico montados."""

    def _mount_settings(
        self,
        design,
        *,
        theme_value,
        change_theme,
        text_scale,
        change_text_scale,
        choose_download_folder,
        snapshots,
        select_existing_component,
    ):
        self._settings_design = design
        self._change_text_scale = change_text_scale
        self._text_scale = text_scale
        self._component_states = {}
        self.grid_columnconfigure(0, weight=1)
        heading = ctk.CTkFrame(self, fg_color="transparent")
        heading.grid(
            row=0, column=0, padx=PAGE_INSET, pady=(PAGE_INSET, 0), sticky="ew"
        )
        design.label(heading, "Configurações", font=design.title).pack(anchor="w")
        subtitle = design.label(
            heading,
            "Ajuste o aplicativo conforme suas preferências.",
            color=MUTED,
            wraplength=420,
        )
        subtitle.pack(fill="x", pady=(4, 0))
        wrap_to_frame(heading, subtitle, reserved=0)

        last_card = self._mount_appearance(theme_value, change_theme)
        if choose_download_folder is not None:
            last_card = self._mount_download_folder(choose_download_folder)
        if snapshots:
            last_card = self._mount_diagnostics(snapshots, select_existing_component)
        last_card.grid_configure(pady=(SECTION_GAP, PAGE_INSET))

    def _settings_card(self, row):
        card = surface(self)
        card.grid(
            row=row, column=0, padx=PAGE_INSET, pady=(SECTION_GAP, 0), sticky="ew"
        )
        card.grid_columnconfigure(0, weight=1)
        return card

    def _card_action(self, card, title, description, action, command):
        design = self._settings_design
        copy = ctk.CTkFrame(card, fg_color="transparent", width=1)
        copy.grid(
            row=0, column=0, sticky="ew", padx=(CARD_INSET, ITEM_GAP), pady=CARD_INSET
        )
        heading = design.label(copy, title, font=design.card_title, wraplength=230)
        heading.pack(fill="x")
        detail = design.label(
            copy,
            description,
            font=design.small,
            color=MUTED,
            wraplength=230,
        )
        detail.pack(fill="x", pady=(3, 0))
        wrap_to_frame(copy, heading, detail, reserved=0)
        button = design.button(
            card, action, command, kind="secondary", keyboard=True, width=190
        )
        button.grid(row=0, column=1, sticky="e", padx=(0, CARD_INSET), pady=CARD_INSET)
        return button

    def _mount_appearance(self, theme_value, change_theme):
        design = self._settings_design
        card = self._settings_card(1)
        design.label(card, "Aparência", font=design.heading).grid(
            row=0,
            column=0,
            columnspan=2,
            padx=CARD_INSET,
            pady=(CARD_INSET, 0),
            sticky="w",
        )
        theme_copy = ctk.CTkFrame(card, fg_color="transparent", width=1)
        theme_copy.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(CARD_INSET, ITEM_GAP),
            pady=(ITEM_GAP, 0),
        )
        design.label(theme_copy, "Tema do aplicativo", font=design.nav).pack(anchor="w")
        hint = design.label(
            theme_copy,
            "Escolha a aparência mais confortável.",
            font=design.small,
            color=MUTED,
            wraplength=185,
        )
        hint.pack(fill="x")
        wrap_to_frame(theme_copy, hint, reserved=0)
        themes = ctk.CTkFrame(card, fg_color="transparent")
        themes.grid(
            row=1, column=1, sticky="e", padx=(0, CARD_INSET), pady=(ITEM_GAP, 0)
        )
        self.theme_buttons = {}

        def select_theme(theme):
            self.show_theme(theme)
            change_theme(theme)

        for theme in ("Claro", "Escuro"):
            button = design.button(
                themes,
                f"Modo {theme}",
                lambda name=theme: select_theme(name),
                kind="secondary",
                keyboard=True,
                width=124,
            )
            button.pack(side="left", padx=(8 if self.theme_buttons else 0, 0))
            self.theme_buttons[theme] = button
        self.show_theme(theme_value)

        scale_copy = ctk.CTkFrame(card, fg_color="transparent")
        scale_copy.grid(row=2, column=0, sticky="w", padx=CARD_INSET, pady=ITEM_GAP)
        design.label(scale_copy, "Tamanho do texto", font=design.nav).pack(anchor="w")
        self.text_scale_status = tk.StringVar(master=self)
        design.form_label(
            scale_copy,
            textvariable=self.text_scale_status,
            font=design.small,
            text_color=MUTED,
        ).pack(anchor="w")
        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(row=2, column=1, sticky="e", padx=(0, CARD_INSET), pady=ITEM_GAP)
        self.text_scale_decrease = design.button(
            controls,
            "A−",
            lambda: self._step_text_scale(-1),
            kind="secondary",
            keyboard=True,
            width=64,
        )
        self.text_scale_increase = design.button(
            controls,
            "A+",
            lambda: self._step_text_scale(1),
            kind="secondary",
            keyboard=True,
            width=64,
        )
        self.text_scale_reset = design.button(
            controls,
            "Restaurar padrão",
            lambda: self._select_text_scale(DEFAULT_TEXT_SCALE),
            kind="link",
            keyboard=True,
            width=124,
        )
        for index, button in enumerate(
            (
                self.text_scale_decrease,
                self.text_scale_increase,
                self.text_scale_reset,
            )
        ):
            button.pack(side="left", padx=(8 if index else 0, 0))
        self.show_text_scale(self._text_scale)

        self._persistence_status = tk.StringVar(master=self)
        self.persistence_label = design.form_label(
            card,
            textvariable=self._persistence_status,
            text_color=ERROR_TEXT,
            wraplength=400,
        )
        self.persistence_label.grid(
            row=3,
            column=0,
            columnspan=2,
            padx=CARD_INSET,
            pady=(0, ITEM_GAP),
            sticky="ew",
        )
        self.persistence_label.grid_remove()
        wrap_to_frame(card, self.persistence_label, reserved=2 * CARD_INSET)
        return card

    def show_theme(self, theme):
        for name, button in self.theme_buttons.items():
            selected = name == theme
            button.configure(
                fg_color=PRIMARY if selected else SOFT,
                hover_color=PRIMARY_HOVER if selected else SOFT_HOVER,
                text_color=ON_PRIMARY if selected else TEXT,
            )

    def _step_text_scale(self, step):
        index = TEXT_SCALE_LEVELS.index(self._text_scale) + step
        if 0 <= index < len(TEXT_SCALE_LEVELS):
            self._select_text_scale(TEXT_SCALE_LEVELS[index])

    def _select_text_scale(self, scale):
        if self._change_text_scale is not None and scale != self._text_scale:
            self._change_text_scale(scale)

    def show_text_scale(self, scale):
        self._text_scale = scale
        self.text_scale_status.set(
            "Padrão (100%)" if scale == DEFAULT_TEXT_SCALE else f"{scale}%"
        )
        for button, enabled in (
            (self.text_scale_decrease, scale > TEXT_SCALE_LEVELS[0]),
            (self.text_scale_increase, scale < TEXT_SCALE_LEVELS[-1]),
            (self.text_scale_reset, scale != DEFAULT_TEXT_SCALE),
        ):
            button.configure(
                state="normal" if enabled and self._change_text_scale else "disabled"
            )

    def _mount_download_folder(self, command):
        design = self._settings_design
        card = self._settings_card(2)
        self.download_folder_path = tk.StringVar(master=self)
        design.label(card, "Salvar arquivos em", font=design.card_title).grid(
            row=0, column=0, padx=CARD_INSET, pady=(CARD_INSET, ITEM_GAP), sticky="w"
        )
        self.download_folder_button = design.button(
            card,
            "Alterar pasta",
            command,
            kind="secondary",
            keyboard=True,
            width=190,
        )
        self.download_folder_button.grid(
            row=0,
            column=1,
            padx=(0, CARD_INSET),
            pady=(CARD_INSET, ITEM_GAP),
            sticky="e",
        )
        self.download_folder_entry = design.form_entry(
            card, width=1, textvariable=self.download_folder_path, state="readonly"
        )
        self.download_folder_entry.grid(
            row=1,
            column=0,
            columnspan=2,
            padx=CARD_INSET,
            pady=(0, CARD_INSET),
            sticky="ew",
        )
        return card

    def show_download_destination(self, path: Path | None, *, default=False):
        if path is None:
            self.download_folder_path.set("Pasta padrão indisponível")
        else:
            self.download_folder_path.set(f"{path} (padrão)" if default else str(path))

    def _mount_diagnostics(self, snapshots, select_existing):
        design = self._settings_design
        card = self._settings_card(3)
        self.diagnostics_button = self._card_action(
            card,
            "Precisa de ajuda com algum componente?",
            "Verifique os componentes quando uma ferramenta apresentar erro.",
            "Ver diagnóstico",
            self._toggle_diagnostics,
        )
        frame = ctk.CTkFrame(card, fg_color="transparent", width=1, height=1)
        frame.grid(
            row=1,
            column=0,
            columnspan=2,
            padx=CARD_INSET,
            pady=(0, CARD_INSET),
            sticky="ew",
        )
        frame.grid_remove()
        self.diagnostics_panel = frame
        self._diagnostics_expanded = False
        self._diagnostic_motion = None
        panel = frame
        if design.motion is not None:
            panel = ctk.CTkFrame(frame, fg_color="transparent", width=1, height=1)
            self._diagnostic_motion = PanelReveal(
                frame, panel, self.diagnostics_button, design.motion
            )
        panel.grid_columnconfigure(0, weight=1)
        self.components_refresh_button = design.button(
            panel,
            "Verificar componentes",
            self._refresh_components,
            keyboard=True,
            width=205,
        )
        self.components_refresh_button.grid(
            row=0, column=0, sticky="w", pady=(0, ITEM_GAP)
        )

        for row, snapshot in enumerate(snapshots, start=1):
            tile = ctk.CTkFrame(panel, fg_color=SOFT, corner_radius=12)
            tile.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            tile.grid_columnconfigure(0, weight=1)
            design.label(tile, snapshot.display_name, font=design.control).grid(
                row=0, column=0, sticky="w", padx=ITEM_GAP, pady=(12, 2)
            )
            indicator = design.form_label(tile, font=design.control)
            indicator.grid(row=0, column=1, sticky="e", padx=ITEM_GAP, pady=(12, 2))
            detail = design.form_label(
                tile, text=snapshot.detail, text_color=MUTED, wraplength=320
            )
            detail.grid(
                row=1, column=0, columnspan=2, padx=ITEM_GAP, pady=(0, 10), sticky="ew"
            )
            wrap_to_frame(tile, detail, reserved=2 * ITEM_GAP)
            self.component_status_labels[snapshot.component_id] = detail
            self.component_state_labels[snapshot.component_id] = indicator
            self.show_component_indicator(snapshot.component_id, snapshot.state)
            if (
                snapshot.component_id is ComponentId.YT_DLP
                and self._component_updater is not None
            ):
                self._mount_yt_dlp_actions(tile)
            if (
                snapshot.component_id is ComponentId.LIBREOFFICE
                and self._component_installer is not None
            ):
                self._mount_libreoffice_actions(tile, select_existing)
            if (
                self._release_observer is not None
                and snapshot.component_id is not ComponentId.YT_DLP
            ):
                actions = ctk.CTkFrame(tile, fg_color="transparent", width=1, height=1)
                actions.grid(
                    row=6,
                    column=0,
                    columnspan=2,
                    sticky="ew",
                    padx=ITEM_GAP,
                    pady=(0, 6),
                )
                component_id = snapshot.component_id
                self.release_check_buttons[component_id] = self._component_button(
                    actions,
                    "Verificar atualização",
                    lambda key=component_id: self._check_component_release(key),
                    0,
                    0,
                    visible=True,
                )
                if getattr(self, "_managed_updater", None) is not None:
                    self.release_update_buttons[component_id] = self._component_button(
                        actions,
                        "Atualizar",
                        lambda key=component_id: self._start_managed_update(key),
                        0,
                        1,
                        visible=False,
                    )
                    self.release_cancel_buttons[component_id] = self._component_button(
                        actions,
                        "Cancelar",
                        self._update_cancel.set,
                        0,
                        2,
                        visible=False,
                    )
                self.release_status_labels[component_id] = self._operation_label(
                    tile, 7
                )
                self.release_status_labels[component_id].grid_remove()
        return card

    def set_diagnostics_open(self, open_panel: bool) -> None:
        self._diagnostics_expanded = open_panel
        if self._diagnostic_motion is not None:
            self._diagnostic_motion.set_expanded(open_panel)
        elif open_panel:
            self.diagnostics_panel.grid()
        else:
            self.diagnostics_panel.grid_remove()
        self.diagnostics_button.configure(
            text="Ocultar diagnóstico" if open_panel else "Ver diagnóstico"
        )

    def _toggle_diagnostics(self):
        self.set_diagnostics_open(not self._diagnostics_expanded)

    def reveal_diagnostics_focus(self, widget):
        motion = getattr(self, "_diagnostic_motion", None)
        if motion is not None:
            motion.reveal_focus(widget)

    def show_component_indicator(self, component_id, state=None, *, checking=False):
        if checking:
            message, tone = "Verificando…", LINK
        else:
            self._component_states[component_id] = state
            message, tone = _COMPONENT_STATES[state]
        self.component_state_labels[component_id].configure(
            text=message, text_color=tone
        )

    def _component_actions(self, tile):
        actions = ctk.CTkFrame(tile, fg_color="transparent", width=1, height=1)
        actions.grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=ITEM_GAP, pady=(0, 6)
        )
        return actions

    def _component_button(
        self, actions, text, command, row, column, *, visible=False, primary=False
    ):
        button = self._settings_design.button(
            actions,
            text,
            command,
            keyboard=True,
            height=38,
            kind="primary" if primary else "secondary",
            width=60,
        )
        if not primary:
            button.configure(fg_color=SURFACE)
        button.grid(
            row=row, column=column, sticky="w", padx=(0, 8), pady=(0, 6), ipadx=6
        )
        if not visible:
            button.grid_remove()
        return button

    def _operation_label(self, tile, row):
        label = self._settings_design.form_label(
            tile,
            text="",
            text_color=MUTED,
            wraplength=320,
        )
        label.grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=ITEM_GAP, pady=(0, 6)
        )
        wrap_to_frame(tile, label, reserved=2 * ITEM_GAP)
        return label

    def _operation_progress(self, tile):
        progress = ProgressBar(tile, fg_color=SOFT_HOVER, progress_color=PRIMARY)
        progress.grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=ITEM_GAP, pady=(0, 8)
        )
        progress.grid_remove()
        return progress

    def _mount_yt_dlp_actions(self, tile):
        actions = self._component_actions(tile)
        self.update_check_button = self._component_button(
            actions,
            "Verificar atualização",
            self._check_yt_dlp_update,
            0,
            0,
            visible=True,
        )
        self.update_action_button = self._component_button(
            actions, "Atualizar", self._start_yt_dlp_update, 0, 1, primary=True
        )
        self.update_cancel_button = self._component_button(
            actions, "Cancelar", self._update_cancel.set, 0, 1
        )
        self.update_repair_button = self._component_button(
            actions, "Usar versão original do yt-dlp", self._repair_yt_dlp, 1, 0
        )
        self.update_progress = self._operation_progress(tile)
        self.update_status = self._operation_label(tile, 4)
        self.update_status.grid_remove()

    def _mount_libreoffice_actions(self, tile, select_existing):
        actions = self._component_actions(tile)
        button = self._component_button
        self.libreoffice_install_button = button(
            actions,
            "Instalar LibreOffice",
            self.start_libreoffice_install,
            0,
            0,
            primary=True,
        )
        self.libreoffice_existing_button = button(
            actions, "Localizar LibreOffice", select_existing, 0, 1
        )
        self.libreoffice_cancel_button = button(
            actions, "Cancelar", self._cancel_libreoffice_install, 0, 0
        )
        self.libreoffice_choose_button = button(
            actions, "Escolher outra pasta", self._choose_libreoffice_destination, 1, 0
        )
        self.libreoffice_copy_button = button(
            actions, "Copiar caminho", self._copy_libreoffice_destination, 1, 1
        )
        self.libreoffice_open_button = button(
            actions, "Abrir instalador", self._open_libreoffice_installer, 2, 0
        )
        self.libreoffice_verify_button = button(
            actions, "Verificar instalação", self._recheck_libreoffice, 2, 1
        )
        self.libreoffice_progress = self._operation_progress(tile)
        self.libreoffice_status = self._operation_label(tile, 4)
        self.libreoffice_path = self._operation_label(tile, 5)
        # Rótulos vazios não reservam linhas entre ações e informações.
        for label in (self.libreoffice_status, self.libreoffice_path):
            label.configure(height=1)
        self._set_libreoffice_actions(ComponentState.NOT_CHECKED)
