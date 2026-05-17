"""
SidebarWidget Component

A reusable sidebar component for the PatientWidget that provides navigation
between different panels (Series, Reception Data, AI Chat).

This component encapsulates all sidebar-related functionality including:
- Vertical button creation and styling
- Panel switching logic
- Button state management
- AI Chat widget integration
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QButtonGroup
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter


class VerticalButton(QPushButton):
    """
    Custom button that displays text vertically (rotated 90 degrees).
    Used for sidebar navigation buttons.
    """
    
    def paintEvent(self, event):
        """Override paintEvent to draw text vertically."""
        painter = QPainter(self)
        painter.save()
        painter.translate(self.width(), 0)
        painter.rotate(90)
        painter.drawText(0, 0, self.height(), self.width(),
                         Qt.AlignmentFlag.AlignCenter, self.text())
        painter.restore()


class SidebarWidget(QWidget):
    """
    Sidebar component that provides navigation between different panels.
    
    Features:
    - Vertical navigation buttons (Series, Reception Data, AI Chat)
    - Exclusive button selection
    - Custom styling for active/inactive states
    - Signal-based communication with parent widget
    - AI Chat widget integration
    """
    
    # Signals for panel switching
    panel_switched = Signal(str)  # Emits panel name when switched
    
    def __init__(self, parent=None):
        """
        Initialize the SidebarWidget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.parent_widget = parent
        self.ai_chat_widget = None
        self.current_panel = "series"  # Default panel
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        """Set up the sidebar UI components."""
        # Configure sidebar widget
        self.setFixedWidth(40)
        self.setStyleSheet("""
            background-color: #171b1e;
            border-top-left-radius: 12px;
            border-bottom-left-radius: 12px;
            margin: 0px;
            padding: 0px;
        """)
        
        # Create main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create navigation buttons
        self._create_navigation_buttons()
        
        # Add buttons to layout
        layout.addWidget(self.btn_series)
        layout.addWidget(self.btn_reception)
        layout.addWidget(self.btn_ai_chat)
        layout.addStretch()
    
    def _create_navigation_buttons(self):
        """Create and configure navigation buttons."""
        # Series button
        self.btn_series = VerticalButton("Series")
        self.btn_series.setFixedHeight(100)
        self.btn_series.setCheckable(True)
        self.btn_series.setChecked(True)
        self.btn_series.setStyleSheet(self._get_button_style(True))
        
        # Reception Data button
        self.btn_reception = VerticalButton("Reception Data")
        self.btn_reception.setFixedHeight(100)
        self.btn_reception.setCheckable(True)
        self.btn_reception.setStyleSheet(self._get_button_style(False))
        
        # AI Chat button
        self.btn_ai_chat = VerticalButton("AI Chat")
        self.btn_ai_chat.setFixedHeight(100)
        self.btn_ai_chat.setCheckable(True)
        self.btn_ai_chat.setStyleSheet(self._get_button_style(False))
        
        # Create button group for exclusive selection
        self.sidebar_btn_group = QButtonGroup(self)
        self.sidebar_btn_group.setExclusive(True)
        self.sidebar_btn_group.addButton(self.btn_series)
        self.sidebar_btn_group.addButton(self.btn_reception)
        self.sidebar_btn_group.addButton(self.btn_ai_chat)
    
    def _connect_signals(self):
        """Connect button signals to handlers."""
        self.btn_series.clicked.connect(self._on_series_clicked)
        self.btn_reception.clicked.connect(self._on_reception_clicked)
        self.btn_ai_chat.clicked.connect(self._on_ai_chat_clicked)

    def _on_series_clicked(self):
        self._switch_panel("series")

    def _on_reception_clicked(self):
        self._switch_panel("reception")

    def _on_ai_chat_clicked(self):
        self._switch_panel("ai_chat")
    
    def _get_button_style(self, checked: bool) -> str:
        """
        Get the appropriate button style based on checked state.
        
        Args:
            checked: Whether the button is checked/active
            
        Returns:
            CSS style string for the button
        """
        if checked:
            return """
                QPushButton {
                    background-color: #2196f3;
                    color: white;
                    font-weight: bold;
                    font-size: 14px;
                    line-height: 1.4;
                    letter-spacing: 0.5px;
                    border: none;
                    border-radius: 8px;
                    padding: 14px 0;
                }
                QPushButton:hover {
                    background-color: #1976d2;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: #222;
                    color: #aaa;
                    font-weight: bold;
                    font-size: 14px;
                    line-height: 1.4;
                    letter-spacing: 0.5px;
                    border: none;
                    border-radius: 8px;
                    padding: 14px 0;
                }
                QPushButton:hover {
                    background-color: #333;
                    color: #ccc;
                }
            """
    
    def _switch_panel(self, panel_name: str):
        """
        Handle panel switching logic.
        
        Args:
            panel_name: Name of the panel to switch to
        """
        self.current_panel = panel_name
        
        # Update button styles
        self._update_button_styles(panel_name)
        
        # Handle AI Chat widget creation if needed
        if panel_name == "ai_chat":
            self._ensure_ai_chat_widget()
        
        # Emit signal for parent widget to handle
        self.panel_switched.emit(panel_name)
    
    def _update_button_styles(self, active_panel: str):
        """
        Update button styles based on active panel.
        
        Args:
            active_panel: Name of the currently active panel
        """
        self.btn_series.setStyleSheet(
            self._get_button_style(active_panel == "series")
        )
        self.btn_reception.setStyleSheet(
            self._get_button_style(active_panel == "reception")
        )
        self.btn_ai_chat.setStyleSheet(
            self._get_button_style(active_panel == "ai_chat")
        )
    
    def _ensure_ai_chat_widget(self):
        """
        Ensure AI Chat widget exists and is properly integrated.
        This method handles the creation and integration of the AI Chat widget.
        """
        if self.ai_chat_widget is None:
            try:
                from modules.EchoMind.viewer_chat.ai_chat_viewer import AIChatViewer
                self.ai_chat_widget = AIChatViewer()
                
                # If parent has right_panel, add the widget
                if (hasattr(self.parent_widget, 'right_panel') and 
                    self.parent_widget.right_panel is not None):
                    self.parent_widget.right_panel.addWidget(self.ai_chat_widget)
                    
            except ImportError as e:
                print(f"Warning: Could not import AIChatViewer: {e}")
                self.ai_chat_widget = None
            except Exception as e:
                print(f"Error creating AI Chat widget: {e}")
                self.ai_chat_widget = None
    
    def switch_to_panel(self, panel_name: str):
        """
        Programmatically switch to a specific panel.
        
        Args:
            panel_name: Name of the panel to switch to
        """
        if panel_name in ["series", "reception", "ai_chat"]:
            self._switch_panel(panel_name)
    
    def get_current_panel(self) -> str:
        """
        Get the currently active panel name.
        
        Returns:
            Name of the currently active panel
        """
        return self.current_panel
    
    def set_button_enabled(self, button_name: str, enabled: bool):
        """
        Enable or disable a specific button.
        
        Args:
            button_name: Name of the button ("series", "reception", "ai_chat")
            enabled: Whether to enable the button
        """
        button_map = {
            "series": self.btn_series,
            "reception": self.btn_reception,
            "ai_chat": self.btn_ai_chat
        }
        
        if button_name in button_map:
            button_map[button_name].setEnabled(enabled)
    
    def get_ai_chat_widget(self):
        """
        Get the AI Chat widget instance.
        
        Returns:
            AIChatViewer instance or None if not created
        """
        return self.ai_chat_widget
    
    def add_custom_button(self, text: str, callback=None, position: int = None):
        """
        Add a custom vertical button to the sidebar.
        
        Args:
            text: Button text
            callback: Function to call when button is clicked
            position: Position to insert button (None for end)
        """
        button = VerticalButton(text)
        button.setFixedHeight(100)
        button.setCheckable(True)
        button.setStyleSheet(self._get_button_style(False))
        
        # Add to button group
        self.sidebar_btn_group.addButton(button)
        
        # Add to layout
        layout = self.layout()
        if position is None:
            layout.insertWidget(layout.count() - 1, button)  # Before stretch
        else:
            layout.insertWidget(position, button)
        
        # Connect callback if provided
        if callback:
            button.clicked.connect(callback)
        
        return button
    
    def remove_custom_button(self, button):
        """
        Remove a custom button from the sidebar.
        
        Args:
            button: Button widget to remove
        """
        if button in self.sidebar_btn_group.buttons():
            self.sidebar_btn_group.removeButton(button)
            self.layout().removeWidget(button)
            button.deleteLater()
    
    def update_style(self, style_dict: dict):
        """
        Update the sidebar styling.
        
        Args:
            style_dict: Dictionary containing style updates
        """
        current_style = self.styleSheet()
        
        # Apply new styles
        for key, value in style_dict.items():
            current_style = current_style.replace(f"{key}:", f"{key}: {value};")
        
        self.setStyleSheet(current_style)
