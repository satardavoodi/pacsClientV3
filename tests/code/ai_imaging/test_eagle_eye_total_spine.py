"""Synthetic clinical geometry and state guards; no patient database or images."""
from copy import deepcopy
import math
import json
from pathlib import Path

import numpy as np
import pytest

from modules.ai_imaging.eagle_eye_total_spine.geometry import (
    CORNERS, LEVELS, endplate_tilt, measure_curve, suggest_apex, horizontal_offset, rotation_record,
    validate_landmarks)
from modules.ai_imaging.eagle_eye_total_spine.measurements import measure_view, validate_report_views


@pytest.fixture(scope='module')
def qapp():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    app = QApplication.instance() or QApplication([])
    for name in ('arial.ttf', 'arialbd.ttf'):
        path = Path('C:/Windows/Fonts')/name
        if path.is_file(): QFontDatabase.addApplicationFont(str(path))
    return app


def body(x, y, angle=0, width=40, height=24):
    dy = width*math.tan(math.radians(angle))/2
    return dict(zip(CORNERS, [[x-width/2, y-dy], [x+width/2, y+dy],
                              [x-width/2, y+height-dy], [x+width/2, y+height+dy]]))


def view(projection='coronal'):
    pixels = np.zeros((1000, 500), dtype=np.uint8)
    points = {'T4': body(240, 150, -20), 'T8': body(300, 390), 'T12': body(240, 700, 20)}
    for p in points.values():
        for x, y in p.values(): pixels[int(y)-2:int(y)+3, int(x)-2:int(x)+3] = 220
    image = dict(pixels=pixels, projection=projection, spacing=(1., 1.), calibrated=False,
                 calibration_method='Uncalibrated', source_sha256='synthetic-only',
                 identity=dict(study_uid='1.2.3', series_uid='1.2.3.1', sop_uid='1.2.3.1.1',
                               patient_id='SYNTHETIC', patient_name='Synthetic Example', study_date='20260917',
                               series_number='1', series_description='Synthetic Total Spine'))
    return dict(image=image, points=points, markers={}, rotations=[], provenance={},
                acquisition_confirmed=True, landmarks_reviewed=False, positive_image_right=False,
                curves=[dict(name='Scoliosis Cobb' if projection == 'coronal' else 'Thoracic kyphosis',
                             upper='T4', lower='T12', lower_endplate='inferior', apex='T8', convexity='left')])


def test_endplate_cobb_known_angles_and_aspect():
    v = view(); p = v['points']
    assert measure_curve(p, 'T4', 'T12')['cobb_deg'] == pytest.approx(40)
    expected = 2*math.degrees(math.atan(math.tan(math.radians(20))*2))
    assert measure_curve(p, 'T4', 'T12', spacing=(2, 1))['cobb_deg'] == pytest.approx(expected)


def test_severe_cobb_is_not_folded_into_acute_angle():
    p = {'T4': body(200, 180, -60, height=100), 'T12': body(200, 650, 60, height=100)}
    assert measure_curve(p, 'T4', 'T12')['cobb_deg'] == pytest.approx(120)


def test_lumbar_lordosis_uses_s1_superior_not_inferior():
    p = {'L1': body(200, 100, -10), 'S1': body(200, 600, 20)}
    p['S1']['inferior_right'][1] += 10
    result = measure_curve(p, 'L1', 'S1', lower_endplate='superior')
    assert result['cobb_deg'] == pytest.approx(30)
    assert measure_curve(p, 'L1', 'S1')['cobb_deg'] != pytest.approx(30)


@pytest.mark.parametrize('spacing', [(0, 1), (-1, 1), (float('nan'), 1), (1,), (1, 2, 3)])
def test_bad_spacing_rejected(spacing):
    with pytest.raises(ValueError): endplate_tilt(body(100, 100), spacing=spacing)


def test_reversed_degenerate_nonfinite_and_outside_points():
    p = view()['points']
    with pytest.raises(ValueError): measure_curve(p, 'T12', 'T4')
    p['T4']['superior_right'] = p['T4']['superior_left']
    with pytest.raises(ValueError): measure_curve(p, 'T4', 'T12')
    for bad in ([float('nan'), 3], [-1, 3], [501, 3]):
        with pytest.raises(ValueError): validate_landmarks({'T4': {'superior_left': bad}}, (1000, 500))


def test_apex_candidate_is_distinct_from_reader_apex():
    v = view(); v['curves'][0]['apex'] = ''
    result = measure_view(v)['curves'][0]
    assert result['apex'] is None and result['apex_candidate'] == 'T8'
    v['points']['T8'] = body(240, 390)
    assert suggest_apex(v['points'], 'T4', 'T12') is None


def test_disc_apex_and_invalid_level():
    v = view(); v['curves'][0]['apex'] = 'T8/T9'
    assert measure_view(v)['curves'][0]['apex'] == 'T8/T9'
    v['curves'][0]['apex'] = 'L2'
    with pytest.raises(ValueError): measure_view(v)


