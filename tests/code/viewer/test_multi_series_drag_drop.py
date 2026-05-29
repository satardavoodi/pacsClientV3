"""
Multi-Series Drag-Drop Stress Test
====================================

Simulates the crash scenario:
  1. Open a patient with multiple series (creates viewers)
  2. Switch series rapidly on multiple viewers (simulates drag-drop)
  3. Scroll through slices on each viewer
  4. Test at different layouts (1×1, 2×2, 1×3)
  5. Test both Advanced (VTK) and Fast (PyDicom) viewer backends
  6. Reference lines active across viewers

Run:
    .venv\\Scripts\\python.exe -m pytest tests/viewer/test_multi_series_drag_drop.py -v -s

This test requires a QApplication and VTK — it creates real VTK widgets.
"""

from __future__ import annotations

import gc
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

import pytest

# ── project root ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("test_multi_drop")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")


# ═══════════════════════════════════════════════════════════════════
#  Qt / VTK availability check
# ═══════════════════════════════════════════════════════════════════

_SKIP_REASON = None
try:
    # Configure graphics fallback BEFORE any Qt/VTK imports (mirrors main.py)
    from aipacs_runtime import resolve_graphics_profile, build_windows_graphics_environment
    if sys.platform == "win32":
        profile = resolve_graphics_profile()
        graphics_env = build_windows_graphics_environment(profile, frozen=False)
        for key in graphics_env.get("clear_env", []):
            os.environ.pop(key, None)
        for key, value in (graphics_env.get("env") or {}).items():
            os.environ[key] = value
        path_prefixes = list(graphics_env.get("path_prefixes") or [])
        if path_prefixes:
            current_path = os.environ.get("PATH", "")
            os.environ["PATH"] = os.pathsep.join(path_prefixes + current_path.split(os.pathsep))
            if hasattr(os, "add_dll_directory"):
                for prefix in path_prefixes:
                    try:
                        os.add_dll_directory(prefix)
                    except Exception:
                        pass
except Exception as e:
    logger.warning("Graphics fallback config failed: %s", e)

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, Qt
except ImportError:
    _SKIP_REASON = "PySide6 not available"

try:
    import vtkmodules.all as vtk
except ImportError:
    _SKIP_REASON = "VTK not available"

try:
    import numpy as np
except ImportError:
    _SKIP_REASON = "numpy not available"

pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def qapp():
    """Create or reuse a QApplication for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])
    yield app


def _make_synthetic_vtk_image(dims=(128, 128, 30), spacing=(1.0, 1.0, 2.0)):
    """Create a synthetic vtkImageData (gradient volume)."""
    img = vtk.vtkImageData()
    img.SetDimensions(*dims)
    img.SetSpacing(*spacing)
    img.SetOrigin(0.0, 0.0, 0.0)
    img.AllocateScalars(vtk.VTK_SHORT, 1)

    scalars = img.GetPointData().GetScalars()
    n = dims[0] * dims[1] * dims[2]
    for i in range(n):
        z = i // (dims[0] * dims[1])
        scalars.SetValue(i, int((z / max(dims[2] - 1, 1)) * 2000 - 1000))

    # Add DirectionMatrix field data (identity)
    dm = vtk.vtkDoubleArray()
    dm.SetName("DirectionMatrix")
    dm.SetNumberOfTuples(16)
    for i in range(4):
        for j in range(4):
            dm.SetValue(i * 4 + j, 1.0 if i == j else 0.0)
    img.GetFieldData().AddArray(dm)
    return img


def _make_synthetic_metadata(series_number: int, num_slices: int = 30,
                              modality: str = "CT"):
    """Create synthetic metadata matching what ImageViewer2D expects."""
    instances = []
    for i in range(num_slices):
        instances.append({
            "instance_number": i + 1,
            "instance_path": f"Instance_{i+1:04d}.dcm",
            "image_position_patient": [0.0, 0.0, float(i * 2.0)],
            "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            "pixel_spacing": [1.0, 1.0],
            "rows": 128,
            "columns": 128,
            "slice_thickness": 2.0,
            "window_width": 2000,
            "window_center": 0,
            "rescale_slope": 1.0,
            "rescale_intercept": 0.0,
            "is_rgb": False,
        })
    return {
        "series": {
            "series_number": str(series_number),
            "series_name": f"Series {series_number}",
            "series_description": f"Test Series {series_number}",
            "series_uid": f"1.2.3.{series_number}",
            "modality": modality,
            "image_count": num_slices,
            "thumbnail_path": "",
            "series_path": "",
            "series_thk": "2.0",
        },
        "instances": instances,
        "patient": {
            "patient_name": "Test Patient",
            "patient_id": "TEST001",
        },
        "study": {
            "study_uid": "1.2.3.999",
            "study_description": "Test Study",
        },
    }


def _make_metadata_fixed():
    """Create metadata_fixed dict for ImageViewer2D corner actors."""
    return {
        "patient_name": "Test^Patient",
        "patient_id": "TEST001",
        "patient_sex": "M",
        "patient_age": "050Y",
        "study_date": "2026-04-05",
        "study_time": "12:00:00",
        "institution_name": "Test Hospital",
        "study_uid": "1.2.3.999",
        "patient_pk": 1,
        "study_pk": 1,
    }


# ═══════════════════════════════════════════════════════════════════
#  Test helpers — create VTK widgets without full PatientWidget
# ═══════════════════════════════════════════════════════════════════

class _MinimalViewer:
    """
    Minimal wrapper that creates a VTKWidget-like object for testing
    series switch + reference lines WITHOUT the full PatientWidget stack.
    """

    def __init__(self, qapp, widget_id: int = 0):
        from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
        self.vtk_widget = VTKWidget(parent=None, height_viewer=400, patient_widget=None)
        self.vtk_widget.id_vtk_widget = widget_id
        self.vtk_widget.resize(400, 400)

    def load_series(self, vtk_image_data, metadata, metadata_fixed=None):
        """Load a series using the VTK path (ImageViewer2D)."""
        from modules.viewer.advanced.viewer_2d import ImageViewer2D

        if metadata_fixed is None:
            metadata_fixed = _make_metadata_fixed()

        w = self.vtk_widget
        if w.image_viewer is not None:
            # Reuse existing viewer (fast path)
            try:
                w.image_viewer.reset_image_viewer(vtk_image_data, metadata)
                w.image_viewer.apply_default_window_level(0)
                w.last_series_show = metadata["series"]["series_number"]
                return True
            except Exception as e:
                logger.warning("Fast path failed, recreating: %s", e)
                w.cleanup_image_viewer()

        # Create new viewer
        w.image_viewer = ImageViewer2D(
            w.render_window, w.interactor, w.height_viewer,
            vtk_image_data, metadata, metadata_fixed or {},
            w.apply_default_filter, vtk_widget=w,
        )
        w.image_viewer.apply_default_window_level(0)
        new_renderer = w.image_viewer.GetRenderer()
        w.render_window.AddRenderer(new_renderer)
        w.render_window.Render()
        w.last_series_show = metadata["series"]["series_number"]
        return True

    def load_series_qt(self, metadata, metadata_fixed=None):
        """Load a series using the Qt/PyDicom path."""
        from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
        from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
        from modules.viewer.fast.lightweight_2d_pipeline import (
            Lightweight2DPipeline, PipelineConfig,
        )

        w = self.vtk_widget
        if w.image_viewer is not None:
            w.cleanup_image_viewer()

        qt_viewer = QtSliceViewer(parent=w)
        pipeline = Lightweight2DPipeline(config=PipelineConfig())
        bridge = QtViewerBridge(
            qt_viewer=qt_viewer, pipeline=pipeline,
            metadata=metadata, metadata_fixed=metadata_fixed or {},
        )
        w.image_viewer = bridge
        w._qt_viewer_widget = qt_viewer
        w._qt_bridge_active = True
        w._active_backend = "pydicom_qt"
        w.last_series_show = metadata["series"]["series_number"]
        return True

    def scroll_to(self, slice_index: int):
        """Scroll to a slice (exercises set_slice path)."""
        w = self.vtk_widget
        if w.image_viewer is None:
            return
        try:
            max_slice = w.get_count_of_slices() - 1
            clamped = max(0, min(slice_index, max_slice))
            if w._qt_bridge_active:
                w.image_viewer.set_slice(clamped)
            else:
                w.image_viewer.SetSlice(clamped)
                w.image_viewer.Render()
        except Exception as e:
            logger.error("scroll_to failed: %s", e)
            raise

    def cleanup(self):
        w = self.vtk_widget
        try:
            if w.image_viewer is not None:
                w.cleanup_image_viewer()
            w.close()
            w.deleteLater()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
#  Reference line test helper
# ═══════════════════════════════════════════════════════════════════

def _test_reference_line_across_viewers(viewers: List[_MinimalViewer]):
    """
    Simulate reference line computation across all viewers.
    This exercises the same code path as PatientWidget.manage_reference_line().
    """
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import reference_line
    import numpy as np

    if len(viewers) < 2:
        return

    src = viewers[0]
    src_iv = src.vtk_widget.image_viewer
    if src_iv is None:
        return

    src_meta = getattr(src_iv, "metadata", None)
    if not isinstance(src_meta, dict):
        return

    instances = src_meta.get("instances", [])
    if not instances:
        return

    src_slice = 0
    try:
        src_slice = src_iv.GetSlice()
    except Exception:
        src_slice = 0

    if src_slice >= len(instances):
        return

    src_inst = instances[src_slice]
    iop = src_inst.get("image_orientation_patient")
    ipp = src_inst.get("image_position_patient")
    if iop is None or ipp is None:
        return

    # Compute source plane normal
    row = np.asarray(iop[3:6], dtype=float)
    col = np.asarray(iop[0:3], dtype=float)
    normal = np.cross(row, col)
    norm_len = np.linalg.norm(normal)
    if norm_len < 1e-9:
        return
    normal /= norm_len

    # For each target viewer, compute intersection
    for tv in viewers[1:]:
        tv_iv = tv.vtk_widget.image_viewer
        if tv_iv is None:
            continue
        tv_meta = getattr(tv_iv, "metadata", None)
        if not isinstance(tv_meta, dict):
            continue
        tv_instances = tv_meta.get("instances", [])
        if not tv_instances:
            continue
        t_slice = 0
        try:
            t_slice = tv_iv.GetSlice()
        except Exception:
            t_slice = 0
        if t_slice >= len(tv_instances):
            continue
        t_inst = tv_instances[t_slice]
        t_iop = t_inst.get("image_orientation_patient")
        t_ipp = t_inst.get("image_position_patient")
        if t_iop is None or t_ipp is None:
            continue
        # Just verify we can access the data without crash
        t_row = np.asarray(t_iop[3:6], dtype=float)
        t_col = np.asarray(t_iop[0:3], dtype=float)
        t_normal = np.cross(t_row, t_col)
        t_origin = np.asarray(t_ipp, dtype=float)
        logger.debug("Reference line: src→target normal dot=%.3f", abs(np.dot(normal, t_normal / (np.linalg.norm(t_normal) + 1e-12))))


# ═══════════════════════════════════════════════════════════════════
#  TESTS
# ═══════════════════════════════════════════════════════════════════

class TestMultiSeriesDragDrop:
    """Stress-test multi-series drag-drop + scroll + reference lines."""

    NUM_SERIES = 4
    SCROLL_STEPS = 10

    @pytest.fixture
    def series_data(self):
        """Create synthetic series data."""
        data = []
        for i in range(1, self.NUM_SERIES + 1):
            vtk_img = _make_synthetic_vtk_image(dims=(128, 128, 30 + i * 5))
            meta = _make_synthetic_metadata(series_number=i, num_slices=30 + i * 5)
            data.append((vtk_img, meta))
        return data

    # ──────────────────────────────────────────────────────────────
    #  S1: Rapid series switch on SINGLE viewer (VTK backend)
    # ──────────────────────────────────────────────────────────────

    def test_s1_rapid_switch_single_viewer_vtk(self, qapp, series_data):
        """S1: Switch 4 series rapidly on a single VTK viewer — no crash."""
        viewer = _MinimalViewer(qapp, widget_id=0)
        crash_count = 0
        try:
            for round_num in range(3):
                for vtk_img, meta in series_data:
                    try:
                        viewer.load_series(vtk_img, meta)
                        # Scroll through some slices
                        for s in range(0, min(10, 30), 3):
                            viewer.scroll_to(s)
                    except Exception as e:
                        crash_count += 1
                        logger.error("S1 crash round=%d series=%s: %s",
                                     round_num, meta["series"]["series_number"], e)
                        logger.error(traceback.format_exc())
            qapp.processEvents()
        finally:
            viewer.cleanup()
        assert crash_count == 0, f"S1: {crash_count} crashes during rapid VTK switch"

    # ──────────────────────────────────────────────────────────────
    #  S2: Rapid series switch on SINGLE viewer (Qt/Fast backend)
    # ──────────────────────────────────────────────────────────────

    def test_s2_rapid_switch_single_viewer_qt(self, qapp, series_data):
        """S2: Switch 4 series rapidly on a single Qt viewer — no crash."""
        viewer = _MinimalViewer(qapp, widget_id=0)
        crash_count = 0
        try:
            for round_num in range(3):
                for _, meta in series_data:
                    try:
                        viewer.load_series_qt(meta)
                    except Exception as e:
                        crash_count += 1
                        logger.error("S2 crash round=%d series=%s: %s",
                                     round_num, meta["series"]["series_number"], e)
            qapp.processEvents()
        finally:
            viewer.cleanup()
        assert crash_count == 0, f"S2: {crash_count} crashes during rapid Qt switch"

    # ──────────────────────────────────────────────────────────────
    #  S3: Multiple viewers, different series, simultaneous (VTK)
    # ──────────────────────────────────────────────────────────────

    def test_s3_multi_viewer_vtk_2x2(self, qapp, series_data):
        """S3: 2×2 layout with 4 viewers, each showing different series (VTK)."""
        viewers = [_MinimalViewer(qapp, widget_id=i) for i in range(4)]
        crash_count = 0
        try:
            # Load each viewer with a different series
            for i, (vtk_img, meta) in enumerate(series_data):
                try:
                    viewers[i].load_series(vtk_img, meta)
                except Exception as e:
                    crash_count += 1
                    logger.error("S3 initial load viewer=%d: %s", i, e)

            qapp.processEvents()

            # Reference line computation across all viewers
            try:
                _test_reference_line_across_viewers(viewers)
            except Exception as e:
                crash_count += 1
                logger.error("S3 reference line: %s", e)

            # Now rapidly switch all viewers to different series
            for round_num in range(3):
                for i in range(4):
                    new_idx = (i + round_num + 1) % len(series_data)
                    vtk_img, meta = series_data[new_idx]
                    try:
                        viewers[i].load_series(vtk_img, meta)
                    except Exception as e:
                        crash_count += 1
                        logger.error("S3 switch round=%d viewer=%d: %s", round_num, i, e)

                qapp.processEvents()

                # Scroll each viewer
                for i in range(4):
                    for s in range(0, 15, 5):
                        try:
                            viewers[i].scroll_to(s)
                        except Exception as e:
                            crash_count += 1
                            logger.error("S3 scroll viewer=%d slice=%d: %s", i, s, e)

                # Reference lines after each round
                try:
                    _test_reference_line_across_viewers(viewers)
                except Exception as e:
                    crash_count += 1
                    logger.error("S3 reference line round=%d: %s", round_num, e)

            qapp.processEvents()
        finally:
            for v in viewers:
                v.cleanup()
        assert crash_count == 0, f"S3: {crash_count} crashes in 2×2 VTK layout"

    # ──────────────────────────────────────────────────────────────
    #  S4: Multiple viewers, different series, simultaneous (Qt)
    # ──────────────────────────────────────────────────────────────

    def test_s4_multi_viewer_qt_2x2(self, qapp, series_data):
        """S4: 2×2 layout with 4 viewers, Qt fast backend."""
        viewers = [_MinimalViewer(qapp, widget_id=i) for i in range(4)]
        crash_count = 0
        try:
            for i, (_, meta) in enumerate(series_data):
                try:
                    viewers[i].load_series_qt(meta)
                except Exception as e:
                    crash_count += 1
                    logger.error("S4 initial load viewer=%d: %s", i, e)

            qapp.processEvents()

            # Switch rapidly
            for round_num in range(3):
                for i in range(4):
                    new_idx = (i + round_num + 1) % len(series_data)
                    _, meta = series_data[new_idx]
                    try:
                        viewers[i].load_series_qt(meta)
                    except Exception as e:
                        crash_count += 1
                        logger.error("S4 switch round=%d viewer=%d: %s", round_num, i, e)

                qapp.processEvents()

        finally:
            for v in viewers:
                v.cleanup()
        assert crash_count == 0, f"S4: {crash_count} crashes in 2×2 Qt layout"

    # ──────────────────────────────────────────────────────────────
    #  S5: Mixed backend — switch between VTK and Qt on same viewer
    # ──────────────────────────────────────────────────────────────

    def test_s5_mixed_backend_switch(self, qapp, series_data):
        """S5: Switch between VTK and Qt backend on same viewer — common crash scenario."""
        viewer = _MinimalViewer(qapp, widget_id=0)
        crash_count = 0
        try:
            for round_num in range(5):
                vtk_img, meta = series_data[round_num % len(series_data)]
                try:
                    if round_num % 2 == 0:
                        # VTK path
                        viewer.load_series(vtk_img, meta)
                        viewer.scroll_to(5)
                    else:
                        # Qt path
                        viewer.load_series_qt(meta)
                except Exception as e:
                    crash_count += 1
                    logger.error("S5 mixed switch round=%d backend=%s: %s",
                                 round_num, "VTK" if round_num % 2 == 0 else "Qt", e)
                    logger.error(traceback.format_exc())
                qapp.processEvents()
        finally:
            viewer.cleanup()
        assert crash_count == 0, f"S5: {crash_count} crashes during mixed backend switch"

    # ──────────────────────────────────────────────────────────────
    #  S6: Series switch during scroll (race condition test)
    # ──────────────────────────────────────────────────────────────

    def test_s6_switch_during_scroll_vtk(self, qapp, series_data):
        """S6: Switch series WHILE scrolling on VTK viewer."""
        viewer = _MinimalViewer(qapp, widget_id=0)
        crash_count = 0
        try:
            vtk_img0, meta0 = series_data[0]
            viewer.load_series(vtk_img0, meta0)

            for round_num in range(5):
                # Start scrolling
                for s in range(0, 20, 2):
                    try:
                        viewer.scroll_to(s)
                    except Exception as e:
                        crash_count += 1
                        logger.error("S6 scroll round=%d slice=%d: %s", round_num, s, e)
                        break

                # Mid-scroll: switch to a different series
                new_idx = (round_num + 1) % len(series_data)
                vtk_img, meta = series_data[new_idx]
                try:
                    viewer.load_series(vtk_img, meta)
                except Exception as e:
                    crash_count += 1
                    logger.error("S6 switch round=%d: %s", round_num, e)

                qapp.processEvents()

        finally:
            viewer.cleanup()
        assert crash_count == 0, f"S6: {crash_count} crashes during scroll+switch"

    # ──────────────────────────────────────────────────────────────
    #  S7: 1×3 layout with reference lines and rapid switching
    # ──────────────────────────────────────────────────────────────

    def test_s7_1x3_layout_with_reference_lines(self, qapp, series_data):
        """S7: 1×3 layout, reference lines active, rapid series switching."""
        viewers = [_MinimalViewer(qapp, widget_id=i) for i in range(3)]
        crash_count = 0
        try:
            # Initial load
            for i in range(3):
                vtk_img, meta = series_data[i]
                try:
                    viewers[i].load_series(vtk_img, meta)
                except Exception as e:
                    crash_count += 1

            qapp.processEvents()

            for round_num in range(5):
                # Reference lines
                try:
                    _test_reference_line_across_viewers(viewers)
                except Exception as e:
                    crash_count += 1
                    logger.error("S7 refline round=%d: %s", round_num, e)

                # Scroll all viewers
                for v in viewers:
                    for s in [0, 5, 10, 15, 20]:
                        try:
                            v.scroll_to(s)
                        except Exception as e:
                            crash_count += 1

                # Reference lines after scroll
                try:
                    _test_reference_line_across_viewers(viewers)
                except Exception as e:
                    crash_count += 1
                    logger.error("S7 refline post-scroll round=%d: %s", round_num, e)

                # Switch one viewer
                target_viewer = round_num % 3
                new_series = (target_viewer + round_num + 1) % len(series_data)
                vtk_img, meta = series_data[new_series]
                try:
                    viewers[target_viewer].load_series(vtk_img, meta)
                except Exception as e:
                    crash_count += 1
                    logger.error("S7 switch round=%d viewer=%d: %s", round_num, target_viewer, e)

                qapp.processEvents()

        finally:
            for v in viewers:
                v.cleanup()
        assert crash_count == 0, f"S7: {crash_count} crashes in 1×3 + reference lines"

    # ──────────────────────────────────────────────────────────────
    #  S8: Cleanup + recreation (simulates MPR open/close cycle)
    # ──────────────────────────────────────────────────────────────

    def test_s8_cleanup_and_recreate_after_mpr(self, qapp, series_data):
        """S8: Simulate MPR lifecycle — cleanup viewer, recreate, then rapid switch.
        
        This simulates: open series → open MPR → close MPR → drag-drop series.
        The crash often happens because VTK resources are not fully released
        after MPR cleanup, and the next viewer creation hits stale state.
        """
        viewer = _MinimalViewer(qapp, widget_id=0)
        crash_count = 0
        try:
            for round_num in range(3):
                # Phase 1: Load initial series (normal viewing)
                vtk_img, meta = series_data[0]
                try:
                    viewer.load_series(vtk_img, meta)
                    viewer.scroll_to(10)
                except Exception as e:
                    crash_count += 1
                    logger.error("S8 initial load round=%d: %s", round_num, e)
                    logger.error(traceback.format_exc())

                qapp.processEvents()

                # Phase 2: Simulate MPR cleanup (destroy viewer internals)
                try:
                    w = viewer.vtk_widget
                    if w.image_viewer is not None:
                        w.image_viewer.cleanup()
                        del w.image_viewer
                        w.image_viewer = None
                    w.last_series_show = None
                    gc.collect()
                except Exception as e:
                    crash_count += 1
                    logger.error("S8 cleanup round=%d: %s", round_num, e)

                qapp.processEvents()

                # Phase 3: Rapid series switching (post-MPR drag-drop)
                for i, (vtk_img, meta) in enumerate(series_data):
                    try:
                        viewer.load_series(vtk_img, meta)
                        viewer.scroll_to(5)
                    except Exception as e:
                        crash_count += 1
                        logger.error("S8 post-mpr switch round=%d series=%d: %s",
                                     round_num, i, e)
                        logger.error(traceback.format_exc())

                qapp.processEvents()

        finally:
            viewer.cleanup()
        assert crash_count == 0, f"S8: {crash_count} crashes in MPR lifecycle simulation"

    # ──────────────────────────────────────────────────────────────
    #  S9: Multi-viewer cleanup+recreate (full MPR scenario)
    # ──────────────────────────────────────────────────────────────

    def test_s9_multi_viewer_mpr_lifecycle(self, qapp, series_data):
        """S9: 2×2 layout → MPR on one viewer → close MPR → rapid drops on all."""
        viewers = [_MinimalViewer(qapp, widget_id=i) for i in range(4)]
        crash_count = 0
        try:
            # Load all viewers
            for i in range(4):
                vtk_img, meta = series_data[i % len(series_data)]
                viewers[i].load_series(vtk_img, meta)

            qapp.processEvents()

            # Simulate MPR on viewer 0 (cleanup its viewer internals)
            w0 = viewers[0].vtk_widget
            if w0.image_viewer is not None:
                w0.image_viewer.cleanup()
                del w0.image_viewer
                w0.image_viewer = None
            w0.last_series_show = None
            gc.collect()

            qapp.processEvents()

            # Now rapidly drop series on ALL viewers (including the one that had MPR)
            for round_num in range(3):
                for i in range(4):
                    new_idx = (i + round_num) % len(series_data)
                    vtk_img, meta = series_data[new_idx]
                    try:
                        viewers[i].load_series(vtk_img, meta)
                    except Exception as e:
                        crash_count += 1
                        logger.error("S9 switch round=%d viewer=%d: %s", round_num, i, e)
                        logger.error(traceback.format_exc())

                qapp.processEvents()

                # Scroll + reference lines
                for i in range(4):
                    try:
                        viewers[i].scroll_to(round_num * 3)
                    except Exception as e:
                        crash_count += 1

                try:
                    _test_reference_line_across_viewers(viewers)
                except Exception as e:
                    crash_count += 1
                    logger.error("S9 refline round=%d: %s", round_num, e)

        finally:
            for v in viewers:
                v.cleanup()
        assert crash_count == 0, f"S9: {crash_count} crashes in multi-viewer MPR lifecycle"

    # ──────────────────────────────────────────────────────────────
    #  S10: Renderer accumulation test
    # ──────────────────────────────────────────────────────────────

    def test_s10_renderer_accumulation(self, qapp, series_data):
        """S10: Verify renderers don't accumulate after repeated series switches.
        
        VTK segfaults when too many renderers are attached to a single
        render window. Each switch that creates a new ImageViewer2D adds
        a renderer — they must be removed during cleanup.
        """
        viewer = _MinimalViewer(qapp, widget_id=0)
        try:
            rw = viewer.vtk_widget.render_window

            for i in range(10):
                vtk_img, meta = series_data[i % len(series_data)]
                viewer.load_series(vtk_img, meta)
                qapp.processEvents()

            renderer_count = rw.GetRenderers().GetNumberOfItems()
            logger.info("S10: renderer count after 10 switches = %d", renderer_count)
            # After proper cleanup, should have at most 2 renderers
            # (current + possibly one pending cleanup)
            assert renderer_count <= 3, (
                f"S10: renderer accumulation detected: {renderer_count} renderers "
                f"after 10 series switches (expected ≤3)"
            )
        finally:
            viewer.cleanup()

    # ──────────────────────────────────────────────────────────────
    #  S11: GC pressure during rapid switching
    # ──────────────────────────────────────────────────────────────

    def test_s11_gc_pressure_during_switch(self, qapp, series_data):
        """S11: Force GC between rapid switches to catch use-after-free."""
        viewer = _MinimalViewer(qapp, widget_id=0)
        crash_count = 0
        try:
            for round_num in range(5):
                for vtk_img, meta in series_data:
                    try:
                        viewer.load_series(vtk_img, meta)
                        gc.collect()  # Force GC to expose UAF
                        viewer.scroll_to(5)
                        gc.collect()
                    except Exception as e:
                        crash_count += 1
                        logger.error("S11 round=%d: %s", round_num, e)
                        logger.error(traceback.format_exc())
                qapp.processEvents()
        finally:
            viewer.cleanup()
        assert crash_count == 0, f"S11: {crash_count} crashes under GC pressure"

    # ──────────────────────────────────────────────────────────────
    #  S12: Use VTKWidget.switch_series() directly (real app code path)
    # ──────────────────────────────────────────────────────────────

    def test_s12_real_switch_series_method(self, qapp, series_data):
        """S12: Exercise VTKWidget.switch_series() — the actual app code path."""
        viewer = _MinimalViewer(qapp, widget_id=0)
        crash_count = 0
        try:
            for round_num in range(3):
                for vtk_img, meta in series_data:
                    try:
                        meta_fixed = _make_metadata_fixed()
                        viewer.vtk_widget.switch_series(
                            vtk_image_data=vtk_img,
                            metadata=meta,
                            metadata_fixed=meta_fixed,
                            series_index=meta["series"]["series_number"],
                        )
                        qapp.processEvents()
                        # Scroll
                        for s in range(0, 10, 3):
                            viewer.scroll_to(s)
                    except Exception as e:
                        crash_count += 1
                        logger.error("S12 round=%d series=%s: %s",
                                     round_num, meta["series"]["series_number"], e)
                        logger.error(traceback.format_exc())
                qapp.processEvents()
        finally:
            viewer.cleanup()
        assert crash_count == 0, f"S12: {crash_count} crashes using real switch_series()"

    # ──────────────────────────────────────────────────────────────
    #  S13: Interleaved processEvents between switches (timer simulation)
    # ──────────────────────────────────────────────────────────────

    def test_s13_interleaved_events_during_switch(self, qapp, series_data):
        """S13: processEvents after every operation to simulate timer callbacks.
        
        In the real app, QTimer callbacks (progressive display, reference lines,
        stale guard) fire between operations. processEvents() triggers these.
        """
        viewers = [_MinimalViewer(qapp, widget_id=i) for i in range(4)]
        crash_count = 0
        try:
            for i in range(4):
                vtk_img, meta = series_data[i]
                meta_fixed = _make_metadata_fixed()
                try:
                    viewers[i].vtk_widget.switch_series(
                        vtk_image_data=vtk_img,
                        metadata=meta,
                        metadata_fixed=meta_fixed,
                        series_index=meta["series"]["series_number"],
                    )
                except Exception as e:
                    crash_count += 1
                    logger.error("S13 initial load viewer=%d: %s", i, e)
                qapp.processEvents()  # Let timers fire

            # Rapid switching with events between each
            for round_num in range(5):
                for i in range(4):
                    new_idx = (i + round_num + 1) % len(series_data)
                    vtk_img, meta = series_data[new_idx]
                    meta_fixed = _make_metadata_fixed()
                    try:
                        viewers[i].vtk_widget.switch_series(
                            vtk_image_data=vtk_img,
                            metadata=meta,
                            metadata_fixed=meta_fixed,
                            series_index=meta["series"]["series_number"],
                        )
                    except Exception as e:
                        crash_count += 1
                        logger.error("S13 switch round=%d viewer=%d: %s",
                                     round_num, i, e)
                    # Process events between each viewer switch — this is key.
                    # In the real app, switching viewer 0 triggers timers that
                    # may call Render() on viewer 1 while we're about to switch it.
                    qapp.processEvents()

                # Scroll all viewers
                for i in range(4):
                    try:
                        viewers[i].scroll_to(round_num * 3)
                    except Exception as e:
                        crash_count += 1
                    qapp.processEvents()

        finally:
            for v in viewers:
                v.cleanup()
        assert crash_count == 0, f"S13: {crash_count} crashes with interleaved events"

    # ──────────────────────────────────────────────────────────────
    #  S14: VTK→Qt→VTK backend flip using switch_series
    # ──────────────────────────────────────────────────────────────

    def test_s14_backend_flip_via_switch_series(self, qapp, series_data):
        """S14: Flip backend VTK→Qt→VTK on same viewer using switch_series.
        
        This is the exact crash scenario: the Qt backend was active (from fast mode),
        then switch_series cleans up the Qt bridge and creates a VTK ImageViewer2D
        using the same render_window. If the Qt viewer left stale state on the
        render_window, the VTK path crashes.
        """
        viewer = _MinimalViewer(qapp, widget_id=0)
        crash_count = 0
        try:
            for round_num in range(5):
                vtk_img, meta = series_data[round_num % len(series_data)]
                meta_fixed = _make_metadata_fixed()

                if round_num % 2 == 0:
                    # Qt path
                    try:
                        viewer.load_series_qt(meta)
                    except Exception as e:
                        crash_count += 1
                        logger.error("S14 Qt round=%d: %s", round_num, e)
                else:
                    # VTK path via switch_series (needs to clean up Qt bridge first)
                    try:
                        viewer.vtk_widget.switch_series(
                            vtk_image_data=vtk_img,
                            metadata=meta,
                            metadata_fixed=meta_fixed,
                            series_index=meta["series"]["series_number"],
                        )
                    except Exception as e:
                        crash_count += 1
                        logger.error("S14 VTK round=%d: %s", round_num, e)
                        logger.error(traceback.format_exc())

                qapp.processEvents()

                # Scroll after VTK switch only (Qt minimal setup doesn't support scroll)
                if round_num % 2 == 1:
                    try:
                        viewer.scroll_to(5)
                    except Exception as e:
                        crash_count += 1
                        logger.error("S14 scroll round=%d: %s", round_num, e)

        finally:
            viewer.cleanup()
        assert crash_count == 0, f"S14: {crash_count} crashes during backend flip"

    # ──────────────────────────────────────────────────────────────
    #  S15: MPR cleanup → switch_series → reference lines (full cycle)
    # ──────────────────────────────────────────────────────────────

    def test_s15_full_mpr_to_drag_drop_cycle(self, qapp, series_data):
        """S15: Full lifecycle — load VTK → MPR cleanup → switch_series → ref lines.
        
        This is the exact crash sequence reported by the user:
        1. Open a study (VTK viewers)
        2. Open MPR (viewer internals cleaned up)
        3. Close MPR (viewer recreated)
        4. Drag-drop multiple series rapidly
        5. With reference lines active
        """
        viewers = [_MinimalViewer(qapp, widget_id=i) for i in range(4)]
        crash_count = 0
        try:
            # Step 1: Load initial series on all viewers
            for i in range(4):
                vtk_img, meta = series_data[i]
                meta_fixed = _make_metadata_fixed()
                try:
                    viewers[i].vtk_widget.switch_series(
                        vtk_image_data=vtk_img,
                        metadata=meta,
                        metadata_fixed=meta_fixed,
                        series_index=meta["series"]["series_number"],
                    )
                except Exception as e:
                    crash_count += 1
                    logger.error("S15 initial load viewer=%d: %s", i, e)

            qapp.processEvents()
            _test_reference_line_across_viewers(viewers)

            # Step 2: MPR cleanup on viewer 0 (simulate _restore_selected_viewer)
            w0 = viewers[0].vtk_widget
            if w0.image_viewer is not None:
                try:
                    # This mirrors toolbar_manager._restore_selected_viewer() flow:
                    # cleanup viewer → delete → gc
                    w0.image_viewer.cleanup()
                    del w0.image_viewer
                    w0.image_viewer = None
                except Exception as e:
                    crash_count += 1
                    logger.error("S15 MPR cleanup: %s", e)

            w0.last_series_show = None
            gc.collect()
            qapp.processEvents()

            # Step 3: Rapid drag-drop on all viewers (including the one that had MPR)
            for round_num in range(5):
                for i in range(4):
                    new_idx = (i + round_num) % len(series_data)
                    vtk_img, meta = series_data[new_idx]
                    meta_fixed = _make_metadata_fixed()
                    try:
                        viewers[i].vtk_widget.switch_series(
                            vtk_image_data=vtk_img,
                            metadata=meta,
                            metadata_fixed=meta_fixed,
                            series_index=meta["series"]["series_number"],
                        )
                    except Exception as e:
                        crash_count += 1
                        logger.error("S15 drop round=%d viewer=%d: %s",
                                     round_num, i, e)
                        logger.error(traceback.format_exc())

                    qapp.processEvents()

                # Scroll each viewer + reference lines
                for i in range(4):
                    try:
                        viewers[i].scroll_to(round_num * 2)
                    except Exception as e:
                        crash_count += 1

                try:
                    _test_reference_line_across_viewers(viewers)
                except Exception as e:
                    crash_count += 1
                    logger.error("S15 refline round=%d: %s", round_num, e)

        finally:
            for v in viewers:
                v.cleanup()
        assert crash_count == 0, f"S15: {crash_count} crashes in full MPR → drag-drop cycle"


# ═══════════════════════════════════════════════════════════════════
#  Standalone runner
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", "--tb=short"]))
