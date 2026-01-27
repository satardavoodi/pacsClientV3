"""
Tools Settings Manager
Manages settings for reference line and measurement tools (ruler, arrow, angle, polygon)
Settings are stored in the database for persistence across sessions.
"""

import json
import threading
from typing import Dict, Tuple, Any, Optional
from dataclasses import dataclass, asdict, field
from PacsClient.utils.database import get_db_connection

# Thread-local cache to avoid database locks during progressive download
_settings_cache = None
_cache_lock = threading.Lock()


@dataclass
class ToolStyle:
    """Style settings for a tool"""
    line_width: float = 2.0
    color: Tuple[float, float, float] = (0.0, 0.9, 0.0)  # RGB values 0-1
    opacity: float = 1.0
    font_size: int = 24
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ToolStyle':
        # Convert color list to tuple if needed
        if 'color' in data and isinstance(data['color'], list):
            data['color'] = tuple(data['color'])
        return cls(**data)


@dataclass
class ToolsSettings:
    """Complete settings for all tools"""
    # Reference line settings
    reference_line: ToolStyle = field(default_factory=lambda: ToolStyle(
        line_width=3.0,
        color=(1.0, 0.85, 0.12),  # Yellow/Orange
        opacity=1.0,
        font_size=24
    ))
    
    # Ruler tool settings
    ruler: ToolStyle = field(default_factory=lambda: ToolStyle(
        line_width=3.0,
        color=(0.0, 0.9, 0.0),  # Green
        opacity=1.0,
        font_size=24
    ))
    
    # Arrow tool settings
    arrow: ToolStyle = field(default_factory=lambda: ToolStyle(
        line_width=6.0,
        color=(0.0, 0.9, 0.0),  # Green
        opacity=1.0,
        font_size=24
    ))
    
    # Angle tool settings
    angle: ToolStyle = field(default_factory=lambda: ToolStyle(
        line_width=2.0,
        color=(0.0, 0.9, 0.0),  # Green
        opacity=1.0,
        font_size=24
    ))
    
    # Polygon tool settings
    polygon: ToolStyle = field(default_factory=lambda: ToolStyle(
        line_width=4.0,
        color=(1.0, 0.1, 0.0),  # Red
        opacity=1.0,
        font_size=24
    ))
    
    # Rectangle tool settings
    rectangle: ToolStyle = field(default_factory=lambda: ToolStyle(
        line_width=2.0,
        color=(1.0, 0.1, 0.0),  # Red
        opacity=1.0,
        font_size=24
    ))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'reference_line': self.reference_line.to_dict(),
            'ruler': self.ruler.to_dict(),
            'arrow': self.arrow.to_dict(),
            'angle': self.angle.to_dict(),
            'polygon': self.polygon.to_dict(),
            'rectangle': self.rectangle.to_dict()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ToolsSettings':
        return cls(
            reference_line=ToolStyle.from_dict(data.get('reference_line', {})) if 'reference_line' in data else ToolStyle(line_width=3.0, color=(1.0, 0.85, 0.12)),
            ruler=ToolStyle.from_dict(data.get('ruler', {})) if 'ruler' in data else ToolStyle(line_width=3.0, color=(0.0, 0.9, 0.0)),
            arrow=ToolStyle.from_dict(data.get('arrow', {})) if 'arrow' in data else ToolStyle(line_width=6.0, color=(0.0, 0.9, 0.0)),
            angle=ToolStyle.from_dict(data.get('angle', {})) if 'angle' in data else ToolStyle(line_width=2.0, color=(0.0, 0.9, 0.0)),
            polygon=ToolStyle.from_dict(data.get('polygon', {})) if 'polygon' in data else ToolStyle(line_width=4.0, color=(1.0, 0.1, 0.0)),
            rectangle=ToolStyle.from_dict(data.get('rectangle', {})) if 'rectangle' in data else ToolStyle(line_width=2.0, color=(1.0, 0.1, 0.0))
        )


