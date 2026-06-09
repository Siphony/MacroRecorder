from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
HOTKEY_ID = 0x4D52
VK_LBUTTON = 0x01
VK_Q = 0x51
VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x00000001

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


ULONG_PTR = wintypes.WPARAM
LRESULT = wintypes.LPARAM
HHOOK = wintypes.HANDLE
HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.mouse_event.argtypes = [
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_ulong,
]
user32.keybd_event.argtypes = [
    wintypes.BYTE,
    wintypes.BYTE,
    wintypes.DWORD,
    ctypes.c_ulong,
]
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = wintypes.SHORT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    HOOKPROC,
    wintypes.HINSTANCE,
    wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = HHOOK
user32.CallNextHookEx.argtypes = [
    HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
class AutomationError(RuntimeError):
    pass


def enable_dpi_awareness() -> bool:
    """Keep Win32 client coordinates aligned with physical MSS screen pixels."""
    try:
        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = [wintypes.HANDLE]
        setter.restype = wintypes.BOOL
        if setter(ctypes.c_void_p(-4)):
            return True
    except Exception:
        pass
    try:
        setter = user32.SetProcessDPIAware
        setter.argtypes = []
        setter.restype = wintypes.BOOL
        return bool(setter())
    except Exception:
        return False


@dataclass
class TargetWindowInfo:
    hwnd: int
    title: str
    class_name: str
    client_left: int
    client_top: int
    client_width: int
    client_height: int
    window_left: int
    window_top: int
    window_width: int
    window_height: int
    dpi: Optional[int] = None

    @property
    def client_rect(self) -> Tuple[int, int, int, int]:
        return (
            self.client_left,
            self.client_top,
            self.client_width,
            self.client_height,
        )

    def contains_client_point(self, x: int, y: int) -> bool:
        return 0 <= x < self.client_width and 0 <= y < self.client_height

    def to_macro_target(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "class_name": self.class_name,
            "hwnd": self.hwnd,
        }

    def size_dict(self) -> Dict[str, int]:
        return {"width": self.client_width, "height": self.client_height}


class WindowManager:
    def list_windows(self) -> List[TargetWindowInfo]:
        windows: List[TargetWindowInfo] = []

        @EnumWindowsProc
        def callback(hwnd: int, _: int) -> bool:
            try:
                if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                    title = self._window_title(hwnd)
                    if title:
                        info = self.get_window_info(hwnd)
                        if info.client_width > 0 and info.client_height > 0:
                            windows.append(info)
            except AutomationError:
                pass
            return True

        user32.EnumWindows(callback, 0)
        return sorted(windows, key=lambda w: w.title.lower())

    def resolve(self, target_data: Optional[Dict[str, Any]]) -> TargetWindowInfo:
        if not target_data:
            raise AutomationError("No target window is bound.")

        hwnd = int(target_data.get("hwnd") or 0)
        title = str(target_data.get("title") or "")
        class_name = str(target_data.get("class_name") or "")

        if hwnd and user32.IsWindow(hwnd):
            try:
                info = self.get_window_info(hwnd)
                if self._target_matches(info, title, class_name):
                    return info
            except AutomationError:
                pass

        candidates = self.list_windows()
        exact = [
            w
            for w in candidates
            if (not title or w.title == title)
            and (not class_name or w.class_name == class_name)
        ]
        if exact:
            return exact[0]

        title_matches = [w for w in candidates if title and title in w.title]
        if title_matches:
            return title_matches[0]

        raise AutomationError(f"Target window not found: {title or class_name or hwnd}")

    def require_ready(
        self,
        target_data: Optional[Dict[str, Any]],
        expected_size: Optional[Dict[str, int]] = None,
    ) -> TargetWindowInfo:
        info = self.resolve(target_data)
        if not user32.IsWindowVisible(info.hwnd):
            raise AutomationError("Target window is not visible.")
        if user32.IsIconic(info.hwnd):
            raise AutomationError("Target window is minimised.")
        if info.client_width <= 0 or info.client_height <= 0:
            raise AutomationError("Target window client area is empty.")

        if expected_size:
            expected_width = int(expected_size.get("width") or 0)
            expected_height = int(expected_size.get("height") or 0)
            if expected_width and expected_height and (
                expected_width != info.client_width
                or expected_height != info.client_height
            ):
                raise AutomationError(
                    "Target window size changed. "
                    f"Expected {expected_width}x{expected_height}, "
                    f"found {info.client_width}x{info.client_height}."
                )
        return info

    def get_window_info(self, hwnd: int) -> TargetWindowInfo:
        if not user32.IsWindow(hwnd):
            raise AutomationError("Window handle is no longer valid.")

        title = self._window_title(hwnd)
        class_name = self._class_name(hwnd)

        window_rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(window_rect)):
            raise AutomationError("Could not read target window bounds.")

        client_rect = RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(client_rect)):
            raise AutomationError("Could not read target window client bounds.")

        origin = POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            raise AutomationError("Could not convert target client coordinates.")

        return TargetWindowInfo(
            hwnd=int(hwnd),
            title=title,
            class_name=class_name,
            client_left=int(origin.x),
            client_top=int(origin.y),
            client_width=int(client_rect.right - client_rect.left),
            client_height=int(client_rect.bottom - client_rect.top),
            window_left=int(window_rect.left),
            window_top=int(window_rect.top),
            window_width=int(window_rect.right - window_rect.left),
            window_height=int(window_rect.bottom - window_rect.top),
            dpi=self._window_dpi(hwnd),
        )

    def client_to_screen(
        self, target: TargetWindowInfo, x: int, y: int
    ) -> Tuple[int, int]:
        if not target.contains_client_point(x, y):
            raise AutomationError(
                f"Point x={x}, y={y} is outside target client size "
                f"{target.client_width}x{target.client_height}."
            )
        return target.client_left + x, target.client_top + y

    def screen_to_client(
        self, target: TargetWindowInfo, screen_x: int, screen_y: int
    ) -> Tuple[int, int]:
        return screen_x - target.client_left, screen_y - target.client_top

    def set_foreground(self, target: TargetWindowInfo) -> None:
        user32.SetForegroundWindow(target.hwnd)

    def is_foreground(self, target: TargetWindowInfo) -> bool:
        return int(user32.GetForegroundWindow() or 0) == int(target.hwnd)

    def capture_next_click(
        self,
        target_data: Dict[str, Any],
        expected_size: Optional[Dict[str, int]],
        timeout_seconds: float = 15.0,
    ) -> Tuple[int, int]:
        target = self.require_ready(target_data, expected_size)
        deadline = time.monotonic() + timeout_seconds

        while user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
            if time.monotonic() > deadline:
                raise AutomationError("Timed out waiting for mouse button release.")
            time.sleep(0.02)

        while time.monotonic() <= deadline:
            if user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
                point = POINT()
                if not user32.GetCursorPos(ctypes.byref(point)):
                    raise AutomationError("Could not read mouse position.")
                current = self.require_ready(target_data, expected_size)
                x, y = self.screen_to_client(current, int(point.x), int(point.y))
                if current.contains_client_point(x, y):
                    return x, y
                raise AutomationError("The click was outside the target window.")
            time.sleep(0.02)

        raise AutomationError("Timed out waiting for a click in the target window.")

    def _target_matches(
        self, info: TargetWindowInfo, title: str, class_name: str
    ) -> bool:
        title_ok = not title or info.title == title
        class_ok = not class_name or info.class_name == class_name
        return title_ok and class_ok

    def _window_title(self, hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _class_name(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value

    def _window_dpi(self, hwnd: int) -> Optional[int]:
        try:
            get_dpi_for_window = user32.GetDpiForWindow
            get_dpi_for_window.argtypes = [wintypes.HWND]
            get_dpi_for_window.restype = wintypes.UINT
            return int(get_dpi_for_window(hwnd))
        except AttributeError:
            return None


class InputController:
    BUTTON_FLAGS = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }

    NAMED_KEYS: Dict[str, int] = {
        "backspace": 0x08,
        "tab": 0x09,
        "enter": 0x0D,
        "return": 0x0D,
        "shift": 0x10,
        "ctrl": 0x11,
        "control": 0x11,
        "alt": 0x12,
        "pause": 0x13,
        "capslock": 0x14,
        "esc": 0x1B,
        "escape": 0x1B,
        "space": 0x20,
        "pageup": 0x21,
        "pagedown": 0x22,
        "end": 0x23,
        "home": 0x24,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "insert": 0x2D,
        "delete": 0x2E,
    }

    def __init__(self, window_manager: WindowManager) -> None:
        self.window_manager = window_manager

    def click(
        self,
        target: TargetWindowInfo,
        x: int,
        y: int,
        button: str = "left",
        click_count: int = 1,
    ) -> None:
        screen_x, screen_y = self.window_manager.client_to_screen(target, int(x), int(y))
        down_flag, up_flag = self.BUTTON_FLAGS.get(str(button).lower(), self.BUTTON_FLAGS["left"])
        self.window_manager.set_foreground(target)
        time.sleep(0.03)
        if not user32.SetCursorPos(screen_x, screen_y):
            raise AutomationError("Could not move the mouse cursor.")
        for _ in range(max(1, int(click_count))):
            user32.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.03)
            user32.mouse_event(up_flag, 0, 0, 0, 0)
            time.sleep(0.05)

    def move_mouse(
        self,
        target: TargetWindowInfo,
        x: int,
        y: int,
        duration_ms: int = 150,
        stop_check: Optional[Callable[[], None]] = None,
    ) -> None:
        screen_x, screen_y = self.window_manager.client_to_screen(target, int(x), int(y))
        duration_seconds = max(0, int(duration_ms)) / 1000
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise AutomationError("Could not read the current mouse position.")

        start_x = int(point.x)
        start_y = int(point.y)
        if duration_seconds <= 0:
            if stop_check:
                stop_check()
            if not user32.SetCursorPos(screen_x, screen_y):
                raise AutomationError("Could not move the mouse cursor.")
            return

        started = time.monotonic()
        while True:
            if stop_check:
                stop_check()
            progress = min(1.0, (time.monotonic() - started) / duration_seconds)
            current_x = round(start_x + (screen_x - start_x) * progress)
            current_y = round(start_y + (screen_y - start_y) * progress)
            if not user32.SetCursorPos(current_x, current_y):
                raise AutomationError("Could not move the mouse cursor.")
            if progress >= 1.0:
                return
            time.sleep(min(0.01, duration_seconds * (1.0 - progress)))

    def key_press(self, target: TargetWindowInfo, key: str, press_count: int = 1) -> None:
        vk, modifiers = self._key_to_vk(key)
        self.window_manager.set_foreground(target)
        time.sleep(0.03)
        for _ in range(max(1, int(press_count))):
            for modifier_vk in modifiers:
                self._key_down(modifier_vk)
            self._key_down(vk)
            time.sleep(0.025)
            self._key_up(vk)
            for modifier_vk in reversed(modifiers):
                self._key_up(modifier_vk)
            time.sleep(0.05)

    def _key_to_vk(self, key: str) -> Tuple[int, List[int]]:
        text = str(key or "").strip()
        if not text:
            raise AutomationError("Key press block has an empty key.")

        lowered = text.lower().replace(" ", "")
        if lowered in self.NAMED_KEYS:
            return self.NAMED_KEYS[lowered], []
        if lowered.startswith("f") and lowered[1:].isdigit():
            number = int(lowered[1:])
            if 1 <= number <= 24:
                return 0x70 + number - 1, []
        if len(text) == 1:
            result = user32.VkKeyScanW(text)
            if result == -1:
                raise AutomationError(f"Unsupported key: {key}")
            vk = result & 0xFF
            shift_state = (result >> 8) & 0xFF
            modifiers: List[int] = []
            if shift_state & 1:
                modifiers.append(0x10)
            if shift_state & 2:
                modifiers.append(0x11)
            if shift_state & 4:
                modifiers.append(0x12)
            return vk, modifiers
        raise AutomationError(f"Unsupported key: {key}")

    def _key_down(self, vk: int) -> None:
        scan = user32.MapVirtualKeyW(vk, 0)
        user32.keybd_event(vk, scan, 0, 0)

    def _key_up(self, vk: int) -> None:
        scan = user32.MapVirtualKeyW(vk, 0)
        user32.keybd_event(vk, scan, KEYEVENTF_KEYUP, 0)


