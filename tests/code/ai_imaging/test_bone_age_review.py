"""Synthetic physician review, age precision and source priority guards."""
import pytest
from modules.ai_imaging.eagle_eye_remote.demographics import prepare_review, validate_review


def test_reception_priority_and_age_at_imaging():
    context = dict(patient_id='fixture', patient_name='DICOM Child', patient_birth_date='20150101', study_date='20260930')
    payload = {'data': {'receptionId': 'fixture', 'patient': {'Name': 'Reception Child', 'Gender': 'F', 'BD': '2016-10-01'}}}
    draft = prepare_review(context, 'M', '1.2.3', lookup=lambda _: payload)
    assert draft['name'] == 'Reception Child' and draft['sex'] == 'F'
    assert draft['chronological_age_months'] == 119
    assert draft['sources']['birth_date'] == 'reception'


def test_ambiguous_reception_and_unknown_calendar_do_not_supply_age():
    context = dict(patient_id='fixture', study_date='20261004')
    payload = {'data': [{'receptionId': 'other', 'patient': {'Name': 'Other', 'BD': '20100101'}}]}
    draft = prepare_review(context, '', '1.2.3', lookup=lambda _: payload)
    assert draft['name'] == '' and draft['sex'] == '' and draft['chronological_age_months'] is None
    context['patient_birth_date'] = '1395/01/01'
    assert prepare_review(context, '', '1.2.3', lookup=lambda _: None)['chronological_age_months'] is None


def test_form_missing_fields_block_confirmation_and_manual_entry_succeeds():
    from PySide6.QtWidgets import QApplication, QDialog
    from modules.ai_imaging.eagle_eye_remote.demographics_ui import DemographicReviewDialog
    app = QApplication.instance() or QApplication([])
    draft = prepare_review({'patient_id': 'fixture'}, '', '1.2.3', lookup=lambda _: None)
    dialog = DemographicReviewDialog(None, draft)
    assert dialog.name.text() == dialog.years.text() == dialog.months.text() == ''
    dialog.confirm()
    assert dialog.confirmed is None
    dialog.name.setText('Synthetic Child')
    dialog.sex.setCurrentIndex(2)
    dialog.years.setText('10')
    dialog.months.setText('3')
    dialog.confirm()
    assert dialog.result() == QDialog.Accepted
    assert dialog.confirmed['chronological_age_months'] == 123
    assert dialog.confirmed['physician_confirmed'] is True
    dialog.close()


def test_review_cannot_move_to_another_study():
    with pytest.raises(ValueError):
        validate_review(dict(name='Synthetic', sex='M', chronological_age_months=100,
                            study_uid='1.2.3', patient_id='fixture'), '1.2.4', 'fixture')


def test_case_switch_discards_completed_popup(monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget, QDialog
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote import demographics_ui as ui
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    identity = ['1.2.3', 'fixture']
    answers = []
    draft = dict(study_uid='1.2.3', patient_id='fixture', name='Synthetic Child', sex='F', chronological_age_months=120)
    worker = SimpleNamespace(study_uid='1.2.3', metadata_context={'patient_id': 'fixture'},
                             demographic_draft=draft, canceled=False,
                             confirm_sex=answers.append, confirm_demographics=answers.append)
    def complete(dialog):
        dialog.confirmed = dict(draft, physician_confirmed=True)
        identity[0] = '1.2.4'
        return QDialog.Accepted
    monkeypatch.setattr(ui.DemographicReviewDialog, 'exec', complete)
    ui.SexConfirmation(parent, worker, lambda: tuple(identity)).request()
    assert answers == [None]
    parent.close()


def test_reviewed_sex_overrides_dicom_only_for_matching_patient(tmp_path):
    import pydicom
    from tests.code.ai_imaging.test_eagle_eye_local_engines import source
    from modules.ai_imaging.eagle_eye_engines import service
    path = source(tmp_path, sex='M')
    ds = pydicom.dcmread(path)
    ds.PatientID = 'fixture'
    ds.save_as(path)
    before = service.digest(path)
    evidence = dict(source='physician-review', study_uid='1.2.3', patient_id='fixture')
    assert service.validate_sources([path], '1.2.3', 'bone-age', 'F', sex_provenance=evidence)[1] == 'F'
    assert service.digest(path) == before
    evidence['patient_id'] = 'other'
    with pytest.raises(ValueError, match='another patient'):
        service.validate_sources([path], '1.2.3', 'bone-age', 'F', sex_provenance=evidence)
