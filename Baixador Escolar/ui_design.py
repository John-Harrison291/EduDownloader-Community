"""Tokens do Figma e widgets compartilhados da interface desktop 3.0."""

import os
import tkinter as tk
import tkinter.font as tkfont
from contextlib import ExitStack
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageTk

from constants import DEFAULT_TEXT_SCALE
from ui_feedback import MotionButton, card_feedback
from ui_lifecycle import FormEntry


CANVAS = ("#F5F8FC", "#0C1826")
SURFACE = ("#FFFFFF", "#17283B")
SOFT = ("#EBF3FA", "#24394D")
SIDEBAR = ("#153651", "#0B2234")
TEXT = ("#152A40", "#F1F7FF")
MUTED = ("#536B82", "#A9BECE")
PRIMARY = ("#2878BA", "#4A9CDE")
# O azul claro do tema escuro precisa de texto escuro para manter contraste.
ON_PRIMARY = ("#FFFFFF", "#0C1826")
LINK = ("#21659F", "#73B9EF")
DANGER = ("#C64050", "#D45765")
ERROR_TEXT = ("#A52C3D", "#FF9FAA")
DISABLED_TEXT = ("#6B7987", "#A1AFBD")
SIDEBAR_TEXT = "#FFFFFF"
NAV_HOVER = ("#244966", "#24455F")
PRIMARY_HOVER = ("#2468A1", "#72B4EA")
SOFT_HOVER = ("#DDEAF5", "#314C65")
DANGER_HOVER = ("#A62E40", "#F07885")

SIDEBAR_WIDTH = 232
PAGE_INSET = 44
CARD_INSET = 24
SECTION_GAP = 22
ITEM_GAP = 16
CONTROL_HEIGHT = 44
CONTROL_RADIUS = 12
CARD_RADIUS = 16


def load_brand_image(base_dir: Path) -> Image.Image | None:
    logo_path = base_dir / "branding" / "edudownloader-logo-original.png"
    try:
        with Image.open(logo_path, formats=("PNG",)) as original:
            return original.crop((300, 185, 950, 835)).copy()
    except (OSError, ValueError):
        return None


def apply_window_icon(
    window, brand_image: Image.Image | None
) -> tuple[ImageTk.PhotoImage, ...]:
    """Aplica o símbolo e devolve as referências que a janela deve preservar."""
    if brand_image is None:
        return ()
    try:
        icons = tuple(
            ImageTk.PhotoImage(
                brand_image.resize((size, size), Image.Resampling.LANCZOS),
                master=window,
            )
            for size in (16, 32, 48)
        )
        if os.name == "nt":
            # Suprime a troca para o ícone padrão agendada pelo CustomTkinter.
            window.iconbitmap()
        window.iconphoto(True, *icons)
    except (OSError, tk.TclError, ValueError):
        return ()
    return icons


