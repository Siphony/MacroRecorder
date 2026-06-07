from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4


SCHEMA_VERSION = 1

PIXEL_SAMPLING_SINGLE = "Single Pixel"
PIXEL_SAMPLING_AVERAGE_3 = "Average 3x3"
PIXEL_SAMPLING_AVERAGE_5 = "Average 5x5"
PIXEL_SAMPLING_CLOSEST_3 = "Closest Match 3x3"
PIXEL_SAMPLING_CLOSEST_5 = "Closest Match 5x5"
PIXEL_SAMPLING_MODES = [
    PIXEL_SAMPLING_SINGLE,
    PIXEL_SAMPLING_AVERAGE_3,
    PIXEL_SAMPLING_AVERAGE_5,
    PIXEL_SAMPLING_CLOSEST_3,
    PIXEL_SAMPLING_CLOSEST_5,
]
REGION_MODE_EXPECTED = "Expected Colour Match"
REGION_MODE_GREEN = "Green Dominance"
REGION_MODE_HSV = "HSV Green"
REGION_DETECTION_MODES = [REGION_MODE_GREEN, REGION_MODE_HSV, REGION_MODE_EXPECTED]


def new_id() -> str:
    return uuid4().hex


BLOCK_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "click": {
        "x": 0,
        "y": 0,
        "button": "left",
        "click_count": 1,
        "delay_after_ms": 300,
    },
    "key_press": {
        "key": "space",
        "press_count": 1,
        "delay_after_ms": 300,
    },
    "wait": {
        "duration_ms": 500,
    },
    "wait_pixel": {
        "x": 0,
        "y": 0,
        "expected_color": "#00FF00",
        "tolerance": 10,
        "check_interval_ms": 100,
        "timeout_ms": 50000,
        "timeout_behavior": "fail",
        "sampling_mode": PIXEL_SAMPLING_SINGLE,
        "after_success_delay_ms": 0,
    },
    "if_pixel": {
        "x": 0,
        "y": 0,
        "expected_color": "#00FF00",
        "tolerance": 10,
        "sampling_mode": PIXEL_SAMPLING_SINGLE,
    },
    "wait_region": {
        "x1": 0,
        "y1": 0,
        "x2": 100,
        "y2": 50,
        "detection_mode": REGION_MODE_GREEN,
        "expected_color": "#35C84A",
        "tolerance": 40,
        "minimum_match_percent": 15,
        "green_strength": 25,
        "minimum_green": 80,
        "hsv_hue_min": 35,
        "hsv_hue_max": 85,
        "hsv_min_saturation": 60,
        "hsv_min_value": 80,
        "sample_step": 2,
        "check_interval_ms": 100,
        "timeout_ms": 50000,
        "timeout_behavior": "fail",
        "after_success_delay_ms": 0,
    },
    "if_region": {
        "x1": 0,
        "y1": 0,
        "x2": 100,
        "y2": 50,
        "detection_mode": REGION_MODE_GREEN,
        "expected_color": "#35C84A",
        "tolerance": 40,
        "minimum_match_percent": 15,
        "green_strength": 25,
        "minimum_green": 80,
        "hsv_hue_min": 35,
        "hsv_hue_max": 85,
        "hsv_min_saturation": 60,
        "hsv_min_value": 80,
        "sample_step": 2,
    },
    "wait_stable": {
        "x1": 0,
        "y1": 0,
        "x2": 100,
        "y2": 50,
        "stable_duration_ms": 300,
        "check_interval_ms": 100,
        "change_threshold": 25,
        "maximum_changed_percent": 2,
        "timeout_ms": 5000,
        "timeout_behavior": "fail",
        "after_success_delay_ms": 0,
    },
    "click_until_change": {
        "x": 0,
        "y": 0,
        "button": "left",
        "click_count": 1,
        "x1": 0,
        "y1": 0,
        "x2": 100,
        "y2": 50,
        "change_threshold": 25,
        "required_changed_percent": 5,
        "post_click_delay_ms": 250,
        "check_interval_ms": 100,
        "check_timeout_ms": 1000,
        "retry_count": 3,
        "retry_delay_ms": 250,
    },
    "repeat": {
        "repeat_count": 2,
    },
    "label": {
        "label_name": "start",
    },
    "goto": {
        "target_label": "start",
    },
    "run_macro": {
        "macro_path": "",
    },
    "stop": {},
}


