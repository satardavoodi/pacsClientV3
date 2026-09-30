"""Worker-only native processing. Inputs and outputs are detached from MRML."""
import json
import os
from pathlib import Path
import sys

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy

from .geometry import sample_path, path_frames

_dll_handles = []


def load_vmtk():
    """Use the versioned local bundle; never download dependencies at runtime."""
    roots = []
    for ancestor in Path(__file__).resolve().parents:
        roots.append(ancestor / "lumen_vmtk")
        if (ancestor / ".git").exists():
            roots.append(ancestor / "generated-files/lumen-vmtk/bundle")
            break
    for root in roots:
        manifest = root / "manifest.json"
        if not manifest.is_file():
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data["python"] != f"{sys.version_info.major}.{sys.version_info.minor}" or data["vtk"] != vtk.vtkVersion.GetVTKVersion():
            raise RuntimeError("VMTK bundle does not match this Slicer Python/VTK runtime")
        if str(root / "python") not in sys.path:
            sys.path.insert(0, str(root / "python"))
            sys.path.insert(0, str(root / "python/vmtk"))
            if hasattr(os, "add_dll_directory"):
                _dll_handles.append(os.add_dll_directory(str(root / "bin")))
        # Only the geometry wrapper and its dependencies are needed here.
        import vtkvmtkComputationalGeometryPython as geometry
        return geometry
    raise RuntimeError("VMTK is not installed for this runtime. Install the complete Advanced Analysis package.")


def check_cancel(cancel):
    if cancel.is_set():
        raise InterruptedError("Analysis cancelled")


def make_surface(mask, ijk_to_ras, cancel):
    check_cancel(cancel)
    if mask.ndim != 3 or not np.any(mask):
        raise ValueError("The selected segment is empty")
    # Padding closes segments that touch their image boundary.
    padded = np.pad(np.asarray(mask, dtype=np.uint8), 1)
    image = vtk.vtkImageData()
    image.SetDimensions(*padded.shape[::-1])
    image.GetPointData().SetScalars(numpy_to_vtk(padded.ravel(), deep=True))
    contour = vtk.vtkFlyingEdges3D()
    contour.SetInputData(image)
    contour.SetValue(0, 0.5)
    contour.Update()
    matrix = vtk.vtkMatrix4x4()
    affine = np.asarray(ijk_to_ras, dtype=float).copy()
    affine[:3, 3] -= affine[:3, :3] @ np.ones(3)
    for i in range(4):
        for j in range(4):
            matrix.SetElement(i, j, affine[i, j])
    transform = vtk.vtkTransform()
    transform.SetMatrix(matrix)
    apply = vtk.vtkTransformPolyDataFilter()
    apply.SetInputConnection(contour.GetOutputPort())
    apply.SetTransform(transform)
    apply.Update()
    check_cancel(cancel)
    surface = vtk.vtkPolyData()
    surface.DeepCopy(apply.GetOutput())
    return surface


