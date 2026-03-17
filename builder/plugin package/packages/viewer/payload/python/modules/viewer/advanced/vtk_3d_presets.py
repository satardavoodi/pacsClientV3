"""
VTK 3D Volume Rendering Presets
================================

This module provides comprehensive 3D volume rendering presets for medical imaging
(CT and MRI) based on industry-standard implementations from:
- 3D Slicer
- GE AW Workstation
- Siemens syngo.via
- Philips IntelliSpace
- Vitrea

All presets are optimized for VTK VolumeProperty and include:
- Color Transfer Functions
- Opacity Transfer Functions
- Gradient Opacity Functions
- Shading Parameters
- Interpolation Settings
"""

import vtkmodules.all as vtk
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum


class PresetCategory(Enum):
    """Preset categories for organization"""
    CT_BONE = "CT Bone"
    CT_SOFT_TISSUE = "CT Soft Tissue"
    CT_LUNG = "CT Lung"
    CT_VESSEL = "CT Vessel"
    CT_CARDIAC = "CT Cardiac"
    CT_CONTRAST = "CT Contrast"
    MRI_BRAIN = "MRI Brain"
    MRI_ANGIOGRAPHY = "MRI Angiography"
    TECHNIQUE = "Technique"


class RenderingTechnique(Enum):
    """Volume rendering techniques"""
    VRT = "Volume Rendering Technique"
    MIP = "Maximum Intensity Projection"
    MINIP = "Minimum Intensity Projection"
    SSD = "Surface Shaded Display"


@dataclass
class VolumePresetConfig:
    """Configuration for a volume rendering preset"""
    name: str
    category: PresetCategory
    description: str
    
    # Color Transfer Function: List of (HU/intensity, R, G, B)
    color_points: List[Tuple[float, float, float, float]]
    
    # Opacity Transfer Function: List of (HU/intensity, opacity)
    opacity_points: List[Tuple[float, float]]
    
    # Gradient Opacity Function: List of (gradient_value, opacity)
    gradient_opacity_points: Optional[List[Tuple[float, float]]] = None
    
    # Shading parameters
    shade: bool = True
    ambient: float = 0.2
    diffuse: float = 0.7
    specular: float = 0.3
    specular_power: float = 20.0
    
    # Interpolation
    interpolation_type: str = "linear"  # "linear" or "nearest"
    
    # Data range (HU for CT, intensity for MRI)
    data_range: Tuple[float, float] = (-3024, 3071)
    
    # Rendering technique
    technique: RenderingTechnique = RenderingTechnique.VRT


# ============================================================================
# CT BONE PRESETS
# ============================================================================

CT_BONE_STANDARD = VolumePresetConfig(
    name="CT-Bone",
    category=PresetCategory.CT_BONE,
    description="Standard bone visualization - shows cortical and trabecular bone structure",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),      # Air: Black
        (-1000, 0.3, 0.28, 0.26),    # Lung: Dark gray
        (-500, 0.4, 0.36, 0.34),     # Fat: Light gray
        (200, 0.0, 0.0, 0.0),        # Soft tissue: Transparent
        (400, 0.93, 0.91, 0.84),     # Bone start: Ivory
        (1000, 1.0, 0.98, 0.90),     # Dense bone: Light yellow-white
        (3071, 1.0, 1.0, 1.0),       # Metal: Pure white
    ],
    opacity_points=[
        (-3024, 0.0),
        (-1000, 0.0),
        (200, 0.0),
        (300, 0.0),
        (400, 0.15),    # Bone starts appearing
        (600, 0.5),
        (1000, 0.85),
        (3071, 0.95),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (10, 0.0),
        (30, 0.3),
        (50, 0.7),
        (100, 1.0),
    ],
    shade=True,
    ambient=0.15,
    diffuse=0.7,
    specular=0.4,
    specular_power=30.0,
)

