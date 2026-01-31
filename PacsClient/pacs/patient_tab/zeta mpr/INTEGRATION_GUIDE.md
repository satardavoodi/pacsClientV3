# Quick Integration Guide for NEW MPR ZETA

## ✅ Files Successfully Copied

All necessary files have been copied to:
```
C:\AI-Pacs codes\PacsClientV2\PacsClient\pacs\patient_tab\zeta mpr\
```

### File List:
1. ✅ `standard_mpr_viewer.py` - Main viewer (2,800+ lines)
2. ✅ `preset_manager.py` - Window/Level presets
3. ✅ `advanced_rendering.py` - Volume rendering
4. ✅ `segmentation_tools.py` - Segmentation algorithms
5. ✅ `surface_reconstruction.py` - 3D surface extraction
6. ✅ `curved_mpr.py` - Curved MPR
7. ✅ `mpr_measurement_tools.py` - Measurements
8. ✅ `toolbar_integration.py` - **NEW** - Toolbar button code
9. ✅ `__init__.py` - Module initialization
10. ✅ `README.md` - Full documentation
11. ✅ `INTEGRATION_GUIDE.md` - This file

---

## 🚀 3-Step Integration

### Step 1: Open toolbar_manager.py

File location:
```
C:\AI-Pacs codes\PacsClientV2\PacsClient\pacs\patient_tab\ui\patient_ui\patient_toolbar\toolbar_manager.py
```

### Step 2: Add Import at Top of File

Find the imports section (usually near line 1-50) and add:

```python
# NEW MPR ZETA Integration
from PacsClient.pacs.patient_tab.zeta_mpr.toolbar_integration import (
    toggle_new_mpr_zeta,
    replace_selected_viewport_with_new_mpr_zeta
)
```

### Step 3A: Add Instance Variable

Find the `__init__` method of `ToolbarManager` class and add:

```python
# NEW MPR ZETA state tracker
self._new_mpr_zeta_active = False
```

### Step 3B: Add Button to Menu

Find where the MPR dropdown menu is created. Look for code like:
```python
mpr_dropdown_menu = QMenu()
# or
mpr_menu = QMenu("MPR")
```

After other MPR menu items, add:

```python
# MPR ζ (Zeta) - Old Standard MPR viewer for comparison
mpr_zeta_action = mpr_dropdown_menu.addAction("MPR ζ (Zeta)")
mpr_zeta_action.setToolTip("Standard MPR viewer - original implementation")
mpr_zeta_action.triggered.connect(
    lambda: toggle_new_mpr_zeta(self, self.patient_widget.selected_widget)
)
```

**Note:** Replace `mpr_dropdown_menu` with whatever variable name is used in your code.

---

## 🎯 That's It!

The integration is complete. Now when you run the application:

1. Load a DICOM series
2. Click on the MPR dropdown menu
3. You'll see "MPR ζ (Zeta)" option
4. Click it to activate the MPR Zeta viewer
5. Click again to toggle back to original viewer

---

## 📍 Where to Add Code (Visual Guide)

```python
# ========================================
# SECTION 1: IMPORTS (Top of file)
# ========================================
from PySide6.QtWidgets import QPushButton, QMenu, ...
from PacsClient.pacs.patient_tab.interactor_styles import ...

# 👇 ADD HERE 👇
from PacsClient.pacs.patient_tab.zeta_mpr.toolbar_integration import (
    toggle_new_mpr_zeta,
    replace_selected_viewport_with_new_mpr_zeta
)
# 👆 ADD HERE 👆


class ToolbarManager:
    def __init__(self, ...):
        # ========================================
        # SECTION 2: INSTANCE VARIABLES
        # ========================================
        self.patient_widget = patient_widget
        self.tool_selected = None
        
        # 👇 ADD HERE 👇
        self._new_mpr_zeta_active = False
        # 👆 ADD HERE 👆
        
        # ... rest of __init__ ...
    
    def _create_mpr_menu(self):  # or wherever MPR menu is created
        # ========================================
        # SECTION 3: MENU BUTTON
        # ========================================
        mpr_menu = QMenu("MPR")
        
        # Existing menu items
        mpr_action1 = mpr_menu.addAction("MPR Alpha")
        mpr_action2 = mpr_menu.addAction("MPR Beta")
        
        # 👇 ADD HERE 👇
        mpr_zeta_action = mpr_menu.addAction("MPR ζ (Zeta)")
        mpr_zeta_action.setToolTip("Standard MPR viewer - original implementation")
        mpr_zeta_action.triggered.connect(
            lambda: toggle_new_mpr_zeta(self, self.patient_widget.selected_widget)
        )
        # 👆 ADD HERE 👆
        
        return mpr_menu
```

