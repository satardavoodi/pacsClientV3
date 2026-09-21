"""Independent same-study inputs preserve the designated primary measurement."""
import pytest
from modules.ai_imaging.eagle_eye_brain import multi_t1
from modules.ai_imaging.eagle_eye_brain.contracts import BrainError


def result(volume):
    return {'posterior_rows': [{'structure': 'hippocampus', 'volume_cm3': volume},
                               {'structure': 'total intracranial', 'volume_cm3': 1000}]}


def test_signed_difference_and_missing_measurements():
    rows = multi_t1.compare_volumes(result(4), result(3))
    assert rows[0]['difference_percent'] == -25
    assert rows[0]['primary_icv_percent'] == .4
    assert rows[0]['supplementary_icv_percent'] == .3
    assert multi_t1.compare_volumes(result(4), {'posterior_rows': []})[0]['difference_percent'] is None


def test_multi_t1_validates_before_processing_and_preserves_primary(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain import patient_context, study_workflow
    monkeypatch.setattr(patient_context, 'dicom_context', lambda path: dict(study_uid='s', series_uid=path, patient_id='test'))
    calls = []
    def run(path, *args, **kwargs):
        calls.append(path)
        r = result(4 if path == 'a' else 3)
        r['artifact_directory'] = str(tmp_path)
        return r
    monkeypatch.setattr(study_workflow, 'run_study_analysis', run)
    monkeypatch.setattr(multi_t1, 'write_comparison_pdf', lambda *args: None)
    with pytest.raises(BrainError):
        multi_t1.run_multi_t1('a', 's', 'a', root=tmp_path, supplementary=[dict(path='a', series_uid='a')])
    assert calls == []
    r = multi_t1.run_multi_t1('a', 's', 'a', root=tmp_path, supplementary=[dict(path='b', series_uid='b')])
    assert calls == ['a', 'b'] and r['posterior_rows'][0]['volume_cm3'] == 4
    assert (tmp_path / 't1-comparison-2.csv').is_file()
    assert r['t1_input_count'] == 2


def test_dicom_demographics_fill_visible_fields_without_starting_analysis():
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    app = QApplication.instance() or QApplication([])
    w = BrainVolumetryWidget()
    try:
        w._apply_demographics({'age_years': 66.5, 'sex': 'F'})
        assert w.age.value() == 66.5 and w.age.isReadOnly()
        assert w.sex.currentData() == 'female' and not w.sex.isEnabled()
        assert w._future is None and w.advanced.isHidden()
        w._apply_demographics({})
        assert w.age.value() == -1 and not w.age.isReadOnly() and w.sex.isEnabled()
    finally:
        w._executor.shutdown(wait=False)
        w.deleteLater(); app.processEvents()


def test_supplementary_failure_is_recorded_without_replacing_primary(tmp_path, monkeypatch):
    import json
    from modules.ai_imaging.eagle_eye_brain import patient_context, study_workflow
    monkeypatch.setattr(patient_context, 'dicom_context', lambda path: dict(study_uid='s', series_uid=path))
    def run(path, *args, **kwargs):
        if path == 'b':
            raise RuntimeError('Synthetic processing failure')
        r = result(4); r['artifact_directory'] = str(tmp_path)
        return r
    monkeypatch.setattr(study_workflow, 'run_study_analysis', run)
    with pytest.raises(BrainError, match='primary report'):
        multi_t1.run_multi_t1('a', 's', 'a', root=tmp_path, supplementary=[dict(path='b', series_uid='b')])
    assert json.loads((tmp_path / 't1-consistency.json').read_text())['status'] == 'incomplete'
    assert not (tmp_path / 't1-consistency.pdf').exists()