BLOCK_LABELS: Dict[str, str] = {
    "click": "Click",
    "key_press": "Key Press",
    "wait": "Wait",
    "wait_pixel": "Wait For Pixel Match",
    "if_pixel": "If Pixel Match",
    "wait_region": "Wait For Region Colour Match",
    "if_region": "If Region Colour Match",
    "wait_stable": "Wait Until Region Stable",
    "click_until_change": "Click Until Region Changes",
    "repeat": "Repeat",
    "label": "Label",
    "goto": "Goto",
    "run_macro": "Run Saved Macro",
    "stop": "Stop Macro",
}


CHILD_BLOCK_TYPES = {"if_pixel", "if_region", "repeat"}
ROOT_ONLY_BLOCK_TYPES = {"label", "goto"}


@dataclass
class MacroBlock:
    type: str
    id: str = field(default_factory=new_id)
    name: str = ""
    note: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    children: List["MacroBlock"] = field(default_factory=list)
    else_children: List["MacroBlock"] = field(default_factory=list)

    @classmethod
    def create(cls, block_type: str) -> "MacroBlock":
        if block_type not in BLOCK_DEFAULTS:
            raise ValueError(f"Unknown block type: {block_type}")
        return cls(
            type=block_type,
            name=BLOCK_LABELS.get(block_type, block_type),
            params=dict(BLOCK_DEFAULTS[block_type]),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MacroBlock":
        block_type = str(data.get("type", "wait"))
        incoming_params = dict(data.get("params") or {})
        if block_type in {"wait_region", "if_region"}:
            incoming_params = _migrate_region_hsv_params(incoming_params)
        params = dict(BLOCK_DEFAULTS.get(block_type, {}))
        params.update(incoming_params)
        return cls(
            type=block_type,
            id=str(data.get("id") or new_id()),
            name=str(data.get("name") or BLOCK_LABELS.get(block_type, block_type)),
            note=str(data.get("note") or ""),
            params=params,
            children=[cls.from_dict(child) for child in data.get("children") or []],
            else_children=[
                cls.from_dict(child) for child in data.get("else_children") or []
            ],
        )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "note": self.note,
            "params": dict(self.params),
        }
        if self.children:
            data["children"] = [child.to_dict() for child in self.children]
        if self.else_children:
            data["else_children"] = [child.to_dict() for child in self.else_children]
        return data

    def clone(self) -> "MacroBlock":
        return MacroBlock(
            type=self.type,
            name=self.name,
            note=self.note,
            params=dict(self.params),
            children=[child.clone() for child in self.children],
            else_children=[child.clone() for child in self.else_children],
        )

    def label(self) -> str:
        return self.name or BLOCK_LABELS.get(self.type, self.type)


@dataclass
class Macro:
    name: str = "Untitled Macro"
    notes: str = ""
    target_window: Optional[Dict[str, Any]] = None
    expected_window_size: Optional[Dict[str, int]] = None
    blocks: List[MacroBlock] = field(default_factory=list)
    path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Macro":
        return cls(
            name=str(data.get("name") or "Untitled Macro"),
            notes=str(data.get("notes") or ""),
            target_window=data.get("target_window"),
            expected_window_size=data.get("expected_window_size"),
            blocks=[MacroBlock.from_dict(block) for block in data.get("blocks") or []],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "notes": self.notes,
            "target_window": self.target_window,
            "expected_window_size": self.expected_window_size,
            "blocks": [block.to_dict() for block in self.blocks],
        }

    def all_blocks(self) -> Iterable[MacroBlock]:
        yield from iter_blocks(self.blocks)


