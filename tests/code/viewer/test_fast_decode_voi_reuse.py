"""Pixel decoding must retain VOI facts instead of reopening the same header."""
from types import SimpleNamespace
import numpy as np
import pytest
from pydicom.dataset import Dataset
import modules.viewer.fast.lightweight_2d_pipeline as lw


@pytest.mark.parametrize('function', [None, 'SIGMOID', 'LINEAR_EXACT', 'LINEAR'])
def test_decoded_dataset_resolves_voi_without_another_file_read(monkeypatch, function):
    ds = Dataset()
    ds.Rows = ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = 'MONOCHROME2'
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    from pydicom.dataset import FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.PixelData = np.arange(4, dtype='<u2').tobytes()
    if function: ds.VOILUTFunction = function
    pipe = lw.Lightweight2DPipeline()
    sm = lw.SliceMeta(path='synthetic.dcm', rows=2, cols=2, pixel_spacing=(1,1),
        iop=(1,0,0,0,1,0), ipp=(0,0,0), slice_thickness=1, spacing_between_slices=1,
        photometric='MONOCHROME2', bits_allocated=16, pixel_representation=0,
        samples_per_pixel=1, window_width=4, window_center=2, slope=1,
        intercept=0, instance_number=1, is_rgb=False)
    pipe._slices = [sm]
    monkeypatch.setattr(lw, 'get_disk_pixel_cache', lambda: SimpleNamespace(get=lambda **kw: None, put=lambda *a, **kw: None))
    monkeypatch.setattr(lw, 'read_dicom', lambda *a, **kw: ds)
    pipe._decode_slice(0)
    reads = []
    monkeypatch.setattr(lw.pydicom, 'dcmread', lambda *a, **kw: reads.append(a) or ds)
    assert pipe._get_voi_lut_function(sm) == function
    assert reads == [], 'Rendering reopened a dataset already read by decoding'
    # An unrelated/next slice must still resolve its own header; absence cannot
    # leak from a retired decode through pipeline-global state.
    from dataclasses import replace
    next_slice = replace(sm, voi_lut_function=None, voi_lut_function_resolved=False)
    pipe._get_voi_lut_function(next_slice)
    assert len(reads) == 1


@pytest.mark.parametrize('function', [None, 'SIGMOID', 'LINEAR_EXACT'])
def test_header_scan_preserves_known_voi_presence_and_absence(monkeypatch, function):
    from modules.viewer.fast.dicom_header_scan import entry_from_dataset
    ds = Dataset()
    if function: ds.VOILUTFunction = function
    pipe = lw.Lightweight2DPipeline()
    sm = pipe._slice_meta_from_entry(entry_from_dataset('synthetic.dcm', ds))
    reads = []
    monkeypatch.setattr(lw.pydicom, 'dcmread', lambda *a, **kw: reads.append(a) or ds)
    assert pipe._get_voi_lut_function(sm) == function
    assert reads == [], 'Header scanning discarded already resolved display facts'
