# W0 + W1 — Responsive UI hardening, first wave landed
**Date:** 2026-05-26
**Status:** Code on disk; awaiting source-build smoke test against Monitor B.

This wave addressed the 4 Critical issues from `comparison_AB.md` using the new responsive-layout convention. Every change is wrapped in a try/except so a helper-import failure cannot break the app — the original behaviour is preserved as a fallback path.

---

## W0 — Foundation (no callers; zero regression risk)

| File | Purpose |
|---|---|
| `docs/conventions/RESPONSIVE_UI_CONVENTION.md` | One-page rule + decision tree. Every new layout commit is reviewed against this. |
| `PacsClient/utils/responsive_layout.py` | Helper module with `wrap_in_horizontal_scroll`, `make_wrapping_label`, `ElidedLabel`, `horizontal_splitter`, `set_form_field_size`, `set_table_column_policy`. All thin wrappers over Qt primitives. Compile-verified. |
| `tools/dev/audit_fixed_sizes.py` | Greps the codebase for `setFixed*` calls and classifies them against the 7 archetypes. Project-wide audit + `--diff <range>` mode for PR review. Verified against `mainwindow_ui.py`. |

---

## W1 — 4 Critical fixes from `comparison_AB.md`

### Fix #1 — Patient chip strip overlap (Archetype 1)

**File:** `PacsClient/pacs/patient_tab/ui/patient_ui/custom_tab_manager.py` (lines ~98-135)
**Defect:** at 4 chips on a 1280-wide window, chips physically overlapped each other; the close × of chip 1 was hidden behind chip 2 — workflow blocker.
**Change:** wrapped `title_bar_tabs_container` in `wrap_in_horizontal_scroll(max_height=70)`. Chips keep their 252 × 70 size; the strip becomes scrollable when narrower than the sum of chip widths.
**Risk:** low. The inner `addStretch(1)` was removed because it would defeat the scroll area's overflow detection (an unbounded stretch reports infinite preferred width). The outer `title_bar_layout.addStretch(1)` after the scroll area absorbs leftover space, so the visual layout at Monitor A's 1920-wide budget is unchanged.

### Fix #2 — Patient Studies centre toolbar clipping (Archetypes 3 + 5)

**File:** `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py` (lines ~966-1000, 1148-1170)
**Defect:** `Patient Studies` → `Patient Stu`; `16 studies found` → `1 study f`; `Offline Sync` → `Offline S:` on Monitor B.
**Change:**
- Replaced the title `QLabel` with `ElidedLabel("Patient Studies")` plus a 60 px floor — the label now shows an explicit `…` when narrow and a tooltip with the full text.
- Same for `results_count_label` with an 80 px floor.
- `offline_export_btn`: `setFixedHeight(40)` → `set_form_field_size(min_height=40, min_width=120)` so the button keeps its floor but grows with font.
**Risk:** low. Pixmap+text combination on `results_count_label` continues to work because `ElidedLabel` is a `QLabel` subclass — only `setText` is overridden, `setPixmap` is unchanged.

### Fix #3 — Home tri-pane → user-resizable splitter (Archetype 4)

**Files:**
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_layout.py` (lines ~75-77, 410-413)
- `PacsClient/pacs/workstation_ui/home_ui/right_panel_widget.py` (lines ~193-206)
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py` (lines 205-218, new method 220-297)

**Defect:** left panel pinned at 306 px + right rail pinned at 216 px = 522 px reserved on a 1280 px window; centre patient table only got 758 px, hiding 6 of 12 columns.
**Change:**
- Left panel min/max relaxed: `setMinimumWidth(max(240, _left_sidebar_width-60))` and `setMaximumWidth(_left_sidebar_width + 180)`; size policy `Preferred / Expanding`.
- Right rail `setFixedWidth(216)` → `setMinimumWidth(200)` + `setMaximumWidth(360)`; size policy `Preferred / Expanding`.
- New method `_wrap_home_tripane_in_splitter()` runs after `setup_*_panel` and reparents the three children into a `horizontal_splitter([left, center, right], stretch_factors=[0, 1, 0], collapsible=False)`. Default sizes `[314, 750, 216]` are deliberately chosen so first-run on a 1280-wide monitor exactly fills the viewport without horizontal scrolling.
- Splitter state persists across sessions via `QSettings("AIPacs", "AIPacs")` key `home/tripane_splitter_state`. Drag → save; startup → restore if present.
- Whole method is wrapped in try/except so a helper failure leaves the original `QHBoxLayout` intact.
**Risk:** medium — this is the most structural change. Mitigations: failure-safe wrap, default sizes mirror previous fixed widths, collapsible=False so panels can never drag to zero, min widths protect the contents inside left and right panels.

