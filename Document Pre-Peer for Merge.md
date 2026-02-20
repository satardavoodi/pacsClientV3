# Document Pre-Peer for Merge

**Date:** 2026-02-08  
**Scope:** Viewer widgets, VTK widget, 2D viewer, sync pipeline (Lock Sync + reference line fix)  
**Purpose:** Record all session changes that touch viewer/VTK/2D logic to speed up conflict resolution after pulling from main (which has major viewer widget / 2D viewer changes).

---

## 1) Executive summary (what changed and why)

### A) Reference line inversion fix (critical)
- **Root cause:** metadata instances were re-sorted by IPP while VTK slices are loaded by **InstanceNumber** order (files named `Instance_NNNN.dcm` via `natsort`). This mismatch flipped reference lines on certain axial shoulder studies.
- **Fix:** **Removed** `_sort_metadata_instances()` in `viewer_2d.py`. Metadata order now stays as DB order (InstanceNumber).
- **Key rule:** **Never re-sort metadata['instances'] by IPP** unless VTK slice order is also changed to match.

### B) Lock Sync feature (auto-sync on slice change)
- Added a **Lock Sync** toggle to the Sync UI (hamburger dropdown next to Sync Image button).
- Lock Sync **keeps sync pipeline alive** but **does not** force click-to-target interactor. Tools like Stack/Zoom continue to work.
- Lock Sync **auto-syncs** the target viewer on *every* slice change.

### C) Stack tool continuous drag fix (bidirectional)
- QTimer debounce in `_apply_sync_cursor()` was **dropping updates** during continuous Stack drag because token invalidated every pending timer.
- **Fix:** Lock Sync applies **directly** to target viewers, **bypassing** the debounce path.

### D) Cursor conflict fix
- When Lock Sync is enabled and another tool is selected, we remove sync interactor/cursor/observers but keep the sync pipeline alive. This fixes the “red circle cursor stuck” issue.

---

## 2) Files touched (viewer + VTK + toolbar + mapping)

### 2.1 `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py`
**Purpose:** VTK widget. Added callback for slice changes to power Lock Sync.

**Changes:**
- **`__init__`**: added
  - `self._on_slice_changed_cb = None` (Lock Sync callback)
- **`set_slice()`**: after internal updates, fires callback if set:
  - `self._on_slice_changed_cb(self)`

**Why it matters for merge:**
- Any changes to `set_slice()` or widget lifecycle must preserve callback behavior to keep Lock Sync working across **all slice change paths** (wheel, slider, Stack drag, direct set).

---

### 2.2 `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget.py`
**Purpose:** Main patient widget; now owns Lock Sync orchestration.

**New/modified attributes:**
- `_lock_sync_enabled: bool` — Lock Sync ON/OFF
- `_lock_sync_updating: bool` — re-entrancy guard

**Key method changes/additions:**
1) `toggle_sync_point()`
   - When **Lock Sync active** and disabling click-to-target:
     - removes observers
     - restores previous interactor style
     - removes cursor
     - **keeps sync pipeline alive** (`_sync_viewer_map` and sync manager remain)

2) `_register_sync_viewers_pipeline_only()` **(NEW)**
   - Registers viewer IDs + sync manager **without** enabling interactor styles.
   - Enables Lock Sync to function while other tools stay active.

3) `set_lock_sync()` **(NEW)**
   - Stores flag + wires callbacks on all VTK widgets.

4) `_wire_lock_sync_callbacks()` **(NEW)**
   - Sets/clears `_on_slice_changed_cb` in each `VTKWidget`.

5) `_auto_sync_on_slice_change()` **(NEW)**
   - Called on every slice change; uses re-entrancy guard, delegates to `_do_lock_sync()`.

6) `_do_lock_sync()` **(NEW)**
   - Computes world center of current slice.
   - Shows red dot on **source** viewer.
   - **Directly applies** mapped world position to target viewers (bypasses QTimer debounce).
   - Syncs target slider with `blockSignals` to avoid signal loops.

7) `_map_sync_cursor()` (existing)
   - Used by Lock Sync to map world position across viewers.
   - Consistent with **reference_line.py** mapping logic.

**Why it matters for merge:**
- Any refactor of sync pipeline or viewer mapping must preserve:
  - `pipeline-only registration`
  - Lock Sync callback wiring
  - **direct apply** path (no QTimer debounce) for Stack dragging

---

### 2.3 `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`
**Purpose:** Sync UI controls + Lock Sync menu.

