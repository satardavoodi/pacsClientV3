"""
Modern Theme - UI theme configuration

Provides modern theme with typography, spacing, and styling.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from .colors import ColorPalette

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TypographyScale:
    """Typography scale"""
    header: int = 18
    title: int = 16
    body: int = 14
    caption: int = 12
    small: int = 11


@dataclass(frozen=True)
class SpacingScale:
    """Spacing scale (8px grid system)"""
    xs: int = 4   # 0.5 grid units
    sm: int = 8   # 1 grid unit
    md: int = 16  # 2 grid units
    lg: int = 24  # 3 grid units
    xl: int = 32  # 4 grid units


class ModernTheme:
    """
    Modern UI theme
    
    Features:
    - Material Design 3 inspired
    - 8px grid system
    - Consistent typography
    - Semantic colors
    """
    
    def __init__(self, dark_mode: bool = False):
        """
        Initialize theme
        
        Args:
            dark_mode: Enable dark mode
        """
        self.dark_mode = dark_mode
        self.colors = ColorPalette()
        self.typography = TypographyScale()
        self.spacing = SpacingScale()
        
        logger.info(f"✅ ModernTheme initialized (dark_mode: {dark_mode})")
    
    @property
    def background_color(self) -> str:
        """Get background color"""
        return self.colors.BACKGROUND_DARK if self.dark_mode else self.colors.BACKGROUND_LIGHT
    
    @property
    def surface_color(self) -> str:
        """Get surface color"""
        return self.colors.SURFACE_DARK if self.dark_mode else self.colors.SURFACE_LIGHT
    
    @property
    def text_primary(self) -> str:
        """Get primary text color"""
        return self.colors.TEXT_PRIMARY_DARK if self.dark_mode else self.colors.TEXT_PRIMARY_LIGHT
    
    @property
    def text_secondary(self) -> str:
        """Get secondary text color"""
        return self.colors.TEXT_SECONDARY_DARK if self.dark_mode else self.colors.TEXT_SECONDARY_LIGHT
    
    @property
    def border_color(self) -> str:
        """Get border color"""
        return self.colors.BORDER_DARK if self.dark_mode else self.colors.BORDER_LIGHT
    
    def get_stylesheet(self) -> str:
        """
        Get complete stylesheet
        
        Returns:
            QSS stylesheet string
        """
        return f"""
        QWidget {{
            background-color: {self.background_color};
            color: {self.text_primary};
            font-family: 'Segoe UI', Roboto, sans-serif;
            font-size: {self.typography.body}px;
        }}
        
        QPushButton {{
            background-color: {self.colors.INFO};
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
        }}
        
        QPushButton:hover {{
            background-color: #2563eb;
        }}
        
        QPushButton:pressed {{
            background-color: #1d4ed8;
        }}
        
        QPushButton:disabled {{
            background-color: #94a3b8;
            color: #cbd5e1;
        }}
        """


# Global theme instance
_current_theme: Optional[ModernTheme] = None


def get_current_theme() -> ModernTheme:
    """
    Get current theme instance
    
    Returns:
        ModernTheme instance
    """
    global _current_theme
    
    if _current_theme is None:
        _current_theme = ModernTheme(dark_mode=False)
    
    return _current_theme
