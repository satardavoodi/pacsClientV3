# W2 + W3 + W4 + W5 — Responsive UI hardening, second wave landed
**Date:** 2026-05-26
**Status:** Code on disk; awaiting source-build smoke test.
**Companion docs:** `W1_LANDED.md` (first wave), `RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md` (theory), `docs/conventions/RESPONSIVE_UI_CONVENTION.md` (rule).

This wave applied the responsive-UI convention to the remaining Major defects from `comparison_AB.md`. Same safety pattern as W1: every helper call is wrapped in try/except so an import or runtime failure falls back to the original Qt primitive without breaking the app.

---

## W2 — `setWordWrap` + vertical-growth size policy on multi-line description QLabels

**Defect:** description text in Settings → Viewer Configuration clipped mid-word on Monitor B (`Core app data (e.g., li configuration)`, `Fast mode is`, `Backend analysis` block).

**Root cause confirmed via code read:** the labels DID have `setWordWrap(True)` already, but without an explicit `QSizePolicy.MinimumExpanding` on the vertical axis, Qt would size them at their construction-time sizeHint and not grow when the column narrowed.

**Files touched:**
- `PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py` — added `setSizePolicy(Preferred, MinimumExpanding)` to `gpu_status_label` and `viewer_mode_desc`.
- `PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py` — same on `cleanup_desc`.

**Risk:** trivial. Adding `MinimumExpanding` only grants the label *permission* to grow; it never forces a layout.

---

## W3 — Table column policies (`set_table_column_policy`)

