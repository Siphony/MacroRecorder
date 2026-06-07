from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from macro_recorder.models import Macro, MacroBlock, block_display_name
from macro_recorder.runner import MacroRunner
from macro_recorder.storage import MacroStorage
from macro_recorder.win32_automation import TargetWindowInfo


TARGET = TargetWindowInfo(
    hwnd=1,
    title="Active Parent Target",
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
PARENT_TARGET = {"title": "Parent", "class_name": "Test", "hwnd": 1}
PARENT_SIZE = {"width": 640, "height": 480}


def key_block(key: str) -> MacroBlock:
    block = MacroBlock.create("key_press")
    block.params.update({"key": key, "delay_after_ms": 0})
    return block


def call_block(reference: str) -> MacroBlock:
    block = MacroBlock.create("run_macro")
    block.params["macro_path"] = reference
    return block


class FakeWindowManager:
    def __init__(self) -> None:
        self.requests = []

    def require_ready(self, target, expected_size):
        self.requests.append((target, expected_size))
        return TARGET


class FakeInputController:
    def __init__(self) -> None:
        self.keys = []

    def key_press(self, _target, key, press_count) -> None:
        self.keys.extend([key] * press_count)

    def click(self, *_args) -> None:
        pass


class FakeScreenAnalysis:
    def save_debug_capture(self, *_args, **_kwargs):
        return None


class RunnerHarness:
    def __init__(self, storage: MacroStorage) -> None:
        self.messages = []
        self.states = []
        self.window_manager = FakeWindowManager()
        self.input = FakeInputController()
        self.runner = MacroRunner(
            self.window_manager,
            self.input,
            FakeScreenAnalysis(),
            log_callback=self.messages.append,
            state_callback=self.states.append,
            storage=storage,
        )


class RunSavedMacroTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)
        self.storage = MacroStorage(self.project_dir / "macros")
        self.harness = RunnerHarness(self.storage)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def save(self, macro: Macro, filename: str) -> Path:
        return self.storage.save(macro, self.storage.base_dir / filename)

    def parent_macro(self, blocks) -> Macro:
        return Macro(
            name="Parent",
            target_window=PARENT_TARGET,
            expected_window_size=PARENT_SIZE,
            blocks=list(blocks),
        )

    def test_basic_call_returns_to_parent_and_shares_active_target(self) -> None:
        child = Macro(
            name="Reusable Setup",
            target_window={"title": "Wrong Child Target"},
            expected_window_size={"width": 1, "height": 1},
            blocks=[key_block("child")],
        )
        child_path = self.save(child, "Reusable Setup.json")
        parent = self.parent_macro(
            [call_block(self.storage.to_reference(child_path)), key_block("parent")]
        )
        self.save(parent, "Parent.json")

        self.harness.runner._run_macro(parent)

        self.assertEqual(self.harness.input.keys, ["child", "parent"])
        self.assertTrue(
            all(request == (PARENT_TARGET, PARENT_SIZE) for request in self.harness.window_manager.requests)
        )
        self.assertTrue(any("Entering macro: Reusable Setup" in m for m in self.harness.messages))
        self.assertTrue(any("Finished macro: Reusable Setup" in m for m in self.harness.messages))

    def test_child_does_not_supply_expected_size_when_parent_has_none(self) -> None:
        child = Macro(
            name="Child",
            expected_window_size={"width": 1, "height": 1},
            blocks=[key_block("child")],
        )
        child_path = self.save(child, "Child.json")
        parent = Macro(
            name="Parent",
            target_window=PARENT_TARGET,
            expected_window_size=None,
            blocks=[call_block(self.storage.to_reference(child_path))],
        )
        self.save(parent, "Parent.json")

        self.harness.runner._run_macro(parent)

        self.assertTrue(
            all(expected is None for _target, expected in self.harness.window_manager.requests)
        )

    def test_nested_calls_finish_inside_out(self) -> None:
        macro_c = Macro(name="C", blocks=[key_block("C")])
        c_path = self.save(macro_c, "C.json")
        macro_b = Macro(
            name="B",
            blocks=[call_block(self.storage.to_reference(c_path)), key_block("B")],
        )
        b_path = self.save(macro_b, "B.json")
        macro_a = self.parent_macro(
            [call_block(self.storage.to_reference(b_path)), key_block("A")]
        )
        self.save(macro_a, "A.json")

        self.harness.runner._run_macro(macro_a)

        self.assertEqual(self.harness.input.keys, ["C", "B", "A"])

    def test_labels_and_gotos_are_scoped_per_macro(self) -> None:
        child_goto = MacroBlock.create("goto")
        child_goto.params["target_label"] = "end"
        child_label = MacroBlock.create("label")
        child_label.params["label_name"] = "end"
        child = Macro(
            name="Child",
            blocks=[child_goto, key_block("skip-child"), child_label, key_block("child")],
        )
        child_path = self.save(child, "Child.json")

        parent_goto = MacroBlock.create("goto")
        parent_goto.params["target_label"] = "end"
        parent_label = MacroBlock.create("label")
        parent_label.params["label_name"] = "end"
        parent = self.parent_macro(
            [
                call_block(self.storage.to_reference(child_path)),
                parent_goto,
                key_block("skip-parent"),
                parent_label,
                key_block("parent"),
            ]
        )
        self.save(parent, "Parent.json")

        self.harness.runner._run_macro(parent)

        self.assertEqual(self.harness.input.keys, ["child", "parent"])

    def test_missing_and_invalid_references_stop_with_clear_errors(self) -> None:
        missing_parent = self.parent_macro([call_block("macros/Missing.json")])
        self.harness.runner._run_macro(missing_parent)
        self.assertIn("Referenced macro file not found", self.harness.runner.stop_reason)

        invalid_path = self.storage.base_dir / "Invalid.json"
        invalid_path.write_text("{not valid json", encoding="utf-8")
        invalid_parent = self.parent_macro(
            [call_block(self.storage.to_reference(invalid_path))]
        )
        self.harness = RunnerHarness(self.storage)
        self.harness.runner._run_macro(invalid_parent)
        self.assertIn("Failed to load referenced macro", self.harness.runner.stop_reason)

    def test_recursive_call_is_detected_with_call_stack(self) -> None:
        parent = self.parent_macro([])
        parent_path = self.save(parent, "Parent.json")
        parent.blocks.append(call_block(self.storage.to_reference(parent_path)))
        self.save(parent, "Parent.json")

        self.harness.runner._run_macro(parent)

        self.assertIn("Recursive macro call detected", self.harness.runner.stop_reason)
        self.assertIn("Parent -> Parent", self.harness.runner.stop_reason)

    def test_indirect_recursive_call_is_detected(self) -> None:
        macro_a = self.parent_macro([])
        a_path = self.save(macro_a, "A.json")
        macro_b = Macro(name="B", blocks=[call_block(self.storage.to_reference(a_path))])
        b_path = self.save(macro_b, "B.json")
        macro_a.blocks.append(call_block(self.storage.to_reference(b_path)))
        self.save(macro_a, "A.json")

        self.harness.runner._run_macro(macro_a)

        self.assertIn("Recursive macro call detected", self.harness.runner.stop_reason)
        self.assertIn("Parent -> B -> Parent", self.harness.runner.stop_reason)

    def test_child_failure_stops_parent_with_child_context(self) -> None:
        child = Macro(
            name="Broken Child",
            blocks=[MacroBlock(type="unknown_block", name="Broken Step")],
        )
        child_path = self.save(child, "Broken Child.json")
        parent = self.parent_macro([call_block(self.storage.to_reference(child_path))])
        self.save(parent, "Parent.json")

        self.harness.runner._run_macro(parent)

        self.assertIn("Child macro failed: Broken Child", self.harness.runner.stop_reason)
        self.assertIn("Unknown block type", self.harness.runner.stop_reason)
        self.assertTrue(any("Parent macro stopped: Parent" in m for m in self.harness.messages))

    def test_stop_during_child_stops_whole_run(self) -> None:
        wait = MacroBlock.create("wait")
        wait.params["duration_ms"] = 5000
        child = Macro(name="Long Child", blocks=[wait])
        child_path = self.save(child, "Long Child.json")
        parent = self.parent_macro([call_block(self.storage.to_reference(child_path))])
        self.save(parent, "Parent.json")

        self.harness.runner.start(parent)
        deadline = time.monotonic() + 2
        while not any("Entering macro: Long Child" in m for m in self.harness.messages):
            if time.monotonic() >= deadline:
                self.fail("Child macro did not start.")
            time.sleep(0.01)
        self.harness.runner.stop("Test stop.")
        self.harness.runner.thread.join(timeout=2)

        self.assertFalse(self.harness.runner.is_running)
        self.assertTrue(
            any(
                "Macro stopped while running child macro: Long Child" in message
                for message in self.harness.messages
            )
        )
        self.assertTrue(any("Execution stopped: Test stop." in m for m in self.harness.messages))

    def test_reference_paths_are_relative_inside_project_and_round_trip(self) -> None:
        child = Macro(name="Child", blocks=[key_block("child")])
        child_path = self.save(child, "Folder Friendly.json")
        reference = self.storage.to_reference(child_path)
        block = call_block(reference)
        loaded = Macro.from_dict(Macro(blocks=[block]).to_dict())

        self.assertEqual(reference, "macros/Folder Friendly.json")
        self.assertEqual(loaded.blocks[0].params["macro_path"], reference)
        clone = loaded.blocks[0].clone()
        self.assertEqual(clone.params["macro_path"], reference)
        self.assertIsNot(clone.params, loaded.blocks[0].params)
        self.assertEqual(
            block_display_name(clone),
            "Run Saved Macro: Folder Friendly",
        )


if __name__ == "__main__":
    unittest.main()
