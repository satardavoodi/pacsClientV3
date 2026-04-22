"""
Sync & reference line methods for PatientWidget.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""


import logging
import numpy as np
import re
import time
from PySide6.QtCore import QTimer, Qt
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import reference_line
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
from modules.zeta_sync import SyncContext, SyncMode, SyncTarget, ijk_to_world
logger = logging.getLogger(__name__)


class _PWSyncMixin:
    """Sync & reference line methods for PatientWidget."""

    def toggle_sync_point(self, enabled: bool):
        """Enable/disable the synced red target point across 2D viewers.
        
        When Lock Sync is active, the sync infrastructure stays alive even
        when the click-to-target interactor is toggled off by other tools.
        Only the interactor style, observers, and cursor are cleaned up so
        that other tools (Ruler, Zoom, Stack, etc.) work normally.
        """
        self._sync_enabled = bool(enabled)
        self.target_mode_enabled = self._sync_enabled
        logger.info(
            "[SYNC-STATE] toggle_sync_point: enabled=%s  lock_sync=%s  sync_mode=%s",
            self._sync_enabled, getattr(self, '_lock_sync_enabled', False),
            "CURSOR" if enabled else "DISABLED",
        )

        if not self._sync_enabled:
            if self._lock_sync_enabled:
                # --- Lock Sync active: fully remove click-to-target interactor ---
                # Remove observers, restore previous style, unset cursor
                # but keep the sync pipeline (viewer map, sync manager) alive
                for vtk_widget in list(self._sync_viewer_map.values()):
                    try:
                        _is_qt = getattr(vtk_widget, '_qt_bridge_active', False)
                        if not _is_qt:
                            # Remove sync event observers so they don't intercept
                            for obs_id in vtk_widget._sync_observer_ids:
                                try:
                                    vtk_widget.interactor.RemoveObserver(obs_id)
                                except Exception:
                                    pass
                            vtk_widget._sync_observer_ids = []
                        vtk_widget._sync_dragging = False
                        vtk_widget._sync_enabled = False

                        if not _is_qt:
                            # Restore the previous interactor style
                            if vtk_widget._sync_prev_style is not None:
                                vtk_widget.interactor.SetInteractorStyle(
                                    vtk_widget._sync_prev_style
                                )
                                vtk_widget._sync_prev_style = None
                            vtk_widget._sync_style = None

                        # Remove the red target cursor
                        vtk_widget._set_target_cursor(False)
                    except Exception:
                        pass
                # Keep _sync_enabled True at patient_widget level for auto-sync
                self._sync_enabled = True
                return

            self.sync_manager.set_mode(SyncMode.DISABLED)
            for vtk_widget in list(self._sync_viewer_map.values()):
                try:
                    vtk_widget.disable_sync_point()
                except Exception:
                    pass
            self._sync_viewer_map.clear()
            self.sync_manager.clear_viewers()
            return

        self.sync_manager.set_mode(SyncMode.CURSOR)
        self._register_sync_viewers()

    def _log_sync_viewer_geometry(self, viewer_id, vtk_widget):
        """Log complete geometry/IOP/IPP/transform info for sync debugging."""
        try:
            viewer = getattr(vtk_widget, 'image_viewer', None)
            if viewer is None:
                return
            is_qt = getattr(vtk_widget, '_qt_bridge_active', False)
            backend_type = "Qt-bridge" if is_qt else "VTK-ImageViewer2"

            # VTK world-space properties
            img = getattr(viewer, 'vtk_image_data', None)
            origin = img.GetOrigin() if img else '?'
            spacing = img.GetSpacing() if img else '?'
            dims = img.GetDimensions() if img else '?'
            try:
                orient_idx = viewer.GetSliceOrientation()
                orient_name = {0: 'YZ(Sag)', 1: 'XZ(Cor)', 2: 'XY(Ax)'}.get(orient_idx, str(orient_idx))
            except Exception:
                orient_name = '?'

            # DICOM metadata IOP/IPP
            metadata = getattr(viewer, 'metadata', {}) or {}
            instances = metadata.get('instances') or []
            n_inst = len(instances)
            iop = ipp_first = ipp_mid = ipp_last = pixel_spacing = rows = cols = sth = sbsi = None
            mid_idx = 0
            if instances:
                f0 = instances[0]
                iop = f0.get('image_orientation_patient')
                ipp_first = f0.get('image_position_patient')
                pixel_spacing = f0.get('pixel_spacing')
                rows = f0.get('rows') or f0.get('Rows')
                cols = f0.get('columns') or f0.get('Columns')
                sth = f0.get('slice_thickness')
                sbsi = f0.get('spacing_between_slices')
                mid_idx = n_inst // 2
                ipp_mid = instances[mid_idx].get('image_position_patient') if mid_idx < n_inst else None
                ipp_last = instances[-1].get('image_position_patient')

            # Orientation classification from IOP
            orient_class = '?'
            if iop and len(iop) == 6:
                _col_dir = np.asarray(iop[0:3], dtype=float)
                _row_dir = np.asarray(iop[3:6], dtype=float)
                _n_iop = np.cross(_col_dir, _row_dir)
                if np.linalg.norm(_n_iop) > 1e-9:
                    orient_class = ['Sagittal', 'Coronal', 'Axial'][int(np.argmax(np.abs(_n_iop)))]

            # ITK direction matrix (patient-to-image transform)
            geom = self._read_itk_geometry(viewer)
            D_itk_str = str(geom['D_itk'].tolist()) if geom else '(unavailable)'

            # Rotate/flip state from Qt viewer
            rotate = flip_h = flip_v = 'N/A'
            qv = getattr(vtk_widget, '_qt_viewer_widget', None)
            if qv is not None:
                rotate = getattr(qv, '_rotation_angle', getattr(qv, 'rotation_angle', '?'))
                flip_h = getattr(qv, '_flip_h', getattr(qv, 'flip_h', '?'))
                flip_v = getattr(qv, '_flip_v', getattr(qv, 'flip_v', '?'))

            logger.info(
                "[SYNC-GEOM] ── viewer=%s  backend=%s  vtk_orient=%s  dicom_orient=%s ──\n"
                "  instances=%d  PixelSpacing=%s  Rows=%s  Cols=%s  SliceThickness=%s  SpacingBetweenSlices=%s\n"
                "  IOP             = %s\n"
                "  IPP[0]          = %s\n"
                "  IPP[%d]         = %s\n"
                "  IPP[-1]         = %s\n"
                "  VTK origin      = %s\n"
                "  VTK spacing     = %s\n"
                "  VTK dims        = %s\n"
                "  ITK DirectionMatrix (row0,row1,row2) = %s\n"
                "  rotate=%s  flip_h=%s  flip_v=%s",
                viewer_id, backend_type, orient_name, orient_class,
                n_inst, pixel_spacing, rows, cols, sth, sbsi,
                iop,
                ipp_first,
                mid_idx, ipp_mid,
                ipp_last,
                origin, spacing, dims,
                D_itk_str,
                rotate, flip_h, flip_v,
            )
        except Exception as _e:
            logger.debug("[SYNC-GEOM] Error logging geometry for %s: %s", viewer_id, _e)

    def _register_sync_viewers(self):
        self._sync_viewer_map.clear()
        self.sync_manager.clear_viewers()

        _registered = 0
        _skipped = 0
        for node in self.lst_nodes_viewer:
            vtk_widget = getattr(node, 'vtk_widget', None)
            if vtk_widget is None or getattr(vtk_widget, 'image_viewer', None) is None:
                _skipped += 1
                continue

            viewer_id = vtk_widget.get_sync_viewer_id()
            self._sync_viewer_map[viewer_id] = vtk_widget

            series_uid = None
            try:
                series_uid = vtk_widget.image_viewer.metadata.get('series', {}).get('series_uid')
            except Exception:
                pass

            context = SyncContext(
                viewer_id=viewer_id,
                target_type=SyncTarget.VIEWER_2D,
                series_uid=series_uid,
                study_uid=self.study_uid
            )
            self.sync_manager.register_viewer(context)
            vtk_widget.enable_sync_point(self.sync_manager, viewer_id=viewer_id)
            self._log_sync_viewer_geometry(viewer_id, vtk_widget)
            _registered += 1

    def _register_sync_viewers_pipeline_only(self):
        """Register sync viewers for Lock Sync without enabling click-to-target
        interactor styles or observers. Only sets up the sync manager pipeline
        so that _auto_sync_on_slice_change can push world positions through."""
        self._sync_viewer_map.clear()
        self.sync_manager.clear_viewers()

        for node in self.lst_nodes_viewer:
            vtk_widget = getattr(node, 'vtk_widget', None)
            if vtk_widget is None or getattr(vtk_widget, 'image_viewer', None) is None:
                continue

            viewer_id = vtk_widget.get_sync_viewer_id()
            self._sync_viewer_map[viewer_id] = vtk_widget

            # Assign sync manager + viewer_id without changing interactor
            vtk_widget._sync_manager = self.sync_manager
            vtk_widget._sync_viewer_id = viewer_id

            series_uid = None
            try:
                series_uid = vtk_widget.image_viewer.metadata.get('series', {}).get('series_uid')
            except Exception:
                pass

            context = SyncContext(
                viewer_id=viewer_id,
                target_type=SyncTarget.VIEWER_2D,
                series_uid=series_uid,
                study_uid=self.study_uid
            )
            self.sync_manager.register_viewer(context)

    def _apply_sync_cursor(self, viewer_id, world_pos):
        vtk_widget = self._sync_viewer_map.get(viewer_id)
        if vtk_widget is None:
            return
        if not self._sync_enabled:
            return

        self._sync_update_token += 1
        token = self._sync_update_token

        viewer = getattr(vtk_widget, 'image_viewer', None)
        orient = viewer.GetSliceOrientation() if viewer else -1
        logger.debug(
            "[SYNC APPLY] viewer=%s orient=%d world_pos=(%.2f, %.2f, %.2f)",
            viewer_id, orient, world_pos[0], world_pos[1], world_pos[2],
        )

        def _apply():
            if not self._sync_enabled:
                return
            if token != self._sync_update_token:
                return
            vtk_widget.apply_sync_point_from_manager(world_pos, adjust_slice=True)

        QTimer.singleShot(self._sync_apply_delay_ms, _apply)

    def set_lock_sync(self, enabled: bool):
        """Enable/disable Lock Sync (auto-sync destination viewer on scroll)."""
        self._lock_sync_enabled = bool(enabled)
        logger.info("[LOCK SYNC] %s", "ENABLED" if self._lock_sync_enabled else "DISABLED")
        # Wire or unwire the slice-changed callback on every VTKWidget
        self._wire_lock_sync_callbacks()

    def _wire_lock_sync_callbacks(self):
        """Set or clear the _on_slice_changed_cb on every VTKWidget."""
        cb = self._auto_sync_on_slice_change if self._lock_sync_enabled else None
        for node in self.lst_nodes_viewer:
            vtk_widget = getattr(node, 'vtk_widget', None)
            if vtk_widget is not None:
                vtk_widget._on_slice_changed_cb = cb

    def _auto_sync_on_slice_change(self, vtk_widget):
        """
        Called after a slice change when Lock Sync is active.
        Computes the world-space center of the current slice in the source viewer,
        then pushes it through the existing sync pipeline so the destination viewer
        navigates to the corresponding location.
        """
        if not self._lock_sync_enabled or not self._sync_enabled:
            return
        # Re-entrancy guard: avoid infinite loop when target viewer's
        # set_slice triggers this callback again
        if self._lock_sync_updating:
            return
        self._lock_sync_updating = True
        try:
            self._do_lock_sync(vtk_widget)
        finally:
            self._lock_sync_updating = False

    def _do_lock_sync(self, vtk_widget):
        """Core Lock Sync logic, called within the re-entrancy guard.

        IMPORTANT: This bypasses sync_manager.notify_cursor_moved() and
        applies directly to target viewers.  The notify path uses
        QTimer.singleShot(0) + token debouncing which drops updates during
        continuous mouse-move streams (Stack drag).  Direct application
        guarantees every slice change is reflected immediately.
        """

        viewer = getattr(vtk_widget, 'image_viewer', None)
        if viewer is None:
            return

        # Find the sync viewer_id for this vtk_widget
        source_id = None
        for vid, vw in self._sync_viewer_map.items():
            if vw is vtk_widget:
                source_id = vid
                break
        if source_id is None:
            # Viewer not registered yet (e.g. series was changed) — re-register
            # Use pipeline-only to avoid setting interactor styles
            self._register_sync_viewers_pipeline_only()
            for vid, vw in self._sync_viewer_map.items():
                if vw is vtk_widget:
                    source_id = vid
                    break
        if source_id is None:
            return

        try:
            img = viewer.vtk_image_data
            if img is None:
                return

            orientation = viewer.GetSliceOrientation()
            current_slice = viewer.GetSlice()
            origin = img.GetOrigin()
            spacing = img.GetSpacing()
            dims = img.GetDimensions()

            # Compute the center of the current slice in world coordinates
            # For each axis: center = origin + (dims/2) * spacing
            # For the slice axis: value = origin + current_slice * spacing
            cx = origin[0] + (dims[0] - 1) * 0.5 * spacing[0]
            cy = origin[1] + (dims[1] - 1) * 0.5 * spacing[1]
            cz = origin[2] + (dims[2] - 1) * 0.5 * spacing[2]

            if orientation == 2:    # Axial (XY) — Z is the slice axis
                cz = origin[2] + current_slice * spacing[2]
            elif orientation == 1:  # Coronal (XZ) — Y is the slice axis
                cy = origin[1] + current_slice * spacing[1]
            else:                   # Sagittal (YZ) — X is the slice axis
                cx = origin[0] + current_slice * spacing[0]

            world_pos = (cx, cy, cz)

            # For Qt/FAST viewers, GetSliceOrientation() always returns 2 (Axial)
            # regardless of the actual series orientation.  The mock VTK spacing[2]
            # is slice_thickness but the normal direction may not be Z.  Instead,
            # compute the true patient-LPS center of the current slice from DICOM
            # IPP/IOP metadata, which is correct for all orientations.
            if getattr(viewer, 'IS_QT_BRIDGE', False):
                try:
                    from modules.viewer.fast.dicom_sync_geometry import image_pixel_to_lps
                    _instances = (viewer.metadata or {}).get('instances') or []
                    if current_slice < len(_instances):
                        _inst = _instances[current_slice]
                        _ipp = _inst.get('image_position_patient')
                        _iop = _inst.get('image_orientation_patient') or []
                        _ps = _inst.get('pixel_spacing') or [1.0, 1.0]
                        _cols = float(_inst.get('columns') or dims[0])
                        _rows = float(_inst.get('rows') or dims[1])
                        if _ipp is not None and len(_iop) >= 6:
                            _P_c = image_pixel_to_lps(
                                _cols / 2.0, _rows / 2.0,
                                np.asarray(_ipp, float), _iop, _ps,
                            )
                            world_pos = (float(_P_c[0]), float(_P_c[1]), float(_P_c[2]))
                            logger.debug(
                                "[LOCK SYNC] Qt source true-LPS: slice=%d "
                                "-> (%.4f, %.4f, %.4f) (was mock-VTK (%.4f, %.4f, %.4f))",
                                current_slice,
                                world_pos[0], world_pos[1], world_pos[2],
                                cx, cy, cz,
                            )
                except Exception as _e:
                    logger.debug("[LOCK SYNC] Qt source LPS fallback: %s", _e)

            logger.debug(
                "[LOCK SYNC] Auto-sync from viewer=%s orient=%d slice=%d → world=(%.2f, %.2f, %.2f)",
                source_id, orientation, current_slice, cx, cy, cz,
            )

            # Show/update the red dot on the source viewer (no slice adjust)
            viewer.set_sync_point(world_pos, adjust_slice=False)

            # --- Direct sync to all target viewers (no QTimer debounce) ---
            self.sync_manager.set_active_point(world_pos)
            _sync_target_count = 0
            _sync_map_fail_count = 0
            for target_vid, target_vw in self._sync_viewer_map.items():
                if target_vid == source_id:
                    continue
                # Map world position from source to target coordinate space
                mapped_world = world_pos
                if hasattr(self, '_map_sync_cursor') and self._map_sync_cursor is not None:
                    mapped = self._map_sync_cursor(source_id, target_vid, world_pos)
                    if mapped is None:
                        _sync_map_fail_count += 1
                        # Source point is outside the target stack (or unmappable).
                        # Hide the stale sync overlay so it doesn't mislead the user.
                        _tgt_iv = getattr(target_vw, 'image_viewer', None)
                        if _tgt_iv is not None:
                            try:
                                _tgt_iv.hide_sync_point()
                            except Exception:
                                pass
                        continue
                    mapped_world = mapped
                _sync_target_count += 1
                # Apply directly to target viewer (bypass QTimer debounce)
                target_viewer = getattr(target_vw, 'image_viewer', None)
                if target_viewer is not None:
                    target_viewer.set_sync_point(mapped_world, adjust_slice=True)
                    # Keep target slider in sync so Stack drag works
                    # correctly when user switches to this viewer
                    new_slice = target_viewer.GetSlice()
                    target_slider = getattr(target_vw, 'slider', None)
                    if target_slider is not None:
                        target_slider.blockSignals(True)
                        target_slider.setValue(new_slice)
                        target_slider.blockSignals(False)

            # v2.2.3.3.4: Debounced reference line update after lock sync.
            # Target viewers have moved to new slices, so the source plane's
            # intersection with each target quad has changed.  Without this,
            # reference lines stayed stale during the entire lock-sync drag.
            # The 80ms debounce from _schedule_reference_line_update()
            # prevents expensive Render-per-target from blocking the drag.
            if _sync_target_count == 0 and _sync_map_fail_count > 0:
                logger.info("[SYNC-DIAG] _do_lock_sync: ALL %d target(s) FAILED mapping (IPP/IOP likely None)", _sync_map_fail_count)
            self._schedule_reference_line_update()

        except Exception as e:
            logger.warning("[LOCK SYNC] Auto-sync error: %s", e)

    @staticmethod
    def _read_itk_geometry(viewer):
        """
        Read original ITK geometry from the pre-reslice image's field data.

        Returns dict with:
          'D_itk'         – np.ndarray (3,3)  original ITK direction
          'spacing'       – np.ndarray (3,)   original ITK spacing
          'dims'          – np.ndarray (3,)   original ITK dimensions (int)
          'extent_y'      – float             (itk_dims_y - 1) * itk_sp_y
          'extent_y_disp' – float             (display_dims_y - 1) * display_sp_y
          'origin'        – np.ndarray (3,)   pre-reslice image origin (= ITK origin)
          'source'        – str               'field_data' or 'image_fallback'
        or None if direction data is unavailable.
        """
        reslice = getattr(viewer, 'image_reslice', None)
        if reslice is None:
            return None
        original_img = getattr(reslice, 'vtk_image_data', None)
        if original_img is None:
            return None
        fd = original_img.GetFieldData()
        if fd is None:
            return None

        # --- Direction matrix (required) ---
        dir_arr = fd.GetArray("DirectionMatrix")
        if dir_arr is None or dir_arr.GetNumberOfTuples() < 16:
            return None
        D = np.zeros((3, 3))
        for r in range(3):
            for c in range(3):
                D[r, c] = dir_arr.GetValue(r * 4 + c)
        # Un-negate row 1 → original ITK direction
        D[1, :] = -D[1, :]

        source = 'field_data'

        # --- Pre-reslice origin (= ITK origin, set in convert_itk2vtk) ---
        pre_origin = np.array(original_img.GetOrigin(), dtype=float)

        # --- Spacing (prefer stored ITK, fallback to image) ---
        sp_arr = fd.GetArray("ITKSpacing")
        if sp_arr is not None and sp_arr.GetNumberOfTuples() >= 3:
            spacing = np.array([sp_arr.GetValue(i) for i in range(3)])
        else:
            spacing = np.array(original_img.GetSpacing())
            source = 'image_fallback'

        # --- Dimensions (prefer stored ITK, fallback to image) ---
        dm_arr = fd.GetArray("ITKDimensions")
        if dm_arr is not None and dm_arr.GetNumberOfTuples() >= 3:
            dims = np.array([int(dm_arr.GetValue(i)) for i in range(3)])
        else:
            dims = np.array(original_img.GetDimensions())
            source = 'image_fallback'

        extent_y_itk = (dims[1] - 1) * spacing[1]

        # Display (post-upsample) extent — needed because vtkImageResample
        # changes dims/spacing and (display_dims-1)*display_sp != extent_y_itk.
        disp_sp = np.array(original_img.GetSpacing(), dtype=float)
        disp_dims = np.array(original_img.GetDimensions(), dtype=float)
        extent_y_disp = (disp_dims[1] - 1) * disp_sp[1]
        # Guard: if display extent is essentially zero, fall back to ITK
        if extent_y_disp < 1e-9:
            extent_y_disp = extent_y_itk

        return {
            'D_itk': D,
            'spacing': spacing,
            'dims': dims,
            'extent_y': extent_y_itk,
            'extent_y_disp': extent_y_disp,
            'origin': pre_origin,
            'source': source,
        }

    @staticmethod
    def _vtk_world_to_patient(world_pos, origin, extent_y_itk, D_itk,
                               extent_y_disp=None):
        """
        Convert VTK post-Y-flip world position to DICOM patient (LPS+) coordinates.

        The VTK picker returns simple origin + ijk * spacing (no direction).
        We undo the Y-flip and apply the ITK direction matrix.

        Math:
          delta       = world - origin
          frac_y      = delta[1] / extent_y_disp
          s_y         = extent_y_itk * (1 - frac_y)   # ITK physical offset (un-flipped)
          s           = (delta[0], s_y, delta[2])
          patient     = origin + D_itk @ s
        """
        o = np.array(origin, dtype=float)
        delta = np.array(world_pos, dtype=float) - o

        # Undo Y-flip using fractional position
        ey_d = extent_y_disp if extent_y_disp is not None else extent_y_itk
        if ey_d > 1e-9:
            frac_y = delta[1] / ey_d
        else:
            frac_y = 0.0
        s_y = extent_y_itk * (1.0 - frac_y)

        s = np.array([delta[0], s_y, delta[2]], dtype=float)

        # Apply direction → patient LPS+
        patient = o + D_itk @ s
        return patient

    @staticmethod
    def _patient_to_vtk_world_clamped(patient_pos, origin,
                                       spacing_itk, dims_itk, extent_y_itk,
                                       D_itk, extent_y_disp=None):
        """
        Convert DICOM patient (LPS+) to VTK world, clamped to the volume.

        Returns (vtk_world_tuple, ijk_itk_raw, was_outside).
          vtk_world_tuple - (float, float, float) VTK world position
          ijk_itk_raw     - np.ndarray(3) continuous ITK voxel indices (before clamp)
          was_outside     - bool  True if any index was outside [0, dim-1]

        The Y component is converted from ITK offset to display offset
        using the fractional position (matching the display extent).
        """
        o = np.array(origin, dtype=float)
        sp = np.array(spacing_itk, dtype=float)
        dm = np.array(dims_itk, dtype=float)

        D_inv = np.linalg.inv(D_itk)
        s = D_inv @ (np.array(patient_pos, dtype=float) - o)

        # ITK continuous voxel indices
        ijk_raw = s / sp

        # Clamp to valid range
        ijk_clamped = np.clip(ijk_raw, 0, dm - 1)
        was_outside = not np.allclose(ijk_raw, ijk_clamped, atol=0.5)

        # Clamped ITK voxel → physical offset → VTK world
        s_clamped = ijk_clamped * sp

        ey_d = extent_y_disp if extent_y_disp is not None else extent_y_itk
        if extent_y_itk > 1e-9:
            frac_y = s_clamped[1] / extent_y_itk       # fraction along ITK Y
        else:
            frac_y = 0.0
        delta_y_display = ey_d * (1.0 - frac_y)        # display Y offset (re-flip)

        delta = np.array([s_clamped[0], delta_y_display, s_clamped[2]])

        vtk_world = o + delta

        return (
            (float(vtk_world[0]), float(vtk_world[1]), float(vtk_world[2])),
            ijk_raw,
            was_outside,
        )

    @staticmethod
    def _ensure_instances_sorted_for_geometry(viewer):
        """Ensure metadata slice order matches geometric slice order."""
        try:
            metadata = getattr(viewer, "metadata", None)
            if not isinstance(metadata, dict):
                return
            if metadata.get("_instances_geometry_sorted", False):
                return
            instances = metadata.get("instances")
            if not isinstance(instances, list) or len(instances) <= 1:
                metadata["_instances_geometry_sorted"] = True
                return
            metadata["instances"] = reference_line.rl_sort_instances_by_ipp(instances)
            metadata["_instances_geometry_sorted"] = True
        except Exception:
            pass

    @staticmethod
    def _map_sync_dicom(source_viewer, target_viewer, world_pos):
        """
        Map a world/patient-LPS position from source to target viewer using
        DICOM IOP/IPP metadata.

        IMPORTANT MODE CONTRACT
        -----------------------
        - UX/UI intent is shared across backends (same user-facing sync behavior).
        - Geometry implementation is backend-specific and MUST remain split:
            * FAST(Qt/pydicom) target: pure-DICOM mapping with explicit validity
              classification (slab/in-plane/final_valid) and explicit rejection.
            * ADVANCED(VTK) target: stable legacy VTK/reference-line path is kept
              unchanged in semantics; do not force FAST rejection rules onto it.

        This separation preserves stable Advanced sync while fixing FAST-specific
        projection/clamp validity issues introduced after backend split.

        Returns (world_target_or_none, ijk_diag, was_outside, rejection_reason) or None.

        Qt target pipeline (no VTK world-space):
          source patient-LPS
            -> find_closest_slice (IPP projection)
            -> project_lps_onto_plane
            -> lps_to_image_pixel (DICOM pixel_spacing)
            -> return P_proj (patient-LPS on target plane)

        VTK target pipeline (unchanged):
          VTK world (source) -> display index -> flip-Y -> true LPS
            -> target plane projection -> k_tgt
            -> flip-Y on target -> index -> VTK world (target)
        """
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import reference_line
        from modules.viewer.fast.dicom_sync_geometry import (
            project_lps_to_target, compute_roundtrip_error_mm,
        )
        _PWSyncMixin._ensure_instances_sorted_for_geometry(source_viewer)
        _PWSyncMixin._ensure_instances_sorted_for_geometry(target_viewer)

        # ---- source geometry ----
        src_img   = source_viewer.vtk_image_data
        src_orig  = np.asarray(src_img.GetOrigin(),     dtype=float)
        src_sp    = np.asarray(src_img.GetSpacing(),     dtype=float)
        src_dims  = np.asarray(src_img.GetDimensions(),  dtype=int)
        _src_is_qt = getattr(source_viewer, 'IS_QT_BRIDGE', False)

        if _src_is_qt:
            # Qt source pick_world_point() already returns true patient-LPS.
            # Do NOT reinterpret this as VTK-world/index space.
            P_lps = np.asarray(world_pos, dtype=float)
            try:
                k_src = int(round(float(source_viewer.GetSlice())))
            except Exception:
                k_src = 0
            k_src = int(max(0, min(k_src, src_dims[2] - 1)))
        else:
            # VTK source: convert VTK-world click -> source display index.
            idx_src = (np.asarray(world_pos, dtype=float) - src_orig) / src_sp
            k_src   = int(round(float(np.clip(idx_src[2], 0, src_dims[2] - 1))))

        # DICOM metadata for this source slice
        try:
            s_inst = source_viewer.metadata['instances'][k_src]
            s_iop  = s_inst['image_orientation_patient']
            s_ipp  = np.asarray(s_inst['image_position_patient'], dtype=float)
            if s_iop is None or s_ipp is None:
                logger.info(
                    "[SYNC-DIAG] _map_sync_dicom ABORT: source slice %d has IOP=%s IPP=%s (total instances=%d)",
                    k_src, s_iop is not None, s_ipp is not None,
                    len((source_viewer.metadata or {}).get('instances') or []),
                )
                return None
        except (KeyError, IndexError, TypeError) as e:
            logger.info("[SYNC-DIAG] _map_sync_dicom ABORT: source metadata error at slice %d: %s", k_src, e)
            return None

        col_s = np.asarray(s_iop[0:3], dtype=float)     # IOP row  = display col dir
        row_s = np.asarray(s_iop[3:6], dtype=float)     # IOP col  = display row dir

        if not _src_is_qt:
            # Build flipped-LPS point from display index, then undo flip-Y -> true LPS
            P_flip_s = (s_ipp
                        + idx_src[0] * src_sp[0] * col_s
                        + idx_src[1] * src_sp[1] * row_s)

            center_s = reference_line.rl_center_of_slice(
                src_dims[1], src_dims[0], s_ipp, row_s, col_s,
                src_sp[1], src_sp[0])

            # VTK viewers have Y-up display -> display index produces "flipped"
            # LPS. Undo the flip to get true LPS.
            P_lps = reference_line.rl_apply_flip_y_in_plane(
                P_flip_s, center_s, col_s, row_s)

        # ── Diagnostic: source geometry ──────────────────────────────────────────────────
        _n_s = np.cross(col_s, row_s)
        _orient_src = ['Sagittal', 'Coronal', 'Axial'][int(np.argmax(np.abs(_n_s)))]
        logger.info(
            "[SYNC-MAP DICOM] SOURCE: viewer=%s  k_src=%d  is_qt=%s  orient_class=%s\n"
            "  world_pos_in = (%.4f, %.4f, %.4f)\n"
            "  IOP = %s\n"
            "  IPP = %s\n"
            "  col_dir(IOP[0:3]) = (%.4f, %.4f, %.4f)\n"
            "  row_dir(IOP[3:6]) = (%.4f, %.4f, %.4f)\n"
            "  P_lps = (%.4f, %.4f, %.4f)",
            getattr(source_viewer, '_sync_viewer_id', '?'), k_src, _src_is_qt, _orient_src,
            world_pos[0], world_pos[1], world_pos[2],
            list(s_iop), list(s_ipp),
            col_s[0], col_s[1], col_s[2],
            row_s[0], row_s[1], row_s[2],
            P_lps[0], P_lps[1], P_lps[2],
        )

        # ── Route: Qt target → pure-DICOM geometry engine ────────────────────────
        _tgt_is_qt = getattr(target_viewer, 'IS_QT_BRIDGE', False)
        _tgt_id = getattr(target_viewer, '_sync_viewer_id', '?')

        if _tgt_is_qt:
            t_instances = (target_viewer.metadata or {}).get('instances') or []
            if not t_instances:
                logger.info("[FAST-SYNC] ABORT: target=%s has no instances", _tgt_id)
                return None

            # Get prev_k for hysteresis (stored on target viewer)
            _prev_k = getattr(target_viewer, '_sync_prev_k_tgt', None)
            _HYSTERESIS_MM = 0.0  # off by default; set > 0 to prevent flicker near slice boundary

            res = project_lps_to_target(P_lps, t_instances, prev_k=_prev_k, hysteresis_mm=_HYSTERESIS_MM)
            if res is None:
                logger.info("[FAST-SYNC] ABORT: project_lps_to_target returned None for target=%s", _tgt_id)
                return None

            # Store k_tgt for next-call hysteresis
            target_viewer._sync_prev_k_tgt = res.k_tgt

            _t_inst0 = t_instances[0]
            _t_iop = _t_inst0.get('image_orientation_patient') or []
            _t_ipp0 = _t_inst0.get('image_position_patient')
            _t_orient = ['Sagittal', 'Coronal', 'Axial'][int(np.argmax(np.abs(res.n_t)))] if res.n_t is not None else '?'

            logger.info(
                "[FAST-SYNC-TRACE] SOURCE → TARGET\n"
                "  src_viewer=%s  k_src=%d  P_lps=(%.4f,%.4f,%.4f)\n"
                "  tgt_viewer=%s  orient=%s  k_float=%.3f  k_tgt=%d\n"
                "  P_proj  =(%.4f,%.4f,%.4f)  dp=%.4f mm  world_delta_mm=%.4f\n"
                "  col_idx=%.2f  row_idx=%.2f  in_bounds=%s  outside=%s",
                getattr(source_viewer, '_sync_viewer_id', '?'), k_src,
                P_lps[0], P_lps[1], P_lps[2],
                _tgt_id, _t_orient, res.k_float, res.k_tgt,
                res.P_proj[0], res.P_proj[1], res.P_proj[2], res.dp, res.world_delta_mm,
                res.col_idx, res.row_idx, res.in_bounds, res.outside_reason or 'none',
            )

            logger.info(
                "[FAST-SYNC-SLICE] k_float=%.3f  prev_k=%s  new_k_tgt=%d"
                "  hysteresis_mm=%.1f  rounding=nearest",
                res.k_float, _prev_k, res.k_tgt, _HYSTERESIS_MM,
            )

            _ps = _t_inst0.get('pixel_spacing') or [1.0, 1.0]
            _col_dir = _t_iop[0:3] if len(_t_iop) >= 6 else [1, 0, 0]
            _row_dir = _t_iop[3:6] if len(_t_iop) >= 6 else [0, 1, 0]
            logger.info(
                "[FAST-SYNC-INPLANE] row_dir=%s  col_dir=%s\n"
                "  pixel_spacing=%s  ipp_k=(%.4f,%.4f,%.4f)\n"
                "  col_idx=%.2f  row_idx=%.2f  in_bounds=%s  outside=%s",
                list(_col_dir), list(_row_dir),
                list(_ps),
                res.ipp_k[0], res.ipp_k[1], res.ipp_k[2],
                res.col_idx, res.row_idx, res.in_bounds, res.outside_reason or 'none',
            )

            # Roundtrip error measurement
            _err_mm, _err_px = compute_roundtrip_error_mm(P_lps, t_instances)
            logger.info(
                "[FAST-SYNC-ERROR] patient_error_mm=%.6f  inplane_error_px=%.6f"
                "  slice_plane_residual_mm=%.4f",
                _err_mm, _err_px, res.dp,
            )

            logger.info(
                "[FAST-SYNC-VALIDATION] source_P_lps=(%.4f,%.4f,%.4f) "
                "slice_count=%d k_min=%d k_max=%d "
                "k_float_before_clamp=%.3f k_tgt_after_clamp=%d clamp_occurred=%s "
                "signed_through_plane_distance_mm=%.4f world_delta_mm=%.4f "
                "slab_valid=%s inplane_valid=%s final_valid_sync_point=%s "
                "rejection_reason=%s "
                "stack_is_sparse=%s typical_spacing_mm=%.3f max_gap_mm=%.3f "
                "min_dist_to_slice_mm=%.3f between_groups=%s "
                "through_plane_valid=%s slice_thickness_mm=%.3f",
                P_lps[0], P_lps[1], P_lps[2],
                res.slice_count, res.k_min, res.k_max,
                res.k_float, res.k_tgt_after_clamp, res.clamp_occurred,
                res.through_plane_distance_mm, res.world_delta_mm,
                res.slab_valid, res.inplane_valid, res.final_valid_sync_point,
                res.rejection_reason,
                res.stack_is_sparse, res.typical_stack_spacing_mm, res.max_stack_gap_mm,
                res.min_distance_to_slice_mm, res.between_groups,
                res.through_plane_valid, res.slice_thickness_mm,
            )

            if not res.final_valid_sync_point:
                # FAST-only policy: invalid correspondences are explicitly rejected.
                # Keep this policy scoped to Qt/FAST targets only; Advanced(VTK)
                # path intentionally preserves stable legacy behavior.
                logger.info(
                    "[FAST-SYNC-REJECT] target=%s reason=%s "
                    "slab_valid=%s inplane_valid=%s",
                    _tgt_id, res.rejection_reason,
                    res.slab_valid, res.inplane_valid,
                )
                ijk_diag = np.array([res.col_idx, res.row_idx, res.k_float])
                return (None, ijk_diag, True, res.rejection_reason)

            # Return patient-LPS P_proj — set_sync_point uses patient_xyz_to_image_xy
            ijk_diag = np.array([res.col_idx, res.row_idx, res.k_float])
            return (
                (float(res.P_proj[0]), float(res.P_proj[1]), float(res.P_proj[2])),
                ijk_diag,
                not res.final_valid_sync_point,
                res.rejection_reason,
            )

        # ══════════════════════════════════════════════════════════════════════════
        # ── Route: Advanced/VTK target → reference_line flip-Y path ─────────────
        #    DO NOT merge with the FAST/Qt path above.
        # ══════════════════════════════════════════════════════════════════════════
        #
        # v2.3.7 (2026-04-22): reverted to the v2.3.1 implementation after a
        # short-lived rewrite that used project_lps_to_target + axis-aligned
        # Y-flip produced visible in-plane drift on oblique MR. The user
        # confirmed the v2.3.1 reference_line path was accurate on the same
        # studies, so this is the authoritative Advanced VTK-target mapping.
        #
        # SPACING CONVENTION (must match manage_reference_line):
        #   rl_lps_to_target_index(P, ipp, col, row, sx, sy, k) computes:
        #     I[0] = dot(P - ipp, col) / sx
        #     I[1] = dot(P - ipp, row) / sy
        #   Then vtk_t = tgt_orig + tgt_sp * I, so:
        #     vtk_t[0] = tgt_orig[0] + tgt_sp[0] * dot(...) / sx
        #   For physical correctness (= tgt_orig[0] + dot(...)), sx MUST equal
        #   tgt_sp[0].  Using itk_sp (original DICOM spacing) while multiplying
        #   by tgt_sp introduces a tgt_sp/itk_sp scale error when CT upsampling
        #   is active — this was the v1.09.1 regression.
        #   manage_reference_line uses sp[0] = tgt_sp[0] consistently (correct).
        #
        # Pipeline:
        #   n_t      = cross(row_t, col_t)                 (slice normal, LPS)
        #   ds       = dot(IPP_1 - IPP_0, n_t)             (slice spacing)
        #   k_float  = dot(P_lps - IPP_0, n_t) / ds
        #   k_tgt    = round(k_float) clamped to [0, n_slices-1]
        #   P_proj   = P_lps − dp · n_t                    (project onto plane)
        #   P_flip_t = rl_apply_flip_y_in_plane(P_proj)    (VTK Y-flip pivot)
        #   I_t      = rl_lps_to_target_index(P_flip_t, tgt_sp)  ← VTK display spacing
        #   vtk_t    = tgt_orig + tgt_sp * I_t             (VTK world for sphere)
        #
        # This is the exact same coordinate path as reference_line.py, which
        # guarantees the sync dot lies on the reference line drawn by the
        # ref-line overlay. See docs/pipelines/IMAGE_PIPELINE_REFERENCE.md
        # §9 "Tier 1 — DICOM IOP/IPP (primary, v1.09.5)".
        tgt_img   = target_viewer.vtk_image_data
        tgt_orig  = np.asarray(tgt_img.GetOrigin(),     dtype=float)
        tgt_sp    = np.asarray(tgt_img.GetSpacing(),     dtype=float)
        tgt_dims  = np.asarray(tgt_img.GetDimensions(),  dtype=int)
        n_slices  = int(tgt_dims[2])

        # Read original ITK spacing from field data (NOT post-upsample spacing)
        itk_sp_arr = tgt_img.GetFieldData().GetArray('ITKSpacing')
        if itk_sp_arr is not None:
            itk_sp = np.array([itk_sp_arr.GetValue(i) for i in range(3)], dtype=float)
        else:
            itk_sp = tgt_sp  # Fallback if field data not found

        try:
            t0_inst = target_viewer.metadata['instances'][0]
            t_iop   = t0_inst['image_orientation_patient']
            ipp_0   = np.asarray(t0_inst['image_position_patient'], dtype=float)
            if t_iop is None or ipp_0 is None:
                logger.info(
                    "[SYNC-DIAG] _map_sync_dicom ABORT: target viewer=%s slice 0 has IOP=%s IPP=%s",
                    _tgt_id, t_iop is not None, ipp_0 is not None,
                )
                return None
            col_t = np.asarray(t_iop[0:3], dtype=float)
            row_t = np.asarray(t_iop[3:6], dtype=float)
            n_t   = np.cross(row_t, col_t)
            n_len = np.linalg.norm(n_t)
            if n_len < 1e-12:
                return None
            n_t /= n_len

            if n_slices > 1:
                t1_inst = target_viewer.metadata['instances'][1]
                ipp_1   = np.asarray(t1_inst['image_position_patient'], dtype=float)
                ds      = float(np.dot(ipp_1 - ipp_0, n_t))
            else:
                ds = float(tgt_sp[2])
        except (KeyError, IndexError, TypeError):
            return None

        _n_t_class = ['Sagittal', 'Coronal', 'Axial'][int(np.argmax(np.abs(n_t)))]
        logger.info(
            "[SYNC-MAP DICOM] TARGET (VTK): viewer=%s  n_slices=%d  orient=%s\n"
            "  IOP=%s  IPP[0]=%s  n_t=(%.4f,%.4f,%.4f)  ds=%.4f\n"
            "  spacing_dicom=%.4f,%.4f  spacing_vtk=%.4f,%.4f  (upsample check)",
            _tgt_id, n_slices, _n_t_class,
            list(t_iop), list(ipp_0),
            n_t[0], n_t[1], n_t[2], ds,
            float(itk_sp[0]), float(itk_sp[1]), float(tgt_sp[0]), float(tgt_sp[1]),
        )

        # Closest target slice
        d0 = float(np.dot(P_lps - ipp_0, n_t))
        k_float = d0 / ds if abs(ds) > 1e-9 else 0.0
        k_tgt = int(round(k_float))
        was_outside = k_tgt < 0 or k_tgt >= n_slices
        k_tgt = max(0, min(k_tgt, n_slices - 1))

        logger.info(
            "[SYNC-MAP DICOM] PROJECTION (VTK): d0=%.4f  k_float=%.3f  k_tgt=%d  was_outside=%s",
            d0, k_float, k_tgt, was_outside,
        )

        # IPP for chosen target slice
        try:
            tk_inst = target_viewer.metadata['instances'][k_tgt]
            ipp_k   = np.asarray(tk_inst['image_position_patient'], dtype=float)
        except (KeyError, IndexError, TypeError):
            ipp_k = ipp_0 + k_tgt * ds * n_t

        # Project LPS onto target plane
        dp     = float(np.dot(P_lps - ipp_k, n_t))
        P_proj = P_lps - dp * n_t

        # Flip-Y for VTK display convention
        center_t = reference_line.rl_center_of_slice(
            tgt_dims[1], tgt_dims[0], ipp_k, row_t, col_t,
            tgt_sp[1], tgt_sp[0])
        P_flip_t = reference_line.rl_apply_flip_y_in_plane(
            P_proj, center_t, col_t, row_t)

        # LPS → target VTK display index.
        # Use VTK display spacing (tgt_sp), matching manage_reference_line convention.
        # rl_lps_to_target_index divides by sx/sy to get display pixel indices;
        # vtk_t = tgt_orig + tgt_sp * I_t requires those indices to be in tgt_sp units.
        # itk_sp (original DICOM spacing) is kept for the upsample-check log below only.
        I_t = reference_line.rl_lps_to_target_index(
            P_flip_t, ipp_k, col_t, row_t,
            tgt_sp[0], tgt_sp[1], k_tgt)

        vtk_t = tgt_orig + tgt_sp * I_t

        logger.info(
            "[SYNC-MAP DICOM] RESULT (VTK): I_t=(%.2f,%.2f)  vtk_world=(%.4f,%.4f,%.4f)",
            I_t[0], I_t[1], vtk_t[0], vtk_t[1], vtk_t[2],
        )

        ijk_diag = np.array([I_t[0], I_t[1], k_float])
        return (
            (float(vtk_t[0]), float(vtk_t[1]), float(vtk_t[2])),
            ijk_diag,
            was_outside,
            'none' if not was_outside else 'out_of_stack',
        )

    def _hide_sync_cursor(self, viewer_id: str) -> None:
        """Hide the stale sync-point overlay on the target viewer.

        Called by SyncManager when _map_cursor returns None (rejection —
        e.g., the source point is outside the target stack).  Without this,
        the last valid sync overlay lingers at the wrong position.

        Safe to call on both Qt (QtViewerBridge.hide_sync_point) and VTK
        (ImageViewer2D.hide_sync_point) viewers.
        """
        vtk_widget = self._sync_viewer_map.get(viewer_id)
        if vtk_widget is None:
            return
        try:
            image_viewer = getattr(vtk_widget, 'image_viewer', None)
            if image_viewer is not None:
                image_viewer.hide_sync_point()
        except Exception:
            pass

    def _map_sync_cursor(self, source_viewer_id, target_viewer_id, world_pos):
        """
        Map a world position from source viewer to target viewer.

        Primary strategy: DICOM IOP/IPP metadata (same path as
        reference_line.py) – guarantees the sync dot lies on the
        reference line.

        Fallback 1: ITK direction matrix from field data.
        Fallback 2: Fractional position mapping.
        """
        if not self._sync_enabled:
            return None

        source_widget = self._sync_viewer_map.get(source_viewer_id)
        target_widget = self._sync_viewer_map.get(target_viewer_id)
        if source_widget is None or target_widget is None:
            return None

        source_viewer = getattr(source_widget, 'image_viewer', None)
        target_viewer = getattr(target_widget, 'image_viewer', None)
        if source_viewer is None or target_viewer is None:
            return None

        imageA = getattr(source_viewer, 'vtk_image_data', None)
        imageB = getattr(target_viewer, 'vtk_image_data', None)
        if imageA is None or imageB is None:
            return None

        try:
            orientA = source_viewer.GetSliceOrientation()  # 0=YZ, 1=XZ, 2=XY
            orientB = target_viewer.GetSliceOrientation()

            # Read original ITK geometry for logging / fallback
            geom_A = self._read_itk_geometry(source_viewer)
            geom_B = self._read_itk_geometry(target_viewer)

            originA = geom_A['origin'] if geom_A is not None else np.asarray(imageA.GetOrigin())
            originB = geom_B['origin'] if geom_B is not None else np.asarray(imageB.GetOrigin())

            # Log geometry once per viewer pair
            log_key = (source_viewer_id, target_viewer_id)
            if log_key not in self._sync_orientation_logged:
                _spA = geom_A['spacing'] if geom_A else imageA.GetSpacing()
                _dmA = geom_A['dims'] if geom_A else imageA.GetDimensions()
                _spB = geom_B['spacing'] if geom_B else imageB.GetSpacing()
                _dmB = geom_B['dims'] if geom_B else imageB.GetDimensions()
                _dspA = imageA.GetSpacing()
                _dspB = imageB.GetSpacing()
                _srcA = geom_A.get('source', '?') if geom_A else 'none'
                _srcB = geom_B.get('source', '?') if geom_B else 'none'
                _eyA = geom_A['extent_y'] if geom_A else 'N/A'
                _eyB = geom_B['extent_y'] if geom_B else 'N/A'
                _eydA = f"{geom_A['extent_y_disp']:.2f}" if geom_A else 'N/A'
                _eydB = f"{geom_B['extent_y_disp']:.2f}" if geom_B else 'N/A'
                logger.debug(
                    "[SYNC MAP] Pair: %s(orient=%d) -> %s(orient=%d)\n"
                    "  imageA: origin=(%.2f,%.2f,%.2f) ITK_sp=(%s) ITK_dims=(%s) "
                    "extent_y_itk=%s extent_y_disp=%s src=%s\n"
                    "  imageB: origin=(%.2f,%.2f,%.2f) ITK_sp=(%s) ITK_dims=(%s) "
                    "extent_y_itk=%s extent_y_disp=%s src=%s\n"
                    "  same_object=%s",
                    source_viewer_id, orientA, target_viewer_id, orientB,
                    originA[0], originA[1], originA[2], _spA, _dmA, _eyA, _eydA, _srcA,
                    originB[0], originB[1], originB[2], _spB, _dmB, _eyB, _eydB, _srcB,
                    imageA is imageB,
                )
                self._sync_orientation_logged.add(log_key)

            # ---------------------------------------------------------------
            # Same VTK object → pass through (same coordinate space)
            # ---------------------------------------------------------------
            if imageA is imageB:
                return world_pos

            # ---------------------------------------------------------------
            # PRIMARY: DICOM IOP/IPP mapping (same as reference_line.py)
            # ---------------------------------------------------------------
            dicom_result = self._map_sync_dicom(source_viewer, target_viewer, world_pos)
            if dicom_result is not None:
                mapped, ijk_diag, was_outside, rejection_reason = dicom_result
                if mapped is None:
                    logger.debug(
                        "[SYNC MAP DICOM] %s->%s rejected: reason=%s slice_float=%.2f",
                        source_viewer_id, target_viewer_id, rejection_reason, ijk_diag[2],
                    )
                    return None
                outside_tag = ""
                if was_outside:
                    outside_tag = (
                        f" OUT_OF_BOUNDS k_float={ijk_diag[2]:.1f}"
                        f" valid=[0..{int(target_viewer.vtk_image_data.GetDimensions()[2])-1}]"
                    )
                logger.debug(
                    "[SYNC MAP DICOM] %s->%s: vtk_world=(%.2f,%.2f,%.2f) "
                    "-> mapped=(%.2f,%.2f,%.2f) slice_float=%.2f reason=%s%s",
                    source_viewer_id, target_viewer_id,
                    world_pos[0], world_pos[1], world_pos[2],
                    mapped[0], mapped[1], mapped[2],
                    ijk_diag[2], rejection_reason, outside_tag,
                )
                return mapped

            # ---------------------------------------------------------------
            # FALLBACK 1: ITK direction matrix from field data
            # ---------------------------------------------------------------
            if geom_A is not None and geom_B is not None:
                slice_axis = orientA
                half_slice = imageA.GetSpacing()[slice_axis] / 2.0
                adjusted = list(world_pos)
                adjusted[slice_axis] += half_slice

                patient = self._vtk_world_to_patient(
                    adjusted, originA,
                    geom_A['extent_y'], geom_A['D_itk'],
                    extent_y_disp=geom_A['extent_y_disp'],
                )

                mapped, ijk_raw, was_outside = self._patient_to_vtk_world_clamped(
                    patient, originB,
                    geom_B['spacing'], geom_B['dims'], geom_B['extent_y'],
                    geom_B['D_itk'],
                    extent_y_disp=geom_B['extent_y_disp'],
                )

                outside_tag = ""
                if was_outside:
                    outside_tag = (
                        f" OUT_OF_BOUNDS ijk_raw=({ijk_raw[0]:.1f},{ijk_raw[1]:.1f},{ijk_raw[2]:.1f})"
                        f" valid=[0..{geom_B['dims'][0]-1}, 0..{geom_B['dims'][1]-1}, 0..{geom_B['dims'][2]-1}]"
                    )

                logger.debug(
                    "[SYNC MAP ITK] %s->%s: vtk_world=(%.2f,%.2f,%.2f) "
                    "adj[%d]+=%.3f -> patient=(%.2f,%.2f,%.2f) "
                    "-> mapped=(%.2f,%.2f,%.2f)%s",
                    source_viewer_id, target_viewer_id,
                    world_pos[0], world_pos[1], world_pos[2],
                    slice_axis, half_slice,
                    patient[0], patient[1], patient[2],
                    mapped[0], mapped[1], mapped[2], outside_tag,
                )
                return mapped

            # ---------------------------------------------------------------
            # FALLBACK 2: fractional mapping (no direction data available)
            # ---------------------------------------------------------------
            spacingA = imageA.GetSpacing()
            dimsA = imageA.GetDimensions()
            spacingB = imageB.GetSpacing()
            dimsB = imageB.GetDimensions()

            mapped = list(world_pos)
            fracs = [0.0, 0.0, 0.0]
            for axis in range(3):
                extentA = (dimsA[axis] - 1) * spacingA[axis]
                extentB = (dimsB[axis] - 1) * spacingB[axis]
                if extentA > 1e-9:
                    frac = (world_pos[axis] - originA[axis]) / extentA
                else:
                    frac = 0.0
                fracs[axis] = frac
                mapped[axis] = originB[axis] + frac * extentB

            logger.debug(
                "[SYNC MAP FRAC] %s->%s: world=(%.2f,%.2f,%.2f) "
                "frac=(%.4f,%.4f,%.4f) -> mapped=(%.2f,%.2f,%.2f)",
                source_viewer_id, target_viewer_id,
                world_pos[0], world_pos[1], world_pos[2],
                fracs[0], fracs[1], fracs[2],
                mapped[0], mapped[1], mapped[2],
            )
            return tuple(mapped)

        except Exception as e:
            logger.warning("[SYNC MAP] Mapping failed: %s", e, exc_info=True)
            return None

    def _get_selected_world_center(self):
        selected_widget = self.selected_widget
        if selected_widget is None or getattr(selected_widget, 'image_viewer', None) is None:
            return None

        viewer = selected_widget.image_viewer
        dims = viewer.vtk_image_data.GetDimensions()
        i = (dims[0] - 1) / 2.0
        j = (dims[1] - 1) / 2.0
        k = viewer.GetSlice()
        try:
            return viewer.ijk_to_world(i, j, k, y_flip=True)
        except Exception:
            return None

    def _schedule_reference_line_update(self):
        """Throttled reference line update — leading + trailing edge.

        v2.2.3.3.7: Round-robin target repaint for smooth reference line sync.

        Previous behavior (v2.2.3.3.6):
          Leading-edge geometry-only + 80ms trailing-edge full repaint.
          Trailing-edge painted ALL target viewers at once (~20ms × N),
          causing ~60ms event-loop blocking every 80ms.  Queue delays
          accumulated to 400-500ms with stale-scroll skips.  Reference
          lines appeared jumpy during fast scroll.

        New behavior (v2.2.3.3.7):
          Leading-edge: geometry-only (repaint=False, ~1ms) — instant.
          Trailing-edge (50ms): geometry-only + paint ONE target viewer
          (round-robin, ~20ms).  Each target gets painted every N×50ms
          where N = number of targets.  Event-loop blocking is capped
          at ~20ms per tick instead of ~60ms.
          Scroll-end: when no new events arrive, the final tick repaints
          ALL targets once to ensure full visual correctness.
        """
        if not hasattr(self, '_rl_throttle_timer'):
            self._rl_throttle_timer = QTimer()
            self._rl_throttle_timer.setSingleShot(True)
            self._rl_throttle_timer.setInterval(50)  # 50ms tick for round-robin
            self._rl_throttle_timer.timeout.connect(self._rl_throttle_fire)
            self._rl_pending = False
            self._rl_rr_index = 0  # round-robin paint index

        if not self._rl_throttle_timer.isActive():
            # Leading edge — geometry only, no repaint
            self.manage_reference_line(repaint=False)
            self._rl_throttle_timer.start()
        else:
            # Inside cooldown window — defer to trailing edge
            self._rl_pending = True
            # Track merged (coalesced) events for instrumentation
            if hasattr(self, '_rl_merged_count'):
                self._rl_merged_count += 1

    def _rl_throttle_fire(self):
        """Trailing-edge callback — outer guard (H8, v2.2.9.3).

        QTimer.timeout slot: exceptions must NOT propagate through the
        Shiboken C++ boundary or they produce untraceable Qt crashes.
        """
        try:
            self._rl_throttle_fire_impl()
        except Exception:
            logger.error(
                "_rl_throttle_fire: unhandled exception (suppressed)",
                exc_info=True,
            )

    def _rl_throttle_fire_impl(self):
        """Trailing-edge callback — round-robin paint or scroll-end all-repaint."""
        # [H10-1] Mismatch detection — reference line callback
        try:
            _sw = getattr(self, 'selected_widget', None)
            _vsn = '?'
            if _sw is not None:
                _vsn = str(getattr(getattr(_sw, 'image_viewer', None), 'metadata', {}).get('series', {}).get('series_number', '?'))
            _dm = getattr(self, '_h10_dm_active_series', getattr(getattr(self, 'parent_widget', None), '_h10_dm_active_series', '?') if hasattr(self, 'parent_widget') else '?')
            logger.debug(
                "[H10-1] fn=_rl_throttle_fire viewer_series=%s dm_active=%s pending=%s",
                _vsn, _dm, self._rl_pending,
            )
        except Exception:
            pass
        if self._rl_pending:
            # Still scrolling — update geometry + paint ONE target (round-robin)
            self._rl_pending = False
            self.manage_reference_line(repaint=False)
            self._rl_repaint_next_target()
            # Re-arm for next tick
            self._rl_throttle_timer.start()
        else:
            # Scroll ended — final repaint ALL targets for visual correctness
            self.manage_reference_line(repaint=True)

    def _rl_repaint_next_target(self):
        """Paint ONE target viewer's reference line (round-robin).

        Limits event-loop blocking to ~20ms per tick (one VTK Render)
        instead of ~20ms × N for all targets simultaneously.
        """
        targets = self._rl_get_target_widgets()
        if not targets:
            return
        idx = self._rl_rr_index % len(targets)
        self._rl_rr_index = idx + 1
        targets[idx].update()

    def _rl_get_target_widgets(self):
        """Get list of VTK widgets that are reference-line targets (not source)."""
        targets = []
        for node in self.lst_nodes_viewer:
            vtk_widget = getattr(node, 'vtk_widget', None)
            if vtk_widget is None or vtk_widget is self.selected_widget:
                continue
            if getattr(vtk_widget, 'image_viewer', None) is not None:
                targets.append(vtk_widget)
        return targets

    def manage_reference_line(self, repaint=True):
        """
        Compute and draw the reference line: intersection of the source viewer's slice plane
        with the current slice rectangle of each target viewer (no MPR needed).

        Args:
            repaint: If True, call vtk_widget.update() on modified target viewers
                     to schedule a Qt paintEvent → VTK Render.  If False, only
                     update VTK actor geometry (SetPoint1/SetPoint2, Visibility)
                     without triggering a paint — the actors will be rendered on
                     the next natural paint cycle.

        v2.2.3.3.6: repaint parameter controls whether target viewer paints
        are triggered.  The scroll throttle uses repaint=False on leading edge
        (geometry only, ~1ms) and repaint=True on trailing edge (~80ms interval)
        to avoid blocking the scroll event loop with paintEvents.
        """
        _t_rl_start = time.perf_counter()

        if len(self.lst_nodes_viewer) == 1:
            return

        # Feature switches (set once if not already defined)
        if not hasattr(self, "RL_APPLY_ROT90"):
            self.RL_APPLY_ROT90 = True  # rotate +90° within target slice plane

        if not hasattr(self, "RL_APPLY_FLIP_X"):
            self.RL_APPLY_FLIP_X = True  # mirror along column axis (x -> -x)

        if not hasattr(self, "RL_APPLY_FLIP_Y"):
            self.RL_APPLY_FLIP_Y = True  # mirror along row axis    (y -> -y); matches your Reslice Flip-Y

        # No selected source viewer → nothing to do
        if not self.selected_widget or not getattr(self.selected_widget, "image_viewer", None):
            return

        # -------- 1) Source plane from DICOM (LPS) --------
        src_iv = self.selected_widget.image_viewer
        self._ensure_instances_sorted_for_geometry(src_iv)
        src_slice = src_iv.GetSlice()
        try:
            src_inst = src_iv.metadata['instances'][src_slice]

            src_image_orientation_patient = src_inst['image_orientation_patient']
            src_image_position_patient = src_inst['image_position_patient']
            if (src_image_orientation_patient is None) or (src_image_position_patient is None):
                return

            row1 = np.asarray(src_image_orientation_patient[3:6], dtype=float)  # IOP row
            col1 = np.asarray(src_image_orientation_patient[0:3], dtype=float)  # IOP col
            n1 = np.cross(row1, col1)
            n1 = n1 / (np.linalg.norm(n1) + reference_line.rl_eps())  # plane normal
            p1 = np.asarray(src_image_position_patient, dtype=float)  # point on plane
        except Exception:
            return

        # -------- 2) For each target viewer, compute intersection and draw --------
        for node in self.lst_nodes_viewer:
            vtk_widget = getattr(node, 'vtk_widget', None)
            if vtk_widget is None:
                continue
            iv = getattr(vtk_widget, "image_viewer", None)
            if iv is None:
                continue
            self._ensure_instances_sorted_for_geometry(iv)

            # Skip drawing on the source viewer itself
            if vtk_widget is self.selected_widget:
                if getattr(iv, 'IS_QT_BRIDGE', False):
                    iv.qt_viewer.clear_overlay_lines()
                else:
                    reference_line.rl_hide_actor_if_any(iv)
                if repaint:
                    vtk_widget.update()
                continue

            try:
                t_slice = iv.GetSlice()
                t_inst = iv.metadata['instances'][t_slice]

                # Use .get() to avoid KeyError when instances come from the
                # filesystem-load path which may not store IOP/IPP keys.
                target_image_orientation_patient = t_inst.get('image_orientation_patient')
                target_image_position_patient = t_inst.get('image_position_patient')
                if (target_image_orientation_patient is None) or (target_image_position_patient is None):
                    if getattr(iv, 'IS_QT_BRIDGE', False):
                        iv.qt_viewer.clear_overlay_lines()
                    else:
                        reference_line.rl_hide_actor_if_any(iv)
                    if repaint:
                        vtk_widget.update()
                    continue  # skip this target, process remaining viewers

                # rows = int(t_inst['rows'])
                # cols = int(t_inst['columns'])
                # row2 = np.asarray(target_image_orientation_patient[3:6], dtype=float)  # IOP row (unit)
                # col2 = np.asarray(target_image_orientation_patient[0:3], dtype=float)  # IOP col (unit)
                # pos2 = np.asarray(target_image_position_patient, dtype=float)  # IPP
                # ps = np.asarray(t_inst['pixel_spacing'], dtype=float)  # [row, col]
                # sy = float(ps[0])
                # sx = float(ps[1])

                dims = iv.vtk_image_data.GetDimensions()  # (dimX, dimY, dimZ)
                sp = iv.vtk_image_data.GetSpacing()  # (sx, sy, sz)

                rows = int(dims[1])  # Y
                cols = int(dims[0])  # X
                sx = float(sp[0])  # pixel size along displayed columns
                sy = float(sp[1])  # pixel size along displayed rows

                # جهت‌ها و IPP همچنان از متادیتا (LPS) برداشته می‌شود
                row2 = np.asarray(target_image_orientation_patient[3:6], dtype=float)
                col2 = np.asarray(target_image_orientation_patient[0:3], dtype=float)
                pos2 = np.asarray(target_image_position_patient, dtype=float)

                # Target slice quad in LPS (voxel centers)
                quad = reference_line.rl_quad_corners_lps(rows, cols, pos2, row2, col2, sy, sx)

                # Intersect source plane with target quad → segment in LPS
                ok, seg = reference_line.rl_clip_plane_with_quad(p1, n1, quad)
                if not ok:
                    if getattr(iv, 'IS_QT_BRIDGE', False):
                        iv.qt_viewer.clear_overlay_lines()
                    else:
                        reference_line.rl_hide_actor_if_any(iv)
                    if repaint:
                        vtk_widget.update()
                    continue

                P0_lps, P1_lps = seg
                center = reference_line.rl_center_of_slice(rows, cols, pos2, row2, col2, sy, sx)

                # # Optional display-space adjustments to match your viewer
                # if self.RL_APPLY_ROT90:
                #     P0_lps = reference_line._rl_rotate_ccw_90_in_plane(P0_lps, center, col2, row2)
                #     P1_lps = reference_line._rl_rotate_ccw_90_in_plane(P1_lps, center, col2, row2)

                # if self.RL_APPLY_FLIP_X:
                #     P0_lps = reference_line._rl_apply_flip_x_in_plane(P0_lps, center, col2, row2)
                #     P1_lps = reference_line._rl_apply_flip_x_in_plane(P1_lps, center, col2, row2)

                # Flip-Y compensates for VTK's bottom-left origin (Y-up).
                # Qt viewers use top-left origin (same as DICOM) → skip flip.
                _is_qt_target = getattr(iv, 'IS_QT_BRIDGE', False)
                if self.RL_APPLY_FLIP_Y and not _is_qt_target:
                    P0_lps = reference_line.rl_apply_flip_y_in_plane(P0_lps, center, col2, row2)
                    P1_lps = reference_line.rl_apply_flip_y_in_plane(P1_lps, center, col2, row2)

                # LPS → target index (i, j, k) on the current slice
                I0 = reference_line.rl_lps_to_target_index(P0_lps, pos2, col2, row2, sx, sy, t_slice)
                I1 = reference_line.rl_lps_to_target_index(P1_lps, pos2, col2, row2, sx, sy, t_slice)

                # Index → target "world" used by the viewer (origin/spacing from vtk_image_data)
                spacing = np.asarray(iv.vtk_image_data.GetSpacing(), dtype=float)
                origin = np.asarray(iv.vtk_image_data.GetOrigin(), dtype=float)
                P0_w = origin + spacing * I0
                P1_w = origin + spacing * I1

                if getattr(iv, 'IS_QT_BRIDGE', False):
                    # ── Qt path: overlay lines via QPainter ──
                    # I0, I1 are (i, j, k) index coords: i=column(x), j=row(y)
                    iv.qt_viewer.set_overlay_lines([
                        (float(I0[0]), float(I0[1]),
                         float(I1[0]), float(I1[1]),
                         1.0, 0.85, 0.12, 3.0),
                    ])
                else:
                    # ── VTK path: line actor ──
                    # Create/update the cached line actor for this viewer
                    ls, act = reference_line.rl_ensure_line_actor(iv, color=(1.0, 0.85, 0.12), width=3.0)
                    ls.SetPoint1(float(P0_w[0]), float(P0_w[1]), float(P0_w[2]))
                    ls.SetPoint2(float(P1_w[0]), float(P1_w[1]), float(P1_w[2]))
                    act.VisibilityOn()
                # v2.2.3.3.6: Only trigger repaint when requested.
                # Leading-edge scroll calls use repaint=False (geometry only)
                # to avoid 20ms×N paintEvents blocking the event loop.
                if repaint:
                    vtk_widget.update()

            except Exception as e:
                print("reference-line: target error:", e)
                if getattr(iv, 'IS_QT_BRIDGE', False):
                    iv.qt_viewer.clear_overlay_lines()
                else:
                    reference_line.rl_hide_actor_if_any(iv)
                if repaint:
                    vtk_widget.update()

        # ── Instrumentation: latency tracking (v2.2.3.3.5) ──────────
        _t_elapsed = (time.perf_counter() - _t_rl_start) * 1000  # ms
        if not hasattr(self, '_rl_latencies'):
            from collections import deque
            self._rl_latencies = deque(maxlen=200)
            self._rl_call_count = 0
            self._rl_merged_count = 0
        self._rl_latencies.append(_t_elapsed)
        self._rl_call_count += 1
        if self._rl_call_count % 100 == 0:
            arr = np.array(self._rl_latencies)
            p50, p95 = float(np.percentile(arr, 50)), float(np.percentile(arr, 95))
            print(f"[ref-line] p50={p50:.1f}ms  p95={p95:.1f}ms  "
                  f"merged={self._rl_merged_count}  calls={self._rl_call_count}")

