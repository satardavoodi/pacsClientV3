"""
Thread-safe VTK utilities and memory management for viewer_2d.py
Improvements to add to existing viewer_2d.py
"""
import gc
import logging
import threading
from typing import Optional, List, Tuple
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class ThreadSafeOverlayManager:
    """
    Thread-safe manager for VTK overlays
    Fixes race conditions in overlay management
    """
    
    def __init__(self, renderer: vtk.vtkRenderer):
        """
        Args:
            renderer: VTK renderer
        """
        self.renderer = renderer
        self._overlays: List[Tuple[vtk.vtkImageData, vtk.vtkImageMapToColors, vtk.vtkImageActor]] = []
        self._lock = threading.RLock()
    
    def add_overlay(
        self,
        vtk_image: vtk.vtkImageData,
        map_colors: vtk.vtkImageMapToColors,
        actor: vtk.vtkImageActor
    ):
        """
        Add an overlay
        
        Args:
            vtk_image: VTK image data
            map_colors: Color mapper
            actor: Image actor
        """
        with self._lock:
            self._overlays.append((vtk_image, map_colors, actor))
            self.renderer.AddActor(actor)
            logger.debug(f"Added overlay, total: {len(self._overlays)}")
    
    def remove_overlay(self, index: int) -> bool:
        """
        Remove overlay by index
        
        Args:
            index: Overlay index
        
        Returns:
            True if removed, False if index invalid
        """
        with self._lock:
            if 0 <= index < len(self._overlays):
                _, _, actor = self._overlays.pop(index)
                try:
                    self.renderer.RemoveActor(actor)
                    logger.debug(f"Removed overlay {index}")
                    return True
                except Exception as e:
                    logger.error(f"Error removing overlay actor: {e}")
            return False
    
    def clear_all(self):
        """Remove all overlays"""
        with self._lock:
            for _, _, actor in self._overlays:
                try:
                    self.renderer.RemoveActor(actor)
                except Exception as e:
                    logger.error(f"Error removing overlay: {e}")
            
            self._overlays.clear()
            logger.info("Cleared all overlays")
    
    def sync_extents(self, base_extent: Tuple[int, ...]):
        """
        Synchronize all overlay extents with base image
        
        Args:
            base_extent: Base image display extent
        """
        with self._lock:
            for _, _, actor in self._overlays:
                try:
                    actor.SetDisplayExtent(*base_extent)
                except Exception as e:
                    logger.error(f"Error syncing overlay extent: {e}")
    
    def get_count(self) -> int:
        """Get number of overlays"""
        with self._lock:
            return len(self._overlays)
    
    def __len__(self) -> int:
        """Get overlay count"""
        return self.get_count()


class VTKMemoryManager:
    """
    Manages VTK memory cleanup
    Prevents memory leaks in VTK objects
    """
    
    @staticmethod
    def cleanup_image_data(image_data: Optional[vtk.vtkImageData]):
        """
        Properly cleanup VTK image data
        
        Args:
            image_data: VTK image data to cleanup
        """
        if image_data is None:
            return
        
        try:
            # Release scalars
            point_data = image_data.GetPointData()
            if point_data:
                scalars = point_data.GetScalars()
                if scalars:
                    point_data.SetScalars(None)
                    scalars.Initialize()
            
            # Clear image data
            image_data.Initialize()
            
            logger.debug("Cleaned up VTK image data")
            
        except Exception as e:
            logger.error(f"Error cleaning up image data: {e}")
    
    @staticmethod
    def cleanup_actor(actor: Optional[vtk.vtkActor]):
        """
        Properly cleanup VTK actor
        
        Args:
            actor: VTK actor to cleanup
        """
        if actor is None:
            return
        
        try:
            # Disconnect mapper
            mapper = actor.GetMapper()
            if mapper:
                mapper.SetInputConnection(None)
                mapper.RemoveAllInputs()
            
            actor.SetMapper(None)
            
            logger.debug("Cleaned up VTK actor")
            
        except Exception as e:
            logger.error(f"Error cleaning up actor: {e}")
    
    @staticmethod
    def cleanup_mapper(mapper: Optional[vtk.vtkMapper]):
        """
        Properly cleanup VTK mapper
        
        Args:
            mapper: VTK mapper to cleanup
        """
        if mapper is None:
            return
        
        try:
            mapper.SetInputConnection(None)
            mapper.RemoveAllInputs()
            
            logger.debug("Cleaned up VTK mapper")
            
        except Exception as e:
            logger.error(f"Error cleaning up mapper: {e}")
    
    @staticmethod
    def cleanup_renderer(renderer: Optional[vtk.vtkRenderer]):
        """
        Properly cleanup VTK renderer
        
        Args:
            renderer: VTK renderer to cleanup
        """
        if renderer is None:
            return
        
        try:
            # Remove all actors
            actors = renderer.GetActors()
            if actors:
                actors.InitTraversal()
                actor = actors.GetNextItem()
                while actor:
                    renderer.RemoveActor(actor)
                    actor = actors.GetNextItem()
            
            # Remove all 2D actors
            actors2d = renderer.GetActors2D()
            if actors2d:
                actors2d.InitTraversal()
                actor2d = actors2d.GetNextItem()
                while actor2d:
                    renderer.RemoveViewProp(actor2d)
                    actor2d = actors2d.GetNextItem()
            
            logger.debug("Cleaned up VTK renderer")
            
        except Exception as e:
            logger.error(f"Error cleaning up renderer: {e}")
    
    @staticmethod
    def force_garbage_collection():
        """Force Python garbage collection"""
        collected = gc.collect()
        logger.debug(f"Garbage collected {collected} objects")


