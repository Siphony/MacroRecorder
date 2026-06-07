from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from .models import Macro


class MacroStorage:
    def __init__(self, base_dir: Path | str = "macros") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.project_dir = self.base_dir.resolve().parent

    def list_macros(self) -> List[Path]:
        return sorted(self.base_dir.glob("*.json"), key=lambda p: p.stem.lower())

    def load(self, path: Path | str) -> Macro:
        macro_path = self.resolve_reference(path)
        with macro_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        macro = Macro.from_dict(data)
        macro.path = str(macro_path)
        return macro

    def save(self, macro: Macro, path: Path | str | None = None) -> Path:
        macro_path = Path(path) if path else Path(macro.path or self.default_path(macro.name))
        macro_path.parent.mkdir(parents=True, exist_ok=True)
        with macro_path.open("w", encoding="utf-8") as handle:
            json.dump(macro.to_dict(), handle, indent=2)
            handle.write("\n")
        macro.path = str(macro_path)
        return macro_path

    def default_path(self, name: str) -> Path:
        filename = safe_filename(name or "Untitled Macro")
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


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip().replace(" ", "_")
    return cleaned or "Untitled_Macro"