CT_BONE_ENHANCED = VolumePresetConfig(
    name="CT-Bone-Enhanced",
    category=PresetCategory.CT_BONE,
    description="Enhanced bone visualization with better trabecular detail",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (-1000, 0.0, 0.0, 0.0),
        (200, 0.0, 0.0, 0.0),
        (250, 0.5, 0.35, 0.25),      # Trabecular: Brown
        (350, 0.88, 0.75, 0.62),     # Cortical: Tan
        (800, 1.0, 0.96, 0.88),      # Dense bone: Off-white
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (200, 0.0),
        (250, 0.05),
        (300, 0.2),
        (400, 0.55),
        (800, 0.9),
        (3071, 1.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (20, 0.2),
        (40, 0.6),
        (80, 1.0),
    ],
    shade=True,
    ambient=0.2,
    diffuse=0.6,
    specular=0.5,
    specular_power=40.0,
)

CT_BONE_MUSCLE = VolumePresetConfig(
    name="CT-Muscle-Bone",
    category=PresetCategory.CT_BONE,
    description="Shows both muscle tissue and bone structure",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (-1000, 0.0, 0.0, 0.0),
        (-100, 0.0, 0.0, 0.0),
        (20, 0.55, 0.25, 0.15),      # Muscle: Red-brown
        (150, 0.65, 0.37, 0.25),     # Dense muscle
        (240, 0.8, 0.8, 0.8),        # Transition
        (300, 0.9, 0.87, 0.82),      # Bone: Light tan
        (1000, 1.0, 0.98, 0.94),
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (-100, 0.0),
        (20, 0.0),
        (80, 0.15),     # Muscle starts
        (150, 0.28),
        (240, 0.0),     # Gap before bone
        (300, 0.35),    # Bone starts
        (600, 0.75),
        (3071, 0.95),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (15, 0.3),
        (40, 0.75),
        (100, 1.0),
    ],
    shade=True,
    ambient=0.18,
    diffuse=0.65,
    specular=0.35,
    specular_power=25.0,
)

# ============================================================================
# CT SOFT TISSUE PRESETS
# ============================================================================

CT_SOFT_TISSUE = VolumePresetConfig(
    name="CT-Soft-Tissue",
    category=PresetCategory.CT_SOFT_TISSUE,
    description="Standard soft tissue visualization for abdominal and general CT",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (-150, 0.0, 0.0, 0.0),
        (-50, 0.18, 0.10, 0.03),     # Fat: Dark brown
        (40, 0.55, 0.35, 0.25),      # Muscle: Red-brown
        (80, 0.75, 0.53, 0.43),      # Organs: Pink-tan
        (150, 0.88, 0.75, 0.68),     # Dense tissue: Light pink
        (300, 0.95, 0.95, 0.95),
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (-150, 0.0),
        (-50, 0.12),
        (40, 0.40),
        (80, 0.65),
        (150, 0.82),
        (300, 0.95),
        (3071, 0.95),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (5, 0.0),
        (15, 0.4),
        (40, 0.8),
        (100, 1.0),
    ],
    shade=True,
    ambient=0.25,
    diffuse=0.70,
    specular=0.20,
    specular_power=15.0,
)

CT_SOFT_TISSUE_SKIN = VolumePresetConfig(
    name="CT-Soft-Tissue-Skin",
    category=PresetCategory.CT_SOFT_TISSUE,
    description="Soft tissue with skin surface visualization",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (-1000, 0.0, 0.0, 0.0),
        (-150, 0.0, 0.0, 0.0),
        (-100, 0.85, 0.72, 0.62),    # Skin: Peach
        (40, 0.75, 0.50, 0.40),      # Muscle: Red-brown
        (150, 0.88, 0.75, 0.68),     # Organs
        (300, 0.95, 0.95, 0.95),
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (-150, 0.0),
        (-100, 0.35),   # Skin visible
        (40, 0.55),
        (150, 0.75),
        (300, 0.90),
        (3071, 0.95),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (10, 0.3),
        (30, 0.7),
        (100, 1.0),
    ],
    shade=True,
    ambient=0.30,
    diffuse=0.65,
    specular=0.25,
    specular_power=20.0,
)

