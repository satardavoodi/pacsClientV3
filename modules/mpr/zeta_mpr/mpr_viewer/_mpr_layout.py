"""
MPR Layout Mixin — expand/collapse, event filter, toolbar tools, cleanup.

Extracted from standard_mpr_viewer.py (Phase 5A refactoring).
"""
import logging

from PySide6.QtCore import Qt, QPoint

logger = logging.getLogger(__name__)


class _MprLayoutMixin:
    """4-view layout management, event filter, toolbar tool routing, cleanup."""

    def eventFilter(self, obj, event):
        """Event filter to detect user interaction with VTK widgets.

        For the 3D render box, we intercept right-mouse-button events at the Qt
        level so they are guaranteed to reach our handler regardless of how VTK
        routes events internally.  RMB click (no drag) → preset menu, RMB drag
        → brightness / contrast / opacity adjustment.
        """
        view_name = self._vtk_widget_to_view.get(obj)

        # ---- Keep per-pane crosshair toggles pinned on pane resize ----
        if event.type() == event.Type.Resize and view_name:
            self._position_view_crosshair_toggle(view_name)

        # ---- Double-click: expand / collapse any view ----
        if event.type() == event.Type.MouseButtonDblClick:
            if view_name:
                self._set_active_view(view_name)
                self._toggle_expand_view(view_name)
                return True

        # ---- Stop auto-rotation on any mouse press or wheel ----
        if event.type() in (event.Type.MouseButtonPress, event.Type.Wheel):
            if view_name:
                self._set_active_view(view_name)
            self.stop_auto_rotation()

        # ---- 3D Render-box RMB handling (Qt level) ----
        if view_name == '3d':
            from PySide6.QtCore import Qt as QtConst

            if event.type() == event.Type.MouseButtonPress and event.button() == QtConst.RightButton:
                self._vrt_qt_rmb_down = True
                self._vrt_qt_rmb_dragging = False
                self._vrt_qt_rmb_start = event.pos()
                self._capture_vrt_baseline()
                return True  # fully consume – RMB is handled here, not in VTK

            if event.type() == event.Type.MouseButtonRelease and event.button() == QtConst.RightButton:
                was_dragging = getattr(self, '_vrt_qt_rmb_dragging', False)
                self._vrt_qt_rmb_down = False
                if not was_dragging:
                    # Pure click → show preset context menu at cursor position
                    self._show_vrt_preset_menu(obj, event.pos())
                self._vrt_qt_rmb_dragging = False
                self._vrt_qt_rmb_start = None
                self._reset_vrt_rmb_state()
                return True  # consume release so VTK doesn't double-fire

            if event.type() == event.Type.MouseMove and getattr(self, '_vrt_qt_rmb_down', False):
                start = getattr(self, '_vrt_qt_rmb_start', None)
                if start is not None:
                    dx = event.pos().x() - start.x()
                    dy = -(event.pos().y() - start.y())  # invert Y for natural feel
                    if not getattr(self, '_vrt_qt_rmb_dragging', False):
                        if abs(dx) >= 6 or abs(dy) >= 6:
                            self._vrt_qt_rmb_dragging = True
                    if self._vrt_qt_rmb_dragging:
                        self._apply_vrt_appearance_delta(dx, dy)
                        return True  # consume move during drag

        return super().eventFilter(obj, event)

    def _register_view(self, view_name, container, vtk_widget, row, col, row_span=1, col_span=1):
        """Register a view container/widget for expand/collapse and event handling."""
        self._view_containers[view_name] = container
        self._view_positions[view_name] = (row, col, row_span, col_span)
        self._vtk_widget_to_view[vtk_widget] = view_name
        vtk_widget.installEventFilter(self)
        if view_name != '3d':
            self._add_view_crosshair_toggle(view_name, vtk_widget)
        self._update_view_highlights()

    # ── Per-viewport crosshair toggle (2026-06-06) ─────────────────────

    def _add_view_crosshair_toggle(self, view_name, pane_widget):
        """Small overlay button on a 2D pane to show/hide ITS crosshair only.

        Layering (fix 2026-06-06): the button must be a CHILD of the pane's
        QVTKRenderWindowInteractor and a NATIVE window itself. As a plain
        sibling of the native GL pane it painted BEHIND the image (a native
        HWND always covers non-native sibling widgets on Windows); as a
        native child window it reliably stacks above the parent GL surface
        and stays clickable. State semantics live in
        _MprCrosshairStateMixin.set_view_crosshair_visible.
        """
        try:
            from PySide6.QtWidgets import QPushButton

            if not hasattr(self, '_crosshair_view_buttons'):
                self._crosshair_view_buttons = {}

            btn = QPushButton("✛", pane_widget)
            btn.setObjectName("mprViewCrosshairToggle")
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setToolTip("Hide crosshair in this viewport")
            btn.setFixedSize(22, 22)
            # Native child HWND: required to stack above the GL render
            # surface; also never steal activation from the render window.
            btn.setAttribute(Qt.WA_NativeWindow, True)
            btn.setAttribute(Qt.WA_ShowWithoutActivating, True)
            btn.setStyleSheet(
                "QPushButton#mprViewCrosshairToggle {"
                " background: rgba(20, 28, 40, 170); color: #6b7785;"
                " border: 1px solid #3a4a5e; border-radius: 4px;"
                " font-size: 12px; padding: 0; }"
                " QPushButton#mprViewCrosshairToggle:hover {"
                " background: rgba(42, 58, 80, 220); }"
                " QPushButton#mprViewCrosshairToggle:checked {"
                " color: #4da3ff; border-color: #2a5a8e; }"
            )
            btn.clicked.connect(
                lambda checked, vn=view_name: self.set_view_crosshair_visible(vn, checked)
            )
            btn.show()
            btn.raise_()
            self._crosshair_view_buttons[view_name] = btn
            self._position_view_crosshair_toggle(view_name)
        except Exception as exc:
            logger.debug("per-view crosshair toggle setup failed for %s: %r", view_name, exc)

    def _position_view_crosshair_toggle(self, view_name):
        """Keep the pane's crosshair toggle pinned to its top-right corner."""
        try:
            btn = (getattr(self, '_crosshair_view_buttons', None) or {}).get(view_name)
            if btn is None:
                return
            pane = btn.parentWidget()
            if pane is None:
                return
            btn.move(max(0, pane.width() - btn.width() - 6), 6)
            btn.raise_()
        except Exception:
            pass

    def _toggle_expand_view(self, view_name):
        """Toggle expand/collapse for a specific view."""
        if not self._views_layout:
            return

        if self._expanded_view == view_name:
            # Collapse back to 4-view layout
            for name, container in self._view_containers.items():
                container.setVisible(True)
                row, col, row_span, col_span = self._view_positions.get(name, (0, 0, 1, 1))
                self._views_layout.addWidget(container, row, col, row_span, col_span)
            self._expanded_view = None
            self._unlock_mpr_size()
            return

        # Expand requested view
        self._lock_mpr_size()
        for name, container in self._view_containers.items():
            if name == view_name:
                container.setVisible(True)
                self._views_layout.addWidget(container, 0, 0, 2, 2)
            else:
                container.setVisible(False)
        self._expanded_view = view_name

    def _lock_mpr_size(self):
        """Lock MPR widget size to avoid layout snapping when expanding a view."""
        if self._size_lock is not None:
            return
        self._size_lock = {
            'min': self.minimumSize(),
            'max': self.maximumSize(),
            'size': self.size()
        }
        self.setMinimumSize(self._size_lock['size'])
        self.setMaximumSize(self._size_lock['size'])

    def _unlock_mpr_size(self):
        """Restore MPR widget size constraints after collapsing a view."""
        if self._size_lock is None:
            return
        self.setMinimumSize(self._size_lock['min'])
        self.setMaximumSize(self._size_lock['max'])
        self._size_lock = None

    # ── Toolbar integration helpers (2D toolbar -> Zeta MPR) ──────────

    def activate_ruler(self):
        return self.measurement_tools.activate_ruler_tool('all')

    def activate_angle(self):
        return self.measurement_tools.activate_angle_tool('all')

    def activate_caption(self):
        return self.measurement_tools.activate_caption_tool('all')

    def deactivate_tool(self):
        self.measurement_tools.deactivate_tool()

    def activate_toolbar_tool(self, tool_name):
        """Activate a 2D toolbar interaction tool inside MPR (zoom/WL/pan/stack/eraser)."""
        from ._interactor_styles import MPRToolbarInteractorStyle

        self._toolbar_active_tool = tool_name
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.viewers:
                continue
            style = self._toolbar_styles.get(view_name)
            if style is None:
                style = MPRToolbarInteractorStyle(self, view_name)
                self._toolbar_styles[view_name] = style
            style.set_active_tool(tool_name)
            interactor = self.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()
            interactor.SetInteractorStyle(style)
        return True

    def deactivate_toolbar_tool(self):
        """Restore default crosshair interaction after a toolbar tool is turned off."""
        self._toolbar_active_tool = None
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.viewers:
                continue
            if self.crosshair_interaction_enabled and self.crosshairs_enabled:
                self._enable_crosshair_interaction(view_name)
            else:
                self._disable_crosshair_interaction(view_name)

    def zoom_to_fit(self):
        """Reset zoom for all 2D MPR views."""
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.viewers:
                continue
            renderer = self.viewers[view_name]['renderer']
            renderer.ResetCamera()
            renderer.ResetCameraClippingRange()
            self._request_render(view_name)

    def delete_measurement_at(self, view_name, display_pos):
        if view_name not in self.viewers:
            return False
        renderer = self.viewers[view_name]['renderer']
        deleted = self.measurement_tools.delete_measurement_at(view_name, display_pos, renderer)
        if deleted:
            self._request_render(view_name)
        return deleted

    def reset_to_initial_state(self):
        """Reset MPR views to initial state and clear annotations."""
        try:
            self.deactivate_toolbar_tool()
            self.measurement_tools.deactivate_tool()
            self.measurement_tools.clear_measurements()
        except Exception:
            pass
        self._reset_rendering()
        self._set_active_view('axial')

    def apply_view_transform(self, action, view_name=None):
        """Apply rotation/flip to a single MPR view."""
        target_view = view_name or self._active_view_name
        if target_view not in self.viewers or target_view == '3d':
            return False
        renderer = self.viewers[target_view]['renderer']
        camera = renderer.GetActiveCamera()

        if action == self.tool_access.ROTATION_LEFT:
            camera.Roll(90)
        elif action == self.tool_access.ROTATION_RIGHT:
            camera.Roll(-90)
        elif action == self.tool_access.FLIP_HORIZONTAL:
            camera.Azimuth(180)
        elif action == self.tool_access.FLIP_VERTICAL:
            camera.Roll(180)
        else:
            return False

        renderer.ResetCameraClippingRange()
        self._request_render(target_view)
        return True

    def _set_active_view(self, view_name):
        """Set the active view for toolbar actions and show selection highlight."""
        if view_name not in self._view_containers:
            return
        self._active_view_name = view_name
        if view_name in ['axial', 'sagittal', 'coronal']:
            self.active_measurement_viewport = view_name
        self._update_view_highlights()

    def _update_view_highlights(self):
        for name, container in self._view_containers.items():
            if name == self._active_view_name:
                container.setStyleSheet(self._active_view_style)
            else:
                container.setStyleSheet(self._inactive_view_style)

    def get_current_volume(self, view_name):
        """Get current volume for a view (for stack tools)"""
        if view_name in self.viewers and 'oblique_volume' in self.viewers[view_name]:
            return self.viewers[view_name]['oblique_volume']
        return self.image_data

    def _update_coordinates_label(self):
        """Update slice info text overlays in viewports"""
        # Slice info is shown in VTK text actors (created in _create_slice_info_text)
        pass

    def cleanup(self):
        """Cleanup"""
        # Stop auto-rotation timer
        if hasattr(self, 'auto_rotation_timer') and self.auto_rotation_timer:
            self.auto_rotation_timer.stop()
            self.auto_rotation_timer = None

        for view_info in self.viewers.values():
            if 'widget' in view_info:
                view_info['widget'].Finalize()
