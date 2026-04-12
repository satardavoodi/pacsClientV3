"""
Crosshair state management — update, toggle, sync, close, settings
for StandardMPRViewer.
"""

import logging

import vtkmodules.all as vtk
from PySide6.QtWidgets import QMenu, QColorDialog

logger = logging.getLogger(__name__)


class _MprCrosshairStateMixin:
    """Mixin: crosshair state sync, toggle, close, settings, color, width."""

    def _update_all_crosshairs(self):
        """Update crosshair visual positions in all views (optimized).

        NOTE (v1.08 fix): oblique reslicing is NO LONGER triggered from
        here.  It is handled by _synchronize_oblique_views() which must
        be called as the LAST step in every interaction path.  This
        prevents _update_slice_positions from overwriting the oblique
        camera state that was set here.
        """
        if not self.crosshairs_enabled:
            return

        bounds = self.image_data.GetBounds()

        for view_name, actors in self.crosshair_actors.items():
            h_p1, h_p2, v_p1, v_p2 = self._calculate_crosshair_endpoints(view_name, bounds)

            h_line_source = actors['h_line_source']
            v_line_source = actors['v_line_source']

            h_line_source.SetPoint1(h_p1)
            h_line_source.SetPoint2(h_p2)
            v_line_source.SetPoint1(v_p1)
            v_line_source.SetPoint2(v_p2)

            h_line_source.Update()
            v_line_source.Update()

            handles = actors.get('handles', [])
            handle_positions = [h_p1, h_p2, v_p1, v_p2]

            for i, handle in enumerate(handles):
                if i < len(handle_positions):
                    handle['source'].SetCenter(handle_positions[i])
                    handle['position'] = handle_positions[i]

            self._request_render(view_name)

        # NOTE: oblique reslicing intentionally removed from here.
        # Call _synchronize_oblique_views() as the final step instead.

    def _update_slice_positions(self):
        """Update slice positions to follow crosshair.

        Orthogonal mode: moves camera + focal point together to preserve
        viewing direction (original behavior).

        Oblique mode (v1.09 fix): updates the focal point to fully match
        current_position so that the oblique slice plane always passes
        through the crosshair center.  Camera position is NOT touched
        here; _synchronize_oblique_views() will recompute it correctly.

        Previous v1.08 only updated the through-plane axis, causing the
        oblique slice to drift when the crosshair center moved in-plane.
        """
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.viewers:
                continue

            renderer = self.viewers[view_name]['renderer']
            camera = renderer.GetActiveCamera()

            current_focal = list(camera.GetFocalPoint())
            current_pos = list(camera.GetPosition())

            if view_name == 'axial':
                delta = self.current_position[2] - current_focal[2]
                current_focal[2] = self.current_position[2]
                current_pos[2] += delta
            elif view_name == 'sagittal':
                delta = self.current_position[0] - current_focal[0]
                current_focal[0] = self.current_position[0]
                current_pos[0] += delta
            elif view_name == 'coronal':
                delta = self.current_position[1] - current_focal[1]
                current_focal[1] = self.current_position[1]
                current_pos[1] += delta

            camera.SetFocalPoint(current_focal)
            camera.SetPosition(current_pos)

            if self._oblique_cameras_active:
                mapper = self.viewers[view_name].get('mapper')
                if mapper is not None:
                    plane = mapper.GetSlicePlane()
                    if plane is not None:
                        plane.SetOrigin(self.current_position)
                        mapper.Modified()

            self._request_render(view_name)

    def _synchronize_oblique_views(self):
        """Final step after any crosshair / slice update.

        Re-applies oblique camera repositioning if any view has rotation.
        Safe to call even when no rotation exists (fast early-return).
        Must be called AFTER both _update_all_crosshairs and
        _update_slice_positions so that the focal points are correct.
        """
        self._update_oblique_reslicing()

    def _update_slice_info_texts(self):
        """Update slice info text in all views (optimized)"""
        for view_name, text_actor in self.text_actors.items():
            text_actor.SetInput(self._get_slice_info_text(view_name))
            self._request_render(view_name)

    def _toggle_crosshairs(self, checked):
        """Toggle crosshairs visibility and interaction (optimized)"""
        self.crosshairs_enabled = checked
        self.crosshair_interaction_enabled = checked

        for view_name, actors in self.crosshair_actors.items():
            h_line_actor = actors['h_line_actor']
            v_line_actor = actors['v_line_actor']
            handles = actors['handles']

            if checked:
                h_line_actor.VisibilityOn()
                v_line_actor.VisibilityOn()
                for handle in handles:
                    handle['actor'].VisibilityOn()
                self._enable_crosshair_interaction(view_name)
            else:
                h_line_actor.VisibilityOff()
                v_line_actor.VisibilityOff()
                for handle in handles:
                    handle['actor'].VisibilityOff()
                self._disable_crosshair_interaction(view_name)

            self._request_render(view_name)

        status = 'enabled' if checked else 'disabled'
        logger.info(f"Crosshairs {status} (visibility + interaction)")

    def _close_mpr(self):
        """Close MPR viewer and return to normal view"""
        logger.info("Closing MPR viewer...")

        try:
            parent = self.parent()
            while parent is not None:
                if hasattr(parent, 'toolbar_manager'):
                    logger.info("Found toolbar_manager, triggering MPR toggle to close")
                    if hasattr(parent, 'selected_widget'):
                        for node in parent.lst_nodes_viewer:
                            if hasattr(node.vtk_widget, '_zeta_mpr_widget'):
                                if node.vtk_widget._zeta_mpr_widget == self:
                                    original_widget = node.vtk_widget

                                    if hasattr(self, 'cleanup'):
                                        self.cleanup()
                                    self.hide()
                                    self.deleteLater()

                                    if hasattr(original_widget, '_zeta_mpr_widget'):
                                        delattr(original_widget, '_zeta_mpr_widget')
                                    original_widget.setVisible(True)

                                    if hasattr(parent, 'toolbar_manager'):
                                        parent.toolbar_manager.tool_selected = None
                                        parent.toolbar_manager.handle_buttons_checked()

                                    logger.info("✓ Zeta MPR closed successfully")
                                    return

                    logger.warning("Could not find original widget to restore")
                    return

                parent = parent.parent()

            logger.warning("Could not find toolbar_manager to close MPR")

        except Exception as e:
            logger.error(f"Error closing MPR: {e}", exc_info=True)

    def _enable_crosshair_interaction(self, view_name):
        """Enable crosshair interaction for a specific view"""
        if view_name not in self.crosshair_styles:
            logger.warning(f"No crosshair style found for {view_name}")
            return

        if view_name not in self.viewers:
            return

        style = self.crosshair_styles[view_name]
        interactor = self.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()

        if style:
            interactor.SetInteractorStyle(style)
            logger.debug(f"Crosshair interaction enabled for {view_name}")

    def _disable_crosshair_interaction(self, view_name):
        """Disable crosshair interaction for a specific view"""
        if view_name not in self.crosshair_styles:
            logger.warning(f"No crosshair style found for {view_name}")
            return

        if view_name not in self.viewers:
            return

        interactor = self.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()
        default_style = vtk.vtkInteractorStyleImage()
        interactor.SetInteractorStyle(default_style)

        logger.debug(f"Crosshair interaction disabled for {view_name}, using default style")

    def _show_crosshair_settings_menu(self, pos):
        """Show crosshair settings menu on right-click"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #2a2a2a;
                color: white;
                border: 1px solid #555;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
            }
            QMenu::item:selected {
                background: #3b82f6;
            }
        """)

        color_menu = menu.addMenu("🎨 Crosshair Color")
        color_menu.setStyleSheet(menu.styleSheet())

        green_action = color_menu.addAction("Green (Default)")
        red_action = color_menu.addAction("Red")
        blue_action = color_menu.addAction("Blue")
        yellow_action = color_menu.addAction("Yellow")
        cyan_action = color_menu.addAction("Cyan")
        magenta_action = color_menu.addAction("Magenta")
        white_action = color_menu.addAction("White")
        custom_action = color_menu.addAction("Custom...")

        menu.addSeparator()

        width_menu = menu.addMenu("📏 Line Width")
        width_menu.setStyleSheet(menu.styleSheet())

        width_1_action = width_menu.addAction("Thin (1px)")
        width_2_action = width_menu.addAction("Normal (2px)")
        width_3_action = width_menu.addAction("Thick (3px)")
        width_4_action = width_menu.addAction("Very Thick (4px)")

        menu.addSeparator()

        reset_rotation_action = menu.addAction("🔄 Reset Rotation")

        action = menu.exec_(self.crosshair_btn.mapToGlobal(pos))

        if action == green_action:
            self._set_crosshair_color((0.0, 1.0, 0.0))
        elif action == red_action:
            self._set_crosshair_color((1.0, 0.0, 0.0))
        elif action == blue_action:
            self._set_crosshair_color((0.0, 0.0, 1.0))
        elif action == yellow_action:
            self._set_crosshair_color((1.0, 1.0, 0.0))
        elif action == cyan_action:
            self._set_crosshair_color((0.0, 1.0, 1.0))
        elif action == magenta_action:
            self._set_crosshair_color((1.0, 0.0, 1.0))
        elif action == white_action:
            self._set_crosshair_color((1.0, 1.0, 1.0))
        elif action == custom_action:
            color = QColorDialog.getColor()
            if color.isValid():
                r, g, b = color.redF(), color.greenF(), color.blueF()
                self._set_crosshair_color((r, g, b))
        elif action == width_1_action:
            self._set_crosshair_width(1)
        elif action == width_2_action:
            self._set_crosshair_width(2)
        elif action == width_3_action:
            self._set_crosshair_width(3)
        elif action == width_4_action:
            self._set_crosshair_width(4)
        elif action == reset_rotation_action:
            self._reset_crosshair_rotation()

    def _get_handle_color(self, color):
        """Slightly brighten the handle color for better visibility."""
        return (
            min(color[0] + 0.1, 1.0),
            min(color[1] + 0.1, 1.0),
            min(color[2] + 0.1, 1.0),
        )

    def _set_crosshair_color(self, color):
        """Set crosshair color (optimized)"""
        self.crosshair_color = color
        self.crosshair_handle_color = self._get_handle_color(color)

        for view_name, actors in self.crosshair_actors.items():
            actors['h_line_actor'].GetProperty().SetColor(*color)
            actors['v_line_actor'].GetProperty().SetColor(*color)

            for handle in actors.get('handles', []):
                handle['actor'].GetProperty().SetColor(*self.crosshair_handle_color)

            self._request_render(view_name)

        logger.info(f"Crosshair color changed to RGB{color}")

    def _set_crosshair_width(self, width):
        """Set crosshair line width (optimized)"""
        self.crosshair_width = width

        for view_name, actors in self.crosshair_actors.items():
            actors['h_line_actor'].GetProperty().SetLineWidth(width)
            actors['v_line_actor'].GetProperty().SetLineWidth(width)

            self._request_render(view_name)

        logger.info(f"Crosshair width changed to {width}px")

    def _reset_crosshair_rotation(self):
        """Reset crosshair rotation to 0 degrees in all views"""
        for view_name in self.crosshair_angles.keys():
            self.crosshair_angles[view_name] = 0.0

        self._update_all_crosshairs()
        self._synchronize_oblique_views()

        logger.info("Crosshair rotation reset to 0°")
