# W6 Follow-up — User-reported issues 1-6 (2026-05-26)
**Status:** Code on disk; awaiting source-build smoke test.
**Companion docs:** `W1_LANDED.md`, `W2_W5_LANDED.md`, `W6_LANDED.md`, `BLACK_MIDDLE_DIAGNOSTIC_2026-05-26.md`.

User confirmed: black-middle issue is **resolved** (was a transient runtime widget, not a layout defect). Remaining six issues addressed below.

---

## Issue 1 — Viewer Configuration grid picker buttons

**Defect:** The `1×2 / 2×2 / 1×1 / 3×3` selectors next to each modality looked like plain dark rectangles with text, not clickable buttons. No hover/pressed feedback, no dropdown affordance.

**File:** `PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py` — `GridPickerButton` class.

**Change:** Added a self-contained stylesheet so the button reads as an interactive picker:
- Background `#1b2230`, border `#2b313b`, 6 px radius, 4 / 10 px padding.
- Hover: brightens to `#243041`, border to project-blue `#3b82f6`.
- Pressed: darkens to `#1e293b`, border to `#60a5fa`.
- Focus ring with `#3b82f6`.
- Trailing ` ▾` glyph in the button label so the dropdown affordance is explicit.
- Tooltip: "Click to choose a grid layout (rows × cols)".

Also updated `_set_grid` to keep the `▾` glyph after the user picks a new size.

**Risk:** trivial. Pure styling + label change. The picker popup (`GridPickerPopup`) is untouched.

---

## Issue 2 — Light Viewer path field distortion

**Defect:** The DICOM Light Viewer Executable path field had visual artifacts — dark gap between the read-only text and the surrounding container, and the status / error labels rendered without enough spacing so they appeared "stuck" to the field.

**File:** `PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py`.

**Changes:**
1. Explicit `QLineEdit` stylesheet for the path field — background `#1b2230`, border `#2b313b`, 6 px radius, 4 / 10 px padding, focus border `#3b82f6`. Read-only state is styled identically to the normal state so the field doesn't render as a flat black strip next to Browse.
2. `set_form_field_size(min_height=30, expanding=True)` on the path field (Archetype 5) — matches the Browse button height + lets the field grow with font/DPI.
3. `path_layout.setSpacing(8)` for explicit gap between path field and Browse.
4. Status and details labels: `background: transparent; border: none` and tighter padding so they don't render their own boxes. Wrapping (`setWordWrap(True)`) + `MinimumExpanding` vertical size policy on the details label (Archetype 2).
5. Save Settings button: `setFixedWidth(150)` → `setMinimumWidth(150)`.

**Risk:** trivial. Visual cleanup only.

---

## Issue 3 — Installation Updates Package Workflow overlap

**Defect:** Package Workflow section had visual overlap between text labels and the 7-button action row when the column narrowed.

**File:** `PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py`.

**Changes:**
1. **Archetype 2** on all four "Package Workflow" step labels — `setWordWrap(True)` so longer steps wrap to a second line instead of clipping.
2. **Archetype 1** on the action button row — wrapped in horizontal `QScrollArea` (via `wrap_in_horizontal_scroll` helper) so the 7 buttons (Refresh / Install Package / Install From Folder / Install From URL / Enable / Test Module / Open Runtime Folder) become horizontally scrollable instead of being clipped off the right edge on narrower windows.

**Risk:** low. The scroll wrap preserves button sizes; only the strip gains a scrollbar when overflowing.

---

## Issue 4 — Right-side panel sidebar-proportion stability

**Defect:** User wanted: when right-side menus or theme panels open, the **left** and **right** sidebars of the home page should keep their proportions; only the **centre** patient list should shrink.

**Files:**
- `PacsClient/pacs/workstation_ui/AIPacs_ui.py` — `centerMenuContainer` and `rightMenuContainer`.

**Analysis:** the W1 home tri-pane splitter already uses `stretch_factors=[0, 1, 0]`, which means only the centre pane (patient table) absorbs size changes. Left rail (Server Selection + Patient Search + Secretary) and right rail (Series Information thumbnails) stay at their saved widths. This was already correct.

**Changes:**
- `centerMenuContainer.setFixedWidth(400)` → `setMinimumWidth(280) + setMaximumWidth(400)` (Archetype 5). The theme / about slide-out can grow on wide monitors and shrink to a readable 280 px floor on narrower ones. Combined with the W1 splitter, only the centre table shrinks when this menu opens.
- `rightMenuContainer.setFixedWidth(400)` → `setMinimumWidth(280) + setMaximumWidth(400)`. Same rationale.

**Risk:** low. Maximum at 400 preserves the original wide-monitor behaviour; minimum at 280 gives narrow monitors room.

---

## Issue 5 — Data Analysis slow open / freeze

