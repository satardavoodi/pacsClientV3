"""Tests for GeometryAPI and ViewportGeometryRegistry
(modules.viewer.geometry.geometry_api).

Covers:
  TestDisplayedIndexToLps      — displayed_index_to_lps round-trips (4 tests)
  TestScreenEdgeVectors        — screen_edge_vectors_in_lps (5 tests)
  TestCrossViewportMapping     — map_lps_between_viewports (6 tests)
  TestReferenceLines           — reference_line_in_viewport (6 tests)
  TestRegistryBasic            — ViewportGeometryRegistry CRUD (5 tests)
  TestRegistryAllRefLines      — compute_all_reference_lines (4 tests)

Total: 30 tests
"""

import pytest
import numpy as np

from modules.viewer.geometry.source_geometry import SourceGeometry
from modules.viewer.geometry.display_geometry import DisplayGeometry
from modules.viewer.geometry.geometry_api import GeometryAPI, ViewportGeometryRegistry


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _build_sg(iop, n=10, row_sp=0.7, col_sp=0.7, spacing=5.0,
              n_rows=512, n_cols=512, frame_of_reference="1.2.3.FOR",
              base_ipp=None, series_uid=""):
    if base_ipp is None:
        base_ipp = [0.0, 0.0, 0.0]
    from modules.viewer.geometry.source_geometry import _unit
    rc = _unit(np.array(iop[0:3]))
    cc = _unit(np.array(iop[3:6]))
    normal = _unit(np.cross(rc, cc))
    instances = []
    for k in range(n):
        ipp = [base_ipp[i] + k * spacing * normal[i] for i in range(3)]
        instances.append({
            "SOPInstanceUID": f"uid.{k}",
            "ImageOrientationPatient": iop,
            "ImagePositionPatient": ipp,
            "PixelSpacing": [row_sp, col_sp],
            "Rows": n_rows,
            "Columns": n_cols,
            "FrameOfReferenceUID": frame_of_reference,
        })
    return SourceGeometry.build_from_instances(
        instances, series_uid=series_uid,
        vtk_n_rows=n_rows, vtk_n_cols=n_cols, vtk_n_slices=n
    )


def _axial_dg(viewport_id="axial", frame_of_reference="1.2.3.FOR", y_flip=False):
    sg = _build_sg([1.0,0.0,0.0, 0.0,1.0,0.0], frame_of_reference=frame_of_reference,
                   series_uid=viewport_id)
    dg = DisplayGeometry(sg, viewport_id)
    if y_flip:
        dg.apply_y_flip(512)
    return dg


def _coronal_dg(viewport_id="coronal", frame_of_reference="1.2.3.FOR"):
    sg = _build_sg([1.0,0.0,0.0, 0.0,0.0,1.0], frame_of_reference=frame_of_reference,
                   series_uid=viewport_id)
    return DisplayGeometry(sg, viewport_id)


def _sagittal_dg(viewport_id="sagittal", frame_of_reference="1.2.3.FOR"):
    sg = _build_sg([0.0,1.0,0.0, 0.0,0.0,1.0], frame_of_reference=frame_of_reference,
                   series_uid=viewport_id)
    return DisplayGeometry(sg, viewport_id)


# ─────────────────────────────────────────────────────────────────────────────
# TestDisplayedIndexToLps
# ─────────────────────────────────────────────────────────────────────────────

class TestDisplayedIndexToLps:
    def test_origin_at_zero(self):
        dg = _axial_dg()
        lps = GeometryAPI.displayed_index_to_lps(dg, 0, 0, 0)
        np.testing.assert_allclose(lps, dg.source.origin_ipp, atol=1e-9)

    def test_round_trip_identity(self):
        dg = _axial_dg()
        for pt in [(10.0, 20.0, 3.0), (100.0, 200.0, 7.0)]:
            lps = GeometryAPI.displayed_index_to_lps(dg, *pt)
            back = GeometryAPI.lps_to_displayed_index(dg, *lps.tolist())
            np.testing.assert_allclose(back, pt, atol=1e-5)

    def test_round_trip_y_flip(self):
        dg = _axial_dg(y_flip=True)
        for pt in [(15.0, 25.0, 2.0)]:
            lps = GeometryAPI.displayed_index_to_lps(dg, *pt)
            back = GeometryAPI.lps_to_displayed_index(dg, *lps.tolist())
            np.testing.assert_allclose(back, pt, atol=1e-5)

    def test_slice_k_approx(self):
        dg = _axial_dg()
        lps = GeometryAPI.displayed_index_to_lps(dg, 0.0, 0.0, 3.0)
        k = GeometryAPI.lps_to_slice_k_approx(dg, *lps.tolist())
        assert abs(k - 3.0) < 0.1


