"""
Preset Manager for 3D Volume Rendering
======================================

This module provides management capabilities for 3D volume rendering presets including:
- Loading and saving presets
- Custom preset creation
- Preset import/export
- Preset favorites
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import asdict
import vtkmodules.all as vtk

from .vtk_3d_presets import (
    VolumePresetConfig,
    PresetCategory,
    RenderingTechnique,
    PRESET_REGISTRY,
    get_preset_names,
    get_presets_by_category,
    apply_preset_to_volume_property,
    create_preset_volume_property,
    get_preset_info,
)


class PresetManager:
    """
    Manager for 3D volume rendering presets
    
    Handles loading, saving, and managing both built-in and custom presets.
    """
    
    def __init__(self, custom_presets_dir: Optional[str] = None):
        """
        Initialize preset manager
        
        Args:
            custom_presets_dir: Directory for custom presets. If None, uses default.
        """
        if custom_presets_dir is None:
            # Use application data directory
            app_data = os.path.expanduser("~/.pacsclient")
            custom_presets_dir = os.path.join(app_data, "3d_presets")
        
        self.custom_presets_dir = Path(custom_presets_dir)
        self.custom_presets_dir.mkdir(parents=True, exist_ok=True)
        
        # Custom presets registry
        self.custom_presets: Dict[str, VolumePresetConfig] = {}
        
        # Favorites
        self.favorites: List[str] = []
        self.favorites_file = self.custom_presets_dir / "favorites.json"
        
        # Load custom presets and favorites
        self._load_custom_presets()
        self._load_favorites()
    
    # ========================================================================
    # Preset Access Methods
    # ========================================================================
    
    def get_all_preset_names(self, include_custom: bool = True) -> List[str]:
        """
        Get all available preset names
        
        Args:
            include_custom: Include custom presets in the list
        
        Returns:
            List of preset names
        """
        names = get_preset_names()
        
        if include_custom:
            names.extend(self.custom_presets.keys())
        
        return sorted(names)
    
    def get_preset_by_category(
        self,
        category: PresetCategory,
        include_custom: bool = True
    ) -> List[str]:
        """
        Get presets filtered by category
        
        Args:
            category: The category to filter by
            include_custom: Include custom presets
        
        Returns:
            List of preset names in the category
        """
        names = get_presets_by_category(category)
        
        if include_custom:
            custom_names = [
                name for name, preset in self.custom_presets.items()
                if preset.category == category
            ]
            names.extend(custom_names)
        
        return sorted(names)
    
    def get_preset(self, preset_name: str) -> Optional[VolumePresetConfig]:
        """
        Get a preset configuration
        
        Args:
            preset_name: Name of the preset
        
        Returns:
            Preset configuration or None if not found
        """
        # Check built-in presets first
        if preset_name in PRESET_REGISTRY:
            return PRESET_REGISTRY[preset_name]
        
        # Check custom presets
        if preset_name in self.custom_presets:
            return self.custom_presets[preset_name]
        
        return None
    
    def preset_exists(self, preset_name: str) -> bool:
        """Check if a preset exists"""
        return (preset_name in PRESET_REGISTRY or 
                preset_name in self.custom_presets)
    
    # ========================================================================
    # Preset Application Methods
    # ========================================================================
    
    def apply_preset(
        self,
        volume_property: vtk.vtkVolumeProperty,
        preset_name: str,
        scalar_range: Optional[Tuple[float, float]] = None
    ) -> bool:
        """
        Apply a preset to a volume property
        
        Args:
            volume_property: VTK volume property to configure
            preset_name: Name of preset to apply
            scalar_range: Optional custom scalar range
        
        Returns:
            True if successful
        """
        preset = self.get_preset(preset_name)
        if preset is None:
            print(f"Preset '{preset_name}' not found")
            return False
        
        # Apply built-in preset
        if preset_name in PRESET_REGISTRY:
            return apply_preset_to_volume_property(
                volume_property,
                preset_name,
                scalar_range
            )
        
        # Apply custom preset
        return self._apply_custom_preset(
            volume_property,
            preset,
            scalar_range
        )
    
    def create_volume_property(
        self,
        preset_name: str,
        scalar_range: Optional[Tuple[float, float]] = None
    ) -> Optional[vtk.vtkVolumeProperty]:
        """
        Create a new volume property with preset applied
        
        Args:
            preset_name: Name of preset
            scalar_range: Optional scalar range
        
        Returns:
            Configured volume property or None
        """
        preset = self.get_preset(preset_name)
        if preset is None:
            return None
        
        volume_property = vtk.vtkVolumeProperty()
        
        if self.apply_preset(volume_property, preset_name, scalar_range):
            return volume_property
        
        return None
    
    def _apply_custom_preset(
        self,
        volume_property: vtk.vtkVolumeProperty,
        preset: VolumePresetConfig,
        scalar_range: Optional[Tuple[float, float]] = None
    ) -> bool:
        """Apply a custom preset configuration"""
        if scalar_range is None:
            scalar_range = preset.data_range
        
        # Color transfer function
        color_func = vtk.vtkColorTransferFunction()
        for hu, r, g, b in preset.color_points:
            color_func.AddRGBPoint(hu, r, g, b)
        
        # Opacity transfer function
        opacity_func = vtk.vtkPiecewiseFunction()
        for hu, opacity in preset.opacity_points:
            opacity_func.AddPoint(hu, opacity)
        
        volume_property.SetColor(color_func)
        volume_property.SetScalarOpacity(opacity_func)
        
        # Gradient opacity
        if preset.gradient_opacity_points:
            gradient_func = vtk.vtkPiecewiseFunction()
            for gradient, opacity in preset.gradient_opacity_points:
                gradient_func.AddPoint(gradient, opacity)
            volume_property.SetGradientOpacity(gradient_func)
            volume_property.SetDisableGradientOpacity(0)
        else:
            volume_property.SetDisableGradientOpacity(1)
        
        # Shading
        if preset.shade:
            volume_property.ShadeOn()
            volume_property.SetAmbient(preset.ambient)
            volume_property.SetDiffuse(preset.diffuse)
            volume_property.SetSpecular(preset.specular)
            volume_property.SetSpecularPower(preset.specular_power)
        else:
            volume_property.ShadeOff()
        
        # Interpolation
        if preset.interpolation_type == "linear":
            volume_property.SetInterpolationTypeToLinear()
        else:
            volume_property.SetInterpolationTypeToNearest()
        
        return True
    
    # ========================================================================
    # Custom Preset Management
    # ========================================================================
    
    def save_custom_preset(
        self,
        preset_name: str,
        preset: VolumePresetConfig,
        overwrite: bool = False
    ) -> bool:
        """
        Save a custom preset
        
        Args:
            preset_name: Name for the preset
            preset: Preset configuration
            overwrite: Allow overwriting existing preset
        
        Returns:
            True if successful
        """
        # Check if name already exists
        if not overwrite and self.preset_exists(preset_name):
            print(f"Preset '{preset_name}' already exists")
            return False
        
        # Save to file
        preset_file = self.custom_presets_dir / f"{preset_name}.json"
        
        try:
            # Convert to dict
            preset_dict = {
                "name": preset.name,
                "category": preset.category.value,
                "description": preset.description,
                "color_points": preset.color_points,
                "opacity_points": preset.opacity_points,
                "gradient_opacity_points": preset.gradient_opacity_points,
                "shade": preset.shade,
                "ambient": preset.ambient,
                "diffuse": preset.diffuse,
                "specular": preset.specular,
                "specular_power": preset.specular_power,
                "interpolation_type": preset.interpolation_type,
                "data_range": preset.data_range,
                "technique": preset.technique.value,
            }
            
            with open(preset_file, 'w', encoding='utf-8') as f:
                json.dump(preset_dict, f, indent=2, ensure_ascii=False)
            
            # Add to custom presets
            self.custom_presets[preset_name] = preset
            
            print(f"Saved custom preset: {preset_name}")
            return True
            
        except Exception as e:
            print(f"Error saving preset: {e}")
            return False
    
    def delete_custom_preset(self, preset_name: str) -> bool:
        """
        Delete a custom preset
        
        Args:
            preset_name: Name of preset to delete
        
        Returns:
            True if successful
        """
        if preset_name not in self.custom_presets:
            print(f"Custom preset '{preset_name}' not found")
            return False
        
        # Remove file
        preset_file = self.custom_presets_dir / f"{preset_name}.json"
        
        try:
            if preset_file.exists():
                preset_file.unlink()
            
            # Remove from registry
            del self.custom_presets[preset_name]
            
            # Remove from favorites if present
            if preset_name in self.favorites:
                self.favorites.remove(preset_name)
                self._save_favorites()
            
            print(f"Deleted custom preset: {preset_name}")
            return True
            
        except Exception as e:
            print(f"Error deleting preset: {e}")
            return False
    
    def _load_custom_presets(self):
        """Load all custom presets from disk"""
        if not self.custom_presets_dir.exists():
            return
        
        for preset_file in self.custom_presets_dir.glob("*.json"):
            if preset_file.name == "favorites.json":
                continue
            
            try:
                with open(preset_file, 'r', encoding='utf-8') as f:
                    preset_dict = json.load(f)
                
                # Convert back to VolumePresetConfig
                preset = VolumePresetConfig(
                    name=preset_dict["name"],
                    category=PresetCategory(preset_dict["category"]),
                    description=preset_dict["description"],
                    color_points=[tuple(p) for p in preset_dict["color_points"]],
                    opacity_points=[tuple(p) for p in preset_dict["opacity_points"]],
                    gradient_opacity_points=(
                        [tuple(p) for p in preset_dict["gradient_opacity_points"]]
                        if preset_dict.get("gradient_opacity_points")
                        else None
                    ),
                    shade=preset_dict.get("shade", True),
                    ambient=preset_dict.get("ambient", 0.2),
                    diffuse=preset_dict.get("diffuse", 0.7),
                    specular=preset_dict.get("specular", 0.3),
                    specular_power=preset_dict.get("specular_power", 20.0),
                    interpolation_type=preset_dict.get("interpolation_type", "linear"),
                    data_range=tuple(preset_dict.get("data_range", (-3024, 3071))),
                    technique=RenderingTechnique(preset_dict.get("technique", "Volume Rendering Technique")),
                )
                
                preset_name = preset_file.stem
                self.custom_presets[preset_name] = preset
                
                print(f"Loaded custom preset: {preset_name}")
                
            except Exception as e:
                print(f"Error loading preset {preset_file.name}: {e}")
    
    # ========================================================================
    # Favorites Management
    # ========================================================================
    
    def add_to_favorites(self, preset_name: str) -> bool:
        """
        Add preset to favorites
        
        Args:
            preset_name: Name of preset
        
        Returns:
            True if successful
        """
        if not self.preset_exists(preset_name):
            print(f"Preset '{preset_name}' not found")
            return False
        
        if preset_name in self.favorites:
            return True
        
        self.favorites.append(preset_name)
        self._save_favorites()
        return True
    
    def remove_from_favorites(self, preset_name: str) -> bool:
        """
        Remove preset from favorites
        
        Args:
            preset_name: Name of preset
        
        Returns:
            True if successful
        """
        if preset_name not in self.favorites:
            return False
        
        self.favorites.remove(preset_name)
        self._save_favorites()
        return True
    
    def is_favorite(self, preset_name: str) -> bool:
        """Check if preset is in favorites"""
        return preset_name in self.favorites
    
    def get_favorites(self) -> List[str]:
        """Get list of favorite presets"""
        # Filter out any favorites that no longer exist
        valid_favorites = [
            name for name in self.favorites
            if self.preset_exists(name)
        ]
        
        if len(valid_favorites) != len(self.favorites):
            self.favorites = valid_favorites
            self._save_favorites()
        
        return self.favorites
    
    def _load_favorites(self):
        """Load favorites from disk"""
        if not self.favorites_file.exists():
            return
        
        try:
            with open(self.favorites_file, 'r', encoding='utf-8') as f:
                self.favorites = json.load(f)
        except Exception as e:
            print(f"Error loading favorites: {e}")
            self.favorites = []
    
    def _save_favorites(self):
        """Save favorites to disk"""
        try:
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, indent=2)
        except Exception as e:
            print(f"Error saving favorites: {e}")
    
    # ========================================================================
    # Import/Export Methods
    # ========================================================================
    
    def export_preset(self, preset_name: str, export_path: str) -> bool:
        """
        Export a preset to a file
        
        Args:
            preset_name: Name of preset to export
            export_path: Path to export to
        
        Returns:
            True if successful
        """
        preset = self.get_preset(preset_name)
        if preset is None:
            print(f"Preset '{preset_name}' not found")
            return False
        
        try:
            preset_dict = {
                "name": preset.name,
                "category": preset.category.value,
                "description": preset.description,
                "color_points": preset.color_points,
                "opacity_points": preset.opacity_points,
                "gradient_opacity_points": preset.gradient_opacity_points,
                "shade": preset.shade,
                "ambient": preset.ambient,
                "diffuse": preset.diffuse,
                "specular": preset.specular,
                "specular_power": preset.specular_power,
                "interpolation_type": preset.interpolation_type,
                "data_range": preset.data_range,
                "technique": preset.technique.value,
            }
            
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(preset_dict, f, indent=2, ensure_ascii=False)
            
            print(f"Exported preset to: {export_path}")
            return True
            
        except Exception as e:
            print(f"Error exporting preset: {e}")
            return False
    
    def import_preset(
        self,
        import_path: str,
        preset_name: Optional[str] = None,
        overwrite: bool = False
    ) -> bool:
        """
        Import a preset from a file
        
        Args:
            import_path: Path to import from
            preset_name: Optional custom name for imported preset
            overwrite: Allow overwriting existing preset
        
        Returns:
            True if successful
        """
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                preset_dict = json.load(f)
            
            # Use provided name or name from file
            if preset_name is None:
                preset_name = preset_dict["name"]
            
            # Create preset config
            preset = VolumePresetConfig(
                name=preset_name,
                category=PresetCategory(preset_dict["category"]),
                description=preset_dict["description"],
                color_points=[tuple(p) for p in preset_dict["color_points"]],
                opacity_points=[tuple(p) for p in preset_dict["opacity_points"]],
                gradient_opacity_points=(
                    [tuple(p) for p in preset_dict["gradient_opacity_points"]]
                    if preset_dict.get("gradient_opacity_points")
                    else None
                ),
                shade=preset_dict.get("shade", True),
                ambient=preset_dict.get("ambient", 0.2),
                diffuse=preset_dict.get("diffuse", 0.7),
                specular=preset_dict.get("specular", 0.3),
                specular_power=preset_dict.get("specular_power", 20.0),
                interpolation_type=preset_dict.get("interpolation_type", "linear"),
                data_range=tuple(preset_dict.get("data_range", (-3024, 3071))),
                technique=RenderingTechnique(preset_dict.get("technique", "Volume Rendering Technique")),
            )
            
            # Save as custom preset
            return self.save_custom_preset(preset_name, preset, overwrite)
            
        except Exception as e:
            print(f"Error importing preset: {e}")
            return False
    
    # ========================================================================
    # Utility Methods
    # ========================================================================
    
    def get_preset_info(self, preset_name: str) -> Optional[Dict]:
        """
        Get information about a preset
        
        Args:
            preset_name: Name of preset
        
        Returns:
            Dictionary with preset info or None
        """
        preset = self.get_preset(preset_name)
        if preset is None:
            return None
        
        return {
            "name": preset.name,
            "category": preset.category.value,
            "description": preset.description,
            "technique": preset.technique.value,
            "data_range": preset.data_range,
            "has_gradient_opacity": preset.gradient_opacity_points is not None,
            "shading_enabled": preset.shade,
            "is_custom": preset_name in self.custom_presets,
            "is_favorite": preset_name in self.favorites,
        }
    
    def search_presets(self, search_term: str) -> List[str]:
        """
        Search presets by name or description
        
        Args:
            search_term: Term to search for
        
        Returns:
            List of matching preset names
        """
        search_term = search_term.lower()
        matches = []
        
        all_presets = {**PRESET_REGISTRY, **self.custom_presets}
        
        for name, preset in all_presets.items():
            if (search_term in name.lower() or 
                search_term in preset.description.lower()):
                matches.append(name)
        
        return sorted(matches)


# Global preset manager instance
_preset_manager: Optional[PresetManager] = None


def get_preset_manager() -> PresetManager:
    """Get the global preset manager instance"""
    global _preset_manager
    
    if _preset_manager is None:
        _preset_manager = PresetManager()
    
    return _preset_manager

