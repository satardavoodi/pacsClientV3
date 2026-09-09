import pytest
from modules.ai_imaging.eagle_eye_brain import volbrain_reference as vr
from modules.ai_imaging.eagle_eye_brain.normative import BrainDemographics
from modules.ai_imaging.eagle_eye_brain.contracts import BrainError

def test_interval_uses_own_icv_and_retains_no_scores():
    source={'Brainstem':{f'{a}yo_{s}':str(v) for a in (17,18) for s,v in [('lower_bound',1),('median',1.5),('upper_bound',2)]}}
    rows=[dict(structure='brain-stem',volume_mm3=21000.,volume_cm3=21.,method='SynthSeg posterior'),dict(structure='total intracranial',volume_mm3=1500000.,volume_cm3=1500.,method='SynthSeg posterior')]
    result=vr.assess(rows,BrainDemographics(17.5,'female'),source)
    r=result['rows'][0]
    assert (r['lower_cm3'],r['upper_cm3'])==(15,30)
    assert r['position']=='Within published interval'
    assert r['z_score'] is None and r['percentile'] is None and not result['qualified']
    assert rows[0]['volume_cm3']==21

def test_unknown_atlas_and_age_not_filled():
    rows=[dict(structure='ctx-lh-insula',volume_mm3=1000.,volume_cm3=1.,method='SynthSeg posterior'),dict(structure='total intracranial',volume_mm3=1000000.,volume_cm3=1000.,method='SynthSeg posterior')]
    assert vr.assess(rows,BrainDemographics(17,'female'),{})['rows']==[]
    assert vr.assess(rows,BrainDemographics(.5,'female'),{})['status']=='unavailable'
    assert vr.assess(rows,BrainDemographics(91,'female'),{})['status']=='unavailable'

def test_duplicate_estimator_and_units_rejected():
    good=dict(structure='total intracranial',volume_mm3=1000000.,volume_cm3=1000.,method='SynthSeg posterior')
    with pytest.raises(BrainError):vr.assess([good,good],BrainDemographics(17,'female'),{})
    with pytest.raises(BrainError):vr.assess([dict(good,volume_cm3=1)],BrainDemographics(17,'female'),{})

def test_volbrain_is_default_ui_reference_and_range_page_not_z_scores():
    from modules.ai_imaging.eagle_eye_brain.normative import REFERENCES
    assert REFERENCES[0].id=='volbrain'
    from modules.ai_imaging.eagle_eye_brain.reference_report import pages
    assert 'Published volBrain' in ''.join(pages(dict(status='published_intervals',reference_id='volbrain',rows=[],reasons=[])))


def test_missing_or_changed_source_never_reuses_stale_scores(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, 'data_root', lambda: tmp_path)
    (tmp_path / 't1.nii.gz').write_bytes(b'synthetic image')
    result = dict(model='SynthSeg 2.0', source_sha256=vr.sha256(tmp_path / 't1.nii.gz'),
                  posterior_rows=[dict(structure='total intracranial', volume_cm3=1500,
                                       volume_mm3=1500000, method='SynthSeg posterior', z_score=9)])
    for content in (None, 'changed reference'):
        if content: (tmp_path / 'bounds_female.csv').write_text(content)
        vr.attach_reference(result, tmp_path, BrainDemographics(17, 'female'))
        assert result['normative']['status'] == 'unavailable'
        assert result['posterior_rows'][0]['z_score'] is None
        assert result['posterior_rows'][0]['volume_cm3'] == 1500
        assert 'unavailable' in result['normative_status']
    result['source_sha256'] = 'mismatched image'
    with pytest.raises(BrainError):
        vr.attach_reference(result, tmp_path, BrainDemographics(17, 'female'))


def test_medial_temporal_ranges_remain_side_specific():
    from modules.ai_imaging.eagle_eye_brain.medial_temporal import section_html
    reference = dict(reference_id='volbrain', rows=[
        dict(structure='left hippocampus', lower_cm3=3, upper_cm3=4),
        dict(structure='right hippocampus', lower_cm3=5, upper_cm3=6)])
    html = section_html(dict(normative=reference, posterior_rows=[]))
    assert 'R: 5.000 - 6.000; L: 3.000 - 4.000' in html
    assert 'Published 95%' in html
    assert 'Normal ranges for either side are unavailable' not in html


def test_cortical_analogue_is_display_only_and_not_an_atrophy_flag():
    source = {'Left opercular inf. frontal gyrus_left': {
        f'46yo_{suffix}': value for suffix, value in
        [('lower_bound', '.2'), ('median', '.3'), ('upper_bound', '.4')]}}
    rows = [dict(structure='ctx-lh-parsopercularis', volume_mm3=1000., volume_cm3=1., method='SynthSeg posterior'),
            dict(structure='total intracranial', volume_mm3=1500000., volume_cm3=1500., method='SynthSeg posterior')]
    result = vr.assess(rows, BrainDemographics(46, 'male'), source)
    row = result['rows'][0]
    assert row['source_row'] == 'Left opercular inf. frontal gyrus_left'
    assert row['lower_cm3'] == 3 and row['upper_cm3'] == 6
    assert row['position'] == 'Atlas analogue only'
    assert row['mapping_status'] == 'anatomical_analogue'
    assert vr.range_text(result, 'ctx-lh-parsopercularis').endswith(' *')
    assert row['z_score'] is None and not result['diagnostic_flags_enabled']


def test_divided_cortical_regions_never_use_partial_or_summed_bounds():
    assert 'ctx-lh-superiorfrontal' not in vr.MAPPING
    assert 'ctx-lh-rostralmiddlefrontal' not in vr.MAPPING
    assert 'ctx-lh-insula' not in vr.MAPPING
    assert 'ctx-lh-parsopercularis' in vr.MAPPING


def test_report_resolves_native_cortical_keys():
    from modules.ai_imaging.eagle_eye_brain.organized_report import render_html
    rows = [dict(structure=f'ctx-{side}-parsopercularis', volume_cm3=4., volume_mm3=4000.) for side in ('lh','rh')]
    reference = dict(reference_id='volbrain', rows=[
        dict(structure=f'ctx-{side}-parsopercularis', observed_cm3=4., icv_percent=.3,
             lower_cm3=3., upper_cm3=6., source_row='test', position='Atlas analogue only',
             mapping_status='anatomical_analogue') for side in ('lh','rh')])
    html = render_html(dict(posterior_rows=rows, normative=reference, qc_scores={},
                            model_revision='synthetic', flair_status='Not supplied'))
    assert 'R: 3.000 - 6.000 *; L: 3.000 - 6.000 *' in html


@pytest.mark.parametrize('value,expected', [(7.5,False),(7.49,True),(25.,False),(25.01,True),(22.,False),(15.,False)])
def test_large_deviation_uses_nearest_endpoint_not_midpoint(value, expected):
    row = dict(observed_cm3=value, lower_cm3=10., upper_cm3=20.)
    assert vr.large_deviation(row) is expected


def test_red_measurement_is_escaped_and_science_is_cited():
    from modules.ai_imaging.eagle_eye_brain.organized_report import _cell
    ref = dict(rows=[dict(structure='test',observed_cm3=30.,lower_cm3=10.,upper_cm3=20.)])
    html = _cell(vr.highlight(ref,'test','30.000'))
    assert '#b91c1c' in html and "align='center'" in html
    assert 'Towards a unified analysis' in vr.scientific_reference_page()
    assert '10.1002/hbm.23743' in vr.scientific_reference_page()
