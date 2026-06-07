from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from macro_recorder.change_detection import compare_bgr_frames
from macro_recorder.models import Macro, MacroBlock
from macro_recorder.runner import MacroRunner, MacroStopped
from macro_recorder.storage import MacroStorage
from macro_recorder.vision_backend import CapturedFrame
from macro_recorder.win32_automation import AutomationError, TargetWindowInfo


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


def frame(value: int = 0) -> CapturedFrame:
    return CapturedFrame(
        bgr=np.full((10, 10, 3), value, dtype=np.uint8),
        screen_left=100,
        screen_top=200,
        relative_left=0,
        relative_top=0,
    )


class FakeWindowManager:
    def require_ready(self, *_args, **_kwargs):
        return TARGET


class FakeInputController:
    def __init__(self) -> None:
        self.clicks = []

    def click(self, target, x, y, button, click_count) -> None:
        self.clicks.append((target, x, y, button, click_count))


class FakeScreenAnalysis:
    def __init__(self, captures) -> None:
        self.captures = list(captures)

    def capture_target_region(self, *_args):
        if not self.captures:
            raise AssertionError("Test requested more captures than expected.")
        return self.captures.pop(0)

    def save_debug_capture(self, *_args, **_kwargs):
        return None


class RecordingRunner(MacroRunner):
    def __init__(self, captures) -> None:
        self.messages = []
        self.input = FakeInputController()
        super().__init__(
            FakeWindowManager(),
            self.input,
            FakeScreenAnalysis(captures),
            log_callback=self.messages.append,
        )


class RegionChangeTests(unittest.TestCase):
    def test_change_percentage_uses_max_per_channel_difference(self) -> None:
        before = np.zeros((10, 10, 3), dtype=np.uint8)
        after = before.copy()
        after[:2, :, 1] = 30

        result = compare_bgr_frames(before, after, pixel_change_threshold=25)

        self.assertEqual(result.changed_pixels, 20)
        self.assertEqual(result.sampled_pixels, 100)
        self.assertAlmostEqual(result.changed_percent, 20.0)

    def test_wait_until_stable_resets_then_succeeds(self) -> None:
        runner = RecordingRunner([frame(0), frame(50), frame(50), frame(50)])
        block = MacroBlock.create("wait_stable")
        block.params.update(
            {
                "stable_duration_ms": 30,
                "check_interval_ms": 20,
                "change_threshold": 25,
                "maximum_changed_percent": 0,
                "timeout_ms": 500,
            }
        )

        runner._wait_until_region_stable(Macro(), block)

        self.assertTrue(any("Result: STABLE" in message for message in runner.messages))

    def test_wait_until_stable_respects_stop_event(self) -> None:
        runner = RecordingRunner([frame(0)])
        block = MacroBlock.create("wait_stable")
        block.params["check_interval_ms"] = 20
        runner.cancel_event.set()

        with self.assertRaises(MacroStopped):
            runner._wait_until_region_stable(Macro(), block)

    def test_verified_click_retries_then_succeeds(self) -> None:
        changed = frame(0)
        changed.bgr[:1, :, :] = 100
        runner = RecordingRunner([frame(0), frame(0), changed])
        block = MacroBlock.create("click_until_change")
        block.params.update(
            {
                "required_changed_percent": 5,
                "change_threshold": 25,
                "post_click_delay_ms": 0,
                "check_timeout_ms": 0,
                "retry_count": 2,
                "retry_delay_ms": 0,
            }
        )

        runner._click_until_region_changes(Macro(), block)

        self.assertEqual(len(runner.input.clicks), 2)
        self.assertTrue(any("Result: SUCCESS" in message for message in runner.messages))

    def test_verified_click_fails_after_configured_attempts(self) -> None:
        runner = RecordingRunner([frame(0), frame(0), frame(0)])
        block = MacroBlock.create("click_until_change")
        block.params.update(
            {
                "required_changed_percent": 5,
                "post_click_delay_ms": 0,
                "check_timeout_ms": 0,
                "retry_count": 2,
                "retry_delay_ms": 0,
            }
        )

        with self.assertRaisesRegex(AutomationError, "failed after 2 attempts"):
            runner._click_until_region_changes(Macro(), block)

        self.assertEqual(len(runner.input.clicks), 2)

    def test_existing_macro_loads_with_zero_after_success_delay(self) -> None:
        path = Path("macros/Easy_Odyssey_1.json")
        macro = MacroStorage().load(path)

        wait_blocks = [
            block
            for block in macro.all_blocks()
            if block.type in {"wait_pixel", "wait_region"}
        ]
        self.assertTrue(wait_blocks)
        self.assertTrue(
            all(block.params.get("after_success_delay_ms") == 0 for block in wait_blocks)
        )

    def test_new_blocks_round_trip_and_success_delay_is_responsive(self) -> None:
        stable = MacroBlock.create("wait_stable")
        stable.params["after_success_delay_ms"] = 375
        verified = MacroBlock.create("click_until_change")
        macro = Macro(blocks=[stable, verified])

        loaded = Macro.from_dict(macro.to_dict())

        self.assertEqual(loaded.blocks[0].params["after_success_delay_ms"], 375)
        self.assertEqual(loaded.blocks[1].params["retry_count"], 3)
        runner = RecordingRunner([])
        sleeps = []
        runner._responsive_sleep = sleeps.append
        runner._after_success_delay(loaded.blocks[0].params)
        self.assertEqual(sleeps, [375])


if __name__ == "__main__":
    unittest.main()