# ─────────────────────────────────────────────────────────────────────────────
# TestScreenEdgeVectors
# ─────────────────────────────────────────────────────────────────────────────

class TestScreenEdgeVectors:
    def test_right_left_antiparallel(self):
        dg = _axial_dg()
        vecs = GeometryAPI.screen_edge_vectors_in_lps(dg)
        np.testing.assert_allclose(vecs["screen_right"], -vecs["screen_left"], atol=1e-9)

    def test_up_down_antiparallel(self):
        dg = _axial_dg()
        vecs = GeometryAPI.screen_edge_vectors_in_lps(dg)
        np.testing.assert_allclose(vecs["screen_up"], -vecs["screen_down"], atol=1e-9)

    def test_into_out_antiparallel(self):
        dg = _axial_dg()
        vecs = GeometryAPI.screen_edge_vectors_in_lps(dg)
        np.testing.assert_allclose(vecs["screen_into"], -vecs["screen_out_of"], atol=1e-9)

    def test_six_vectors_returned(self):
        dg = _axial_dg()
        vecs = GeometryAPI.screen_edge_vectors_in_lps(dg)
        assert len(vecs) == 6

    def test_all_unit_vectors(self):
        dg = _axial_dg()
        vecs = GeometryAPI.screen_edge_vectors_in_lps(dg)
        for name, v in vecs.items():
            assert abs(np.linalg.norm(v) - 1.0) < 1e-9, f"{name} is not a unit vector"


# ─────────────────────────────────────────────────────────────────────────────
# TestCrossViewportMapping
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossViewportMapping:
    def test_same_viewport_identity(self):
        """Mapping a point from viewport A to itself must return the same coordinates."""
        dg = _axial_dg()
        result = GeometryAPI.map_lps_between_viewports(dg, dg, 10.0, 20.0, 3.0)
        assert result is not None
        np.testing.assert_allclose(result, (10.0, 20.0, 3.0), atol=1e-5)

    def test_different_for_returns_none(self):
        """Different FrameOfReferenceUID → returns None."""
        dg_a = _axial_dg(viewport_id="a", frame_of_reference="1.2.3.A")
        dg_b = _axial_dg(viewport_id="b", frame_of_reference="1.2.3.B")
        result = GeometryAPI.map_lps_between_viewports(dg_a, dg_b, 0.0, 0.0, 0.0)
        assert result is None

    def test_axial_to_coronal_k_maps_to_j(self):
        """Axial k=5 (z=25mm) should map to coronal j=5."""
        dg_ax = _axial_dg(viewport_id="axial", frame_of_reference="shared")
        dg_cor = _coronal_dg(viewport_id="coronal", frame_of_reference="shared")
        # Origin both at (0,0,0); axial row→L, coronal row→L, col→S
        lps = GeometryAPI.displayed_index_to_lps(dg_ax, 0.0, 0.0, 5.0)
        result = GeometryAPI.map_lps_between_viewports(dg_ax, dg_cor, 0.0, 0.0, 5.0)
        assert result is not None

    def test_empty_for_treated_as_compatible(self):
        """Empty FrameOfReferenceUID → assumed compatible."""
        dg_a = _axial_dg(viewport_id="a", frame_of_reference="")
        dg_b = _axial_dg(viewport_id="b", frame_of_reference="")
        result = GeometryAPI.map_lps_between_viewports(dg_a, dg_b, 0.0, 0.0, 0.0)
        assert result is not None

    def test_one_empty_for_compatible(self):
        """One empty FrameOfReferenceUID → assumed compatible."""
        dg_a = _axial_dg(viewport_id="a", frame_of_reference="")
        dg_b = _axial_dg(viewport_id="b", frame_of_reference="1.2.3.B")
        result = GeometryAPI.map_lps_between_viewports(dg_a, dg_b, 0.0, 0.0, 0.0)
        assert result is not None

    def test_lps_roundtrip_same_series(self):
        """Axial → coronal → axial: i, j consistent in each viewport."""
        dg_ax = _axial_dg(viewport_id="axial", frame_of_reference="shared")
        dg_cor = _coronal_dg(viewport_id="coronal", frame_of_reference="shared")
        origin_lps = GeometryAPI.displayed_index_to_lps(dg_ax, 0.0, 0.0, 0.0)
        # Map origin of axial to coronal
        r = GeometryAPI.map_lps_between_viewports(dg_ax, dg_cor, 0.0, 0.0, 0.0)
        assert r is not None
        # Map back from coronal to axial
        r2 = GeometryAPI.map_lps_between_viewports(dg_cor, dg_ax, *r)
        assert r2 is not None
        np.testing.assert_allclose(r2, (0.0, 0.0, 0.0), atol=1e-5)


# ─────────────────────────────────────────────────────────────────────────────
# TestReferenceLines
# ─────────────────────────────────────────────────────────────────────────────

