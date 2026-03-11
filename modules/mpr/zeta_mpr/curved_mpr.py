"""
True Curved Planar Reformation (Curved MPR) with Mandibular Unfolding
======================================================================

This module implements proper Curved Planar Reformation for medical imaging
including specialized support for CBCT Mandibular Unfolding.

Unlike simple oblique slicing, this creates a true long-axis reconstruction
by computing planes strictly perpendicular to the path tangent.

Key Components:
- Path3D: Catmull-Rom spline interpolation for smooth 3D paths
- PlaneGenerator: Parallel transport frame for stable plane orientation
- ResliceEngine: Proper trilinear interpolation sampling
- MandibularUnfoldingModule: 2D unwrapping for dental CBCT
- MultiPlanarSync: Synchronized orthogonal views along spline

Features:
✓ True curved reformation (NOT oblique axial slices)
✓ Parallel transport frame (no flipping)
✓ Spline-driven reslicing
✓ Mandibular canal unfolding for CBCT
✓ Multi-planar synchronized views

References:
- Kanitsar et al., "CPR - Curved Planar Reformation" (2002)
- Bishop, "There is More than One Way to Frame a Curve" (1975)
- Hatcher et al., "Dental CBCT Reformatting" (2010)
"""

import vtkmodules.all as vtk
from typing import List, Tuple, Optional
import numpy as np
import math


# =============================================================================
# Path3D: 3D Spline Path with Catmull-Rom Interpolation
# =============================================================================

