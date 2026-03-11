"""
Color Palette - Modern color system

Material Design 3 inspired color palette for professional UI.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ColorPalette:
    """
    Modern color palette
    
    Uses Material Design 3 color system with semantic naming.
    """
    
    # Priority Colors (from constants)
    CRITICAL_START = '#ef4444'  # Red 500
    CRITICAL_END = '#dc2626'    # Red 600
    CRITICAL_BORDER = '#b91c1c'  # Red 700
    
    HIGH_START = '#f97316'      # Orange 500
    HIGH_END = '#ea580c'        # Orange 600
    HIGH_BORDER = '#c2410c'     # Orange 700
    
    NORMAL_START = '#06b6d4'    # Cyan 500
    NORMAL_END = '#0891b2'      # Cyan 600
    NORMAL_BORDER = '#0e7490'   # Cyan 700
    
    LOW_START = '#64748b'       # Slate 500
    LOW_END = '#475569'         # Slate 600
    LOW_BORDER = '#334155'      # Slate 700
    
    # Status Colors
    STATUS_PENDING = '#94a3b8'      # Slate 400
    STATUS_DOWNLOADING = '#3b82f6'  # Blue 500
    STATUS_PAUSED = '#f59e0b'       # Amber 500
    STATUS_COMPLETED = '#10b981'    # Emerald 500
    STATUS_FAILED = '#ef4444'       # Red 500
    STATUS_CANCELLED = '#6b7280'    # Gray 500
    
    # UI Colors
    BACKGROUND_LIGHT = '#ffffff'
    BACKGROUND_DARK = '#1e293b'
    SURFACE_LIGHT = '#f8fafc'
    SURFACE_DARK = '#334155'
    
    TEXT_PRIMARY_LIGHT = '#0f172a'
    TEXT_PRIMARY_DARK = '#f8fafc'
    TEXT_SECONDARY_LIGHT = '#64748b'
    TEXT_SECONDARY_DARK = '#cbd5e1'
    
    BORDER_LIGHT = '#e2e8f0'
    BORDER_DARK = '#475569'
    
    # Semantic Colors
    SUCCESS = '#10b981'  # Emerald 500
    WARNING = '#f59e0b'  # Amber 500
    ERROR = '#ef4444'    # Red 500
    INFO = '#3b82f6'     # Blue 500
    
    @classmethod
    def get_priority_colors(cls, priority_name: str) -> Dict[str, str]:
        """
        Get colors for priority level
        
        Args:
            priority_name: Priority name (CRITICAL, HIGH, NORMAL, LOW)
            
        Returns:
            Dict with gradient_start, gradient_end, border
        """
        color_map = {
            'CRITICAL': {
                'gradient_start': cls.CRITICAL_START,
                'gradient_end': cls.CRITICAL_END,
                'border': cls.CRITICAL_BORDER,
                'text': '#ffffff'
            },
            'HIGH': {
                'gradient_start': cls.HIGH_START,
                'gradient_end': cls.HIGH_END,
                'border': cls.HIGH_BORDER,
                'text': '#ffffff'
            },
            'NORMAL': {
                'gradient_start': cls.NORMAL_START,
                'gradient_end': cls.NORMAL_END,
                'border': cls.NORMAL_BORDER,
                'text': '#ffffff'
            },
            'LOW': {
                'gradient_start': cls.LOW_START,
                'gradient_end': cls.LOW_END,
                'border': cls.LOW_BORDER,
                'text': '#ffffff'
            }
        }
        
        return color_map.get(priority_name.upper(), color_map['NORMAL'])
    
    @classmethod
    def get_status_color(cls, status_name: str) -> str:
        """
        Get color for status
        
        Args:
            status_name: Status name
            
        Returns:
            Hex color code
        """
        color_map = {
            'PENDING': cls.STATUS_PENDING,
            'DOWNLOADING': cls.STATUS_DOWNLOADING,
            'PAUSED': cls.STATUS_PAUSED,
            'COMPLETED': cls.STATUS_COMPLETED,
            'FAILED': cls.STATUS_FAILED,
            'CANCELLED': cls.STATUS_CANCELLED,
        }
        
        return color_map.get(status_name.upper(), cls.STATUS_PENDING)
