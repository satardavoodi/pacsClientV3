# Responsive UI — Structural Pattern Analysis
**Date:** 2026-05-26
**Inputs:** `findings_monitor_A.md`, `findings_monitor_B.md`, `comparison_AB.md`, plus the audit of `setFixed*` usage across PacsClient/ (172 occurrences in 30 files).
**Purpose:** Step back from individual defects. Identify the antipattern that produces them. Define a codebase-wide convention that prevents the same class of defect from recurring elsewhere.

---

## 1. Why this analysis matters

We tested ~11 specific widgets on Monitor B and found 4 Critical + 8 Major defects. That looks like a manageable patch list. But:

- The codebase contains **172 `setFixed*` calls across 30 files**. We exercised maybe 15–20 of those during the tour. **The remaining ~150 are latent defects** waiting for a narrower window, a different font, a future Windows scaling change, or a translation that produces longer strings.
- The defects we did observe cluster into **seven structural archetypes**, not eleven independent bugs. Every defect we saw is the same misuse of Qt's layout system applied to a slightly different widget kind.
- Patching the 11 specific widgets we saw would leave ~150 ticking defects in place — and the next monitor change, font change, or translation would surface them as fresh-looking "bugs," wasting future engineering time on what is really the same root cause.

Fixing this at the pattern level is what we want, not the widget level.

---

## 2. The one underlying cause (in one sentence)

**The codebase commits to absolute pixel dimensions (`setFixedSize` / `setFixedWidth` / `setFixedHeight`) without supplying any fallback negotiation mechanism — and Qt's layout engine, when its negotiation paths are removed, has no choice but to let widgets overlap, clip, or collapse.**

A `setFixedWidth(252)` call is a contract with Qt that says: *this widget is exactly 252 pixels, full stop, do not ask for less, do not give more*. Combined with `QSizePolicy.Fixed`, it removes every degree of freedom the layout engine could have used to recover from a pixel shortfall. When the parent gets narrower than `sum(fixed_widths)`, Qt cannot redistribute. It draws the children at their pinned sizes and lets them overlap.

This is not a Qt bug. This is the layout system working as documented — but documented as the fallback behaviour for situations the developer was supposed to prevent by either (a) using `setMinimum*` instead, or (b) wrapping the container in `QScrollArea`, or (c) using a `QSplitter` to let the user redistribute, or (d) letting text wrap or elide. None of these were applied.

---

## 3. The seven archetypes (every observed defect maps to one)

Each archetype is a *class* of layout situation that, when handled with `setFixed*` alone, fails predictably under pressure. The Qt-native fix is the *primitive that restores the missing negotiation path* — different per archetype.

### Archetype 1 — Horizontal strip of pinned widgets in a narrow parent

**Examples observed:**
- Patient chip strip (4 chips × 252 px in title bar)
- Light Viewer `Browse... / Clear Path` button pair
- Patient Studies centre toolbar (label + badge + buttons)
- Modality Grid Layout rows (label + combo + label + combo)
- Viewer toolbar (16 buttons in a row) — *partially fixed* via `QScrollArea`

**Mechanism:** the parent container is a `QHBoxLayout`. Children are `setFixedWidth/Size` so they cannot shrink. Container has no `QScrollArea` wrapper, no `addStretch()` to absorb extra space, and the row sum exceeds the parent's available width on a narrower monitor.

**Qt-native fix (in priority order):**
1. Wrap the strip in a horizontal `QScrollArea(horizontalScrollBarPolicy=ScrollBarAsNeeded)` so overflow becomes scrollable. Children keep their pinned size — zero visual regression at default widths.
2. *Or* relax `setFixedWidth(N)` → `setMinimumWidth(N_min) + setMaximumWidth(N_max)` + `QSizePolicy.Preferred` so children shrink under pressure.
3. *Or* if some children are optional (toolbar overflow case), add a `QToolButton` "more" popover for the rightmost items.

### Archetype 2 — Multi-line description text in a `QLabel` without word wrap

**Examples observed:**
- Viewer Configuration: `Local Storage & Database Cleanup` description (`Core app data (e.g., li configuration)` — clipped at `li`)
- Viewer Configuration: `GPU Boost` block ends `Fast mode is` and trails off
- Viewer Configuration: `Backend analysis` block clipped at the right edge