# ============================================================================
# CT LUNG PRESETS
# ============================================================================

CT_LUNG = VolumePresetConfig(
    name="CT-Lung",
    category=PresetCategory.CT_LUNG,
    description="Pulmonary visualization showing airways and vessels",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (-1024, 0.0, 0.38, 0.45),    # Air: Dark cyan
        (-800, 0.15, 0.55, 0.68),    # Lung: Cyan
        (-600, 0.35, 0.70, 0.80),    # Aerated lung: Light cyan
        (-400, 0.55, 0.82, 0.88),    # Ground glass
        (-200, 0.75, 0.88, 0.90),    # Consolidation
        (100, 0.85, 0.85, 0.85),     # Soft tissue
        (200, 0.92, 0.92, 0.92),
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (-1024, 0.0),
        (-800, 0.25),
        (-600, 0.45),
        (-400, 0.60),
        (-200, 0.75),
        (100, 0.0),     # Hide soft tissue
        (200, 0.0),
        (3071, 0.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (8, 0.4),
        (25, 0.8),
        (50, 1.0),
    ],
    shade=True,
    ambient=0.30,
    diffuse=0.65,
    specular=0.15,
    specular_power=10.0,
)

CT_LUNG_AIRWAYS = VolumePresetConfig(
    name="CT-Lung-Airways",
    category=PresetCategory.CT_LUNG,
    description="Enhanced airway tree visualization",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (-1024, 0.0, 0.20, 0.40),    # Airways: Dark blue
        (-850, 0.2, 0.45, 0.70),     # Bronchi: Blue
        (-700, 0.4, 0.65, 0.85),     # Small airways: Light blue
        (-500, 0.6, 0.78, 0.90),     # Parenchyma: Very light blue
        (0, 0.8, 0.8, 0.8),
        (200, 0.9, 0.9, 0.9),
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (-1024, 0.0),
        (-950, 0.18),
        (-800, 0.40),
        (-600, 0.65),
        (-400, 0.82),
        (0, 0.0),
        (3071, 0.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (12, 0.5),
        (35, 0.9),
        (80, 1.0),
    ],
    shade=True,
    ambient=0.28,
    diffuse=0.68,
    specular=0.18,
    specular_power=12.0,
)

# ============================================================================
# CT VESSEL PRESETS
# ============================================================================

CT_VESSEL_RED = VolumePresetConfig(
    name="CT-Vessels-Red",
    category=PresetCategory.CT_VESSEL,
    description="Red arterial visualization for CTA (CT Angiography)",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (-1000, 0.0, 0.0, 0.0),
        (100, 0.0, 0.0, 0.0),
        (150, 0.4, 0.0, 0.0),        # Dark red start
        (200, 0.8, 0.1, 0.0),        # Red
        (300, 1.0, 0.3, 0.2),        # Bright red
        (500, 1.0, 0.5, 0.4),        # Light red
        (800, 1.0, 0.8, 0.7),        # Very light red
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (100, 0.0),
        (130, 0.0),
        (150, 0.15),
        (200, 0.50),
        (300, 0.85),
        (500, 0.95),
        (3071, 1.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (15, 0.4),
        (40, 0.8),
        (100, 1.0),
    ],
    shade=True,
    ambient=0.20,
    diffuse=0.70,
    specular=0.40,
    specular_power=25.0,
)

