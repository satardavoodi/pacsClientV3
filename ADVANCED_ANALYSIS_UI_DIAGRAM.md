# Advanced Analysis Panel – UI Layout Diagram

## New Structure (After Refactor)

```
┌─────────────────────────────────────────────────┐
│  Patient Tab – Advanced Analysis Section        │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │ [Thumbnails] ← Title                      │  │
│  ├───────────────────────────────────────────┤  │
│  │                                           │  │
│  │  ┌──────────────┐  ┌──────────────┐     │  │ TOP 50%
│  │  │ Series 1     │  │ Series 3     │     │  │ (Scrollable)
│  │  │ CT Chest     │  │ CT Abdomen   │     │  │
│  │  └──────────────┘  └──────────────┘     │  │
│  │  ┌──────────────┐  ┌──────────────┐     │  │
│  │  │ Series 2     │  │ Series 4     │     │  │
│  │  │ CT Head      │  │ MR Brain     │     │  │
│  │  └──────────────┘  └──────────────┘     │  │
│  │                                         ⬇ │  Scrollbar if needed
│  │  (more series if available...)         │  │
│  │                                           │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │ [Advanced Models] ← Title                 │  │
│  ├───────────────────────────────────────────┤  │
│  │                                           │  │
│  │  ┌─────────────────────────────────────┐  │  │ BOTTOM 50%
│  │  │ Advanced MPR and AI segmentation    │  │  │
│  │  │         [Blue Button]               │  │  │
│  │  └─────────────────────────────────────┘  │  │
│  │                                           │  │
│  │  (future buttons can be added here)      │  │
│  │                                           │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## User Interaction Flow

```
User clicks "Advanced Analysis" tab
          ↓
┌─────────────────────────────────┐
│ PatientWidget showing:           │
│ - Thumbnails (series cards)      │
│ - Advanced Models section        │
└─────────────────────────────────┘
          ↓
User clicks on Series Thumbnail
          ↓
┌─────────────────────────────────┐
│ Series card highlights:          │
│ - Blue border                    │
│ - Blue background                │
│ - Stored in _selected_series     │
└─────────────────────────────────┘
          ↓
User clicks "Advanced MPR and AI segmentation" button
          ↓
┌─────────────────────────────────┐
│ Loading UI replaces thumbnails:  │
│ - "Advanced MPR" title (blue)    │
│ - Rotating spinner animation     │
│ - "Launching..." text            │
│ - Center-aligned                 │
└─────────────────────────────────┘
          ↓
3D Slicer starts (background process)
          ↓
3D Slicer window opens
          ↓
User works in Slicer, then closes it
          ↓
