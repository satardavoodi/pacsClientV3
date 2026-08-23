"""MPR teardown must run on EVERY destruction path (2026-08-19).

FOUND BY AUDITING A REAL READING SESSION (patient 54921, pid 340640). The
teardown itself was excellent — `_MprLayoutMixin.cleanup()` releases GPU
resources, finalizes the render windows, drops the flipped host volume and
breaks the interactor-style reference cycles — but it was reachable from
exactly ONE place: the toolbar's MPR toggle.

The log ledger (MPR "init started" vs "cleanup() completed"):

    pid 340640 : 4 opened, 2 freed
    all pids   : 14 opened, 6 freed

and the smoking gun, all in one process:

    12:57:02  MPR opened  (never toggled off)
    15:35:03  close_patient
    17:45:19  toggle scan -> active_mpr_widget: None   (the widget is gone)
              ...no cleanup() logged anywhere in between

THE TRAP THIS SUITE EXISTS TO PIN: a `closeEvent` hook alone does NOT fix
this. Qt does not call `closeEvent` when a parent is destroyed or when a
widget is merely re-parented away — which is exactly how all three leaking
paths worked (patient-tab close, layout rebuild, app exit). The fix has to be
the OWNERS calling `release_mpr_children` *before* they drop the widget, while
the GL context is still valid; `closeEvent` only covers explicit `close()`.

So `test_layout_teardown_releases_before_orphaning` and
`test_patient_close_releases_the_mpr_child` are the load-bearing guards. If
someone "simplifies" this down to just the `closeEvent`, they come back green
on the closeEvent tests and silently restore the leak.
"""
from __future__ import annotations

import ast
import inspect
import os
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.mpr.zeta_mpr.mpr_viewer import _mpr_lifecycle as life


# ── Fakes ───────────────────────────────────────────────────────────────────

class FakeMPR:
    """Anything with `cleanup` + `_mpr_closed` is an MPR viewer to the helper."""

    def __init__(self, raises: bool = False):
        self._mpr_closed = False
        self.cleanup_calls = 0
        self._raises = raises

    def cleanup(self):
        self.cleanup_calls += 1
        if self._raises:
            raise RuntimeError("Internal C++ object already deleted")
        self._mpr_closed = True


class FakeHost:
    """A viewport container that may or may not be hosting an MPR."""

    def __init__(self, **children):
        for name, value in children.items():
            setattr(self, name, value)


class ExplodingHost:
    """A host whose C++ object is gone — attribute access raises."""

    def __getattr__(self, name):
        raise RuntimeError("Internal C++ object already deleted")


# ══════════════════════════════════════════════════════════════════════════
# release_mpr_children — the helper the owners call
# ══════════════════════════════════════════════════════════════════════════

def test_a_hosted_mpr_is_torn_down():
    mpr = FakeMPR()
    assert life.release_mpr_children(FakeHost(_zeta_mpr_widget=mpr), "test") == 1
    assert mpr.cleanup_calls == 1
    assert mpr._mpr_closed is True


@pytest.mark.parametrize("attr", life.MPR_CHILD_ATTRS)
def test_every_known_child_slot_is_covered(attr):
    """The toolbar publishes the viewer under one of four names; missing any
    one of them means that MPR flavour still leaks."""
    mpr = FakeMPR()
    assert life.release_mpr_children(FakeHost(**{attr: mpr}), "test") == 1
    assert mpr.cleanup_calls == 1


def test_the_widget_itself_can_be_the_mpr():
    """`delete_widgets_in_layout` may hand us the MPR viewer directly."""
    mpr = FakeMPR()
    assert life.release_mpr_children(mpr, "test") == 1
    assert mpr.cleanup_calls == 1


def test_a_plain_widget_is_left_alone():
    assert life.release_mpr_children(FakeHost(), "test") == 0
    assert life.release_mpr_children(None, "test") == 0
    assert life.release_mpr_children(object(), "test") == 0


def test_an_already_closed_viewer_is_not_torn_down_twice():
    mpr = FakeMPR()
    mpr._mpr_closed = True
    assert life.release_mpr_children(FakeHost(_zeta_mpr_widget=mpr), "test") == 0
    assert mpr.cleanup_calls == 0, (
        "cleanup() is idempotent, but re-running it would make the log lie "
        "about how many viewers were actually released"
    )


