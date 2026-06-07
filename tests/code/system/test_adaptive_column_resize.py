"""Guards: balanced 'Adaptive to Screen Size' column resize (2026-06-06).

The width delta between the table area and the base column widths is now
distributed PROPORTIONALLY across all visible resizable columns. Previously
one Stretch column (Study Description) absorbed the entire difference and
grew/shrank disproportionately. Manual drag-resizing must keep working on
every data column, and a manual drag stops window-resize auto-refit from
clobbering the user's widths.
"""
import inspect
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def stub_qta(monkeypatch):
    from PySide6.QtGui import QIcon
    import qtawesome
    monkeypatch.setattr(qtawesome, "icon", lambda *a, **k: QIcon())
    yield


def _widget_cls():
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import (
        PatientTableWidget,
    )
    return PatientTableWidget


def _code(name):
    src = inspect.getsource(getattr(_widget_cls(), name))
    return '\n'.join(line.split('#', 1)[0] for line in src.splitlines())


# ----------------------------------------------------------- source pins ----

def test_no_stretch_column_in_adaptive_pass():
    code = _code('auto_resize_columns')
    assert "QHeaderView.Stretch" not in code, (
        "no single Stretch column may absorb the whole width delta"
    )
    assert "scale" in code and "resizable_base_total" in code


def test_manual_drag_disarms_window_refit():
    code = _code('_on_header_section_resized')
    assert "_user_adjusted_columns = True" in code
    code_resize = _code('resizeEvent')
    assert "_user_adjusted_columns" in code_resize  # refit stands down


# ------------------------------------------------------- functional pass ----

def test_proportional_distribution_fills_viewport(qapp, stub_qta):
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import COL

    w = _widget_cls()()
    w.resize(1400, 600)
    w.show()
    qapp.processEvents()

    w.auto_resize_columns()
    qapp.processEvents()

    table = w.results_table
    header = table.horizontalHeader()
    from PySide6.QtWidgets import QHeaderView

    visible = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
    assert visible

    # 1) No Stretch sections anywhere — all data columns drag-resizable.
    for col in visible:
        assert header.sectionResizeMode(col) != QHeaderView.Stretch

    # 2) Total visible width tracks the viewport (no giant last-column gap).
    total = sum(table.columnWidth(c) for c in visible)
    viewport_w = table.viewport().width()
    assert abs(total - viewport_w) <= 12, (total, viewport_w)

    # 3) Proportionality: visible resizable columns keep their BASE ratios
    #    (each scales by the same factor — nobody absorbs the whole delta).
    #    patient_name base 160 vs patient_id base 100 → ratio 1.6.
    #    (Column visibility comes from the user's saved settings, so only
    #    assert on columns guaranteed visible.)
    name_w = table.columnWidth(COL['patient_name'])
    id_w = table.columnWidth(COL['patient_id'])
    assert name_w > 0 and id_w > 0
    ratio = name_w / float(id_w)
    assert 1.3 <= ratio <= 1.9, f"expected ~1.6 base ratio, got {ratio:.2f}"


def test_window_resize_refit_rearms_after_adaptive_pass(qapp, stub_qta):
    w = _widget_cls()()
    w.resize(1200, 600)
    w.show()
    qapp.processEvents()

    w.auto_resize_columns()
    assert getattr(w, '_user_adjusted_columns') is False

    # simulate a manual drag (outside the adaptive pass)
    w._on_header_section_resized(2, 100, 140)
    assert w._user_adjusted_columns is True

    # adaptive pass re-arms auto refit
    w.auto_resize_columns()
    assert w._user_adjusted_columns is False