**Mechanism:** `QLabel` defaults to `wordWrap = False`. Text overflows horizontally and gets clipped instead of wrapping to a second line.

**Qt-native fix:** `description_label.setWordWrap(True)`. One method call per label. No other change needed. The label automatically wraps when the container narrows and unwraps when it widens.

### Archetype 3 — Single-line text in a fixed container without elision

**Examples observed:**
- Patient names in chip and table cell: `ABDOLHOSEIN^MOHAM...` (table cell elides correctly; chip clips)
- `Patient Studies` header truncated to `Patient Stu`
- `16 studies found` badge truncated to `1 study f`
- `Offline Sync` button label truncated to `Offline S:`
- Folder path in Offline Cloud Server table: `C:/Users/vahid/Dropbo...`
- Print module series-card text: `MR · 52 ir`, `t2_trufi_CC`, `t2_trufi_tra`

**Mechanism:** the text label is sized to its parent container, which has a fixed width that's too small for the contents. Qt clips by default unless explicitly told to elide.

**Qt-native fix:**
- For `QLabel` with single-line text: override `resizeEvent` to call `QFontMetrics.elidedText(text, Qt.ElideRight, width)` and `setText(elided)` — give a `QToolTip` with the full text so the user can still read it.
- For `QTableView` cells: ensure `QHeaderView::ResizeToContents` or `Stretch` on the relevant column; cell text elides natively when truncated.
- For badge / button labels: also use elided text + tooltip. Don't accept hard clipping.

### Archetype 4 — Tri-pane / multi-pane layouts with fixed-width panels

**Examples observed:**
- Home tri-pane: left nav (~62 px) + left side panel (~280 px) + centre table + right rail (216 px) → only 6 of 12 table columns fit at 1280 px
- Viewer: vertical-tab strip + Series sidebar (~216 px) + 2-up viewer area
- Settings two-column: left form + right list

**Mechanism:** the layout commits to specific panel widths via `setFixedWidth` (e.g. `default_panel_width = 260`). The user cannot redistribute pixels between panels even when they know which panel they want bigger.

**Qt-native fix:** use `QSplitter(Qt.Horizontal)` for the divider between left/centre/right (or wherever the redistribution is wanted). The user drags the splitter; Qt persists state via `splitter.saveState()` / `restoreState()` round-tripped through `QSettings`. The default sizes can still be the current values — but they become starting points, not pinned values.

### Archetype 5 — Form fields with fixed heights/widths inside grid layouts

**Examples observed:**
- `server_settings.py`: every `QLineEdit.setFixedHeight(28)` (13 instances)
- Same file: label widths pinned at 55 / 95 px
- Form buttons: `setFixedHeight(30)`
- Modality Grid `Name` field collapses to 0 px

**Mechanism:** the form grid (`QGridLayout`) can negotiate **column widths** correctly (this is good — `server_settings.py:315-316` uses `setColumnStretch(1, 1)`), but the children commit to fixed **heights**. Result: when font scales or DPI changes, fields cannot grow to accommodate.

For the `Name` field collapse specifically: the field was added without a `stretch=1` argument to `addWidget`, so the parent layout shrank it to its minimum (which Qt computed as 0 because no `setMinimumWidth` was set) to make room for the fixed-width `Grid` combo next to it.

**Qt-native fix:**
- Replace `setFixedHeight(N)` → `setMinimumHeight(N)`. Fields keep their floor height but grow with font.
- For input fields meant to take remaining horizontal space: `addWidget(field, stretch=1)` or `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)` + `setMinimumWidth(120)`.

### Archetype 6 — Table columns with fixed widths

**Examples observed:**
- Patient table on home page: columns at fixed widths, 6 of 12 hidden below visible area on 1280 px
- Offline Cloud Server `Folder` column: `C:/Users/vahid/Dropbo...`

**Mechanism:** `QTableView` columns default to a fixed pixel width or a width based on header text only. There's no stretch policy on the column header, so the table doesn't redistribute when the viewport narrows.

**Qt-native fix:**
- `header.setSectionResizeMode(col_index, QHeaderView.Stretch)` for the column that should absorb extra/insufficient space.
- *Or* `header.setSectionResizeMode(QHeaderView.ResizeToContents)` to auto-size columns to their content, combined with `setHorizontalScrollMode(ScrollPerPixel)` for smooth scrolling when content exceeds viewport.

