"""Início e catálogo de ferramentas sobre as páginas persistentes do aplicativo."""

from functools import partial
import tkinter as tk

import customtkinter as ctk
from ui_scroll import ScrollableFrame

from constants import CONTENT_TYPES
from ui_design import (
    CANVAS,
    CARD_INSET,
    CONTROL_HEIGHT,
    ERROR_TEXT,
    ITEM_GAP,
    MUTED,
    ON_PRIMARY,
    PAGE_INSET,
    PRIMARY,
    PRIMARY_HOVER,
    SECTION_GAP,
    SOFT,
    SOFT_HOVER,
    TEXT,
    surface,
    wrap_to_frame,
)


class CatalogPage(ScrollableFrame):
    def __init__(self, parent, design, title, subtitle):
        super().__init__(
            parent, corner_radius=0, fg_color=CANVAS, scrollbar_fg_color=CANVAS
        )
        self.design = design
        self.grid_columnconfigure(0, weight=1)
        self._layout_row = 0
        header = ctk.CTkFrame(self, fg_color="transparent")
        design.label(header, title, font=design.title, height=38).pack(anchor="w")
        design.label(header, subtitle, color=MUTED, height=22).pack(
            anchor="w", pady=(4, 0)
        )
        self._append(header, top=PAGE_INSET)

    def _append(self, widget, *, top=0, bottom=SECTION_GAP):
        widget.grid(
            row=self._layout_row,
            column=0,
            padx=PAGE_INSET,
            pady=(top, bottom),
            sticky="ew",
        )
        self._layout_row += 1

    def _section(self, title, subtitle=None):
        heading = ctk.CTkFrame(self, fg_color="transparent")
        self.design.label(heading, title, font=self.design.heading, height=26).pack(
            anchor="w"
        )
        if subtitle:
            self.design.label(
                heading, subtitle, color=MUTED, font=self.design.nav, height=20
            ).pack(anchor="w")
        self._append(heading, bottom=18)

    def _cards(self, shortcuts):
        row = ctk.CTkFrame(self, fg_color="transparent")
        buttons = {}
        cards = []
        for key, title, description, label, command in shortcuts:
            card = surface(row)
            cards.append(card)
            card.grid_columnconfigure(0, weight=1)
            card.grid_rowconfigure(1, minsize=38)
            card.grid_rowconfigure(3, weight=1)
            card.configure(height=174)
            card.grid_propagate(False)
            heading = self.design.label(
                card, title, font=self.design.card_title, wraplength=136
            )
            heading.grid(row=0, column=0, padx=CARD_INSET, pady=(20, 3), sticky="ew")
            caption = self.design.label(
                card,
                description,
                color=MUTED,
                font=self.design.small,
                wraplength=136,
                height=20,
            )
            caption.grid(row=1, column=0, padx=CARD_INSET, sticky="new")
            wrap_to_frame(card, heading, caption, reserved=2 * CARD_INSET)
            button = self.design.button(
                card, label, command, kind="link", width=0, anchor="w", keyboard=True
            )
            button.grid(row=2, column=0, padx=(16, 8), pady=(0, 6), sticky="w")
            self.design.interactive_card(card, button)
            buttons[key] = button

        columns = 0

        def arrange(count):
            nonlocal columns
            if count == columns:
                return
            columns = count
            for column in range(len(cards)):
                row.grid_columnconfigure(
                    column,
                    weight=int(column < count),
                    uniform="tools" if column < count else "",
                )
            for index, card in enumerate(cards):
                line, column = divmod(index, count)
                card.grid(
                    row=line,
                    column=column,
                    padx=(0, ITEM_GAP if column < count - 1 else 0),
                    pady=(ITEM_GAP if line else 0, 0),
                    sticky="nsew",
                )

        def resize(event):
            width = row._reverse_widget_scaling(event.width) - 2 * PAGE_INSET
            arrange(min(len(cards), 1 + (width >= 560) + (width >= 760)))

        arrange(len(cards))
        tk.Misc.bind(self._parent_canvas, "<Configure>", resize, add="+")
        self._append(row)
        return buttons


