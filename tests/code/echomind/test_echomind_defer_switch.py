"""Guard: EchoMind change_series defers the viewport switch to the next event-loop
turn (OPT-23, 2026-07-08) so the loading spinner paints before the synchronous
switch and the command-bus / IPC drain is not blocked.

Root cause: `ViewerWriteCommandAdapter.change_series` called
`method_change_series_on_viewer(...)` INLINE on the UI thread, unlike the real
drop handler (`_vw_dragdrop.dropEvent -> QTimer.singleShot(0, _do_series_switch)`),
so the spinner never painted and the whole switch (incl. the Advanced/VTK render)
blocked dispatch. Fix (flag AIPACS_ECHOMIND_DEFER_SWITCH, default on): schedule the
switch via QTimer.singleShot(0, ...); the deferred callback still runs the exact
same switch.

Headless: a fake PySide6.QtCore.QTimer captures singleShot without a Qt loop, so
this runs in the offscreen verify lane.
"""

import sys
import types

import pytest

from modules.EchoMind.secretary.command_envelope import CommandPlan
from modules.EchoMind.secretary.adapters.viewer_write_adapter import (
    ViewerWriteCommandAdapter,
)


@pytest.fixture
def capture_singleshot(monkeypatch):
    """Capture QTimer.singleShot(ms, cb) calls without running them."""
    calls = []
    try:
        from PySide6.QtCore import QTimer  # real Qt present
        monkeypatch.setattr(
            QTimer, "singleShot",
            staticmethod(lambda ms, cb: calls.append((ms, cb))),
        )
    except Exception:
        qtcore = types.ModuleType("PySide6.QtCore")

        class QTimer:  # minimal fake
            @staticmethod
            def singleShot(ms, cb):
                calls.append((ms, cb))

        qtcore.QTimer = QTimer
        ps = sys.modules.get("PySide6") or types.ModuleType("PySide6")
        ps.QtCore = qtcore
        monkeypatch.setitem(sys.modules, "PySide6", ps)
        monkeypatch.setitem(sys.modules, "PySide6.QtCore", qtcore)
    return calls


class _Spinner:
    def __init__(self):
        self.shown = []

    def show_loading(self, text):
        self.shown.append(text)


class _VtkW:
    def __init__(self):
        self.id_vtk_widget = "v0"
        self.slider = None
        self.viewport_spinner = _Spinner()
        self.calls = []  # records method_change_series_on_viewer(...)

    def method_change_series_on_viewer(self, **kwargs):
        self.calls.append(kwargs)


class _Node:
    def __init__(self, vtk_w):
        self.vtk_widget = vtk_w
        self.slider = None


class _Tab:
    def __init__(self, nodes):
        self.lst_nodes_viewer = nodes
        self._pending_action_id = None
        self._pending_action_series = None


def _adapter_and_widget():
    vtk_w = _VtkW()
    tab = _Tab([_Node(vtk_w)])
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)
    return adapter, vtk_w


def _plan():
    return CommandPlan(
        action="change_series",
        entities={"series_number": 5, "viewport": 0, "show_spinner": False},
    )


def test_default_defers_switch_via_singleshot(capture_singleshot, monkeypatch):
    monkeypatch.delenv("AIPACS_ECHOMIND_DEFER_SWITCH", raising=False)
    adapter, vtk_w = _adapter_and_widget()

    res = adapter.change_series(_plan(), {})

    # Command returns OK immediately ("async load dispatched").
    assert res.ok is True
    # The switch was NOT run inline — it was scheduled on the event loop.
    assert vtk_w.calls == [], "switch must not run synchronously in dispatch"
    assert len(capture_singleshot) == 1
    ms, cb = capture_singleshot[0]
    assert ms == 0
    # Running the deferred callback performs the real switch with the right series.
    cb()
    assert len(vtk_w.calls) == 1
    assert vtk_w.calls[0]["series_index"] == 5


def test_flag_off_runs_switch_inline(capture_singleshot, monkeypatch):
    monkeypatch.setenv("AIPACS_ECHOMIND_DEFER_SWITCH", "0")
    adapter, vtk_w = _adapter_and_widget()

    res = adapter.change_series(_plan(), {})

    assert res.ok is True
    # Legacy: switch ran inline; no deferral scheduled.
    assert len(vtk_w.calls) == 1
    assert vtk_w.calls[0]["series_index"] == 5
    assert capture_singleshot == []


def test_spinner_shown_before_switch(capture_singleshot, monkeypatch):
    monkeypatch.delenv("AIPACS_ECHOMIND_DEFER_SWITCH", raising=False)
    vtk_w = _VtkW()
    tab = _Tab([_Node(vtk_w)])
    adapter = ViewerWriteCommandAdapter(get_active_patient_tab=lambda: tab)
    plan = CommandPlan(
        action="change_series",
        entities={"series_number": 3, "viewport": 0, "show_spinner": True},
    )
    adapter.change_series(plan, {})
    # Spinner requested, and the switch is still deferred (paints first).
    assert vtk_w.viewport_spinner.shown == ["Switching series..."]
    assert vtk_w.calls == []
    assert len(capture_singleshot) == 1
