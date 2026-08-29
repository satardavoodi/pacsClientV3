# Overlay re-entrancy crash — pid 217556, 2026-08-26 13:40:25

**Reported:** *"check we have crash and close 5 minutes ago in this pc"*
**Answer:** yes — and it was a **hard process death, not a close.**

---

## What happened

| | |
|---|---|
| Process | pid **217556**, `python.exe main.py` |
| Ran | 13:27:26 → **13:40:25** (≈13 min) |
| Ended by | `Windows fatal exception: **access violation**` |
| Clean shutdown record | **none** — no `[SHUTDOWN-INITIATOR]` anywhere for this pid |
| OS-level event | none — no Application Error/Hang, no Kernel-Power/6008 |
| Restarted | 13:40:40 as pid 219724 (still running, AboveNormal) |

Also present and **benign**: `code 0x8001010d`
(`RPC_E_CANTCALLOUT_ININPUTSYNCCALL`) at 13:27:23 and 13:40:40 — the known
survivable family the app already guards against. Not this.

---

## Root cause: `processEvents()` re-entered the event loop mid-switch

The faulthandler stack in `native_fault.log` names it outright — read bottom-up:

```
main.py:1467              <module>
qasync                    run_forever
main.py:820               notify                      ← Qt event dispatch #1
_vc_load.py:1668          _ui_apply
_vc_load.py:1614          _apply_loaded_series_data
qt_fast_container.py:866  switch_series
loading_spinner.py:195    show_loading
loading_overlay.py:661    show_overlay                ← processEvents() RE-ENTERS
main.py:820               notify                      ← Qt event dispatch #2, NESTED
_vc_switch.py:1132        _finish_on_ui
_vc_switch.py:1492        _perform_series_switch_optimized
qt_fast_container.py:866  switch_series               ← a SECOND switch
loading_spinner.py:195    show_loading
loading_overlay.py:648    show_overlay
loading_overlay.py:398    __init__  →  QProgressBar(self)   ← ACCESS VIOLATION
```

`AiPacsLoadingOverlay.show_overlay` ended with:

```python
# Force the event loop to paint the overlay immediately
QApplication.processEvents()
QApplication.processEvents()
```

`processEvents()` does far more than paint — it **re-enters the Qt event loop and
dispatches queued work**. A viewer-controller command was dispatched from inside
a series switch and started a **second switch on top of the first**. The nested
path then built an overlay against a viewport the outer switch was already
tearing down, and dereferenced a freed Qt C++ object.

### app.log corroborates it independently

The final second of pid 217556:

```
13:40:25  [PERF] apply_loaded series=7 … perform_switch=26.1ms   ← switch #1 completes
13:40:25  [VIEWER_SWITCH] switch_start switch-7-322390054 series=7  ← #2 starts
13:40:25  [VIEWER_SWITCH] switch_start switch-7-322390060 series=7  ← #3 starts
                                                                     (log ends)
```

**Three `switch_start` for one series inside one second, one `phase_summary`.**
The two orphans never complete.

**The trigger** is visible just above: repeated `[PROTECTED_DRAG] begin/end` —
stack-scrolling while a series switch was in flight.

### This is the second time, and the first fix treated the symptom

`loading_overlay.py:689` still carries the comment from 2026-06-05:

> *"1× native access violation HERE — the overlay's C++ object was already
> destroyed (**series-switch teardown raced the fade**), so
> QPropertyAnimation(overlay,…)/windowOpacity() dereferenced a deleted QWidget."*

That fix added a `shiboken6.isValid` liveness check inside
`hide_overlay._start_fade`. It hardened **one call site**. The cause — re-entering
the event loop mid-switch — was never addressed, so the same race moved from the
**fade** to **construction**.

---

## The fix

### (a) The cause — `loading_overlay.show_overlay`

`overlay.repaint()` paints the widget **synchronously without running the event
loop**, so the overlay still appears immediately and nothing can nest. The old
double `processEvents()` survives only inside the kill-switch else-branch, and a
guard asserts it can never sit on the default path again.
Kill switch `AIPACS_OVERLAY_SYNC_PAINT=0`.

### (b) Defence in depth — `qt_fast_container.switch_series`

A nested `switch_series` on the same container is refused and logged. The flag
clears in a `finally` that **also covers the early `return False`** — a stuck
flag would turn a crash into a permanently dead pane.

Not redundant with (a): `processEvents()` is called from a dozen other places in
this codebase, and any of them reached during a switch could nest again.
Note the existing same-series no-op could **not** have caught this — the first
switch of the crash carried an **empty `series_uid`**, so the identity
comparison never matched. Kill switch `AIPACS_SWITCH_REENTRANCY_GUARD=0`.

### (c) Defence in depth — `AiPacsLoadingOverlay.__init__`

Refuses a destroyed anchor **before anything touches it** —
`_anchor_has_native_render_window(anchor)`, `super().__init__(anchor)`,
`_sync_geometry()` and `installEventFilter` all dereference it. Raising is safe:
both callers of `show_overlay` already try/except and degrade to no overlay.
`_widget_is_alive` falls back to **True** when `shiboken6` is unimportable — a
missing probe must never be read as "widget is dead".
Kill switch `AIPACS_OVERLAY_ANCHOR_GUARD=0`.

---

## Verification

- **13 guards**, `tests/code/system/test_overlay_reentrancy_crash.py`.
  **11 fail pre-fix** — `verify_overlay_reentrancy_guard_fails_prefix_2026_08_26.py`
  restores only the two changed files (this tree has unrelated uncommitted work
  elsewhere) and refuses to run if HEAD already has the fix.
- The load-bearing guard is **behavioural and reproduces the crash without Qt**:
  it binds the real `switch_series` to a plain stub and calls it re-entrantly
  from inside `_start_qt_viewer`, exactly as `processEvents()` used to.
- **Regression surface: 3,862 passed, 6 failed.** Four are the
  `test_local_search_progressive` pins carried since 2026-08-21. The other two
  are in `tests/code/ui_services` and were **measured, not argued** —
  `check_overlay_fix_delta_2026_08_26.py` runs them with and without the two
  changed files and gets the identical failure set. **Caused by this fix: 0.**

---

## Known diagnostic gap — worth closing separately

**faulthandler dumps in `native_fault.log` are not stamped with a pid.** This
dump had to be attributed to 217556 by its stack contents and timing: the
`=== session start ===` header immediately above it belongs to pid **178048**,
which wrote nothing to app.log at all. One line in
`PacsClient/utils/native_fault_log.py` would remove that ambiguity for the next
crash.

## Deliberately not done

- No change to what the overlay looks like, or to when it is shown.
- The `QTimer.singleShot(180, _safe_hide_spinner)` hide path is untouched.
- The 2026-06-05 fade guard is left exactly as it is, and is now **pinned by a
  test** so this fix cannot regress it.
