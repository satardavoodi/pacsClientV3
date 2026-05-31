# Home Page — Cluster / Layout Review (V2)

**Status:** Review + implementation plan. All proposed changes are gated behind
`get_ui_variant('home') == 'v2'`; V1 stays byte-identical.
**Date:** 2026-05-30
**Method:** Live inspection of the running source build (Home page) on monitor A.
**Companions:** `V2_DESIGN_SYSTEM_AS_BUILT.md` (authoritative as-built), `UI_UX_DESIGN_REVIEW.md`,
`CLAUDE_DESIGN_WORKSTATION_V1_PLAN.md`.

This review looks specifically at **clustering** — how the Home screen groups its controls — and
how to tighten the visual hierarchy using the V2 helpers we already ship.

## Zones (as-built)

1. **Left icon rail** — vertical monochrome nav (menu, home, list, print, settings, download,
   globe, book; then grid, info, help). Clean.
2. **Left control panel** — `Adaptive to Screen Size` button (ungrouped, top) · **Server Selection**
   box (Local/Server/Import, PACS server picker, "Server Ready") · **Patient Search** box (DX/CT/MR/
   US/MG/CR/NM/PT/XA modality grid, Patient ID, Patient Name, date range, **Search Patients**) ·
   EchoMind avatar circle + "Ready" status.
3. **Top header** — AI‑Pacs logo · active-patient chip · download · user/role · window controls.
4. **Sub-toolbar row** — `Patient …` · `10 studies found` pill · A‑/A+ · refresh · gear · trash ·
   `Offline Sync` · print · capture · download · `Study Information` pill · `10 series`.
5. **Results table** — Patient Name, Patient ID, Body Part, Status, Report, Assign, Time, Date,
   Images, Modality, Age.
6. **Right series rail** — Series 0/1/2/3 cards (preview, label, image count).

## What works
Two clearly boxed left-panel groups; clean monochrome rail; semantic green status checks;
consistent right-rail series cards.

## Clustering problems (priority order)

### P1 — The sub-toolbar (zone 4) is an undifferentiated cluster
~10 equal-weight controls in one row with no separators and no grouping. Mixed shapes (pills +
square icons) and no clear primary. Hard to scan.
**Fix:** split into 3 visually separated clusters with thin 1px `border` dividers + small spacing:
- **View:** `A‑` / `A+` / refresh
- **Study actions:** Offline Sync / print / capture / download
- **Destructive:** trash (slightly separated; `danger` only on hover/intent)
Give every icon the V2 ghost treatment (transparent rest, `accent_soft` hover) so they read as one family.

### P2 — Blue overload / no single primary action
`Search Patients`, the `Study Information` pill, and the `10 studies found` pill all use accent blue.
**Fix:** exactly one primary-blue per zone. Keep `Search Patients` primary; demote `Study Information`
to the V2 **secondary outline** (`secondary_button_qss`); render `10 studies found` / `10 series` as a
quiet count chip (`badge_blue`/muted), not a filled accent pill.

### P3 — Left-panel weighting
`Adaptive to Screen Size` competes at the top (V2 already demotes it to outline — keep that). The
EchoMind avatar circle is visually heavy for its function density.
**Fix:** keep the Adaptive demotion; reduce the avatar's chrome (smaller ring / quieter border) so the
Search group remains the focal point.

### P4 — Mixed control shapes
Pills, square icon buttons, and one large rounded button mix radii/fills in the same view.
**Fix:** unify via the V2 tokens — one corner radius, ghost-rest, `accent` active — across the zone.

### P5 — Table micro-alignment
Short/numeric columns (Images, Age, Time, Modality) are centred, which slows scanning.
**Fix:** right-align numeric columns (Images, Age), keep text columns left-aligned; consistent header
casing. Lives in `results_table_qss` / the table's column setup.

## Implementation mapping (all gated `home==v2`, applied at the source style fn)

| Item | Helper / where |
|---|---|
| P2 demote `Study Information` | `apply_secondary_button_v2` (reuse `secondary_button_qss`) at the button's source style |
| P2 count chips | reuse `badge_qss` / a quiet `count_chip_qss` for `N studies found` / `N series` |
| P1 sub-toolbar ghost icons | reuse `qtoolbutton_qss` / `tool_button_qss` ghost; add separators in the layout (gated) |
| P5 numeric alignment | `results_table_qss` + per-column `setTextAlignment` (gated in `_apply_theme` / table setup) |
| P3 avatar chrome | quiet border/size on the EchoMind avatar widget (gated) |

## Rollout order (value ÷ risk)
1. **P2** — demote `Study Information` + quiet count chips. *Styling only, lowest risk, immediate hierarchy win.*
2. **P5** — numeric column alignment. *Small, but see note below.*
3. **P1** — sub-toolbar grouping + ghost icons (separators = minor layout edit, gated).
4. **P3 / P4** — left-panel weighting + shape unification polish.

Each step: gate it, relaunch V2, confirm V1 (flag off) unchanged, run
`tests/code/test_v2_style_scaffold.py`.

## Progress (2026-05-30)

- **P2 — DONE.** `home_panel_header_qss` / `apply_home_panel_header_v2` flattens the
  `Study Information` header (filled blue gradient → quiet panel header) at its source style fn in
  `home_ui/right_panel_widget.py`; `home_count_chip_qss` / `apply_home_count_chip_v2` quiets the
  series-count chip. The `N studies found` label is **already** a quiet grey chip (no change). So in
  V2 the only primary-blue on Home is now `Search Patients`. Tests added to
  `test_v2_style_scaffold.py`.
- **P5 — DONE (safe route).** Added `_RightAlignCombinedDelegate(CombinedDelegate)` in
  `patient_table_widget.py` that only overrides `initStyleOption` to right-align text; it's installed
  on the **Images** and **Age** columns inside `_setup_neon_highlight_delegate`, which reads
  `home_is_v2()` **once** at table construction (never per-row/per-paint, so no repeated disk reads).
  Reuses CombinedDelegate's painting so selection/underline behaviour is unchanged. V1 keeps the
  centred CombinedDelegate.
- **P1 — DONE.** `home_toolbar_button_qss` + `apply_home_toolbar_buttons_v2` flatten the sub-toolbar's
  coloured gradient blocks into one flat ghost family — `download` = the single filled-accent primary,
  `delete` = danger-on-hover, the rest neutral ghost (hooked once at the end of
  `PatientTableWidget._apply_theme`, survives re-styling). `_make_v2_toolbar_separator` adds thin
  dividers so the row reads as **view | config | study-actions** clusters (gated, inserted once in
  `header_layout`, no reorder). Also resolves **P4** for this row.
- **P3** — left-panel EchoMind avatar (`secretary_button_widget.py`) is custom-painted and already
  visually subtle on screen; deprioritised (low value; would need a cached flag for its `paintEvent`).
- **P4** — covered by P1's flattening.

## Verified live (V2, monitor A — 2026-05-30)
Confirmed rendering in the running source build: quiet "Study Information" header + "N series" chip,
flat ghost sub-toolbar (no coloured blocks, trash not red), and right-aligned Images/Age columns.
Sub-toolbar separators appear on the next table build (relaunch).
