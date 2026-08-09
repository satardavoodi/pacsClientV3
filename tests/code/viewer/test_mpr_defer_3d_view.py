"""Guard: L1 MPR-open optimization — defer the 3D VRT view (2026-06-28).

Opening Standard (Zeta) MPR froze the GUI thread ~5-11.5 s (live: 8.1 s on a
512x512x588 CBCT) building four VTK render windows synchronously — the 3D VRT's
GPU upload + first ray-cast being the single biggest cost. L1 builds the three
diagnostic 2D planes first and defers ``_create_3d_view`` to a ``QTimer.singleShot(0)``
idle callback so the planes paint first.

GEOMETRY SAFETY (the whole point of this guard): only the *timing* of the 3D
view's construction changes. Each view computes its own camera/reslice per-view
(independent of creation order), and the all-views post-passes are 2D-only by
design — so a 3D built a moment later changes NO geometry/orientation/reslice/
crosshair/baseline. These pins fail if a future edit makes a post-pass depend on
the 3D view (which would re-introduce a geometry coupling).

Flag ``AIPACS_MPR_DEFER_3D`` (default OFF => byte-identical synchronous 4-panel
build). Teardown-safe: closing MPR during the brief defer must never touch a
deleted VTK/Qt object.

Source-pins the wiring + geometry-safety + a behavioral check of the teardown-safe
callback (the actual VTK render needs the clinical lane).
"""
import re
import types
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _views_src() -> str:
    return (
        _repo_root() / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_views.py"
    ).read_text(encoding="utf-8")


def _layout_src() -> str:
    return (
        _repo_root() / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_layout.py"
    ).read_text(encoding="utf-8")


def _orientation_src() -> str:
    return (
        _repo_root() / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_orientation.py"
    ).read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# Flag — default ON (2026-06-28: flipped to fix the MPR-open freeze; kill switch =0).
# ----------------------------------------------------------------------------
def test_flag_default_on():
    src = _views_src()
    assert '_MPR_DEFER_3D = (_os.getenv("AIPACS_MPR_DEFER_3D", "1")' in src
    # default "1" resolves truthy (deferred 3D is the default path)
    blk = src[src.find("_MPR_DEFER_3D ="):src.find("_MPR_DEFER_3D =") + 200]
    assert 'not in ("0", "false", "no", "off")' in blk


# ----------------------------------------------------------------------------
# _setup_ui — deferred branch builds the 3 planes + placeholder + schedules the
# idle callback; the legacy synchronous 4-panel branch is preserved unchanged.
# ----------------------------------------------------------------------------
def test_setup_ui_defers_only_the_3d_view():
    src = _views_src()
    fn = src.find("def _setup_ui(")
    assert fn != -1
    body = src[fn:fn + 4000]
    # deferred branch
    elif_at = body.find("elif _MPR_DEFER_3D:")
    assert elif_at != -1
    branch = body[elif_at:body.find("else:", elif_at)]
    # the THREE 2D planes are built synchronously...
    assert "_create_axial_view(views_layout, 0, 0)" in branch
    assert "_create_sagittal_view(views_layout, 1, 0)" in branch
    assert "_create_coronal_view(views_layout, 1, 1)" in branch
    # ...the 3D is NOT built synchronously in this branch (it's deferred)...
    assert "_create_3d_view(" not in branch
    # ...a placeholder holds its cell, and the build is scheduled on the idle turn.
    assert "_install_deferred_3d_placeholder(views_layout, 0, 1)" in branch
    assert "self._deferred_3d_pending = True" in branch
    assert "QTimer.singleShot(0, self._build_deferred_3d_view)" in branch
    # legacy synchronous branch preserved verbatim (the 4-panel order incl. 3D).
    legacy = body[body.find("else:", elif_at):]
    assert "_create_axial_view(views_layout, 0, 0)" in legacy
    assert "_create_3d_view(views_layout, 0, 1)" in legacy
    assert "_create_sagittal_view(views_layout, 1, 0)" in legacy
    assert "_create_coronal_view(views_layout, 1, 1)" in legacy


# ----------------------------------------------------------------------------
# Teardown-safe callback + placeholder.
# ----------------------------------------------------------------------------
def test_deferred_callback_is_teardown_safe():
    src = _views_src()
    fn = src.find("def _build_deferred_3d_view(self):")
    assert fn != -1
    # Bound the window at the NEXT def rather than a fixed character count: the
    # 2026-08-01 loading-presentation work (busy dialog + repaint-suppressed swap)
    # pushed `_create_3d_view` past the old 1600-char slice even though the call is
    # still there. A positional window silently rots as the function grows.
    _end = src.find("\n    def ", fn + 1)
    body = src[fn:_end if _end != -1 else len(src)]
    assert "getattr(self, '_deferred_3d_pending', False)" in body   # bail if cleaned up
    assert "self._deferred_3d_pending = False" in body              # one-shot
    assert "self._create_3d_view(layout, 0, 1)" in body             # builds the real 3D into (0,1)
    assert "except RuntimeError" in body                            # swallow deleted-object race
    # placeholder install exists and labels the cell
    assert "def _install_deferred_3d_placeholder(self, layout, row, col):" in src
    assert "Rendering 3D" in src
    assert "self._deferred_3d_placeholder = placeholder" in src


