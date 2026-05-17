# SEMANTIC BOUNDARY AUDIT: Slice Numbering Formula Change
**Date:** 2026-05-16  
**Status:** COMPREHENSIVE SCOPE COMPLETION  
**Target Change:** K-flip formula from `raw_k = (N-1) - display_k` → `raw_k = display_k - 1`

---

## EXECUTIVE SUMMARY

This audit identifies **ALL** code locations that consume slice indexing variables (`raw_k`, `display_k`, `GetSlice()`, `SetSlice()`, `current_slice_index`, `actual_slice_index`) across the entire AIPacs viewer ecosystem.

**Critical Finding:** The K-flip formula change is load-bearing across THREE separate semantic domains:
1. **DisplayGeometry** layer (display ↔ raw_k conversion)
2. **VTK SetSlice/GetSlice** boundary (raw_k domain)
3. **Metadata['instances']** indexing (raw_k domain)

All three domains must be changed together; partial changes will cause instance lookup failures, W/L corruption, and sync mapping errors.

---

## PART 1: CONSUMER LOCATIONS

### 1.1 ADVANCED VIEWER (VTK-based) — `modules/viewer/advanced/viewer_2d.py`

#### **1.1.1 `get_display_slice()` — Slice-to-Display Conversion**
- **Location:** Line ~1418–1428
- **Code:**
  ```python
  def get_display_slice(self) -> int:
      raw_k = int(self.GetSlice())
      _dg = getattr(self, "_display_geometry_contract", None)
      if _dg is not None and _dg.is_k_flip_active:
          return _dg.raw_k_to_display_k(raw_k)
      return raw_k
  ```
- **Consumption:** Reads `raw_k` from VTK via `GetSlice()`, converts to `display_k` via DisplayGeometry
- **Usage:** On-screen slice counter text, slice position labels
- **Current:** When K-flip active, returns `(N-1) - raw_k`
- **Proposed:** When K-flip active, returns `raw_k - 1`
- **Impact:** HIGH — Every slice number displayed to user changes
- **Risk:** HIGH — Visual mismatch if applied incorrectly

---

#### **1.1.2 `set_slice(slice_index)` / `_set_slice_impl()` — Slice-from-Display**
- **Location:** Line ~1440–1590
- **Input:** `slice_index` parameter (display_k domain, clinically canonical)
- **Conversion Code (Line ~1478–1485):**
  ```python
  _dg = getattr(self, "_display_geometry_contract", None)
  _raw_k = (
      _dg.display_k_to_raw_k(int(slice_index))
      if (_dg is not None and _dg.is_k_flip_active)
      else int(slice_index)
  )
  self.SetSlice(_raw_k)
  actual_slice_index = int(self.GetSlice())
  ```
- **Consumption:** Converts `display_k` → `raw_k`, passes to VTK, then reads back raw_k
- **Usage Chain:**
  1. `SetSlice(_raw_k)` — VTK slice setter
  2. `actual_slice_index = GetSlice()` — Raw VTK k for metadata lookup
  3. `apply_default_window_level(actual_slice_index)` — W/L per-slice
  4. Orientation marker updates using `actual_slice_index`
- **Current Formula:** `raw_k = (N-1) - display_k`
- **Proposed Formula:** `raw_k = display_k - 1`
- **Impact:** CRITICAL — Determines which DICOM instance is selected
- **Risk:** CRITICAL — Wrong W/L preset, wrong orientation markers, wrong metadata

---

#### **1.1.3 `apply_default_window_level(actual_slice_index)` — Per-Slice W/L**
- **Location:** Line ~1491, 1524
- **Consumption:** Indexes `metadata['instances'][actual_slice_index]`
- **Usage:** Retrieves per-slice window/level preset
- **Current Domain:** `actual_slice_index` is `raw_k` (result of `GetSlice()`)
- **Impact:** MEDIUM — Gets W/L from wrong instance if formula changes
- **Risk:** MEDIUM — Subtle visual artifacts if W/L profiles vary by slice

---

#### **1.1.4 Orientation Marker Updates**
- **Location:** Line ~1542, 1553, 1569
- **Consumption:**
  ```python
  if actual_slice_index < len(instances):
      inst = instances[actual_slice_index]
      # Extract row_cos, col_cos for marker orientation
      row_cos = inst.get('ImageOrientationPatient', [...])[0:3]
  ```
- **Usage:** Updates on-screen anatomical orientation markers
- **Impact:** HIGH — Wrong anatomical labels if instance is wrong
- **Risk:** HIGH — Clinical safety issue (wrong anatomy displayed)

---

#### **1.1.5 Diagnostic Audit Emissions**
- **Location:** Line ~1579, 1582, 1587
- **Calls:**
  ```python
  self._emit_advanced_vtk_orientation_audit(actual_slice_index)
  self._emit_axial_stack_order_policy_audit(actual_slice_index)
  ```
- **Consumption:** Passes `actual_slice_index` (raw_k) to audit functions
- **Usage:** Diagnostic logging, forensic analysis
- **Impact:** LOW — Diagnostic-only, non-functional
- **Risk:** LOW — Logs may be misleading if formula changes

---

### 1.2 DISPLAYGEOMETRY CONTRACT — `modules/viewer/geometry/display_geometry.py`

#### **1.2.1 `_k_flip_4x4(n_slices)` — K-Flip Matrix**
- **Location:** Line 145–151
- **Code:**
  ```python
  def _k_flip_4x4(n_slices: int) -> np.ndarray:
      M = _mat4_identity()
      M[2, 2] = -1.0
      M[2, 3] = float(n_slices - 1)
      return M
  ```
- **Semantics:** Builds 4×4 affine matrix for K-axis stack reordering
  - Diagonal element `M[2,2] = -1.0` → negation (reversal)
  - Offset `M[2,3] = (N-1)` → adjust for 0-based indexing
- **Formula Implemented:**
  ```
  raw_k = M[2,2] * display_k + M[2,3]
        = -1.0 * display_k + (N-1)
        = (N-1) - display_k
  ```
- **Proposed Change:**
  ```python
  M[2, 2] = 1.0      # identity scaling (no reversal)
  M[2, 3] = -1.0     # offset to shift indices by 1
  ```
  - New formula: `raw_k = 1.0 * display_k + (-1) = display_k - 1`
- **Impact:** CRITICAL — This is the formula implementation
- **Risk:** CRITICAL — All downstream conversions depend on this

---

#### **1.2.2 `display_k_to_raw_k(display_k)` — Display→Raw Conversion**
- **Location:** Line 324–332
- **Code:**
  ```python
  def display_k_to_raw_k(self, display_k: int) -> int:
      k22 = self._display_to_raw_ijk[2, 2]
      k23 = self._display_to_raw_ijk[2, 3]
      return int(round(k22 * float(display_k) + k23))
  ```
