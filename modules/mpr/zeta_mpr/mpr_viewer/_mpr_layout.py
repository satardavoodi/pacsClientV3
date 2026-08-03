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
            # Select the MPR's HOST cell as the active viewport on a pane click, so
            # annotation tools (ruler / arrow / text) target the MPR — exactly like
            # clicking a FAST cell selects it. Without this, after annotating another
            # cell the MPR could not be re-selected by clicking it, so the ruler kept
            # arming the other cell (patient 48272 — "can't draw on MPR after
            # annotating the other layout"). PASSIVE: we do NOT return True, so the
            # press still reaches VTK (crosshair / WL / stack unchanged). The callback
            # is set by the host only when enabled and is a cheap no-op when the MPR
            # cell is already active.
            if event.type() == event.Type.MouseButtonPress:
                try:
                    _vac = getattr(self, '_viewport_activate_cb', None)
                    if callable(_vac):
                        _vac()
                except Exception:
                    pass

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

    def set_viewport_activate_callback(self, cb):
        """Host hook: invoked on a mouse press in ANY MPR pane so the host can make
        the MPR's cell the active viewport — annotation tools (ruler / arrow / text)
        then target the MPR, exactly like clicking a FAST cell selects it. No-op
        until the host sets it (so flag-off / unwired = byte-identical legacy).
        Wired by ToolbarManager.toggle_zeta_mpr (patient 48272)."""
        self._viewport_activate_cb = cb

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

    def activate_arrow(self):
        # Two-click arrow (tail → head). Distinct from caption, which spawns
        # a "Text" box with a default leader line — the toolbar ARROW used to
        # call activate_caption, producing the reported wrong arrows.
        return self.measurement_tools.activate_arrow_tool('all')

    def set_tool_auto_exit_callback(self, callback):
        """Register the toolbar callback invoked when a single-use tool
        (ruler/angle/arrow) finishes one measurement — lets MPR drop the tool
        highlight + restore the default mouse mode, matching the 2D viewer."""
        try:
            self.measurement_tools.on_auto_exit = callback
        except Exception:
            pass

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
        # ── STEP 1 of the teardown contract: STOP ACCEPTING NEW MPR OPERATIONS ──
        # Set FIRST, before any timer stop or VTK call, so that anything already
        # queued on the event loop (a deferred render, an interaction flush, a
        # wheel event mid-teardown) sees a closed viewer and no-ops instead of
        # touching half-finalized VTK objects. This is the deterministic version
        # of the per-call `if view_name in self.viewers` guards — those work only
        # AFTER `viewers.clear()` runs at the very end of this method, leaving a
        # window during teardown where a callback still finds live entries.
        self._mpr_closed = True

        # L1 deferred-3D teardown safety: if MPR is closed before the deferred
        # 3D VRT idle callback fires, clear the pending flag so the callback
        # bails instead of building into a finalizing widget (the callback also
        # swallows the deleted-object RuntimeError as a second layer).
        self._deferred_3d_pending = False

        # Stop auto-rotation timer
        if hasattr(self, 'auto_rotation_timer') and self.auto_rotation_timer:
            self.auto_rotation_timer.stop()
            self.auto_rotation_timer = None

        # ── OPT-47: FULL teardown — release GPU + host memory, not just Finalize() ────────
        # This used to be `Finalize()` only. That leaves the renderer's props, the mappers'
        # input, the interactor observers and — critically — the render window's GRAPHICS
        # RESOURCES (the uploaded 3D texture(s), up to ~400 MB VRAM for a large study) alive.
        # Across a working session the leaked VRAM accumulates, which is why the FIRST MPR
        # open on a big study could die in the GPU allocator while the SAME study opened
        # fine right after an app relaunch (fresh VRAM). It also leaked the flipped host
        # volume via `self.image_data` + a reference CYCLE (each view holds a
        # VRTInteractorStyle that holds self), so a second open could build a second full
        # volume while the first was still resident.
        # Ordering matters: release GL resources while the context is STILL VALID (before
        # Finalize()), then drop observers, inputs and props. Modelled on the proven
        # `_teardown_curved_mpr_vtk`. Every step is individually guarded — a teardown race
        # (Qt object already deleted) must never raise out of cleanup(). Idempotent.
        # Kill switch: AIPACS_MPR_FULL_TEARDOWN=0 restores the legacy Finalize()-only path.
        import os as _os47t
        _full_teardown = (_os47t.environ.get("AIPACS_MPR_FULL_TEARDOWN", "1") or "1").strip() != "0"

        # Stop the unparented deferred-render timer: a pending 5 ms singleShot firing after
        # Finalize() renders into a dead window (the "already deleted" RuntimeError class).
        if _full_teardown:
            for _tname in ("_render_timer", "_prewarm_timer"):
                try:
                    _t = getattr(self, _tname, None)
                    if _t is not None:
                        _t.stop()
                except Exception:
                    pass
            try:
                _mt = getattr(self, "measurement_tools", None)
                if _mt is not None:
                    try:
                        _mt.deactivate_tool()
                    except Exception:
                        pass
                    try:
                        _mt.clear_measurements()
                    except Exception:
                        pass
            except Exception:
                pass

        for view_info in self.viewers.values():
            _w = view_info.get('widget') if isinstance(view_info, dict) else None
            if _full_teardown:
                # 1. detach the volume/slice inputs so the mappers stop referencing image_data
                for _mkey in ('mapper', 'slice_mapper', 'volume_mapper', 'reslice_mapper'):
                    try:
                        _m = view_info.get(_mkey) if isinstance(view_info, dict) else None
                        if _m is not None and hasattr(_m, 'SetInputData'):
                            _m.SetInputData(None)
                    except Exception:
                        pass
                # 2. drop actors/props from the renderer
                try:
                    _r = view_info.get('renderer') if isinstance(view_info, dict) else None
                    if _r is not None:
                        _r.RemoveAllViewProps()
                except Exception:
                    pass
                # 3. stop event delivery to a widget that is about to die
                try:
                    _i = view_info.get('interactor') if isinstance(view_info, dict) else None
                    if _i is None and _w is not None:
                        _i = _w
                    if _i is not None:
                        try:
                            _i.RemoveAllObservers()
                        except Exception:
                            pass
                        try:
                            _i.Disable()
                        except Exception:
                            pass
                except Exception:
                    pass
                # 4. release the GPU textures/FBOs WHILE the GL context is still valid
                try:
                    if _w is not None:
                        _rw = _w.GetRenderWindow()
                        if _rw is not None:
                            try:
                                _rw.ReleaseGraphicsResources(_rw)
                            except Exception:
                                pass
                            try:
                                _rw.RemoveRenderer(view_info.get('renderer'))
                            except Exception:
                                pass
                except Exception:
                    pass
            # 5. finally tear the render window down (legacy behaviour, always runs)
            try:
                if _w is not None:
                    _w.Finalize()
            except Exception:
                pass

        if _full_teardown:
            # 6. break the view dicts (they hold the interactor styles that reference self —
            #    a reference CYCLE that would otherwise wait for a generational gc.collect(),
            #    which this codebase deliberately avoids as stop-the-world) and drop the
            #    flipped full-size volume so its host memory is reclaimed promptly.
            try:
                self.viewers.clear()
            except Exception:
                pass
            try:
                self.image_data = None
            except Exception:
                pass

            # ── 7. LIFECYCLE COMPLETION (2026-08-01) ──────────────────────────
            # OPT-47 released the GPU + the volume, but left a second class of
            # references alive. `self.viewers` was the only container cleared;
            # these were assigned once and never cleared, so after "close" the
            # StandardMPRViewer still held every vtkTextActor, every crosshair
            # actor, every pane container widget and a widget->view map — and a
            # Qt widget keeps its whole parent chain alive. Repeated
            # open → close → open (the exact scenario reported) therefore grew
            # host memory monotonically even though each open's *volume* was
            # freed correctly. Clearing them here is what makes close ≈ the
            # inverse of open.
            #
            # `_toolbar_styles` / `_viewport_activate_cb` / `_diag` additionally
            # close CROSS-MODULE cycles: the activate callback is a closure over
            # the ToolbarManager and the host cell, so a "closed" MPR kept the
            # patient tab's toolbar reachable from VTK-side state.
            for _dict_attr in (
                "text_actors",          # vtkTextActor per pane (slice info)
                "crosshair_actors",     # crosshair line actors per pane
                "_view_containers",     # QWidget per pane
                "_vtk_widget_to_view",  # QVTKRenderWindowInteractor -> view name
                "_toolbar_styles",      # per-pane toolbar style state
                "_render_pending",      # deferred-render bookkeeping
            ):
                try:
                    _d = getattr(self, _dict_attr, None)
                    if _d is not None and hasattr(_d, "clear"):
                        _d.clear()
                except Exception:
                    pass

            # Drop the cross-module callback + diagnostics sink so nothing in
            # the patient tab stays reachable through this (closed) viewer.
            for _ref_attr in ("_viewport_activate_cb", "_diag"):
                try:
                    if hasattr(self, _ref_attr):
                        setattr(self, _ref_attr, None)
                except Exception:
                    pass

            # The interaction-throttle timer was the one timer cleanup() never
            # stopped. It is created lazily in `_request_interaction_update` and
            # fires `_flush_interaction_update` -> `_apply_interaction_update`,
            # which walks `self.viewers` and renders. Left running through a
            # close it is a stale callback into a finalized render window — the
            # exact use-after-free class this teardown exists to prevent.
            # `_render_timer`/`_prewarm_timer` are stopped above (step 0); here
            # they are also DISCONNECTED and dropped so a later
            # `_request_render` cannot resurrect one against a dead widget.
            for _tname in ("_interaction_timer", "_render_timer", "_prewarm_timer"):
                try:
                    _t = getattr(self, _tname, None)
                    if _t is None:
                        continue
                    try:
                        _t.stop()
                    except Exception:
                        pass
                    try:
                        _t.timeout.disconnect()
                    except Exception:
                        pass  # not connected / already disconnected
                    try:
                        setattr(self, _tname, None)
                    except Exception:
                        pass
                except Exception:
                    pass