def test_cleanup_clears_pending_flag():
    src = _layout_src()
    fn = src.find("def cleanup(self):")
    assert fn != -1
    # Window widened 600 -> 3000 on 2026-08-01: the lifecycle work prepended the
    # `_mpr_closed = True` stop-accepting flag (plus its rationale comment) above
    # this assignment, pushing it past the old slice. The assertion itself is
    # unchanged — cleanup() must still clear the deferred-3D pending flag early,
    # before any VTK teardown, so the idle callback bails.
    body = src[fn:fn + 3000]
    assert "self._deferred_3d_pending = False" in body
    # ...and it must still come before the first VTK release.
    assert body.index("self._deferred_3d_pending = False") < body.index("_full_teardown")


# ----------------------------------------------------------------------------
# GEOMETRY SAFETY — the all-views post-passes must stay 2D-only, so deferring the
# 3D cannot change any geometry/orientation/reslice/baseline.
# ----------------------------------------------------------------------------
def test_post_passes_are_2d_only():
    views = _views_src()
    orient = _orientation_src()
    # native-plane interpolation iterates only the 2D reslice panes
    assert "for view in ('axial', 'sagittal', 'coronal'):" in views
    # baseline-camera capture ("single source of truth for oblique") is 2D-only
    bc = orient.find("def _capture_baseline_camera_state(")
    assert bc != -1
    assert "for view_name in ['axial', 'sagittal', 'coronal']:" in orient[bc:bc + 600]
    # window/level is 2D-only (the 3D VRT uses its own preset built in _create_3d_view)
    wl = orient.find("def _apply_window_level(")
    assert wl != -1
    assert "for view_name in ['axial', 'sagittal', 'coronal']:" in orient[wl:wl + 400]


# ----------------------------------------------------------------------------
# Behavioral — the deferred callback's one-shot + teardown-race handling, bound
# to a fake self (no VTK/Qt render window needed).
# ----------------------------------------------------------------------------
def test_deferred_callback_behavioral():
    pytest.importorskip("PySide6")
    pytest.importorskip("vtkmodules")
    try:
        from modules.mpr.zeta_mpr.mpr_viewer._mpr_views import _MprViewsMixin
    except Exception as exc:  # pragma: no cover - import env dependent
        pytest.skip(f"_mpr_views import unavailable: {exc}")

    build = _MprViewsMixin._build_deferred_3d_view

    class FakeLayout:
        def __init__(self):
            self.removed = []

        def removeWidget(self, w):
            self.removed.append(w)

    class FakePlaceholder:
        def __init__(self):
            self.parented_none = False
            self.deleted = False

        def setParent(self, p):
            self.parented_none = p is None

        def deleteLater(self):
            self.deleted = True

    # Case A: not pending -> no build (cleaned up before the idle turn).
    calls = []
    fake = types.SimpleNamespace(_deferred_3d_pending=False)
    fake._create_3d_view = lambda *a, **k: calls.append(a)
    build.__get__(fake)()
    assert calls == []

    # Case B: pending -> builds once into cell (0,1), clears the flag, drops placeholder.
    layout = FakeLayout()
    ph = FakePlaceholder()
    built = []
    fake = types.SimpleNamespace(
        _deferred_3d_pending=True, _views_layout=layout, _deferred_3d_placeholder=ph
    )
    fake._create_3d_view = lambda lay, r, c: built.append((lay, r, c))
    build.__get__(fake)()
    assert fake._deferred_3d_pending is False
    assert built == [(layout, 0, 1)]            # exactly the 3D cell, once
    assert ph in layout.removed and ph.deleted  # placeholder removed
    # idempotent: a second fire (e.g. duplicate timer) does nothing.
    built.clear()
    build.__get__(fake)()
    assert built == []

    # Case C: build raises RuntimeError (MPR closed mid-defer) -> swallowed, no raise.
    fake = types.SimpleNamespace(
        _deferred_3d_pending=True, _views_layout=FakeLayout(), _deferred_3d_placeholder=None
    )

    def _raise(*a, **k):
        raise RuntimeError("Internal C++ object already deleted")

    fake._create_3d_view = _raise
    build.__get__(fake)()  # must not raise
    assert fake._deferred_3d_pending is False
