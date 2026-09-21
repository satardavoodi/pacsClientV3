"""Synthetic indication and longitudinal review contracts; no clinical database."""
import json
import threading
from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
from modules.ai_imaging.eagle_eye_brain.lesion_indication import clinical_context, context_html
from modules.ai_imaging.eagle_eye_brain.lesion_longitudinal import validate_pair, compare_masks


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    application = QApplication.instance() or QApplication([])
    for font in ('arial.ttf', 'arialbd.ttf'):
        path = Path('C:/Windows/Fonts') / font
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    yield application
    application.processEvents()


def contexts():
    old = dict(patient_id='synthetic', birth_date='19800101', sex='F', study_uid='old', study_date='20200101')
    return old, dict(old, study_uid='new', study_date='20210101')


@pytest.mark.parametrize('change', ['patient_id', 'birth_date', 'sex', 'study_uid', 'study_date'])
def test_comparison_rejects_identity_and_chronology_conflicts(change):
    old, new = contexts()
    new[change] = old[change] if change in ('study_uid', 'study_date') else 'conflict'
    with pytest.raises(BrainError):
        validate_pair(old, new)


def test_comparison_uses_dicom_dates():
    assert validate_pair(*contexts()) == 366


def test_svd_context_is_declaration_not_fazekas_or_percentile():
    html = context_html({'clinical_context': clinical_context('svd', '<script>')})
    assert 'Small-vessel disease' in html and '&lt;script&gt;' in html
    assert 'Fazekas: not assessed' in html and 'percentile: not calculated' in html
    assert 'not an automated diagnosis' in html
    assert 'Not recorded' in context_html({})
    with pytest.raises(BrainError):
        clinical_context('invented')


def test_required_context_and_ms_only_comparison(app):
    from modules.ai_imaging.eagle_eye_brain.lesion_widget import BrainLesionWidget
    widget = BrainLesionWidget(study_uid='synthetic')
    widget._selected_series = {'path': 't1', 'series_uid': '1'}
    widget._selected_flair = {'path': 'flair', 'series_uid': '2'}
    widget.confirm.setChecked(True)
    widget._start()
    assert widget._future is None and 'primary disease' in widget.status.text()
    widget.primary_disease.setCurrentIndex(widget.primary_disease.findData('ms'))
    assert not widget.ms_comparison.isHidden()
    widget.ms_comparison.setChecked(True)
    widget._comparison_pair = ['synthetic']
    widget.primary_disease.setCurrentIndex(widget.primary_disease.findData('svd'))
    assert not widget.ms_comparison.isChecked() and widget._comparison_pair is None
    widget.deleteLater()


def masks():
    a = np.zeros((24, 24, 24), dtype=np.uint8)
    a[3:7, 3:7, 3:7] = 1
    return a, a.copy()


def test_stable_mask_has_no_new_or_enlarged_candidates():
    a,b = masks()
    result = compare_masks(sitk.GetImageFromArray(a), sitk.GetImageFromArray(b))
    assert result['possible_new'] == result['possible_enlarged'] == 0


def test_disjoint_new_and_growth_are_review_candidates():
    a,b = masks()
    b[3:10, 3:7, 3:7] = 1
    b[18:20, 18:20, 18:20] = 1
    result = compare_masks(sitk.GetImageFromArray(a), sitk.GetImageFromArray(b))
    assert result['possible_new'] == result['possible_enlarged'] == 1


def test_one_voxel_border_difference_does_not_claim_growth():
    a,b = masks()
    b[7, 3:7, 3:7] = 1
    assert compare_masks(sitk.GetImageFromArray(a), sitk.GetImageFromArray(b))['possible_enlarged'] == 0


def test_merge_is_not_declared_enlargement():
    a,b = masks()
    a[3:7, 10:14, 3:7] = 1
    b[3:7, 3:14, 3:7] = 1
    result = compare_masks(sitk.GetImageFromArray(a), sitk.GetImageFromArray(b))
    assert result['rows'][0]['status'] == 'Merge / split: review'
    assert result['possible_enlarged'] == 0