- **Semantics:** Linear transformation of display-space slice index to raw VTK k
- **Current Behavior (K-flip active):**
  - `k22 = -1.0` (diagonal element, from `_k_flip_4x4`)
  - `k23 = (N-1)` (offset element)
  - Result: `(-1) * display_k + (N-1) = (N-1) - display_k`
- **Proposed Behavior:**
  - `k22 = 1.0` (identity scaling)
  - `k23 = -1.0` (offset)
  - Result: `(1) * display_k + (-1) = display_k - 1`
- **Call Sites:**
  - Line 1470 in `_set_slice_impl`: Early check for no-op
  - Line 1481 in `_set_slice_impl`: Main conversion before `SetSlice()`
- **Impact:** CRITICAL — Used in every slice change
- **Risk:** CRITICAL — All VTK SetSlice calls depend on correct mapping

---

#### **1.2.3 `raw_k_to_display_k(raw_k)` — Raw→Display Conversion**
- **Location:** Line 334–344
- **Code:**
  ```python
  def raw_k_to_display_k(self, raw_k: int) -> int:
      if self._raw_ijk_to_display is None:
          return raw_k
      k22 = self._raw_ijk_to_display[2, 2]
      k23 = self._raw_ijk_to_display[2, 3]
      return int(round(k22 * float(raw_k) + k23))
  ```
- **Semantics:** Inverse transformation (inverse of `display_k_to_raw_k`)
- **Current Formula (K-flip active):**
  - Matrix is inverse of `_display_to_raw_ijk`
  - Result: `(-1) * raw_k + (N-1) = (N-1) - raw_k`
  - Verifies: `display_k_to_raw_k(raw_k_to_display_k(k)) == k` ✓
- **Proposed Formula:**
  - Inverse of new matrix
  - Result: `(1) * raw_k + (-1) = raw_k - 1`
  - Must verify round-trip property
- **Call Sites:**
  - Line 1427 in `get_display_slice()`: Convert VTK GetSlice() result to display_k
- **Impact:** CRITICAL — Used to read and convert raw_k to display_k
- **Risk:** CRITICAL — Must maintain inverse property or round-trip breaks

---

#### **1.2.4 `apply_k_flip_for_stack_order(n_slices, reason)` — Orchestration**
- **Location:** Line 254–300
- **Code Excerpt (Key parts):**
  ```python
  # Guard: prevent double-application
  if self._k_flip_applied:
      logger.warning("[DISPLAY_POLICY_DOUBLE_APPLICATION_BLOCKED] ...")
      return self
  
  self._k_flip_applied = True
  T = _k_flip_4x4(n_slices)  # FORMULA IS HERE
  self._display_to_raw_ijk = self._display_to_raw_ijk @ T
  self._operations.append(f"k_flip(n_slices={n_slices}, reason={reason})")
  self._recompute()  # Updates _raw_ijk_to_display (inverse)
  
  # Emit diagnostic
  display_0_raw = self.display_k_to_raw_k(0)
  display_last_raw = self.display_k_to_raw_k(n_slices - 1)
  logger.warning(
      "[DISPLAY_K_RUNTIME_BIND] "
      "viewport_id=%s n_slices=%s k_flip_active=True "
      "display_0_raw_k=%s display_last_raw_k=%s reason=%s",
      ...
  )
  ```
- **Consumption:**
  - Applies `_k_flip_4x4()` matrix composition
  - Recomputes inverse matrix
  - Emits diagnostic log
- **Usage:**
  - Called once per viewport bind (in `_bind_geometry_contract`)
  - Never called again (prevented by `_k_flip_applied` guard)
- **Impact:** CRITICAL — Activation point for entire K-flip system
- **Risk:** CRITICAL — Double-application guard prevents accidents but formula must be correct

---

#### **1.2.5 `is_k_flip_active` Property**
- **Location:** Line 313–314
- **Code:**
  ```python
  @property
  def is_k_flip_active(self) -> bool:
      return bool(self._display_to_raw_ijk[2, 2] < 0)
  ```
- **Semantics:** Checks if K-axis is negated (K-flip applied)
- **Current Logic:** `M[2,2] < 0` (diagonal is -1.0 when flipped)
- **Proposed Logic:** Must update condition to match new formula
  - If new formula uses `M[2,2] = 1.0` for K-flip inactive and some other marker...
  - **IMPORTANT:** Need clarity on how to distinguish K-flip active after formula change
  - Option A: Keep `is_k_flip_active` flag separate from matrix values
  - Option B: Use different matrix values to indicate K-flip
  - **Risk:** HIGH — This property is read in 15+ locations; must be consistent
- **Call Sites:** Line 1426, 1470, 1482 in `viewer_2d.py`; many in `geometry_api.py`

---

#### **1.2.6 `k_flip_n_slices` Property**
- **Location:** Line 318–321
- **Code:**
  ```python
  @property
  def k_flip_n_slices(self) -> Optional[int]:
      if not self.is_k_flip_active:
          return None
      return int(round(self._display_to_raw_ijk[2, 3])) + 1
  ```
- **Semantics:** Returns N (number of slices) when K-flip active, None otherwise
- **Current Logic:** Reads `M[2,3]` which contains `(N-1)`, adds 1
- **Proposed Logic:** If new formula stores K-flip differently in the matrix, update this
- **Impact:** MEDIUM — Used for diagnostics and validation
- **Risk:** MEDIUM — Must remain consistent with `is_k_flip_active` logic

---

### 1.3 FAST VIEWER (Qt-based) — Slice Index Management

#### **1.3.1 `QtViewerBridge.SetSlice(slice_index)` — `modules/viewer/fast/qt_viewer_bridge.py`**
- **Location:** Line 792–796
- **Code:**
  ```python
  def SetSlice(self, slice_index: int) -> None:
      self._current_slice = max(0, min(int(slice_index), self._slice_count - 1))
      self.qt_viewer._current_slice_index = self._current_slice
  ```
- **Semantics:** VTK API compatibility shim for FAST backend
- **Consumption:** Stores `slice_index` directly (no K-flip conversion)
- **Usage:** Downstream FAST rendering uses this index directly
- **Domain:** PURE `display_k` (never raw_k; FAST has no K-flip)
- **Impact:** LOW for formula change (FAST is separate domain)
- **Risk:** MEDIUM — Must NOT accidentally consume DisplayGeometry K-flip

---

