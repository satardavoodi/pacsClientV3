"""
MultiViewerLayoutManager Component

A comprehensive layout manager for handling multiple viewer configurations in the PatientWidget.
This component encapsulates all multi-viewer layout functionality including grid configurations,
viewer positioning, and layout management.

Features:
- Support for all grid configurations (1x1 to 4x4)
- Viewer positioning and management
- Layout switching
- Viewer creation and deletion
- border management
- Layout optimization
"""

from PySide6.QtCore import Qt, Signal, QObject
from PacsClient.pacs.patient_tab.utils import delete_widgets_in_layout


class MultiViewerLayoutManager(QObject):
    """
    Multi-viewer layout manager that handles all grid configurations and viewer positioning.
    
    Features:
    - Support for all grid configurations (1x1 to 4x4)
    - Viewer positioning and management
    - Layout switching
    - Viewer creation and deletion
    """
    
    # Signals for layout events
    layout_changed = Signal(tuple)  # Emits (rows, cols) when layout changes
    viewer_added = Signal(int, int, object)  # Emits row, col, widget when viewer added
    viewer_removed = Signal(int, int)  # Emits row, col when viewer removed
    
    def __init__(self, center_layout_widget, viewer_creation_callback=None):
        """
        Initialize the MultiViewerLayoutManager.
        
        Args:
            center_layout_widget: CenterLayoutWidget instance
            viewer_creation_callback: Function to create new viewers
        """
        super().__init__()
        self.center_layout = center_layout_widget
        self.viewer_creation_callback = viewer_creation_callback
        self.current_layout = (1, 1)  # (rows, cols)
        self.viewer_widgets = []  # List of viewer widgets
        self.selected_viewer_index = 0
        
        # Layout configuration mappings
        self.layout_configs = {
            (1, 1): self._setup_1x1,
            (1, 2): self._setup_1x2,
            (1, 3): self._setup_1x3,
            (1, 4): self._setup_1x4,
            (2, 1): self._setup_2x1,
            (3, 1): self._setup_3x1,
            (4, 1): self._setup_4x1,
            (2, 2): self._setup_2x2,
            (2, 3): self._setup_2x3,
            (2, 4): self._setup_2x4,
            (3, 2): self._setup_3x2,
            (3, 3): self._setup_3x3,
            (3, 4): self._setup_3x4,
            (4, 2): self._setup_4x2,
            (4, 3): self._setup_4x3,
            (4, 4): self._setup_4x4,
        }
    
    def set_layout(self, rows: int, cols: int):
        """
        Set the viewer layout configuration.
        
        Args:
            rows: Number of rows
            cols: Number of columns
        """
        if (rows, cols) not in self.layout_configs:
            raise ValueError(f"Unsupported layout configuration: {rows}x{cols}")
        
        # Clear current layout
        self._clear_layout()
        
        # Create required viewers
        required_viewers = rows * cols
        self._ensure_viewers(required_viewers)
        
        # Apply new layout
        self.layout_configs[(rows, cols)]()
        
        # Update current layout
        self.current_layout = (rows, cols)
        self.layout_changed.emit(self.current_layout)
    
    def _clear_layout(self):
        """Clear the current layout."""
        self.center_layout.clear_layout()
    
    def _ensure_viewers(self, count: int):
        """
        Ensure we have enough viewers for the layout.
        
        Args:
            count: Required number of viewers
        """
        while len(self.viewer_widgets) < count:
            if self.viewer_creation_callback:
                new_viewer = self.viewer_creation_callback()
                self.viewer_widgets.append(new_viewer)
            else:
                # Create a placeholder viewer if no callback provided
                from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
                placeholder = QWidget()
                placeholder.setStyleSheet("background-color: #333; border: 1px solid #555;")
                label = QLabel(f"Viewer {len(self.viewer_widgets) + 1}")
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setStyleSheet("color: white; font-size: 16px;")
                layout = QVBoxLayout(placeholder)
                layout.addWidget(label)
                placeholder.setLayout(layout)
                self.viewer_widgets.append(placeholder)
    
    def _setup_1x1(self):
        """Setup 1x1 layout."""
        if len(self.viewer_widgets) >= 1:
            self.center_layout.add_viewer(self.viewer_widgets[0], 0, 0)
            self.viewer_added.emit(0, 0, self.viewer_widgets[0])
    
    def _setup_1x2(self):
        """Setup 1x2 layout."""
        if len(self.viewer_widgets) >= 2:
            self.center_layout.add_viewer(self.viewer_widgets[0], 0, 0)
            self.center_layout.add_viewer(self.viewer_widgets[1], 0, 1)
            self.viewer_added.emit(0, 0, self.viewer_widgets[0])
            self.viewer_added.emit(0, 1, self.viewer_widgets[1])
    
    def _setup_1x3(self):
        """Setup 1x3 layout."""
        if len(self.viewer_widgets) >= 3:
            for i in range(3):
                self.center_layout.add_viewer(self.viewer_widgets[i], 0, i)
                self.viewer_added.emit(0, i, self.viewer_widgets[i])
    
    def _setup_1x4(self):
        """Setup 1x4 layout."""
        if len(self.viewer_widgets) >= 4:
            for i in range(4):
                self.center_layout.add_viewer(self.viewer_widgets[i], 0, i)
                self.viewer_added.emit(0, i, self.viewer_widgets[i])
    
    def _setup_2x1(self):
        """Setup 2x1 layout."""
        if len(self.viewer_widgets) >= 2:
            self.center_layout.add_viewer(self.viewer_widgets[0], 0, 0)
            self.center_layout.add_viewer(self.viewer_widgets[1], 1, 0)
            self.viewer_added.emit(0, 0, self.viewer_widgets[0])
            self.viewer_added.emit(1, 0, self.viewer_widgets[1])
    
    def _setup_3x1(self):
        """Setup 3x1 layout."""
        if len(self.viewer_widgets) >= 3:
            for i in range(3):
                self.center_layout.add_viewer(self.viewer_widgets[i], i, 0)
                self.viewer_added.emit(i, 0, self.viewer_widgets[i])
    
    def _setup_4x1(self):
        """Setup 4x1 layout."""
        if len(self.viewer_widgets) >= 4:
            for i in range(4):
                self.center_layout.add_viewer(self.viewer_widgets[i], i, 0)
                self.viewer_added.emit(i, 0, self.viewer_widgets[i])
    
    def _setup_2x2(self):
        """Setup 2x2 layout."""
        if len(self.viewer_widgets) >= 4:
            positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
            for i, (row, col) in enumerate(positions):
                self.center_layout.add_viewer(self.viewer_widgets[i], row, col)
                self.viewer_added.emit(row, col, self.viewer_widgets[i])
    
    def _setup_2x3(self):
        """Setup 2x3 layout."""
        if len(self.viewer_widgets) >= 6:
            positions = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]
            for i, (row, col) in enumerate(positions):
                self.center_layout.add_viewer(self.viewer_widgets[i], row, col)
                self.viewer_added.emit(row, col, self.viewer_widgets[i])
    
    def _setup_2x4(self):
        """Setup 2x4 layout."""
        if len(self.viewer_widgets) >= 8:
            positions = [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3)]
            for i, (row, col) in enumerate(positions):
                self.center_layout.add_viewer(self.viewer_widgets[i], row, col)
                self.viewer_added.emit(row, col, self.viewer_widgets[i])
    
    def _setup_3x2(self):
        """Setup 3x2 layout."""
        if len(self.viewer_widgets) >= 6:
            positions = [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]
            for i, (row, col) in enumerate(positions):
                self.center_layout.add_viewer(self.viewer_widgets[i], row, col)
                self.viewer_added.emit(row, col, self.viewer_widgets[i])
    
    def _setup_3x3(self):
        """Setup 3x3 layout."""
        if len(self.viewer_widgets) >= 9:
            positions = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)]
            for i, (row, col) in enumerate(positions):
                self.center_layout.add_viewer(self.viewer_widgets[i], row, col)
                self.viewer_added.emit(row, col, self.viewer_widgets[i])
    
    def _setup_3x4(self):
        """Setup 3x4 layout."""
        if len(self.viewer_widgets) >= 12:
            positions = [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3), (2, 0), (2, 1), (2, 2), (2, 3)]
            for i, (row, col) in enumerate(positions):
                self.center_layout.add_viewer(self.viewer_widgets[i], row, col)
                self.viewer_added.emit(row, col, self.viewer_widgets[i])
    
    def _setup_4x2(self):
        """Setup 4x2 layout."""
        if len(self.viewer_widgets) >= 8:
            positions = [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1), (3, 0), (3, 1)]
            for i, (row, col) in enumerate(positions):
                self.center_layout.add_viewer(self.viewer_widgets[i], row, col)
                self.viewer_added.emit(row, col, self.viewer_widgets[i])
    
    def _setup_4x3(self):
        """Setup 4x3 layout."""
        if len(self.viewer_widgets) >= 12:
            positions = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2), (3, 0), (3, 1), (3, 2)]
            for i, (row, col) in enumerate(positions):
                self.center_layout.add_viewer(self.viewer_widgets[i], row, col)
                self.viewer_added.emit(row, col, self.viewer_widgets[i])
    
    def _setup_4x4(self):
        """Setup 4x4 layout."""
        if len(self.viewer_widgets) >= 16:
            positions = [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3), (2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3)]
            for i, (row, col) in enumerate(positions):
                self.center_layout.add_viewer(self.viewer_widgets[i], row, col)
                self.viewer_added.emit(row, col, self.viewer_widgets[i])
    
    def get_current_layout(self):
        """
        Get the current layout configuration.
        
        Returns:
            Tuple of (rows, cols)
        """
        return self.current_layout
    
    def get_viewer_count(self):
        """
        Get the number of viewers.
        
        Returns:
            Number of viewers
        """
        return len(self.viewer_widgets)
    
    def get_viewer_at_position(self, row: int, col: int):
        """
        Get viewer at specific position.
        
        Args:
            row: Row position
            col: Column position
            
        Returns:
            Viewer widget or None
        """
        # Calculate index from position
        index = row * self.current_layout[1] + col
        if 0 <= index < len(self.viewer_widgets):
            return self.viewer_widgets[index]
        return None
    
    def get_viewer_by_index(self, index: int):
        """
        Get viewer by index.
        
        Args:
            index: Viewer index
            
        Returns:
            Viewer widget or None
        """
        if 0 <= index < len(self.viewer_widgets):
            return self.viewer_widgets[index]
        return None
    
    def set_selected_viewer(self, index: int):
        """
        Set the selected viewer index.
        
        Args:
            index: Viewer index to select
        """
        if 0 <= index < len(self.viewer_widgets):
            self.selected_viewer_index = index
    
    def get_selected_viewer(self):
        """
        Get the selected viewer.
        
        Returns:
            Selected viewer widget or None
        """
        return self.get_viewer_by_index(self.selected_viewer_index)
    
    def add_viewer(self, viewer_widget):
        """
        Add a new viewer to the collection.
        
        Args:
            viewer_widget: Viewer widget to add
        """
        self.viewer_widgets.append(viewer_widget)
    
    def remove_viewer(self, index: int):
        """
        Remove a viewer by index.
        
        Args:
            index: Index of viewer to remove
        """
        if 0 <= index < len(self.viewer_widgets):
            viewer = self.viewer_widgets.pop(index)
            # Remove from layout
            self.center_layout.remove_viewer(widget=viewer)
            viewer.deleteLater()
            
            # Adjust selected index if necessary
            if self.selected_viewer_index >= index:
                self.selected_viewer_index = max(0, self.selected_viewer_index - 1)
    
    def clear_all_viewers(self):
        """Clear all viewers."""
        for viewer in self.viewer_widgets:
            self.center_layout.remove_viewer(widget=viewer)
            viewer.deleteLater()
        self.viewer_widgets.clear()
        self.selected_viewer_index = 0
    
    def get_supported_layouts(self):
        """
        Get list of supported layout configurations.
        
        Returns:
            List of (rows, cols) tuples
        """
        return list(self.layout_configs.keys())
    
    def is_layout_supported(self, rows: int, cols: int):
        """
        Check if a layout configuration is supported.
        
        Args:
            rows: Number of rows
            cols: Number of columns
            
        Returns:
            True if supported, False otherwise
        """
        return (rows, cols) in self.layout_configs
    
    def get_layout_info(self):
        """
        Get information about the current layout.
        
        Returns:
            Dictionary with layout information
        """
        return {
            "current_layout": self.current_layout,
            "viewer_count": len(self.viewer_widgets),
            "selected_index": self.selected_viewer_index,
            "supported_layouts": self.get_supported_layouts(),
            "viewers": [f"Viewer {i}" for i in range(len(self.viewer_widgets))]
        }
    
    def set_viewer_creation_callback(self, callback):
        """
        Set the callback function for creating new viewers.
        
        Args:
            callback: Function that creates and returns a new viewer widget
        """
        self.viewer_creation_callback = callback
    
    def refresh_layout(self):
        """Refresh the current layout."""
        current_layout = self.current_layout
        self.set_layout(current_layout[0], current_layout[1])
    
    def optimize_layout(self):
        """
        Optimize the layout based on the number of viewers.
        This method automatically selects the best layout configuration.
        """
        viewer_count = len(self.viewer_widgets)
        
        # Find the best layout for the number of viewers
        best_layout = (1, 1)
        min_waste = float('inf')
        
        for rows, cols in self.layout_configs.keys():
            total_slots = rows * cols
            if total_slots >= viewer_count:
                waste = total_slots - viewer_count
                if waste < min_waste:
                    min_waste = waste
                    best_layout = (rows, cols)
        
        self.set_layout(best_layout[0], best_layout[1])
    
    def set_viewer_borders(self, border_style: str):
        """
        Set border style for all viewers.
        
        Args:
            border_style: CSS border style string
        """
        for viewer in self.viewer_widgets:
            if hasattr(viewer, 'setStyleSheet'):
                current_style = viewer.styleSheet()
                new_style = current_style + f" border: {border_style};"
                viewer.setStyleSheet(new_style)
    
    def highlight_selected_viewer(self, highlight: bool = True):
        """
        Highlight the selected viewer.
        
        Args:
            highlight: Whether to highlight or remove highlight
        """
        selected_viewer = self.get_selected_viewer()
        if selected_viewer and hasattr(selected_viewer, 'setStyleSheet'):
            if highlight:
                current_style = selected_viewer.styleSheet()
                new_style = current_style + " border: 2px solid #2196f3;"
                selected_viewer.setStyleSheet(new_style)
            else:
                # Remove highlight
                current_style = selected_viewer.styleSheet()
                new_style = current_style.replace(" border: 2px solid #2196f3;", "")
                selected_viewer.setStyleSheet(new_style)
