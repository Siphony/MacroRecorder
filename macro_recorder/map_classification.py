from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np


SUPPORTED_REFERENCE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


class MapClassificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MapMatch:
    map_id: str
    reference_path: Path
    score: float
    location: Tuple[int, int]
    scale: float
    reference_size: Tuple[int, int]
    template_size: Tuple[int, int]


@dataclass(frozen=True)
class MapClassificationResult:
    matches: Tuple[MapMatch, ...]
    warnings: Tuple[str, ...]
    runtime_size: Tuple[int, int]
    reference_count: int
    loaded_count: int

    @property
    def best(self) -> Optional[MapMatch]:
        return self.matches[0] if self.matches else None

    @property
    def second(self) -> Optional[MapMatch]:
        return self.matches[1] if len(self.matches) > 1 else None

    @property
    def margin(self) -> float:
        if not self.best:
            return 0.0
        if not self.second:
            return 1.0
        return self.best.score - self.second.score

    def passes(self, minimum_best_score: float, minimum_margin: float) -> bool:
        return bool(
            self.best
            and self.best.score >= float(minimum_best_score)
            and self.margin >= float(minimum_margin)
        )


def classify_map_patch(
    runtime_bgr: np.ndarray,
    reference_folder: Path | str,
    *,
    enable_multi_scale: bool = True,
    scale_min: float = 0.90,
    scale_max: float = 1.10,
    scale_step: float = 0.05,
    stop_check: Optional[Callable[[], None]] = None,
) -> MapClassificationResult:
    runtime = _validate_bgr(runtime_bgr, "Runtime patch")
    if float(np.std(runtime)) < 2.0:
        raise MapClassificationError(
            "Runtime patch has too little visual detail for reliable classification."
        )
    folder = Path(reference_folder)
    if not folder.is_dir():
        raise MapClassificationError(f"Reference folder was not found: {folder}")

    reference_paths = sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_REFERENCE_EXTENSIONS
        ),
        key=lambda path: path.name.casefold(),
    )
    if not reference_paths:
        raise MapClassificationError(
            f"No PNG/JPG map reference images were found in: {folder}"
        )

    scales = _scale_values(enable_multi_scale, scale_min, scale_max, scale_step)
    matches: List[MapMatch] = []
    warnings: List[str] = []
    loaded_count = 0
    for path in reference_paths:
        if stop_check:
            stop_check()
        reference = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if reference is None or reference.size == 0:
            warnings.append(f"Could not load reference image: {path}")
            continue
        loaded_count += 1
        match = _match_reference(runtime, reference, path, scales, stop_check)
        if match:
            matches.append(match)
        else:
            warnings.append(
                f"Skipped reference smaller than every tested runtime scale: {path}"
            )

    if not matches:
        details = f" {' '.join(warnings)}" if warnings else ""
        raise MapClassificationError(
            "No valid map references could be matched against the runtime patch."
            + details
        )
    matches = _best_match_per_map_id(matches, warnings)
    matches.sort(key=lambda item: item.score, reverse=True)
    return MapClassificationResult(
        matches=tuple(matches),
        warnings=tuple(warnings),
        runtime_size=(int(runtime.shape[1]), int(runtime.shape[0])),
        reference_count=len(reference_paths),
        loaded_count=loaded_count,
    )


def save_map_reference(
    bgr: np.ndarray, reference_folder: Path | str, map_id: str
) -> Path:
    image = _validate_bgr(bgr, "Reference capture")
    safe_id = normalize_map_id(map_id)
    if not safe_id:
        raise MapClassificationError("Map ID cannot be empty.")
    folder = Path(reference_folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe_id}.png"
    if path.exists():
        raise FileExistsError(f"Reference image already exists: {path}")
    if not cv2.imwrite(str(path), image):
        raise MapClassificationError(f"Could not save map reference image: {path}")
    return path.resolve()


