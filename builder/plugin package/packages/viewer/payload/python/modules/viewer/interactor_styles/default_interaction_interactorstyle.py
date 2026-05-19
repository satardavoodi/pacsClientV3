from .abstract_interactorstyle import AbstractInteractorStyle
import vtkmodules.all as vtk
from PacsClient.pacs.patient_tab.utils import create_attachment_folder, create_random_string


class DefaultInteractionInteractorStyle(AbstractInteractorStyle):
    """
        Methods available: Zoom to fit, Zoom, Window Level, Stacked, Pan
    """
    def __init__(self, image_viewer):
        super().__init__(image_viewer)
        self.image_viewer = image_viewer
        self.interaction_tool = None
        self.capture_mode = 'active'  # 'active', 'all', 'region'

    def zoom_to_fit(self):
        self.image_viewer.zoom_to_fit()

    def on_left_button_press(self, obj, event):
        mouse_pos = self.GetInteractor().GetEventPosition()
        # Check for annotation drag first (body or endpoint hit)
        drag_result = self._find_any_drag_target(mouse_pos)
        if drag_result is not None:
            drag_obj, drag_type, start_data = drag_result
            self._dragging_obj = drag_obj
            self._drag_type = drag_type
            self._drag_start_data = start_data
            self._drag_start_world = self.display_to_world(mouse_pos[0], mouse_pos[1])
            self._set_cursor(vtk.VTK_CURSOR_HAND)
            return
        self.left_button_down = True
        self.last_pos = mouse_pos
        # self.emit_interaction()  # send signal for interaction

    def on_left_button_release(self, obj, event):
        if self._dragging_obj is not None:
            # Delegate to abstract base which handles TWO_LINE_ANGLE persistence + cleanup
            super().on_left_button_release(obj, event)
            return
        self.left_button_down = False
        self.last_pos = None

    def on_mouse_move(self, obj, event):
        # ── Active annotation drag ──
        if self._dragging_obj is not None and self._drag_start_data is not None:
            current_pos = self.GetInteractor().GetEventPosition()
            current_world = self.display_to_world(current_pos[0], current_pos[1])
            if current_world is not None and self._drag_start_world is not None:
                dx = current_world[0] - self._drag_start_world[0]
                dy = current_world[1] - self._drag_start_world[1]
                dz = current_world[2] - self._drag_start_world[2]
                self._apply_drag_delta(dx, dy, dz)
            return
        # ── Hover cursor for annotations ──
        mouse_pos = self.GetInteractor().GetEventPosition()
        hover_result = self._find_any_drag_target(mouse_pos)
        if hover_result is not None:
            if self._hover_obj != hover_result[0]:
                self._hover_obj = hover_result[0]
                self._set_cursor(vtk.VTK_CURSOR_HAND)
        else:
            if self._hover_obj is not None:
                self._hover_obj = None
                self._set_cursor(vtk.VTK_CURSOR_ARROW)
        # ── Normal tool interaction ──
        if self.left_button_down and self.interaction_tool is not None:
            try:
                self.interaction_tool()
            except TypeError:
                pass

    def activate(self, tool):
        if tool == self.tool_access.ZOOM:
            self.interaction_tool = self.change_zoom

        elif tool == self.tool_access.WINDOW_LEVEL:
            self.image_viewer.flag_set_custom_window_level = True  # default window width/center are inactive.
            self.interaction_tool = self.change_window_level

        elif tool == self.tool_access.PAN:
            self.turn_on_pan()
            self.interaction_tool = super().OnMouseMove

        elif tool == self.tool_access.STACKED:
            self.interaction_tool = self.change_quickly_slices

        elif tool == self.tool_access.CAPTURE:
            # برای جلوگیری از خطا، یک تابع خالی تنظیم می‌کنیم
            self.interaction_tool = lambda: None
            # گرفتن اسکرین‌شات بلافاصله
            self.capture()

    def deactivate(self, tool):
        if tool == self.tool_access.PAN:
            self.turn_off_pan()
        self.interaction_tool = None

    def capture(self):
        """گرفتن اسکرین‌شات از ویجت فعال"""
        try:
            # مرحله ۲: خروجی رندر را به تصویر تبدیل کن
            window_to_image = vtk.vtkWindowToImageFilter()
            window_to_image.SetInput(self.image_viewer.image_render_window)
            window_to_image.Update()

            # folder path
            if hasattr(self.image_viewer, 'metadata_fixed') and self.image_viewer.metadata_fixed:
                study_uid = self.image_viewer.metadata_fixed.get('study_uid')
            else:
                import random
                study_uid = str(random.randint(10000, 100000))

            folder_path = create_attachment_folder(study_uid)
            random_name = create_random_string()
            file_path = f'{folder_path}/{random_name}.png'

            writer = vtk.vtkPNGWriter()
            writer.SetFileName(file_path)
            writer.SetInputConnection(window_to_image.GetOutputPort())
            writer.Write()
            
            print(f"✅ Screenshot saved: {file_path}")
            
        except Exception as e:
            print(f"[ERROR] Failed to capture screenshot: {e}")