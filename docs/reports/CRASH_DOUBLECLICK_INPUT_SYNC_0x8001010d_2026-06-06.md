# Crash on Patient Double-Click — 0x8001010d Input-Sync Fix (2026-06-06)

## The incident (installed app, this PC)

`D:\AIPacs\User Data\logs`, session 14:16:18 (pid 18464): user double-clicked a
patient at **14:18:59** (8-burst of `_hp_patient_open._emit*` traces), process
died, relaunch at 14:19:59 (new pid 39704). `native_fault.log` (last event):

```
Windows fatal exception: code 0x8001010d        (RPC_E_WRONGTHREAD)
Current thread (main):
  thumbnail_manager.py:53   ThumbnailWidget.__init__   ← QPropertyAnimation
  thumbnail_manager.py:1412 create_thumbnail_widget
  right_panel_widget.py:589 display_thumbnails_immediately
  right_panel_widget.py:480 <lambda>                   ← QTimer.singleShot(0,…)
  main.py:907               notify
```

## Root cause

The right-panel thumbnail rebuild is deferred via `QTimer.singleShot(0, …)`.
On a double-click open, the open path pumps events while the double-click's
**input-synchronous SendMessage dispatch is still on the native stack** — so
the deferred rebuild executes *inside* that dispatch. Creating thumbnail
widgets fires outgoing UIA/accessibility COM calls, and Windows forbids
outgoing COM during an input-synchronous call: it raises
**RPC_E_WRONGTHREAD (0x8001010d) as a fatal exception** → instant process
death. This is the same family as the single `thumbnail_manager.py:53` AV
flagged "watch" in `OTHER_PC_LOG_EVALUATION_2026-06-05.md` — now reproduced
and root-caused on this PC. It is timing-dependent, which is why it is a
one-time/occasional crash rather than systematic.

## Fix (source — `right_panel_widget.py`)

New `_inside_input_synchronous_dispatch()` (ctypes `user32.InSendMessageEx`,
fail-open) and three guards that **defer widget creation until the input
dispatch has returned**:

- `display_thumbnails_immediately` / `display_thumbnails_progressively`:
  under the gate, re-post themselves via `QTimer.singleShot(16, …)` —
  bounded (25 hops) and stale-safe (the existing generation check runs
  first, so a newer render simply wins).
- `display_next_thumbnail` (the 120 ms progressive tick): skips the tick;
  the timer retries naturally.

No behavior change outside the dangerous window: the gate reports False in
normal dispatch and everything renders exactly as before. Right-panel
invariants (clear-inside-deferred-rebuild, render-coalescing signature,
fast-cache gate) untouched.

## Verification

| Check | Result |
|---|---|
| `tests/code/test_right_panel_input_sync_guard.py` (helper fail-open bool; gate→re-post before any widget work in both renderers; generation check stays first; tick skip) | **5/5 passed** |
| `py_compile` | OK |
| `verify_plugin_mirrors` (PacsClient not mirrored) | 291/291 |

## Important operational note

The crash happened in the **installed frozen build**, which also lacks every
fix from this week (Eagle Eye VTK guard, takeover, large-batch, dead-sidebar,
probe cache…). This fix lands in source — **the installed app keeps this
crash until the next build is shipped and installed.** Shipping remains the
single highest-value action.
