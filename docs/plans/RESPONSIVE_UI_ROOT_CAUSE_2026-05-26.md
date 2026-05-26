# Why UI Scaling Is Not Working — Root Cause Analysis
**Created:** 2026-05-26
**Scope:** Settings menus, viewer toolbars, patient tabs, main window — the areas the user reports as overlapping on small monitors and shrunken on large ones.
**Conclusion:** The previous plan (`RESPONSIVE_UI_SCALING_PLAN.md`, custom `sf()` helper) addresses the wrong layer. **The primary defect is misuse of Qt's layout primitives**, not lack of a scale-factor multiplier. Applying `sf()` over the current code only multiplies fixed sizes — it does not make them flexible. The overlap continues, just at a different scale.

---

## 1. The user's actual complaints — restated

- Small monitors → buttons / text / UI elements overlap.
- Large monitors → elements become too small.
- Different Windows scaling % → layout breaks.

These are **all symptoms of the same root cause**: the codebase is using `setFixedSize` / `setFixedWidth` / `setFixedHeight` instead of Qt's flexible layout primitives, and it's not wrapping overflowing content in `QScrollArea`. The Qt layout engine cannot reflow what is hard-pinned.

---

## 2. What Qt 6 / PySide6 already provides for free

These are the standard mechanisms the codebase **should** use. None of them require custom code.

| Qt primitive | What it does | When you should use it |
|---|---|---|
| `setMinimumWidth/Height/Size` | Floor only — widget can grow above this | A button that should stay readable but can expand |
| `setMaximumWidth/Height/Size` | Ceiling only — widget can shrink below this | A label that shouldn't dominate when there's space |
| `setSizePolicy(Expanding, Fixed)` etc. | Tells the layout how to distribute space | Buttons in a row that should share width but stay short |
| `QHBoxLayout` / `QVBoxLayout` / `QGridLayout` | Reflows children when parent resizes | Any panel of widgets |
| `QFormLayout` | Two-column label+field grid that auto-wraps on narrow screens | Settings forms |
| `QGridLayout.setColumnStretch(col, n)` | Distribute extra horizontal space across columns | Tables of fields |
| `QScrollArea(widgetResizable=True)` | Auto-adds scrollbars when content > viewport | Any panel that could overflow |
| `QSplitter(Qt.Horizontal)` | User-resizable panel boundaries | Sidebar + main area, viewer + thumbnail panel |
| `QStackedWidget` | Swap whole sub-pages | Reception mode vs default mode |
| `QTabBar.setUsesScrollButtons(True)` | Tab strip scrolls when tabs overflow | Patient tab chip strip |
| Qt 6 native HiDPI auto-scaling | Geometry and fonts auto-scale by Windows DPI | Everything, automatically |
| Qt CSS `font-size: 10pt` | Qt scales `pt` by logical DPI automatically | Font sizes that should respect Windows scaling |

These cover ~90% of what the user is asking for. None of them are in the locked `sf()` plan.

---

## 3. What Qt does NOT provide — narrow set, custom code justified

| Need | Why Qt doesn't cover it | Custom code that fits |
|---|---|---|
| User-controllable in-app scale slider on top of Qt's DPI auto-scaling | Per Qt 6.11 docs: *"Qt does not provide end-user facilities to configure the behavior of Qt's high-DPI support."* | `sf()` helper, scoped to user preference only |
| Selective scaling that excludes the VTK viewport | Qt would scale everything globally if you used `QT_SCALE_FACTOR` | `sf()` helper applied per-widget, never to the viewer hot paths |
| Saved per-user clinical ergonomic preference | Qt has no concept of "save my preferred UI size" | `ui_settings.json` + restart prompt |

This is a much smaller surface than the original plan implied.

---

## 4. Evidence — what the codebase actually does

### 4.1 The main window — zero size policies

```
PacsClient/pacs/workstation_ui/mainwindow_ui.py
  setFixedSize / setFixedWidth / setFixedHeight calls : 5
  setSizePolicy / QSizePolicy calls                   : 0   ← root cause
  QScrollArea uses                                    : 0
```

Title bar pinned at `setFixedHeight(84)`, user info container at `setFixedHeight(70)`, window buttons at `setFixedSize(46, 32)`. No size policies anywhere. Qt's layout engine has nothing to negotiate.

### 4.2 The settings dialog — no scrolling, no policies

```
PacsClient/pacs/workstation_ui/settings_ui/settings_ui.py
  QScrollArea uses     : 0    ← causes "overlap on small monitors"
  setSizePolicy uses   : 0
  setMinimumSize uses  : 0
  setMaximumSize uses  : 0
```

The main `SettingsTabWidget` is a bare `QTabWidget` with `QWidget` containers and `QVBoxLayout(margins=0)`. When a settings page is taller than the available window, **content is clipped or overlaps** because nothing wraps it in a scrollable viewport.

Sub-panel `server_settings.py` does use `QScrollArea` and `setSizePolicy` (good!), but most others don't. The behaviour is therefore inconsistent across tabs.

### 4.3 The form fields — everything pinned

