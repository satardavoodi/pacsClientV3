"""
Tools Settings UI Panel
User interface for customizing reference line and measurement tools appearance
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QGroupBox, QDoubleSpinBox, QSlider, QColorDialog, QFormLayout,
                               QMessageBox, QFrame, QTabWidget)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PacsClient.pacs.patient_tab.utils.tools_settings import (
    get_tools_settings, ToolStyle, ToolsSettings
)


class ColorButton(QPushButton):
    """Button that shows current color and opens color picker"""
    colorChanged = Signal(tuple)  # RGB tuple (0-1 range)
    
    def __init__(self, initial_color=(0.0, 0.9, 0.0), parent=None):
        super().__init__(parent)
        self.current_color = initial_color
        self.clicked.connect(self.pick_color)
        self.update_button_color()
        self.setFixedHeight(34)
        self.setCursor(Qt.PointingHandCursor)
    
    def update_button_color(self):
        """Update button background color"""
        # Convert from 0-1 range to 0-255 range
        r = int(self.current_color[0] * 255)
        g = int(self.current_color[1] * 255)
        b = int(self.current_color[2] * 255)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: rgb({r}, {g}, {b});
                border: 2px solid #4a5568;
                border-radius: 4px;
                min-width: 80px;
            }}
            QPushButton:hover {{
                border: 2px solid #3182ce;
            }}
        """)
    
    def pick_color(self):
        """Open color picker dialog"""
        # Convert from 0-1 range to QColor (0-255 range)
        initial_color = QColor(
            int(self.current_color[0] * 255),
            int(self.current_color[1] * 255),
            int(self.current_color[2] * 255)
        )
        
        color = QColorDialog.getColor(initial_color, self, "Select Color")
        if color.isValid():
            # Convert back to 0-1 range
            self.current_color = (
                color.red() / 255.0,
                color.green() / 255.0,
                color.blue() / 255.0
            )
            self.update_button_color()
            self.colorChanged.emit(self.current_color)
    
    def set_color(self, color_tuple):
        """Set color programmatically"""
        self.current_color = color_tuple
        self.update_button_color()


