"""Synthetic guards: menu, server contract, geometry and honest signal reporting."""
import threading
import uuid

import numpy as np
import pytest

from modules.ai_imaging.eagle_eye_function_catalog import function_options_for_modality
from modules.ai_imaging.eagle_eye_remote.contracts import validate
from modules.ai_imaging.lumbar_marrow import measure, validate_parameters


def request(**params):
    return dict(protocol=1, request_id=uuid.uuid4().hex, module='lumbar-marrow',
                study_uid='1.2.3', series={'primary': {'series_uid': '1.2.4', 'expected_count': 10}},
                parameters=dict(t1_confirmed=True, **params))


def test_marrow_menu_available_for_lumbar_only():
    assert 'lumbar_bone_marrow' in {x.key for x in function_options_for_modality('MR', 'lumbar_mri')}
    for modality, mode in [('MR', 'brain_mri'), ('DX', None), ('MG', None)]:
        assert 'lumbar_bone_marrow' not in {x.key for x in function_options_for_modality(modality, mode)}


def test_remote_marrow_contract_requires_primary_and_confirmation():
    assert validate(request())['module'] == 'lumbar-marrow'
    for change in ({'parameters': {}}, {'series': {}}, {'parameters': {'t1_confirmed': 1}},
                   {'parameters': {'t1_confirmed': True, 'red_marrow_percent': 50}}):
        body = request()
        body.update(change)
        with pytest.raises(ValueError):
            validate(body)


@pytest.mark.parametrize('clinical', [{'ferritin_ng_ml': float('nan')}, {'dxa_z_score': True},
                                      {'transferrin_saturation_percent': 101}, {'emh': 'automatically detected'},
                                      {'patient_name': 'synthetic'}])
def test_clinical_context_bounded(clinical):
    with pytest.raises(ValueError):
        validate_parameters(dict(t1_confirmed=True, clinical=clinical))


def sample(tmp_path, affine=None):
    labels = np.zeros((16, 16, 16), dtype=np.uint8)
    labels[2:14, 2:14, 2:14] = 1
    array = np.full(labels.shape, 125, dtype=np.float32)
    array[labels == 0] = 900
    result = measure(array, labels, np.eye(4) if affine is None else affine,
                     [{'label': 1, 'name': 'vertebrae_L1'}], tmp_path,
                     dict(t1_confirmed=True, clinical={'ferritin_ng_ml': 500}))
    return result


def test_signal_sampling_excludes_background_and_exports_draft(tmp_path):
    result = sample(tmp_path)
    row = result['marrow_measurements'][0]
    assert row['mean_si'] == row['median_si'] == 125
    assert row['sample_voxels'] == 8 ** 3
    assert row['sample_volume_mm3'] == 512
    assert result['red_marrow_fraction'] is result['fat_fraction'] is result['iron_concentration'] is None
    assert result['report_status'] == 'unreviewed_research_draft'
    assert result['clinical_context']['ferritin_ng_ml'] == 500
    assert 'posterior elements' in (tmp_path / 'report.html').read_text()
    for name in ['report.html', 'preview.png', 'marrow.csv', 'marrow-roi.npy']:
        assert (tmp_path / name).is_file()


