"""
HeaderWidget Component

A reusable header component that provides toolbar functionality for the PatientWidget.
This component encapsulates all header-related functionality including toolbar creation,
styling, and action management.

Features:
- Toolbar with gradient background
- Integration with ToolbarManager
- Customizable styling
- Action management
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QToolBar
from PySide6.QtCore import Qt, Signal
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import ToolbarManager

# Theme-aware header toolbar: previously the gradient and border colors
# were hard-coded slate (#1f2937 → #111827, border #374151, separator
# #4b5563), which kept the same look under every workstation theme. Now
# the gradient + border come from the active theme's panel + border
# tokens, so a Green/Yellow/Dark Red theme paints a tonally consistent
# toolbar instead of a stranded slate strip.
try:
    from PacsClient.utils.theme_manager import get_theme_manager
except Exception:  # pragma: no cover — defensive fallback
    get_theme_manager = None


class HeaderWidget(QWidget):
    """
    Header component that provides toolbar functionality.
    
    Features:
    - Gradient background toolbar
    - Integration with ToolbarManager
    - Customizable styling
    - Action management
    """
    
    # Signals for header events
    action_triggered = Signal(str)  # Emits action name when triggered
    
    def __init__(self, parent=None):
        """
        Initialize the HeaderWidget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.parent_widget = parent
        self.toolbar_manager = None
        self.toolbar = None
        
        self._setup_ui()

        # Re-style on theme switch so the toolbar background follows the
        # active workstation theme live (no app restart needed).
        try:
            if get_theme_manager is not None:
                get_theme_manager().themeChanged.connect(self._on_theme_changed)
        except Exception:
            pass

    def _current_theme(self) -> dict:
        try:
            if get_theme_manager is not None:
                return get_theme_manager().current_theme() or {}
        except Exception:
            pass
        return {}

    def _on_theme_changed(self, _theme: dict) -> None:
        try:
            if self.toolbar is not None:
                self.toolbar.setStyleSheet(self._build_toolbar_stylesheet())
        except Exception:
            pass

    def _build_toolbar_stylesheet(self, start_color: str = "", end_color: str = "") -> str:
        """Stylesheet for the header toolbar.

        Reads start/end gradient colors from the theme by default
        (panel_alt_bg → panel_deep_bg), and uses the theme's `border` token
        for the surrounding frame and a slightly lighter mix for the
        separator. `start_color` / `end_color` overrides allow callers to
        force a specific gradient (used by `update_gradient`).
        """
        t = self._current_theme()
        gstart = start_color or t.get("panel_alt_bg", "#1f2937")
        gend = end_color or t.get("panel_deep_bg", "#111827")
        border = t.get("border", "#374151")
        # Separator: just the border with a touch more weight so it reads
        # as an intentional divider without competing with the toolbar's
        # own border.
        separator = t.get("border", "#4b5563")
        return f"""
            QToolBar {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {gstart}, stop:1 {gend});
                border: 1px solid {border};
                border-radius: 12px;
                padding: 2px;
                spacing: 2px;
            }}
            QToolBar::separator:horizontal {{
                width: 1px;
                background-color: {separator};
                margin: 1px 4px;
            }}
        """
    
    def _setup_ui(self):
        """Set up the header UI components."""
        # Create main layout
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(8, 4, 8, 4)
        self.main_layout.setSpacing(0)
        
        # Create toolbar
        self._create_toolbar()
        
        # Add toolbar to layout
        self.main_layout.addWidget(self.toolbar)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
    
    def _create_toolbar(self):
        """Create and configure the toolbar."""
        self.toolbar = QToolBar()
        # Theme-aware stylesheet (was hard-coded slate gradient + border).
        self.toolbar.setStyleSheet(self._build_toolbar_stylesheet())

        # Set toolbar properties
        self.toolbar.setContentsMargins(8, 4, 8, 4)

        # Initialize toolbar manager
        self._initialize_toolbar_manager()
    
    def _initialize_toolbar_manager(self):
        """Initialize the toolbar manager and add actions."""
        if self.parent_widget is not None:
            try:
                self.toolbar_manager = ToolbarManager(self.parent_widget)
                self.toolbar_manager.add_toolbar_actions(self.toolbar)
            except Exception as e:
                print(f"Warning: Could not initialize ToolbarManager: {e}")
                self.toolbar_manager = None
    
    def get_toolbar(self):
        """
        Get the toolbar widget.
        
        Returns:
            QToolBar instance
        """
        return self.toolbar
    
    def get_toolbar_manager(self):
        """
        Get the toolbar manager instance.
        
        Returns:
            ToolbarManager instance or None
        """
        return self.toolbar_manager
    
    def add_custom_action(self, action):
        """
        Add a custom action to the toolbar.
        
        Args:
            action: QAction to add to toolbar
        """
        if self.toolbar:
            self.toolbar.addAction(action)
    
    def add_separator(self):
        """Add a separator to the toolbar."""
        if self.toolbar:
            self.toolbar.addSeparator()
    
    def clear_actions(self):
        """Clear all actions from the toolbar."""
        if self.toolbar:
            self.toolbar.clear()
    
    def set_toolbar_style(self, style_dict: dict):
        """
        Update the toolbar styling.
        
        Args:
            style_dict: Dictionary containing style updates
        """
        if not self.toolbar:
            return
            
        current_style = self.toolbar.styleSheet()
        
        # Apply new styles
        for key, value in style_dict.items():
            current_style = current_style.replace(f"{key}:", f"{key}: {value};")
        
        self.toolbar.setStyleSheet(current_style)
    
    def update_gradient(self, start_color: str, end_color: str):
        """
        Update the toolbar gradient colors.
        
        Args:
            start_color: Starting color for gradient
            end_color: Ending color for gradient
        """
        # Build with explicit gradient overrides but still derive border /
        # separator from the active theme so caller-specified gradients
        # don't trap the rest of the chrome in slate.
        self.toolbar.setStyleSheet(
            self._build_toolbar_stylesheet(start_color=start_color, end_color=end_color)
        )
    
    def set_toolbar_enabled(self, enabled: bool):
        """
        Enable or disable the toolbar.
        
        Args:
            enabled: Whether to enable the toolbar
        """
        if self.toolbar:
            self.toolbar.setEnabled(enabled)
    
    def get_toolbar_actions(self):
        """
        Get all toolbar actions.
        
        Returns:
            List of QAction objects
        """
        if self.toolbar:
            return self.toolbar.actions()
        return []
    
    def find_action(self, text: str):
        """
        Find an action by its text.
        
        Args:
            text: Action text to search for
            
        Returns:
            QAction if found, None otherwise
        """
        if not self.toolbar:
            return None
            
        for action in self.toolbar.actions():
            if action.text() == text:
                return action
        return None
    
    def set_action_enabled(self, action_text: str, enabled: bool):
        """
        Enable or disable a specific action.
        
        Args:
            action_text: Text of the action to modify
            enabled: Whether to enable the action
        """
        action = self.find_action(action_text)
        if action:
            action.setEnabled(enabled)
    
    def set_toolbar_orientation(self, orientation: Qt.Orientation):
        """
        Set the toolbar orientation.
        
        Args:
            orientation: Qt.Horizontal or Qt.Vertical
        """
        if self.toolbar:
            self.toolbar.setOrientation(orientation)
    
    def set_toolbar_movable(self, movable: bool):
        """
        Set whether the toolbar is movable.
        
        Args:
            movable: Whether the toolbar can be moved
        """
        if self.toolbar:
            self.toolbar.setMovable(movable)
    
    def set_toolbar_floatable(self, floatable: bool):
        """
        Set whether the toolbar is floatable.
        
        Args:
            floatable: Whether the toolbar can be floated
        """
        if self.toolbar:
            self.toolbar.setFloatable(floatable)
    
    def get_toolbar_size(self):
        """
        Get the toolbar size.
        
        Returns:
            QSize of the toolbar
        """
        if self.toolbar:
            return self.toolbar.size()
        return None
    
    def set_toolbar_size(self, width: int, height: int):
        """
        Set the toolbar size.
        
        Args:
            width: Toolbar width
            height: Toolbar height
        """
        if self.toolbar:
            self.toolbar.setFixedSize(width, height)
    
    def refresh_toolbar(self):
        """Refresh the toolbar by reinitializing the toolbar manager."""
        if self.toolbar_manager and self.parent_widget:
            try:
                self.toolbar.clear()
                self.toolbar_manager.add_toolbar_actions(self.toolbar)
            except Exception as e:
                print(f"Error refreshing toolbar: {e}")
    
    def set_custom_toolbar_manager(self, toolbar_manager):
        """
        Set a custom toolbar manager.
        
        Args:
            toolbar_manager: Custom ToolbarManager instance
        """
        self.toolbar_manager = toolbar_manager
        if self.toolbar and toolbar_manager:
            try:
                self.toolbar.clear()
                toolbar_manager.add_toolbar_actions(self.toolbar)
            except Exception as e:
                print(f"Error setting custom toolbar manager: {e}")
    
    def get_layout(self):
        """
        Get the main layout.
        
        Returns:
            QHBoxLayout instance
        """
        return self.main_layout
    
    def add_widget_to_header(self, widget, stretch=0):
        """
        Add a widget to the header layout.
        
        Args:
            widget: Widget to add
            stretch: Stretch factor for the widget
        """
        self.main_layout.addWidget(widget, stretch)
    
    def add_stretch(self, stretch=0):
        """
        Add stretch to the header layout.
        
        Args:
            stretch: Stretch factor
        """
        self.main_layout.addStretch(stretch)
    
    def set_header_margins(self, left: int, top: int, right: int, bottom: int):
        """
        Set the header layout margins.
        
        Args:
            left: Left margin
            top: Top margin
            right: Right margin
            bottom: Bottom margin
        """
        self.main_layout.setContentsMargins(left, top, right, bottom)
    
    def set_header_spacing(self, spacing: int):
        """
        Set the header layout spacing.
        
        Args:
            spacing: Spacing between widgets
        """
        self.main_layout.setSpacing(spacing)
