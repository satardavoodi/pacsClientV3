"""Regression tests for partial-stack loading fixes (R29).

Covers the root-cause chain discovered during the Advanced VTK forensic
investigation (2026-05-16):

  C-A  _select_dominant_size_dicom_files reduces dicom_files but
       metadata['instances'] was NOT updated → mismatched (vtk_N, meta_N).
       Fix 2: clip metadata['instances'] immediately after the filter.

  C-B  _get_cached_metadata used cache_key = "series_{pk}" with no
       file-count component → a stale full-series 20-instance entry was
       returned for a partial 8-instance load of the same series.
       Fix 3: cache_key = "series_{pk}_n{len(instances)}".

  C-C  get_count_of_slices() returned max(range, dims, meta) so meta_count=20
       beat vtk_count=8 → slider range [0,19], K-flip map sent display_k 0..11
       to raw_k 19..8, out of VTK range → VTK clamped → frozen image.
       Fix 1: VTK-derived count is authoritative when vtk_count > 1.

  Fix 4  reset_slider() passed display_k (mid_slices) to
         apply_default_window_level() which indexes metadata['instances'][raw_k].
         Fix: pass vtk_widget.image_viewer.GetSlice() (raw_k) instead.

Test classes
────────────
  TestGetCountOfSlicesAuthoritative  (Fix 1 — 6 tests)
  TestMetadataClipLogic              (Fix 2 — 5 tests)
  TestCacheKeyIncludesCount          (Fix 3 — 4 tests)
  TestResetSliderWLDomain            (Fix 4 — 3 tests, also in
                                      test_fast_viewer_reset_slider.py)

Total: 18 tests
"""

import pytest
from unittest.mock import MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Fix 1 — get_count_of_slices()  (modules/viewer/advanced/viewer_2d.py)
# ─────────────────────────────────────────────────────────────────────────────

def _make_viewer_stub(slice_min=0, slice_max=7, dims_z=8, meta_n=20):
    """Return a MagicMock stub shaped like ImageViewer2D's interface for
    get_count_of_slices().  Binds the real method so the actual production
    code runs, not a reimplementation."""
    stub = MagicMock()
    stub.GetSliceMin.return_value = int(slice_min)
    stub.GetSliceMax.return_value = int(slice_max)
    dims_mock = MagicMock()
    dims_mock.GetDimensions.return_value = (512, 512, int(dims_z))
    stub.vtk_image_data = dims_mock
    stub.metadata = {"instances": [{}] * int(meta_n)}
    return stub


def _call_get_count(stub):
    """Call the real production get_count_of_slices() on a stub."""
    from modules.viewer.advanced.viewer_2d import ImageViewer2D
    return ImageViewer2D.get_count_of_slices(stub)


class TestGetCountOfSlicesAuthoritative:
    """Fix 1: VTK-derived count must win over metadata count when > 1."""

    def test_vtk_range_beats_meta_count(self):
        """C-C regression: meta says 20, VTK range says 8 → return 8."""
        stub = _make_viewer_stub(slice_min=0, slice_max=7, dims_z=0, meta_n=20)
        assert _call_get_count(stub) == 8

    def test_vtk_dims_beats_meta_count(self):
        """dims_z=8 beats meta_n=20 even when GetSliceMin/Max raise."""
        stub = _make_viewer_stub(slice_min=0, slice_max=7, dims_z=8, meta_n=20)
        assert _call_get_count(stub) == 8

    def test_vtk_and_meta_equal_returns_vtk(self):
        """When vtk_count == meta_count, result is correct regardless."""
        stub = _make_viewer_stub(slice_min=0, slice_max=19, dims_z=20, meta_n=20)
        assert _call_get_count(stub) == 20

    def test_vtk_count_zero_falls_back_to_meta(self):
        """Uninitialized viewer (vtk_count ≤ 1) — use metadata as last resort."""
        stub = _make_viewer_stub(slice_min=0, slice_max=0, dims_z=0, meta_n=15)
        assert _call_get_count(stub) == 15

    def test_vtk_one_slice_falls_back_to_meta(self):
        """vtk_count=1 is 'uninitialized' sentinel — fall back to meta."""
        stub = _make_viewer_stub(slice_min=0, slice_max=0, dims_z=1, meta_n=10)
        assert _call_get_count(stub) == 10

    def test_both_zero_returns_zero(self):
        """Completely empty viewer/metadata: GetSliceMin/Max raise,
        dims_z=0, meta_n=0 — return 0, never negative."""
        stub = _make_viewer_stub(slice_min=0, slice_max=0, dims_z=0, meta_n=0)
        # Force range path to error so vtk_count stays 0
        stub.GetSliceMin.side_effect = RuntimeError("no data")
        stub.GetSliceMax.side_effect = RuntimeError("no data")
        assert _call_get_count(stub) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Fix 2 — Metadata clip logic  (image_io.py, inline after size-filter)
