"""Synthetic native-slab location and tissue-normalized enhancement screens."""
import numpy as np
import SimpleITK as sitk


def im(a):
    return sitk.GetImageFromArray(np.asarray(a))


def test_topography_does_not_bridge_unobserved_slice_gap():
    from modules.ai_imaging.eagle_eye_brain.lesion_characterization import locations
    a=np.full((4,10,10),2,np.uint16);mask=np.zeros_like(a,np.uint8)
    a[0,4,4]=4;mask[1,4,4]=1
    a[1,4,7]=4;mask[1,4,6]=1
    data=locations(im(mask),im(a),thickness=2)
    assert 'Periventricular contact' not in data['rows'][0]['regions']
    assert 'Periventricular contact' in data['rows'][1]['regions']
    assert data['rows'][1]['side']=='Left'


def test_global_gain_offset_is_not_enhancement_but_focal_increase_is():
    from modules.ai_imaging.eagle_eye_brain.lesion_characterization import enhancement
    rng=np.random.default_rng(3)
    a=np.full((24,24,24),2,np.uint16);a[:12]=3
    pre=np.where(a==2,100.,60.)+rng.normal(0,4,a.shape)
    post=pre*2+20
    ids=np.zeros(a.shape,np.uint32);ids[15:19,10:14,10:14]=1
    coverage=np.ones(a.shape,np.uint8)
    result,_=enhancement(im(pre.astype('float32')),im(post.astype('float32')),im(a),im(ids),im(coverage))
    assert result['lesions'][0]['assessment']=='No focal increase detected by screen'
    post[15:19,10:14,10:14]+=80
    result,_=enhancement(im(pre.astype('float32')),im(post.astype('float32')),im(a),im(ids),im(coverage))
    assert result['lesions'][0]['assessment']=='Possible enhancement; confirm on native T1'


def test_missing_coverage_cannot_be_called_non_enhancing():
    from modules.ai_imaging.eagle_eye_brain.lesion_characterization import enhancement
    rng=np.random.default_rng(5);pre=rng.normal(100,10,(16,16,16)).astype('float32')
    a=np.full(pre.shape,2,np.uint16);a[:8]=3;pre[:8]-=40
    ids=np.zeros(pre.shape,np.uint32);ids[10:14,5:9,5:9]=1
    coverage=np.ones(pre.shape,np.uint8);coverage[ids>0]=0
    result,_=enhancement(im(pre),im(pre),im(a),im(ids),im(coverage))
    assert result['lesions'][0]['assessment'].startswith('Not evaluable')

def test_primary_candidate_missing_on_t1_is_preserved_with_reason():
    from modules.ai_imaging.eagle_eye_brain.lesion_characterization import preserve_primary_ids
    ids=np.zeros((3,4,5),np.uint32);ids[1,1,1]=1;ids[1,2,3]=2
    result={'lesions':[dict(component_id=1,assessment='No focal increase detected by screen')]}
    preserve_primary_ids(result,im(ids),im(np.ones(ids.shape,np.uint8)))
    assert len(result['lesions'])==2
    assert result['lesions'][1]['assessment']=='Not evaluable'


def test_boundary_increase_is_not_reported_as_plain_enhancement():
    from modules.ai_imaging.eagle_eye_brain.lesion_characterization import enhancement
    rng=np.random.default_rng(3);a=np.full((24,24,24),2,np.uint16);a[:12]=3
    pre=np.where(a==2,100.,60.)+rng.normal(0,4,a.shape);post=pre.copy()
    ids=np.zeros(a.shape,np.uint32);ids[15:19,10:14,10:14]=1
    a[15:19,10:14,9]=4;a[15:19,10:14,14]=4
    post[ids>0]+=40
    result,_=enhancement(im(pre.astype('float32')),im(post.astype('float32')),im(a),im(ids),im(np.ones(a.shape,np.uint8)))
    assert result['lesions'][0]['assessment'].startswith('Indeterminate: boundary')

def test_incompatible_pair_has_no_positive_or_negative_claim():
    from modules.ai_imaging.eagle_eye_brain.lesion_characterization import enhancement
    import json
    rng=np.random.default_rng(33);a=np.full((24,24,24),2,np.uint16);a[:12]=3
    pre=np.where(a==2,100.,60.)+rng.normal(0,4,a.shape)
    post=rng.uniform(10,150,a.shape)
    ids=np.zeros(a.shape,np.uint32);ids[15:19,10:14,10:14]=1
    result,_=enhancement(im(pre.astype('float32')),im(post.astype('float32')),im(a),im(ids),im(np.ones(a.shape,np.uint8)))
    assert not result['quality_passed']
    assert result['lesions'][0]['assessment']=='Not evaluable'
    json.dumps(result,allow_nan=False)
