from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import cv2
import mss
import numpy as np

from .win32_automation import AutomationError, TargetWindowInfo, WindowManager


@dataclass
class CapturedFrame:
    bgr: np.ndarray
    screen_left: int
    screen_top: int
    relative_left: int
    relative_top: int

    @property
    def width(self) -> int:
        return int(self.bgr.shape[1])

    @property
    def height(self) -> int:
        return int(self.bgr.shape[0])

    @property
    def rgb(self) -> np.ndarray:
        return cv2.cvtColor(self.bgr, cv2.COLOR_BGR2RGB)


class ScreenAnalysisBackend:
    """MSS screen capture plus OpenCV/NumPy image handling."""

    def __init__(
        self,
        window_manager: WindowManager,
        debug_dir: Path | str = "debug_captures",
    ) -> None:
        self.window_manager = window_manager
        self.debug_dir = Path(debug_dir)
        self.debug_captures_enabled = False
        self._capture_lock = threading.Lock()

    def get_pixel(self, target: TargetWindowInfo, x: int, y: int) -> Tuple[int, int, int]:
        frame = self.capture_target_region(target, int(x), int(y), int(x), int(y))
        blue, green, red = (int(value) for value in frame.bgr[0, 0])
        return red, green, blue

    def capture_pixel_area(
        self, target: TargetWindowInfo, x: int, y: int, sample_size: int
    ) -> CapturedFrame:
        sample_size = max(1, int(sample_size))
        if sample_size % 2 == 0:
            sample_size += 1
        radius = sample_size // 2
        left = max(0, int(x) - radius)
        top = max(0, int(y) - radius)
        right = min(target.client_width - 1, int(x) + radius)
        bottom = min(target.client_height - 1, int(y) + radius)
        return self.capture_target_region(target, left, top, right, bottom)

    def capture_target_region(
        self,
        target: TargetWindowInfo,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> CapturedFrame:
        left, top, right, bottom = _normalize_rect(left, top, right, bottom)
        screen_left, screen_top = self.window_manager.client_to_screen(target, left, top)
        screen_right, screen_bottom = self.window_manager.client_to_screen(
            target, right, bottom
        )
        width = screen_right - screen_left + 1
        height = screen_bottom - screen_top + 1
        return self.capture_screen_region(
            screen_left,
            screen_top,
            width,
            height,
            relative_left=left,
            relative_top=top,
        )

    def capture_screen_region(
        self,
        screen_left: int,
        screen_top: int,
        width: int,
        height: int,
        relative_left: int = 0,
        relative_top: int = 0,
    ) -> CapturedFrame:
        width = int(width)
        height = int(height)
        if width <= 0 or height <= 0:
            raise AutomationError("Capture region must have positive size.")
        monitor = {
            "left": int(screen_left),
            "top": int(screen_top),
            "width": width,
            "height": height,
        }
        try:
            with self._capture_lock:
                with mss.mss() as capture:
                    shot = capture.grab(monitor)
                    bgra = np.asarray(shot, dtype=np.uint8)
        except Exception as exc:
            raise AutomationError(f"MSS screen capture failed: {exc}") from exc
        if bgra.size == 0 or bgra.shape[:2] != (height, width):
            raise AutomationError("MSS returned an empty or unexpected-size capture.")
        bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        return CapturedFrame(
            bgr=np.ascontiguousarray(bgr),
            screen_left=int(screen_left),
            screen_top=int(screen_top),
            relative_left=int(relative_left),
            relative_top=int(relative_top),
        )

    def save_debug_capture(
        self,
        frame: CapturedFrame,
        label: str,
        result: str,
        force: bool = False,
    ) -> Optional[Path]:
        if not force and not self.debug_captures_enabled:
            return None
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")[:-3]
        safe_label = _safe_filename(label)
        safe_result = _safe_filename(result)
        path = self.debug_dir / f"{timestamp}_{safe_label}_{safe_result}.png"
        if not cv2.imwrite(str(path), frame.bgr):
            raise AutomationError(f"Could not save debug capture: {path}")
        return path.resolve()


def _normalize_rect(left: int, top: int, right: int, bottom: int) -> Tuple[int, int, int, int]:
    left, top, right, bottom = int(left), int(top), int(right), int(bottom)
    return min(left, right), min(top, bottom), max(left, right), max(top, bottom)


def _safe_filename(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return text.strip("._-")[:80] or "capture"
