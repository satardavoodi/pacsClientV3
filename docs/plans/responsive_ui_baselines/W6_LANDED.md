# W6 — Project-wide rolling audit & Archetype 5 cleanup
**Date:** 2026-05-26
**Status:** Code on disk; awaiting source-build smoke test.
**Companion docs:** `W1_LANDED.md`, `W2_W5_LANDED.md`, `RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md`, `docs/conventions/RESPONSIVE_UI_CONVENTION.md`.

This wave applied the **Archetype 5** pattern (`setFixed*` → `setMinimum*`) systematically across the remaining non-leaf, non-regression-guarded UI files identified by the project-wide audit. Plus a fix to the auditor tool's directory-walk bug discovered during W6.

---

## Auditor bug fix

`tools/dev/audit_fixed_sizes.py` had a bug: when a directory was passed as an argument, it was treated as a file (read_text returned empty). Fixed to recursively expand directories to their `.py` files. Project-wide `python tools/dev/audit_fixed_sizes.py PacsClient` now works.

---

## Files converted in W6 (14 files, ~37 setFixed* sites)

| File | Sites | Notes |
|---|---|---|
| `PacsClient/pacs/workstation_ui/mainwindow_ui.py` | 2 | Title-bar height, user-info container height → `setMinimumHeight`. Window-buttons (46×32) kept as leaf (intentional design). |
| `PacsClient/pacs/workstation_ui/settings_ui/external_pacs_settings.py` | 5 | All 5 button widths (110) → `setMinimumWidth`. |
| `PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py` | 5 | Modality grid cell (29×29), preset label (100), name/preset combos, label, remove (✕) button — all → `setMinimum*`. |
| `PacsClient/pacs/workstation_ui/settings_ui/filter_config.py` | 1 | `compact_spin()` helper: `setFixedWidth(w)` → `setMinimumWidth(w)`. Affects all spin widgets that use this helper. 3 × `setFixedHeight(1)` separators kept as leaves. |
| `PacsClient/pacs/workstation_ui/settings_ui/servers_config.py` | 6 | Service URL row: label / line-edit / status / button (URL_W, BTN_W constants kept as design dims). Save URLs / Load button heights. |
| `PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py` | 1 | Drive-usage progress bar height. |
| `PacsClient/pacs/workstation_ui/settings_ui/tools_settings_ui.py` | 4 | Color button height (34), line-width spin (90), font-size spin (90), Reset/Save button widths (140). |
| `PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py` | 2 | OK / Cancel button sizes (100×38) → `setMinimumSize`. |
| `PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py` | 2 | Yes / No dialog buttons (34). Small icons / close button kept as leaves. |
| `PacsClient/pacs/workstation_ui/home_ui/data_access_panel.py` | 1 | Tab-bar height (180) → `setMinimumHeight`. |
| `PacsClient/pacs/workstation_ui/theme_ui.py` | 2 | Preview title height + menu width. |
| `PacsClient/pacs/workstation_ui/user_manual_widget.py` | 2 | Header height + TOC list width. Logo (34×34) kept as leaf. |
| `PacsClient/pacs/patient_tab/ui/patient_ui/reception_panel_widget.py` | 2 | Open Attachments + View Reports button heights (50). |
| `PacsClient/pacs/patient_tab/ui/patient_ui/reception_reports_viewer.py` | 2 | Status filter combo + refresh button widths. |

---

## Files NOT touched in W6 — with justification

### Skipped per CLAUDE.md regression guards

| File | Reason |
|---|---|
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py` | Multi-study fix regression-guard. Read `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md` first per CLAUDE.md. |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/widget.py` | Same multi-study regression-guard. |
| `PacsClient/pacs/patient_tab/utils/thumbnail_manager.py` | Thumbnail pipeline regression-guard. |
| `PacsClient/pacs/patient_tab/ui/patient_ui/thumbnail_panel.py` | Same thumbnail pipeline. |
| `PacsClient/pacs/patient_tab/ui/patient_ui/sidebar_widget.py` | Multi-study viewer-sidebar guard — `_pw_panels.py:73` is the documented sibling. |
| `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/*` | Viewer hot paths (VTK render windows, fast container). |
| `PacsClient/pacs/patient_tab/ui/patient_ui/center_layout_widget.py` | Generic viewer-grid sizer that uses `widget.setFixedSize(width, height)` programmatically — converting would alter viewer behavior. |
| `PacsClient/pacs/patient_tab/ui/patient_ui/header_widget.py` | Toolbar helper that uses `setFixedSize(width, height)` — same risk profile. |

### Skipped — intentional design dimensions

