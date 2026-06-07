from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import cv2
import numpy as np

from .models import (
    color_to_hex,
    color_to_rgb_text,
    normalize_sampling_mode,
    parse_color,
    required_tolerance,
    sampling_mode_kind,
    sampling_mode_size,
)
from .vision_backend import CapturedFrame, ScreenAnalysisBackend
from .win32_automation import TargetWindowInfo, WindowManager


@dataclass
class PixelSampleResult:
    block_type: str
    target_title: str
    relative_x: int
    relative_y: int
    screen_x: int
    screen_y: int
    sampling_mode: str
    sample_size: int
    sample_count: int
    sampled_rgb: Tuple[int, int, int]
    expected_rgb: Optional[Tuple[int, int, int]]
    configured_tolerance: Optional[int]
    required_tolerance: Optional[int]
    matched: Optional[bool]
    capture: CapturedFrame
    debug_capture_path: Optional[Path] = None
    closest_offset: Optional[Tuple[int, int]] = None
    closest_screen: Optional[Tuple[int, int]] = None

    def sampled_label(self) -> str:
        if sampling_mode_kind(self.sampling_mode) == "closest":
            return "Closest"
        if sampling_mode_kind(self.sampling_mode) == "average":
            return "Sampled"
        return "Actual"

    def sampled_text(self) -> str:
        return f"{color_to_hex(self.sampled_rgb)} {color_to_rgb_text(self.sampled_rgb)}"


def sample_pixel_for_params(
    window_manager: WindowManager,
    screen_analysis: ScreenAnalysisBackend,
    target: TargetWindowInfo,
    x: int,
    y: int,
    params: dict[str, Any],
    block_type: str = "",
) -> PixelSampleResult:
    mode = normalize_sampling_mode(params.get("sampling_mode"))
    sample_size = sampling_mode_size(mode)
    kind = sampling_mode_kind(mode)
    center_screen_x, center_screen_y = window_manager.client_to_screen(target, x, y)
    capture = screen_analysis.capture_pixel_area(target, x, y, sample_size)
    rgb = capture.rgb
    center_local_x = x - capture.relative_left
    center_local_y = y - capture.relative_top

    expected_rgb: Optional[Tuple[int, int, int]] = None
    configured_tolerance: Optional[int] = None
    required: Optional[int] = None
    matched: Optional[bool] = None
    expected_value = params.get("expected_color")
    if expected_value not in ("", None):
        expected_rgb = parse_color(expected_value)
        configured_tolerance = max(0, int(params.get("tolerance", 0) or 0))

    closest_offset: Optional[Tuple[int, int]] = None
    closest_screen: Optional[Tuple[int, int]] = None
    if kind == "average":
        mean = cv2.mean(rgb)[:3]
        sampled_rgb = tuple(int(round(value)) for value in mean)
    elif kind == "closest" and expected_rgb is not None:
        expected = np.array(expected_rgb, dtype=np.int16)
        differences = np.max(np.abs(rgb.astype(np.int16) - expected), axis=2)
        local_y, local_x = np.unravel_index(int(np.argmin(differences)), differences.shape)
        sampled_rgb = tuple(int(value) for value in rgb[local_y, local_x])
        closest_offset = (int(local_x - center_local_x), int(local_y - center_local_y))
        closest_screen = (
            capture.screen_left + int(local_x),
            capture.screen_top + int(local_y),
        )
    else:
        sampled_rgb = tuple(
            int(value) for value in rgb[center_local_y, center_local_x]
        )

    if expected_rgb is not None and configured_tolerance is not None:
        required = required_tolerance(sampled_rgb, expected_rgb)
        matched = required <= configured_tolerance

    return PixelSampleResult(
        block_type=block_type,
        target_title=target.title,
        relative_x=x,
        relative_y=y,
        screen_x=center_screen_x,
        screen_y=center_screen_y,
        sampling_mode=mode,
        sample_size=sample_size,
        sample_count=int(rgb.shape[0] * rgb.shape[1]),
        sampled_rgb=sampled_rgb,
        expected_rgb=expected_rgb,
        configured_tolerance=configured_tolerance,
        required_tolerance=required,
        matched=matched,
        capture=capture,
        closest_offset=closest_offset,
        closest_screen=closest_screen,
    )
