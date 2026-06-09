from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


STRATEGY_NAME_PATTERN = re.compile(r"_(Defla|Impop)$", re.IGNORECASE)


@dataclass(frozen=True)
class ConversionSummary:
    matched_files: Tuple[Path, ...]
    converted_files: Tuple[Path, ...]
    converted_clicks: int
    backup_dir: Path


def matching_strategy_macros(macros_dir: Path | str) -> List[Path]:
    directory = Path(macros_dir)
    return sorted(
        (
            path
            for path in directory.glob("*.json")
            if path.name.casefold() != "macro_order.json"
            and (
                STRATEGY_NAME_PATTERN.search(path.stem)
                or _saved_macro_name_matches(path)
            )
        ),
        key=lambda path: path.name.casefold(),
    )


def _saved_macro_name_matches(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return bool(
            isinstance(data, dict)
            and STRATEGY_NAME_PATTERN.search(str(data.get("name") or ""))
        )
    except (OSError, ValueError, TypeError):
        return False


def convert_click_blocks(blocks: Iterable[Dict[str, Any]], duration_ms: int = 150) -> int:
    converted = 0
    for block in blocks:
        if block.get("type") == "click":
            block["type"] = "move_and_click"
            params = block.setdefault("params", {})
            if not isinstance(params, dict):
                raise ValueError("Click block params must be a JSON object.")
            params.setdefault("movement_duration_ms", max(0, int(duration_ms)))
            converted += 1
        for branch in ("children", "else_children"):
            nested = block.get(branch) or []
            if not isinstance(nested, list):
                raise ValueError(f"Block {branch} must be a JSON array.")
            converted += convert_click_blocks(nested, duration_ms)
    return converted


def prepare_conversions(
    paths: Iterable[Path], duration_ms: int = 150
) -> List[Tuple[Path, Dict[str, Any], int]]:
    prepared: List[Tuple[Path, Dict[str, Any], int]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            original = json.load(handle)
        if not isinstance(original, dict):
            raise ValueError(f"Macro file must contain a JSON object: {path}")
        converted = copy.deepcopy(original)
        blocks = converted.get("blocks") or []
        if not isinstance(blocks, list):
            raise ValueError(f"Macro blocks must be a JSON array: {path}")
        count = convert_click_blocks(blocks, duration_ms)
        prepared.append((path, converted, count))
    return prepared


def migrate_strategy_macros(
    macros_dir: Path | str = "macros",
    backup_dir: Path | str = "macro_backups/v1.9.2_click_to_move_click",
    duration_ms: int = 150,
) -> ConversionSummary:
    macros_path = Path(macros_dir)
    backup_path = Path(backup_dir)
    matched = matching_strategy_macros(macros_path)
    prepared = prepare_conversions(matched, duration_ms)

    if backup_path.exists():
        raise FileExistsError(
            f"Backup destination already exists; no files were changed: {backup_path}"
        )
    backup_path.mkdir(parents=True)

    for path in matched:
        shutil.copy2(path, backup_path / path.name)

    converted_files: List[Path] = []
    converted_clicks = 0
    for path, data, count in prepared:
        if count <= 0:
            continue
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        converted_files.append(path)
        converted_clicks += count

    return ConversionSummary(
        matched_files=tuple(matched),
        converted_files=tuple(converted_files),
        converted_clicks=converted_clicks,
        backup_dir=backup_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Back up *_Defla and *_Impop macro files, then recursively convert "
            "plain Click blocks to Move And Click."
        )
    )
    parser.add_argument("--macros-dir", default="macros")
    parser.add_argument(
        "--backup-dir", default="macro_backups/v1.9.2_click_to_move_click"
    )
    parser.add_argument("--duration-ms", type=int, default=150)
    args = parser.parse_args()

    summary = migrate_strategy_macros(
        args.macros_dir, args.backup_dir, args.duration_ms
    )
    print(f"Matching macros found: {len(summary.matched_files)}")
    print(f"Macros converted: {len(summary.converted_files)}")
    print(f"Click blocks converted: {summary.converted_clicks}")
    print(f"Backup folder: {summary.backup_dir}")
    if summary.matched_files:
        print("Matched files:")
        for path in summary.matched_files:
            print(f"  {path}")
    skipped = [
        path for path in summary.matched_files if path not in summary.converted_files
    ]
    if skipped:
        print("Matched files with no plain Click blocks:")
        for path in skipped:
            print(f"  {path}")


if __name__ == "__main__":
    main()
