from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from macro_recorder.app import MacroEditorApp
from macro_recorder.models import Macro, MacroBlock
from macro_recorder.storage import MacroStorage


class ValueHolder:
    def __init__(self, value="") -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class TextHolder:
    def __init__(self, value="") -> None:
        self.value = value

    def get(self, *_args):
        return self.value


class RunnerState:
    is_running = False


def dirty_app() -> MacroEditorApp:
    app = MacroEditorApp.__new__(MacroEditorApp)
    app.macro = Macro()
    app.macro_name_var = ValueHolder(app.macro.name)
    app.notes_text = TextHolder(app.macro.notes)
    app.unsaved_indicator_var = ValueHolder()
    app._saved_snapshot = ""
    app._mark_clean()
    return app


def transition_app() -> MacroEditorApp:
    app = dirty_app()
    app.recording = False
    app.running = False
    app.runner = RunnerState()
    return app


class MacroOrderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = MacroStorage(Path(self.temp_dir.name) / "macros")
        for name in ("Alpha", "Beta", "Gamma"):
            self.storage.save(Macro(name=name), self.storage.base_dir / f"{name}.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def names(self):
        return [path.stem for path in self.storage.list_macros()]

    def test_manual_order_persists_and_metadata_is_not_a_macro(self) -> None:
        beta = self.storage.base_dir / "Beta.json"
        self.storage.move_macro(beta, -1)

        reopened = MacroStorage(self.storage.base_dir)

        self.assertEqual([path.stem for path in reopened.list_macros()], ["Beta", "Alpha", "Gamma"])
        self.assertTrue(reopened.order_path.is_file())
        self.assertNotIn(reopened.order_path, reopened.list_macros())

    def test_new_macros_append_and_missing_order_entries_are_ignored(self) -> None:
        self.storage.move_macro(self.storage.base_dir / "Gamma.json", -2)
        (self.storage.base_dir / "Alpha.json").unlink()
        self.storage.save(Macro(name="Delta"), self.storage.base_dir / "Delta.json")

        self.assertEqual(self.names(), ["Gamma", "Beta", "Delta"])

    def test_corrupt_or_incomplete_order_falls_back_safely(self) -> None:
        self.storage.order_path.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.names(), ["Alpha", "Beta", "Gamma"])

        self.storage.order_path.write_text(
            json.dumps(["Missing.json", "Gamma.json"]), encoding="utf-8"
        )
        self.assertEqual(self.names(), ["Gamma", "Alpha", "Beta"])


class SaveSafetyTests(unittest.TestCase):
    def test_snapshot_tracking_covers_content_metadata_and_recording_changes(self) -> None:
        app = dirty_app()
        self.assertFalse(app.is_dirty())

        app.macro.blocks.append(MacroBlock.create("wait"))
        self.assertTrue(app.is_dirty())
        app._mark_clean()
        app.macro.blocks[0].params["duration_ms"] = 900
        self.assertTrue(app.is_dirty())
        app._mark_clean()
        app.macro_name_var.value = "Renamed"
        self.assertTrue(app.is_dirty())
        app._mark_clean()
        app.macro.target_window = {"title": "Target"}
        self.assertTrue(app.is_dirty())

    def test_recorded_block_marks_snapshot_dirty(self) -> None:
        app = dirty_app()
        app.recording = True
        app.recording_target_list = app.macro.blocks
        app.recording_insert_index = 0
        app.recording_count = 0
        app.refresh_tree = lambda *_args, **_kwargs: None
        app.show_selected_properties = lambda: None
        app.status_var = ValueHolder()
        app.threadsafe_log = lambda _message: None

        app._append_recorded_block(MacroBlock.create("click"), "Recorded click")

        self.assertTrue(app.is_dirty())

    def test_transition_prompt_supports_save_discard_and_cancel(self) -> None:
        app = transition_app()
        app.is_dirty = lambda: True
        app._save_for_transition = Mock(return_value=True)

        with patch("macro_recorder.app.messagebox.askyesnocancel", return_value=True):
            self.assertTrue(app._confirm_safe_transition("switching macros"))
            app._save_for_transition.assert_called_once()

        app._save_for_transition.reset_mock()
        with patch("macro_recorder.app.messagebox.askyesnocancel", return_value=False):
            self.assertTrue(app._confirm_safe_transition("switching macros"))
            app._save_for_transition.assert_not_called()

        with patch("macro_recorder.app.messagebox.askyesnocancel", return_value=None):
            self.assertFalse(app._confirm_safe_transition("switching macros"))

    def test_running_and_recording_prevent_transitions(self) -> None:
        app = transition_app()
        app.recording = True
        with patch("macro_recorder.app.messagebox.showinfo") as showinfo:
            self.assertFalse(app._confirm_safe_transition("closing"))
            showinfo.assert_called_once()

        app.recording = False
        app.runner.is_running = True
        with patch("macro_recorder.app.messagebox.showinfo") as showinfo:
            self.assertFalse(app._confirm_safe_transition("closing"))
            showinfo.assert_called_once()

    def test_new_unsaved_macro_requires_save_as_before_run(self) -> None:
        app = transition_app()
        app.macro.path = None
        app.save_macro_as = Mock(return_value=False)

        with patch("macro_recorder.app.messagebox.showinfo") as showinfo:
            self.assertFalse(app._save_before_run())

        app.save_macro_as.assert_called_once()
        showinfo.assert_called_once()

    def test_existing_macro_is_saved_before_run_and_failure_blocks_run(self) -> None:
        app = transition_app()
        app.macro.path = "macros/Existing.json"
        app.save_macro = Mock(return_value=False)

        self.assertFalse(app._save_before_run())
        app.save_macro.assert_called_once()

        app.recording = False
        app.running = False
        app.apply_macro_header = lambda: None
        app.macro.target_window = {"title": "Target"}
        app.macro.blocks = [MacroBlock.create("wait")]
        app._save_before_run = Mock(return_value=False)
        self.assertFalse(app._prepare_macro_run())

    def test_close_cancel_keeps_app_open(self) -> None:
        app = transition_app()
        app.closing = False
        app._confirm_safe_transition = Mock(return_value=False)

        app.on_close()

        self.assertFalse(app.closing)


if __name__ == "__main__":
    unittest.main()
