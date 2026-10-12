"""Closing an editor must not permanently latch its source Client button."""
import json
from concurrent.futures import Future
from types import SimpleNamespace

import pytest


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_existing_session_reopen_is_dispatched_to_worker(qapp, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    widget = BrainVolumetryWidget()
    calls = []
    widget._executor.shutdown(wait=False)
    widget._executor = SimpleNamespace(submit=lambda *args: calls.append(args) or Future())
    widget._result = {'posterior_rows': []}
    widget._manual_session = 'synthetic-saved-session'
    widget._manual_open()
    assert calls and calls[0][2] == 'synthetic-saved-session'
    assert widget._future_kind == 'manual_open'
    assert widget.manual_edit.text() == 'Manual Correction — Advanced Image Analysis'
    widget.timer.stop()
    widget._future = None
    widget.deleteLater()


def test_closed_editor_reopens_same_draft_without_overwriting_original(tmp_path, monkeypatch):
    import numpy as np
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain import manual_review as review, runtime
    original = sitk.GetImageFromArray(np.ones((2, 3, 4), dtype=np.uint8))
    edited = sitk.GetImageFromArray(np.ones((2, 3, 4), dtype=np.uint8))
    edited[0, 0, 0] = 0
    for name, image in [('image.nii.gz', original), ('original.nii.gz', original), ('corrected.nii.gz', edited)]:
        sitk.WriteImage(image, str(tmp_path / name))
    manifest = json.dumps({'lesion': False, 'source_result': {'synthetic': True}})
    (tmp_path / 'session.json').write_text(manifest)
    monkeypatch.setattr(runtime, 'slicer_executable', lambda: 'SyntheticViewer.exe')
    process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(review, '_REVIEW_PROCESSES', {str(tmp_path): process})
    with pytest.raises(review.BrainError, match='still open'):
        review.reopen_review(tmp_path)
    process.poll = lambda: 0
    launched = []
    monkeypatch.setattr(review.subprocess, 'Popen', lambda *a, **k: launched.append(a) or process)
    assert review.reopen_review(tmp_path) == str(tmp_path)
    assert len(launched) == 1
    assert (tmp_path / 'session.json').read_text() == manifest
    assert np.array_equal(sitk.GetArrayFromImage(sitk.ReadImage(str(tmp_path / 'editor-input.nii.gz'))), sitk.GetArrayFromImage(edited))
    assert np.all(sitk.GetArrayFromImage(sitk.ReadImage(str(tmp_path / 'original.nii.gz'))) == 1)


def test_restored_session_checks_editor_identity_not_just_reused_pid(tmp_path, monkeypatch):
    import psutil
    from modules.ai_imaging.eagle_eye_brain import manual_review as review
    monkeypatch.setattr(review, '_REVIEW_PROCESSES', {})
    script = str(tmp_path / 'unique-session-script.py')
    (tmp_path / 'editor-process.json').write_text(json.dumps({'pid': 1234, 'script': script}))
    monkeypatch.setattr(psutil, 'Process', lambda pid: SimpleNamespace(cmdline=lambda: ['unrelated-app.exe']))
    assert not review._review_running(tmp_path)
    monkeypatch.setattr(psutil, 'Process', lambda pid: SimpleNamespace(cmdline=lambda: ['AdvancedViewer.exe', '--python-script', script]))
    assert review._review_running(tmp_path)


def test_immediate_reopen_waits_for_previous_process_exit(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain import manual_review as review
    states = iter([True, True, False])
    monkeypatch.setattr(review, '_review_running', lambda directory: next(states))
    monkeypatch.setattr(review.time, 'sleep', lambda duration: None)
    launched = []
    monkeypatch.setattr(review, '_launch_review_locked', lambda directory: launched.append(directory) or str(directory))
    assert review._launch_review(tmp_path) == str(tmp_path)
    assert launched == [tmp_path]


def test_ready_wait_rejects_old_launch_and_completes_only_after_visible_state(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain import manual_review as review
    (tmp_path / 'launch-request.json').write_text(json.dumps({'token': 'new'}))
    state = tmp_path / 'editor-state.json'
    state.write_text(json.dumps({'token': 'old', 'status': 'ready'}))
    waited = []
    def advance(seconds):
        waited.append(seconds)
        state.write_text(json.dumps({'token': 'new', 'status': 'ready'}))
    monkeypatch.setattr(review.time, 'sleep', advance)
    assert review.wait_review_ready(str(tmp_path), timeout=1) == str(tmp_path)
    assert waited


def test_ready_wait_reports_current_launch_failure(tmp_path):
    from modules.ai_imaging.eagle_eye_brain import manual_review as review
    (tmp_path / 'launch-request.json').write_text(json.dumps({'token': 'new'}))
    (tmp_path / 'editor-state.json').write_text(json.dumps({'token': 'new', 'status': 'error'}))
    with pytest.raises(review.BrainError, match='could not be initialized'):
        review.wait_review_ready(str(tmp_path), timeout=1)


def test_open_worker_returns_only_after_ready_acknowledgement(monkeypatch):
    from modules.ai_imaging.eagle_eye_brain import manual_review as review
    events = []
    monkeypatch.setattr(review, 'reopen_review', lambda session: events.append('launch') or session)
    monkeypatch.setattr(review, 'wait_review_ready', lambda session: events.append('visible-ready') or session)
    assert review.open_review_ready({}, 'synthetic') == 'synthetic'
    assert events == ['launch', 'visible-ready']


def test_presentation_acknowledgement_is_launch_bound(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain.manual_slicer import publish_review_state
    monkeypatch.setenv('AIPACS_MANUAL_REVIEW', str(tmp_path))
    monkeypatch.setenv('AIPACS_MANUAL_REVIEW_TOKEN', 'synthetic-current-launch')
    publish_review_state('ready')
    assert json.loads((tmp_path / 'editor-state.json').read_text()) == {
        'token': 'synthetic-current-launch', 'status': 'ready'}
    assert not (tmp_path / 'editor-state.tmp').exists()