def iter_blocks(blocks: Iterable[MacroBlock]) -> Iterable[MacroBlock]:
    for block in blocks:
        yield block
        yield from iter_blocks(block.children)
        yield from iter_blocks(block.else_children)


def find_block(
    blocks: List[MacroBlock], block_id: str
) -> Optional[Tuple[MacroBlock, List[MacroBlock], Optional[MacroBlock], str]]:
    """Return block, owning list, parent block, and branch name."""
    for block in blocks:
        if block.id == block_id:
            return block, blocks, None, "root"
        nested = find_block_with_parent(block.children, block_id, block, "children")
        if nested:
            return nested
        nested = find_block_with_parent(
            block.else_children, block_id, block, "else_children"
        )
        if nested:
            return nested
    return None


def find_block_with_parent(
    blocks: List[MacroBlock], block_id: str, parent: MacroBlock, branch: str
) -> Optional[Tuple[MacroBlock, List[MacroBlock], Optional[MacroBlock], str]]:
    for block in blocks:
        if block.id == block_id:
            return block, blocks, parent, branch
        nested = find_block_with_parent(block.children, block_id, block, "children")
        if nested:
            return nested
        nested = find_block_with_parent(
            block.else_children, block_id, block, "else_children"
        )
        if nested:
            return nested
    return None


def block_summary(block: MacroBlock) -> str:
    p = block.params
    if block.type == "click":
        return (
            f"{p.get('button', 'left')} click x={p.get('x', 0)}, "
            f"y={p.get('y', 0)} x{p.get('click_count', 1)}"
        )
    if block.type == "key_press":
        return f"press {p.get('key', '')} x{p.get('press_count', 1)}"
    if block.type == "wait":
        return f"wait {p.get('duration_ms', 0)} ms"
    if block.type == "wait_pixel":
        timeout = p.get("timeout_ms")
        timeout_text = "no timeout" if timeout in ("", None) else f"timeout {timeout} ms"
        return (
            f"x={p.get('x', 0)}, y={p.get('y', 0)} "
            f"color={p.get('expected_color', '')} tol={p.get('tolerance', 0)}, "
            f"{normalize_sampling_mode(p.get('sampling_mode'))}, {timeout_text}"
        )
    if block.type == "if_pixel":
        return (
            f"x={p.get('x', 0)}, y={p.get('y', 0)} "
            f"color={p.get('expected_color', '')} tol={p.get('tolerance', 0)}, "
            f"{normalize_sampling_mode(p.get('sampling_mode'))}"
        )
    if block.type in {"wait_region", "if_region"}:
        left, top, right, bottom = normalize_region(
            p.get("x1", 0), p.get("y1", 0), p.get("x2", 0), p.get("y2", 0)
        )
        return (
            f"region=({left},{top})-({right},{bottom}), "
            f"{normalize_region_detection_mode(p.get('detection_mode'))}, "
            f"min={p.get('minimum_match_percent', 0)}%"
        )
    if block.type == "wait_stable":
        left, top, right, bottom = normalize_region(
            p.get("x1", 0), p.get("y1", 0), p.get("x2", 0), p.get("y2", 0)
        )
        return (
            f"region=({left},{top})-({right},{bottom}), "
            f"stable {p.get('stable_duration_ms', 0)} ms, "
            f"max changed={p.get('maximum_changed_percent', 0)}%"
        )
    if block.type == "click_until_change":
        left, top, right, bottom = normalize_region(
            p.get("x1", 0), p.get("y1", 0), p.get("x2", 0), p.get("y2", 0)
        )
        return (
            f"click=({p.get('x', 0)},{p.get('y', 0)}), "
            f"watch=({left},{top})-({right},{bottom}), "
            f"required={p.get('required_changed_percent', 0)}%, "
            f"attempts={p.get('retry_count', 1)}"
        )
    if block.type == "repeat":
        return f"repeat {p.get('repeat_count', 1)} times"
    if block.type == "label":
        return f"label={normalize_label_name(p.get('label_name')) or '<empty>'}"
    if block.type == "goto":
        return f"target={normalize_label_name(p.get('target_label')) or '<empty>'}"
    if block.type == "run_macro":
        return f"macro={str(p.get('macro_path', '') or '<not selected>')}"
    if block.type == "stop":
        return "stop execution"
    return ""