class ToolsSettingsManager:
    """
    Manager for tools settings with database persistence
    Singleton pattern to ensure consistent settings across the application
    Uses caching to avoid database locks during progressive download
    """
    
    _instance = None
    _settings: Optional[ToolsSettings] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_database()
            # Don't load settings here - will be loaded on first access
        return cls._instance
    
    def _initialize_database(self):
        """Create settings table if it doesn't exist"""
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tools_settings (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        settings_json TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except Exception as e:
            print(f"⚠️ Error initializing tools_settings table: {e}")
    
    def _load_settings(self):
        """Load settings from database or create default"""
        global _settings_cache
        
        # Try to use cached settings first
        with _cache_lock:
            if _settings_cache is not None:
                self._settings = _settings_cache
                return
        
        # Load from database
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT settings_json FROM tools_settings WHERE id = 1")
                row = cur.fetchone()
                
                if row:
                    try:
                        data = json.loads(row[0])
                        self._settings = ToolsSettings.from_dict(data)
                    except Exception as e:
                        print(f"⚠️ Error loading tools settings: {e}")
                        self._settings = ToolsSettings()
                        self._save_settings()
                else:
                    # Create default settings
                    self._settings = ToolsSettings()
                    self._save_settings()
        except Exception as e:
            print(f"⚠️ Error accessing database for tools settings: {e}")
            # Use default settings without saving
            self._settings = ToolsSettings()
        
        # Update cache
        with _cache_lock:
            _settings_cache = self._settings
    
    def _save_settings(self):
        """Save settings to database"""
        if self._settings is None:
            return
        
        try:
            settings_json = json.dumps(self._settings.to_dict())
            
            print(f"💾 [TOOLS SETTINGS] Saving to database...")
            print(f"💾 [TOOLS SETTINGS] JSON length: {len(settings_json)} chars")
            
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR REPLACE INTO tools_settings (id, settings_json, updated_at)
                    VALUES (1, ?, CURRENT_TIMESTAMP)
                """, (settings_json,))
                conn.commit()
                print(f"💾 [TOOLS SETTINGS] Successfully saved to database!")
            
            # Update cache
            global _settings_cache
            with _cache_lock:
                _settings_cache = self._settings
                print(f"💾 [TOOLS SETTINGS] Cache updated")
                
        except Exception as e:
            print(f"⚠️ Error saving tools settings: {e}")
            import traceback
            traceback.print_exc()
    
    def get_settings(self) -> ToolsSettings:
        """Get current settings (lazy load if needed)"""
        if self._settings is None:
            self._load_settings()
        return self._settings
    
    def update_tool_style(self, tool_name: str, **kwargs):
        """
        Update style for a specific tool
        
        Args:
            tool_name: Name of the tool (reference_line, ruler, arrow, angle, polygon, rectangle)
            **kwargs: Style properties to update (line_width, color, opacity, font_size)
        """
        if self._settings is None:
            self._load_settings()
        
        if not hasattr(self._settings, tool_name):
            raise ValueError(f"Unknown tool: {tool_name}")
        
        tool_style = getattr(self._settings, tool_name)
        
        # Update provided properties
        for key, value in kwargs.items():
            if hasattr(tool_style, key):
                setattr(tool_style, key, value)
        
        self._save_settings()
    
    def reset_to_defaults(self):
        """Reset all settings to defaults"""
        self._settings = ToolsSettings()
        self._save_settings()
    
    def get_tool_style(self, tool_name: str) -> ToolStyle:
        """Get style for a specific tool"""
        if self._settings is None:
            self._load_settings()
        
        if not hasattr(self._settings, tool_name):
            raise ValueError(f"Unknown tool: {tool_name}")
        
        return getattr(self._settings, tool_name)
    
    def clear_cache(self):
        """Clear the settings cache (useful for testing or after updates)"""
        global _settings_cache
        with _cache_lock:
            _settings_cache = None
        self._settings = None


# Convenience function to get the singleton instance
def get_tools_settings() -> ToolsSettingsManager:
    """Get the tools settings manager instance"""
    return ToolsSettingsManager()


# Convenience functions for getting specific tool styles
def get_reference_line_style() -> ToolStyle:
    """Get reference line style"""
    return get_tools_settings().get_tool_style('reference_line')


def get_ruler_style() -> ToolStyle:
    """Get ruler tool style"""
    return get_tools_settings().get_tool_style('ruler')


def get_arrow_style() -> ToolStyle:
    """Get arrow tool style"""
    return get_tools_settings().get_tool_style('arrow')


def get_angle_style() -> ToolStyle:
    """Get angle tool style"""
    return get_tools_settings().get_tool_style('angle')


def get_polygon_style() -> ToolStyle:
    """Get polygon tool style"""
    return get_tools_settings().get_tool_style('polygon')


def get_rectangle_style() -> ToolStyle:
    """Get rectangle tool style"""
    return get_tools_settings().get_tool_style('rectangle')

