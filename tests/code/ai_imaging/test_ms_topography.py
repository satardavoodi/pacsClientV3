"""Synthetic anatomical contact and conditional McDonald-report guards."""
from pathlib import Path
import numpy as np
import pytest
import SimpleITK as sitk
from modules.ai_imaging.eagle_eye_brain.ms_assessment import assess_topography, face_neighbors, ms_pages


def fixture_arrays():
    anatomy=np.full((24,24,24),2,np.uint16)
    anatomy[3:20,3:20,4]=4
    anatomy[3:20,3:20,19]=1003
    anatomy[20:24,:,:]=16
    return anatomy,np.zeros_like(anatomy,np.uint8)


def assess(a,b):
    return assess_topography(sitk.GetImageFromArray(b),sitk.GetImageFromArray(a),{'1003':'ctx-lh-caudalmiddlefrontal'})


def test_face_contact_does_not_wrap_or_bridge_gap():
    a=np.zeros((5,5,5),bool);a[0,2,2]=True
    n=face_neighbors(a)
    assert n[1,2,2] and not n[-1,2,2] and not n[1,3,2]


def test_two_distinct_contact_regions_flag_only_conditional_support():
    a,b=fixture_arrays()
    b[7:12,8,5]=1; b[13:18,10,18]=1
    result=assess(a,b)
    assert result['potential_brain_dis_support']
    assert result['diagnosis'] is None and result['physician_confirmation_required']
    assert result['unique_candidate_count']==2
    assert not next(r for r in result['regions'] if r['region']=='Corpus callosum')['available']


def test_near_ventricle_with_intervening_wm_is_not_contact():
    a,b=fixture_arrays();b[7:12,8,6]=1
    result=assess(a,b)
    assert result['regions'][0]['count']==0
    assert not result['potential_brain_dis_support']


def test_cortical_overlap_is_not_clean_contact_support():
    a,b=fixture_arrays();b[7:12,8,5]=1;b[13:18,10,18:20]=1
    result=assess(a,b)
    assert result['regions'][1]['count']==1
    assert result['regions'][1]['size_candidate_count']==0
    assert not result['potential_brain_dis_support']


def test_one_bridge_component_cannot_supply_two_dis_regions():
    a,b=fixture_arrays();b[8,8,5:19]=1
    result=assess(a,b)
    assert result['regions'][0]['count']==result['regions'][1]['count']==1
    assert result['unique_candidate_count']==1
    assert not result['potential_brain_dis_support']


def test_small_contact_is_retained_but_not_used_for_support():
    a,b=fixture_arrays();b[8,8,5]=1;b[12,10,18]=1
    result=assess(a,b)
    assert result['unique_candidate_count']==2
    assert result['regions'][0]['size_candidate_count']==0
    assert not result['potential_brain_dis_support']


def test_missing_anatomical_landmarks_is_indeterminate_not_negative():
    a,b=fixture_arrays();a[:]=2;b[8,8,8]=1
    result=assess(a,b)
    assert result['conclusion'].startswith('Indeterminate')


def test_ms_pages_are_context_specific_and_never_diagnose():
    assert ms_pages({'clinical_context':{'primary_disease':'svd'}})==[]
    html=''.join(ms_pages({'clinical_context':{'primary_disease':'ms'}}))
    assert 'Not assessed' in html and 'MS diagnosis is not established' in html
    assert 'five anatomical' in html and 'physician must confirm' in html


def test_ms_pdf_render(tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    from modules.ai_imaging.eagle_eye_brain.lesion_report import write_lesion_report
    app=QApplication.instance() or QApplication([])
    for name in ('arial.ttf','arialbd.ttf'):
        path=Path('C:/Windows/Fonts')/name
        if path.exists():QFontDatabase.addApplicationFont(str(path))
    a,b=fixture_arrays();b[7:12,8,5]=1;b[13:18,10,18]=1
    flair=sitk.GetImageFromArray(np.arange(a.size,dtype=np.float32).reshape(a.shape))
    mask=sitk.GetImageFromArray(b)
    from modules.ai_imaging.eagle_eye_brain.lesions import measure_mask
    result=dict(patient_context={'patient_name':'Synthetic MS review example','patient_id':'SYNTHETIC'},
                age_years=35,sex='female',clinical_context={'primary_disease':'ms'},
                metrics=measure_mask(flair,mask),ms_topography=assess(a,b))
    write_lesion_report(result,flair,mask,tmp_path)
    assert (tmp_path/'report.pdf').read_bytes().startswith(b'%PDF-')
    html=(tmp_path/'report.html').read_text(encoding='utf-8')
    assert 'Potential two-region' in html and 'MS candidate review list' in html