CT_VESSEL_BLUE_RED = VolumePresetConfig(
    name="CT-Vessels-Blue-Red",
    category=PresetCategory.CT_VESSEL,
    description="Blue veins and red arteries for complete vascular visualization",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (50, 0.0, 0.0, 0.0),
        (80, 0.0, 0.2, 0.6),         # Veins: Blue
        (120, 0.2, 0.4, 0.8),        # Veins: Light blue
        (180, 0.6, 0.0, 0.0),        # Arteries: Dark red
        (240, 0.9, 0.2, 0.1),        # Arteries: Red
        (350, 1.0, 0.4, 0.3),        # Arteries: Bright red
        (500, 1.0, 0.7, 0.6),        # Light vessels
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (50, 0.0),
        (80, 0.20),
        (120, 0.45),
        (180, 0.70),
        (300, 0.90),
        (500, 0.98),
        (3071, 1.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (18, 0.45),
        (45, 0.85),
        (120, 1.0),
    ],
    shade=True,
    ambient=0.18,
    diffuse=0.72,
    specular=0.45,
    specular_power=30.0,
)

# ============================================================================
# CT CARDIAC PRESETS
# ============================================================================

CT_CARDIAC = VolumePresetConfig(
    name="CT-Cardiac",
    category=PresetCategory.CT_CARDIAC,
    description="Cardiac visualization showing heart chambers and coronary arteries",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (-50, 0.0, 0.0, 0.0),
        (10, 0.3, 0.1, 0.1),         # Myocardium: Dark red
        (50, 0.5, 0.2, 0.15),        # Myocardium: Red-brown
        (100, 0.15, 0.0, 0.0),       # Blood pool: Dark
        (150, 0.7, 0.1, 0.05),       # Contrast: Bright red
        (300, 1.0, 0.3, 0.2),        # High contrast: Very bright red
        (500, 1.0, 0.6, 0.5),
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (-50, 0.0),
        (10, 0.0),
        (30, 0.15),
        (50, 0.30),
        (100, 0.0),     # Blood pool transparent
        (130, 0.45),    # Contrast visible
        (200, 0.75),
        (300, 0.92),
        (3071, 1.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (10, 0.3),
        (30, 0.7),
        (80, 1.0),
    ],
    shade=True,
    ambient=0.22,
    diffuse=0.68,
    specular=0.35,
    specular_power=22.0,
)

CT_CORONARY = VolumePresetConfig(
    name="CT-Coronary",
    category=PresetCategory.CT_CARDIAC,
    description="Optimized for coronary artery visualization",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (50, 0.0, 0.0, 0.0),
        (120, 0.0, 0.0, 0.0),
        (150, 0.5, 0.05, 0.0),       # Coronaries: Dark red
        (220, 0.9, 0.15, 0.05),      # Coronaries: Red
        (350, 1.0, 0.35, 0.25),      # Bright coronaries
        (500, 1.0, 0.65, 0.55),
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (120, 0.0),
        (150, 0.25),
        (220, 0.65),
        (350, 0.90),
        (500, 0.98),
        (3071, 1.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (20, 0.5),
        (50, 0.9),
        (120, 1.0),
    ],
    shade=True,
    ambient=0.18,
    diffuse=0.72,
    specular=0.50,
    specular_power=35.0,
)

# ============================================================================
# CT CONTRAST PRESETS
# ============================================================================

CT_CONTRAST_ENHANCED = VolumePresetConfig(
    name="CT-Contrast-Enhanced",
    category=PresetCategory.CT_CONTRAST,
    description="General contrast-enhanced CT visualization",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (-100, 0.0, 0.0, 0.0),
        (50, 0.4, 0.3, 0.2),         # Soft tissue: Brown
        (100, 0.7, 0.5, 0.4),        # Enhanced tissue
        (150, 0.9, 0.7, 0.3),        # Contrast: Yellow-orange
        (250, 1.0, 0.85, 0.4),       # High contrast: Bright yellow
        (400, 1.0, 0.95, 0.7),       # Very bright
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (-100, 0.0),
        (50, 0.25),
        (100, 0.50),
        (150, 0.75),
        (250, 0.92),
        (400, 0.98),
        (3071, 1.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (12, 0.4),
        (35, 0.8),
        (90, 1.0),
    ],
    shade=True,
    ambient=0.25,
    diffuse=0.68,
    specular=0.30,
    specular_power=20.0,
)

# ============================================================================
# MRI BRAIN PRESETS
# ============================================================================

