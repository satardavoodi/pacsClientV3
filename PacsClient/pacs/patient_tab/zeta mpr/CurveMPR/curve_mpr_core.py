import vtkmodules.all as vtk
import numpy as np
from typing import List, Tuple, Optional
import math

class CurveMPRCore:
    """
    Core logic for Curved MPR.
    Handles spline generation, parallel transport frame, and resampling.
    """
    def __init__(self, vtk_image_data: vtk.vtkImageData):
        self.vtk_image_data = vtk_image_data
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
        if abs(T0[2]) < 0.9:
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

    def generate_curved_image(self, width: int = 500, height: int = 500, physical_width: float = 100.0) -> vtk.vtkImageData:
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
        
        points = vtk.vtkPoints()
        for j in range(height):
            y_offset = (j * spacing_y) - (physical_width / 2.0)
            for i in range(width):
                target_s = i * spacing_x
                idx = 0
                while idx < len(self.arc_lengths) - 1 and self.arc_lengths[idx + 1] < target_s:
                    idx += 1
                    
                if idx >= len(self.frames) - 1:
                    frame = self.frames[-1]
                else:
                    s0 = self.arc_lengths[idx]
                    s1 = self.arc_lengths[idx + 1]
                    t = (target_s - s0) / (s1 - s0) if s1 > s0 else 0.0
                    
                    f0 = self.frames[idx]
                    f1 = self.frames[idx + 1]
                    
                    origin = f0[0] + t * (f1[0] - f0[0])
                    normal = f0[2] + t * (f1[2] - f0[2])
                    normal = normal / np.linalg.norm(normal)
                    frame = (origin, None, normal, None)
                    
                p = frame[0] + y_offset * frame[2]
                points.InsertNextPoint(p[0], p[1], p[2])
                
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

    def generate_mip_image(self, width: int = 500, height: int = 500, physical_width: float = 100.0, slab_thickness: float = 20.0, num_samples: int = 10) -> vtk.vtkImageData:
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
                
            points = vtk.vtkPoints()
            for j in range(height):
                y_offset = (j * spacing_y) - (physical_width / 2.0)
                for i in range(width):
                    target_s = i * spacing_x
                    idx = 0
                    while idx < len(self.arc_lengths) - 1 and self.arc_lengths[idx + 1] < target_s:
                        idx += 1
                        
                    if idx >= len(self.frames) - 1:
                        frame = self.frames[-1]
                    else:
                        s0 = self.arc_lengths[idx]
                        s1 = self.arc_lengths[idx + 1]
                        t = (target_s - s0) / (s1 - s0) if s1 > s0 else 0.0
                        
                        f0 = self.frames[idx]
                        f1 = self.frames[idx + 1]
                        
                        origin = f0[0] + t * (f1[0] - f0[0])
                        normal = f0[2] + t * (f1[2] - f0[2])
                        normal = normal / np.linalg.norm(normal)
                        binormal = f0[3] + t * (f1[3] - f0[3])
                        binormal = binormal / np.linalg.norm(binormal)
                        frame = (origin, None, normal, binormal)
                        
                    # Point is origin + y_offset * normal + z_offset * binormal
                    p = frame[0] + y_offset * frame[2] + z_offset * frame[3]
                    points.InsertNextPoint(p[0], p[1], p[2])
                    
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
