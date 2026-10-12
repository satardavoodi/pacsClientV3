"""Prewarm one native pane per event-loop turn and retire on teardown."""
from types import SimpleNamespace
from unittest.mock import Mock
from modules.mpr.zeta_mpr.mpr_viewer import _mpr_views as module


def test_prewarm_yields_between_panes_and_stops_after_close(monkeypatch):
    scheduled = []
    monkeypatch.setattr(module, '_MPR_PREWARM', True)
    monkeypatch.setattr(module.QTimer, 'singleShot', lambda *args: scheduled.append(args[-1]))
    state = SimpleNamespace(_mpr_closed=False, viewers={
        name: {'widget': Mock(), 'mapper': Mock()} for name in ('axial', 'sagittal', 'coronal')})
    state._prewarm_mpr_reslice = lambda: module._MprViewsMixin._prewarm_mpr_reslice(state)
    state._prewarm_mpr_reslice()
    renders = lambda: sum(v['widget'].GetRenderWindow.return_value.Render.call_count
                          for v in state.viewers.values())
    assert renders() <= 1, 'Prewarming must yield between native renders'
    assert scheduled
    state._mpr_closed = True
    for callback in scheduled[:]:
        callback()
    assert renders() <= 1


def test_prewarm_visits_all_panes_once_without_geometry_changes(monkeypatch):
    scheduled = []
    monkeypatch.setattr(module, '_MPR_PREWARM', True)
    monkeypatch.setattr(module.QTimer, 'singleShot', lambda *args: scheduled.append(args[-1]))
    state = SimpleNamespace(_mpr_closed=False, viewers={
        name: {'widget': Mock(), 'mapper': Mock()} for name in ('axial', 'sagittal', 'coronal')})
    state._prewarm_mpr_reslice = lambda: module._MprViewsMixin._prewarm_mpr_reslice(state)
    state._prewarm_mpr_reslice()
    while scheduled:
        scheduled.pop(0)()
    state._prewarm_mpr_reslice()
    for view in state.viewers.values():
        view['widget'].GetRenderWindow.return_value.Render.assert_called_once()
        assert view['mapper'].method_calls == [('Modified', (), {})]
