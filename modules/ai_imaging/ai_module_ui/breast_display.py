"""Separate parenchymal labels and native calcium overlays in the Breast viewer."""
from copy import copy
import math


def parenchymal_display_items(items):
    """Filter legacy AI calcium labels without deleting boxes or editing raw CSVs.

    Human corrections are authoritative. A calcium-only legacy label becomes
    unclassified, never an invented Mass, distortion, or normal finding.
    """
    result = []
    for original in items or []:
        item = copy(original)
        if (item.get('source_kind') or 'ai') == 'ai':
            labels = item.get('classification', [])
            if isinstance(labels, str):
                labels = [labels]
            item['classification'] = [x for x in (labels or [])
                                      if 'calcif' not in str(x).casefold()]
        result.append(item)
    return result


def calcium_record_for_view(result, viewer):
    """Accept only the dedicated native-point branch, not legacy classifier data."""
    if (result.get('status') != 'success'
            or result.get('coordinate_space') != 'native_source_pixels_xy'):
        raise ValueError('The separate calcium result is unavailable or unsupported.')
    instances = viewer.metadata.get('instances', [])
    if len(instances) != 1:
        raise ValueError('A single source instance is required.')
    sop = instances[0].get('sop_uid') or instances[0].get('sop_instance_uid')
    records = [r for r in result.get('files', []) if r.get('sop_uid') == sop]
    if len(records) != 1:
        raise ValueError('Missing or duplicate calcium image result.')
    validated_calcium_points(records[0], result.get('study_id'), viewer)
    return records[0]


def validated_calcium_points(record, study_id, viewer):
    """Bind native XY to exactly one displayed source; no resize/UID guessing."""
    metadata = viewer.metadata
    instances = metadata.get('instances', [])
    if len(instances) != 1:
        raise ValueError('Calcium display requires one verified source instance.')
    sop = instances[0].get('sop_uid') or instances[0].get('sop_instance_uid')
    if (not study_id or str(study_id) != str(viewer.metadata_fixed.get('study_uid', ''))
            or not sop or str(record.get('sop_uid', '')) != str(sop)
            or not record.get('series_uid')
            or str(record['series_uid']) != str(metadata.get('series', {}).get('series_uid', ''))):
        raise ValueError('Calcium result does not belong to the displayed source.')
    nx, ny, nz = viewer.vtk_image_data.GetDimensions()
    if nz != 1 or record.get('shape_hw') != [ny, nx]:
        raise ValueError('Calcium source geometry differs from the displayed image.')
    points = record.get('points_xy')
    if not isinstance(points, list) or len(points) > 200000:
        raise ValueError('Invalid calcium point collection.')
    result = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError('Invalid calcium coordinate.')
        x, y = map(float, point)
        if not math.isfinite(x) or not math.isfinite(y) or not (0 <= x < nx and 0 <= y < ny):
            raise ValueError('Calcium coordinate is outside its source.')
        result.append((x, y))
    return result


class CalciumDisplayLayer:
    """Own only calcium actors; tissue box/segmentation ownership stays unchanged."""

    def __init__(self):
        self.visible = True
        self.available = False
        self.actors = []
        self.renderer = None

    def set_visible(self, visible):
        self.visible = bool(visible)
        for actor in self.actors:
            actor.SetVisibility(int(self.visible))

    def clear(self):
        if self.renderer is not None:
            for actor in self.actors:
                self.renderer.RemoveActor(actor)
        self.actors = []
        self.renderer = None
        self.available = False

    def apply_result(self, record, study_id, viewer):
        points = validated_calcium_points(record, study_id, viewer)
        import vtk
        self.clear()
        self.renderer = viewer.renderer
        if self.renderer is None:
            raise ValueError('Calcium renderer is unavailable.')
        if points:
            vertices, vtk_points = vtk.vtkCellArray(), vtk.vtkPoints()
            for x, y in points:
                index = vtk_points.InsertNextPoint(*viewer.ijk_to_world(x, y, None, y_flip=True))
                vertices.InsertNextCell(1)
                vertices.InsertCellPoint(index)
            poly = vtk.vtkPolyData()
            poly.SetPoints(vtk_points)
            poly.SetVerts(vertices)
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(poly)
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(1.0, .8, 0.0)
            actor.GetProperty().SetPointSize(4)
            actor.GetProperty().LightingOff()
            actor.SetPickable(False)
            actor.SetVisibility(int(self.visible))
            self.renderer.AddActor(actor)
            self.actors.append(actor)
        self.available = True
