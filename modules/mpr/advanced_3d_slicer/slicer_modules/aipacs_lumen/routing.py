"""Allowlisted post-load navigation, independent of workstation Qt imports."""

MODULES = {"vascular": "AIPacsVascular", "bronchoscopy": "AIPacsBronchoscopy"}


def load_exact_volume(directory, series_uid):
    """No first-patient/first-series fallback for quantitative workspaces."""
    import slicer
    from DICOMLib import DICOMUtils
    if not series_uid:
        raise ValueError("Select a series with an exact Series Instance UID")
    with DICOMUtils.TemporaryDICOMDatabase() as database:
        DICOMUtils.importDicom(directory, database)
        available = [series for patient in database.patients()
                     for study in database.studiesForPatient(patient) for series in database.seriesForStudy(study)]
        if series_uid not in available:
            raise ValueError("The selected series is not present in the source folder")
        study_uid = database.studyForSeries(series_uid)
        ids = DICOMUtils.loadSeriesByUID([series_uid])
    nodes = [slicer.mrmlScene.GetNodeByID(node_id) for node_id in ids]
    volumes = [node for node in nodes if node and node.IsA("vtkMRMLScalarVolumeNode")]
    if len(volumes) != 1:
        raise ValueError("The selected series must resolve to one scalar volume")
    volume = volumes[0]
    volume.SetAttribute("AIPacsLumen.SeriesInstanceUID", series_uid)
    volume.SetAttribute("AIPacsLumen.StudyInstanceUID", study_uid)
    return volume


def validate(workflow):
    if workflow and workflow not in MODULES:
        raise ValueError("Unknown Advanced Analysis workflow")
    return workflow


def activate(workflow, volume):
    import slicer
    validate(workflow)
    if not workflow:
        return
    if volume is None or not volume.IsA("vtkMRMLScalarVolumeNode"):
        raise ValueError("This workflow requires one scalar image volume")
    name = MODULES[workflow]
    module = getattr(slicer.modules, name.lower(), None)
    if module is None:
        raise RuntimeError("The selected analysis workspace is missing from this runtime")
    widget = module.widgetRepresentation().self()
    slicer.util.selectModule(name)
    widget.setSource(volume)
