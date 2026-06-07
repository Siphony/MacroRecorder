from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import cv2
import numpy as np

from .models import (
    REGION_MODE_EXPECTED,
    REGION_MODE_GREEN,
    REGION_MODE_HSV,
    color_to_hex,
    color_to_rgb_text,
    normalize_region,
    normalize_region_detection_mode,
    parse_color,
    required_tolerance,
)
from .vision_backend import CapturedFrame, ScreenAnalysisBackend
from .win32_automation import TargetWindowInfo, WindowManager


LOW_SATURATION_THRESHOLD = 51
HIGH_SATURATION_THRESHOLD = 128
COLOR_BUCKET_SIZE = 32
TOP_COLOR_BUCKET_COUNT = 5


@dataclass
class RegionAnalysis:
    detection_mode: str
    expected_rgb: Optional[Tuple[int, int, int]]
    tolerance: Optional[int]
    expected_lower_rgb: Optional[Tuple[int, int, int]]
    expected_upper_rgb: Optional[Tuple[int, int, int]]
    green_strength: int
    minimum_green: int
    hsv_hue_min: int
    hsv_hue_max: int
    hsv_min_saturation: int
    hsv_min_value: int
    sampled_pixels: int
    matching_pixels: int
    actual_match_percent: float
    expected_match_percent: float
    rgb_green_percent: float
    hsv_green_pixels: int
    hsv_green_percent: float
    average_rgb: Tuple[int, int, int]
    min_rgb: Tuple[int, int, int]
    max_rgb: Tuple[int, int, int]
    average_hsv: Tuple[float, float, float]
    min_hsv: Tuple[int, int, int]
    max_hsv: Tuple[int, int, int]
    low_saturation_pixels: int
    low_saturation_percent: float
    high_saturation_pixels: int
    high_saturation_percent: float
    top_color_buckets: Tuple[Tuple[Tuple[int, int, int], int, float], ...]


@dataclass
class RegionCheckResult:
    block_type: str
    target_title: str
    left: int
    top: int
    right: int
    bottom: int
    window_left: int
    window_top: int
    window_width: int
    window_height: int
    client_left: int
    client_top: int
    client_width: int
    client_height: int
    dpi: Optional[int]
    screen_left: int
    screen_top: int
    screen_right: int
    screen_bottom: int
    width: int
    height: int
    detection_mode: str
    expected_rgb: Optional[Tuple[int, int, int]]
    tolerance: Optional[int]
    expected_lower_rgb: Optional[Tuple[int, int, int]]
    expected_upper_rgb: Optional[Tuple[int, int, int]]
    minimum_match_percent: float
    actual_match_percent: float
    expected_match_percent: float
    rgb_green_percent: float
    matching_pixels: int
    sampled_pixels: int
    expected_sampled_pixels: int
    sample_step: int
    average_rgb: Tuple[int, int, int]
    min_rgb: Tuple[int, int, int]
    max_rgb: Tuple[int, int, int]
    average_hsv: Tuple[float, float, float]
    min_hsv: Tuple[int, int, int]
    max_hsv: Tuple[int, int, int]
    average_required_tolerance: Optional[int]
    elapsed_ms: float
    green_strength: int
    minimum_green: int
    hsv_hue_min: int
    hsv_hue_max: int
    hsv_min_saturation: int
    hsv_min_value: int
    hsv_green_pixels: int
    hsv_green_percent: float
    low_saturation_pixels: int
    low_saturation_percent: float
    high_saturation_pixels: int
    high_saturation_percent: float
    top_color_buckets: Tuple[Tuple[Tuple[int, int, int], int, float], ...]
    capture: CapturedFrame
    matched: bool
    debug_capture_path: Optional[Path] = None

    def result_text(self) -> str:
        return "MATCH" if self.matched else "NO MATCH"

    def short_probe_text(self) -> str:
        outcome = "PASS" if self.matched else "FAIL"
        return (
            f"Last probe: {self.actual_match_percent:.1f}% match - "
            f"{outcome} ({self.elapsed_ms:.0f} ms)"
        )


