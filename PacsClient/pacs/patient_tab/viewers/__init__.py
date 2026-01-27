"""
Viewers module with patient list styling
Provides 2D, 3D, and AI Chat viewers with consistent UI design
"""

from .ai_chat_viewer import AIChatViewer
# from .viewer_2d import ImageViewer2D, Viewer2DWidget, ImageReslice, ViewerType
from .viewer_2d import ImageViewer2D, ImageReslice, ViewerType
from .viewer_3d import Viewer3DWidget

__all__ = [
    # AI Chat components
    'AIChatViewer',
    
    # 2D Viewer components
    'ImageViewer2D',
    # 'Viewer2DWidget',
    'ImageReslice',
    'ViewerType',
    
    # 3D Viewer components
    'Viewer3DWidget',
]

# Version info
__version__ = "1.0.0"
__description__ = "Medical imaging viewers with patient list styling"
