from __future__ import annotations

import unittest
from unittest.mock import patch

from macro_recorder.app import MacroEditorApp
from macro_recorder.models import Macro, MacroBlock
from macro_recorder.win32_automation import TargetWindowInfo, vk_code_to_key


class ImmediateRoot:
    def after(self, _delay, callback):
        callback()


class ValueHolder:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class FakeRunner:
    is_running = False


class FakeWindowManager:
    def __init__(self) -> None:
        self.target = TargetWindowInfo(
            hwnd=1,
            title="Target",
            class_name="Test",
            client_left=100,
            client_top=200,
            client_width=640,
            client_height=480,
            window_left=95,
            window_top=170,
            window_width=650,
            window_height=515,
            dpi=96,
        )
        self.foreground = True

    def require_ready(self, *_args):
        return self.target

    def screen_to_client(self, target, screen_x, screen_y):
        return screen_x - target.client_left, screen_y - target.client_top

    def is_foreground(self, _target):
        return self.foreground


def recording_app() -> MacroEditorApp:
    app = MacroEditorApp.__new__(MacroEditorApp)
    app.root = ImmediateRoot()
    app.window_manager = FakeWindowManager()
    app.macro = Macro(
        target_window={"title": "Target", "hwnd": 1},
        expected_window_size={"width": 640, "height": 480},
    )
    app.runner = FakeRunner()
    app.recording = True
    app.recording_count = 0
    app.recording_target_list = app.macro.blocks
    app.recording_insert_index = 0
    app.builder_bounds = (0, 0, 80, 80)
    app.status_var = ValueHolder()
    app.messages = []
    app.threadsafe_log = app.messages.append
    app.refresh_tree = lambda *_args, **_kwargs: None
    app.show_selected_properties = lambda: None
    return app


class RecordingTests(unittest.TestCase):
    def test_vk_codes_convert_to_supported_key_names(self) -> None:
        self.assertEqual(vk_code_to_key(0x20), "space")
        self.assertEqual(vk_code_to_key(0x51), "q")
        self.assertEqual(vk_code_to_key(0x70), "f1")
        self.assertEqual(vk_code_to_key(0x25), "left")
        self.assertIsNone(vk_code_to_key(0x10))  # Modifier-only Shift is ignored.
        self.assertIsNone(vk_code_to_key(0x11))  # Modifier-only Ctrl is ignored.

    def test_target_click_becomes_relative_click_block_with_button(self) -> None:
        app = recording_app()

        app.on_user_mouse_click(125, 245, "right")

        self.assertEqual(len(app.macro.blocks), 1)
        block = app.macro.blocks[0]
        self.assertEqual(block.type, "click")
        self.assertEqual(
            (block.params["x"], block.params["y"], block.params["button"]),
            (25, 45, "right"),
        )

    def test_click_uses_live_target_origin_after_window_moves(self) -> None:
        app = recording_app()
        app.window_manager.target.client_left = 350
        app.window_manager.target.client_top = 400

        app.on_user_mouse_click(375, 445, "left")

        block = app.macro.blocks[0]
        self.assertEqual((block.params["x"], block.params["y"]), (25, 45))

    def test_builder_and_outside_clicks_are_not_recorded(self) -> None:
        app = recording_app()

        app.on_user_mouse_click(20, 20, "left")
        app.on_user_mouse_click(900, 900, "left")

        self.assertEqual(app.macro.blocks, [])
        self.assertTrue(any("outside the target" in message for message in app.messages))

    def test_keyboard_records_only_supported_keys_while_target_is_foreground(self) -> None:
        app = recording_app()

        app.on_user_keyboard_input(0x20)
        app.on_user_keyboard_input(0x10)
        app.window_manager.foreground = False
        app.on_user_keyboard_input(0x51)

        self.assertEqual(len(app.macro.blocks), 1)
        block = app.macro.blocks[0]
        self.assertEqual(block.type, "key_press")
        self.assertEqual(block.params["key"], "space")

    def test_live_recording_preserves_insertion_order(self) -> None:
        app = recording_app()
        existing = MacroBlock.create("wait")
        app.macro.blocks.append(existing)
        app.recording_target_list = app.macro.blocks
        app.recording_insert_index = 0

        app._record_keyboard_input("q")
        app._record_mouse_click(10, 20, "left")

        self.assertEqual(
            [block.type for block in app.macro.blocks],
            ["key_press", "click", "wait"],
        )

    def test_recorded_blocks_round_trip_as_normal_existing_blocks(self) -> None:
        app = recording_app()
        app._record_mouse_click(10, 20, "middle")
        app._record_keyboard_input("space")

        loaded = Macro.from_dict(app.macro.to_dict())

        self.assertEqual([block.type for block in loaded.blocks], ["click", "key_press"])
        self.assertEqual(loaded.blocks[0].params["button"], "middle")
        self.assertEqual(loaded.blocks[1].params["key"], "space")

    def test_running_is_refused_while_recording(self) -> None:
        app = recording_app()

        with patch("macro_recorder.app.messagebox.showinfo") as showinfo:
            allowed = app._prepare_macro_run()

        self.assertFalse(allowed)
        showinfo.assert_called_once()


if __name__ == "__main__":
    unittest.main()
