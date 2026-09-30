import numpy as np
import SimpleITK as sitk
from modules.ai_imaging.eagle_eye_brain.lesion_corroboration import comparison_classes, t1_support

def im(a): return sitk.GetImageFromArray(a)

def test_three_classes_preserve_secondary_and_matched_extent():
    p=np.zeros((3,8,8),np.uint32);s=p.copy()
    p[1,1,1]=1;p[1,4,4]=2
    s[1,1,1:3]=4;s[1,6,6]=5
    out=comparison_classes(im(p),im(s),[{'primary_id':1,'secondary_id':4}])
    a=sitk.GetArrayFromImage(out)
    assert a[1,1,2]==3 and a[1,4,4]==1 and a[1,6,6]==2

def test_t1_support_preserves_ids_and_excludes_csf_boundary():
    a=np.full((24,24,24),2,np.uint16);t=np.full(a.shape,100,np.float32)
    ids=np.zeros(a.shape,np.uint32);ids[10:14,10:14,10:14]=1
    t[ids==1]=50
    r=t1_support(im(t),im(a),im(ids),[1,2])
    assert r['rows'][0]['assessment']=='Low T1 signal; supportive evidence'
    assert r['rows'][1]['assessment']=='Not evaluable'
    a[9:15,9:15,9:15]=4
    r=t1_support(im(t),im(a),im(ids),[1,2])
    assert r['rows'][0]['assessment']=='Indeterminate boundary or insufficient tissue'
    assert np.count_nonzero(ids)==64

def test_patient_reference_pages_use_scientific_citations():
    from modules.ai_imaging.eagle_eye_brain.volbrain_reference import pages
    html=''.join(pages({'rows':[]}))
    assert 'github' not in html.lower()
    assert '10.1002/hbm.23743' in html


def test_t1_report_explains_persistence_without_diagnosing_chronicity():
    from modules.ai_imaging.eagle_eye_brain.lesion_corroboration import pages
    html=''.join(pages({'t1_support':{'rows':[{'component_id':1,'lesion_to_wm_ratio':.7,'assessment':'Low T1 signal; supportive evidence'}]}}))
    assert 'axonal loss' in html
    assert 'longitudinal confirmation' in html
    assert '10.1111/jon.12439' in html
