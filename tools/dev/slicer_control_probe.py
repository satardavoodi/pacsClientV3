"""Synthetic-only control probe, executed by the existing Slicer runtime.

Not a production bridge. Never load this into an interactive patient session.
The paired client starts a separate, hidden runtime with temporary settings.
Only generated fixtures and fixed output paths are accepted. No Python/exec,
file browser, DICOMweb, or generic Slicer HTTP handlers are exposed.
"""

import importlib.util
import json
import math
import os
from pathlib import Path
import secrets
import sys

import numpy as np
import qt
import slicer
import vtk
from WebServer import SlicerHTTPServer
from WebServerLib.BaseRequestHandler import BaseRequestHandler


ROOT = Path(os.environ["AIPACS_SLICER_PROBE_DIR"]).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
if slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLVolumeNode"):
    raise RuntimeError("Probe requires an empty, isolated scene")
TOKEN = secrets.token_urlsafe(32)
STATE = {}


def fixture_array():
    array = np.zeros((12, 24, 32), dtype=np.int16)
    array[2:10, 6:18, 8:24] = 40
    array[4:8, 10:14, 12:20] = 80
    return array


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def capabilities():
    names = [str(name) for name in slicer.app.moduleManager().factoryManager().loadedModuleNames()]
    widget = slicer.qMRMLSegmentEditorWidget()
    effects = [str(name) for name in widget.availableEffectNames()]
    widget.deleteLater()
    return {
        "application": str(slicer.app.applicationName),
        "version": str(slicer.app.applicationVersion),
        "revision": str(slicer.app.repositoryRevision),
        "python": sys.version.split()[0],
        "vtk": vtk.vtkVersion.GetVTKVersion(),
        "modules": sorted(names),
        "segment_editor_effects": sorted(effects),
        "packages": {name: importlib.util.find_spec(name) is not None
                     for name in ("numpy", "pydicom", "SimpleITK", "torch", "monai", "mcp", "totalsegmentator")},
        "transport": "bundled WebServer.SlicerHTTPServer with synthetic-only handler",
        "operations": ["capabilities", "open_fixture", "open_dicom_fixture", "threshold", "save_reload", "shutdown"]
                      + (["extension_cross_section"] if os.environ.get("AIPACS_SLICER_PROBE_EXTENSION") == "1" else []),
    }


def open_fixture():
    check("volume" not in STATE, "Fixture is already open")
    original = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "SYNTHETIC_CONTROL_FIXTURE")
    original.SetSpacing(0.8, 0.9, 2.5)
    slicer.util.updateVolumeFromArray(original, fixture_array())
    path = ROOT / "synthetic_input.nrrd"
    check(slicer.util.saveNode(original, str(path)), "Could not save fixture")
    slicer.mrmlScene.RemoveNode(original)
    volume = slicer.util.loadVolume(str(path), {"show": False})
    check(volume is not None, "Could not load fixture")
    check(np.array_equal(slicer.util.arrayFromVolume(volume), fixture_array()), "Input pixel mismatch")
    STATE["volume"] = volume
    return {"shape_kji": list(fixture_array().shape), "spacing_ijk_mm": list(volume.GetSpacing()),
            "pixel_roundtrip_equal": True, "input": path.name}


