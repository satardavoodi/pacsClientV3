# Text annotation tool — the FAST viewer never asked what to write

**Date:** 2026-08-18
**Reported by:** owner, from the floor —
> "in the tools at patient viewer page there is a text function to write the text
> on the image / its not working fix it"

**Status:** Fixed. 25 guards in `tests/code/viewer/test_text_annotation_input.py`;
6 of them verified to FAIL on the pre-fix codebase.

---

## 1. Symptom

Select **Text** in the patient-viewer toolbar, click on the image, and the
literal word `Text` appears at the click point. There is no dialog, no caret,
no way to type anything. Clicking again produces a second `Text`.

So the tool was not dead — it was placing an annotation every single time. It
just placed the *placeholder* instead of the user's words, which from the
reading desk is indistinguishable from "not working".

## 2. Root cause

The FAST viewer's text tool was wired end to end **except for the input step**:

| Stage | File | State |
|---|---|---|
| Toolbar button | `PacsClient/.../toolbar_manager.py:3663` (`create_dropdown_tool('Text', …)`) | OK |
| Toggle handler | `toolbar_manager.py:2646` `toggle_text()` | OK |
| Tool routing | `vtk_widget/_vw_interactor.py:196` `ta.TEXT: (qv.TOOL_TEXT, "TEXT")` | OK |
| Press handling | `qt_slice_viewer.py:1608` (`_is_text_tool` → `update()` + `_emit_tool_completed()`) | OK |
| **Annotation creation** | **`modules/viewer/tools/controller.py::_text_press`** | **hard-coded `text="Text"`** |
| Store | `modules/viewer/tools/store.py` | OK |
| Rendering | `renderers/qpainter.py:740` `_render_text` → `painter.drawText(QPointF(*pw), model.text)` | OK |

`_text_press` built its `TextModel` with a literal:

```python
self._store.add(TextModel(..., text="Text"))
```

Nothing anywhere in the FAST path called `QInputDialog` (the only
`QInputDialog` uses in the viewer were `getInt`/`getDouble` for MPR slab
thickness). The renderer was innocent — it drew `model.text` faithfully; the
model simply never carried anything else.

### Why only FAST

The Advanced (VTK) backend has asked since forever —
`modules/viewer/interactor_styles/text_interactorstyle.py::on_left_button_press`
opens `QInputDialog.getText(None, "Enter Text", "Text:")` before building the
actor. So the intended UX was never in doubt; the FAST backend — which is the
default — was the one that had never implemented it.

## 3. Fix

Three changes, all additive.

### 3.1 `modules/viewer/tools/controller.py` — an injection point

`_text_press` now asks, via an injected callable, and falls back to the legacy
placeholder when nothing is wired:

```python
text = "Text"
if self._text_prompt_fn is not None:
    try:
        entered = self._text_prompt_fn()
    except Exception:
        return False          # a broken prompt must not stamp a stray label
    if entered is None:
        return False          # cancelled
    entered = str(entered).strip()
    if not entered:
        return False          # empty input is a cancel, not a blank label
    text = entered
```

`_text_prompt_fn` was added to `__slots__` and initialised to `None`.

**Why injected rather than opened here.** `controller.py` is deliberately
Qt-free — it imports only `os`, `typing` and its own package, it carries the
tool state machine, and it is imported by headless unit tests
(`tests/code/fast_viewer/test_tools_*.py`, `tests/code/viewer/test_tool_layer.py`,
the EchoMind viewer write adapter). A controller that pops dialogs cannot be
unit-tested. This mirrors the `_pixel_data_fn` / `_pixel_spacing_fn` injection
convention already used for ROI statistics.

**Returning `False` matters.** `qt_slice_viewer` only calls `update()` and
`_emit_tool_completed()` when the press returns True; on False it falls through
harmlessly and the tool stays armed. So a cancel places nothing *and* does not
consume the tool — "I mistyped, let me try again" still works.

### 3.2 `modules/viewer/fast/qt_viewer_bridge.py` — the Qt side

`_init_tool_controller` wires the prompt next to the existing injections:

```python
ctrl._text_prompt_fn = self._prompt_annotation_text
```

and `_prompt_annotation_text()` opens the dialog. Three deliberate properties:

* **Lazy import.** `from PySide6.QtWidgets import QInputDialog, QLineEdit`
  happens inside the method, so importing the bridge stays as cheap as it is
  today — the widget import is paid the first time somebody places text.
* **Re-entrancy guard.** A modal dialog re-enters the Qt event loop, so a
  second mouse press delivered while the dialog is up could stack a second
  dialog. `_text_prompt_open` blocks that and reports the re-entrant call as a
  cancel. It is released in a `finally`, so a raising dialog cannot leave the
  tool permanently muted.
* **Never raises.** An exception out of a mouse press would be log noise for
  no benefit; the controller already treats "no answer" as "place nothing".

The dialog uses the **same title and label as the VTK backend**
(`"Enter Text"` / `"Text:"`), so the two viewers ask the same question in the
same words. A guard test pins that they stay in step.

### 3.3 `modules/viewer/interactor_styles/text_interactorstyle.py` — Cancel

Found while confirming the VTK path: `ok` was collected from
`QInputDialog.getText` and then **ignored**, so pressing Cancel (or OK on an
empty box) still added an empty `vtkVectorText` actor to the renderer *and* an
entry to the tools store — an invisible label the user could neither see nor
easily delete. Added a four-line bail-out before `create_text_actor`, matching
the FAST contract (place nothing, leave the tool armed).