**Changes:**
- Import: `SyncMode`
- New methods:
  - `_show_sync_dropdown()` (Lock Sync toggle UI)
  - `_toggle_lock_sync()` (enable/disable logic)
  - `_update_sync_menu_icon()` (green link icon when ON)
- `check_and_deactivate_tools()` now always calls `toggle_sync_point(False)`;
  - `PatientWidget.toggle_sync_point(False)` preserves pipeline when Lock Sync active.
- New **Sync container UI**:
  - Left hamburger button for Lock Sync dropdown
  - Right main Sync Image button (keeps red indicator)

**Why it matters for merge:**
- The Sync UI is now a **compound control** (hamburger + main button). If main changes toolbar layouts, keep this container to preserve Lock Sync UX.

---

### 2.4 `PacsClient/pacs/patient_tab/viewers/viewer_2d.py`
**Purpose:** 2D viewer rendering + sync point drawing + slice mapping.

**Changes:**
- **Removed** `_sort_metadata_instances()` (critical to reference line correctness).
- Sync point methods (`set_sync_point`, `hide_sync_point`) remain unchanged but are essential for Lock Sync.

**Why it matters for merge:**
- Do not reintroduce any metadata resorting here.

---

## 3) Lock Sync behavior & data flow

**Trigger sources for slice change:**
- Mouse wheel → `VTKWidget.wheelEvent()` → slider set
- Stack drag → interactor style `change_quickly_slices()` → slider set
- Slider drag → `on_slider_value_changed()` → `vtk_widget.set_slice()`
- Direct code path → `vtk_widget.set_slice()`

**Unified: `VTKWidget.set_slice()` fires `_on_slice_changed_cb`**

### Flow (simplified)
1. User changes slice in Viewer A
2. `VTKWidget.set_slice()` fires callback
3. `PatientWidget._auto_sync_on_slice_change()`
4. `_do_lock_sync()` computes world center
5. `_map_sync_cursor()` maps to Viewer B
6. `ViewerB.set_sync_point(mapped_world, adjust_slice=True)`
7. Viewer B slider updated (signals blocked)

**Important:** `_do_lock_sync()` is direct; it does **not** use `sync_manager.notify_cursor_moved()` to avoid QTimer debounce dropouts during continuous drag.

---

## 4) Conflict resolution guidance (what to keep after pulling main)

### viewer_2d.py
- **Do NOT reintroduce metadata sorting** or any `_sort_metadata_instances()` calls.
- Keep `set_sync_point()` and `_slice_index_from_world()` logic compatible with Lock Sync.

### vtk_widget.py
- Preserve `_on_slice_changed_cb` and callback invocation inside `set_slice()`.
- If main adds new slice update logic, ensure callback is still invoked **after** slice update and overlay refresh.

### patient_widget.py
- Keep `Lock Sync` methods intact:
  - `set_lock_sync`, `_wire_lock_sync_callbacks`, `_auto_sync_on_slice_change`, `_do_lock_sync`
- Preserve pipeline-only registration method `_register_sync_viewers_pipeline_only()`.
- Preserve logic in `toggle_sync_point()` that **keeps sync pipeline alive** when Lock Sync is ON.

### toolbar_manager.py
- Preserve Sync container (hamburger + sync button) and dropdown logic.
- Ensure `check_and_deactivate_tools()` always calls `toggle_sync_point(False)` so tools can switch without locking cursor.

---

## 5) Known pitfalls + prevention

1) **Do not re-sort metadata instances by IPP**
   - This will desync reference lines from actual VTK slices.

2) **Avoid QTimer debounce in Lock Sync path**
   - Lock Sync must apply directly to keep Stack dragging smooth.

3) **Always keep sync pipeline alive when Lock Sync ON**
   - Disabling click-to-target should not disable sync manager registration.

---

## 6) Quick checklist after pull (manual verification)

- [ ] Sync Image button still toggles click-to-target (red indicator).
- [ ] Lock Sync toggle exists in dropdown (hamburger) with green link icon when ON.
- [ ] Lock Sync works during Stack drag in **both directions**.
- [ ] Changing tools while Lock Sync ON does **not** leave red cursor active.
- [ ] Reference lines move correctly on axial shoulder studies.

---

## 7) Notes about updated logging vs print

Several debug `print()` calls were converted to `logger.debug(...)` in:
- `vtk_widget.py`
- `viewer_2d.py`
- `patient_widget.py`

If main refactors logging, preserve these log points or equivalent diagnostics.

---

## 8) Summary of file list (viewer‑related)

- `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`
- `PacsClient/pacs/patient_tab/viewers/viewer_2d.py`

---

### End of document