def extract_path(surface, endpoints, cancel):
    geometry = load_vmtk()
    check_cancel(cancel)
    smooth = vtk.vtkWindowedSincPolyDataFilter()
    smooth.SetInputData(surface)
    smooth.SetNumberOfIterations(20)
    smooth.SetPassBand(0.1)
    smooth.BoundarySmoothingOff()
    smooth.FeatureEdgeSmoothingOff()
    smooth.NormalizeCoordinatesOn()
    smooth.Update()
    surface = smooth.GetOutput()
    if surface.GetNumberOfPoints() > 40000:
        reduce = vtk.vtkDecimatePro()
        reduce.SetInputData(surface)
        reduce.SetTargetReduction(1 - 40000 / surface.GetNumberOfPoints())
        reduce.PreserveTopologyOn()
        reduce.Update()
        surface = reduce.GetOutput()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(surface)
    clean.Update()
    surface = clean.GetOutput()
    locator = vtk.vtkPointLocator()
    locator.SetDataSet(surface)
    locator.BuildLocator()
    seeds = [locator.FindClosestPoint(point) for point in endpoints]
    if len(seeds) != 2 or seeds[0] == seeds[1]:
        raise ValueError("Place distinct start and destination points near the ends of one connected lumen")
    source, target = vtk.vtkIdList(), vtk.vtkIdList()
    source.InsertNextId(seeds[0])
    target.InsertNextId(seeds[1])
    centerline = geometry.vtkvmtkPolyDataCenterlines()
    centerline.SetInputData(surface)
    centerline.SetSourceSeedIds(source)
    centerline.SetTargetSeedIds(target)
    centerline.SetRadiusArrayName("MaximumInscribedSphereRadius")
    centerline.SetCostFunction("1/R")
    centerline.SetAppendEndPointsToCenterlines(1)
    centerline.SetCenterlineResampling(1)
    centerline.SetResamplingStepLength(0.75)
    centerline.AddObserver(vtk.vtkCommand.ProgressEvent,
                           lambda caller, event: caller.SetAbortExecute(cancel.is_set()))
    centerline.Update()
    check_cancel(cancel)
    result = centerline.GetOutput()
    if result.GetNumberOfLines() != 1:
        raise ValueError("No single connected route was found. Review the segment and endpoints.")
    ids = result.GetCell(0).GetPointIds()
    points = np.array([result.GetPoint(ids.GetId(i)) for i in range(ids.GetNumberOfIds())])
    if np.linalg.norm(points[-1] - endpoints[0]) < np.linalg.norm(points[0] - endpoints[0]):
        points = points[::-1]
    snapped = np.array([surface.GetPoint(seed) for seed in seeds])
    tolerance = max(1.5, surface.GetLength() * .01)
    if (len(points) < 2 or np.linalg.norm(points[0] - snapped[0]) > tolerance
            or np.linalg.norm(points[-1] - snapped[1]) > tolerance):
        raise ValueError("Centerline did not reach both endpoints. Review the lumen connectivity and endpoint placement.")
    return sample_path(points)[0]


def cross_section_area(surface, point, tangent, up):
    """Area of the nearest closed contour; open/ambiguous sections are invalid."""
    plane = vtk.vtkPlane()
    plane.SetOrigin(point)
    plane.SetNormal(tangent)
    cut = vtk.vtkCutter()
    cut.SetInputData(surface)
    cut.SetCutFunction(plane)
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(cut.GetOutputPort())
    strip = vtk.vtkStripper()
    strip.SetInputConnection(clean.GetOutputPort())
    strip.Update()
    contours = strip.GetOutput()
    candidates = []
    right = np.cross(tangent, up)
    for index in range(contours.GetNumberOfCells()):
        cell = contours.GetCell(index)
        xyz = np.array([contours.GetPoint(cell.GetPointId(i)) for i in range(cell.GetNumberOfPoints())])
        if len(xyz) < 4 or np.linalg.norm(xyz[0] - xyz[-1]) > 1e-3:
            continue
        local = xyz - point
        x, y = local @ right, local @ up
        # Only a contour containing the centerline point can measure this lumen.
        inside = False
        for i in range(len(x) - 1):
            if (y[i] > 0) != (y[i + 1] > 0):
                if x[i] + (x[i + 1] - x[i]) * (-y[i]) / (y[i + 1] - y[i]) > 0:
                    inside = not inside
        if inside:
            area = abs(np.dot(x[:-1], y[1:]) - np.dot(y[:-1], x[1:])) * 0.5
            candidates.append(area)
    return candidates[0] if len(candidates) == 1 else float("nan")


def analyze(mask, affine, endpoints, manual_points, cancel):
    surface = make_surface(mask, affine, cancel)
    points = sample_path(manual_points)[0] if manual_points is not None else extract_path(surface, endpoints, cancel)
    points, distances = sample_path(points)
    ijk = (np.column_stack([points, np.ones(len(points))]) @ np.linalg.inv(affine).T)[:, :3]
    indices = np.rint(ijk).astype(int)[:, ::-1]
    in_bounds = np.all((indices >= 0) & (indices < np.array(mask.shape)), axis=1)
    contained = np.zeros(len(points), dtype=bool)
    valid_indices = indices[in_bounds]
    contained[in_bounds] = mask[tuple(valid_indices.T)] != 0
    if not contained[1:-1].all():
        raise ValueError("The route leaves the selected lumen. Review its segment and control points.")
    tangents, ups = path_frames(points)
    areas = []
    for point, tangent, up in zip(points, tangents, ups):
        check_cancel(cancel)
        areas.append(cross_section_area(surface, point, tangent, up))
    areas = np.asarray(areas)
    return {"surface": surface, "points": points, "distance": distances,
            "tangents": tangents, "ups": ups, "area": areas,
            "diameter": np.sqrt(4 * areas / np.pi)}
