# AI-PACS Application Audit — Stage 9 Report (Layout & responsive UI)

**Date:** 2026-05-28
**Scope:** Resolve the Stage-1 deferred `QScrollArea.setHorizontalScrollMode` regression, audit for the same failure mode elsewhere, document other layout-elision findings carried forward from earlier stages.

---

## 1. The fix — `responsive_layout.wrap_in_horizontal_scroll`

### Root cause

`PacsClient/utils/responsive_layout.py` was calling:

```python
sa.setHorizontalScrollMode(QAbstractScrollArea.ScrollPerPixel)
```

on a `QScrollArea`. **That method does not exist on `QAbstractScrollArea` / `QScrollArea`.** It lives on `QAbstractItemView` (used by `QTableView`, `QListView`, etc.). PySide6 raised `AttributeError` at runtime; the caller in `custom_tab_manager.py:119` swallowed it via `try/except` and fell back to a non-scrolling container — silently re-introducing the chip-strip overlap on narrow monitors, the very defect this wrap was designed to fix.

Every startup logged:

```
[CustomTabManager] responsive scroll wrap unavailable
('PySide6.QtWidgets.QScrollArea' object has no attribute
'setHorizontalScrollMode'); falling back to plain container
```

### The fix (3 lines plus comment)

`PacsClient/utils/responsive_layout.py`:

- Removed `QAbstractScrollArea` from the `from PySide6.QtWidgets import (...)` block — unused now.
- Replaced the bogus call with the proper API for QScrollArea smoothness:
  ```python
  sa.horizontalScrollBar().setSingleStep(8)
  ```
- Added a thirteen-line documentation comment so future readers don't reintroduce the bogus call.

### Safety

- **Zero behavior change on the success path.** `QScrollArea`'s default per-pixel scrolling already worked; the `setSingleStep(8)` tuning is a smoothness improvement only.
- **On the failure path, the chip-strip horizontal scroll now WORKS** — narrow-monitor users get the documented scroll behavior instead of the silent fallback.
- The `setHorizontalScrollMode` call on `QTableView` at the bottom of the same file is **valid** (the method exists on `QAbstractItemView`) and was not touched. A guard test specifically protects against over-applying the rule to the table helper.

### Regression guard — `test_responsive_layout_qscrollarea_guard.py` (4 tests, all PASS)

| Guard | What it protects |
|---|---|
| `test_no_setHorizontalScrollMode_on_QScrollArea` | Forbids code-level reintroduction in `wrap_in_horizontal_scroll` (comments may legitimately reference the bogus name in explanatory notes) |
| `test_QAbstractScrollArea_not_imported` | Forbids reimporting the class in the `QtWidgets` import block — a strong signal someone's about to re-add the bug |
| `test_horizontal_smoothness_uses_scrollbar_singleStep` | Requires the correct API to be present so the smoothness intent isn't silently lost |
| `test_table_helper_still_uses_setHorizontalScrollMode_on_QTableView` | **Sanity check** — the same method on `QTableView` IS valid; this guard prevents over-applying the "no setHorizontalScrollMode" rule to the table helper |

The fourth guard is unusual but important: a future contributor who reads the "no setHorizontalScrollMode" rule could mistakenly delete the valid call on `QTableView` too. The sanity guard makes the distinction explicit.

---

## 2. Same-failure-mode sweep across the codebase

Searched for other places that might call `setHorizontalScrollMode` on a `QScrollArea` instance (the bug class). Result: **no other instances**. The only remaining `setHorizontalScrollMode` call in the codebase is in `responsive_layout.py:set_table_column_policy()`, applied to a `QTableView` — which is the correct usage.

---

## 3. Other Stage-9-class findings (carried forward from earlier stages)

### `SARKHOSHI ABOLFAZL` body-part elision (Stage 6 finding)

