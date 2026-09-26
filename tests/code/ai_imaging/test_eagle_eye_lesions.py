"""Synthetic lesion geometry, burden and study-bound UI guards."""
import threading
import numpy as np
import pytest
import SimpleITK as sitk

from modules.ai_imaging.eagle_eye_brain import lesions
from modules.ai_imaging.eagle_eye_brain.contracts import BrainError


def pair():
    flair = sitk.GetImageFromArray(np.arange(125, dtype=np.float32).reshape(5, 5, 5))
    flair.SetSpacing((0.5, 1, 2))
    array = np.zeros((5, 5, 5), dtype=np.uint8)
    array[0, 0, 0] = array[1, 1, 1] = array[4, 4, 4] = 1
    mask = sitk.GetImageFromArray(array)
    mask.CopyInformation(flair)
    return flair, mask


def test_native_voxel_burden_and_diagonal_connectivity():
    result = lesions.measure_mask(*pair())
    assert result['candidate_count'] == 2
    assert result['total_volume_cm3'] == .003
    assert result['components_mm3'] == [2, 1]


@pytest.mark.parametrize('change', ['origin', 'spacing', 'direction', 'nonbinary'])
def test_invalid_masks_never_publish_volume(change):
    flair, mask = pair()
    if change == 'origin':
        mask.SetOrigin((1, 0, 0))
    elif change == 'spacing':
        mask.SetSpacing((1, 1, 1))
    elif change == 'direction':
        mask.SetDirection((-1, 0, 0, 0, 1, 0, 0, 0, 1))
    else:
        mask = mask * 2
    with pytest.raises(BrainError):
        lesions.measure_mask(flair, mask)


