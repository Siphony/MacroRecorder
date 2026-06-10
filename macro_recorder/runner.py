from __future__ import annotations

import threading
import time
from typing import Callable, Iterable, Optional

from .change_detection import RegionChangeResult, compare_captured_frames
from .map_classification import (
    MapClassificationError,
    classify_map_patch,
    format_classification_log,
)
from .models import (
    Macro,
    MacroBlock,
    block_summary,
    color_to_hex,
    color_to_rgb_text,
    control_flow_errors,
    find_block,
    normalize_label_name,
    normalize_region,
    root_label_indices,
)
from .pixel_sampling import PixelSampleResult, sample_pixel_for_params
from .region_detection import (
    RegionCheckResult,
    check_region_for_params,
    region_colour_diagnostics,
    region_mode_details,
)
from .storage import MacroStorage
from .vision_backend import ScreenAnalysisBackend
from .win32_automation import AutomationError, InputController, WindowManager


LogCallback = Callable[[str], None]
StateCallback = Callable[[bool], None]


class MacroStopped(RuntimeError):
    pass


class MacroRunner:
    def __init__(
        self,
        window_manager: WindowManager,
        input_controller: InputController,
        screen_analysis: ScreenAnalysisBackend,
        log_callback: Optional[LogCallback] = None,
        state_callback: Optional[StateCallback] = None,
        storage: Optional[MacroStorage] = None,
    ) -> None:
        self.window_manager = window_manager
        self.input_controller = input_controller
        self.screen_analysis = screen_analysis
        self.log_callback = log_callback or (lambda message: None)
        self.state_callback = state_callback or (lambda running: None)
        self.storage = storage or MacroStorage()
        self.cancel_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self._macro: Optional[Macro] = None
        self.stop_reason: Optional[str] = None
        self._active_target_window = None
        self._active_expected_window_size = None
        self._active_context_set = False
        self._call_stack: list[tuple[str, str]] = []

    @property
    def is_running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, macro: Macro, start_block_id: Optional[str] = None) -> None:
        if self.is_running:
            self.log("A macro is already running.")
            return
        self._macro = macro
        self.cancel_event.clear()
        self.stop_reason = None
        self.thread = threading.Thread(
            target=self._run_macro, args=(macro, start_block_id), daemon=True
        )
        self.thread.start()

    def stop(self, reason: str = "Stop button clicked.") -> None:
        if not self.stop_reason:
            self.stop_reason = reason
        if not self.cancel_event.is_set():
            self.log(f"Stop requested: {self.stop_reason}")
        self.cancel_event.set()

    def log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_callback(f"[{timestamp}] {message}")

    def _run_macro(self, macro: Macro, start_block_id: Optional[str] = None) -> None:
        self.state_callback(True)
        self.log(f"Starting macro: {macro.name}")
        try:
            validation_errors = control_flow_errors(macro)
            if validation_errors:
                raise AutomationError(
                    "Invalid Label/Goto control flow: " + " ".join(validation_errors)
                )
            self._active_target_window = macro.target_window
            self._active_expected_window_size = macro.expected_window_size
            self._active_context_set = True
            self._call_stack = [(self._macro_identity(macro), macro.name)]
            target = self._target(macro)
            self.log(
                "Target bound: "
                f"{target.title} ({target.client_width}x{target.client_height})"
            )
            root_start_index = 0
            nested_blocks = None
            if start_block_id:
                found = find_block(macro.blocks, start_block_id)
                if not found:
                    raise AutomationError("Start block was not found in this macro.")
                block, owner, parent, _ = found
                start_index = owner.index(block)
                if parent is None and owner is macro.blocks:
                    root_start_index = start_index
                else:
                    nested_blocks = owner[start_index:]
                self.log(
                    "Running macro from block: "
                    f"{block.label()} ({block_summary(block)})"
                )
            if nested_blocks is not None:
                self._execute_blocks(macro, nested_blocks)
            else:
                self._execute_root_blocks(macro, root_start_index)
            self._check_stop()
            self.log("Macro finished.")
        except MacroStopped:
            reason = self.stop_reason or "Stop requested."
            self.log(f"Execution stopped: {reason}")
        except AutomationError as exc:
            self.stop_reason = str(exc)
            self.log(f"Error: {exc}")
        except Exception as exc:  # Defensive: surface unexpected failures in the UI.
            self.stop_reason = f"Unexpected error: {exc}"
            self.log(f"Unexpected error: {exc}")
        finally:
            self.cancel_event.set()
            self._active_target_window = None
            self._active_expected_window_size = None
            self._active_context_set = False
            self._call_stack = []
            self.state_callback(False)

    def _execute_root_blocks(self, macro: Macro, start_index: int = 0) -> None:
        labels = root_label_indices(macro)
        index = max(0, int(start_index))
        goto_count = 0
        while index < len(macro.blocks):
            self._check_stop()
            block = macro.blocks[index]
            should_log_control_flow = goto_count < 20 or goto_count % 100 == 0
            if block.type not in {"label", "goto"} or should_log_control_flow:
                self.log(f"Run: {block.label()} ({block_summary(block)})")
            if block.type == "label":
                if should_log_control_flow:
                    self.log(
                        f"Label: '{normalize_label_name(block.params.get('label_name'))}'"
                    )
                index += 1
                continue
            if block.type == "goto":
                target = normalize_label_name(block.params.get("target_label"))
                target_index = labels.get(target)
                if target_index is None:
                    raise AutomationError(f"Goto target label '{target}' was not found.")
                if should_log_control_flow:
                    self.log(f"Goto: jumping to label '{target}'")
                goto_count += 1
                if goto_count % 1000 == 0:
                    self.log(
                        f"Goto loop has executed {goto_count} jumps; "
                        "emergency stop remains available."
                    )
                index = target_index + 1
                self._responsive_sleep(5)
                continue
            self._execute_block(macro, block)
            index += 1

    def _execute_blocks(self, macro: Macro, blocks: Iterable[MacroBlock]) -> None:
        for block in blocks:
            self._check_stop()
            self.log(f"Run: {block.label()} ({block_summary(block)})")
            self._execute_block(macro, block)

    def _execute_block(self, macro: Macro, block: MacroBlock) -> None:
        params = block.params
        if block.type == "click":
            target = self._target(macro)
            self.input_controller.click(
                target,
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                str(params.get("button", "left")),
                int(params.get("click_count", 1)),
            )
            self._delay_after(params)
            return

        if block.type == "move_mouse":
            target = self._target(macro)
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            duration_ms = max(0, int(params.get("movement_duration_ms", 150) or 0))
            self.log(f"[MoveMouse] Moving to ({x}, {y}) over {duration_ms} ms")
            self.input_controller.move_mouse(
                target, x, y, duration_ms, stop_check=self._check_stop
            )
            return

        if block.type == "move_and_click":
            target = self._target(macro)
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            button = str(params.get("button", "left"))
            click_count = int(params.get("click_count", 1))
            duration_ms = max(0, int(params.get("movement_duration_ms", 150) or 0))
            self.log(
                f"[MoveAndClick] Moving to ({x}, {y}) over {duration_ms} ms, "
                f"then {button} click x{click_count}"
            )
            self.input_controller.move_mouse(
                target, x, y, duration_ms, stop_check=self._check_stop
            )
            self._check_stop()
            self.input_controller.click(target, x, y, button, click_count)
            self._delay_after(params)
            return

        if block.type == "key_press":
            target = self._target(macro)
            self.input_controller.key_press(
                target,
                str(params.get("key", "")),
                int(params.get("press_count", 1)),
            )
            self._delay_after(params)
            return

        if block.type == "wait":
            self._responsive_sleep(int(params.get("duration_ms", 0)))
            return

        if block.type == "wait_pixel":
            self._wait_for_pixel(macro, block)
            return

        if block.type == "if_pixel":
            if self._pixel_matches(macro, block):
                self.log("If condition matched; running then-blocks.")
                self._execute_blocks(macro, block.children)
            elif block.else_children:
                self.log("If condition did not match; running else-blocks.")
                self._execute_blocks(macro, block.else_children)
            else:
                self.log("If condition did not match.")
            return

        if block.type == "wait_region":
            self._wait_for_region(macro, block)
            return

        if block.type == "wait_stable":
            self._wait_until_region_stable(macro, block)
            return

        if block.type == "click_until_change":
            self._click_until_region_changes(macro, block)
            return

        if block.type == "if_region":
            if self._region_matches(macro, block):
                self.log("Region condition matched; running then-blocks.")
                self._execute_blocks(macro, block.children)
            elif block.else_children:
                self.log("Region condition did not match; running else-blocks.")
                self._execute_blocks(macro, block.else_children)
            else:
                self.log("Region condition did not match.")
            return

        if block.type == "repeat":
            count = max(0, int(params.get("repeat_count", 0)))
            for index in range(count):
                self._check_stop()
                self.log(f"Repeat {index + 1}/{count}")
                self._execute_blocks(macro, block.children)
            return

        if block.type == "run_macro":
            self._run_saved_macro(macro, block)
            return

        if block.type == "classify_map_run":
            self._classify_map_and_run_macro(macro, block)
            return

        if block.type == "stop":
            self.stop_reason = "Stop block reached."
            raise MacroStopped()

        if block.type in {"label", "goto"}:
            raise AutomationError(
                f"{block.label()} is nested. Label and Goto blocks are root-level only."
            )

        raise AutomationError(f"Unknown block type: {block.type}")

    def _wait_for_pixel(self, macro: Macro, block: MacroBlock) -> None:
        params = block.params
        interval_ms = max(20, int(params.get("check_interval_ms", 100) or 100))
        timeout_value = params.get("timeout_ms")
        timeout_ms = None if timeout_value in ("", None) else int(timeout_value)
        deadline = None if timeout_ms is None else time.monotonic() + timeout_ms / 1000
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))
        self.log(
            "[PixelWaitStart] WaitForPixelMatch\n"
            f"Relative Coord: ({x}, {y})\n"
            f"Expected: {params.get('expected_color', '#000000')}\n"
            f"Configured tolerance: {params.get('tolerance', 0)}\n"
            f"Sampling: {params.get('sampling_mode', 'Single Pixel')}\n"
            f"Check interval: {interval_ms} ms\n"
            f"Timeout: {'none' if timeout_ms is None else f'{timeout_ms} ms'}"
        )
        check_count = 0
        last_failed_log_time = 0.0
        last_result: Optional[PixelSampleResult] = None

        while True:
            self._check_stop()
            result = self._pixel_check(macro, block)
            last_result = result
            check_count += 1
            now = time.monotonic()
            should_log = (
                check_count == 1
                or result.matched
                or now - last_failed_log_time >= 1.0
            )
            if should_log:
                self._log_pixel_check(result)
                last_failed_log_time = now
            if result.matched:
                self.log("Pixel matched.")
                self._after_success_delay(params)
                return
            if deadline is not None and time.monotonic() >= deadline:
                behavior = str(params.get("timeout_behavior", "fail")).lower()
                if last_result:
                    self._save_debug_capture(
                        last_result.capture,
                        f"{macro.name}_pixel_wait_{block.label()}_"
                        f"x{last_result.relative_x}_y{last_result.relative_y}",
                        "timeout",
                    )
                    self._log_pixel_timeout(timeout_ms or 0, last_result)
                if behavior == "continue":
                    self.log("Pixel wait timed out; continuing.")
                    return
                raise AutomationError("Pixel wait timed out.")
            self._responsive_sleep(interval_ms)

    def _pixel_matches(
        self, macro: Macro, block: MacroBlock, log_result: bool = True
    ) -> bool:
        result = self._pixel_check(macro, block)
        if log_result:
            self._log_pixel_check(result)
        return result.matched

    def _pixel_check(self, macro: Macro, block: MacroBlock) -> PixelSampleResult:
        params = block.params
        target = self._target(macro)
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))
        return sample_pixel_for_params(
            self.window_manager,
            self.screen_analysis,
            target,
            x,
            y,
            params,
            block.type,
        )

    def _log_pixel_check(self, result: PixelSampleResult) -> None:
        block_name = self._pixel_block_log_name(result.block_type)
        outcome = "MATCH" if result.matched else "NO MATCH"
        closest_line = ""
        if result.closest_offset:
            dx, dy = result.closest_offset
            closest_line = f"Closest Offset: ({dx:+d}, {dy:+d})\n"
        self.log(
            "[PixelCheck]\n"
            f"Block: {block_name}\n"
            f"Target Window: {result.target_title}\n"
            f"Sampling: {result.sampling_mode}\n"
            f"Sample size: {result.sample_size}x{result.sample_size} ({result.sample_count} pixels read)\n"
            f"Relative Coord: ({result.relative_x}, {result.relative_y})\n"
            f"Resolved Screen Coord: ({result.screen_x}, {result.screen_y})\n"
            f"{closest_line}"
            f"Expected: {color_to_hex(result.expected_rgb)} {color_to_rgb_text(result.expected_rgb)}\n"
            f"{result.sampled_label()}:   {color_to_hex(result.sampled_rgb)} {color_to_rgb_text(result.sampled_rgb)}\n"
            f"Configured tolerance: {result.configured_tolerance}\n"
            f"Required tolerance: {result.required_tolerance}\n"
            f"Result: {outcome}"
        )

    def _log_pixel_timeout(self, timeout_ms: int, result: PixelSampleResult) -> None:
        seconds = timeout_ms / 1000
        self.log(
            "WaitForPixelMatch timed out "
            f"after {seconds:g}s.\n"
            f"Expected {color_to_hex(result.expected_rgb)} at relative "
            f"({result.relative_x}, {result.relative_y}).\n"
            f"Sampling was {result.sampling_mode}.\n"
            f"Final sampled colour was {color_to_hex(result.sampled_rgb)} "
            f"{color_to_rgb_text(result.sampled_rgb)}.\n"
            f"Configured tolerance was {result.configured_tolerance}.\n"
            f"Required tolerance for final colour was {result.required_tolerance}."
        )

    def _pixel_block_log_name(self, block_type: str) -> str:
        return {
            "wait_pixel": "WaitForPixelMatch",
            "if_pixel": "IfPixelMatch",
        }.get(block_type, block_type)

    def _wait_for_region(self, macro: Macro, block: MacroBlock) -> None:
        params = block.params
        interval_ms = max(20, int(params.get("check_interval_ms", 100) or 100))
        timeout_value = params.get("timeout_ms")
        timeout_ms = None if timeout_value in ("", None) else int(timeout_value)
        deadline = None if timeout_ms is None else time.monotonic() + timeout_ms / 1000
        self.log(
            "[RegionWaitStart] WaitForRegionColourMatch\n"
            f"Region: x1={params.get('x1', 0)} y1={params.get('y1', 0)} "
            f"x2={params.get('x2', 0)} y2={params.get('y2', 0)}\n"
            f"Mode: {params.get('detection_mode', 'Green Dominance')}\n"
            f"Required match: {params.get('minimum_match_percent', 0)}%\n"
            f"Sample step: {params.get('sample_step', 1)}\n"
            f"Check interval: {interval_ms} ms\n"
            f"Timeout: {'none' if timeout_ms is None else f'{timeout_ms} ms'}"
        )
        check_count = 0
        last_failed_log_time = 0.0
        last_result: Optional[RegionCheckResult] = None

        while True:
            self._check_stop()
            result = self._region_check(macro, block)
            last_result = result
            check_count += 1
            now = time.monotonic()
            should_log = (
                check_count == 1
                or result.matched
                or now - last_failed_log_time >= 1.0
            )
            if should_log:
                self._log_region_check(result)
                last_failed_log_time = now
            if result.matched:
                self.log("Region matched.")
                self._after_success_delay(params)
                return
            if deadline is not None and time.monotonic() >= deadline:
                behavior = str(params.get("timeout_behavior", "fail")).lower()
                if last_result:
                    self._save_debug_capture(
                        last_result.capture,
                        f"{macro.name}_region_wait_{block.label()}_"
                        f"{last_result.left}_{last_result.top}_"
                        f"{last_result.right}_{last_result.bottom}",
                        "timeout",
                    )
                    self._log_region_timeout(timeout_ms or 0, last_result)
                if behavior == "continue":
                    self.log("Region wait timed out; continuing.")
                    return
                raise AutomationError("Region wait timed out.")
            self._responsive_sleep(interval_ms)

    def _region_matches(self, macro: Macro, block: MacroBlock) -> bool:
        result = self._region_check(macro, block)
        self._log_region_check(result)
        return result.matched

    def _region_check(self, macro: Macro, block: MacroBlock) -> RegionCheckResult:
        return check_region_for_params(
            self.window_manager,
            self.screen_analysis,
            self._target(macro),
            block.params,
            block.type,
        )

    def _log_region_check(self, result: RegionCheckResult) -> None:
        average_required_line = ""
        if result.average_required_tolerance is not None:
            average_required_line = (
                f"Average required tolerance: {result.average_required_tolerance}\n"
            )
        self.log(
            "[RegionCheck]\n"
            f"Block: {self._region_block_log_name(result.block_type)}\n"
            f"Target Window: {result.target_title}\n"
            f"Region: left={result.left} top={result.top} right={result.right} bottom={result.bottom}\n"
            f"Screen Region: left={result.screen_left} top={result.screen_top} "
            f"right={result.screen_right} bottom={result.screen_bottom}\n"
            f"Window Bounds: X={result.window_left} Y={result.window_top} "
            f"W={result.window_width} H={result.window_height}\n"
            f"Client Bounds: X={result.client_left} Y={result.client_top} "
            f"W={result.client_width} H={result.client_height}\n"
            f"DPI: {result.dpi if result.dpi is not None else 'unknown'}\n"
            f"Size: {result.width}x{result.height}\n"
            f"{region_mode_details(result)}\n"
            f"Sample step: {result.sample_step}\n"
            f"Expected sampled pixels: {result.expected_sampled_pixels}\n"
            f"Sampled pixels: {result.sampled_pixels}\n"
            f"Average sampled: {color_to_hex(result.average_rgb)} {color_to_rgb_text(result.average_rgb)}\n"
            f"Min RGB: {color_to_rgb_text(result.min_rgb)}\n"
            f"Max RGB: {color_to_rgb_text(result.max_rgb)}\n"
            f"{region_colour_diagnostics(result)}\n"
            f"{average_required_line}"
            f"Required match: {result.minimum_match_percent:g}%\n"
            f"Actual match: {result.actual_match_percent:.1f}%\n"
            f"Matching pixels: {result.matching_pixels} / {result.sampled_pixels}\n"
            f"Elapsed: {result.elapsed_ms:.0f} ms\n"
            f"Result: {result.result_text()}"
        )

    def _log_region_timeout(self, timeout_ms: int, result: RegionCheckResult) -> None:
        seconds = timeout_ms / 1000
        self.log(
            "WaitForRegionColourMatch timed out "
            f"after {seconds:g}s.\n"
            f"Region: left={result.left} top={result.top} right={result.right} bottom={result.bottom}\n"
            f"Mode: {result.detection_mode}\n"
            f"Required match: {result.minimum_match_percent:g}%\n"
            f"Final actual match: {result.actual_match_percent:.1f}%\n"
            f"Matching pixels: {result.matching_pixels} / {result.sampled_pixels}\n"
            f"Average sampled: {color_to_hex(result.average_rgb)} {color_to_rgb_text(result.average_rgb)}\n"
            f"{region_colour_diagnostics(result)}\n"
            f"Elapsed on final check: {result.elapsed_ms:.0f} ms\n"
            "Result: NO MATCH"
        )

    def _region_block_log_name(self, block_type: str) -> str:
        return {
            "wait_region": "WaitForRegionColourMatch",
            "if_region": "IfRegionColourMatch",
        }.get(block_type, block_type)

    def _wait_until_region_stable(self, macro: Macro, block: MacroBlock) -> None:
        params = block.params
        stable_duration_ms = max(0, int(params.get("stable_duration_ms", 300) or 0))
        interval_ms = max(20, int(params.get("check_interval_ms", 100) or 100))
        change_threshold = max(0, min(255, int(params.get("change_threshold", 25) or 0)))
        maximum_changed = max(
            0.0, min(100.0, float(params.get("maximum_changed_percent", 2) or 0))
        )
        timeout_value = params.get("timeout_ms")
        timeout_ms = None if timeout_value in ("", None) else max(0, int(timeout_value))
        started = time.monotonic()
        deadline = None if timeout_ms is None else started + timeout_ms / 1000
        previous, region, target_title = self._capture_change_region(macro, params)
        stable_time_ms = 0.0
        previous_time = time.monotonic()
        last_progress_log = 0.0
        comparison_count = 0

        self.log(
            "[WaitUntilRegionStable]\n"
            f"Target Window: {target_title}\n"
            f"Region: {self._format_region(region)}\n"
            f"Stable duration required: {stable_duration_ms} ms\n"
            f"Check interval: {interval_ms} ms\n"
            f"Pixel change threshold: {change_threshold}\n"
            f"Maximum changed pixels: {maximum_changed:g}%\n"
            f"Timeout: {'none' if timeout_ms is None else f'{timeout_ms} ms'}"
        )
        if stable_duration_ms == 0:
            self.log("[WaitUntilRegionStable] Result: STABLE (zero duration required)")
            self._after_success_delay(params)
            return

        while True:
            self._responsive_sleep(interval_ms)
            current, current_region, _ = self._capture_change_region(macro, params)
            now = time.monotonic()
            result = compare_captured_frames(previous, current, change_threshold)
            comparison_count += 1
            comparison_elapsed_ms = (now - previous_time) * 1000
            was_stable = stable_time_ms > 0
            stability_reset = False
            if result.stable_enough(maximum_changed):
                stable_time_ms += comparison_elapsed_ms
            else:
                stability_reset = was_stable
                stable_time_ms = 0.0
            elapsed_ms = (now - started) * 1000
            should_log = (
                comparison_count == 1
                or (was_stable and stable_time_ms == 0)
                or now - last_progress_log >= 1.0
            )
            if should_log:
                self.log(
                    "[WaitUntilRegionStable]\n"
                    f"Region: {self._format_region(current_region)}\n"
                    f"Changed pixels: {result.changed_pixels} / {result.sampled_pixels} "
                    f"({result.changed_percent:.2f}%)\n"
                    f"Maximum changed: {maximum_changed:g}%\n"
                    f"Stable time so far: {stable_time_ms:.0f} / {stable_duration_ms} ms\n"
                    f"State: {'stability reset' if stability_reset else 'waiting'}\n"
                    f"Elapsed: {elapsed_ms:.0f} ms"
                )
                last_progress_log = now
            if stable_time_ms >= stable_duration_ms:
                self.log(
                    "[WaitUntilRegionStable]\n"
                    f"Current changed percentage: {result.changed_percent:.2f}%\n"
                    f"Stable time: {stable_time_ms:.0f} ms\n"
                    f"Elapsed: {elapsed_ms:.0f} ms\n"
                    "Result: STABLE"
                )
                self._after_success_delay(params)
                return
            if deadline is not None and now >= deadline:
                self._save_debug_capture(
                    current,
                    f"{macro.name}_stable_wait_{block.label()}",
                    "timeout",
                )
                self.log(
                    "[WaitUntilRegionStable]\n"
                    f"Current changed percentage: {result.changed_percent:.2f}%\n"
                    f"Stable time: {stable_time_ms:.0f} / {stable_duration_ms} ms\n"
                    f"Elapsed: {elapsed_ms:.0f} ms\n"
                    "Result: TIMEOUT"
                )
                if str(params.get("timeout_behavior", "fail")).lower() == "continue":
                    self.log("Region stability wait timed out; continuing.")
                    return
                raise AutomationError("Wait Until Region Stable timed out.")
            previous = current
            previous_time = now

    def _click_until_region_changes(self, macro: Macro, block: MacroBlock) -> None:
        params = block.params
        attempts = max(1, int(params.get("retry_count", 3) or 1))
        post_click_delay_ms = max(0, int(params.get("post_click_delay_ms", 250) or 0))
        check_interval_ms = max(20, int(params.get("check_interval_ms", 100) or 100))
        check_timeout_ms = max(0, int(params.get("check_timeout_ms", 1000) or 0))
        retry_delay_ms = max(0, int(params.get("retry_delay_ms", 250) or 0))
        change_threshold = max(0, min(255, int(params.get("change_threshold", 25) or 0)))
        required_changed = max(
            0.0, min(100.0, float(params.get("required_changed_percent", 5) or 0))
        )
        baseline, region, target_title = self._capture_change_region(macro, params)
        final_result: Optional[RegionChangeResult] = None
        final_capture = baseline

        self.log(
            "[ClickUntilRegionChanges]\n"
            f"Target Window: {target_title}\n"
            f"Click: ({params.get('x', 0)}, {params.get('y', 0)}) "
            f"{params.get('button', 'left')} x{params.get('click_count', 1)}\n"
            f"Watch Region: {self._format_region(region)}\n"
            f"Pixel change threshold: {change_threshold}\n"
            f"Required changed pixels: {required_changed:g}%\n"
            f"Attempts: {attempts}"
        )

        for attempt in range(1, attempts + 1):
            self._check_stop()
            self._save_debug_capture(
                baseline,
                f"{macro.name}_{block.label()}_attempt_{attempt}_before",
                "before",
            )
            self.log(
                "[ClickUntilRegionChanges]\n"
                f"Attempt {attempt}/{attempts}\n"
                f"Click: ({params.get('x', 0)}, {params.get('y', 0)})\n"
                f"Watch Region: {self._format_region(region)}\n"
                f"Post-click delay: {post_click_delay_ms} ms\n"
                f"Check timeout: {check_timeout_ms} ms"
            )
            target = self._target(macro)
            self.input_controller.click(
                target,
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                str(params.get("button", "left")),
                int(params.get("click_count", 1)),
            )
            self._responsive_sleep(post_click_delay_ms)

            check_deadline = time.monotonic() + check_timeout_ms / 1000
            best_result: Optional[RegionChangeResult] = None
            best_capture = baseline
            while True:
                current, current_region, _ = self._capture_change_region(macro, params)
                result = compare_captured_frames(baseline, current, change_threshold)
                if best_result is None or result.changed_percent > best_result.changed_percent:
                    best_result = result
                    best_capture = current
                if result.changed_enough(required_changed):
                    self._save_debug_capture(
                        current,
                        f"{macro.name}_{block.label()}_attempt_{attempt}_after",
                        "success",
                    )
                    self.log(
                        "[ClickUntilRegionChanges]\n"
                        f"Attempt {attempt}/{attempts}\n"
                        f"Watch Region: {self._format_region(current_region)}\n"
                        f"Changed pixels: {result.changed_pixels} / {result.sampled_pixels} "
                        f"({result.changed_percent:.2f}%)\n"
                        f"Required: {required_changed:g}%\n"
                        "Result: SUCCESS"
                    )
                    return
                if time.monotonic() >= check_deadline:
                    break
                self._responsive_sleep(check_interval_ms)

            final_result = best_result
            final_capture = best_capture
            if best_result is not None:
                self._save_debug_capture(
                    best_capture,
                    f"{macro.name}_{block.label()}_attempt_{attempt}_after",
                    "no_change",
                )
                self.log(
                    "[ClickUntilRegionChanges]\n"
                    f"Attempt {attempt}/{attempts}\n"
                    f"Changed pixels: {best_result.changed_pixels} / "
                    f"{best_result.sampled_pixels} ({best_result.changed_percent:.2f}%)\n"
                    f"Required: {required_changed:g}%\n"
                    + (
                        "Result: NO CHANGE, retrying"
                        if attempt < attempts
                        else "Result: NO CHANGE"
                    )
                )
            baseline = best_capture
            if attempt < attempts:
                self._responsive_sleep(retry_delay_ms)

        final_percent = final_result.changed_percent if final_result else 0.0
        self._save_debug_capture(
            final_capture,
            f"{macro.name}_{block.label()}_final",
            "failed",
        )
        raise AutomationError(
            "Click Until Region Changes failed "
            f"after {attempts} attempts. Final changed percentage: {final_percent:.2f}%."
        )

    def _capture_change_region(self, macro: Macro, params):
        target = self._target(macro)
        region = normalize_region(
            params.get("x1", 0),
            params.get("y1", 0),
            params.get("x2", 0),
            params.get("y2", 0),
        )
        return (
            self.screen_analysis.capture_target_region(target, *region),
            region,
            target.title,
        )

    def _format_region(self, region) -> str:
        left, top, right, bottom = region
        return f"left={left} top={top} right={right} bottom={bottom}"

    def _run_saved_macro(self, parent_macro: Macro, block: MacroBlock) -> None:
        reference = str(block.params.get("macro_path", "") or "").strip()
        child, path, identity, child_name = self._validate_saved_macro_reference(
            reference
        )
        if (
            child.expected_window_size
            and self._active_expected_window_size
            and child.expected_window_size != self._active_expected_window_size
        ):
            self.log(
                "[RunSavedMacro] Target-size note: "
                f"'{child_name}' was saved for "
                f"{child.expected_window_size.get('width', '?')}x"
                f"{child.expected_window_size.get('height', '?')}, "
                "but it will use the parent macro's active target and expected size."
            )

        self.log(
            f"[RunSavedMacro] Entering macro: {child_name} ({reference})"
        )
        self._call_stack.append((identity, child_name))
        try:
            self._execute_root_blocks(child)
            self._check_stop()
        except MacroStopped:
            self.log(f"Macro stopped while running child macro: {child_name}")
            raise
        except AutomationError as exc:
            self.log(
                f"[RunSavedMacro] Child macro failed: {child_name}\n"
                f"Reason: {exc}\n"
                f"Parent macro stopped: {parent_macro.name}"
            )
            raise AutomationError(
                f"Child macro failed: {child_name}. Reason: {exc}"
            ) from exc
        finally:
            self._call_stack.pop()
        self.log(f"[RunSavedMacro] Finished macro: {child_name}")

    def _classify_map_and_run_macro(self, macro: Macro, block: MacroBlock) -> None:
        params = block.params
        target = self._target(macro)
        region = normalize_region(
            params.get("x1", 0),
            params.get("y1", 0),
            params.get("x2", 0),
            params.get("y2", 0),
        )
        capture = self.screen_analysis.capture_target_region(target, *region)
        reference_value = str(params.get("reference_folder", "") or "").strip()
        if not reference_value:
            raise AutomationError("Classify Map And Run Macro has no reference folder.")
        reference_folder = self.storage.resolve_reference(reference_value)
        try:
            result = classify_map_patch(
                capture.bgr,
                reference_folder,
                enable_multi_scale=_as_bool(params.get("enable_multi_scale", True)),
                scale_min=float(params.get("scale_min", 0.90)),
                scale_max=float(params.get("scale_max", 1.10)),
                scale_step=float(params.get("scale_step", 0.05)),
                stop_check=self._check_stop,
            )
        except MapClassificationError as exc:
            self._save_debug_capture(capture, f"{macro.name}_classify_map_runtime", "error")
            raise AutomationError(f"Map classification failed: {exc}") from exc

        minimum_best = float(params.get("minimum_best_score", 0.75))
        minimum_margin = float(params.get("minimum_score_margin", 0.05))
        self.log(
            format_classification_log(
                result,
                heading="ClassifyMapAndRunMacro",
                reference_folder=reference_folder,
                region=region,
                minimum_best_score=minimum_best,
                minimum_margin=minimum_margin,
            )
        )
        best_id = result.best.map_id if result.best else "unknown"
        confidence_passed = result.passes(minimum_best, minimum_margin)
        self._save_debug_capture(
            capture,
            f"{macro.name}_classify_map_runtime",
            best_id if confidence_passed else f"low_confidence_{best_id}",
        )
        if not confidence_passed:
            raise AutomationError(
                "Map classification confidence was too low. "
                f"Best={result.best.score:.4f} "
                f"margin={result.margin:.4f}; no map was clicked or run."
            )

        mapping = params.get("map_macro_mapping") or {}
        if not isinstance(mapping, dict):
            raise AutomationError("Map-to-macro mapping must be a JSON object.")
        mapped_macro = _mapping_value(mapping, best_id)
        if not mapped_macro:
            raise AutomationError(
                f"Detected map '{best_id}' has no mapped saved macro."
            )
        self._validate_saved_macro_reference(str(mapped_macro))
        self.log(
            f"[ClassifyMapAndRunMacro] Detected map: {best_id}; "
            f"mapped macro: {mapped_macro}"
        )

        if _as_bool(params.get("click_before_run", True)):
            x = int(params.get("map_click_x", 0))
            y = int(params.get("map_click_y", 0))
            duration_ms = max(0, int(params.get("movement_duration_ms", 150) or 0))
            self.log(
                f"[ClassifyMapAndRunMacro] Moving to map slot ({x}, {y}) "
                f"over {duration_ms} ms, then left click"
            )
            self.input_controller.move_mouse(
                target, x, y, duration_ms, stop_check=self._check_stop
            )
            self._check_stop()
            self.input_controller.click(target, x, y, "left", 1)
            self._responsive_sleep(
                max(0, int(params.get("post_click_delay_ms", 500) or 0))
            )

        call = MacroBlock.create("run_macro")
        call.params["macro_path"] = str(mapped_macro)
        self._run_saved_macro(macro, call)

    def _validate_saved_macro_reference(self, reference: str):
        reference = str(reference or "").strip()
        if not reference:
            raise AutomationError("Run Saved Macro has no referenced macro file.")
        path = self.storage.resolve_reference(reference)
        if not path.is_file():
            raise AutomationError(f"Referenced macro file not found: {reference}")
        try:
            child = self.storage.load(path)
        except Exception as exc:
            raise AutomationError(
                f"Failed to load referenced macro '{reference}': {exc}"
            ) from exc

        identity = self.storage.reference_identity(path)
        child_name = child.name or path.stem
        active_identities = {item[0] for item in self._call_stack}
        if identity in active_identities:
            stack_names = [item[1] for item in self._call_stack] + [child_name]
            raise AutomationError(
                "Recursive macro call detected. Call stack: "
                + " -> ".join(stack_names)
            )
        validation_errors = control_flow_errors(child)
        if validation_errors:
            raise AutomationError(
                f"Child macro '{child_name}' has invalid Label/Goto control flow: "
                + " ".join(validation_errors)
            )
        return child, path, identity, child_name

    def _macro_identity(self, macro: Macro) -> str:
        if macro.path:
            return self.storage.reference_identity(macro.path)
        return f"memory:{id(macro)}"

    def _target(self, macro: Macro):
        if self._active_context_set:
            target_window = self._active_target_window
            expected_size = self._active_expected_window_size
        else:
            target_window = macro.target_window
            expected_size = macro.expected_window_size
        return self.window_manager.require_ready(
            target_window,
            expected_size,
        )

    def _save_debug_capture(self, capture, label: str, result: str) -> None:
        path = self.screen_analysis.save_debug_capture(capture, label, result)
        if path:
            self.log(f"Saved debug capture: {path}")

    def _delay_after(self, params) -> None:
        self._responsive_sleep(int(params.get("delay_after_ms", 0) or 0))

    def _after_success_delay(self, params) -> None:
        duration_ms = max(0, int(params.get("after_success_delay_ms", 0) or 0))
        if duration_ms:
            self.log(f"Wait succeeded; delaying {duration_ms} ms before continuing.")
            self._responsive_sleep(duration_ms)

    def _responsive_sleep(self, duration_ms: int) -> None:
        end = time.monotonic() + max(0, duration_ms) / 1000
        while time.monotonic() < end:
            self._check_stop()
            time.sleep(min(0.05, max(0, end - time.monotonic())))

    def _check_stop(self) -> None:
        if self.cancel_event.is_set():
            raise MacroStopped()


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _mapping_value(mapping, map_id: str) -> Optional[str]:
    exact = mapping.get(map_id)
    if exact:
        return str(exact)
    wanted = str(map_id).casefold()
    for key, value in mapping.items():
        if str(key).casefold() == wanted and value:
            return str(value)
    return None