### Archetype 7 — Empty / oversized centre panes wasting real estate

**Examples observed:**
- Print module centre preview: ~700 × 800 px empty while the side panels are cramped at 1280 px

**Mechanism:** the centre pane has `QSizePolicy.Expanding` (correct in general!) but is empty in the *unselected* state. Qt has no semantic understanding of "this pane is currently empty, give its space to siblings."

**Qt-native fix:** swap the central widget via `QStackedWidget` between "empty state" and "preview state". The empty state can be a small placeholder with `QSizePolicy.Maximum` so siblings reclaim the space. Or wrap the side panels and the centre in a `QSplitter` that the user can drag.

---

## 4. Why this is one problem, not eleven

Look at the column "Mechanism" in §3. Every defect comes from the same two-word phrase: **missing negotiation**. The developer wrote `setFixed*` and the layout engine has no fallback path. The flavour of failure (overlap vs clip vs collapse vs hidden) is just a function of which negotiation primitive was missing:

| Missing primitive | Failure flavour |
|---|---|
| `QScrollArea` wrapper | Overlap (Archetype 1) |
| `setWordWrap(True)` | Multi-line text clipping (Archetype 2) |
| `QFontMetrics.elidedText` | Single-line text hard-clipping (Archetype 3) |
| `QSplitter` | User cannot rebalance panes (Archetype 4) |
| `setMinimum*` + size policy | Field collapse / no font growth (Archetype 5) |
| `QHeaderView::Stretch` | Table columns hidden (Archetype 6) |
| `QStackedWidget` / empty-state handling | Wasted real estate (Archetype 7) |

This is one mistake repeated in seven flavours, ~200 times in the codebase.

---

## 5. The structural solution — three parts

### Part A — Define a project responsive-UI convention (codify the right answer per archetype)

Create `docs/conventions/RESPONSIVE_UI_CONVENTION.md` (new file). It lists the seven archetypes and, for each, *the one Qt primitive AI-PACS uses going forward*. This is short — one page. Future code review against this convention is mechanical: any new `setFixed*` call requires the reviewer to identify which archetype it belongs to and apply the matching primitive.

The convention is the *contract* between contributors. Without it, every developer reinvents a slightly different fix.

### Part B — Provide a small responsive-layout helper module

Create `PacsClient/utils/responsive_layout.py` (new file, ~80 lines). It does **not** re-implement Qt — it bundles the recurring Qt idioms into one-liners so consistency is easy:

```python
"""Project-standard responsive-layout helpers.

These are thin wrappers around Qt primitives — no new behaviour, just
guaranteed-consistent application of the seven archetypes from
RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QHeaderView, QLabel, QScrollArea, QSizePolicy, QSplitter,
    QTableView, QToolTip, QWidget,
)


# --- Archetype 1 ---------------------------------------------------------
def wrap_in_horizontal_scroll(widget: QWidget, *, max_height: int | None = None) -> QScrollArea:
    """Wrap a fixed-width horizontal strip so overflow becomes scrollable.

    Use for: patient chip strip, toolbar with overflow, any row of pinned
    widgets that may exceed parent width on narrow monitors.
    """
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    sa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sa.setFrameShape(QFrame.NoFrame)
    if max_height is not None:
        sa.setMaximumHeight(max_height)
    sa.setWidget(widget)
    return sa


# --- Archetype 2 ---------------------------------------------------------
def make_wrapping_label(text: str, *, max_lines: int | None = None) -> QLabel:
    """Description-style label that wraps to multiple lines."""
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    if max_lines is not None:
        # No native Qt cap, but we can pre-compute height via font metrics
        fm = QFontMetrics(lbl.font())
        lbl.setMaximumHeight(fm.lineSpacing() * max_lines + 4)
    return lbl


# --- Archetype 3 ---------------------------------------------------------
class ElidedLabel(QLabel):
    """Single-line label that ellipsises with tooltip carrying full text.

    Use for: patient names in chips, file paths in narrow cells, badges
    that mustn't grow but must always be readable.
    """
    def __init__(self, text: str = "", parent: QWidget | None = None,
                 elide: Qt.TextElideMode = Qt.ElideRight) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._elide_mode = elide
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self._apply_elision()

    def resizeEvent(self, event) -> None:  # noqa: D401
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        fm = QFontMetrics(self.font())
        super().setText(fm.elidedText(self._full_text, self._elide_mode, max(0, self.width() - 2)))


# --- Archetype 4 ---------------------------------------------------------
def horizontal_splitter(*widgets: QWidget,
                        stretch_factors: list[int] | None = None,
                        collapsible: bool = False) -> QSplitter:
    """Tri-pane / multi-pane horizontal splitter with project defaults."""
    sp = QSplitter(Qt.Horizontal)
    for w in widgets:
        sp.addWidget(w)
    sp.setChildrenCollapsible(collapsible)
    if stretch_factors:
        for i, s in enumerate(stretch_factors):
            sp.setStretchFactor(i, s)
    return sp


# --- Archetype 5 ---------------------------------------------------------
def set_form_field_size(field: QWidget, *, min_height: int = 28,
                        min_width: int | None = None, expanding: bool = False) -> None:
    """Replace setFixedHeight/Width on form fields with min + size policy.

    Default: keeps the 28 px visual floor while letting the field grow with
    font or DPI changes.
    """
    field.setMinimumHeight(min_height)
    if min_width is not None:
        field.setMinimumWidth(min_width)
    hpol = QSizePolicy.Expanding if expanding else QSizePolicy.Preferred
    field.setSizePolicy(hpol, QSizePolicy.Fixed)


# --- Archetype 6 ---------------------------------------------------------
def set_table_column_policy(table: QTableView, *,
                            stretch_column: int | None = None,
                            resize_to_contents: bool = True) -> None:
    """Apply project-standard header sizing to a QTableView."""
    h = table.horizontalHeader()
    if resize_to_contents:
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
    if stretch_column is not None:
        h.setSectionResizeMode(stretch_column, QHeaderView.Stretch)
    table.setHorizontalScrollMode(QTableView.ScrollPerPixel)


# --- Archetype 7 has no helper ------------------------------------------
# Empty-state handling is per-screen design; no one-size-fits-all wrapper.
```

This file is small on purpose. It is **not** a framework. It's a glossary that prevents 30 developers from each guessing a slightly different way to wrap something in `QScrollArea`.

### Part C — Migration playbook (the actual change to the codebase)

The codebase has 172 `setFixed*` calls. We do not need to remove all of them — many are correctly placed on widgets that should genuinely be a fixed size (icons, badge dots, separator widths). The playbook decides which ones to migrate:

**For each `setFixed*` call, ask:**

1. *Is the widget a leaf icon / badge / 1-px separator / radio button indicator?* → keep `setFixed*` (correct usage).
2. *Is the widget in a horizontal/vertical strip that could overflow on a narrow monitor?* → apply Archetype 1 (wrap strip in `wrap_in_horizontal_scroll`).
3. *Is the widget a `QLabel` containing multi-line description text?* → apply Archetype 2 (`make_wrapping_label`).
4. *Is the widget a `QLabel` carrying single-line content that could be longer than its container?* → apply Archetype 3 (`ElidedLabel`).
5. *Is the widget a panel container that the user might want to resize?* → apply Archetype 4 (`horizontal_splitter`).
6. *Is the widget a form field with `setFixedHeight`/`setFixedWidth`?* → apply Archetype 5 (`set_form_field_size`).
7. *Is the widget a `QTableView` column?* → apply Archetype 6 (`set_table_column_policy`).

This is a *mechanical* decision tree. A reviewer can apply it to any `setFixed*` call in ~30 seconds without architectural debate.

**Suggested rollout order** (by ROI):

| Wave | Scope | Effort | Defects resolved |
|---|---|---|---|
| **W0** | Land Part A (convention doc) + Part B (helper module). Zero callers. | 1 h | none yet — infrastructure |
| **W1** | Apply the 4 Critical fixes from Phase 1 of `comparison_AB.md`, but use the helpers from Part B instead of one-off code | 1.5 h | 4 Criticals on Monitor B |
| **W2** | Apply Archetype 2 (`setWordWrap(True)`) everywhere a `QLabel` has multi-line description text. Fast and visible. | 1 h | 3+ Majors |
| **W3** | Apply Archetype 6 to `QTableView` columns in patient table, Offline Cloud Server, any other tables that clip | 1.5 h | 2 Majors |
| **W4** | Apply Archetype 3 (`ElidedLabel`) to chip names, file paths, badge text, button labels project-wide | 2 h | rest of clipping Majors + cleaner UX |
| **W5** | Apply Archetype 5 to `server_settings.py` and other heavy forms — `setFixedHeight(28)` → `set_form_field_size(min_height=28)` | 1.5 h | latent defects under font scaling |
| **W6** | Audit remaining `setFixed*` calls in batches (~30 per session) — apply playbook decision to each | spread | latent defects across remaining files |