def block_display_name(block: MacroBlock) -> str:
    if block.type == "label":
        return f":{normalize_label_name(block.params.get('label_name')) or '<empty>'}"
    if block.type == "goto":
        return f"Goto -> {normalize_label_name(block.params.get('target_label')) or '<empty>'}"
    if block.type == "run_macro":
        reference = str(block.params.get("macro_path", "") or "").strip()
        reference_name = reference.replace("\\", "/").rsplit("/", 1)[-1]
        if reference_name.lower().endswith(".json"):
            reference_name = reference_name[:-5]
        custom_name = block.label()
        display = (
            custom_name
            if custom_name and custom_name != BLOCK_LABELS["run_macro"]
            else reference_name or "<not selected>"
        )
        return f"Run Saved Macro: {display}"
    return block.label()


def normalize_label_name(value: Any) -> str:
    return str(value or "").strip()


def root_label_names(macro: Macro) -> List[str]:
    return [
        normalize_label_name(block.params.get("label_name"))
        for block in macro.blocks
        if block.type == "label" and normalize_label_name(block.params.get("label_name"))
    ]


def root_label_indices(macro: Macro) -> Dict[str, int]:
    labels: Dict[str, int] = {}
    for index, block in enumerate(macro.blocks):
        if block.type != "label":
            continue
        name = normalize_label_name(block.params.get("label_name"))
        if name and name not in labels:
            labels[name] = index
    return labels


def control_flow_errors(macro: Macro) -> List[str]:
    errors: List[str] = []
    label_counts: Dict[str, int] = {}
    for block in macro.blocks:
        if block.type == "label":
            name = normalize_label_name(block.params.get("label_name"))
            if not name:
                errors.append("A root Label block has an empty label name.")
            else:
                label_counts[name] = label_counts.get(name, 0) + 1

    for name, count in label_counts.items():
        if count > 1:
            errors.append(f"Label name '{name}' is duplicated {count} times.")

    label_names = set(label_counts)
    for block in macro.blocks:
        if block.type != "goto":
            continue
        target = normalize_label_name(block.params.get("target_label"))
        if not target:
            errors.append("A root Goto block has an empty target label.")
        elif target not in label_names:
            errors.append(f"Goto target label '{target}' was not found.")

    for block in macro.blocks:
        errors.extend(_nested_control_flow_errors(block.children))
        errors.extend(_nested_control_flow_errors(block.else_children))
    return errors


def _nested_control_flow_errors(blocks: Iterable[MacroBlock]) -> List[str]:
    errors: List[str] = []
    for block in blocks:
        if block.type in ROOT_ONLY_BLOCK_TYPES:
            errors.append(
                f"{BLOCK_LABELS[block.type]} block '{block_display_name(block)}' "
                "is nested. Label and Goto blocks are root-level only."
            )
        errors.extend(_nested_control_flow_errors(block.children))
        errors.extend(_nested_control_flow_errors(block.else_children))
    return errors


