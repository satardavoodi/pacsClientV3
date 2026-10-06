"""Synthetic, read-only diagnosis of Standard MPR stack-direction provenance.

Run with the repository interpreter. No GUI, database or clinical files are used.
Exit 1 means the tested presentation invariant is violated, not a probe error.
The temporary DICOM headers and scalar volume are generated from scratch.
"""

from __future__ import annotations

import json
import sys
import tempfile
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pydicom
import vtkmodules.all as vtk
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from modules.mpr.zeta_mpr import _mpr_canonicalize as canon
from modules.mpr.zeta_mpr.mpr_viewer._mpr_orientation import _MprOrientationMixin
from PacsClient.pacs.patient_tab.utils.image_io import get_itk_image
from PacsClient.pacs.patient_tab.utils.utils import convert_itk2vtk


def run_case(instance_sign: int, volume_sign: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="mpr-synthetic-order-") as temporary:
        study_uid, series_uid = generate_uid(), generate_uid()
        files = []
        for index in range(3):
            meta = FileMetaDataset()
            meta.TransferSyntaxUID = ExplicitVRLittleEndian
            meta.MediaStorageSOPClassUID = CTImageStorage
            meta.MediaStorageSOPInstanceUID = generate_uid()
            path = Path(temporary) / f"slice-{index + 1}.dcm"
            ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
            ds.is_little_endian = True
            ds.is_implicit_VR = False
            ds.SOPClassUID = CTImageStorage
            ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
            ds.StudyInstanceUID = study_uid
            ds.SeriesInstanceUID = series_uid
            ds.Modality = "CT"
            ds.PatientPosition = "HFS"
            ds.InstanceNumber = index + 1
            ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.ImagePositionPatient = [0, 0, instance_sign * index * 2]
            ds.PixelSpacing = [1, 1]
            ds.Rows = ds.Columns = 3
            ds.BitsAllocated = ds.BitsStored = 16
            ds.HighBit = 15
            ds.PixelRepresentation = ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            ds.PixelData = np.full((3, 3), instance_sign * index * 2, dtype=np.int16).tobytes()
            ds.save_as(path, write_like_original=False)
            files.append(str(path))

        # Known volume order, independent of InstanceNumber. A production
        # loader may have reordered the files before handing this volume over.
        ordered_files = files if instance_sign == volume_sign else files[::-1]
        with contextlib.redirect_stdout(io.StringIO()):
            volume = convert_itk2vtk(get_itk_image(ordered_files))

        # Suppress the canonicalizer's diagnostic file writes, even though
        # these inputs are synthetic. Do not modify the actual application.
        with patch.object(canon, "probe", lambda message: None):
            result = canon.canonicalize_volume(volume, temporary)
        array = result.GetFieldData().GetArray("ZetaAnatA")
        viewer = _MprOrientationMixin()
        viewer._anat_A = np.array([array.GetValue(i) for i in range(9)]).reshape(3, 3)
        viewer.center = (1, 1, 2)
        true_axes = np.diag([-1.0, -1.0, float(volume_sign)])
        views = {}
        for view in ("sagittal", "coronal"):
            _, _, up = viewer._anatomical_camera(view)
            superior = float((true_axes @ np.asarray(up))[2])
            views[view] = {"screen_up_is_superior": superior > 0}
        return {
            "instance_order_sign": instance_sign,
            "actual_volume_sign": volume_sign,
            "attached_sign": float(viewer._anat_A[2, 2]),
            "views": views,
        }


if __name__ == "__main__":
    cases = [run_case(i, v) for i, v in ((-1, -1), (1, 1), (1, -1), (-1, 1))]
    print(json.dumps(cases, indent=2))
    failed = sum(not view["screen_up_is_superior"] for case in cases for view in case["views"].values())
    print(f"Presentation invariant failures: {failed}/8")
    raise SystemExit(1 if failed else 0)
