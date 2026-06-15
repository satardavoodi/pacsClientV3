"""Guard for the per-instance DICOM window fix (46370 series 61, 2026-06-15).

Bug: a heterogeneous series (Siemens CSI spectroscopy mixing SPECTRUM secondary
captures at WC2048/WW4096 with REFERENCEIMAGE frames at WC301/WW637) kept slice 0's
window across all slices, so the reference images rendered near-black under a
4096-wide window. Fix: on stack scroll, when no manual window is set, re-apply each
slice's OWN DICOM WC/WW (`_FAST_PER_INSTANCE_WINDOW`, default on). For a homogeneous
series every slice's WC/WW equals slice 0's, so the scroll-cache guard short-circuits
and output is byte-identical.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
BRIDGE = REPO / "modules/viewer/fast/qt_viewer_bridge.py"


def _func_src(src, name):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node)
    return None


# ── backend really returns each instance's OWN window ────────────────────────

def test_backend_get_default_window_level_is_per_instance():
    from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
    # Heterogeneous fake series: slice 0 = SPECTRUM window, slice 1 = REFERENCEIMAGE.
    fake = SimpleNamespace(
        _slices=[
            SimpleNamespace(window_width=4096.0, window_center=2048.0),
            SimpleNamespace(window_width=637.0, window_center=301.0),
        ],
        _clamp_index=lambda i: max(0, min(int(i), 1)),
        get_pixel_array=lambda i: None,
    )
    ww0, wc0 = PyDicom2DBackend.get_default_window_level(fake, 0)
    ww1, wc1 = PyDicom2DBackend.get_default_window_level(fake, 1)
    assert (ww0, wc0) == (4096.0, 2048.0)
    # The reference frame must report ITS OWN window, not slice 0's 4096/2048.
    assert (ww1, wc1) == (637.0, 301.0)


# ── homogeneous series: every slice has the same window (fix is a no-op) ──────

def test_backend_homogeneous_series_window_unchanged_across_slices():
    from modules.viewer.fast.pydicom_2d_backend import PyDicom2DBackend
    fake = SimpleNamespace(
        _slices=[SimpleNamespace(window_width=400.0, window_center=40.0) for _ in range(5)],
        _clamp_index=lambda i: max(0, min(int(i), 4)),
        get_pixel_array=lambda i: None,
    )
    wins = {PyDicom2DBackend.get_default_window_level(fake, i) for i in range(5)}
    assert wins == {(400.0, 40.0)}  # identical across all slices -> scroll-cache no-op


# ── flag default ON + scroll handler applies it, gated by manual-WL ──────────

def test_flag_default_on():
    src = BRIDGE.read_text(encoding="utf-8-sig")
    assert "AIPACS_FAST_PER_INSTANCE_WINDOW" in src
    assert "'AIPACS_FAST_PER_INSTANCE_WINDOW', '1'" in src  # default ON
    assert "not in ('0', 'false', 'no', 'off')" in src


def test_set_slice_applies_per_instance_window_gated():
    src = BRIDGE.read_text(encoding="utf-8-sig")
    impl = _func_src(src, "_set_slice_impl")
    assert impl is not None
    assert "_FAST_PER_INSTANCE_WINDOW" in impl
    # Must be skipped when the user set a custom window (manual W/L persists).
    assert "not self.flag_set_custom_window_level" in impl
    # Only re-windows on a SUBSTANTIAL difference (normal series stays stable).
    assert "_window_differs_substantially" in impl
    assert "apply_default_window_level(idx)" in impl


def test_window_differs_substantially_threshold():
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge as B
    f = B._window_differs_substantially
    # Spectroscopy case: 4096-wide vs 637-wide (6.4x) -> re-window.
    assert f(4096, 2048, 637, 301) is True
    # Identical -> no re-window.
    assert f(400, 40, 400, 40) is False
    # Minor per-slice variation in a normal series -> stay stable (no re-window).
    assert f(400, 40, 410, 42) is False
    # Large level shift at same width -> re-window.
    assert f(400, 40, 400, 260) is True


def test_apply_default_window_level_uses_per_slice_default():
    """apply_default_window_level must read get_default_window_level(idx) (per-slice),
    not a fixed series window, and stay guarded by the scroll cache."""
    src = BRIDGE.read_text(encoding="utf-8-sig")
    fn = _func_src(src, "apply_default_window_level")
    assert fn is not None
    assert "get_default_window_level(idx)" in fn
    assert "_wl_scroll_cache_ww" in fn  # scroll-cache guard keeps homogeneous no-op
