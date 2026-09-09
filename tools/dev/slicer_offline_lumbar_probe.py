"""Slicer-side synthetic qualification of the offline extension; run only in isolation."""
import json
import os
from pathlib import Path
import traceback
import faulthandler

import numpy as np
import qt
import slicer

ROOT = Path(os.environ["AIPACS_LUMBAR_PROBE_DIR"])
RESULT = {"scope": "synthetic only", "passed": False}
TRACE = (ROOT / "threads.log").open("w", encoding="utf-8")
faulthandler.dump_traceback_later(45, repeat=True, file=TRACE)


def progress(stage):
    (ROOT / "progress.json").write_text(json.dumps({"stage": stage}), encoding="utf-8")


def finish(result):
    faulthandler.cancel_dump_traceback_later()
    RESULT.update(result)
    if "logic" in globals():
        logic.cleanup()
    (ROOT / "result.json").write_text(json.dumps(RESULT, indent=2), encoding="utf-8")
    slicer.app.exit(0 if RESULT["passed"] else 1)


try:
    progress("import extension")
    from AIPacsOfflineLumbar import _segmentation_data, AIPacsOfflineLumbarLogic
    if slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLVolumeNode"):
        raise RuntimeError("An empty isolated scene is required")
    # Test nonzero image extents and a nontrivial affine without model uncertainty.
    labels = np.zeros((12, 16, 20), dtype=np.uint8)
    labels[3:7, 5:11, 4:13] = 2
    affine = np.array([[0, -0.9, 0, 25], [0.8, 0, 0, -35], [0, 0, 2.5, 14], [0, 0, 0, 1]])
    volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "SYNTHETIC_OFFLINE_GEOMETRY")
    import vtk
    matrix = vtk.vtkMatrix4x4()
    for i in range(4):
        for j in range(4):
            matrix.SetElement(i, j, affine[i, j])
    volume.SetIJKToRASMatrix(matrix)
    slicer.util.updateVolumeFromArray(volume, labels.astype(np.int16))
    data = _segmentation_data(labels, affine, [{"label": 2, "name": "vertebrae_L5"}])
    segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
    segmentation.SetAndObserveSegmentation(data)
    segmentation.CreateDefaultDisplayNodes()
    segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    recovered = slicer.util.arrayFromSegmentBinaryLabelmap(segmentation, "vertebrae_L5", volume)
    if not np.array_equal(recovered > 0, labels > 0):
        raise RuntimeError("Cropped segmentation geometry does not match source")
    RESULT["cropped_rotated_geometry_equal"] = True
    progress("initialize GUI")
    widget = slicer.modules.aipacsofflinelumbar.widgetRepresentation().self()
    if not all(hasattr(widget, name) for name in ("logic", "selector", "apply", "cancelButton", "status")):
        raise RuntimeError("Offline module GUI did not initialize")
    RESULT["gui_initialized"] = True
    progress("reject changed source")
    # A completed result must not be attached after its source data changes.
    stale_logic = AIPacsOfflineLumbarLogic()
    stale_logic._source = volume
    stale_logic._source_mtime = volume.GetImageData().GetMTime()
    stale_logic._affine = affine.copy()
    rejected = []
    stale_logic._callback = rejected.append
    volume.GetImageData().Modified()
    before = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSegmentationNode")
    stale_logic._results.put(({"status": "succeeded"}, data, None))
    stale_logic._poll()
    if rejected[0]["status"] != "failed" or before != slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSegmentationNode"):
        raise RuntimeError("Stale source result was not rejected")
    stale_logic.cleanup()
    RESULT["stale_source_result_rejected"] = True
    progress("start model")
    if os.environ.get("AIPACS_LUMBAR_PROBE_INFERENCE") != "1":
        finish({"passed": True, "model_inference_executed": False})
    else:
        # Numerical smoke test only: the model's anatomy accuracy is not assessed.
        source = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "SYNTHETIC_MR_INPUT")
        k, j, i = np.indices((32, 48, 48))
        image = (100 * np.exp(-((i - 24)**2 + (j - 24)**2 + (k - 16)**2) / 100)).astype(np.float32)
        source.SetSpacing(1.5, 1.5, 2.5)
        slicer.util.updateVolumeFromArray(source, image)
        logic = AIPacsOfflineLumbarLogic()
        def completed(result):
            RESULT["inference"] = result
            finish({"passed": result.get("status") == "succeeded", "model_inference_executed": True})
        logic.start(source, completed)
        progress("model running")
        qt.QTimer.singleShot(900000, lambda: finish({"passed": False, "error": "Probe timed out"}))
except Exception:
    # Synthetic-only trace; never use this diagnostic probe with patient data.
    finish({"passed": False, "error": traceback.format_exc()})
