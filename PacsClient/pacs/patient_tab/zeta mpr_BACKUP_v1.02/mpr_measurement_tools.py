"""
MPR Measurement Tools - VTK Widget-based measurements for MPR viewports
Uses VTK's built-in widgets that work independently of interactor styles
"""
import logging
import vtk

logger = logging.getLogger(__name__)


class MPRMeasurementTools:
    """
    Measurement tools for MPR viewports using VTK widgets.
    These tools work independently of interactor styles and can be used
    even when Crosshairs are active.
    """
    
    def __init__(self, mpr_viewer):
        """
        Initialize MPR measurement tools
        Args:
            mpr_viewer: StandardMPRViewer instance
        """
        self.mpr_viewer = mpr_viewer
        self.active_tools = {}  # {view_name: {'ruler': [widgets], 'angle': [widgets], ...}}
        self.current_tool = None  # 'ruler', 'angle', 'arrow', None
        self.tool_color = (1.0, 1.0, 0.0)  # Yellow
        
        # Initialize tool storage for each view
        for view_name in ['axial', 'sagittal', 'coronal']:
            self.active_tools[view_name] = {
                'ruler': [],
                'angle': [],
                'caption': []
            }
        
        logger.info("MPR Measurement Tools initialized")
    
    def activate_ruler_tool(self, view_name='axial'):
        """
        Activate ruler (distance) measurement tool on specified view
        Args:
            view_name: 'axial', 'sagittal', 'coronal', or 'all' to activate on all 2D views
        """
        # If 'all' is specified, activate on all 2D views
        if view_name == 'all':
            success_count = 0
            for vn in ['axial', 'sagittal', 'coronal']:
                if self._activate_ruler_on_view(vn):
                    success_count += 1
            logger.info(f"✓ Ruler tool activated on {success_count}/3 views")
            return success_count > 0
        else:
            return self._activate_ruler_on_view(view_name)
    
    def _activate_ruler_on_view(self, view_name):
        """Internal method to activate ruler on a single view"""
        if view_name not in self.mpr_viewer.viewers:
            logger.warning(f"View {view_name} not found")
            return False
        
        self.current_tool = 'ruler'
        
        # Get the interactor for this view
        print('self.mpr_viewer.viewers[view_name]:', self.mpr_viewer.viewers[view_name], '\n')
        print("self.mpr_viewer.viewers[view_name]['widget']:", self.mpr_viewer.viewers[view_name]['widget'])
        interactor = self.mpr_viewer.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()
        renderer = self.mpr_viewer.viewers[view_name]['renderer']
        
        # IMPORTANT: Create distance widget representation FIRST
        distance_rep = vtk.vtkDistanceRepresentation2D()
        distance_rep.GetAxis().GetProperty().SetColor(self.tool_color)
        distance_rep.GetAxis().GetProperty().SetLineWidth(2)
        
        # Create distance widget
        distance_widget = vtk.vtkDistanceWidget()
        distance_widget.SetInteractor(interactor)
        distance_widget.SetRepresentation(distance_rep)
        
        # CRITICAL: Create default representation BEFORE enabling
        distance_widget.CreateDefaultRepresentation()
        
        # Enable the widget - this makes it interactive
        distance_widget.On()
        
        # Enable ProcessEvents to make it actually work
        distance_widget.SetProcessEvents(1)
        
        # Store the widget
        self.active_tools[view_name]['ruler'].append(distance_widget)
        
        logger.info(f"✓ Ruler widget created and enabled on {view_name}")
        return True
    
    def activate_angle_tool(self, view_name='axial'):
        """
        Activate angle measurement tool on specified view
        Args:
            view_name: 'axial', 'sagittal', 'coronal', or 'all' to activate on all 2D views
        """
        # If 'all' is specified, activate on all 2D views
        if view_name == 'all':
            success_count = 0
            for vn in ['axial', 'sagittal', 'coronal']:
                if self._activate_angle_on_view(vn):
                    success_count += 1
            logger.info(f"✓ Angle tool activated on {success_count}/3 views")
            return success_count > 0
        else:
            return self._activate_angle_on_view(view_name)
    
    def _activate_angle_on_view(self, view_name):
        """Internal method to activate angle on a single view"""
        if view_name not in self.mpr_viewer.viewers:
            logger.warning(f"View {view_name} not found")
            return False
        
        self.current_tool = 'angle'
        
        # Get the interactor for this view
        interactor = self.mpr_viewer.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()
        renderer = self.mpr_viewer.viewers[view_name]['renderer']
        
        # IMPORTANT: Create angle widget representation FIRST
        angle_rep = vtk.vtkAngleRepresentation2D()
        angle_rep.GetRay1().GetProperty().SetColor(self.tool_color)
        angle_rep.GetRay2().GetProperty().SetColor(self.tool_color)
        angle_rep.GetRay1().GetProperty().SetLineWidth(2)
        angle_rep.GetRay2().GetProperty().SetLineWidth(2)
        
        # Create angle widget
        angle_widget = vtk.vtkAngleWidget()
        angle_widget.SetInteractor(interactor)
        angle_widget.SetRepresentation(angle_rep)
        
        # CRITICAL: Create default representation BEFORE enabling
        angle_widget.CreateDefaultRepresentation()
        
        # Enable the widget - this makes it interactive
        angle_widget.On()
        
        # Enable ProcessEvents to make it actually work
        angle_widget.SetProcessEvents(1)
        
        # Store the widget
        self.active_tools[view_name]['angle'].append(angle_widget)
        
        logger.info(f"✓ Angle widget created and enabled on {view_name}")
        return True
    
    def activate_caption_tool(self, view_name='axial'):
        """
        Activate caption (text/arrow) tool on specified view
        Args:
            view_name: 'axial', 'sagittal', 'coronal', or 'all' to activate on all 2D views
        """
        # If 'all' is specified, activate on all 2D views
        if view_name == 'all':
            success_count = 0
            for vn in ['axial', 'sagittal', 'coronal']:
                if self._activate_caption_on_view(vn):
                    success_count += 1
            logger.info(f"✓ Caption tool activated on {success_count}/3 views")
            return success_count > 0
        else:
            return self._activate_caption_on_view(view_name)
    
    def _activate_caption_on_view(self, view_name):
        """Internal method to activate caption on a single view"""
        if view_name not in self.mpr_viewer.viewers:
            logger.warning(f"View {view_name} not found")
            return False
        
        self.current_tool = 'caption'
        
        # Get the interactor for this view
        interactor = self.mpr_viewer.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()
        renderer = self.mpr_viewer.viewers[view_name]['renderer']
        
        # IMPORTANT: Create caption widget representation FIRST
        caption_rep = vtk.vtkCaptionRepresentation()
        caption_rep.GetCaptionActor2D().GetTextActor().SetTextScaleModeToNone()
        caption_rep.GetCaptionActor2D().GetCaptionTextProperty().SetFontSize(14)
        caption_rep.GetCaptionActor2D().GetCaptionTextProperty().SetColor(self.tool_color)
        caption_rep.GetCaptionActor2D().SetCaption("Text")
        
        # Create caption widget
        caption_widget = vtk.vtkCaptionWidget()
        caption_widget.SetInteractor(interactor)
        caption_widget.SetRepresentation(caption_rep)
        
        # CRITICAL: Create default representation BEFORE enabling
        caption_widget.CreateDefaultRepresentation()
        
        # Enable the widget - this makes it interactive
        caption_widget.On()
        
        # Enable ProcessEvents to make it actually work
        caption_widget.SetProcessEvents(1)
        
        # Store the widget
        self.active_tools[view_name]['caption'].append(caption_widget)
        
        logger.info(f"✓ Caption widget created and enabled on {view_name}")
        return True
    
    def deactivate_tool(self, view_name=None):
        """
        Deactivate current tool
        Args:
            view_name: Specific view or None for all views
        """
        if view_name:
            views = [view_name]
        else:
            views = ['axial', 'sagittal', 'coronal']
        
        for vn in views:
            if vn not in self.active_tools:
                continue
            
            # We don't remove existing measurements, just stop creating new ones
            # User can clear measurements separately
        
        self.current_tool = None
        logger.info("Tool deactivated")
    
    def clear_measurements(self, view_name=None, tool_type=None):
        """
        Clear measurements from views
        Args:
            view_name: Specific view or None for all views
            tool_type: Specific tool or None for all tools
        """
        if view_name:
            views = [view_name]
        else:
            views = ['axial', 'sagittal', 'coronal']
        
        if tool_type:
            tools = [tool_type]
        else:
            tools = ['ruler', 'angle', 'caption']
        
        count = 0
        for vn in views:
            if vn not in self.active_tools:
                continue
            
            for tool in tools:
                if tool not in self.active_tools[vn]:
                    continue
                
                for widget in self.active_tools[vn][tool]:
                    try:
                        widget.Off()
                        count += 1
                    except Exception as e:
                        logger.error(f"Error removing widget: {e}")
                
                self.active_tools[vn][tool].clear()
        
        logger.info(f"✓ Cleared {count} measurements")
        return count
    
    def get_measurement_count(self, view_name=None):
        """
        Get total count of measurements
        Args:
            view_name: Specific view or None for all views
        Returns:
            Total count of measurements
        """
        if view_name:
            views = [view_name]
        else:
            views = ['axial', 'sagittal', 'coronal']
        
        count = 0
        for vn in views:
            if vn not in self.active_tools:
                continue
            
            for tool_type in self.active_tools[vn]:
                count += len(self.active_tools[vn][tool_type])
        
        return count

