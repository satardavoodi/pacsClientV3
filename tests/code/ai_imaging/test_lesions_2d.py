"""Synthetic guards for the separate native-slice lesion pathway."""
import numpy as np
import pytest
import SimpleITK as sitk


def test_publish_2d_artifacts_supports_long_patient_paths(tmp_path):
    from modules.ai_imaging.eagle_eye_brain.lesions_2d import publish_artifacts, filesystem_path
    source = tmp_path / 'short'
    source.mkdir()
    (source / 'process-diagnostics.jsonl').write_text('synthetic')
    destination = tmp_path / ('a' * 90) / ('b' * 90) / ('c' * 90)
    publish_artifacts(source, destination)
    assert (filesystem_path(destination) / 'process-diagnostics.jsonl').read_text() == 'synthetic'


def test_remote_2d_packet_retains_mask_and_pdf_with_long_patient_paths(tmp_path, monkeypatch):
    import json
    import zipfile
    import os
    from pathlib import Path
    from modules.ai_imaging.eagle_eye_brain.lesions_2d import filesystem_path
    from modules.ai_imaging.eagle_eye_remote.artifacts import publish
    directory = tmp_path / ('a' * 90) / ('b' * 90) / ('c' * 90)
    target = filesystem_path(directory)
    target.mkdir(parents=True)
    for name in ('report.pdf', 'labels.nii.gz', 'flair.nii.gz', 'labels-raw.nii.gz', 'labels-band-review.nii.gz'):
        (target / name).write_bytes(b'synthetic')
    request = dict(protocol=1, request_id='0' * 32, module='brain-lesions', study_uid='1.2.3')
    result = dict(analysis_type='brain_lesions', acquisition_mode='2d',
                  artifact_directory=str(directory), mask_path=str(directory / 'labels.nii.gz'),
                  raw_mask_path=str(directory / 'labels-raw.nii.gz'), band_mask_path=str(directory / 'labels-band-review.nii.gz'))
    original_is_file = Path.is_file
    if os.name == 'nt':
        # The service host can lack the workstation's long-path manifest/policy.
        monkeypatch.setattr(Path, 'is_file', lambda p: False if len(str(p)) >= 260
                            and not str(p).startswith('\\\\?\\') else original_is_file(p))
    publish(tmp_path, request, [], result)
    with zipfile.ZipFile(tmp_path / 'artifacts.zip') as archive:
        packet = json.loads(archive.read('envelope.json'))
        assert set(packet['files']) == {'report.pdf', 'labels.nii.gz', 'flair.nii.gz', 'labels-raw.nii.gz', 'labels-band-review.nii.gz'}
        assert packet['result']['mask_path'] == {'artifact': 'labels.nii.gz'}
        assert packet['result']['raw_mask_path'] == {'artifact': 'labels-raw.nii.gz'}
        assert packet['result']['band_mask_path'] == {'artifact': 'labels-band-review.nii.gz'}


def images():
    image = sitk.GetImageFromArray(np.arange(125, dtype=np.float32).reshape(5, 5, 5))
    image.SetSpacing((.5, .5, 6))
    a = np.zeros((5, 5, 5), dtype=np.uint8)
    a[1, 2, 2] = a[2, 2, 2] = 1
    mask = sitk.GetImageFromArray(a)
    mask.CopyInformation(image)
    return image, mask


def test_slice_volume_excludes_unobserved_gap():
    from modules.ai_imaging.eagle_eye_brain.lesions_2d import measure_slices
    m = measure_slices(*images(), thickness_mm=5)
    assert m['total_volume_mm3'] == 2.5
    assert m['grid_estimate_volume_mm3'] == 3
    assert m['slice_candidate_count'] == 2
    assert m['candidate_count'] == 1
    assert m['volume_basis'] == 'sampled_slabs'


@pytest.mark.parametrize('thickness', [0, -1, 7, float('nan'), None])
def test_no_invented_or_overlapping_slice_thickness(thickness):
    from modules.ai_imaging.eagle_eye_brain.lesions_2d import measure_slices
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
    with pytest.raises(BrainError):
        measure_slices(*images(), thickness_mm=thickness)


def test_same_dialog_exposes_two_paths_without_enabling_2d_longitudinal():
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.lesion_widget import BrainLesionWidget
    app = QApplication.instance() or QApplication([])
    w = BrainLesionWidget(study_uid='synthetic')
    assert w.acquisition_mode.currentData() == '3d'
    w.primary_disease.setCurrentIndex(w.primary_disease.findData('ms'))
    w.acquisition_mode.setCurrentIndex(w.acquisition_mode.findData('2d'))
    assert not w.ms_comparison.isEnabled()
    assert '2D' in w.input_summary.text()
    w.deleteLater()
    app.processEvents()