def open_dicom_fixture():
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid
    from DICOMLib import DICOMUtils

    check("dicom_checked" not in STATE, "DICOM fixture already checked")
    directory = ROOT / "synthetic_dicom"
    directory.mkdir(exist_ok=False)
    study_uid, series_uid, frame_uid = generate_uid(), generate_uid(), generate_uid()
    array = fixture_array()
    for index, plane in enumerate(array):
        meta = Dataset()
        meta.MediaStorageSOPClassUID = MRImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file = FileDataset(str(directory / f"slice_{index:03d}.dcm"), {}, file_meta=meta, preamble=b"\0" * 128)
        file.is_little_endian, file.is_implicit_VR = True, False
        file.SOPClassUID, file.SOPInstanceUID = MRImageStorage, meta.MediaStorageSOPInstanceUID
        file.StudyInstanceUID, file.SeriesInstanceUID, file.FrameOfReferenceUID = study_uid, series_uid, frame_uid
        file.PatientName, file.PatientID = "SYNTHETIC^CONTROL", "SYNTHETIC_CONTROL_FIXTURE"
        file.PatientBirthDate, file.PatientSex = "", "O"
        file.StudyDate, file.StudyTime, file.StudyID = "20000101", "120000", "SYNTHETIC"
        file.AccessionNumber, file.StudyDescription = "", "Synthetic control probe"
        file.SeriesDescription, file.Modality, file.SeriesNumber = "Synthetic MR volume", "MR", 1
        file.InstanceNumber = index + 1
        file.ImageType = ["ORIGINAL", "PRIMARY", "OTHER"]
        file.Rows, file.Columns = plane.shape
        file.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        file.ImagePositionPatient = [0, 0, index * 2.5]
        file.PixelSpacing, file.SliceThickness, file.SpacingBetweenSlices = [0.9, 0.8], 2.5, 2.5
        file.SamplesPerPixel, file.PhotometricInterpretation = 1, "MONOCHROME2"
        file.BitsAllocated, file.BitsStored, file.HighBit, file.PixelRepresentation = 16, 16, 15, 1
        file.PixelData = plane.tobytes()
        file.save_as(file.filename, write_like_original=False)
    with DICOMUtils.TemporaryDICOMDatabase(str(ROOT / "synthetic_dicom_database")) as database:
        check(DICOMUtils.importDicom(str(directory), database), "Synthetic DICOM import failed")
        node_ids = DICOMUtils.loadSeriesByUID([series_uid])
        volumes = [slicer.mrmlScene.GetNodeByID(node_id) for node_id in node_ids]
        volumes = [node for node in volumes if node and node.IsA("vtkMRMLScalarVolumeNode")]
        check(len(volumes) == 1, "Synthetic DICOM did not produce one scalar volume")
        node = volumes[0]
        check(np.array_equal(slicer.util.arrayFromVolume(node), array), "DICOM pixels differ")
        check(np.allclose(node.GetSpacing(), (0.8, 0.9, 2.5)), "DICOM spacing differs")
        spacing = list(node.GetSpacing())
        slicer.mrmlScene.RemoveNode(node)
    STATE["dicom_checked"] = True
    return {"instances": len(array), "pixel_roundtrip_equal": True, "spacing_ijk_mm": spacing,
            "database": "isolated synthetic database; no PACS database used"}


def threshold(lower, upper):
    check(type(lower) in (int, float) and type(upper) in (int, float), "Numeric thresholds required")
    check(math.isfinite(lower) and math.isfinite(upper) and 0 <= lower <= upper <= 100, "Thresholds outside synthetic range")
    volume = STATE["volume"]
    if "segmentation" not in STATE:
        segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "SYNTHETIC_THRESHOLD")
        segmentation.CreateDefaultDisplayNodes()
        segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
        segment_id = segmentation.GetSegmentation().AddEmptySegment("synthetic_region", "Synthetic region")
        editor_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        editor = slicer.qMRMLSegmentEditorWidget()
        editor.setMRMLScene(slicer.mrmlScene)
        editor.setMRMLSegmentEditorNode(editor_node)
        editor.setSegmentationNode(segmentation)
        editor.setSourceVolumeNode(volume)
        editor.setCurrentSegmentID(segment_id)
        STATE.update(segmentation=segmentation, segment_id=segment_id, editor=editor, editor_node=editor_node)
    editor = STATE["editor"]
    editor.setActiveEffectByName("Threshold")
    effect = editor.activeEffect()
    check(effect is not None, "Threshold effect unavailable")
    effect.setParameter("MinimumThreshold", lower)
    effect.setParameter("MaximumThreshold", upper)
    readback = [effect.doubleParameter("MinimumThreshold"), effect.doubleParameter("MaximumThreshold")]
    effect.self().onApply()
    mask = slicer.util.arrayFromSegmentBinaryLabelmap(STATE["segmentation"], STATE["segment_id"], volume)
    expected = (fixture_array() >= lower) & (fixture_array() <= upper)
    check(np.array_equal(mask > 0, expected), "Threshold result differs from known synthetic region")
    STATE["mask"] = mask.copy()
    return {"parameters_readback": readback, "voxels": int(np.count_nonzero(mask)),
            "matches_expected_region": True, "volume_mm3": float(np.count_nonzero(mask) * np.prod(volume.GetSpacing()))}


