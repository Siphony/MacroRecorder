from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from macro_recorder.app import MacroEditorApp
from macro_recorder.models import (
    Macro,
    MacroBlock,
    convert_clicks_to_move_and_click,
)
from macro_recorder.storage import MacroStorage


class ValueHolder:
    def __init__(self, value="") -> None:
        self.value = value

    def set(self, value) -> None:
        self.value = value


class RunnerState:
    is_running = False


def click(name: str, x: int, y: int) -> MacroBlock:
    block = MacroBlock.create("click")
    block.name = name
    block.note = f"note for {name}"
    block.params.update(
        {
            "x": x,
            "y": y,
            "button": "right",
            "click_count": 2,
            "delay_after_ms": 475,
            "custom_click_setting": "preserve",
        }
    )
    return block


def app_harness(storage: MacroStorage, macro: Macro) -> MacroEditorApp:
    app = MacroEditorApp.__new__(MacroEditorApp)
    app.storage = storage
    app.macro = macro
    app.recording = False
    app.running = False
    app.runner = RunnerState()
    app.status_var = ValueHolder()
    app.messages = []
    app.threadsafe_log = app.messages.append
    app.refresh_all = Mock()
    app.refresh_macro_list = Mock()
    app._mark_clean = Mock()
    app._confirm_click_conversion = Mock(return_value=True)
    return app


class ClickConversionModelTests(unittest.TestCase):
    def test_conversion_is_recursive_and_preserves_click_data(self) -> None:
        root_click = click("Root placement", 10, 20)
        nested_click = click("Nested placement", 30, 40)
        else_click = click("Else placement", 50, 60)
        repeat = MacroBlock.create("repeat")
        repeat.children.append(nested_click)
        condition = MacroBlock.create("if_pixel")
        condition.else_children.append(else_click)
        existing_move = MacroBlock.create("move_and_click")
        existing_move.params["movement_duration_ms"] = 99
        macro = Macro(blocks=[root_click, repeat, condition, existing_move])
        original_ids = [block.id for block in macro.all_blocks()]

        converted = convert_clicks_to_move_and_click(macro)

        self.assertEqual(converted, 3)
        self.assertEqual([block.id for block in macro.all_blocks()], original_ids)
        for block in (root_click, nested_click, else_click):
            self.assertEqual(block.type, "move_and_click")
            self.assertEqual(block.params["movement_duration_ms"], 150)
            self.assertEqual(block.params["button"], "right")
            self.assertEqual(block.params["click_count"], 2)
            self.assertEqual(block.params["delay_after_ms"], 475)
            self.assertEqual(block.params["custom_click_setting"], "preserve")
            self.assertTrue(block.name.endswith("placement"))
            self.assertTrue(block.note.startswith("note for"))
        self.assertEqual(existing_move.params["movement_duration_ms"], 99)


class ClickConversionAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)
        self.storage = MacroStorage(self.project / "macros")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def save_current_then_convert(self, app: MacroEditorApp, path: Path):
        events = []

        def save_before() -> bool:
            events.append("save_before")
            self.storage.save(app.macro, path)
            return True

        def save_converted() -> bool:
            events.append("save_converted")
            self.storage.save(app.macro, path)
            return True

        app._save_for_transition = Mock(side_effect=save_before)
        app.save_macro = Mock(side_effect=save_converted)
        return events

    def test_current_macro_is_saved_backed_up_converted_and_reloaded(self) -> None:
        nested = click("Nested", 30, 40)
        repeat = MacroBlock.create("repeat")
        repeat.children.append(nested)
        existing_move = MacroBlock.create("move_and_click")
        existing_move.params["movement_duration_ms"] = 85
        current_path = self.storage.save(
            Macro(name="Current", blocks=[click("Root", 10, 20), repeat, existing_move]),
            self.storage.base_dir / "Current.json",
        )
        other_path = self.storage.save(
            Macro(name="Other", blocks=[click("Other", 1, 2)]),
            self.storage.base_dir / "Other.json",
        )
        app = app_harness(self.storage, self.storage.load(current_path))
        app.macro.blocks[0].params["x"] = 777
        events = self.save_current_then_convert(app, current_path)

        with patch("macro_recorder.app.messagebox.showerror"):
            app.convert_current_macro_clicks()

        self.assertEqual(events, ["save_before", "save_converted"])
        loaded = self.storage.load(current_path)
        converted = [block for block in loaded.all_blocks() if block.type == "move_and_click"]
        self.assertEqual(len(converted), 3)
        self.assertEqual(converted[0].params["x"], 777)
        self.assertEqual(converted[0].params["movement_duration_ms"], 150)
        self.assertEqual(converted[1].params["movement_duration_ms"], 150)
        self.assertEqual(converted[2].params["movement_duration_ms"], 85)
        self.assertEqual(self.storage.load(other_path).blocks[0].type, "click")

        backup_dir = self.project / "macro_backups" / "v1.11_click_to_move_click"
        backups = list(backup_dir.glob("Current_*.json"))
        self.assertEqual(len(backups), 1)
        backup_data = json.loads(backups[0].read_text(encoding="utf-8"))
        self.assertEqual(backup_data["blocks"][0]["type"], "click")
        self.assertEqual(backup_data["blocks"][0]["params"]["x"], 777)
        app.refresh_all.assert_called()
        app.refresh_macro_list.assert_called_with(current_path.resolve())
        app._mark_clean.assert_called()
        self.assertTrue(any("Converted 2 Click blocks" in item for item in app.messages))

    def test_new_unsaved_macro_is_saved_before_backup_and_conversion(self) -> None:
        path = self.storage.base_dir / "New Macro.json"
        app = app_harness(
            self.storage, Macro(name="New Macro", blocks=[click("Root", 10, 20)])
        )

        def save_as() -> bool:
            self.storage.save(app.macro, path)
            return True

        app._save_for_transition = Mock(side_effect=save_as)
        app.save_macro = Mock(
            side_effect=lambda: bool(self.storage.save(app.macro, path))
        )

        with patch("macro_recorder.app.messagebox.showerror"):
            app.convert_current_macro_clicks()

        self.assertEqual(self.storage.load(path).blocks[0].type, "move_and_click")
        self.assertEqual(
            len(
                list(
                    (
                        self.project
                        / "macro_backups"
                        / "v1.11_click_to_move_click"
                    ).glob("New Macro_*.json")
                )
            ),
            1,
        )

    def test_cancel_or_save_cancel_does_not_convert(self) -> None:
        macro = Macro(name="Current", blocks=[click("Root", 10, 20)])
        app = app_harness(self.storage, macro)
        app._confirm_click_conversion = Mock(return_value=False)
        app._save_for_transition = Mock(return_value=True)

        app.convert_current_macro_clicks()

        self.assertEqual(app.macro.blocks[0].type, "click")
        app._save_for_transition.assert_not_called()

        app._confirm_click_conversion = Mock(return_value=True)
        app._save_for_transition = Mock(return_value=False)
        app.convert_current_macro_clicks()
        self.assertEqual(app.macro.blocks[0].type, "click")

    def test_no_clicks_is_not_an_error_and_creates_no_backup(self) -> None:
        path = self.storage.save(
            Macro(name="No Clicks", blocks=[MacroBlock.create("wait")]),
            self.storage.base_dir / "No Clicks.json",
        )
        app = app_harness(self.storage, self.storage.load(path))
        app._save_for_transition = Mock(return_value=True)

        with patch("macro_recorder.app.messagebox.showinfo") as showinfo:
            app.convert_current_macro_clicks()

        self.assertTrue(any("No plain Click blocks" in item for item in app.messages))
        showinfo.assert_called_once()
        self.assertFalse((self.project / "macro_backups").exists())

    def test_backup_failure_does_not_modify_macro(self) -> None:
        path = self.storage.save(
            Macro(name="Current", blocks=[click("Root", 10, 20)]),
            self.storage.base_dir / "Current.json",
        )
        app = app_harness(self.storage, self.storage.load(path))
        app._save_for_transition = Mock(return_value=True)
        app.save_macro = Mock(return_value=True)

        with (
            patch("macro_recorder.app.shutil.copy2", side_effect=OSError("disk full")),
            patch("macro_recorder.app.messagebox.showerror") as showerror,
        ):
            app.convert_current_macro_clicks()

        self.assertEqual(app.macro.blocks[0].type, "click")
        self.assertEqual(self.storage.load(path).blocks[0].type, "click")
        app.save_macro.assert_not_called()
        showerror.assert_called_once()

    def test_failed_converted_save_restores_backup_and_original_macro(self) -> None:
        path = self.storage.save(
            Macro(name="Current", blocks=[click("Root", 10, 20)]),
            self.storage.base_dir / "Current.json",
        )
        app = app_harness(self.storage, self.storage.load(path))
        app._save_for_transition = Mock(return_value=True)
        app.save_macro = Mock(return_value=False)

        with patch("macro_recorder.app.messagebox.showerror"):
            app.convert_current_macro_clicks()

        self.assertEqual(app.macro.blocks[0].type, "click")
        self.assertEqual(self.storage.load(path).blocks[0].type, "click")
        self.assertEqual(
            len(
                list(
                    (
                        self.project
                        / "macro_backups"
                        / "v1.11_click_to_move_click"
                    ).glob("Current_*.json")
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
