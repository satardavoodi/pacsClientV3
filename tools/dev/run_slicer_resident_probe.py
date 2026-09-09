"""Qualify only owned source-linked Slicer processes with synthetic data."""
import json
import os
from pathlib import Path
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def synthetic_series(directory):
    import numpy as np
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid
    directory.mkdir()
    study, frame = generate_uid(), generate_uid()
    chosen = None
    for series_number, count in ((1, 4), (2, 6)):
        chosen = generate_uid()
        for index in range(count):
            sop = generate_uid()
            meta = FileMetaDataset()
            meta.MediaStorageSOPClassUID = MRImageStorage
            meta.MediaStorageSOPInstanceUID = sop
            meta.TransferSyntaxUID = ExplicitVRLittleEndian
            path = directory / f"series-{series_number}-{index}.dcm"
            ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
            ds.SOPClassUID, ds.SOPInstanceUID = MRImageStorage, sop
            ds.PatientID, ds.PatientName = "SYNTHETIC-RESIDENT", "Synthetic^Resident"
            ds.StudyInstanceUID, ds.SeriesInstanceUID = study, chosen
            ds.FrameOfReferenceUID, ds.Modality = frame, "MR"
            ds.StudyDate, ds.StudyTime = "20260831", "120000"
            ds.SeriesNumber, ds.InstanceNumber = series_number, index + 1
            ds.ImagePositionPatient = [0, 0, index * 2.5]
            ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.PixelSpacing, ds.SliceThickness = [0.9, 0.8], 2.5
            ds.Rows, ds.Columns = 24, 32
            ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
            ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 0
            ds.PixelData = np.full((24, 32), series_number * 40 + index, dtype=np.uint16).tobytes()
            ds.is_little_endian, ds.is_implicit_VR = True, False
            ds.save_as(path, write_like_original=False)
    return chosen


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--inference", action="store_true", help="Also run the prepared offline model on synthetic data")
    options = parser.parse_args()
    import subprocess
    processes = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq AIPacsAdvancedViewer.exe", "/FO", "CSV", "/NH"],
                                        text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if '"aipacsadvancedviewer.exe"' in processes.lower():
        raise RuntimeError("An Advanced Viewer exists; no synthetic probe started")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    from modules.mpr.advanced_3d_slicer.resident_service import LocalRuntime, ResidentService, OperationRejected
    app = QApplication.instance() or QApplication([])
    output = REPO / "generated-files/offline-lumbar/resident-probes" / uuid.uuid4().hex
    output.mkdir(parents=True)
    exe = REPO / "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build/AIPacsAdvancedViewer.exe"
    runtimes = {}
    services = {}
    for role in ("viewer", "analysis"):
        runtime = LocalRuntime(role, executable=exe, diagnostic_log=output / (role + ".log"))
        runtimes[role] = runtime
        services[role] = ResidentService(role, backend_factory=lambda r=runtime: r, startup_timeout=45)
    ticks = []
    heartbeat = QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
    heartbeat.start()
    def await_future(future, timeout=60):
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if future.done() else None)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(timeout * 1000)
        loop.exec()
        return future.result(timeout=0)
    result = {"scope": "synthetic only", "passed": False}
    try:
        start = time.monotonic()
        await_future(services["viewer"].warmup())
        result["viewer_cold_seconds"] = time.monotonic() - start
        before = await_future(services["viewer"].request("status"))
        result["hidden_viewer"] = before
        assert before["window_exists"] and not before["window_visible"] and before["hidden_before_show"]
        start = time.monotonic()
        shown = await_future(services["viewer"].request("show"))
        result["viewer_warm_seconds"] = time.monotonic() - start
        assert shown["pid"] == before["pid"]
        await_future(services["viewer"].request("hide"))
        # Authentication and command allowlisting must reject without ending the viewer.
        import socket
        with socket.create_connection(("127.0.0.1", runtimes["viewer"].connection["port"]), timeout=3) as connection:
            connection.sendall(b'{"operation":"ping","token":"invalid"}\n')
            assert json.loads(connection.recv(4096))["ok"] is False
        try:
            await_future(services["viewer"].request("execute_python", {"code": "raise RuntimeError"}))
            raise AssertionError("Arbitrary code was accepted")
        except OperationRejected:
            pass
        directory = output / "synthetic-dicom"
        selected = synthetic_series(directory)
        try:
            await_future(services["viewer"].request("load_dicom", {"dicom_dir": str(directory)}))
            raise AssertionError("An ambiguous folder was accepted")
        except OperationRejected:
            pass
        loaded = await_future(services["viewer"].request("load_dicom", {"dicom_dir": str(directory), "series_uid": selected}))
        assert loaded["pid"] == before["pid"] and loaded["dimensions_ijk"] == [32, 24, 6]
        try:
            await_future(services["viewer"].request("load_dicom", {"dicom_dir": str(directory), "series_uid": selected}))
            raise AssertionError("The existing scene was replaced")
        except OperationRejected:
            pass
        assert (await_future(services["viewer"].request("status")))["volume_nodes"] == 1
        await_future(services["viewer"].request("hide"))
        result["source_selection"] = {"exact_second_series": True, "ambiguous_folder_rejected": True,
                                       "existing_scene_preserved": True, "unauthorized_requests_rejected": True}
        import numpy as np
        array = np.zeros((12, 24, 32), dtype=np.float32)
        array[2:6, 4:12, 3:15] = 40
        array.setflags(write=False)
        affine = np.diag([0.8, 0.9, 2.5, 1])
        inference = await_future(services["analysis"].analyze_snapshot(array, affine, algorithm="threshold", lower=30, upper=100))
        assert inference["voxels"] == 384
        assert np.array_equal(np.load(inference["labels_file"]), array > 0)
        assert inference["pid"] != before["pid"]
        analysis = await_future(services["analysis"].request("status"))
        assert not analysis["window_exists"] and analysis["volume_nodes"] == 0
        result["analysis"] = {"voxels": inference["voxels"], "volume_mm3": inference["volume_mm3"],
                              "separate_process": True, "no_main_window": True, "mask_equal": True}
        if options.inference:
            start = time.monotonic()
            model_result = await_future(services["analysis"].analyze_snapshot(array, affine), timeout=180)
            labels = np.load(model_result["labels_file"], allow_pickle=False)
            assert labels.shape == array.shape and labels.dtype == np.uint8 and labels.max() <= 25
            assert model_result["pid"] == inference["pid"]
            assert not (await_future(services["analysis"].request("status")))["window_exists"]
            result["offline_model"] = {"seconds": time.monotonic() - start, "same_headless_process": True,
                                        "geometry_preserved": True, "nonzero_voxels": int(np.count_nonzero(labels))}
        result["heartbeat_ticks"] = len(ticks)
        result["max_heartbeat_gap_seconds"] = max(b - a for a, b in zip(ticks, ticks[1:]))
        assert result["max_heartbeat_gap_seconds"] < 1
        result["passed"] = True
    except Exception:
        import traceback
        result["error"] = traceback.format_exc()
    finally:
        for service in services.values():
            service.stop()
        for runtime in runtimes.values():
            runtime.close()
        (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "result": str(output / "result.json")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