class HomePage(CatalogPage):
    def __init__(self, parent, design, *, open_module, analyze_link, choose_format):
        super().__init__(
            parent,
            design,
            "Bom dia, professor(a)!",
            "Prepare seus materiais em poucos cliques.",
        )
        quick = surface(self)
        quick.grid_columnconfigure(0, weight=1)
        downloads_width = 140
        format_width = 164
        format_gap = 12
        title = design.label(
            quick,
            "Baixe um vídeo ou áudio para sua aula",
            font=design.heading,
            wraplength=305,
        )
        title.grid(row=0, column=0, padx=(CARD_INSET, 0), pady=(14, 4), sticky="w")
        downloads = design.button(
            quick,
            "Abrir Downloads",
            partial(open_module, "Downloads"),
            kind="link",
            width=downloads_width,
        )
        downloads.grid(row=0, column=1, padx=(8, CARD_INSET), pady=(14, 4), sticky="e")

        link = ctk.CTkFrame(quick, fg_color="transparent")
        link.grid(row=1, column=0, columnspan=2, padx=CARD_INSET, sticky="ew")
        link.grid_columnconfigure(0, weight=1)
        self.link_entry = design.entry(link, "Cole aqui o link do conteúdo…")
        self.link_entry.grid(row=0, column=0, padx=(0, 14), sticky="ew")
        self.analyze_button = design.button(
            link, "Analisar link", analyze_link, width=190
        )
        self.analyze_button.grid(row=0, column=1)
        self.link_entry.bind("<Return>", self._analyze_from_keyboard)

        choices = ctk.CTkFrame(quick, fg_color="transparent")
        choices.grid(
            row=2, column=0, columnspan=2, padx=CARD_INSET, pady=(18, 24), sticky="ew"
        )
        choices.grid_columnconfigure(2, weight=1)
        self.format_buttons = {}
        for column, kind in enumerate(CONTENT_TYPES):
            button = design.button(
                choices,
                kind,
                partial(choose_format, kind),
                kind="secondary",
                width=format_width,
            )
            button.grid(row=0, column=column, padx=(0, format_gap))
            self.format_buttons[kind] = button
        hint = design.label(
            choices,
            "Qualidade e pasta podem ser ajustadas no próximo passo.",
            color=MUTED,
            font=design.small,
            wraplength=100,
            height=CONTROL_HEIGHT,
        )
        hint.grid(row=0, column=2, sticky="ew")
        hint_stacked = False

        def arrange_choices(event):
            nonlocal hint_stacked
            width = (
                int(choices._reverse_widget_scaling(event.width))
                - 2 * PAGE_INSET
                - 2 * CARD_INSET
            )
            stacked = width < 570
            if stacked != hint_stacked:
                hint_stacked = stacked
                hint.grid_configure(
                    row=int(stacked),
                    column=0 if stacked else 2,
                    columnspan=3 if stacked else 1,
                    pady=(6, 0) if stacked else 0,
                )
            reserved = (
                0 if stacked else len(CONTENT_TYPES) * (format_width + format_gap)
            )
            limit = max(100, width - reserved)
            if hint.cget("wraplength") != limit:
                hint.configure(wraplength=limit)

        tk.Misc.bind(self._parent_canvas, "<Configure>", arrange_choices, add="+")
        self.link_feedback = design.label(
            quick, "", color=ERROR_TEXT, font=design.nav, wraplength=450
        )
        self.link_feedback.grid(
            row=3, column=0, columnspan=2, padx=CARD_INSET, pady=(0, 18), sticky="ew"
        )
        self.link_feedback.grid_remove()
        wrap_to_frame(quick, title, reserved=2 * CARD_INSET + downloads_width + 8)
        wrap_to_frame(quick, self.link_feedback, reserved=2 * CARD_INSET)
        self.link_entry.bind("<KeyRelease>", self._clear_link_feedback)
        self._append(quick)

        self._section(
            "Ferramentas para preparar sua aula",
            "Escolha a tarefa que precisa realizar.",
        )
        self.module_buttons = {"Downloads": downloads}
        self.module_buttons.update(
            self._cards(
                (
                    (
                        "PDF",
                        "PDF e impressão",
                        "Junte, extraia, converta e prepare pôsteres.",
                        "Ver opções →",
                        partial(open_module, "PDF"),
                    ),
                    (
                        "Documentos",
                        "Documentos",
                        "Transforme Word, ODT e texto em PDF.",
                        "Converter →",
                        partial(open_module, "Documentos"),
                    ),
                    (
                        "Mídia",
                        "Mídia",
                        "Extraia o áudio completo ou trechos de vídeos.",
                        "Extrair áudio →",
                        partial(open_module, "Mídia"),
                    ),
                )
            )
        )
        recent = surface(self)
        recent.grid_columnconfigure(0, weight=1)
        recent_title = design.label(
            recent,
            "Encontre o que acabou de preparar",
            font=design.control,
            wraplength=250,
        )
        recent_title.grid(
            row=0, column=0, padx=(CARD_INSET, 8), pady=(24, 0), sticky="w"
        )
        files = design.button(
            recent,
            "Abrir arquivos",
            partial(open_module, "Arquivos"),
            kind="secondary",
            width=184,
        )
        files.grid(row=0, column=1, padx=(0, CARD_INSET), pady=(24, 0), sticky="e")
        self.module_buttons["Arquivos"] = files
        self.recent = design.label(
            recent, "", color=MUTED, font=design.nav, wraplength=470
        )
        self.recent.grid(
            row=1, column=0, columnspan=2, padx=CARD_INSET, pady=(8, 20), sticky="ew"
        )
        wrap_to_frame(recent, self.recent, reserved=2 * CARD_INSET)
        self.show_recent(None)
        self._append(recent, bottom=36)

    def _analyze_from_keyboard(self, _event):
        self.analyze_button.invoke()
        return "break"

    def _clear_link_feedback(self, event):
        if event.keysym != "Return" and self.link_feedback.winfo_manager():
            self.show_link_error("")

    def show_link_error(self, message):
        self.link_feedback.configure(text=message)
        if message:
            self.link_feedback.grid()
            self.link_entry.focus_set()
        else:
            self.link_feedback.grid_remove()

    def show_format(self, selected):
        for value, button in self.format_buttons.items():
            colors = (
                (PRIMARY, PRIMARY_HOVER, ON_PRIMARY)
                if value == selected
                else (SOFT, SOFT_HOVER, TEXT)
            )
            if button.cget("fg_color") != colors[0]:
                button.configure(
                    fg_color=colors[0], hover_color=colors[1], text_color=colors[2]
                )

    def show_recent(self, filename):
        text = (
            f"Último download nesta sessão: {filename}"
            if filename
            else "Os arquivos criados pelo aplicativo ficam na pasta que você escolher."
        )
        if self.recent.cget("text") != text:
            self.recent.configure(text=text)