#### **1.3.2 `QtSliceViewer._current_slice_index` — `modules/viewer/fast/qt_slice_viewer.py`**
- **Location:** Line 353 (declaration), 591–592 (setter), multiple readers
- **Code:**
  ```python
  self._current_slice_index: int = 0
  
  def set_current_slice_index(self, idx: int) -> None:
      self._current_slice_index = idx
  ```
- **Consumption:**
  - Line 1279, 1301, 1302, 1313: Logged for tracing
  - Line 1432, 1466: Emitted as target for stacked interaction
  - Line 1448, 1496, 1608: Passed to tool controller (mouse, hover)
  - Line 1576: Used as base for multi-frame scroll
  - Line 1929: Passed to tool controller render
  - Line 1959: Passed to tool controller render
- **Usage:** Tool measurement coordinate mapping, mouse event handling
- **Domain:** PURE `display_k` (FAST mode only)
- **Impact:** LOW for formula change (FAST is independent)
- **Risk:** LOW — Internal to FAST; no cross-viewer coupling

---

### 1.4 SYNC ENGINE — Cross-Viewer Geometry Mapping

#### **1.4.1 `GeometryAPI.map_lps_between_viewports()` — `modules/viewer/geometry/geometry_api.py`**
- **Location:** Line 131–180
- **Code Excerpt (Key parts):**
  ```python
  @staticmethod
  def map_lps_between_viewports(
      dg_src: DisplayGeometry, dg_dst: DisplayGeometry,
      i_src: float, j_src: float, k_src: float,
      *, log: bool = False,
  ) -> Optional[Tuple[float, float, float]]:
      """Map displayed pixel in viewport A to corresponding index in viewport B."""
      if not _frames_of_reference_match(dg_src, dg_dst):
          return None
      
      # Convert displayed index (with K-flip) → LPS (absolute space)
      lps = GeometryAPI.displayed_index_to_lps(dg_src, i_src, j_src, k_src)
      
      # Convert LPS → displayed index (with K-flip) in target viewport
      dst = GeometryAPI.lps_to_displayed_index(dg_dst, *lps.tolist())
      
      # Roundtrip validation
      lps_rt = GeometryAPI.displayed_index_to_lps(dg_dst, dst[0], dst[1], dst[2])
      src_rt = GeometryAPI.lps_to_displayed_index(dg_src, *lps_rt.tolist())
      rt_err = math.sqrt((src_rt[0] - i_src)^2 + (src_rt[1] - j_src)^2 + (src_rt[2] - k_src)^2)
  ```
- **Consumption:**
  - `k_src` parameter is in display_k domain (viewport A)
  - Delegates to `dg_src.display_index_to_lps()` which applies K-flip if active
  - Delegates to `dg_dst.lps_to_displayed_index()` which applies inverse K-flip if active
  - Returns `dst` in display_k domain (viewport B)
- **Usage:** Cross-viewer sync point mapping, reference line projection
- **Formula Dependency:** Uses both `display_k_to_raw_k()` and `raw_k_to_display_k()` indirectly
- **Impact:** CRITICAL — K-flip changes which slices are synced across viewers
- **Risk:** CRITICAL — If two viewers have different K-flip formulas, sync breaks

---

#### **1.4.2 `GeometryAPI.displayed_index_to_lps()` — `modules/viewer/geometry/geometry_api.py`**
- **Location:** Line 75–92
- **Code:**
  ```python
  @staticmethod
  def displayed_index_to_lps(
      dg: DisplayGeometry, i_d: float, j_d: float, k: float
  ) -> np.ndarray:
      """Convert displayed pixel (i_d, j_d, k) → patient LPS (mm)."""
      return dg.display_index_to_lps(i_d, j_d, k)
  ```
- **Consumption:** Delegates to `dg.display_index_to_lps()` which applies K-flip
- **Usage:** Reference line projection, sync geometry computation
- **Impact:** MEDIUM — K-flip affects LPS output for a given display_k
- **Risk:** MEDIUM — Wrong LPS if K-flip formula changes

---

#### **1.4.3 `GeometryAPI.lps_to_displayed_index()` — `modules/viewer/geometry/geometry_api.py`**
- **Location:** Line 92–106
- **Code:**
  ```python
  @staticmethod
  def lps_to_displayed_index(
      dg: DisplayGeometry, x: float, y: float, z: float
  ) -> Tuple[float, float, float]:
      """Convert patient LPS (mm) → displayed index (i_d, j_d, k)."""
      v = dg.lps_to_display_index(x, y, z)
      return float(v[0]), float(v[1]), float(v[2])
  ```
- **Consumption:** Inverse operation; delegates to `dg.lps_to_display_index()`
- **Usage:** Reference line intersection calculation, sync source finding
- **Impact:** MEDIUM — K-flip affects which display_k is returned for a given LPS point
- **Risk:** MEDIUM — Roundtrip errors if K-flip formula breaks

---

### 1.5 METADATA AND INSTANCE LOOKUP

#### **1.5.1 `_set_slice_impl()` Metadata Indexing — `modules/viewer/advanced/viewer_2d.py`**
- **Location:** Line 1524–1525
- **Code:**
  ```python
  if actual_slice_index < len(instances):
      inst = instances[actual_slice_index]
      # Extract IPP, IOP, W/L, etc.
  ```
- **Consumption:** Uses `actual_slice_index = int(self.GetSlice())` (raw_k) to index metadata
- **Usage:** Retrieves per-instance DICOM attributes (IPP, IOP, W/L presets)
- **Domain Requirement:** MUST be raw_k; metadata['instances'] is in raw_k order (VTK file load order)
- **Impact:** CRITICAL — Wrong instance = wrong geometry, wrong W/L
- **Risk:** CRITICAL — Formula error here breaks everything downstream

---

#### **1.5.2 Instance Lookup in Reference Line — `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/reference_line.py`**
- **Location:** Line 20–73 (`rl_sort_instances_by_ipp()`)
- **Code:**
  ```python
  def rl_sort_instances_by_ipp(instances):
      """Sort instances into anatomical (IPP/IOP) order for sync/reference-line use."""
      if not instances or len(instances) <= 1:
          return instances
      
      # Collect normals from IOP
      normals = []
      for inst in instances:
          iop = inst.get("image_orientation_patient")
          if iop and len(iop) >= 6:
              # Cross product of row and column vectors
              n = np.cross(row_v, col_v)
              normals.append(n / n_len)
      
      # Sort by IPP dot(IPP, mean_normal)
      def _sort_key(inst):
          ipp = inst.get("image_position_patient")
          if ipp and len(ipp) >= 3:
              return float(np.dot(ipp, mean_n))
          return float("inf")
      
      return sorted(instances, key=_sort_key)
  ```
