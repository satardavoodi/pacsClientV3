"""Synthetic equivalent DICOM copies must retain strict result ownership."""
from copy import deepcopy
import threading

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, DigitalXRayImageStorageForPresentation

from modules.ai_imaging.eagle_eye_alignment.service import load_image
from modules.ai_imaging.eagle_eye_remote import routing
from modules.ai_imaging.eagle_eye_total_spine.assist_service import image_binding


def image(tmp_path, name, **changes):
    path = tmp_path / name
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = DigitalXRayImageStorageForPresentation
    meta.MediaStorageSOPInstanceUID = '1.2.3.4.5'
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0'*128)
    for key, value in dict(StudyInstanceUID='1.2.3', SeriesInstanceUID='1.2.3.4',
                          SOPInstanceUID='1.2.3.4.5', Modality='DX', Rows=40, Columns=40,
                          SamplesPerPixel=1, BitsAllocated=16, BitsStored=16, HighBit=15,
                          PixelRepresentation=0, PhotometricInterpretation='MONOCHROME2',
                          PixelSpacing=[.2, .2], PatientName=name,
                          PixelData=np.arange(1600, dtype='<u2').tobytes()).items():
        setattr(ds, key, value)
    for key, value in changes.items():
        setattr(ds, key, value)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(path, write_like_original=False)
    return dict(load_image(path, '1.2.3', '1.2.3.4'), projection='coronal')


def response(remote):
    return dict(source_binding=[dict(study_uid='1.2.3', series_uid='1.2.3.4',
                                    sop_uid=remote['identity']['sop_uid'], sha256=remote['source_sha256'])],
                radiograph_binding=remote.get('radiograph_binding'), binding=image_binding(remote), candidates=[])


def run(monkeypatch, local, result):
    monkeypatch.setattr(routing, 'Client', lambda: type('ClientStub', (), {'analyze': lambda *a, **kw: deepcopy(result)})())
    return routing.radiograph('total-spine', local, threading.Event(), region=[0, 0, 40, 40])


def test_equivalent_reencoded_copy_returns_locally_bound_result(tmp_path, monkeypatch):
    local, remote = image(tmp_path, 'local'), image(tmp_path, 'server')
    assert local['source_sha256'] != remote['source_sha256']
    result = run(monkeypatch, local, response(remote))
    assert result['binding'] == image_binding(local)
    assert result['source_binding'][0]['sha256'] == remote['source_sha256']


@pytest.mark.parametrize('changes', [
    {'PixelData': (np.arange(1600, dtype='<u2')+1).tobytes()},
    {'PixelSpacing': [.3, .2]}, {'PixelSpacingCalibrationType': 'GEOMETRY'},
    {'ImageOrientationPatient': [0, 1, 0, 1, 0, 0]},
    {'PhotometricInterpretation': 'MONOCHROME1'}, {'PixelPaddingValue': 0},
    {'SOPInstanceUID': '1.2.3.4.6'},
])
def test_changed_source_rejected(tmp_path, monkeypatch, changes):
    local, remote = image(tmp_path, 'local'), image(tmp_path, 'server', **changes)
    with pytest.raises(ValueError):
        run(monkeypatch, local, response(remote))


def test_missing_evidence_rejects_different_bytes(tmp_path, monkeypatch):
    local, remote = image(tmp_path, 'local'), image(tmp_path, 'server')
    result = response(remote)
    result.pop('radiograph_binding')
    with pytest.raises(ValueError):
        run(monkeypatch, local, result)


def test_wrong_identity_rejected_even_for_equal_file_hash(tmp_path, monkeypatch):
    local = image(tmp_path, 'local')
    result = response(local)
    result['source_binding'][0]['study_uid'] = '9.8.7'
    with pytest.raises(ValueError):
        run(monkeypatch, local, result)


@pytest.mark.parametrize('field,value', [('projection', 'lateral'), ('shape', [40, 41]),
                                        ('source_sha256', 'unrelated')])
def test_spine_review_binding_cannot_be_rebound_without_proof(tmp_path, monkeypatch, field, value):
    local, remote = image(tmp_path, 'local'), image(tmp_path, 'server')
    result = response(remote)
    result['binding'][field] = value
    with pytest.raises(ValueError):
        run(monkeypatch, local, result)


def test_identical_legacy_source_remains_compatible(tmp_path, monkeypatch):
    local = image(tmp_path, 'local')
    result = response(local)
    result.pop('radiograph_binding')
    assert run(monkeypatch, local, result)['binding'] == image_binding(local)
