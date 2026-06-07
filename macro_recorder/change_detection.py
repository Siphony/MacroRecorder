from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .vision_backend import CapturedFrame


@dataclass(frozen=True)
class RegionChangeResult:
    changed_pixels: int
    sampled_pixels: int
    changed_percent: float
    pixel_change_threshold: int

    def changed_enough(self, required_percent: float) -> bool:
        return self.changed_percent >= float(required_percent)

    def stable_enough(self, maximum_percent: float) -> bool:
        return self.changed_percent <= float(maximum_percent)


def compare_captured_frames(
    before: CapturedFrame,
    after: CapturedFrame,
    pixel_change_threshold: int,
) -> RegionChangeResult:
    return compare_bgr_frames(before.bgr, after.bgr, pixel_change_threshold)


def compare_bgr_frames(
    before_bgr: np.ndarray,
    after_bgr: np.ndarray,
    pixel_change_threshold: int,
) -> RegionChangeResult:
    if before_bgr is None or after_bgr is None:
        raise ValueError("Captured frames are missing.")
    if before_bgr.size == 0 or after_bgr.size == 0:
        raise ValueError("Captured frames must not be empty.")
    if before_bgr.shape != after_bgr.shape:
        raise ValueError(
            "Captured frames must have matching dimensions "
            f"(before={before_bgr.shape}, after={after_bgr.shape})."
        )

    threshold = max(0, min(255, int(pixel_change_threshold or 0)))
    difference = cv2.absdiff(before_bgr, after_bgr)
    changed_mask = np.max(difference, axis=2) > threshold
    sampled_pixels = int(changed_mask.size)
    changed_pixels = int(np.count_nonzero(changed_mask))
    changed_percent = (
        changed_pixels / sampled_pixels * 100.0 if sampled_pixels else 0.0
    )
    return RegionChangeResult(
        changed_pixels=changed_pixels,
        sampled_pixels=sampled_pixels,
        changed_percent=changed_percent,
        pixel_change_threshold=threshold,
    )
