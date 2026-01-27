"""
Surface Reconstruction Tools
============================

This module provides surface reconstruction for medical imaging:
- Marching Cubes / Flying Edges
- Surface smoothing and decimation
- Multiple tissue types (bone, muscle, organs)
- Quality optimization

Based on VTK surface extraction algorithms.
"""

import vtkmodules.all as vtk
from typing import Optional, Tuple, Literal, List, Dict
import numpy as np


class SurfaceReconstructor:
    """
    3D surface reconstruction from medical images
    """
    
    def __init__(self, image_data: vtk.vtkImageData):
        """
        Initialize surface reconstructor
        
        Args:
            image_data: Input image data
        """
        self.image_data = image_data
        self.scalar_range = image_data.GetScalarRange()
    
    def extract_surface(
        self,
        threshold: float,
        use_flying_edges: bool = True
    ) -> vtk.vtkPolyData:
        """
        Extract isosurface at given threshold
        
        Args:
            threshold: Iso-value for surface extraction
            use_flying_edges: Use Flying Edges (faster) vs Marching Cubes
            
        Returns:
            Surface polydata
        """
        if use_flying_edges:
            surface_filter = vtk.vtkFlyingEdges3D()
        else:
            surface_filter = vtk.vtkMarchingCubes()
        
        surface_filter.SetInputData(self.image_data)
        surface_filter.SetValue(0, threshold)
        surface_filter.ComputeNormalsOn()
        surface_filter.Update()
        
        return surface_filter.GetOutput()
    
    def extract_bone_surface(
        self,
        hu_threshold: float = 300.0,
        smooth: bool = True,
        smooth_iterations: int = 50,
        decimate: bool = True,
        target_reduction: float = 0.5
    ) -> vtk.vtkPolyData:
        """
        Extract bone surface from CT
        
        Args:
            hu_threshold: HU threshold for bone
            smooth: Apply smoothing
            smooth_iterations: Number of smoothing iterations
            decimate: Apply decimation
            target_reduction: Decimation target (0-1)
            
        Returns:
            Bone surface mesh
        """
        # Extract surface
        surface = self.extract_surface(hu_threshold, use_flying_edges=True)
        
        # Clean polydata
        cleaner = vtk.vtkCleanPolyData()
        cleaner.SetInputData(surface)
        cleaner.Update()
        surface = cleaner.GetOutput()
        
        # Smooth
        if smooth:
            surface = self._smooth_surface(surface, smooth_iterations)
        
        # Decimate
        if decimate:
            surface = self._decimate_surface(surface, target_reduction)
        
        # Compute normals
        surface = self._compute_normals(surface)
        
        return surface
    
    def extract_muscle_surface(
        self,
        hu_range: Tuple[float, float] = (10, 60),
        smooth: bool = True,
        smooth_iterations: int = 30
    ) -> vtk.vtkPolyData:
        """
        Extract muscle surface from CT
        
        Args:
            hu_range: HU range for muscle
            smooth: Apply smoothing
            smooth_iterations: Number of smoothing iterations
            
        Returns:
            Muscle surface mesh
        """
        # Threshold to isolate muscle
        threshold = vtk.vtkImageThreshold()
        threshold.SetInputData(self.image_data)
        threshold.ThresholdBetween(hu_range[0], hu_range[1])
        threshold.SetInValue(1)
        threshold.SetOutValue(0)
        # SetOutputScalarTypeToUnsignedChar() removed in VTK 9.x - type is auto-set
        threshold.Update()
        
        # Extract surface
        surface_filter = vtk.vtkFlyingEdges3D()
        surface_filter.SetInputData(threshold.GetOutput())
        surface_filter.SetValue(0, 0.5)
        surface_filter.Update()
        
        surface = surface_filter.GetOutput()
        
        # Clean
        cleaner = vtk.vtkCleanPolyData()
        cleaner.SetInputData(surface)
        cleaner.Update()
        surface = cleaner.GetOutput()
        
        # Smooth
        if smooth:
            surface = self._smooth_surface(surface, smooth_iterations, method="sinc")
        
        # Normals
        surface = self._compute_normals(surface)
        
        return surface
    
    def extract_organ_surface(
        self,
        mask: vtk.vtkImageData,
        smooth: bool = True,
        smooth_iterations: int = 40,
        target_reduction: float = 0.6
    ) -> vtk.vtkPolyData:
        """
        Extract organ surface from binary mask
        
        Args:
            mask: Binary mask of organ
            smooth: Apply smoothing
            smooth_iterations: Number of iterations
            target_reduction: Decimation target
            
        Returns:
            Organ surface mesh
        """
        # Extract surface
        surface_filter = vtk.vtkFlyingEdges3D()
        surface_filter.SetInputData(mask)
        surface_filter.SetValue(0, 0.5)
        surface_filter.Update()
        
        surface = surface_filter.GetOutput()
        
        # Clean
        cleaner = vtk.vtkCleanPolyData()
        cleaner.SetInputData(surface)
        cleaner.Update()
        surface = cleaner.GetOutput()
        
        # Smooth (organs need more smoothing)
        if smooth:
            surface = self._smooth_surface(
                surface,
                smooth_iterations,
                method="sinc",
                pass_band=0.05
            )
        
        # Decimate
        if target_reduction > 0:
            surface = self._decimate_surface(surface, target_reduction)
        
        # Normals
        surface = self._compute_normals(surface)
        
        return surface
    
    def _smooth_surface(
        self,
        surface: vtk.vtkPolyData,
        iterations: int,
        method: Literal["laplacian", "sinc"] = "laplacian",
        pass_band: float = 0.1
    ) -> vtk.vtkPolyData:
        """
        Smooth surface mesh
        
        Args:
            surface: Input surface
            iterations: Number of iterations
            method: Smoothing method
            pass_band: Pass band for sinc filter
            
        Returns:
            Smoothed surface
        """
        if method == "laplacian":
            smoother = vtk.vtkSmoothPolyDataFilter()
            smoother.SetInputData(surface)
            smoother.SetNumberOfIterations(iterations)
            smoother.SetRelaxationFactor(0.1)
            smoother.FeatureEdgeSmoothingOn()
            smoother.BoundarySmoothingOn()
            smoother.Update()
        else:  # sinc
            smoother = vtk.vtkWindowedSincPolyDataFilter()
            smoother.SetInputData(surface)
            smoother.SetNumberOfIterations(iterations)
            smoother.BoundarySmoothingOn()
            smoother.FeatureEdgeSmoothingOff()
            smoother.SetPassBand(pass_band)
            smoother.NonManifoldSmoothingOn()
            smoother.NormalizeCoordinatesOn()
            smoother.Update()
        
        return smoother.GetOutput()
    
    def _decimate_surface(
        self,
        surface: vtk.vtkPolyData,
        target_reduction: float
    ) -> vtk.vtkPolyData:
        """
        Decimate surface to reduce polygon count
        
        Args:
            surface: Input surface
            target_reduction: Reduction ratio (0-1)
            
        Returns:
            Decimated surface
        """
        decimate = vtk.vtkQuadricDecimation()
        decimate.SetInputData(surface)
        decimate.SetTargetReduction(target_reduction)
        decimate.Update()
        
        return decimate.GetOutput()
    
    def _compute_normals(self, surface: vtk.vtkPolyData) -> vtk.vtkPolyData:
        """
        Compute surface normals
        
        Args:
            surface: Input surface
            
        Returns:
            Surface with normals
        """
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(surface)
        normals.ComputePointNormalsOn()
        normals.ComputeCellNormalsOn()
        normals.SplittingOff()
        normals.ConsistencyOn()
        normals.AutoOrientNormalsOn()
        normals.Update()
        
        return normals.GetOutput()


