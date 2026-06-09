from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro_recorder.app import MacroEditorApp
from macro_recorder.models import Macro, MacroBlock, block_summary
from macro_recorder.runner import MacroRunner, MacroStopped
from macro_recorder.win32_automation import (
    AutomationError,
    InputController,
    TargetWindowInfo,
)
from tools.convert_strategy_clicks_v192 import migrate_strategy_macros


TARGET = TargetWindowInfo(
    hwnd=1,
    title="Test Target",
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


class FakeWindowManager:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def require_ready(self, *_args, **_kwargs):
        if self.fail:
            raise AutomationError("Target window is missing.")
        return TARGET


class CoordinateWindowManager:
    def __init__(self) -> None:
        self.requests = []

    def client_to_screen(self, target, x, y):
        self.requests.append((target, x, y))
        return target.client_left + x, target.client_top + y


class FakeUser32:
    def __init__(self) -> None:
        self.positions = []

    def GetCursorPos(self, point) -> bool:
        point._obj.x = 10
        point._obj.y = 20
        return True

    def SetCursorPos(self, x, y) -> bool:
        self.positions.append((x, y))
        return True


class FakeInputController:
    def __init__(self) -> None:
        self.calls = []

    def move_mouse(self, target, x, y, duration_ms, stop_check=None) -> None:
        self.calls.append(("move", target, x, y, duration_ms))
        if stop_check:
            stop_check()

    def click(self, target, x, y, button, click_count) -> None:
        self.calls.append(("click", target, x, y, button, click_count))


class FakeScreenAnalysis:
    pass


def runner(fail_target: bool = False):
    inputs = FakeInputController()
    instance = MacroRunner(
        FakeWindowManager(fail_target),
        inputs,
        FakeScreenAnalysis(),
    )
    sleeps = []
    instance._responsive_sleep = sleeps.append
    return instance, inputs, sleeps


class MoveBlockTests(unittest.TestCase):
    def test_new_blocks_round_trip_with_defaults_and_summaries(self) -> None:
        move = MacroBlock.create("move_mouse")
        move_click = MacroBlock.create("move_and_click")

        loaded = Macro.from_dict(Macro(blocks=[move, move_click]).to_dict())

        self.assertEqual(loaded.blocks[0].params["movement_duration_ms"], 150)
        self.assertEqual(loaded.blocks[1].params["movement_duration_ms"], 150)
        self.assertEqual(loaded.blocks[1].params["delay_after_ms"], 300)
        self.assertIn("move to", block_summary(loaded.blocks[0]))
        self.assertIn("then left click", block_summary(loaded.blocks[1]))

    def test_move_mouse_moves_without_clicking(self) -> None:
        instance, inputs, sleeps = runner()
        block = MacroBlock.create("move_mouse")
        block.params.update({"x": 25, "y": 45, "movement_duration_ms": 0})

        instance._execute_block(Macro(), block)

        self.assertEqual(inputs.calls, [("move", TARGET, 25, 45, 0)])
        self.assertEqual(sleeps, [])

    def test_move_and_click_preserves_click_and_delay_behavior(self) -> None:
        instance, inputs, sleeps = runner()
        block = MacroBlock.create("move_and_click")
        block.params.update(
            {
                "x": 25,
                "y": 45,
                "button": "right",
                "click_count": 2,
                "movement_duration_ms": 175,
                "delay_after_ms": 400,
            }
        )

        instance._execute_block(Macro(), block)

        self.assertEqual(
            inputs.calls,
            [
                ("move", TARGET, 25, 45, 175),
                ("click", TARGET, 25, 45, "right", 2),
            ],
        )
        self.assertEqual(sleeps, [400])

    def test_move_blocks_fail_safely_without_ready_target(self) -> None:
        instance, _inputs, _sleeps = runner(fail_target=True)

        with self.assertRaisesRegex(AutomationError, "Target window is missing"):
            instance._execute_block(Macro(), MacroBlock.create("move_mouse"))

    def test_instant_input_movement_uses_client_relative_conversion(self) -> None:
        manager = CoordinateWindowManager()
        user32 = FakeUser32()

        with patch("macro_recorder.win32_automation.user32", user32):
            InputController(manager).move_mouse(TARGET, 25, 45, 0)

        self.assertEqual(manager.requests, [(TARGET, 25, 45)])
        self.assertEqual(user32.positions, [(125, 245)])

    def test_movement_checks_stop_before_moving(self) -> None:
        manager = CoordinateWindowManager()
        user32 = FakeUser32()

        with patch("macro_recorder.win32_automation.user32", user32):
            with self.assertRaises(MacroStopped):
                InputController(manager).move_mouse(
                    TARGET,
                    25,
                    45,
                    150,
                    stop_check=lambda: (_ for _ in ()).throw(MacroStopped()),
                )

        self.assertEqual(user32.positions, [])

    def test_editor_treats_new_blocks_as_crosshair_coordinate_blocks(self) -> None:
        app = MacroEditorApp.__new__(MacroEditorApp)
        for block_type in ("move_mouse", "move_and_click"):
            block = MacroBlock.create(block_type)
            app.selected_block_units = lambda selected=block: [selected]
            self.assertIs(app._coordinate_marker_block(), block)
            self.assertTrue(app._block_uses_coordinates(block))
        self.assertEqual(app._coerce_param("movement_duration_ms", "0"), 0)


class StrategyConversionTests(unittest.TestCase):
    def test_conversion_is_recursive_backed_up_and_narrowly_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            macros = root / "macros"
            backup = root / "backups" / "v192"
            macros.mkdir()

            click = {
                "id": "plain",
                "type": "click",
                "name": "Place Tower",
                "note": "preserve me",
                "params": {
                    "x": 12,
                    "y": 34,
                    "button": "right",
                    "click_count": 2,
                    "delay_after_ms": 456,
                },
            }
            matching_data = {
                "name": "Map Strategy",
                "blocks": [
                    {
                        "id": "repeat",
                        "type": "repeat",
                        "params": {"repeat_count": 1},
                        "children": [click],
                    },
                    {
                        "id": "existing",
                        "type": "move_and_click",
                        "params": {"x": 1, "y": 2, "movement_duration_ms": 99},
                    },
                ],
            }
            matching_path = macros / "XX_Defla.json"
            matching_path.write_text(json.dumps(matching_data, indent=2), encoding="utf-8")
            unrelated_path = macros / "Navigation.json"
            unrelated_path.write_text(json.dumps({"blocks": [click]}), encoding="utf-8")

            summary = migrate_strategy_macros(macros, backup)

            self.assertEqual(summary.matched_files, (matching_path,))
            self.assertEqual(summary.converted_files, (matching_path,))
            self.assertEqual(summary.converted_clicks, 1)
            self.assertTrue((backup / matching_path.name).is_file())
            converted = json.loads(matching_path.read_text(encoding="utf-8"))
            nested = converted["blocks"][0]["children"][0]
            self.assertEqual(nested["type"], "move_and_click")
            self.assertEqual(nested["name"], "Place Tower")
            self.assertEqual(nested["note"], "preserve me")
            self.assertEqual(nested["params"]["button"], "right")
            self.assertEqual(nested["params"]["click_count"], 2)
            self.assertEqual(nested["params"]["delay_after_ms"], 456)
            self.assertEqual(nested["params"]["movement_duration_ms"], 150)
            self.assertEqual(
                converted["blocks"][1]["params"]["movement_duration_ms"], 99
            )
            unrelated = json.loads(unrelated_path.read_text(encoding="utf-8"))
            self.assertEqual(unrelated["blocks"][0]["type"], "click")

    def test_existing_backup_destination_aborts_before_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            macros = root / "macros"
            backup = root / "backup"
            macros.mkdir()
            backup.mkdir()
            path = macros / "XX_Impop.json"
            original = '{"blocks": [{"type": "click", "params": {}}]}'
            path.write_text(original, encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "no files were changed"):
                migrate_strategy_macros(macros, backup)

            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_macro_internal_name_can_select_strategy_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            macros = root / "macros"
            backup = root / "backup"
            macros.mkdir()
            path = macros / "Reusable Strategy.json"
            path.write_text(
                json.dumps(
                    {
                        "name": "XX_Impop",
                        "blocks": [{"type": "click", "params": {"x": 1, "y": 2}}],
                    }
                ),
                encoding="utf-8",
            )

            summary = migrate_strategy_macros(macros, backup)

            self.assertEqual(summary.matched_files, (path,))
            self.assertEqual(summary.converted_clicks, 1)
            converted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(converted["blocks"][0]["type"], "move_and_click")


if __name__ == "__main__":
    unittest.main()
