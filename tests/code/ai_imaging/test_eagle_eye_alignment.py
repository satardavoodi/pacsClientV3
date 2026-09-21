"""Synthetic alignment geometry, identity and UI guards; no clinical database."""
import math
import numpy as np
import pytest


def points(side='R', offset=0):
    x = 100 if side == 'R' else 300
    med = 1 if side == 'R' else -1
    return dict(hip=[x, 10], knee=[x+offset, 410],
                femur_lateral=[x+offset-30*med,400], femur_medial=[x+offset+30*med,400],
                tibia_lateral=[x+offset-30*med,420], tibia_medial=[x+offset+30*med,420],
                ankle_lateral=[x-20*med,810], ankle_medial=[x+20*med,810])


def test_alignment_function_available_for_dx_and_cr_only():
    from modules.ai_imaging.eagle_eye_function_catalog import function_options_for_modality
    for modality in ('DX', 'CR'):
        assert any(x.key == 'alignment_view' and x.enabled for x in function_options_for_modality(modality))
    assert all(x.key != 'alignment_view' for x in function_options_for_modality('MR'))


def test_neutral_lengths_and_separate_joint_endpoints():
    from modules.ai_imaging.eagle_eye_alignment.geometry import measure_leg
    r = measure_leg(points(), 'R', (.5,.5), calibrated=True)
    assert r['hka_deg'] == 0
    assert r['mldfa_deg'] == r['mpta_deg'] == r['ldta_deg'] == 90
    assert r['femur_length'] == r['tibia_length'] == 195
    assert r['limb_length'] == 400
    assert r['length_unit'] == 'mm'


@pytest.mark.parametrize('side,offset',[('R',-20),('L',20)])
def test_varus_laterality_and_obtuse_angle_preserved(side,offset):
    from modules.ai_imaging.eagle_eye_alignment.geometry import measure_leg
    r=measure_leg(points(side,offset),side)
    assert r['hka_deg'] == pytest.approx(-2*math.degrees(math.atan(20/400)))
    assert r['mldfa_deg'] > 90
    assert r['mpta_deg'] < 90
    assert r['mad'] == pytest.approx(20)


def test_uncalibrated_lengths_stay_pixels_but_angles_use_aspect():
    from modules.ai_imaging.eagle_eye_alignment.geometry import measure_bilateral
    p={'R':points('R',-20),'L':points('L',20)}
    r=measure_bilateral(p,(.2,.4))
    assert r['R']['limb_length']==800
    assert r['R']['hka_deg']==pytest.approx(-2*math.degrees(math.atan(40/400)))
    assert r['R']['length_unit']=='px'


def test_single_leg_unverified_scale_does_not_label_scaled_lengths_as_pixels():
    from modules.ai_imaging.eagle_eye_alignment.geometry import measure_leg
    result = measure_leg(points('R', -20), 'R', (.2, .4))
    assert result['limb_length'] == 800
    assert result['mad'] == pytest.approx(20)
    assert result['hka_deg'] == pytest.approx(-2*math.degrees(math.atan(40/400)))


@pytest.mark.parametrize('bad',[float('nan'),float('inf')])
def test_invalid_landmarks_rejected(bad):
    from modules.ai_imaging.eagle_eye_alignment.geometry import measure_leg
    p=points();p['hip'][0]=bad
    with pytest.raises(ValueError):measure_leg(p,'R')


def test_degenerate_joint_line_rejected():
    from modules.ai_imaging.eagle_eye_alignment.geometry import measure_leg
    p=points();p['femur_lateral']=p['femur_medial']
    with pytest.raises(ValueError):measure_leg(p,'R')


def dicom(tmp_path,*,study='1.2.3',photometric='MONOCHROME2'):
    from pydicom.dataset import FileDataset,FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian,DigitalXRayImageStorageForPresentation
    meta=FileMetaDataset();meta.TransferSyntaxUID=ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID=DigitalXRayImageStorageForPresentation;meta.MediaStorageSOPInstanceUID='1.2.3.4.5'
    ds=FileDataset(str(tmp_path/'image.dcm'),{},file_meta=meta,preamble=b'\0'*128)
    ds.StudyInstanceUID=study;ds.SeriesInstanceUID='1.2.3.4';ds.SOPInstanceUID=meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID=meta.MediaStorageSOPClassUID;ds.Modality='DX';ds.PatientName='SYNTHETIC';ds.PatientID='SYNTHETIC'
    ds.Rows=900;ds.Columns=400;ds.SamplesPerPixel=1;ds.PhotometricInterpretation=photometric
    ds.BitsAllocated=16;ds.BitsStored=16;ds.HighBit=15;ds.PixelRepresentation=0
    ds.ImagerPixelSpacing=[.2,.2]
    ds.PixelData=np.tile(np.arange(400,dtype=np.uint16),(900,1)).tobytes()
    ds.save_as(ds.filename,write_like_original=False)
    return ds


