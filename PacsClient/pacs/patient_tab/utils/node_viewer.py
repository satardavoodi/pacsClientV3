class NodeViewer:
    def __init__(self, main_widget, vtk_widget, slider, thumb_index=None):
        self.widget = main_widget
        self.vtk_widget = vtk_widget
        self.slider = slider
        self.thumb_index = thumb_index
        self.viewer_id = None
        self.num_slices = 0
        self.current_slice = 0

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
    
    def initialize_pipeline(self, thumb_data):
        """Initialize the viewer pipeline with thumbnail data"""
        try:
            # Check if vtk_widget is None (placeholder viewer)
            if self.vtk_widget is None:
                print("⚠️ vtk_widget is None (placeholder viewer), cannot initialize pipeline")
                return False

            # Extract image data and metadata from thumb_data
            if isinstance(thumb_data, dict):
                vtk_image_data = thumb_data.get('vtk_image_data')
                metadata = thumb_data.get('metadata')
                series_index = thumb_data.get('series_index', 0)
                
                if vtk_image_data is not None and metadata is not None:
                    # Initialize the viewer with the data
                    if hasattr(self.vtk_widget, 'start_process_series'):
                        self.vtk_widget.start_process_series(
                            vtk_image_data, 
                            metadata, 
                            series_index, 
                            self.viewer_id if hasattr(self, 'viewer_id') else 0,
                            metadata.get('metadata_fixed', {})
                        )
                        return True
                    else:
                        print("⚠️ vtk_widget does not have start_process_series method")
                        return False
                else:
                    print("⚠️ Missing vtk_image_data or metadata in thumb_data")
                    return False
            else:
                print("⚠️ thumb_data is not a dictionary")
                return False
                
        except Exception as e:
            print(f"❌ Error in NodeViewer.initialize_pipeline: {e}")
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