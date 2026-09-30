"""Opt-in native resident socket probe; synthetic data and offscreen windows only.

Run with the workstation .venv and PYTHONPATH=.; never add --python-script or
--python-code to the child. Those change startup timing and masked implicit quit.
Only the probe-owned child is terminated by LocalRuntime.close().
"""
import argparse
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch

import numpy as np
import psutil
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from modules.mpr.advanced_3d_slicer import resident_service


def synthetic_series(directory):
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    for index in range(8):
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        path = directory / f"slice-{index}.dcm"
        image = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
        image.is_little_endian, image.is_implicit_VR = True, False
        values = dict(SOPClassUID=CTImageStorage, SOPInstanceUID=meta.MediaStorageSOPInstanceUID,
            StudyInstanceUID=study, SeriesInstanceUID=series, FrameOfReferenceUID=frame,
            PatientName="SYNTHETIC", PatientID="SYNTHETIC", Modality="CT",
            StudyDate="20000101", StudyTime="120000", SeriesNumber=1, InstanceNumber=index + 1,
            ImagePositionPatient=[0, 0, index], ImageOrientationPatient=[1, 0, 0, 0, 1, 0],
            PixelSpacing=[1, 1], SliceThickness=1, Rows=16, Columns=16,
            BitsAllocated=16, BitsStored=16, HighBit=15, PixelRepresentation=1,
            SamplesPerPixel=1, PhotometricInterpretation="MONOCHROME2",
            RescaleSlope=1, RescaleIntercept=0,
            PixelData=np.zeros((16, 16), dtype=np.int16).tobytes())
        for key, value in values.items():
            setattr(image, key, value)
        image.save_as(path, write_like_original=False)
    return series


def main(cycles):
    original_popen = resident_service.subprocess.Popen
    def offscreen_child(*args, **kwargs):
        kwargs["env"]["QT_QPA_PLATFORM"] = "offscreen"
        return original_popen(*args, **kwargs)

    with tempfile.TemporaryDirectory(prefix="aipacs-synthetic-lumen-") as temporary:
        root = Path(temporary)
        dicom = root / "dicom"
        dicom.mkdir()
        series = synthetic_series(dicom)
        for cycle in range(cycles):
            for workflow in ("vascular", "bronchoscopy"):
                runtime = resident_service.LocalRuntime("viewer", diagnostic_log=root / "native.log")
                try:
                    with patch.object(resident_service.subprocess, "Popen", offscreen_child):
                        runtime.start()
                    deadline = time.monotonic() + 60
                    while not runtime.ready():
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Synthetic runtime readiness timeout")
                        time.sleep(0.05)
                    loaded = runtime.command("load_dicom", dict(dicom_dir=str(dicom),
                        series_uid=series, workflow=workflow), threading.Event(), 60)
                    assert loaded["loaded"] and loaded["dimensions_ijk"] == [16, 16, 8]
                    shown = runtime.command("show", {}, threading.Event(), 10)
                    assert shown["visible"] and shown["pid"] == loaded["pid"]
                    print(f"PASS native socket cycle={cycle + 1} workflow={workflow}", flush=True)
                finally:
                    children = []
                    if runtime.process is not None:
                        try:
                            children = psutil.Process(runtime.process.pid).children(recursive=True)
                        except psutil.NoSuchProcess:
                            pass
                    runtime.close()
                    # CTK's parent can exit before its killed child releases the
                    # redirected log handle. Wait only for this probe's children.
                    _, alive = psutil.wait_procs(children, timeout=5)
                    if alive:
                        raise TimeoutError("Probe-owned native child did not finish cleanup")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, choices=range(1, 21), default=1)
    main(parser.parse_args().cycles)
