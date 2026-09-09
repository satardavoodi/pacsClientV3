"""Fixed brain measurement operation in a dedicated headless Slicer process.

Never run in an interactive patient scene. No server or arbitrary-code endpoint.
"""
import json
import os
from pathlib import Path


def measure(directory):
    import numpy as np
    import slicer
    import vtk
    import SegmentStatistics
    if slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLVolumeNode"):
        raise RuntimeError("An empty analysis scene is required")
    label_names = json.loads((directory / "label_names.json").read_text(encoding="utf-8"))
    volume = slicer.util.loadVolume(str(directory / "resampled.nii.gz"))
    labels = slicer.util.loadLabelVolume(str(directory / "labels.nii.gz"))
    if not volume or not labels:
        raise RuntimeError("Image loading failed")
    volume.SetName("Brain T1")
    labels.SetName("Brain labels")
    array = slicer.util.arrayFromVolume(labels)
    if not np.isfinite(array).all() or np.any(array != np.floor(array)):
        raise RuntimeError("Segmentation must contain finite integer labels")
    unique = [int(value) for value in np.unique(array) if value != 0]
    if not unique or any(str(value) not in label_names for value in unique):
        raise RuntimeError("Unexpected or empty segmentation")
    matrices = []
    for node in (volume, labels):
        matrix = vtk.vtkMatrix4x4()
        node.GetIJKToRASMatrix(matrix)
        matrices.append(np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)]))
    if (volume.GetImageData().GetDimensions() != labels.GetImageData().GetDimensions()
            or not np.allclose(matrices[0], matrices[1], atol=1e-4)):
        raise RuntimeError("Resampled source and label geometry disagree")
    voxel_volume = abs(float(np.linalg.det(matrices[1][:3, :3])))
    if not np.isfinite(voxel_volume) or voxel_volume <= 0:
        raise RuntimeError("Invalid voxel volume")
    colors = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLColorTableNode", "Brain label identities")
    colors.SetTypeToUser()
    colors.SetNumberOfColors(max(unique) + 1)
    colors.SetNamesInitialised(True)
    colors.SetColor(0, "Background", 0, 0, 0, 0)
    for value in unique:
        colors.SetColor(value, str(value), ((value * 31) % 191 + 64) / 255,
                        ((value * 67) % 191 + 64) / 255, ((value * 97) % 191 + 64) / 255, 1)
    labels.GetDisplayNode().SetAndObserveColorNodeID(colors.GetID())
    segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Brain parcellation")
    segmentation.CreateDefaultDisplayNodes()
    segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    if not slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labels, segmentation):
        raise RuntimeError("Segmentation import failed")
    statistics = SegmentStatistics.SegmentStatisticsLogic()
    parameters = statistics.getParameterNode()
    parameters.SetParameter("Segmentation", segmentation.GetID())
    parameters.SetParameter("ScalarVolumeSegmentStatisticsPlugin.enabled", "False")
    parameters.SetParameter("ClosedSurfaceSegmentStatisticsPlugin.enabled", "False")
    statistics.computeStatistics()
    stats = statistics.getStatistics()
    rows = []
    for segment_id in stats["SegmentIDs"]:
        segment = segmentation.GetSegmentation().GetSegment(segment_id)
        label = int(segment.GetName())
        measured = float(stats[segment_id, "LabelmapSegmentStatisticsPlugin.volume_mm3"])
        expected = int(np.count_nonzero(array == label)) * voxel_volume
        if not np.isclose(measured, expected, rtol=1e-5, atol=1e-5):
            raise RuntimeError("Independent voxel volume verification failed")
        segment.SetName(label_names[str(label)])
        rows.append({"label": label, "structure": label_names[str(label)], "volume_mm3": measured,
                     "volume_cm3": measured / 1000, "method": "Slicer binary labelmap"})
    segmentation.GetDisplayNode().SetOpacity2DFill(0.2)
    slicer.util.setSliceViewerLayers(background=volume)
    if (directory / "flair_registered.nii.gz").is_file():
        flair = slicer.util.loadVolume(str(directory / "flair_registered.nii.gz"))
        flair.SetName("FLAIR rigid registration - review required")
    if not slicer.util.saveNode(segmentation, str(directory / "brain.seg.nrrd")):
        raise RuntimeError("Segmentation export failed")
    slicer.mrmlScene.RemoveNode(labels)
    if not slicer.util.saveScene(str(directory / "brain_review.mrb")):
        raise RuntimeError("Review scene export failed")
    return {"status": "succeeded", "job_id": directory.name, "rows": rows,
            "slicer_revision": str(slicer.app.repositoryRevision), "voxel_volume_mm3": voxel_volume,
            "clinical_validation": "not_established"}


def main():
    import slicer
    directory = Path(os.environ["AIPACS_BRAIN_JOB"]).resolve()
    try:
        result = measure(directory)
        code = 0
    except Exception as exc:
        result = {"status": "failed", "error_type": type(exc).__name__, "job_id": directory.name}
        code = 1
    (directory / "slicer_result.json").write_text(json.dumps(result), encoding="utf-8")
    slicer.app.exit(code)


if __name__ == "__main__":
    import qt
    qt.QTimer.singleShot(0, main)
