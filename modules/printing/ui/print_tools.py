"""
Tool mode management for printing preview widget.
Mirrors the ToolAccess pattern from PACS viewer.
"""

from enum import Enum


class PrintToolMode(Enum):
    """Tool modes for printing preview widget, mirroring PACS ToolAccess."""
    PAN = "pan"
    ZOOM = "zoom"
    WINDOW_LEVEL = "window_level"
    DEFAULT = "default"  # Default interactive mode (right-click for WL, middle for zoom)


class PrintToolManager:
    """
    Tool mode management for printing preview.
    Mirrors the behavior from PACS viewer's ToolAccess class.
    """
    
    # Tool mode constants
    PAN = "pan"
    ZOOM = "zoom"
    WINDOW_LEVEL = "window_level"
    CAPTURE = "capture"
    DEFAULT = "default"
    
    def __init__(self):
        self.current_tool = self.DEFAULT
        self.previous_tool = self.DEFAULT
        
    def set_tool(self, tool: str) -> None:
        """Set the current tool mode."""
        self.previous_tool = self.current_tool
        self.current_tool = tool
        
    def get_tool(self) -> str:
        """Get the current tool mode."""
        return self.current_tool
        
    def is_pan_mode(self) -> bool:
        return self.current_tool == self.PAN
        
    def is_zoom_mode(self) -> bool:
        return self.current_tool == self.ZOOM
        
    def is_window_level_mode(self) -> bool:
        return self.current_tool == self.WINDOW_LEVEL
        
    def is_default_mode(self) -> bool:
        return self.current_tool == self.DEFAULT


# Global tool manager instance (can be shared across widgets)
_print_tool_manager = PrintToolManager()


def get_print_tool_manager() -> PrintToolManager:
    """Get the global print tool manager instance."""
    return _print_tool_manager