class SafeImageGrowth:
    """
    Safe in-place image growth for progressive loading
    Prevents memory corruption and leaks
    """
    
    @staticmethod
    def can_grow_safely(
        old_dims: Tuple[int, int, int],
        new_dims: Tuple[int, int, int]
    ) -> bool:
        """
        Check if image can grow safely
        
        Args:
            old_dims: Old dimensions (nx, ny, nz)
            new_dims: New dimensions (nx, ny, nz)
        
        Returns:
            True if safe to grow
        """
        ox, oy, oz = old_dims
        nx, ny, nz = new_dims
        
        # No growth needed
        if (nx <= ox and ny <= oy and nz <= oz):
            return False
        
        # XY must remain constant (only Z can grow)
        if (ox, oy) != (nx, ny):
            logger.warning(f"Cannot grow: XY dimensions changed from {(ox, oy)} to {(nx, ny)}")
            return False
        
        # Z must only increase
        if nz < oz:
            logger.warning(f"Cannot grow: Z dimension decreased from {oz} to {nz}")
            return False
        
        return True
    
    @staticmethod
    def grow_image_inplace(
        old_image: vtk.vtkImageData,
        new_image: vtk.vtkImageData,
        verify: bool = True
    ) -> bool:
        """
        Grow image in-place safely
        
        Args:
            old_image: Existing image to grow
            new_image: New image with more data
            verify: Verify dimensions before growing
        
        Returns:
            True if grew successfully, False otherwise
        """
        try:
            old_dims = old_image.GetDimensions()
            new_dims = new_image.GetDimensions()
            
            if verify and not SafeImageGrowth.can_grow_safely(old_dims, new_dims):
                return False
            
            # Update spacing and origin if changed
            old_spacing = old_image.GetSpacing()
            new_spacing = new_image.GetSpacing()
            if old_spacing != new_spacing:
                old_image.SetSpacing(new_spacing)
            
            old_origin = old_image.GetOrigin()
            new_origin = new_image.GetOrigin()
            if old_origin != new_origin:
                old_image.SetOrigin(new_origin)
            
            # Update dimensions
            nx, ny, nz = new_dims
            old_image.SetDimensions(nx, ny, nz)
            old_image.SetExtent(0, nx-1, 0, ny-1, 0, nz-1)
            
            # Swap scalars (reference, not copy)
            new_scalars = new_image.GetPointData().GetScalars()
            old_image.GetPointData().SetScalars(new_scalars)
            
            # Mark as modified
            old_image.GetPointData().Modified()
            old_image.Modified()
            
            logger.debug(f"Grew image from {old_dims} to {new_dims}")
            return True
            
        except Exception as e:
            logger.error(f"Error growing image: {e}", exc_info=True)
            return False


# Mixin class to add to ImageViewer2D