class Design:
    """Resolve as fontes locais uma vez para cada janela."""

    _TEXT_WIDGETS = (
        ctk.CTkButton,
        ctk.CTkCheckBox,
        ctk.CTkComboBox,
        ctk.CTkEntry,
        ctk.CTkLabel,
        ctk.CTkOptionMenu,
        ctk.CTkRadioButton,
        ctk.CTkSwitch,
        ctk.CTkTextbox,
    )

    def __init__(self, window, *, motion=None):
        self._window = window
        self.motion = motion
        self._text_scale = DEFAULT_TEXT_SCALE
        self._native_fonts = {}
        families = tkfont.families(window)
        family = "Inter" if "Inter" in families else "Segoe UI"
        self.title = ctk.CTkFont(family=family, size=32, weight="bold")
        self.heading = ctk.CTkFont(family=family, size=20, weight="bold")
        self.card_title = ctk.CTkFont(family=family, size=19, weight="bold")
        self.body = ctk.CTkFont(family=family, size=16)
        self.small = ctk.CTkFont(family=family, size=13)
        self.control = ctk.CTkFont(family=family, size=14, weight="bold")
        self.nav = ctk.CTkFont(family=family, size=14)
        self.brand = ctk.CTkFont(family=family, size=18, weight="bold")
        self.caption = ctk.CTkFont(family=family, size=11)

    def set_text_scale(self, scale: int) -> None:
        """Redimensiona fontes no próprio widget, preservando geometria e estado."""
        if scale == self._text_scale:
            return
        if not self._native_fonts:
            for name in (
                "TkDefaultFont",
                "TkTextFont",
                "TkFixedFont",
                "TkHeadingFont",
                "TkMenuFont",
            ):
                font = tkfont.nametofont(name, root=self._window)
                self._native_fonts[name] = (font, font.cget("size"))
            tk.Misc.bind(self._window, "<Map>", self._scale_mapped_widget, add="+")
        # Páginas persistentes já existem mesmo quando estão ocultas. Map também
        # cobre widgets legados criados depois, como linhas de listas de entrada.
        widgets = list(self._window.winfo_children())
        with ExitStack() as keep_mapped:
            for widget in widgets:
                widgets.extend(widget.winfo_children())
                if os.name == "nt" and isinstance(widget, self._TEXT_WIDGETS):
                    canvas = getattr(widget, "_canvas", None)
                    if isinstance(canvas, tk.Canvas) and "grid_forget" not in vars(
                        canvas
                    ):
                        # No Windows, desmapear e mapear os canvases nas
                        # callbacks de fonte do CTk deixa pixels da grade antiga.
                        # O Tk recalcula a geometria quando a fonte muda.
                        canvas.grid_forget = lambda: None
                        keep_mapped.callback(delattr, canvas, "grid_forget")
            self._text_scale = scale
            for font, base_size in self._native_fonts.values():
                font.configure(size=round(base_size * scale / DEFAULT_TEXT_SCALE))
            for widget in widgets:
                self._scale_widget_font(widget)

    def _scale_mapped_widget(self, event) -> None:
        if self._text_scale != DEFAULT_TEXT_SCALE:
            self._scale_widget_font(event.widget)

    def _scale_widget_font(self, widget) -> None:
        if isinstance(widget, self._TEXT_WIDGETS):
            self._scale_ctk_font(widget.cget("font"))
            if isinstance(widget, (ctk.CTkOptionMenu, ctk.CTkComboBox)):
                self._scale_ctk_font(widget.cget("dropdown_font"))

    def _scale_ctk_font(self, font) -> None:
        if isinstance(font, ctk.CTkFont):
            size = font.cget("size")
            base_size = getattr(font, "_edudownloader_base_size", size)
            font._edudownloader_base_size = base_size
            scaled = round(base_size * self._text_scale / DEFAULT_TEXT_SCALE)
            if font is self.brand:
                # A largura do menu lateral é fixa para preservar a área de trabalho.
                scaled = min(scaled, 20)
            if size != scaled:
                font.configure(size=scaled)

    def label(self, parent, text, *, font=None, color=TEXT, **kwargs):
        return ctk.CTkLabel(
            parent,
            text=text,
            font=font or self.body,
            text_color=color,
            anchor="w",
            justify="left",
            **kwargs,
        )

    def button(
        self,
        parent,
        text,
        command,
        *,
        kind="primary",
        keyboard=False,
        height=CONTROL_HEIGHT,
        **kwargs,
    ):
        background, hover, color = {
            "primary": (PRIMARY, PRIMARY_HOVER, ON_PRIMARY),
            "secondary": (SOFT, SOFT_HOVER, TEXT),
            "danger": (DANGER, DANGER_HOVER, ON_PRIMARY),
            "link": ("transparent", SOFT, LINK),
            "navigation": ("transparent", NAV_HOVER, SIDEBAR_TEXT),
        }[kind]
        button = MotionButton(
            parent,
            motion=self.motion,
            text=text,
            command=command,
            height=height,
            corner_radius=CONTROL_RADIUS,
            fg_color=background,
            hover_color=hover,
            text_color=color,
            text_color_disabled=DISABLED_TEXT,
            disabled_surface=SOFT,
            font=self.nav if kind == "navigation" else self.control,
            **kwargs,
        )

        if keyboard:
            button.configure(border_color=LINK)
            keyboard_control(
                button,
                button.invoke,
                show_focus=lambda focused: button.configure(
                    border_width=2 if focused else 0
                ),
            )
        return button

    def interactive_card(self, card, action) -> None:
        card_feedback(card, action, self.motion, SURFACE, PRIMARY)

    def entry(self, parent, placeholder):
        return ctk.CTkEntry(
            parent,
            height=54,
            width=160,
            corner_radius=CONTROL_RADIUS,
            border_width=0,
            fg_color=SOFT,
            text_color=TEXT,
            placeholder_text=placeholder,
            placeholder_text_color=MUTED,
            font=self.nav,
        )

    def form_label(self, parent, **options):
        options.setdefault("font", self.nav)
        options.setdefault("text_color", TEXT)
        options.setdefault("anchor", "w")
        options.setdefault("justify", "left")
        return ctk.CTkLabel(parent, **options)

    def form_entry(self, parent, **options):
        options.setdefault("height", CONTROL_HEIGHT)
        entry = FormEntry(
            parent,
            corner_radius=CONTROL_RADIUS,
            fg_color=SOFT,
            border_width=0,
            border_color=LINK,
            font=self.nav,
            text_color=TEXT,
            placeholder_text_color=MUTED,
            **options,
        )
        entry.bind("<FocusIn>", lambda _: entry.configure(border_width=2), add="+")
        entry.bind("<FocusOut>", lambda _: entry.configure(border_width=0), add="+")
        return entry

    def form_menu(self, parent, **options):
        options.setdefault("height", CONTROL_HEIGHT)
        menu = ctk.CTkOptionMenu(
            parent,
            corner_radius=CONTROL_RADIUS,
            fg_color=SOFT,
            button_color=SOFT,
            button_hover_color=SOFT_HOVER,
            text_color=TEXT,
            text_color_disabled=DISABLED_TEXT,
            dynamic_resizing=False,
            font=self.nav,
            dropdown_fg_color=SURFACE,
            dropdown_hover_color=SOFT_HOVER,
            dropdown_text_color=TEXT,
            dropdown_font=self.nav,
            **options,
        )
        keyboard_control(
            menu,
            menu._clicked,
            show_focus=lambda focused: menu.configure(
                button_color=SOFT_HOVER if focused else SOFT
            ),
        )
        return menu

    def tool_header(self, parent, title, subtitle):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        self.form_label(header, textvariable=title, font=self.title).pack(anchor="w")
        caption = self.form_label(
            header,
            textvariable=subtitle,
            text_color=MUTED,
            wraplength=460,
        )
        caption.pack(fill="x", pady=(4, 0))
        wrap_to_frame(header, caption, reserved=0)
        return header

    def form_radio(self, parent, **options):
        radio = ctk.CTkRadioButton(
            parent,
            font=self.nav,
            text_color=TEXT,
            text_color_disabled=DISABLED_TEXT,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            border_color=DISABLED_TEXT,
            **options,
        )
        keyboard_control(
            radio,
            radio.invoke,
            show_focus=lambda focused: radio.configure(
                border_color=LINK if focused else DISABLED_TEXT
            ),
        )
        return radio