class ToolsPage(CatalogPage):
    def __init__(self, parent, design, *, open_pdf, open_module):
        super().__init__(
            parent,
            design,
            "Ferramentas",
            "Escolha o que deseja fazer com seus materiais.",
        )
        self._section("PDF e impressão")
        self.tool_buttons = self._cards(
            (
                (
                    "merge",
                    "Juntar PDFs",
                    "Combine arquivos na ordem que desejar.",
                    "Abrir →",
                    partial(open_pdf, "Juntar PDFs"),
                ),
                (
                    "extract",
                    "Extrair páginas",
                    "Crie um PDF apenas com as páginas escolhidas.",
                    "Abrir →",
                    partial(open_pdf, "Extrair páginas"),
                ),
                (
                    "poster",
                    "Pôster / painel",
                    "Divida uma imagem em folhas para impressão.",
                    "Abrir →",
                    partial(open_pdf, "Pôster/Painel"),
                ),
            )
        )
        self._section("Outras tarefas úteis")
        self.tool_buttons.update(
            self._cards(
                (
                    (
                        "images",
                        "Imagens para PDF",
                        "Coloque até 4 imagens em uma folha.",
                        "Abrir →",
                        partial(open_pdf, "Imagens → PDF"),
                    ),
                    (
                        "documents",
                        "Documentos para PDF",
                        "Converta DOCX, ODT e TXT de forma simples.",
                        "Abrir →",
                        partial(open_module, "Documentos"),
                    ),
                    (
                        "media",
                        "Vídeo para MP3",
                        "Extraia áudio completo ou um trecho.",
                        "Abrir →",
                        partial(open_module, "Mídia"),
                    ),
                )
            )
        )
        other = surface(self)
        design.label(other, "Também disponíveis", font=design.control).pack(
            anchor="w",
            padx=CARD_INSET,
            pady=(14, 4),
        )
        actions = ctk.CTkFrame(other, fg_color="transparent")
        actions.pack(anchor="w", padx=CARD_INSET, pady=(0, 20))
        for key, label, target in (
            ("pdf_images", "PDF para imagens", "PDF → Imagens"),
            ("word", "PDF para Word", "PDF para Word"),
        ):
            button = design.button(
                actions, label, partial(open_pdf, target), kind="secondary", width=184
            )
            button.pack(side="left", padx=(0, 12))
            self.tool_buttons[key] = button
        self._append(other, bottom=36)
