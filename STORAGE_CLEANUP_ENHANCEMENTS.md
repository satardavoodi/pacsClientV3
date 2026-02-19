# Storage Cleanup Feature Enhancements

**Date:** 2026-02-10  
**Feature:** Local Storage & Database Cleanup (Viewer Configuration)

## Overview
Enhanced the storage cleanup system with visual drive usage indicators, responsive layouts, and granular patient filtering options.

---

## 1. Drive Usage Visualization Bars

### Previous State
- Text-only drive usage display with color-coded labels
- No visual representation of disk usage proportions

### Enhancement
**Added QProgressBar-based visualization with color-coded thresholds:**

```python
# Color logic based on free space:
if free_pct < 20.0:
    bar_color = "#ef4444"  # red (critical)
elif free_pct < 40.0:
    bar_color = "#f59e0b"  # amber/yellow (warning)
else:
    bar_color = "#10b981"  # green (healthy)
```

**Visual Structure:**
- Drive label with full stats (used/total/free/percentage)
- 12px height progress bar showing used percentage
- Color-coded styling for immediate visual assessment
- Styled with dark theme borders and backgrounds

**File:** [storage_cleanup_panel.py](PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py#L200-L245)

---

## 2. Responsive Layout Fixes

### Previous State
- Fixed width labels caused text overflow/truncation
- Patient folder paths not fully visible
- Composition percentage labels constrained

### Enhancement
**Replaced fixed widths with minimum widths + flexible stretch:**

```python
label.setMinimumWidth(150)   # was setFixedWidth(170)
path_label.setMinimumWidth(120)
size_label.setMinimumWidth(80)
comp_label.setMinimumWidth(120)
```

**Benefits:**
- Labels can expand to fit content when space available
- Maintains minimum readability threshold
- Better adaptation to different screen sizes/resolutions

**File:** [storage_cleanup_panel.py](PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py#L95-L110)

---

## 3. Granular Patient Cleanup Filters

### Previous State
- Only "Clear ALL Patients Data" option
- No way to selectively clean old/outdated patients
- Risk of losing recently accessed data

### Enhancement
**Added 4 cleanup strategies with preview capability:**

#### Strategy Options:
1. **Clear ALL patient data** (original behavior)
2. **Keep only patients from last X days** (delete older)
3. **Delete patients older than X days** (keep recent)
4. **Delete oldest X patients** (by count)

#### UI Components:
- QDialog with radio button strategy selection
- QSpinBox for numeric value input (days/count)
- "Preview Count" button shows impact before execution
- Confirmation dialog before actual deletion

**File:** [storage_cleanup_panel.py](PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py#L188-L295)

---

## 4. Backend Filtering Implementation

### New Methods Added:

#### `get_total_patient_count()`
Returns total patient count from database for preview calculations.

#### `count_patients_to_delete(strategy, value)`
Counts how many patients would be deleted with given strategy without executing deletion.

**Strategies handled:**
- `older_than_days`: Counts patients with `created_at < cutoff_ts`
- `keep_recent_days`: Counts patients NOT in last X days
- `delete_oldest_count`: Returns minimum of requested count and total patients

#### `cleanup_patients_folder_filtered(strategy, value)`
Executes filtered patient cleanup:

**Process:**
1. Query database for matching patient UIDs based on strategy
2. Delete matching patient folders from SOURCE_PATH
3. Delete matching DB records from `patients` table
4. Clean up related `download_progress` entries
5. Invalidate caches and return CleanupResult

**Safety:**
- Uses parameterized SQL queries (prevents injection)
- Gracefully handles missing folders
- Logs warnings for failed deletions
- Commits transaction only after all operations

**File:** [local_storage_cleanup_manager.py](PacsClient/utils/local_storage_cleanup_manager.py#L375-L509)

---

## 5. Integration Points

### UI Wiring:
```python
# In storage_cleanup_panel.py:
if key == "patients":
    clear_btn.clicked.connect(lambda _, k=key: self._show_patient_cleanup_dialog())
else:
    clear_btn.clicked.connect(lambda _, k=key: self._handle_cleanup_action(k))
```

### Signal Flow:
1. User clicks "Clear Patients Data" button
2. `_show_patient_cleanup_dialog()` opens filter dialog
3. User selects strategy + value, clicks "Preview Count" (optional)
4. User clicks "Execute Cleanup"
5. Confirmation dialog appears
6. Backend executes `cleanup_patients_folder_filtered(strategy, value)`
7. Success dialog shows results
8. UI refreshes with `force_refresh=True`
9. `storageChanged` signal emitted to parent

---

## 6. Database Schema Assumptions

**Required patient table columns:**
- `patient_uid` (TEXT PRIMARY KEY)
- `created_at` (INTEGER - Unix timestamp)

**Related tables:**
- `download_progress` (with `patient_uid` foreign key)

**Fallback behavior:**
- If `created_at` is NULL, treated as timestamp 0 (epoch)
- Filters using `COALESCE(created_at, 0)` for safety

---

## 7. Testing Checklist

### Visual Testing:
- [ ] Drive bars display with correct colors (red <20%, yellow 20-40%, green >40% free)
- [ ] Bars correctly show used percentage
- [ ] Layout remains responsive when resizing window
- [ ] Patient folder paths display fully without truncation

### Functional Testing:
- [ ] "Preview Count" shows accurate patient counts for each strategy
- [ ] "Clear ALL" still works (backward compatibility)
- [ ] "Keep recent 30 days" deletes only older patients
- [ ] "Delete older than 90 days" preserves recent patients
- [ ] "Delete oldest 50 patients" removes correct count
- [ ] DB records cleaned alongside folders
- [ ] Storage insights refresh after cleanup
- [ ] No errors when no patients match filter

### Edge Cases:
- [ ] Strategy with 0 matching patients (should show message, not error)
- [ ] patients table has NULL created_at values
- [ ] Patient folders exist but DB records missing (orphaned folders)
- [ ] DB records exist but folders missing (orphaned records)

---

## 8. User Experience Flow

### Before Cleanup:
1. User opens Viewer Configuration → Storage Cleanup panel
2. Sees drive usage bars (visual assessment)
3. Sees per-folder sizes with composition percentages
4. Notices patient folder size is high

### Cleanup Decision:
5. Clicks "Clear Patients Data"
6. Sees dialog with 4 strategy options
7. Selects "Keep only patients from last 7 days"
8. Clicks "Preview Count" → sees "Will delete 150 patients (keeping 45 from last 7 days)"
9. Confirms strategy is correct

### Execution:
10. Clicks "Execute Cleanup"
11. Confirms in second dialog
12. Sees progress/completion message with stats
13. Storage panel refreshes automatically
14. Drive bars update to show freed space

---

## 9. Code Quality & Safety

### Safety Features:
- ✅ Parameterized SQL queries (no string concatenation)
- ✅ Double confirmation (filter dialog + confirmation dialog)
- ✅ Preview capability before deletion
- ✅ Transaction-based DB operations
- ✅ Cache invalidation after cleanup
- ✅ Graceful error handling with user-facing messages
- ✅ Logging for debugging

### Performance:
- ✅ Uses cached folder sizes (30s TTL)
- ✅ Force refresh after cleanup operations
- ✅ Efficient SQL queries with LIMIT and indexed lookups
- ✅ Single-pass folder deletion with rglob

---

## 10. Files Modified

| File | Changes | Lines |
|------|---------|-------|
| [storage_cleanup_panel.py](PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py) | Added QProgressBar drive bars, patient filter dialog, preview/execute methods | +172 lines |
| [local_storage_cleanup_manager.py](PacsClient/utils/local_storage_cleanup_manager.py) | Added filtering methods (get_total_patient_count, count_patients_to_delete, cleanup_patients_folder_filtered) | +135 lines |

**Total Enhancement:** ~300 lines of production code, 0 errors in diagnostics

---

## 11. Deployment Notes

### No Breaking Changes:
- Existing cleanup behavior preserved for education/cache/printing
- "Clear ALL patients" still available as option
- Backward compatible with existing DB schema
- No migration required

### Required Dependencies:
- PySide6 (QProgressBar, QDialog, QRadioButton, QSpinBox, QButtonGroup, QGroupBox)
- Already included in base requirements

### Configuration:
No configuration changes required. All defaults sensible:
- Keep recent: 30 days default
- Delete older: 90 days default
- Delete oldest: 50 patients default

---

## 12. Future Enhancement Ideas

### Potential Additions:
1. **Date range picker** (from-to dates instead of relative days)
2. **Patient usage analytics** (last accessed timestamp)
3. **Multi-select cleanup** (education + cache + printing together)
4. **Scheduled auto-cleanup** (cron-like rules)
5. **Export patient list** before deletion (audit trail)
6. **Undo mechanism** (backup to temp before deletion)
7. **Size-based filtering** (delete patients >1GB)
8. **Modality-based filtering** (delete only CT patients older than X)

### Not Implemented (By Design):
- Real-time progress bar during deletion (would complicate threading)
- Partial or incremental deletion (all-or-nothing per strategy)
- Patient recovery (would require backup system)

---

## Summary

✅ **Completed all requested enhancements:**
1. Visual drive usage bars with color-coded thresholds
2. Responsive layout fixes for folder display
3. Granular patient filtering with 4 strategies
4. Preview capability before deletion
5. Backend filtering methods with DB sync
6. All diagnostics passing (0 errors)

**User Benefits:**
- Immediate visual assessment of disk health
- Safer cleanup with preview-before-execute
- Flexibility to keep recent patients while freeing space
- Better responsive UI on various screen sizes

**Technical Benefits:**
- Maintainable modular architecture
- Reusable filtering logic
- Safe SQL with parameterization
- Comprehensive error handling
- Cache-aware performance