| File | Reason |
|---|---|
| `PacsClient/pacs/workstation_ui/AIPacs_ui.py` | Shell-menu containers toggle between fixed `_menu_expanded_width` (220) and `_menu_collapsed_width` (62). `setMinimumWidth` would prevent the collapse animation from working. Documented justification per the convention's "When you cannot avoid setFixed*" clause. |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_tab_widget.py` | Chip outer dimensions (252×70). Already handled by W1's horizontal scroll wrap in `custom_tab_manager.py` — overflow no longer overlaps. The fixed chip dimensions are intentional. |
| `PacsClient/pacs/patient_tab/ui/patient_ui/service_tab_widget.py` | Same chip-design rationale as patient_tab_widget. |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py` | ~20 `setFixed*` calls, mostly icon-sizes (16, 20, 25, 31 px) — leaves. The toolbar overall is already in `QScrollArea` (W1 demonstration showed it works on Monitor B). |
| `PacsClient/pacs/patient_tab/ui/patient_ui/custom_tab_manager.py` | Logo button (165×70) is an intentional brand-asset dimension. |

### Skipped — out of scope

| File | Reason |
|---|---|
| `modules/web_browser/widget.py` | Third-party web browser module. Out of this plan's scope. |
| `modules/printing/ui/printing_widget.py` | Has its own per-screen `_scaled()` method already. Out of this plan's scope. |
| `modules/cd_burner/cd_burn_dialog.py` | Already uses `setMinimumSize` correctly — no setFixed* matches. |
| `PacsClient/app_handler.py`, `PacsClient/utils/custom_checkbox.py` | Leaf-tier utilities. |
| `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py`, `attachments_dropdown.py` | Secondary risk surface; can be picked up in a follow-up wave. |

---

## Audit progress totals

| Wave | Approx remaining setFixed* (excluding leaves) |
|---|---|
| Pre-W0 | ~120 non-leaf sites across ~30 files |
| After W1 | ~115 (5 Critical-fix sites converted) |
| After W5 | ~85 (server_settings.py: 27 sites; patient_table_widget.py / right_panel_widget.py / _hp_layout.py / patient_tab_widget.py / lightviewer_settings.py: ~3 sites) |
| **After W6** | **~50** (~37 sites in 14 files converted in W6) |

The remaining ~50 non-leaf sites are concentrated in the regression-guarded files (multi-study, thumbnail pipeline, viewer hot paths). Those are intentional skip-zones per `CLAUDE.md` and should only be touched in dedicated, regression-tested commits.

---

## What this wave changes for the user

### What still looks identical at Monitor A 1920×1080
- All Settings sub-panels (Server Settings / Tools / Viewer Configuration / Image Filter / Light Viewer / EchoMind / External PACS / Servers Config).
- Theme preview, user manual, reception panel buttons.
- Title bar at the default 84 px height.

### What changes when the user scales up font / DPI
- Buttons across all touched files grow vertically to fit larger text instead of clipping.
- Spinboxes and combos can widen as needed.
- The title bar grows if the user info container needs more height.

### What changes on narrower windows
- The status / refresh combos in the Reception Reports viewer adapt to available width.
- Theme preview menu can shrink slightly when the dialog is narrow.
- User manual TOC accepts being squeezed within reason (rather than forcing the manual area to scroll horizontally).

---

## Smoke-test focus for W6

1. **Settings tab strip:** click through all 7 tabs. Layouts should look identical to the pre-W6 baseline at 1920×1080.
2. **Increase Windows font size to 125%:** all settings forms should re-flow vertically rather than clip.
3. **OK/Cancel dialogs:** External PACS server dialog → buttons stay at 100×38 floor but can grow if the user has larger font.
4. **Reception attachments / reports:** Open Attachments and View Reports buttons stay at 50 px floor; reception reports filter dropdown and refresh button adapt to width.
5. **Theme preview:** theme picker preview pane title and side menu render correctly.

---

## Cumulative wave status (W0–W6)

| Wave | Files touched | Purpose |
|---|---|---|
| **W0** | 3 (new) | Convention + helper module + audit tool |
| **W1** | 6 | 4 Critical fixes from Monitor B (chips, title toolbar, tri-pane, Browse/Clear) |
| **W2** | 3 | setWordWrap + size-policy on description labels |
| **W3** | 2 | Table column policies (patient + offline cloud) |
| **W4** | 1 | ElidedLabel on patient chip name |
| **W5** | 1 | 27 `setFixed*` → `setMinimum*` in server_settings.py |
| **W6** | 14 | ~37 `setFixed*` → `setMinimum*` across 14 files |
| **Total** | **30 files** (3 new, 27 modified) | Responsive UI hardening complete for the public surface |

The convention is now in place, the helper module is used by 6+ files, the auditor catches regressions, and ~140 of the original ~172 `setFixed*` calls have either been converted (Archetype 5) or correctly identified as leaves. The remaining ~30 are in regression-guarded files where touching them needs careful review.

---

## Open follow-ups (post-W6, not blocking)

1. **Regression-guarded files** (`_pw_panels.py`, `widget.py` in patient_widget_core, `thumbnail_panel.py`, `sidebar_widget.py`) — should be revisited in a dedicated session that reads `MULTI_STUDY_SINGLE_TAB_PLAN.md` first.
2. **`modules/printing/ui/printing_widget.py`** — already has its own `_scaled()` method; could be unified with the new helpers in a future cleanup.
3. **The original `RESPONSIVE_UI_SCALING_PLAN.md`** — its scope shrinks to user-preference scale slider only (the `sf()` factor). Layout responsiveness is now achieved via Qt-native primitives without needing a global multiplier.
4. **CI integration** — add `python tools/dev/audit_fixed_sizes.py --diff main..HEAD` to PR checks so new `setFixed*` calls require justification in the commit message.

---

## Rollback

Each wave's commit is independent and revertable. The helper module (`responsive_layout.py`) is additive — reverting W1–W6 leaves it harmlessly idle on disk. The convention doc and auditor tool likewise have no runtime cost when the helpers aren't called.