def test_erosion_respects_kji_spacing_and_oblique_orientation(tmp_path):
    angle = .3
    affine = np.eye(4)
    affine[:3, :3] = np.array([[np.cos(angle), -np.sin(angle), 0],
                             [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]) @ np.diag([1, 1, 4])
    row = sample(tmp_path, affine)['marrow_measurements'][0]
    assert row['sample_voxels'] == 12 * 8 * 8
    assert row['sample_volume_mm3'] == pytest.approx(row['sample_voxels'] * 4)


def test_no_lumbar_labels_does_not_create_report(tmp_path):
    with pytest.raises(ValueError, match='No lumbar'):
        measure(np.zeros((5, 5, 5)), np.zeros((5, 5, 5)), np.eye(4), [], tmp_path, {'t1_confirmed': True})
    assert not (tmp_path / 'report.html').exists()


def test_client_requires_server_capability_before_submission(monkeypatch, tmp_path):
    from modules.ai_imaging import lumbar_marrow_widget as widget
    from modules.ai_imaging.eagle_eye_remote.client import Client
    monkeypatch.setattr(Client, '__init__', lambda self: None)
    monkeypatch.setattr(Client, 'json', lambda *a: {'modules': ['lumbar']})
    monkeypatch.setattr(Client, 'analyze', lambda *a, **k: pytest.fail('Must not submit to an old server'))
    with pytest.raises(ValueError, match='No job was submitted'):
        widget.analyze_series({'path': str(tmp_path), 'series_uid': '1.2.4'}, '1.2.3',
                              {'t1_confirmed': True}, threading.Event())


def test_client_rejects_cross_study_source_before_submission(monkeypatch, tmp_path):
    from modules.ai_imaging import lumbar_marrow_widget as widget
    from modules.ai_imaging.eagle_eye_remote import routing
    from modules.ai_imaging.eagle_eye_remote.client import Client
    monkeypatch.setattr(Client, '__init__', lambda self: None)
    monkeypatch.setattr(Client, 'json', lambda *a: {'modules': ['lumbar-marrow']})
    monkeypatch.setattr(routing, 'reference', lambda *a: ('1.2.9', {'series_uid': '1.2.4'}))
    monkeypatch.setattr(Client, 'analyze', lambda *a, **k: pytest.fail('Identity mismatch must not submit'))
    with pytest.raises(ValueError, match='identity changed'):
        widget.analyze_series({'path': str(tmp_path), 'series_uid': '1.2.4'}, '1.2.3',
                              {'t1_confirmed': True}, threading.Event())


def test_draft_artifacts_roundtrip_without_server_paths(tmp_path):
    import json
    import zipfile
    from modules.ai_imaging.eagle_eye_remote.artifacts import publish
    job = tmp_path / uuid.uuid4().hex
    directory = job / 'work'
    directory.mkdir(parents=True)
    result = sample(directory)
    result['artifact_directory'] = str(directory)
    body = request()
    records = [dict(study_uid='1.2.3', series_uid='1.2.4', sop_uid='1.2.5', sha256='0' * 64, path='synthetic.dcm')]
    publish(job, body, records, result)
    with zipfile.ZipFile(job / 'artifacts.zip') as archive:
        names = archive.namelist()
        assert {'report.html', 'preview.png', 'marrow.csv', 'marrow-roi.npy'}.issubset(names)
        packet = json.loads(archive.read('envelope.json'))['result']
    assert str(directory) not in json.dumps(packet)


def test_form_opens_without_inference_and_requires_confirmation(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.lumbar_marrow_widget import LumbarMarrowWidget
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(LumbarMarrowWidget, 'load_series', lambda self: None)
    widget = LumbarMarrowWidget(study_uid='1.2.3')
    try:
        widget.series.addItem('Synthetic lumbar T1', dict(path='unused', series_uid='1.2.4'))
        assert widget._future is None
        widget.start()
        assert widget._future is None
        assert 'confirm' in widget.status.text()
        assert app is not None
    finally:
        widget.teardown()
        widget.close()


def test_existing_resource_configuration_inherits_lumbar_budget_without_mutation():
    from modules.ai_imaging.eagle_eye_remote.contracts import MODULES
    from modules.ai_imaging.eagle_eye_remote.scheduling import Resources
    old = {name: {'jobs': 1} for name in MODULES if name != 'lumbar-marrow'}
    resources = Resources({'capacity': {'jobs': 1}, 'modules': old})
    assert resources.profiles['lumbar-marrow'] == resources.profiles['lumbar']
    assert 'lumbar-marrow' not in old
    old.pop('brain')
    with pytest.raises(ValueError):
        Resources({'capacity': {'jobs': 1}, 'modules': old})


@pytest.mark.parametrize('description', ['T1 sagittal', 'T2 sagittal', 'T1 Dixon', 'T1 postcontrast', 'STIR'])
def test_sequence_header_gate_rejects_known_incompatible_acquisitions(tmp_path, description):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage
    from modules.ai_imaging.lumbar_marrow import validate_t1_headers
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = MRImageStorage
    meta.MediaStorageSOPInstanceUID = '1.2.5'
    path = tmp_path / 'synthetic.dcm'
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.SeriesDescription = description
    ds.is_little_endian, ds.is_implicit_VR = True, False
    ds.save_as(path, write_like_original=False)
    if description == 'T1 sagittal':
        validate_t1_headers([path])
    else:
        with pytest.raises(ValueError, match='requires native'):
            validate_t1_headers([path])


def test_server_adapter_reuses_lumbar_model_on_rescaled_dicom(monkeypatch, tmp_path):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage
    from modules.ai_imaging.eagle_eye_remote.adapters import execute
    from modules.ai_imaging.offline_lumbar import service
    from modules.ai_imaging.eagle_eye import assets
    folder = tmp_path / 'source'
    folder.mkdir()
    records = []
    for index in range(6):
        path = folder / f'{index}.dcm'
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = MRImageStorage
        meta.MediaStorageSOPInstanceUID = f'1.2.5.{index + 1}'
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = MRImageStorage, meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID = '1.2.3', '1.2.4'
        ds.Modality, ds.SeriesDescription = 'MR', 'Lumbar T1 sagittal'
        ds.ImageOrientationPatient = [0, 1, 0, 0, 0, -1]
        ds.ImagePositionPatient = [-index * 2, 0, 24]
        ds.PixelSpacing, ds.SliceThickness = [1, 1], 2
        ds.Rows, ds.Columns = 24, 24
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 'MONOCHROME2'
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 0
        ds.RescaleSlope, ds.RescaleIntercept = 2, 10
        ds.PixelData = np.full((24, 24), 50, dtype=np.uint16).tobytes()
        ds.is_little_endian, ds.is_implicit_VR = True, False
        ds.save_as(path, write_like_original=False)
        records.append(dict(path=str(path), roles=['primary']))
    model = tmp_path / 'bundle'
    model.mkdir()
    (model / 'manifest.json').write_text('{}')
    monkeypatch.setenv('AIPACS_OFFLINE_LUMBAR_ROOT', str(model))
    monkeypatch.setattr(assets, 'installed_feature_roots', lambda name: [model])
    def snapshot(bundle, output, array, affine, *, cancel):
        assert bundle == model
        assert array.shape == (6, 24, 24)
        assert np.all(array == 110)
        labels = np.zeros(array.shape, dtype=np.uint8)
        labels[1:5, 4:20, 4:20] = 1
        return dict(artifact_directory=str(output), segments=[{'name': 'vertebrae_L1', 'label': 1}]), labels
    monkeypatch.setattr(service, 'run_snapshot', snapshot)
    result = execute(request(), records, tmp_path / 'work')
    assert result['task'] == 'lumbar_marrow_t1_exploratory'
    assert result['marrow_measurements'][0]['mean_si'] == 110
    assert result['marrow_measurements'][0]['sample_voxels'] == 288
