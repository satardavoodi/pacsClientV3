"""Synthetic required/optional input and descriptive signal-map guards."""
import threading
import uuid
import numpy as np
import pytest
from test_eagle_eye_total_spine import qapp


def request(roles):
    return dict(protocol=1, request_id=uuid.uuid4().hex, module='lumbar-marrow', study_uid='1.2.3',
        parameters=dict(mode='multiparametric', input_protocol=2, inputs_confirmed=True),
        series={r: dict(series_uid=f'1.2.4.{i}', expected_count=9) for i, r in enumerate(roles)})


def test_optional_echo_and_stir_do_not_block_contract():
    from modules.ai_imaging.eagle_eye_remote.contracts import validate
    for extras in ([], ['stir'], ['multiecho'], ['stir', 'multiecho', 'fat', 'water']):
        validate(request(['primary', 'opposed', 't1', 't2', *extras]))
    for missing in ('primary', 'opposed', 't1', 't2'):
        with pytest.raises(ValueError):
            validate(request(set(['primary', 'opposed', 't1', 't2']) - {missing}))
    with pytest.raises(ValueError):
        validate(request(['primary', 'opposed', 't1', 't2', 'fat']))


def test_suggestions_leave_ambiguous_series_unselected():
    from modules.ai_imaging.marrow_inputs import suggest
    def row(uid, description, **meta):
        return dict(series_uid=uid, available=True, description=description,
                    marrow_metadata=dict(sagittal=True, **meta))
    rows = [row('1', 't1 sag'), row('2', 't2 sag'), row('3', 't1 vibe dixon SAG iso opp'),
            row('4', 't1 vibe dixon SAG iso in'), row('5', 'stir sag'), row('6', 'GRE', echo_count=9)]
    assert suggest(rows) == dict(t1='1', t2='2', opposed='3', primary='4', stir='5', multiecho='6')
    assert 't1' not in suggest(rows + [row('7', 't1 sag')])


def test_widget_suggests_roles_and_preserves_manual_override(qapp):
    from modules.ai_imaging.lumbar_marrow_widget import LumbarMarrowWidget
    widget = LumbarMarrowWidget(study_uid='1.2.3', load_inputs=False)
    rows = [dict(series_uid=str(i), available=True, description=name,
                 marrow_metadata=dict(sagittal=True)) for i,name in enumerate(
        ['t1 sag', 't2 sag', 'dixon in sag', 'dixon opp sag', 'stir sag'])]
    widget._series_rows = rows
    for combo in (widget.series, *widget.extra_series.values()):
        combo.addItem('Not selected', None)
        for row in rows:
            combo.addItem(row['description'], row)
    widget.mode.setCurrentIndex(1)
    assert widget.series.currentData()['description'] == 'dixon in sag'
    assert widget.extra_series['opposed'].currentData()['description'] == 'dixon opp sag'
    assert widget.extra_series['multiecho'].currentData() is None
    widget.confirm.setChecked(True)
    widget.extra_series['t2'].setCurrentIndex(1)
    assert not widget.confirm.isChecked()
    widget.suggest_inputs()
    assert widget.extra_series['t2'].currentIndex() == 1
    widget.teardown(); widget.deleteLater()


def test_calculate_without_optional_inputs_and_corrected_mask(tmp_path):
    import SimpleITK as sitk
    from modules.ai_imaging.marrow_multisequence import calculate, recalculate
    def image(value):
        return sitk.GetImageFromArray(np.full((7, 20, 20), value, np.float32))
    images = dict(primary=image(100), opposed=image(70), t1=image(200), t2=image(300))
    labels = np.zeros((7, 20, 20), np.uint8); labels[:, 3:17, 3:17] = 6
    params = dict(mode='multiparametric', input_protocol=2, inputs_confirmed=True)
    result = calculate(images, [], labels, {6:'L1'}, tmp_path, params, threading.Event())
    row = result['marrow_measurements'][0]
    assert row['signal_drop_median_percent'] == pytest.approx(30)
    assert row['signal_ff_median_percent'] is None
    assert row['t1_signal']['median_si'] == 200
    assert row['echo_measurements'] == []
    assert result['map_kind'] == 'in_opposed_signal_drop'
    assert 'Signal drop %' in (tmp_path/'report.html').read_text(encoding='utf-8')
    out = tmp_path/'corrected'; out.mkdir()
    edited = sitk.GetImageFromArray(labels)
    corrected = recalculate(result, edited, out, threading.Event())
    assert corrected['marrow_measurements'][0]['signal_drop_median_percent'] == pytest.approx(30)


def test_server_loads_core_dicom_stack_without_echo_and_rejects_wrong_geometry(monkeypatch):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian
    from modules.ai_imaging import marrow_multisequence as service, lumbar_marrow
    def stack():
        result = []
        for z in range(3):
            d = Dataset(); d.file_meta = FileMetaDataset(); d.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            d.StudyInstanceUID = '1.2.3'; d.FrameOfReferenceUID = '1.2.5'
            d.ImageOrientationPatient = [0,1,0,0,0,1]; d.ImagePositionPatient = [z,0,0]
            d.PixelSpacing = [1,1]; d.SliceThickness = 1; d.Rows = 8; d.Columns = 8
            d.SamplesPerPixel = 1; d.PhotometricInterpretation = 'MONOCHROME2'
            d.BitsAllocated = 16; d.BitsStored = 16; d.HighBit = 15; d.PixelRepresentation = 0
            d.PixelData = np.full((8,8),100,np.uint16).tobytes()
            result.append(d)
        return result
    headers = {r:stack() for r in ('primary','opposed','t1','t2')}
    records = [dict(path=r,roles=[r]) for r in headers]
    monkeypatch.setattr(service,'read_headers',lambda paths:headers[paths[0]])
    monkeypatch.setattr(lumbar_marrow,'validate_t1_headers',lambda paths:None)
    images, planes = service.load_inputs(records,dict(input_protocol=2))
    assert set(images) == set(headers) and planes == []
    headers['opposed'][0].RescaleSlope = 2
    with pytest.raises(ValueError,match='scaling'):
        service.load_inputs(records,dict(input_protocol=2))
    del headers['opposed'][0].RescaleSlope
    headers['t2'][0].FrameOfReferenceUID = '1.2.6'
    with pytest.raises(ValueError,match='frames of reference'):
        service.load_inputs(records,dict(input_protocol=2))
