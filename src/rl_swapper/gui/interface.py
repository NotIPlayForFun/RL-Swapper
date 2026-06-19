#!/usr/bin/env python3
"""Dark-mode Tkinter UI for prepare_rl_swap.py.

The app opens on an overview of prepared swaps, color-coded by push state.
Use "Add New Swap" to enter an editor where you can search items by product
name, choose donor and target separately, prepare the swap, and return to the
overview.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import shutil
from datetime import datetime
import rl_swapper.backend.upk_swap as backend
from rl_swapper import config
from rl_swapper.gui.ui_components import ScrollableFrame, SwapCard, swap_border_color, format_human_timestamp
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, Canvas, Entry, Frame, Label, StringVar, Tk, TclError, Text, Toplevel, messagebox
from tkinter import ttk
from pathlib import Path

BG = "#0f1117"
PANEL = "#151925"
PANEL_ALT = "#23293e"
CARD = "#171d2b"
CARD_SELECTED = "#20283a"
# Base text and support colors.
TEXT = "#e5e7eb"
MUTED = "#9ca3af"
# Accent colors for primary actions.
ACCENT = "#6ea8fe"
ACCENT_HOVER = "#86b7ff"
# Status colors for swap state.
GREEN = "#22c55e"
ORANGE = "#f59e0b"
RED = "#ef4444"
BORDER = "#2a3142"
INPUT = "#101521"
# Button palette for push/revert state.
PUSH_BUTTON_PENDING = "#325688"
PUSH_BUTTON_PENDING_ACTIVE = "#41679c"
PUSH_BUTTON_PUSHED = "#4a607c"
PUSH_BUTTON_PUSHED_ACTIVE = "#5a708c"
REVERT_BUTTON = "#a25a07"
REVERT_BUTTON_ACTIVE = "#b87b12"
BUTTON_SURFACE = "#23293e"
BUTTON_SURFACE_ACTIVE = "#2a3347"
BADGE_STRIPE = "#5f6877"

INFO_ICON = "i"
DELETE_ICON = "🗑"
OPEN_FOLDER_ICON = "📁"
PUSH_ICON = "⤴"
REVERT_ICON = "↩"


def enable_windows_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def swap_border_color(swap: backend.SwapRecord) -> str:
    return GREEN if swap.is_pushed() else ORANGE


def format_item_details(item: backend.ItemRecord | None) -> str:
    if item is None:
        return "Select an item to inspect its details."
    return "\n".join(
        [
            f"Product: {item.product}",
            f"Item ID: {item.item_id}",
            f"Slot: {item.slot or '(unknown)'}",
            f"Quality: {item.quality or '(unknown)'}",
            f"Unlock Method: {item.unlock_method or '(unknown)'}",
            f"Asset Package: {item.asset_package}",
            f"Asset Path: {item.asset_path or '(unknown)'}",
        ]
    )


def format_swap_details(swap: backend.SwapRecord | None) -> str:
    if swap is None:
        return "Select a swap from the overview to inspect it."
    return "\n".join(
        [
            f"Run: {swap.run_name}",
            f"Status: {'Pushed' if swap.is_pushed() else 'Prepared, not pushed'}", 
            f"Created: {swap.created_at}",
            f"Pushed at: {swap.pushed_at or '(not pushed)'}",
            "",
            f"Target: {swap.target_product}",
            f"Target slot: {swap.target_slot or '(unknown)'}",
            f"Target quality: {swap.target_quality or '(unknown)'}",
            f"Target unlock: {swap.target_unlock_method or '(unknown)'}",
            f"Target asset package: {swap.target_asset_package}",
            f"Target asset path: {swap.target_asset_path or '(unknown)'}",
            "",
            f"Donor: {swap.donor_product}",
            f"Donor slot: {swap.donor_slot or '(unknown)'}",
            f"Donor quality: {swap.donor_quality or '(unknown)'}",
            f"Donor unlock: {swap.donor_unlock_method or '(unknown)'}",
            f"Donor asset package: {swap.donor_asset_package}",
            f"Donor asset path: {swap.donor_asset_path or '(unknown)'}",
            "",
            f"Thumbnail mode: {'with thumbnails' if swap.with_thumbnails else 'without thumbnails'}",
        ]
    )


class SwapManagerApp:
    def __init__(self, root: Tk) -> None:
        self.settings = config.load_settings()
        self.runs_dir = Path(self.settings.runs_dir)
        config.setup_logging()
        backend.ensure_workspace(self.settings.items_path, self.settings.swapper_path, self.runs_dir)
        self.root = root
        self.root.title("RL Swap Dashboard")
        self.root.geometry("1480x860")
        self.root.minsize(1220, 760)
        self.root.configure(bg=BG)

        self.items = backend.load_items(self.settings.items_path)
        self.filtered_items = list(self.items)
        self.swaps: list[backend.SwapRecord] = []
        self.selected_swap: backend.SwapRecord | None = None
        self.selected_item: backend.ItemRecord | None = None
        self.selected_donor: backend.ItemRecord | None = None
        self.selected_target: backend.ItemRecord | None = None
        self.selected_item_tree_id: str | None = None
        self.swap_cards: list[SwapCard] = []
        self.item_sort_column = "Product"
        self.item_sort_reverse = False
        self.drag_start_index: int | None = None
        self.drag_item: backend.ItemRecord | None = None
        self.drag_label: Label | None = None
        self.selected_tree_item: str | None = None
        self.swap_search_var = StringVar(value="")

        self.search_var = StringVar(value="")
        self.status_var = StringVar(value="Ready")
        self.include_thumbnails_var = BooleanVar(value=False)

        self._build_style()
        self._build_shell()
        self.root.bind_all("<Button-1>", self._clear_focus_from_non_text, add="+")
        self.show_overview()
        self.refresh_overview()

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except TclError:
            pass
        style.configure("TButton", focusthickness=0, focuscolor=BG)
        style.configure("TFrame", background=BG)
        style.configure("TButton", focusthickness=0, focuscolor=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("PanelAlt.TFrame", background=PANEL_ALT)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 18))
        style.configure("SubTitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("Accent.TButton", padding=(14, 9), background=ACCENT, foreground="#0a1020", borderwidth=0, relief="flat", focusthickness=0, focuscolor=BG)
        style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("pressed", ACCENT_HOVER)])
        style.configure("PendingAccent.TButton", padding=(14, 9), background=PUSH_BUTTON_PENDING, foreground="#eef4ff", borderwidth=0, relief="flat", focusthickness=0, focuscolor=BG)
        style.map("PendingAccent.TButton", background=[("active", PUSH_BUTTON_PENDING_ACTIVE), ("pressed", PUSH_BUTTON_PENDING_ACTIVE)])
        style.configure("PushedAccent.TButton", padding=(14, 9), background=PUSH_BUTTON_PUSHED, foreground="#eef4ff", borderwidth=0, relief="flat", focusthickness=0, focuscolor=BG)
        style.map("PushedAccent.TButton", background=[("active", PUSH_BUTTON_PUSHED_ACTIVE), ("pressed", PUSH_BUTTON_PUSHED_ACTIVE)])
        style.configure("RevertAccent.TButton", padding=(14, 9), background=REVERT_BUTTON, foreground="#1b1204", borderwidth=0, relief="flat", focusthickness=0, focuscolor=BG)
        style.map("RevertAccent.TButton", background=[("active", REVERT_BUTTON_ACTIVE), ("pressed", REVERT_BUTTON_ACTIVE)])
        style.configure("Info.TButton", padding=(4, 0), background=PANEL_ALT, foreground=TEXT, borderwidth=0, relief="flat", focusthickness=0, focuscolor=BG)
        style.configure("Info.TButton", padding=(4, 0), background=BUTTON_SURFACE, foreground=TEXT, borderwidth=0, relief="flat", focusthickness=0, focuscolor=BG)
        style.map("Info.TButton", background=[("active", BUTTON_SURFACE_ACTIVE)])
        style.configure("Ghost.TButton", padding=(14, 9), background=PANEL_ALT, foreground=TEXT, borderwidth=0, relief="flat", focusthickness=0, focuscolor=BG)
        style.configure("Ghost.TButton", padding=(14, 9), background=BUTTON_SURFACE, foreground=TEXT, borderwidth=0, relief="flat", focusthickness=0, focuscolor=BG)
        style.map("Ghost.TButton", background=[("active", BUTTON_SURFACE_ACTIVE)])
        style.configure("DeleteAccent.TButton", padding=(7, 4), background="#2a3142", foreground=MUTED, borderwidth=0, relief="flat", focusthickness=0, focuscolor=BG)
        style.map("DeleteAccent.TButton", background=[("active", "#394357"), ("pressed", "#394357")], foreground=[("active", TEXT), ("pressed", TEXT)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT, borderwidth=0, focuscolor=PANEL)
        style.map("TCheckbutton", background=[("active", PANEL), ("pressed", PANEL)], foreground=[("active", TEXT)])
        style.configure(
            "Treeview",
            background=INPUT,
            fieldbackground=INPUT,
            foreground=TEXT,
            rowheight=28,
            borderwidth=0,
            relief="flat",
        )
        style.map("Treeview", background=[("selected", "#2f3b55")])
        style.configure("Treeview.Heading", background=PANEL_ALT, foreground=TEXT, relief="flat", borderwidth=0)
        style.map("Treeview.Heading", background=[("active", "#242b3c"), ("pressed", "#242b3c")])
        style.configure("Vertical.TScrollbar", background=PANEL_ALT, troughcolor=PANEL, borderwidth=0, arrowcolor=TEXT, darkcolor=PANEL_ALT, lightcolor=PANEL_ALT)
        style.configure("DonorItem.Treeview", background=INPUT)
        style.configure("TargetItem.Treeview", background=INPUT)
        self.donor_tag_color = "#1e3a2e"
        self.target_tag_color = "#2e2e1e"
        style.configure("donor_item.Treeview", foreground="#4ade80")
        style.configure("target_item.Treeview", foreground="#fbbf24")
        # Ensure donor/target colors persist when rows are selected
        self.item_tree_donor_tag = "donor"
        self.item_tree_target_tag = "target"

    def _build_shell(self) -> None:
        self.shell = Frame(self.root, bg=BG)
        self.shell.pack(fill=BOTH, expand=True)

        self.overview_frame = Frame(self.shell, bg=BG)
        self.editor_frame = Frame(self.shell, bg=BG)

        self._build_overview()
        self._build_editor()

    def _build_overview(self) -> None:
        header = Frame(self.overview_frame, bg=BG, padx=22, pady=18)
        header.pack(fill=X)
        left = Frame(header, bg=BG)
        left.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(left, text="RL Swap Dashboard", style="Title.TLabel").pack(anchor="w")
        # ttk.Label(left, text="Prepared swaps are orange, pushed swaps are green.", style="SubTitle.TLabel").pack(anchor="w", pady=(4, 0))

        actions = Frame(header, bg=BG)
        actions.pack(side=RIGHT)
        ttk.Button(actions, text="Refresh", style="Ghost.TButton", command=self.refresh_overview).pack(side=RIGHT, padx=(0, 10))

        body = Frame(self.overview_frame, bg=BG, padx=22, pady=0)
        body.pack(fill=BOTH, expand=True)

        self.overview_left = Frame(body, bg=BG)
        self.overview_left.pack(side=LEFT, fill=BOTH, expand=True)
        left_header = Frame(self.overview_left, bg=BG)
        left_header.pack(fill=X, pady=(0, 10))
        Label(left_header, text="All swaps", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 13)).pack(side=LEFT)
        ttk.Button(left_header, text="Add New Swap", style="Accent.TButton", command=self.show_editor).pack(side=LEFT, padx=(12, 0))
        # Label(left_header, text="Click a swap to inspect it.", bg=BG, fg=MUTED).pack(side=RIGHT)

        swap_search_row = Frame(self.overview_left, bg=BG)
        swap_search_row.pack(fill=X, pady=(0, 12))
        swap_search_entry = Entry(
            swap_search_row,
            textvariable=self.swap_search_var,
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        swap_search_entry.pack(side=LEFT, fill=X, expand=True, ipady=7)
        swap_search_entry.bind("<KeyRelease>", lambda _event: self.refresh_overview())
        ttk.Button(swap_search_row, text="Clear", style="Ghost.TButton", command=self.clear_swap_search).pack(side=LEFT, padx=(10, 0))

        self.cards_scroll = ScrollableFrame(self.overview_left, bg=BG)
        self.cards_scroll.pack(fill=BOTH, expand=True)

        footer = Frame(self.overview_frame, bg=BG, padx=22, pady=14)
        footer.pack(fill=X)
        Label(footer, textvariable=self.status_var, bg=BG, fg=MUTED).pack(anchor="w")

    def _build_editor(self) -> None:
        header = Frame(self.editor_frame, bg=BG, padx=22, pady=18)
        header.pack(fill=X)
        left = Frame(header, bg=BG)
        left.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(left, text="Add New Swap", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Search items, then drag to assign donor and target. Click chips to clear.", style="SubTitle.TLabel").pack(anchor="w", pady=(4, 0))
        actions = Frame(header, bg=BG)
        actions.pack(side=RIGHT)
        ttk.Button(actions, text="Back to Overview", style="Ghost.TButton", command=self.show_overview).pack(side=RIGHT)

        body = Frame(self.editor_frame, bg=BG, padx=22, pady=0)
        body.pack(fill=BOTH, expand=True)

        controls = Frame(body, bg=BG)
        controls.pack(side=LEFT, fill=BOTH, expand=True)
        inspector = Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, width=420)
        inspector.pack(side=RIGHT, fill=Y, padx=(18, 0))
        inspector.pack_propagate(False)

        self.search_entry_var = StringVar(value="")
        Label(controls, text="Item lookup", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 13)).pack(anchor="w")
        search_row = Frame(controls, bg=BG)
        search_row.pack(fill=X, pady=(10, 8))
        search_entry = Entry(search_row, textvariable=self.search_entry_var, bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat", highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        search_entry.pack(side=LEFT, fill=X, expand=True, ipady=7)
        search_entry.bind("<KeyRelease>", lambda _event: self.refresh_items())
        ttk.Button(search_row, text="Search", style="Ghost.TButton", command=self.refresh_items).pack(side=LEFT, padx=(10, 0))

        selection_row = Frame(controls, bg=BG)
        selection_row.pack(fill=X, pady=(0, 12))
        self.replace_chip = Label(selection_row, text="Replace", bg=BG, fg=MUTED, font=("Segoe UI", 11))
        self.replace_chip.pack(side=LEFT, padx=(0, 10))
        self.target_chip = Label(selection_row, text="↙ Drag target here", bg="#1e293b", fg=MUTED, padx=12, pady=8)
        self.target_chip.pack(side=LEFT, padx=(0, 10))
        self.target_chip.bind("<Enter>", lambda e: self.target_chip.config(bg=self.target_tag_color))
        self.target_chip.bind("<Leave>", lambda e: self.target_chip.config(bg="#1e293b"))
        self.with_chip = Label(selection_row, text="with", bg=BG, fg=MUTED, font=("Segoe UI", 11))
        self.with_chip.pack(side=LEFT, padx=(0, 10))
        self.donor_chip = Label(selection_row, text="↙ Drag donor here", bg="#1e293b", fg=MUTED, padx=12, pady=8)
        self.donor_chip.pack(side=LEFT, padx=(0, 10))
        self.donor_chip.bind("<Enter>", lambda e: self.donor_chip.config(bg=self.donor_tag_color))
        self.donor_chip.bind("<Leave>", lambda e: self.donor_chip.config(bg="#1e293b"))
        
        # Make chips drop targets
        self.donor_chip.bind("<Button-1>", lambda e: self._clear_donor())
        self.target_chip.bind("<Button-1>", lambda e: self._clear_target())
        
        # Prepare swap button row (right-aligned on same row)
        ttk.Button(selection_row, text="Prepare Swap", style="Accent.TButton", command=self.prepare_selected_swap).pack(side=RIGHT)
        ttk.Checkbutton(selection_row, text="Include thumbnails", variable=self.include_thumbnails_var).pack(side=RIGHT, padx=(0, 10))

        item_table_frame = Frame(controls, bg=BG)
        item_table_frame.pack(fill=BOTH, expand=True)
        cols = ("Product", "Slot", "Quality", "Package", "ID")
        self.item_tree = ttk.Treeview(item_table_frame, columns=cols, show="headings", selectmode="none")
        for col in cols:
            self.item_tree.heading(col, text=col, command=lambda c=col: self.sort_items_by_column(c))
        self.item_tree.column("Product", width=230, anchor="w")
        self.item_tree.column("Slot", width=120, anchor="w")
        self.item_tree.column("Quality", width=100, anchor="w")
        self.item_tree.column("Package", width=260, anchor="w")
        self.item_tree.column("ID", width=80, anchor="center")
        item_scroll = ttk.Scrollbar(item_table_frame, orient="vertical", command=self.item_tree.yview)
        self.item_tree.configure(yscrollcommand=item_scroll.set)
        self.item_tree.pack(side=LEFT, fill=BOTH, expand=True)
        item_scroll.pack(side=RIGHT, fill=Y)
        self.item_tree.bind("<<TreeviewSelect>>", self.on_item_select)
        self.item_tree.bind("<Button-1>", self._on_tree_click)
        self.item_tree.bind("<B1-Motion>", self._drag_motion)
        self.item_tree.bind("<ButtonRelease-1>", self._drop_item)



        inspector_inner = Frame(inspector, bg=PANEL, padx=16, pady=16)
        inspector_inner.pack(fill=BOTH, expand=True)
        Label(inspector_inner, text="Selected item", bg=PANEL, fg=TEXT, font=("Segoe UI Semibold", 13)).pack(anchor="w")
        self.item_detail_text = Text(
            inspector_inner,
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            wrap="word",
            height=18,
            padx=12,
            pady=12,
        )
        self.item_detail_text.pack(fill=BOTH, expand=True, pady=(12, 0))
        self.item_detail_text.configure(state="disabled")

        ttk.Button(inspector_inner, text="Cancel", style="Ghost.TButton", command=self.show_overview).pack(anchor="e", pady=(14, 0))

    def show_overview(self) -> None:
        self.editor_frame.pack_forget()
        self.overview_frame.pack(fill=BOTH, expand=True)
        self.refresh_overview()

    def show_editor(self) -> None:
        self.overview_frame.pack_forget()
        self.editor_frame.pack(fill=BOTH, expand=True)
        self.refresh_items()
        self._set_item_text(self.item_detail_text, "Select an item from the list.")

    def refresh_overview(self, select_run_name: str | None = None) -> None:
        self.swaps = backend.list_swaps(self.runs_dir)
        query = self.swap_search_var.get().strip().lower()
        if query:
            self.swaps = [
                swap
                for swap in self.swaps
                if query in swap.run_name.lower()
                or query in swap.target_product.lower()
                or query in swap.donor_product.lower()
                or query in (swap.target_slot or "").lower()
                or query in (swap.donor_slot or "").lower()
                or query in ("pushed" if swap.is_pushed() else "prepared")
            ]
        if select_run_name is not None:
            for swap in self.swaps:
                if swap.run_name == select_run_name:
                    self.selected_swap = swap
                    break
        if self.selected_swap is not None and all(swap.run_name != self.selected_swap.run_name for swap in self.swaps):
            self.selected_swap = None

        for child in self.cards_scroll.content.winfo_children():
            child.destroy()
        self.swap_cards = []

        if not self.swaps:
            empty = Frame(self.cards_scroll.content, bg=BG, pady=24)
            empty.pack(fill=X)
            Label(empty, text="No swaps yet. Click 'Add New Swap' to prepare one.", bg=BG, fg=MUTED, font=("Segoe UI", 11)).pack(anchor="w")
        else:
            for swap in self.swaps:
                card = SwapCard(
                    self.cards_scroll.content,
                    swap,
                    self.select_swap,
                    self.show_swap_details_popup,
                    self.open_swap_folder,
                    self.confirm_push_swap,
                    self.confirm_revert_swap,
                    self.confirm_delete_swap,
                    selected=False,
                )
                card.pack(fill=X, pady=(0, 12))
                self.swap_cards.append(card)

        self.status_var.set(f"Loaded {len(self.swaps)} swaps")

    def clear_swap_search(self) -> None:
        self.swap_search_var.set("")
        self.refresh_overview()

    def _clear_focus_from_non_text(self, event: object) -> None:
        widget = getattr(event, "widget", None)
        if widget is None:
            return
        widget_class = widget.winfo_class() if hasattr(widget, "winfo_class") else ""
        if widget_class in {"Entry", "Text"}:
            return
        self.root.focus_set()

    def select_swap(self, swap: backend.SwapRecord) -> None:
        _ = swap

    def _set_text_widget(self, widget: Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", END)
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _set_item_text(self, widget: Text, text: str) -> None:
        self._set_text_widget(widget, text)

    def show_swap_details_popup(self, swap: backend.SwapRecord) -> None:
        popup = Toplevel(self.root)
        popup.title(f"Swap Details - {swap.run_name}")
        popup.configure(bg=BG)
        popup.transient(self.root)
        popup.grab_set()
        popup.geometry("640x560")

        outer = Frame(popup, bg=BG, padx=16, pady=16)
        outer.pack(fill=BOTH, expand=True)

        Label(outer, text="Swap details", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 15)).pack(anchor="w")
        Label(outer, text=swap.run_name, bg=BG, fg=MUTED).pack(anchor="w", pady=(2, 12))

        details = Text(
            outer,
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            wrap="word",
            height=24,
            padx=12,
            pady=12,
        )
        details.pack(fill=BOTH, expand=True)
        details.insert("1.0", format_swap_details(swap))
        details.configure(state="disabled")

        ttk.Button(outer, text="Close", style="Ghost.TButton", command=popup.destroy).pack(anchor="e", pady=(12, 0))

    def refresh_items(self) -> None:
        query = self.search_entry_var.get().strip()
        self.filtered_items = backend.search_items(self.items, query)
        self.filtered_items.sort(key=self._item_sort_key, reverse=self.item_sort_reverse)
        self.selected_tree_item = None
        for row in self.item_tree.get_children():
            self.item_tree.delete(row)
        for index, item in enumerate(self.filtered_items):
            self.item_tree.insert("", END, iid=str(index), values=(item.product, item.slot, item.quality, item.asset_package, item.item_id))
        self._update_tree_styling()
        self.status_var.set(f"Found {len(self.filtered_items)} items")

    def _current_item(self) -> backend.ItemRecord | None:
        selection = self.item_tree.selection()
        if not selection:
            return None
        index = int(selection[0])
        if index < 0 or index >= len(self.filtered_items):
            return None
        return self.filtered_items[index]

    def on_item_select(self, _event: object) -> None:
        self.selected_item = self._current_item()
        self._set_item_text(self.item_detail_text, format_item_details(self.selected_item))
        self._update_tree_styling()

    def _on_tree_click(self, event: object) -> None:
        """Handle tree clicks for selection and drag start."""
        item_id = self.item_tree.identify_row(event.y)
        if item_id:
            # Manually handle selection to preserve tag colors
            self.selected_tree_item = item_id
            
            # Update the selected item and inspector panel
            index = int(item_id)
            if 0 <= index < len(self.filtered_items):
                self.selected_item = self.filtered_items[index]
                self._set_item_text(self.item_detail_text, format_item_details(self.selected_item))
            
            self._start_drag(event)
        self._update_tree_styling()

    def _start_drag(self, event: object) -> None:
        """Start a drag operation when clicking on a tree item."""
        try:
            # Get the item directly under the mouse cursor
            item_id = self.item_tree.identify_row(event.y)
            if not item_id:
                return
            
            index = int(item_id)
            if index < 0 or index >= len(self.filtered_items):
                return
            
            self.drag_start_index = index
            self.drag_item = self.filtered_items[index]
            
            # Create a floating label that shows what's being dragged
            self.drag_label = Label(
                self.root,
                text=f"↙ {self.drag_item.product}",
                bg=PANEL,
                fg=TEXT,
                padx=10,
                pady=6,
                relief="solid",
                bd=1,
                borderwidth=2,
                highlightthickness=0
            )
            # Get actual cursor position from system and convert to window-relative coords
            cursor_x = self.root.winfo_pointerx()
            cursor_y = self.root.winfo_pointery()
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            window_x = cursor_x - root_x
            window_y = cursor_y - root_y
            # Position relative to window
            self.drag_label.place(x=window_x, y=window_y)
        except (ValueError, IndexError, AttributeError):
            pass

    def _drag_motion(self, event: object) -> None:
        """Update drag label position to follow mouse."""
        if self.drag_item is None or self.drag_label is None:
            return
        
        try:
            # Get actual cursor position from system and convert to window-relative coords
            cursor_x = self.root.winfo_pointerx()
            cursor_y = self.root.winfo_pointery()
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            window_x = cursor_x - root_x
            window_y = cursor_y - root_y
            # Move relative to window
            self.drag_label.place(x=window_x, y=window_y)
        except Exception:
            pass

    def _drop_item(self, event: object) -> None:
        """Handle drop on donor or target chips."""
        # Clean up drag label
        if self.drag_label is not None:
            try:
                self.drag_label.destroy()
            except Exception:
                pass
            self.drag_label = None
        
        if self.drag_item is None:
            self.drag_start_index = None
            return

        try:
            # Get absolute mouse position
            abs_x = event.x_root
            abs_y = event.y_root
            
            # Get donor chip bounds
            donor_abs_x = self.donor_chip.winfo_rootx()
            donor_abs_y = self.donor_chip.winfo_rooty()
            donor_w = self.donor_chip.winfo_width()
            donor_h = self.donor_chip.winfo_height()
            
            # Get target chip bounds
            target_abs_x = self.target_chip.winfo_rootx()
            target_abs_y = self.target_chip.winfo_rooty()
            target_w = self.target_chip.winfo_width()
            target_h = self.target_chip.winfo_height()
            
            # Check if over donor chip
            if (donor_abs_x <= abs_x <= donor_abs_x + donor_w and
                donor_abs_y <= abs_y <= donor_abs_y + donor_h):
                self._set_as_donor(self.drag_item)
            # Check if over target chip
            elif (target_abs_x <= abs_x <= target_abs_x + target_w and
                  target_abs_y <= abs_y <= target_abs_y + target_h):
                self._set_as_target(self.drag_item)
        except Exception:
            pass
        finally:
            self.drag_start_index = None
            self.drag_item = None

    def _set_as_donor(self, item: backend.ItemRecord) -> None:
        """Set an item as the donor. Only swap if it's coming from target."""
        # If same item is already donor, do nothing
        if self.selected_donor and self.selected_donor.item_id == item.item_id:
            return
        
        # If item is currently in target, move it (swap)
        if self.selected_donor is None:
            # Donor is empty, just set it
            pass
        elif self.selected_target and self.selected_target.item_id == item.item_id:
            # Item is coming from target, swap them
            self.selected_target = self.selected_donor
        # If item is new (not in target or donor), just replace donor
        
        self.selected_donor = item
        self.donor_chip.config(text=f"🎁 {item.product}", fg=GREEN)
        
        # Update target chip display if it changed
        if self.selected_target:
            self.target_chip.config(text=f"🎯 {self.selected_target.product}", fg=ORANGE)
        else:
            self.target_chip.config(text="↙ Drag target here", fg=MUTED)
        
        self._update_tree_styling()
        self.status_var.set(f"Selected donor: {item.product}")

    def _set_as_target(self, item: backend.ItemRecord) -> None:
        """Set an item as the target. Only swap if it's coming from donor."""
        # If same item is already target, do nothing
        if self.selected_target and self.selected_target.item_id == item.item_id:
            return
        
        # If item is currently in donor, move it (swap)
        if self.selected_target is None:
            # Target is empty, just set it
            pass
        elif self.selected_donor and self.selected_donor.item_id == item.item_id:
            # Item is coming from donor, swap them
            self.selected_donor = self.selected_target
        # If item is new (not in donor or target), just replace target
        
        self.selected_target = item
        self.target_chip.config(text=f"🎯 {item.product}", fg=ORANGE)
        
        # Update donor chip display if it changed
        if self.selected_donor:
            self.donor_chip.config(text=f"🎁 {self.selected_donor.product}", fg=GREEN)
        else:
            self.donor_chip.config(text="↙ Drag donor here", fg=MUTED)
        
        self._update_tree_styling()
        self.status_var.set(f"Selected target: {item.product}")

    def _clear_donor(self) -> None:
        """Clear the donor selection (click on chip to clear)."""
        self.selected_donor = None
        self.donor_chip.config(text="↙ Drag donor here", fg=MUTED)
        self._update_tree_styling()
        self.status_var.set("Cleared donor selection")

    def _clear_target(self) -> None:
        """Clear the target selection (click on chip to clear)."""
        self.selected_target = None
        self.target_chip.config(text="↙ Drag target here", fg=MUTED)
        self._update_tree_styling()
        self.status_var.set("Cleared target selection")

    def _update_tree_styling(self) -> None:
        """Update tree item colors to reflect donor/target status and selection."""
        # Configure tags with explicit foreground colors
        self.item_tree.tag_configure("donor", foreground=GREEN)
        self.item_tree.tag_configure("target", foreground=ORANGE)
        self.item_tree.tag_configure("selected", background="#2f3b55")
        
        for i, item in enumerate(self.filtered_items):
            iid = str(i)
            tags = []
            
            # Add donor/target tag
            if self.selected_donor and self.selected_donor.item_id == item.item_id:
                tags.append("donor")
            elif self.selected_target and self.selected_target.item_id == item.item_id:
                tags.append("target")
            
            # Add selected tag if this item is manually selected
            if iid == self.selected_tree_item:
                tags.append("selected")
            
            self.item_tree.item(iid, tags=tuple(tags))

    def sort_items_by_column(self, col: str) -> None:
        if self.item_sort_column == col:
            self.item_sort_reverse = not self.item_sort_reverse
        else:
            self.item_sort_column = col
            self.item_sort_reverse = False
        self.refresh_items()

    def _item_sort_key(self, item: backend.ItemRecord) -> tuple[int, str]:
        if self.item_sort_column == "ID":
            return (0, f"{item.item_id:020d}")
        value = {
            "Product": item.product,
            "Slot": item.slot,
            "Quality": item.quality,
            "Package": item.asset_package,
        }.get(self.item_sort_column, item.product)
        return (0, (value or "").lower())

    def confirm_delete_swap(self, swap: backend.SwapRecord) -> None:
        if swap.is_pushed():
            messagebox.showinfo("Swap pushed", "Only prepared swaps can be deleted.")
            return
        if not messagebox.askyesno("Delete prepared swap", f"Delete the prepared swap run '{swap.run_name}'? This removes the local swap files."):
            return
        backend.delete_swap(swap)
        if self.selected_swap is not None and self.selected_swap.run_name == swap.run_name:
            self.selected_swap = None
        self.refresh_overview()

    def prepare_selected_swap(self) -> None:
        if self.selected_donor is None or self.selected_target is None:
            messagebox.showwarning("Missing selection", "Pick both a donor and a target first.")
            return
        if self.selected_donor.item_id == self.selected_target.item_id:
            messagebox.showwarning("Invalid swap", "Donor and target must be different items.")
            return
        if self.selected_donor.slot != self.selected_target.slot:
            messagebox.showerror(
                "Incompatible slots",
                f"Donor is a {self.selected_donor.slot or 'unknown'} item and target is a {self.selected_target.slot or 'unknown'} item. "
                "This swapper only supports items from the same slot.",
            )
            self.status_var.set("Swap blocked: donor and target slots do not match")
            return
        try:
            rl_source_dir = Path(self.settings.rl_source_dir)
            swap = backend.prepare_swap(
                self.selected_donor,
                self.selected_target,
                swapper_path=self.settings.swapper_path,
                items_path=self.settings.items_path,
                keys_path=self.settings.keys_path,
                keys_map_path=self.settings.keys_map_path,
                source_dir=rl_source_dir,
                runs_dir=self.runs_dir,
                work_dir=self.settings.work_path,
                with_thumbnails=self.include_thumbnails_var.get(),
            )
        except SystemExit as exc:
            messagebox.showerror("Prepare failed", str(exc))
            return
        self.status_var.set(f"Prepared {swap.run_name}")
        self.selected_swap = swap
        self.show_overview()
        self.refresh_overview(select_run_name=swap.run_name)
        messagebox.showinfo("Swap prepared", f"Prepared swap:\n{swap.run_name}")

    def confirm_push_swap(self, swap: backend.SwapRecord) -> None:
        if not messagebox.askyesno("Confirm push", f"Mark '{swap.run_name}' as pushed?\n\nThis will copy the prepared files into the live RL folder and update the saved swap state."):
            return
        try:
            rl_source_dir = Path(self.settings.rl_source_dir)
            updated = backend.push_swap(swap, rl_source_dir)
        except SystemExit as exc:
            messagebox.showerror("Push failed", str(exc))
            return
        self.selected_swap = updated
        self.refresh_overview(select_run_name=updated.run_name)
        messagebox.showinfo("Swap pushed", f"Marked as pushed:\n{updated.target_name}")

    def confirm_revert_swap(self, swap: backend.SwapRecord) -> None:
        if not messagebox.askyesno("Confirm revert", f"Revert '{swap.run_name}' back to not pushed?\n\nThis will restore the original target from backup into the live RL folder and update the saved swap state."):
            return
        try:
            rl_source_dir = Path(self.settings.rl_source_dir)
            updated = backend.revert_swap(swap, rl_source_dir)
        except SystemExit as exc:
            messagebox.showerror("Revert failed", str(exc))
            return
        self.selected_swap = updated
        self.refresh_overview(select_run_name=updated.run_name)
        messagebox.showinfo("Swap reverted", f"Marked as not pushed:\n{updated.target_name}")

    def open_swap_folder(self, swap: backend.SwapRecord) -> None:
        path = Path(swap.run_dir)
        try:
            if not path.exists():
                messagebox.showerror("Open failed", f"Swap folder not found:\n{path}")
                return
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))


def run_ui() -> int:
    try:
        enable_windows_dpi_awareness()
        root = Tk()
    except TclError as exc:
        raise SystemExit(f"Unable to start the UI: {exc}") from exc
    SwapManagerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_ui())
