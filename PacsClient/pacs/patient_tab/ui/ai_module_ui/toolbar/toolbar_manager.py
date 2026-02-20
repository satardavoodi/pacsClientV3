from PacsClient.pacs.patient_tab.interactor_styles import PolygonSegmentationInteractorStyle, RectangleSegmentationInteractorStyle
from PacsClient.pacs.patient_tab.interactor_styles import ToolAccess
from PacsClient.pacs.patient_tab.interactor_styles.ai_chat_interactorstyle import AIChatInteractorStyle


class ToolBarManager:
    def __init__(self, patient_widget):
        self.patient_widget = patient_widget
        self.tool_selected = None
        self.tool_access = ToolAccess()

    def activate_tool(self, selected_widget, tool_name):
        if tool_name == self.tool_access.POLYGON_SEGMENTATION:
            print('segment clicked.')
            self.toggle_polygon_segment(selected_widget)
        elif tool_name == self.tool_access.AI_CHAT:
            print('AI chat clicked.')
            self.toggle_ai_chat(selected_widget)

        elif tool_name == self.tool_access.RECTANGLE_SEGMENTATION:
            print('rectangle clicked.')
            self.toggle_rectangle_segment(selected_widget)

    def toggle_polygon_segment(self, selected_widget):
        if selected_widget is None:
            return
        if self.tool_selected is None:
            selected_widget.set_new_interactorstyle(PolygonSegmentationInteractorStyle)
            if getattr(selected_widget, 'current_style', None) is not None:
                selected_widget.current_style.On()
            self.tool_selected = self.tool_access.POLYGON_SEGMENTATION

        else:
            if getattr(selected_widget, 'current_style', None) is not None:
                selected_widget.current_style.Off()
            if hasattr(selected_widget, 'restore_default_interactorstyle'):
                selected_widget.restore_default_interactorstyle()
            self.tool_selected = None

    def toggle_rectangle_segment(self, selected_widget):
        if selected_widget is None:
            return
        if self.tool_selected is None:
            selected_widget.set_new_interactorstyle(RectangleSegmentationInteractorStyle)
            if getattr(selected_widget, 'current_style', None) is not None:
                selected_widget.current_style.On()
            self.tool_selected = self.tool_access.RECTANGLE_SEGMENTATION

    def toggle_ai_chat(self, selected_widget):
        if selected_widget is None:
            return
        if self.tool_selected is None:
            selected_widget.set_new_interactorstyle(AIChatInteractorStyle)
            if getattr(selected_widget, 'current_style', None) is not None:
                selected_widget.current_style.On()
            self.tool_selected = self.tool_access.AI_CHAT

        else:
            if getattr(selected_widget, 'current_style', None) is not None:
                selected_widget.current_style.Off()
            if hasattr(selected_widget, 'restore_default_interactorstyle'):
                selected_widget.restore_default_interactorstyle()
            self.tool_selected = None

    def get_tool_activated_method(self):
        if self.tool_selected is None: return None

        elif self.tool_selected == self.tool_access.POLYGON_SEGMENTATION:
            return self.toggle_polygon_segment
        elif self.tool_selected == self.tool_access.RECTANGLE_SEGMENTATION:
            return self.toggle_rectangle_segment
        elif self.tool_selected == self.tool_access.AI_CHAT:
            return self.toggle_ai_chat
        return None

    def check_and_deactivate_tools(self):
        if self.tool_selected is None:  # it's mean we haven't selected tool before
            return
        if self.patient_widget.selected_widget is None:
            return
        elif self.tool_selected is self.tool_access.POLYGON_SEGMENTATION:
            self.toggle_polygon_segment(self.patient_widget.selected_widget)
        elif self.tool_selected is self.tool_access.RECTANGLE_SEGMENTATION:
            self.toggle_rectangle_segment(self.patient_widget.selected_widget)
        elif self.tool_selected is self.tool_access.AI_CHAT:
            self.toggle_ai_chat(self.patient_widget.selected_widget)
        return

    def turn_off_all_tools(self):
        self.check_and_deactivate_tools()
        # self.handle_buttons_checked()
