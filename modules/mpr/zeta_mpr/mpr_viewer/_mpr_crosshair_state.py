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
        """Update slice positions to follow the crosshair.

        BOTH modes: the camera moves along this pane's through-plane (look)
        axis ONLY, carrying focal point and position together so the viewing
        direction and distance are preserved. The image stays put; the slice
        advances.

        Oblique mode additionally re-points the mapper's explicit ``vtkPlane``
        origin at ``current_position``, because since **v1.09.Fix-E** the
        oblique plane is carried by that plane and NOT by the camera
        (``_set_oblique_camera`` runs ``SliceFacesCameraOff()`` +
        ``SliceAtFocalPointOff()``). The crosshair centre is therefore on the
        displayed oblique plane by construction.

        DOCSTRING CORRECTED 2026-08-23. It previously described the v1.09
        behaviour — "updates the focal point to fully match current_position…
        _synchronize_oblique_views() will recompute it correctly" — which
        Fix-E **reverted** because moving the focal point in-plane made the
        image pan under the cursor during rotation. Both of those clauses had
        been false for some time and contradicted the code directly below;
        acting on them would have re-introduced that defect. Do not restore
        full focal-point tracking here. See ``docs/pipelines/mpr-geometry-pipeline.md``
        §10.9 and ``docs/plans/architecture/MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md``.
        """
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.viewers:
                continue

            renderer = self.viewers[view_name]['renderer']
            camera = renderer.GetActiveCamera()

            current_focal = list(camera.GetFocalPoint())
            current_pos = list(camera.GetPosition())

            # Move the camera ONLY along this pane's through-plane (look) axis to follow the
            # crosshair, keeping focal+position together so the viewing direction & distance are
            # preserved (image stays put; the slice advances). The look axis comes from
            # _view_axes() so a routed non-axial-native series uses its ACTUAL through-plane axis
            # instead of the hardcoded axial=Z/sag=X/cor=Y (which slid the slice out of the
            # volume → black image). Axial-native returns the legacy axis → unchanged.
            look_axis = self._view_axes(view_name)[0]
            delta = self.current_position[look_axis] - current_focal[look_axis]
            current_focal[look_axis] = self.current_position[look_axis]
            current_pos[look_axis] += delta

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

        # Slice-bound annotations (2026-06-09): this is the universal post-
        # reslice hook (wheel scroll + crosshair move/scroll/rotate all reach
        # it), so refresh which measurements are visible for each pane's new
        # through-plane position. Cheap (change-only toggle) + fully guarded so
        # it can never break the reslice path.
        mt = getattr(self, 'measurement_tools', None)
        if mt is not None:
            try:
                mt.refresh_slice_visibility()
            except Exception:
                pass

    def _update_slice_info_texts(self):
        """Update slice info text in all views (optimized)"""
        for view_name, text_actor in self.text_actors.items():
            text_actor.SetInput(self._get_slice_info_text(view_name))
            self._request_render(view_name)

    def _toggle_crosshairs(self, checked):
        """Toggle crosshairs visibility and interaction (optimized)"""
        self.crosshairs_enabled = checked
        self.crosshair_interaction_enabled = checked

        # The global switch overrides any per-viewport hides (simple mental
        # model: turning Crosshairs ON shows them everywhere again).
        self._crosshair_hidden_views = set()
        self._sync_view_crosshair_buttons()

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

    # ------------------------------------------------------------------
    # Per-viewport crosshair visibility (2026-06-06)
    # ------------------------------------------------------------------
    # Each 2D pane has its own small overlay toggle (see
    # _mpr_views._add_view_crosshair_toggle) so the crosshair can be hidden
    # in one viewport without hiding it everywhere. Effective visibility of
    # a pane = crosshairs_enabled AND pane not in _crosshair_hidden_views.

    def toggle_view_crosshair(self, view_name):
        """Flip crosshair visibility for a single viewport."""
        hidden = getattr(self, '_crosshair_hidden_views', set())
        self.set_view_crosshair_visible(view_name, view_name in hidden)

    def set_view_crosshair_visible(self, view_name, visible):
        """Show/hide the crosshair in ONE viewport only.

        Interaction follows visibility for that pane (an invisible crosshair
        must not be a drag target), but is only touched while no toolbar tool
        owns the pane's interactor (_toolbar_active_tool is None) — a toolbar
        tool's style must never be stomped.
        """
        if not hasattr(self, '_crosshair_hidden_views'):
            self._crosshair_hidden_views = set()

        if visible:
            self._crosshair_hidden_views.discard(view_name)
        else:
            self._crosshair_hidden_views.add(view_name)

        self._apply_view_crosshair_visibility(view_name)
        self._sync_view_crosshair_buttons()

    def _apply_view_crosshair_visibility(self, view_name):
        """Apply effective (global AND per-view) crosshair visibility to a pane."""
        actors = (getattr(self, 'crosshair_actors', None) or {}).get(view_name)
        if not actors:
            return

        effective = bool(self.crosshairs_enabled) and (
            view_name not in getattr(self, '_crosshair_hidden_views', set())
        )

        h_line_actor = actors['h_line_actor']
        v_line_actor = actors['v_line_actor']
        handles = actors.get('handles', [])
        if effective:
            h_line_actor.VisibilityOn()
            v_line_actor.VisibilityOn()
            for handle in handles:
                handle['actor'].VisibilityOn()
        else:
            h_line_actor.VisibilityOff()
            v_line_actor.VisibilityOff()
            for handle in handles:
                handle['actor'].VisibilityOff()

        if getattr(self, '_toolbar_active_tool', None) is None:
            if effective and self.crosshair_interaction_enabled:
                self._enable_crosshair_interaction(view_name)
            else:
                self._disable_crosshair_interaction(view_name)

        self._request_render(view_name)

    def _sync_view_crosshair_buttons(self):
        """Reflect per-view crosshair state on the per-pane overlay buttons."""
        buttons = getattr(self, '_crosshair_view_buttons', None) or {}
        hidden = getattr(self, '_crosshair_hidden_views', set())
        for view_name, btn in buttons.items():
            if btn is None:
                continue
            try:
                visible = view_name not in hidden
                btn.blockSignals(True)
                btn.setChecked(visible)
                btn.setToolTip(
                    "Hide crosshair in this viewport" if visible
                    else "Show crosshair in this viewport"
                )
                btn.blockSignals(False)
            except Exception:
                pass

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
        """Turn OFF crosshair GRABBING for a view while KEEPING the left button on
        STACK (the prior MPR function).

        Previously this installed a fresh ``vtkInteractorStyleImage`` whose DEFAULT
        left button is window/level — so toggling crosshairs off silently switched
        left-drag from stack to WW/WL (the reported bug). Instead we keep the view's
        ``CrosshairInteractorStyle`` (left=stack, right=WL, middle=zoom,
        wheel=scroll); its press handler routes left-drag straight to stack whenever
        crosshair grabbing is inactive (see
        ``CrosshairInteractorStyle._crosshair_grab_active``)."""
        if view_name not in self.crosshair_styles:
            logger.warning(f"No crosshair style found for {view_name}")
            return

        if view_name not in self.viewers:
            return

        style = self.crosshair_styles.get(view_name)
        interactor = self.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()
        if style is not None:
            # Keep the crosshair style so left stays on stack; grabbing is gated off
            # because crosshair_interaction_enabled / crosshairs_enabled is now False.
            interactor.SetInteractorStyle(style)

        logger.debug(f"Crosshair interaction disabled for {view_name}; left button stays on stack")

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
