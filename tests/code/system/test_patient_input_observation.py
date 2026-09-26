"""Observe native table input without patient content or changing event delivery."""
import ast
import logging
from pathlib import Path
import time

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QTableWidget, QWidget

PATH = Path(__file__).resolve().parents[3] / 'PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py'


def test_viewport_double_click_has_phi_free_observation(caplog):
    app = QApplication.instance() or QApplication([])
    tree = ast.parse(PATH.read_text(encoding='utf-8'))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PatientTableWidget')
    method = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'eventFilter')
    cls = ast.ClassDef(name='Probe', bases=[ast.Name(id='QWidget', ctx=ast.Load())],
                       keywords=[], body=[method], decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = dict(QWidget=QWidget, logger=logging.getLogger('patient-input-test'), time=time)
    exec(compile(module, str(PATH), 'exec'), namespace)
    widget = namespace['Probe']()
    widget.results_table = QTableWidget(1, 2, widget)
    event = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    with caplog.at_level(logging.INFO):
        assert widget.eventFilter(widget.results_table.viewport(), event) is False
    records = [r.getMessage() for r in caplog.records if '[PATIENT_INPUT]' in r.getMessage()]
    assert len(records) == 1
    assert 'event=MouseButtonDblClick' in records[0]
    assert 'patient_id' not in records[0] and 'study_uid' not in records[0]
    widget.close()
    widget.deleteLater()
