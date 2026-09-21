"""Deferred 3D construction must not resume after progress painting closes MPR."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6 import QtWidgets

from modules.mpr.zeta_mpr.mpr_viewer import _mpr_views as views


@pytest.mark.parametrize("close_during_paint", [True, False])
@pytest.mark.parametrize("build_fails", [True, False])
def test_progress_event_pump_respects_teardown(monkeypatch, close_during_paint, build_fails):
    dialog = Mock()
    layout = Mock()
    host = layout.parentWidget.return_value
    placeholder = Mock()
    state = SimpleNamespace(
        _deferred_3d_pending=True, _mpr_closed=False,
        _views_layout=layout, _deferred_3d_placeholder=placeholder,
        _create_3d_view=Mock(side_effect=RuntimeError("synthetic build failure") if build_fails else None),
    )
    monkeypatch.setattr(views, "mpr_deferred_3d_progress_enabled", lambda: True)
    monkeypatch.setattr(views, "mpr_deferred_3d_stable_swap_enabled", lambda: True)
    monkeypatch.setattr(QtWidgets, "QProgressDialog", Mock(return_value=dialog))

    def paint_progress():
        if close_during_paint:
            state._mpr_closed = True
            state._deferred_3d_pending = False

    monkeypatch.setattr(QtWidgets, "QApplication", SimpleNamespace(processEvents=paint_progress))
    views._MprViewsMixin._build_deferred_3d_view(state)

    if close_during_paint:
        state._create_3d_view.assert_not_called()
        host.setUpdatesEnabled.assert_not_called()
        layout.removeWidget.assert_not_called()
    else:
        state._create_3d_view.assert_called_once_with(layout, 0, 1)
        assert host.setUpdatesEnabled.call_args_list[-1].args == (True,)
        assert layout.removeWidget.call_count == (0 if build_fails else 1)
    dialog.close.assert_called_once()
    dialog.deleteLater.assert_called_once()
    assert state._deferred_3d_pending is False