class _LowLevelHookMonitor:
    def __init__(self, hook_type: int) -> None:
        self.hook_type = hook_type
        self.thread: Optional[threading.Thread] = None
        self.thread_id = 0
        self.stop_event = threading.Event()
        self.hook: Optional[int] = None
        self._hook_proc: Optional[HOOKPROC] = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._message_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        if self.thread:
            self.thread.join(timeout=1.0)

    def _message_loop(self) -> None:
        self.thread_id = int(kernel32.GetCurrentThreadId())
        self._hook_proc = HOOKPROC(self._handle_hook)
        module = kernel32.GetModuleHandleW(None)
        self.hook = user32.SetWindowsHookExW(
            self.hook_type, self._hook_proc, module, 0
        )
        if not self.hook:
            return
        try:
            msg = MSG()
            while not self.stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or msg.message == WM_QUIT:
                    break
        finally:
            user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
            self._hook_proc = None

    def _handle_hook(self, n_code: int, w_param: int, l_param: int) -> int:
        return user32.CallNextHookEx(self.hook, n_code, w_param, l_param)


class UserKeyboardMonitor(_LowLevelHookMonitor):
    def __init__(self, callback: Callable[[int], None]) -> None:
        super().__init__(WH_KEYBOARD_LL)
        self.callback = callback

    def _handle_hook(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code == HC_ACTION and int(w_param) in (WM_KEYDOWN, WM_SYSKEYDOWN):
            event = ctypes.cast(
                l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)
            ).contents
            if not event.flags & LLKHF_INJECTED:
                self.callback(int(event.vkCode))
        return user32.CallNextHookEx(self.hook, n_code, w_param, l_param)