def check_region_for_params(
    window_manager: WindowManager,
    screen_analysis: ScreenAnalysisBackend,
    target: TargetWindowInfo,
    params: dict[str, Any],
    block_type: str = "",
) -> RegionCheckResult:
    left, top, right, bottom = normalize_region(
        params.get("x1", 0),
        params.get("y1", 0),
        params.get("x2", 0),
        params.get("y2", 0),
    )
    minimum = float(params.get("minimum_match_percent", 0) or 0)
    step = max(1, int(params.get("sample_step", 1) or 1))
    screen_left, screen_top = window_manager.client_to_screen(target, left, top)
    screen_right, screen_bottom = window_manager.client_to_screen(target, right, bottom)
    width = right - left + 1
    height = bottom - top + 1

    start = time.perf_counter()
    capture = screen_analysis.capture_target_region(target, left, top, right, bottom)
    analysis = analyse_region_bgr(capture.bgr, params, step)
    elapsed_ms = (time.perf_counter() - start) * 1000
    average_required = (
        required_tolerance(analysis.average_rgb, analysis.expected_rgb)
        if analysis.expected_rgb is not None
        else None
    )
    return RegionCheckResult(
        block_type=block_type,
        target_title=target.title,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        window_left=target.window_left,
        window_top=target.window_top,
        window_width=target.window_width,
        window_height=target.window_height,
        client_left=target.client_left,
        client_top=target.client_top,
        client_width=target.client_width,
        client_height=target.client_height,
        dpi=target.dpi,
        screen_left=screen_left,
        screen_top=screen_top,
        screen_right=screen_right,
        screen_bottom=screen_bottom,
        width=width,
        height=height,
        detection_mode=analysis.detection_mode,
        expected_rgb=analysis.expected_rgb,
        tolerance=analysis.tolerance,
        expected_lower_rgb=analysis.expected_lower_rgb,
        expected_upper_rgb=analysis.expected_upper_rgb,
        minimum_match_percent=minimum,
        actual_match_percent=analysis.actual_match_percent,
        expected_match_percent=analysis.expected_match_percent,
        rgb_green_percent=analysis.rgb_green_percent,
        matching_pixels=analysis.matching_pixels,
        sampled_pixels=analysis.sampled_pixels,
        expected_sampled_pixels=_expected_sample_count(width, height, step),
        sample_step=step,
        average_rgb=analysis.average_rgb,
        min_rgb=analysis.min_rgb,
        max_rgb=analysis.max_rgb,
        average_hsv=analysis.average_hsv,
        min_hsv=analysis.min_hsv,
        max_hsv=analysis.max_hsv,
        average_required_tolerance=average_required,
        elapsed_ms=elapsed_ms,
        green_strength=analysis.green_strength,
        minimum_green=analysis.minimum_green,
        hsv_hue_min=analysis.hsv_hue_min,
        hsv_hue_max=analysis.hsv_hue_max,
        hsv_min_saturation=analysis.hsv_min_saturation,
        hsv_min_value=analysis.hsv_min_value,
        hsv_green_pixels=analysis.hsv_green_pixels,
        hsv_green_percent=analysis.hsv_green_percent,
        low_saturation_pixels=analysis.low_saturation_pixels,
        low_saturation_percent=analysis.low_saturation_percent,
        high_saturation_pixels=analysis.high_saturation_pixels,
        high_saturation_percent=analysis.high_saturation_percent,
        top_color_buckets=analysis.top_color_buckets,
        capture=capture,
        matched=analysis.actual_match_percent >= minimum,
    )