def extension_cross_section(axis):
    """Exercise reviewed third-party logic and separately inspect its GUI support."""
    check(os.environ.get("AIPACS_SLICER_PROBE_EXTENSION") == "1", "Extension probe is disabled")
    check(axis in ("slice", "row", "column"), "Unsupported extension axis")
    from SegmentCrossSectionArea import SegmentCrossSectionAreaLogic

    segmentation, volume = STATE["segmentation"], STATE["volume"]
    check(segmentation.GetSegmentation().GetNumberOfSegments() == 1, "Expected one synthetic segment")
    check(np.count_nonzero(STATE["mask"]) == 128, "Expected the high-threshold synthetic mask")
    if "extension_gui" not in STATE:
        try:
            widget = slicer.modules.segmentcrosssectionarea.widgetRepresentation().self()
            check(widget.logic is not None, "Extension widget setup did not initialize logic; see runtime log")
            STATE["extension_widget"] = widget
            STATE["extension_gui"] = {"initialized": True}
        except Exception as exc:
            # UI compatibility and computational compatibility are separate.
            STATE["extension_gui"] = {"initialized": False, "error": str(exc)}
    logic = SegmentCrossSectionAreaLogic()
    parameter_node = logic.getParameterNode()
    widget = STATE.get("extension_widget")
    if widget is not None:
        widget.setParameterNode(parameter_node)
    table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", f"SYNTHETIC_AREA_{axis}")
    chart = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode", f"SYNTHETIC_AREA_PLOT_{axis}")
    modified = parameter_node.StartModify()
    parameter_node.SetNodeReferenceID("Segmentation", segmentation.GetID())
    parameter_node.SetNodeReferenceID("Volume", volume.GetID())
    parameter_node.SetNodeReferenceID("ResultsTable", table.GetID())
    parameter_node.SetNodeReferenceID("ResultsChart", chart.GetID())
    parameter_node.SetParameter("Axis", axis)
    parameter_node.EndModify(modified)
    check(parameter_node.GetParameter("Axis") == axis, "Extension parameter readback failed")
    if widget is not None:
        check(widget.ui.axisSelectorBox.currentText == axis, "Extension GUI did not reflect the parameter")
        check(widget.ui.segmentationSelector.currentNode() == segmentation, "Extension input GUI mismatch")
        check(widget.ui.tableSelector.currentNode() == table, "Extension output GUI mismatch")
    logic.run(segmentation, volume, axis, table, chart)
    segment_name = segmentation.GetSegmentation().GetSegment(STATE["segment_id"]).GetName()
    areas = slicer.util.arrayFromTableColumn(table, segment_name).copy()
    axis_ijk, expected_count, expected_peak = {"slice": (2, 4, 23.04), "row": (0, 8, 36.0),
                                              "column": (1, 4, 64.0)}[axis]
    check(np.count_nonzero(areas) == expected_count, "Unexpected count of nonempty cross sections")
    check(np.allclose(areas[areas > 0], expected_peak), "Cross-section area differs from known cuboid")
    measured_volume = float(areas.sum() * volume.GetSpacing()[axis_ijk])
    check(math.isclose(measured_volume, 230.4, rel_tol=1e-6), "Integrated cross-section volume differs")
    path = ROOT / f"synthetic_cross_section_{axis}.tsv"
    check(slicer.util.saveNode(table, str(path)), "Extension table save failed")
    loaded = slicer.util.loadTable(str(path))
    check(loaded is not None, "Extension table reload failed")
    reloaded_areas = slicer.util.arrayFromTableColumn(loaded, segment_name)
    check(np.allclose(reloaded_areas.astype(float), areas), "Saved extension measurements differ")
    slicer.mrmlScene.RemoveNode(loaded)
    return {"extension": "PerkLab/SlicerSandbox:SegmentCrossSectionArea",
            "source_commit": "7211da97bf65edc26fc67f1c69668be584409786", "axis": axis,
            "parameter_readback_equal": True, "gui": STATE["extension_gui"],
            "gui_parameter_readback_equal": widget is not None, "table_rows": int(len(areas)),
            "nonempty_cross_sections": expected_count, "maximum_area_mm2": float(areas.max()),
            "integrated_volume_mm3": measured_volume, "table_roundtrip_equal": True, "file": path.name}


