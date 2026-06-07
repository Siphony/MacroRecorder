from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from .models import Macro


class MacroStorage:
    ORDER_FILENAME = "macro_order.json"

    def __init__(self, base_dir: Path | str = "macros") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.project_dir = self.base_dir.resolve().parent
        self.order_path = self.base_dir / self.ORDER_FILENAME

    def list_macros(self) -> List[Path]:
        discovered = sorted(
            (
                path
                for path in self.base_dir.glob("*.json")
                if path.name.casefold() != self.ORDER_FILENAME.casefold()
            ),
            key=lambda path: path.stem.lower(),
        )
        by_name = {path.name.casefold(): path for path in discovered}
        ordered: List[Path] = []
        used: set[str] = set()
        for name in self._load_order():
            key = Path(name).name.casefold()
            path = by_name.get(key)
            if path and key not in used:
                ordered.append(path)
                used.add(key)
        ordered.extend(path for path in discovered if path.name.casefold() not in used)
        return ordered

    def move_macro(self, path: Path | str, delta: int) -> int:
        macros = self.list_macros()
        identity = self.reference_identity(path)
        index = next(
            (
                position
                for position, candidate in enumerate(macros)
                if self.reference_identity(candidate) == identity
            ),
            -1,
        )
        if index < 0:
            raise FileNotFoundError(f"Saved macro was not found: {path}")
        new_index = max(0, min(len(macros) - 1, index + int(delta)))
        if new_index != index:
            macros[index], macros[new_index] = macros[new_index], macros[index]
            self._save_order(macros)
        return new_index

    def load(self, path: Path | str) -> Macro:
        macro_path = self.resolve_reference(path)
        with macro_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        macro = Macro.from_dict(data)
        macro.path = str(macro_path)
        return macro

    def save(self, macro: Macro, path: Path | str | None = None) -> Path:
        macro_path = Path(path) if path else Path(macro.path or self.default_path(macro.name))
        if macro_path.resolve() == self.order_path.resolve():
            raise ValueError(f"{self.ORDER_FILENAME} is reserved for saved macro ordering.")
        macro_path.parent.mkdir(parents=True, exist_ok=True)
        with macro_path.open("w", encoding="utf-8") as handle:
            json.dump(macro.to_dict(), handle, indent=2)
            handle.write("\n")
        macro.path = str(macro_path)
        return macro_path

    def default_path(self, name: str) -> Path:
        filename = safe_filename(name or "Untitled Macro")
        if f"{filename}.json".casefold() == self.ORDER_FILENAME.casefold():
            filename += "_macro"
        return self.base_dir / f"{filename}.json"

    def to_reference(self, path: Path | str) -> str:
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(self.project_dir).as_posix()
        except ValueError:
            return str(resolved)

    def resolve_reference(self, reference: Path | str) -> Path:
        path = Path(str(reference or "").strip())
        if not path.is_absolute():
            path = self.project_dir / path
        return path.resolve()

    def reference_identity(self, reference: Path | str) -> str:
        return str(self.resolve_reference(reference)).casefold()

    def _load_order(self) -> List[str]:
        try:
            with self.order_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, list):
                return []
            return [str(item) for item in data if str(item).strip()]
        except (OSError, ValueError, TypeError):
            return []

    def _save_order(self, paths: List[Path]) -> None:
        with self.order_path.open("w", encoding="utf-8") as handle:
            json.dump([path.name for path in paths], handle, indent=2)
            handle.write("\n")


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip().replace(" ", "_")
    return cleaned or "Untitled_Macro"
