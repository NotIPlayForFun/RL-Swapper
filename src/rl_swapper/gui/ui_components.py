from __future__ import annotations

from datetime import datetime
from tkinter import BOTH, RIGHT, LEFT, Y, X, Canvas, Frame, Label
from tkinter import ttk
import rl_swapper.backend.models as backend

CARD = "#171d2b"
CARD_SELECTED = "#20283a"
TEXT = "#e5e7eb"
MUTED = "#9ca3af"
PANEL = "#151925"
PANEL_ALT = "#23293e"
GREEN = "#22c55e"
ORANGE = "#f59e0b"
BORDER = "#2a3142"
BADGE_STRIPE = "#5f6877"

INFO_ICON = "i"
DELETE_ICON = "🗑"
OPEN_FOLDER_ICON = "📁"
PUSH_ICON = "⤴"
REVERT_ICON = "↩"


def swap_border_color(swap: backend.SwapRecord) -> str:
    return GREEN if swap.is_pushed() else ORANGE

def format_human_timestamp(value: str) -> str:
    if not value:
        return "(not set)"
    for pattern in ("%Y%m%d-%H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, pattern).strftime("%b %d, %Y %I:%M %p")
        except ValueError:
            continue
    return value


class ScrollableFrame(Frame):
    def __init__(self, master: Frame, *, bg: str) -> None:
        super().__init__(master, bg=bg)
        self._scroll_first = 0.0
        self._scroll_last = 1.0
        self._drag_offset = 0

        self.scrollbar = Canvas(self, bg=bg, width=14, highlightthickness=0, borderwidth=0)
        self.scrollbar.pack(side=RIGHT, fill=Y)

        self.canvas = Canvas(self, bg=bg, highlightthickness=0, borderwidth=0, yscrollcommand=self._on_canvas_scroll)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.content = Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.scrollbar.bind("<Configure>", self._on_scrollbar_configure)
        self.scrollbar.bind("<Button-1>", self._on_scrollbar_press)
        self.scrollbar.bind("<B1-Motion>", self._on_scrollbar_drag)
        self.scrollbar.bind("<ButtonRelease-1>", self._on_scrollbar_release)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux)

    def _on_content_configure(self, _event: object) -> None:
        bbox = self.canvas.bbox("all")
        if bbox is not None:
            self.canvas.configure(scrollregion=bbox)
        self._draw_scrollbar()

    def _on_canvas_configure(self, event: object) -> None:
        self.canvas.itemconfigure(self._window, width=getattr(event, "width", 0))
        self._draw_scrollbar()

    def _on_scrollbar_configure(self, _event: object) -> None:
        self._draw_scrollbar()

    def _on_canvas_scroll(self, first: str, last: str) -> None:
        self._scroll_first = float(first)
        self._scroll_last = float(last)
        self._draw_scrollbar()

    def _scrollbar_geometry(self) -> tuple[int, int, int, int]:
        height = max(self.scrollbar.winfo_height(), 1)
        width = max(self.scrollbar.winfo_width(), 1)
        inset = 2
        track_height = max(height - inset * 2, 1)
        visible_ratio = max(self._scroll_last - self._scroll_first, 0.02)
        thumb_height = min(track_height, max(28, int(track_height * visible_ratio)))
        if visible_ratio >= 0.999:
            thumb_top = inset
            thumb_height = track_height
        else:
            max_first = max(1.0 - visible_ratio, 0.0001)
            scroll_progress = max(0.0, min(self._scroll_first / max_first, 1.0))
            thumb_top = int(inset + (track_height - thumb_height) * scroll_progress)
        thumb_bottom = min(height - inset, thumb_top + thumb_height)
        return inset, thumb_top, width - inset, thumb_bottom

    def _draw_scrollbar(self) -> None:
        self.scrollbar.delete("all")
        width = self.scrollbar.winfo_width()
        height = self.scrollbar.winfo_height()
        if width <= 1 or height <= 1:
            return
        self.scrollbar.create_rectangle(0, 0, width, height, fill=PANEL, outline=PANEL)
        if self._scroll_last - self._scroll_first >= 0.999:
            top = 2
            bottom = max(height - 2, 2)
        else:
            _, top, _, bottom = self._scrollbar_geometry()
        self.scrollbar.create_rectangle(2, top, width - 2, bottom, fill="#3a455a", outline="#3a455a", tags=("thumb",))
        self.scrollbar.tag_bind("thumb", "<Button-1>", self._on_scrollbar_press)
        self.scrollbar.tag_bind("thumb", "<B1-Motion>", self._on_scrollbar_drag)
        self.scrollbar.tag_bind("thumb", "<ButtonRelease-1>", self._on_scrollbar_release)

    def _move_scrollbar_to(self, y: int) -> None:
        _, top, _, bottom = self._scrollbar_geometry()
        thumb_height = max(bottom - top, 1)
        track_height = max(self.scrollbar.winfo_height() - 4, 1)
        movable_height = max(track_height - thumb_height, 1)
        target_top = max(2, min(y - self._drag_offset, self.scrollbar.winfo_height() - thumb_height - 2))
        visible_ratio = max(self._scroll_last - self._scroll_first, 0.02)
        max_first = max(1.0 - visible_ratio, 0.0001)
        thumb_progress = max(0.0, min((target_top - 2) / movable_height, 1.0))
        self.canvas.yview_moveto(max(0.0, min(max_first, thumb_progress * max_first)))

    def _on_scrollbar_press(self, event: object) -> None:
        _, top, _, _ = self._scrollbar_geometry()
        y = getattr(event, "y", 0)
        self._drag_offset = max(0, y - top)
        self._move_scrollbar_to(y)

    def _on_scrollbar_drag(self, event: object) -> None:
        self._move_scrollbar_to(getattr(event, "y", 0))

    def _on_scrollbar_release(self, _event: object) -> None:
        self._drag_offset = 0

    def _on_mousewheel(self, event: object) -> None:
        delta = getattr(event, "delta", 0)
        if delta:
            self.canvas.yview_scroll(int(-1 * (delta / 120)), "units")

    def _on_mousewheel_linux(self, event: object) -> None:
        num = getattr(event, "num", None)
        if num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif num == 5:
            self.canvas.yview_scroll(1, "units")