**Defects:**
- Patient table: 6 of 12 columns hidden on Monitor B (root cause was the surrounding tri-pane pinning — already fixed by W1's splitter, but smooth horizontal scrolling was missing).
- Offline Cloud Server table: `Folder` path truncated to `C:/Users/vahid/Dropbo...` — column was at default fixed width, no stretch.

**Files touched:**
- `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py` — added `setHorizontalScrollMode(ScrollPerPixel)` + `setTextElideMode(Qt.ElideRight)` after the column setup. The table header already had `setTextElideMode(ElideRight)` and individual column resize modes; this wave just adds smooth pixel-scroll for the horizontal axis when the table is narrower than the sum of column widths.
- `PacsClient/pacs/workstation_ui/settings_ui/server_settings.py` (Offline Cloud Server) — applied `set_table_column_policy(stretch_column=1)`. Folder column (index 1) now Stretches; the five other columns ResizeToContents.

**Risk:** low. The patient table changes are additive; column widths and visibility are unchanged. The Offline Cloud changes alter the visual layout slightly (Folder column wider, others tighter) but eliminate the path truncation.

---

## W4 — `ElidedLabel` for the patient-chip name (Archetype 3)

**Defect:** patient chip name labels clipped at the chip's fixed width on Monitor B — `ABDOLHOSEIN^MOHAMMAD ABAS` rendered as `ABDOLHOSEIN^MOHA...` with hard truncation and no tooltip.

**File touched:** `PacsClient/pacs/patient_tab/ui/patient_ui/patient_tab_widget.py:78-86` — replaced `QLabel(self.patient_name)` with `ElidedLabel(self.patient_name)`. The chip's 252-px fixed size is unchanged; the label inside now elides explicitly with `...` and shows a tooltip with the full patient name on hover.

**Risk:** trivial. `ElidedLabel` is a `QLabel` subclass; existing stylesheets (`QLabel#PatientName { ... }`) continue to apply.

---

## W5 — `set_form_field_size` across `server_settings.py` (Archetype 5)

**Defect:** every form field in `server_settings.py` pinned with `setFixedHeight(28)` or `setFixedHeight(30)`; every form label pinned with `setFixedWidth(55)` or `setFixedWidth(95)`. On Monitor B these fields cannot grow with font/DPI; on font-scaling accessibility settings the fields would clip their content.

**File touched:** `PacsClient/pacs/workstation_ui/settings_ui/server_settings.py` — converted **all 26 non-leaf `setFixed*` calls** to `setMinimum*` via global `replace_all`:
- `setFixedHeight(28)` → `setMinimumHeight(28)` (13 occurrences)
- `setFixedHeight(30)` → `setMinimumHeight(30)` (10 occurrences)
- `setFixedWidth(55)` → `setMinimumWidth(55)` (form label widths)
- `setFixedWidth(95)` → `setMinimumWidth(95)`
- `setFixedWidth(90)` / `(120)` / `(110)` — status pill and spinner widths → `setMinimumWidth`

The only remaining `setFixed*` in this file is `sep.setFixedHeight(1)` — a 1-pixel separator line, which is a legitimate leaf use (no need to grow).

**Audit verification:** `python tools/dev/audit_fixed_sizes.py server_settings.py` now shows `total: 1, archetype: leaf`. Was 27 before this wave.

**Risk:** low. Replacing `setFixed*` with `setMinimum*` is strictly more permissive — every layout that worked before still works (the minimum is the same); some layouts that didn't fit before now do. The tagging comment `# Archetype 5: grows with font/DPI` after each change is informational.

---

## Summary of behaviour changes

### What looks the same (Monitor A, 1920 × 1080, default font)
- Patient table on home page: same column widths, same visible columns.
- Server Settings form fields: same 28 / 30 px heights at default font.
- Viewer Configuration description blocks: same 1–2 line height at default width.
- Patient chip strip: chips at 252 × 70 px, same as before.

### What looks different (Monitor B, 1280 × 1024)
- **Patient chip names:** `…` with hover-tooltip instead of hard-truncated `MOHA`.
- **Offline Cloud Server "Folder" column:** stretches to absorb available width, full path readable when there's room.
- **Patient table:** smooth horizontal-pixel scrolling when narrow.

### What looks different when the user changes font/DPI/accessibility
- **Form fields in Server Settings:** grow vertically to accommodate larger text instead of clipping.
- **Form labels:** widen as needed when font scales up.
- **Description blocks in Viewer Configuration:** wrap to additional lines instead of clipping.

---

## Files touched in W2-W5 (total: 6)

| File | Wave | Changes |
|---|---|---|
| `PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py` | W2 | +`setSizePolicy(Preferred, MinimumExpanding)` on 2 description labels |
| `PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py` | W2 | +`setSizePolicy(Preferred, MinimumExpanding)` on 1 description label |
| `PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py` | W3 | +`setHorizontalScrollMode(ScrollPerPixel)`, +`setTextElideMode(ElideRight)` |
| `PacsClient/pacs/workstation_ui/settings_ui/server_settings.py` | W3 + W5 | +`set_table_column_policy` on Offline Cloud table; 26 setFixed* → setMinimum* |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_tab_widget.py` | W4 | name_label: `QLabel` → `ElidedLabel` |

---

## Audit progress

| Wave | Project-wide setFixed* count |
|---|---|
| Before W0 | ~172 across 30 files |
| After W1 | ~167 (4 Critical fixes touched ~5 sites) |
| **After W5** | **~140** (~27 more sites converted in server_settings.py + scattered) |

Remaining sites for W6 rolling cleanup:
- `mainwindow_ui.py` (5 sites; 3 are window buttons — leaves, 2 are title-bar heights — Archetype 5)
- `AIPacs_ui.py` (9 sites; the shell-menu constants like `_menu_button_size` are debatable — they're "spec dimensions" the project wants to keep)
- `patient_tab_widget.py` (4 sites; the chip outer dimensions are intentional for the W1 scroll-area design)
- `toolbar_manager.py` (20 sites; mostly icon-sizes which are leaves)
- Various others (~50–70 sites)

Many of the remaining are legitimately leaf-tier (icons, badges, separators, 1-px lines). The auditor's classification heuristic catches most of those (`archetype: leaf`); the rest are reviewer judgement calls.

---

## Smoke-test checklist (Monitor B, source build)

1. **Patient chip name:** open a patient with a long name → chip shows `…` and full name appears as tooltip on hover.
2. **Server Settings → Offline Cloud Server:** when a long folder path is added, the Folder column expands to show the full path; on narrower windows it elides with `...` (Qt's native table-cell elision).
3. **Server Settings form fields:** open Settings → Server Settings; with the default font everything looks the same; if you increase Windows text size (Settings → Accessibility → Text size to 125%), the form fields grow vertically and don't clip their content.
4. **Viewer Configuration descriptions:** drag the home splitter to make the Settings column narrower → the GPU Boost and Local Storage descriptions wrap to more lines instead of being clipped.
5. **Patient table horizontal scroll:** with the splitter narrowed, the table scrolls smoothly per-pixel with the mouse wheel instead of jumping column-by-column.

---

## Rollback

Each wave is a small set of edits to a small set of files. Rollback is `git revert` on the specific files. The helper module (`PacsClient/utils/responsive_layout.py`) stays in place — it has no callers when no waves are active, so reverting is straightforward per-wave.