class ToolSettingsPanel(QGroupBox):
    """Panel for editing a single tool's settings"""
    
    def __init__(self, tool_name, tool_display_name, style: ToolStyle, parent=None):
        super().__init__(tool_display_name, parent)
        self.tool_name = tool_name
        self.style = style
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the UI elements"""
        layout = QFormLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Line Width
        line_width_layout = QHBoxLayout()
        self.line_width_spin = QDoubleSpinBox()
        self.line_width_spin.setRange(0.5, 20.0)
        self.line_width_spin.setSingleStep(0.5)
        self.line_width_spin.setValue(self.style.line_width)
        self.line_width_spin.setFixedWidth(90)
        self.line_width_spin.setSuffix(" px")
        line_width_layout.addWidget(self.line_width_spin)
        line_width_layout.addStretch()
        layout.addRow("Line Width:", line_width_layout)
        
        # Color
        color_layout = QHBoxLayout()
        self.color_button = ColorButton(self.style.color)
        color_layout.addWidget(self.color_button)
        color_layout.addStretch()
        layout.addRow("Color:", color_layout)
        
        # Opacity
        opacity_layout = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(int(self.style.opacity * 100))
        self.opacity_slider.setTickPosition(QSlider.TicksBelow)
        self.opacity_slider.setTickInterval(10)
        self.opacity_label = QLabel(f"{int(self.style.opacity * 100)}%")
        self.opacity_label.setMinimumWidth(50)
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_label.setText(f"{v}%")
        )
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addWidget(self.opacity_label)
        layout.addRow("Opacity:", opacity_layout)
        
        # Font Size (for text labels)
        font_size_layout = QHBoxLayout()
        self.font_size_spin = QDoubleSpinBox()
        self.font_size_spin.setRange(8, 72)
        self.font_size_spin.setSingleStep(2)
        self.font_size_spin.setValue(self.style.font_size)
        self.font_size_spin.setFixedWidth(90)
        self.font_size_spin.setSuffix(" pt")
        font_size_layout.addWidget(self.font_size_spin)
        font_size_layout.addStretch()
        layout.addRow("Font Size:", font_size_layout)
        
        self.setLayout(layout)
    
    def get_current_style(self) -> ToolStyle:
        """Get the current style from UI"""
        return ToolStyle(
            line_width=self.line_width_spin.value(),
            color=self.color_button.current_color,
            opacity=self.opacity_slider.value() / 100.0,
            font_size=int(self.font_size_spin.value())
        )


class ToolsSettingsWidget(QWidget):
    """Main widget for tools settings"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings_manager = get_tools_settings()
        self.tool_panels = {}  # Initialize tool panels dictionary
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the main UI"""
        # Apply dark theme
        self.setStyleSheet("""
            QWidget {
                background-color: #1a202c;
                color: #e2e8f0;
            }
            QGroupBox {
                background-color: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 8px;
                padding: 15px;
                margin-top: 10px;
                font-weight: bold;
                color: #e2e8f0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                font-size: 14px;
            }
            QLabel {
                color: #e2e8f0;
                font-size: 14px;
            }
            QDoubleSpinBox, QSpinBox {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 5px 8px;
                min-height: 34px;
                font-size: 14px;
            }
            QDoubleSpinBox:focus, QSpinBox:focus {
                border: 1px solid #3182ce;
            }
            QSlider::groove:horizontal {
                background-color: #4a5568;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background-color: #3182ce;
                width: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background-color: #2c5aa0;
            }
            QTabWidget::pane {
                background-color: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #1a202c;
                color: #e2e8f0;
                padding: 7px 14px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 14px;
            }
            QTabBar::tab:selected {
                background-color: #2d3748;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #374151;
            }
            QPushButton {
                background-color: #3182ce;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 14px;
                min-height: 36px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
            QPushButton:pressed {
                background-color: #1e4a8a;
            }
        """)
        
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Title
        title_label = QLabel("Tools & Reference Line Settings")
        title_label.setStyleSheet(
            "font-size: 18px; font-weight: 800; padding: 10px; color: #e2e8f0;"
        )
        main_layout.addWidget(title_label)


                

        # Description
        desc_label = QLabel(
            "Customize the appearance of measurement tools and reference lines.\n"
            "Changes are saved automatically to the database."
        )
        desc_label.setStyleSheet("color: #a0aec0; padding: 5px 10px;")
        desc_label.setWordWrap(True)
        main_layout.addWidget(desc_label)
                
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("color: #334155;")
        main_layout.addWidget(separator)
                
        # Tab widget for different tools
        tabs = QTabWidget()
        
        # Get current settings
        settings = self.settings_manager.get_settings()
        
        # Create tabs for each tool
        tools = [
            ('reference_line', 'Reference Line', settings.reference_line),
            ('ruler', 'Ruler Tool', settings.ruler),
            ('arrow', 'Arrow Tool', settings.arrow),
            ('angle', 'Angle Tool', settings.angle),
            ('polygon', 'Polygon Tool', settings.polygon),
            ('rectangle', 'Rectangle Tool', settings.rectangle),
        ]
        
        for tool_name, display_name, style in tools:
            panel = ToolSettingsPanel(tool_name, display_name, style)
            self.tool_panels[tool_name] = panel
            tabs.addTab(panel, display_name)
        
        main_layout.addWidget(tabs)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Reset to defaults button
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        reset_btn.setFixedWidth(140)
        button_layout.addWidget(reset_btn)
        
        # Save button
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setFixedWidth(140)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #48bb78;
                color: white;
                font-weight: bold;
                padding: 8px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #38a169;
            }
        """)
        button_layout.addWidget(save_btn)
        
        main_layout.addLayout(button_layout)
        
        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #48bb78; padding: 5px 10px;")
        main_layout.addWidget(self.status_label)
        
        main_layout.addStretch()
        
        self.setLayout(main_layout)
    
    def save_settings(self):
        """Save all settings to database"""
        try:
            print("💾 [SETTINGS UI] Starting save...")
            
            # Update each tool's settings
            for tool_name, panel in self.tool_panels.items():
                current_style = panel.get_current_style()
                print(f"💾 [SETTINGS UI] Updating {tool_name}: width={current_style.line_width}, color={current_style.color}")
                self.settings_manager.update_tool_style(
                    tool_name,
                    line_width=current_style.line_width,
                    color=current_style.color,
                    opacity=current_style.opacity,
                    font_size=current_style.font_size
                )
            
            # NO cache clear here! The cache is already updated by update_tool_style
            print("💾 [SETTINGS UI] All settings saved successfully!")
            
            self.status_label.setText("✓ Settings saved successfully!")
            self.status_label.setStyleSheet("color: #48bb78; padding: 5px 10px; font-weight: bold;")
            
            # Show success message
            QMessageBox.information(
                self,
                "Settings Saved",
                "Tool settings have been saved successfully!\n\n"
                "Note: New tools created after saving will use the new settings.\n"
                "Existing tools will keep their current appearance."
            )
            
        except Exception as e:
            self.status_label.setText(f"✗ Error saving settings: {str(e)}")
            self.status_label.setStyleSheet("color: #60a5fa; padding: 5px 10px; font-weight: bold;")
            
            print(f"❌ [SETTINGS ERROR] Failed to save: {e}")
            import traceback
            traceback.print_exc()
            
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save settings:\n{str(e)}"
            )
    
    def reset_to_defaults(self):
        """Reset all settings to defaults"""
        reply = QMessageBox.question(
            self,
            "Reset to Defaults",
            "Are you sure you want to reset all tool settings to their default values?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # Reset in database
                self.settings_manager.reset_to_defaults()
                
                # Reload UI with default values
                settings = self.settings_manager.get_settings()
                
                # Update each panel
                for tool_name, panel in self.tool_panels.items():
                    style = getattr(settings, tool_name)
                    panel.line_width_spin.setValue(style.line_width)
                    panel.color_button.set_color(style.color)
                    panel.opacity_slider.setValue(int(style.opacity * 100))
                    panel.font_size_spin.setValue(style.font_size)
                
                self.status_label.setText("✓ Settings reset to defaults!")
                self.status_label.setStyleSheet("color: #48bb78; padding: 5px 10px; font-weight: bold;")
                
                QMessageBox.information(
                    self,
                    "Reset Complete",
                    "All settings have been reset to their default values."
                )
                
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to reset settings:\n{str(e)}"
                )