class SwapCard(Frame):
    def __init__(self, master: Frame, swap: backend.SwapRecord, on_select, on_info, on_open, on_push, on_revert, on_delete, *, selected: bool = False) -> None:
        self.swap = swap
        self._on_select = on_select
        self._on_info = on_info
        self._on_open = on_open
        self._on_push = on_push
        self._on_revert = on_revert
        self._on_delete = on_delete
        self.border_color = swap_border_color(swap)
        super().__init__(master, bg=self.border_color, highlightthickness=0)
        self.inner = Frame(self, bg=CARD_SELECTED if selected else CARD, padx=14, pady=12)
        self.inner.pack(fill=BOTH, expand=True, padx=2, pady=2)
        self._build()
        self.set_selected(selected)
        self._bind_recursive(self)

    def _bind_recursive(self, widget) -> None:
        widget.bind("<Button-1>", self._handle_click)
        for child in widget.winfo_children():
            self._bind_recursive(child)

    def _handle_click(self, _event: object) -> None:
        self._on_select(self.swap)

    def _build(self) -> None:
        header_row = Frame(self.inner, bg=self.inner["bg"])
        header_row.pack(fill=X)

        status_text = "Pushed" if self.swap.is_pushed() else "Prepared"
        status_bg = GREEN if self.swap.is_pushed() else ORANGE
        status = Label(
            header_row,
            text=status_text,
            bg=status_bg,
            fg="#0b1020",
            padx=10,
            pady=3,
            font=("Segoe UI", 9, "bold"),
        )
        status.pack(side=LEFT)

        if not self.swap.is_pushed():
            ttk.Button(
                header_row,
                text=DELETE_ICON,
                style="DeleteAccent.TButton",
                width=3,
                takefocus=False,
                command=lambda: self._on_delete(self.swap),
            ).pack(side=LEFT, padx=(8, 0))

        right_header = Frame(header_row, bg=self.inner["bg"])
        right_header.pack(side=RIGHT)

        date_label = Label(
            right_header,
            text=f"Created: {format_human_timestamp(self.swap.created_at)}",
            bg=self.inner["bg"],
            fg=MUTED,
            font=("Segoe UI", 9),
        )
        date_label.pack(side=LEFT, padx=(0, 10))

        info_button = ttk.Button(
            right_header,
            text=INFO_ICON,
            width=2,
            style="Info.TButton",
            takefocus=False,
            command=lambda: self._on_info(self.swap),
        )
        info_button.pack(side=LEFT)

        Frame(right_header, bg=self.inner["bg"], width=10).pack(side=LEFT)

        content_row = Frame(self.inner, bg=self.inner["bg"])
        content_row.pack(fill=X, pady=(12, 4))
        content_row.grid_columnconfigure(0, weight=1)

        text_block = Frame(content_row, bg=self.inner["bg"])
        text_block.grid(row=0, column=0, sticky="nw")

        top_text_row = Frame(text_block, bg=self.inner["bg"])
        top_text_row.pack(fill=X)

        type_shell = Frame(top_text_row, bg=BORDER)
        type_shell.pack(side=LEFT, padx=(0, 12))
        type_badge = Frame(type_shell, bg=PANEL_ALT)
        type_badge.pack(padx=(1, 0), pady=1)
        Frame(type_badge, bg=BADGE_STRIPE, width=4).pack(side=LEFT, fill=Y)
        Label(
            type_badge,
            text=(self.swap.target_slot or "Unknown").upper(),
            bg=PANEL_ALT,
            fg=TEXT,
            padx=12,
            pady=6,
            font=("Segoe UI Semibold", 10),
        ).pack(side=LEFT)

        target_text = Frame(top_text_row, bg=self.inner["bg"])
        target_text.pack(side=LEFT, fill=X, expand=True)
        Label(
            target_text,
            text=self.swap.donor_product,
            bg=self.inner["bg"],
            fg=TEXT,
            anchor="w",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")

        Label(
            text_block,
            text=f"Replacing {self.swap.target_product}",
            bg=self.inner["bg"],
            fg=MUTED,
            anchor="w",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        button_style = "PushedAccent.TButton" if self.swap.is_pushed() else "PendingAccent.TButton"
        action_row = Frame(content_row, bg=self.inner["bg"])
        action_row.grid(row=0, column=1, sticky="se", padx=(12, 0))

        button_cluster = Frame(action_row, bg=self.inner["bg"])
        button_cluster.pack(side=RIGHT)

        if self.swap.is_pushed():
            ttk.Button(button_cluster, text=OPEN_FOLDER_ICON, style="Ghost.TButton", width=3, takefocus=False, command=lambda: self._on_open(self.swap)).pack(side=RIGHT)
            ttk.Button(button_cluster, text=f"{PUSH_ICON} Push Swap", style=button_style, takefocus=False, command=lambda: self._on_push(self.swap)).pack(side=RIGHT, padx=(0, 10))
            ttk.Button(button_cluster, text=f"{REVERT_ICON} Revert Push", style="RevertAccent.TButton", takefocus=False, command=lambda: self._on_revert(self.swap)).pack(side=RIGHT, padx=(0, 10))
        else:
            ttk.Button(button_cluster, text=OPEN_FOLDER_ICON, style="Ghost.TButton", width=3, takefocus=False, command=lambda: self._on_open(self.swap)).pack(side=RIGHT)
            ttk.Button(button_cluster, text=f"{PUSH_ICON} Push Swap", style=button_style, takefocus=False, command=lambda: self._on_push(self.swap)).pack(side=RIGHT, padx=(0, 10))

    def set_selected(self, selected: bool) -> None:
        _ = selected