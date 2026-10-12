"""Native view construction yields without exposing interactive partial state."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from modules.mpr.zeta_mpr.mpr_viewer import _mpr_views as module


@pytest.mark.parametrize('close_after_first', [False, True])
def test_native_view_build_yields_and_cancels(monkeypatch, close_after_first):
    queued, made = [], []
    monkeypatch.setattr(module.QTimer, 'singleShot', lambda *args: queued.append(args[-1]))
    state = SimpleNamespace(
        _mpr_closed=False, _initial_views_pending=True,
        _initial_view_steps=[('axial', 0, 0), ('sagittal', 1, 0), ('coronal', 1, 1)],
        _initial_view_placeholders={}, _views_layout=Mock(),
        _finish_initial_views=Mock(), _apply_native_plane_interpolation=Mock(),
        _initial_window_level=None, _highlight_current_series=Mock(),
        setEnabled=Mock(), _deferred_3d_pending=True, _vrt_on_demand=True,
        cleanup=Mock(), _initial_views_failure_callback=Mock())
    for name in ('axial', 'sagittal', 'coronal'):
        setattr(state, '_create_' + name + '_view', lambda *args, name=name: made.append(name))
    state._build_next_initial_view = lambda: module._MprViewsMixin._build_next_initial_view(state)
    state._build_next_initial_view()
    assert made == ['axial']
    assert len(queued) == 1
    state._finish_initial_views.assert_not_called()
    if close_after_first:
        state._mpr_closed = True
    while queued:
        queued.pop(0)()
    assert made == (['axial'] if close_after_first else ['axial', 'sagittal', 'coronal'])
    assert state._finish_initial_views.call_count == (0 if close_after_first else 1)
    assert state.setEnabled.call_count == (0 if close_after_first else 1)


def test_build_error_retires_native_state_and_restores_host(monkeypatch):
    state = SimpleNamespace(_mpr_closed=False, _initial_views_pending=True,
        _initial_view_steps=[('axial',0,0)], _views_layout=Mock(),
        _create_axial_view=Mock(side_effect=RuntimeError('synthetic')),
        cleanup=Mock(), _initial_views_failure_callback=Mock())
    module._MprViewsMixin._build_next_initial_view(state)
    state.cleanup.assert_called_once()
    state._initial_views_failure_callback.assert_called_once()
    assert not state._initial_views_pending


def test_progressive_shell_attaches_before_any_native_constructor(monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget, QLabel
    app = QApplication.instance() or QApplication([])
    queued, made = [], []
    monkeypatch.setattr(module.QTimer, 'singleShot', lambda *args: queued.append(args[-1]))
    monkeypatch.setattr(module, '_MPR_DEFER_3D', True)

    class Shell(module._MprViewsMixin, QWidget):
        def __init__(self):
            super().__init__()
            self._progressive_2d = True
            self._layout_views = None
            self.dims = (8, 8, 8)
            self._initial_views_pending = False
        def _install_deferred_3d_placeholder(self, layout, row, col):
            layout.addWidget(QLabel('3D'), row, col)
        def _create_axial_view(self, *args):
            made.append('axial')
        _create_sagittal_view = _create_axial_view
        _create_coronal_view = _create_axial_view
        def _finish_initial_views(self):
            raise AssertionError('Native panes are not ready')

    shell = Shell()
    shell._setup_ui()
    assert shell.layout() is not None
    assert shell._views_layout.count() == 4
    assert made == []
    assert len(queued) == 1
    assert not shell.isEnabled()
    shell.deleteLater()