def analyse_region_bgr(
    bgr: np.ndarray, params: dict[str, Any], sample_step: Optional[int] = None
) -> RegionAnalysis:
    if bgr is None or bgr.size == 0:
        raise ValueError("Captured image is empty.")
    step = max(1, int(sample_step or params.get("sample_step", 1) or 1))
    sampled_bgr = np.ascontiguousarray(bgr[::step, ::step])
    rgb = cv2.cvtColor(sampled_bgr, cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(sampled_bgr, cv2.COLOR_BGR2HSV)
    sampled_pixels = int(rgb.shape[0] * rgb.shape[1])

    expected_rgb = parse_color(params.get("expected_color", "#35C84A"))
    tolerance = max(0, min(255, int(params.get("tolerance", 40) or 0)))
    expected_array = np.array(expected_rgb, dtype=np.int16)
    lower_array = np.clip(expected_array - tolerance, 0, 255).astype(np.uint8)
    upper_array = np.clip(expected_array + tolerance, 0, 255).astype(np.uint8)
    expected_mask = cv2.inRange(rgb, lower_array, upper_array)

    green_strength = max(0, int(params.get("green_strength", 25) or 0))
    minimum_green = max(0, min(255, int(params.get("minimum_green", 80) or 0)))
    rgb16 = rgb.astype(np.int16)
    rgb_green_mask = (
        (rgb16[:, :, 1] >= rgb16[:, :, 0] + green_strength)
        & (rgb16[:, :, 1] >= rgb16[:, :, 2] + green_strength)
        & (rgb16[:, :, 1] >= minimum_green)
    ).astype(np.uint8) * 255

    hue_min, hue_max, saturation_min, value_min = opencv_hsv_thresholds(params)
    hsv_mask = _opencv_hsv_mask(hsv, hue_min, hue_max, saturation_min, value_min)

    expected_count = int(cv2.countNonZero(expected_mask))
    rgb_green_count = int(cv2.countNonZero(rgb_green_mask))
    hsv_green_count = int(cv2.countNonZero(hsv_mask))
    expected_percent = _percent(expected_count, sampled_pixels)
    rgb_green_percent = _percent(rgb_green_count, sampled_pixels)
    hsv_green_percent = _percent(hsv_green_count, sampled_pixels)

    mode = normalize_region_detection_mode(params.get("detection_mode"))
    if mode == REGION_MODE_EXPECTED:
        matching_pixels = expected_count
        actual_percent = expected_percent
    elif mode == REGION_MODE_HSV:
        matching_pixels = hsv_green_count
        actual_percent = hsv_green_percent
    else:
        mode = REGION_MODE_GREEN
        matching_pixels = rgb_green_count
        actual_percent = rgb_green_percent

    average_rgb = tuple(int(round(value)) for value in cv2.mean(rgb)[:3])
    min_rgb = tuple(int(value) for value in rgb.reshape(-1, 3).min(axis=0))
    max_rgb = tuple(int(value) for value in rgb.reshape(-1, 3).max(axis=0))
    average_hsv = tuple(float(value) for value in cv2.mean(hsv)[:3])
    min_hsv = tuple(int(value) for value in hsv.reshape(-1, 3).min(axis=0))
    max_hsv = tuple(int(value) for value in hsv.reshape(-1, 3).max(axis=0))
    low_saturation_count = int(np.count_nonzero(hsv[:, :, 1] < LOW_SATURATION_THRESHOLD))
    high_saturation_count = int(np.count_nonzero(hsv[:, :, 1] >= HIGH_SATURATION_THRESHOLD))

    return RegionAnalysis(
        detection_mode=mode,
        expected_rgb=expected_rgb,
        tolerance=tolerance,
        expected_lower_rgb=tuple(int(value) for value in lower_array),
        expected_upper_rgb=tuple(int(value) for value in upper_array),
        green_strength=green_strength,
        minimum_green=minimum_green,
        hsv_hue_min=hue_min,
        hsv_hue_max=hue_max,
        hsv_min_saturation=saturation_min,
        hsv_min_value=value_min,
        sampled_pixels=sampled_pixels,
        matching_pixels=matching_pixels,
        actual_match_percent=actual_percent,
        expected_match_percent=expected_percent,
        rgb_green_percent=rgb_green_percent,
        hsv_green_pixels=hsv_green_count,
        hsv_green_percent=hsv_green_percent,
        average_rgb=average_rgb,
        min_rgb=min_rgb,
        max_rgb=max_rgb,
        average_hsv=average_hsv,
        min_hsv=min_hsv,
        max_hsv=max_hsv,
        low_saturation_pixels=low_saturation_count,
        low_saturation_percent=_percent(low_saturation_count, sampled_pixels),
        high_saturation_pixels=high_saturation_count,
        high_saturation_percent=_percent(high_saturation_count, sampled_pixels),
        top_color_buckets=_top_colour_buckets(rgb),
    )


def opencv_hsv_thresholds(params: dict[str, Any]) -> Tuple[int, int, int, int]:
    hue_min = float(params.get("hsv_hue_min", 35) or 0)
    hue_max = float(params.get("hsv_hue_max", 85) or 0)
    saturation_min = float(params.get("hsv_min_saturation", 60) or 0)
    value_min = float(params.get("hsv_min_value", 80) or 0)
    # v1.4.1 stored hue as degrees and saturation/value as 0-1 fractions.
    if saturation_min <= 1 and value_min <= 1:
        hue_min /= 2
        hue_max /= 2
        saturation_min *= 255
        value_min *= 255
    return (
        max(0, min(179, int(round(hue_min)))),
        max(0, min(179, int(round(hue_max)))),
        max(0, min(255, int(round(saturation_min)))),
        max(0, min(255, int(round(value_min)))),
    )


def region_mode_details(result: RegionCheckResult) -> str:
    if result.detection_mode == REGION_MODE_EXPECTED and result.expected_rgb:
        return (
            "Mode: Expected Colour\n"
            f"Expected: {color_to_hex(result.expected_rgb)} {color_to_rgb_text(result.expected_rgb)}\n"
            f"Tolerance: {result.tolerance}\n"
            f"RGB bounds: {result.expected_lower_rgb} to {result.expected_upper_rgb}"
        )
    if result.detection_mode == REGION_MODE_HSV:
        return (
            "Mode: HSV Green\n"
            f"OpenCV HSV rule: H={result.hsv_hue_min}-{result.hsv_hue_max}, "
            f"S >= {result.hsv_min_saturation}, V >= {result.hsv_min_value}"
        )
    return (
        "Mode: Green Dominance\n"
        f"Green rule: G >= R + {result.green_strength}, "
        f"G >= B + {result.green_strength}, G >= {result.minimum_green}"
    )


def region_colour_diagnostics(result: RegionCheckResult) -> str:
    buckets = "; ".join(
        f"{color_to_hex(rgb)} {color_to_rgb_text(rgb)}: {count} ({percent:.1f}%)"
        for rgb, count, percent in result.top_color_buckets
    ) or "none"
    hue, saturation, value = result.average_hsv
    return (
        f"Classifier comparison: Expected={result.expected_match_percent:.1f}%, "
        f"RGB Green={result.rgb_green_percent:.1f}%, HSV Green={result.hsv_green_percent:.1f}%\n"
        f"Average HSV (OpenCV): H={hue:.1f}, S={saturation:.1f}, V={value:.1f}\n"
        f"Min HSV: {result.min_hsv}\n"
        f"Max HSV: {result.max_hsv}\n"
        f"Low saturation (< {LOW_SATURATION_THRESHOLD}): "
        f"{result.low_saturation_pixels} / {result.sampled_pixels} "
        f"({result.low_saturation_percent:.1f}%)\n"
        f"High saturation (>= {HIGH_SATURATION_THRESHOLD}): "
        f"{result.high_saturation_pixels} / {result.sampled_pixels} "
        f"({result.high_saturation_percent:.1f}%)\n"
        f"Top colour buckets: {buckets}"
    )


def _opencv_hsv_mask(
    hsv: np.ndarray, hue_min: int, hue_max: int, saturation_min: int, value_min: int
) -> np.ndarray:
    if hue_min <= hue_max:
        return cv2.inRange(
            hsv,
            np.array((hue_min, saturation_min, value_min), dtype=np.uint8),
            np.array((hue_max, 255, 255), dtype=np.uint8),
        )
    upper = cv2.inRange(
        hsv,
        np.array((0, saturation_min, value_min), dtype=np.uint8),
        np.array((hue_max, 255, 255), dtype=np.uint8),
    )
    lower = cv2.inRange(
        hsv,
        np.array((hue_min, saturation_min, value_min), dtype=np.uint8),
        np.array((179, 255, 255), dtype=np.uint8),
    )
    return cv2.bitwise_or(lower, upper)


def _top_colour_buckets(
    rgb: np.ndarray,
) -> Tuple[Tuple[Tuple[int, int, int], int, float], ...]:
    quantized = (
        (rgb.astype(np.uint16) // COLOR_BUCKET_SIZE) * COLOR_BUCKET_SIZE
        + COLOR_BUCKET_SIZE // 2
    )
    quantized = np.clip(quantized, 0, 255).astype(np.uint8).reshape(-1, 3)
    counts = Counter(tuple(int(value) for value in row) for row in quantized)
    total = int(quantized.shape[0])
    return tuple(
        (bucket, count, _percent(count, total))
        for bucket, count in counts.most_common(TOP_COLOR_BUCKET_COUNT)
    )


def _expected_sample_count(width: int, height: int, step: int) -> int:
    x_count = ((max(1, width) - 1) // step) + 1
    y_count = ((max(1, height) - 1) // step) + 1
    return x_count * y_count


def _percent(part: int, total: int) -> float:
    return (part / total * 100) if total else 0.0
