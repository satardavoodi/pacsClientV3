# Button Safeguard Implementation Guide

## ملخص (Persian Summary)

**هدف**: جلوگیری از کلیک چندگانه و همزمان دکمه‌ها که می‌تواند باعث هنگ یا Not Responding شدن برنامه شود.

**نحوه کار**: هنگامی که کاربر یک دکمه را کلیک می‌کند، سیستم safeguard تمام دکمه‌های دیگر را غیرفعال می‌کند تا عملیات فعلی کامل شود (موفق یا ناموفق).

**پیاده‌سازی شده در**: 
- `PacsClient/pacs/patient_tab/utils/button_safeguard.py` - کلاس اصلی
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget.py` - استفاده در PatientWidget

---

## Overview

The Button Safeguard system prevents multiple concurrent button clicks that could cause the application to hang or become unresponsive. When a user clicks a button, all other buttons are disabled until the operation completes (success or failure).

## Features

✅ **Automatic Button Management**: Registers and manages all interactive buttons
✅ **Thread-Safe**: Handles async operations and Qt event loop safely
✅ **Clear Lifecycle**: Start operation → Do work → End operation
✅ **Error Handling**: Automatically re-enables buttons on errors
✅ **Context Manager Support**: Clean syntax for manual control
✅ **Decorator Support**: Easy protection for click handlers
✅ **Logging**: Full operation tracking for debugging

## Implementation in PatientWidget

### 1. Initialization

In `PatientWidget.__init__()`:
```python
# Button safeguard is initialized automatically
self.button_safeguard = ButtonSafeguard(self)
```

### 2. Button Registration

Buttons are automatically registered after UI initialization in `_register_buttons_with_safeguard()`:
```python
# Sidebar buttons
self.btn_series
self.btn_reception
self.btn_ai_chat
self.btn_ai_module
self.btn_advanced_tools

# Advanced Analysis buttons
self.btn_advanced_mpr
self.btn_stitching

# Auto-discover any other buttons
self.button_safeguard.auto_discover_buttons()
```

### 3. Protected Button Handlers

#### Advanced MPR Button (`_on_advanced_mpr_clicked`)

**Lifecycle:**
1. User clicks "Advanced MPR" button
2. Safeguard starts → All buttons disabled
3. Loading overlay shows
4. QTimer defers actual launch (500ms)
5. Slicer process starts → `_on_advanced_mpr_started()` called
6. Safeguard ends → All buttons re-enabled

**Error Paths:**
- No series selected → Safeguard ends → Buttons re-enabled
- Directory not found → Safeguard ends → Buttons re-enabled
- Launch error → `_on_advanced_mpr_error()` → Safeguard ends → Buttons re-enabled

#### Stitching Button (`_on_stitching_clicked`)

**Lifecycle:**
1. User clicks "Stitching" button
2. Safeguard starts → All buttons disabled
3. Loading overlay shows
4. QTimer defers actual launch (500ms)
5. Stitching widget opens → `_on_stitching_started()` called
6. Safeguard ends → All buttons re-enabled

**Error Paths:**
- No series selected → Safeguard ends → Buttons re-enabled
- Directory not found → Safeguard ends → Buttons re-enabled
- Launch error → `_on_stitching_error()` → Safeguard ends → Buttons re-enabled

## Code Examples

### Protected Click Handler (Manual Control)

```python
def _on_advanced_mpr_clicked(self) -> None:
    # Start the safeguard
    if not self.button_safeguard.start_operation("Advanced MPR Launch"):
        QMessageBox.warning(
            self, "Operation In Progress",
            "Another operation is currently running. Please wait for it to complete."
        )
        return
    
    try:
        # Do validation work
        if not dicom_directory:
            # End safeguard on early return
            self.button_safeguard.end_operation(success=False, operation_name="Advanced MPR Launch")
            return
        
        # Show loading UI and defer heavy work
        self._show_advanced_mpr_loading_ui()
        QTimer.singleShot(500, lambda: self._launch_advanced_mpr_async(...))
        
    except Exception as e:
        # End safeguard on exception
        self.button_safeguard.end_operation(success=False, operation_name="Advanced MPR Launch")
        raise

def _on_advanced_mpr_started(self):
    # Operation completed successfully
    self.button_safeguard.end_operation(success=True, operation_name="Advanced MPR Launch")

def _on_advanced_mpr_error(self, error_msg: str):
    # Operation failed
    self.button_safeguard.end_operation(success=False, operation_name="Advanced MPR Launch")
```

### Using the Decorator (For Simple Cases)

```python
from PacsClient.pacs.patient_tab.utils.button_safeguard import safeguard_action

@safeguard_action
def _on_simple_button_clicked(self):
    # Your code here
    # Buttons are automatically disabled during execution
    # and re-enabled when complete or on error
    pass

@safeguard_action(show_error_dialog=True)
def _on_important_button_clicked(self):
    # Shows error dialog automatically on exceptions
    pass
```

### Using Context Manager

```python
def _on_button_clicked(self):
    try:
        with self.button_safeguard:
            # Buttons disabled here
            self._do_heavy_work()
            # Buttons re-enabled on exit
    except Exception as e:
        # Buttons automatically re-enabled on exception
        logger.error(f"Error: {e}")