def color_to_hex(rgb: Tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def color_to_rgb_text(rgb: Tuple[int, int, int]) -> str:
    return f"RGB({rgb[0]}, {rgb[1]}, {rgb[2]})"


def parse_color(value: Any) -> Tuple[int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(max(0, min(255, int(v))) for v in value)  # type: ignore[return-value]
    text = str(value or "").strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6:
        raise ValueError("Colour must be in #RRGGBB format")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def colors_match(actual: Tuple[int, int, int], expected: Any, tolerance: Any) -> bool:
    expected_rgb = parse_color(expected)
    tol = max(0, int(tolerance or 0))
    return all(abs(a - b) <= tol for a, b in zip(actual, expected_rgb))


def required_tolerance(actual: Tuple[int, int, int], expected: Any) -> int:
    expected_rgb = parse_color(expected)
    return max(abs(a - b) for a, b in zip(actual, expected_rgb))


def normalize_sampling_mode(value: Any) -> str:
    text = str(value or PIXEL_SAMPLING_SINGLE).strip()
    aliases = {
        "single": PIXEL_SAMPLING_SINGLE,
        "single_pixel": PIXEL_SAMPLING_SINGLE,
        "single pixel": PIXEL_SAMPLING_SINGLE,
        "average_3x3": PIXEL_SAMPLING_AVERAGE_3,
        "average 3x3": PIXEL_SAMPLING_AVERAGE_3,
        "average 3": PIXEL_SAMPLING_AVERAGE_3,
        "average_5x5": PIXEL_SAMPLING_AVERAGE_5,
        "average 5x5": PIXEL_SAMPLING_AVERAGE_5,
        "average 5": PIXEL_SAMPLING_AVERAGE_5,
        "closest_3x3": PIXEL_SAMPLING_CLOSEST_3,
        "closest match 3x3": PIXEL_SAMPLING_CLOSEST_3,
        "closest 3x3": PIXEL_SAMPLING_CLOSEST_3,
        "closest_5x5": PIXEL_SAMPLING_CLOSEST_5,
        "closest match 5x5": PIXEL_SAMPLING_CLOSEST_5,
        "closest 5x5": PIXEL_SAMPLING_CLOSEST_5,
    }
    return aliases.get(text.lower(), text if text in PIXEL_SAMPLING_MODES else PIXEL_SAMPLING_SINGLE)


def sampling_mode_size(mode: Any) -> int:
    normalized = normalize_sampling_mode(mode)
    if normalized.endswith("5x5"):
        return 5
    if normalized.endswith("3x3"):
        return 3
    return 1


def sampling_mode_kind(mode: Any) -> str:
    normalized = normalize_sampling_mode(mode)
    if normalized.startswith("Average"):
        return "average"
    if normalized.startswith("Closest"):
        return "closest"
    return "single"


def normalize_region_detection_mode(value: Any) -> str:
    text = str(value or REGION_MODE_GREEN).strip()
    aliases = {
        "green": REGION_MODE_GREEN,
        "green dominance": REGION_MODE_GREEN,
        "rgb green": REGION_MODE_GREEN,
        "rgb green dominance": REGION_MODE_GREEN,
        "hsv": REGION_MODE_HSV,
        "hsv green": REGION_MODE_HSV,
        "saturated green": REGION_MODE_HSV,
        "expected": REGION_MODE_EXPECTED,
        "expected colour": REGION_MODE_EXPECTED,
        "expected color": REGION_MODE_EXPECTED,
        "expected colour match": REGION_MODE_EXPECTED,
        "expected color match": REGION_MODE_EXPECTED,
    }
    return aliases.get(
        text.lower(), text if text in REGION_DETECTION_MODES else REGION_MODE_GREEN
    )


def normalize_region(x1: Any, y1: Any, x2: Any, y2: Any) -> Tuple[int, int, int, int]:
    ax, ay, bx, by = int(x1), int(y1), int(x2), int(y2)
    return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)


def _migrate_region_hsv_params(params: Dict[str, Any]) -> Dict[str, Any]:
    migrated = dict(params)
    if "hsv_min_saturation" not in migrated or "hsv_min_value" not in migrated:
        return migrated
    saturation = float(migrated.get("hsv_min_saturation") or 0)
    value = float(migrated.get("hsv_min_value") or 0)
    if saturation <= 1 and value <= 1:
        migrated["hsv_hue_min"] = round(float(migrated.get("hsv_hue_min", 80)) / 2)
        migrated["hsv_hue_max"] = round(float(migrated.get("hsv_hue_max", 160)) / 2)
        migrated["hsv_min_saturation"] = round(saturation * 255)
        migrated["hsv_min_value"] = round(value * 255)
    return migrated