---

## 🔍 Finding the Right Location

### To Find the MPR Menu Creation:

1. Open `toolbar_manager.py`
2. Search for: `"MPR"` or `"mpr"` or `"Multi-Planar"`
3. Look for `QMenu` or `addAction` calls
4. Find where other MPR options are added
5. Add the Zeta button in the same place

### Common Patterns:

**Pattern 1: Direct Menu**
```python
mpr_menu = QMenu("MPR")
mpr_action = mpr_menu.addAction("MPR Option")
# Add Zeta here
```

**Pattern 2: Dropdown Menu**
```python
mpr_dropdown = QPushButton("MPR ▼")
mpr_dropdown_menu = QMenu()
# Add Zeta here
mpr_dropdown.setMenu(mpr_dropdown_menu)
```

**Pattern 3: Toolbar with Menu**
```python
mpr_button = self.addAction("MPR")
mpr_submenu = QMenu()
# Add Zeta here
mpr_button.setMenu(mpr_submenu)
```

---

## ⚠️ Important Notes

1. **Module Name:** Use `zeta_mpr` (underscore) in imports, not "zeta mpr" (space)
   
2. **Function Signature:** Note that `toggle_new_mpr_zeta` takes `self` as first parameter:
   ```python
   toggle_new_mpr_zeta(self, selected_widget)
   ```

3. **Lambda Function:** Use lambda to pass the toolbar manager instance:
   ```python
   lambda: toggle_new_mpr_zeta(self, self.patient_widget.selected_widget)
   ```

---

## 🧪 Testing Checklist

After integration, test:

- [ ] Application starts without errors
- [ ] MPR menu shows "MPR ζ (Zeta)" option
- [ ] Clicking button loads MPR Zeta viewer
- [ ] Three views display (Axial, Sagittal, Coronal)
- [ ] Window/Level controls work
- [ ] Slice navigation works
- [ ] Clicking button again restores original viewer
- [ ] No console errors

---

## 🐛 Troubleshooting

### Error: "Cannot import toggle_new_mpr_zeta"

**Cause:** Import path is wrong

**Fix:** Ensure the import uses `zeta_mpr` (underscore):
```python
from PacsClient.pacs.patient_tab.zeta_mpr.toolbar_integration import toggle_new_mpr_zeta
```

### Error: "module 'zeta_mpr' has no attribute 'toggle_new_mpr_zeta'"

**Cause:** Importing from wrong module

**Fix:** Import from `toolbar_integration`, not from `__init__`:
```python
from PacsClient.pacs.patient_tab.zeta_mpr.toolbar_integration import ...
```

### Error: Button doesn't appear

**Cause:** Code added in wrong location

**Fix:** Find where other MPR buttons are created and add Zeta button there

### Error: Viewer doesn't display

**Cause:** Check console output for detailed error

**Fix:** The code has extensive debug logging. Check stderr/console for messages like:
```
[NEW MPR ZETA] Creating StandardMPRViewer...
ERROR importing StandardMPRViewer: ...
```

---

## 📞 Support

If you encounter issues:

1. Check console output (stderr) for detailed debug messages
2. Verify all files are present in the `zeta mpr` folder
3. Ensure import paths match exactly (including underscores)
4. Check that `__init__.py` is in the `zeta mpr` folder

---

## 📊 What Was Changed

### From Source (PACS Client INO 2):
- Extracted `toolbar_manager.py` functions
- Copied `standard_mpr_viewer--.py` (renamed to `standard_mpr_viewer.py`)
- Copied all dependency files

### To Target (PacsClientV2):
- Created new `zeta mpr` folder
- Made functions standalone (removed `self` references)
- Created `toolbar_integration.py` wrapper
- Added comprehensive documentation

---

**Integration Time:** 5-10 minutes  
**Difficulty:** Easy  
**Risk:** Low (only adding new code, not modifying existing)

---

**Ready to go! 🚀**
