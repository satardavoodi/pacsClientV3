"""
Medical Image Segmentation Tools
=================================

This module provides segmentation tools for medical imaging:
- Lung segmentation (threshold + region growing)
- Airway tree extraction
- Vessel segmentation
- Bone/tissue segmentation
- Connected component analysis

Based on VTK algorithms and medical imaging best practices.
"""

import vtkmodules.all as vtk
from typing import Optional, List, Tuple, Dict
import numpy as np


class LungSegmenter:
    """
    Lung segmentation from chest CT using threshold and region growing
    """
    
    def __init__(self, image_data: vtk.vtkImageData):
        """
        Initialize lung segmenter
        
        Args:
            image_data: Input CT image data
        """
        self.image_data = image_data
        self.lung_mask = None
        self.scalar_range = image_data.GetScalarRange()
    
    def segment_lungs(
        self,
        hu_range: Tuple[float, float] = (-1000, -300),
        seed_points: Optional[List[Tuple[int, int, int]]] = None,
        auto_find_seeds: bool = True
    ) -> vtk.vtkImageData:
        """
        Segment lung parenchyma
        
        Args:
            hu_range: HU range for lung tissue
            seed_points: Optional seed points (x, y, z) in image coordinates
            auto_find_seeds: Automatically find seed points if not provided
            
        Returns:
            Binary mask of lungs
        """
        # Step 1: Threshold
        threshold = vtk.vtkImageThreshold()
        threshold.SetInputData(self.image_data)
        threshold.ThresholdBetween(hu_range[0], hu_range[1])
        threshold.SetInValue(1)
        threshold.SetOutValue(0)
        # SetOutputScalarTypeToUnsignedChar() removed in VTK 9.x - type is auto-set
        threshold.Update()
        
        # Step 2: Region growing with connectivity
        if seed_points is None and auto_find_seeds:
            seed_points = self._auto_find_lung_seeds()
        
        if seed_points and len(seed_points) > 0:
            connectivity = vtk.vtkImageThresholdConnectivity()
            connectivity.SetInputData(self.image_data)
            connectivity.ThresholdBetween(hu_range[0], hu_range[1])
            
            # Add seed points - compatible with both old and new VTK API
            for seed in seed_points:
                try:
                    # Try new API first (VTK 9.x+)
                    connectivity.SetSeedPoint(seed[0], seed[1], seed[2])
                except AttributeError:
                    try:
                        # Fall back to old API (VTK 8.x)
                        connectivity.AddSeed(seed[0], seed[1], seed[2])
                    except AttributeError:
                        # If both fail, use vtkPoints
                        points = vtk.vtkPoints()
                        for s in seed_points:
                            points.InsertNextPoint(s[0], s[1], s[2])
                        connectivity.SetSeedPoints(points)
                        break
            
            connectivity.ReplaceInOn()
            connectivity.SetInValue(1)
            connectivity.ReplaceOutOn()
            connectivity.SetOutValue(0)
            # SetOutputScalarTypeToUnsignedChar() removed in VTK 9.x - type is auto-set
            connectivity.Update()
            
            self.lung_mask = connectivity.GetOutput()
        else:
            # No connectivity, just threshold
            self.lung_mask = threshold.GetOutput()
        
        return self.lung_mask
    
    def _auto_find_lung_seeds(self) -> List[Tuple[int, int, int]]:
        """
        Automatically find seed points in lungs
        
        Returns:
            List of seed points
        """
        dims = self.image_data.GetDimensions()
        
        # Simple heuristic: seeds at mid-height, left and right sides
        mid_z = dims[2] // 2
        mid_y = dims[1] // 2
        
        left_seed = (dims[0] // 4, mid_y, mid_z)
        right_seed = (3 * dims[0] // 4, mid_y, mid_z)
        
        seeds = []
        
        # Verify seeds are in lung range
        for seed in [left_seed, right_seed]:
            value = self.image_data.GetScalarComponentAsFloat(
                seed[0], seed[1], seed[2], 0
            )
            if -1000 < value < -300:  # Lung HU range
                seeds.append(seed)
        
        return seeds if seeds else [(dims[0]//2, mid_y, mid_z)]
    
    def compute_lung_density_map(self) -> Dict[str, float]:
        """
        Compute lung density statistics
        
        Returns:
            Dictionary with density statistics
        """
        if self.lung_mask is None:
            raise ValueError("Must segment lungs first")
        
        # Count voxels in mask using NumPy
        import numpy as np
        from vtkmodules.util import numpy_support
        
        mask_array = numpy_support.vtk_to_numpy(self.lung_mask.GetPointData().GetScalars())
        image_array = numpy_support.vtk_to_numpy(self.image_data.GetPointData().GetScalars())
        
        # Get only lung voxels (where mask > 0)
        lung_voxels = image_array[mask_array > 0]
        
        if len(lung_voxels) == 0:
            return {
                "mean_hu": 0.0,
                "std_hu": 0.0,
                "min_hu": 0.0,
                "max_hu": 0.0,
                "voxel_count": 0
            }
        
        stats = {
            "mean_hu": float(np.mean(lung_voxels)),
            "std_hu": float(np.std(lung_voxels)),
            "min_hu": float(np.min(lung_voxels)),
            "max_hu": float(np.max(lung_voxels)),
            "voxel_count": int(len(lung_voxels))
        }
        
        return stats
    
    def _mask_to_stencil(self, mask: vtk.vtkImageData) -> vtk.vtkImageStencilData:
        """Convert binary mask to stencil"""
        to_stencil = vtk.vtkImageToImageStencil()
        to_stencil.SetInputData(mask)
        to_stencil.ThresholdByUpper(0.5)
        to_stencil.Update()
        return to_stencil.GetOutput()
    
    def create_surface_mesh(
        self,
        smooth: bool = True,
        decimation: float = 0.5
    ) -> vtk.vtkPolyData:
        """
        Create surface mesh from lung mask
        
        Args:
            smooth: Apply smoothing
            decimation: Decimation factor (0-1, lower = more reduction)
            
        Returns:
            Surface mesh
        """
        if self.lung_mask is None:
            raise ValueError("Must segment lungs first")
        
        # Marching cubes
        surface = vtk.vtkFlyingEdges3D()
        surface.SetInputData(self.lung_mask)
        surface.SetValue(0, 0.5)
        surface.Update()
        
        poly_data = surface.GetOutput()
        
        # Smooth if requested
        if smooth:
            smoother = vtk.vtkWindowedSincPolyDataFilter()
            smoother.SetInputData(poly_data)
            smoother.SetNumberOfIterations(20)
            smoother.BoundarySmoothingOn()
            smoother.FeatureEdgeSmoothingOff()
            smoother.SetPassBand(0.1)
            smoother.NonManifoldSmoothingOn()
            smoother.NormalizeCoordinatesOn()
            smoother.Update()
            poly_data = smoother.GetOutput()
        
        # Decimate if requested
        if decimation < 1.0:
            decimate = vtk.vtkQuadricDecimation()
            decimate.SetInputData(poly_data)
            decimate.SetTargetReduction(1.0 - decimation)
            decimate.Update()
            poly_data = decimate.GetOutput()
        
        # Compute normals
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(poly_data)
        normals.ComputePointNormalsOn()
        normals.ComputeCellNormalsOn()
        normals.Update()
        
        return normals.GetOutput()


class AirwaySegmenter:
    """
    Airway tree extraction from chest CT
    """
    
    def __init__(self, image_data: vtk.vtkImageData):
        """
        Initialize airway segmenter
        
        Args:
            image_data: Input CT image data
        """
        self.image_data = image_data
        self.airway_mask = None
    
    def segment_airways(
        self,
        hu_range: Tuple[float, float] = (-1024, -950),
        trachea_seed: Optional[Tuple[int, int, int]] = None,
        auto_find_seed: bool = True
    ) -> vtk.vtkImageData:
        """
        Segment airway tree starting from trachea
        
        Args:
            hu_range: HU range for air
            trachea_seed: Seed point in trachea
            auto_find_seed: Automatically find trachea seed
            
        Returns:
            Binary mask of airways
        """
        if trachea_seed is None and auto_find_seed:
            trachea_seed = self._auto_find_trachea_seed()
        
        if trachea_seed is None:
            raise ValueError("Could not find trachea seed point")
        
        # Connected threshold starting from trachea
        connectivity = vtk.vtkImageThresholdConnectivity()
        connectivity.SetInputData(self.image_data)
        connectivity.ThresholdBetween(hu_range[0], hu_range[1])
        
        # Add seed point - compatible with both old and new VTK API
        try:
            # Try new API first (VTK 9.x+)
            connectivity.SetSeedPoint(trachea_seed[0], trachea_seed[1], trachea_seed[2])
        except AttributeError:
            try:
                # Fall back to old API (VTK 8.x)
                connectivity.AddSeed(trachea_seed[0], trachea_seed[1], trachea_seed[2])
            except AttributeError:
                # If both fail, use vtkPoints
                points = vtk.vtkPoints()
                points.InsertNextPoint(trachea_seed[0], trachea_seed[1], trachea_seed[2])
                connectivity.SetSeedPoints(points)
        
        connectivity.ReplaceInOn()
        connectivity.SetInValue(1)
        connectivity.ReplaceOutOn()
        connectivity.SetOutValue(0)
        # SetOutputScalarTypeToUnsignedChar() removed in VTK 9.x - type is auto-set
        connectivity.Update()
        
        self.airway_mask = connectivity.GetOutput()
        return self.airway_mask
    
    def _auto_find_trachea_seed(self) -> Optional[Tuple[int, int, int]]:
        """
        Automatically find seed point in trachea
        
        Returns:
            Seed point or None
        """
        dims = self.image_data.GetDimensions()
        
        # Search in upper-middle region (trachea location)
        center_x = dims[0] // 2
        upper_z = int(dims[2] * 0.75)  # Upper quarter
        
        # Scan in Y direction to find air-filled structure (trachea)
        for y in range(dims[1] // 4, 3 * dims[1] // 4):
            value = self.image_data.GetScalarComponentAsFloat(
                center_x, y, upper_z, 0
            )
            if -1024 < value < -950:  # Air
                return (center_x, y, upper_z)
        
        # Fallback: center-upper
        return (center_x, dims[1] // 2, upper_z)
    
    def create_centerline(self) -> vtk.vtkPolyData:
        """
        Extract centerline of airway tree
        Note: This is a simplified version. For production,
        consider using VMTK (vmtkcenterlines)
        
        Returns:
            Centerline polydata
        """
        if self.airway_mask is None:
            raise ValueError("Must segment airways first")
        
        # Create surface
        surface = vtk.vtkFlyingEdges3D()
        surface.SetInputData(self.airway_mask)
        surface.SetValue(0, 0.5)
        surface.Update()
        
        # Skeleton (simplified - for full centerline use VMTK)
        # This is a placeholder for demonstration
        return surface.GetOutput()


class VesselSegmenter:
    """
    Blood vessel segmentation from CTA/MRA
    """
    
    def __init__(self, image_data: vtk.vtkImageData):
        """
        Initialize vessel segmenter
        
        Args:
            image_data: Input CTA/MRA image data
        """
        self.image_data = image_data
        self.vessel_mask = None
    
    def segment_vessels(
        self,
        intensity_range: Tuple[float, float] = (150, 800),
        seed_points: Optional[List[Tuple[int, int, int]]] = None
    ) -> vtk.vtkImageData:
        """
        Segment contrast-enhanced vessels
        
        Args:
            intensity_range: Intensity range for vessels (HU for CT)
            seed_points: Optional seed points in vessels
            
        Returns:
            Binary mask of vessels
        """
        if seed_points is None or len(seed_points) == 0:
            # Simple threshold without connectivity
            threshold = vtk.vtkImageThreshold()
            threshold.SetInputData(self.image_data)
            threshold.ThresholdBetween(intensity_range[0], intensity_range[1])
            threshold.SetInValue(1)
            threshold.SetOutValue(0)
            # SetOutputScalarTypeToUnsignedChar() removed in VTK 9.x - type is auto-set
            threshold.Update()
            
            self.vessel_mask = threshold.GetOutput()
        else:
            # With connectivity
            connectivity = vtk.vtkImageThresholdConnectivity()
            connectivity.SetInputData(self.image_data)
            connectivity.ThresholdBetween(intensity_range[0], intensity_range[1])
            
            # Add seed points - compatible with both old and new VTK API
            for seed in seed_points:
                try:
                    # Try new API first (VTK 9.x+)
                    connectivity.SetSeedPoint(seed[0], seed[1], seed[2])
                except AttributeError:
                    try:
                        # Fall back to old API (VTK 8.x)
                        connectivity.AddSeed(seed[0], seed[1], seed[2])
                    except AttributeError:
                        # If both fail, use vtkPoints
                        points = vtk.vtkPoints()
                        for s in seed_points:
                            points.InsertNextPoint(s[0], s[1], s[2])
                        connectivity.SetSeedPoints(points)
                        break
            
            connectivity.ReplaceInOn()
            connectivity.SetInValue(1)
            connectivity.ReplaceOutOn()
            connectivity.SetOutValue(0)
            # SetOutputScalarTypeToUnsignedChar() removed in VTK 9.x - type is auto-set
            connectivity.Update()
            
            self.vessel_mask = connectivity.GetOutput()
        
        return self.vessel_mask
    
    def enhance_vessels_frangi(
        self,
        sigma_range: Tuple[float, float] = (0.5, 3.0),
        num_sigma_steps: int = 5
    ) -> vtk.vtkImageData:
        """
        Enhance vessels using Frangi vesselness filter
        Note: This requires scipy/scikit-image for full implementation
        This is a placeholder showing the concept
        
        Args:
            sigma_range: Range of scales to detect
            num_sigma_steps: Number of scales
            
        Returns:
            Enhanced image
        """
        # This is a simplified version
        # For full Frangi filter, use scikit-image:
        # from skimage.filters import frangi
        
        # Apply simple gradient magnitude as approximation
        gradient = vtk.vtkImageGradientMagnitude()
        gradient.SetInputData(self.image_data)
        gradient.SetDimensionality(3)
        gradient.Update()
        
        return gradient.GetOutput()


class BoneSegmenter:
    """
    Bone segmentation for orthopedic applications
    """
    
    def __init__(self, image_data: vtk.vtkImageData):
        """
        Initialize bone segmenter
        
        Args:
            image_data: Input CT image data
        """
        self.image_data = image_data
        self.bone_mask = None
    
    def segment_bone(
        self,
        hu_threshold: float = 250.0,
        remove_small_objects: bool = True,
        min_size: int = 1000
    ) -> vtk.vtkImageData:
        """
        Segment bone tissue
        
        Args:
            hu_threshold: HU threshold for bone
            remove_small_objects: Remove small disconnected components
            min_size: Minimum size in voxels
            
        Returns:
            Binary mask of bone
        """
        # Threshold
        threshold = vtk.vtkImageThreshold()
        threshold.SetInputData(self.image_data)
        threshold.ThresholdByUpper(hu_threshold)
        threshold.SetInValue(1)
        threshold.SetOutValue(0)
        # SetOutputScalarTypeToUnsignedChar() removed in VTK 9.x - type is auto-set
        threshold.Update()
        
        bone_mask = threshold.GetOutput()
        
        # Remove small objects
        if remove_small_objects:
            connectivity = vtk.vtkImageConnectivityFilter()
            connectivity.SetInputData(bone_mask)
            connectivity.SetExtractionModeToLargestRegion()
            connectivity.Update()
            bone_mask = connectivity.GetOutput()
        
        self.bone_mask = bone_mask
        return bone_mask
    
    def create_3d_model(
        self,
        smooth: bool = True,
        decimation: float = 0.7
    ) -> vtk.vtkPolyData:
        """
        Create 3D surface model of bone
        
        Args:
            smooth: Apply smoothing
            decimation: Decimation factor
            
        Returns:
            Surface mesh
        """
        if self.bone_mask is None:
            raise ValueError("Must segment bone first")
        
        # Marching cubes
        surface = vtk.vtkFlyingEdges3D()
        surface.SetInputData(self.bone_mask)
        surface.SetValue(0, 0.5)
        surface.Update()
        
        poly_data = surface.GetOutput()
        
        # Smooth
        if smooth:
            smoother = vtk.vtkSmoothPolyDataFilter()
            smoother.SetInputData(poly_data)
            smoother.SetNumberOfIterations(50)
            smoother.SetRelaxationFactor(0.1)
            smoother.FeatureEdgeSmoothingOn()
            smoother.BoundarySmoothingOn()
            smoother.Update()
            poly_data = smoother.GetOutput()
        
        # Decimate
        if decimation < 1.0:
            decimate = vtk.vtkQuadricDecimation()
            decimate.SetInputData(poly_data)
            decimate.SetTargetReduction(1.0 - decimation)
            decimate.Update()
            poly_data = decimate.GetOutput()
        
        # Normals
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(poly_data)
        normals.Update()
        
        return normals.GetOutput()


def create_overlay_mask(
    base_image: vtk.vtkImageData,
    mask: vtk.vtkImageData,
    color: Tuple[float, float, float] = (1.0, 0.0, 0.0),
    opacity: float = 0.5
) -> vtk.vtkImageData:
    """
    Create colored overlay of mask on base image
    
    Args:
        base_image: Base grayscale image
        mask: Binary mask to overlay
        color: RGB color for mask
        opacity: Opacity of overlay
        
    Returns:
        RGB image with overlay
    """
    # This is a simplified version
    # Full implementation would blend images properly
    
    # Convert mask to RGB
    extract = vtk.vtkImageExtractComponents()
    extract.SetInputData(mask)
    extract.SetComponents(0)
    extract.Update()
    
    return extract.GetOutput()