def test_dicom_identity_checked_before_pixels(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.service import load_image
    ds=dicom(tmp_path)
    with pytest.raises(ValueError,match='another examination'):load_image(ds.filename,'9.8.7')


def test_detector_spacing_does_not_invent_patient_plane_length(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.service import load_image
    ds=dicom(tmp_path);r=load_image(ds.filename,'1.2.3')
    assert not r['calibrated'] and r['spacing']==(.2,.2)
    ds.PixelSpacing=[.18,.18];ds.PixelSpacingCalibrationType='FIDUCIAL';ds.save_as(ds.filename,write_like_original=False)
    r=load_image(ds.filename,'1.2.3');assert r['calibrated']


def test_monochrome1_and_padding(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.service import load_image
    ds=dicom(tmp_path,photometric='MONOCHROME1');ds.PixelPaddingValue=0;ds.save_as(ds.filename,write_like_original=False)
    p=load_image(ds.filename,'1.2.3')['pixels']
    assert p[0,0]==0 and p[0,1]>p[0,399]


def test_multiframe_and_color_rejected(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.service import load_image
    ds=dicom(tmp_path);ds.NumberOfFrames=2;ds.save_as(ds.filename,write_like_original=False)
    with pytest.raises(ValueError,match='single-frame'):load_image(ds.filename,'1.2.3')


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def image():
    return dict(pixels=np.zeros((900,400),dtype=np.uint8),spacing=(.5,.5),calibrated=True,
                calibration_method='Synthetic calibration',source_sha256='synthetic',
                identity=dict(patient_name='SYNTHETIC <b>',patient_id='TEST',study_date='20260914',study_uid='1.2.3'))


def test_widget_manual_edit_invalidates_review(qapp):
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    w=AlignmentWidget(study_uid='1.2.3');w._apply_image(image())
    w.points={'R':points(),'L':points('L')};w.confirm.setChecked(True);w._redraw_points()
    w.review.setChecked(True);assert w.export.isEnabled()
    w._point_changed('R','knee',95,410);qapp.processEvents()
    assert not w.review.isChecked() and not w.export.isEnabled()
    assert w.metrics['R']['hka_deg']<0
    w.teardown();w.deleteLater();qapp.processEvents()


def test_widget_flip_discards_previous_points(qapp):
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    w=AlignmentWidget(study_uid='1.2.3');w._apply_image(image())
    w.points={'R':points(),'L':points('L')};w.confirm.setChecked(True);w._redraw_points()
    w.flip_image()
    assert w.points=={'R':{},'L':{}} and w.metrics is None
    assert not w.confirm.isChecked() and w.image['flipped']
    w.teardown();w.deleteLater();qapp.processEvents()


def test_cancel_drops_completed_prediction(qapp):
    from concurrent.futures import Future
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    w=AlignmentWidget(study_uid='1.2.3');w._apply_image(image())
    f=Future();f.set_result({'landmarks':{'R':points(),'L':points('L')}})
    w._future=f;w._kind='ai';w._cancel.set();w._poll()
    assert w.points=={'R':{},'L':{}} and w.metrics is None
    w.teardown();w.deleteLater();qapp.processEvents()


def test_report_contains_reviewed_values_and_escaped_identity(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.service import export_report
    from modules.ai_imaging.eagle_eye_alignment.geometry import measure_bilateral
    import json
    p={'R':points(),'L':points('L')};m=measure_bilateral(p,(.5,.5),calibrated=True)
    path=tmp_path/'report.html';export_report(image(),p,m,{'model':'Manual'},path)
    report=path.read_text(encoding='utf-8')
    assert 'SYNTHETIC &lt;b&gt;' in report and 'data:image/png;base64,' in report
    data=json.loads(next(tmp_path.glob('*.json')).read_text())
    assert data['reviewed'] and data['measurements']['R']['limb_length']==400
    assert data['landmarks']==p


def test_closed_widget_does_not_own_running_worker(qapp):
    import threading
    from PySide6.QtCore import QCoreApplication,QEvent
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    w=AlignmentWidget(study_uid='1.2.3');gate=threading.Event();cancel=w._cancel
    w._submit('scan',lambda:gate.wait(2))
    w.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    assert cancel.is_set();gate.set()
