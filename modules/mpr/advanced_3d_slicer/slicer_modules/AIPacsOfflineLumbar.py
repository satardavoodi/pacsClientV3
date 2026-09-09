"""Slicer extension for locally bundled lumbar MR anatomy inference."""
import os
from pathlib import Path
import queue
import sys
import threading
import time

import numpy as np
import qt
import slicer
import vtk
from slicer.ScriptedLoadableModule import ScriptedLoadableModule, ScriptedLoadableModuleWidget


class AIPacsOfflineLumbar(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        parent.title = "AI-PACS Offline Lumbar"
        parent.categories = ["Segmentation"]
        parent.dependencies = ["Segmentations"]
        parent.contributors = ["AI-PACS"]
        parent.helpText = "Offline MR vertebral anatomy. Requires the bundled CPU model. Not a diagnosis."


def bundle_root():
    configured = os.environ.get("AIPACS_OFFLINE_LUMBAR_ROOT")
    return Path(configured) if configured else Path(slicer.app.slicerHome) / "offline_lumbar"


def _segmentation_data(labels, affine, segments):
    """Construct independent VTK data in the worker; attach it to MRML only later."""
    from vtk.util.numpy_support import numpy_to_vtk
    representation = slicer.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName()
    segmentation = slicer.vtkSegmentation()
    segmentation.SetSourceRepresentationName(representation)
    matrix = vtk.vtkMatrix4x4()
    for row in range(4):
        for column in range(4):
            matrix.SetElement(row, column, float(affine[row, column]))
    for item in segments:
        indices = np.where(labels == item["label"])
        if not len(indices[0]):
            continue
        k0, j0, i0 = [int(axis.min()) for axis in indices]
        k1, j1, i1 = [int(axis.max()) for axis in indices]
        mask = np.ascontiguousarray(labels[k0:k1+1, j0:j1+1, i0:i1+1] == item["label"], dtype=np.uint8)
        image = slicer.vtkOrientedImageData()
        image.SetExtent(i0, i1, j0, j1, k0, k1)
        image.SetImageToWorldMatrix(matrix)
        image.GetPointData().SetScalars(numpy_to_vtk(mask.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        segment = slicer.vtkSegment()
        segment.SetName(item["name"])
        segment.SetColor((item["label"] * 0.37) % 0.8 + 0.2, 0.6, 0.9)
        segment.AddRepresentation(representation, image)
        segmentation.AddSegment(segment, item["name"])
    return segmentation


class AIPacsOfflineLumbarLogic:
    """Asynchronous function surface usable by the UI or a future named-tool adapter."""
    def __init__(self):
        self._thread = None
        self._cancel = threading.Event()
        self._results = queue.Queue()
        self._timer = qt.QTimer()
        self._timer.setInterval(100)
        self._timer.connect("timeout()", self._poll)
        self._source = None
        self._callback = None
        self._scene_observer = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.StartCloseEvent, lambda *_: self.cancel())

    @property
    def running(self):
        return self._thread is not None

    def start(self, volume, callback=None):
        if self.running:
            raise RuntimeError("An offline analysis is already active")
        if not volume or not volume.IsA("vtkMRMLScalarVolumeNode") or volume.GetImageData() is None:
            raise ValueError("Select a scalar MR volume")
        if volume.GetParentTransformNode() is not None:
            raise ValueError("Use an untransformed MR source volume")
        if volume.GetAttribute("DICOM.Modality") not in (None, "", "MR"):
            raise ValueError("This model supports MR images only")
        # Snapshot memory and geometry while MRML is owned by this thread.
        source_array = slicer.util.arrayFromVolume(volume)
        if source_array.ndim != 3 or source_array.size > 256 * 1024 * 1024:
            raise ValueError("Unsupported input volume dimensions")
        array = source_array.copy()
        matrix = vtk.vtkMatrix4x4()
        volume.GetIJKToRASMatrix(matrix)
        affine = slicer.util.arrayFromVTKMatrix(matrix).copy()
        self._source = volume
        self._source_mtime = volume.GetImageData().GetMTime()
        self._affine = affine
        self._callback = callback
        self._cancel.clear()
        root = bundle_root().resolve()
        work = Path(slicer.app.temporaryPath) / "aipacs-offline-lumbar"

        def execute():
            try:
                # Model and filesystem work happen outside the GUI thread.
                app = str(root / "app")
                if app not in sys.path:
                    sys.path.append(app)
                from offline_lumbar.service import run_snapshot
                result, labels = run_snapshot(root, work, array, affine, cancel=self._cancel)
                data = _segmentation_data(labels, affine, result["segments"])
                self._results.put((result, data, None))
            except Exception as exc:
                self._results.put((None, None, type(exc).__name__))
        self._thread = threading.Thread(target=execute, name="OfflineLumbar", daemon=True)
        self._thread.start()
        self._timer.start()
        return {"status": "running", "task": "vertebrae_mr"}

    def cancel(self):
        self._cancel.set()

    def cleanup(self):
        self.cancel()
        self._timer.stop()
        if self._scene_observer is not None:
            slicer.mrmlScene.RemoveObserver(self._scene_observer)
            self._scene_observer = None
        self._callback = None

    def _poll(self):
        if self._thread is not None:
            # PythonQt can hold the GIL between events. Briefly yield as in
            # Slicer's SimpleFilters pattern so worker I/O can resume. No event
            # pumping, filesystem access or inference occurs in this callback.
            time.sleep(0.001)
        try:
            result, data, error = self._results.get_nowait()
        except queue.Empty:
            return
        self._timer.stop()
        self._thread = None
        try:
            if self._cancel.is_set():
                result = {"status": "cancelled"}
            elif error:
                result = {"status": "failed", "error_type": error,
                          "message": "Offline analysis failed. Check installed bundle, input, and available memory."}
            else:
                source = self._source
                if (source.GetScene() != slicer.mrmlScene or
                        source.GetImageData().GetMTime() != self._source_mtime or
                        source.GetParentTransformNode() is not None):
                    raise RuntimeError("Source changed while analysis was running")
                matrix = vtk.vtkMatrix4x4()
                source.GetIJKToRASMatrix(matrix)
                if not np.allclose(slicer.util.arrayFromVTKMatrix(matrix), self._affine):
                    raise RuntimeError("Source geometry changed while analysis was running")
                node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Offline MR vertebral anatomy")
                node.SetAndObserveSegmentation(data)
                node.CreateDefaultDisplayNodes()
                node.SetReferenceImageGeometryParameterFromVolumeNode(source)
                node.SetAttribute("AI-PACS.ClinicalValidation", "not_established")
                node.SetAttribute("AI-PACS.ModelTask", "vertebrae_mr")
                result["segmentation_node_id"] = node.GetID()
        except Exception:
            result = {"status": "failed", "message": "Source changed; result was not attached to the scene"}
        if self._callback:
            self._callback(result)


class AIPacsOfflineLumbarWidget(ScriptedLoadableModuleWidget):
    def setup(self):
        super().setup()
        self.logic = AIPacsOfflineLumbarLogic()
        self.selector = slicer.qMRMLNodeComboBox()
        self.selector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.selector.addEnabled = False
        self.selector.removeEnabled = False
        self.selector.setMRMLScene(slicer.mrmlScene)
        self.layout.addWidget(qt.QLabel("Source MR volume"))
        self.layout.addWidget(self.selector)
        self.confirm = qt.QCheckBox("I confirm this is an MR volume; output is anatomy assistance, not diagnosis")
        self.layout.addWidget(self.confirm)
        self.apply = qt.QPushButton("Segment vertebrae offline (CPU)")
        self.cancelButton = qt.QPushButton("Cancel analysis")
        self.status = qt.QLabel("CPU inference may take several minutes. No first-run download.")
        self.status.wordWrap = True
        self.layout.addWidget(self.apply)
        self.layout.addWidget(self.cancelButton)
        self.layout.addWidget(self.status)
        self.layout.addStretch(1)
        self.apply.connect("clicked()", self.onApply)
        self.cancelButton.connect("clicked()", self.logic.cancel)

    def onApply(self):
        if not self.confirm.checked:
            self.status.text = "Confirm the input modality before starting."
            return
        try:
            self.logic.start(self.selector.currentNode(), self.onComplete)
            self.apply.enabled = False
            self.status.text = "Running local CPU model. You can continue viewing or cancel."
        except Exception as exc:
            self.status.text = str(exc)

    def onComplete(self, result):
        self.apply.enabled = True
        self.status.text = result.get("message", result["status"])

    def cleanup(self):
        self.logic.cleanup()