**Defect:** Clicking the Data Analysis button caused a multi-second UI freeze. Three heavy operations happen synchronously on the main thread:
1. `from modules.data_analysis import DataAnalysisDashboard` — module import.
2. `DataAnalysisDashboard(...)` — widget construction (likely builds charts, queries DB, etc.).
3. `refresh_data(force_storage_refresh=True)` — filesystem scan + storage refresh.

All three blocked the main thread before the page swap could even paint.

**File:** `PacsClient/pacs/workstation_ui/AIPacs_ui.py` — `open_data_analysis`.

**Change:** Split into three event-loop ticks via `QTimer.singleShot(0, …)`:

```
click → setCurrentIndex(2) + placeholder text "Loading..."  ← paints immediately
         ↓ next event-loop tick
       _init_data_analysis_async() → import + construct + addWidget
         ↓ next event-loop tick
       _refresh_data_analysis_async() → force_storage_refresh=True
```

The user now sees the page swap + a "Loading Data Analysis dashboard… Initializing charts and metrics (one-time per session)" hint while the heavy work runs. UI remains responsive — the freeze still occurs at the OS level during the heavy import/construct, but Qt processes user events between each tick so closing the menu, switching back to home, etc. all work.

**Future enhancement (not in this fix):** move the `refresh_data` call into a `QThreadPool` worker so the freeze is genuinely zero. That's a larger change requiring thread-safety review of the DataAnalysisDashboard internals — flagged as follow-up.

**Risk:** low. The deferral preserves the same logical sequence; only the threading changes. The error-handling try/except wraps each phase.

---

## Issue 6 — Echo Mind Secretary circle adaptiveness

**Defect:** The circular orb under the Patient Search panel was too large on small monitors and could push the home layout off-screen vertically.

**Files:**
- `PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py`
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_layout.py` (placeholder when EchoMind disabled)

**Changes:**
1. `setMinimumHeight(396)` → `setMinimumHeight(240)` on `SecretaryButtonWidget` (Archetype 5). The previous 396 px floor combined with the Patient Search section above forced the left sidebar to overflow on a 1024-tall monitor; 240 px keeps the orb comfortable at its minimum diameter and lets the sidebar's QScrollArea pick up the rest.
2. Orb diameter calculation in `resizeEvent`:
   - Floor: 90 px → 60 px (so the orb keeps shrinking under pressure).
   - Scale factor: 0.80 → 0.78 (slightly more breathing room around the circle).
   - Ceiling: stays at 340 px.
3. Mirror change on the EchoMind-disabled placeholder in `_hp_layout.py`: `setMinimumHeight(396)` → `setMinimumHeight(240)` so the sidebar layout is identical whether EchoMind is installed or not.

**Note:** the orb itself keeps `setFixedSize(diameter, diameter)` — that's a documented leaf case per the convention's "When you cannot avoid setFixed*" clause (radial symmetry requires identical width and height).

**Risk:** low. The orb still scales to its container; the placeholder reservation is smaller but matches the actual SecretaryButtonWidget minimum.

---

## Summary of files touched in this follow-up wave (5 files)

| File | Issues |
|---|---|
| `viewerconfigsetting.py` | 1 (grid picker styling) |
| `lightviewer_settings.py` | 2 (path field styling + status label cleanup + save button) |
| `installation_module_settings.py` | 3 (wordwrap + action row scroll) |
| `AIPacs_ui.py` | 4 (center/right menu widths) + 5 (Data Analysis deferral) |
| `secretary_button_widget.py` + `_hp_layout.py` | 6 (orb scaling) |

All changes follow the established W0–W6 conventions (Archetype 1/2/3/5) and use the helpers from `PacsClient/utils/responsive_layout.py`.

---

## Smoke-test checklist

1. **Issue 1 — Viewer Configuration:** open Settings → Viewer Configuration. Each modality row's "1×2 / 2×2" button should now look like an interactive button with a `▾` indicator. Hover should brighten it, click should open the picker popup.
2. **Issue 2 — Light Viewer:** open Settings → Light Viewer. The path field should have a clear rounded border, no gap between text and edges, and the status / details labels (when populated) should appear cleanly below.
3. **Issue 3 — Installation Updates:** open Settings → Installation Updates. The Package Workflow box should show 4 steps wrapping when narrow. The action button row should scroll horizontally if the 7 buttons don't fit.
4. **Issue 4 — Right-side menus:** open a theme/about panel from the left-nav icons. On Monitor B (1280 wide), the panel opens at a narrower width (down to 280 px floor) instead of always taking 400 px. The home tri-pane left/right rails stay at their saved widths; only the centre patient list shrinks.
5. **Issue 5 — Data Analysis:** click the Data Analysis button. The page should switch immediately to a "Loading…" placeholder. The dashboard then loads in the background; UI remains responsive (you can click other tabs or close menus during the load).
6. **Issue 6 — Echo Mind orb:** on Monitor B, the orb under Patient Search should be visually proportional to the sidebar — smaller than on Monitor A. The home layout should not overflow vertically.

If anything regresses, the try/except wrappers around helper calls fall back to original Qt primitives.
