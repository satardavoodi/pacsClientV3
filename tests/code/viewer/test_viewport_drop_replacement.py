"""Drop-replacement identity guards (45154 s102 bug, fixed 2026-06-07).

Root cause (log-verified on the live app): QtFastContainer.switch_series and
VTKWidget switch_series (_vw_series.py) decided their same-series no-op by
comparing ``last_series_show == series_index`` — a THUMBNAIL-LIST INDEX.
``last_series_show`` stores a list index by contract (_vc_layout.py), and
indexes alias across multi-study sidebar rebuilds (patient 45154: offset-key
series 1000102 vs 1000005), so a drop into pane 1 was silently swallowed
(debug-level skip, no [VIEWER_SWITCH] completion) while the identical drop
into pane 2 worked.

The fix compares the actually displayed series IDENTITY: series_number plus
the series_path tie-breaker when both sides carry one (synthetic numbers like
100000 repeat across studies — same contract as the in-place-refresh check).

These tests pin the new behavior on the FAST container (the pane type the bug
hit) plus a source-level anti-pattern guard for both active implementations.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
VTK_WIDGET_DIR = (
    REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "vtk_widget"
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def container(qapp, monkeypatch):
    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import (
        QtFastContainer,
    )

    c = QtFastContainer(height_viewer=100)
    calls = []
    monkeypatch.setattr(
        c, "_start_qt_viewer", lambda md, mf: calls.append(md), raising=False
    )
    c._test_start_calls = calls
    return c


def _meta(series_number, series_path=""):
    series = {"series_number": str(series_number)}
    if series_path:
        series["series_path"] = series_path
    return {"series": series}


def _bridge(series_number, series_path=""):
    return SimpleNamespace(metadata=_meta(series_number, series_path))


def test_aliased_index_still_replaces_different_series(container):
    """THE 45154 bug: same list index, different series → must replace."""
    container._qt_bridge = _bridge("1000005")
    container.last_series_show = 7  # index under which 1000005 was shown
    ok = container.switch_series(None, _meta("1000102"), series_index=7)
    assert ok is True
    assert len(container._test_start_calls) == 1
    assert container.last_series_show == 7  # index contract preserved


def test_same_series_redrop_skips(container):
    """Genuine same-series re-drop keeps the cheap no-op (even if the index
    shifted after a sidebar rebuild)."""
    container._qt_bridge = _bridge("1000102")
    container.last_series_show = 3
    ok = container.switch_series(None, _meta("1000102"), series_index=9)
    assert ok is False
    assert container._test_start_calls == []


def test_synthetic_number_cross_study_replaces_on_path_mismatch(container):
    """Synthetic numbers (100000 docs) repeat across studies — series_path
    must break the tie and allow the replacement."""
    container._qt_bridge = _bridge("100000", series_path="X:/study_A/100000")
    container.last_series_show = 2
    ok = container.switch_series(
        None, _meta("100000", series_path="X:/study_B/100000"), series_index=2
    )
    assert ok is True
    assert len(container._test_start_calls) == 1


def test_same_series_same_path_skips(container):
    container._qt_bridge = _bridge("100000", series_path="X:/study_A/100000")
    container.last_series_show = 2
    ok = container.switch_series(
        None, _meta("100000", series_path="X:/study_A/100000"), series_index=5
    )
    assert ok is False


def test_fresh_pane_always_loads(container):
    """No bridge yet (empty pane) → never skip."""
    container._qt_bridge = None
    container.last_series_show = 4
    ok = container.switch_series(None, _meta("1000102"), series_index=4)
    assert ok is True
    assert len(container._test_start_calls) == 1


def test_missing_metadata_fails_open(container):
    """Unknown incoming identity (N/A) must not be treated as same-series."""
    container._qt_bridge = _bridge("1000005")
    container.last_series_show = 1
    ok = container.switch_series(None, {}, series_index=1)
    assert ok is True
    assert len(container._test_start_calls) == 1


def test_source_no_index_based_same_series_guard():
    """Anti-pattern guard: the active switch paths must not decide the
    same-series no-op via the thumbnail-list index."""
    for fname in ("qt_fast_container.py", "_vw_series.py"):
        src = (VTK_WIDGET_DIR / fname).read_text(encoding="utf-8")
        assert "self.last_series_show == series_index" not in src, fname
