import vtkmodules.all as vtk
import numpy as np
from typing import List, Tuple, Optional
import math
import logging


logger = logging.getLogger(__name__)

class CurveMPRCore:
    """
    Core logic for Curved MPR.
    Handles spline generation, parallel transport frame, and resampling.
    """
    def __init__(self, vtk_image_data: vtk.vtkImageData, reference_normal=None):
        self.vtk_image_data = vtk_image_data
        self.reference_normal = reference_normal
        self.tube_mask = None
        self.control_points = []
        self.spline_points = []
        self.arc_lengths = []
        self.total_length = 0.0
        self.frames = [] # List of (origin, tangent, normal, binormal)
        
        # Extract direction matrix for patient space mapping
        self.direction_matrix = vtk.vtkMatrix4x4()
        self.direction_matrix.Identity()
        field_data = self.vtk_image_data.GetFieldData()
        if field_data:
            direction_array = field_data.GetArray("DirectionMatrix")
            if direction_array and direction_array.GetNumberOfTuples() == 16:
                for i in range(4):
                    for j in range(4):
                        self.direction_matrix.SetElement(i, j, direction_array.GetValue(i * 4 + j))
                # Adjust for X-flip
                for i in range(3):
                    self.direction_matrix.SetElement(i, 0, -self.direction_matrix.GetElement(i, 0))
                    
    def vtk_to_patient_space(self, point: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Convert VTK world coordinates to Patient Space (LPS)"""
        p = [point[0], point[1], point[2], 1.0]
        out = [0.0, 0.0, 0.0, 1.0]
        self.direction_matrix.MultiplyPoint(p, out)
        return (out[0], out[1], out[2])
        
    def add_control_point(self, point: Tuple[float, float, float]):
        self.control_points.append(np.array(point, dtype=np.float64))
        if len(self.control_points) >= 2:
            self._update_spline()
            
    def clear_points(self):
        self.control_points = []
        self.spline_points = []
        self.arc_lengths = []
        self.total_length = 0.0
        self.frames = []
        
    def _update_spline(self, samples_per_segment: int = 50):
        if len(self.control_points) < 2:
            return
            
        n = len(self.control_points)
        self.spline_points = []
        
        for i in range(n - 1):
            p0 = self.control_points[max(0, i - 1)]
            p1 = self.control_points[i]
            p2 = self.control_points[i + 1]
            p3 = self.control_points[min(n - 1, i + 2)]
            
            for j in range(samples_per_segment):
                t = j / samples_per_segment
                point = self._catmull_rom(p0, p1, p2, p3, t)
                self.spline_points.append(point)
                
        self.spline_points.append(self.control_points[-1].copy())
        self._compute_arc_lengths()
        self._generate_frames()
        
    def _catmull_rom(self, p0, p1, p2, p3, t, tension=0.5):
        t2 = t * t
        t3 = t2 * t
        return tension * (
            2 * p1 +
            (-p0 + p2) * t +
            (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
            (-p0 + 3 * p1 - 3 * p2 + p3) * t3
        )
        
    def _compute_arc_lengths(self):
        self.arc_lengths = [0.0]
        for i in range(1, len(self.spline_points)):
            dist = np.linalg.norm(self.spline_points[i] - self.spline_points[i-1])
            self.arc_lengths.append(self.arc_lengths[-1] + dist)
        self.total_length = self.arc_lengths[-1]
        
    def _generate_frames(self):
        if len(self.spline_points) < 2:
            return
            
        # Compute tangents
        tangents = []
        n = len(self.spline_points)
        for i in range(n):
            if i == 0:
                t = self.spline_points[1] - self.spline_points[0]
            elif i == n - 1:
                t = self.spline_points[-1] - self.spline_points[-2]
            else:
                t = self.spline_points[i+1] - self.spline_points[i-1]
            norm = np.linalg.norm(t)
            tangents.append(t / norm if norm > 1e-10 else np.array([0.0, 0.0, 1.0]))
            
        # Parallel transport
        self.frames = []
        T0 = tangents[0]
        
        # Initial normal (try to make it point "up" or "right" depending on tangent)
        if self.reference_normal is not None:
            N0 = np.asarray(self.reference_normal, dtype=float)
            N0 = N0 - np.dot(N0, T0) * T0
            if np.linalg.norm(N0) < 1e-8:
                axis = np.eye(3)[np.argmin(np.abs(T0))]
                N0 = np.cross(T0, axis)
        elif abs(T0[2]) < 0.9:
            N0 = np.cross(T0, np.array([0.0, 0.0, 1.0]))
        else:
            N0 = np.cross(T0, np.array([0.0, 1.0, 0.0]))
        N0 = N0 / np.linalg.norm(N0)
        B0 = np.cross(T0, N0)
        B0 = B0 / np.linalg.norm(B0)
        
        self.frames.append((self.spline_points[0], T0, N0, B0))
        
        for i in range(1, n):
            T1 = tangents[i]
            T0 = self.frames[i-1][1]
            N0 = self.frames[i-1][2]
            
            axis = np.cross(T0, T1)
            norm = np.linalg.norm(axis)
            
            if norm > 1e-10:
                axis = axis / norm
                angle = np.arccos(np.clip(np.dot(T0, T1), -1.0, 1.0))
                
                # Rodrigues rotation formula
                K = np.array([
                    [0, -axis[2], axis[1]],
                    [axis[2], 0, -axis[0]],
                    [-axis[1], axis[0], 0]
                ])
                R = np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * np.dot(K, K)
                N1 = np.dot(R, N0)
            else:
                N1 = N0
                
            N1 = N1 - np.dot(N1, T1) * T1
            N1 = N1 / np.linalg.norm(N1)
            B1 = np.cross(T1, N1)
            B1 = B1 / np.linalg.norm(B1)
            
            self.frames.append((self.spline_points[i], T1, N1, B1))

    def _sample_points(self, width, height, physical_width, z_offset=0.0, angle_degrees=0):
        """Interpolate once per column, retaining the legacy float32 probe grid."""
        from vtkmodules.util.numpy_support import numpy_to_vtk

        targets = np.arange(width) * (self.total_length / max(1, width - 1))
        arcs = np.asarray(self.arc_lengths)
        indices = np.clip(np.searchsorted(arcs, targets, side="left") - 1,
                          0, len(self.frames) - 2)
        span = arcs[indices + 1] - arcs[indices]
        fraction = np.divide(targets - arcs[indices], span,
                             out=np.zeros_like(targets), where=span > 0)[:, None]
        frames = np.asarray(self.frames)
        first, second = frames[indices], frames[indices + 1]
        origins = first[:, 0] + fraction * (second[:, 0] - first[:, 0])
        normals = first[:, 2] + fraction * (second[:, 2] - first[:, 2])
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        binormals = first[:, 3] + fraction * (second[:, 3] - first[:, 3])
        binormals /= np.linalg.norm(binormals, axis=1)[:, None]
        if angle_degrees:
            angle = np.deg2rad(angle_degrees)
            normals, binormals = (np.cos(angle) * normals + np.sin(angle) * binormals,
                                  -np.sin(angle) * normals + np.cos(angle) * binormals)
        offsets = np.arange(height) * (physical_width / max(1, height - 1)) - physical_width / 2
        coordinates = (origins[None, :, :] + offsets[:, None, None] * normals[None, :, :]
                       + z_offset * binormals[None, :, :])
        points = vtk.vtkPoints()
        points.SetData(numpy_to_vtk(coordinates.reshape(-1, 3).astype(np.float32), deep=True))
        return points

    def generate_path_volume(self, physical_width=40.0, cancelled=None):
        """Bound a circular swept tube; the crop is only its storage envelope."""
        import itertools
        self.tube_mask = None
        if not self.spline_points or self.vtk_image_data.GetPointData().GetScalars() is None:
            return None
        if cancelled is not None and cancelled.is_set():
            return None
        points = np.asarray(self.spline_points)
        lower, upper = points.min(axis=0) - physical_width / 2, points.max(axis=0) + physical_width / 2
        indices = []
        for corner in itertools.product(*zip(lower, upper)):
            index = [0.0] * 3
            self.vtk_image_data.TransformPhysicalPointToContinuousIndex(corner, index)
            indices.append(index)
        extent = self.vtk_image_data.GetExtent()
        indices = np.asarray(indices)
        voi = []
        for axis in range(3):
            low = max(extent[2 * axis], math.floor(indices[:, axis].min()))
            high = min(extent[2 * axis + 1], math.ceil(indices[:, axis].max()))
            if high < low:
                return None
            voi.extend((low, high))
        crop = vtk.vtkExtractVOI()
        crop.SetInputData(self.vtk_image_data)
        crop.SetVOI(*voi)
        crop.SetSampleRate(*(max(1, math.ceil((voi[i+1] - voi[i] + 1) / 256)) for i in (0, 2, 4)))
        crop.Update()
        if cancelled is not None and cancelled.is_set():
            return None
        output = vtk.vtkImageData()
        output.ShallowCopy(crop.GetOutput())
        # GPU binary-mask sampling requires a zero-based local texture grid.
        # ExtractVOI retains source extent offsets. Rebase only this private crop,
        # moving its origin to the same physical first voxel (including direction).
        # Scalar order, spacing, direction and every voxel's world position stay fixed.
        local_extent = output.GetExtent()
        first_voxel = [0.0, 0.0, 0.0]
        output.TransformIndexToPhysicalPoint(
            (local_extent[0], local_extent[2], local_extent[4]), first_voxel)
        dimensions = output.GetDimensions()
        output.SetExtent(0, dimensions[0]-1, 0, dimensions[1]-1, 0, dimensions[2]-1)
        output.SetOrigin(first_voxel)
        self.tube_mask = self._path_tube_mask(output, physical_width / 2, cancelled)
        if self.tube_mask is None:
            return None
        self._clear_outside_tube(output, self.tube_mask)
        return output

    @staticmethod
    def _clear_outside_tube(image, mask):
        from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
        source = vtk_to_numpy(image.GetPointData().GetScalars())
        values = source.astype(np.result_type(source.dtype, np.int16), copy=True)
        values[vtk_to_numpy(mask.GetPointData().GetScalars()) == 0] = -32768
        image.GetPointData().SetScalars(numpy_to_vtk(values, deep=True))

    @staticmethod
    def _mask_image(image, inside):
        from vtkmodules.util.numpy_support import numpy_to_vtk
        mask = vtk.vtkImageData()
        mask.CopyStructure(image)
        mask.GetPointData().SetScalars(numpy_to_vtk(
            np.ascontiguousarray(inside, dtype=np.uint8).ravel() * 255, deep=True))
        return mask

    def _path_tube_mask(self, image, radius, cancelled):
        """Native distance to line segments in a physical-mm orthonormal grid.

        Only the spline line cells contribute distances. The binary VRT mask excludes
        outside voxels independently of the selected transfer function.
        """
        from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
        direction = np.array([[image.GetDirectionMatrix().GetElement(i,j) for j in range(3)] for i in range(3)])
        if not np.allclose(direction.T @ direction, np.eye(3), atol=1e-5):
            raise ValueError('Tube masking requires orthonormal image directions')
        points = (np.asarray(self.spline_points) - image.GetOrigin()) @ direction
        dims, extent, spacing = image.GetDimensions(), image.GetExtent(), image.GetSpacing()
        model_dims = tuple(max(2, d) for d in dims)
        bounds = [(extent[2*i]*spacing[i], (extent[2*i]+model_dims[i]-1)*spacing[i]) for i in range(3)]
        vertices = vtk.vtkPoints()
        vertices.SetData(numpy_to_vtk(points, deep=True))
        lines = vtk.vtkCellArray()
        for i in range(len(points)-1):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i)
            lines.InsertCellPoint(i+1)
        poly = vtk.vtkPolyData()
        poly.SetPoints(vertices)
        poly.SetLines(lines)
        # VTK ComputeModelBounds scales by the longest model side, despite the
        # public setter documentation saying input diagonal. Include a voxel margin.
        longest_side = max(high-low for low, high in bounds)
        model = vtk.vtkImplicitModeller()
        model.SetInputData(poly)
        model.SetSampleDimensions(*model_dims)
        model.SetModelBounds(*(v for pair in bounds for v in pair))
        model.AdjustBoundsOff()
        model.CappingOff()
        model.SetProcessModeToPerCell()
        model.SetMaximumDistance(min(1.0, (radius + max(spacing)) / longest_side))
        model.SetOutputScalarTypeToFloat()
        if cancelled is not None:
            model.AddObserver('ProgressEvent', lambda *_: model.SetAbortExecute(cancelled.is_set()))
            if cancelled.is_set():
                return None
        model.Update()
        if cancelled is not None and cancelled.is_set():
            return None
        distances = vtk_to_numpy(model.GetOutput().GetPointData().GetScalars()).reshape(model_dims[::-1])
        inside = distances[:dims[2], :dims[1], :dims[0]] <= radius + 1e-5
        return self._mask_image(image, inside)

    def generate_straightened_volume(self, physical_width=40.0, step=None, cancelled=None):
        """Bounded local volume: X is arc length, Y/Z are transport N/B in mm.

        This is resampling around a user path, not vessel segmentation. Process
        one plane at a time so cancellation and peak coordinate memory stay bounded.
        """
        from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
        self.tube_mask = None
        if not self.frames or self.total_length <= 1e-6:
            return None
        if cancelled is not None and cancelled.is_set():
            return None
        if step is None:
            step = max(0.25, min(1.0, min(abs(s) for s in self.vtk_image_data.GetSpacing())))
        if not np.isfinite(physical_width) or not np.isfinite(step) or physical_width <= 0 or step <= 0:
            raise ValueError("Invalid straightened volume sampling size")
        width = min(512, max(2, math.ceil(self.total_length / step) + 1))
        cross = min(128, max(2, math.ceil(physical_width / step) + 1))
        spacing = (self.total_length / (width - 1), physical_width / (cross - 1),
                   physical_width / (cross - 1))
        source_scalars = self.vtk_image_data.GetPointData().GetScalars()
        if source_scalars is None:
            return None
        background = min(-1024.0, source_scalars.GetRange()[0])
        values = np.empty((cross, cross, width), dtype=np.float32)
        for k in range(cross):
            if cancelled is not None and cancelled.is_set():
                return None
            poly = vtk.vtkPolyData()
            poly.SetPoints(self._sample_points(width, cross, physical_width,
                                              -physical_width / 2 + k * spacing[2]))
            probe = vtk.vtkProbeFilter()
            probe.SetInputData(poly)
            probe.SetSourceData(self.vtk_image_data)
            probe.Update()
            data = probe.GetOutput().GetPointData()
            plane = vtk_to_numpy(data.GetScalars()).astype(np.float32, copy=True)
            valid = data.GetArray('vtkValidPointMask')
            if valid is not None:
                plane[vtk_to_numpy(valid) == 0] = background
            values[k] = plane.reshape(cross, width)
        output = vtk.vtkImageData()
        output.SetDimensions(width, cross, cross)
        output.SetSpacing(*spacing)
        output.SetOrigin(0, -physical_width / 2, -physical_width / 2)
        output.GetPointData().SetScalars(numpy_to_vtk(values.ravel(), deep=True))
        offsets = np.arange(cross) * spacing[1] - physical_width / 2
        circle = offsets[:, None]**2 + offsets[None, :]**2 <= (physical_width / 2)**2 + 1e-5
        self.tube_mask = self._mask_image(output, np.broadcast_to(circle[:, :, None], values.shape))
        self._clear_outside_tube(output, self.tube_mask)
        return output

    def generate_curved_image(self, width: int = 500, height: int = 500, physical_width: float = 100.0, angle_degrees=0) -> vtk.vtkImageData:
        """
        Generates the curved MPR image.
        width: number of pixels along the curve
        height: number of pixels perpendicular to the curve
        physical_width: physical size of the perpendicular cross-section in mm
        """
        if not self.frames:
            return None
            
        output = vtk.vtkImageData()
        output.SetDimensions(width, height, 1)
        
        # Spacing
        spacing_x = self.total_length / max(1, width - 1)
        spacing_y = physical_width / max(1, height - 1)
        output.SetSpacing(spacing_x, spacing_y, 1.0)
        output.SetOrigin(0.0, -physical_width / 2.0, 0.0)
        
        points = self._sample_points(width, height, physical_width, angle_degrees=angle_degrees)

        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        
        probe = vtk.vtkProbeFilter()
        probe.SetInputData(polydata)
        probe.SetSourceData(self.vtk_image_data)
        probe.Update()
        
        scalars = probe.GetOutput().GetPointData().GetScalars()
        if scalars:
            output.GetPointData().SetScalars(scalars)
        
        return output
        
    def generate_orthogonal_slice(self, arc_length: float, size: int = 200, physical_size: float = 100.0) -> vtk.vtkImageData:
        """
        Generates an orthogonal cross-section at a specific arc length.
        """
        if not bool(getattr(self, "_guard_logged_curve_mpr_orthogonal", False)):
            logger.warning(
                "[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH] feature=curve_mpr_generate_orthogonal_slice "
                "reason=legacy_curve_reslice_without_advanced_contract_adapter "
                "fallback_behavior=continue_legacy_curve_mpr_path action=warn_only"
            )
            self._guard_logged_curve_mpr_orthogonal = True
        if not self.frames:
            return None
            
        idx = 0
        while idx < len(self.arc_lengths) - 1 and self.arc_lengths[idx + 1] < arc_length:
            idx += 1
            
        if idx >= len(self.frames):
            idx = len(self.frames) - 1
            
        frame = self.frames[idx]
        origin, tangent, normal, binormal = frame
        
        reslice = vtk.vtkImageReslice()
        reslice.SetInputData(self.vtk_image_data)
        reslice.SetInterpolationModeToLinear()
        reslice.SetOutputDimensionality(2)
        
        spacing = physical_size / max(1, size - 1)
        reslice.SetOutputSpacing(spacing, spacing, 1.0)
        reslice.SetOutputExtent(0, size - 1, 0, size - 1, 0, 0)
        reslice.SetOutputOrigin(-physical_size / 2.0, -physical_size / 2.0, 0.0)
        
        transform = vtk.vtkTransform()
        matrix = vtk.vtkMatrix4x4()
        matrix.Identity()
        
        # X axis = normal
        matrix.SetElement(0, 0, normal[0])
        matrix.SetElement(1, 0, normal[1])
        matrix.SetElement(2, 0, normal[2])
        
        # Y axis = binormal
        matrix.SetElement(0, 1, binormal[0])
        matrix.SetElement(1, 1, binormal[1])
        matrix.SetElement(2, 1, binormal[2])
        
        # Z axis = tangent
        matrix.SetElement(0, 2, tangent[0])
        matrix.SetElement(1, 2, tangent[1])
        matrix.SetElement(2, 2, tangent[2])
        
        # Origin
        matrix.SetElement(0, 3, origin[0])
        matrix.SetElement(1, 3, origin[1])
        matrix.SetElement(2, 3, origin[2])
        
        reslice.SetResliceAxes(matrix)
        reslice.Update()
        
        return reslice.GetOutput()

    def generate_mip_image(self, width: int = 500, height: int = 500, physical_width: float = 100.0, slab_thickness: float = 20.0, num_samples: int = 10, cancelled=None, angle_degrees=0) -> vtk.vtkImageData:
        """
        Generates a Maximum Intensity Projection (MIP) curved MPR image.
        Samples multiple layers along the binormal and takes the maximum.
        """
        if not self.frames:
            return None
            
        output = vtk.vtkImageData()
        output.SetDimensions(width, height, 1)
        
        spacing_x = self.total_length / max(1, width - 1)
        spacing_y = physical_width / max(1, height - 1)
        output.SetSpacing(spacing_x, spacing_y, 1.0)
        output.SetOrigin(0.0, -physical_width / 2.0, 0.0)
        
        # We will accumulate the maximum scalars
        import numpy as np
        from vtkmodules.util.numpy_support import vtk_to_numpy, numpy_to_vtk
        
        max_scalars = None
        
        for k in range(num_samples):
            # Offset from -slab_thickness/2 to +slab_thickness/2
            if num_samples > 1:
                z_offset = -slab_thickness / 2.0 + k * (slab_thickness / (num_samples - 1))
            else:
                z_offset = 0.0
                
            if cancelled is not None and cancelled.is_set():
                return None
            points = self._sample_points(width, height, physical_width, z_offset, angle_degrees)

            polydata = vtk.vtkPolyData()
            polydata.SetPoints(points)
            
            probe = vtk.vtkProbeFilter()
            probe.SetInputData(polydata)
            probe.SetSourceData(self.vtk_image_data)
            probe.Update()
            
            scalars = probe.GetOutput().GetPointData().GetScalars()
            if scalars:
                np_scalars = vtk_to_numpy(scalars)
                if max_scalars is None:
                    max_scalars = np_scalars.copy()
                else:
                    max_scalars = np.maximum(max_scalars, np_scalars)
                    
        if max_scalars is not None:
            vtk_scalars = numpy_to_vtk(max_scalars, deep=True)
            vtk_scalars.SetName("Scalars")
            output.GetPointData().SetScalars(vtk_scalars)
            
        return output