┌─────────────────────────────────┐
│ Thumbnails restored:             │
│ - Back to series cards           │
│ - Ready for next selection       │
└─────────────────────────────────┘
```

---

## Thumbnail Card Design (New)

```
┌──────────────────┐
│ Series 1         │  ← Series number (bold, #cbd5e1)
│ CT Chest         │  ← Series description (subtitle, #94a3b8, light bg)
│                  │
│ Background: #1a202c (dark gray)
│ Border: 1px solid #2d3748
│ On hover: #252d39, border #4b5563
│ When selected: blue bg, blue border
└──────────────────┘
```

---

## Loading UI (New)

```
┌─────────────────────────────────────┐
│                                     │
│   Advanced MPR                      │ ← Blue title, 18px
│                                     │
│        ╱╲                           │
│       ╱  ╲                          │ ← Rotating spinner
│      ╱    ╲     (Blue arc #2563eb)  │
│     ╱      ╲                        │
│                                     │
│  Launching Advanced MPR and         │
│  AI segmentation...                 │ ← Status text
│                                     │
│  Please wait while the              │
│  application initializes.           │
│                                     │
└─────────────────────────────────────┘
```

---

## Color Scheme

| Element | Color | Usage |
|---------|-------|-------|
| Header Title (Thumbnails) | `#7c3aed` to `#5b21b6` | Gradient purple |
| Header Title (Models) | `#7c3aed` to `#5b21b6` | Gradient purple |
| Card Background | `#1a202c` | Dark gray |
| Card Border | `#2d3748` | Medium gray |
| Card Hover Border | `#4b5563` | Light gray |
| Selected Card BG | `#1e3a8a` | Dark blue |
| Selected Card Border | `#2563eb` | Bright blue |
| Button (Normal) | `#2563eb` to `#1e40af` | Blue gradient |
| Button (Hover) | `#1d4ed8` to `#1e3a8a` | Darker blue |
| Spinner | `#2563eb` | Bright blue |
| Loading Title | `#2563eb` | Bright blue |
| Loading Text | `#cbd5e1` | Light text |

---

## Component Hierarchy

```
PatientWidget
├── advanced_tools_panel (QWidget)
│   └── layout (QVBoxLayout)
│       └── splitter (QSplitter, Vertical)
│           │
│           ├── top_widget (QWidget) - 50% height
│           │   └── top_layout (QVBoxLayout)
│           │       ├── thumb_title_label (QLabel) "Thumbnails"
│           │       └── thumb_scroll (QScrollArea)
│           │           └── thumb_container (QWidget)
│           │               └── advanced_analysis_thumb_grid (QGridLayout)
│           │                   ├── Card 1 (QWidget + QVBoxLayout)
│           │                   ├── Card 2 (QWidget + QVBoxLayout)
│           │                   └── ... (2 columns)
│           │
│           └── bottom_widget (QWidget) - 50% height
│               └── bottom_layout (QVBoxLayout)
│                   ├── models_title_label (QLabel) "Advanced Models"
│                   └── models_scroll (QScrollArea)
│                       └── models_container (QWidget)
│                           └── models_container_layout (QVBoxLayout)
│                               ├── btn_advanced_mpr (QPushButton)
│                               └── stretch()
```

---

## Old vs New Comparison

### OLD Structure (Before)
```
┌─────────────────────────────────────┐
│ Advanced Analysis - Series          │
├─────────────────────────────────────┤
│ [Series 1 - CT Chest]               │
│ [Series 2 - CT Head]                │ Full list
│ [Series 3 - CT Abdomen]             │ (click = launch)
│ [Series 4 - MR Brain]               │
└─────────────────────────────────────┘
┌─────────────────────────────────────┐
│ [Empty dashed box]                  │ ← Placeholder
│ (was reserved for future features)  │
└─────────────────────────────────────┘

→ Clicking "Advanced Analysis" → Auto-launches Slicer
→ Terminal-like waiting page shown
```

### NEW Structure (After)
```
┌─────────────────────────────────────┐
│ Thumbnails                          │
├─────────────────────────────────────┤
│ ┌──────────┐ ┌──────────┐           │
│ │Series 1  │ │Series 2  │           │ Cards displayed
│ │CT Chest  │ │CT Head   │           │ (click = select)
│ └──────────┘ └──────────┘           │
│ ┌──────────┐ ┌──────────┐           │
│ │Series 3  │ │Series 4  │           │
│ │CT Abd    │ │MR Brain  │           │
│ └──────────┘ └──────────┘           │
│ (Scrollable, 2-column layout)       │
└─────────────────────────────────────┘
┌─────────────────────────────────────┐
│ Advanced Models                     │
├─────────────────────────────────────┤
│ [Advanced MPR and AI segmentation]  │ ← Click to launch
│                                     │
│ (Ready for future buttons)          │
└─────────────────────────────────────┘

→ Clicking "Advanced Analysis" → Shows thumbnails only
→ Select series → Click button → Loading UI
→ Professional loading screen shown
```

---

## Timeline of Changes

| Step | Before | After | Time |
|------|--------|-------|------|
| 1. Click Advanced Analysis | Auto-launches Slicer | Shows thumbnails | Immediate |
| 2. (N/A) | Terminal page appears | - | - |
| 3. Select Series | (Auto-selected) | Click card to select | User controlled |
| 4. Launch MPR | (Automatic) | Click button | User triggered |
| 5. Loading Indicator | Terminal-like | Professional UI | Immediate |
| 6. App Window | Slicer opens | Same behavior | ~2-5 seconds |

---

## API/Method References

### Public Methods Called from UI
- `_on_advanced_mpr_clicked()` – Button click handler
- `_refresh_advanced_analysis_series_list()` – Populate thumbnails
- `_on_option_sidebar_clicked('advanced_tools')` – Tab selection

### Internal Methods
- `_show_advanced_mpr_loading_ui()` – Replace view with loading
- `_create_spinner_widget()` – Create animation
- `_launch_advanced_mpr_async()` – Launch Slicer
- `_restore_thumbnails_view()` – Restore view on completion
- `_update_advanced_series_selection()` – Highlight selected card

### Signal Handlers
- `_on_advanced_mpr_finished(exit_code)` – Slicer closed
- `_on_advanced_mpr_error(error_msg)` – Launch failed

---

Created: 2026-02-19 (v2.2.2)