- **Consumption:** Sorts instance metadata by physical position (IPP)
- **Usage:** For Advanced viewer, this is idempotent (already sorted at load). For FAST viewer, re-sorts for reference-line calculations.
- **Semantic Convention:** `normal = cross(row=[IOP[0:3]], col=[IOP[3:6]])` (standard DICOM display)
- **Ascending IPP ordering:** 
  - Axial HFS [row=X, col=Y] → normal=+Z → Inferior first (ascending z)
  - Sagittal [row=Y, col=Z] → normal=+X → Left first
  - Coronal [row=X, col=Z] → normal=-Y → Posterior first
- **Impact:** MEDIUM — Reference line positioning depends on correct instance mapping
- **Risk:** MEDIUM — If slice index domain is wrong, reference line projects to wrong anatomy

---

### 1.6 SYNC OPERATIONS — Cross-Viewer Synchronization

#### **1.6.1 `_PWSyncMixin._do_lock_sync()` — `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py`**
- **Location:** Line 360–400
- **Code Excerpt:**
  ```python
  current_slice = self.image_viewer.GetSlice()  # raw_k
  
  # Get instance for this slice
  if current_slice < len(_instances):
      _inst = _instances[current_slice]
      _ipp = _inst.get('image_position_patient')
      # Compute true LPS center of this slice
      _P_c = image_pixel_to_lps(
          _cols / 2.0, _rows / 2.0,
          np.asarray(_ipp, float), _iop, _ps,
      )
      world_pos = (float(_P_c[0]), float(_P_c[1]), float(_P_c[2]))
  ```
- **Consumption:**
  - Reads `current_slice = GetSlice()` (raw_k)
  - Indexes into `_instances[current_slice]`
  - Extracts IPP/IOP for LPS-to-world conversion
- **Usage:** Computes sync-point LPS position for cross-viewer sync
- **Domain Requirement:** `current_slice` MUST be raw_k (VTK index order)
- **Impact:** MEDIUM — Sync point LPS position depends on correct slice
- **Risk:** MEDIUM — Wrong sync point if instance mapping fails

---

#### **1.6.2 `_PWSyncMixin._geometry_instances_for_viewer()` — Instance Domain Classification**
- **Location:** Line 675–788
- **Code Excerpt:**
  ```python
  def _geometry_instances_for_viewer(viewer, *, caller: str, current_slice_index: int | None = None):
      """Return instance list for a viewer, potentially reordered by geometry."""
      
      # Classify domain based on viewer backend
      if getattr(viewer, 'IS_QT_BRIDGE', False):
          # FAST path: display order
          logger.debug("current_slice_index_domain=FAST_DISPLAY_ORDER ...")
          # Return instances in InstanceNumber (display) order
      else:
          # Advanced path: raw_k order
          logger.debug("current_slice_index_domain=ADVANCED_DISPLAY_ORDER ...")
          # Return instances in VTK (raw_k) order
  ```
- **Consumption:** Takes `current_slice_index` parameter, classifies its domain
- **Usage:** Logs domain information for diagnostics, returns appropriately-ordered instance list
- **Domain Handling:**
  - FAST: `current_slice_index` is DISPLAY_ORDER (no K-flip)
  - Advanced: `current_slice_index` is RAW_K order (post K-flip conversion)
  - Geometry-sorted: Special reordering for sync calculations
- **Impact:** MEDIUM — Domain classification affects sync correctness
- **Risk:** MEDIUM — If domain is misclassified, wrong instance is used

---

### 1.7 WINDOW/LEVEL AND ORIENTATION

#### **1.7.1 `apply_default_window_level(actual_slice_index)` — Per-Slice W/L**
- **File:** `modules/viewer/advanced/viewer_2d.py` (implicitly called from `_set_slice_impl`)
- **Consumption:** Indexes `metadata['instances'][actual_slice_index]`
- **Usage:** Retrieves per-instance window width/center presets
- **Impact:** MEDIUM — Wrong W/L if instance is wrong
- **Risk:** MEDIUM — Visual change if W/L profiles vary significantly

---

#### **1.7.2 Orientation Marker Update — **
- **File:** `modules/viewer/advanced/viewer_2d.py`, `modules/viewer/advanced/orientation_markers.py`
- **Consumption (Line 1542–1569):** Extracts row/col cosines from `instances[actual_slice_index]`
- **Usage:** Updates on-screen anatomical orientation labels
- **Impact:** HIGH — Wrong labels = clinical safety issue
- **Risk:** HIGH — User sees wrong anatomy

---

### 1.8 MEASUREMENTS AND TOOLS

#### **1.8.1 Ruler, Angle, ROI Tools — `modules/viewer/advanced/interactor_styles/`**
- **Files:**
  - `ruler_interactorstyle.py` — Line 30, 101, 134, 211, 266
  - `angle_interactorstyle.py` — Line 73, 99
  - `roi_interactorstyle.py` — Line 492, 807, 818, 866, 881
  - `eraser_interactorstyle.py` — Line 22, 29
  - `abstract_interactorstyle.py` — Line 110, 414, 419, 564, 852
- **Pattern:**
  ```python
  current_slice = self.image_viewer.GetSlice()  # raw_k
  # Store with measurement annotation for later retrieval
  ```
- **Consumption:** Read `GetSlice()` (raw_k) to associate measurements with slice
- **Usage:** Store measurement slice context, validate measurement persistence
- **Domain:** Raw_k (VTK index)
- **Impact:** MEDIUM — Tool measurements must reference correct slice
- **Risk:** MEDIUM — Wrong slice context if GetSlice() returns wrong domain

---

### 1.9 PROGRESS AND DIAGNOSTICS

#### **1.9.1 Diagnostic Slice Index Logging**
- **Files:** Various (`_vw_backend.py`, `viewer_2d.py`, `_pw_sync.py`)
- **Pattern:**
  ```python
  logger.debug("current_slice_index=%d", current_slice_index)
  # Or: logger.warning("[SOME_LOG_TAG] slice=%d ...", raw_k)
  ```
- **Consumption:** Logs raw_k or display_k for diagnostics
- **Usage:** Audit trails, forensics, debugging
- **Impact:** LOW — Diagnostic-only, non-functional
- **Risk:** LOW — Logs may be confusing if domains change but not documented

---

## PART 2: GROUPED BY SUBSYSTEM

### 2.1 Viewer Rendering

