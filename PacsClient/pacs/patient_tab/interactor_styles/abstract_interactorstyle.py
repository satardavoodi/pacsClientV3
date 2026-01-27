import vtkmodules.all as vtk
from vtkmodules.all import vtkInteractorStyleImage
from PySide6.QtCore import QObject, Signal
from .tools_object_manager import ToolAccess
from PacsClient.pacs.patient_tab.viewers.viewer_2d import ImageViewer2D
from .tools_object_manager import ToolObjectAbstract

class InteractionSignal(QObject):
    interactionOccurred = Signal()


class AbstractInteractorStyle(vtkInteractorStyleImage):

    def __init__(self, image_viewer: ImageViewer2D):
        super(AbstractInteractorStyle, self).__init__()
        self.image_viewer: ImageViewer2D = image_viewer
        self.signal_emitter: InteractionSignal = InteractionSignal()  # signal for interaction

        # left click
        self.AddObserver("LeftButtonPressEvent", self.on_left_button_press)
        self.AddObserver("LeftButtonReleaseEvent", self.on_left_button_release)

        # right click
        self.AddObserver("RightButtonPressEvent", self.on_right_button_press)
        self.AddObserver("RightButtonReleaseEvent", self.on_right_button_release)

        # middle mouse click
        self.AddObserver("MiddleButtonPressEvent", self.on_middle_button_press)
        self.AddObserver("MiddleButtonReleaseEvent", self.on_middle_button_release)

        # moving mouse
        self.AddObserver("MouseMoveEvent", self.on_mouse_move)

        self.left_button_down = False
        self.right_button_down = False
        self.middle_button_down = False
        self.pan_active = False
        self.last_pos = None
        self.tool_access = ToolAccess()
        self.color = (1, 0, 1)
        self.interactor_name = self.tool_access.ABSTRACT
        
        # Use shared widgets storage from image_viewer if available (for Curved MPR)
        # Otherwise create local storage (for regular viewers)
        if hasattr(image_viewer, 'widgets_by_slice'):
            # Curved MPR: use shared storage that persists across style changes
            self.widgets_by_slice = image_viewer.widgets_by_slice
        else:
            # Regular viewer: use local storage
            self.widgets_by_slice = {}


    def reset_events(self):
        self.left_button_down = False
        self.right_button_down = False
        self.middle_button_down = False
        self.pan_active = False
        self.last_pos = None

    def update_slice(self):
        """
        Update the visibility of measurements when the slice changes.
        """
        current_slice = self.image_viewer.GetSlice()
        total_widgets = sum(len(w) for w in self.widgets_by_slice.values())
        
        if total_widgets > 0:
            # Only log if there are widgets to manage
            visible_count = len(self.widgets_by_slice.get(current_slice, set()))
            hidden_count = total_widgets - visible_count
            print(f"[WIDGET VISIBILITY] Slice {current_slice}: Showing {visible_count}, Hiding {hidden_count}")

        # Show/hide widgets based on slice
        for slice, widgets in self.widgets_by_slice.items():
            if slice == current_slice:
                for widget in widgets:
                    widget.On()
            else:
                for widget in widgets:
                    widget.Off()

        # Render to update the display
        self.image_viewer.renderer.ResetCameraClippingRange()
        self.image_viewer.renderer.Render()

    def delete_widget(self, obj: ToolObjectAbstract, selected_slice: int):
        if obj:
            obj.delete_widget(self.image_viewer)
            self.widgets_by_slice[selected_slice].remove(obj)
            self.image_viewer.Render()
            del obj

    def delete_all_widgets(self):
        for slice in self.widgets_by_slice.keys():
            while True:
                try:
                    widget = next(iter(self.widgets_by_slice[slice]))
                    self.delete_widget(widget, slice)

                except Exception as e:
                    break  # all widgets on slice deleted and don't have any widget on slice
        self.image_viewer.update_corners_actors(update_just_zoom=True)

    def emit_interaction(self):
        self.signal_emitter.interactionOccurred.emit()

    def on_left_button_press(self, obj, event):
        self.left_button_down = True
        self.last_pos = self.GetInteractor().GetEventPosition()
        self.check_left_right_pan_start()
        self.emit_interaction()  # send signal for interaction

    def on_left_button_release(self, obj, event):
        self.left_button_down = False
        self.last_pos = None
        self.check_left_right_pan_end()
        # self.emit_interaction()  # send signal for interaction

    ###################################################################

    def on_right_button_press(self, obj, event):
        self.image_viewer.flag_set_custom_window_level = True  # default window width/center are inactive.

        self.right_button_down = True
        self.last_pos = self.GetInteractor().GetEventPosition()
        self.check_left_right_pan_start()
        self.emit_interaction()  # send signal for interaction

    def on_right_button_release(self, obj, event):
        self.right_button_down = False
        self.last_pos = None
        self.check_left_right_pan_end()
        # self.emit_interaction()  # send signal for interaction

    ###################################################################
    def on_middle_button_press(self, obj, event):
        self.middle_button_down = True
        self.last_pos = self.GetInteractor().GetEventPosition()
        self.emit_interaction()  # send signal for interaction

    def on_middle_button_release(self, obj, event):
        self.middle_button_down = False
        self.last_pos = None
        # self.emit_interaction()  # send signal for interaction

    ####################################################################
    def on_mouse_move(self, obj, event):
        if self.pan_active:  # if left and right click pressed
            super().OnMouseMove()
            # self.emit_interaction()  # send signal for interaction
            return True

        elif self.left_button_down:
            try:
                self.change_quickly_slices()
                # self.emit_interaction()  # send signal for interaction
                return True
            except:
                return False


        elif self.right_button_down:  # if right-click hold: change window level
            self.change_window_level()
            # self.emit_interaction()  # send signal for interaction
            return True

        elif self.middle_button_down:  # if middle button hold: zoom in/out
            self.change_zoom()
            # self.emit_interaction()  # send signal for interaction
            return True

        # no option chosen
        return False

    def check_left_right_pan_start(self):
        if self.left_button_down and self.right_button_down:
            # start pan
            self.turn_on_pan()

    def turn_on_pan(self):
        self.pan_active = True
        super().OnMiddleButtonDown()

    def check_left_right_pan_end(self):
        # release pan
        if self.pan_active:
            self.left_button_down = False
            self.right_button_down = False
            self.turn_off_pan()

    def turn_off_pan(self):
        self.pan_active = False
        super().OnMiddleButtonUp()

    def change_quickly_slices(self):
        current_pos = self.GetInteractor().GetEventPosition()
        dy = current_pos[1] - self.last_pos[1]

        max_slice = self.image_viewer.get_count_of_slices()
        if max_slice <= 25:
            basic_slice_change = 10
        elif 25 < max_slice <= 50:
            basic_slice_change = 8
        elif 50 < max_slice <= 75:
            basic_slice_change = 7
        else:
            basic_slice_change = 5  # each 5 pixel on window

        if abs(dy) >= basic_slice_change:  # Slice change criteria
            # step = 1 if dy > 0 else -1 if dy < 0 else 0  # determine increase/decrease slice
            step = round(dy / basic_slice_change)  # determine increase/decrease slice

            next_slice = self.image_viewer.GetSlice() + self.image_viewer.skip_slices - step

            if 0 <= next_slice < max_slice:  # if slice valid
                self.slider.setValue(next_slice)

            self.image_viewer.Render()
            self.last_pos = current_pos

    def change_window_level(self):
        current_pos = self.GetInteractor().GetEventPosition()
        dx = current_pos[0] - self.last_pos[0]
        dy = current_pos[1] - self.last_pos[1]

        window, level = self.image_viewer.get_window_level()
        # print('current_pos:', current_pos, 'dy:', dy, 'dx:', dx)

        # Check if modality is MG (Mammography) for increased sensitivity
        modality = 'UNKNOWN'
        try:
            if hasattr(self.image_viewer, 'metadata') and self.image_viewer.metadata:
                modality = self.image_viewer.metadata.get('series', {}).get('modality', 'UNKNOWN')
        except:
            pass
        
        # MG images need 10x sensitivity due to their large dynamic range
        sensitivity_multiplier = 10.0 if modality == 'MG' else 1.0

        # invert dy for invert change window width
        # if you down your mouse, window width increases
        dy = -dy
        new_y = dy * 1.3 * sensitivity_multiplier
        new_window_center = level + new_y  # level

        # 1.5 is correlation
        new_x = dx * 1.5 * sensitivity_multiplier
        new_window_width = window + new_x

        self.image_viewer.set_window_level(new_window_width, new_window_center)
        self.image_viewer.Render()

        self.last_pos = current_pos

    def change_zoom(self):
        current_pos = self.GetInteractor().GetEventPosition()
        dy = current_pos[1] - self.last_pos[1]

        camera = self.image_viewer.GetRenderer().GetActiveCamera()
        zoom_factor = 1.0
        zoom_sensitivity = 0.005  # sensitive zoom

        if dy > 0:  # mouse moves up -> zoom in
            zoom_factor = 1 + abs(dy) * zoom_sensitivity
        elif dy < 0:  # mouse moves down -> zoom out
            zoom_factor = 1 / (1 + abs(dy) * zoom_sensitivity)

        camera.Zoom(zoom_factor)
        self.image_viewer.update_corners_actors(update_just_zoom=True)
        self.image_viewer.Render()

        self.last_pos = current_pos

    def set_slider_from_ui(self, slider):
        self.slider = slider

    def world_to_display(self, world_point):
        try:
            renderer = self.image_viewer.GetRenderer()
            coordinate = vtk.vtkCoordinate()
            coordinate.SetCoordinateSystemToWorld()
            coordinate.SetValue(world_point)
            display_point = coordinate.GetComputedDisplayValue(renderer)
            return display_point[0], display_point[1]
        except Exception as e:
            print(f"Error in world_to_display: {e}")
            return None

    def display_to_world(self, x, y):
        # z_phys = self.image_viewer.GetSlice() * self.image_viewer.get_count_of_slices()
        z_phys = self.image_viewer.get_count_of_slices()
        c = vtk.vtkCoordinate()
        c.SetCoordinateSystemToDisplay()
        c.SetValue(x, y, 0)
        w = c.GetComputedWorldValue(self.image_viewer.renderer)
        # return w[0], w[1], z_phys
        return w[0], w[1], w[2]

    def add_object_to_store_widgets(self, obj, obj_name):
        current_slice = self.image_viewer.GetSlice()
        
        if current_slice not in self.widgets_by_slice:
            self.widgets_by_slice[current_slice] = set()

        self.widgets_by_slice[current_slice].add(obj)
        total_widgets = sum(len(w) for w in self.widgets_by_slice.values())
        print(f"[ADD WIDGET] {obj_name} added to slice {current_slice} (Total: {total_widgets} widgets)")
        setattr(obj, obj_name, current_slice)
    
    def activate(self, tool=None):
        """
        Base activate method for toolbar compatibility.
        Subclasses can override this for specific activation behavior.
        
        Args:
            tool: Optional tool identifier
        """
        pass
    
    def deactivate(self, tool=None):
        """
        Base deactivate method for toolbar compatibility.
        Subclasses can override this for specific deactivation behavior.
        
        Args:
            tool: Optional tool identifier
        """
        pass