This is the same tool the user complained about, on the other backend, so it is
in scope rather than an unrelated refactor.

## 4. Deliberately NOT changed

* **The legacy placeholder stays.** A bare `ToolController` with no prompt
  wired still places `"Text"`. Every existing tool test and the EchoMind
  viewer write adapter build controllers that way; changing that would be a
  regression in code that has nothing to do with the user's click.
  `test_without_a_prompt_the_legacy_placeholder_is_kept` pins it.
* **Single-line input.** `_render_text` is a single `painter.drawText(...)`,
  so multi-line entry would render as one run with the newlines swallowed.
  `getText` (single-line) is the correct match for the renderer as it stands.
  Multi-line would need `_render_text` changed first.
* **No new environment flag.** The change is "ask instead of assume" with a
  full legacy fallback already reachable by not wiring the prompt; a kill
  switch here would only let a site opt back into the reported bug.
* **`builder/plugin package/packages/viewer/payload/python/…`** carries an
  older copy of both files. Its git history shows it is refreshed only at
  release commits, i.e. it is a builder snapshot, so it was left alone — it
  will pick the fix up at the next release build.

## 5. Risk

Low, and bounded to the Text tool.

* The controller change is inside `_text_press` only; no other tool reads
  `_text_prompt_fn`, and `test_the_prompt_is_only_asked_for_the_text_tool`
  proves a ruler placement never calls it.
* The bridge change adds one assignment and one new method; `QtViewerBridge`
  has no `__slots__`, so `_text_prompt_open` is a legal instance attribute.
* The one genuinely new user-visible behaviour is a **modal dialog on a mouse
  press**. That is why the re-entrancy guard exists, and why the whole method
  is exception-proof.
* The VTK change can only *prevent* an object from being created, and only on
  the cancel/empty path.

## 6. Verification

```
tests/code/viewer/test_text_annotation_input.py    25 passed
tests/code/viewer                                  2265 passed, 28 skipped,
                                                   54 xfailed, 2 xpassed
tests/code/fast_viewer                             416 passed, 12 skipped
```

No new failures. All xfails/xpasses are pre-existing quarantined entries.

**Pre-fix proof** — `tools/analysis/oneoff/verify_text_guard_fails_prefix.py`
reconstructs the pre-fix sources with `git show HEAD:` (the working tree is
never touched — it carries unrelated in-flight EchoMind work) and reports:

```
1. BEHAVIOURAL - pre-fix modules/viewer/tools (12 files checked out)
  [FAILS pre-fix] test_the_typed_text_is_what_lands_on_the_image:
      pre-fix ToolController.__slots__ has no _text_prompt_fn; text placed = 'Text'
  [FAILS pre-fix] test_cancel_places_nothing
  [back-compat]   pre-fix bare controller places 'Text' - unchanged after the fix
2. STRUCTURAL - pre-fix qt_viewer_bridge.py
  [FAILS pre-fix] test_the_bridge_wires_the_prompt
  [FAILS pre-fix] test_the_bridge_exposes_the_prompt_method
3. STRUCTURAL - pre-fix text_interactorstyle.py
  [FAILS pre-fix] test_the_vtk_text_tool_honours_cancel
  [FAILS pre-fix] test_both_backends_ask_the_same_question
```

The behavioural half is the important one: the pre-fix controller placed
`'Text'` when handed a prompt returning `"L4-L5 disc"` — literally the reported
bug, reproduced from HEAD.

The load-bearing guards:

* `test_the_bridge_wires_the_prompt` — the controller change is **inert**
  without the one-line Qt wiring, and that line is easy to lose in a merge.
  AST-based, so a comment naming `_text_prompt_fn` cannot satisfy it.
* `test_without_a_prompt_the_legacy_placeholder_is_kept` — the no-regression
  pin for every bare-controller caller.
* `test_a_cancel_leaves_the_tool_armed` — cancel must place nothing *and* not
  consume the click.
* `test_the_controller_module_stays_qt_free` — AST scan of `controller.py`'s
  imports; the whole point of the injection design.

## 7. Observed, not fixed

* **`pytest tests/code/fast_viewer` cannot start without `-p no:debugging`.**
  `_pytest.debugging.pytest_configure` does `import pdb`, which does
  `import code`, which resolves to the repo's `tests/code` package once pytest
  puts `tests/` on `sys.path` — `AttributeError: module 'code' has no attribute
  'InteractiveConsole'`, raised as an INTERNALERROR before collection.
  `tests/code/viewer` is unaffected because it has no `__init__.py`.
  Pre-existing and unrelated to this fix; the workaround is `-p no:debugging`
  (used for the run above). The real fix would be renaming `tests/code` or
  adding `-p no:debugging` to the pytest config — both wider than this change.
* **Text annotations are single-line** by renderer construction (§4). If
  multi-line labels are wanted, `_render_text` needs splitting on newlines
  with a line-height advance first, and only then `getMultiLineText`.
* **The Advanced backend's text actor is 3D** (`vtkVectorText` + extrusion +
  follower) while FAST draws with `QPainter`. They will not look identical.
  Out of scope here; noted so it is not later mistaken for a regression.