class MultiTissueSurfaceExtractor:
    """
    Extract multiple tissue surfaces from single CT scan
    """
    
    def __init__(self, image_data: vtk.vtkImageData):
        """
        Initialize multi-tissue extractor
        
        Args:
            image_data: Input CT image data
        """
        self.image_data = image_data
        self.reconstructor = SurfaceReconstructor(image_data)
        self.surfaces = {}
    
    def extract_all_tissues(
        self,
        tissues: List[Literal["bone", "muscle", "skin"]] = ["bone", "muscle", "skin"]
    ) -> Dict[str, vtk.vtkPolyData]:
        """
        Extract multiple tissue surfaces
        
        Args:
            tissues: List of tissues to extract
            
        Returns:
            Dictionary of tissue name to surface
        """
        if "bone" in tissues:
            self.surfaces["bone"] = self.reconstructor.extract_bone_surface(
                hu_threshold=300,
                smooth=True,
                decimate=True,
                target_reduction=0.5
            )
        
        if "muscle" in tissues:
            self.surfaces["muscle"] = self.reconstructor.extract_muscle_surface(
                hu_range=(10, 60),
                smooth=True
            )
        
        if "skin" in tissues:
            self.surfaces["skin"] = self.reconstructor.extract_surface(
                threshold=-100,  # Approximate skin boundary
                use_flying_edges=True
            )
            # Smooth skin heavily
            self.surfaces["skin"] = self.reconstructor._smooth_surface(
                self.surfaces["skin"],
                iterations=100,
                method="sinc"
            )
        
        return self.surfaces
    
    def create_colored_actors(self) -> Dict[str, vtk.vtkActor]:
        """
        Create colored actors for each tissue
        
        Returns:
            Dictionary of tissue name to actor
        """
        colors = {
            "bone": (0.95, 0.95, 0.85),  # Ivory
            "muscle": (0.7, 0.3, 0.3),   # Red-brown
            "skin": (0.9, 0.75, 0.65),   # Peach
        }
        
        actors = {}
        
        for tissue_name, surface in self.surfaces.items():
            # Create mapper
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(surface)
            mapper.ScalarVisibilityOff()
            
            # Create actor
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            
            # Set color
            if tissue_name in colors:
                actor.GetProperty().SetColor(colors[tissue_name])
            
            # Set properties
            actor.GetProperty().SetSpecular(0.3)
            actor.GetProperty().SetSpecularPower(20)
            
            # Transparency for non-bone
            if tissue_name != "bone":
                actor.GetProperty().SetOpacity(0.7)
            
            actors[tissue_name] = actor
        
        return actors