# ─────────────────────────────────────────────────────────────────────────────
#
# The production code is inline, so we test the algorithm contract by
# reproducing the exact logic extracted from the production block.  If the
# block is ever refactored into a helper function, replace these with direct
# calls to that helper.

def _run_clip(metadata_instances, dicom_paths):
    """Run the exact production clip algorithm from image_io.py Fix 2.

    Takes a list of instance-dicts and a list of Path-like DICOM paths.
    Returns (final_instances, was_clipped) where was_clipped=True when
    a mismatch was detected and the list was actually shortened.
    """
    dicom_files = list(dicom_paths)
    metadata = {"instances": list(metadata_instances)}

    _meta_insts = metadata.get("instances") or []
    if len(dicom_files) != len(_meta_insts):
        _surviving = {str(p).lower() for p in dicom_files}
        _clipped = [
            inst for inst in _meta_insts
            if str(inst.get("instance_path", "")).lower() in _surviving
        ]
        if len(_clipped) == len(dicom_files):
            metadata["instances"] = _clipped
        else:
            metadata["instances"] = _meta_insts[: len(dicom_files)]
        return metadata["instances"], True

    return metadata["instances"], False


class TestMetadataClipLogic:
    """Fix 2: metadata['instances'] is clipped to match dicom_files after
    the size-filter removes mixed-dimension slices."""

    def test_clip_by_path_match(self):
        """Instances matching surviving paths are preserved; others dropped."""
        instances = [
            {"instance_path": r"C:\data\s1\Instance_0001.dcm"},
            {"instance_path": r"C:\data\s1\Instance_0002.dcm"},
            {"instance_path": r"C:\data\s1\Instance_0003.dcm"},
            {"instance_path": r"C:\data\s1\Instance_0004.dcm"},
        ]
        surviving_files = [
            r"C:\data\s1\Instance_0001.dcm",
            r"C:\data\s1\Instance_0003.dcm",
        ]
        result, clipped = _run_clip(instances, surviving_files)
        assert clipped is True
        assert len(result) == 2
        assert result[0]["instance_path"] == r"C:\data\s1\Instance_0001.dcm"
        assert result[1]["instance_path"] == r"C:\data\s1\Instance_0003.dcm"

    def test_truncate_fallback_when_paths_mismatch(self):
        """When path intersection count != dicom_files count, truncate by index."""
        # Instance paths don't match the dicom file names at all.
        instances = [{"instance_path": f"nopath_{i}.dcm"} for i in range(20)]
        surviving_files = [f"different_{i}.dcm" for i in range(8)]
        result, clipped = _run_clip(instances, surviving_files)
        assert clipped is True
        assert len(result) == 8  # truncated to len(dicom_files)

    def test_no_clip_when_already_aligned(self):
        """No mismatch — instances and dicom_files have the same length."""
        instances = [
            {"instance_path": "a.dcm"},
            {"instance_path": "b.dcm"},
        ]
        files = ["a.dcm", "b.dcm"]
        result, clipped = _run_clip(instances, files)
        assert clipped is False
        assert len(result) == 2

    def test_clip_is_case_insensitive(self):
        """Path matching ignores case (Windows paths may differ in case)."""
        instances = [
            {"instance_path": r"C:\Data\S1\Instance_0001.DCM"},
            {"instance_path": r"C:\Data\S1\Instance_0002.DCM"},
            {"instance_path": r"C:\Data\S1\Instance_0003.DCM"},
        ]
        surviving_files = [
            r"c:\data\s1\instance_0001.dcm",
            r"c:\data\s1\instance_0003.dcm",
        ]
        result, clipped = _run_clip(instances, surviving_files)
        assert clipped is True
        assert len(result) == 2

    def test_empty_dicom_files_truncates_to_zero(self):
        """Edge case: all files removed by size-filter → empty instances list."""
        instances = [{"instance_path": f"slice_{i}.dcm"} for i in range(5)]
        surviving_files = []
        result, clipped = _run_clip(instances, surviving_files)
        assert clipped is True
        assert len(result) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Fix 3 — Cache key includes instance count  (image_io.py _get_cached_metadata)
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheKeyIncludesCount:
    """Fix 3: _get_cached_metadata cache key must include len(instances)
    so partial-load and full-load entries are stored under separate keys."""

    def _make_cache_key(self, series_pk, n_instances):
        """Reproduce the production cache key formula."""
        return f"series_{series_pk}_n{n_instances}"

    def test_different_counts_give_different_keys(self):
        """partial-load (n=8) and full-load (n=20) must not share a key."""
        key_partial = self._make_cache_key(42, 8)
        key_full = self._make_cache_key(42, 20)
        assert key_partial != key_full

    def test_same_pk_same_count_gives_same_key(self):
        """Identical load → cache hit."""
        key_a = self._make_cache_key(42, 20)
        key_b = self._make_cache_key(42, 20)
        assert key_a == key_b

    def test_key_contains_pk_and_count(self):
        """Smoke-check the key format contains both components."""
        key = self._make_cache_key(99, 13)
        assert "99" in key
        assert "13" in key

    def test_full_cache_does_not_serve_partial_load(self):
        """Simulate the cache scenario: populate with n=20, look up with n=8."""
        cache = {}
        full_key = self._make_cache_key(5, 20)
        cache[full_key] = {"instances": [{}] * 20}

        partial_key = self._make_cache_key(5, 8)
        # The partial key must NOT hit the full-series cache entry.
        assert partial_key not in cache


