"""
Widgets module - Qt widgets for MPR visualization.

Classes:
- OrthogonalMPRWidget: Main widget with three MPR views
- SliceSlider: Slider widget for slice navigation
- MPRToolbar: Toolbar with presets and tools
"""

from .mpr_viewer_widget import OrthogonalMPRWidget
from .slice_slider import SliceSlider
from .toolbar import MPRToolbar

__all__ = [
    "OrthogonalMPRWidget",
    "SliceSlider",
    "MPRToolbar",
]
