"""Synthetic demographic fallback and identity guards; no live database."""
import pytest
from modules.ai_imaging.eagle_eye_engines import service
from tests.code.ai_imaging.test_eagle_eye_local_engines import source


def test_physician_confirmation_can_supply_missing_sex_without_editing_source(tmp_path):
    p = source(tmp_path, sex='O')
    import pydicom
    d = pydicom.dcmread(p)
    d.PatientID = 'fixture'
    d.save_as(p)
    before = service.digest(p)
    evidence = dict(source='physician', patient_id='fixture', study_uid='1.2.3')
    records, sex = service.validate_sources([p], '1.2.3', 'bone-age', 'F', sex_provenance=evidence)
    assert sex == 'F' and records and service.digest(p) == before


def test_confirmation_cannot_override_valid_dicom_or_another_identity(tmp_path):
    p = source(tmp_path, sex='M')
    evidence = dict(source='physician', patient_id='fixture', study_uid='1.2.3')
    with pytest.raises(ValueError):
        service.validate_sources([p], '1.2.3', 'bone-age', 'F', sex_provenance=evidence)


def test_reception_requires_exact_admission_and_unambiguous_gender():
    from modules.ai_imaging.eagle_eye_remote.demographics import reception_sex
    payload = {'data': [{'receptionId': 'fixture', 'patient': {'Gender': 'F'}}]}
    assert reception_sex(payload, 'fixture') == 'F'
    assert reception_sex(payload, 'different') is None
    payload['data'].append({'receptionId': 'fixture', 'patient': {'Gender': 'M'}})
    assert reception_sex(payload, 'fixture') is None


def test_reception_lookup_is_skipped_for_valid_dicom_and_missing_identity():
    from modules.ai_imaging.eagle_eye_remote.demographics import resolve
    calls = []
    lookup = lambda identity: calls.append(identity) or 'F'
    assert resolve('M', 'fixture', '1.2.3', lookup=lookup) == ('M', None)
    assert resolve('O', '', '1.2.3', lookup=lookup) == (None, None)
    assert not calls
    assert resolve('O', 'fixture', '1.2.3', lookup=lookup) == (
        'F', dict(source='reception', patient_id='fixture', study_uid='1.2.3'))


def test_numeric_unknown_is_not_guessed():
    from modules.ai_imaging.eagle_eye_remote.demographics import normalize
    assert normalize(0) is None and normalize('1') is None
    assert normalize(' female ') == 'F'


def test_wrong_patient_confirmation_and_unverified_override_are_rejected(tmp_path):
    p = source(tmp_path, sex='O')
    with pytest.raises(ValueError):
        service.validate_sources([p], '1.2.3', 'bone-age', 'F')
    with pytest.raises(ValueError, match='another patient'):
        service.validate_sources([p], '1.2.3', 'bone-age', 'F', sex_provenance={
            'source': 'physician', 'patient_id': 'other', 'study_uid': '1.2.3'})