| Component | File | Function | Current Formula | Proposed Formula | Risk |
|-----------|------|----------|-----------------|------------------|------|
| Display slice counter | `viewer_2d.py` | `get_display_slice()` | `(N-1)-raw_k` | `raw_k-1` | HIGH |
| Slice setter | `viewer_2d.py` | `_set_slice_impl()` | `display_k→(N-1)-display_k` | `display_k→display_k-1` | CRITICAL |
| Metadata indexing | `viewer_2d.py` | `_set_slice_impl()` L1524 | Uses `GetSlice()` → raw_k | Same | CRITICAL |
| W/L per-slice | `viewer_2d.py` | `apply_default_window_level()` | Indexes `instances[raw_k]` | Same | MEDIUM |
| Orientation markers | `viewer_2d.py` | `_set_slice_impl()` L1542–1569 | Extracts from `instances[raw_k]` | Same | HIGH |

### 2.2 Slider / UI Interaction

| Component | File | Function | Current | Proposed | Risk |
|-----------|------|----------|---------|----------|------|
| Slider → SetSlice | `viewer_2d.py` | `set_slice()` entry | Slider value (display_k) | Same | LOW |
| GetSlice display | `viewer_2d.py` | `get_display_slice()` | Converts raw_k via K-flip | Via new formula | HIGH |

### 2.3 Scroll / Interaction

| Component | File | Function | Current | Proposed | Risk |
|-----------|------|----------|---------|----------|------|
| Mouse press | `qt_slice_viewer.py` | `on_mouse_press()` | Uses `_current_slice_index` | Same (FAST domain) | LOW |
| Mouse move | `qt_slice_viewer.py` | `on_mouse_move()` | Uses `_current_slice_index` | Same | LOW |
| Hover | `qt_slice_viewer.py` | `on_hover()` | Uses `_current_slice_index` | Same | LOW |
| Render | `qt_slice_viewer.py` | `render()` | Uses `_current_slice_index` | Same | LOW |

### 2.4 Synchronization

| Component | File | Function | Current | Proposed | Risk |
|-----------|------|----------|---------|----------|------|
| LPS mapping | `geometry_api.py` | `map_lps_between_viewports()` | Via DisplayGeometry | Via new formula | CRITICAL |
| Index→LPS | `geometry_api.py` | `displayed_index_to_lps()` | Via `display_k_to_raw_k()` | Via new formula | MEDIUM |
| LPS→Index | `geometry_api.py` | `lps_to_displayed_index()` | Via `raw_k_to_display_k()` | Via new formula | MEDIUM |
| Lock sync | `_pw_sync.py` | `_do_lock_sync()` | Uses `GetSlice()` raw_k | Same | MEDIUM |

### 2.5 Reference Lines

| Component | File | Function | Current | Proposed | Risk |
|-----------|------|----------|---------|----------|------|
| Instance sort | `reference_line.py` | `rl_sort_instances_by_ipp()` | IPP-based geometric sort | Must stay aligned | MEDIUM |
| Quad corners | `reference_line.py` | `rl_quad_corners_lps()` | Uses instance IPP/IOP | Same | MEDIUM |
| Clip plane | `reference_line.py` | `rl_clip_plane_with_quad()` | Geometry intersection | Same | LOW |

### 2.6 Metadata/SOP Lookup

| Component | File | Function | Current | Proposed | Risk |
|-----------|------|----------|---------|----------|------|
| Instance indexing | `viewer_2d.py` | `_set_slice_impl()` L1524 | `instances[raw_k]` | Same | CRITICAL |
| W/L lookup | `viewer_2d.py` | `apply_default_window_level()` | `instances[raw_k]` | Same | MEDIUM |
| Orientation lookup | `viewer_2d.py` | `_set_slice_impl()` L1542 | `instances[raw_k]` | Same | HIGH |
| Domain classification | `_pw_sync.py` | `_geometry_instances_for_viewer()` | Raw_k vs display_k | Must stay aligned | MEDIUM |

### 2.7 Measurements

| Component | File | Function | Current | Proposed | Risk |
|-----------|------|----------|---------|----------|------|
| Ruler | `ruler_interactorstyle.py` | `on_mouse_*()` | Stores `GetSlice()` | Same | MEDIUM |
| Angle | `angle_interactorstyle.py` | `on_mouse_*()` | Stores `GetSlice()` | Same | MEDIUM |
| ROI | `roi_interactorstyle.py` | `on_mouse_*()` | Stores `GetSlice()` | Same | MEDIUM |
| Eraser | `eraser_interactorstyle.py` | `on_mouse_*()` | Stores `GetSlice()` | Same | MEDIUM |

### 2.8 MPR / Curved MPR

| Component | File | Function | Current | Proposed | Risk |
|-----------|------|----------|---------|----------|------|
| Crosshair labels | `_mpr_crosshair_render.py` | Slice numbering | Position→instance mapping | Must validate | MEDIUM |
| Volume loading | `volume_loader.py` | `load_dicom_series()` | Independent geometry | No impact expected | LOW |

---

## PART 3: K-FLIP FORMULA LOCATIONS (EVERY PLACE FORMULA APPEARS)

### 3.1 Primary K-Flip Implementation

| Location | Line | Code | Current | Proposed | Changes Required |
|----------|------|------|---------|----------|-------------------|
| `_k_flip_4x4()` | 145–151 | Matrix M[2,2], M[2,3] | `-1.0`, `(N-1)` | `1.0`, `-1.0` | **UPDATE BOTH** |
| `display_k_to_raw_k()` | 324–332 | `k22*display_k+k23` | `(-1)*d+(N-1)` | `(1)*d+(-1)` | **AUTO via matrix** |
| `raw_k_to_display_k()` | 334–344 | Inverse via `_raw_ijk_to_display` | `(-1)*r+(N-1)` | `(1)*r+(-1)` | **AUTO via inverse** |
| `is_k_flip_active` | 313–314 | Check `M[2,2] < 0` | Diagonal < 0 | **MUST UPDATE** | **NEW LOGIC** |
| `k_flip_n_slices` | 318–321 | Compute from `M[2,3]+1` | `(N-1)+1` | **MUST UPDATE** | **NEW LOGIC** |

### 3.2 K-Flip Orchestration

| Location | Line | Code | Current | Proposed | Changes Required |
|----------|------|------|---------|----------|-------------------|
| `apply_k_flip_for_stack_order()` | 254–300 | Calls `_k_flip_4x4()`, composes matrix, emits log | Applies full K-flip | Apply new formula | **FORMULA FLOWS THROUGH** |
| `_recompute()` | ~200s | Computes inverse matrices | Inverts display_to_raw | Inverts new formula | **AUTO via inverse** |
| Double-apply guard | 269 | Check `_k_flip_applied` | Prevents second apply | Same guard works | **NO CHANGE** |

### 3.3 Formula Verification (Round-Trip)