def test_wrong_study_rejected_before_model_access(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain import patient_context
    monkeypatch.setattr(patient_context, 'dicom_context', lambda path: {'study_uid': 'another', 'series_uid': path})
    monkeypatch.setattr(lesions, 'lesion_bundle', lambda: pytest.fail('Model access before identity check'))
    with pytest.raises(BrainError, match='examination'):
        lesions.run_lesions('t1', 'flair', study_uid='wanted', t1_uid='t1', flair_uid='flair', root=tmp_path)


def test_lesion_work_respects_existing_brain_analysis_lock(tmp_path):
    from modules.ai_imaging.eagle_eye_brain.service import _ANALYSIS_LOCK
    with _ANALYSIS_LOCK:
        with pytest.raises(BrainError, match='Another brain analysis'):
            lesions.run_lesions('missing', 'missing', study_uid='study', t1_uid='1', flair_uid='2', root=tmp_path)


def test_lesion_widget_requires_two_study_inputs():
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.lesion_widget import BrainLesionWidget
    app = QApplication.instance() or QApplication([])
    widget = BrainLesionWidget(study_uid='synthetic-study')
    widget.confirm.setChecked(True)
    widget._selected_series = {'path': 't1', 'series_uid': '1'}
    widget._start()
    assert widget._future is None
    assert 'T1 and 3D FLAIR' in widget.status.text()
    assert widget.advanced.isHidden()
    widget.deleteLater()
    app.processEvents()


def test_registration_adapter_quotes_paths_without_changing_boolean_options():
    from types import SimpleNamespace
    from tools.eagle_eye.lesion_runner import adapt_registration
    calls = []
    def operation(path, reverse=False):
        calls.append((f'{path}', reverse))
    module = SimpleNamespace(_greedy=lambda args: None, **{key: operation for key in
                              ('mni_registration', 'rigid_reg', 'apply_warp_label', 'apply_warp_interp')})
    adapt_registration(module)
    module.apply_warp_label('C:/a folder/image.nii.gz', reverse=True)
    assert calls == [('"C:/a folder/image.nii.gz"', True)]


def test_registration_adapter_pins_seed_and_registration_thread_budget():
    from types import SimpleNamespace
    from tools.eagle_eye.lesion_runner import adapt_registration
    calls = []
    module = SimpleNamespace(_greedy=calls.append)
    def operation(path, reverse=False, n_threads=2):
        return module._greedy(f'-d 3 -i {path} -threads {n_threads}')
    for name in ('mni_registration', 'rigid_reg', 'apply_warp_label', 'apply_warp_interp'):
        setattr(module, name, operation)
    adapt_registration(module)
    module.mni_registration('C:/synthetic folder/t1.nii.gz')
    module.rigid_reg('C:/synthetic folder/flair.nii.gz', n_threads=8)
    assert len(calls) == 2
    for command in calls:
        assert command.startswith('-seed 1729 ')
        assert '-threads 1' in command
        assert '"C:/synthetic folder/' in command


def test_lesion_html_previews_survive_transfer_without_server_files(tmp_path, monkeypatch):
    import base64
    import io
    import re
    from PIL import Image
    from modules.ai_imaging.eagle_eye_brain import lesion_report, organized_report
    from modules.ai_imaging.eagle_eye_brain.lesion_indication import clinical_context

    flair, mask = pair()
    result = dict(patient_context={'patient_name': 'Synthetic', 'patient_id': 'fixture',
                                  'study_date': '20000101'}, age_years=40, sex='female',
                  metrics=lesions.measure_mask(flair, mask),
                  clinical_context=clinical_context('other', '', None))
    monkeypatch.setattr(organized_report, 'write_paged_pdf', lambda *args, **kwargs: None)
    lesion_report.write_lesion_report(result, flair, mask, tmp_path)
    html = (tmp_path / 'report.html').read_text(encoding='utf-8')
    previews = list(tmp_path.glob('lesion-preview-*.png'))
    expected = [path.read_bytes() for path in previews]
    for path in previews:
        path.unlink()
    sources = re.findall(r'<img[^>]+src="([^"]+)"', html)
    assert sources and len(sources) == len(expected)
    for source in sources:
        assert source.startswith('data:image/png;base64,')
        data = base64.b64decode(source.split(',', 1)[1], validate=True)
        assert data in expected
        Image.open(io.BytesIO(data)).verify()
    assert 'file:///' not in html and str(tmp_path) not in html


@pytest.mark.parametrize('cancel_during_report', [False, True])
@pytest.mark.parametrize('primary_disease', ['other', 'ms', 'svd'])
def test_pipeline_publishes_only_completed_native_mask_report(tmp_path, monkeypatch, cancel_during_report, primary_disease):
    from modules.ai_imaging.eagle_eye_brain import images, patient_context, runtime, lesion_report
    cancel = threading.Event()
    context = {'study_uid': 'study', 'patient_id': 'synthetic', 'patient_name': 'Synthetic example',
               'sex': 'F', 'age_years': 40}
    monkeypatch.setattr(patient_context, 'dicom_context', lambda path: dict(context, series_uid=path))
    monkeypatch.setattr(lesions, 'lesion_bundle', lambda: tmp_path / 'model')
    monkeypatch.setattr(lesions, 'validate_lesion_bundle', lambda path: {'version': lesions.LST_VERSION})
    (tmp_path / 'model').mkdir()
    (tmp_path / 'model/manifest.json').write_text('synthetic manifest')
    flair, mask = pair()
    monkeypatch.setattr(images, 'read_volume', lambda *args, **kwargs: flair)
    def inference(command, directory, token, **kwargs):
        (directory / 'output').mkdir()
        sitk.WriteImage(mask, str(directory / 'output/space-flair_seg-lst.nii.gz'))
    monkeypatch.setattr(runtime, 'run_process', inference)
    def report(result, flair, mask, directory):
        (directory / 'report.pdf').write_bytes(b'synthetic report fixture')
        if cancel_during_report:
            cancel.set()
    monkeypatch.setattr(lesion_report, 'write_lesion_report', report)
    from modules.ai_imaging.eagle_eye_brain import ms_assessment, svd_assessment
    def topography(result, directory, **kwargs):
        assert kwargs['t1_source'] == 't1'
        return {'conclusion': 'Synthetic topographic review', 'physician_confirmation_required': True}
    monkeypatch.setattr(ms_assessment, 'enrich_ms', topography)
    def spatial(result, directory, **kwargs):
        assert result['clinical_context']['primary_disease'] == 'svd'
        assert kwargs['t1_source'] == 't1'
        return {'status': 'Synthetic spatial review'}
    monkeypatch.setattr(svd_assessment, 'enrich_svd', spatial)
    call = lambda: lesions.run_lesions('t1', 'flair', study_uid='study', t1_uid='t1', flair_uid='flair',
                                      root=tmp_path, cancel=cancel, primary_disease=primary_disease)
    if cancel_during_report:
        with pytest.raises(BrainError, match='cancelled'):
            call()
        assert list(tmp_path.rglob('FAILED'))
        assert not list(tmp_path.rglob('result.json'))
    else:
        result = call()
        assert result['analysis_type'] == 'brain_lesions' and result['pdf_available']
        assert result['metrics']['total_volume_mm3'] == 3
        assert result['age_years'] == 40 and result['sex'] == 'female'
        assert 'normative' not in result
        assert result['flair_series_uid'] == 'flair' and len(result['model_manifest_sha256']) == 64
        assert set(result['input_sha256']) == {'t1', 'flair'}
        assert ('ms_topography' in result) == (primary_disease == 'ms')
        assert result['lesion_topography']['physician_confirmation_required']
        assert ('svd_spatial' in result) == (primary_disease == 'svd')
