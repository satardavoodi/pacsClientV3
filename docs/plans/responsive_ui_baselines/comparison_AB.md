# Monitor A vs Monitor B — Comparison & Implementation Backlog
**Date:** 2026-05-26
**Test setup:** Identical app, identical session, identical 100 % Windows scaling. The only variable is pixel budget (1920 × 1080 vs 1280 × 1024).
**Conclusion:** Layout defects are caused by `setFixed*` + missing `QScrollArea`, not by DPI math. Qt-native layout hardening (Track 1) is the correct intervention. The `sf()` scale-factor helper (Track 2) would not have prevented any of the observed Critical issues.

---

## 1. Side-by-side KPI table

| Screen | KPI | Monitor A (1920) | Monitor B (1280) | Diff |
|---|---|---|---|---|
| 01_home | G2 clipping | m (Modality header borderline) | **C** (Patient Studies / 16 studies found / Offline Sync all truncated) | **regression** |
| 01_home | G3 hidden | OK | **C** (6 of 12 table columns require horizontal scroll, including Date and Modality) | **regression** |
| 01_home | G5 scrollbars | OK | OK (table provides horizontal scrollbar — Qt-native works) | identical |
| 04_chip_strip | G1 overlap | OK at 4 chips (512 px clear) | **C** (chips physically stack, close × of chip 1 hidden) | **regression** |
| 04_chip_strip | L4 overflow | OK | **C** (no scroll, no shrink, no overflow button — chips just collide) | **regression** |
| 03_viewer toolbar | G3 hidden | OK (all 16 buttons visible) | M (`eye`/`graduate`/`MPR`/`cloud` need horizontal scroll) | **regression** |
| 03_viewer toolbar | G5 scrollbars | OK | OK (QScrollArea works — buttons reachable) | identical |
| 05_settings_server | G1 overlap | OK | OK (two columns still fit) | identical |
| 05_settings_server | G2 clipping | OK | M (Folder path truncated `C:/Users/vahid/Dropbo...`) | **regression** |
| 05_settings_server | G5 scrollbars | OK | OK (vertical scroll works) | identical |
| 06–09 other settings | most KPIs | OK | OK / m (tighter spacing, no breakage) | minor |
| 13_settings_echomind | all | OK | OK (single-column adapts cleanly) | **identical — proof the pattern works** |

---

## 2. Issues unique to Monitor B (regressions caused by smaller pixel budget)