def dicom_stack(tmp_path, description='t2_tirm_tra_dark-fluid_320', ti=2500, irregular=False):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    for i in range(4):
        sop = generate_uid()
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID = MRImageStorage, sop
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(str(tmp_path / f'{i}.dcm'), {}, file_meta=meta, preamble=b'\0' * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = MRImageStorage, sop
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = study, series, frame
        ds.PatientName, ds.PatientID = 'Synthetic', 'SYNTHETIC'
        ds.Modality, ds.MRAcquisitionType, ds.SeriesDescription = 'MR', '2D', description
        ds.InversionTime = ti
        ds.Rows, ds.Columns = 5, 5
        ds.ImagePositionPatient = [0, 0, i * 6 + (1 if irregular and i == 3 else 0)]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.PixelSpacing, ds.SliceThickness = [.5, .5], 5
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 'MONOCHROME2'
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 0
        ds.PixelData = (np.arange(25, dtype=np.uint16) + i).tobytes()
        ds.is_little_endian, ds.is_implicit_VR = True, False
        ds.save_as(ds.filename, write_like_original=False)


def test_2d_dark_fluid_preserves_real_grid_and_3d_gate(tmp_path):
    from modules.ai_imaging.eagle_eye_brain.images import read_volume
    from modules.ai_imaging.eagle_eye_brain.lesions_2d import slice_geometry
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
    dicom_stack(tmp_path)
    image = read_volume(tmp_path, expected_protocol='flair', allow_2d=True)
    assert image.GetSpacing() == (.5, .5, 6.)
    assert slice_geometry(tmp_path) == 5
    with pytest.raises(BrainError):
        read_volume(tmp_path, expected_protocol='flair')


@pytest.mark.parametrize('description,ti,irregular', [
    ('t2_tirm_tra_dark-fluid_320', 150, False), ('t2_tse', 2500, False),
    ('t2_stir', 200, False), ('t1_flair', 2500, False), ('t2_flair', 2500, True)])
def test_2d_does_not_bypass_protocol_or_geometry(tmp_path, description, ti, irregular):
    from modules.ai_imaging.eagle_eye_brain.images import read_volume
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
    dicom_stack(tmp_path, description, ti, irregular)
    with pytest.raises(BrainError):
        read_volume(tmp_path, expected_protocol='flair', allow_2d=True)


@pytest.mark.parametrize('mode', ['2d', '3d', 'automatic', None])
def test_server_acquisition_contract(mode):
    import uuid
    from modules.ai_imaging.eagle_eye_remote.contracts import validate
    request = dict(protocol=1, request_id=uuid.uuid4().hex, module='brain-lesions', study_uid='1.2.3',
                   series={'t1': {'series_uid': '1.2.3.1', 'expected_count': 4},
                           'flair': {'series_uid': '1.2.3.2', 'expected_count': 4}},
                   parameters={'acquisition_mode': mode})
    if mode in ('2d', '3d'):
        assert validate(request) == request
    else:
        with pytest.raises(ValueError, match='acquisition'):
            validate(request)


def test_2d_report_does_not_borrow_3d_norms_or_criteria():
    from modules.ai_imaging.eagle_eye_brain.lesion_report_2d import sections
    from modules.ai_imaging.eagle_eye_brain.lesions_2d import measure_slices
    result = {'metrics': measure_slices(*images(), thickness_mm=5), 'sex': 'F',
              'acquisition_mode': '2d', 'clinical_context': {'primary_disease': 'ms'}}
    html = '\n'.join(sections(result, 'Synthetic', '27', ''))
    assert 'Sampled-slab' in html and 'Gap-inclusive' in html
    assert '4,247' in html and 'MindGlide' in html
    assert 'LST-AI' not in html and 'Requires native-image review' in html
    assert 'No MS diagnosis' in html


def test_manual_2d_revision_retains_slice_thickness_and_never_runs_3d_anatomy(tmp_path, monkeypatch):
    import json
    from modules.ai_imaging.eagle_eye_brain import manual_review, lesion_report, ms_assessment, svd_assessment
    from modules.ai_imaging.eagle_eye_brain.runtime import sha256
    from modules.ai_imaging.eagle_eye_brain.lesions_2d import measure_slices
    image, mask = images()
    for name, value in [('image.nii.gz', image), ('original.nii.gz', mask), ('corrected.nii.gz', mask)]:
        sitk.WriteImage(value, str(tmp_path / name))
    result = {'acquisition_mode': '2d', 'metrics': measure_slices(image, mask, thickness_mm=5),
              'clinical_context': {'primary_disease': 'ms'}, 'band_filter': {'status': 'applied'}}
    manifest = {'source_mask': str(tmp_path / 'original.nii.gz'), 'source_sha256': sha256(tmp_path / 'original.nii.gz'),
                'source_result': result, 'lesion': True}
    (tmp_path / 'session.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(lesion_report, 'write_lesion_report', lambda *a: None)
    monkeypatch.setattr(ms_assessment, 'enrich_ms', lambda *a, **k: pytest.fail('3D atlas used for 2D revision'))
    monkeypatch.setattr(svd_assessment, 'enrich_svd', lambda *a, **k: pytest.fail('3D reference used for 2D revision'))
    updated = manual_review._recalculate_review(tmp_path)
    assert updated['metrics']['total_volume_mm3'] == 2.5
    assert updated['metrics']['slice_thickness_mm'] == 5
    assert updated['pdf_available'] is True
    assert 'band_filter' not in updated and updated['source_band_filter']['status'] == 'applied'
    assert (tmp_path / 'original.nii.gz').is_file()