def save_reload():
    import SegmentStatistics

    segmentation, volume = STATE["segmentation"], STATE["volume"]
    path = ROOT / "synthetic_result.seg.nrrd"
    check(slicer.util.saveNode(segmentation, str(path)), "Segmentation save failed")
    loaded = slicer.util.loadSegmentation(str(path))
    check(loaded is not None, "Segmentation reload failed")
    loaded_id = loaded.GetSegmentation().GetNthSegmentID(0)
    actual = slicer.util.arrayFromSegmentBinaryLabelmap(loaded, loaded_id, volume)
    check(np.array_equal(actual, STATE["mask"]), "Segmentation roundtrip mismatch")
    labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "SYNTHETIC_EXPORT")
    check(slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(segmentation, labelmap, volume), "Labelmap export failed")
    label_path = ROOT / "synthetic_result.nii.gz"
    check(slicer.util.saveNode(labelmap, str(label_path)), "NIfTI save failed")
    label_loaded = slicer.util.loadLabelVolume(str(label_path), {"show": False})
    check(np.array_equal(slicer.util.arrayFromVolume(label_loaded) > 0, STATE["mask"] > 0), "NIfTI mask mismatch")
    matrix_before, matrix_after = vtk.vtkMatrix4x4(), vtk.vtkMatrix4x4()
    labelmap.GetIJKToRASMatrix(matrix_before)
    label_loaded.GetIJKToRASMatrix(matrix_after)
    check(np.allclose(slicer.util.arrayFromVTKMatrix(matrix_before), slicer.util.arrayFromVTKMatrix(matrix_after)), "NIfTI geometry mismatch")
    statistics = SegmentStatistics.SegmentStatisticsLogic()
    statistics.getParameterNode().SetParameter("Segmentation", segmentation.GetID())
    statistics.getParameterNode().SetParameter("ScalarVolumeSegmentStatisticsPlugin.enabled", "False")
    statistics.getParameterNode().SetParameter("ClosedSurfaceSegmentStatisticsPlugin.enabled", "False")
    statistics.computeStatistics()
    stats = statistics.getStatistics()
    measured = float(stats[STATE["segment_id"], "LabelmapSegmentStatisticsPlugin.volume_mm3"])
    expected_mm3 = float(np.count_nonzero(STATE["mask"]) * np.prod(volume.GetSpacing()))
    check(math.isclose(measured, expected_mm3, rel_tol=1e-6), "Measured volume differs")
    for node in (loaded, labelmap, label_loaded):
        slicer.mrmlScene.RemoveNode(node)
    return {"segmentation_roundtrip_equal": True, "nifti_roundtrip_equal": True,
            "nifti_geometry_equal": True, "segment_statistics_mm3": measured,
            "files": [path.name, label_path.name]}


class ProbeHandler(BaseRequestHandler):
    def __init__(self, logMessage=None):
        self.logMessage = logMessage or (lambda *args: None)

    def canHandleRequest(self, method, uri, requestBody):
        return 1.0 if method == "POST" and uri == b"/probe" else 0.0

    def handleRequest(self, method, uri, requestBody):
        try:
            check(len(requestBody) <= 2048, "Request too large")
            request = json.loads(requestBody)
            check(isinstance(request, dict), "JSON object required")
            check(secrets.compare_digest(str(request.get("token", "")), TOKEN), "Unauthorized")
            operation = request.get("operation")
            parameters = request.get("parameters", {})
            check(isinstance(parameters, dict), "Parameters must be an object")
            functions = {"capabilities": capabilities, "open_fixture": open_fixture,
                         "open_dicom_fixture": open_dicom_fixture, "threshold": threshold,
                         "save_reload": save_reload}
            if os.environ.get("AIPACS_SLICER_PROBE_EXTENSION") == "1":
                functions["extension_cross_section"] = extension_cross_section
            if operation == "shutdown":
                qt.QTimer.singleShot(250, finish)
                result = {"shutdown_scheduled": True}
            else:
                check(operation in functions, "Unsupported operation")
                result = functions[operation](**parameters)
            response = {"ok": True, "operation": operation, "result": result}
        except Exception as exc:
            response = {"ok": False, "error_type": type(exc).__name__, "message": str(exc)}
        return b"application/json", json.dumps(response).encode("utf-8")


def finish():
    SERVER.stop()
    (ROOT / "connection.json").unlink(missing_ok=True)
    if "editor" in STATE:
        STATE["editor"].setMRMLScene(None)
        STATE["editor"].deleteLater()
    slicer.app.exit(0)


# Instantiate the server directly: the bundled WebServerLogic.start() binds all
# interfaces, whereas this probe must be loopback-only. No default handlers.
try:
    SERVER = SlicerHTTPServer(server_address=("127.0.0.1", 0), requestHandlers=[ProbeHandler()],
                              docroot=str(ROOT), logMessage=lambda *args: None, enableCORS=False)
    SERVER.start()
    (ROOT / "connection.json").write_text(json.dumps({"port": SERVER.server_port, "token": TOKEN}), encoding="utf-8")
    qt.QTimer.singleShot(120000, finish)
except Exception as exc:
    (ROOT / "startup_error.json").write_text(json.dumps({"type": type(exc).__name__, "message": str(exc)}), encoding="utf-8")
    slicer.app.exit(1)