def test_plumb_distance_calibration_and_sign():
    assert horizontal_offset([20, 10], [10, 900], (.2, .4)) == {'value': 10., 'unit': 'px'}
    assert horizontal_offset([20, 10], [10, 900], (.2, .4), calibrated=True,
                             positive_image_right=False) == {'value': -4., 'unit': 'mm'}
    v = view(); v['markers'] = {'C7 center': [280, 10], 'Sacral center': [240, 900]}
    assert measure_view(v)['balance']['value'] == -40


def test_rotation_is_manual_ordinal_never_degrees():
    assert rotation_record('T8', 2, 'right')['axial_degrees'] is None
    for args in [('T8', 0, 'right'), ('T8', 2, 'none'), ('T8', 5, 'left'), ('T8', True, 'right')]:
        with pytest.raises(ValueError): rotation_record(*args)
    v = view('lateral'); v['rotations'] = [rotation_record('T8', 2, 'right')]
    with pytest.raises(ValueError): measure_view(v)


def test_review_and_acquisition_are_separate_gates():
    v = view()
    validate_report_views([v], '1.2.3')
    with pytest.raises(ValueError): validate_report_views([v], '1.2.3', reviewed=True)
    v['landmarks_reviewed'] = True
    validate_report_views([v], '1.2.3', reviewed=True)
    v['acquisition_confirmed'] = False
    with pytest.raises(ValueError): validate_report_views([v], '1.2.3')


def test_report_identity_projection_and_patient_conflict():
    a, b = view(), view('lateral')
    with pytest.raises(ValueError): validate_report_views([a], 'other-study')
    with pytest.raises(ValueError): validate_report_views([a, b], '1.2.3')
    b['image']['identity']['sop_uid'] = '1.2.3.2.1'
    b['image']['identity']['patient_id'] = 'OTHER'
    with pytest.raises(ValueError): validate_report_views([a, b], '1.2.3')
    b['image']['identity']['patient_id'] = 'SYNTHETIC'
    assert len(validate_report_views([a, b], '1.2.3')) == 2


def test_ai_candidate_validation_and_numbering_assumption():
    from modules.ai_imaging.eagle_eye_total_spine.service import assign_candidates
    result = {'candidates': [{'corners': list(body(200, 10+i*50).values()), 'confidence': .8} for i in range(17)]}
    points = assign_candidates(result, (1000, 500))
    assert list(points) == list(LEVELS[7:24])
    result['candidates'][5]['confidence'] = .1
    with pytest.raises(ValueError): assign_candidates(result, (1000, 500))
    result['candidates'][5]['confidence'] = .8
    result['candidates'][5]['corners'][0][0] = -1
    with pytest.raises(ValueError): assign_candidates(result, (1000, 500))


def test_function_routes_only_radiographs():
    from modules.ai_imaging.eagle_eye_function_catalog import function_options_for_modality
    for modality in ('DX', 'CR'):
        assert any(o.key == 'total_spine_alignment' for o in function_options_for_modality(modality))
    assert all(o.key != 'total_spine_alignment' for o in function_options_for_modality('MR'))


def test_major_curve_proposal_keeps_reader_confirmation_separate():
    from modules.ai_imaging.eagle_eye_total_spine.geometry import suggest_major_curve
    p = view()['points']
    spec = suggest_major_curve(p)
    assert (spec['upper'], spec['lower']) == ('T4', 'T12')
    assert not spec['apex'] and spec['convexity'] == 'not assessed'


def test_dicom_projection_and_series_gate_before_measurement(tmp_path):
    from test_eagle_eye_alignment import dicom
    from modules.ai_imaging.eagle_eye_total_spine.service import load_view
    ds = dicom(tmp_path); ds.ViewPosition = 'AP'; ds.save_as(ds.filename)
    with pytest.raises(ValueError, match='projection'): load_view(ds.filename, '1.2.3', str(ds.SeriesInstanceUID), 'lateral')
    with pytest.raises(ValueError, match='series'): load_view(ds.filename, '1.2.3', '1.9.9', 'coronal')
    assert load_view(ds.filename, '1.2.3', str(ds.SeriesInstanceUID), 'coronal')['projection'] == 'coronal'


def test_cancelled_completion_cannot_replace_landmarks(qapp):
    from concurrent.futures import Future
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    w = TotalSpineWidget(study_uid='1.2.3'); e = w.editors[0]
    e.accept_image(view()['image']); e.points = view()['points']
    before = deepcopy(e.points)
    w._future = Future(); w._future.set_result({'candidates': []})
    w._kind = 'inference'; w._target = e; w._cancel.set(); w._poll()
    assert e.points == before and w._future is None and w.report_result is None
    w.teardown(); w.deleteLater()