def test_a_failing_teardown_never_raises_into_the_caller():
    """This runs on close paths — an exception would strand the caller
    mid-teardown with a half-destroyed layout."""
    mpr = FakeMPR(raises=True)
    life.release_mpr_children(FakeHost(_zeta_mpr_widget=mpr), "test")
    assert mpr.cleanup_calls == 1


def test_a_deleted_cpp_object_never_raises():
    """Attribute access on a destroyed Qt object raises; the helper must
    survive it, because that is a normal teardown race."""
    life.release_mpr_children(ExplodingHost(), "test")


def test_two_viewers_on_one_host_are_both_released():
    a, b = FakeMPR(), FakeMPR()
    host = FakeHost(_zeta_mpr_widget=a, _curved_mpr_widget=b)
    assert life.release_mpr_children(host, "test") == 2


def test_the_same_viewer_in_two_slots_is_released_once():
    mpr = FakeMPR()
    host = FakeHost(_zeta_mpr_widget=mpr, _mpr_widget=mpr)
    assert life.release_mpr_children(host, "test") == 1
    assert mpr.cleanup_calls == 1


def test_the_release_has_a_kill_switch(monkeypatch):
    monkeypatch.setenv("AIPACS_MPR_RELEASE_ON_DESTROY", "0")
    mpr = FakeMPR()
    assert life.release_mpr_children(FakeHost(_zeta_mpr_widget=mpr), "test") == 0
    assert mpr.cleanup_calls == 0


# ══════════════════════════════════════════════════════════════════════════
# Memory probe — so this question is answerable from the log next time
# ══════════════════════════════════════════════════════════════════════════

def test_the_memory_probe_returns_a_number(caplog):
    with caplog.at_level("INFO"):
        rss = life.mpr_memory_probe("unit_test", dims="(1,2,3)")
    if rss is not None:
        assert rss > 0
    assert any("[MPR-MEM]" in r.message or "[MPR-MEM]" in r.getMessage()
               for r in caplog.records)


def test_the_memory_probe_has_a_kill_switch(monkeypatch):
    monkeypatch.setenv("AIPACS_MPR_MEM_PROBE", "0")
    assert life.mpr_memory_probe("unit_test") is None


def test_the_memory_probe_never_raises_without_psutil(monkeypatch):
    monkeypatch.setattr(life, "_rss_mb", lambda: None)
    assert life.mpr_memory_probe("unit_test") is None


# ══════════════════════════════════════════════════════════════════════════
# closeEvent — the explicit-close half of the contract
# ══════════════════════════════════════════════════════════════════════════

def _src(module_rel: str) -> str:
    root = Path(inspect.getsourcefile(life)).parent
    return (root / module_rel).read_text(encoding="utf-8")


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


@pytest.fixture(scope="module")
def layout_tree():
    return ast.parse(_src("_mpr_layout.py"))


def test_the_layout_mixin_defines_closeevent(layout_tree):
    assert _func(layout_tree, "closeEvent") is not None, (
        "without closeEvent an explicit close() releases nothing"
    )


def test_closeevent_calls_cleanup_and_then_super(layout_tree):
    src = ast.unparse(_func(layout_tree, "closeEvent"))
    assert "self.cleanup()" in src
    assert "closeEvent" in src.split("self.cleanup()")[1], (
        "the base-class closeEvent must still run, or the widget never closes"
    )


def test_closeevent_reruns_nothing_on_an_already_closed_viewer():
    """Behavioural: bind the real method to a stub."""
    from modules.mpr.zeta_mpr.mpr_viewer._mpr_layout import _MprLayoutMixin

    calls = []
    stub = SimpleNamespace(
        _mpr_closed=False,
        cleanup=lambda: calls.append(1),
    )
    bound = types.MethodType(_MprLayoutMixin.closeEvent, stub)
    bound(SimpleNamespace(accept=lambda: None, ignore=lambda: None))
    assert calls == [1]

    stub._mpr_closed = True
    bound(SimpleNamespace(accept=lambda: None, ignore=lambda: None))
    assert calls == [1], "a close after a toolbar toggle must not re-tear-down"


