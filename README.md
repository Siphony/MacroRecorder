# Window-Relative Macro Recorder

A small desktop macro builder for readable, window-relative automation blocks. It is designed for general input automation and works well for games or apps that have stable UI positions, such as Bloons TD 6 running in a fixed-size window.

This MVP is intentionally conservative:

- It stores clicks and pixel checks relative to the bound target window client area.
- It stops instead of clicking if the target window is missing, minimised, or resized from the macro's saved expected size.
- It uses normal user input only: mouse clicks, key presses, waits, and pixel reads.
- It does not read game memory, inspect network traffic, perform OCR, or do image/template matching.

## Requirements

- Windows
- Python 3.10 or newer
- Tkinter, which is included with the normal Windows Python installer
- MSS, OpenCV, and NumPy

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run

From this folder:

```powershell
python main.py
```

## Basic Workflow

1. Open the target app or game window.
2. Click **Bind Target** and select the window. The app stores the current client size as the expected macro size.
3. Add blocks in the middle panel.
4. Select a block and edit its properties on the right, then click **Apply**.
5. Use **Capture Click Position** for click blocks or **Capture Pixel** for pixel blocks, then click inside the target window.
6. Coordinate blocks show a red target marker over the bound window while editing.
7. Ctrl-click blocks to select multiple blocks.
8. Right-click a block to copy, cut, paste, duplicate, delete, or run from that block.
9. Click **Save** to write a readable JSON macro under `macros/`.
10. Click **Run** to execute the macro.
11. While a macro is running, press any physical key, click inside the Macro Builder window, click **Stop**, press Escape while the editor is focused, or press **Ctrl+Shift+Q** globally to stop execution.

Use **Record** to append simple target-window clicks and key presses as normal blocks, then click **Stop Recording** when finished.

## Block Types

- **Click**: clicks at `x, y` relative to the target window client area.
- **Key Press**: focuses the target window and presses a key one or more times.
- **Wait**: waits a fixed number of milliseconds.
- **Wait For Pixel Match**: polls a target-relative pixel until it matches the expected colour within tolerance or times out.
- **If Pixel Match**: checks one pixel and runs nested `Then` blocks or optional `Else` blocks.
- **Wait For Region Colour Match**: polls a target-relative rectangle until enough sampled pixels match a colour rule.
- **If Region Colour Match**: checks a target-relative rectangle once and runs nested `Then` or optional `Else` blocks.
- **Wait Until Region Stable**: waits until a target-relative rectangle remains within a configured visual-change limit for the required duration.
- **Click Until Region Changes**: clicks, verifies that a watched rectangle changed, and retries a configured number of attempts before failing safely.
- **Repeat**: repeats nested blocks a fixed number of times.
- **Label**: marks a named root-level position in the macro.
- **Goto**: jumps to a matching root-level Label and continues after it.
- **Run Saved Macro**: executes another saved macro, then returns and continues with the next parent block.
- **Stop Macro**: stops execution immediately.

Pixel colours use `#RRGGBB`. Tolerance is per-channel, so a tolerance of `10` means red, green, and blue may each differ by up to 10.

## Coordinate And Pixel Debugging

Coordinates are relative to the target window client/content area, not the outer window frame. Crosshair display, click execution, pixel capture, pixel probes, Wait For Pixel Match, and If Pixel Match all resolve coordinates through the same client-to-screen conversion path.

When a Click, Wait For Pixel Match, or If Pixel Match block is selected, the app shows a small red marker over the bound target window at that block's relative coordinate. The marker uses the same target-window coordinate conversion as macro execution and updates as you edit `x` or `y`. The marker overlay is click-through, so it should not block interaction with the target application.

The target panel includes **Show target marker while editing**. Turn it off if the overlay is distracting.

Colour fields display a live swatch beside the hex value. Invalid colours show a red invalid state instead of crashing.

Pixel blocks include a **Probe Pixel Now** button. It hides the marker briefly, reads the current target pixel using the same path as runtime checks, and logs target title, relative coordinate, resolved screen coordinate, window bounds, client bounds, target DPI, sampling mode, read colour, and crosshair/pixel alignment.

Pixel checks write detailed debug entries to the in-app log, including target title, relative coordinate, resolved screen coordinate, expected colour, sampled colour, configured tolerance, required tolerance, sampling mode, and match result. Wait For Pixel Match logs the first check, successes, timeouts, and throttled failed checks about once per second so the log stays readable.

Pixel capture also logs the target title, relative coordinate, screen coordinate, and captured colour.

Pixel detection blocks support these sampling modes:

- **Single Pixel**: reads exactly the target pixel.
- **Average 3x3** / **Average 5x5**: averages a square region around the target coordinate.
- **Closest Match 3x3** / **Closest Match 5x5**: uses the sampled pixel closest to the expected colour and logs its offset from the target.

## Region Colour Detection

Region blocks are useful when a single pixel is too fragile, such as a button with text, icon art, borders, gradients, or hover effects.

Add **Wait For Region Colour Match** or **If Region Colour Match**, then use **Capture First Corner** and **Capture Second Corner** to define the rectangle. The app normalises the two corners, so reverse-order captures still work. A red click-through rectangle overlay appears over the bound target window while editing.

Detection modes:

- **Green Dominance**: counts pixels where green is stronger than red and blue by the configured strength and meets the minimum green value.
- **HSV Green**: uses an OpenCV HSV mask. Hue uses OpenCV's `0-179` range; saturation and value use `0-255`.
- **Expected Colour Match**: counts pixels within the configured per-channel tolerance of the expected colour.

The condition passes when `matching sampled pixels / sampled pixels` is at least **Minimum Match (%)**. **Sample Step** controls performance: `1` checks every pixel, `2` checks every second pixel, and `4` checks every fourth pixel.

Use **Probe Region Now** to log the current match percentage, matching pixels, sampled pixels, resolved screen region, target bounds, detection thresholds, and pass/fail result before running a macro.

## Stability Waits And Verified Clicks

**Wait Until Region Stable** compares consecutive MSS/OpenCV captures of the selected region. A pixel counts as changed when any colour channel differs by more than **Pixel Change Threshold**. The stable timer advances while the changed-pixel percentage stays at or below **Maximum Changed (%)**, and resets when meaningful movement returns.

**Click Until Region Changes** captures the watched region before each attempt, clicks the configured target, then compares post-click captures against that baseline until **Check Timeout** expires. It succeeds as soon as **Required Changed (%)** is reached. Otherwise it updates the baseline, waits the retry delay, and tries again. After all configured attempts fail, the macro stops with the final observed change percentage.

Both blocks use the same target-client-relative MSS capture path as region colour detection. Their selected watched regions use the existing red click-through rectangle overlay. Verified-click properties also include **Capture Click Position** for the click target.

Wait For Pixel Match, Wait For Region Colour Match, and Wait Until Region Stable include an optional **After Success Delay (ms)**. It runs only after a successful condition, not after timeout/failure. Existing macros default to `0`.

When **Save debug captures** is enabled, stability timeouts and verified-click attempts save relevant region captures under `debug_captures/`.

## Vision Backend And Debug Captures

Pixel and region capture use MSS. MSS supplies BGRA pixels, which are converted to OpenCV BGR arrays. Pixel and expected-colour analysis convert BGR to RGB where needed; HSV analysis uses OpenCV's BGR-to-HSV conversion.

Enable **Save debug captures** in the Target Window panel to automatically save pixel probes, region probes, and timed-out wait captures under `debug_captures/`. Pixel and region properties also include **Save Last Probe Image**, which saves the most recent probe even when automatic capture saving is disabled.

Probe logs show the saved PNG path. Region probes evaluate Expected Colour, RGB Green Dominance, and HSV Green together so their percentages can be compared against the exact same captured image.

Analyse a saved PNG using the same OpenCV region logic:

```powershell
python tools/analyse_region_capture.py debug_captures/example.png --mode hsv-green
python tools/analyse_region_capture.py debug_captures/example.png --mode expected --expected "#35C84A" --tolerance 40
```

## Editing Shortcuts

The block list supports a right-click context menu with:

- Run From Here
- Copy
- Cut
- Paste
- Duplicate
- Delete

Ctrl-click toggles block selection for group operations. If both a parent block and one of its child blocks are selected, group operations treat the parent as the selected unit and ignore the separately selected child.

The same actions are available from the keyboard when the block list has focus:

- `Ctrl+C`: copy
- `Ctrl+X`: cut
- `Ctrl+V`: paste
- `Ctrl+D`: duplicate
- `Delete`: delete

Copy, cut, paste, and duplicate preserve nested child blocks and create independent copies.

## Labels And Goto

Label blocks appear in the tree as `:label_name`. Goto blocks appear as `Goto -> label_name`.

Labels and Gotos are root-level only. The editor prevents adding or pasting them into child/else branches, and loaded macros with nested Label/Goto blocks are reported as invalid. Label names must be non-empty and unique. Goto targets can be selected from an editable dropdown of current labels.

Run validates Label/Goto control flow before execution. Missing targets, duplicate labels, empty names, and nested Label/Goto blocks prevent execution with a clear error. A Goto logs its jump and yields briefly so tight loops remain responsive to Stop, user-input override, Escape, and the global emergency hotkey.