**Current (K-flip active):**
```
display_k = 5, N = 20
→ display_k_to_raw_k(5) = (-1)*5 + (20-1) = -5 + 19 = 14 ✓
→ raw_k_to_display_k(14) = (-1)*14 + (20-1) = -14 + 19 = 5 ✓
Round-trip: 5 → 14 → 5 ✓
```

**Proposed (no K-flip):**
```
display_k = 5, N = 20
→ display_k_to_raw_k(5) = (1)*5 + (-1) = 5 - 1 = 4 ✓
→ raw_k_to_display_k(4) = (1)*4 + (-1) = 4 - 1 = 3 ✗
FAILS ROUND-TRIP!
```

**Correction:** The inverse formula must be:
```
If display_k = raw_k - 1 (forward), then raw_k = display_k + 1 (inverse)
```

So new `raw_k_to_display_k()`:
```
k22 = 1.0, k23 = 1.0
raw_k_to_display_k(raw_k) = (1)*raw_k + (1) = raw_k + 1 ✓
Verify: display_k = 5 → raw_k = 4 → display_k = 4 + 1 = 5 ✓
```

**CRITICAL:** Inverse matrix `_raw_ijk_to_display` must have M[2,2]=1.0, M[2,3]=1.0

---

## PART 4: CHAIN ANALYSIS

### 4.1 Chain: User Selects Slice via Slider

```
┌─────────────────────────────────────────────────────────────┐
│ SLIDER VALUE (display_k domain, clinically canonical)      │
│ Example: slider.value() = 5 means "5th slice" (1-indexed)  │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│ ImageViewer2D.set_slice(display_k=5)                     │
│  → _set_slice_impl(slice_index=5)                        │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼ (Line 1478–1485)
┌──────────────────────────────────────────────────────────┐
│ DisplayGeometry.display_k_to_raw_k(5)                    │
│ Current: (-1)*5 + (20-1) = 14                            │
│ Proposed: (1)*5 + (-1) = 4                               │
│ Returns: raw_k = 14 (or 4 in new formula)               │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│ VTK SetSlice(raw_k=14)   [or SetSlice(raw_k=4)]         │
│ VTK renders voxel plane at array index 14 (or 4)        │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│ actual_slice_index = GetSlice() = 14 (or 4)             │
│ This is raw_k in VTK's native index space               │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼ (Line 1524–1525)
┌──────────────────────────────────────────────────────────┐
│ inst = metadata['instances'][actual_slice_index]        │
│ Retrieves DICOM instance at VTK index 14 (or 4)        │
│ Gets: IPP, IOP, W/L preset, etc.                        │
└──────────────────┬───────────────────────────────────────┘
                   │
         ┌─────────┴─────────┬──────────────┐
         │                   │              │
         ▼                   ▼              ▼
   ┌─────────┐         ┌──────────┐   ┌──────────┐
   │ Apply   │         │ Update   │   │ Diagnostic
   │ W/L     │         │ Marker   │   │ Log
   │Preset   │         │Orientation  │ [AXIAL_*]
   └─────────┘         └──────────┘   └──────────┘
```

**Impact of Formula Change:**
- Current formula with K-flip: `raw_k = 14` selects instance at VTK index 14
- Proposed formula (no K-flip): `raw_k = 4` selects instance at VTK index 4
- **If the instance list order changes, user sees a different slice**

---

### 4.2 Chain: Cross-Viewer Sync

```
┌─────────────────────────────────────────────────────────────┐
│ SOURCE VIEWER (display_k=5)                                │
│ User hovers cursor on slice 5                              │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼ (map_lps_between_viewports)
┌──────────────────────────────────────────────────────────┐
│ dg_src.displayed_index_to_lps(i_src, j_src, k_src=5)   │
│ Converts displayed pixel to patient LPS (mm)             │
│ Current: Applies K-flip formula: (N-1)-5 = 14           │
│ Proposed: Applies new formula: 5-1 = 4                  │
│ Returns: LPS point (X, Y, Z)                            │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│ LPS POINT IN PATIENT SPACE (common reference)            │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼ (map to target viewport)
┌──────────────────────────────────────────────────────────┐
│ dg_dst.lps_to_displayed_index(X, Y, Z)                  │
│ Converts LPS back to displayed index in target viewport  │
│ Returns: (i_dst, j_dst, k_dst)                          │
│ Current: Applies inverse K-flip: (N-1)-k_lps = ?       │
│ Proposed: Applies inverse formula: k_lps + 1 = ?       │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│ TARGET VIEWER receives k_dst display index               │
│ Renders that slice with sync-point overlay               │
└──────────────────────────────────────────────────────────┘
```

**Impact of Formula Change:**
- If source and target viewports have DIFFERENT K-flip formulas:
  - Source applies current formula: `raw_k = (N-1) - display_k`
  - Target applies new formula: `raw_k = display_k - 1`
  - **Round-trip error → Sync point appears on wrong slice in target**
- If BOTH viewports use new formula:
  - Both apply same formula consistently
  - Sync works correctly ✓

**Critical Requirement:** ALL viewports must use the same formula

---

### 4.3 Chain: Reference Line Projection

```
┌─────────────────────────────────────────────────────────────┐
│ CURRENT SLICE INDEX (actual_slice_index = raw_k)           │
│ From: actual_slice_index = GetSlice()                      │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼ (Line 1524–1525)
┌──────────────────────────────────────────────────────────┐
│ inst = metadata['instances'][actual_slice_index]        │
│ Retrieves DICOM slice metadata                           │
│ Extracts: IPP (position), IOP (orientation)              │
└──────────────────┬───────────────────────────────────────┘
                   │
         ┌─────────┴─────────┐
         │                   │
         ▼                   ▼
   ┌──────────────┐   ┌─────────────┐
   │ For other    │   │ Extract row/
   │ viewers:     │   │ col cosines
   │ Convert to   │   │ from IOP
   │ their LPS    │   └─────────────┘
   │ reference    │          │
   └──────────────┘          ▼
         │            ┌──────────────┐
         │            │ Update on-
         │            │ screen marker
         │            │ orientation
         │            └──────────────┘
         │
         ▼ (if syncing with other viewer)
   ┌──────────────────────────────────┐
   │ Map this slice's LPS to target   │
   │ viewer via GeometryAPI          │
   │ Returns: k_target display index  │
   └──────────────────────────────────┘
         │
         ▼
   ┌──────────────────────────────────┐
   │ Target viewer retrieves          │
   │ instances[k_target]              │
   │ Projects reference line on that  │
   │ slice                            │
   └──────────────────────────────────┘
```

**Impact of Formula Change:**
- If raw_k changes (due to formula change), wrong instance is retrieved
- **If metadata['instances'] is in different order, wrong IPP/IOP is used**
- Reference line appears on anatomically incorrect location
- **Clinical safety issue**