**Total active effort: ~10 hours of focused work.** Defects fixed at *every* `setFixed*` site touched, not just the 11 we observed.

### Part D — Auditing tool (one-off, reusable)

Create `tools/dev/audit_fixed_sizes.py` (new file, ~50 lines). It greps the codebase for `setFixed*` calls and produces:

```
PacsClient/pacs/workstation_ui/mainwindow_ui.py:598  setFixedHeight(84)   <ARCHETYPE 5 candidate>
PacsClient/pacs/workstation_ui/mainwindow_ui.py:981  setFixedSize(46, 32) <Archetype 1 / leaf>
PacsClient/pacs/patient_tab/.../patient_tab_widget.py:114  setFixedWidth(252)   <ARCHETYPE 1 — STRIP>
...
```

A reviewer can rerun this after each wave to see how many migrations remain. It also keeps a CI signal — if the count *increases* in a PR, the author has to justify the new `setFixed*` against the convention.

---

## 6. What this is NOT

To be clear about scope:

- **NOT a rewrite of the UI.** The convention and helpers are additive. Existing layouts keep working at Monitor A widths (where they look fine today). Monitor B widths gain the negotiation paths they're missing.
- **NOT a custom layout framework.** Qt's primitives are correct and sufficient. The helper module is a glossary, not a framework.
- **NOT dependent on the `sf()` scale-factor work.** The `sf()` helper from `RESPONSIVE_UI_SCALING_PLAN.md` solves a different problem (user-preference zoom on top of Qt's HiDPI). It composes cleanly with this work but does not block it and is not blocked by it.
- **NOT a touching of viewer hot paths.** Every archetype's fix is at `__init__` time, in container widgets above the VTK renderer. The `vtk_widget.py` / `lightweight_2d_pipeline.py` files are not in scope.

---

## 7. Decision the project owner needs to make

Two paths are now on the table:

**Path A — Patch the 4 specific defects from `comparison_AB.md` Phase 1.**
- Effort: ~100 minutes.
- Outcome: Monitor B home page + chip strip + Light Viewer all stop overlapping.
- Risk: ~150 other `setFixed*` calls remain latent. The next narrow window / longer translation / accessibility-font user will surface a fresh "bug" that is structurally identical.

**Path B — Adopt the convention + helpers + migration playbook (Part A + B + C + D).**
- Effort: ~10 hours of focused work, spread across ~6 small waves.
- Outcome: Monitor B defects fixed PLUS the structural antipattern is named, codified, and migrated. New code is reviewed against a one-page rule. Latent defects continue to be cleaned up as files are touched.
- Risk: more upfront work; no clinical-workflow risk because each wave is independent and gated.

Path B is what the user is asking for ("a broader, correct solution that can improve UI responsiveness across the software"). Path A leaves the antipattern alive in the rest of the codebase.

If Path B is approved, **W0 (convention + helper module) is the first commit** — it has no callers yet, zero regression risk, and unblocks every subsequent wave. W1 then re-implements the Phase 1 Critical fixes using the helpers, so the patch and the structural work are not two separate streams of effort.

---

## 8. One-paragraph summary

The two-monitor test surfaced eleven defects that look isolated but are all the same antipattern: `setFixed*` without a fallback negotiation primitive (`QScrollArea`, `setWordWrap`, `QFontMetrics.elidedText`, `QSplitter`, `setMinimum*` + size policy, `QHeaderView::Stretch`, or `QStackedWidget`). The pattern recurs 172 times in 30 files across the codebase — we tested ~15 sites and saw 11 fail. Patching the 11 widgets fixes the symptoms; codifying a one-page responsive-UI convention + a small helper module + a mechanical migration playbook fixes the cause. The cause-level fix takes about ten hours, uses only Qt-native primitives, does not touch viewer hot paths, and prevents the same class of defect from re-appearing in future code.
