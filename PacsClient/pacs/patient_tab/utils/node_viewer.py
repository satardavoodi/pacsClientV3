class NodeViewer:
    def __init__(self, main_widget, vtk_widget, slider):
        self.widget = main_widget
        self.vtk_widget = vtk_widget
        self.slider = slider

    def change_main_widget(self, widget):
        self.widget = widget
    
    def switch_series(self, vtk_image_data, metadata, series_index, vtk_widget_data_2=None, metadata_2=None, metadata_fixed=None):
        """Switch series in the viewer"""
        try:
            # Check if vtk_widget is None (placeholder viewer)
            if self.vtk_widget is None:
                print("⚠️ vtk_widget is None (placeholder viewer), cannot switch series")
                return False
            
            # Debug info
            print(f"🔍 NodeViewer.switch_series called for series_index: {series_index}")
            print(f"🔍 vtk_widget type: {type(self.vtk_widget)}")
            print(f"🔍 vtk_widget has switch_series: {hasattr(self.vtk_widget, 'switch_series')}")
                
            # Delegate to the vtk_widget if it has the method
            if hasattr(self.vtk_widget, 'switch_series'):
                result = self.vtk_widget.switch_series(vtk_image_data, metadata, series_index, vtk_widget_data_2, metadata_2, metadata_fixed)
                print(f"🔍 vtk_widget.switch_series returned: {result}")
                return result
            else:
                print("⚠️ vtk_widget does not have switch_series method")
                return False
        except Exception as e:
            print(f"❌ Error in NodeViewer.switch_series: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def grow_current_series_inplace(self, vtk_image_data, metadata):
        """Grow current series in place"""
        try:
            # Check if vtk_widget is None (placeholder viewer)
            if self.vtk_widget is None:
                print("⚠️ vtk_widget is None (placeholder viewer), cannot grow series")
                return False
                
            # Delegate to the vtk_widget if it has the method
            if hasattr(self.vtk_widget, 'grow_current_series_inplace'):
                return self.vtk_widget.grow_current_series_inplace(vtk_image_data, metadata)
            else:
                print("⚠️ vtk_widget does not have grow_current_series_inplace method")
                return False
        except Exception as e:
            print(f"❌ Error in NodeViewer.grow_current_series_inplace: {e}")
            return False