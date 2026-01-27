"""
CenterLayoutWidget Component

A reusable center layout component that provides the main viewing area for the PatientWidget.
This component encapsulates all center layout functionality including grid layout management,
viewer positioning, and styling.

Features:
- Grid layout for multiple viewers
- Viewer management
- Customizable styling
- Layout configuration
- Widget positioning
"""

from PySide6.QtWidgets import QWidget, QGridLayout, QVBoxLayout, QHBoxLayout
from PySide6.QtCore import Qt, Signal
from PacsClient.pacs.patient_tab.utils import delete_widgets_in_layout


class CenterLayoutWidget(QWidget):
    """
    Center layout component that provides the main viewing area.
    
    Features:
    - Grid layout for multiple viewers
    - Viewer management
    - Customizable styling
    - Layout configuration
    """
    
    # Signals for center layout events
    viewer_added = Signal(int, int, object)  # Emits row, col, widget when viewer added
    viewer_removed = Signal(int, int)  # Emits row, col when viewer removed
    layout_cleared = Signal()  # Emits when layout is cleared
    
    def __init__(self, parent=None):
        """
        Initialize the CenterLayoutWidget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.parent_widget = parent
        self.viewer_widgets = {}  # Dictionary to store viewer widgets by (row, col)
        self.current_layout_type = "grid"  # "grid" or "horizontal" or "vertical"
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the center layout UI components."""
        # Configure widget styling
        self.setStyleSheet('''
            background-color: #21272a;
            border: 1px solid #21272a;
            border-radius: 10px;
            margin: 0px;
            padding: 0px;
        ''')
        
        # Create grid layout
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)
        
        # Create alternative layouts for different modes
        self.horizontal_layout = QHBoxLayout()
        self.horizontal_layout.setContentsMargins(0, 0, 0, 0)
        self.horizontal_layout.setSpacing(0)
        
        self.vertical_layout = QVBoxLayout()
        self.vertical_layout.setContentsMargins(0, 0, 0, 0)
        self.vertical_layout.setSpacing(0)
    
    def add_viewer(self, widget, row: int = 0, col: int = 0):
        """
        Add a viewer widget to the layout.
        
        Args:
            widget: Widget to add
            row: Row position (for grid layout)
            col: Column position (for grid layout)
        """
        if self.current_layout_type == "grid":
            self.grid_layout.addWidget(widget, row, col)
            self.viewer_widgets[(row, col)] = widget
            self.viewer_added.emit(row, col, widget)
        elif self.current_layout_type == "horizontal":
            self.horizontal_layout.addWidget(widget)
            self.viewer_widgets[len(self.viewer_widgets)] = widget
        elif self.current_layout_type == "vertical":
            self.vertical_layout.addWidget(widget)
            self.viewer_widgets[len(self.viewer_widgets)] = widget
    
    def remove_viewer(self, row: int = None, col: int = None, widget=None):
        """
        Remove a viewer widget from the layout.
        
        Args:
            row: Row position (for grid layout)
            col: Column position (for grid layout)
            widget: Widget to remove (alternative to row/col)
        """
        if widget:
            if self.current_layout_type == "grid":
                # Find widget position in grid
                for (r, c), w in self.viewer_widgets.items():
                    if w == widget:
                        self.grid_layout.removeWidget(widget)
                        del self.viewer_widgets[(r, c)]
                        self.viewer_removed.emit(r, c)
                        break
            else:
                # Remove from linear layout
                if self.current_layout_type == "horizontal":
                    self.horizontal_layout.removeWidget(widget)
                elif self.current_layout_type == "vertical":
                    self.vertical_layout.removeWidget(widget)
                
                # Remove from dictionary
                for key, w in list(self.viewer_widgets.items()):
                    if w == widget:
                        del self.viewer_widgets[key]
                        break
        elif row is not None and col is not None:
            if (row, col) in self.viewer_widgets:
                widget = self.viewer_widgets[(row, col)]
                self.grid_layout.removeWidget(widget)
                del self.viewer_widgets[(row, col)]
                self.viewer_removed.emit(row, col)
    
    def clear_layout(self):
        """Clear all viewers from the layout."""
        if self.current_layout_type == "grid":
            delete_widgets_in_layout(self.grid_layout)
        elif self.current_layout_type == "horizontal":
            delete_widgets_in_layout(self.horizontal_layout)
        elif self.current_layout_type == "vertical":
            delete_widgets_in_layout(self.vertical_layout)
        
        self.viewer_widgets.clear()
        self.layout_cleared.emit()
    
    def set_layout_type(self, layout_type: str):
        """
        Set the layout type.
        
        Args:
            layout_type: "grid", "horizontal", or "vertical"
        """
        if layout_type not in ["grid", "horizontal", "vertical"]:
            raise ValueError("Layout type must be 'grid', 'horizontal', or 'vertical'")
        
        # Store current widgets
        current_widgets = list(self.viewer_widgets.values())
        
        # Clear current layout
        self.clear_layout()
        
        # Set new layout type
        self.current_layout_type = layout_type
        
        # Re-add widgets to new layout
        for i, widget in enumerate(current_widgets):
            if layout_type == "grid":
                # Calculate grid position
                row = i // 2  # Assuming 2 columns
                col = i % 2
                self.add_viewer(widget, row, col)
            else:
                self.add_viewer(widget)
    
    def get_layout_type(self):
        """
        Get the current layout type.
        
        Returns:
            Current layout type string
        """
        return self.current_layout_type
    
    def get_viewer_count(self):
        """
        Get the number of viewers in the layout.
        
        Returns:
            Number of viewers
        """
        return len(self.viewer_widgets)
    
    def get_viewer_at_position(self, row: int, col: int):
        """
        Get viewer at specific position (for grid layout).
        
        Args:
            row: Row position
            col: Column position
            
        Returns:
            Widget at position or None
        """
        return self.viewer_widgets.get((row, col))
    
    def get_all_viewers(self):
        """
        Get all viewer widgets.
        
        Returns:
            List of all viewer widgets
        """
        return list(self.viewer_widgets.values())
    
    def set_grid_spacing(self, spacing: int):
        """
        Set spacing between grid items.
        
        Args:
            spacing: Spacing in pixels
        """
        self.grid_layout.setSpacing(spacing)
    
    def set_grid_margins(self, left: int, top: int, right: int, bottom: int):
        """
        Set grid layout margins.
        
        Args:
            left: Left margin
            top: Top margin
            right: Right margin
            bottom: Bottom margin
        """
        self.grid_layout.setContentsMargins(left, top, right, bottom)
    
    def set_linear_spacing(self, spacing: int):
        """
        Set spacing for linear layouts (horizontal/vertical).
        
        Args:
            spacing: Spacing in pixels
        """
        self.horizontal_layout.setSpacing(spacing)
        self.vertical_layout.setSpacing(spacing)
    
    def set_linear_margins(self, left: int, top: int, right: int, bottom: int):
        """
        Set margins for linear layouts.
        
        Args:
            left: Left margin
            top: Top margin
            right: Right margin
            bottom: Bottom margin
        """
        self.horizontal_layout.setContentsMargins(left, top, right, bottom)
        self.vertical_layout.setContentsMargins(left, top, right, bottom)
    
    def set_background_color(self, color: str):
        """
        Set background color.
        
        Args:
            color: Color string (e.g., "#21272a")
        """
        current_style = self.styleSheet()
        new_style = current_style.replace("background-color: #21272a;", f"background-color: {color};")
        self.setStyleSheet(new_style)
    
    def set_border_style(self, border: str):
        """
        Set border style.
        
        Args:
            border: border string (e.g., "1px solid #21272a")
        """
        current_style = self.styleSheet()
        new_style = current_style.replace("border: 1px solid #21272a;", f"border: {border};")
        self.setStyleSheet(new_style)
    
    def set_border_radius(self, radius: int):
        """
        Set border radius.
        
        Args:
            radius: border radius in pixels
        """
        current_style = self.styleSheet()
        new_style = current_style.replace("border-radius: 10px;", f"border-radius: {radius}px;")
        self.setStyleSheet(new_style)
    
    def update_style(self, style_dict: dict):
        """
        Update styling with custom properties.
        
        Args:
            style_dict: Dictionary containing style updates
        """
        current_style = self.styleSheet()
        
        for key, value in style_dict.items():
            current_style = current_style.replace(f"{key}:", f"{key}: {value};")
        
        self.setStyleSheet(current_style)
    
    def get_current_layout(self):
        """
        Get the current active layout.
        
        Returns:
            Current layout (QGridLayout, QHBoxLayout, or QVBoxLayout)
        """
        if self.current_layout_type == "grid":
            return self.grid_layout
        elif self.current_layout_type == "horizontal":
            return self.horizontal_layout
        elif self.current_layout_type == "vertical":
            return self.vertical_layout
    
    def set_layout_alignment(self, alignment: Qt.Alignment):
        """
        Set layout alignment.
        
        Args:
            alignment: Qt alignment flags
        """
        layout = self.get_current_layout()
        if layout:
            layout.setAlignment(alignment)
    
    def add_stretch(self, stretch: int = 0):
        """
        Add stretch to the current layout.
        
        Args:
            stretch: Stretch factor
        """
        layout = self.get_current_layout()
        if layout:
            if self.current_layout_type == "horizontal":
                self.horizontal_layout.addStretch(stretch)
            elif self.current_layout_type == "vertical":
                self.vertical_layout.addStretch(stretch)
    
    def set_widget_stretch(self, widget, stretch: int):
        """
        Set stretch factor for a widget in linear layouts.
        
        Args:
            widget: Widget to set stretch for
            stretch: Stretch factor
        """
        if self.current_layout_type == "horizontal":
            self.horizontal_layout.setStretchFactor(widget, stretch)
        elif self.current_layout_type == "vertical":
            self.vertical_layout.setStretchFactor(widget, stretch)
    
    def get_layout_info(self):
        """
        Get information about the current layout.
        
        Returns:
            Dictionary with layout information
        """
        return {
            "type": self.current_layout_type,
            "viewer_count": len(self.viewer_widgets),
            "viewers": list(self.viewer_widgets.keys()) if self.current_layout_type == "grid" else list(self.viewer_widgets.values()),
            "spacing": self.grid_layout.spacing() if self.current_layout_type == "grid" else 0,
            "margins": self.grid_layout.getContentsMargins() if self.current_layout_type == "grid" else (0, 0, 0, 0)
        }
    
    def resize_viewers(self, width: int, height: int):
        """
        Resize all viewers to specified dimensions.
        
        Args:
            width: Target width
            height: Target height
        """
        for widget in self.viewer_widgets.values():
            if hasattr(widget, 'setFixedSize'):
                widget.setFixedSize(width, height)
            elif hasattr(widget, 'resize'):
                widget.resize(width, height)
    
    def set_viewer_minimum_size(self, width: int, height: int):
        """
        Set minimum size for all viewers.
        
        Args:
            width: Minimum width
            height: Minimum height
        """
        for widget in self.viewer_widgets.values():
            if hasattr(widget, 'setMinimumSize'):
                widget.setMinimumSize(width, height)
    
    def set_viewer_maximum_size(self, width: int, height: int):
        """
        Set maximum size for all viewers.
        
        Args:
            width: Maximum width
            height: Maximum height
        """
        for widget in self.viewer_widgets.values():
            if hasattr(widget, 'setMaximumSize'):
                widget.setMaximumSize(width, height)
