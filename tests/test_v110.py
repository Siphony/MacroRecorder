from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from macro_recorder.app import MacroEditorApp
from macro_recorder.map_classification import (
    MapClassificationError,
    classify_map_patch,
    save_map_reference,
)
from macro_recorder.models import Macro, MacroBlock, block_summary
from macro_recorder.runner import MacroRunner
from macro_recorder.storage import MacroStorage
from macro_recorder.vision_backend import CapturedFrame
from macro_recorder.win32_automation import TargetWindowInfo


TARGET = TargetWindowInfo(
    hwnd=1,
    title="Active BTD6 Target",
    class_name="Test",
    client_left=100,
    client_top=200,
    client_width=1280,
    client_height=720,
    window_left=95,
    window_top=170,
    window_width=1290,
    window_height=755,
    dpi=96,
)
PARENT_TARGET = {"title": "Active BTD6 Target", "class_name": "Test", "hwnd": 1}
PARENT_SIZE = {"width": 1280, "height": 720}


def textured_patch(width: int = 60, height: int = 40, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    patch = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
    cv2.circle(patch, (width // 3, height // 2), min(width, height) // 5, (0, 220, 80), -1)
    cv2.line(patch, (0, 0), (width - 1, height - 1), (250, 30, 180), 2)
    return patch


def reference_with_patch(
    patch: np.ndarray, width: int = 180, height: int = 120, location=(37, 29)
) -> np.ndarray:
    reference = np.full((height, width, 3), 25, dtype=np.uint8)
    x, y = location
    reference[y : y + patch.shape[0], x : x + patch.shape[1]] = patch
    return reference


class FakeWindowManager:
    def __init__(self) -> None:
        self.requests = []

    def require_ready(self, target, expected_size):
        self.requests.append((target, expected_size))
        return TARGET


class FakeInputController:
    def __init__(self) -> None:
        self.calls = []

    def move_mouse(self, target, x, y, duration_ms, stop_check=None) -> None:
        self.calls.append(("move", target, x, y, duration_ms))
        if stop_check:
            stop_check()

    def click(self, target, x, y, button, click_count) -> None:
        self.calls.append(("click", target, x, y, button, click_count))

    def key_press(self, target, key, press_count) -> None:
        self.calls.append(("key", target, key, press_count))


class FakeScreenAnalysis:
    def __init__(self, patch: np.ndarray) -> None:
        self.patch = patch
        self.regions = []
        self.saved = []

    def capture_target_region(self, _target, *region):
        self.regions.append(region)
        return CapturedFrame(
            bgr=self.patch.copy(),
            screen_left=100,
            screen_top=200,
            relative_left=region[0],
            relative_top=region[1],
        )

    def save_debug_capture(self, capture, label, result, force=False):
        self.saved.append((capture.width, capture.height, label, result, force))
        return None


def key_block(key: str) -> MacroBlock:
    block = MacroBlock.create("key_press")
    block.params.update({"key": key, "delay_after_ms": 0})
    return block


class MapClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.references = self.root / "references"
        self.references.mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_reference(self, name: str, bgr: np.ndarray) -> Path:
        path = self.references / f"{name}.png"
        self.assertTrue(cv2.imwrite(str(path), bgr))
        return path

    def test_runtime_patch_is_found_inside_larger_reference(self) -> None:
        patch = textured_patch()
        self.write_reference("dark_castle", reference_with_patch(patch, location=(37, 29)))
        self.write_reference(
            "infernal", reference_with_patch(textured_patch(seed=99), location=(12, 8))
        )

        result = classify_map_patch(patch, self.references, enable_multi_scale=False)

        self.assertEqual(result.best.map_id, "dark_castle")
        self.assertEqual(result.best.location, (37, 29))
        self.assertAlmostEqual(result.best.scale, 1.0)
        self.assertGreater(result.best.score, 0.999)
        self.assertGreater(result.margin, 0.5)
        self.assertTrue(result.passes(0.75, 0.05))

    def test_multi_scale_matches_smaller_runtime_patch(self) -> None:
        large_patch = textured_patch(width=50, height=40)
        runtime = cv2.resize(large_patch, (45, 36), interpolation=cv2.INTER_AREA)
        self.write_reference("workshop", reference_with_patch(large_patch, location=(45, 31)))

        result = classify_map_patch(
            runtime,
            self.references,
            enable_multi_scale=True,
            scale_min=0.90,
            scale_max=1.10,
            scale_step=0.05,
        )

        self.assertEqual(result.best.map_id, "workshop")
        self.assertAlmostEqual(result.best.scale, 1.10, places=2)
        self.assertGreater(result.best.score, 0.75)

    def test_missing_empty_and_too_small_references_fail_safely(self) -> None:
        patch = textured_patch()
        with self.assertRaisesRegex(MapClassificationError, "not found"):
            classify_map_patch(patch, self.root / "missing")
        with self.assertRaisesRegex(MapClassificationError, "No PNG/JPG"):
            classify_map_patch(patch, self.references)

        self.write_reference("tiny", np.zeros((5, 5, 3), dtype=np.uint8))
        with self.assertRaisesRegex(MapClassificationError, "No valid"):
            classify_map_patch(patch, self.references, enable_multi_scale=False)

    def test_visually_flat_runtime_patch_is_rejected(self) -> None:
        self.write_reference("flat", np.full((100, 150, 3), 120, dtype=np.uint8))

        with self.assertRaisesRegex(MapClassificationError, "too little visual detail"):
            classify_map_patch(
                np.full((40, 60, 3), 120, dtype=np.uint8),
                self.references,
            )

    def test_reference_save_uses_map_id_png_and_does_not_overwrite(self) -> None:
        patch = textured_patch()
        path = save_map_reference(patch, self.references, "Dark Castle")

        self.assertEqual(path.name, "Dark_Castle.png")
        loaded = cv2.imread(str(path), cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(loaded, patch)
        with self.assertRaises(FileExistsError):
            save_map_reference(patch, self.references, "Dark Castle")

    def test_unreadable_reference_is_skipped_with_warning(self) -> None:
        patch = textured_patch()
        self.write_reference("dark_castle", reference_with_patch(patch))
        (self.references / "broken.jpg").write_text("not an image", encoding="utf-8")

        result = classify_map_patch(patch, self.references, enable_multi_scale=False)

        self.assertEqual(result.best.map_id, "dark_castle")
        self.assertTrue(any("Could not load reference image" in item for item in result.warnings))
        self.assertEqual(result.reference_count, 2)
        self.assertEqual(result.loaded_count, 1)

    def test_duplicate_reference_extensions_rank_as_one_map(self) -> None:
        patch = textured_patch()
        reference = reference_with_patch(patch)
        self.write_reference("dark_castle", reference)
        self.assertTrue(cv2.imwrite(str(self.references / "dark_castle.jpg"), reference))

        result = classify_map_patch(patch, self.references, enable_multi_scale=False)

        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.best.map_id, "dark_castle")
        self.assertTrue(any("Multiple references use map ID" in item for item in result.warnings))

    def test_classification_checks_stop_between_comparisons(self) -> None:
        patch = textured_patch()
        self.write_reference("dark_castle", reference_with_patch(patch))

        with self.assertRaisesRegex(RuntimeError, "stop requested"):
            classify_map_patch(
                patch,
                self.references,
                stop_check=lambda: (_ for _ in ()).throw(
                    RuntimeError("stop requested")
                ),
            )


class ClassificationRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)
        self.storage = MacroStorage(self.project / "macros")
        self.references = self.project / "references" / "maps" / "expert"
        self.references.mkdir(parents=True)
        self.patch = textured_patch()
        cv2.imwrite(
            str(self.references / "dark_castle.png"),
            reference_with_patch(self.patch),
        )
        cv2.imwrite(
            str(self.references / "infernal.png"),
            reference_with_patch(textured_patch(seed=44)),
        )
        self.input = FakeInputController()
        self.screen = FakeScreenAnalysis(self.patch)
        self.messages = []
        self.window_manager = FakeWindowManager()
        self.runner = MacroRunner(
            self.window_manager,
            self.input,
            self.screen,
            log_callback=self.messages.append,
            storage=self.storage,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def classification_block(self, mapping) -> MacroBlock:
        block = MacroBlock.create("classify_map_run")
        block.params.update(
            {
                "x1": 700,
                "y1": 100,
                "x2": 759,
                "y2": 139,
                "reference_folder": "references/maps/expert",
                "map_macro_mapping": mapping,
                "map_click_x": 850,
                "map_click_y": 250,
                "movement_duration_ms": 175,
                "post_click_delay_ms": 0,
                "minimum_best_score": 0.75,
                "minimum_score_margin": 0.05,
                "enable_multi_scale": False,
            }
        )
        return block

    def parent(self, block: MacroBlock) -> Macro:
        return Macro(
            name="Parent",
            target_window=PARENT_TARGET,
            expected_window_size=PARENT_SIZE,
            blocks=[block],
        )

    def test_confident_match_clicks_and_runs_mapped_macro(self) -> None:
        child = Macro(name="Dark Castle Strategy", blocks=[key_block("space")])
        child_path = self.storage.save(child, self.storage.base_dir / "DC_Defla.json")
        block = self.classification_block(
            {"dark_castle": self.storage.to_reference(child_path)}
        )

        self.runner._run_macro(self.parent(block))

        self.assertEqual(
            self.input.calls,
            [
                ("move", TARGET, 850, 250, 175),
                ("click", TARGET, 850, 250, "left", 1),
                ("key", TARGET, "space", 1),
            ],
        )
        self.assertEqual(self.screen.regions, [(700, 100, 759, 139)])
        self.assertTrue(any("Top 1: dark_castle" in message for message in self.messages))
        self.assertTrue(any("Entering macro: Dark Castle Strategy" in message for message in self.messages))

    def test_low_confidence_does_not_click_or_run(self) -> None:
        block = self.classification_block({"dark_castle": "macros/DC_Defla.json"})
        block.params["minimum_best_score"] = 1.01

        self.runner._run_macro(self.parent(block))

        self.assertEqual(self.input.calls, [])
        self.assertIn("confidence was too low", self.runner.stop_reason)

    def test_missing_mapping_stops_before_click(self) -> None:
        block = self.classification_block({})

        self.runner._run_macro(self.parent(block))

        self.assertEqual(self.input.calls, [])
        self.assertIn("has no mapped saved macro", self.runner.stop_reason)

    def test_ambiguous_top_matches_fail_margin_before_click(self) -> None:
        cv2.imwrite(
            str(self.references / "infernal.png"),
            reference_with_patch(self.patch, location=(9, 7)),
        )
        block = self.classification_block(
            {
                "dark_castle": "macros/DC_Defla.json",
                "infernal": "macros/IF_Impop.json",
            }
        )

        self.runner._run_macro(self.parent(block))

        self.assertEqual(self.input.calls, [])
        self.assertIn("confidence was too low", self.runner.stop_reason)
        self.assertTrue(any("Margin: 0.0000" in message for message in self.messages))

    def test_missing_mapped_macro_is_validated_before_click(self) -> None:
        block = self.classification_block(
            {"dark_castle": "macros/Missing Strategy.json"}
        )

        self.runner._run_macro(self.parent(block))

        self.assertEqual(self.input.calls, [])
        self.assertIn("Referenced macro file not found", self.runner.stop_reason)

    def test_click_can_be_disabled_and_mapping_is_case_insensitive(self) -> None:
        child_path = self.storage.save(
            Macro(name="Child", blocks=[key_block("q")]),
            self.storage.base_dir / "Child.json",
        )
        block = self.classification_block(
            {"DARK_CASTLE": self.storage.to_reference(child_path)}
        )
        block.params["click_before_run"] = False

        self.runner._run_macro(self.parent(block))

        self.assertEqual(self.input.calls, [("key", TARGET, "q", 1)])


class ClassificationModelAndEditorTests(unittest.TestCase):
    def test_block_round_trip_deep_copies_mapping(self) -> None:
        first = MacroBlock.create("classify_map_run")
        second = MacroBlock.create("classify_map_run")
        first.params["map_macro_mapping"]["dark_castle"] = "macros/DC_Defla.json"

        self.assertEqual(second.params["map_macro_mapping"], {})
        loaded = Macro.from_dict(Macro(blocks=[first]).to_dict())
        clone = loaded.blocks[0].clone()
        clone.params["map_macro_mapping"]["infernal"] = "macros/IF_Impop.json"

        self.assertNotIn("infernal", loaded.blocks[0].params["map_macro_mapping"])
        self.assertIn("mappings=1", block_summary(loaded.blocks[0]))

    def test_editor_prioritizes_runtime_region_overlay_and_coerces_settings(self) -> None:
        app = MacroEditorApp.__new__(MacroEditorApp)
        block = MacroBlock.create("classify_map_run")
        app.selected_block_units = lambda: [block]

        self.assertIs(app._region_marker_block(), block)
        self.assertTrue(app._block_uses_coordinates(block))
        self.assertFalse(app._coerce_param("click_before_run", "false"))
        self.assertTrue(app._coerce_param("enable_multi_scale", "true"))
        self.assertEqual(app._coerce_param("minimum_best_score", "2"), 1.0)
        self.assertEqual(app._coerce_param("minimum_score_margin", "-1"), 0.0)


if __name__ == "__main__":
    unittest.main()
