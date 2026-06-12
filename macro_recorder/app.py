from __future__ import annotations

import ctypes
import json
import shutil
import threading
import tkinter as tk
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Dict, List, Optional, Tuple

from .map_classification import (
    MapClassificationError,
    classify_map_patch,
    format_classification_log,
    normalize_map_id,
    save_map_reference,
)
from .models import (
    BLOCK_LABELS,
    PIXEL_SAMPLING_MODES,
    PIXEL_SAMPLING_SINGLE,
    REGION_DETECTION_MODES,
    REGION_MODE_EXPECTED,
    REGION_MODE_GREEN,
    REGION_MODE_HSV,
    ROOT_ONLY_BLOCK_TYPES,
    Macro,
    MacroBlock,
    block_display_name,
    block_summary,
    color_to_hex,
    color_to_rgb_text,
    control_flow_errors,
    convert_clicks_to_move_and_click,
    find_block,
    normalize_label_name,
    normalize_sampling_mode,
    normalize_region,
    normalize_region_detection_mode,
    parse_color,
    root_label_names,
)
from .pixel_sampling import PixelSampleResult, sample_pixel_for_params
from .region_detection import (
    RegionCheckResult,
    check_region_for_params,
    region_colour_diagnostics,
    region_mode_details,
)
from .runner import MacroRunner
from .storage import MacroStorage
from .vision_backend import CapturedFrame, ScreenAnalysisBackend
from .win32_automation import (
    AutomationError,
    GlobalHotkey,
    InputController,
    UserKeyboardMonitor,
    UserMouseMonitor,
    WindowManager,
    enable_dpi_awareness,
    format_window,
    vk_code_to_key,
)


class TargetMarkerOverlay:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.window: Optional[tk.Toplevel] = None
        self.canvas: Optional[tk.Canvas] = None
        self.size = 76
        self.hwnd: Optional[int] = None

    def show(self, screen_x: int, screen_y: int, label: str) -> bool:
        if not self.window:
            self._create_window()
        if not self.window or not self.canvas:
            return False

        left = screen_x - self.size // 2
        top = screen_y - self.size // 2
        self.window.geometry(f"{self.size}x{self.size}+{left}+{top}")
        self._draw(label)
        self.window.deiconify()
        self.window.lift()
        self._make_click_through()
        if not self.has_click_through_style():
            self.hide()
            return False
        return True

    def hide(self) -> None:
        if self.window:
            self.window.withdraw()

    def destroy(self) -> None:
        if self.window:
            self.window.destroy()
            self.window = None
            self.canvas = None
            self.hwnd = None

    def _create_window(self) -> None:
        window = tk.Toplevel(self.root)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.attributes("-alpha", 0.92)
        try:
            window.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        try:
            window.attributes("-disabled", True)
        except tk.TclError:
            pass
        canvas = tk.Canvas(
            window,
            width=self.size,
            height=self.size,
            highlightthickness=0,
            bg="#111111",
        )
        canvas.pack(fill="both", expand=True)
        self.window = window
        self.canvas = canvas
        window.update_idletasks()
        self.hwnd = int(window.winfo_id())
        self._make_click_through()

    def _draw(self, label: str) -> None:
        if not self.canvas:
            return
        c = self.canvas
        c.delete("all")
        mid = self.size // 2
        radius = 10
        c.create_rectangle(0, 0, self.size, self.size, fill="#111111", outline="#E02121", width=1)
        c.create_line(mid - 30, mid, mid + 30, mid, fill="white", width=5)
        c.create_line(mid, mid - 30, mid, mid + 30, fill="white", width=5)
        c.create_oval(
            mid - radius,
            mid - radius,
            mid + radius,
            mid + radius,
            outline="white",
            width=5,
        )
        c.create_line(mid - 30, mid, mid + 30, mid, fill="#E02121", width=3)
        c.create_line(mid, mid - 30, mid, mid + 30, fill="#E02121", width=3)
        c.create_oval(
            mid - radius,
            mid - radius,
            mid + radius,
            mid + radius,
            outline="#E02121",
            width=3,
        )
        c.create_text(mid + 1, mid + 31, text=label, fill="white", font=("Segoe UI", 9, "bold"))
        c.create_text(mid, mid + 30, text=label, fill="#E02121", font=("Segoe UI", 9, "bold"))

    def _make_click_through(self) -> None:
        if not self.window:
            return
        try:
            hwnd = self.hwnd or int(self.window.winfo_id())
            self.hwnd = hwnd
            user32 = ctypes.windll.user32
            gwl_exstyle = -20
            ws_ex_layered = 0x00080000
            ws_ex_transparent = 0x00000020
            ws_ex_toolwindow = 0x00000080
            ws_ex_noactivate = 0x08000000
            hwnd_topmost = -1
            swp_nosize = 0x0001
            swp_nomove = 0x0002
            swp_noactivate = 0x0010
            swp_framechanged = 0x0020
            lwa_alpha = 0x00000002

            get_window_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_window_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = ctypes.c_ssize_t
            set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            set_window_long.restype = ctypes.c_ssize_t
            user32.SetLayeredWindowAttributes.argtypes = [
                wintypes.HWND,
                wintypes.COLORREF,
                wintypes.BYTE,
                wintypes.DWORD,
            ]
            user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL

            style = get_window_long(hwnd, gwl_exstyle)
            set_window_long(
                hwnd,
                gwl_exstyle,
                style
                | ws_ex_layered
                | ws_ex_transparent
                | ws_ex_toolwindow
                | ws_ex_noactivate,
            )
            user32.SetLayeredWindowAttributes(hwnd, 0, 235, lwa_alpha)
            user32.SetWindowPos(
                hwnd,
                hwnd_topmost,
                0,
                0,
                0,
                0,
                swp_nomove | swp_nosize | swp_noactivate | swp_framechanged,
            )
        except Exception:
            pass

    def has_click_through_style(self) -> bool:
        if not self.window:
            return False
        try:
            hwnd = self.hwnd or int(self.window.winfo_id())
            user32 = ctypes.windll.user32
            get_window_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = ctypes.c_ssize_t
            style = get_window_long(hwnd, -20)
            return bool(style & 0x00000020)
        except Exception:
            return False


class TargetRegionOverlay(TargetMarkerOverlay):
    def show_region(
        self,
        screen_left: int,
        screen_top: int,
        screen_right: int,
        screen_bottom: int,
        label: str,
    ) -> bool:
        if not self.window:
            self._create_window()
        if not self.window or not self.canvas:
            return False

        left = min(screen_left, screen_right)
        top = min(screen_top, screen_bottom)
        right = max(screen_left, screen_right)
        bottom = max(screen_top, screen_bottom)
        padding = 10
        width = max(36, right - left + 1 + padding * 2)
        height = max(36, bottom - top + 1 + padding * 2)
        self.window.attributes("-alpha", 0.55)
        self.window.geometry(f"{width}x{height}+{left - padding}+{top - padding}")
        self.canvas.configure(width=width, height=height)
        self._draw_region(width, height, padding, label)
        self.window.deiconify()
        self.window.lift()
        self._make_click_through()
        if not self.has_click_through_style():
            self.hide()
            return False
        return True

    def _draw_region(self, width: int, height: int, padding: int, label: str) -> None:
        if not self.canvas:
            return
        c = self.canvas
        c.delete("all")
        c.create_rectangle(0, 0, width, height, fill="#111111", outline="")
        c.create_rectangle(
            padding,
            padding,
            width - padding - 1,
            height - padding - 1,
            outline="white",
            width=5,
        )
        c.create_rectangle(
            padding,
            padding,
            width - padding - 1,
            height - padding - 1,
            outline="#E02121",
            width=3,
        )
        c.create_text(
            padding + 4,
            max(12, padding - 2),
            anchor="w",
            text=label,
            fill="white",
            font=("Segoe UI", 9, "bold"),
        )
        c.create_text(
            padding + 3,
            max(11, padding - 3),
            anchor="w",
            text=label,
            fill="#E02121",
            font=("Segoe UI", 9, "bold"),
        )


class MacroEditorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Window-Relative Macro Recorder")
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        default_width = min(1600, max(1, screen_width - 60))
        default_height = min(900, max(1, screen_height - 100))
        self.root.geometry(f"{default_width}x{default_height}")
        self.root.minsize(min(1040, default_width), min(650, default_height))

        self.storage = MacroStorage(Path.cwd() / "macros")
        self.window_manager = WindowManager()
        self.screen_analysis = ScreenAnalysisBackend(
            self.window_manager, Path.cwd() / "debug_captures"
        )
        self.input_controller = InputController(self.window_manager)
        self.runner = MacroRunner(
            self.window_manager,
            self.input_controller,
            self.screen_analysis,
            self.threadsafe_log,
            self.threadsafe_running_state,
            storage=self.storage,
        )
        self.hotkey = GlobalHotkey(self.on_global_stop)
        self.hotkey.start()
        self.user_keyboard_monitor = UserKeyboardMonitor(self.on_user_keyboard_input)
        self.user_mouse_monitor = UserMouseMonitor(self.on_user_mouse_click)
        self.marker_overlay = TargetMarkerOverlay(root)
        self.region_overlay = TargetRegionOverlay(root)
        self.marker_enabled_var = tk.BooleanVar(value=True)
        self.debug_captures_var = tk.BooleanVar(value=True)
        self.screen_analysis.debug_captures_enabled = True
        self.last_probe_capture: Optional[CapturedFrame] = None
        self.last_probe_label = "probe"
        self.last_probe_result = "capture"
        self.marker_update_after_id: Optional[str] = None
        self.last_marker_error: Optional[str] = None
        self.builder_bounds = (0, 0, 0, 0)
        self.stop_button: Optional[ttk.Button] = None
        self.record_button: Optional[ttk.Button] = None
        self.stop_recording_button: Optional[ttk.Button] = None
        self.recording = False
        self.recording_count = 0
        self.recording_target_list: Optional[List[MacroBlock]] = None
        self.recording_insert_index = 0
        self.recording_indicator_var = tk.StringVar(value="")
        self.unsaved_indicator_var = tk.StringVar(value="")
        self._saved_snapshot = ""
        self.dirty_check_after_id: Optional[str] = None

        self.macro = Macro()
        self.block_item_ids: set[str] = set()
        self.block_clipboard: List[MacroBlock] = []
        self.context_menu_block_id: Optional[str] = None
        self.property_vars: Dict[str, tk.Variable] = {}
        self.probe_result_var = tk.StringVar(value="")
        self.running = False
        self.closing = False

        self._build_ui()
        self.refresh_macro_list()
        self.refresh_all()
        self._mark_clean()
        self.root.bind("<Configure>", self.update_builder_bounds, add="+")
        self.root.bind_all("<MouseWheel>", self._on_properties_mousewheel, add="+")
        self.root.after(100, self.update_builder_bounds)
        self.dirty_check_after_id = self.root.after(300, self._refresh_dirty_indicator)
        self.root.bind(
            "<Escape>",
            lambda _event: self.stop_macro("Escape key pressed in Macro Builder."),
        )
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        self._build_toolbar()

        self.status_var = tk.StringVar(value="")
        status = ttk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            padding=(8, 4),
        )
        status.pack(fill="x")
        self.notice_var = tk.StringVar(value="")
        self.notice_label = ttk.Label(
            self.root,
            textvariable=self.notice_var,
            anchor="w",
            padding=(8, 4),
            foreground="#8A1F11",
        )
        self.notice_label.pack(fill="x")

        vertical = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        vertical.pack(fill="both", expand=True)

        panels = ttk.PanedWindow(vertical, orient=tk.HORIZONTAL)
        vertical.add(panels, weight=5)

        self.left_panel = ttk.Frame(panels, padding=8)
        self.middle_panel = ttk.Frame(panels, padding=8)
        self.right_panel = ttk.Frame(panels, padding=8)
        panels.add(self.left_panel, weight=1)
        panels.add(self.middle_panel, weight=3)
        panels.add(self.right_panel, weight=2)

        self._build_left_panel()
        self._build_middle_panel()
        self._build_right_panel()
        self._build_log_panel(vertical)

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        toolbar.pack(fill="x")
        action_row = ttk.Frame(toolbar)
        action_row.pack(fill="x")
        detail_row = ttk.Frame(toolbar)
        detail_row.pack(fill="x", pady=(6, 0))

        actions = [
            ("New", self.new_macro),
            ("Save", self.save_macro),
            ("Save As", self.save_macro_as),
            ("Load", self.load_selected_macro),
            ("Bind Target", self.open_bind_window),
            ("Run", self.run_macro),
            ("Stop", self.stop_macro),
            ("Record", self.start_recording),
            ("Stop Recording", self.stop_recording),
        ]
        for label, command in actions:
            button = ttk.Button(action_row, text=label, command=command)
            button.pack(side="left", padx=(0, 6))
            if label == "Stop":
                self.stop_button = button
            elif label == "Record":
                self.record_button = button
            elif label == "Stop Recording":
                self.stop_recording_button = button
                button.state(["disabled"])

        ttk.Label(detail_row, text="Macro").pack(side="left", padx=(0, 4))
        self.macro_name_var = tk.StringVar()
        name_entry = ttk.Entry(detail_row, textvariable=self.macro_name_var, width=28)
        name_entry.pack(side="left")
        name_entry.bind("<FocusOut>", lambda _event: self.apply_macro_header())
        name_entry.bind("<Return>", lambda _event: self.apply_macro_header())

        ttk.Label(
            detail_row,
            textvariable=self.recording_indicator_var,
            foreground="#B00020",
        ).pack(side="right", padx=(8, 0))
        ttk.Label(
            detail_row,
            textvariable=self.unsaved_indicator_var,
            foreground="#8A1F11",
        ).pack(side="right", padx=(8, 0))
        ttk.Label(detail_row, text="Any key or app click stops while running").pack(side="right")

    def _build_left_panel(self) -> None:
        ttk.Label(self.left_panel, text="Saved Macros").pack(anchor="w")
        self.macro_list = tk.Listbox(self.left_panel, exportselection=False)
        self.macro_list.pack(fill="both", expand=True, pady=(6, 6))
        self.macro_list.bind("<Double-Button-1>", lambda _event: self.load_selected_macro())

        button_row = ttk.Frame(self.left_panel)
        button_row.pack(fill="x")
        ttk.Button(button_row, text="Refresh", command=self.refresh_macro_list).pack(
            side="left"
        )
        ttk.Button(button_row, text="Open JSON", command=self.load_from_file).pack(
            side="left", padx=(6, 0)
        )
        order_row = ttk.Frame(self.left_panel)
        order_row.pack(fill="x", pady=(5, 0))
        ttk.Button(order_row, text="Move Up", command=lambda: self.move_saved_macro(-1)).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(order_row, text="Move Down", command=lambda: self.move_saved_macro(1)).pack(
            side="left", padx=(6, 0)
        )
        utilities = ttk.LabelFrame(self.left_panel, text="Utilities", padding=6)
        utilities.pack(fill="x", pady=(8, 0))
        ttk.Button(
            utilities,
            text="Convert Clicks to Move+Click",
            command=self.convert_current_macro_clicks,
        ).pack(fill="x")

    def _build_middle_panel(self) -> None:
        header = ttk.Frame(self.middle_panel)
        header.pack(fill="x")
        ttk.Label(header, text="Macro Blocks").pack(side="left")

        controls = ttk.Frame(self.middle_panel)
        controls.pack(fill="x", pady=(6, 6))
        add_controls = ttk.Frame(controls)
        add_controls.pack(fill="x")
        branch_controls = ttk.Frame(controls)
        branch_controls.pack(fill="x", pady=(5, 0))
        edit_controls = ttk.Frame(controls)
        edit_controls.pack(fill="x", pady=(5, 0))
        self.add_type_var = tk.StringVar(value="click")
        add_options = list(BLOCK_LABELS.keys())
        add_combo = ttk.Combobox(
            add_controls,
            textvariable=self.add_type_var,
            values=add_options,
            state="readonly",
            width=20,
        )
        add_controls.columnconfigure(0, weight=1)
        add_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(add_controls, text="Add", command=self.add_block).grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )
        for column in range(2):
            branch_controls.columnconfigure(column, weight=1)
        ttk.Button(branch_controls, text="Add Child", command=self.add_child_block).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(branch_controls, text="Add Else", command=self.add_else_block).grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )
        for column in range(3):
            edit_controls.columnconfigure(column, weight=1)
        ttk.Button(edit_controls, text="Remove", command=self.delete_selected_block).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(edit_controls, text="Up", command=lambda: self.move_selected_block(-1)).grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )
        ttk.Button(edit_controls, text="Down", command=lambda: self.move_selected_block(1)).grid(
            row=0, column=2, sticky="ew", padx=(6, 0)
        )

        self.block_tree = ttk.Treeview(
            self.middle_panel,
            columns=("type", "summary"),
            show="tree headings",
            selectmode="extended",
        )
        self.block_tree.heading("#0", text="Name")
        self.block_tree.heading("type", text="Type")
        self.block_tree.heading("summary", text="Details")
        self.block_tree.column("#0", width=210, minwidth=150)
        self.block_tree.column("type", width=130, minwidth=110, stretch=False)
        self.block_tree.column("summary", width=360, minwidth=220)
        self.block_tree.tag_configure("label", foreground="#245B93", font=("Segoe UI", 9, "bold"))
        self.block_tree.tag_configure("goto", foreground="#386641")
        self.block_tree.pack(fill="both", expand=True)
        self.block_tree.bind("<<TreeviewSelect>>", lambda _event: self.show_selected_properties())
        self.block_tree.bind("<Button-3>", self.show_block_context_menu)
        self.block_tree.bind("<Control-c>", self.copy_selected_block)
        self.block_tree.bind("<Control-x>", self.cut_selected_block)
        self.block_tree.bind("<Control-v>", self.paste_block)
        self.block_tree.bind("<Control-d>", self.duplicate_selected_block)
        self.block_tree.bind("<Delete>", self.delete_selected_block)

        self.block_context_menu = tk.Menu(self.block_tree, tearoff=False)
        self.block_context_menu.add_command(
            label="Run From Here", command=self.run_from_context_block
        )
        self.block_context_menu.add_separator()
        self.block_context_menu.add_command(label="Copy", command=self.copy_selected_block)
        self.block_context_menu.add_command(label="Cut", command=self.cut_selected_block)
        self.block_context_menu.add_command(label="Paste", command=self.paste_block)
        self.block_context_menu.add_command(
            label="Duplicate", command=self.duplicate_selected_block
        )
        self.block_context_menu.add_command(label="Delete", command=self.delete_selected_block)

    def _build_right_panel(self) -> None:
        macro_frame = ttk.LabelFrame(self.right_panel, text="Macro Notes", padding=8)
        macro_frame.pack(fill="x")
        self.notes_text = tk.Text(macro_frame, height=4, wrap="word")
        self.notes_text.pack(fill="x")
        self.notes_text.bind("<FocusOut>", lambda _event: self.apply_macro_header())

        self.target_text_var = tk.StringVar()
        target_frame = ttk.LabelFrame(self.right_panel, text="Target Window", padding=8)
        target_frame.pack(fill="x", pady=(8, 8))
        ttk.Label(target_frame, textvariable=self.target_text_var, wraplength=330).pack(
            anchor="w", fill="x"
        )
        ttk.Checkbutton(
            target_frame,
            text="Show target marker while editing",
            variable=self.marker_enabled_var,
            command=self.update_target_marker,
        ).pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(
            target_frame,
            text="Save debug captures",
            variable=self.debug_captures_var,
            command=self.update_debug_capture_setting,
        ).pack(anchor="w", pady=(4, 0))

        self.properties_container = ttk.LabelFrame(
            self.right_panel, text="Selected Block"
        )
        self.properties_container.pack(fill="both", expand=True)
        self.properties_canvas = tk.Canvas(
            self.properties_container,
            highlightthickness=0,
            borderwidth=0,
        )
        properties_scrollbar = ttk.Scrollbar(
            self.properties_container,
            orient="vertical",
            command=self.properties_canvas.yview,
        )
        self.properties_canvas.configure(yscrollcommand=properties_scrollbar.set)
        properties_scrollbar.pack(side="right", fill="y")
        self.properties_canvas.pack(side="left", fill="both", expand=True)
        self.properties_frame = ttk.Frame(self.properties_canvas, padding=8)
        self.properties_canvas_window = self.properties_canvas.create_window(
            (0, 0), window=self.properties_frame, anchor="nw"
        )
        self.properties_frame.bind(
            "<Configure>",
            lambda _event: self.properties_canvas.configure(
                scrollregion=self.properties_canvas.bbox("all")
            ),
        )
        self.properties_canvas.bind(
            "<Configure>",
            lambda event: self.properties_canvas.itemconfigure(
                self.properties_canvas_window, width=event.width
            ),
        )

    def _build_log_panel(self, vertical: ttk.PanedWindow) -> None:
        log_frame = ttk.Frame(vertical, padding=(8, 4, 8, 8))
        vertical.add(log_frame, weight=1)
        ttk.Label(log_frame, text="Execution Log").pack(anchor="w")
        self.log_text = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True, pady=(4, 0))

    def refresh_all(self) -> None:
        self.macro_name_var.set(self.macro.name)
        self.notes_text.delete("1.0", tk.END)
        self.notes_text.insert("1.0", self.macro.notes)
        self.refresh_target_status()
        self.refresh_tree()
        self.show_selected_properties()

    def _current_macro_snapshot(self) -> str:
        data = self.macro.to_dict()
        try:
            data["name"] = self.macro_name_var.get().strip() or "Untitled Macro"
            data["notes"] = self.notes_text.get("1.0", tk.END).strip()
        except (AttributeError, tk.TclError):
            pass
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def is_dirty(self) -> bool:
        return self._current_macro_snapshot() != self._saved_snapshot

    def _mark_clean(self) -> None:
        self._saved_snapshot = self._current_macro_snapshot()
        self.unsaved_indicator_var.set("")

    def _refresh_dirty_indicator(self) -> None:
        if self.closing:
            return
        self.unsaved_indicator_var.set("Unsaved changes" if self.is_dirty() else "")
        self.dirty_check_after_id = self.root.after(300, self._refresh_dirty_indicator)

    def _confirm_safe_transition(self, action: str) -> bool:
        if self.recording:
            messagebox.showinfo(
                "Recording Active",
                f"Stop recording before {action}.",
            )
            return False
        if self.runner.is_running or self.running:
            messagebox.showinfo(
                "Macro Running",
                f"Stop the running macro before {action}.",
            )
            return False
        if not self.is_dirty():
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved Changes",
            f"You have unsaved changes. Would you like to save before {action}?",
        )
        if answer is None:
            return False
        if answer is False:
            return True
        return self._save_for_transition()

    def _save_for_transition(self) -> bool:
        return self.save_macro() if self.macro.path else self.save_macro_as()

    def refresh_macro_list(self, select_path: Optional[Path | str] = None) -> None:
        selected_identity = (
            self.storage.reference_identity(select_path) if select_path else None
        )
        self.macro_paths = self.storage.list_macros()
        self.macro_list.delete(0, tk.END)
        selected_index = None
        for index, path in enumerate(self.macro_paths):
            self.macro_list.insert(tk.END, path.stem)
            if (
                selected_identity
                and self.storage.reference_identity(path) == selected_identity
            ):
                selected_index = index
        if selected_index is not None:
            self.macro_list.selection_set(selected_index)
            self.macro_list.see(selected_index)

    def move_saved_macro(self, delta: int) -> None:
        selection = self.macro_list.curselection()
        if not selection:
            return
        path = self.macro_paths[selection[0]]
        try:
            new_index = self.storage.move_macro(path, delta)
            self.refresh_macro_list(path)
            self.macro_list.selection_clear(0, tk.END)
            self.macro_list.selection_set(new_index)
            self.macro_list.see(new_index)
            self.status_var.set(f"Moved saved macro: {path.stem}")
        except Exception as exc:
            messagebox.showerror("Move Saved Macro Failed", str(exc))

    def update_builder_bounds(self, _event: Optional[tk.Event] = None) -> None:
        try:
            left = self.root.winfo_rootx()
            top = self.root.winfo_rooty()
            right = left + self.root.winfo_width()
            bottom = top + self.root.winfo_height()
            self.builder_bounds = (left, top, right, bottom)
        except tk.TclError:
            self.builder_bounds = (0, 0, 0, 0)

    def _on_properties_mousewheel(self, event: tk.Event) -> Optional[str]:
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
            if not self._widget_is_descendant(widget, self.properties_container):
                return None
            units = -1 if event.delta > 0 else 1
            self.properties_canvas.yview_scroll(units * 3, "units")
            return "break"
        except tk.TclError:
            return None

    def _widget_is_descendant(
        self, widget: Optional[tk.Widget], ancestor: tk.Widget
    ) -> bool:
        current = widget
        while current is not None:
            if current == ancestor:
                return True
            current = getattr(current, "master", None)
        return False

    def clear_stop_notice(self) -> None:
        self.notice_var.set("")

    def update_debug_capture_setting(self) -> None:
        self.screen_analysis.debug_captures_enabled = self.debug_captures_var.get()
        state = "enabled" if self.debug_captures_var.get() else "disabled"
        self.status_var.set(f"Debug captures {state}.")

    def save_last_probe_image(self) -> None:
        if self.last_probe_capture is None:
            messagebox.showinfo("No Probe Image", "Probe a pixel or region first.")
            return
        try:
            path = self.screen_analysis.save_debug_capture(
                self.last_probe_capture,
                self.last_probe_label,
                self.last_probe_result,
                force=True,
            )
            self.threadsafe_log(f"Saved last probe image: {path}")
            self.status_var.set(f"Saved probe image: {path}")
        except Exception as exc:
            messagebox.showerror("Save Probe Image Failed", str(exc))

    def show_stop_notice(self, reason: str) -> None:
        self.notice_var.set(f"Macro stopped: {reason}")

    def schedule_marker_update(self) -> None:
        if self.marker_update_after_id:
            try:
                self.root.after_cancel(self.marker_update_after_id)
            except tk.TclError:
                pass
        self.marker_update_after_id = self.root.after(100, self.update_target_marker)

    def update_target_marker(self) -> None:
        self.marker_update_after_id = None
        if self.running or self.recording or not self.marker_enabled_var.get():
            self.marker_overlay.hide()
            self.region_overlay.hide()
            return

        region_block = self._region_marker_block()
        if region_block:
            self.marker_overlay.hide()
            self._update_region_overlay(region_block)
            return

        block = self._coordinate_marker_block()
        if not block:
            self.marker_overlay.hide()
            self.region_overlay.hide()
            self.last_marker_error = None
            return
        if not self.macro.target_window:
            self.marker_overlay.hide()
            self.region_overlay.hide()
            self._report_marker_error("Target marker hidden: no target window bound.")
            return

        try:
            x, y = self._marker_coordinates(block)
            target = self.window_manager.require_ready(
                self.macro.target_window, self.macro.expected_window_size
            )
            screen_x, screen_y = self.window_manager.client_to_screen(target, x, y)
            if not self.marker_overlay.show(screen_x, screen_y, f"{x}, {y}"):
                self.region_overlay.hide()
                self._report_marker_error(
                    "Target marker hidden: overlay could not be made click-through."
                )
                return
            self.region_overlay.hide()
            self.last_marker_error = None
            self.marker_update_after_id = self.root.after(500, self.update_target_marker)
        except (AutomationError, ValueError) as exc:
            self.marker_overlay.hide()
            self.region_overlay.hide()
            self._report_marker_error(f"Target marker hidden: {exc}")

    def hide_target_marker(self) -> None:
        self.marker_overlay.hide()
        self.region_overlay.hide()
        if self.marker_update_after_id:
            try:
                self.root.after_cancel(self.marker_update_after_id)
            except tk.TclError:
                pass
            self.marker_update_after_id = None

    def _report_marker_error(self, message: str) -> None:
        self.status_var.set(message)
        if self.last_marker_error != message:
            self.last_marker_error = message
            self.threadsafe_log(message)

    def _coordinate_marker_block(self) -> Optional[MacroBlock]:
        selected_units = self.selected_block_units()
        if len(selected_units) != 1:
            return None
        block = selected_units[0]
        return (
            block
            if block.type
            in {"click", "move_mouse", "move_and_click", "wait_pixel", "if_pixel"}
            else None
        )

    def _block_uses_coordinates(self, block: MacroBlock) -> bool:
        return block.type in {
            "click",
            "move_mouse",
            "move_and_click",
            "wait_pixel",
            "if_pixel",
            "wait_region",
            "if_region",
            "wait_stable",
            "click_until_change",
            "classify_map_run",
        }

    def _region_marker_block(self) -> Optional[MacroBlock]:
        selected_units = self.selected_block_units()
        if len(selected_units) != 1:
            return None
        block = selected_units[0]
        return (
            block
            if block.type
            in {
                "wait_region",
                "if_region",
                "wait_stable",
                "click_until_change",
                "classify_map_run",
            }
            else None
        )

    def _update_region_overlay(self, block: MacroBlock) -> None:
        if not self.macro.target_window:
            self.region_overlay.hide()
            self._report_marker_error("Target region hidden: no target window bound.")
            return
        try:
            left, top, right, bottom = self._marker_region(block)
            target = self.window_manager.require_ready(
                self.macro.target_window, self.macro.expected_window_size
            )
            screen_left, screen_top = self.window_manager.client_to_screen(target, left, top)
            screen_right, screen_bottom = self.window_manager.client_to_screen(target, right, bottom)
            label = f"{left},{top} - {right},{bottom}"
            if not self.region_overlay.show_region(
                screen_left, screen_top, screen_right, screen_bottom, label
            ):
                self._report_marker_error(
                    "Target region hidden: overlay could not be made click-through."
                )
                return
            self.last_marker_error = None
            self.marker_update_after_id = self.root.after(500, self.update_target_marker)
        except (AutomationError, ValueError) as exc:
            self.region_overlay.hide()
            self._report_marker_error(f"Target region hidden: {exc}")

    def _marker_coordinates(self, block: MacroBlock) -> Tuple[int, int]:
        x_value = self.property_vars.get("x").get() if "x" in self.property_vars else block.params.get("x", 0)
        y_value = self.property_vars.get("y").get() if "y" in self.property_vars else block.params.get("y", 0)
        return int(str(x_value).strip()), int(str(y_value).strip())

    def _marker_region(self, block: MacroBlock) -> Tuple[int, int, int, int]:
        params = self.draft_block_params(block) if self.property_vars else block.params
        return normalize_region(
            params.get("x1", 0),
            params.get("y1", 0),
            params.get("x2", 0),
            params.get("y2", 0),
        )

    def _point_inside_widget(self, widget: Optional[tk.Widget], x: int, y: int) -> bool:
        if not widget:
            return False
        try:
            left = widget.winfo_rootx()
            top = widget.winfo_rooty()
            right = left + widget.winfo_width()
            bottom = top + widget.winfo_height()
            return left <= x < right and top <= y < bottom
        except tk.TclError:
            return False

    def refresh_target_status(self) -> None:
        if not self.macro.target_window:
            self.target_text_var.set("No target bound.")
            self.status_var.set("No target bound.")
            return
        title = self.macro.target_window.get("title", "Unknown")
        expected = self.macro.expected_window_size or {}
        expected_text = (
            f"{expected.get('width', '?')}x{expected.get('height', '?')}"
            if expected
            else "not set"
        )
        try:
            info = self.window_manager.require_ready(self.macro.target_window, None)
            current_text = f"{info.client_width}x{info.client_height}"
            warning = ""
            if expected and (
                expected.get("width") != info.client_width
                or expected.get("height") != info.client_height
            ):
                warning = " Size differs from the saved macro size."
            text = f"{title}\nCurrent client: {current_text}\nExpected: {expected_text}.{warning}"
            self.target_text_var.set(text)
            self.status_var.set(f"Target: {title} ({current_text})")
        except AutomationError as exc:
            self.target_text_var.set(f"{title}\nExpected: {expected_text}\nWarning: {exc}")
            self.status_var.set(f"Target warning: {exc}")

    def refresh_tree(
        self,
        select_id: Optional[str] = None,
        select_ids: Optional[List[str]] = None,
    ) -> None:
        open_items = {
            item_id
            for item_id in self.block_tree.get_children("")
            if self.block_tree.item(item_id, "open")
        }
        self.block_item_ids.clear()
        self.block_tree.delete(*self.block_tree.get_children(""))
        self._insert_blocks("", self.macro.blocks)

        for item_id in open_items:
            if self.block_tree.exists(item_id):
                self.block_tree.item(item_id, open=True)
        ids_to_select = select_ids or ([select_id] if select_id else [])
        existing_ids = [
            item_id
            for item_id in ids_to_select
            if item_id and self.block_tree.exists(item_id)
        ]
        if existing_ids:
            self.block_tree.selection_set(*existing_ids)
            self.block_tree.focus(existing_ids[-1])
            self.block_tree.see(existing_ids[-1])

    def _insert_blocks(self, parent_item: str, blocks: List[MacroBlock]) -> None:
        for block in blocks:
            self.block_item_ids.add(block.id)
            self.block_tree.insert(
                parent_item,
                "end",
                iid=block.id,
                text=block_display_name(block),
                values=(BLOCK_LABELS.get(block.type, block.type), block_summary(block)),
                tags=(block.type,) if block.type in ROOT_ONLY_BLOCK_TYPES else (),
                open=True,
            )
            if block.type in {"if_pixel", "if_region"}:
                then_id = f"then:{block.id}"
                else_id = f"else:{block.id}"
                self.block_tree.insert(block.id, "end", iid=then_id, text="Then", values=("", ""))
                self.block_tree.insert(block.id, "end", iid=else_id, text="Else", values=("", ""))
                self._insert_blocks(then_id, block.children)
                self._insert_blocks(else_id, block.else_children)
            elif block.type == "repeat":
                self._insert_blocks(block.id, block.children)

    def selected_item_id(self) -> Optional[str]:
        selection = self.block_tree.selection()
        if not selection:
            return None
        focus = self.block_tree.focus()
        if focus in selection:
            return focus
        return selection[-1]

    def selected_block(self) -> Optional[MacroBlock]:
        item_id = self.selected_item_id()
        if item_id and item_id in self.block_item_ids:
            found = find_block(self.macro.blocks, item_id)
            return found[0] if found else None
        return None

    def selected_block_ids(self) -> List[str]:
        selected = set(self.block_tree.selection())
        return [
            item_id
            for item_id in self.visual_block_ids()
            if item_id in selected and item_id in self.block_item_ids
        ]

    def selected_block_units(self) -> List[MacroBlock]:
        selected_ids = set(self.selected_block_ids())
        units: List[MacroBlock] = []
        for item_id in self.visual_block_ids():
            if item_id not in selected_ids:
                continue
            if self._has_selected_block_ancestor(item_id, selected_ids):
                continue
            block = self._block_by_id(item_id)
            if block:
                units.append(block)
        return units

    def selected_block_refs(
        self,
    ) -> List[Tuple[MacroBlock, List[MacroBlock], int]]:
        refs: List[Tuple[MacroBlock, List[MacroBlock], int]] = []
        for block in self.selected_block_units():
            found = find_block(self.macro.blocks, block.id)
            if found:
                _, owner, _, _ = found
                refs.append((block, owner, owner.index(block)))
        return refs

    def visual_block_ids(self, parent_item: str = "") -> List[str]:
        ids: List[str] = []
        for item_id in self.block_tree.get_children(parent_item):
            if item_id in self.block_item_ids:
                ids.append(item_id)
            ids.extend(self.visual_block_ids(item_id))
        return ids

    def _has_selected_block_ancestor(self, item_id: str, selected_ids: set[str]) -> bool:
        parent_id = self.block_tree.parent(item_id)
        while parent_id:
            if parent_id in selected_ids and parent_id in self.block_item_ids:
                return True
            parent_id = self.block_tree.parent(parent_id)
        return False

    def _selection_label(self, count: int, action: str) -> str:
        noun = "block" if count == 1 else "blocks"
        return f"{action} {count} {noun}"

    def show_block_context_menu(self, event: tk.Event) -> None:
        item_id = self.block_tree.identify_row(event.y)
        self.context_menu_block_id = item_id if item_id in self.block_item_ids else None
        if item_id:
            if item_id not in self.block_tree.selection():
                self.block_tree.selection_set(item_id)
            self.block_tree.focus(item_id)
        else:
            self.block_tree.selection_remove(*self.block_tree.selection())
            self.context_menu_block_id = None

        self._update_block_context_menu()
        try:
            self.block_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.block_context_menu.grab_release()

    def _update_block_context_menu(self) -> None:
        has_block = bool(self.selected_block_units())
        block_state = "normal" if has_block else "disabled"
        paste_state = "normal" if self.block_clipboard else "disabled"
        run_state = "normal" if self.context_menu_block_id else "disabled"
        self.block_context_menu.entryconfigure(0, state=run_state)
        self.block_context_menu.entryconfigure(2, state=block_state)
        self.block_context_menu.entryconfigure(3, state=block_state)
        self.block_context_menu.entryconfigure(4, state=paste_state)
        self.block_context_menu.entryconfigure(5, state=block_state)
        self.block_context_menu.entryconfigure(6, state=block_state)

    def copy_selected_block(self, _event: Optional[tk.Event] = None) -> str:
        blocks = self.selected_block_units()
        if blocks:
            self.block_clipboard = [block.clone() for block in blocks]
            self.threadsafe_log(self._selection_label(len(blocks), "Copied"))
        return "break"

    def cut_selected_block(self, _event: Optional[tk.Event] = None) -> str:
        refs = self.selected_block_refs()
        if not refs:
            return "break"
        self.block_clipboard = [block.clone() for block, _, _ in refs]
        for block, _, _ in reversed(refs):
            self._remove_block(block)
        self.threadsafe_log(self._selection_label(len(refs), "Cut"))
        self.refresh_tree()
        self.show_selected_properties()
        self._report_control_flow_warnings()
        return "break"

    def paste_block(self, _event: Optional[tk.Event] = None) -> str:
        if not self.block_clipboard:
            return "break"
        blocks = [block.clone() for block in self.block_clipboard]
        target_list, insert_index = self._paste_location()
        if target_list is not self.macro.blocks and any(
            block.type in ROOT_ONLY_BLOCK_TYPES for block in blocks
        ):
            messagebox.showinfo(
                "Root-Level Only",
                "Label and Goto blocks can only be pasted into the root macro list.",
            )
            return "break"
        for offset, block in enumerate(blocks):
            target_list.insert(insert_index + offset, block)
        self.threadsafe_log(self._selection_label(len(blocks), "Pasted"))
        self.refresh_tree(select_ids=[block.id for block in blocks])
        self.show_selected_properties()
        self._report_control_flow_warnings()
        return "break"

    def duplicate_selected_block(self, _event: Optional[tk.Event] = None) -> str:
        refs = self.selected_block_refs()
        if not refs:
            return "break"
        inserted_ids: List[str] = []
        for owner, owner_refs in self._refs_grouped_by_owner(refs):
            sorted_refs = sorted(owner_refs, key=lambda item: owner.index(item[0]))
            insert_index = max(owner.index(block) for block, _, _ in sorted_refs) + 1
            clones = [block.clone() for block, _, _ in sorted_refs]
            for offset, clone in enumerate(clones):
                owner.insert(insert_index + offset, clone)
                inserted_ids.append(clone.id)
        self.threadsafe_log(self._selection_label(len(refs), "Duplicated"))
        self.refresh_tree(select_ids=inserted_ids)
        self.show_selected_properties()
        self._report_control_flow_warnings()
        return "break"

    def delete_selected_block(self, _event: Optional[tk.Event] = None) -> str:
        refs = self.selected_block_refs()
        if refs:
            for block, _, _ in reversed(refs):
                self._remove_block(block)
            self.threadsafe_log(self._selection_label(len(refs), "Deleted"))
            self.refresh_tree()
            self.show_selected_properties()
            self._report_control_flow_warnings()
        return "break"

    def add_block(self) -> None:
        block = MacroBlock.create(self.add_type_var.get())
        item_id = self.selected_item_id()
        target_list, insert_index = self._list_for_add_after(item_id)
        if block.type in ROOT_ONLY_BLOCK_TYPES and target_list is not self.macro.blocks:
            messagebox.showinfo(
                "Root-Level Only",
                "Label and Goto blocks can only be added to the root macro list.",
            )
            return
        target_list.insert(insert_index, block)
        self.refresh_tree(block.id)
        self.show_selected_properties()
        if block.type in ROOT_ONLY_BLOCK_TYPES:
            self._report_control_flow_warnings()

    def add_child_block(self) -> None:
        if self.add_type_var.get() in ROOT_ONLY_BLOCK_TYPES:
            messagebox.showinfo(
                "Root-Level Only",
                "Label and Goto blocks cannot be added as child blocks.",
            )
            return
        item_id = self.selected_item_id()
        target_list = self._list_for_child(item_id, else_branch=False)
        if target_list is None:
            messagebox.showinfo("Add Child", "Select a Repeat, If, Then, or Else branch.")
            return
        block = MacroBlock.create(self.add_type_var.get())
        target_list.append(block)
        self.refresh_tree(block.id)
        self.show_selected_properties()

    def add_else_block(self) -> None:
        if self.add_type_var.get() in ROOT_ONLY_BLOCK_TYPES:
            messagebox.showinfo(
                "Root-Level Only",
                "Label and Goto blocks cannot be added to an Else branch.",
            )
            return
        item_id = self.selected_item_id()
        target_list = self._list_for_child(item_id, else_branch=True)
        if target_list is None:
            messagebox.showinfo("Add Else", "Select an If Pixel Match block or its Else branch.")
            return
        block = MacroBlock.create(self.add_type_var.get())
        target_list.append(block)
        self.refresh_tree(block.id)
        self.show_selected_properties()

    def _remove_block(self, block: MacroBlock) -> None:
        found = find_block(self.macro.blocks, block.id)
        if not found:
            return
        _, owner, _, _ = found
        owner.remove(block)

    def _paste_location(self) -> Tuple[List[MacroBlock], int]:
        refs = self.selected_block_refs()
        if refs:
            block, owner, _ = refs[-1]
            return owner, owner.index(block) + 1
        item_id = self.selected_item_id()
        return self._list_for_add_after(item_id)

    def _refs_grouped_by_owner(
        self, refs: List[Tuple[MacroBlock, List[MacroBlock], int]]
    ) -> List[Tuple[List[MacroBlock], List[Tuple[MacroBlock, List[MacroBlock], int]]]]:
        groups: List[
            Tuple[List[MacroBlock], List[Tuple[MacroBlock, List[MacroBlock], int]]]
        ] = []
        for ref in refs:
            _, owner, _ = ref
            for existing_owner, existing_refs in groups:
                if existing_owner is owner:
                    existing_refs.append(ref)
                    break
            else:
                groups.append((owner, [ref]))
        return groups

    def move_selected_block(self, delta: int) -> None:
        block = self.selected_block()
        if not block:
            return
        found = find_block(self.macro.blocks, block.id)
        if not found:
            return
        _, owner, _, _ = found
        index = owner.index(block)
        new_index = index + delta
        if 0 <= new_index < len(owner):
            owner[index], owner[new_index] = owner[new_index], owner[index]
            self.refresh_tree(block.id)

    def _list_for_add_after(
        self, item_id: Optional[str]
    ) -> Tuple[List[MacroBlock], int]:
        if not item_id:
            return self.macro.blocks, len(self.macro.blocks)
        if item_id.startswith("then:"):
            parent = self._block_by_id(item_id.split(":", 1)[1])
            return (parent.children, len(parent.children)) if parent else (self.macro.blocks, len(self.macro.blocks))
        if item_id.startswith("else:"):
            parent = self._block_by_id(item_id.split(":", 1)[1])
            return (
                (parent.else_children, len(parent.else_children))
                if parent
                else (self.macro.blocks, len(self.macro.blocks))
            )
        found = find_block(self.macro.blocks, item_id)
        if not found:
            return self.macro.blocks, len(self.macro.blocks)
        block, owner, _, _ = found
        return owner, owner.index(block) + 1

    def _list_for_child(
        self, item_id: Optional[str], else_branch: bool
    ) -> Optional[List[MacroBlock]]:
        if not item_id:
            return None
        if item_id.startswith("then:"):
            parent = self._block_by_id(item_id.split(":", 1)[1])
            return parent.children if parent else None
        if item_id.startswith("else:"):
            parent = self._block_by_id(item_id.split(":", 1)[1])
            return parent.else_children if parent else None
        block = self._block_by_id(item_id)
        if not block:
            return None
        if block.type == "repeat":
            return block.children if not else_branch else None
        if block.type in {"if_pixel", "if_region"}:
            return block.else_children if else_branch else block.children
        return None

    def _block_by_id(self, block_id: str) -> Optional[MacroBlock]:
        found = find_block(self.macro.blocks, block_id)
        return found[0] if found else None

    def show_selected_properties(self) -> None:
        for child in self.properties_frame.winfo_children():
            child.destroy()
        self.properties_canvas.yview_moveto(0)
        self.property_vars.clear()

        selected_units = self.selected_block_units()
        if len(selected_units) > 1:
            self.hide_target_marker()
            ttk.Label(
                self.properties_frame,
                text=(
                    f"{len(selected_units)} blocks selected. "
                    "Use the context menu or keyboard shortcuts for group actions."
                ),
                wraplength=330,
            ).pack(anchor="w")
            return

        item_id = self.selected_item_id()
        if item_id and item_id.startswith(("then:", "else:")):
            self.hide_target_marker()
            ttk.Label(self.properties_frame, text="Branch selected. Add child blocks here.").pack(
                anchor="w"
            )
            return

        block = selected_units[0] if selected_units else self.selected_block()
        if not block:
            self.hide_target_marker()
            ttk.Label(self.properties_frame, text="Select a block to edit its properties.").pack(
                anchor="w"
            )
            return
        self.probe_result_var.set("")

        self._field("Name", "name", block.name)
        self._field("Note", "note", block.note)

        if block.type == "click":
            self._field("X", "x", block.params.get("x", 0))
            self._field("Y", "y", block.params.get("y", 0))
            self._choice("Button", "button", block.params.get("button", "left"), ["left", "right", "middle"])
            self._field("Click Count", "click_count", block.params.get("click_count", 1))
            self._field("Delay After (ms)", "delay_after_ms", block.params.get("delay_after_ms", 0))
            ttk.Button(
                self.properties_frame,
                text="Capture Click Position",
                command=lambda: self.capture_click(block),
            ).pack(anchor="w", pady=(8, 0))
            self._probe_controls(block)
        elif block.type == "move_mouse":
            self._field("Target X", "x", block.params.get("x", 0))
            self._field("Target Y", "y", block.params.get("y", 0))
            self._field(
                "Movement Duration (ms)",
                "movement_duration_ms",
                block.params.get("movement_duration_ms", 150),
            )
            ttk.Button(
                self.properties_frame,
                text="Capture Target Position",
                command=lambda: self.capture_click(block),
            ).pack(anchor="w", pady=(8, 0))
        elif block.type == "move_and_click":
            self._field("Target X", "x", block.params.get("x", 0))
            self._field("Target Y", "y", block.params.get("y", 0))
            self._choice(
                "Button",
                "button",
                block.params.get("button", "left"),
                ["left", "right", "middle"],
            )
            self._field("Click Count", "click_count", block.params.get("click_count", 1))
            self._field(
                "Movement Duration (ms)",
                "movement_duration_ms",
                block.params.get("movement_duration_ms", 150),
            )
            self._field(
                "Delay After (ms)",
                "delay_after_ms",
                block.params.get("delay_after_ms", 0),
            )
            ttk.Button(
                self.properties_frame,
                text="Capture Target Position",
                command=lambda: self.capture_click(block),
            ).pack(anchor="w", pady=(8, 0))
        elif block.type == "key_press":
            self._field("Key", "key", block.params.get("key", "space"))
            self._field("Press Count", "press_count", block.params.get("press_count", 1))
            self._field("Delay After (ms)", "delay_after_ms", block.params.get("delay_after_ms", 0))
        elif block.type == "wait":
            self._field("Duration (ms)", "duration_ms", block.params.get("duration_ms", 500))
        elif block.type == "wait_pixel":
            self._field("X", "x", block.params.get("x", 0))
            self._field("Y", "y", block.params.get("y", 0))
            self._color_field("Expected Colour", "expected_color", block.params.get("expected_color", "#00FF00"))
            self._field("Tolerance", "tolerance", block.params.get("tolerance", 10))
            self._field("Check Interval (ms)", "check_interval_ms", block.params.get("check_interval_ms", 100))
            self._field("Timeout (ms, blank allowed)", "timeout_ms", block.params.get("timeout_ms", ""))
            self._choice("On Timeout", "timeout_behavior", block.params.get("timeout_behavior", "fail"), ["fail", "continue"])
            self._field(
                "After Success Delay (ms)",
                "after_success_delay_ms",
                block.params.get("after_success_delay_ms", 0),
            )
            self._choice(
                "Sampling",
                "sampling_mode",
                normalize_sampling_mode(block.params.get("sampling_mode", PIXEL_SAMPLING_SINGLE)),
                PIXEL_SAMPLING_MODES,
            )
            ttk.Button(
                self.properties_frame,
                text="Capture Pixel",
                command=lambda: self.capture_pixel(block),
            ).pack(anchor="w", pady=(8, 0))
            self._probe_controls(block)
        elif block.type == "if_pixel":
            self._field("X", "x", block.params.get("x", 0))
            self._field("Y", "y", block.params.get("y", 0))
            self._color_field("Expected Colour", "expected_color", block.params.get("expected_color", "#00FF00"))
            self._field("Tolerance", "tolerance", block.params.get("tolerance", 10))
            self._choice(
                "Sampling",
                "sampling_mode",
                normalize_sampling_mode(block.params.get("sampling_mode", PIXEL_SAMPLING_SINGLE)),
                PIXEL_SAMPLING_MODES,
            )
            ttk.Button(
                self.properties_frame,
                text="Capture Pixel",
                command=lambda: self.capture_pixel(block),
            ).pack(anchor="w", pady=(8, 0))
            self._probe_controls(block)
        elif block.type == "wait_region":
            self._region_fields(block, include_wait=True)
        elif block.type == "if_region":
            self._region_fields(block, include_wait=False)
        elif block.type == "wait_stable":
            self._stable_region_fields(block)
        elif block.type == "click_until_change":
            self._click_until_change_fields(block)
        elif block.type == "repeat":
            self._field("Repeat Count", "repeat_count", block.params.get("repeat_count", 2))
        elif block.type == "label":
            self._field("Label Name", "label_name", block.params.get("label_name", "start"))
            ttk.Label(
                self.properties_frame,
                text="Root-level marker. Execution continues with the following block.",
                wraplength=390,
            ).pack(anchor="w", fill="x", pady=(6, 0))
        elif block.type == "goto":
            self._editable_choice(
                "Target Label",
                "target_label",
                block.params.get("target_label", ""),
                root_label_names(self.macro),
            )
            ttk.Label(
                self.properties_frame,
                text="Root-level only. Jumps to the selected label and continues after it.",
                wraplength=390,
            ).pack(anchor="w", fill="x", pady=(6, 0))
        elif block.type == "run_macro":
            self._field(
                "Macro File",
                "macro_path",
                block.params.get("macro_path", ""),
            )
            ttk.Button(
                self.properties_frame,
                text="Browse Saved Macro",
                command=lambda: self.browse_saved_macro(block),
            ).pack(anchor="w", pady=(8, 0))
            ttk.Label(
                self.properties_frame,
                text=(
                    "The called macro uses this run's active target window. "
                    "Its saved target metadata is not used for input."
                ),
                wraplength=390,
            ).pack(anchor="w", fill="x", pady=(6, 0))
        elif block.type == "classify_map_run":
            self._classify_map_fields(block)
        elif block.type == "stop":
            ttk.Label(self.properties_frame, text="This block stops macro execution.").pack(anchor="w")

        control_flow_warning = self._control_flow_warning_for_block(block)
        if control_flow_warning:
            ttk.Label(
                self.properties_frame,
                text=control_flow_warning,
                foreground="#8A1F11",
                wraplength=390,
            ).pack(anchor="w", fill="x", pady=(8, 0))

        ttk.Button(self.properties_frame, text="Apply", command=self.apply_block_properties).pack(
            anchor="w", pady=(12, 0)
        )
        if self._block_uses_coordinates(block):
            self._watch_marker_fields()
            self.schedule_marker_update()
        else:
            self.hide_target_marker()

    def _field(self, label: str, key: str, value: Any) -> tk.StringVar:
        row = ttk.Frame(self.properties_frame)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text=label, width=22).pack(side="left")
        var = tk.StringVar(value="" if value is None else str(value))
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        self.property_vars[key] = var
        return var

    def _color_field(self, label: str, key: str, value: Any) -> tk.StringVar:
        row = ttk.Frame(self.properties_frame)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text=label, width=22).pack(side="left")
        var = tk.StringVar(value="" if value is None else str(value))
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        swatch = tk.Canvas(row, width=28, height=20, highlightthickness=1, highlightbackground="#777777")
        swatch.pack(side="left", padx=(6, 0))
        swatch_rect = swatch.create_rectangle(2, 2, 26, 18, outline="#444444", fill="")
        self.property_vars[key] = var

        def update_swatch(*_args: Any) -> None:
            try:
                rgb = parse_color(var.get())
                swatch.itemconfigure(swatch_rect, fill=color_to_hex(rgb), outline="#444444")
                swatch.configure(highlightbackground="#777777")
                swatch.configure(cursor="hand2")
                swatch.bind(
                    "<Enter>",
                    lambda _event, text=color_to_rgb_text(rgb): self.status_var.set(text),
                )
            except ValueError:
                swatch.itemconfigure(swatch_rect, fill="", outline="#B00020")
                swatch.configure(highlightbackground="#B00020")
                swatch.configure(cursor="")
                swatch.bind("<Enter>", lambda _event: self.status_var.set("Invalid colour"))

        var.trace_add("write", update_swatch)
        update_swatch()
        return var

    def _watch_marker_fields(self) -> None:
        for key in ("x", "y", "x1", "y1", "x2", "y2"):
            var = self.property_vars.get(key)
            if var:
                var.trace_add("write", lambda *_args: self.schedule_marker_update())

    def _probe_controls(self, block: MacroBlock) -> None:
        ttk.Button(
            self.properties_frame,
            text="Probe Pixel Now",
            command=lambda: self.probe_pixel(block),
        ).pack(anchor="w", pady=(8, 0))
        ttk.Button(
            self.properties_frame,
            text="Save Last Probe Image",
            command=self.save_last_probe_image,
        ).pack(anchor="w", pady=(5, 0))
        ttk.Label(
            self.properties_frame,
            textvariable=self.probe_result_var,
            wraplength=340,
        ).pack(anchor="w", fill="x", pady=(4, 0))

    def _section_label(self, text: str) -> None:
        ttk.Separator(self.properties_frame, orient="horizontal").pack(
            fill="x", pady=(12, 5)
        )
        ttk.Label(
            self.properties_frame, text=text, font=("Segoe UI", 9, "bold")
        ).pack(anchor="w")

    def _boolean_field(self, text: str, key: str, value: Any) -> tk.BooleanVar:
        enabled = (
            value
            if isinstance(value, bool)
            else str(value or "").strip().lower() in {"1", "true", "yes", "on"}
        )
        var = tk.BooleanVar(value=enabled)
        ttk.Checkbutton(
            self.properties_frame,
            text=text,
            variable=var,
        ).pack(anchor="w", pady=(5, 0))
        self.property_vars[key] = var
        return var

    def _classify_map_fields(self, block: MacroBlock) -> None:
        self._section_label("Runtime Patch")
        self._region_coordinate_fields(block)
        self._region_capture_buttons(block)
        ttk.Button(
            self.properties_frame,
            text="Probe Classification Now",
            command=lambda: self.probe_map_classification(block),
        ).pack(anchor="w", pady=(7, 0))

        self._section_label("Reference Capture")
        self._field(
            "Reference X1",
            "reference_x1",
            block.params.get("reference_x1", 0),
        )
        self._field(
            "Reference Y1",
            "reference_y1",
            block.params.get("reference_y1", 0),
        )
        self._field(
            "Reference X2",
            "reference_x2",
            block.params.get("reference_x2", 240),
        )
        self._field(
            "Reference Y2",
            "reference_y2",
            block.params.get("reference_y2", 160),
        )
        self._region_capture_buttons(block, prefix="reference_")
        self._field(
            "Reference Folder",
            "reference_folder",
            block.params.get("reference_folder", "references/maps/expert"),
        )
        reference_buttons = ttk.Frame(self.properties_frame)
        reference_buttons.pack(fill="x", pady=(7, 0))
        ttk.Button(
            reference_buttons,
            text="Browse Folder",
            command=lambda: self.browse_reference_folder(block),
        ).pack(side="left")
        ttk.Button(
            reference_buttons,
            text="Capture Reference Image",
            command=lambda: self.capture_map_reference(block),
        ).pack(side="left", padx=(6, 0))

        self._section_label("Matching")
        self._field(
            "Minimum Best Score",
            "minimum_best_score",
            block.params.get("minimum_best_score", 0.75),
        )
        self._field(
            "Minimum Score Margin",
            "minimum_score_margin",
            block.params.get("minimum_score_margin", 0.05),
        )
        self._boolean_field(
            "Enable multi-scale matching",
            "enable_multi_scale",
            block.params.get("enable_multi_scale", True),
        )
        self._field("Scale Min", "scale_min", block.params.get("scale_min", 0.90))
        self._field("Scale Max", "scale_max", block.params.get("scale_max", 1.10))
        self._field("Scale Step", "scale_step", block.params.get("scale_step", 0.05))
        ttk.Label(
            self.properties_frame,
            text=(
                "Scores use OpenCV normalized correlation: 1.0 is an essentially "
                "identical patch. Both score and runner-up margin must pass."
            ),
            wraplength=340,
        ).pack(anchor="w", fill="x", pady=(5, 0))

        self._section_label("Map Macro Mapping")
        mapping = block.params.get("map_macro_mapping")
        mapping_count = len(mapping) if isinstance(mapping, dict) else 0
        ttk.Label(
            self.properties_frame,
            text=f"{mapping_count} map-to-macro mapping(s) configured.",
        ).pack(anchor="w", fill="x")
        ttk.Button(
            self.properties_frame,
            text="Edit Map Macro Mapping",
            command=lambda: self.edit_map_macro_mapping(block),
        ).pack(anchor="w", pady=(6, 0))

        self._section_label("Click Before Run")
        self._boolean_field(
            "Click map slot before running mapped macro",
            "click_before_run",
            block.params.get("click_before_run", True),
        )
        self._field("Map Click X", "map_click_x", block.params.get("map_click_x", 0))
        self._field("Map Click Y", "map_click_y", block.params.get("map_click_y", 0))
        self._field(
            "Movement Duration (ms)",
            "movement_duration_ms",
            block.params.get("movement_duration_ms", 150),
        )
        self._field(
            "Post-click Delay (ms)",
            "post_click_delay_ms",
            block.params.get("post_click_delay_ms", 500),
        )
        ttk.Button(
            self.properties_frame,
            text="Capture Map Click Position",
            command=lambda: self.capture_click(
                block, x_key="map_click_x", y_key="map_click_y"
            ),
        ).pack(anchor="w", pady=(7, 0))
        ttk.Label(
            self.properties_frame,
            textvariable=self.probe_result_var,
            wraplength=340,
        ).pack(anchor="w", fill="x", pady=(7, 0))

    def _region_fields(self, block: MacroBlock, include_wait: bool) -> None:
        self._field("X1", "x1", block.params.get("x1", 0))
        self._field("Y1", "y1", block.params.get("y1", 0))
        self._field("X2", "x2", block.params.get("x2", 100))
        self._field("Y2", "y2", block.params.get("y2", 50))
        mode = normalize_region_detection_mode(
            block.params.get("detection_mode", REGION_MODE_GREEN)
        )
        mode_var = self._choice(
            "Detection Mode",
            "detection_mode",
            mode,
            REGION_DETECTION_MODES,
        )
        mode_var.trace_add(
            "write",
            lambda *_args, selected=block, var=mode_var: self.root.after_idle(
                lambda: self._apply_region_mode_change(selected, var.get())
            ),
        )
        if mode == REGION_MODE_EXPECTED:
            self._color_field("Expected Colour", "expected_color", block.params.get("expected_color", "#35C84A"))
            self._field("Tolerance", "tolerance", block.params.get("tolerance", 40))
        self._field(
            "Minimum Match (%)",
            "minimum_match_percent",
            block.params.get("minimum_match_percent", 15),
        )
        if mode == REGION_MODE_GREEN:
            self._field("Green Strength", "green_strength", block.params.get("green_strength", 25))
            self._field("Minimum Green", "minimum_green", block.params.get("minimum_green", 80))
        if mode == REGION_MODE_HSV:
            self._field("Hue Min (OpenCV)", "hsv_hue_min", block.params.get("hsv_hue_min", 35))
            self._field("Hue Max (OpenCV)", "hsv_hue_max", block.params.get("hsv_hue_max", 85))
            self._field(
                "Minimum Saturation (0-255)",
                "hsv_min_saturation",
                block.params.get("hsv_min_saturation", 60),
            )
            self._field(
                "Minimum Value (0-255)",
                "hsv_min_value",
                block.params.get("hsv_min_value", 80),
            )
            ttk.Label(
                self.properties_frame,
                text="OpenCV hue uses 0-179. HSV is usually better for green UI states.",
                wraplength=340,
            ).pack(anchor="w", fill="x", pady=(4, 0))
        self._choice(
            "Sample Step",
            "sample_step",
            str(block.params.get("sample_step", 2)),
            ["1", "2", "4"],
        )
        if include_wait:
            self._field("Check Interval (ms)", "check_interval_ms", block.params.get("check_interval_ms", 100))
            self._field("Timeout (ms, blank allowed)", "timeout_ms", block.params.get("timeout_ms", ""))
            self._choice("On Timeout", "timeout_behavior", block.params.get("timeout_behavior", "fail"), ["fail", "continue"])
            self._field(
                "After Success Delay (ms)",
                "after_success_delay_ms",
                block.params.get("after_success_delay_ms", 0),
            )

        self._region_capture_buttons(block)
        ttk.Button(
            self.properties_frame,
            text="Probe Region Now",
            command=lambda: self.probe_region(block),
        ).pack(anchor="w", pady=(6, 0))
        ttk.Button(
            self.properties_frame,
            text="Save Last Probe Image",
            command=self.save_last_probe_image,
        ).pack(anchor="w", pady=(6, 0))
        ttk.Label(
            self.properties_frame,
            textvariable=self.probe_result_var,
            wraplength=340,
        ).pack(anchor="w", fill="x", pady=(4, 0))

    def _stable_region_fields(self, block: MacroBlock) -> None:
        self._region_coordinate_fields(block)
        self._field(
            "Stable Duration (ms)",
            "stable_duration_ms",
            block.params.get("stable_duration_ms", 300),
        )
        self._field(
            "Check Interval (ms)",
            "check_interval_ms",
            block.params.get("check_interval_ms", 100),
        )
        self._field(
            "Pixel Change Threshold",
            "change_threshold",
            block.params.get("change_threshold", 25),
        )
        self._field(
            "Maximum Changed (%)",
            "maximum_changed_percent",
            block.params.get("maximum_changed_percent", 2),
        )
        self._field(
            "Timeout (ms, blank allowed)",
            "timeout_ms",
            block.params.get("timeout_ms", ""),
        )
        self._choice(
            "On Timeout",
            "timeout_behavior",
            block.params.get("timeout_behavior", "fail"),
            ["fail", "continue"],
        )
        self._field(
            "After Success Delay (ms)",
            "after_success_delay_ms",
            block.params.get("after_success_delay_ms", 0),
        )
        self._region_capture_buttons(block)

    def _click_until_change_fields(self, block: MacroBlock) -> None:
        self._field("Click X", "x", block.params.get("x", 0))
        self._field("Click Y", "y", block.params.get("y", 0))
        self._choice(
            "Button",
            "button",
            block.params.get("button", "left"),
            ["left", "right", "middle"],
        )
        self._field("Click Count", "click_count", block.params.get("click_count", 1))
        ttk.Button(
            self.properties_frame,
            text="Capture Click Position",
            command=lambda: self.capture_click(block),
        ).pack(anchor="w", pady=(8, 0))
        ttk.Label(
            self.properties_frame,
            text="Watched region",
        ).pack(anchor="w", pady=(10, 0))
        self._region_coordinate_fields(block)
        self._field(
            "Pixel Change Threshold",
            "change_threshold",
            block.params.get("change_threshold", 25),
        )
        self._field(
            "Required Changed (%)",
            "required_changed_percent",
            block.params.get("required_changed_percent", 5),
        )
        self._field(
            "Post-click Delay (ms)",
            "post_click_delay_ms",
            block.params.get("post_click_delay_ms", 250),
        )
        self._field(
            "Check Interval (ms)",
            "check_interval_ms",
            block.params.get("check_interval_ms", 100),
        )
        self._field(
            "Check Timeout (ms)",
            "check_timeout_ms",
            block.params.get("check_timeout_ms", 1000),
        )
        self._field(
            "Attempts",
            "retry_count",
            block.params.get("retry_count", 3),
        )
        self._field(
            "Delay Between Retries (ms)",
            "retry_delay_ms",
            block.params.get("retry_delay_ms", 250),
        )
        self._region_capture_buttons(block)
        ttk.Label(
            self.properties_frame,
            text=(
                "The watched region overlay is shown while editing. "
                "The click target remains available through its coordinates and capture button."
            ),
            wraplength=340,
        ).pack(anchor="w", fill="x", pady=(6, 0))

    def _region_coordinate_fields(self, block: MacroBlock) -> None:
        self._field("X1", "x1", block.params.get("x1", 0))
        self._field("Y1", "y1", block.params.get("y1", 0))
        self._field("X2", "x2", block.params.get("x2", 100))
        self._field("Y2", "y2", block.params.get("y2", 50))

    def _region_capture_buttons(self, block: MacroBlock, prefix: str = "") -> None:
        buttons = ttk.Frame(self.properties_frame)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(
            buttons,
            text="Capture First Corner",
            command=lambda: self.capture_region_corner(block, "first", prefix),
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="Capture Second Corner",
            command=lambda: self.capture_region_corner(block, "second", prefix),
        ).pack(side="left", padx=(6, 0))

    def _choice(self, label: str, key: str, value: Any, options: List[str]) -> tk.StringVar:
        row = ttk.Frame(self.properties_frame)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text=label, width=22).pack(side="left")
        var = tk.StringVar(value=str(value))
        ttk.Combobox(row, textvariable=var, values=options, state="readonly").pack(
            side="left", fill="x", expand=True
        )
        self.property_vars[key] = var
        return var

    def _editable_choice(
        self, label: str, key: str, value: Any, options: List[str]
    ) -> tk.StringVar:
        row = ttk.Frame(self.properties_frame)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text=label, width=22).pack(side="left")
        var = tk.StringVar(value=str(value))
        ttk.Combobox(row, textvariable=var, values=options, state="normal").pack(
            side="left", fill="x", expand=True
        )
        self.property_vars[key] = var
        return var

    def _control_flow_warning_for_block(self, block: MacroBlock) -> str:
        found = find_block(self.macro.blocks, block.id)
        if (
            block.type in ROOT_ONLY_BLOCK_TYPES
            and found
            and found[1] is not self.macro.blocks
        ):
            return "Warning: Label and Goto blocks are root-level only."
        if block.type == "label":
            name = normalize_label_name(block.params.get("label_name"))
            if not name:
                return "Warning: label name cannot be empty."
            if root_label_names(self.macro).count(name) > 1:
                return f"Warning: label name '{name}' is duplicated."
        if block.type == "goto":
            target = normalize_label_name(block.params.get("target_label"))
            if not target:
                return "Warning: goto target cannot be empty."
            if target not in root_label_names(self.macro):
                return f"Warning: goto target label '{target}' does not exist."
        if block.type == "run_macro":
            return self._run_macro_reference_warning(block)
        if block.type == "classify_map_run":
            reference = str(block.params.get("reference_folder", "") or "").strip()
            if not reference:
                return "Warning: select a map reference folder."
            if not self.storage.resolve_reference(reference).is_dir():
                return f"Warning: map reference folder is missing: {reference}"
            mapping = block.params.get("map_macro_mapping")
            if not isinstance(mapping, dict) or not mapping:
                return "Warning: configure at least one map-to-macro mapping."
        return ""

    def _run_macro_reference_warning(self, block: MacroBlock) -> str:
        reference = str(block.params.get("macro_path", "") or "").strip()
        if not reference:
            return "Warning: select a saved macro file."
        path = self.storage.resolve_reference(reference)
        if not path.is_file():
            return f"Warning: referenced macro file is missing: {reference}"
        if self.macro.path and (
            self.storage.reference_identity(path)
            == self.storage.reference_identity(self.macro.path)
        ):
            return "Warning: this macro directly calls itself."
        try:
            child = self.storage.load(path)
        except Exception as exc:
            return f"Warning: referenced macro could not be loaded: {exc}"
        if self.macro.path:
            current_identity = self.storage.reference_identity(self.macro.path)
            for child_block in child.all_blocks():
                if child_block.type != "run_macro":
                    continue
                child_reference = str(
                    child_block.params.get("macro_path", "") or ""
                ).strip()
                if child_reference and (
                    self.storage.reference_identity(child_reference)
                    == current_identity
                ):
                    return (
                        "Warning: the selected macro directly calls the current macro. "
                        "Runtime recursion protection will stop execution."
                    )
        return ""

    def _apply_region_mode_change(self, block: MacroBlock, mode_value: str) -> None:
        selected = self.selected_block()
        if not selected or selected.id != block.id:
            return
        block.params.update(self.draft_block_params(block))
        block.params["detection_mode"] = normalize_region_detection_mode(mode_value)
        self.refresh_tree(block.id)
        self.show_selected_properties()
        self.schedule_marker_update()

    def apply_block_properties(self) -> None:
        block = self.selected_block()
        if not block:
            return
        values = {key: var.get() for key, var in self.property_vars.items()}
        new_name = values.pop("name", block.name).strip() or BLOCK_LABELS.get(block.type, block.type)
        new_note = values.pop("note", block.note).strip()
        new_params = dict(block.params)

        try:
            for key, value in values.items():
                new_params[key] = self._coerce_param(key, value)
        except ValueError as exc:
            messagebox.showerror("Invalid Value", str(exc))
            return

        error, warning = self._validate_control_flow_candidate(block, new_params)
        if error:
            messagebox.showerror("Invalid Label/Goto", error)
            return
        block.name = new_name
        block.note = new_note
        block.params = new_params
        if warning:
            self.threadsafe_log(f"Control-flow warning: {warning}")
            self.status_var.set(warning)
        self.refresh_tree(block.id)
        self.show_selected_properties()
        if block.type in ROOT_ONLY_BLOCK_TYPES:
            self._report_control_flow_warnings()
        self.schedule_marker_update()

    def _validate_control_flow_candidate(
        self, block: MacroBlock, params: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[str]]:
        if block.type not in ROOT_ONLY_BLOCK_TYPES:
            return None, None
        found = find_block(self.macro.blocks, block.id)
        if found and found[1] is not self.macro.blocks:
            return "Label and Goto blocks are root-level only.", None
        if block.type == "label":
            name = normalize_label_name(params.get("label_name"))
            if not name:
                return "Label name cannot be empty.", None
            duplicates = [
                candidate
                for candidate in self.macro.blocks
                if candidate.type == "label"
                and candidate.id != block.id
                and normalize_label_name(candidate.params.get("label_name")) == name
            ]
            if duplicates:
                return f"Label name '{name}' is already used.", None
            params["label_name"] = name
            return None, None
        target = normalize_label_name(params.get("target_label"))
        if not target:
            return "Goto target label cannot be empty.", None
        params["target_label"] = target
        if target not in root_label_names(self.macro):
            return None, f"Goto target label '{target}' does not exist yet."
        return None, None

    def _coerce_param(self, key: str, value: Any) -> Any:
        if key in {"click_before_run", "enable_multi_scale"}:
            if isinstance(value, bool):
                return value
            return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
        value = str(value).strip()
        int_keys = {
            "x",
            "y",
            "x1",
            "y1",
            "x2",
            "y2",
            "click_count",
            "press_count",
            "delay_after_ms",
            "movement_duration_ms",
            "after_success_delay_ms",
            "duration_ms",
            "tolerance",
            "check_interval_ms",
            "stable_duration_ms",
            "change_threshold",
            "post_click_delay_ms",
            "check_timeout_ms",
            "retry_count",
            "retry_delay_ms",
            "repeat_count",
            "green_strength",
            "minimum_green",
            "sample_step",
            "reference_x1",
            "reference_y1",
            "reference_x2",
            "reference_y2",
            "map_click_x",
            "map_click_y",
        }
        if key == "timeout_ms":
            return "" if value == "" else max(0, int(value))
        if key in {
            "minimum_match_percent",
            "maximum_changed_percent",
            "required_changed_percent",
        }:
            return max(0.0, min(100.0, float(value)))
        if key in {"hsv_hue_min", "hsv_hue_max"}:
            return max(0, min(179, int(float(value))))
        if key in {"hsv_min_saturation", "hsv_min_value"}:
            return max(0, min(255, int(float(value))))
        if key == "minimum_best_score":
            return max(-1.0, min(1.0, float(value)))
        if key == "minimum_score_margin":
            return max(0.0, min(2.0, float(value)))
        if key in {"scale_min", "scale_max"}:
            return max(0.05, min(4.0, float(value)))
        if key == "scale_step":
            return max(0.01, min(1.0, float(value)))
        if key in int_keys:
            return max(0, int(value))
        if key == "expected_color":
            text = value.upper()
            if not text.startswith("#"):
                text = f"#{text}"
            if len(text) != 7:
                raise ValueError("Expected colour must be #RRGGBB.")
            int(text[1:], 16)
            return text
        if key == "sampling_mode":
            return normalize_sampling_mode(value)
        if key == "detection_mode":
            return normalize_region_detection_mode(value)
        if key in {"macro_path", "reference_folder"}:
            return value
        return value

    def draft_block_params(self, block: MacroBlock) -> Dict[str, Any]:
        params = dict(block.params)
        for key, var in self.property_vars.items():
            if key in {"name", "note"}:
                continue
            try:
                params[key] = self._coerce_param(key, var.get())
            except ValueError:
                params[key] = var.get()
        return params

    def probe_pixel(self, block: MacroBlock) -> None:
        if not self.macro.target_window:
            messagebox.showinfo("No Target", "Bind a target window before probing pixels.")
            return

        params = self.draft_block_params(block)
        try:
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
        except ValueError as exc:
            messagebox.showerror("Invalid Coordinate", str(exc))
            return

        marker_resolution = self.current_marker_resolution()
        marker_was_visible = bool(
            self.marker_overlay.window
            and self.marker_overlay.window.state() == "normal"
        )
        self.hide_target_marker()
        self.root.update_idletasks()
        time_sleep_ms = 50
        self.root.after(time_sleep_ms, lambda: self._finish_pixel_probe(block, params, x, y, marker_resolution, marker_was_visible))

    def _finish_pixel_probe(
        self,
        block: MacroBlock,
        params: Dict[str, Any],
        x: int,
        y: int,
        marker_resolution: Optional[Tuple[int, int, int, int]],
        restore_marker: bool,
    ) -> None:
        try:
            target = self.window_manager.require_ready(
                self.macro.target_window, self.macro.expected_window_size
            )
            result = sample_pixel_for_params(
                self.window_manager,
                self.screen_analysis,
                target,
                x,
                y,
                params,
                block.type,
            )
            outcome = "match" if result.matched else "no_match"
            self.last_probe_capture = result.capture
            self.last_probe_label = (
                f"{self.macro.name}_pixel_probe_{block.label()}_x{x}_y{y}"
            )
            self.last_probe_result = outcome
            result.debug_capture_path = self.screen_analysis.save_debug_capture(
                result.capture, self.last_probe_label, outcome
            )
            marker_line = "Crosshair Coord: unavailable"
            alignment = "Crosshair/Pixel Alignment: unavailable"
            if marker_resolution:
                marker_rel_x, marker_rel_y, marker_screen_x, marker_screen_y = marker_resolution
                marker_line = (
                    "Crosshair Coord: "
                    f"relative ({marker_rel_x}, {marker_rel_y}), "
                    f"screen ({marker_screen_x}, {marker_screen_y})"
                )
                alignment = (
                    "Crosshair/Pixel Alignment: "
                    + (
                        "MATCH"
                        if (marker_screen_x, marker_screen_y)
                        == (result.screen_x, result.screen_y)
                        else "MISMATCH"
                    )
                )

            self.threadsafe_log(self._format_pixel_probe_log(block, target, result, marker_line, alignment))
            self.probe_result_var.set(
                f"{result.sampled_label()}: {result.sampled_text()} at "
                f"screen ({result.screen_x}, {result.screen_y}); {alignment.split(': ', 1)[-1]}"
            )
        except Exception as exc:
            self.threadsafe_log(f"[PixelProbe] Error: {exc}")
            self.probe_result_var.set(f"Probe failed: {exc}")
        finally:
            if restore_marker:
                self.schedule_marker_update()

    def current_marker_resolution(self) -> Optional[Tuple[int, int, int, int]]:
        block = self._coordinate_marker_block()
        if not block or not self.macro.target_window:
            return None
        try:
            x, y = self._marker_coordinates(block)
            target = self.window_manager.require_ready(
                self.macro.target_window, self.macro.expected_window_size
            )
            screen_x, screen_y = self.window_manager.client_to_screen(target, x, y)
            return x, y, screen_x, screen_y
        except (AutomationError, ValueError):
            return None

    def _format_pixel_probe_log(
        self,
        block: MacroBlock,
        target: Any,
        result: PixelSampleResult,
        marker_line: str,
        alignment: str,
    ) -> str:
        closest_line = ""
        if result.closest_offset:
            dx, dy = result.closest_offset
            closest_line = f"Closest Offset: ({dx:+d}, {dy:+d})\n"
        expected_lines = ""
        if result.expected_rgb is not None:
            outcome = "MATCH" if result.matched else "NO MATCH"
            expected_lines = (
                f"Expected: {color_to_hex(result.expected_rgb)} {color_to_rgb_text(result.expected_rgb)}\n"
                f"Configured tolerance: {result.configured_tolerance}\n"
                f"Required tolerance: {result.required_tolerance}\n"
                f"Result: {outcome}\n"
            )
        return (
            "[PixelProbe]\n"
            f"Block: {BLOCK_LABELS.get(block.type, block.type)}\n"
            f"Target Window: {target.title}\n"
            f"Relative Coord: ({result.relative_x}, {result.relative_y})\n"
            f"Resolved Screen Coord: ({result.screen_x}, {result.screen_y})\n"
            f"{marker_line}\n"
            f"{alignment}\n"
            f"Window Bounds: X={target.window_left} Y={target.window_top} "
            f"W={target.window_width} H={target.window_height}\n"
            f"Client Bounds: X={target.client_left} Y={target.client_top} "
            f"W={target.client_width} H={target.client_height}\n"
            f"Target DPI: {getattr(target, 'dpi', None) or 'unknown'}\n"
            f"Sampling: {result.sampling_mode}\n"
            f"Sample size: {result.sample_size}x{result.sample_size} ({result.sample_count} pixels read)\n"
            f"{closest_line}"
            f"{result.sampled_label()}: {result.sampled_text()}\n"
            f"{expected_lines}"
            f"Saved Capture: {result.debug_capture_path or 'disabled'}\n"
            "Capture backend: MSS -> BGRA -> OpenCV BGR -> RGB analysis\n"
            "Coordinate convention: target client/content area"
        )

    def capture_region_corner(
        self, block: MacroBlock, corner: str, prefix: str = ""
    ) -> None:
        self.apply_block_properties()
        if not self.macro.target_window:
            messagebox.showinfo("No Target", "Bind a target window before capturing a region.")
            return
        region_name = "reference capture region" if prefix else "runtime region"
        self.threadsafe_log(
            f"{region_name.title()} corner capture armed ({corner}). "
            "Click inside the target window within 15 seconds."
        )

        def worker() -> None:
            try:
                x, y = self.window_manager.capture_next_click(
                    self.macro.target_window,
                    self.macro.expected_window_size,
                    timeout_seconds=15,
                )
                if corner == "first":
                    block.params[f"{prefix}x1"] = x
                    block.params[f"{prefix}y1"] = y
                else:
                    block.params[f"{prefix}x2"] = x
                    block.params[f"{prefix}y2"] = y
                message = f"Captured {corner} {region_name} corner x={x}, y={y}"
                self.root.after(0, lambda: self._after_region_capture(block, message))
            except Exception as exc:
                error = str(exc)
                self.root.after(0, lambda: messagebox.showerror("Capture Failed", error))

        threading.Thread(target=worker, daemon=True).start()

    def _after_region_capture(self, block: MacroBlock, message: str) -> None:
        self.threadsafe_log(message)
        self.refresh_tree(block.id)
        self.block_tree.selection_set(block.id)
        self.show_selected_properties()
        self.schedule_marker_update()

    def probe_region(self, block: MacroBlock) -> None:
        if not self.macro.target_window:
            messagebox.showinfo("No Target", "Bind a target window before probing regions.")
            return
        params = self.draft_block_params(block)
        self.hide_target_marker()
        self.root.update_idletasks()
        self.root.after(50, lambda: self._finish_region_probe(block, params))

    def _finish_region_probe(self, block: MacroBlock, params: Dict[str, Any]) -> None:
        try:
            target = self.window_manager.require_ready(
                self.macro.target_window, self.macro.expected_window_size
            )
            result = check_region_for_params(
                self.window_manager,
                self.screen_analysis,
                target,
                params,
                block.type,
            )
            outcome = "match" if result.matched else "no_match"
            self.last_probe_capture = result.capture
            self.last_probe_label = (
                f"{self.macro.name}_region_probe_{block.label()}_"
                f"{result.left}_{result.top}_{result.right}_{result.bottom}"
            )
            self.last_probe_result = outcome
            result.debug_capture_path = self.screen_analysis.save_debug_capture(
                result.capture, self.last_probe_label, outcome
            )
            self.threadsafe_log(self._format_region_probe_log(block, target, result))
            self.probe_result_var.set(result.short_probe_text())
        except Exception as exc:
            self.threadsafe_log(f"[RegionProbe] Error: {exc}")
            self.probe_result_var.set(f"Probe failed: {exc}")
        finally:
            self.schedule_marker_update()

    def _format_region_probe_log(
        self, block: MacroBlock, target: Any, result: RegionCheckResult
    ) -> str:
        average_required_line = ""
        if result.average_required_tolerance is not None:
            average_required_line = (
                f"Average required tolerance: {result.average_required_tolerance}\n"
            )
        return (
            "[RegionProbe]\n"
            f"Block: {BLOCK_LABELS.get(block.type, block.type)}\n"
            f"Target Window: {target.title}\n"
            f"Relative Region: left={result.left} top={result.top} right={result.right} bottom={result.bottom}\n"
            f"Screen Region: left={result.screen_left} top={result.screen_top} "
            f"right={result.screen_right} bottom={result.screen_bottom}\n"
            f"Window Bounds: X={target.window_left} Y={target.window_top} "
            f"W={target.window_width} H={target.window_height}\n"
            f"Client Bounds: X={target.client_left} Y={target.client_top} "
            f"W={target.client_width} H={target.client_height}\n"
            f"DPI: {target.dpi if target.dpi is not None else 'unknown'}\n"
            f"Size: {result.width}x{result.height}\n"
            f"{region_mode_details(result)}\n"
            f"Sample step: {result.sample_step}\n"
            f"Expected sampled pixels: {result.expected_sampled_pixels}\n"
            f"Sampled pixels: {result.sampled_pixels}\n"
            f"Average sampled: {color_to_hex(result.average_rgb)} {color_to_rgb_text(result.average_rgb)}\n"
            f"Min RGB: {color_to_rgb_text(result.min_rgb)}\n"
            f"Max RGB: {color_to_rgb_text(result.max_rgb)}\n"
            f"{region_colour_diagnostics(result)}\n"
            f"{average_required_line}"
            f"Required match: {result.minimum_match_percent:g}%\n"
            f"Actual match: {result.actual_match_percent:.1f}%\n"
            f"Matching pixels: {result.matching_pixels} / {result.sampled_pixels}\n"
            f"Elapsed: {result.elapsed_ms:.0f} ms\n"
            f"Result: {result.result_text()}\n"
            f"Saved Capture: {result.debug_capture_path or 'disabled'}\n"
            "Capture backend: MSS -> BGRA -> OpenCV BGR/RGB/HSV\n"
            "Coordinate convention: target client/content area"
        )

    def probe_map_classification(self, block: MacroBlock) -> None:
        if not self.macro.target_window:
            messagebox.showinfo(
                "No Target", "Bind a target window before probing classification."
            )
            return
        params = self.draft_block_params(block)
        self.hide_target_marker()
        self.root.update_idletasks()
        self.root.after(
            50, lambda: self._finish_map_classification_probe(block, params)
        )

    def _finish_map_classification_probe(
        self, block: MacroBlock, params: Dict[str, Any]
    ) -> None:
        try:
            target = self.window_manager.require_ready(
                self.macro.target_window, self.macro.expected_window_size
            )
            region = normalize_region(
                params.get("x1", 0),
                params.get("y1", 0),
                params.get("x2", 0),
                params.get("y2", 0),
            )
            capture = self.screen_analysis.capture_target_region(target, *region)
            reference_value = str(params.get("reference_folder", "") or "").strip()
            if not reference_value:
                raise MapClassificationError("No reference folder is configured.")
            folder = self.storage.resolve_reference(reference_value)
            result = classify_map_patch(
                capture.bgr,
                folder,
                enable_multi_scale=bool(params.get("enable_multi_scale", True)),
                scale_min=float(params.get("scale_min", 0.90)),
                scale_max=float(params.get("scale_max", 1.10)),
                scale_step=float(params.get("scale_step", 0.05)),
            )
            minimum_best = float(params.get("minimum_best_score", 0.75))
            minimum_margin = float(params.get("minimum_score_margin", 0.05))
            outcome = (
                result.best.map_id
                if result.passes(minimum_best, minimum_margin) and result.best
                else "low_confidence"
            )
            self.last_probe_capture = capture
            self.last_probe_label = f"{self.macro.name}_classify_map_runtime"
            self.last_probe_result = outcome
            saved = self.screen_analysis.save_debug_capture(
                capture, self.last_probe_label, outcome
            )
            log = format_classification_log(
                result,
                heading="ClassifyMapProbe",
                reference_folder=folder,
                region=region,
                minimum_best_score=minimum_best,
                minimum_margin=minimum_margin,
            )
            self.threadsafe_log(
                log + f"\nSaved Runtime Patch: {saved or 'disabled'}"
            )
            best_text = result.best.map_id if result.best else "none"
            verdict = (
                "PASS"
                if result.passes(minimum_best, minimum_margin)
                else "LOW CONFIDENCE"
            )
            best_score = result.best.score if result.best else -1.0
            self.probe_result_var.set(
                f"Last probe: {best_text} score={best_score:.4f}, "
                f"margin={result.margin:.4f} - {verdict}"
            )
        except Exception as exc:
            self.threadsafe_log(f"[ClassifyMapProbe] Error: {exc}")
            self.probe_result_var.set(f"Probe failed: {exc}")
        finally:
            self.schedule_marker_update()

    def browse_reference_folder(self, block: MacroBlock) -> None:
        self.apply_block_properties()
        current = self.storage.resolve_reference(
            str(block.params.get("reference_folder", "") or "references/maps/expert")
        )
        path = filedialog.askdirectory(
            title="Select Map Reference Folder",
            initialdir=str(current if current.exists() else self.storage.project_dir),
        )
        if not path:
            return
        block.params["reference_folder"] = self.storage.to_reference(path)
        self.threadsafe_log(
            f"Selected map reference folder: {block.params['reference_folder']}"
        )
        self.refresh_tree(block.id)
        self.block_tree.selection_set(block.id)
        self.show_selected_properties()

    def capture_map_reference(self, block: MacroBlock) -> None:
        self.apply_block_properties()
        if not self.macro.target_window:
            messagebox.showinfo(
                "No Target", "Bind a target window before capturing a reference."
            )
            return
        map_id = simpledialog.askstring(
            "Map Reference",
            "Map ID for the new reference image:",
            parent=self.root,
        )
        if map_id is None:
            return
        map_id = normalize_map_id(map_id)
        if not map_id:
            messagebox.showerror("Invalid Map ID", "Map ID cannot be empty.")
            return
        params = dict(block.params)
        self.hide_target_marker()
        self.root.update_idletasks()

        def worker() -> None:
            try:
                target = self.window_manager.require_ready(
                    self.macro.target_window, self.macro.expected_window_size
                )
                region = normalize_region(
                    params.get("reference_x1", params.get("x1", 0)),
                    params.get("reference_y1", params.get("y1", 0)),
                    params.get("reference_x2", params.get("x2", 0)),
                    params.get("reference_y2", params.get("y2", 0)),
                )
                capture = self.screen_analysis.capture_target_region(target, *region)
                reference_value = str(
                    params.get("reference_folder", "") or ""
                ).strip()
                if not reference_value:
                    raise MapClassificationError("No reference folder is configured.")
                folder = self.storage.resolve_reference(reference_value)
                path = save_map_reference(capture.bgr, folder, map_id)
                message = (
                    f"[MapReferenceCapture]\nMap ID: {map_id}\n"
                    f"Region: left={region[0]} top={region[1]} "
                    f"right={region[2]} bottom={region[3]}\nSaved: {path}"
                )
                self.root.after(0, lambda: self._after_map_reference_capture(message))
            except Exception as exc:
                error = str(exc)
                self.root.after(
                    0, lambda: messagebox.showerror("Reference Capture Failed", error)
                )
                self.root.after(0, self.schedule_marker_update)

        threading.Thread(target=worker, daemon=True).start()

    def _after_map_reference_capture(self, message: str) -> None:
        self.threadsafe_log(message)
        self.status_var.set("Map reference image saved.")
        self.schedule_marker_update()

    def apply_macro_header(self) -> None:
        self.macro.name = self.macro_name_var.get().strip() or "Untitled Macro"
        self.macro.notes = self.notes_text.get("1.0", tk.END).strip()

    def new_macro(self) -> None:
        if not self._confirm_safe_transition("creating a new macro"):
            return
        self.macro = Macro()
        self.refresh_all()
        self.macro_list.selection_clear(0, tk.END)
        self._mark_clean()

    def convert_current_macro_clicks(self) -> None:
        if not self.macro:
            messagebox.showinfo("No Macro", "Open a macro before converting Click blocks.")
            return
        if self.recording:
            messagebox.showinfo(
                "Recording Active", "Stop recording before converting Click blocks."
            )
            return
        if self.runner.is_running or self.running:
            messagebox.showinfo(
                "Macro Running", "Stop the running macro before converting Click blocks."
            )
            return
        if not self._confirm_click_conversion():
            return
        if not self._save_for_transition():
            self.threadsafe_log("Click conversion cancelled because the macro was not saved.")
            return

        plain_click_count = sum(
            1 for block in self.macro.all_blocks() if block.type == "click"
        )
        if plain_click_count == 0:
            message = "No plain Click blocks found to convert."
            self.threadsafe_log(message)
            self.status_var.set(message)
            messagebox.showinfo("Convert Click Blocks", message)
            return

        source_path = Path(str(self.macro.path or "")).resolve()
        try:
            backup_path = self._create_click_conversion_backup(source_path)
            original_macro = self.storage.load(source_path)
        except Exception as exc:
            self.threadsafe_log(f"Click conversion backup failed: {exc}")
            messagebox.showerror(
                "Click Conversion Backup Failed",
                f"The macro was not modified.\n\n{exc}",
            )
            return

        try:
            converted = convert_clicks_to_move_and_click(self.macro, 150)
            if converted != plain_click_count:
                raise RuntimeError(
                    f"Expected to convert {plain_click_count} Click blocks, "
                    f"but converted {converted}."
                )
        except Exception as exc:
            self.macro = original_macro
            self.refresh_all()
            self._mark_clean()
            self.threadsafe_log(f"Click conversion failed before save: {exc}")
            messagebox.showerror(
                "Click Conversion Failed",
                f"The original macro remains loaded.\n\n{exc}",
            )
            return

        if not self.save_macro():
            restore_error = self._restore_click_conversion_backup(
                backup_path, source_path, original_macro
            )
            message = "The converted macro could not be saved. The original was restored."
            if restore_error:
                message += f"\n\nRestore warning: {restore_error}"
            self.threadsafe_log(message)
            messagebox.showerror("Click Conversion Failed", message)
            return

        try:
            self.macro = self.storage.load(source_path)
            self.refresh_all()
            self.refresh_macro_list(source_path)
            self._mark_clean()
        except Exception as exc:
            restore_error = self._restore_click_conversion_backup(
                backup_path, source_path, original_macro
            )
            message = f"Converted macro reload failed: {exc}"
            if restore_error:
                message += f" Restore warning: {restore_error}"
            self.threadsafe_log(message)
            messagebox.showerror("Click Conversion Failed", message)
            return

        message = (
            f"Converted {converted} Click blocks to Move And Click blocks in "
            f"{self.macro.name}. Backup saved to {backup_path}"
        )
        self.threadsafe_log(message)
        self.status_var.set(f"Converted {converted} Click blocks to Move And Click.")

    def _confirm_click_conversion(self) -> bool:
        decision = {"convert": False}
        dialog = tk.Toplevel(self.root)
        dialog.title("Convert Click Blocks")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        ttk.Label(
            dialog,
            text=(
                "Convert all plain Click blocks in the current macro to "
                "Move And Click blocks?\n\n"
                "This will preserve click coordinates and button settings, "
                "and add a 150ms movement duration."
            ),
            justify="left",
            wraplength=430,
        ).pack(fill="x", padx=14, pady=(14, 10))

        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=14, pady=(0, 14))

        def close(convert: bool) -> None:
            decision["convert"] = convert
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=lambda: close(False)).pack(
            side="right"
        )
        ttk.Button(buttons, text="Convert", command=lambda: close(True)).pack(
            side="right", padx=(0, 7)
        )
        dialog.protocol("WM_DELETE_WINDOW", lambda: close(False))
        dialog.bind("<Escape>", lambda _event: close(False))
        dialog.wait_window()
        return decision["convert"]

    def _create_click_conversion_backup(self, source_path: Path) -> Path:
        if not source_path.is_file():
            raise FileNotFoundError(f"Saved macro file was not found: {source_path}")
        backup_dir = (
            self.storage.project_dir
            / "macro_backups"
            / "v1.11_click_to_move_click"
        )
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        backup_path = backup_dir / f"{source_path.stem}_{timestamp}.json"
        counter = 2
        while backup_path.exists():
            backup_path = backup_dir / (
                f"{source_path.stem}_{timestamp}_{counter}.json"
            )
            counter += 1
        shutil.copy2(source_path, backup_path)
        return backup_path.resolve()

    def _restore_click_conversion_backup(
        self, backup_path: Path, source_path: Path, original_macro: Macro
    ) -> Optional[str]:
        try:
            shutil.copy2(backup_path, source_path)
            self.macro = self.storage.load(source_path)
            self.refresh_all()
            self.refresh_macro_list(source_path)
            self._mark_clean()
            return None
        except Exception as exc:
            self.macro = original_macro
            self.refresh_all()
            return str(exc)

    def save_macro(self) -> bool:
        try:
            self.apply_macro_header()
            self._report_control_flow_warnings()
            path = self.storage.save(self.macro)
            self.threadsafe_log(f"Saved macro to {path}")
            self.refresh_macro_list(path)
            self._mark_clean()
            return True
        except Exception as exc:
            self.threadsafe_log(f"Save failed: {exc}")
            messagebox.showerror("Save Failed", str(exc))
            return False

    def save_macro_as(self) -> bool:
        self.apply_macro_header()
        self._report_control_flow_warnings()
        path = filedialog.asksaveasfilename(
            title="Save Macro As",
            initialdir=str(self.storage.base_dir),
            defaultextension=".json",
            filetypes=[("Macro JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return False
        try:
            saved = self.storage.save(self.macro, path)
            self.threadsafe_log(f"Saved macro to {saved}")
            self.refresh_macro_list(saved)
            self._mark_clean()
            return True
        except Exception as exc:
            self.threadsafe_log(f"Save failed: {exc}")
            messagebox.showerror("Save Failed", str(exc))
            return False

    def load_selected_macro(self) -> None:
        selection = self.macro_list.curselection()
        if not selection:
            self.load_from_file()
            return
        path = self.macro_paths[selection[0]]
        self.load_macro_path(path)

    def load_from_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load Macro",
            initialdir=str(self.storage.base_dir),
            filetypes=[("Macro JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.load_macro_path(Path(path))

    def load_macro_path(self, path: Path) -> None:
        if not self._confirm_safe_transition("switching macros"):
            if self.macro.path:
                self.refresh_macro_list(self.macro.path)
            return
        try:
            self.macro = self.storage.load(path)
            self.threadsafe_log(f"Loaded macro from {path}")
            self.refresh_all()
            self.refresh_macro_list(path)
            self._mark_clean()
            self._report_control_flow_warnings()
        except Exception as exc:
            messagebox.showerror("Load Failed", str(exc))
            if self.macro.path:
                self.refresh_macro_list(self.macro.path)

    def browse_saved_macro(self, block: MacroBlock) -> None:
        path = filedialog.askopenfilename(
            title="Select Saved Macro",
            initialdir=str(self.storage.base_dir.resolve()),
            filetypes=[("Macro JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        block.params["macro_path"] = self.storage.to_reference(path)
        self.threadsafe_log(
            f"Selected called macro: {block.params['macro_path']}"
        )
        self.refresh_tree(block.id)
        self.block_tree.selection_set(block.id)
        self.block_tree.focus(block.id)
        self.show_selected_properties()

    def edit_map_macro_mapping(self, block: MacroBlock) -> None:
        self.apply_block_properties()
        existing = block.params.get("map_macro_mapping") or {}
        mapping = (
            {str(key): str(value) for key, value in existing.items()}
            if isinstance(existing, dict)
            else {}
        )

        dialog = tk.Toplevel(self.root)
        dialog.title("Map To Macro Mapping")
        dialog.geometry("760x460")
        dialog.transient(self.root)
        dialog.grab_set()

        tree = ttk.Treeview(
            dialog,
            columns=("map_id", "macro_path"),
            show="headings",
            selectmode="browse",
        )
        tree.heading("map_id", text="Map ID")
        tree.heading("macro_path", text="Saved Macro")
        tree.column("map_id", width=180, stretch=False)
        tree.column("macro_path", width=520)
        tree.pack(fill="both", expand=True, padx=8, pady=(8, 6))

        editor = ttk.Frame(dialog)
        editor.pack(fill="x", padx=8)
        map_id_var = tk.StringVar()
        macro_path_var = tk.StringVar()
        ttk.Label(editor, text="Map ID", width=12).grid(row=0, column=0, sticky="w")
        ttk.Entry(editor, textvariable=map_id_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 6)
        )
        ttk.Label(editor, text="Macro", width=12).grid(row=1, column=0, sticky="w")
        ttk.Entry(editor, textvariable=macro_path_var).grid(
            row=1, column=1, sticky="ew", padx=(0, 6), pady=(5, 0)
        )
        editor.columnconfigure(1, weight=1)

        def refresh() -> None:
            tree.delete(*tree.get_children(""))
            for map_id in sorted(mapping, key=str.casefold):
                tree.insert("", "end", iid=map_id, values=(map_id, mapping[map_id]))

        def choose_macro() -> None:
            path = filedialog.askopenfilename(
                title="Select Saved Macro",
                initialdir=str(self.storage.base_dir.resolve()),
                filetypes=[("Macro JSON", "*.json"), ("All files", "*.*")],
                parent=dialog,
            )
            if path:
                macro_path_var.set(self.storage.to_reference(path))

        def add_or_update() -> None:
            map_id = normalize_map_id(map_id_var.get())
            macro_path = macro_path_var.get().strip()
            if not map_id or not macro_path:
                messagebox.showerror(
                    "Invalid Mapping",
                    "Provide both a map ID and saved macro path.",
                    parent=dialog,
                )
                return
            mapping[map_id] = macro_path
            refresh()
            tree.selection_set(map_id)

        def remove() -> None:
            selection = tree.selection()
            if selection:
                mapping.pop(selection[0], None)
                refresh()

        def on_select(_event=None) -> None:
            selection = tree.selection()
            if not selection:
                return
            map_id = selection[0]
            map_id_var.set(map_id)
            macro_path_var.set(mapping[map_id])

        def apply_mapping() -> None:
            block.params["map_macro_mapping"] = dict(mapping)
            self.threadsafe_log(
                f"Updated map-to-macro mapping: {len(mapping)} entry/entries."
            )
            self.refresh_tree(block.id)
            self.block_tree.selection_set(block.id)
            self.show_selected_properties()
            dialog.destroy()

        actions = ttk.Frame(dialog)
        actions.pack(fill="x", padx=8, pady=(6, 8))
        ttk.Button(editor, text="Browse", command=choose_macro).grid(
            row=1, column=2, sticky="ew", pady=(5, 0)
        )
        ttk.Button(actions, text="Add / Update", command=add_or_update).pack(
            side="left"
        )
        ttk.Button(actions, text="Remove", command=remove).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(actions, text="Apply Mapping", command=apply_mapping).pack(
            side="right"
        )
        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(
            side="right", padx=(0, 6)
        )
        tree.bind("<<TreeviewSelect>>", on_select)
        refresh()

    def open_bind_window(self) -> None:
        if self.recording:
            messagebox.showinfo(
                "Recording Active", "Stop recording before binding another target."
            )
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Bind Target Window")
        dialog.geometry("760x420")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Select a visible window. Coordinates use the client area.").pack(
            anchor="w", padx=8, pady=(8, 4)
        )

        tree = ttk.Treeview(dialog, columns=("size", "class", "hwnd"), show="headings")
        tree.heading("size", text="Client Size")
        tree.heading("class", text="Class")
        tree.heading("hwnd", text="Handle / Title")
        tree.column("size", width=100, stretch=False)
        tree.column("class", width=150, stretch=False)
        tree.column("hwnd", width=480)
        tree.pack(fill="both", expand=True, padx=8, pady=4)

        windows: List[Any] = []

        def refresh() -> None:
            nonlocal windows
            tree.delete(*tree.get_children(""))
            windows = self.window_manager.list_windows()
            for index, info in enumerate(windows):
                tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(
                        f"{info.client_width}x{info.client_height}",
                        info.class_name,
                        f"{info.hwnd}: {info.title}",
                    ),
                )

        def bind() -> None:
            selection = tree.selection()
            if not selection:
                return
            info = windows[int(selection[0])]
            self.macro.target_window = info.to_macro_target()
            self.macro.expected_window_size = info.size_dict()
            self.refresh_target_status()
            self.threadsafe_log(f"Bound target: {format_window(info)}")
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=8, pady=(4, 8))
        ttk.Button(buttons, text="Refresh", command=refresh).pack(side="left")
        ttk.Button(buttons, text="Bind Selected", command=bind).pack(side="right")
        refresh()

    def capture_click(
        self, block: MacroBlock, x_key: str = "x", y_key: str = "y"
    ) -> None:
        self.apply_block_properties()
        self._capture(block, include_pixel=False, x_key=x_key, y_key=y_key)

    def capture_pixel(self, block: MacroBlock) -> None:
        self.apply_block_properties()
        self._capture(block, include_pixel=True)

    def _capture(
        self,
        block: MacroBlock,
        include_pixel: bool,
        x_key: str = "x",
        y_key: str = "y",
    ) -> None:
        if not self.macro.target_window:
            messagebox.showinfo("No Target", "Bind a target window before capturing.")
            return
        if include_pixel:
            self.hide_target_marker()
        self.threadsafe_log("Capture armed. Click inside the target window within 15 seconds.")

        def worker() -> None:
            try:
                x, y = self.window_manager.capture_next_click(
                    self.macro.target_window,
                    self.macro.expected_window_size,
                    timeout_seconds=15,
                )
                block.params[x_key] = x
                block.params[y_key] = y
                message = f"Captured x={x}, y={y}"
                if include_pixel:
                    target = self.window_manager.require_ready(
                        self.macro.target_window,
                        self.macro.expected_window_size,
                    )
                    screen_x, screen_y = self.window_manager.client_to_screen(target, x, y)
                    color = self.screen_analysis.get_pixel(target, x, y)
                    block.params["expected_color"] = color_to_hex(color)
                    message += f", colour {block.params['expected_color']}"
                    self.threadsafe_log(
                        "[PixelCapture]\n"
                        f"Target Window: {target.title}\n"
                        f"Relative Coord: ({x}, {y})\n"
                        f"Screen Coord: ({screen_x}, {screen_y})\n"
                        f"Captured: {color_to_hex(color)} {color_to_rgb_text(color)}"
                    )
                self.root.after(0, lambda: self._after_capture(block, message))
            except Exception as exc:
                error = str(exc)
                self.root.after(0, lambda: messagebox.showerror("Capture Failed", error))

        threading.Thread(target=worker, daemon=True).start()

    def _after_capture(self, block: MacroBlock, message: str) -> None:
        self.threadsafe_log(message)
        self.refresh_tree(block.id)
        self.block_tree.selection_set(block.id)
        self.show_selected_properties()
        self.schedule_marker_update()

    def run_macro(self) -> None:
        if not self._prepare_macro_run():
            return
        self.clear_stop_notice()
        self.hide_target_marker()
        self.start_user_override_monitors()
        self.runner.start(self.macro)

    def run_from_context_block(self) -> str:
        block_id = self.context_menu_block_id
        block = self._block_by_id(block_id) if block_id else None
        if not block:
            messagebox.showinfo("Run From Here", "Right-click a macro block to run from it.")
            return "break"
        if not self._prepare_macro_run():
            return "break"
        self.clear_stop_notice()
        self.threadsafe_log(
            f"Run From Here requested: {block.label()} ({block_summary(block)})"
        )
        self.hide_target_marker()
        self.start_user_override_monitors()
        self.runner.start(self.macro, block.id)
        return "break"

    def _prepare_macro_run(self) -> bool:
        if self.recording:
            messagebox.showinfo(
                "Recording Active", "Stop recording before running a macro."
            )
            return False
        if self.running:
            return False
        self.apply_macro_header()
        if not self.macro.target_window:
            messagebox.showinfo("No Target", "Bind a target window before running a macro.")
            return False
        if not self.macro.blocks:
            messagebox.showinfo("No Blocks", "Add at least one block before running a macro.")
            return False
        errors = control_flow_errors(self.macro)
        if errors:
            message = "\n".join(f"- {error}" for error in errors)
            self.threadsafe_log(f"Control-flow validation failed:\n{message}")
            messagebox.showerror("Invalid Label/Goto Control Flow", message)
            return False
        if not self._save_before_run():
            return False
        return True

    def _save_before_run(self) -> bool:
        if not self.macro.path:
            messagebox.showinfo(
                "Save Required",
                "Save this new macro before running it.",
            )
            return self.save_macro_as()
        return self.save_macro()

    def _report_control_flow_warnings(self) -> None:
        errors = control_flow_errors(self.macro)
        if not errors:
            return
        message = " ".join(errors)
        self.threadsafe_log(f"Control-flow warning: {message}")
        self.status_var.set(f"Control-flow warning: {errors[0]}")

    def stop_macro(self, reason: str = "Stop button clicked.") -> None:
        if self.runner.is_running:
            self.show_stop_notice(reason)
            self.runner.stop(reason)

    def on_global_stop(self) -> None:
        self.root.after(0, lambda: self.stop_macro("Global emergency hotkey pressed."))

    def start_recording(self) -> None:
        if self.recording:
            return
        if self.runner.is_running or self.running:
            messagebox.showinfo(
                "Macro Running", "Stop the running macro before recording."
            )
            return
        if not self.macro.target_window:
            messagebox.showinfo(
                "No Target", "Bind a target window before recording."
            )
            return
        try:
            target = self.window_manager.require_ready(
                self.macro.target_window, self.macro.expected_window_size
            )
        except AutomationError as exc:
            messagebox.showerror("Cannot Start Recording", str(exc))
            return

        self.apply_macro_header()
        self.update_builder_bounds()
        self.recording_target_list, self.recording_insert_index = self._list_for_add_after(
            self.selected_item_id()
        )
        self.recording_count = 0
        self.recording = True
        self.hide_target_marker()
        self.recording_indicator_var.set("Recording...")
        self.status_var.set(f"Recording input from: {target.title}")
        if self.record_button:
            self.record_button.state(["disabled"])
        if self.stop_recording_button:
            self.stop_recording_button.state(["!disabled"])
        self.start_user_override_monitors()
        self.threadsafe_log(
            "Recording started. Target-window clicks and foreground target keys "
            "will be appended as normal macro blocks."
        )

    def stop_recording(self, reason: str = "Stop Recording clicked.") -> None:
        if not self.recording:
            return
        self.recording = False
        self.stop_user_override_monitors()
        self.recording_target_list = None
        self.recording_indicator_var.set("")
        if self.record_button:
            self.record_button.state(["!disabled"])
        if self.stop_recording_button:
            self.stop_recording_button.state(["disabled"])
        self.status_var.set(f"Recording stopped. Added {self.recording_count} blocks.")
        self.threadsafe_log(
            f"Recording stopped: {reason} Added {self.recording_count} blocks."
        )
        self.schedule_marker_update()

    def _append_recorded_block(self, block: MacroBlock, message: str) -> None:
        if not self.recording or self.recording_target_list is None:
            return
        self.recording_target_list.insert(self.recording_insert_index, block)
        self.recording_insert_index += 1
        self.recording_count += 1
        self.refresh_tree(block.id)
        self.show_selected_properties()
        self.status_var.set(message)
        self.threadsafe_log(message)

    def _record_mouse_click(self, x: int, y: int, button: str) -> None:
        block = MacroBlock.create("click")
        block.params.update({"x": int(x), "y": int(y), "button": button, "click_count": 1})
        self._append_recorded_block(
            block, f"Recorded {button} click at ({x}, {y})"
        )

    def _record_keyboard_input(self, key: str) -> None:
        block = MacroBlock.create("key_press")
        block.params.update({"key": key, "press_count": 1})
        self._append_recorded_block(block, f"Recorded key: {key}")

    def _recording_target_error(self, message: str) -> None:
        if not self.recording:
            return
        self.threadsafe_log(f"Recording stopped: {message}")
        self.stop_recording(message)

    def on_user_keyboard_input(self, vk_code: int) -> None:
        if self.recording:
            try:
                target = self.window_manager.require_ready(
                    self.macro.target_window, self.macro.expected_window_size
                )
                if not self.window_manager.is_foreground(target):
                    return
                key = vk_code_to_key(vk_code)
                if key:
                    self.root.after(0, lambda value=key: self._record_keyboard_input(value))
            except AutomationError as exc:
                self.root.after(
                    0, lambda message=str(exc): self._recording_target_error(message)
                )
            return
        if self.runner.is_running:
            self.root.after(
                0, lambda: self.stop_macro("User keyboard input detected.")
            )

    def on_user_mouse_click(
        self, screen_x: int, screen_y: int, button: str = "left"
    ) -> None:
        if self.recording:
            left, top, right, bottom = self.builder_bounds
            if left <= screen_x < right and top <= screen_y < bottom:
                return
            try:
                target = self.window_manager.require_ready(
                    self.macro.target_window, self.macro.expected_window_size
                )
                x, y = self.window_manager.screen_to_client(
                    target, screen_x, screen_y
                )
                if target.contains_client_point(x, y):
                    self.root.after(
                        0,
                        lambda rel_x=x, rel_y=y, mouse_button=button: self._record_mouse_click(
                            rel_x, rel_y, mouse_button
                        ),
                    )
                else:
                    self.root.after(
                        0,
                        lambda: self.threadsafe_log(
                            "Ignored recording click outside the target window."
                        ),
                    )
            except AutomationError as exc:
                self.root.after(
                    0, lambda message=str(exc): self._recording_target_error(message)
                )
            return
        if not self.runner.is_running:
            return
        left, top, right, bottom = self.builder_bounds
        if left <= screen_x < right and top <= screen_y < bottom:
            reason = (
                "Stop button clicked."
                if self._point_inside_widget(self.stop_button, screen_x, screen_y)
                else "User clicked Macro Builder window."
            )
            self.root.after(0, lambda: self.stop_macro(reason))

    def start_user_override_monitors(self) -> None:
        self.update_builder_bounds()
        self.user_keyboard_monitor.start()
        self.user_mouse_monitor.start()

    def stop_user_override_monitors(self) -> None:
        self.user_keyboard_monitor.stop()
        self.user_mouse_monitor.stop()

    def threadsafe_log(self, message: str) -> None:
        if self.closing:
            return
        try:
            self.root.after(0, lambda: self._append_log(message))
        except tk.TclError:
            pass

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def threadsafe_running_state(self, running: bool) -> None:
        if self.closing:
            return
        try:
            self.root.after(0, lambda: self._set_running_state(running))
        except tk.TclError:
            pass

    def _set_running_state(self, running: bool) -> None:
        self.running = running
        if running:
            self.hide_target_marker()
            self.start_user_override_monitors()
            if self.record_button:
                self.record_button.state(["disabled"])
        else:
            self.stop_user_override_monitors()
            if self.record_button and not self.recording:
                self.record_button.state(["!disabled"])
            if self.runner.stop_reason:
                self.show_stop_notice(self.runner.stop_reason)
        self.status_var.set("Running..." if running else self.status_var.get())
        if not running:
            self.refresh_target_status()
            self.schedule_marker_update()

    def on_close(self) -> None:
        if not self._confirm_safe_transition("closing"):
            return
        self.closing = True
        self.recording = False
        if self.dirty_check_after_id:
            try:
                self.root.after_cancel(self.dirty_check_after_id)
            except tk.TclError:
                pass
            self.dirty_check_after_id = None
        if self.marker_update_after_id:
            try:
                self.root.after_cancel(self.marker_update_after_id)
            except tk.TclError:
                pass
            self.marker_update_after_id = None
        if self.runner.is_running:
            self.runner.stop("Macro Builder is closing.")
            if self.runner.thread:
                self.runner.thread.join(timeout=1.0)
        self.stop_user_override_monitors()
        self.hotkey.stop()
        self.marker_overlay.destroy()
        self.region_overlay.destroy()
        self.root.destroy()


def main() -> None:
    enable_dpi_awareness()
    root = tk.Tk()
    style = ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = MacroEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