def test_closeevent_survives_a_raising_cleanup():
    from modules.mpr.zeta_mpr.mpr_viewer._mpr_layout import _MprLayoutMixin

    def _boom():
        raise RuntimeError("already deleted")

    stub = SimpleNamespace(_mpr_closed=False, cleanup=_boom)
    bound = types.MethodType(_MprLayoutMixin.closeEvent, stub)
    bound(SimpleNamespace(accept=lambda: None, ignore=lambda: None))


def test_cleanup_measures_what_it_freed(layout_tree):
    src = ast.unparse(_func(layout_tree, "cleanup"))
    assert "mpr_memory_probe" in src
    assert "cleanup_begin" in src and "cleanup_end" in src, (
        "an open/close pair with no memory numbers is what made this question "
        "take a four-log reconstruction to answer"
    )


# ══════════════════════════════════════════════════════════════════════════
# THE LOAD-BEARING GUARDS: the owners release BEFORE they orphan
# ══════════════════════════════════════════════════════════════════════════

def _repo_root() -> Path:
    return Path(inspect.getsourcefile(life)).parents[4]


def test_layout_teardown_releases_before_orphaning():
    """`delete_widgets_in_layout` used to `setParent(None)` a cell hosting an
    open MPR — orphaning its volume, 4 render windows and GPU texture.

    Order is the whole point: after `setParent(None)` the GL context is gone
    and `ReleaseGraphicsResources()` cannot free the VRAM any more.
    """
    path = (_repo_root() / "PacsClient" / "pacs" / "patient_tab" / "utils" / "utils.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for fname in ("delete_widgets_in_layout", "delete_layout"):
        fn = _func(tree, fname)
        assert fn is not None, f"{fname} vanished"
        lines = ast.unparse(fn).splitlines()
        rel = next((i for i, l in enumerate(lines) if "_release_mpr_before_drop" in l), None)
        drop = next((i for i, l in enumerate(lines) if "setParent(None)" in l), None)
        assert rel is not None, f"{fname} does not release MPR children"
        assert drop is not None, f"{fname} no longer orphans widgets?"
        assert rel < drop, (
            f"{fname} releases the MPR AFTER setParent(None) — too late for "
            "ReleaseGraphicsResources() to reach a live GL context"
        )


def test_patient_close_releases_the_mpr_child():
    """Closing the patient tab cleaned the HOST viewer and nulled
    node.vtk_widget, but the MPR viewer hangs off the host as
    `_zeta_mpr_widget` and was never reached. This is the exact path the log
    caught: MPR open 12:57 -> close_patient 15:35 -> widget gone, no cleanup.
    """
    path = (_repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
            / "patient_widget_core" / "_pw_lifecycle.py")
    src = path.read_text(encoding="utf-8")
    assert "release_mpr_children" in src, (
        "patient-tab close must release an open MPR before dropping the host"
    )
    rel = src.index("release_mpr_children")
    host = src.index("cleanup_image_viewer")
    assert rel < host, (
        "the MPR child must be released BEFORE the host viewer is torn down"
    )


def test_the_helper_is_the_single_implementation():
    """Both owners must go through one helper, or they drift."""
    root = _repo_root()
    utils = (root / "PacsClient" / "pacs" / "patient_tab" / "utils"
             / "utils.py").read_text(encoding="utf-8")
    lifecycle = (root / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
                 / "patient_widget_core" / "_pw_lifecycle.py").read_text(encoding="utf-8")
    for src, name in ((utils, "utils.py"), (lifecycle, "_pw_lifecycle.py")):
        assert "_mpr_lifecycle import" in src or "_mpr_lifecycle" in src, (
            f"{name} should call the shared helper, not reimplement teardown"
        )


# ══════════════════════════════════════════════════════════════════════════
# The 3D mapper pinning the previous volume across an in-MPR series switch
# ══════════════════════════════════════════════════════════════════════════

def test_series_switch_repoints_the_3d_mapper_source():
    src = _src("_mpr_series.py")
    tree = ast.parse(src)
    fn = _func(tree, "_reload_with_series")
    assert fn is not None
    body = ast.unparse(fn)
    assert "'3d'" in body or '"3d"' in body, (
        "the 3D view must be re-pointed; the orthogonal loop covers only "
        "axial/sagittal/coronal, so 3D kept the PREVIOUS full volume"
    )


def test_series_switch_actually_repoints_the_3d_mapper():
    """Behavioural, with real VTK objects (no render window needed)."""
    vtk = pytest.importorskip("vtkmodules.all")
    from modules.mpr.zeta_mpr.mpr_viewer._mpr_series import _MprSeriesMixin

    def _volume(nz):
        src = vtk.vtkImageEllipsoidSource()
        src.SetWholeExtent(0, 7, 0, 7, 0, nz - 1)
        src.SetCenter(3, 3, nz // 2)
        src.SetRadius(3, 3, nz // 2)
        src.Update()
        return src.GetOutput()

    old, new = _volume(4), _volume(6)

    mapper = vtk.vtkGPUVolumeRayCastMapper()
    mapper.SetInputData(old)

    stub = SimpleNamespace(
        image_data=old,
        dims=(8, 8, 4),
        origin=(0, 0, 0),
        spacing=(1, 1, 1),
        scalar_range=(0, 1),
        current_position=[0, 0, 0],
        # Only the 3D pane exists, so the orthogonal loop is a no-op and this
        # test isolates exactly the new re-point block.
        viewers={"3d": {"mapper": mapper}},
        _deferred_3d_pending=False,
        _request_render=lambda *_a, **_k: None,
        _capture_baseline_camera_state=lambda *_a, **_k: None,
        _update_all_crosshairs=lambda *_a, **_k: None,
        _update_slice_positions=lambda *_a, **_k: None,
        _synchronize_oblique_views=lambda *_a, **_k: None,
        _update_slice_info_texts=lambda *_a, **_k: None,
        _needs_radiological_correction=lambda *_a, **_k: False,
        _get_camera_vectors_for_view=lambda *_a, **_k: ((0, 0, 1), (0, 0, 0), (0, 1, 0)),
    )
    bound = types.MethodType(_MprSeriesMixin._reload_with_series, stub)
    bound(new)

    got = mapper.GetInput()
    assert got is not None
    assert got.GetDimensions() == stub.image_data.GetDimensions(), (
        f"3D mapper still points at a {got.GetDimensions()} volume while the "
        f"viewer moved to {stub.image_data.GetDimensions()} — that is the old "
        "series pinned in host memory AND rendered next to three panes "
        "showing the new one"
    )


def test_series_switch_survives_a_missing_3d_view():
    """3D is deferred by default; a switch before it is built must not raise."""
    vtk = pytest.importorskip("vtkmodules.all")
    from modules.mpr.zeta_mpr.mpr_viewer._mpr_series import _MprSeriesMixin

    src = vtk.vtkImageEllipsoidSource()
    src.SetWholeExtent(0, 7, 0, 7, 0, 3)
    src.Update()

    stub = SimpleNamespace(
        image_data=None, dims=(8, 8, 4), origin=(0, 0, 0), spacing=(1, 1, 1),
        scalar_range=(0, 1), current_position=[0, 0, 0],
        viewers={},                      # nothing built yet
        _deferred_3d_pending=True,
        _request_render=lambda *_a, **_k: None,
        _capture_baseline_camera_state=lambda *_a, **_k: None,
        _update_all_crosshairs=lambda *_a, **_k: None,
        _update_slice_positions=lambda *_a, **_k: None,
        _synchronize_oblique_views=lambda *_a, **_k: None,
        _update_slice_info_texts=lambda *_a, **_k: None,
        _needs_radiological_correction=lambda *_a, **_k: False,
        _get_camera_vectors_for_view=lambda *_a, **_k: ((0, 0, 1), (0, 0, 0), (0, 1, 0)),
    )
    types.MethodType(_MprSeriesMixin._reload_with_series, stub)(src.GetOutput())


# ══════════════════════════════════════════════════════════════════════════
# The helper must stay cheap to import (it is pulled in on close paths)
# ══════════════════════════════════════════════════════════════════════════

def test_the_lifecycle_helper_imports_no_qt_or_vtk():
    tree = ast.parse(_src("_mpr_lifecycle.py"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    bad = [m for m in imported if "PySide" in m or "vtk" in m.lower()]
    assert not bad, (
        f"the lifecycle helper is imported from layout/close paths and must "
        f"stay light; found {bad}"
    )