class ThreadSafeViewerMixin:
    """
    Mixin to add thread safety to ImageViewer2D
    Add these methods to your existing ImageViewer2D class
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize thread-safe components"""
        super().__init__(*args, **kwargs)
        
        # Replace _overlays with thread-safe manager
        if hasattr(self, 'renderer'):
            self.overlay_manager = ThreadSafeOverlayManager(self.renderer)
        
        # Memory manager
        self.memory_manager = VTKMemoryManager()
        
        # Safe growth helper
        self.safe_growth = SafeImageGrowth()
    
    def overlay_threadsafe(self, path: str, color=(1.0, 1.0, 0.0), opacity=0.4, is_label=True):
        """
        Thread-safe overlay addition
        
        Args:
            path: Path to overlay file
            color: RGB color tuple
            opacity: Opacity value
            is_label: Whether it's a label image
        """
        try:
            from .image_io_improved import read_segment_nifti
            
            # Read overlay
            vtk_image = read_segment_nifti(file=path)
            
            # Create LUT
            lut = vtk.vtkLookupTable()
            lut.SetNumberOfTableValues(256)
            lut.Build()
            
            if is_label:
                lut.SetTableValue(0, 0.0, 0.0, 0.0, 0.0)  # Transparent background
                for i in range(1, 256):
                    lut.SetTableValue(i, color[0], color[1], color[2], opacity)
            else:
                for i in range(256):
                    lut.SetTableValue(i, color[0], color[1], color[2], opacity)
            
            # Create color mapper
            map_colors = vtk.vtkImageMapToColors()
            map_colors.SetLookupTable(lut)
            map_colors.SetInputData(vtk_image)
            map_colors.Update()
            
            # Create actor
            actor = vtk.vtkImageActor()
            actor.GetMapper().SetInputConnection(map_colors.GetOutputPort())
            actor.SetPickable(False)
            
            # Add to manager (thread-safe)
            self.overlay_manager.add_overlay(vtk_image, map_colors, actor)
            
            # Sync and render
            base_extent = self.GetImageActor().GetDisplayExtent()
            self.overlay_manager.sync_extents(base_extent)
            self.Render()
            
            logger.info(f"Added overlay: {path}")
            
        except Exception as e:
            logger.error(f"Error adding overlay: {e}", exc_info=True)
            raise
    
    def clear_all_overlays_threadsafe(self):
        """Thread-safe overlay clearing"""
        if hasattr(self, 'overlay_manager'):
            self.overlay_manager.clear_all()
            self.Render()
    
    def grow_input_image_safe(self, new_vtk_image_data, new_metadata=None):
        """
        Safe image growth with proper memory management
        
        Args:
            new_vtk_image_data: New image data
            new_metadata: Optional new metadata
        
        Returns:
            True if successful
        """
        if not hasattr(self, 'image_reslice'):
            return False
        
        old_input = self.image_reslice.vtk_image_data
        
        # Use safe growth helper
        success = self.safe_growth.grow_image_inplace(
            old_input,
            new_vtk_image_data,
            verify=True
        )
        
        if not success:
            return False
        
        # Update metadata if provided
        if new_metadata is not None and hasattr(self, 'metadata'):
            # Selective metadata update (avoid deep copy)
            if 'instances' in new_metadata:
                self.metadata['instances'] = new_metadata['instances']
        
        # Mark as modified
        self.image_reslice.Modified()
        
        # Schedule delayed render
        if hasattr(self, '_schedule_render'):
            self._schedule_render(100)
        
        return True
    
    def cleanup_safe(self):
        """
        Safe cleanup with proper memory management
        """
        try:
            # Clear overlays
            if hasattr(self, 'overlay_manager'):
                self.overlay_manager.clear_all()
            
            # Cleanup renderer
            if hasattr(self, 'renderer'):
                self.memory_manager.cleanup_renderer(self.renderer)
            
            # Cleanup color mapper
            if hasattr(self, 'color_mapper'):
                self.memory_manager.cleanup_mapper(self.color_mapper)
                self.color_mapper = None
            
            # Cleanup image data
            if hasattr(self, 'vtk_image_data'):
                self.memory_manager.cleanup_image_data(self.vtk_image_data)
                self.vtk_image_data = None
            
            # Cleanup reslice
            if hasattr(self, 'image_reslice'):
                self.image_reslice.SetInputData(None)
                self.image_reslice = None
            
            # Force GC
            self.memory_manager.force_garbage_collection()
            
            logger.info("Cleanup completed successfully")
            
        except Exception as e:
            logger.error(f"Error in cleanup: {e}", exc_info=True)