MRI_BRAIN_T1 = VolumePresetConfig(
    name="MRI-Brain-T1",
    category=PresetCategory.MRI_BRAIN,
    description="T1-weighted MRI brain visualization (gray/white matter contrast)",
    color_points=[
        (0, 0.0, 0.0, 0.0),          # Background: Black
        (20, 0.1, 0.05, 0.0),        # CSF: Dark
        (50, 0.3, 0.25, 0.2),        # Gray matter: Gray-brown
        (80, 0.6, 0.55, 0.5),        # White matter: Light gray
        (120, 0.85, 0.82, 0.78),     # Bright structures
        (180, 1.0, 0.98, 0.95),      # Very bright
        (255, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (0, 0.0),
        (20, 0.0),
        (35, 0.25),
        (60, 0.60),
        (100, 0.85),
        (180, 0.95),
        (255, 1.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (5, 0.3),
        (15, 0.7),
        (40, 1.0),
    ],
    shade=True,
    ambient=0.30,
    diffuse=0.65,
    specular=0.20,
    specular_power=15.0,
    data_range=(0, 255),
)

MRI_BRAIN_T2 = VolumePresetConfig(
    name="MRI-Brain-T2",
    category=PresetCategory.MRI_BRAIN,
    description="T2-weighted MRI brain visualization (fluid bright)",
    color_points=[
        (0, 0.0, 0.0, 0.0),
        (20, 0.15, 0.10, 0.08),      # Gray matter: Dark
        (50, 0.35, 0.30, 0.28),      # White matter: Medium gray
        (90, 0.60, 0.55, 0.52),      # Tissue
        (140, 0.80, 0.85, 0.90),     # CSF/Fluid: Light blue-gray
        (200, 0.92, 0.95, 0.98),     # Bright fluid
        (255, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (0, 0.0),
        (20, 0.15),
        (50, 0.45),
        (90, 0.70),
        (140, 0.88),
        (200, 0.96),
        (255, 1.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (6, 0.35),
        (18, 0.75),
        (45, 1.0),
    ],
    shade=True,
    ambient=0.28,
    diffuse=0.67,
    specular=0.22,
    specular_power=18.0,
    data_range=(0, 255),
)

MRI_BRAIN_FLAIR = VolumePresetConfig(
    name="MRI-Brain-FLAIR",
    category=PresetCategory.MRI_BRAIN,
    description="FLAIR MRI for lesion detection (CSF suppressed)",
    color_points=[
        (0, 0.0, 0.0, 0.0),
        (30, 0.2, 0.15, 0.12),       # Normal tissue: Dark
        (60, 0.45, 0.38, 0.33),      # Gray matter
        (100, 0.70, 0.62, 0.55),     # White matter
        (150, 0.90, 0.75, 0.55),     # Lesions: Yellow-orange
        (200, 1.0, 0.88, 0.65),      # Bright lesions
        (255, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (0, 0.0),
        (30, 0.20),
        (60, 0.50),
        (100, 0.75),
        (150, 0.90),
        (200, 0.97),
        (255, 1.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (8, 0.4),
        (22, 0.8),
        (55, 1.0),
    ],
    shade=True,
    ambient=0.32,
    diffuse=0.65,
    specular=0.18,
    specular_power=14.0,
    data_range=(0, 255),
)

# ============================================================================
# MRI ANGIOGRAPHY PRESETS
# ============================================================================

MRI_MRA = VolumePresetConfig(
    name="MRI-MRA",
    category=PresetCategory.MRI_ANGIOGRAPHY,
    description="MR Angiography - bright blood vessels",
    color_points=[
        (0, 0.0, 0.0, 0.0),
        (40, 0.0, 0.0, 0.0),
        (80, 0.4, 0.0, 0.0),         # Vessels: Dark red
        (120, 0.8, 0.1, 0.0),        # Vessels: Red
        (160, 1.0, 0.3, 0.2),        # Bright vessels: Bright red
        (200, 1.0, 0.6, 0.5),        # Very bright vessels
        (255, 1.0, 0.9, 0.8),
    ],
    opacity_points=[
        (0, 0.0),
        (40, 0.0),
        (80, 0.30),
        (120, 0.70),
        (160, 0.92),
        (200, 0.98),
        (255, 1.0),
    ],
    gradient_opacity_points=[
        (0, 0.0),
        (10, 0.45),
        (28, 0.85),
        (70, 1.0),
    ],
    shade=True,
    ambient=0.20,
    diffuse=0.72,
    specular=0.42,
    specular_power=28.0,
    data_range=(0, 255),
)

# ============================================================================
# TECHNIQUE-SPECIFIC PRESETS
# ============================================================================

TECHNIQUE_MIP = VolumePresetConfig(
    name="MIP (Maximum Intensity)",
    category=PresetCategory.TECHNIQUE,
    description="Maximum Intensity Projection - shows brightest voxels",
    color_points=[
        (-3024, 0.0, 0.0, 0.0),
        (0, 0.0, 0.0, 0.0),
        (150, 1.0, 1.0, 1.0),
        (3071, 1.0, 1.0, 1.0),
    ],
    opacity_points=[
        (-3024, 0.0),
        (0, 0.0),
        (150, 1.0),
        (3071, 1.0),
    ],
    gradient_opacity_points=None,
    shade=False,
    ambient=1.0,
    diffuse=0.0,
    specular=0.0,
    specular_power=1.0,
    technique=RenderingTechnique.MIP,
)

TECHNIQUE_MINIP = VolumePresetConfig(
    name="MinIP (Minimum Intensity)",
    category=PresetCategory.TECHNIQUE,
    description="Minimum Intensity Projection - useful for airways",
    color_points=[
        (-3024, 0.0, 0.38, 0.45),
        (-800, 0.15, 0.55, 0.68),
        (0, 0.0, 0.0, 0.0),
        (3071, 0.0, 0.0, 0.0),
    ],
    opacity_points=[
        (-3024, 1.0),
        (-800, 1.0),
        (0, 0.0),
        (3071, 0.0),
    ],
    gradient_opacity_points=None,
    shade=False,
    ambient=1.0,
    diffuse=0.0,
    specular=0.0,
    specular_power=1.0,
    technique=RenderingTechnique.MINIP,
)

# ============================================================================
# PRESET REGISTRY
# ============================================================================

PRESET_REGISTRY: Dict[str, VolumePresetConfig] = {
    # CT Bone
    "CT-Bone": CT_BONE_STANDARD,
    "CT-Bone-Enhanced": CT_BONE_ENHANCED,
    "CT-Muscle-Bone": CT_BONE_MUSCLE,
    
    # CT Soft Tissue
    "CT-Soft-Tissue": CT_SOFT_TISSUE,
    "CT-Soft-Tissue-Skin": CT_SOFT_TISSUE_SKIN,
    
    # CT Lung
    "CT-Lung": CT_LUNG,
    "CT-Lung-Airways": CT_LUNG_AIRWAYS,
    
    # CT Vessel
    "CT-Vessels-Red": CT_VESSEL_RED,
    "CT-Vessels-Blue-Red": CT_VESSEL_BLUE_RED,
    
    # CT Cardiac
    "CT-Cardiac": CT_CARDIAC,
    "CT-Coronary": CT_CORONARY,
    
    # CT Contrast
    "CT-Contrast-Enhanced": CT_CONTRAST_ENHANCED,
    
    # MRI Brain
    "MRI-Brain-T1": MRI_BRAIN_T1,
    "MRI-Brain-T2": MRI_BRAIN_T2,
    "MRI-Brain-FLAIR": MRI_BRAIN_FLAIR,
    
    # MRI Angiography
    "MRI-MRA": MRI_MRA,
    
    # Techniques
    "MIP": TECHNIQUE_MIP,
    "MinIP": TECHNIQUE_MINIP,
}


def get_preset_names() -> List[str]:
    """Get list of all available preset names"""
    return list(PRESET_REGISTRY.keys())


def get_presets_by_category(category: PresetCategory) -> List[str]:
    """Get preset names filtered by category"""
    return [
        name for name, preset in PRESET_REGISTRY.items()
        if preset.category == category
    ]


def apply_preset_to_volume_property(
    volume_property: vtk.vtkVolumeProperty,
    preset_name: str,
    scalar_range: Optional[Tuple[float, float]] = None
) -> bool:
    """
    Apply a preset to a VTK VolumeProperty
    
    Args:
        volume_property: The VTK volume property to configure
        preset_name: Name of the preset to apply
        scalar_range: Optional custom scalar range (min, max). If None, uses preset default.
    
    Returns:
        True if successful, False if preset not found
    """
    if preset_name not in PRESET_REGISTRY:
        print(f"Preset '{preset_name}' not found")
        return False
    
    preset = PRESET_REGISTRY[preset_name]
    
    # Determine scalar range
    if scalar_range is None:
        scalar_range = preset.data_range
    
    # Create and configure color transfer function
    color_func = vtk.vtkColorTransferFunction()
    for hu, r, g, b in preset.color_points:
        color_func.AddRGBPoint(hu, r, g, b)
    
    # Create and configure opacity transfer function
    opacity_func = vtk.vtkPiecewiseFunction()
    for hu, opacity in preset.opacity_points:
        opacity_func.AddPoint(hu, opacity)
    
    # Set color and opacity
    volume_property.SetColor(color_func)
    volume_property.SetScalarOpacity(opacity_func)
    
    # Configure gradient opacity if specified
    if preset.gradient_opacity_points:
        gradient_func = vtk.vtkPiecewiseFunction()
        for gradient, opacity in preset.gradient_opacity_points:
            gradient_func.AddPoint(gradient, opacity)
        volume_property.SetGradientOpacity(gradient_func)
        volume_property.SetDisableGradientOpacity(0)
    else:
        volume_property.SetDisableGradientOpacity(1)
    
    # Configure shading
    if preset.shade:
        volume_property.ShadeOn()
        volume_property.SetAmbient(preset.ambient)
        volume_property.SetDiffuse(preset.diffuse)
        volume_property.SetSpecular(preset.specular)
        volume_property.SetSpecularPower(preset.specular_power)
    else:
        volume_property.ShadeOff()
    
    # Configure interpolation
    if preset.interpolation_type == "linear":
        volume_property.SetInterpolationTypeToLinear()
    else:
        volume_property.SetInterpolationTypeToNearest()
    
    return True


def create_preset_volume_property(
    preset_name: str,
    scalar_range: Optional[Tuple[float, float]] = None
) -> Optional[vtk.vtkVolumeProperty]:
    """
    Create a new VolumeProperty with a preset applied
    
    Args:
        preset_name: Name of the preset to apply
        scalar_range: Optional custom scalar range
    
    Returns:
        Configured VolumeProperty, or None if preset not found
    """
    if preset_name not in PRESET_REGISTRY:
        return None
    
    volume_property = vtk.vtkVolumeProperty()
    
    if apply_preset_to_volume_property(volume_property, preset_name, scalar_range):
        return volume_property
    
    return None


def get_preset_info(preset_name: str) -> Optional[Dict[str, Any]]:
    """
    Get information about a preset
    
    Args:
        preset_name: Name of the preset
    
    Returns:
        Dictionary with preset information, or None if not found
    """
    if preset_name not in PRESET_REGISTRY:
        return None
    
    preset = PRESET_REGISTRY[preset_name]
    
    return {
        "name": preset.name,
        "category": preset.category.value,
        "description": preset.description,
        "technique": preset.technique.value,
        "data_range": preset.data_range,
        "has_gradient_opacity": preset.gradient_opacity_points is not None,
        "shading_enabled": preset.shade,
    }

