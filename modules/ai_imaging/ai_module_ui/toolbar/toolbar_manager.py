from modules.viewer.interactor_styles import (
    PolygonSegmentationInteractorStyle,
    RectangleSegmentationInteractorStyle,
    RulerInteractorStyle,
)
from modules.viewer.interactor_styles import ToolAccess
from modules.viewer.interactor_styles.ai_chat_interactorstyle import AIChatInteractorStyle


class ToolBarManager:
    def __init__(self, patient_widget):
        self.patient_widget = patient_widget
        self.tool_selected = None
        self._active_tool_widget = None
        self.tool_access = ToolAccess()

    def _deactivate_active_tool(self, fallback_widget=None):
        widget = self._active_tool_widget or fallback_widget
        if widget is None:
            return
        try:
            if getattr(widget, 'current_style', None) is not None:
                if hasattr(widget.current_style, 'deactivate'):
                    widget.current_style.deactivate()
                else:
                    widget.current_style.Off()
        except Exception:
            pass
        try:
            if hasattr(widget, 'restore_default_interactorstyle'):
                widget.restore_default_interactorstyle()
        except Exception:
            pass
        self.tool_selected = None
        self._active_tool_widget = None

    def activate_tool(self, selected_widget, tool_name):
        if selected_widget is None:
            return

        # If another tool is active, switch in one click (deactivate old, then activate new).
        if self.tool_selected is not None and self.tool_selected != tool_name:
            self._deactivate_active_tool(fallback_widget=selected_widget)

        if tool_name == self.tool_access.POLYGON_SEGMENTATION:
            print('segment clicked.')
            self.toggle_polygon_segment(selected_widget)
        elif tool_name == self.tool_access.RULER:
            print('ruler clicked.')
            self.toggle_ruler(selected_widget)
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
            self._active_tool_widget = selected_widget

        else:
            self._deactivate_active_tool(fallback_widget=selected_widget)

    def toggle_rectangle_segment(self, selected_widget):
        if selected_widget is None:
            return
        if self.tool_selected is None:
            selected_widget.set_new_interactorstyle(RectangleSegmentationInteractorStyle)
            if getattr(selected_widget, 'current_style', None) is not None:
                selected_widget.current_style.On()
            self.tool_selected = self.tool_access.RECTANGLE_SEGMENTATION
            self._active_tool_widget = selected_widget
        else:
            self._deactivate_active_tool(fallback_widget=selected_widget)

    def toggle_ai_chat(self, selected_widget):
        if selected_widget is None:
            return
        if self.tool_selected is None:
            selected_widget.set_new_interactorstyle(AIChatInteractorStyle)
            if getattr(selected_widget, 'current_style', None) is not None:
                selected_widget.current_style.On()
            self.tool_selected = self.tool_access.AI_CHAT
            self._active_tool_widget = selected_widget

        else:
            self._deactivate_active_tool(fallback_widget=selected_widget)

    def toggle_ruler(self, selected_widget):
        if selected_widget is None:
            return
        if self.tool_selected is None:
            selected_widget.set_new_interactorstyle(RulerInteractorStyle)
            if getattr(selected_widget, 'current_style', None) is not None:
                selected_widget.current_style.activate()
            self.tool_selected = self.tool_access.RULER
            self._active_tool_widget = selected_widget

        else:
            self._deactivate_active_tool(fallback_widget=selected_widget)

    def get_tool_activated_method(self):
        if self.tool_selected is None: return None

        elif self.tool_selected == self.tool_access.POLYGON_SEGMENTATION:
            return self.toggle_polygon_segment
        elif self.tool_selected == self.tool_access.RECTANGLE_SEGMENTATION:
            return self.toggle_rectangle_segment
        elif self.tool_selected == self.tool_access.AI_CHAT:
            return self.toggle_ai_chat
        elif self.tool_selected == self.tool_access.RULER:
            return self.toggle_ruler
        return None

    def check_and_deactivate_tools(self):
        if self.tool_selected is None:  # it's mean we haven't selected tool before
            return
        if self.patient_widget.selected_widget is None and self._active_tool_widget is None:
            return
        if self._active_tool_widget is not None:
            self._deactivate_active_tool(fallback_widget=self.patient_widget.selected_widget)
            return
        elif self.tool_selected is self.tool_access.POLYGON_SEGMENTATION:
            self.toggle_polygon_segment(self.patient_widget.selected_widget)
        elif self.tool_selected is self.tool_access.RECTANGLE_SEGMENTATION:
            self.toggle_rectangle_segment(self.patient_widget.selected_widget)
        elif self.tool_selected is self.tool_access.AI_CHAT:
            self.toggle_ai_chat(self.patient_widget.selected_widget)
        elif self.tool_selected is self.tool_access.RULER:
            self.toggle_ruler(self.patient_widget.selected_widget)
        return

    def turn_off_all_tools(self):
        self.check_and_deactivate_tools()
        # self.handle_buttons_checked()

    def turn_off_all_tools_after_switch(self, target_widget=None):
        """Compatibility hook used by shared viewer switch pipeline.

        In AI module mode, only deactivate the active tool when the switched
        target is the selected widget (or when no target is provided).
        """
        if target_widget is not None:
            selected = getattr(self.patient_widget, 'selected_widget', None)
            if selected is not None and selected is not target_widget:
                return
        self.turn_off_all_tools()