def test_reception_override_is_verified_again_by_server(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import demographics
    import pydicom
    p = source(tmp_path, sex='O')
    d = pydicom.dcmread(p)
    d.PatientID = 'fixture'
    d.save_as(p)
    evidence = dict(source='reception', patient_id='fixture', study_uid='1.2.3')
    monkeypatch.setattr(demographics, 'lookup_reception', lambda _: 'M')
    with pytest.raises(ValueError, match='verify the Reception'):
        service.validate_sources([p], '1.2.3', 'bone-age', 'F', sex_provenance=evidence)
    monkeypatch.setattr(demographics, 'lookup_reception', lambda _: 'F')
    assert service.validate_sources([p], '1.2.3', 'bone-age', 'F', sex_provenance=evidence)[1] == 'F'


@pytest.mark.parametrize('answer,accepted,changed,expected', [
    ('Female', True, False, 'F'), ('Select patient sex', True, False, None),
    ('Male', False, False, None), ('Male', True, True, None)])
def test_gui_confirmation_is_explicit_and_case_bound(monkeypatch, answer, accepted, changed, expected):
    from PySide6.QtWidgets import QWidget, QInputDialog, QApplication
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote.demographics_ui import SexConfirmation
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    answers = []
    identity = ['1.2.3', 'fixture']
    worker = SimpleNamespace(study_uid='1.2.3', metadata_context={'patient_id': 'fixture'},
                             canceled=False, confirm_sex=answers.append)
    def prompt(*args):
        assert args[-2] == 0 and args[-1] is False
        if changed:
            identity[0] = '1.2.9'
        return answer, accepted
    monkeypatch.setattr(QInputDialog, 'getItem', prompt)
    SexConfirmation(parent, worker, lambda: tuple(identity)).request()
    assert answers == [expected]
    parent.close()


@pytest.mark.parametrize('confirmed', ['F', None])
@pytest.mark.parametrize('initial_sex', ['O', 'M'])
def test_worker_requests_confirmation_before_submission(tmp_path, monkeypatch, confirmed, initial_sex):
    # Load the actual worker class without importing viewer controllers/live config.
    import ast
    from pathlib import Path
    from PySide6.QtCore import QThread, Signal, Qt
    from modules.ai_imaging.eagle_eye_remote import demographics
    from modules.ai_imaging.eagle_eye_remote import routing
    tree = ast.parse(Path('modules/viewer/interactor_styles/ai_chat_interactorstyle.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BoneAgeWorker')
    namespace = {'QThread': QThread, 'Signal': Signal, 'Path': Path, 'ATTACHMENT_PATH': tmp_path}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), '<actual-bone-age-worker>', 'exec'), namespace)
    worker = namespace['BoneAgeWorker']('1.2.3', initial_sex, '', metadata_context={'patient_id': 'fixture'})
    monkeypatch.setattr(demographics, 'resolve', lambda *a: (None, None))
    monkeypatch.setattr(demographics, 'prepare_review', lambda *a: dict(
        study_uid='1.2.3', patient_id='fixture', name='Synthetic Child', sex='',
        chronological_age_months=None))
    calls, errors = [], []
    monkeypatch.setattr(routing, 'study', lambda *a, **kw: calls.append(kw) or {'sex': kw['sex']})
    monkeypatch.setattr(worker, '_save_result_json', lambda data: tmp_path/'synthetic.json')
    worker.sex_required.connect(lambda: worker.confirm_demographics(dict(
        worker.demographic_draft, sex=confirmed, chronological_age_months=120) if confirmed else None), Qt.DirectConnection)
    worker.error.connect(errors.append, Qt.DirectConnection)
    worker.run()
    if confirmed:
        assert len(calls) == 1 and not errors
        assert calls[0]['sex_provenance'] == {'source': 'physician-review', 'study_uid': '1.2.3', 'patient_id': 'fixture'}
    else:
        assert not calls and len(errors) == 1 and 'cancelled' in errors[0]


@pytest.mark.parametrize('capability', [None, 1])
def test_client_negotiates_confirmation_before_submitting(tmp_path, monkeypatch, capability):
    from modules.ai_imaging.eagle_eye_remote import routing
    from PacsClient.utils import data_paths
    from types import SimpleNamespace
    calls = []
    client = SimpleNamespace(json=lambda _: {'bone_age_demographic_confirmation': capability},
                             analyze=lambda *a, **kw: calls.append((a, kw)) or {})
    monkeypatch.setattr(routing, 'Client', lambda: client)
    monkeypatch.setattr(data_paths, 'ATTACHMENTS_DIR', tmp_path)
    evidence = dict(source='physician', study_uid='1.2.3', patient_id='fixture')
    if capability is None:
        with pytest.raises(ValueError, match='Update the Eagle Eye server'):
            routing.study('bone-age', '1.2.3', sex='female', sex_provenance=evidence)
        assert not calls
    else:
        routing.study('bone-age', '1.2.3', sex='female', sex_provenance=evidence)
        assert calls[0][0][3] == {'sex': 'F', 'sex_provenance': evidence}


def test_contract_rejects_stale_or_extra_provenance():
    from modules.ai_imaging.eagle_eye_remote.contracts import validate
    request = dict(protocol=1, request_id='a'*32, module='bone-age', study_uid='1.2.3', series={},
                   parameters={'sex': 'F', 'sex_provenance': {
                       'source': 'physician', 'study_uid': '1.2.9', 'patient_id': 'fixture'}})
    with pytest.raises(ValueError, match='does not match'):
        validate(request)
    request['parameters']['sex_provenance']['study_uid'] = '1.2.3'
    assert validate(request) is request
    request['parameters']['sex_provenance']['untrusted'] = 'value'
    with pytest.raises(ValueError):
        validate(request)
