# Monitor A — Findings (1920 × 1080 @ 100% scaling)
**Date:** 2026-05-26
**Build observed:** `d:\ai-pacs mohamad\ino-pooyan viewer\ai pacs viewer.exe` (packaged build — flagged to user; layout values are identical to the source build's `setFixed*` calls so observations transfer).
**Rubric:** see `RESPONSIVE_UI_TEST_CRITERIA_2026-05-26.md` §1–§2.
**Legend:** **C** = Critical, **M** = Major, **m** = minor, **OK** = pass, **N/A** = not reachable.

---

## Headline result for Monitor A

At 1920 × 1080 the application is **largely well-behaved**. Most panels lay out cleanly, scrollbars appear where the content overflows, and the patient table / sidebar / right-rail thumbnails all fit with room to spare. **No Critical issues observed on Monitor A.** A few Minor inconsistencies noted below. The real value of this baseline is the *comparison* with Monitor B (1280 × 1024) — the layout is sized for the 1920-class budget, so the Monitor B pass is where the `setFixed*` problems should surface.

---

## Screen-by-screen

### 01_home — Home (default after login)

| KPI | Result | Notes |
|---|---|---|
| G1 overlap | OK | None |
| G2 clipping | m | "Modality" column header sort-arrow space looks borderline; long patient name `KAZEM ZADEH^SHAHRBANOO` wraps to 2 lines (graceful — table row autosizes) |
| G3 hidden | OK | All panels visible |
| G4 window-edge | OK | |
| G5 scrollbars | OK | Right-rail thumbnails scroll vertically |
| T1 readability floor | OK | |
| T2 readability ceiling | OK | |
| L1 horizontal reflow | N/A | (not narrowed) |
| L5 spacing/alignment | OK | Patient Search 3×3 modality checkbox grid is even |

**Layout notes:** left nav uses an icon-only collapsed strip + an expanding panel for Server Selection / Patient Search. Right panel shows series thumbnails with the "Study Information" header + "7 series" badge. Centre is a `QTableView` of patients.

### 03_viewer_default_layout — Viewer (single patient open, 2-up empty)

| KPI | Result | Notes |
|---|---|---|
| G1 overlap | OK | |
| G2 clipping | OK | |
| G3 hidden | OK | Toolbar fully visible (~16 buttons + "Intelligent Medical Imaging" label) |
| L1 horizontal reflow | N/A | (not narrowed) |
| L3 sidebar resize | OK | Series Thumbnails sidebar at default ~216 px is reasonable |
| L4 tab strip | OK | Patient chip + AI-Pacs logo + user info all separated with comfortable gaps |
| I1 icon legibility | OK | |
| I2 hit-target | OK | Toolbar buttons ≥ 40×40 px effective |

**Layout notes:** the viewer area is split 2-up with empty drop targets. The far-left vertical-text tab strip (Series / Reception Data / ECHO MIND / EAGLE EYE / Advanced Analysis) renders cleanly. Notable gap between "Intelligent Medical Imaging" label (left) and the rest of the toolbar buttons — looks like a layout `addStretch()` is producing a large empty area at this width.

### 04_title_bar_with_4_chips — Patient chip overflow stress test

| KPI | Result | Notes |
|---|---|---|
| G1 overlap | OK at 4 chips | Plenty of horizontal room — chips end around x≈990, user info container starts around x≈1140, ~150 px clear gap |
| L4 tab strip | OK | |

**🔴 Discovered behaviour worth noting:**
- The app enforces a **hard cap of 4 patient tabs** open at once.
- When trying to open a 5th, a modal dialog appears: "Maximum Patient Tabs Reached - AIPacs — You can only open a maximum of **3** patient tabs at once."
- **Wording bug:** the dialog text says "3" but the actual enforced limit is 4. (Off-by-one in the message string — minor but visible.)

**Layout implication:** because the cap is 4, the worst-case chip-strip width is fixed at `4 × 252 px = 1008 px`. This is the key number for the Monitor B comparison:
- Monitor A (1920 px): 1920 − (150 logo + 1008 chips + 170 user info + 80 window controls) = **+512 px clear** → no overlap possible.
- Monitor B (1280 px): 1280 − 1408 = **−128 px shortfall** → guaranteed overlap or clipping unless the title bar can shrink chips, scroll horizontally, or hide elements. Per the code (`patient_tab_widget.py:113`: `setSizePolicy(Fixed, Fixed)` + `setFixedWidth(252)`), **none of those mechanisms are present**, so we expect a Critical layout break on Monitor B at 4 chips.

This is the cleanest demonstrable case of the `setFixed*` root-cause in `RESPONSIVE_UI_ROOT_CAUSE_2026-05-26.md`.

### 05_settings_server — Settings → Server Settings

| KPI | Result | Notes |
|---|---|---|
| G1 overlap | OK | |
| G3 hidden | OK | Content extends below viewport but **scrolls** — vertical scrollbar appears on the right inside this tab's container (this sub-panel uses `QScrollArea` per audit) |
| L1 horizontal reflow | OK | Two-column AI-PACS / External-PACS layout fits |
| L5 alignment | OK | Form labels (Name / Host / Port / AE Title) align in the grid |

**Layout notes:** Two-column form (AI-PACS Servers + External PACS + Offline Cloud Server + AI Service URL + Reception/Workflow API + Local SCU). Fits comfortably; scroll works for vertical overflow.

### 06_settings_tools — Settings → Tools Settings

| KPI | Result | Notes |
|---|---|---|
| All | OK | Sparse content — only Line Width / Color / Opacity slider / Font Size for the Reference Line sub-tab. Opacity slider expands cleanly across available width (Qt size policy doing the right thing here). |

### 07_settings_viewer — Settings → Viewer Configuration

| KPI | Result | Notes |
|---|---|---|
| G1 overlap | OK | |
| G5 scrollbars | OK | Right-side "Local Storage & Database Cleanup" panel scrolls (drive bars + per-folder breakdown) |
| L1 reflow | OK | Two-column layout: left = Modality Grid + Viewer Mode + GPU Boost + Save/Reload, right = storage panel |

### 08_settings_filter — Settings → Image Filter

| KPI | Result | Notes |
|---|---|---|
| G1 overlap | OK | |
| L5 alignment | OK | Left "Quick guide" text column + right CT/MR collapsible-section column |

### 13_settings_echomind — Settings → EchoMind

| KPI | Result | Notes |
|---|---|---|
| All | OK | Single-column vertical stack (AI Backend, Network/Proxy, Company Authentication). Stretches horizontally; should adapt cleanly to narrower viewports. |

---

## Summary for Monitor A

- **Critical (C):** 0
- **Major (M):** 0
- **Minor (m):** 1 (off-by-one wording in the "Maximum Patient Tabs Reached" dialog: says "3", enforces 4)
- **OK:** rest

**Working well:**
- `QScrollArea` is used on Server Settings, Viewer Configuration (right pane), and the right-rail thumbnail strip — so vertical overflow is handled cleanly on these screens.
- Two-column settings layouts fit comfortably at 1920 px.
- The viewer toolbar and thumbnail sidebar fit without overlap at this width.

**Predicted-to-break on Monitor B (1280 × 1024):**
- **Patient chip strip in title bar** — at 4 chips the math says 128 px shortfall, with no shrink mechanism in the code → expected Critical overlap.
- **Settings two-column layouts** (Server Settings, Viewer Configuration) — fixed widths on left/right columns will fight for space.
- **Viewer toolbar** — 20 fixed-size buttons may push off the right edge or wrap awkwardly.
- **Patient table** — 12 columns at ~80–110 px each = ~1100 px minimum; should fit, but Body Part / Status / Report / Assign columns are narrow and may clip headers.
- **Right-rail thumbnail strip (216 px)** + sidebar collapsed (~62 px) + main content = ~280 px taken before the centre table gets anything. At 1280 px wide this leaves only ~1000 px for the table — borderline.

**Next step:** move the app to Monitor B (1280 × 1024) and repeat the same screen tour with the same KPI grid. The 4-chips-on-Monitor-B case in particular is the litmus test for the layout-defect hypothesis.
