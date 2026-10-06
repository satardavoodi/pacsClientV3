"""Synthetic statistical, provenance and PDF publication guards."""
import math
import pytest


def result():
    return dict(study_id='1.2.3', patient_id='fixture', sex='M',
                predicted_bone_age_months=125.68,
                confirmed_demographics=dict(study_uid='1.2.3', patient_id='fixture',
                    name='Synthetic Child', sex='M', chronological_age_months=120,
                    physician_confirmed=True, age_source='physician'))


def test_reference_uses_population_mean_not_equality_line():
    from modules.ai_imaging.eagle_eye_engines.bone_age_reference import calculate
    r = calculate(120,125.68,'M')
    assert r['z_score'] == 0 and r['estimated_reference_percentile'] == 50
    assert r['difference_from_chronological_months'] == pytest.approx(5.68)
    assert r['reference_range_2sd_months'] == pytest.approx([106.10,145.26])


@pytest.mark.parametrize('sex,age', [('M',2.99),('M',204.01),('F',192.01)])
def test_reference_prohibits_extrapolation(sex,age):
    from modules.ai_imaging.eagle_eye_engines.bone_age_reference import calculate
    with pytest.raises(ValueError,match='reference range'):
        calculate(age,100,sex)


@pytest.mark.parametrize('age,bone,sex', [(math.nan,120,'M'),(120,math.inf,'M'),
                                        (120,120,''),(True,120,'M'),(120,-1,'M')])
def test_reference_rejects_invalid_numeric_or_sex(age,bone,sex):
    from modules.ai_imaging.eagle_eye_engines.bone_age_reference import calculate
    with pytest.raises(ValueError):
        calculate(age,bone,sex)


def test_reference_tails_and_boundaries():
    from modules.ai_imaging.eagle_eye_engines.bone_age_reference import calculate
    for z,percentile,category in [(-2,2.275013,'Within reference range'),
                                 (2,97.724987,'Within reference range'),
                                 (-2.1,1.786442,'Below reference range'),
                                 (2.1,98.213558,'Above reference range')]:
        r=calculate(120,125.68+z*9.79,'M')
        assert r['estimated_reference_percentile'] == pytest.approx(percentile,abs=1e-5)
        assert r['category'] == category
    assert calculate(126,(125.68+137.32)/2,'M')['z_score'] == pytest.approx(0)


@pytest.mark.parametrize('change', ['study','patient','sex','unconfirmed','nonfinite'])
def test_report_rejects_foreign_unconfirmed_or_incompatible_result(change):
    from modules.ai_imaging.eagle_eye_engines.bone_age_report import assessment
    r=result()
    if change == 'study': r['confirmed_demographics']['study_uid']='1.2.9'
    if change == 'patient': r['confirmed_demographics']['patient_id']='other'
    if change == 'sex': r['confirmed_demographics']['sex']='F'
    if change == 'unconfirmed': r['confirmed_demographics']['physician_confirmed']=False
    if change == 'nonfinite': r['predicted_bone_age_months']=math.nan
    with pytest.raises(ValueError): assessment(r,'1.2.3','fixture')


def test_report_outside_table_keeps_measurement_without_percentile():
    from modules.ai_imaging.eagle_eye_engines.bone_age_report import assessment
    r=result(); r['confirmed_demographics']['chronological_age_months']=230
    a=assessment(r,'1.2.3','fixture')
    assert a['reference']['available'] is False
    assert 'z_score' not in a['reference']
    assert a['bone_age_months'] == 125.68


def test_explicit_preview_never_claims_demographic_confirmation():
    from modules.ai_imaging.eagle_eye_engines.bone_age_report import assessment
    r=result(); r['confirmed_demographics']['physician_confirmed']=False
    a=assessment(r,'1.2.3','fixture',preview=True)
    assert a['demographics_confirmed'] is False
    assert a['demographics']['physician_confirmed'] is False


def test_report_uses_dates_for_fractional_age_and_escapes_identity():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from modules.ai_imaging.eagle_eye_engines.bone_age_report import assessment, render_html
    r=result(); r['confirmed_demographics'].update(name='<b>Synthetic</b>',
        birth_date='2016-01-01',study_date='2026-01-16',age_source='birth_date')
    a=assessment(r,'1.2.3','fixture')
    assert 120 < a['chronological_age_months'] < 121
    html=render_html(a)
    assert '&lt;b&gt;Synthetic&lt;/b&gt;' in html and '<b>Synthetic</b>' not in html
    assert 'not a model confidence interval' in html
    assert 'not a height percentile' in html


def test_pdf_real_writer_and_atomic_publication(tmp_path):
    from PySide6.QtWidgets import QApplication
    from pypdf import PdfReader
    from modules.ai_imaging.eagle_eye_engines.bone_age_report import create_report
    app=QApplication.instance() or QApplication([])
    data=result(); data.update(checkpoint_sha256='a'*64,engine_revision='bone-age-2026-09-21')
    outcome=create_report(data,'1.2.3','fixture',tmp_path)
    reader=PdfReader(outcome['pdf_path'])
    text=' '.join(' '.join(p.extract_text().split()) for p in reader.pages)
    assert len(reader.pages) == 2
    for label in ('Synthetic Child','Z-score','50.0','Reference','Unsigned','Page 2 of 2'):
        assert label in text
    assert not list(tmp_path.glob('*.partial'))


def test_pdf_failure_preserves_previous_report(tmp_path,monkeypatch):
    from modules.ai_imaging.eagle_eye_engines import bone_age_report as reports
    from modules.ai_imaging.eagle_eye_brain import organized_report
    old=tmp_path/'bone_age_report.pdf'; old.write_bytes(b'existing-report')
    def failed(html,path,**kw):
        path.write_bytes(b'incomplete'); raise RuntimeError('Synthetic writer failure')
    monkeypatch.setattr(organized_report,'write_paged_pdf',failed)
    with pytest.raises(RuntimeError): reports.create_report(result(),'1.2.3','fixture',tmp_path)
    assert old.read_bytes() == b'existing-report'
    assert not list(tmp_path.glob('*.partial'))


def test_reception_jalali_calendar_is_explicit_and_dicom_remains_gregorian():
    from modules.ai_imaging.eagle_eye_remote.demographics import prepare_review
    context=dict(patient_id='fixture',study_date='20260321')
    def lookup(_):
        return {'data':{'receptionId':'fixture','patient':{'Name':'Synthetic','Gender':'F','BD':'14000101'}}}
    r=prepare_review(context,'M','1.2.3',lookup=lookup)
    assert r['birth_date'] == '2021-03-21'
    assert r['chronological_age_months'] == 60
    assert r['birth_calendar'] == 'Jalali'
    context['patient_birth_date']='14000101'
    assert prepare_review(context,'M','1.2.3',lookup=lambda _:None)['birth_date'] == ''
