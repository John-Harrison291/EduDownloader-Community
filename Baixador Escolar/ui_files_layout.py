"""Composição visual da biblioteca, sobre os contratos da página persistente."""

import tkinter as tk
from contextlib import nullcontext
from tkinter import ttk

from ui_scroll import wheel_region

import customtkinter as ctk
from ui_lifecycle import PreviewTextbox

from ui_design import (
    CARD_INSET,
    CONTROL_HEIGHT,
    CONTROL_RADIUS,
    DISABLED_TEXT,
    LINK,
    MUTED,
    PAGE_INSET,
    PRIMARY,
    SECTION_GAP,
    SOFT,
    SOFT_HOVER,
    SURFACE,
    TEXT,
    keyboard_control,
    surface,
    wrap_to_frame,
)


class FilesWorkspace:
    def _build_files_workspace(self, design):
        heading = ctk.CTkFrame(self, fg_color="transparent")
        heading.grid(
            row=0,
            column=0,
            padx=PAGE_INSET,
            pady=(PAGE_INSET, SECTION_GAP),
            sticky="ew",
        )
        design.label(heading, "Seus arquivos", font=design.title).pack(anchor="w")
        subtitle = design.label(
            heading,
            "Encontre materiais e envie-os para as ferramentas do EduDownloader.",
            color=MUTED,
            wraplength=470,
        )
        subtitle.pack(fill="x", pady=(4, 0))
        wrap_to_frame(heading, subtitle, reserved=0)

        self._files_empty = surface(self)
        self._files_empty.grid(
            row=1, column=0, padx=PAGE_INSET, pady=(0, SECTION_GAP), sticky="ew"
        )
        title = ctk.CTkLabel(
            self._files_empty,
            text="Escolha uma pasta para começar",
            font=design.heading,
            text_color=TEXT,
            wraplength=440,
        )
        title.pack(fill="x", padx=CARD_INSET, pady=(42, 8))
        description = ctk.CTkLabel(
            self._files_empty,
            text="Pesquise e abra materiais dessa pasta sem sair do EduDownloader.",
            font=design.body,
            text_color=MUTED,
            wraplength=440,
        )
        description.pack(fill="x", padx=CARD_INSET)
        self.initial_choose_button = design.button(
            self._files_empty,
            "Escolher pasta",
            self._choose_directory,
            width=224,
            keyboard=True,
        )
        self.initial_choose_button.pack(pady=12)
        privacy = ctk.CTkLabel(
            self._files_empty,
            text="Somente a pasta escolhida será consultada. Seus arquivos ficam no computador.",
            font=design.small,
            text_color=MUTED,
            wraplength=440,
        )
        privacy.pack(fill="x", padx=CARD_INSET, pady=(0, 42))
        wrap_to_frame(
            self._files_empty, title, description, privacy, reserved=2 * CARD_INSET
        )

        self._files_toolbar = surface(self)
        self._files_toolbar.grid(
            row=2, column=0, padx=PAGE_INSET, pady=(0, 10), sticky="ew"
        )
        self._files_toolbar.grid_columnconfigure(0, weight=1)
        self._build_files_toolbar(design)

        self._favorites_card = surface(self)
        self._favorites_card.grid(
            row=3, column=0, padx=PAGE_INSET, pady=(0, 14), sticky="ew"
        )
        self._favorites_card.grid_columnconfigure(0, weight=1)
        self.favorite_menu = self._files_menu(
            self._favorites_card,
            design,
            [self._FAVORITES_PLACEHOLDER],
            self._favorite_choice,
            self._select_favorite,
        )
        self.favorite_menu.grid(
            row=0, column=0, padx=(CARD_INSET, 8), pady=10, sticky="ew"
        )
        self.remove_favorite_button = design.button(
            self._favorites_card,
            "Remover dos favoritos",
            self._remove_selected_favorite,
            kind="secondary",
            width=170,
            keyboard=True,
        )
        self.remove_favorite_button.grid(
            row=0, column=1, padx=(0, CARD_INSET), pady=10, sticky="e"
        )

        self._files_workarea = ctk.CTkFrame(self, fg_color="transparent")
        self._files_workarea.grid(
            row=4, column=0, padx=PAGE_INSET, pady=(0, 14), sticky="ew"
        )
        self._files_workarea.grid_columnconfigure(0, weight=1)
        self._build_files_list(design)
        self._build_file_details(design)
        self._files_wide = None
        tk.Misc.bind(
            self._files_workarea, "<Configure>", self._arrange_files_workarea, add="+"
        )

        self.status_frame = surface(self)
        self.status_frame.grid(
            row=6, column=0, padx=PAGE_INSET, pady=(0, 28), sticky="ew"
        )
        self.status_frame.grid_columnconfigure(0, weight=1)
        status = design.label(
            self.status_frame,
            "",
            textvariable=self._status,
            color=MUTED,
            font=design.small,
            wraplength=440,
        )
        status.grid(row=0, column=0, padx=CARD_INSET, pady=10, sticky="ew")
        wrap_to_frame(self.status_frame, status, reserved=2 * CARD_INSET)
        self.progress_bar = ctk.CTkProgressBar(
            self.status_frame,
            mode="indeterminate",
            height=8,
            fg_color=SOFT,
            progress_color=PRIMARY,
        )
        self.progress_bar.grid(
            row=1, column=0, padx=CARD_INSET, pady=(0, 12), sticky="ew"
        )
        self.progress_bar.set(0)

    @staticmethod
    def _files_menu(parent, design, values, variable, command):
        menu = ctk.CTkOptionMenu(
            parent,
            values=values,
            variable=variable,
            command=command,
            width=150,
            height=CONTROL_HEIGHT,
            dynamic_resizing=False,
            corner_radius=CONTROL_RADIUS,
            fg_color=SOFT,
            button_color=SOFT,
            button_hover_color=SOFT_HOVER,
            text_color=TEXT,
            text_color_disabled=DISABLED_TEXT,
            font=design.nav,
            dropdown_font=design.nav,
            dropdown_fg_color=SURFACE,
            dropdown_hover_color=SOFT_HOVER,
            dropdown_text_color=TEXT,
        )
        keyboard_control(
            menu,
            menu._clicked,
            show_focus=lambda focused: menu.configure(
                button_color=SOFT_HOVER if focused else SOFT
            ),
        )
        return menu

    def _build_files_toolbar(self, design):
        toolbar = self._files_toolbar
        design.label(toolbar, "Pasta atual", font=design.control).grid(
            row=0,
            column=0,
            padx=CARD_INSET,
            pady=(14, 0),
            sticky="w",
        )
        path = design.label(
            toolbar,
            "",
            textvariable=self._folder_text,
            font=design.nav,
            wraplength=450,
        )
        path.grid(row=1, column=0, padx=CARD_INSET, sticky="ew")
        wrap_to_frame(toolbar, path, reserved=2 * CARD_INSET)
        options = ctk.CTkFrame(toolbar, fg_color="transparent")
        options.grid(row=2, column=0, padx=CARD_INSET, pady=(8, 12), sticky="ew")
        self.choose_button = design.button(
            options, "Escolher pasta", self._choose_directory, width=124, keyboard=True
        )
        self.favorite_button = design.button(
            options,
            "Favoritar pasta",
            self._toggle_current_favorite,
            kind="secondary",
            width=159,
            keyboard=True,
        )
        self.refresh_button = design.button(
            options,
            "Atualizar",
            self._refresh_directory,
            kind="secondary",
            width=88,
            keyboard=True,
        )
        for button in (self.choose_button, self.favorite_button, self.refresh_button):
            button.pack(side="left", padx=(0, 8))

        search = ctk.CTkFrame(toolbar, fg_color="transparent")
        search.grid(row=3, column=0, padx=CARD_INSET, sticky="ew")
        search.grid_columnconfigure(0, weight=1)
        design.label(search, "Pesquisar por nome", font=design.control).grid(
            row=0, column=0, pady=(0, 3), sticky="w"
        )
        design.label(search, "Ordenar por", font=design.control).grid(
            row=0, column=1, pady=(0, 3), sticky="w"
        )
        self.search_entry = design.entry(search, "")
        self.search_entry.configure(
            textvariable=self._query,
            height=CONTROL_HEIGHT,
            border_color=LINK,
        )
        self.search_entry.grid(row=1, column=0, padx=(0, 8), sticky="ew")
        self.search_entry.bind("<Return>", self._apply_search_now)
        self.search_entry.bind(
            "<FocusIn>", lambda _: self.search_entry.configure(border_width=2), add="+"
        )
        self.search_entry.bind(
            "<FocusOut>", lambda _: self.search_entry.configure(border_width=0), add="+"
        )
        self.sort_menu = self._files_menu(
            search,
            design,
            list(self.sort_names),
            self._sort_name,
            self._on_sort_change,
        )
        self.sort_menu.grid(row=1, column=1, sticky="e")
        self.filter_control = ctk.CTkSegmentedButton(
            toolbar,
            values=list(self.filter_names),
            command=self._on_filter_change,
            height=36,
            corner_radius=CONTROL_RADIUS,
            font=design.control,
            fg_color=SURFACE,
            selected_color=("#CDE6FB", "#314F6D"),
            selected_hover_color=SOFT_HOVER,
            unselected_color=SOFT,
            unselected_hover_color=SOFT_HOVER,
            text_color=TEXT,
        )
        self.filter_control.set(self.filter_names[0])
        self.filter_control.grid(
            row=4, column=0, padx=CARD_INSET, pady=(10, 14), sticky="w"
        )
        for button in self.filter_control._buttons_dict.values():
            # Cada segmento é um CTkButton, com foco do Tk e ação real.
            keyboard_control(
                button,
                button.invoke,
                show_focus=lambda focused, segment=button: segment.configure(
                    border_color=LINK,
                    border_width=2 if focused else 0,
                ),
            )

    def _build_files_list(self, design):
        self.file_list_frame = surface(self)
        self.file_list_frame.grid_columnconfigure(0, weight=1)
        self.file_list_frame.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self.file_list_frame, fg_color="transparent")
        header.grid(
            row=0, column=0, columnspan=2, padx=CARD_INSET, pady=(14, 4), sticky="ew"
        )
        header.grid_columnconfigure(0, weight=1)
        design.label(
            header, "", textvariable=self._visible_count_text, font=design.control
        ).grid(row=0, column=0, sticky="w")
        self.show_more_button = design.button(
            header,
            "Mostrar mais",
            self._show_more,
            kind="secondary",
            width=117,
            keyboard=True,
        )
        self.show_more_button.grid(row=0, column=1)
        self.show_more_button.grid_remove()

        self.file_tree = ttk.Treeview(
            self.file_list_frame,
            columns=("name", "type", "size", "modified"),
            displaycolumns=("name", "type", "size"),
            show="headings",
            selectmode="browse",
            height=10,
            style=self._TREE_STYLE,
        )
        for column, heading, width in (
            ("name", "Nome", 232),
            ("type", "Tipo", 96),
            ("size", "Tamanho", 88),
            ("modified", "Modificado", 128),
        ):
            self.file_tree.heading(column, text=heading)
            self.file_tree.column(
                column, width=width, minwidth=60, stretch=column == "name", anchor="w"
            )
        self.file_scrollbar = ctk.CTkScrollbar(
            self.file_list_frame, orientation="vertical", command=self.file_tree.yview
        )
        wheel_region(self.file_list_frame, self.file_tree)
        self.file_tree.configure(yscrollcommand=self.file_scrollbar.set)
        self.file_tree.grid(
            row=1, column=0, sticky="nsew", padx=(CARD_INSET, 0), pady=(0, 14)
        )
        self.file_scrollbar.grid(
            row=1, column=1, sticky="ns", padx=(0, CARD_INSET), pady=(0, 14)
        )
        tk.Misc.bind(
            self.file_tree, "<Configure>", self._schedule_file_columns, add="+"
        )
        self.file_tree.bind("<<TreeviewSelect>>", self._on_tree_selection)
        self.file_tree.bind("<Double-1>", self._on_tree_double_click)
        self.file_tree.bind("<Return>", lambda _: self._open_selected())

    def _build_file_details(self, design):
        self.context_frame = surface(self)
        card = self.context_frame
        card.grid_columnconfigure(0, weight=1)
        name = design.label(
            card,
            "",
            textvariable=self._detail_heading,
            font=design.card_title,
            wraplength=260,
        )
        name.grid(row=0, column=0, padx=CARD_INSET, pady=(14, 6), sticky="ew")

        self.preview_frame = ctk.CTkFrame(
            card, height=290, fg_color=SOFT, corner_radius=CONTROL_RADIUS
        )
        self.preview_frame.grid(row=1, column=0, padx=CARD_INSET, sticky="ew")
        self.preview_frame.grid_propagate(False)
        self.preview_frame.grid_rowconfigure(0, weight=1)
        self.preview_frame.grid_columnconfigure(0, weight=1)
        self.preview_label = ctk.CTkLabel(
            self.preview_frame,
            textvariable=self._preview_text,
            wraplength=244,
            justify="center",
            font=design.small,
            text_color=MUTED,
        )
        self.preview_label.grid(row=0, column=0, padx=8, pady=6, sticky="nsew")
        self.preview_document = PreviewTextbox(
            self.preview_frame,
            width=160,
            height=108,
            wrap="word",
            fg_color=SOFT,
            text_color=TEXT,
            font=design.nav,
        )
        self.preview_document.configure(state="disabled")
        wheel_region(self.preview_document, self.preview_document._textbox, step=3)
        wrap_to_frame(self.preview_frame, self.preview_label, reserved=16)
        tk.Misc.bind(
            self.preview_frame, "<Configure>", self._resize_preview_image, add="+"
        )

        caption = design.label(
            card, "", textvariable=self._preview_caption, color=MUTED, font=design.small
        )
        caption.grid(row=2, column=0, padx=CARD_INSET, sticky="ew")
        file_actions = ctk.CTkFrame(card, fg_color="transparent")
        file_actions.grid(row=3, column=0, padx=CARD_INSET, pady=(10, 4), sticky="ew")
        self.open_button = design.button(
            file_actions, "Abrir", self._open_selected, width=82, keyboard=True
        )
        self.reveal_button = design.button(
            file_actions,
            "Mostrar na pasta",
            self._reveal_selected,
            kind="secondary",
            width=131,
            keyboard=True,
        )
        self.open_button.pack(side="left", padx=(0, 8))
        self.reveal_button.pack(side="left")
        labels = [name]
        for row, (label, variable) in enumerate(
            (
                ("Tipo", self._detail_type),
                ("Tamanho", self._detail_size),
                ("Modificado", self._detail_modified),
            ),
            start=4,
        ):
            field = ctk.CTkFrame(card, fg_color="transparent")
            field.grid(row=row, column=0, padx=CARD_INSET, sticky="ew")
            design.label(field, label, color=MUTED, font=design.small, width=76).pack(
                side="left"
            )
            design.label(field, "", textvariable=variable, font=design.small).pack(
                side="left"
            )
        hint = design.label(
            card,
            "",
            textvariable=self._edu_action_text,
            color=MUTED,
            font=design.small,
            wraplength=255,
        )
        hint.grid(row=7, column=0, padx=CARD_INSET, pady=(8, 4), sticky="ew")
        labels.append(hint)
        wrap_to_frame(card, *labels, reserved=2 * CARD_INSET)
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=8, column=0, padx=CARD_INSET, pady=(0, 14), sticky="ew")

        def route(callback):
            return lambda: (
                self._route_selected(callback) if callback is not None else None
            )

        for name, label, action in (
            ("extract_button", "Extrair páginas", route(self._actions.extract_pages)),
            ("pdf_images_button", "PDF → Imagens", route(self._actions.pdf_to_images)),
            ("pdf_word_button", "PDF para Word", route(self._actions.pdf_to_docx)),
            ("image_pdf_button", "Imagens → PDF", route(self._actions.image_to_pdf)),
            ("poster_button", "Criar pôster", route(self._actions.create_poster)),
            (
                "video_mp3_button",
                "Extrair áudio do vídeo",
                route(self._actions.video_to_mp3),
            ),
            ("docx_pdf_button", "Converter para PDF", self._convert_selected_document),
        ):
            setattr(
                self,
                name,
                design.button(actions, label, action, kind="secondary", keyboard=True),
            )
        self._context_buttons = (
            self.extract_button,
            self.pdf_images_button,
            self.pdf_word_button,
            self.image_pdf_button,
            self.poster_button,
            self.video_mp3_button,
            self.docx_pdf_button,
        )

    def _arrange_files_workarea(self, event):
        width = self._files_workarea._reverse_widget_scaling(event.width)
        wide = width >= 815
        if wide == self._files_wide:
            return
        self._files_wide = wide
        self._files_workarea.grid_columnconfigure(
            1, weight=2 if wide else 0, minsize=315 if wide else 0
        )
        self._files_workarea.grid_columnconfigure(0, weight=3 if wide else 1)
        self.file_list_frame.grid(
            in_=self._files_workarea, row=0, column=0, sticky="new"
        )
        self.context_frame.grid(
            in_=self._files_workarea,
            row=0 if wide else 1,
            column=1 if wide else 0,
            padx=(16, 0) if wide else 0,
            pady=0 if wide else (14, 0),
            sticky="new",
        )

    def _show_files_workspace(self):
        opened = self._directory is not None or self._loading
        viewport_change = getattr(self, "_viewport_change", nullcontext)
        visible_layout = bool(self._files_toolbar.grid_info()) == opened
        with nullcontext() if visible_layout else viewport_change():
            for widget, visible in (
                (self._files_empty, not opened),
                (self._files_toolbar, opened),
                (self._files_workarea, opened),
                (self._favorites_card, bool(self._favorite_path_by_label)),
                (self.status_frame, opened),
                (self.progress_bar, self._loading),
            ):
                if bool(widget.grid_info()) == visible:
                    continue
                if visible:
                    widget.grid()
                else:
                    widget.grid_remove()
