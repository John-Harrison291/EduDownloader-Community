"""Persistent, paginated PDF preview viewport. Only this thread creates Tk images."""

import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk

from ui_design import SOFT, SURFACE, TEXT, PRIMARY, Design, keyboard_control
from ui_scroll import wheel_region


class PagePreviewPane(ctk.CTkFrame):
    def __init__(
        self,
        master,
        worker,
        *,
        height=400,
        design=None,
        accent=None,
        on_result=None,
        on_toggle_selection=None,
        empty_text="Selecione arquivos para visualizar.",
        **kwargs,
    ):
        kwargs.setdefault("fg_color", SURFACE)
        super().__init__(master, **kwargs)
        design = design or Design(self.winfo_toplevel())
        self.worker = worker
        self.on_result = on_result
        self.on_toggle_selection = on_toggle_selection
        self.selection_enabled = False
        self._preferred_height = height
        self._layout_width = None
        self.empty_text = empty_text
        self.canvas_colors = SOFT
        self.owner = id(self)
        self.accent = accent or PRIMARY
        self.spec = None
        self.index, self.total, self.zoom = 0, 0, 1.0
        self.generation = 0
        self.selection = frozenset()
        self.highlight = False
        self._closed = False
        self._poll_id = self._resize_id = None
        self._resize_bounds = None
        self._photo = None
        self._thumb_sources = []
        self._thumb_keys = None
        self._bundle = None
        self._displayed_key = None
        self._request_key = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        navigation = ctk.CTkFrame(self, fg_color="transparent")
        navigation.grid(row=0, column=0, sticky="w", padx=5, pady=(5, 2))
        self.previous = design.button(
            navigation,
            text="‹",
            width=28,
            height=30,
            command=lambda: self.goto(self.index - 1),
            kind="secondary",
            keyboard=True,
        )
        self.previous.grid(row=0, column=0, padx=(0, 4))
        self.page_label = design.form_label(navigation, text="Página", width=40)
        self.page_label.grid(row=0, column=1, padx=2)
        self.number = tk.StringVar(value="1")
        self.entry = design.form_entry(
            navigation, textvariable=self.number, width=48, height=30
        )
        self.entry.grid(row=0, column=2, padx=2)
        self.entry.bind("<Return>", self._jump)
        self.counter = design.form_label(navigation, text="de 0", width=48)
        self.counter.grid(row=0, column=3, padx=2, sticky="w")
        self.next = design.button(
            navigation,
            text="›",
            width=28,
            height=30,
            command=lambda: self.goto(self.index + 1),
            kind="secondary",
            keyboard=True,
        )
        self.next.grid(row=0, column=4, padx=2)

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self._zoom_buttons = []
        for column, (title, command, width) in enumerate(
            (
                ("−", lambda: self.change_zoom(1 / 1.25), 28),
                ("+", lambda: self.change_zoom(1.25), 28),
                ("Ajustar", self.fit, 62),
                ("Restaurar", self.reset, 76),
            )
        ):
            button = design.button(
                tools,
                title,
                command,
                width=width,
                height=30,
                kind="secondary",
                keyboard=True,
            )
            button.grid(row=0, column=column + int(column > 0), padx=2)
            self._zoom_buttons.append(button)
        self.zoom_indicator = design.form_label(tools, text="100%")
        self.zoom_indicator.grid(row=0, column=1, padx=4)
        self.caption = design.form_label(
            self,
            text=self.empty_text,
            wraplength=360,
            justify="left",
            anchor="w",
        )
        self.caption.grid(row=2, column=0, padx=8, pady=3, sticky="ew")

        viewport = ctk.CTkFrame(self, fg_color="transparent")
        viewport.grid(row=3, column=0, sticky="nsew", padx=5)
        viewport.grid_columnconfigure(0, weight=1)
        viewport.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            viewport, width=230, height=height, highlightthickness=0, bd=0
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical = ctk.CTkScrollbar(viewport, command=self.canvas.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ctk.CTkScrollbar(
            viewport, orientation="horizontal", command=self.canvas.xview
        )
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        self._image_item = self.canvas.create_image(0, 0, anchor="nw")
        self._message_item = self.canvas.create_text(
            110,
            height / 2,
            text=self.empty_text,
            width=200,
            justify="center",
        )
        self.canvas.bind("<Configure>", self._resize)
        wheel_region(viewport, self.canvas, zoom=self._wheel_zoom)
        self.canvas.bind("<ButtonPress-1>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind(
            "<B1-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1)
        )
        self.strip = ctk.CTkFrame(self, fg_color="transparent")
        self.strip.grid(row=4, column=0, sticky="ew", padx=5, pady=4)
        self.strip.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="thumbnail")
        self.thumbs = []
        self._selection_buttons = []
        for column in range(4):
            button = design.button(
                self.strip,
                text="",
                command=None,
                width=20,
                height=110,
                compound="top",
                border_width=2,
                kind="secondary",
                keyboard=True,
            )
            button.grid(row=0, column=column, padx=2, sticky="ew")
            self.thumbs.append(button)
            if on_toggle_selection is not None:
                selection = ctk.CTkCheckBox(
                    self.strip,
                    text="Incluir",
                    width=1,
                    checkbox_width=18,
                    checkbox_height=18,
                    font=design.small,
                    fg_color=self.accent,
                    text_color=TEXT,
                )
                keyboard_control(
                    selection,
                    lambda box=selection: box.toggle(),
                    show_focus=lambda focused, box=selection: box.configure(
                        text_color=self.accent if focused else TEXT,
                    ),
                )
                selection.grid(row=1, column=column, padx=2, pady=(4, 0))
                self._selection_buttons.append(selection)
        self.bind("<Configure>", self._resize_layout, add="+")
        self._clear_thumbs()
        self._controls()

    def set_context(self, spec, *, count=0, preserve_view=False):
        if self._closed:
            return
        if spec == self.spec:
            if count and not self.total:
                self.total = count
                self._controls()
            return
        preserve = (
            preserve_view
            and self.spec
            and spec
            and self.spec.kind == spec.kind == "images"
            and bool(set(self.spec.paths).intersection(spec.paths))
        )
        self.spec = spec
        self.page_label.configure(
            text={"merge": "PDF", "poster": "Folha"}.get(
                getattr(spec, "kind", ""), "Página"
            )
        )
        self.index = min(self.index, max(0, count - 1)) if preserve else 0
        self.total = count
        self.zoom = self.zoom if preserve else 1.0
        self._bundle = None
        self._request_key = None
        self._clear_thumbs()
        self.refresh()

    def set_selection(self, pages, *, highlight=True, enabled=True):
        selection = None if pages is None else frozenset(pages)
        if (self.selection_enabled, self.selection, self.highlight) == (
            enabled,
            selection,
            highlight,
        ):
            return
        self.selection_enabled = enabled
        self.selection = selection
        self.highlight = highlight
        self._paint_thumbs()
        self._controls()

    def _selected(self, index):
        return self.highlight and (
            self.selection is None or index + 1 in self.selection
        )

    def goto(self, index):
        if self._closed or not self.total:
            return
        index = max(0, min(self.total - 1, index))
        if index != self.index:
            self.index = index
            self.refresh()

    def _jump(self, _event=None):
        try:
            self.goto(int(self.number.get()) - 1)
        except ValueError:
            pass
        self._controls()
        self.number.set(str(self.index + 1 if self.total else 0))
        return "break"

    def change_zoom(self, factor):
        value = max(0.25, min(2.0, self.zoom * factor))
        if value != self.zoom:
            self.zoom = value
            self.refresh()

    def fit(self):
        self.zoom = 1.0
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.refresh()

    def reset(self):
        self.index = 0
        self.fit()

    def _wheel_zoom(self, event):
        self.change_zoom(1.25 if event.delta > 0 else 1 / 1.25)
        return "break"

    def _resize_layout(self, event):
        if self._closed or event.width == self._layout_width:
            return
        self._layout_width = event.width
        logical_width = self._reverse_widget_scaling(event.width)
        height = max(self._preferred_height, min(540, round(logical_width * 0.85)))
        if self.canvas.cget("height") != str(height):
            self.canvas.configure(height=height)
        wrapped = logical_width < 288
        for index, button in enumerate(self._zoom_buttons[2:]):
            button.grid_configure(
                row=int(wrapped), column=index + (0 if wrapped else 3)
            )

    def _resize(self, event):
        if self._closed:
            return
        bounds = event.width, event.height
        if bounds == self._resize_bounds:
            return
        self._resize_bounds = bounds
        wrap = max(140, int(self._reverse_widget_scaling(event.width)) - 20)
        if self.caption.cget("wraplength") != wrap:
            self.caption.configure(wraplength=wrap)
        # A imagem atual continua visível enquanto chegam novas geometrias.
        if self._resize_id is not None:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(90, self._resized)

    def _resized(self):
        self._resize_id = None
        if not self._closed:
            self.refresh(force=False)

    def refresh(self, *, force=True):
        if self._closed:
            return
        bounds = (
            max(180, self.canvas.winfo_width() - 24),
            max(160, self.canvas.winfo_height() - 24),
        )
        request_bounds = tuple(max(32, round(value * self.zoom)) for value in bounds)
        key = (self.spec, self.index, request_bounds)
        if not force and key == self._request_key:
            return
        self._request_key = key
        self.generation += 1
        keep_image = self._photo is not None and self._displayed_key == (
            self.spec,
            self.index,
        )
        if not keep_image:
            self.canvas.itemconfigure(self._image_item, image="")
            self._photo = None
        self.canvas.configure(
            bg=self._apply_appearance_mode(self.canvas_colors),
            scrollregion=(0, 0, *bounds),
        )
        self.canvas.coords(self._message_item, bounds[0] / 2, bounds[1] / 2)
        self.canvas.itemconfigure(
            self._message_item,
            text=""
            if keep_image
            else "Carregando prévia…"
            if self.spec and self.spec.paths
            else self.empty_text,
            width=bounds[0] - 20,
        )
        self._controls()
        if not self.spec or not self.spec.paths:
            self.worker.invalidate(self.owner)
            if self._poll_id is not None:
                self.after_cancel(self._poll_id)
                self._poll_id = None
            self._bundle = None
            self._clear_thumbs()
            return
        try:
            self.worker.submit(
                self.owner, self.generation, self.spec, self.index, request_bounds
            )
        except (OSError, RuntimeError):
            self.canvas.itemconfigure(
                self._message_item, text="Não foi possível iniciar a prévia."
            )
            return
        if self._poll_id is None:
            self._poll_id = self.after(40, self._poll)

    def _poll(self):
        self._poll_id = None
        if self._closed or self.worker.closed:
            return
        result = self.worker.take(self.owner)
        if result is None:
            self._poll_id = self.after(40, self._poll)
            return
        generation, bundle = result
        if generation != self.generation:
            self._poll_id = self.after(40, self._poll)
            return
        self._bundle = bundle
        self.total = bundle.total
        if bundle.main is None:
            self.canvas.itemconfigure(self._image_item, image="")
            self._photo = None
            self._displayed_key = None
            self.canvas.itemconfigure(self._message_item, text=bundle.error)
        else:
            image = bundle.main.image()
            try:
                self._photo = ImageTk.PhotoImage(image, master=self.canvas)
            finally:
                image.close()
            width, height = self._photo.width(), self._photo.height()
            x = max(12, (self.canvas.winfo_width() - width) / 2)
            y = max(12, (self.canvas.winfo_height() - height) / 2)
            self.canvas.coords(self._image_item, x, y)
            self.canvas.itemconfigure(self._image_item, image=self._photo)
            self._displayed_key = (self.spec, self.index)
            self.canvas.itemconfigure(self._message_item, text="")
            self.canvas.configure(
                scrollregion=(
                    0,
                    0,
                    max(width + 24, self.canvas.winfo_width()),
                    max(height + 24, self.canvas.winfo_height()),
                )
            )
        self._paint_thumbs()
        self._controls()
        if self.on_result is not None:
            self.on_result(bundle)

    def _controls(self):
        focus = self.focus_get()
        if focus is None or getattr(focus, "master", None) is not self.entry:
            self.number.set(str(self.index + 1 if self.total else 0))
        self.counter.configure(text=f"de {self.total}")
        self.zoom_indicator.configure(text=f"{round(self.zoom * 100)}%")
        self._zoom_buttons[0].configure(
            state="normal" if self.total and self.zoom > 0.25 else "disabled"
        )
        self._zoom_buttons[1].configure(
            state="normal" if self.total and self.zoom < 2.0 else "disabled"
        )
        for button in self._zoom_buttons[2:]:
            button.configure(state="normal" if self.total else "disabled")
        self.previous.configure(state="normal" if self.index > 0 else "disabled")
        self.next.configure(
            state="normal" if self.index + 1 < self.total else "disabled"
        )
        title = ""
        if self._bundle is not None and self._bundle.main is not None:
            title = self._bundle.main.caption
        status = " · selecionada" if self._selected(self.index) else ""
        self.caption.configure(
            text=f"{title}{status}" if self.total else self.empty_text
        )

    def _clear_thumbs(self):
        for button in self.thumbs:
            button.configure(image=None, text="", state="disabled", command=None)
            button.grid_remove()
        for selection in self._selection_buttons:
            selection.grid_remove()
        for source in self._thumb_sources:
            source.close()
        self._thumb_sources.clear()
        self._thumb_keys = None

    def _paint_thumbs(self):
        if self._bundle is None:
            return
        thumb_width = max(24, (self.winfo_width() - 40) // 4)
        keys = (
            thumb_width,
            tuple((number, id(raster)) for number, raster in self._bundle.thumbs),
        )
        new_content = keys != self._thumb_keys
        if new_content:
            self._clear_thumbs()
            self._thumb_keys = keys
        for column, (button, (number, raster)) in enumerate(
            zip(self.thumbs, self._bundle.thumbs)
        ):
            if not button.winfo_manager():
                button.grid()
            label = str(number + 1)
            if self.spec.kind == "merge":
                label += "\n" + self.spec.paths[number].name[:16]
            if self._selected(number):
                label += " ✓"
            image = None
            if raster.rgb and new_content:
                source = raster.image()
                source.thumbnail(
                    (thumb_width, 80),
                    Image.Resampling.LANCZOS,
                )
                self._thumb_sources.append(source)
                image = ctk.CTkImage(source, size=source.size)
            elif not raster.rgb:
                label += "\nIndisponível"
            options = dict(
                text=label,
                state="normal",
                border_color=self.accent
                if self._selected(number) or number == self.index
                else self.cget("fg_color"),
            )
            if new_content:
                options.update(image=image, command=lambda i=number: self.goto(i))
            changed = {
                key: value
                for key, value in options.items()
                if button.cget(key) != value
            }
            if changed:
                button.configure(**changed)
            if self._selection_buttons:
                selection = self._selection_buttons[column]
                selection.configure(
                    state="normal" if self.selection_enabled else "disabled",
                    command=lambda page=number + 1: self.on_toggle_selection(page),
                )
                if self._selected(number):
                    selection.select()
                else:
                    selection.deselect()
                if not selection.winfo_manager():
                    selection.grid()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.worker.invalidate(self.owner)
        for after_id in (self._poll_id, self._resize_id):
            if after_id is not None:
                self.after_cancel(after_id)
        self._poll_id = self._resize_id = None
        self.canvas.itemconfigure(self._image_item, image="")
        self._photo = None
        self._bundle = None
        self._clear_thumbs()

    def destroy(self):
        self.close()
        super().destroy()

    def _set_appearance_mode(self, mode_string):
        super()._set_appearance_mode(mode_string)
        if hasattr(self, "canvas") and not self._closed:
            self.canvas.configure(bg=self._apply_appearance_mode(self.canvas_colors))
            self.canvas.itemconfigure(
                self._message_item,
                fill=self._apply_appearance_mode(TEXT),
            )