```

## How to Add Protection to New Buttons

### Method 1: Automatic Registration (Recommended)

Just create the button and it will be auto-discovered:

```python
self.btn_my_new_feature = QPushButton("My Feature")
self.btn_my_new_feature.clicked.connect(self._on_my_feature_clicked)
# Button will be auto-registered via auto_discover_buttons()
```

### Method 2: Manual Registration

```python
# In __init__ or after button creation
self.button_safeguard.register_button(self.btn_my_new_feature)
```

### Method 3: Batch Registration

```python
buttons = [self.btn_1, self.btn_2, self.btn_3]
self.button_safeguard.register_buttons(buttons)
```

## Adding Protection to New Click Handlers

### For Simple Synchronous Operations

Use the decorator:

```python
@safeguard_action
def _on_my_button_clicked(self):
    # Your code here
    pass
```

### For Complex Async Operations (Like Advanced MPR)

Use manual control:

```python
def _on_my_button_clicked(self):
    # 1. Start safeguard
    if not self.button_safeguard.start_operation("My Operation"):
        QMessageBox.warning(self, "Busy", "Please wait...")
        return
    
    try:
        # 2. Do validation
        if not self._validate():
            self.button_safeguard.end_operation(False, "My Operation")
            return
        
        # 3. Start async work
        self._start_async_work()
        
    except Exception as e:
        # 4. End safeguard on error
        self.button_safeguard.end_operation(False, "My Operation")
        raise

def _on_my_operation_completed(self):
    # 5. End safeguard on success
    self.button_safeguard.end_operation(True, "My Operation")

def _on_my_operation_error(self, error):
    # 6. End safeguard on error
    self.button_safeguard.end_operation(False, "My Operation")
```

## Testing the Implementation

### Manual Testing

1. Open the application
2. Load a patient study
3. Click "Advanced MPR" button
4. Immediately try to click another button (Series, Reception, etc.)
5. ✅ Other buttons should be disabled (grayed out)
6. Wait for Advanced MPR to open
7. ✅ Buttons should become enabled again

### Stress Testing

1. Rapidly click multiple buttons in succession
2. ✅ Only the first click should be processed
3. ✅ Subsequent clicks should be blocked
4. ✅ No hangs or "Not Responding" state

## Debugging

Enable debug logging to see safeguard operations:

```python
import logging
logging.getLogger("PacsClient.pacs.patient_tab.utils.button_safeguard").setLevel(logging.DEBUG)
```

Output example:
```
[ButtonSafeguard] Starting operation: Advanced MPR Launch (#1)
[ButtonSafeguard] Ending operation: Advanced MPR Launch (success=True, #1)
```

## Troubleshoking Common Issues

### Issue: Buttons Stay Disabled

**Cause**: Operation didn't call `end_operation()`

**Solution**: Add try/except blocks and ensure ALL exit paths call `end_operation()`:
```python
try:
    if not self.button_safeguard.start_operation("My Op"):
        return
    
    # ... work ...
    
except Exception as e:
    self.button_safeguard.end_operation(False, "My Op")
    raise
```

### Issue: Buttons Not Protected

**Cause**: Button not registered with safeguard

**Solution**: Either:
1. Let auto-discovery find it
2. Manually register: `self.button_safeguard.register_button(my_button)`

### Issue: Emergency Recovery

If buttons get stuck disabled (shouldn't happen but just in case):

```python
# In Python console or debug code
patient_widget.button_safeguard.force_end_operation()
```

## Benefits

✅ **Prevents Crashes**: No more "Not Responding" from concurrent operations
✅ **Better UX**: Clear visual feedback that operation is in progress
✅ **Maintainable**: Easy to add protection to new buttons
✅ **Reliable**: Automatic cleanup on errors
✅ **Debuggable**: Full logging of operations

## Version History

- **2026-02-25**: Initial implementation for v2.2.2.10
  - Created `button_safeguard.py` utility
  - Integrated into `PatientWidget`
  - Protected Advanced MPR and Stitching buttons
  - Auto-registration of sidebar and analysis buttons

## Future Enhancements

Potential improvements:
- Visual loading indicator on disabled buttons
- Operation queue system (instead of rejecting clicks)
- Per-button timeout detection
- Configurable disable strategy (all vs. related buttons only)

---

**راهنمای فارسی (Persian Guide)**

### نحوه استفاده

1. **برای دکمه‌های جدید**: فقط دکمه را بسازید، به صورت خودکار ثبت می‌شود
2. **برای handler های ساده**: از دکوراتور `@safeguard_action` استفاده کنید
3. **برای handler های پیچیده**: به صورت دستی `start_operation()` و `end_operation()` را فراخوانی کنید

### تست کردن

1. دکمه "Advanced MPR" را بزنید
2. سریع دکمه دیگری بزنید
3. باید دکمه دوم غیرفعال باشد و کلیک نشود
4. بعد از اتمام عملیات، دکمه‌ها دوباره فعال می‌شوند

---

**Contact**: For questions about this implementation, refer to this documentation or check the tests in `test_button_safeguard.py`.
