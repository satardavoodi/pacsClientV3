"""Phase 0/1 guards for the stitching refactor (2026-06-08).

Covers:
- T5: the worker runs end-to-end on preloaded images (no disk read) and emits a
      float32 result — guards the float32 + image-reuse path.
- T6: source/structure guards — dead code stays quarantined, the module uses
      logging (not print, which crashed on the cp1256 console), the blend is
      float32, the widget wires worker reuse + lifecycle, and the plugin mirror
      is in parity.

See docs/reports/STITCHING_MODULE_REVIEW_2026-06-08.md.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[2]
for p in (str(_ROOT), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

_MODDIR = _ROOT / "modules" / "stitching"
_MIRROR = (_ROOT / "builder" / "plugin package" / "packages" / "stitching"
           / "payload" / "python" / "modules" / "stitching")
_ACTIVE_FILES = [
    "__init__.py", "blend_engine.py", "stitch_engine.py", "stitch_worker.py",
    "stitching_widget.py", "landmark_interactor_style.py", "landmark_store.py",
]


# ======================================================================
#  T5 — worker integration (preloaded images, float32 result)
# ======================================================================

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _make_sitk(origin, size=(50, 50), base=1000.0):
    yy, xx = np.mgrid[0:size[1], 0:size[0]].astype(np.float32)
    arr = base + xx + 2.0 * yy  # strictly positive ramp
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing((1.0, 1.0))
    img.SetOrigin(origin)
    return img


def _store_with_pairs(shift_x=30.0, jitter=0.0):
    from modules.stitching.landmark_store import LandmarkStore
    store = LandmarkStore()
    # 4 corresponding pairs; right = left + (shift_x, 0). ``jitter`` perturbs
    # one point so residuals exceed the 4 mm threshold (to exercise the gate).
    pts = [(10, 10), (40, 10), (10, 40), (40, 40)]
    for i, (lx, ly) in enumerate(pts):
        rx = lx + shift_x + (jitter if i == 0 else 0.0)
        store.add_pair(0, (float(lx), float(ly)), (float(rx), float(ly)))
    return store


def test_worker_runs_on_preloaded_images_float32(qapp):
    from modules.stitching.stitch_worker import StitchWorker

    img_a = _make_sitk((0.0, 0.0))
    img_b = _make_sitk((30.0, 0.0))  # overlaps A in x∈[30,49]
    store = _store_with_pairs()

    worker = StitchWorker(
        series_dirs=["", ""],            # must NOT be read (preloaded given)
        landmark_store=store,
        transform_type="rigid",
        preloaded_images=[img_a, img_b],
    )
    results, errors = [], []
    worker.completed.connect(results.append)
    worker.error.connect(errors.append)
    worker.run()  # synchronous — exercises the full pipeline in-thread

    assert not errors, f"worker errored: {errors}"
    assert len(results) == 1
    out = results[0]
    assert isinstance(out, sitk.Image) and out.GetDimension() == 2
    arr = sitk.GetArrayFromImage(out)
    assert arr.dtype == np.float32
    assert np.all(np.isfinite(arr))


def test_preview_mode_caps_canvas_and_skips_gate(qapp):
    """Quick preview: caps the canvas to preview_max_dim, uses the fast blend,
    and must NOT hang on the accuracy gate even when residuals exceed 4 mm."""
    from modules.stitching.stitch_worker import StitchWorker

    img_a = _make_sitk((0.0, 0.0), size=(80, 80))
    img_b = _make_sitk((40.0, 0.0), size=(80, 80))
    # jitter=15 mm on one point → residuals exceed 4 mm → the full pipeline
    # would pause here; preview must skip the gate and finish on its own.
    store = _store_with_pairs(shift_x=40.0, jitter=15.0)

    worker = StitchWorker(
        series_dirs=["", ""],
        landmark_store=store,
        transform_type="rigid",
        preloaded_images=[img_a, img_b],
        preview=True,
        preview_max_dim=40,
    )
    results, errors = [], []
    worker.completed.connect(results.append)
    worker.error.connect(errors.append)
    worker.run()

    assert not errors, f"preview errored: {errors}"
    assert len(results) == 1, "preview must complete without the accuracy gate"
    out = results[0]
    assert max(out.GetSize()) <= 41, f"canvas not capped: {out.GetSize()}"
    assert sitk.GetArrayFromImage(out).dtype == np.float32


# ======================================================================
#  T6 — structure / source guards
# ======================================================================

def test_dead_code_quarantined():
    assert not (_MODDIR / "canvas_builder.py").exists(), "canvas_builder.py must be quarantined"
    assert not (_MODDIR / "stitch_controller.py").exists(), "stitch_controller.py must be quarantined"


def test_stitchcontroller_not_exported():
    import modules.stitching as st
    assert "StitchController" not in getattr(st, "__all__", [])
    assert not hasattr(st, "StitchController")


def test_no_print_in_active_modules():
    """print() crashed on the user's cp1256 console (Unicode arrows); the
    module must log instead."""
    offenders = {}
    for name in _ACTIVE_FILES:
        src = (_MODDIR / name).read_text(encoding="utf-8")
        hits = re.findall(r"(?<!\.)\bprint\s*\(", src)
        if hits:
            offenders[name] = len(hits)
    assert not offenders, f"print() left in: {offenders}"


def test_blend_is_float32_and_logs():
    src = (_MODDIR / "blend_engine.py").read_text(encoding="utf-8")
    assert "import logging" in src
    assert "np.float32" in src
    # the float64 casts that doubled memory must be gone from the blend
    # (match real usage, not the word in the module docstring)
    assert "np.float64" not in src, "blend_engine must not use np.float64"
    assert ".astype(np.float64)" not in src


def test_worker_float32_and_preloaded():
    src = (_MODDIR / "stitch_worker.py").read_text(encoding="utf-8")
    assert "preloaded_images" in src
    assert ".astype(np.float64)" not in src, "worker must keep arrays float32"
    assert "import logging" in src


def test_widget_wires_reuse_and_lifecycle():
    src = (_MODDIR / "stitching_widget.py").read_text(encoding="utf-8")
    assert "preloaded_images=preloaded" in src, "widget must feed preloaded images"
    assert "self._worker.finished.connect" in src, "worker must be released on finish"
    assert "_on_worker_finished" in src


def test_widget_has_quick_preview_and_hint():
    """Phase 3/4 UX: fast preview button + the 'need N more pairs' hint."""
    src = (_MODDIR / "stitching_widget.py").read_text(encoding="utf-8")
    assert "_btn_quick_preview" in src
    assert "_on_quick_preview" in src
    assert "preview=True" in src, "quick preview must run the worker in preview mode"
    assert "_lbl_compute_hint" in src, "missing the compute-disabled hint label"


def test_worker_has_preview_and_cap():
    src = (_MODDIR / "stitch_worker.py").read_text(encoding="utf-8")
    assert "preview" in src and "preview_max_dim" in src
    assert "n_image_feather_blend" in src, "preview must use the fast feather blend"


# ======================================================================
#  Phase 4 — V2 theme reskin guards
# ======================================================================

_FAKE_THEME = {
    "window_bg": "#0e1726", "panel_bg": "#111927", "panel_alt_bg": "#1d2533",
    "panel_deep_bg": "#0d1420", "border": "#33405a", "text_primary": "#f8fafc",
    "text_muted": "#93a4b7", "accent": "#3b82f6", "accent_hover": "#60a5fa",
    "accent_pressed": "#1d4ed8", "button_text": "#ffffff",
    "menu_active_bg": "#31486a", "warning": "#f59e0b", "danger": "#ef4444",
    "danger_hover": "#f87171", "success": "#10b981", "success_hover": "#34d399",
    "info": "#06b6d4",
}


def test_app_stylesheet_is_themed_and_valid():
    from modules.stitching.stitching_widget import _build_app_stylesheet
    qss = _build_app_stylesheet(_FAKE_THEME)
    assert qss.count("{") == qss.count("}"), "unbalanced braces in stylesheet"
    assert "{t[" not in qss and "{'" not in qss, "unsubstituted token placeholder"
    # tokens resolved through, not hard-coded slate
    assert _FAKE_THEME["accent"] in qss
    assert _FAKE_THEME["window_bg"] in qss


def test_widget_reskinned_to_theme_tokens():
    src = (_MODDIR / "stitching_widget.py").read_text(encoding="utf-8")
    assert "get_theme_manager" in src
    assert "_build_app_stylesheet" in src
    assert "_apply_theme_styles" in src
    assert "themeChanged.connect" in src, "must re-skin on live theme change"
    assert "_DARK_STYLE" not in src, "hard-coded dark style must be gone"
    # No 6-digit hex literals (the only colour left is the #000 image viewport).
    assert not re.findall(r"#[0-9a-fA-F]{6}\b", src), "hard-coded hex remains in widget"


def test_plugin_mirror_parity():
    if not _MIRROR.exists():
        pytest.skip("plugin payload mirror not present")
    # dead files must not linger in the payload either
    assert not (_MIRROR / "canvas_builder.py").exists()
    assert not (_MIRROR / "stitch_controller.py").exists()
    for name in _ACTIVE_FILES:
        canonical = (_MODDIR / name).read_text(encoding="utf-8", errors="ignore")
        mirror = (_MIRROR / name)
        assert mirror.exists(), f"{name} missing from plugin payload mirror"
        assert mirror.read_text(encoding="utf-8", errors="ignore") == canonical, (
            f"plugin payload mirror stale: {name}"
        )
