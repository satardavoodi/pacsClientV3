"""
One-shot script: rewrite set_sync_point in qt_viewer_bridge.py.
Adds _find_closest_slice helper + IPP-based slice nav + bounds-check log.
"""
import re, pathlib, sys

PATH = pathlib.Path(__file__).parent.parent.parent / "modules/viewer/fast/qt_viewer_bridge.py"
content = PATH.read_text(encoding="utf-8")

# ── Helper insertion point: just before def set_sync_point ───────────────────
HELPER = '''
    def _find_closest_slice(self, patient_lps) -> "Optional[int]":
        """Return slice index closest to patient_lps via IOP/IPP projection.

        Used by set_sync_point so Qt targets navigate correctly for all
        orientations (Axial, Sagittal, Coronal, Oblique).  The old Z-index
        formula only worked for axial series.
        Returns None when metadata is insufficient.
        """
        try:
            instances = self.metadata.get("instances") or []
            n = len(instances)
            if n < 2:
                return None
            iop = instances[0].get("image_orientation_patient") or []
            if len(iop) < 6:
                return None
            ipp_0 = np.asarray(instances[0]["image_position_patient"], dtype=float)
            ipp_1 = np.asarray(instances[1]["image_position_patient"], dtype=float)
            col_d = np.asarray(iop[0:3], dtype=float)
            row_d = np.asarray(iop[3:6], dtype=float)
            nv = np.cross(row_d, col_d)
            nv_len = float(np.linalg.norm(nv))
            if nv_len < 1e-12:
                return None
            nv /= nv_len
            ds = float(np.dot(ipp_1 - ipp_0, nv))
            if abs(ds) < 1e-9:
                return None
            d0 = float(np.dot(np.asarray(patient_lps, dtype=float) - ipp_0, nv))
            k = int(round(d0 / ds))
            return max(0, min(k, n - 1))
        except Exception:
            return None

'''

NEW_SET_SYNC = '''    def set_sync_point(self, world_pos, adjust_slice: bool = False) -> None:
        """Display a sync-point crosshair by converting world patient-LPS -> image coords.

        *world_pos* is TRUE patient-LPS from _map_sync_dicom (Qt target fix).
        Slice navigation uses _find_closest_slice() (IPP projection) so that
        Sagittal and Coronal targets navigate to the correct slice.
        """
        try:
            if adjust_slice:
                # Primary: IOP/IPP slice finder - correct for all orientations
                _new_slice = self._find_closest_slice(world_pos)
                if _new_slice is None and self.vtk_image_data is not None:
                    # Fallback: mock-VTK Z formula (axial legacy path)
                    sp = self.vtk_image_data.GetSpacing()
                    orig = self.vtk_image_data.GetOrigin()
                    dims = self.vtk_image_data.GetDimensions()
                    if sp[2] > 1e-9:
                        z_idx = int(round((world_pos[2] - orig[2]) / sp[2]))
                        _new_slice = max(0, min(z_idx, dims[2] - 1))
                if _new_slice is not None and _new_slice != self._current_slice:
                    logger.info(
                        "[QT-SET-SYNC] adjust_slice: %d -> %d",
                        self._current_slice, _new_slice,
                    )
                    self.set_slice(_new_slice)

            # world_pos is patient-LPS - patient_xyz_to_image_xy is the
            # exact inverse of image_xy_to_patient_xyz for any orientation.
            img_x, img_y = 0.0, 0.0
            try:
                img_x, img_y = self.pipeline.patient_xyz_to_image_xy(
                    world_pos, self._current_slice)
            except Exception:
                # Fallback: mock-VTK index formula (axial only)
                if self.vtk_image_data is not None:
                    sp = self.vtk_image_data.GetSpacing()
                    orig = self.vtk_image_data.GetOrigin()
                    img_x = (world_pos[0] - orig[0]) / sp[0] if sp[0] > 1e-9 else 0.0
                    img_y = (world_pos[1] - orig[1]) / sp[1] if sp[1] > 1e-9 else 0.0

            # Bounds check diagnostic
            try:
                _inst_list = self.metadata.get("instances") or []
                _inst = _inst_list[self._current_slice] if self._current_slice < len(_inst_list) else {}
                _t_rows = _inst.get("rows") or 0
                _t_cols = _inst.get("columns") or 0
            except Exception:
                _t_rows = _t_cols = 0
            _out_reason = []
            if _t_cols:
                if img_x < 0:          _out_reason.append("left")
                elif img_x >= _t_cols: _out_reason.append("right")
            if _t_rows:
                if img_y < 0:          _out_reason.append("top")
                elif img_y >= _t_rows: _out_reason.append("bottom")
            _in_bounds = not _out_reason and bool(_t_rows and _t_cols)
            logger.info(
                "[QT-SET-SYNC] world=(%.4f,%.4f,%.4f) adjust=%s slice=%d\\n"
                "  img=(%.2f,%.2f)  target=[%dx%d]  in_bounds=%s  outside=%s"
                "  rotate=%s flip_h=%s flip_v=%s",
                world_pos[0], world_pos[1], world_pos[2], adjust_slice, self._current_slice,
                img_x, img_y, _t_cols, _t_rows, _in_bounds, _out_reason or "none",
                getattr(self.qt_viewer, "_rotation_angle", "?"),
                getattr(self.qt_viewer, "_flip_h", "?"),
                getattr(self.qt_viewer, "_flip_v", "?"),
            )
            self.qt_viewer.set_sync_point(img_x, img_y)
        except Exception:
            pass
'''

# ── Find and replace the old set_sync_point block ───────────────────────────
# Pattern: from "    def set_sync_point" up to (not including) "    def hide_sync_point"
pattern = re.compile(
    r'(    def set_sync_point\(self.*?)(?=\n    def hide_sync_point)',
    re.DOTALL,
)
m = pattern.search(content)
if not m:
    print("ERROR: could not find set_sync_point block", file=sys.stderr)
    sys.exit(1)

old_block = m.group(1)
print(f"Found set_sync_point block ({len(old_block)} chars)")

# Insert _find_closest_slice before set_sync_point
replacement = HELPER + NEW_SET_SYNC

new_content = content[:m.start()] + replacement + content[m.end():]

# Verify the helper was inserted
assert "_find_closest_slice" in new_content, "helper not inserted"
assert "_find_closest_slice" not in content, "helper already existed (unexpected)"
assert "adjust_slice: %d -> %d" in new_content, "new set_sync_point not inserted"

PATH.write_text(new_content, encoding="utf-8")
print("OK: qt_viewer_bridge.py updated")