## Run Saved Macro

Add **Run Saved Macro**, select it, and use **Browse Saved Macro** to choose a reusable macro JSON file. The existing block **Name** field can provide a friendlier display name. Files inside this project are stored as portable project-relative references such as `macros/Dark Castle Setup.json`; files outside the project use absolute paths.

When execution reaches the block, the child macro is loaded, validated, executed from its first block, and then the parent continues with its next block. Called macros use the parent run's active target window and expected size. Their own saved target metadata is only used for an informational size note.

Child calls share the same runner thread and cancellation event, so Stop, Escape, user-input override, and the global emergency hotkey stop the child and parent together. Entering, finishing, child failures, and stops inside child macros are logged.

Each macro has its own root Label/Goto scope. A child Goto cannot jump into its parent, and a parent Goto cannot jump into a child.

Runtime call-stack tracking prevents direct and indirect recursion. A circular call stops safely and logs a stack such as `Main -> Setup -> Main`. Missing files, invalid JSON, invalid child Label/Goto flow, and child block failures also stop the parent with a visible error reason.

## Simple Input Recording

The main toolbar includes **Record** and **Stop Recording**. While active, a red `Recording...` indicator is shown and captured actions appear live in the macro tree.

Recording appends after the selected block when recording starts. With no selection, actions append to the root macro list. Captured actions are ordinary **Click** and **Key Press** blocks, so they use the existing save/load, copy/paste, and runner behavior.

Only physical left, right, and middle mouse-button presses inside the bound target client area are recorded. Each click is converted using fresh live target-window bounds, so moving the target during recording still produces correct client-relative coordinates. Clicks inside Macro Builder or outside the target are ignored.

Keyboard presses are recorded only while the bound target window is foreground. Common keys, letters, digits, function keys, punctuation, Space, Enter, Tab, Escape, and arrow/navigation keys are supported. Modifier-only Shift, Ctrl, and Alt events are ignored.

Recording and macro execution are mutually exclusive. Starting a run while recording, or starting recording while a macro runs, is refused with a clear message. Recording does not treat intended user input as an emergency stop.

v1.9 does not record mouse movement, dragging, click counts, key combinations, or pauses as Wait blocks. Repeated clicks or keys become separate readable blocks, and waits can be added manually afterward.

## Saved Macro Ordering And Save Safety

The Saved Macros panel includes **Move Up** and **Move Down** controls. Manual order is stored separately in `macros/macro_order.json`; macro JSON files are not modified when the list is reordered. New or previously unlisted macro files appear after the ordered entries. Missing order entries are ignored, and missing/corrupt metadata safely falls back to alphabetical discovery.

The editor compares the current macro against the last saved/loaded snapshot. Block additions, deletion, reordering, property edits, recording, target binding, macro name, notes, Run Saved Macro references, labels, and other macro-content changes therefore produce an **Unsaved changes** indicator.

Before creating/loading another macro or closing the app, unsaved work prompts for **Save**, **Don't Save**, or **Cancel**. Save continues only after a successful write; Cancel keeps the current macro open. Running or recording must be stopped before switching or closing.

**Run** and **Run From Here** always save the current macro before execution. A macro that has never been saved opens Save As first. Canceling Save As or encountering a save error prevents execution, ensuring called macros and the on-disk parent reflect the run being started.

## Layout

The app opens at up to `1600x900`, constrained to the available screen size. Macro editing controls are split across compact rows so they remain accessible in narrower panes. The selected-block properties panel scrolls vertically with its scrollbar or mouse wheel, keeping long region-detection forms and probe controls reachable.

## Run From Here

Right-click a block and choose **Run From Here** to start execution from that block. For nested blocks, the app runs the selected block and subsequent sibling blocks in the same sequence.

## Emergency Stops

The app has several stop paths while a macro is running:

- Any non-macro-generated keyboard input stops execution.
- A non-macro-generated click inside the Macro Builder window stops execution.
- **Ctrl+Shift+Q** remains registered as a global emergency hotkey.
- The **Stop** button and focused-window Escape shortcut still work.

Stop reasons are written to the execution log.

A visible notice below the status bar also shows why the macro stopped, such as `Macro stopped: User keyboard input detected.`

## Saved Macro Format

Macros are saved as formatted JSON. A macro includes:

- `schema_version`
- `name`
- `notes`
- `target_window`
- `expected_window_size`
- `blocks`

Nested blocks are stored in `children`; `If Pixel Match` else blocks are stored in `else_children`.

## Notes For Bloons TD 6

Run BTD6 in a stable window size before binding the target. If you usually use a `1280x720` game window, bind the target after setting that size. The app stores the client area size and will stop with a warning if the size changes later.
