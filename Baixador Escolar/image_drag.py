"""Mouse reordering for a path list; owns no file or rendering state."""

import tkinter as tk
import customtkinter as ctk

from ui_design import LINK


class ImageListDrag:
    def __init__(self, listing):
        self.listing = listing
        self.canvas = listing._rows._parent_canvas
        self.source = None
        self.target = None
        self.snapshot = ()
        self.active = False
        self.after_id = None
        self.escape_id = None
        self.marker = tk.Frame(self.canvas, height=2, bg=LINK[0])
        self.pointer = (0, 0)

    def bind_row(self, control, index):
        control.bind("<ButtonPress-1>", lambda event, i=index: self.press(i, event))
        control.bind("<B1-Motion>", self.motion)
        control.bind("<ButtonRelease-1>", self.release)

    def press(self, index, event):
        self.cancel()
        if not self.listing._enabled or not 0 <= index < len(self.listing.paths):
            return
        self.source = index
        self.snapshot = self.listing.paths
        self.origin = (event.x_root, event.y_root)
        self.listing._selected.set(index)
        if self.listing._on_selection_change:
            self.listing._on_selection_change()
        self.escape_id = self.listing.winfo_toplevel().bind(
            "<Escape>", self.cancel, add="+"
        )

    def motion(self, event):
        if self.source is None:
            return
        self.pointer = (event.x_root, event.y_root)
        if (
            abs(event.x_root - self.origin[0]) + abs(event.y_root - self.origin[1]) < 5
            and not self.active
        ):
            return
        if not self.active:
            self.marker.configure(bg=LINK[int(ctk.get_appearance_mode() == "Dark")])
        self.active = True
        self.update_target()
        if self.active and self.after_id is None:
            self.after_id = self.listing.after(50, self.tick)

    def update_target(self):
        if self.listing.paths != self.snapshot or not self.snapshot:
            self.cancel()
            return
        x, y = self.pointer
        left, top = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
        if not (
            left <= x < left + self.canvas.winfo_width()
            and top <= y < top + self.canvas.winfo_height()
        ):
            self.target = None
            self.marker.place_forget()
            return
        lo, hi = 0, len(self.snapshot)
        while lo < hi:
            mid = (lo + hi) // 2
            row = self.listing._row_controls[mid]
            if y < row.winfo_rooty() + row.winfo_height() / 2:
                hi = mid
            else:
                lo = mid + 1
        self.target = lo
        if lo < len(self.snapshot):
            line = self.listing._row_controls[lo].winfo_rooty() - top
        else:
            last = self.listing._row_controls[lo - 1]
            line = last.winfo_rooty() + last.winfo_height() - top + 2
        self.marker.place(
            x=4, y=max(0, min(self.canvas.winfo_height() - 2, line)), relwidth=0.96
        )
        self.marker.lift()

    def tick(self):
        self.after_id = None
        if not self.active or not self.listing.winfo_ismapped():
            self.cancel()
            return
        x, y = self.pointer
        top = self.canvas.winfo_rooty()
        if (
            self.canvas.winfo_rootx()
            <= x
            <= self.canvas.winfo_rootx() + self.canvas.winfo_width()
        ):
            direction = (
                -1
                if y < top + 20
                else 1
                if y > top + self.canvas.winfo_height() - 20
                else 0
            )
            if direction:
                self.canvas.yview_scroll(direction * 3, "units")
        self.update_target()
        if self.active:
            self.after_id = self.listing.after(50, self.tick)

    def release(self, event):
        source = self.source
        if self.active:
            self.pointer = (event.x_root, event.y_root)
            self.update_target()
        target = self.target
        valid = (
            self.active
            and target is not None
            and self.listing.paths == self.snapshot
            and self.listing._enabled
        )
        self.cancel()
        if valid:
            self.listing.move_to_insertion(source, target)

    def cancel(self, _event=None):
        if self.after_id is not None:
            self.listing.after_cancel(self.after_id)
            self.after_id = None
        if self.escape_id is not None:
            try:
                self.listing.winfo_toplevel().unbind("<Escape>", self.escape_id)
            except tk.TclError:
                pass
            self.escape_id = None
        self.marker.place_forget()
        self.source = self.target = None
        self.active = False
        self.snapshot = ()
        return "break"