```
PacsClient/pacs/workstation_ui/settings_ui/server_settings.py
  setFixedHeight(28) / setFixedHeight(30) : 13 fields
  setFixedWidth(55) / (95) / (120)        : 7 fields
  setSizePolicy uses                      : 6
```

`QLineEdit.setFixedHeight(28)` means the field can never grow with the font. On a high-DPI monitor where the user has increased Windows text size, the field still renders at 28 px and clips the text. The Qt-native fix is `setMinimumHeight(28)` with default vertical size policy — the field grows when needed.

Same pattern across all form fields. Same pattern across all settings sub-panels.

### 4.4 The patient tab chips — Fixed policy by design

```
PacsClient/pacs/patient_tab/ui/patient_ui/patient_tab_widget.py:113-115
  self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
  self.setFixedWidth(252)
  self.setFixedHeight(70)
```

Each tab chip explicitly opts out of flexibility. When the title bar is too narrow to hold all chips, **they overlap** because the layout cannot ask any chip to shrink. The Qt-native fix is either:

1. Wrap the chip strip in a horizontal `QScrollArea` so it scrolls horizontally when overflow occurs, **or**
2. Replace the custom chip widgets with `QTabBar` items (Qt's tab bar already supports overflow scrolling via `setUsesScrollButtons(True)`).

### 4.5 The viewer toolbar — same disease

```
PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py
  setFixedSize / setFixedWidth / setFixedHeight : 20
  setSizePolicy / QSizePolicy                   :  6
```

A 6900-line toolbar with 20 pinned dimensions and only 6 size policies. When the viewer window is narrow, the toolbar cannot shrink — it pushes content off-screen instead.

### 4.6 The numbers, project-wide

```
PacsClient/  setFixedSize/Width/Height occurrences : 172 across 30 files
PacsClient/  QScrollArea usage                     : 15 files (mostly the home panel; not Settings core)
```

172 fixed-size pins is the textbook signature of a Qt UI that *cannot* be responsive, no matter how clever the wrapping helper.

---

## 5. The correct fix — two tracks

### Track 1 (PRIMARY — Qt-native layout repair)

**This fixes the user's actual complaint** with zero custom scaling code.

| Issue | Qt-native fix | Effort |
|---|---|---|
| Settings overlap on small monitors | Wrap each settings sub-page in `QScrollArea(widgetResizable=True)`. Add it to `SettingsTabWidget._add_lazy_tab()` so every tab gets one automatically. | 1 file, ~15 lines |
| Form fields don't grow with font/DPI | Replace `setFixedHeight(28)` → `setMinimumHeight(28)` across `server_settings.py` and other settings sub-panels | grep + sed; ~30 min |
| Patient tab chips overlap when narrow | Wrap the chip strip in a horizontal `QScrollArea` (already a common Qt pattern). The chips themselves can keep `Fixed/Fixed` policy. | 1 file, ~10 lines |
| Toolbar can't shrink on narrow viewer | Add `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)` to the toolbar's outer container. Where buttons cluster into groups, use `QHBoxLayout.addStretch()` between groups instead of fixed widths. | toolbar_manager.py, ~20 lines (NOT a rewrite) |
| Title bar can't grow with font | Replace `setFixedHeight(84)` → `setMinimumHeight(84)` on the title-bar frame. | 1 line |
| User info container won't expand | Same: `setFixedHeight(70)` → `setMinimumHeight(70)`. | 1 line |

**Estimated effort:** ~4–6 hours total. **Estimated impact:** resolves the overlap complaint on small monitors and the shrinkage complaint on large monitors **directly**, because Qt's layout engine takes over.

### Track 2 (POLISH — user preference, smaller scope)

The previously-locked `RESPONSIVE_UI_SCALING_PLAN.md` `sf()` helper. Now its purpose is clearer:

- **Not** the fix for overlap (Track 1 fixes that).
- It is purely a user-controllable additional zoom on top of Track 1's responsive base.
- Only widgets where the user genuinely wants a "make everything 25% bigger" knob need to go through `sf()`. That is a much smaller subset than the 20 files originally enumerated.

Recommended scope reduction for Track 2 after Track 1 lands:

- **Keep:** main shell constants in `AIPacs_ui.py` (`_menu_button_size`, `_menu_expanded_width`, etc.), toolbar icon sizes, font sizes (CSS `font-size`).
- **Drop:** any `setFixedHeight`/`setFixedWidth` that Track 1 has converted to `setMinimum*` — Qt now handles those.
- **Result:** Phase 0 + 2 + 5 (icon and font tiers) + 10 (settings hook) are still useful. Phases 1, 3, 4, 6, 7, 8, 9 reduce to "scale only the remaining icon/font values, not geometry."

---

## 6. Which problems can be solved by Qt alone

| User complaint | Qt-native solution alone? | Custom code needed? |
|---|---|---|
| Buttons overlap on small monitors | **Yes** — replace setFixedX with setMinimumX + size policies; wrap overflowing panels in QScrollArea | None |
| Text overlaps | **Yes** — same fix; text grows the widget when min-height isn't fixed | None |
| UI elements collide | **Yes** — layout reflow + QScrollArea | None |
| Elements too small on large monitors | **Partial** — Qt's HiDPI handles Windows scaling automatically; for further user preference, custom slider needed | Optional: `sf()` for the slider |
| Windows DPI scaling (100/125/150/175/200%) | **Yes** — Qt 6 handles automatically, no app code needed | None — already works |
| Different physical monitor sizes at same DPI | **Yes** — layout reflow handles this | None |
| User-preferred UI size independent of Windows scaling | **No** — Qt doesn't expose this | `sf()` helper, Settings slider |

So out of 7 stated user concerns, **6 are solvable with Qt-native code**. Only the 7th genuinely needs custom code.

---

## 7. Concrete next step recommendation

Stop the work on `RESPONSIVE_UI_SCALING_PLAN.md` as primary. Instead:

1. **Open a new ticket: `LAYOUT_HARDENING_PLAN.md`** — Track 1 above. This is the actual fix for overlap.
2. **Demote `RESPONSIVE_UI_SCALING_PLAN.md` to Phase 2** — it lands after layout hardening, with a reduced scope (fonts, icons, shell constants only — not every fixed pixel).

The layout-hardening work is also safer:
- It uses Qt's documented primitives — no custom code paths.
- It reduces the codebase's fixed-size footprint, which makes everything more responsive automatically (multi-monitor drag, font changes, accessibility settings, future Windows scale changes).
- It cannot regress functionality because `setMinimumHeight(28)` is strictly more permissive than `setFixedHeight(28)` — every fit that worked before still works; some that didn't fit now also work.
- It removes the need to multiply 172 pinned values by `sf()` later.

If the user prefers, the two tracks can ship in parallel — but **Track 1 should land first** because Track 2 inherits its responsiveness gains.

---

## 8. Concrete examples — before / after

### 8.1 Settings tab — wrap in QScrollArea

Before (`settings_ui.py:66-74`):

```python
def _add_lazy_tab(self, label, builder):
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    idx = self.addTab(container, label)
    self._tab_creators[idx] = builder
    self._tab_containers[idx] = container
    return idx
```

After:

```python
def _add_lazy_tab(self, label, builder):
    from PySide6.QtWidgets import QScrollArea
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)              # widget grows to viewport width
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setFrameShape(QFrame.NoFrame)         # no extra border
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    scroll.setWidget(container)
    idx = self.addTab(scroll, label)             # tab now hosts the scroll area
    self._tab_creators[idx] = builder
    self._tab_containers[idx] = container        # builders still get the inner container
    return idx
```

Five lines of additional Qt-native code. Settings panels can no longer overlap regardless of monitor size.

### 8.2 Form fields — minimum, not fixed

Before (`server_settings.py:287-288`):

```python
self.name_edit = QLineEdit()
self.name_edit.setPlaceholderText("Server Name")
self.name_edit.setFixedHeight(28)               # ← can never grow
```

After:

```python
self.name_edit = QLineEdit()
self.name_edit.setPlaceholderText("Server Name")
self.name_edit.setMinimumHeight(28)             # ← grows with font/DPI
```

Same minimum, but no upper pin. When font scales up, field grows; when font is normal, layout is unchanged.

### 8.3 Title bar — minimum, not fixed

Before (`mainwindow_ui.py:598`):

```python
self.title_bar.setFixedHeight(84)
```

After:

```python
self.title_bar.setMinimumHeight(84)
self.title_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
```

The title bar now keeps its 84-px floor but can grow if a child needs more vertical space (e.g. user info container with larger font).

### 8.4 Patient chip strip — wrap in horizontal scroll

Before: chips packed into a fixed horizontal layout; overflow → overlap.

After (in the chip container's parent layout):

```python
chip_scroll = QScrollArea()
chip_scroll.setWidgetResizable(True)
chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
chip_scroll.setFrameShape(QFrame.NoFrame)
chip_scroll.setFixedHeight(chip_container.sizeHint().height())  # height matches chips
chip_scroll.setWidget(chip_container)
title_layout.addWidget(chip_scroll, stretch=1)
```

Chips keep their `Fixed/Fixed` policy and 252×70 size; the scroll area handles overflow.

---

## 9. Bottom line

The user is right that the locked `sf()` plan does not solve the real problem. The dominant defect is **misuse of `setFixedX` and absence of `QScrollArea`**, not lack of a global scale multiplier.

Roughly **90% of the responsive-UI problem** can be solved with Qt-native primitives that already exist in PySide6, in approximately 4–6 hours of focused changes across ~6 files. The remaining 10% (per-user scale preference) is what `sf()` is for, and its scope shrinks considerably once layout hardening lands.

Recommended order of operations:

1. **Track 1 first** — `LAYOUT_HARDENING_PLAN.md` (new file to be written, scoped to the changes in §5).
2. **Track 2 second** — the existing `RESPONSIVE_UI_SCALING_PLAN.md`, reduced in scope per §5 Track 2.

This avoids the duplication-of-work concern: we use Qt where Qt is the right answer, and we use custom code only where Qt genuinely has no answer.