class Path3D:
    """
    Represents a smooth 3D path using Catmull-Rom spline interpolation.
    
    This class takes user-defined control points and creates a smooth
    continuous curve that passes through all points. The curve can be
    sampled at any parameter t in [0, 1].
    
    Attributes:
        control_points: Original user-defined points
        spline_points: Densely sampled points on the spline
        arc_lengths: Cumulative arc length at each spline point
        total_length: Total arc length of the path
    """
    
    def __init__(self, control_points: List[Tuple[float, float, float]], tension: float = 0.5):
        """
        Initialize Path3D with control points.
        
        Args:
            control_points: List of 3D points (x, y, z) defining the path
            tension: Catmull-Rom tension parameter (0.5 = standard, 0 = sharp, 1 = loose)
        """
        if len(control_points) < 2:
            raise ValueError("Path requires at least 2 points")
        
        self.control_points = [np.array(p, dtype=np.float64) for p in control_points]
        self.tension = tension
        self.spline_points = []
        self.arc_lengths = []
        self.total_length = 0.0
        
        # Build the spline
        self._build_spline()
    
    def _build_spline(self, samples_per_segment: int = 50):
        """
        Build the Catmull-Rom spline from control points.
        
        The spline is sampled densely and arc lengths are computed
        for uniform parameterization by arc length.
        
        Args:
            samples_per_segment: Number of samples between each pair of control points
        """
        n = len(self.control_points)
        
        # Generate spline points using Catmull-Rom
        self.spline_points = []
        
        for i in range(n - 1):
            # Get the 4 control points for this segment
            # Use endpoint duplication for first and last segments
            p0 = self.control_points[max(0, i - 1)]
            p1 = self.control_points[i]
            p2 = self.control_points[i + 1]
            p3 = self.control_points[min(n - 1, i + 2)]
            
            # Sample the segment
            for j in range(samples_per_segment):
                t = j / samples_per_segment
                point = self._catmull_rom_point(p0, p1, p2, p3, t)
                self.spline_points.append(point)
        
        # Add the last point
        self.spline_points.append(self.control_points[-1].copy())
        
        # Compute arc lengths for uniform parameterization
        self._compute_arc_lengths()
    
    def _catmull_rom_point(
        self, 
        p0: np.ndarray, 
        p1: np.ndarray, 
        p2: np.ndarray, 
        p3: np.ndarray, 
        t: float
    ) -> np.ndarray:
        """
        Compute a point on the Catmull-Rom spline.
        
        Uses the standard Catmull-Rom formula with tension control.
        
        Args:
            p0, p1, p2, p3: Four control points
            t: Parameter in [0, 1]
            
        Returns:
            Interpolated point
        """
        # Catmull-Rom basis matrix with tension
        # Standard Catmull-Rom has tension = 0.5
        tau = self.tension
        
        t2 = t * t
        t3 = t2 * t
        
        # Catmull-Rom polynomial coefficients
        # P(t) = 0.5 * [(2*p1) + (-p0 + p2)*t + (2*p0 - 5*p1 + 4*p2 - p3)*t^2 + (-p0 + 3*p1 - 3*p2 + p3)*t^3]
        point = tau * (
            2 * p1 +
            (-p0 + p2) * t +
            (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
            (-p0 + 3 * p1 - 3 * p2 + p3) * t3
        )
        
        return point
    
    def _catmull_rom_tangent(
        self, 
        p0: np.ndarray, 
        p1: np.ndarray, 
        p2: np.ndarray, 
        p3: np.ndarray, 
        t: float
    ) -> np.ndarray:
        """
        Compute the tangent (derivative) on the Catmull-Rom spline.
        
        Args:
            p0, p1, p2, p3: Four control points
            t: Parameter in [0, 1]
            
        Returns:
            Tangent vector (not normalized)
        """
        tau = self.tension
        t2 = t * t
        
        # Derivative of Catmull-Rom polynomial
        # P'(t) = 0.5 * [(-p0 + p2) + 2*(2*p0 - 5*p1 + 4*p2 - p3)*t + 3*(-p0 + 3*p1 - 3*p2 + p3)*t^2]
        tangent = tau * (
            (-p0 + p2) +
            2 * (2 * p0 - 5 * p1 + 4 * p2 - p3) * t +
            3 * (-p0 + 3 * p1 - 3 * p2 + p3) * t2
        )
        
        return tangent
    
    def _compute_arc_lengths(self):
        """
        Compute cumulative arc lengths for all spline points.
        
        This enables uniform sampling by arc length rather than
        by spline parameter, which gives evenly-spaced samples.
        """
        self.arc_lengths = [0.0]
        
        for i in range(1, len(self.spline_points)):
            dist = np.linalg.norm(self.spline_points[i] - self.spline_points[i-1])
            self.arc_lengths.append(self.arc_lengths[-1] + dist)
        
        self.total_length = self.arc_lengths[-1]
    
    def sample_uniform(self, num_samples: int) -> List[np.ndarray]:
        """
        Sample the path uniformly by arc length.
        
        This gives evenly-spaced points along the curve,
        which is essential for proper curved MPR.
        
        Args:
            num_samples: Number of samples to generate
            
        Returns:
            List of 3D points uniformly spaced along the path
        """
        if num_samples < 2:
            return [self.spline_points[0], self.spline_points[-1]]
        
        # Target arc lengths for uniform sampling
        target_lengths = np.linspace(0, self.total_length, num_samples)
        
        samples = []
        spline_idx = 0
        
        for target in target_lengths:
            # Find the segment containing this arc length
            while spline_idx < len(self.arc_lengths) - 1 and self.arc_lengths[spline_idx + 1] < target:
                spline_idx += 1
            
            # Handle edge case at the end
            if spline_idx >= len(self.spline_points) - 1:
                samples.append(self.spline_points[-1].copy())
                continue
            
            # Interpolate within the segment
            s0 = self.arc_lengths[spline_idx]
            s1 = self.arc_lengths[spline_idx + 1]
            
            if s1 > s0:
                t = (target - s0) / (s1 - s0)
            else:
                t = 0.0
            
            # Linear interpolation between spline points
            p0 = self.spline_points[spline_idx]
            p1 = self.spline_points[spline_idx + 1]
            point = p0 + t * (p1 - p0)
            
            samples.append(point)
        
        return samples
    
    def get_tangent_at(self, arc_length: float) -> np.ndarray:
        """
        Get the tangent vector at a specific arc length.
        
        Args:
            arc_length: Position along the curve by arc length
            
        Returns:
            Normalized tangent vector
        """
        # Find the segment
        idx = 0
        while idx < len(self.arc_lengths) - 1 and self.arc_lengths[idx + 1] < arc_length:
            idx += 1
        
        # Compute tangent from finite difference
        if idx >= len(self.spline_points) - 1:
            idx = len(self.spline_points) - 2
        
        tangent = self.spline_points[idx + 1] - self.spline_points[idx]
        norm = np.linalg.norm(tangent)
        
        if norm > 1e-10:
            tangent = tangent / norm
        else:
            # Fallback for degenerate case
            tangent = np.array([0.0, 0.0, 1.0])
        
        return tangent


# =============================================================================
# PlaneGenerator: Parallel Transport Frame for Stable Plane Orientation
# =============================================================================

class PlaneGenerator:
    """
    Generates stable perpendicular planes along a 3D path.
    
    Uses the Parallel Transport Frame (PTF) algorithm to avoid
    the instability and flipping that occurs with the Frenet frame.
    The PTF maintains a consistent orientation by minimizing
    rotation around the tangent vector.
    
    Reference: Bishop, "There is More than One Way to Frame a Curve" (1975)
    """
    
    def __init__(self, path: Path3D):
        """
        Initialize PlaneGenerator with a path.
        
        Args:
            path: Path3D object defining the curve
        """
        self.path = path
    
    def generate_frames(self, num_frames: int) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
        """
        Generate frames (coordinate systems) along the path.
        
        Each frame consists of:
        - origin: Point on the path
        - tangent: Direction along the path (T)
        - normal: First perpendicular direction (N)
        - binormal: Second perpendicular direction (B)
        
        The plane for reslicing is defined by (normal, binormal) with
        the tangent being the plane's normal vector.
        
        Args:
            num_frames: Number of frames to generate
            
        Returns:
            List of (origin, tangent, normal, binormal) tuples
        """
        # Sample points uniformly along the path
        points = self.path.sample_uniform(num_frames)
        
        # Compute tangents at each point
        tangents = self._compute_tangents(points)
        
        # Generate frames using parallel transport
        frames = self._parallel_transport(points, tangents)
        
        return frames
    
    def _compute_tangents(self, points: List[np.ndarray]) -> List[np.ndarray]:
        """
        Compute tangent vectors at each point using central differences.
        
        Args:
            points: List of 3D points
            
        Returns:
            List of normalized tangent vectors
        """
        n = len(points)
        tangents = []
        
        for i in range(n):
            if i == 0:
                # Forward difference for first point
                tangent = points[1] - points[0]
            elif i == n - 1:
                # Backward difference for last point
                tangent = points[-1] - points[-2]
            else:
                # Central difference for interior points
                tangent = points[i + 1] - points[i - 1]
            
            # Normalize
            norm = np.linalg.norm(tangent)
            if norm > 1e-10:
                tangent = tangent / norm
            else:
                # Use previous tangent if degenerate
                tangent = tangents[-1] if tangents else np.array([0.0, 0.0, 1.0])
            
            tangents.append(tangent)
        
        return tangents
    
    def _parallel_transport(
        self, 
        points: List[np.ndarray], 
        tangents: List[np.ndarray]
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
        """
        Compute parallel transport frames along the path.
        
        The parallel transport frame avoids the instability of the
        Frenet frame by propagating the normal/binormal along the
        curve with minimal twist.
        
        Args:
            points: List of 3D points
            tangents: List of normalized tangent vectors
            
        Returns:
            List of (origin, tangent, normal, binormal) tuples
        """
        n = len(points)
        frames = []
        
        # Initialize first frame
        # Choose initial normal perpendicular to first tangent
        T0 = tangents[0]
        N0 = self._initial_normal(T0)
        B0 = np.cross(T0, N0)
        B0 = B0 / np.linalg.norm(B0)  # Ensure normalized
        
        # DEBUG: Show initial frame orientation
        print(f"[PTF] Initial frame:")
        print(f"      Tangent:  {T0}")
        print(f"      Normal:   {N0}")
        print(f"      Binormal: {B0} (should be [0, 0, +1] for dental arch)")
        
        frames.append((points[0].copy(), T0.copy(), N0.copy(), B0.copy()))
        
        # Propagate frame along the curve using parallel transport
        N_prev = N0
        B_prev = B0
        
        # DEBUG: Track frame stability
        max_N_change = 0.0
        max_B_change = 0.0
        
        for i in range(1, n):
            T_curr = tangents[i]
            T_prev = tangents[i - 1]
            
            # Parallel transport: rotate N and B to be perpendicular to new T
            # while minimizing twist
            N_curr, B_curr = self._transport_frame(T_prev, T_curr, N_prev, B_prev)
            
            # DEBUG: Measure change in orientation
            N_change = np.linalg.norm(N_curr - N_prev)
            B_change = np.linalg.norm(B_curr - B_prev)
            max_N_change = max(max_N_change, N_change)
            max_B_change = max(max_B_change, B_change)
            
            frames.append((points[i].copy(), T_curr.copy(), N_curr.copy(), B_curr.copy()))
            
            N_prev = N_curr
            B_prev = B_curr
        
        print(f"[PTF DEBUG] Max Normal change: {max_N_change:.6f}")
        print(f"[PTF DEBUG] Max Binormal change: {max_B_change:.6f}")
        if max_N_change > 0.5:
            print(f"[PTF WARNING] Large Normal changes detected - possible frame instability!")
        
        return frames
    
    def _initial_normal(self, tangent: np.ndarray) -> np.ndarray:
        """
        Compute initial normal vector perpendicular to tangent.
        
        FIXED FOR DENTAL PANORAMIC:
        For paths in the axial plane (Z component ≈ 0), ensures Normal stays
        in the XY plane (perpendicular to path) and Binormal points in Z direction.
        
        Args:
            tangent: Normalized tangent vector
            
        Returns:
            Normalized normal vector perpendicular to tangent
        """
        # CRITICAL FIX: For dental scans with paths in axial plane
        # Check if tangent is mostly in XY plane (Z component small)
        abs_t = np.abs(tangent)
        
        if abs_t[2] < 0.5:  # Tangent is mostly in XY plane (dental arch case)
            # For dental arch in XY plane:
            # - Tangent is in XY plane (along the arch)
            # - Normal should be in XY plane (pointing inward/outward from arch)
            # - Binormal will be in Z direction (superior-inferior) pointing UPWARD
            
            # Use Z-axis as reference to create Normal in XY plane
            z_axis = np.array([0.0, 0.0, 1.0])
            
            # CRITICAL FIX: Use Z × Tangent (not Tangent × Z)
            # This ensures Binormal = T × N = T × (Z × T) points UPWARD (+Z)
            # Math: If N = Z × T, then B = T × N = T × (Z × T) = Z (for unit vectors in XY)
            normal = np.cross(z_axis, tangent)
            norm = np.linalg.norm(normal)
            
            if norm > 1e-10:
                normal = normal / norm
            else:
                # Fallback: tangent is parallel to Z (shouldn't happen for dental)
                normal = np.array([1.0, 0.0, 0.0])
                normal = normal - np.dot(normal, tangent) * tangent
                normal = normal / np.linalg.norm(normal)
            
            print(f"[PTF] Dental arch detected (Tangent Z-component: {abs_t[2]:.3f})")
            print(f"[PTF] Initial Normal in XY plane: {normal}")
            
        else:
            # For 3D paths (not in XY plane), use standard method
            # Choose reference axis least parallel to tangent
            if abs_t[0] <= abs_t[1] and abs_t[0] <= abs_t[2]:
                ref = np.array([1.0, 0.0, 0.0])
            elif abs_t[1] <= abs_t[0] and abs_t[1] <= abs_t[2]:
                ref = np.array([0.0, 1.0, 0.0])
            else:
                ref = np.array([0.0, 0.0, 1.0])
            
            # Gram-Schmidt orthogonalization
            normal = ref - np.dot(ref, tangent) * tangent
            norm = np.linalg.norm(normal)
            
            if norm > 1e-10:
                normal = normal / norm
            else:
                # Fallback
                normal = np.array([0.0, 1.0, 0.0])
                normal = normal - np.dot(normal, tangent) * tangent
                normal = normal / np.linalg.norm(normal)
        
        return normal
    
    def _transport_frame(
        self,
        T_prev: np.ndarray,
        T_curr: np.ndarray,
        N_prev: np.ndarray,
        B_prev: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Transport the frame from previous tangent to current tangent.
        
        Uses CORRECT parallel transport algorithm with atan2 for stable angle computation.
        This prevents frame twisting and flipping in panoramic views.
        
        Args:
            T_prev: Previous tangent
            T_curr: Current tangent
            N_prev: Previous normal
            B_prev: Previous binormal
            
        Returns:
            (N_curr, B_curr) - transported normal and binormal
        """
        # CORRECT PARALLEL TRANSPORT FRAME ALGORITHM
        # Step 1: Compute rotation axis v = cross(T_prev, T_curr)
        v = np.cross(T_prev, T_curr)
        v_norm_value = np.linalg.norm(v)
        
        # Step 2: Compute dot product c = dot(T_prev, T_curr)
        c = np.dot(T_prev, T_curr)
        
        # Step 3: Check if tangents are nearly parallel
        epsilon = 1e-10
        if v_norm_value < epsilon:
            # Tangents are parallel (or anti-parallel)
            if c > 0:
                # Same direction - no rotation needed
                return N_prev.copy(), B_prev.copy()
            else:
                # Opposite direction - rotate 180 degrees around N
                return -N_prev.copy(), -B_prev.copy()
        
        # Step 4: Normalize rotation axis
        v_normalized = v / v_norm_value
        
        # Step 5: Compute rotation angle using ATAN2 (NOT ARCCOS!)
        # This is the key fix: atan2(norm(v), c) is more stable than arccos(c)
        angle = np.arctan2(v_norm_value, c)
        
        # Step 6: Rotate N_prev around v_normalized by angle
        N_curr = self._rodrigues_rotate(N_prev, v_normalized, angle)
        
        # Step 7: Recompute B_curr to maintain orthonormality
        B_curr = np.cross(T_curr, N_curr)
        
        # Step 8: Normalize to ensure unit vectors
        N_curr = N_curr / np.linalg.norm(N_curr)
        B_curr = B_curr / np.linalg.norm(B_curr)
        
        return N_curr, B_curr
    
    def _rodrigues_rotate(
        self, 
        v: np.ndarray, 
        axis: np.ndarray, 
        angle: float
    ) -> np.ndarray:
        """
        Rotate vector v around axis by angle using Rodrigues' formula.
        
        v_rot = v*cos(angle) + (axis x v)*sin(angle) + axis*(axis . v)*(1 - cos(angle))
        
        Args:
            v: Vector to rotate
            axis: Rotation axis (normalized)
            angle: Rotation angle in radians
            
        Returns:
            Rotated vector
        """
        cos_a = np.cos(angle)
        sin_a = np.sin(angle)
        
        return (
            v * cos_a +
            np.cross(axis, v) * sin_a +
            axis * np.dot(axis, v) * (1 - cos_a)
        )


# =============================================================================
# ResliceEngine: Volume Reslicing with Proper Sampling
# =============================================================================

def auto_crop_image(image_data: vtk.vtkImageData, threshold_percentile: float = 1.0) -> vtk.vtkImageData:
    """
    Automatically crop VTK image to remove empty space (gray areas).
    
    Args:
        image_data: Input vtkImageData
        threshold_percentile: Percentage of max value to use as threshold (default: 1%)
        
    Returns:
        Cropped vtkImageData
    """
    from vtkmodules.util import numpy_support
    
    # Get scalar data
    scalars = image_data.GetPointData().GetScalars()
    if scalars is None:
        return image_data
    
    # Convert to numpy
    dims = image_data.GetDimensions()
    np_array = numpy_support.vtk_to_numpy(scalars)
    
    # Reshape to 3D
    if dims[2] > 1:
        volume_3d = np_array.reshape(dims[2], dims[1], dims[0])
    else:
        volume_3d = np_array.reshape(dims[1], dims[0])
    
    # Find threshold
    max_val = volume_3d.max()
    if max_val == 0:
        return image_data
    
    threshold = max_val * (threshold_percentile / 100.0)
    
    print(f"[AUTO-CROP] Original dims: {dims}, threshold: {threshold:.2f}")
    
    # Find bounding box
    if dims[2] > 1:
        # 3D volume
        z_has_content = np.any(volume_3d > threshold, axis=(1, 2))
        y_has_content = np.any(volume_3d > threshold, axis=(0, 2))
        x_has_content = np.any(volume_3d > threshold, axis=(0, 1))
        
        z_indices = np.where(z_has_content)[0]
        y_indices = np.where(y_has_content)[0]
        x_indices = np.where(x_has_content)[0]
        
        if len(z_indices) > 0 and len(y_indices) > 0 and len(x_indices) > 0:
            # Add 5% padding
            z_padding = max(1, int(0.05 * len(z_indices)))
            y_padding = max(1, int(0.05 * len(y_indices)))
            x_padding = max(1, int(0.05 * len(x_indices)))
            
            z_start = max(0, z_indices[0] - z_padding)
            z_end = min(dims[2], z_indices[-1] + 1 + z_padding)
            y_start = max(0, y_indices[0] - y_padding)
            y_end = min(dims[1], y_indices[-1] + 1 + y_padding)
            x_start = max(0, x_indices[0] - x_padding)
            x_end = min(dims[0], x_indices[-1] + 1 + x_padding)
            
            # Crop
            cropped_volume = volume_3d[z_start:z_end, y_start:y_end, x_start:x_end]
            
            new_dims = (x_end - x_start, y_end - y_start, z_end - z_start)
            print(f"[AUTO-CROP] Cropped dims: {new_dims}, space saved: {(1 - cropped_volume.size / volume_3d.size) * 100:.1f}%")
            
            # Create new vtkImageData
            output = vtk.vtkImageData()
            output.SetDimensions(new_dims)
            output.SetSpacing(image_data.GetSpacing())
            output.SetOrigin(image_data.GetOrigin())
            
            # Convert back to VTK
            flat_array = cropped_volume.flatten()
            vtk_array = numpy_support.numpy_to_vtk(flat_array, deep=True)
            vtk_array.SetNumberOfComponents(1)
            output.GetPointData().SetScalars(vtk_array)
            
            return output
    else:
        # 2D image
        y_has_content = np.any(volume_3d > threshold, axis=1)
        x_has_content = np.any(volume_3d > threshold, axis=0)
        
        y_indices = np.where(y_has_content)[0]
        x_indices = np.where(x_has_content)[0]
        
        if len(y_indices) > 0 and len(x_indices) > 0:
            # Add 5% padding
            y_padding = max(1, int(0.05 * len(y_indices)))
            x_padding = max(1, int(0.05 * len(x_indices)))
            
            y_start = max(0, y_indices[0] - y_padding)
            y_end = min(dims[1], y_indices[-1] + 1 + y_padding)
            x_start = max(0, x_indices[0] - x_padding)
            x_end = min(dims[0], x_indices[-1] + 1 + x_padding)
            
            # Crop
            cropped_image = volume_3d[y_start:y_end, x_start:x_end]
            
            new_dims = (x_end - x_start, y_end - y_start, 1)
            print(f"[AUTO-CROP] Cropped dims: {new_dims}, space saved: {(1 - cropped_image.size / volume_3d.size) * 100:.1f}%")
            
            # Create new vtkImageData
            output = vtk.vtkImageData()
            output.SetDimensions(new_dims)
            output.SetSpacing(image_data.GetSpacing())
            output.SetOrigin(image_data.GetOrigin())
            
            # Convert back to VTK
            flat_array = cropped_image.flatten(order='F')
            vtk_array = numpy_support.numpy_to_vtk(flat_array, deep=True)
            vtk_array.SetNumberOfComponents(1)
            output.GetPointData().SetScalars(vtk_array)
            
            return output
    
    # If no content found, return original
    return image_data


class ResliceEngine:
    """
    Engine for reslicing a 3D volume along planes defined by frames.
    
    For each frame, extracts a 2D slice perpendicular to the tangent,
    using the normal and binormal as the slice axes. Uses trilinear
    interpolation for proper sampling.
    """
    
    def __init__(self, image_data: vtk.vtkImageData):
        """
        Initialize ResliceEngine with a VTK image.
        
        Args:
            image_data: Input 3D volume (vtkImageData)
        """
        self.image_data = image_data
        self.spacing = image_data.GetSpacing()
        self.origin = image_data.GetOrigin()
        self.dims = image_data.GetDimensions()
        
        # Compute image bounds
        self.bounds = image_data.GetBounds()
        
        # Create probe filter for efficient sampling
        self.probe = vtk.vtkProbeFilter()
        self.probe.SetSourceData(image_data)
    
    def reslice_along_path(
        self,
        frames: List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
        slice_size: float = 100.0,
        output_spacing: Optional[float] = None
    ) -> vtk.vtkImageData:
        """
        Reslice the volume along the path defined by frames.
        
        For each frame, extracts a perpendicular slice and stacks
        them to create a straightened volume.
        
        Args:
            frames: List of (origin, tangent, normal, binormal) from PlaneGenerator
            slice_size: Size of each slice in mm (width and height)
            output_spacing: Output pixel spacing (default: minimum input spacing)
            
        Returns:
            Straightened volume as vtkImageData
        """
        if not frames:
            raise ValueError("No frames provided")
        
        # Determine output spacing
        if output_spacing is None:
            output_spacing = min(self.spacing[0], self.spacing[1])
        
        # Calculate output dimensions for each slice
        slice_pixels = int(np.ceil(slice_size / output_spacing))
        if slice_pixels % 2 == 1:
            slice_pixels += 1  # Ensure even dimensions
        
        num_slices = len(frames)
        
        print(f"[CURVED MPR] Reslicing: {num_slices} slices, {slice_pixels}x{slice_pixels} pixels")
        
        # Extract slices
        slices = []
        for i, (origin, tangent, normal, binormal) in enumerate(frames):
            slice_img = self._extract_slice(
                origin, tangent, normal, binormal,
                slice_size, output_spacing, slice_pixels
            )
            slices.append(slice_img)
        
        # Stack slices into 3D volume
        result = self._stack_slices(slices, output_spacing)
        
        return result
    
    def generate_panoramic_image_slicer_method(
        self,
        frames: List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
        slice_thickness_mm: float = 10.0,
        slice_height_mm: float = 150.0,
        output_spacing: Optional[float] = None,
        projection_type: str = 'mean'
    ) -> vtk.vtkImageData:
        """
        Generate panoramic image using 3D Slicer's two-step method.
        
        BASED ON: lassoan's CurvedPlanarReformatting.py gist
        https://gist.github.com/lassoan/b445c734f118a5fb7643f3fb05f98b07
        
        TWO-STEP PROCESS:
        =================
        
        STEP A: Build Straightened Volume
        ----------------------------------
        For each position along the centerline:
          1. Extract a full 2D orthogonal slice (perpendicular to path)
          2. Each slice has dimensions: (thickness × height)
             - thickness: radial extent (Normal direction)
             - height: vertical extent (Binormal direction, superior-inferior)
          3. Stack all slices to create 3D straightenedVolume
             - Dimensions: (num_positions × height × thickness)
             - Axes: (along-curve × vertical × radial)
        
        STEP B: Panoramic Projection
        -----------------------------
        Project the straightenedVolume along the radial (thickness) axis:
          - panoramicArray = straightenedVolumeArray.mean(axis=2)  # or .max()
          - Result: 2D image (num_positions × height)
          - Horizontal axis: distance along dental arch
          - Vertical axis: superior-inferior (root to crown)
        
        WHY THIS WORKS:
        ===============
        - Old method: Sampled only a thin line at each position → only crown visible
        - New method: Captures full radial extent → includes both crowns AND roots
        - Projection: Averages/maxes through thickness → shows complete anatomy
        
        Args:
            frames: List of (origin, tangent, normal, binormal) from PlaneGenerator
            slice_thickness_mm: Radial thickness to sample (Normal direction)
            slice_height_mm: Vertical extent to sample (Binormal direction)
            output_spacing: Output pixel spacing (default: minimum input spacing)
            projection_type: 'mean' or 'max' intensity projection
            
        Returns:
            2D panoramic image as vtkImageData
        """
        from vtkmodules.util import numpy_support
        
        if not frames:
            raise ValueError("No frames provided")
        
        # Determine output spacing
        if output_spacing is None:
            output_spacing = min(self.spacing[0], self.spacing[1], self.spacing[2])
        
        num_positions = len(frames)
        
        # Calculate dimensions for each orthogonal slice
        thickness_pixels = int(np.ceil(slice_thickness_mm / output_spacing))
        height_pixels = int(np.ceil(slice_height_mm / output_spacing))
        
        # Ensure even dimensions
        if thickness_pixels % 2 == 1:
            thickness_pixels += 1
        if height_pixels % 2 == 1:
            height_pixels += 1
        
        print(f"\n[PANORAMIC SLICER METHOD] Generating panoramic using Slicer's approach:")
        print(f"      STEP A: Building straightened volume...")
        print(f"      - Positions along path: {num_positions}")
        print(f"      - Slice thickness: {slice_thickness_mm:.1f}mm ({thickness_pixels} pixels)")
        print(f"      - Slice height: {slice_height_mm:.1f}mm ({height_pixels} pixels)")
        print(f"      - Output spacing: {output_spacing:.3f} mm")
        print(f"      - Projection type: {projection_type}")
        
        # ===================================================================
        # STEP A: BUILD STRAIGHTENED VOLUME
        # ===================================================================
        # Create 3D array: (num_positions × height × thickness)
        # - Axis 0: along the curve (dental arch)
        # - Axis 1: vertical (superior-inferior, Binormal direction)
        # - Axis 2: radial/thickness (Normal direction, inward-outward)
        
        straightened_volume = np.zeros(
            (num_positions, height_pixels, thickness_pixels),
            dtype=np.float32
        )
        
        print(f"[PANORAMIC] Straightened volume shape: {straightened_volume.shape}")
        print(f"[PANORAMIC] Extracting {num_positions} orthogonal slices...")
        
        # For each position along the centerline
        for i, (origin, tangent, normal, binormal) in enumerate(frames):
            # Extract a full 2D orthogonal slice at this position
            # The slice is perpendicular to the path (Tangent is the slice normal)
            # In-plane directions: Normal (radial) × Binormal (vertical)
            
            slice_2d = self._extract_orthogonal_slice_for_panoramic(
                origin, tangent, normal, binormal,
                thickness_pixels, height_pixels, output_spacing
            )
            
            # Store in straightened volume
            # slice_2d has shape (height_pixels, thickness_pixels)
            straightened_volume[i, :, :] = slice_2d
            
            # Progress indicator
            if (i + 1) % 20 == 0 or i == 0 or i == num_positions - 1:
                progress = ((i + 1) / num_positions) * 100
                print(f"      Progress: {i+1}/{num_positions} ({progress:.0f}%)")
        
        print(f"[PANORAMIC] ✓ Straightened volume built")
        print(f"      Value range: [{straightened_volume.min():.1f}, {straightened_volume.max():.1f}]")
        
        # ===================================================================
        # STEP B: PANORAMIC PROJECTION
        # ===================================================================
        # Project along the radial axis (axis 2 = thickness)
        # This combines all the radial samples into a single 2D panoramic image
        
        print(f"[PANORAMIC] STEP B: Computing {projection_type} projection along radial axis...")
        
        if projection_type == 'mean':
            # Mean Intensity Projection (similar to Slicer's default)
            panoramic_array = np.mean(straightened_volume, axis=2)
        elif projection_type == 'max':
            # Maximum Intensity Projection
            panoramic_array = np.max(straightened_volume, axis=2)
        else:
            raise ValueError(f"Unknown projection type: {projection_type}")
        
        # panoramic_array now has shape: (num_positions, height_pixels)
        # - Horizontal: along dental arch
        # - Vertical: superior-inferior
        
        print(f"[PANORAMIC] ✓ Projection complete")
        print(f"      Panoramic shape before transpose: {panoramic_array.shape}")
        print(f"      Value range: [{panoramic_array.min():.1f}, {panoramic_array.max():.1f}]")
        
        # ===================================================================
        # CREATE VTK OUTPUT WITH CORRECT SPACING (CRITICAL FOR MEASUREMENTS!)
        # ===================================================================
        
        # Current: panoramic_array is (num_positions, height_pixels)
        # We need: (num_positions × height_pixels) for panoramic display
        # Where:
        #   - X axis (width) = num_positions (along dental arch) 
        #   - Y axis (height) = height_pixels (superior-inferior)
        
        # Flip vertically so superior is at top (similar to Slicer's np.flip)
        # This ensures upper teeth at top, lower teeth at bottom
        panoramic_flipped = np.flip(panoramic_array, axis=1)
        
        print(f"[PANORAMIC] Flipped vertically for correct orientation")
        
        # ===================================================================
        # AUTO-CROP: Remove empty space (gray areas)
        # ===================================================================
        print(f"[PANORAMIC] Auto-cropping to remove empty space...")
        print(f"      Original shape: {panoramic_flipped.shape}")
        
        # Find bounding box of non-zero content
        # Set a threshold (e.g., values > 1% of max are considered content)
        threshold = panoramic_flipped.max() * 0.01 if panoramic_flipped.max() > 0 else 0
        
        # Find rows and columns that contain content
        row_has_content = np.any(panoramic_flipped > threshold, axis=1)
        col_has_content = np.any(panoramic_flipped > threshold, axis=0)
        
        # Get indices of first and last content
        content_rows = np.where(row_has_content)[0]
        content_cols = np.where(col_has_content)[0]
        
        if len(content_rows) > 0 and len(content_cols) > 0:
            # Add small padding (5% on each side)
            row_padding = max(1, int(0.05 * len(content_rows)))
            col_padding = max(1, int(0.05 * len(content_cols)))
            
            row_start = max(0, content_rows[0] - row_padding)
            row_end = min(panoramic_flipped.shape[0], content_rows[-1] + 1 + row_padding)
            col_start = max(0, content_cols[0] - col_padding)
            col_end = min(panoramic_flipped.shape[1], content_cols[-1] + 1 + col_padding)
            
            # Crop the array
            panoramic_cropped = panoramic_flipped[row_start:row_end, col_start:col_end]
            
            # Store crop info for spacing adjustment
            crop_info = {
                'row_start': row_start,
                'row_end': row_end,
                'col_start': col_start,
                'col_end': col_end
            }
            
            print(f"      Cropped shape: {panoramic_cropped.shape}")
            print(f"      Removed rows: {row_start} to {panoramic_flipped.shape[0] - row_end}")
            print(f"      Removed cols: {col_start} to {panoramic_flipped.shape[1] - col_end}")
            print(f"      Space saved: {(1 - panoramic_cropped.size / panoramic_flipped.size) * 100:.1f}%")
            
            # Update for further processing
            panoramic_flipped = panoramic_cropped
            height_pixels_cropped = panoramic_cropped.shape[1]
            num_positions_cropped = panoramic_cropped.shape[0]
        else:
            print(f"      ⚠ Warning: No content found, skipping crop")
            height_pixels_cropped = height_pixels
            num_positions_cropped = num_positions
            crop_info = None
        
        # CRITICAL: Calculate CORRECT spacing for each axis
        # This is essential for accurate measurements in medical imaging!
        
        # Get actual path length from frames
        path_length = 0.0
        for i in range(1, len(frames)):
            origin_prev = frames[i-1][0]
            origin_curr = frames[i][0]
            segment_length = np.linalg.norm(origin_curr - origin_prev)
            path_length += segment_length
        
        # X spacing: actual distance between positions along the arch
        spacing_x = path_length / (num_positions - 1) if num_positions > 1 else output_spacing
        
        # Y spacing: same as output_spacing (vertical resolution)
        spacing_y = output_spacing
        
        print(f"[PANORAMIC] CORRECT SPACING for accurate measurements:")
        print(f"      Path length: {path_length:.2f} mm")
        print(f"      X spacing (along arch): {spacing_x:.4f} mm/pixel")
        print(f"      Y spacing (vertical): {spacing_y:.4f} mm/pixel")
        print(f"      Aspect ratio: {spacing_x/spacing_y:.2f}")
        
        output = vtk.vtkImageData()
        # VTK dimensions: (X=positions, Y=height, Z=1) - use cropped dimensions
        output.SetDimensions(num_positions_cropped, height_pixels_cropped, 1)
        
        # CRITICAL FIX: Use CORRECT spacing for each axis
        # This ensures measurements are accurate and anatomy is not distorted
        output.SetSpacing(spacing_x, spacing_y, 1.0)
        output.SetOrigin(0, 0, 0)
        
        # Convert numpy array to VTK
        # VTK expects data in (X, Y, Z) order, row-major flattening
        # panoramic_flipped is (num_positions_cropped, height_pixels_cropped)
        # We need to transpose to (height_pixels_cropped, num_positions_cropped) then flatten
        flat_array = panoramic_flipped.T.flatten()
        vtk_array = numpy_support.numpy_to_vtk(flat_array, deep=True)
        vtk_array.SetNumberOfComponents(1)
        output.GetPointData().SetScalars(vtk_array)
        
        print(f"[PANORAMIC SLICER METHOD] ✓ Complete!")
        print(f"      Output dimensions: {output.GetDimensions()}")
        print(f"      Physical size: {num_positions_cropped * spacing_x:.1f} × {height_pixels_cropped * spacing_y:.1f} mm")
        print(f"      Width (along arch): {num_positions_cropped} pixels ({num_positions_cropped * spacing_x:.1f} mm)")
        print(f"      Height (vertical): {height_pixels_cropped} pixels ({height_pixels_cropped * spacing_y:.1f} mm)")
        
        return output
    
    def _extract_orthogonal_slice_for_panoramic(
        self,
        origin: np.ndarray,
        tangent: np.ndarray,
        normal: np.ndarray,
        binormal: np.ndarray,
        thickness_pixels: int,
        height_pixels: int,
        output_spacing: float
    ) -> np.ndarray:
        """
        Extract a full 2D orthogonal slice for panoramic reconstruction.
        
        This is the core of the Slicer method: extract a COMPLETE 2D slice
        perpendicular to the path, with sufficient radial extent to capture
        both crowns AND roots.
        
        Args:
            origin: Center point on the path
            tangent: Path direction (becomes slice normal)
            normal: First in-plane direction (radial, for thickness)
            binormal: Second in-plane direction (vertical, superior-inferior)
            thickness_pixels: Number of pixels in radial direction
            height_pixels: Number of pixels in vertical direction
            output_spacing: Pixel spacing
            
        Returns:
            2D numpy array (height_pixels × thickness_pixels)
        """
        from vtkmodules.util import numpy_support
        
        # Create vtkImageReslice for high-quality extraction
        reslice = vtk.vtkImageReslice()
        reslice.SetInputData(self.image_data)
        reslice.SetOutputDimensionality(2)
        reslice.SetInterpolationModeToCubic()
        
        # Set reslice axes:
        # - X axis (output columns): Normal direction (radial, thickness)
        # - Y axis (output rows): Binormal direction (vertical, height)
        # - Z axis (slice normal): Tangent direction (perpendicular to slice)
        reslice.SetResliceAxesDirectionCosines(
            normal[0], normal[1], normal[2],      # X: radial
            binormal[0], binormal[1], binormal[2], # Y: vertical
            tangent[0], tangent[1], tangent[2]     # Z: slice normal
        )
        
        # Set origin
        reslice.SetResliceAxesOrigin(origin[0], origin[1], origin[2])
        
        # Set output extent (centered around origin)
        half_thickness = thickness_pixels // 2
        half_height = height_pixels // 2
        reslice.SetOutputExtent(
            -half_thickness, half_thickness - 1,  # X: radial extent
            -half_height, half_height - 1,        # Y: vertical extent
            0, 0                                   # Z: single slice
        )
        
        # Set spacing
        reslice.SetOutputSpacing(output_spacing, output_spacing, 1.0)
        reslice.SetOutputOrigin(0.0, 0.0, 0.0)
        
        # Handle out-of-bounds
        reslice.SetBackgroundLevel(0)
        reslice.SetBorder(False)
        reslice.SetWrap(False)
        reslice.AutoCropOutputOff()
        
        # Execute
        reslice.Update()
        
        # Convert to numpy array
        output_data = reslice.GetOutput()
        scalars = output_data.GetPointData().GetScalars()
        slice_array = numpy_support.vtk_to_numpy(scalars)
        
        # Reshape to 2D: (height, thickness)
        slice_2d = slice_array.reshape(height_pixels, thickness_pixels)
        
        return slice_2d
    
    def _sample_volume_at_point(self, world_pos: np.ndarray) -> float:
        """
        Sample the volume at a given world position using trilinear interpolation.
        
        Args:
            world_pos: 3D world position
            
        Returns:
            Interpolated intensity value
        """
        # Convert world position to index position
        index_pos = np.array([
            (world_pos[0] - self.origin[0]) / self.spacing[0],
            (world_pos[1] - self.origin[1]) / self.spacing[1],
            (world_pos[2] - self.origin[2]) / self.spacing[2]
        ])
        
        # Check bounds
        if (index_pos[0] < 0 or index_pos[0] >= self.dims[0] - 1 or
            index_pos[1] < 0 or index_pos[1] >= self.dims[1] - 1 or
            index_pos[2] < 0 or index_pos[2] >= self.dims[2] - 1):
            return 0.0
        
        # Get integer and fractional parts
        i0 = int(np.floor(index_pos[0]))
        i1 = min(i0 + 1, self.dims[0] - 1)
        j0 = int(np.floor(index_pos[1]))
        j1 = min(j0 + 1, self.dims[1] - 1)
        k0 = int(np.floor(index_pos[2]))
        k1 = min(k0 + 1, self.dims[2] - 1)
        
        fx = index_pos[0] - i0
        fy = index_pos[1] - j0
        fz = index_pos[2] - k0
        
        # Trilinear interpolation
        # Get 8 corner values
        from vtkmodules.util import numpy_support
        scalars = self.image_data.GetPointData().GetScalars()
        
        def get_value(i, j, k):
            idx = k * (self.dims[0] * self.dims[1]) + j * self.dims[0] + i
            return scalars.GetTuple1(idx)
        
        v000 = get_value(i0, j0, k0)
        v100 = get_value(i1, j0, k0)
        v010 = get_value(i0, j1, k0)
        v110 = get_value(i1, j1, k0)
        v001 = get_value(i0, j0, k1)
        v101 = get_value(i1, j0, k1)
        v011 = get_value(i0, j1, k1)
        v111 = get_value(i1, j1, k1)
        
        # Interpolate
        v00 = v000 * (1 - fx) + v100 * fx
        v01 = v001 * (1 - fx) + v101 * fx
        v10 = v010 * (1 - fx) + v110 * fx
        v11 = v011 * (1 - fx) + v111 * fx
        
        v0 = v00 * (1 - fy) + v10 * fy
        v1 = v01 * (1 - fy) + v11 * fy
        
        value = v0 * (1 - fz) + v1 * fz
        
        return float(value)
    
    def _extract_slice(
        self,
        origin: np.ndarray,
        tangent: np.ndarray,
        normal: np.ndarray,
        binormal: np.ndarray,
        slice_size: float,
        output_spacing: float,
        slice_pixels: int
    ) -> vtk.vtkImageData:
        """
        Extract a single slice perpendicular to the path.
        
        The slice plane is defined by:
        - Origin: center of the slice (on the path)
        - X-axis: normal vector (N)
        - Y-axis: binormal vector (B)
        - Normal: tangent vector (T) - this is the plane's normal
        
        Args:
            origin: Center point of the slice
            tangent: Tangent vector (path direction, becomes plane normal)
            normal: Normal vector (first in-plane axis)
            binormal: Binormal vector (second in-plane axis)
            slice_size: Size of slice in mm
            output_spacing: Pixel spacing
            slice_pixels: Number of pixels
            
        Returns:
            2D slice as vtkImageData
        """
        # Create vtkImageReslice for proper interpolation
        reslice = vtk.vtkImageReslice()
        reslice.SetInputData(self.image_data)
        reslice.SetOutputDimensionality(2)
        
        # Use cubic interpolation for high quality
        reslice.SetInterpolationModeToCubic()
        
        # Set reslice axes
        # The direction cosines define the orientation of the output image
        # First vector: X direction in output (maps to normal)
        # Second vector: Y direction in output (maps to binormal)
        # Third vector: normal to the slice plane (tangent)
        reslice.SetResliceAxesDirectionCosines(
            normal[0], normal[1], normal[2],      # Output X axis
            binormal[0], binormal[1], binormal[2], # Output Y axis
            tangent[0], tangent[1], tangent[2]     # Output Z axis (slice normal)
        )
        
        # Set origin of the slice
        reslice.SetResliceAxesOrigin(origin[0], origin[1], origin[2])
        
        # Set output extent (centered around origin)
        half_pixels = slice_pixels // 2
        reslice.SetOutputExtent(
            -half_pixels, half_pixels - 1,
            -half_pixels, half_pixels - 1,
            0, 0
        )
        
        # Set output spacing
        reslice.SetOutputSpacing(output_spacing, output_spacing, 1.0)
        
        # CRITICAL FIX: OutputOrigin must be (0,0,0) when extent is centered
        # The extent already defines the range, origin should be at center
        reslice.SetOutputOrigin(0.0, 0.0, 0.0)
        
        # CRITICAL FIX: Set background value for out-of-bounds regions
        # This prevents all-zero output when slice is outside volume
        reslice.SetBackgroundLevel(0)
        reslice.SetBorder(False)  # Don't extend borders
        
        # Enable wrapping/clamping to handle edge cases
        reslice.SetWrap(False)
        reslice.SetMirror(False)
        
        # CRITICAL: Enable AutoCropOutput to handle out-of-bounds
        reslice.AutoCropOutputOff()  # Keep full extent even if partially outside
        
        # Execute
        reslice.Update()
        
        # Check if output has valid data
        output_data = reslice.GetOutput()
        scalar_range = output_data.GetScalarRange()
        
        # Debug: warn if slice is empty
        if scalar_range[0] == 0 and scalar_range[1] == 0:
            print(f"[CURVED MPR] WARNING: Empty slice at origin {origin} - may be outside volume bounds")
        
        # Return a deep copy to ensure data is not lost
        output = vtk.vtkImageData()
        output.DeepCopy(output_data)
        
        return output
    
    def _stack_slices(
        self, 
        slices: List[vtk.vtkImageData],
        output_spacing: float
    ) -> vtk.vtkImageData:
        """
        Stack 2D slices into a 3D volume.
        
        Uses numpy for efficient memory operations.
        
        Args:
            slices: List of 2D slice images
            output_spacing: Spacing between slices
            
        Returns:
            3D volume as vtkImageData
        """
        from vtkmodules.util import numpy_support
        
        if not slices:
            return None
        
        # Get dimensions from first slice
        dims = slices[0].GetDimensions()
        num_slices = len(slices)
        
        # Get scalar type
        scalar_type = slices[0].GetScalarType()
        
        # Map VTK scalar type to numpy dtype
        dtype_map = {
            vtk.VTK_CHAR: np.int8,
            vtk.VTK_UNSIGNED_CHAR: np.uint8,
            vtk.VTK_SHORT: np.int16,
            vtk.VTK_UNSIGNED_SHORT: np.uint16,
            vtk.VTK_INT: np.int32,
            vtk.VTK_UNSIGNED_INT: np.uint32,
            vtk.VTK_FLOAT: np.float32,
            vtk.VTK_DOUBLE: np.float64,
        }
        dtype = dtype_map.get(scalar_type, np.float32)
        
        # Create numpy array for the stacked volume
        # Shape: (Z, Y, X) for proper VTK memory layout
        volume_array = np.zeros((num_slices, dims[1], dims[0]), dtype=dtype)
        
        # Copy slices into volume
        for i, slice_img in enumerate(slices):
            scalars = slice_img.GetPointData().GetScalars()
            if scalars is not None:
                slice_array = numpy_support.vtk_to_numpy(scalars)
                slice_array = slice_array.reshape(dims[1], dims[0])
                volume_array[i, :, :] = slice_array
        
        # Create output vtkImageData
        output = vtk.vtkImageData()
        output.SetDimensions(dims[0], dims[1], num_slices)
        output.SetSpacing(output_spacing, output_spacing, output_spacing)
        output.SetOrigin(0, 0, 0)
        
        # Convert numpy array to VTK array
        flat_array = volume_array.flatten()
        vtk_array = numpy_support.numpy_to_vtk(flat_array, deep=True)
        vtk_array.SetNumberOfComponents(1)
        
        output.GetPointData().SetScalars(vtk_array)
        
        return output


# =============================================================================
# CurvedMPRGenerator: Main Interface
# =============================================================================

class CurvedMPRGenerator:
    """
    Main class for generating Curved Planar Reformation.
    
    This is the primary interface for curved MPR. It coordinates:
    - Path3D for spline interpolation
    - PlaneGenerator for stable frame computation
    - ResliceEngine for volume sampling
    
    Usage:
        generator = CurvedMPRGenerator(vtk_image_data)
        generator.set_centerline([(x1,y1,z1), (x2,y2,z2), ...])
        curved_volume = generator.generate_curved_mpr(slice_size=100, num_slices=50)
    """
    
    def __init__(self, image_data: vtk.vtkImageData):
        """
        Initialize the curved MPR generator.
        
        Args:
            image_data: Input 3D volume as vtkImageData
        """
        self.image_data = image_data
        self.spacing = image_data.GetSpacing()
        self.path = None
        self.centerline_points = []
        self.curved_image = None
    
    def set_centerline(self, points: List[Tuple[float, float, float]]):
        """
        Set the path for curved MPR.
        
        The points should be in 3D world coordinates (x, y, z).
        A smooth Catmull-Rom spline will be fitted through these points.
        
        Args:
            points: List of 3D points defining the path
        """
        if len(points) < 2:
            raise ValueError("At least 2 points required for curved MPR")
        
        self.centerline_points = points
        
        # Check if all points are coplanar (common mistake!)
        points_array = np.array(points)
        
        # Check variation in each dimension
        x_range = points_array[:, 0].max() - points_array[:, 0].min()
        y_range = points_array[:, 1].max() - points_array[:, 1].min()
        z_range = points_array[:, 2].max() - points_array[:, 2].min()
        
        print(f"[CURVED MPR] Path ranges: X={x_range:.1f}mm, Y={y_range:.1f}mm, Z={z_range:.1f}mm")
        
        if z_range < 1.0:  # Less than 1mm variation in Z
            print(f"[CURVED MPR] WARNING: All points are nearly coplanar in Z (range: {z_range:.2f}mm)")
            print(f"[CURVED MPR] WARNING: For true 3D curved MPR, pick points on DIFFERENT slices!")
            print(f"[CURVED MPR] WARNING: Current path is essentially 2D in the axial plane")
            
            # For coplanar points in XY plane, we can still do in-plane CPR
            # but perpendicular slices will be thin and may miss the volume
        
        # Create the smooth 3D path
        self.path = Path3D(points)
        
        print(f"[CURVED MPR] Path set with {len(points)} control points, "
              f"total length: {self.path.total_length:.1f} mm")
    
    def generate_curved_mpr(
        self,
        slice_width: float = 100.0,
        slice_height: float = 100.0,
        num_slices: Optional[int] = None,
        output_spacing: Optional[float] = None
    ) -> vtk.vtkImageData:
        """
        Generate the curved MPR volume.
        
        Creates a straightened volume by:
        1. Sampling the path uniformly
        2. Computing stable perpendicular planes at each sample
        3. Reslicing the volume at each plane
        4. Stacking slices into a new volume
        
        Args:
            slice_width: Width of each perpendicular slice in mm
            slice_height: Height of each perpendicular slice in mm (currently equals width)
            num_slices: Number of slices along the path (default: auto based on path length)
            output_spacing: Output pixel spacing (default: minimum input spacing)
            
        Returns:
            Curved MPR volume as vtkImageData
        """
        if self.path is None:
            raise ValueError("Must call set_centerline() first")
        
        # Determine number of slices
        if num_slices is None:
            # Default: approximately 1 slice per mm of path length
            min_spacing = min(self.spacing)
            num_slices = max(20, int(self.path.total_length / min_spacing))
        
        # Use the larger of width/height as slice size
        slice_size = max(slice_width, slice_height)
        
        print(f"[CURVED MPR] Generating: {num_slices} slices, {slice_size:.0f}mm size")
        
        # Step 1: Generate frames along the path using parallel transport
        plane_generator = PlaneGenerator(self.path)
        frames = plane_generator.generate_frames(num_slices)
        
        print(f"[CURVED MPR] Generated {len(frames)} frames")
        
        # Step 2: Reslice the volume at each frame
        reslice_engine = ResliceEngine(self.image_data)
        curved_volume = reslice_engine.reslice_along_path(
            frames,
            slice_size=slice_size,
            output_spacing=output_spacing
        )
        
        # Auto-crop to remove empty space
        print(f"[CURVED MPR] Auto-cropping curved volume...")
        curved_volume_cropped = auto_crop_image(curved_volume, threshold_percentile=1.0)
        
        self.curved_image = curved_volume_cropped
        
        dims = curved_volume_cropped.GetDimensions()
        scalar_range = curved_volume_cropped.GetScalarRange()
        print(f"[CURVED MPR] Result (after crop): {dims[0]}x{dims[1]}x{dims[2]}, range: {scalar_range}")
        
        return curved_volume_cropped
    
    def generate_panoramic_view(
        self,
        slice_thickness_mm: float = 10.0,
        slice_height_mm: float = 150.0,
        num_positions: Optional[int] = None,
        output_spacing: Optional[float] = None,
        projection_type: str = 'mean'
    ) -> vtk.vtkImageData:
        """
        Generate panoramic image using 3D Slicer's two-step method.
        
        BASED ON: lassoan's CurvedPlanarReformatting.py
        https://gist.github.com/lassoan/b445c734f118a5fb7643f3fb05f98b07
        
        Args:
            slice_thickness_mm: Radial thickness to sample (Normal direction)
            slice_height_mm: Vertical extent to sample (Binormal direction)
            num_positions: Number of positions along path (default: auto)
            output_spacing: Output pixel spacing (default: minimum input spacing)
            projection_type: 'mean' or 'max' intensity projection
            
        Returns:
            2D panoramic image as vtkImageData
        """
        if self.path is None:
            raise ValueError("Must call set_centerline() first")
        
        # Determine number of positions
        if num_positions is None:
            # Use higher sampling for panoramic (wider image)
            # Approximately 3-4 positions per mm for better resolution
            num_positions = max(100, min(500, int(self.path.total_length * 3)))
        
        print(f"[PANORAMIC] Generating panoramic view (Slicer method)...")
        print(f"      Path length: {self.path.total_length:.1f} mm")
        print(f"      Num positions: {num_positions}")
        
        # Generate frames along the path
        plane_generator = PlaneGenerator(self.path)
        frames = plane_generator.generate_frames(num_positions)
        
        # Generate panoramic using Slicer's method
        reslice_engine = ResliceEngine(self.image_data)
        panoramic_image = reslice_engine.generate_panoramic_image_slicer_method(
            frames,
            slice_thickness_mm=slice_thickness_mm,
            slice_height_mm=slice_height_mm,
            output_spacing=output_spacing,
            projection_type=projection_type
        )
        
        return panoramic_image


# =============================================================================
# InteractiveCurvedMPR: Interactive Path Definition
# =============================================================================

class InteractiveCurvedMPR:
    """
    Interactive curved MPR with visual feedback.
    
    Allows users to define a path by clicking points in a VTK renderer,
    with real-time visualization of the path.
    """
    
    def __init__(
        self,
        image_data: vtk.vtkImageData,
        renderer: vtk.vtkRenderer
    ):
        """
        Initialize interactive curved MPR.
        
        Args:
            image_data: Input volume
            renderer: VTK renderer for visualization
        """
        self.image_data = image_data
        self.renderer = renderer
        self.path_points = []
        self.sphere_actors = []
        self.line_actor = None
        self.spline_actor = None
        self.generator = CurvedMPRGenerator(image_data)
    
    def add_path_point(self, point: Tuple[float, float, float]):
        """
        Add a point to the path.
        
        Args:
            point: 3D point coordinates (x, y, z)
        """
        self.path_points.append(point)
        
        # Visualize the point
        sphere = vtk.vtkSphereSource()
        sphere.SetCenter(point)
        sphere.SetRadius(3.0)
        sphere.SetPhiResolution(16)
        sphere.SetThetaResolution(16)
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        
        # First point is green, others are red
        if len(self.path_points) == 1:
            actor.GetProperty().SetColor(0.0, 1.0, 0.0)  # Green
        else:
            actor.GetProperty().SetColor(1.0, 0.0, 0.0)  # Red
        
        self.renderer.AddActor(actor)
        self.sphere_actors.append(actor)
        
        # Update path visualization
        self._update_path_visualization()
    
    def clear_path(self):
        """Clear all path points and visuals."""
        self.path_points = []
        
        # Remove sphere actors
        for actor in self.sphere_actors:
            self.renderer.RemoveActor(actor)
        self.sphere_actors = []
        
        # Remove line actor
        if self.line_actor:
            self.renderer.RemoveActor(self.line_actor)
            self.line_actor = None
        
        # Remove spline actor
        if self.spline_actor:
            self.renderer.RemoveActor(self.spline_actor)
            self.spline_actor = None
    
    def _update_path_visualization(self):
        """Update the visual representation of the path."""
        if len(self.path_points) < 2:
            return
        
        # Remove old visuals
        if self.line_actor:
            self.renderer.RemoveActor(self.line_actor)
        if self.spline_actor:
            self.renderer.RemoveActor(self.spline_actor)
        
        # Create spline through points
        try:
            path = Path3D(self.path_points)
            spline_points = path.sample_uniform(100)
            
            # Create polydata for spline
            points = vtk.vtkPoints()
            for p in spline_points:
                points.InsertNextPoint(p[0], p[1], p[2])
            
            lines = vtk.vtkCellArray()
            for i in range(len(spline_points) - 1):
                line = vtk.vtkLine()
                line.GetPointIds().SetId(0, i)
                line.GetPointIds().SetId(1, i + 1)
                lines.InsertNextCell(line)
            
            polydata = vtk.vtkPolyData()
            polydata.SetPoints(points)
            polydata.SetLines(lines)
            
            # Create tube filter for better visibility
            tube = vtk.vtkTubeFilter()
            tube.SetInputData(polydata)
            tube.SetRadius(1.5)
            tube.SetNumberOfSides(12)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(tube.GetOutputPort())
            
            self.spline_actor = vtk.vtkActor()
            self.spline_actor.SetMapper(mapper)
            self.spline_actor.GetProperty().SetColor(1.0, 1.0, 0.0)  # Yellow
            
            self.renderer.AddActor(self.spline_actor)
            
        except Exception as e:
            print(f"[CURVED MPR] Visualization error: {e}")
    
    def generate_curved_mpr(
        self,
        slice_size: float = 100.0,
        num_slices: Optional[int] = None
    ) -> Optional[vtk.vtkImageData]:
        """
        Generate curved MPR from the current path.
        
        Args:
            slice_size: Size of each slice in mm
            num_slices: Number of slices (default: auto)
            
        Returns:
            Curved MPR volume or None if insufficient points
        """
        if len(self.path_points) < 2:
            print("[CURVED MPR] Need at least 2 points")
            return None
        
        self.generator.set_centerline(self.path_points)
        return self.generator.generate_curved_mpr(
            slice_width=slice_size,
            slice_height=slice_size,
            num_slices=num_slices
        )


# =============================================================================
# MandibularUnfoldingModule: 2D Unwrapping for CBCT Dental Images
# =============================================================================

class MandibularUnfoldingModule:
    """
    Specialized module for unwrapping mandibular arch in CBCT images.
    
    This creates a 2D panoramic-like image by:
    1. Following the mandibular arch curve (inferior border or canal)
    2. Sampling perpendicular planes at each curve point
    3. Creating a straightened 2D image where:
       - Horizontal axis = distance along arch
       - Vertical axis = perpendicular distance from arch
    
    This is the dental equivalent of vessel straightening.
    """
    
    def __init__(self, image_data: vtk.vtkImageData):
        """
        Initialize mandibular unfolding module.
        
        Args:
            image_data: Input CBCT volume
        """
        self.image_data = image_data
        self.spacing = image_data.GetSpacing()
        self.path = None
        self.unfolded_image = None
    
    def set_arch_curve(self, points: List[Tuple[float, float, float]]):
        """
        Set the mandibular arch curve.
        
        Points should follow the inferior border of mandible or
        the mandibular canal centerline.
        
        Args:
            points: List of 3D points defining the arch
        """
        if len(points) < 3:
            raise ValueError("Mandibular arch requires at least 3 points")
        
        self.path = Path3D(points, tension=0.5)
        
        print(f"[MANDIBULAR UNFOLDING] Arch curve set: "
              f"{len(points)} points, length: {self.path.total_length:.1f} mm")
    
    def generate_panoramic_unfold(
        self,
        height_mm: float = 60.0,
        width_samples: Optional[int] = None,
        height_samples: int = 200,
        output_spacing: Optional[float] = None
    ) -> vtk.vtkImageData:
        """
        Generate panoramic unfolded image.
        
        Creates a 2D image where:
        - X-axis: distance along mandibular arch (straightened)
        - Y-axis: superior-inferior extent (perpendicular to arch)
        
        Args:
            height_mm: Vertical extent to sample (mm) above and below curve
            width_samples: Number of samples along arch (default: auto)
            height_samples: Number of samples perpendicular to arch
            output_spacing: Output pixel spacing (default: min input spacing)
            
        Returns:
            2D panoramic image as vtkImageData
        """
        if self.path is None:
            raise ValueError("Must call set_arch_curve() first")
        
        # Determine output spacing
        if output_spacing is None:
            output_spacing = min(self.spacing)
        
        # Determine width samples (along arch)
        if width_samples is None:
            # Sample at approximately 1 sample per mm
            width_samples = max(100, int(self.path.total_length / output_spacing))
        
        print(f"[MANDIBULAR UNFOLDING] Generating panoramic: "
              f"{width_samples}x{height_samples} pixels, "
              f"height: {height_mm:.1f}mm")
        
        # Generate frames along the path
        plane_generator = PlaneGenerator(self.path)
        frames = plane_generator.generate_frames(width_samples)
        
        # Sample perpendicular to each frame
        panoramic_data = self._sample_panoramic(
            frames, height_mm, height_samples, output_spacing
        )
        
        self.unfolded_image = panoramic_data
        
        return panoramic_data
    
    def _sample_panoramic(
        self,
        frames: List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
        height_mm: float,
        height_samples: int,
        output_spacing: float
    ) -> vtk.vtkImageData:
        """
        Sample volume to create panoramic image.
        
        For each frame (position along arch), samples a vertical line
        perpendicular to the arch.
        
        Args:
            frames: List of (origin, tangent, normal, binormal) frames
            height_mm: Height to sample (total, centered on curve)
            height_samples: Number of vertical samples
            output_spacing: Pixel spacing
            
        Returns:
            2D panoramic image
        """
        from vtkmodules.util import numpy_support
        
        width_samples = len(frames)
        
        # Create output array
        scalar_type = self.image_data.GetScalarType()
        dtype_map = {
            vtk.VTK_CHAR: np.int8,
            vtk.VTK_UNSIGNED_CHAR: np.uint8,
            vtk.VTK_SHORT: np.int16,
            vtk.VTK_UNSIGNED_SHORT: np.uint16,
            vtk.VTK_INT: np.int32,
            vtk.VTK_UNSIGNED_INT: np.uint32,
            vtk.VTK_FLOAT: np.float32,
            vtk.VTK_DOUBLE: np.float64,
        }
        dtype = dtype_map.get(scalar_type, np.float32)
        
        panoramic_array = np.zeros((height_samples, width_samples), dtype=dtype)
        
        # Probe filter for sampling
        probe = vtk.vtkProbeFilter()
        probe.SetSourceData(self.image_data)
        
        # For each column (position along arch)
        for col_idx, (origin, tangent, normal, binormal) in enumerate(frames):
            # Sample along binormal (vertical direction in panoramic image)
            # This typically corresponds to superior-inferior direction
            
            # Create sample points along vertical line
            points = vtk.vtkPoints()
            half_height = height_mm / 2.0
            
            for row_idx in range(height_samples):
                # Vertical offset from curve center
                t = (row_idx / (height_samples - 1)) - 0.5  # Range: -0.5 to 0.5
                offset = t * height_mm
                
                # Sample point = origin + offset * binormal
                sample_point = origin + offset * binormal
                points.InsertNextPoint(sample_point[0], sample_point[1], sample_point[2])
            
            # Create polydata for this vertical line
            polydata = vtk.vtkPolyData()
            polydata.SetPoints(points)
            
            # Probe the volume
            probe.SetInputData(polydata)
            probe.Update()
            
            # Extract values
            sampled_scalars = probe.GetOutput().GetPointData().GetScalars()
            if sampled_scalars:
                values = numpy_support.vtk_to_numpy(sampled_scalars)
                panoramic_array[:, col_idx] = values
        
        # Create output vtkImageData
        output = vtk.vtkImageData()
        output.SetDimensions(width_samples, height_samples, 1)
        output.SetSpacing(output_spacing, output_spacing, 1.0)
        output.SetOrigin(0, 0, 0)
        
        # Convert numpy array to VTK
        flat_array = panoramic_array.flatten(order='F')  # Column-major for VTK
        vtk_array = numpy_support.numpy_to_vtk(flat_array, deep=True)
        vtk_array.SetNumberOfComponents(1)
        
        output.GetPointData().SetScalars(vtk_array)
        
        print(f"[MANDIBULAR UNFOLDING] Panoramic image created: "
              f"{width_samples}x{height_samples}")
        
        return output


# =============================================================================
# MultiPlanarSync: Synchronized Orthogonal Views Along Spline
# =============================================================================

class MultiPlanarSync:
    """
    Provides synchronized multi-planar views along a curved path.
    
    For each position along the spline, generates three orthogonal views:
    1. Axial-like: plane perpendicular to spline (normal × binormal)
    2. Sagittal-like: plane containing tangent and normal (T × N)
    3. Coronal-like: plane containing tangent and binormal (T × B)
    
    When scrolling along the spline, all three views update synchronously.
    """
    
    def __init__(self, image_data: vtk.vtkImageData, path: Path3D):
        """
        Initialize multi-planar synchronization.
        
        Args:
            image_data: Input 3D volume
            path: Path3D object defining the curve
        """
        self.image_data = image_data
        self.path = path
        self.spacing = image_data.GetSpacing()
        self.current_index = 0
        self.frames = []
        self.num_positions = 0
    
    def initialize(self, num_positions: int = 100):
        """
        Initialize frames along the path.
        
        Args:
            num_positions: Number of positions along the path
        """
        self.num_positions = num_positions
        
        # Generate frames
        plane_generator = PlaneGenerator(self.path)
        self.frames = plane_generator.generate_frames(num_positions)
        
        print(f"[MULTI-PLANAR SYNC] Initialized with {len(self.frames)} positions")
    
    def get_slice_at_index(
        self,
        index: int,
        view_type: str,
        slice_size: float = 100.0,
        output_spacing: Optional[float] = None
    ) -> vtk.vtkImageData:
        """
        Get a specific view at a given index along the spline.
        
        Args:
            index: Position index along spline (0 to num_positions-1)
            view_type: Type of view - 'axial', 'sagittal', or 'coronal'
            slice_size: Size of the slice in mm
            output_spacing: Output pixel spacing
            
        Returns:
            2D slice as vtkImageData
        """
        if index < 0 or index >= len(self.frames):
            raise ValueError(f"Index {index} out of range [0, {len(self.frames)-1}]")
        
        if output_spacing is None:
            output_spacing = min(self.spacing)
        
        origin, tangent, normal, binormal = self.frames[index]
        
        # Determine reslice axes based on view type
        if view_type == 'axial':
            # Perpendicular to spline: N × B plane
            x_axis = normal
            y_axis = binormal
            z_axis = tangent  # Plane normal
        elif view_type == 'sagittal':
            # Along spline, one perpendicular: T × N plane
            x_axis = tangent
            y_axis = normal
            z_axis = binormal  # Plane normal
        elif view_type == 'coronal':
            # Along spline, other perpendicular: T × B plane
            x_axis = tangent
            y_axis = binormal
            z_axis = normal  # Plane normal
        else:
            raise ValueError(f"Unknown view type: {view_type}")
        
        # Create reslice
        reslice = vtk.vtkImageReslice()
        reslice.SetInputData(self.image_data)
        reslice.SetOutputDimensionality(2)
        reslice.SetInterpolationModeToCubic()
        
        # Set orientation
        reslice.SetResliceAxesDirectionCosines(
            x_axis[0], x_axis[1], x_axis[2],
            y_axis[0], y_axis[1], y_axis[2],
            z_axis[0], z_axis[1], z_axis[2]
        )
        
        # Set origin
        reslice.SetResliceAxesOrigin(origin[0], origin[1], origin[2])
        
        # Set output extent
        slice_pixels = int(np.ceil(slice_size / output_spacing))
        if slice_pixels % 2 == 1:
            slice_pixels += 1
        
        half_pixels = slice_pixels // 2
        reslice.SetOutputExtent(
            -half_pixels, half_pixels - 1,
            -half_pixels, half_pixels - 1,
            0, 0
        )
        
        # Set spacing
        reslice.SetOutputSpacing(output_spacing, output_spacing, 1.0)
        reslice.SetOutputOrigin(
            -half_pixels * output_spacing,
            -half_pixels * output_spacing,
            0.0
        )
        
        # Execute
        reslice.Update()
        
        # Return deep copy
        output = vtk.vtkImageData()
        output.DeepCopy(reslice.GetOutput())
        
        return output
    
    def get_all_views_at_index(
        self,
        index: int,
        slice_size: float = 100.0
    ) -> dict:
        """
        Get all three orthogonal views at a given position.
        
        Args:
            index: Position index along spline
            slice_size: Size of slices in mm
            
        Returns:
            Dictionary with keys 'axial', 'sagittal', 'coronal'
        """
        return {
            'axial': self.get_slice_at_index(index, 'axial', slice_size),
            'sagittal': self.get_slice_at_index(index, 'sagittal', slice_size),
            'coronal': self.get_slice_at_index(index, 'coronal', slice_size)
        }
    
    def scroll_to_index(self, index: int):
        """
        Update current position.
        
        Args:
            index: New position index
        """
        if 0 <= index < len(self.frames):
            self.current_index = index
    
    def scroll_by_delta(self, delta: int):
        """
        Scroll by relative amount.
        
        Args:
            delta: Number of positions to move (+/-)
        """
        new_index = self.current_index + delta
        new_index = max(0, min(new_index, len(self.frames) - 1))
        self.current_index = new_index


# =============================================================================
# Utility Functions
# =============================================================================

def create_vessel_curved_mpr(
    image_data: vtk.vtkImageData,
    vessel_mask: vtk.vtkImageData,
    start_seed: Tuple[int, int, int]
) -> vtk.vtkImageData:
    """
    Create curved MPR along a vessel centerline.
    
    Note: This is a placeholder. For production use, extract the
    centerline using VMTK or similar tools.
    
    Args:
        image_data: Input CT/MRA volume
        vessel_mask: Binary mask of the vessel
        start_seed: Starting point in the vessel
        
    Returns:
        Curved MPR volume
    """
    # In production, you would:
    # 1. Extract surface from vessel_mask using vtkMarchingCubes
    # 2. Use VMTK to compute centerlines
    # 3. Pass centerline points to CurvedMPRGenerator
    
    generator = CurvedMPRGenerator(image_data)
    
    # Placeholder: create simple path
    dims = image_data.GetDimensions()
    spacing = image_data.GetSpacing()
    origin = image_data.GetOrigin()
    
    # Convert voxel coordinates to world coordinates
    x = origin[0] + start_seed[0] * spacing[0]
    y = origin[1] + start_seed[1] * spacing[1]
    
    simple_path = []
    for z_idx in range(start_seed[2], dims[2], 5):
        z = origin[2] + z_idx * spacing[2]
        simple_path.append((x, y, z))
    
    if len(simple_path) < 2:
        return None
    
    generator.set_centerline(simple_path)
    return generator.generate_curved_mpr()


def create_mandibular_panoramic(
    image_data: vtk.vtkImageData,
    arch_points: List[Tuple[float, float, float]],
    height_mm: float = 60.0,
    width_samples: Optional[int] = None,
    height_samples: int = 200
) -> vtk.vtkImageData:
    """
    Create panoramic mandibular unfolding for CBCT.
    
    This straightens the mandibular arch into a 2D panoramic-like view,
    useful for dental implant planning and mandibular canal assessment.
    
    Args:
        image_data: Input CBCT volume
        arch_points: Points along mandible (inferior border or canal)
        height_mm: Vertical extent above/below arch (default: 60mm)
        width_samples: Number of samples along arch (default: auto)
        height_samples: Number of vertical samples (default: 200)
        
    Returns:
        2D panoramic unfolded image
    
    Example:
        # Define arch points (can be manually clicked or auto-extracted)
        arch_points = [
            (x1, y1, z1),  # Right condyle
            (x2, y2, z2),  # Right angle
            ...
            (xn, yn, zn)   # Left condyle
        ]
        panoramic = create_mandibular_panoramic(cbct_volume, arch_points)
    """
    unfolder = MandibularUnfoldingModule(image_data)
    unfolder.set_arch_curve(arch_points)
    
    return unfolder.generate_panoramic_unfold(
        height_mm=height_mm,
        width_samples=width_samples,
        height_samples=height_samples
    )


def create_synchronized_mpr_views(
    image_data: vtk.vtkImageData,
    path_points: List[Tuple[float, float, float]],
    num_positions: int = 100,
    slice_size: float = 100.0
) -> MultiPlanarSync:
    """
    Create synchronized multi-planar views along a path.
    
    This allows scrolling through the volume along a curved path
    with three synchronized orthogonal views at each position.
    
    Args:
        image_data: Input 3D volume
        path_points: Points defining the path
        num_positions: Number of positions along path
        slice_size: Size of each view in mm
        
    Returns:
        MultiPlanarSync object for interactive viewing
    
    Example:
        # Create synchronized views
        sync_views = create_synchronized_mpr_views(
            ct_volume, 
            vessel_centerline,
            num_positions=150
        )
        
        # Get all views at position 50
        views = sync_views.get_all_views_at_index(50)
        axial_view = views['axial']
        sagittal_view = views['sagittal']
        coronal_view = views['coronal']
        
        # Scroll through
        for i in range(sync_views.num_positions):
            views = sync_views.get_all_views_at_index(i)
            # Display views...
    """
    path = Path3D(path_points)
    sync = MultiPlanarSync(image_data, path)
    sync.initialize(num_positions)
    
    return sync
