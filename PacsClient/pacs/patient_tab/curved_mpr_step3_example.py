"""
Curved MPR Module - Step 3 Example: Centerline Polyline

This example demonstrates the new centerline polyline feature added in Step 3.

Key Improvement:
----------------
Instead of creating N-1 individual line actors for N points,
we now create a single polyline that updates efficiently.
"""

import vtk
from PacsClient.pacs.patient_tab.curved_mpr_module import CurvedMPRModule


def example_basic_centerline():
    """Basic example of centerline polyline creation"""
    
    # Create module
    module = CurvedMPRModule()
    
    # Create a dummy volume (for demonstration)
    image_data = vtk.vtkImageData()
    image_data.SetDimensions(100, 100, 100)
    image_data.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    
    # Start the module
    module.start_curved_mpr(image_data)
    
    # Add some points
    print("=== Adding Points ===")
    points = [
        (10.0, 20.0, 30.0),
        (20.0, 25.0, 35.0),
        (30.0, 30.0, 40.0),
        (40.0, 28.0, 42.0),
    ]
    
    for i, pt in enumerate(points, 1):
        module.add_point_world(pt)
        print(f"Point {i} added: {pt}")
        
        # Get centerline polydata
        polydata = module.get_centerline_polydata()
        if polydata:
            print(f"  → Centerline now has {polydata.GetNumberOfPoints()} points")
            print(f"  → Centerline has {polydata.GetNumberOfLines()} polyline")
        else:
            print(f"  → Not enough points for centerline yet (need ≥2)")
        print()
    
    # Get final polydata
    final_polydata = module.get_centerline_polydata()
    print(f"\n=== Final Centerline ===")
    print(f"Total points: {final_polydata.GetNumberOfPoints()}")
    print(f"Total cells: {final_polydata.GetNumberOfCells()}")
    
    return module


def example_with_viewer_integration():
    """
    Example showing how the viewer uses the centerline.
    
    This mimics what happens in viewer_2d.py
    """
    
    print("\n=== Viewer Integration Example ===\n")
    
    # Simulated viewer code
    class SimulatedViewer:
        def __init__(self):
            self.curved_mpr_module = CurvedMPRModule()
            self.curved_mpr_centerline_actor = None
            self.renderer = vtk.vtkRenderer()
        
        def enable_curved_mpr_mode(self, volume):
            """Start curved MPR mode"""
            self.curved_mpr_module.start_curved_mpr(volume)
            print("[Viewer] Curved MPR mode enabled")
        
        def on_user_click(self, world_point):
            """Called when user clicks on the viewer"""
            # Add point to module
            self.curved_mpr_module.add_point_world(world_point)
            print(f"[Viewer] User clicked at {world_point}")
            
            # Update centerline visualization
            self._update_centerline()
        
        def _update_centerline(self):
            """Update the centerline actor (Step 3 feature)"""
            
            # Remove old actor if exists
            if self.curved_mpr_centerline_actor is not None:
                self.renderer.RemoveActor(self.curved_mpr_centerline_actor)
                print("[Viewer]   Removed old centerline actor")
            
            # Get polydata from module
            polydata = self.curved_mpr_module.get_centerline_polydata()
            
            if polydata is None:
                print("[Viewer]   No centerline (need ≥2 points)")
                return
            
            # Create new actor
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(polydata)
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(1.0, 0.9, 0.0)  # Yellow
            actor.GetProperty().SetLineWidth(3.0)
            
            self.renderer.AddActor(actor)
            self.curved_mpr_centerline_actor = actor
            
            point_count = self.curved_mpr_module.get_point_count()
            print(f"[Viewer]   Centerline updated with {point_count} points ✓")
    
    # Create dummy volume
    volume = vtk.vtkImageData()
    volume.SetDimensions(100, 100, 100)
    volume.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    
    # Create viewer
    viewer = SimulatedViewer()
    viewer.enable_curved_mpr_mode(volume)
    
    # Simulate user clicks
    print()
    viewer.on_user_click((10.0, 20.0, 30.0))
    print()
    viewer.on_user_click((20.0, 25.0, 35.0))
    print()
    viewer.on_user_click((30.0, 30.0, 40.0))
    print()
    
    print(f"\n[Viewer] Final state: {viewer.curved_mpr_module.get_point_count()} points picked")


def example_performance_comparison():
    """
    Demonstrate performance improvement of Step 3.
    
    OLD WAY (Steps 1-2):
        For N points → N-1 individual line actors
        
    NEW WAY (Step 3):
        For N points → 1 polyline actor
    """
    
    print("\n=== Performance Comparison ===\n")
    
    N = 10  # Number of points
    
    print(f"Scenario: User picks {N} points\n")
    
    print("OLD WAY (Steps 1-2):")
    print(f"  • Creates {N-1} individual line actors")
    print(f"  • Each actor = separate mapper + properties")
    print(f"  • Memory: ~{N-1} objects in renderer")
    print(f"  • Render time: O(N) actor draws")
    
    print("\nNEW WAY (Step 3):")
    print(f"  • Creates 1 polyline actor")
    print(f"  • Single mapper + properties")
    print(f"  • Memory: ~1 object in renderer")
    print(f"  • Render time: O(1) actor draw")
    
    print(f"\nImprovement: {N-1}× fewer actors! 🚀")


def example_undo_functionality():
    """Demonstrate that undo updates the centerline"""
    
    print("\n=== Undo Functionality Example ===\n")
    
    module = CurvedMPRModule()
    
    # Dummy volume
    volume = vtk.vtkImageData()
    volume.SetDimensions(100, 100, 100)
    volume.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    module.start_curved_mpr(volume)
    
    # Add points
    points = [(10, 20, 30), (20, 25, 35), (30, 30, 40), (40, 35, 45)]
    for pt in points:
        module.add_point_world(pt)
    
    print(f"Added {module.get_point_count()} points")
    polydata = module.get_centerline_polydata()
    print(f"Centerline has {polydata.GetNumberOfPoints()} points\n")
    
    # Undo last point
    print("Undoing last point...")
    module.remove_last_point()
    
    polydata = module.get_centerline_polydata()
    print(f"After undo: {module.get_point_count()} points")
    print(f"Centerline has {polydata.GetNumberOfPoints()} points")
    print("→ Centerline automatically updated! ✓")


if __name__ == "__main__":
    print("=" * 60)
    print("Curved MPR Module - Step 3 Examples")
    print("=" * 60)
    
    # Run examples
    example_basic_centerline()
    example_with_viewer_integration()
    example_performance_comparison()
    example_undo_functionality()
    
    print("\n" + "=" * 60)
    print("All examples completed successfully! ✓")
    print("=" * 60)