def keyboard_control(widget, activate, *, show_focus):
    """Inclui controles desenhados pelo CTk na navegação nativa do Tk."""
    tk.Frame.configure(
        widget,
        takefocus=widget.register(
            lambda _path: widget.winfo_viewable() and widget.cget("state") != "disabled"
        ),
    )
    for child in widget.winfo_children():
        tk.Misc.configure(child, takefocus=False)

    def on_key(_event):
        if widget.cget("state") != "disabled":
            activate()
        return "break"

    for key in ("<Return>", "<space>"):
        tk.Misc.bind(widget, key, on_key, add="+")
    tk.Misc.bind(widget, "<FocusIn>", lambda _event: show_focus(True), add="+")
    tk.Misc.bind(widget, "<FocusOut>", lambda _event: show_focus(False), add="+")


def reveal_scrollable_focus(page, widget: tk.Misc) -> None:
    """Rola a página quando o foco chega a um controle fora da área visível."""
    ancestor = widget
    while ancestor is not None and ancestor is not page:
        ancestor = ancestor.master
    if ancestor is None:
        return
    canvas = page._parent_canvas
    top = widget.winfo_rooty() - canvas.winfo_rooty()
    bottom = top + widget.winfo_height() - canvas.winfo_height()
    delta = 0
    if top < 0:
        delta = top - 8
    elif bottom > 0:
        delta = bottom + 8
    if delta and page.winfo_height() > 1:
        canvas.yview_moveto((canvas.canvasy(0) + delta) / page.winfo_height())


