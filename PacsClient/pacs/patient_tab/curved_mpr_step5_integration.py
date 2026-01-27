"""
Curved MPR Module - Step 5: UI Integration Examples

This file shows how to integrate the Curved MPR view window with
the main application UI (toolbar, menu, hotkeys).

Examples:
- Adding a toolbar button
- Adding a menu item
- Adding a keyboard shortcut
- Connecting to the viewer
"""

from PySide6.QtWidgets import QPushButton, QAction
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence


# =============================================================================
# Example 1: Toolbar Button Integration
# =============================================================================

def add_curved_mpr_button_to_toolbar(toolbar, vtk_widget):
    """
    Add a "Generate Curved MPR" button to a toolbar.
    
    Args:
        toolbar: QToolBar instance
        vtk_widget: VTKWidget instance containing the viewer
    
    Returns:
        The created button
    """
    
    def on_generate_curved_mpr():
        """Handler for the button click"""
        viewer = vtk_widget.image_viewer
        
        if viewer is None:
            print("No viewer available")
            return
        
        # Check if curved MPR mode is active
        if not viewer.curved_mpr_module.is_active():
            print("⚠️ Curved MPR mode is not active. Please activate it first and pick points.")
            return
        
        # Check point count
        point_count = viewer.curved_mpr_module.get_point_count()
        if point_count < 2:
            print(f"⚠️ Need at least 2 points, but only {point_count} picked")
            return
        
        print(f"🎯 Generating Curved MPR with {point_count} points...")
        
        # Generate and show
        view_window = viewer.generate_and_show_curved_mpr(
            num_samples=200,
            slice_width=100,
            slice_height=100
        )
        
        if view_window:
            print("✓ Curved MPR window opened")
        else:
            print("✗ Failed to generate Curved MPR")
    
    # Create button
    button = QPushButton("Generate Curved MPR")
    button.setToolTip("Generate and view the curved MPR reformation (Ctrl+G)")
    button.clicked.connect(on_generate_curved_mpr)
    
    # Style the button
    button.setStyleSheet("""
        QPushButton {
            background-color: #2196F3;
            color: white;
            padding: 8px 16px;
            border-radius: 4px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #1976D2;
        }
        QPushButton:pressed {
            background-color: #0D47A1;
        }
    """)
    
    # Add to toolbar
    toolbar.addWidget(button)
    
    return button


# =============================================================================
# Example 2: Menu Item Integration
# =============================================================================

def add_curved_mpr_menu_item(menu, vtk_widget):
    """
    Add a "Generate Curved MPR" menu item.
    
    Args:
        menu: QMenu instance (e.g., "Tools" menu)
        vtk_widget: VTKWidget instance
    
    Returns:
        The created QAction
    """
    
    def on_generate_curved_mpr():
        viewer = vtk_widget.image_viewer
        
        if viewer and viewer.curved_mpr_module.is_active():
            viewer.generate_and_show_curved_mpr()
    
    # Create action
    action = QAction("Generate Curved MPR", menu)
    action.setShortcut(QKeySequence("Ctrl+G"))
    action.setStatusTip("Generate curved MPR from picked points")
    action.triggered.connect(on_generate_curved_mpr)
    
    # Add to menu
    menu.addAction(action)
    
    return action


# =============================================================================
# Example 3: Complete Toolbar Manager Integration
# =============================================================================

class CurvedMPRToolbarIntegration:
    """
    Example of complete integration with a toolbar manager.
    
    This shows how to add both mode toggle and generation buttons.
    """
    
    def __init__(self, toolbar, vtk_widget):
        self.toolbar = toolbar
        self.vtk_widget = vtk_widget
        self.curved_mpr_active = False
        
        # Create buttons
        self.toggle_button = None
        self.generate_button = None
        
        self._setup_buttons()
    
    def _setup_buttons(self):
        """Setup toolbar buttons"""
        
        # Toggle mode button
        self.toggle_button = QPushButton("Start Curved MPR")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setToolTip("Enable/disable curved MPR point picking mode")
        self.toggle_button.clicked.connect(self._on_toggle_mode)
        
        # Generate button (initially disabled)
        self.generate_button = QPushButton("Generate Curved MPR")
        self.generate_button.setEnabled(False)
        self.generate_button.setToolTip("Generate and view the curved reformation")
        self.generate_button.clicked.connect(self._on_generate)
        
        # Add to toolbar
        self.toolbar.addWidget(self.toggle_button)
        self.toolbar.addWidget(self.generate_button)
        
        # Style
        self._update_button_styles()
    
    def _on_toggle_mode(self, checked):
        """Toggle curved MPR picking mode"""
        viewer = self.vtk_widget.image_viewer
        
        if viewer is None:
            self.toggle_button.setChecked(False)
            return
        
        # Toggle mode
        viewer.enable_curved_mpr_mode(checked)
        self.curved_mpr_active = checked
        
        # Update button text
        if checked:
            self.toggle_button.setText("Stop Curved MPR")
        else:
            self.toggle_button.setText("Start Curved MPR")
        
        # Update generate button state
        self._update_generate_button()
        
        # Update styles
        self._update_button_styles()
    
    def _on_generate(self):
        """Generate and show curved MPR"""
        viewer = self.vtk_widget.image_viewer
        
        if viewer is None:
            return
        
        # Generate with custom parameters
        view_window = viewer.generate_and_show_curved_mpr(
            num_samples=250,  # Higher quality
            slice_width=120,
            slice_height=120
        )
        
        if view_window:
            print("✓ Curved MPR generated and displayed")
    
    def _update_generate_button(self):
        """Update generate button enabled state"""
        viewer = self.vtk_widget.image_viewer
        
        if viewer and self.curved_mpr_active:
            point_count = viewer.curved_mpr_module.get_point_count()
            self.generate_button.setEnabled(point_count >= 2)
            
            if point_count >= 2:
                self.generate_button.setText(f"Generate CPR ({point_count} points)")
            else:
                self.generate_button.setText(f"Generate CPR (need {2-point_count} more)")
        else:
            self.generate_button.setEnabled(False)
            self.generate_button.setText("Generate Curved MPR")
    
    def _update_button_styles(self):
        """Update button appearance"""
        if self.curved_mpr_active:
            self.toggle_button.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    padding: 8px 16px;
                    font-weight: bold;
                }
            """)
        else:
            self.toggle_button.setStyleSheet("""
                QPushButton {
                    background-color: #757575;
                    color: white;
                    padding: 8px 16px;
                }
            """)
        
        self.generate_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 8px 16px;
            }
            QPushButton:disabled {
                background-color: #424242;
                color: #888;
            }
        """)
    
    def on_point_added(self):
        """Call this when a point is added to update UI"""
        self._update_generate_button()