def test_ai_completion_keeps_candidates_unassigned_without_automatic_report(qapp, monkeypatch):
    from concurrent.futures import Future
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    w = TotalSpineWidget(study_uid='1.2.3'); e = w.editors[0]; e.accept_image(view()['image'])
    e.confirm.setChecked(True)
    result = {'candidates': [{'corners': list(body(200, 30+i*50, -10+i).values()), 'confidence': .8} for i in range(17)]}
    w._future = Future(); w._future.set_result(result); w._kind = 'inference'; w._target = e
    calls = []; monkeypatch.setattr(w, 'generate', lambda reviewed: calls.append(reviewed))
    w._poll()
    assert len(e.candidates) == 17 and not e.points and not e.curves and calls == []
    assert not e.review.isChecked()
    w.teardown(); w.deleteLater()


def test_ui_correction_and_series_change_invalidate_report(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    w = TotalSpineWidget(study_uid='1.2.3')
    editor = w.editors[0]; v = view()
    editor.accept_image(v['image']); editor.points = v['points']; editor.curves = v['curves']
    editor.confirm.setChecked(True); editor.review.setChecked(True)
    w.report_result = {'artifact_directory': 'synthetic'}
    editor._point_changed('T4', 'superior_left', 219, 157)
    assert not editor.review.isChecked() and w.report_result is None
    w.report_result = {'artifact_directory': 'synthetic'}
    editor.files.addItem('Changed image', 'synthetic-path')
    assert editor.image is None and not editor.points and not editor.curves and w.report_result is None
    w.teardown(); w.close(); w.deleteLater()


def test_ui_manual_curve_and_lordosis_defaults(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e = ProjectionEditor('lateral'); e.accept_image(view('lateral')['image'])
    e.points = view()['points']; e._add_curve()
    assert len(e.curves) == 1 and e.table.rowCount() == 1
    e.kind.setCurrentText('Lumbar lordosis')
    assert (e.upper.currentText(), e.lower.currentText(), e.endplate.currentText()) == ('L1', 'S1', 'superior')
    e.close(); e.deleteLater()


def test_owned_popup_reuses_view_state_and_cancels_on_workspace_teardown(qapp, monkeypatch):
    from types import SimpleNamespace
    from concurrent.futures import Future
    from PySide6.QtWidgets import QWidget
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    monkeypatch.setattr(TotalSpineWidget, 'scan_study', lambda self: None)
    window = QWidget(); window.eagle_eye_mode = 'bone_age'; window._study_uid = '1.2.3'
    window.imaging_tab = SimpleNamespace()
    controller = EagleEyeWorkspaceController(window)
    controller.open_total_spine()
    dialog, widget = controller._total_spine_dialog, controller._total_spine_widget
    widget._future = Future(); widget._kind = 'inference'
    dialog.close(); qapp.processEvents()
    assert not widget._cancel.is_set()
    controller.open_total_spine()
    assert controller._total_spine_dialog is dialog
    controller.teardown()
    assert widget._cancel.is_set() and widget._disposed
    widget._future = None; window.close(); window.deleteLater(); qapp.processEvents()


def test_pdf_report_snapshot_and_escape(tmp_path, qapp):
    from modules.ai_imaging.eagle_eye_total_spine.report import generate_report
    from pypdf import PdfReader
    v = view()
    result = generate_report([v], '1.2.3', notes='<script>synthetic</script>', root=tmp_path)
    folder = Path(result['artifact_directory'])
    data = json.loads((folder/'report.json').read_text())
    assert data['views'][0]['measurements']['curves'][0]['cobb_deg'] == pytest.approx(40)
    assert 'pixels' not in data['views'][0]['image']
    assert not data['clinical_report_signed']
    assert '&lt;script&gt;' in (folder/'report.html').read_text()
    reader = PdfReader(folder/'report.pdf')
    assert len(reader.pages) == 3  # Measurements, annotated evidence, methods.
    assert 'DRAFT' in reader.pages[0].extract_text()


def test_multi_curve_report_is_paginated_and_failed_report_not_published(tmp_path, qapp, monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine.report import generate_report
    from modules.ai_imaging.eagle_eye_brain import organized_report
    from pypdf import PdfReader
    v = view(); v['curves'] = [deepcopy(v['curves'][0]) for _ in range(5)]
    v['rotations'] = [rotation_record(level, 1, 'right') for level in ('T5', 'T6', 'T7', 'T8', 'T9')]
    folder = Path(generate_report([v], '1.2.3', root=tmp_path)['artifact_directory'])
    assert len(PdfReader(folder/'report.pdf').pages) == 7
    before = set(tmp_path.rglob('report.pdf'))
    def fail(*args, **kwargs): raise RuntimeError('Synthetic report failure')
    monkeypatch.setattr(organized_report, 'write_paged_pdf', fail)
    with pytest.raises(RuntimeError): generate_report([v], '1.2.3', root=tmp_path)
    assert set(tmp_path.rglob('report.pdf')) == before