class SurfaceQualityOptimizer:
    """
    Optimize surface quality for rendering and analysis
    """
    
    @staticmethod
    def optimize_for_rendering(
        surface: vtk.vtkPolyData,
        target_polygons: int = 100000
    ) -> vtk.vtkPolyData:
        """
        Optimize surface for real-time rendering
        
        Args:
            surface: Input surface
            target_polygons: Target polygon count
            
        Returns:
            Optimized surface
        """
        current_polygons = surface.GetNumberOfPolys()
        
        if current_polygons > target_polygons:
            reduction = 1.0 - (target_polygons / current_polygons)
            
            decimate = vtk.vtkQuadricDecimation()
            decimate.SetInputData(surface)
            decimate.SetTargetReduction(reduction)
            decimate.Update()
            
            surface = decimate.GetOutput()
        
        # Clean
        cleaner = vtk.vtkCleanPolyData()
        cleaner.SetInputData(surface)
        cleaner.Update()
        
        # Normals
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(cleaner.GetOutput())
        normals.Update()
        
        return normals.GetOutput()
    
    @staticmethod
    def optimize_for_measurement(
        surface: vtk.vtkPolyData
    ) -> vtk.vtkPolyData:
        """
        Optimize surface for accurate measurements
        Minimal decimation, careful smoothing
        
        Args:
            surface: Input surface
            
        Returns:
            Optimized surface
        """
        # Light smoothing only
        smoother = vtk.vtkSmoothPolyDataFilter()
        smoother.SetInputData(surface)
        smoother.SetNumberOfIterations(10)
        smoother.SetRelaxationFactor(0.05)
        smoother.FeatureEdgeSmoothingOn()
        smoother.BoundarySmoothingOn()
        smoother.Update()
        
        # Clean
        cleaner = vtk.vtkCleanPolyData()
        cleaner.SetInputData(smoother.GetOutput())
        cleaner.Update()
        
        # Normals
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(cleaner.GetOutput())
        normals.Update()
        
        return normals.GetOutput()
    
    @staticmethod
    def compute_surface_area(surface: vtk.vtkPolyData) -> float:
        """
        Compute total surface area
        
        Args:
            surface: Input surface
            
        Returns:
            Surface area in mm²
        """
        mass_properties = vtk.vtkMassProperties()
        mass_properties.SetInputData(surface)
        mass_properties.Update()
        
        return mass_properties.GetSurfaceArea()
    
    @staticmethod
    def compute_volume(surface: vtk.vtkPolyData) -> float:
        """
        Compute enclosed volume
        
        Args:
            surface: Input surface
            
        Returns:
            Volume in mm³
        """
        mass_properties = vtk.vtkMassProperties()
        mass_properties.SetInputData(surface)
        mass_properties.Update()
        
        return mass_properties.GetVolume()


def create_bone_actor(
    surface: vtk.vtkPolyData,
    color: Tuple[float, float, float] = (0.95, 0.95, 0.85)
) -> vtk.vtkActor:
    """
    Create actor for bone surface with appropriate properties
    
    Args:
        surface: Bone surface
        color: RGB color
        
    Returns:
        Configured actor
    """
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(surface)
    mapper.ScalarVisibilityOff()
    
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(color)
    actor.GetProperty().SetSpecular(0.4)
    actor.GetProperty().SetSpecularPower(30)
    actor.GetProperty().SetDiffuse(0.7)
    actor.GetProperty().SetAmbient(0.2)
    
    return actor


def create_transparent_organ_actor(
    surface: vtk.vtkPolyData,
    color: Tuple[float, float, float] = (0.8, 0.4, 0.4),
    opacity: float = 0.6
) -> vtk.vtkActor:
    """
    Create transparent actor for organ surface
    
    Args:
        surface: Organ surface
        color: RGB color
        opacity: Opacity (0-1)
        
    Returns:
        Configured actor
    """
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(surface)
    mapper.ScalarVisibilityOff()
    
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(color)
    actor.GetProperty().SetOpacity(opacity)
    actor.GetProperty().SetSpecular(0.2)
    actor.GetProperty().SetSpecularPower(15)
    
    return actor

