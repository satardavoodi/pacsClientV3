"""Report recovery must preserve snapshots without claiming edits are reviewed."""
from concurrent.futures import Future
from test_eagle_eye_alignment import image, points, qapp


def ready():
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    w = AlignmentWidget(study_uid='1.2.3')
    w._apply_image(image()); w.points = {'R': points(), 'L': points('L')}
    w._redraw_points()
    f = Future(); f.set_result({'artifact_directory': 'synthetic', 'pdf_available': True})
    w._future = f; w._kind = 'report'; w._poll()
    return w


def test_edit_retains_previous_pdf_but_not_current_review(qapp):
    w = ready()
    w.impression.setText('Edited impression')
    assert w.report_result is None
    assert w.open_pdf.isEnabled() and w.save_pdf.isEnabled()
    assert 'previous' in w.open_pdf.text().lower()
    assert 'not included' in w.report_help.text()
    assert not w.review.isChecked()
    w._apply_image(image())
    assert not w.open_pdf.isEnabled()
    w.teardown(); w.close()


def test_restore_source_spacing_preserves_points_and_does_not_attest_review(qapp):
    w = ready(); original = dict(w.image)
    w.col_spacing.setValue(.000001)
    w.restore_scale.click()
    assert w.image['spacing'] == original['spacing']
    assert w.image['calibrated'] == original['calibrated']
    assert w.points == {'R': points(), 'L': points('L')}
    assert not w.review.isChecked() and not w.confirm.isChecked()
    assert 'Confirm' in w.report_help.text()
    w.teardown(); w.close()


def test_draft_is_available_without_false_clinical_confirmation(qapp, monkeypatch):
    w = ready(); w.impression.setText('New note')
    calls = []
    monkeypatch.setattr(w, '_generate_pdf', lambda **kw: calls.append(kw))
    assert w.draft_pdf.isEnabled()
    w.draft_pdf.click()
    assert calls == [{'landmarks_reviewed': False}]
    assert not w.review.isChecked() and not w.confirm.isChecked()
    w.teardown(); w.close()


def test_previous_pdf_actions_use_snapshot_and_clear_on_series_change(qapp, monkeypatch, tmp_path):
    from modules.ai_imaging.eagle_eye_alignment import widget
    w = ready(); w.impression.setText('Edited')
    opened=[]; submitted=[]
    monkeypatch.setattr(widget.QDesktopServices,'openUrl',lambda url:opened.append(url.toLocalFile()))
    monkeypatch.setattr(widget.QFileDialog,'getSaveFileName',lambda *args:(str(tmp_path/'copy.pdf'),'PDF'))
    monkeypatch.setattr(w,'_submit',lambda *args:submitted.append(args))
    w._open_pdf();w._save_pdf()
    assert opened[0].replace('\\','/').endswith('synthetic/report.pdf')
    assert submitted[0][2]['artifact_directory']=='synthetic'
    w._future=Future();w._refresh_controls()
    assert not w.draft_pdf.isEnabled() and not w.restore_scale.isEnabled()
    w._future=None;w._series_changed()
    assert w._previous_report is None and not w.open_pdf.isEnabled()
    w.teardown();w.close()