def normalize_map_id(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return text.strip("._-")


def format_classification_log(
    result: MapClassificationResult,
    *,
    heading: str,
    reference_folder: Path | str,
    region: Sequence[int],
    minimum_best_score: float,
    minimum_margin: float,
    top_count: int = 3,
) -> str:
    left, top, right, bottom = region
    best = result.best
    lines = [
        f"[{heading}]",
        f"Runtime Region: left={left} top={top} right={right} bottom={bottom}",
        f"Runtime Patch Size: {result.runtime_size[0]}x{result.runtime_size[1]}",
        f"Reference Folder: {reference_folder}",
        f"References Found: {result.reference_count}",
        f"References Loaded: {result.loaded_count}",
        f"Valid Matches: {len(result.matches)}",
        f"Minimum Best Score: {float(minimum_best_score):.3f}",
        f"Minimum Margin: {float(minimum_margin):.3f}",
    ]
    for index, match in enumerate(result.matches[: max(1, int(top_count))], start=1):
        lines.append(
            f"Top {index}: {match.map_id} score={match.score:.4f} "
            f"location=({match.location[0]}, {match.location[1]}) "
            f"scale={match.scale:.3f} "
            f"template={match.template_size[0]}x{match.template_size[1]}"
        )
    lines.extend(
        [
            f"Best Score: {best.score:.4f}" if best else "Best Score: none",
            f"Second Score: {result.second.score:.4f}"
            if result.second
            else "Second Score: none",
            f"Margin: {result.margin:.4f}",
            "Result: PASS"
            if result.passes(minimum_best_score, minimum_margin)
            else "Result: LOW CONFIDENCE",
        ]
    )
    lines.extend(f"Warning: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def _match_reference(
    runtime: np.ndarray,
    reference: np.ndarray,
    reference_path: Path,
    scales: Iterable[float],
    stop_check: Optional[Callable[[], None]],
) -> Optional[MapMatch]:
    best: Optional[MapMatch] = None
    ref_height, ref_width = reference.shape[:2]
    for scale in scales:
        if stop_check:
            stop_check()
        template = _scaled_image(runtime, scale)
        height, width = template.shape[:2]
        if width > ref_width or height > ref_height:
            continue
        scores = cv2.matchTemplate(reference, template, cv2.TM_CCOEFF_NORMED)
        scores = np.nan_to_num(scores, nan=-1.0, posinf=1.0, neginf=-1.0)
        _, score, _, location = cv2.minMaxLoc(scores)
        candidate = MapMatch(
            map_id=reference_path.stem,
            reference_path=reference_path.resolve(),
            score=float(score),
            location=(int(location[0]), int(location[1])),
            scale=float(scale),
            reference_size=(int(ref_width), int(ref_height)),
            template_size=(int(width), int(height)),
        )
        if best is None or candidate.score > best.score:
            best = candidate
    return best


def _best_match_per_map_id(
    matches: Iterable[MapMatch], warnings: List[str]
) -> List[MapMatch]:
    by_id: dict[str, MapMatch] = {}
    duplicate_ids: set[str] = set()
    for match in matches:
        key = match.map_id.casefold()
        existing = by_id.get(key)
        if existing:
            duplicate_ids.add(match.map_id)
        if existing is None or match.score > existing.score:
            by_id[key] = match
    for map_id in sorted(duplicate_ids, key=str.casefold):
        warnings.append(
            f"Multiple references use map ID '{map_id}'; only its best score was ranked."
        )
    return list(by_id.values())


def _scale_values(
    enabled: bool, scale_min: float, scale_max: float, scale_step: float
) -> Tuple[float, ...]:
    if not enabled:
        return (1.0,)
    minimum = max(0.05, float(scale_min))
    maximum = max(minimum, float(scale_max))
    step = max(0.01, float(scale_step))
    values: List[float] = []
    value = minimum
    while value <= maximum + step / 2:
        values.append(round(value, 6))
        value += step
    if not values:
        values.append(1.0)
    return tuple(values)


def _scaled_image(image: np.ndarray, scale: float) -> np.ndarray:
    if abs(float(scale) - 1.0) < 1e-9:
        return image
    width = max(1, round(image.shape[1] * float(scale)))
    height = max(1, round(image.shape[0] * float(scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    return cv2.resize(image, (width, height), interpolation=interpolation)


def _validate_bgr(image: np.ndarray, label: str) -> np.ndarray:
    if not isinstance(image, np.ndarray) or image.size == 0:
        raise MapClassificationError(f"{label} is empty.")
    if image.ndim != 3 or image.shape[2] != 3:
        raise MapClassificationError(f"{label} must be an OpenCV BGR image.")
    return np.ascontiguousarray(image)