class UserMouseMonitor(_LowLevelHookMonitor):
    DOWN_MESSAGES = {
        WM_LBUTTONDOWN: "left",
        WM_RBUTTONDOWN: "right",
        WM_MBUTTONDOWN: "middle",
    }

    def __init__(self, callback: Callable[[int, int, str], None]) -> None:
        super().__init__(WH_MOUSE_LL)
        self.callback = callback

    def _handle_hook(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code == HC_ACTION and int(w_param) in self.DOWN_MESSAGES:
            event = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not event.flags & LLMHF_INJECTED:
                self.callback(
                    int(event.pt.x),
                    int(event.pt.y),
                    self.DOWN_MESSAGES[int(w_param)],
                )
        return user32.CallNextHookEx(self.hook, n_code, w_param, l_param)


class GlobalHotkey:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.thread: Optional[threading.Thread] = None
        self.thread_id = 0
        self.stop_event = threading.Event()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._message_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        if self.thread:
            self.thread.join(timeout=1.0)

    def _message_loop(self) -> None:
        self.thread_id = int(kernel32.GetCurrentThreadId())
        if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT, VK_Q):
            return
        try:
            msg = MSG()
            while not self.stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or msg.message == WM_QUIT:
                    break
                if msg.message == WM_HOTKEY and int(msg.wParam) == HOTKEY_ID:
                    self.callback()
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)


def format_window(info: TargetWindowInfo) -> str:
    return f"{info.title} [{info.client_width}x{info.client_height}]"


def vk_code_to_key(vk_code: int) -> Optional[str]:
    vk = int(vk_code)
    named = {
        0x08: "backspace",
        0x09: "tab",
        0x0D: "enter",
        0x1B: "escape",
        0x20: "space",
        0x21: "pageup",
        0x22: "pagedown",
        0x23: "end",
        0x24: "home",
        0x25: "left",
        0x26: "up",
        0x27: "right",
        0x28: "down",
        0x2D: "insert",
        0x2E: "delete",
        0xBA: ";",
        0xBB: "=",
        0xBC: ",",
        0xBD: "-",
        0xBE: ".",
        0xBF: "/",
        0xC0: "`",
        0xDB: "[",
        0xDC: "\\",
        0xDD: "]",
        0xDE: "'",
    }
    if vk in named:
        return named[vk]
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    if 0x70 <= vk <= 0x87:
        return f"f{vk - 0x70 + 1}"
    return None