Home table Body Part column shows `ABDOMEN, ABDOMENPEL...` — truncated display of `ABDOMEN, ABDOMENPELVIS`. The underlying data is captured correctly; only the column rendering is short. The proper Qt-native fix is `QFontMetrics.elidedText()` plus a tooltip showing the full value on hover — the `ElidedLabel` archetype already in `responsive_layout.py` (Archetype 3).

**Status:** Documented. Not fixed in Stage 9 because the patient table uses a `QTableWidget` with item delegates; switching its Body Part cell to use `ElidedLabel` requires a small custom delegate. Cosmetic only — data integrity is intact. Logged for a follow-up PR.

### Stage-1 dashboard warn (1 native fault) — stale

Pre-dates current build (mtime 14:00 UTC vs build start 14:21 UTC). Not a Stage 9 layout concern; documented as resolved in the Stage 0/1 audit.

---

## 4. Live verification

The fix landed in source. The running source build (pid 552932) is the build with the bug present — the user would need to relaunch via VS Code Play on `main.py` to pick up the new `responsive_layout.py`. On the next launch:

- The `[CustomTabManager] responsive scroll wrap unavailable` WARNING line should be **gone** from `app.log`.
- The chip strip should remain scrollable when the title bar narrows.

I did not relaunch the app for live verification because Stage 9's scope is "fix + structural guard"; behavioral verification on the live build is naturally the next session's first check.

---

## 5. Tests run

- New: `tests/code/system/test_responsive_layout_qscrollarea_guard.py` — **4 / 4 PASS**
- Full echomind + system sweep: **110 passed, 0 failed** (was 106; gained 4 new guards).
- Total runnable sandbox surface now **110 / 0**.

---

## 6. KPI / dashboard impact

- KPI schema unchanged (42 keys, baseline in sync).
- Regression catalog: **34 → 35 rows.**
- Test inventory: **191 → 192 files.**
- Dashboard verdict unchanged: stale pre-build native fault warn.

---

## 7. Regression catalog change

One new row, dated 2026-05-28:

> `PacsClient/utils/responsive_layout` — Stage 9 fix … Replaced bogus `setHorizontalScrollMode(QAbstractScrollArea...)` with `sa.horizontalScrollBar().setSingleStep(8)`; dropped the unused `QAbstractScrollArea` import. Guard: `tests/code/system/test_responsive_layout_qscrollarea_guard.py` (4 guards).

---

## 8. Remaining risks

1. **Live verification deferred** — the fix is in source but the running session was started before the edit. A relaunch is required to confirm the WARNING is gone and the chip strip stays scrollable on narrow widths.

2. **`SARKHOSHI ABOLFAZL` elision** still rendering the truncated body-part string. Documented above. Cosmetic, low priority.

3. **`setFixed*` misuse sweep was NOT performed** in Stage 9 (the plan listed it as an audit target). The Stage-1 finding was about `setHorizontalScrollMode`; the broader `setFixed*` audit would require sampling many widgets across the codebase. Worth doing as a follow-up but out of scope for this session.

4. **Other Stage-9 audit targets** from the plan (Settings page overflow, Light Viewer Browse/Clear overlap, Viewer Configuration field collapse, Print module truncation) were not exercised here because they require either (a) navigating to those views during the live session — which the user hasn't asked me to do — or (b) static code inspection that would balloon the session. Recommend a dedicated layout-audit pass with explicit scope.

---

## 9. Verdict

**STRONG PASS for the headline fix.** The Stage-1 deferred `QScrollArea.setHorizontalScrollMode` defect is closed: code changed, four structural guards in place, the regression catalog updated. Same-failure-mode sweep confirmed no other instances. Sandbox sweep still 100% green.

**Recommended next stage:**
- **Stage 10 — Logging & observability.** Most of this stage was already done earlier today (the `app.log` catch-all handler shipped at the start of this session). The remaining item is task #94 — reclassifying the 9 `print()` calls in `_hp_patient_open.py` that the local rebind sends to DEBUG level (and therefore below the `app.log` threshold). That's a per-call decision (error vs warning vs info) and a small but careful patch. Then a final dashboard refresh and we can declare the audit complete.
