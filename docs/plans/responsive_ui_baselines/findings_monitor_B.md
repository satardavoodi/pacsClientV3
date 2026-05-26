# Monitor B — Findings (1280 × 1024 @ 100% scaling)
**Date:** 2026-05-26
**Build observed:** `d:\ai-pacs mohamad\ino-pooyan viewer\ai pacs viewer.exe` (same packaged build as Monitor A pass)
**Rubric:** see `RESPONSIVE_UI_TEST_CRITERIA_2026-05-26.md` §1–§2.
**Legend:** **C** = Critical, **M** = Major, **m** = minor, **OK** = pass, **N/A** = not reachable.

---

## Headline result for Monitor B

Layout **breaks in multiple visible, workflow-blocking ways** at 1280 × 1024. The defects are exactly those predicted from the code audit: `setFixedWidth/Height/Size` + missing `QSizePolicy`/`QScrollArea` mean the layout cannot negotiate when the pixel budget shrinks. The chip-strip overlap is the cleanest visual proof of the root cause — chips render on top of each other, hiding close buttons, instead of scrolling or shrinking.

**Critical issues: 3.** **Major: 4.** **Minor: 2.**

---

## Screen-by-screen

### 01_home — Home (default after login)

| KPI | Result | Notes |
|---|---|---|
| **G2 clipping** | **C** | Multiple labels truncated: `Patient Studies` → `Patient Stu`; `16 studies found` badge → `1 study f`; `Offline Sync` button → `Offline S:` |
| **G3 hidden** | **C** | Patient table shows only 6 of 12 columns (Patient Name / Patient ID / Body Part / Status / Report visible; Assign / Time / Date / Images / Modality / Age require horizontal scroll). The hidden columns include **Date** and **Modality** — both routinely needed for clinical workflow. |
| G2 patient name | M | `ABDOLHOSEIN^MOHAM...` truncated with ellipsis in the table cell |
| G5 scrollbars | OK | Horizontal scrollbar appears on the patient table (this works — Qt's `QTableView` does it natively) |
| L1 reflow | M | Left panel (Server Selection + Patient Search at default ~280 px) + right rail (Series Information, 216 px) consume ~500 px / 1280 = 39 % of width on a 1280 px screen, leaving only ~780 px for the centre table |
| T1 readability | OK | Body text remains legible |

### 04_title_bar_with_4_chips — **DEFINITIVE LAYOUT-DEFECT DEMO**

| KPI | Result | Notes |
|---|---|---|
| **G1 overlap** | **C** | **Chips physically overlap each other.** Each subsequent chip is drawn on top of the preceding chip. |
| **G3 hidden** | **C** | The **close button (×) of chip 1 (ABDOLHOSEIN) is hidden** behind chip 2, so the user cannot close the first tab without first closing later tabs. Workflow blocker. |
| L4 tab strip overflow | **C** | No horizontal scroll, no shrink, no wrap, no "more" overflow button. Chips just stack visually. |

**Mechanism:** `patient_tab_widget.py:113-115`:
```python
self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
self.setFixedWidth(252)
self.setFixedHeight(70)
```
The chip explicitly opts out of layout flexibility. When the available chip-strip width (~650 px on Monitor B) is less than `4 × 252 px = 1008 px`, the parent `QHBoxLayout` has no negotiation path and lets the children overlap.

**Qt-native fixes that would work:**
- Wrap the chip container in a horizontal `QScrollArea(setHorizontalScrollBarPolicy=ScrollBarAsNeeded)`. Chips keep their fixed size, strip scrolls horizontally — the established Qt pattern.
- *or* replace custom chips with `QTabBar` items + `setUsesScrollButtons(True)` — Qt's tab bar already handles overflow.
- *or* change `setFixedWidth(252)` → `setMinimumWidth(180) + setMaximumWidth(252)` + `QSizePolicy.Preferred` so chips shrink down to 180 px under pressure.

### 03_viewer_default_layout — Viewer (single patient open)

| KPI | Result | Notes |
|---|---|---|
| **G3 hidden** | **M** | Viewer toolbar has more buttons than fit (`eye`, `graduate cap`, `MPR` were visible only after horizontal-scrolling the toolbar; `cloud download` still hidden) |
| G5 scrollbars | OK | Horizontal scrollbar appears below the toolbar — `toolbar_manager.py` does have a `QScrollArea` wrapping the buttons, so this is the Qt-native fix already working here |
| L3 sidebar | M | Series Thumbnails sidebar at fixed 216 px is consuming ~17 % of the 1280 px width — heavy but not blocking |
| I1 icon legibility | OK | |
| G2 patient name in chip | M | `ABDOLHOSEIN^MOHA...` truncated |

**Note:** the viewer toolbar IS using `QScrollArea` (one of the 6 `QScrollArea` usages I confirmed earlier in `toolbar_manager.py`), and it's working correctly here. The user can scroll to reach hidden buttons. So the toolbar is **workflow-degraded but not broken** — contrast with the chip strip which has no scroll.

### 05_settings_server — Settings → Server Settings

| KPI | Result | Notes |
|---|---|---|
| G1 overlap | OK | Two-column layout still fits |
| **G2 clipping** | **M** | `Offline Cloud Server` Folder column shows `C:/Users/vahid/Dropbo...` — long folder path truncated. Date may also be affected (off-screen). |
| G5 scrollbars | OK | Vertical scrollbar visible on right edge — `QScrollArea` is wrapping this sub-panel and it works |
| L1 reflow | M | The two columns get cramped — left column ~570 px, right column ~570 px. Button rows in the right column (New / Echo / Verify All / Delete / Edit / Refresh) get tighter but still fit. |

### 13_settings_echomind — Settings → EchoMind

| KPI | Result | Notes |
|---|---|---|
| All | OK | Single-column vertical stack adapts cleanly. This is the layout pattern that doesn't break — every other settings sub-panel should probably follow this model. |

### Settings tabs strip

| KPI | Result | Notes |
|---|---|---|
| L4 | m | All 7 tabs (Server Settings, Tools Settings, Viewer Configuration, Image Filter, Installation Updates, Light Viewer, EchoMind) still fit at 1280 px, but tighter spacing. No tab clipping. |

---

### 14_settings_lightviewer — Settings → Light Viewer (user-supplied screenshot, 2026-05-26)

| KPI | Result | Notes |
|---|---|---|
| **G1 overlap** | **C** | `Browse...` and `Clear Path` buttons physically overlap each other on the right of the DICOM Light Viewer Executable path field. Same root cause as chip overlap — both buttons are pinned with `setFixed*` and the parent layout has no room to give them. Result: clicking the visible button works, but the lower button (`Clear Path`) is partially or fully hidden. |

### 07_settings_viewer_config — Settings → Viewer Configuration (user-supplied screenshot, 2026-05-26)

| KPI | Result | Notes |
|---|---|---|
| **G2 clipping** | **M** | Multiple description text blocks truncated mid-word: `Local Storage & Database Cleanup` description ends with `Core app data (e.g., li configuration) is never deleted` (the word `license` is cropped); `GPU Boost` block ends with `Fast mode is` and trails off; `Backend analysis` block clipped at the right edge. These are not single labels — they are multi-line `QLabel` blocks that should `setWordWrap(True)` and adapt to the container width. |
| **G3 hidden / G1 overlap** | **M** | `Modality Grid Layout` dropdowns: the `Layout` column shows `1 × 2` text only in some cells; other cells render as empty dark rectangles. The underlying QComboBoxes appear to be sized correctly but their popup-content rendering is missing — likely a `setFixed*` width on the combo that's smaller than the text needs. |
| **G3 hidden** | **M** | `Name` field next to the `Grid` combo at the bottom of Modality Grid Layout collapses to ~0 px wide — invisible. The label is there but the input field has no allocated space. |

### 11_print_module — Print module main screen (user-supplied screenshot, 2026-05-26)

| KPI | Result | Notes |
|---|---|---|
| **G2 clipping** | **m–M** | Series card labels truncated in the left panel: `MR · 52 ir` (should be `52 images`), `MR · 30 ir`, etc. on every series card. Description text `t2_trufi_CC`, `t2_trufi_tra` truncated. |
| L1 reflow | **M** | Centre preview pane is ~700 × 800 px and entirely empty — that real-estate could be redistributed to the cramped left/right panels at 1280 px width. Not a defect of overlap, but of layout proportion. |
| G1 / G3 overlap / hidden | OK | Nothing physically overlapping in the visible widgets; the layout itself negotiates here (printer panel labels fit, Image range From/To fit). |

---

## Summary for Monitor B

- **Critical (C):** **4** (chip overlap with hidden close button; patient table 6 of 12 columns hidden; header / badge / "Offline Sync" label truncation; Light Viewer Browse/Clear Path button overlap)
- **Major (M):** **8** (viewer toolbar buttons hidden behind scroll; sidebar consumes too much width; patient name truncated in cells; Folder path truncated in Offline Cloud Server table; Viewer Configuration description blocks clipped × 3; Modality Grid dropdowns missing content; Name field collapsed; Print module preview pane oversized)
- **Minor (m):** 3 (settings tab strip tighter; minor spacing variance; print module series-card text truncation)
- **OK:** all `QScrollArea`-wrapped panels work — Server Settings scrolls, viewer toolbar scrolls, patient table scrolls.

### What worked (Qt-native primitives that protect the layout)

- `QTableView` native horizontal/vertical scrollbars (patient table is browseable).
- `QScrollArea` on Server Settings, Viewer Configuration right pane, viewer toolbar.
- EchoMind's single-column vertical layout adapts naturally.

### What broke (places `setFixed*` defeats Qt's layout engine)

1. **Chip strip in title bar** — `setSizePolicy(Fixed, Fixed) + setFixedWidth(252)` with no `QScrollArea` wrapper. Chips stack visually on top of each other.
2. **Center toolbar buttons** above the patient table (`Patient Studies` label, `16 studies found` badge, `A-/A+/refresh/settings/trash/Offline Sync/print/?/download`) — labels and badge text get clipped because their containers are pinned and there's no `QScrollArea` for that toolbar.
3. **Patient table column visibility** — actually a column-width / panel-priority issue: left panel + right rail consume 39 % of the screen, squeezing the centre.
4. **Truncation in dialogs / cells** — text labels in tight containers don't get an ellipsis or shrink mechanism in some places, just a hard cut.

### The 3-line code change that would fix the worst defect

To stop chip overlap (the most visible problem), in `patient_tab_widget.py`'s parent container:

```python
# Wrap the chip strip in a horizontal scroll area
chip_scroll = QScrollArea()
chip_scroll.setWidgetResizable(True)
chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
chip_scroll.setFrameShape(QFrame.NoFrame)
chip_scroll.setWidget(chip_container)   # the existing container that holds all chips
title_layout.addWidget(chip_scroll, stretch=1)
```

The chips themselves stay `Fixed/Fixed` at 252 × 70 — no risk of altering their appearance. The strip just becomes scrollable when overflowing. This is purely Qt-native, no custom `sf()` math, no `setFixed*` removal.

### Confirmation of the root-cause hypothesis

The Monitor A vs Monitor B comparison is unambiguous:
- **Monitor A (1920 px):** no Critical issues. Same code paths, but the pixel budget is large enough to hide the defects.
- **Monitor B (1280 px):** 3 Criticals + 4 Majors. Same code paths, smaller budget — defects manifest exactly where the audit predicted (`setFixed*` + missing `QScrollArea`).

The DPI is identical on both monitors (100 %), so this is **purely** a pixel-budget / layout-flexibility problem. A `sf()` scale-factor helper would not have helped here — multiplying `setFixedWidth(252)` by `sf(1.0)` still gives `setFixedWidth(252)`, and the chips would still overlap. The fix has to come from Qt's layout primitives, not from a scale-factor multiplier.

This confirms the conclusion in `RESPONSIVE_UI_ROOT_CAUSE_2026-05-26.md`: **Track 1 (Qt-native layout hardening) is the correct intervention. Track 2 (`sf()` helper) is polish on top.**
