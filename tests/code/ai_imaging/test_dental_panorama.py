"""Synthetic identity, output completeness and admission guards for the dental trial."""
import copy
import pytest
from modules.ai_imaging import dental_panorama as dental
from modules.ai_imaging.eagle_eye_remote.contracts import validate
from modules.ai_imaging.eagle_eye_function_catalog import function_options_for_modality


def request():
    return {'protocol': 1, 'request_id': 'a' * 32, 'module': 'dental-panorama',
            'study_uid': '1.2.3', 'series': {'primary': {'series_uid': '1.2.4', 'sop_uid': '1.2.5', 'expected_count': 1}},
            'parameters': {'panoramic_confirmed': True}}


def rows():
    return [{'fdi': str(q * 10 + n), 'finding': f, 'score': .2}
            for q in range(1, 5) for n in range(1, 9) for f in dental.FINDINGS]


def test_exact_panorama_is_admitted():
    assert validate(request())['module'] == 'dental-panorama'


@pytest.mark.parametrize('change', ['missing_sop', 'unconfirmed', 'count', 'source_path', 'correction'])
def test_unsafe_requests_rejected(change):
    value = request()
    if change == 'missing_sop':
        del value['series']['primary']['sop_uid']
    elif change == 'unconfirmed':
        value['parameters']['panoramic_confirmed'] = False
    elif change == 'count':
        value['series']['primary']['expected_count'] = 2
    else:
        value['parameters'][change] = 'untrusted'
    with pytest.raises(ValueError):
        validate(value)


def test_output_contract():
    assert len(dental.validate_rows(rows())) == 256


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'nan', 'range', 'unknown'])
def test_incomplete_or_invalid_output_never_becomes_normal(change):
    value = rows()
    if change == 'missing':
        value.pop()
    elif change == 'duplicate':
        value[1] = copy.deepcopy(value[0])
    elif change == 'nan':
        value[0]['score'] = float('nan')
    elif change == 'range':
        value[0]['score'] = 2
    else:
        value[0]['finding'] = 'PULPITIS'
    with pytest.raises(ValueError):
        dental.validate_rows(value)


def test_picker_radiographs_only():
    for modality in ('DX', 'CR', 'PX', 'IO'):
        assert any(o.key == 'dental_panorama' for o in function_options_for_modality(modality))
    assert not any(o.key == 'dental_panorama' for o in function_options_for_modality('MR'))


def test_result_identity_and_raw_rows_are_checked(monkeypatch, tmp_path):
    from modules.ai_imaging.eagle_eye_remote import client
    from PacsClient.utils import data_paths
    monkeypatch.setattr(data_paths, 'AI_DIR', tmp_path)
    class FakeClient:
        def json(self, path):
            return {'modules': ['dental-panorama']}
        def analyze(self, *args, **kwargs):
            return {'dental_scores': rows(), 'source_binding': [{'study_uid': '1.2.9', 'series_uid': '1.2.4', 'sop_uid': '1.2.5'}]}
    monkeypatch.setattr(client, 'Client', FakeClient)
    import threading
    with pytest.raises(ValueError, match='does not match'):
        dental.analyze({'identity': {'study_uid': '1.2.3', 'series_uid': '1.2.4', 'sop_uid': '1.2.5'}}, threading.Event())


def image_file(tmp_path, photometric='MONOCHROME2'):
    import numpy as np
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, DigitalXRayImageStorageForPresentation
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = DigitalXRayImageStorageForPresentation
    meta.MediaStorageSOPInstanceUID = '1.2.5'
    ds = FileDataset(str(tmp_path / 'synthetic.dcm'), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.StudyInstanceUID = '1.2.3'; ds.SeriesInstanceUID = '1.2.4'; ds.SOPInstanceUID = '1.2.5'
    ds.Modality = 'DX'; ds.Rows = 2; ds.Columns = 3; ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated = 16; ds.BitsStored = 16; ds.HighBit = 15; ds.PixelRepresentation = 0
    ds.PixelPaddingValue = 0
    ds.PixelData = np.array([[0, 100, 200], [300, 400, 500]], dtype='<u2').tobytes()
    ds.is_little_endian = True; ds.is_implicit_VR = False
    ds.save_as(ds.filename, write_like_original=False)
    return ds


def test_padding_contrast_and_monochrome_inversion(tmp_path):
    ds = image_file(tmp_path)
    a = dental.load_image(ds.filename, '1.2.3')['pixels']
    assert a.tolist() == [[0, 0, 63], [127, 191, 255]]
    ds.PhotometricInterpretation = 'MONOCHROME1'; ds.save_as(ds.filename)
    b = dental.load_image(ds.filename, '1.2.3')['pixels']
    assert b.tolist() == [[0, 255, 191], [127, 63, 0]]


def test_cross_study_and_multiframe_images_rejected(tmp_path):
    ds = image_file(tmp_path)
    with pytest.raises(ValueError, match='another study'):
        dental.load_image(ds.filename, '1.2.9')
    ds.NumberOfFrames = 2; ds.save_as(ds.filename)
    with pytest.raises(ValueError, match='One monochrome'):
        dental.load_image(ds.filename, '1.2.3')


def test_saved_review_identity_and_model_are_checked(tmp_path):
    from PIL import Image
    Image.new('L', (10, 10)).save(tmp_path / 'preview.png')
    result = dict(analysis_study_uid='1.2.3', source_binding=[{'study_uid': '1.2.3'}], model_digest=dental.IMAGE_DIGEST,
                  dental_scores=rows(), artifact_directory=str(tmp_path))
    assert dental.load_saved(result, '1.2.3')['pixels'].shape == (10, 10)
    with pytest.raises(ValueError, match='another study'):
        dental.load_saved(result, '1.2.9')
    result['model_digest'] = 'other'
    with pytest.raises(ValueError, match='revision'):
        dental.load_saved(result, '1.2.3')


def test_saved_review_renders_raw_scores_without_enabling_inference(tmp_path):
    import time
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.dental_panorama_widget import DentalPanoramaWidget
    app = QApplication.instance() or QApplication([])
    Image.new('L', (20, 10)).save(tmp_path / 'preview.png')
    result = dict(analysis_study_uid='1.2.3', source_binding=[{'study_uid': '1.2.3'}], model_digest=dental.IMAGE_DIGEST,
                  dental_scores=rows(), artifact_directory=str(tmp_path))
    widget = DentalPanoramaWidget(study_uid='1.2.3')
    try:
        widget.restore_saved_result(result)
        deadline = time.monotonic() + 5
        while widget._future is not None and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.01)
        assert widget._future is None
        widget.cutoff.setValue(0)
        assert widget.table.rowCount() == 256
        assert widget.table.item(0, 2).text() == '0.2000'
        assert not widget.run.isEnabled()
        assert not widget.preview.pixmap().isNull()
    finally:
        widget.teardown(); widget.close()
