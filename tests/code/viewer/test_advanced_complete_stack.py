"""Synthetic disk -> metadata -> VTK -> last-slice checks for complete MR stacks."""
import numpy as np
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage
import vtkmodules.all as vtk
from vtkmodules.util.numpy_support import vtk_to_numpy


@pytest.mark.parametrize("count", [3, 30])
def test_all_spatial_frames_reach_vtk_and_last_slice(tmp_path, count):
    from PacsClient.pacs.patient_tab.utils import image_io
    from modules.viewer.advanced.viewer_2d import ImageViewer2D
    folder = tmp_path / "1"
    folder.mkdir()
    for number in reversed(range(1, count + 1)):
        path = folder / f"{number}.dcm"
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
        for key, value in dict(
            SOPClassUID=MRImageStorage, SOPInstanceUID=f"1.2.826.0.1.3680043.10.999.4.{number}",
            StudyInstanceUID="1.2.826.0.1.3680043.10.999.1",
            SeriesInstanceUID="1.2.826.0.1.3680043.10.999.2", Modality="MR",
            SeriesNumber=1, InstanceNumber=number, Rows=8, Columns=10,
            SamplesPerPixel=1, PhotometricInterpretation="MONOCHROME2",
            BitsAllocated=16, BitsStored=16, HighBit=15, PixelRepresentation=0,
            ImageOrientationPatient=[1, 0, 0, 0, 1, 0],
            ImagePositionPatient=[0, 0, number * 2], PixelSpacing=[1, 1], SliceThickness=2,
        ).items():
            setattr(ds, key, value)
        ds.PixelData = np.full((8, 10), number, dtype=np.uint16).tobytes()
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.save_as(path, write_like_original=False)
    image, metadata, _ = image_io._load_series_from_filesystem(tmp_path, 1)
    assert image.GetDimensions()[2] == len(metadata["instances"]) == count
    frames = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(count, 8, 10)
    assert sorted(int(frame[0, 0]) for frame in frames) == list(range(1, count + 1))
    assert [int(frame[0, 0]) for frame in frames] == [x["instance_number"] for x in metadata["instances"]]
    viewer = vtk.vtkResliceImageViewer()
    viewer.SetInputData(image)
    viewer.SetSliceOrientationToXY()
    assert ImageViewer2D.get_count_of_slices(viewer) == count
    for k in (0, count - 1, 0):
        viewer.SetSlice(k)
        assert viewer.GetSlice() == k
