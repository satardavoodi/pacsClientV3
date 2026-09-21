"""Synthetic progress and assigned-anchor correction guards."""
import threading
import pytest
from test_eagle_eye_total_spine import qapp, body, view


def test_assigned_anchor_includes_remaining_candidates():
    from modules.ai_imaging.eagle_eye_total_spine.editing import numbering_proposal
    points = {'L4': body(200, 500, 0)}
    candidates = [{'corners': list(body(200, y, 0).values())} for y in (300, 400, 600)]
    mapping, labels = numbering_proposal(points, candidates, 'L4', 0)
    assert mapping == {'L4': 'L4'}
    assert labels == ['L2', 'L3', 'L5']
    with pytest.raises(ValueError):
        numbering_proposal({}, candidates, 'C1', 1)


def test_region_reports_real_completed_stages():
    from modules.ai_imaging.eagle_eye_total_spine.review_workflow import predict_region
    updates = []
    def predictor(image, cancel):
        assert updates[-1][0] == 1
        return {'candidates': []}
    predict_region(view()['image'], [0, 0, 100, 100], threading.Event(), predictor,
                   progress=lambda done, total, text: updates.append((done, total, text)))
    assert [u[0] for u in updates] == [0, 1, 2, 3]
    assert all(u[1] == 4 for u in updates)


def test_background_uses_completed_stage_percentage(qapp):
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
    from modules.ai_imaging.background_analysis import BackgroundAnalysisDialog
    from modules.ai_imaging.analysis_progress import AnalysisProgress
    dialog = BackgroundAnalysisDialog(); QVBoxLayout(dialog)
    widget = QWidget(dialog); widget._future = object(); widget.status = QLabel('Working')
    widget.analysis_progress = AnalysisProgress()
    widget.analysis_progress.update(2, 4, 'Checking landmarks')
    dialog.bind_analysis(widget)
    try:
        assert dialog.activity_bar.maximum() == 100
        assert dialog.activity_bar.value() == 50
        assert '2/4' in dialog.activity_status.text()
        assert '2 remaining' in dialog.activity_status.text()
    finally:
        dialog.deleteLater()


def test_assign_then_number_with_exception_and_single_undo(qapp):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QCheckBox, QTableWidget
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    editor = ProjectionEditor('coronal'); editor.accept_image(view()['image'])
    editor.accept_candidates({'candidates': [dict(corners=list(body(240, y).values()))
                                            for y in (200, 350, 500)], 'model': 'synthetic'})
    editor.candidate.setCurrentIndex(2); editor.level.setCurrentText('L4')
    editor._assign_candidate()
    assert set(editor.points) == {'L4'}
    def confirm():
        dialog = QApplication.activeModalWidget()
        table = dialog.findChild(QTableWidget)
        # An explicitly reviewed missing-level exception, without duplicate labels.
        table.cellWidget(1, 1).setCurrentText('L1')
        dialog.findChild(QCheckBox).setChecked(True); dialog.accept()
    QTimer.singleShot(20, confirm); editor._candidate_numbering()
    assert set(editor.points) == {'L1', 'L3', 'L4'}
    assert editor.provenance['per_level']['L1']['numbering_exception']
    assert not editor.candidates
    editor._undo_edit()
    assert set(editor.points) == {'L4'} and len(editor.candidates) == 2
    editor.close()


def test_cancelled_model_does_not_report_completion():
    from modules.ai_imaging.eagle_eye_total_spine.review_workflow import predict_region
    cancel = threading.Event(); updates = []
    def predictor(image, event):
        event.set()
        return {'candidates': []}
    with pytest.raises(ValueError, match='cancelled'):
        predict_region(view()['image'], [0, 0, 100, 100], cancel, predictor,
                       progress=lambda done, total, text: updates.append(done))
    assert updates == [0, 1]
