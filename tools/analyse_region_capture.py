from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macro_recorder.models import (  # noqa: E402
    REGION_MODE_EXPECTED,
    REGION_MODE_GREEN,
    REGION_MODE_HSV,
)
from macro_recorder.region_detection import analyse_region_bgr  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse a saved Macro Builder debug capture with the app's OpenCV logic."
    )
    parser.add_argument("image", type=Path)
    parser.add_argument(
        "--mode",
        choices=("expected", "rgb-green", "hsv-green"),
        default="hsv-green",
    )
    parser.add_argument("--expected", default="#35C84A")
    parser.add_argument("--tolerance", type=int, default=40)
    parser.add_argument("--hue-min", type=int, default=35)
    parser.add_argument("--hue-max", type=int, default=85)
    parser.add_argument("--saturation-min", type=int, default=60)
    parser.add_argument("--value-min", type=int, default=80)
    parser.add_argument("--green-strength", type=int, default=25)
    parser.add_argument("--minimum-green", type=int, default=80)
    parser.add_argument("--sample-step", type=int, default=1)
    args = parser.parse_args()

    bgr = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit(f"Could not read image: {args.image}")
    modes = {
        "expected": REGION_MODE_EXPECTED,
        "rgb-green": REGION_MODE_GREEN,
        "hsv-green": REGION_MODE_HSV,
    }
    params = {
        "detection_mode": modes[args.mode],
        "expected_color": args.expected,
        "tolerance": args.tolerance,
        "hsv_hue_min": args.hue_min,
        "hsv_hue_max": args.hue_max,
        "hsv_min_saturation": args.saturation_min,
        "hsv_min_value": args.value_min,
        "green_strength": args.green_strength,
        "minimum_green": args.minimum_green,
        "sample_step": args.sample_step,
    }
    result = analyse_region_bgr(bgr, params)
    print(f"Image: {args.image.resolve()}")
    print(f"Image size: {bgr.shape[1]}x{bgr.shape[0]}")
    print(f"Sample step: {args.sample_step}")
    print(f"Sampled pixels: {result.sampled_pixels}")
    print(f"Average RGB: {result.average_rgb}")
    print(f"Min RGB: {result.min_rgb}")
    print(f"Max RGB: {result.max_rgb}")
    print(f"Average HSV (OpenCV): {tuple(round(v, 1) for v in result.average_hsv)}")
    print(f"Min HSV: {result.min_hsv}")
    print(f"Max HSV: {result.max_hsv}")
    print(f"Expected colour match: {result.expected_match_percent:.2f}%")
    print(f"RGB green dominance: {result.rgb_green_percent:.2f}%")
    print(f"HSV green match: {result.hsv_green_percent:.2f}%")
    print(
        "HSV thresholds: "
        f"H={result.hsv_hue_min}-{result.hsv_hue_max}, "
        f"S>={result.hsv_min_saturation}, V>={result.hsv_min_value}"
    )
    print(f"Selected mode result: {result.actual_match_percent:.2f}%")


if __name__ == "__main__":
    main()
