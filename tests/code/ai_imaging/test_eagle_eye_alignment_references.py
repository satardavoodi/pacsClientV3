"""Guard reference meaning, age scope, units and coverage without patient data."""
from test_eagle_eye_alignment import image, points, qapp


def test_every_report_measurement_has_reference_context():
    from modules.ai_imaging.eagle_eye_alignment.geometry import MEASUREMENT_LABELS
    from modules.ai_imaging.eagle_eye_alignment.references import REFERENCE
    assert set(REFERENCE)==set(MEASUREMENT_LABELS)|{'jlo_deg','lld','lld_percent'}
    assert REFERENCE['mpta_deg']['low']==85 and REFERENCE['ldta_deg']['high']==92
    assert REFERENCE['hka_deg']['kind']=='neutral_band'
    assert REFERENCE['ahka_deg']['kind']=='classification_band'
    assert REFERENCE['mad']['kind']=='published_summary' and 'low' not in REFERENCE['mad']
    for key in ('lld','limb_length','femur_length','tibia_length'):
        assert REFERENCE[key]['kind']=='no_universal_range'


def test_pediatric_and_unknown_age_do_not_get_matched_adult_norms():
    from modules.ai_imaging.eagle_eye_alignment.references import reference_text,scope_text,age_at_study
    sample=image()
    assert 'age unavailable' in scope_text(sample)
    sample['identity']['birth_date']='20100915'
    assert age_at_study(sample)==15
    assert 'not applicable' in reference_text('mpta_deg',sample)
    sample['identity']['birth_date']='20000914'
    assert age_at_study(sample)==26 and reference_text('mpta_deg',sample)=='85-90 deg [1]'


def test_pixel_mad_is_not_compared_with_millimeter_summary():
    from modules.ai_imaging.eagle_eye_alignment.references import reference_text,reference_manifest
    sample=image();sample['calibrated']=False
    assert 'not comparable to px' in reference_text('mad',sample)
    record=reference_manifest(sample)
    assert record['entries']['mad']['unit']=='mm' and record['version']
    record['entries']['mpta_deg']['low']=999
    assert reference_manifest(sample)['entries']['mpta_deg']['low']==85


def test_widget_and_pdf_share_the_reference_registry(qapp):
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    from modules.ai_imaging.eagle_eye_alignment.report import render_html
    w=AlignmentWidget(study_uid='1.2.3');w._apply_image(image());w.points={'R':points(),'L':points('L')};w._redraw_points()
    assert w.table.columnCount()==4
    html=render_html(w.image,w.points,{})
    for row in range(w.table.rowCount()):
        text=w.table.item(row,3).text()
        assert text in html
    assert '177-183 deg; CPAK neutral [3]' in html
    assert 'age unavailable' in html
    w.teardown();w.deleteLater();qapp.processEvents()