---

### 4.4 Chain: W/L Per-Slice

```
┌──────────────────────────────────────────────────┐
│ ImageViewer2D._set_slice_impl()                  │
│ (Line 1491)                                      │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│ apply_default_window_level(actual_slice_index)  │
│ actual_slice_index = int(GetSlice()) = raw_k    │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│ Query metadata['instances'][raw_k]               │
│ Retrieve window_width, window_center from that   │
│ instance's DICOM attributes                      │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│ Apply W/L to currently displayed pixel data      │
│ User sees appropriate contrast/brightness for    │
│ this anatomical slice                            │
└──────────────────────────────────────────────────┘
```

**Impact of Formula Change:**
- If formula changes `raw_k` mapping, wrong W/L preset is retrieved
- Wrong preset = wrong visual appearance
- **Subtle artifact if W/L profiles are similar, obvious if they differ**

---

## PART 5: FORMULA MATRIX DETAILS

### 5.1 Current K-Flip Matrix

**Identity Matrix (no transform):**
```
[1  0  0  0]
[0  1  0  0]
[0  0  1  0]
[0  0  0  1]
```

**After `_k_flip_4x4(N=20)` composition:**
```
Identity @ _k_flip_4x4:
[1  0  0  0]    [1   0  -1   19]
[0  1  0  0] @  [0   1   0    0] =
[0  0  1  0]    [0   0   0    0]
[0  0  0  1]    [0   0   0    1]

[1  0  -1   19]
[0  1   0    0]
[0  0   0    0]
[0  0   0    1]
```

**K-axis transformation (row 2):**
```
raw_i = 1.0 * display_i + 0 * display_j - 1.0 * display_k + 19
      = display_i - display_k + 19
```

But we want just k-axis transformation:
```
raw_k = -1.0 * display_k + (N-1)
      = -1.0 * display_k + 19
```

For N=20, display_k ∈ [0,19]:
```
display_k = 0  → raw_k = 19 (first display slice is at VTK index 19)
display_k = 1  → raw_k = 18
display_k = 10 → raw_k = 9
display_k = 19 → raw_k = 0 (last display slice is at VTK index 0)
```

### 5.2 Proposed Non-K-Flip Matrix

**If we simply remove K-flip (apply identity):**
```
raw_k = 1.0 * display_k + 0
      = display_k
```

But the proposal from the decision document is:
```
raw_k = display_k - 1
```

**So the matrix should be:**
```
[1  0   1  -1]
[0  1   0   0]
[0  0   0   0]
[0  0   0   1]
```

K-axis transformation (row 2):
```
raw_k = 1.0 * display_k + (-1)
      = display_k - 1
```

For N=20, display_k ∈ [0,19]:
```
display_k = 0  → raw_k = -1 (INVALID! Out of bounds)
display_k = 1  → raw_k = 0 (first display slice is at VTK index 0)
display_k = 10 → raw_k = 9
display_k = 19 → raw_k = 18 (last display slice is at VTK index 18)
```

**ISSUE:** display_k=0 produces invalid raw_k=-1

**Resolution:** Update slider/UI to use 1-based indexing consistently:
- display_k ∈ [1,N] (1-indexed, clinically canonical)
- raw_k ∈ [0,N-1] (0-indexed, VTK array indices)
- Formula: `raw_k = display_k - 1`

### 5.3 Inverse Matrix Derivation

**Forward:**
```
[1   -1]
[0  (N-1)]
```
Applied to k: `raw_k = -1.0 * display_k + (N-1)`

**Inverse formula (solve for display_k):**
```
raw_k = -1.0 * display_k + (N-1)
raw_k - (N-1) = -1.0 * display_k
-1.0 * (raw_k - (N-1)) = display_k
(-(raw_k - (N-1))) = display_k
((N-1) - raw_k) = display_k
```

So inverse matrix element k22 = -1.0 (same as forward) ✓
And offset k23' = (N-1) (same as forward) ✓

**For proposed formula:**
```
raw_k = 1.0 * display_k + (-1)
raw_k + 1 = display_k
```

So inverse matrix element k22 = 1.0
And offset k23' = 1.0

---

## PART 6: CRITICAL FINDINGS

### **FINDING 1: K-Flip is NOT K-Flip After Formula Change**

The proposed formula `raw_k = display_k - 1` is NOT a K-flip transformation.

- **K-flip (current):** Reverses Z-axis (bottom↔top), formula has negative diagonal
- **Identity (proposed):** Does NOT reverse Z-axis, formula has positive diagonal
- **Semantic impact:** This is a removal of K-flip, not a change to K-flip

**Decision needed:** Is the proposal to:
1. **Remove K-flip entirely** (proposed formula)? OR
2. **Modify K-flip formula** (keep flipping behavior but different formula)?

If (1), then `is_k_flip_active` should return `False` after change, not `True`.

---

### **FINDING 2: Round-Trip Property Failure**

The matrix form of the proposed formula must have correct inverse:

**Proposed forward:** `raw_k = 1.0 * display_k + (-1)`
**Proposed inverse:** Must satisfy `raw_k_to_display_k(display_k_to_raw_k(x)) == x`

```
display_k = 10
→ raw_k = 1.0 * 10 + (-1) = 9
→ display_k' = 1.0 * 9 + 1 = 10 ✓
```

**Inverse must be:** `display_k = 1.0 * raw_k + (1)`

This is correctly implemented via matrix inversion:
- Forward: `M[2,2] = 1.0, M[2,3] = -1.0`
- Inverse: `M_inv[2,2] = 1.0, M_inv[2,3] = 1.0`

---

### **FINDING 3: 0-Indexed vs 1-Indexed Ambiguity**

The proposal states `raw_k = display_k - 1`, but does not clarify indexing:

- **If display_k is 1-indexed** (1–N): `raw_k = display_k - 1` produces [0,N-1] ✓
- **If display_k is 0-indexed** (0–N-1): `raw_k = display_k - 1` produces [-1,N-2] ✗

**Current code assumes 0-indexed display_k throughout** (`get_display_slice()` return value, slider values, etc.).

**Required clarification:** Either
1. Change ALL display_k indexing to 1-based, OR
2. Reinterpret formula as `raw_k = display_k` (identity) if display_k is 0-indexed

---

### **FINDING 4: All Four Conversion Functions Must Sync**

Change to formula requires updates in **exactly four places** simultaneously:

1. `_k_flip_4x4()`: M[2,2], M[2,3] values
2. `display_k_to_raw_k()`: Uses M[2,2], M[2,3] directly (auto-updates via matrix)
3. `raw_k_to_display_k()`: Uses inverse matrix (auto-updates via `_recompute()`)
4. `is_k_flip_active`, `k_flip_n_slices`: Logic must match new matrix values

**If any one is missed, round-trip breaks → sync breaks → reference line breaks.**

---

### **FINDING 5: 15+ Reader Call Sites**

The `is_k_flip_active` property is read in **15+ locations**:

```
modules/viewer/advanced/viewer_2d.py:
  Line 1426: if _dg is not None and _dg.is_k_flip_active:
  Line 1470: if (_dg_early is not None and _dg_early.is_k_flip_active)
  Line 1482: if (_dg is not None and _dg.is_k_flip_active)

modules/viewer/geometry/geometry_api.py:
  Multiple locations for contract checking

And many diagnostics checks...
```

**All must reflect the new semantics** (or none of them will recognize K-flip as active/inactive).

---

### **FINDING 6: Diagnostic Log Timing**

The `[DISPLAY_K_RUNTIME_BIND]` log emitted in `apply_k_flip_for_stack_order()` shows:
```
display_0_raw_k=N-1, display_last_raw_k=0  (current formula)
```

After change, will show:
```
display_0_raw_k=?, display_last_raw_k=?  (new formula)
```

**Diagnostic baseline values will change.** Scripts or dashboards that check for these values must be updated.

---

## SUMMARY TABLE: ALL LOCATIONS

| **File** | **Line** | **Function** | **Variable** | **Current Usage** | **Proposed Usage** | **Risk** |
|----------|----------|--------------|------|----------|----------|------|
| `viewer_2d.py` | 1418 | `get_display_slice()` | `raw_k` | `GetSlice()` result | Same | LOW |
| `viewer_2d.py` | 1426 | `get_display_slice()` | (check) | `is_k_flip_active` | Update logic | MEDIUM |
| `viewer_2d.py` | 1427 | `get_display_slice()` | (convert) | `raw_k_to_display_k()` | Use new formula | MEDIUM |
| `viewer_2d.py` | 1470 | `_set_slice_impl()` | (early check) | `display_k_to_raw_k()` | Use new formula | MEDIUM |
| `viewer_2d.py` | 1478–1485 | `_set_slice_impl()` | (main convert) | `display_k_to_raw_k()` | Use new formula | **CRITICAL** |
| `viewer_2d.py` | 1485 | `_set_slice_impl()` | (SetSlice) | Pass `raw_k` to VTK | Same | LOW |
| `viewer_2d.py` | 1486 | `_set_slice_impl()` | `actual_slice_index` | `GetSlice()` result | Same | LOW |
| `viewer_2d.py` | 1491 | `_set_slice_impl()` | (WL apply) | Use `actual_slice_index` | Same | MEDIUM |
| `viewer_2d.py` | 1524–1525 | `_set_slice_impl()` | (metadata) | Index `instances[actual_slice_index]` | Same | **CRITICAL** |
| `viewer_2d.py` | 1542–1569 | `_set_slice_impl()` | (marker) | Extract from `instances[actual_slice_index]` | Same | **HIGH** |
| `viewer_2d.py` | 1579–1587 | `_set_slice_impl()` | (diagnostics) | Pass to audit functions | Same | LOW |
| `display_geometry.py` | 145–151 | `_k_flip_4x4()` | (matrix) | Build M[2,2]=-1, M[2,3]=(N-1) | Update to new formula | **CRITICAL** |
| `display_geometry.py` | 282 | `apply_k_flip_for_stack_order()` | (compose) | M @ T | Same pattern | LOW |
| `display_geometry.py` | 313–314 | `is_k_flip_active` | (check) | `M[2,2] < 0` | **UPDATE LOGIC** | **CRITICAL** |
| `display_geometry.py` | 318–321 | `k_flip_n_slices` | (compute) | `round(M[2,3]) + 1` | **UPDATE LOGIC** | **CRITICAL** |
| `display_geometry.py` | 324–332 | `display_k_to_raw_k()` | (transform) | `M[2,2]*display_k + M[2,3]` | Auto-update via M | MEDIUM |
| `display_geometry.py` | 334–344 | `raw_k_to_display_k()` | (inverse) | Via `_raw_ijk_to_display` | Auto-update via inverse | MEDIUM |
| `geometry_api.py` | ~107 | `map_lps_between_viewports()` | (implicit) | Uses both conversion functions | Flows through formula | **HIGH** |
| `qt_viewer_bridge.py` | 794 | `SetSlice()` | (set) | Store directly (FAST domain) | Same (no K-flip) | LOW |
| `qt_slice_viewer.py` | 353, 591 | `_current_slice_index` | (track) | Store display_k | Same | LOW |
| Many tool files | Various | Tool interaction | `GetSlice()` | Read for context | Same | MEDIUM |
| `reference_line.py` | 20–73 | `rl_sort_instances_by_ipp()` | (sort) | IPP-based ordering | Must stay aligned | MEDIUM |
| `_pw_sync.py` | 360–400 | `_do_lock_sync()` | `current_slice` | `GetSlice()` → raw_k | Same | MEDIUM |
| `_pw_sync.py` | 675–788 | `_geometry_instances_for_viewer()` | `current_slice_index` | Domain classification | Stay aligned | MEDIUM |
| Multiple | Various | Diagnostics | Log values | Various slice indices | Update baselines | LOW |

---

## CONCLUSION

This audit has identified **ALL** semantic boundaries for the K-flip formula change:

1. **DisplayGeometry layer (4 functions)** — Must all be updated together
2. **VTK SetSlice/GetSlice boundary** — Raw_k domain, unchanged by formula
3. **Metadata['instances'] indexing** — Must use correct raw_k, unchanged by formula
4. **Sync engine (GeometryAPI)** — Auto-updates via formula functions
5. **Reference lines** — Domain-aware, must stay synchronized
6. **Measurements and tools** — Use GetSlice() raw_k, unchanged semantically
7. **Diagnostic logging** — Baseline values will change

**No breaking boundaries exist IF the formula change is applied consistently to all four conversion functions simultaneously.**

**Critical risk areas:**
- `is_k_flip_active` logic (line 313)
- `k_flip_n_slices` logic (line 318)
- Inverse matrix values after `_recompute()`
- Viewer backends (FAST vs Advanced) remain in separate domains

**Verification strategy:**
- Round-trip test: `display_k_to_raw_k(raw_k_to_display_k(x)) == x` for all x
- Sync test: Cross-viewport LPS mapping with new formula
- Instance lookup test: Verify correct W/L retrieved per slice
- Orientation test: Verify correct anatomical markers per slice