### Fix #4 — Light Viewer Browse / Clear Path buttons (Archetype 5)

**File:** `PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py` (lines ~145-181)
**Defect:** both buttons had `setFixedWidth(100)` with no shrink mechanism; on narrow widths their containers compressed and the buttons appeared visually close together.
**Change:** both buttons now use `set_form_field_size(min_height=30, min_width=100)` — minimum dimensions preserved, but the buttons can grow with font / DPI changes.
**Risk:** trivial.

---

## What the user should smoke-test next

Per `CLAUDE.md`, the source build (VS Code Play on `main.py`) is the authoritative test target. The packaged build at `d:\ai-pacs mohamad\ino-pooyan viewer\ai pacs viewer.exe` cannot pick up these changes until rebuilt.

### Test 1 — Monitor A (1920 × 1080)
Visual regression: home page, opening a patient, Settings → Server Settings / Tools / Viewer Config / Image Filter / Installation / Light Viewer / EchoMind. **Expectation:** pixel-identical to the pre-W1 baseline. Splitter handles are visible but at the same default sizes.

### Test 2 — Monitor B (1280 × 1024) — the four Critical regressions
- Open 4 patient tabs → confirm chips no longer overlap; strip scrolls horizontally when needed; close × of chip 1 reachable.
- Home page → `Patient Studies` and `16 studies found` show `…` with tooltips when crowded; `Offline Sync` retains a readable label.
- Drag the splitter handles → centre table reclaims space; column visibility improves; state persists after app restart.
- Settings → Light Viewer → Browse... and Clear Path buttons remain visible and clickable at 1280 px.

### Test 3 — Multi-patient + multi-study (existing regression guard)
- Open two patients with > 1 study under one Patient ID.
- Confirm grouped sidebar still renders correctly (the Phase 4 changes touched `_pw_panels.py` ancestors but the multi-study path itself was not modified).

### Test 4 — Edge cases
- Splitter persistence: drag, close app, reopen, sizes should restore.
- Theme change (if user toggles): splitter remains in place; styles re-apply.
- Window resize: the splitter respects min/max widths set on each panel; user can't drag a pane below readability.

---

## Files NOT touched (preserved as-is, per CLAUDE.md regression guards)

- `vtk_widget.py`, `lightweight_2d_pipeline.py` — viewer hot paths.
- `_vc_load.py`, `_vc_switch.py` — multi-study regression-guarded code.
- `thumbnail_manager.py`, `thumbnail_panel.py` — thumbnail pipeline.
- `database/_pool.py`, `database/core.py` — DB connection layer.
- `modules/download_manager/*` — Zeta Download Manager.

---

## Remaining backlog (W2–W6)

Per the structural plan (`docs/plans/RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md`), Waves 2–6 are ready to land after W1 smoke tests pass:

- **W2 — `setWordWrap(True)`** on multi-line description QLabels (Viewer Configuration's Local Storage / GPU Boost / Backend analysis blocks). ~10 min total.
- **W3 — `set_table_column_policy`** on patient table + Offline Cloud Server. ~1.5 h.
- **W4 — `ElidedLabel`** rolled out across remaining single-line clipping sites (chip patient names, badge text). ~2 h.
- **W5 — `set_form_field_size`** in `server_settings.py` and other heavy forms. ~1.5 h.
- **W6 — Auditor rolling cleanup** of remaining `setFixed*` calls. Spread.

To start the next wave, point the auditor at the file set:
```powershell
python tools/dev/audit_fixed_sizes.py PacsClient/pacs/workstation_ui/settings_ui/
```

---

## Rollback

Each change is in a single commit (when committed to git). Rollback for any individual fix is `git revert <commit>`. The convention and helper module land first, so reverting a W1 fix removes only the application of the helper — the helper itself remains for the next attempt.