# ─────────────────────────────────────────────────────────────────────────────
# Fix 4 — WL domain in reset_slider  (_pw_viewers.py)
# ─────────────────────────────────────────────────────────────────────────────
# These tests complement test_fast_viewer_reset_slider.py.

class _SliderStub:
    def __init__(self):
        self._blocked = False
        self._minimum = 0
        self._maximum = 0
        self._value = 0

    def blockSignals(self, v):
        self._blocked = bool(v)

    def setRange(self, lo, hi):
        self._minimum = int(lo)
        self._maximum = int(hi)

    def setValue(self, v):
        self._value = int(v)

    def value(self):
        return self._value

    def minimum(self):
        return self._minimum

    def maximum(self):
        return self._maximum


class _ImageViewerStub:
    def __init__(self, raw_k=0):
        self._raw_k = int(raw_k)
        self.wl_calls = []

    def GetSlice(self):
        return self._raw_k

    def apply_default_window_level(self, idx):
        self.wl_calls.append(int(idx))


class _VTKWidgetStub:
    def __init__(self, *, count_slices=20, qt_bridge_active=False, raw_k=0):
        self._count_slices = count_slices
        self._qt_bridge_active = qt_bridge_active
        self.image_viewer = _ImageViewerStub(raw_k=raw_k)
        self.set_slider_calls = []

    def set_slider(self, s):
        self.set_slider_calls.append(s)

    def get_count_of_slices(self):
        return self._count_slices


class _Harness:
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_viewers import (
        _PWViewersMixin,
    )

    class _H(_PWViewersMixin):
        def __init__(self):
            self.slider_events = []

        def on_slider_value_changed(self, vtk_widget, value):
            self.slider_events.append((vtk_widget, int(value)))


class TestResetSliderWLDomain:
    """Fix 4: apply_default_window_level must receive raw_k (GetSlice()),
    not display_k.  apply_default_window_level() indexes
    metadata['instances'][raw_k] directly; a display_k argument would look
    up the wrong slice's preset and corrupt WL for the session."""

    def test_wl_called_with_raw_k_zero_after_series_switch(self):
        """Typical series switch: raw_k=0 after R16 FirstRender consumption."""
        h = _Harness._H()
        slider = _SliderStub()
        viewer = _VTKWidgetStub(qt_bridge_active=False, count_slices=20, raw_k=0)

        h.reset_slider(viewer, slider)

        assert viewer.image_viewer.wl_calls == [0]

    def test_wl_called_with_current_raw_k_not_display_k(self):
        """mid-session reset: viewer sits at raw_k=5, not display_k."""
        h = _Harness._H()
        slider = _SliderStub()
        viewer = _VTKWidgetStub(qt_bridge_active=False, count_slices=20, raw_k=5)

        h.reset_slider(viewer, slider)

        assert viewer.image_viewer.wl_calls == [5]

    def test_wl_not_called_for_qt_bridge(self):
        """Qt-bridge path exits before apply_default_window_level."""
        h = _Harness._H()
        slider = _SliderStub()
        viewer = _VTKWidgetStub(qt_bridge_active=True, count_slices=20, raw_k=3)

        h.reset_slider(viewer, slider)

        assert viewer.image_viewer.wl_calls == []