def surface(parent):
    return ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=CARD_RADIUS)


def wrap_to_frame(frame, *labels, reserved):
    """Ajusta o texto à largura disponível sem reagendar a navegação."""

    def resize(event):
        width = int(frame._reverse_widget_scaling(event.width)) - reserved
        if width <= 0:
            return
        for label in labels:
            if label.cget("wraplength") != width:
                label.configure(wraplength=width)

    tk.Misc.bind(frame, "<Configure>", resize, add="+")


class ToolOutputFolder(ctk.CTkFrame):
    """Atalho para a pasta preferida do diálogo de saída da própria ferramenta."""

    def __init__(self, parent, design: Design, preferences, key: str):
        super().__init__(parent, fg_color="transparent")
        self._preferences = preferences
        self._key = key
        self.path_text = tk.StringVar(master=self)
        self.grid_columnconfigure(0, weight=1)
        design.form_label(self, text="Salvar em", font=design.control).grid(
            row=0,
            column=0,
            sticky="w",
        )
        label = design.form_label(
            self,
            textvariable=self.path_text,
            wraplength=220,
            text_color=MUTED,
        )
        label.grid(row=1, column=0, sticky="ew")
        self.button = design.button(
            self,
            "Alterar pasta",
            self._choose,
            kind="secondary",
            width=126,
            keyboard=True,
        )
        self.button.grid(row=0, column=1, rowspan=2, padx=(10, 0))
        wrap_to_frame(self, label, reserved=136)
        self.show_folder(preferences.available(key))

    def _choose(self) -> None:
        answer = self._preferences.choose(
            filedialog.askdirectory,
            self._key,
            directory=True,
            title="Escolher pasta de saída",
            parent=self.winfo_toplevel(),
            mustexist=True,
        )
        if answer:
            self.show_folder(Path(answer))

    def show_folder(self, path: Path | None) -> None:
        self.path_text.set(
            str(path) if path is not None else "Escolha a pasta ao salvar."
        )

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        if self.button.cget("state") != state:
            self.button.configure(state=state)


class NavigationRail(ctk.CTkFrame):
    def __init__(self, parent, design, pages, navigate, *, brand_image):
        super().__init__(parent, width=SIDEBAR_WIDTH, corner_radius=0, fg_color=SIDEBAR)
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)

        self.branding = ctk.CTkFrame(self, fg_color="transparent")
        self.branding.grid(row=0, column=0, padx=12, pady=(26, 36), sticky="w")
        if brand_image is not None:
            self.brand_symbol = ctk.CTkLabel(
                self.branding,
                text="",
                width=40,
                height=40,
                image=ctk.CTkImage(light_image=brand_image, size=(40, 40)),
            )
            self.brand_symbol.pack(side="left", padx=(0, 10))
        brand_text = ctk.CTkFrame(self.branding, fg_color="transparent")
        brand_text.pack(side="left")
        self.brand_label = design.label(
            brand_text,
            "EduDownloader",
            font=design.brand,
            color=SIDEBAR_TEXT,
            height=22,
        )
        self.brand_label.pack(anchor="w")
        design.label(
            brand_text,
            "Ferramentas para aulas",
            font=design.caption,
            color=SIDEBAR_TEXT,
            height=16,
        ).pack(anchor="w")

        self.buttons = {}
        for row, page in enumerate(pages, start=1):
            button = design.button(
                self,
                page,
                lambda name=page: navigate(name),
                kind="navigation",
                width=208,
                anchor="w",
                border_spacing=12,
                keyboard=True,
            )
            button.grid(row=row, column=0, padx=12, pady=(4, 4), sticky="ew")
            self.buttons[page] = button