def test_report_revision_preserves_original_and_measures_mask(tmp_path, app):
    from modules.ai_imaging.eagle_eye_brain.lesion_indication import regenerate_lesion_report
    a,_ = masks()
    mask = sitk.GetImageFromArray(a)
    flair = sitk.Cast(mask, sitk.sitkFloat32)
    sitk.WriteImage(mask, str(tmp_path/'mask.nii.gz'))
    sitk.WriteImage(flair, str(tmp_path/'flair.nii.gz'))
    result = dict(analysis_type='brain_lesions', pdf_available=True, patient_context=contexts()[0],
                  mask_path=str(tmp_path/'mask.nii.gz'), age_years=40, sex='female', metrics={})
    source=tmp_path/'result.json'; source.write_text(json.dumps(result))
    (tmp_path/'report.pdf').write_bytes(b'original')
    revised=regenerate_lesion_report(source,'svd')
    assert (tmp_path/'report.pdf').read_bytes() == b'original'
    assert revised['metrics']['total_volume_mm3'] == 64
    assert revised['clinical_context']['primary_disease'] == 'svd'
    assert (Path(revised['artifact_directory'])/'report.pdf').read_bytes().startswith(b'%PDF-')


def test_comparison_report_records_native_delta_and_no_division_by_zero(tmp_path, monkeypatch, app):
    from modules.ai_imaging.eagle_eye_brain import lesion_longitudinal as module
    old_context,new_context=contexts()
    a,b=masks(); a[:]=0
    results=[]
    for index,(array,context) in enumerate(((a,old_context),(b,new_context))):
        directory=tmp_path/str(index); directory.mkdir()
        mask=sitk.GetImageFromArray(array)
        sitk.WriteImage(mask,str(directory/'mask.nii.gz'))
        sitk.WriteImage(sitk.Cast(mask,sitk.sitkFloat32),str(directory/'flair.nii.gz'))
        results.append(dict(patient_context=context, artifact_directory=str(directory),mask_path=str(directory/'mask.nii.gz'),
                            model_manifest_sha256='same-synthetic-model',clinical_context=clinical_context('ms'),
                            age_years=40,sex='female', analysis_type='brain_lesions'))
    monkeypatch.setattr(module,'register_previous',lambda *args: sitk.Transform(3,sitk.sitkIdentity))
    result=module.compare_results(*results)
    assert result['longitudinal']['volume_change_percent'] is None
    assert result['longitudinal']['possible_new'] == 1
    assert result['pdf_available']


def test_real_rigid_registration_identical_phantom_and_cancel():
    from modules.ai_imaging.eagle_eye_brain.lesion_longitudinal import register_previous
    z,y,x=np.mgrid[:32,:32,:32]
    image=sitk.GetImageFromArray((100*np.exp(-((x-14)**2+(y-17)**2+(z-15)**2)/50)
                                +40*np.exp(-((x-22)**2+(y-9)**2+(z-18)**2)/10)).astype(np.float32))
    transform=register_previous(image,image,threading.Event())
    assert np.linalg.norm(np.asarray(transform.TransformPoint((16,16,16)))-16) < 1
    token=threading.Event(); token.set()
    with pytest.raises(BrainError,match='cancelled'):
        register_previous(image,image,token)


def test_svd_visual_grade_is_explicit_clinician_data():
    from modules.ai_imaging.eagle_eye_brain.svd_assessment import svd_pages
    value=clinical_context('svd',fazekas_overall=1)
    assert value['fazekas_overall']==1
    assert '1 (mild)' in svd_pages({'clinical_context':value})[0]
    with pytest.raises(BrainError):
        clinical_context('ms',fazekas_overall=1)
    with pytest.raises(BrainError):
        clinical_context('svd',fazekas_overall=4)


def test_svd_spatial_compartments_conserve_volume_and_keep_outside_voxels():
    from modules.ai_imaging.eagle_eye_brain.svd_assessment import spatial_burden
    a=np.zeros((12,12,12),np.uint16)
    a[2:10,2:10,1:6]=2; a[2:10,2:10,6:11]=41
    a[5,5,5]=4; a[5,5,6]=43
    a[2,2,1]=1003; a[2,2,10]=2003
    b=np.zeros_like(a,np.uint8)
    b[4,4,4]=1;b[4,4,8]=1;b[0,0,0]=1
    anatomy=sitk.GetImageFromArray(a);mask=sitk.GetImageFromArray(b)
    result=spatial_burden(mask,anatomy,{'1003':'ctx-lh-caudalmiddlefrontal','2003':'ctx-rh-caudalmiddlefrontal'})
    assert sum(r['volume_mm3'] for r in result['compartments'])==3
    assert result['compartments'][-1]['volume_mm3']==1
    assert sum(r['volume_mm3'] for r in result['cerebral_wm_regions'])==2
