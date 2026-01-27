"""
Curved MPR Module - Integration Example

This file demonstrates how to integrate the Curved MPR module with the viewer.

Usage Example:
--------------

# Step 1: Access the viewer (ImageViewer2D instance)
viewer = vtk_widget.image_viewer  # Get the viewer from VTKWidget

# Step 2: Enable Curved MPR mode
viewer.enable_curved_mpr_mode(True)

# This will:
# - Initialize the CurvedMPRModule with the current volume
# - Show "Curved MPR Mode: Click to add points" overlay
# - Enable left-click interception for point picking

# Step 3: User clicks on the viewer
# - Points are automatically added via _on_curved_mpr_click
# - Each click converts display coords → world coords
# - Calls curved_mpr_module.add_point_world(point)
# - Visualizes the point with a sphere and number label

# Step 4: Access the picked points
points = viewer.curved_mpr_module.get_current_points()
print(f"Picked {len(points)} points:")
for i, pt in enumerate(points, 1):
    print(f"  Point {i}: ({pt[0]:.2f}, {pt[1]:.2f}, {pt[2]:.2f})")

# Step 5: Check module state
print(f"Module active: {viewer.curved_mpr_module.is_active()}")
print(f"Point count: {viewer.curved_mpr_module.get_point_count()}")

# Step 6: (Optional) Remove last point (undo)
if viewer.curved_mpr_module.remove_last_point():
    print("Last point removed")

# Step 7: Disable Curved MPR mode when done
viewer.enable_curved_mpr_mode(False)

# This will:
# - Reset the module
# - Hide the overlay text
# - Remove click observer


Integration with Toolbar
-------------------------

# In your toolbar class (e.g., ToolbarManager):

def on_curved_mpr_button_clicked(self):
    '''Handle curved MPR tool button click'''
    viewer = self.vtk_widget.image_viewer
    
    if viewer is None:
        print("No viewer available")
        return
    
    # Toggle mode
    is_active = viewer.curved_mpr_module.is_active()
    viewer.enable_curved_mpr_mode(not is_active)
    
    # Update button appearance
    if not is_active:
        self.curved_mpr_button.setStyleSheet("background-color: green;")
    else:
        self.curved_mpr_button.setStyleSheet("")


Integration with Main Window
-----------------------------

# In PatientWidget or similar:

def activate_curved_mpr_tool(self):
    '''Activate Curved MPR tool on the selected viewer'''
    
    # Get the currently selected VTK widget
    current_viewer = self.selected_widget.image_viewer
    
    if current_viewer is None:
        print("No active viewer")
        return
    
    # Enable the tool
    current_viewer.enable_curved_mpr_mode(True)
    
    print(f"Curved MPR activated. Volume: {current_viewer.curved_mpr_module.get_volume()}")


API Reference
-------------

CurvedMPRModule Methods:
    - start_curved_mpr(volume: vtkImageData) -> None
      Start the tool with a volume
      
    - add_point_world(world_point: Tuple[float, float, float]) -> None
      Add a world-space point
      
    - get_current_points() -> List[Tuple[float, float, float]]
      Get all picked points
      
    - get_volume() -> Optional[vtkImageData]
      Get the loaded volume
      
    - is_active() -> bool
      Check if module is active
      
    - reset() -> None
      Reset and clear all points
      
    - remove_last_point() -> bool
      Remove the last point (undo)
      
    - get_point_count() -> int
      Get number of points

ImageViewer2D Methods (Curved MPR related):
    - enable_curved_mpr_mode(enabled: bool) -> None
      Enable/disable point-picking mode
      
    - curved_mpr_module: CurvedMPRModule
      Access to the module instance

"""

# Example function to integrate into toolbar
def example_toolbar_integration(vtk_widget):
    """
    Example of how to add Curved MPR to a toolbar.
    
    Args:
        vtk_widget: The VTKWidget instance containing the viewer
    """
    from PySide6.QtWidgets import QPushButton
    
    def toggle_curved_mpr():
        viewer = vtk_widget.image_viewer
        if viewer is None:
            print("Viewer not initialized")
            return
        
        # Toggle the mode
        is_currently_active = viewer.curved_mpr_module.is_active()
        viewer.enable_curved_mpr_mode(not is_currently_active)
        
        # Update button text
        if viewer.curved_mpr_module.is_active():
            curved_mpr_btn.setText("Stop Curved MPR")
            curved_mpr_btn.setStyleSheet("background-color: #4CAF50; color: white;")
            print(f"[TOOLBAR] Curved MPR mode started")
        else:
            curved_mpr_btn.setText("Start Curved MPR")
            curved_mpr_btn.setStyleSheet("")
            print(f"[TOOLBAR] Curved MPR mode stopped")
            
            # Print collected points
            points = viewer.curved_mpr_module.get_current_points()
            print(f"[TOOLBAR] Collected {len(points)} points")
    
    # Create button
    curved_mpr_btn = QPushButton("Start Curved MPR")
    curved_mpr_btn.clicked.connect(toggle_curved_mpr)
    
    return curved_mpr_btn


# Example function to demonstrate point access
def example_point_processing(viewer):
    """
    Example of how to process the picked points.
    
    Args:
        viewer: The ImageViewer2D instance
    """
    # Get points from module
    points = viewer.curved_mpr_module.get_current_points()
    
    if len(points) < 2:
        print("Need at least 2 points for curved MPR")
        return
    
    print(f"\n=== Curved MPR Points ({len(points)} total) ===")
    for i, pt in enumerate(points, 1):
        print(f"Point {i}: X={pt[0]:.2f}, Y={pt[1]:.2f}, Z={pt[2]:.2f}")
    
    # Calculate path length (for demonstration)
    import numpy as np
    total_length = 0.0
    for i in range(len(points) - 1):
        p1 = np.array(points[i])
        p2 = np.array(points[i + 1])
        segment_length = np.linalg.norm(p2 - p1)
        total_length += segment_length
        print(f"Segment {i+1} length: {segment_length:.2f} mm")
    
    print(f"Total path length: {total_length:.2f} mm")
    
    # Future steps will compute and display the curved MPR here
    print("\n[NOTE] Step 1 complete - points collected successfully!")
    print("[NOTE] Step 2+ will compute and display the curved reformation")

