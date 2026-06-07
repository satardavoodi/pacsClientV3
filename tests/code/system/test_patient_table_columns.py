"""Guards: Status/Report patient-table columns are narrower and resizable.

2026-06-06 request: Status and Report were the only data columns the user
could not drag-resize — `auto_resize_columns` re-applied QHeaderView.Fixed
to them after every bulk insert. They are now Interactive (like Patient ID),
default widths reduced ~30% (150→105 / 170-180→125), and — being normal
resizable columns — included in the generic column-width persistence.

Source-pinned (the full PatientTableWidget needs live home wiring).
"""
import inspect
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _src(name):
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import (
        PatientTableWidget,
    )
    return inspect.getsource(getattr(PatientTableWidget, name))


def _code(name):
    return '\n'.join(line.split('#', 1)[0] for line in _src(name).splitlines())


def test_status_report_not_in_fixed_columns():
    code = _code('auto_resize_columns')
    # the fixed set must contain exactly select+assign — not status/report
    assert "fixed_cols = {COL['select'], COL['assign']}" in code, (
        "Status/Report must stay drag-resizable (Interactive), not Fixed"
    )


def test_status_report_default_widths_reduced():
    code = _code('auto_resize_columns')
    assert "COL['status']: 105" in code
    assert "COL['report']: 125" in code
    assert "COL['status']: 150" not in code
    assert "COL['report']: 170" not in code


def test_initial_setup_widths_match_reduced_defaults():
    from PacsClient.pacs.workstation_ui.home_ui import patient_table_widget as mod
    src = inspect.getsource(mod)
    assert "setColumnWidth(COL['status'], 105)" in src
    assert "setColumnWidth(COL['report'], 125)" in src


def test_persistence_saves_all_visible_columns_generically():
    code = _code('_save_column_settings')
    # generic per-column loop → Status/Report widths persist automatically
    assert "for col in range(self.results_table.columnCount())" in code
    assert "columnWidth(col)" in code