# =============================================================================
# Example 4: Keyboard Shortcut Handler
# =============================================================================

def setup_curved_mpr_shortcuts(main_window, vtk_widget):
    """
    Setup keyboard shortcuts for curved MPR operations.
    
    Args:
        main_window: QMainWindow instance
        vtk_widget: VTKWidget instance
    
    Shortcuts:
        Ctrl+M: Toggle curved MPR mode
        Ctrl+G: Generate and show curved MPR
        Ctrl+Z: Remove last point (undo)
    """
    from PySide6.QtGui import QShortcut
    
    # Toggle mode: Ctrl+M
    toggle_shortcut = QShortcut(QKeySequence("Ctrl+M"), main_window)
    def toggle_mode():
        viewer = vtk_widget.image_viewer
        if viewer:
            is_active = viewer.curved_mpr_module.is_active()
            viewer.enable_curved_mpr_mode(not is_active)
            print(f"Curved MPR mode: {'ON' if not is_active else 'OFF'}")
    
    toggle_shortcut.activated.connect(toggle_mode)
    
    # Generate: Ctrl+G
    generate_shortcut = QShortcut(QKeySequence("Ctrl+G"), main_window)
    def generate():
        viewer = vtk_widget.image_viewer
        if viewer and viewer.curved_mpr_module.is_active():
            viewer.generate_and_show_curved_mpr()
    
    generate_shortcut.activated.connect(generate)
    
    # Undo: Ctrl+Z (when in curved MPR mode)
    undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), main_window)
    def undo_point():
        viewer = vtk_widget.image_viewer
        if viewer and viewer.curved_mpr_module.is_active():
            if viewer.curved_mpr_module.remove_last_point():
                # Also remove visual
                if viewer.curved_mpr_sphere_actors:
                    # Remove last 2 actors (sphere + label)
                    for _ in range(min(2, len(viewer.curved_mpr_sphere_actors))):
                        actor = viewer.curved_mpr_sphere_actors.pop()
                        viewer.renderer.RemoveActor(actor)
                
                # Update centerline
                viewer._update_curved_mpr_centerline()
                print("✓ Last point removed")
    
    undo_shortcut.activated.connect(undo_point)
    
    print("Curved MPR shortcuts registered:")
    print("  Ctrl+M: Toggle mode")
    print("  Ctrl+G: Generate CPR")
    print("  Ctrl+Z: Undo last point")


# =============================================================================
# Example 5: Complete Integration Template
# =============================================================================

def integrate_curved_mpr_complete(main_window, toolbar, tools_menu, vtk_widget):
    """
    Complete integration template - adds all UI elements.
    
    Call this function during your main window initialization.
    
    Args:
        main_window: QMainWindow instance
        toolbar: QToolBar instance
        tools_menu: QMenu instance (e.g., "Tools" menu)
        vtk_widget: VTKWidget instance
    """
    
    # Add toolbar buttons
    print("Adding curved MPR buttons to toolbar...")
    integration = CurvedMPRToolbarIntegration(toolbar, vtk_widget)
    
    # Add menu item
    print("Adding curved MPR menu item...")
    add_curved_mpr_menu_item(tools_menu, vtk_widget)
    
    # Setup keyboard shortcuts
    print("Setting up curved MPR keyboard shortcuts...")
    setup_curved_mpr_shortcuts(main_window, vtk_widget)
    
    # Connect point addition to UI update
    # (This would require modifying the viewer to emit a signal)
    # For now, toolbar integration handles it internally
    
    print("✓ Curved MPR integration complete!")
    
    return integration


# =============================================================================
# Usage Example
# =============================================================================

"""
# In your main window class (e.g., PatientWidget):

class PatientWidget(QWidget):
    def __init__(self):
        super().__init__()
        
        # ... your existing setup ...
        
        # Add curved MPR integration
        self.curved_mpr_integration = integrate_curved_mpr_complete(
            main_window=self,
            toolbar=self.toolbar,
            tools_menu=self.tools_menu,
            vtk_widget=self.selected_widget  # Your active VTK widget
        )
    
    # Optional: Update UI when points are added
    def on_curved_mpr_point_added(self):
        if hasattr(self, 'curved_mpr_integration'):
            self.curved_mpr_integration.on_point_added()
"""

