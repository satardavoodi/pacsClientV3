"""Synthetic masks, known endplates, model boundaries and explicit preview review."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import threading

import numpy as np
import pytest

from modules.ai_imaging.eagle_eye_total_spine.mask_geometry import propose_endplates, validate_box
from modules.ai_imaging.eagle_eye_total_spine.geometry import endplate_tilt
from modules.ai_imaging.eagle_eye_total_spine import assist_service, assist_assets


def wedge():
    y, x = np.mgrid[:160, :220]
    return (x >= 30) & (x <= 190) & (y >= 35+.2*(x-30)) & (y <= 125-.1*(x-30))


def image():
    return dict(pixels=np.zeros((400, 500), dtype=np.uint8), projection='lateral',
                source_sha256='synthetic', spacing=(1., 1.), calibrated=False,
                calibration_method='Synthetic', identity=dict(study_uid='1', series_uid='2', sop_uid='3'))


def test_wedged_mask_keeps_two_independent_endplate_slopes_and_origin():
    result = propose_endplates(wedge(), (50, 80))
    p = result['points']
    assert endplate_tilt(p) == pytest.approx(np.degrees(np.arctan(.2)), abs=.2)
    assert endplate_tilt(p, 'inferior') == pytest.approx(np.degrees(np.arctan(-.1)), abs=.2)
    assert p['superior_left'][0] > 80 and p['superior_left'][1] > 115
    assert result['anatomical_corners'] is False
    assert endplate_tilt(p, spacing=(2, 1)) == pytest.approx(np.degrees(np.arctan(.4)), abs=.3)


@pytest.mark.parametrize('kind', ['empty', 'multiple', 'border', 'holes', 'wrong_type', 'curved'])
def test_unsuitable_masks_are_rejected(kind):
    mask = wedge()
    if kind == 'empty': mask[:] = False
    elif kind == 'multiple': mask[1:20, 1:20] = True
    elif kind == 'border': mask[0:40, 30:60] = True
    elif kind == 'holes': mask[70:95, 70:140] = False
    elif kind == 'wrong_type': mask = mask.astype(np.uint8)
    elif kind == 'curved':
        y, x = np.mgrid[:160, :220]
        mask = (x > 20) & (x < 200) & (y > 30+.007*(x-110)**2) & (y < 130)
    with pytest.raises(ValueError): propose_endplates(mask)


@pytest.mark.parametrize('box', [[0,0,3,4], [-1,4,30,40], [0,0,500,40], [5,5,float('nan'),30]])
def test_invalid_body_boxes(box):
    with pytest.raises(ValueError): validate_box(box, (400, 500))


def test_sam_preview_preserves_mask_when_fitting_rejects(monkeypatch):
    monkeypatch.setattr(assist_service, '_run', lambda *args: dict(mask=wedge(), origin=(50,80), score=.4))
    result = assist_service.segment_body(image(), 'T4', [60,90,240,240], threading.Event())
    assert result['proposal'] is None and 'Low SAM' in result['proposal_error']
    assert result['mask'].any() and result['binding']['sop_uid'] == '3'


def test_sam_known_mask_is_a_proposal_not_an_applied_measurement(monkeypatch):
    monkeypatch.setattr(assist_service, '_run', lambda *args: dict(mask=wedge(), origin=(50,80), score=.98))
    result = assist_service.segment_body(image(), 'T4', [60,90,240,240], threading.Event())
    assert result['proposal'] and result['level'] == 'T4'
    assert result['mask_sha256'] == hashlib.sha256(wedge().tobytes()).hexdigest()


def test_s1_and_lateral_detector_requests_fail_before_model_execution(monkeypatch):
    def forbidden(*args): pytest.fail('Model must not run for unsupported input')
    monkeypatch.setattr(assist_service, '_run', forbidden)
    with pytest.raises(ValueError, match='S1'): assist_service.segment_body(image(), 'S1', [60,90,240,240], threading.Event())
    with pytest.raises(ValueError, match='AP model'): assist_service.predict_scoliovis(image(), threading.Event())


@pytest.fixture(scope='module')
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app


def preview(img):
    return dict(mask=wedge(), origin=(50,80), score=.98, binding=assist_service.image_binding(img), level='T4',
                box=[60,90,240,240], proposal=propose_endplates(wedge(), (50,80)), proposal_error='',
                model='Synthetic SAM', weight_sha256='synthetic', mask_sha256='synthetic')


def test_ui_preview_requires_explicit_apply_and_invalidates_review(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    editor = ProjectionEditor('lateral')
    editor.accept_image(image()); editor.confirm.setChecked(True); editor.review.setChecked(True)
    editor.sam.accept_preview(preview(editor.image))
    assert not editor.points
    editor.sam.accept_endplates()
    assert 'T4' in editor.points and not editor.review.isChecked()
    assert editor.sam.preview is None and not editor.sam.graphics
    assert editor.provenance['per_level']['T4']['reader_applied']
    editor._point_changed('T4', 'superior_left', 105, 120)
    assert editor.provenance['per_level']['T4']['reader_modified']
    editor.clear_image()
    assert not editor.sam.graphics and editor.sam.preview is None
    editor.close()


def test_ui_rejects_stale_image_and_clears_preview_on_level_change(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    editor = ProjectionEditor('lateral'); editor.accept_image(image())
    stale = preview(editor.image); stale['binding']['sop_uid'] = 'other'
    with pytest.raises(ValueError, match='changed'): editor.sam.accept_preview(stale)
    editor.sam.accept_preview(preview(editor.image))
    editor.level.setCurrentText('T5')
    assert editor.sam.preview is None and not editor.sam.apply.isEnabled()
    editor.close()


def test_cancelled_worker_result_never_applies(qapp):
    from concurrent.futures import Future
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    widget = TotalSpineWidget(study_uid='1')
    editor = widget.editors[1]; editor.accept_image(image())
    widget._kind = 'segmentation'; widget._target = editor
    widget._future = Future(); widget._future.set_result(preview(editor.image))
    widget._cancel.set(); widget._poll()
    assert editor.sam.preview is None and not editor.points
    widget.teardown(); widget.close()


def make_bundle(root, monkeypatch):
    digest = hashlib.sha256(b'synthetic').hexdigest()
    monkeypatch.setattr(assist_assets, 'WEIGHTS', {name: ('synthetic', digest) for name in assist_assets.WEIGHTS})
    for name in assist_assets.REQUIRED:
        target=root/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b'synthetic')
    manifest = dict(format_version=1, sam_revision=assist_assets.SAM_REVISION,
                    scoliovis_revision=assist_assets.SCOLIOVIS_REVISION,
                    sha256={name:digest for name in assist_assets.REQUIRED})
    (root/'manifest.json').write_text(json.dumps(manifest))
    return manifest


def test_assist_seal_pinned_weights_and_separate_distribution_acceptance(tmp_path, monkeypatch):
    manifest=make_bundle(tmp_path,monkeypatch)
    assist_assets.validate_assist(tmp_path)
    with pytest.raises(RuntimeError,match='acceptance'): assist_assets.validate_assist(tmp_path,for_distribution=True)
    (tmp_path/'sam_vit_b.pth').write_bytes(b'changed')
    manifest['sha256']['sam_vit_b.pth']=hashlib.sha256(b'changed').hexdigest()
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError): assist_assets.validate_assist(tmp_path)


def test_assist_manifest_rejects_path_injection(tmp_path,monkeypatch):
    manifest=make_bundle(tmp_path,monkeypatch)
    manifest['sha256']['../outside.py']='0'*64
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError): assist_assets.validate_assist(tmp_path)


def test_mask_outside_selected_box_cannot_supply_endplates(monkeypatch):
    monkeypatch.setattr(assist_service, '_run', lambda *args: dict(mask=wedge(), origin=(50,80), score=.98))
    result = assist_service.segment_body(image(), 'T4', [5,5,25,25], threading.Event())
    assert result['proposal'] is None and 'outside' in result['proposal_error']


def test_offscreen_mouse_box_uses_source_coordinates(qapp):
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtTest import QTest
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    editor = ProjectionEditor('lateral'); editor.resize(1000,800); editor.show()
    editor.accept_image(image()); qapp.processEvents(); editor.canvas.fit()
    editor.sam.select_box()
    for point in ((70,110),(260,240)):
        position = editor.canvas.mapFromScene(QPointF(*point))
        QTest.mouseClick(editor.canvas.viewport(), Qt.LeftButton, pos=position)
    assert np.allclose(editor.sam.box, [70,110,260,240], atol=2)
    assert editor.sam.run.isEnabled() and not editor.points
    editor.close()


@pytest.mark.parametrize('outcome', ['success', 'failed', 'cancelled', 'running_cancelled'])
def test_subprocess_is_owned_and_temporary_pixels_are_removed(tmp_path, monkeypatch, outcome):
    from modules.ai_imaging.eagle_eye_total_spine import service
    from modules.ai_imaging.eagle_eye_alignment import service as alignment
    from modules.mpr.advanced_3d_slicer import owned_process
    monkeypatch.setattr(service, 'bundle_root', lambda: tmp_path/'bundle')
    monkeypatch.setattr(assist_service, 'validate_assist', lambda *args: {})
    monkeypatch.setattr(alignment, 'bundle_root', lambda: tmp_path/'runtime')
    monkeypatch.setattr(alignment, 'validate_bundle', lambda *args: {})
    cancel = threading.Event(); captured = {}
    class Owner:
        def assign(self, process): captured['assigned'] = process
        def close(self): captured['closed'] = True
    class Process:
        returncode = None if outcome == 'running_cancelled' else (0 if outcome == 'success' else 1)
        def __init__(self, args, **kwargs):
            folder=Path(args[-1]); captured['folder']=folder; captured['kwargs']=kwargs
            pixels=np.load(folder/'input.npy', allow_pickle=False)
            request=json.loads((folder/'request.json').read_text())
            captured['box']=request['box']; captured['shape']=pixels.shape
            mask=np.zeros_like(pixels,dtype=bool); mask[20:-20,20:-20]=True
            np.save(folder/'mask.npy',mask,allow_pickle=False)
            (folder/'result.json').write_text('{"score":0.98}')
            if outcome in ('cancelled', 'running_cancelled'): cancel.set()
        def poll(self): return self.returncode
        def wait(self,timeout): captured['waited']=True
        def kill(self): captured['killed']=True; self.returncode=-1
    monkeypatch.setattr(owned_process, 'ProcessJob', Owner)
    monkeypatch.setattr(assist_service.subprocess, 'Popen', Process)
    if outcome == 'success':
        result=assist_service._run(image(),'sam',cancel,[100,100,200,200])
        assert result['origin'] == (65,65)
        assert captured['box'] == [35,35,135,135]
        assert result['mask'].shape == captured['shape']
    else:
        with pytest.raises(ValueError): assist_service._run(image(),'sam',cancel,[100,100,200,200])
    assert captured['assigned'] and captured['closed'] and captured['waited']
    assert not captured['folder'].exists()
    assert captured['kwargs']['stdout'] == assist_service.subprocess.DEVNULL
    if outcome == 'running_cancelled': assert captured['killed']


def test_runtime_seal_reuses_unchanged_verification_and_rechecks_changed_files(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine.runtime_seal import RuntimeSeal
    from modules.ai_imaging.eagle_eye_alignment import service as alignment
    binary=tmp_path/'python.exe'; binary.write_bytes(b'synthetic')
    (tmp_path/'manifest.json').write_text(json.dumps({'sha256': {'python.exe': 'synthetic'}}))
    calls=[]
    monkeypatch.setattr(alignment, 'validate_bundle', lambda *args: calls.append(True))
    seal=RuntimeSeal(); cancel=threading.Event()
    seal.verify(tmp_path,cancel); seal.verify(tmp_path,cancel)
    assert len(calls) == 1
    binary.write_bytes(b'changed-size')
    seal.verify(tmp_path,cancel)
    assert len(calls) == 2
    cancel.set()
    with pytest.raises(ValueError,match='cancelled'): seal.verify(tmp_path,cancel)


def test_runtime_seal_never_caches_failed_or_inflight_changed_files(tmp_path,monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine.runtime_seal import RuntimeSeal
    from modules.ai_imaging.eagle_eye_alignment import service as alignment
    binary=tmp_path/'python.exe'; binary.write_bytes(b'synthetic')
    (tmp_path/'manifest.json').write_text(json.dumps({'sha256': {'python.exe': 'synthetic'}}))
    def changing(*args): binary.write_bytes(b'changed-during-check')
    monkeypatch.setattr(alignment,'validate_bundle',changing)
    seal=RuntimeSeal()
    with pytest.raises(ValueError,match='changed'): seal.verify(tmp_path,threading.Event())
    assert seal._verified is None
    def fail(*args): raise ValueError('Invalid seal')
    monkeypatch.setattr(alignment,'validate_bundle',fail)
    with pytest.raises(ValueError,match='Invalid seal'): seal.verify(tmp_path,threading.Event())
    assert seal._verified is None


def test_review_checkbox_emits_change_and_invalidates_existing_report(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    widget = TotalSpineWidget(study_uid='1')
    editor = widget.editors[1]; editor.accept_image(image())
    events=[]; editor.changed.connect(lambda: events.append(True))
    widget.report_result={'artifact_directory':'synthetic'}
    editor.review.setChecked(True)
    assert events and widget.report_result is None
    widget.teardown(); widget.close()