| # | Severity | Location | Symptom | Root cause | Qt-native fix |
|---|---|---|---|---|---|
| **1** | **C** | Patient chip strip in title bar (`patient_tab_widget.py:113-115`) | Chips overlap each other; close × of chip 1 hidden | `setSizePolicy(Fixed, Fixed) + setFixedWidth(252)` with no `QScrollArea` wrapper | Wrap the chip container in a horizontal `QScrollArea(horizontalScrollBarPolicy=ScrollBarAsNeeded)`. ~5 lines added in the parent. |
| **2** | **C** | Centre toolbar above patient table (`Patient Studies` header bar) | `Patient Studies` label, `16 studies found` badge, `Offline Sync` button text all clipped | Containers pinned with `setFixedWidth/Height`, no shrink negotiation | Replace `setFixed*` with `setMinimum*` + `QSizePolicy.Preferred`. Allow labels to elide naturally via Qt's `QLabel.setTextFormat` + `setWordWrap`. |
| **3** | **C** | Patient table column visibility (home page) | 6 of 12 columns hidden by default (Date, Modality among them) | Left panel default width (~280 px) + right rail (216 px) + sidebar nav (~62 px) = 558 px taken before the centre table gets any pixels | Convert the left/centre/right tri-pane into a `QSplitter(Qt.Horizontal)`. User can drag the splitter to give the centre more room, and the saved state persists. Qt-native, ~10 lines. |
| **4** | **C** | Settings → Light Viewer (`lightviewer_settings.py`) — `Browse...` and `Clear Path` buttons | The two buttons physically overlap each other on the right of the path field | Same `setFixed*` pattern as the chip strip — buttons pinned with absolute size, parent layout cannot redistribute when the field grows | Either (a) replace `setFixed*` on both buttons with `setMinimum*` + `QSizePolicy.Preferred`, or (b) move both buttons into a `QVBoxLayout` (stacked vertically) inside a fixed-width column container so they never compete horizontally. |
| **5** | M | Viewer toolbar | 4 buttons (`eye`, `graduate`, `MPR`, `cloud`) hidden behind horizontal scroll | Already has `QScrollArea` (which is why the user CAN reach them by scrolling) but the toolbar's natural width exceeds the window | Two options: a) keep the scroll (acceptable degradation), b) introduce a "More" overflow popover for the rightmost icons (`QToolButton` with `setPopupMode(InstantPopup)`). Both are Qt-native. |
| **6** | M | Left side-panel default width | Server Selection + Patient Search panel takes ~280 px / 1280 = 22 % of width; combined with right rail this leaves only ~780 px for the centre table | `default_panel_width = 260` in `patient_widget_core/widget.py:293` and similar in the home page | Convert the home tri-pane to `QSplitter` (same fix as #3). |
| **7** | M | Folder path truncation in `Offline Cloud Server` table on Server Settings | `C:/Users/vahid/Dropbo...` | Table column has fixed width that can't grow | Set `QHeaderView::Stretch` mode on the `Folder` column, or use `QHeaderView::ResizeToContents` and provide a horizontal scrollbar. Both Qt-native. |
| **8** | M | Patient name truncation in chip + table | `ABDOLHOSEIN^MOHAM...` clipped in chip header AND in `Patient Name` table cell | Chip text label has fixed width; table cell auto-elides which is acceptable, but chip uses a fixed `QLabel` | Use `QFontMetrics.elidedText()` in the chip's name label so the elision is explicit (with an ellipsis), or use `QToolTip` to show the full name on hover. |
| **9** | M | Settings → Viewer Configuration — multi-line description blocks (`Local Storage & Database Cleanup` description; `GPU Boost` block; `Backend analysis` block) | Text clipped mid-word at the right edge of the container | `QLabel` does not have `setWordWrap(True)` enabled, or has a fixed `setMaximumWidth` that's too small for the running text | `description_label.setWordWrap(True)` and ensure the container's size policy is `Preferred` not `Fixed`. Standard Qt idiom — works without any other changes. |
| **10** | M | Settings → Viewer Configuration — Modality Grid `Layout` column QComboBoxes | Some combos display `1 × 2`, others render empty | Combo width set with `setFixedWidth` smaller than the contained text + dropdown indicator, so when the row reflows tightly, the visible text is clipped to nothing | `setMinimumWidth(70)` + `setSizePolicy(Preferred, Fixed)` + `setSizeAdjustPolicy(QComboBox.AdjustToContents)`. |
| **11** | M | Settings → Viewer Configuration — `Name` field at bottom of Modality Grid Layout | Field collapses to ~0 px wide, invisible | The `QLineEdit` has `QSizePolicy.Preferred` but the parent `QHBoxLayout` has a stretch factor of 0 on it and runs out of horizontal budget — Qt shrinks it to 0 rather than the label | Set `stretch=1` on the `addWidget(name_edit)` call so the field claims the remaining horizontal space; or `setMinimumWidth(120)` on the field itself. |
| **12** | m–M | Print module series-card text | `MR · 52 ir`, `MR · 30 ir`, `t2_trufi_CC`, `t2_trufi_tra` all clipped on the right | Series card has fixed width and the text labels inside it have `setFixedWidth` that doesn't accommodate longer strings | `QFontMetrics.elidedText()` for explicit ellipsis, or `setMinimumWidth` on the card and let the text grow. |
| **13** | M | Print module — centre preview pane | ~700 × 800 px empty space; left and right panels cramped while centre is unused | Centre `QWidget` has `QSizePolicy.Expanding` (correct!) but is empty in this state; the left/right panels could use that real estate when no preview is loaded | Acceptable design choice — but consider hiding the centre pane via `setVisible(False)` when empty, or letting the left/right panels expand into it via `QSplitter`. |

---

## 3. Issues common to both monitors

None of severity C or M.

Minor wording bug shared: the "Maximum Patient Tabs Reached" dialog says "3" when the actual cap is 4 (off-by-one in message string).

---

## 4. What Qt is already doing right (lessons to replicate)

Both monitors show these working correctly — these are the patterns the project should extend, not fight:

- **`QTableView` provides native horizontal & vertical scrollbars** automatically when content exceeds the viewport (patient table).
- **`QScrollArea` wrapping** the Server Settings sub-panel, the Viewer Configuration right pane, and the viewer toolbar makes content reachable on both monitors.
- **Single-column vertical stacks** (EchoMind Settings) adapt cleanly to any width. The `QVBoxLayout` reflows naturally.
- **Tab strip with all 7 tabs** fits at both widths because the `QTabBar` calculates its own size budget — no `setFixedWidth` interferes.

---

## 5. Implementation backlog — prioritized for Track 1 (Qt-native layout hardening)

### Phase 1 — Critical (target: stop overlap, restore workflow)

1. **Wrap patient chip strip in horizontal `QScrollArea`** (fixes Issue #1 — the chip overlap).
   - File: parent container of `patient_tab_widget.py` chips (probably in `AIPacs_ui.py` or `mainwindow_ui.py`).
   - Effort: ~15 min.
   - Risk: zero — chips keep their `Fixed/Fixed` policy and 252 × 70 dimensions; the strip just gains horizontal scroll under pressure.

2. **Convert centre `Patient Studies` toolbar to size-policy-aware** (fixes Issue #2 — header / badge / button clipping).
   - File: `PacsClient/pacs/workstation_ui/home_ui/*` (centre toolbar above patient table).
   - Effort: ~30 min.
   - Replace `setFixedWidth/Height` on the toolbar container with `setMinimum*` + `QSizePolicy.Preferred`. Set labels to `setWordWrap(False)` and use `QFontMetrics.elidedText()` if needed.

3. **Convert home tri-pane to `QSplitter(Qt.Horizontal)`** (fixes Issue #3 — patient table column visibility and Issue #6 — left panel hog).
   - File: home page main layout.
   - Effort: ~45 min.
   - Replace the current fixed-width left + fixed-width right + centre layout with a `QSplitter`. Save/restore splitter sizes via `QSettings` so the user's drag persists across sessions.

4. **Fix Light Viewer `Browse... / Clear Path` button overlap** (fixes Issue #4).
   - File: `PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py`.
   - Effort: ~10 min.
   - Either replace `setFixed*` on both buttons with `setMinimum*` + `QSizePolicy.Preferred`, or stack them vertically in a `QVBoxLayout`. The second option is more compact and is the pattern Qt's File-open dialog uses.

**Total Phase 1 effort: ~100 minutes for the 4 Critical fixes.**

### Phase 2 — Major (target: reduce truncation, improve density on small monitors)

5. **Add `setWordWrap(True)` to multi-line description QLabels** in Viewer Configuration (Issue #9 — Local Storage / GPU Boost / Backend analysis blocks).
   - File: `viewerconfigsetting.py` and/or `storage_cleanup_panel.py`.
   - Effort: ~10 min.
   - Trivial Qt-native fix — one method call per affected label.

6. **Fix Modality Grid `Layout` comboboxes** (Issue #10).
   - Replace `setFixedWidth` with `setMinimumWidth(70) + setSizeAdjustPolicy(QComboBox.AdjustToContents) + setSizePolicy(Preferred, Fixed)`.
   - Effort: ~15 min.

7. **Fix `Name` field collapse in Modality Grid Layout** (Issue #11).
   - Add `stretch=1` argument to the `addWidget(name_edit)` call, or set `setMinimumWidth(120)` on the QLineEdit.
   - Effort: ~5 min.

8. **Add "More" overflow popover to viewer toolbar** OR accept the existing horizontal scroll (Issue #5).

9. **Set `QHeaderView::Stretch` mode on `Folder` column** of Offline Cloud Server table (Issue #7).

10. **Use `QFontMetrics.elidedText()` for patient chip name label** with `QToolTip` for full name (Issue #8).

11. **Print module series-card text elision** (Issue #12).
    - Apply `QFontMetrics.elidedText()` to the modality/image-count label and the description label inside each series card.
    - Effort: ~10 min.

### Phase 3 — Polish

7. Off-by-one wording bug in "Maximum Patient Tabs Reached" dialog ("3" → "4").
8. Audit remaining `setFixed*` calls (~172 across PacsClient/) and replace with `setMinimum*` + size-policies as touched.

### What NOT to do

- Do **not** start with the `sf()` scale-factor rollout (the original `RESPONSIVE_UI_SCALING_PLAN.md`). It would scale the pinned values but they would still be pinned — chip overlap would persist. The plan stays useful as Track 2 (user-preference layer) but only after the layout primitives are fixed.
- Do **not** touch any viewer hot-path code (`vtk_widget.py`, `lightweight_2d_pipeline.py`) per the project's regression-guard rules.
- Do **not** add custom paint or absolute positioning. The defects come from Qt's layout being defeated; the fix is to let Qt do its job.

---

## 6. Verification protocol after each Phase 1 fix

For each of the 3 Critical fixes:

1. Build the source via VS Code Play button (per `CLAUDE.md`).
2. Run on Monitor B (1280 × 1024).
3. Re-perform the specific screen tour for that fix:
   - Fix 1: open 4 patient tabs → verify chip strip scrolls horizontally instead of overlapping; verify chip 1's close × is reachable.
   - Fix 2: open home page → verify `Patient Studies` header reads in full; `Offline Sync` button shows full label.
   - Fix 3: open home page → verify centre table column count; drag splitter → verify state persists.
4. Re-perform the same screens on Monitor A → verify no regression (KPIs that were OK stay OK).
5. Capture before/after screenshots into `responsive_ui_baselines/phase1_fixN/`.

---

## 7. Final answer to the project owner's original question

**Q:** "Why isn't UI scaling working correctly?"

**A:** Because the code defeats Qt's built-in layout engine in ~30 files by calling `setFixedSize/Width/Height` instead of `setMinimum*` + `setSizePolicy`, and because most overflow-prone panels (chip strip, centre toolbar) are not wrapped in `QScrollArea`. Qt itself handles DPI scaling, multi-monitor moves, font reflow, and content overflow correctly — but only when widgets are given size policies that let the layout negotiate. The current code says "this widget is exactly 252 pixels wide, period," and Qt has no choice but to let it overflow when 4 of them don't fit.

**The fix is Qt-native and small.** Three changes (≈ 90 minutes) eliminate the 3 Critical issues observed on Monitor B without any custom scale-factor code, without touching the viewer hot paths, and without altering the visual design at the default widths used on Monitor A. The `sf()` user-preference helper remains useful for the separate "make everything 25 % bigger because I prefer it" knob, but it is not the right tool for the overlap problem and should be Track 2, not Track 1.