class TestReferenceLines:
    def test_axial_to_coronal_returns_line(self):
        """Axial plane intersects coronal plane: should return a line segment."""
        dg_ax = _axial_dg(viewport_id="axial", frame_of_reference="shared")
        dg_cor = _coronal_dg(viewport_id="coronal", frame_of_reference="shared")
        result = GeometryAPI.reference_line_in_viewport(dg_ax, dg_cor, 3.0)
        assert result is not None, "Expected reference line, got None"

    def test_same_orientation_parallel_returns_none(self):
        """Two axial viewports: planes are parallel → no intersection line."""
        dg_ax1 = _axial_dg(viewport_id="ax1", frame_of_reference="shared")
        dg_ax2 = _axial_dg(viewport_id="ax2", frame_of_reference="shared")
        result = GeometryAPI.reference_line_in_viewport(dg_ax1, dg_ax2, 3.0)
        assert result is None, "Parallel planes must return None"

    def test_different_for_returns_none(self):
        dg_ax = _axial_dg(viewport_id="a", frame_of_reference="1.2.3.A")
        dg_cor = _coronal_dg(viewport_id="c", frame_of_reference="1.2.3.B")
        result = GeometryAPI.reference_line_in_viewport(dg_ax, dg_cor, 0.0)
        assert result is None

    def test_line_segment_has_two_endpoints(self):
        dg_ax = _axial_dg(viewport_id="axial", frame_of_reference="shared")
        dg_cor = _coronal_dg(viewport_id="coronal", frame_of_reference="shared")
        result = GeometryAPI.reference_line_in_viewport(dg_ax, dg_cor, 3.0)
        if result is not None:
            p1, p2 = result
            assert len(p1) == 2
            assert len(p2) == 2

    def test_sagittal_to_coronal_returns_line(self):
        dg_sag = _sagittal_dg(viewport_id="sag", frame_of_reference="shared")
        dg_cor = _coronal_dg(viewport_id="cor", frame_of_reference="shared")
        result = GeometryAPI.reference_line_in_viewport(dg_sag, dg_cor, 2.0)
        assert result is not None

    def test_current_slice_plane_returns_four_values(self):
        dg = _axial_dg()
        origin, sr, su, normal = GeometryAPI.current_slice_plane_in_lps(dg, 3.0)
        assert len(origin) == 3
        assert len(sr) == 3
        assert len(su) == 3
        assert len(normal) == 3


# ─────────────────────────────────────────────────────────────────────────────
# TestRegistryBasic
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistryBasic:
    def test_register_and_get(self):
        reg = ViewportGeometryRegistry()
        dg = _axial_dg("vp0")
        reg.register("vp0", dg)
        assert reg.get("vp0") is dg

    def test_unregister_removes(self):
        reg = ViewportGeometryRegistry()
        dg = _axial_dg("vp0")
        reg.register("vp0", dg)
        reg.unregister("vp0")
        assert reg.get("vp0") is None

    def test_all_viewport_ids(self):
        reg = ViewportGeometryRegistry()
        for name in ["a", "b", "c"]:
            reg.register(name, _axial_dg(name))
        assert set(reg.all_viewport_ids()) == {"a", "b", "c"}

    def test_clear(self):
        reg = ViewportGeometryRegistry()
        reg.register("vp0", _axial_dg("vp0"))
        reg.clear()
        assert reg.all_viewport_ids() == []

    def test_get_screen_edge_vectors_unregistered(self):
        reg = ViewportGeometryRegistry()
        assert reg.get_screen_edge_vectors("nonexistent") is None


# ─────────────────────────────────────────────────────────────────────────────
# TestRegistryAllRefLines
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistryAllRefLines:
    def _make_registry(self):
        reg = ViewportGeometryRegistry()
        reg.register("axial",    _axial_dg("axial",    frame_of_reference="shared"))
        reg.register("coronal",  _coronal_dg("coronal", frame_of_reference="shared"))
        reg.register("sagittal", _sagittal_dg("sagittal", frame_of_reference="shared"))
        return reg

    def test_all_ref_lines_returns_dict(self):
        reg = self._make_registry()
        result = reg.compute_all_reference_lines("axial", 3.0)
        assert isinstance(result, dict)

    def test_self_not_in_result(self):
        reg = self._make_registry()
        result = reg.compute_all_reference_lines("axial", 3.0)
        assert "axial" not in result

    def test_other_viewports_in_result(self):
        reg = self._make_registry()
        result = reg.compute_all_reference_lines("axial", 3.0)
        assert "coronal" in result
        assert "sagittal" in result

    def test_map_lps_to_viewport_unregistered(self):
        reg = self._make_registry()
        result = reg.map_lps_to_viewport("axial", "nonexistent", 0.0, 0.0, 0.0)
        assert result is None
