"""Guard tests — OPT-48 Phase 1: MPR open latency on high slice counts.

Measured on patient 52827 (512x512x672 CT): MPR open = ~21 s wall,
`standard_mpr_construct_ms=17944`, main thread blocked ~30 s. Phase 1 removes
~10.5 s of that WITHOUT touching geometry:

  #2 scalar range computed on the loader's worker thread; the widget reads it
     from the PRE-FLIP volume (a flip permutes voxels, so the range is identical)
  #4 the 3D VRT is built ON DEMAND for large volumes (click the 3D cell) instead
     of auto-building ~9 s of GPU work right after the 2D panes appear
  #5 a busy dialog explains the remaining GUI-thread construction

Every change is flag-gated with the legacy path preserved; the diagnostic 2D
MPR planes (axial/sagittal/coronal) are untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIEWS = ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_views.py"
WIDGET = ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "widget.py"
TOOLBAR = (
    ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)


# ---------------------------------------------------------------------------
# #4 — pure on-demand-VRT decision (importable without Qt/VTK? _mpr_views needs
#      VTK, so the decision is re-implemented-free: we test it via source pins
#      plus a direct import when VTK is available.)
# ---------------------------------------------------------------------------

def _load_decision():
    """Import the pure helper if VTK/PySide6 are importable; else skip."""
    try:
        from modules.mpr.zeta_mpr.mpr_viewer._mpr_views import should_defer_vrt_to_demand
        return should_defer_vrt_to_demand
    except Exception:
        return None


def test_vrt_on_demand_decision_thresholds():
    fn = _load_decision()
    if fn is None:
        import pytest
        pytest.skip("VTK/PySide6 not importable in this environment")
    # large volume -> on demand
    assert fn(672, enabled=True, threshold=200) is True
    assert fn(200, enabled=True, threshold=200) is True
    # small volume -> auto-build (legacy)
    assert fn(199, enabled=True, threshold=200) is False
    assert fn(30, enabled=True, threshold=200) is False
    # kill switch -> always legacy
    assert fn(672, enabled=False, threshold=200) is False
    # garbage -> legacy (never break the open)
    assert fn(None, enabled=True, threshold=200) is False
    assert fn("abc", enabled=True, threshold=200) is False


def test_vrt_on_demand_flags_default_on_with_threshold():
    src = VIEWS.read_text(encoding="utf-8", errors="replace")
    assert 'getenv("AIPACS_MPR_VRT_ON_DEMAND", "1")' in src
    assert 'AIPACS_MPR_VRT_ON_DEMAND_SLICES", "200"' in src
    assert "def should_defer_vrt_to_demand(" in src


def test_large_volume_does_not_autobuild_vrt():
    """The deferred-build timer must be SKIPPED when on-demand is chosen."""
    src = VIEWS.read_text(encoding="utf-8", errors="replace")
    block = src[src.index("self._vrt_on_demand = should_defer_vrt_to_demand"):]
    block = block[: block.index("def ")]
    assert "if self._vrt_on_demand:" in block
    # the auto-build is gated on NOT on-demand (small volumes only). Deliberately
    # written as a second `if` rather than an `else:` — the pre-existing L1 guard
    # test slices this branch at the first `else:`.
    assert "if not self._vrt_on_demand:" in block
    idx_guard = block.index("if not self._vrt_on_demand:")
    idx_timer = block.index("QTimer.singleShot(0, self._build_deferred_3d_view)")
    assert idx_timer > idx_guard, "auto-build must be gated on the small-volume path"


def test_placeholder_is_clickable_when_on_demand():
    src = VIEWS.read_text(encoding="utf-8", errors="replace")
    ph = src[src.index("def _install_deferred_3d_placeholder"): src.index("def _build_deferred_3d_view")]
    assert "on_demand" in ph
    assert "click to render" in ph
    assert "mousePressEvent" in ph
    # SUPERSEDED 2026-08-01: the click used to call the builder INLINE. It now
    # schedules it with QTimer.singleShot(0, ...) so the "Rendering 3D…" state
    # actually paints before the (multi-second, GUI-thread-blocking) VTK build.
    # The invariant this test exists for — clicking the placeholder triggers the
    # deferred 3D build — is unchanged; only the dispatch mechanism moved.
    assert "QTimer.singleShot(0, _self._build_deferred_3d_view)" in ph
    assert "PointingHandCursor" in ph
    # legacy text preserved for the auto-build path
    assert "Rendering 3D…" in ph


def test_2d_planes_untouched_by_on_demand():
    """The three diagnostic planes are still built unconditionally."""
    src = VIEWS.read_text(encoding="utf-8", errors="replace")
    block = src[src.index("elif _MPR_DEFER_3D:"):]
    block = block[: block.index("else:\n            self._create_axial_view(views_layout, 0, 0)\n            self._create_3d_view")]
    for creator in ("_create_axial_view", "_create_sagittal_view", "_create_coronal_view"):
        assert f"self.{creator}(views_layout" in block, f"{creator} must always run"


# ---------------------------------------------------------------------------
# #2 — scalar range off the GUI thread
# ---------------------------------------------------------------------------

def test_widget_reads_scalar_range_from_source_volume():
    src = WIDGET.read_text(encoding="utf-8", errors="replace")
    assert 'AIPACS_MPR_SCALAR_RANGE_FROM_SOURCE", "1"' in src
    block = src[src.index("_range_from_source"): src.index("# Extract Direction Matrix")]
    # reads the PRE-FLIP volume (identical values, warmed off-thread)
    assert "vtk_image_data.GetScalarRange()" in block
    # and still falls back to the flipped output
    assert "self.image_data.GetScalarRange()" in block


def test_loader_warms_scalar_range_off_thread():
    src = TOOLBAR.read_text(encoding="utf-8", errors="replace")
    worker = src[src.index("class _VtkLoadWorker"): src.index("worker = _VtkLoadWorker()")]
    assert "AIPACS_MPR_WARM_SCALAR_RANGE" in worker
    assert "GetScalarRange()" in worker
    assert "_vol.GetScalarRange()" in worker


# ---------------------------------------------------------------------------
# #5 — build progress feedback
# ---------------------------------------------------------------------------

def test_build_progress_dialog_is_gated_and_closed():
    src = TOOLBAR.read_text(encoding="utf-8", errors="replace")
    start = src.index("OPT-48 #5")
    block = src[start: src.index("[MPR-OPEN-KPI]", start)]
    assert 'AIPACS_MPR_BUILD_PROGRESS", "1"' in block
    assert 'AIPACS_MPR_BUILD_PROGRESS_SLICES", "200"' in block
    assert "_zdim >= _prog_min" in block         # only for slow (large) volumes
    assert "processEvents()" in block            # painted before the blocking build
    assert "finally:" in block                   # dialog always closed
    assert "_build_dlg.close()" in block
    assert "setCancelButton(None)" in block      # the build cannot be cancelled midway


def test_open_kpi_reports_new_fields():
    src = TOOLBAR.read_text(encoding="utf-8", errors="replace")
    kpi = src[src.index("[MPR-OPEN-KPI]"):]
    kpi = kpi[: kpi.index("except Exception")]
    for field in ("standard_mpr_construct_ms", "slices=", "vrt_on_demand=", "warm_scalar_range="):
        assert field in kpi
