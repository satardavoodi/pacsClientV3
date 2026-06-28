"""
MPR Measurement Tools - VTK Widget-based measurements for MPR viewports
Uses VTK's built-in widgets that work independently of interactor styles
"""
import logging
import os
import vtk

logger = logging.getLogger(__name__)


# Smooth, FAST-like annotation drawing in MPR (2026-06-28): a LIVE rubber-band
# preview for the two-click arrow (the leader follows the cursor from the tail,
# like the ruler's vtkDistanceWidget and the FAST viewer) + an IMMEDIATE final
# render so the placed arrow appears instantly. Purely additive — a transient
# overlay actor + render-timing only; NO geometry, reslice, slice order, or
# measurement-value change. Kill switch ``AIPACS_MPR_ANNOTATION_SMOOTH=0`` =
# byte-identical legacy (no preview, batched final render).
def _annotation_smooth_enabled():
    return os.environ.get("AIPACS_MPR_ANNOTATION_SMOOTH", "").strip().lower() not in (
        "0", "false", "off",
    )


_MPR_ANNOTATION_SMOOTH = _annotation_smooth_enabled()


# Annotation persistence (2026-06-28, unified 2026-06-28): multiple measurements
# stay visible together. The single-use auto-exit removes ONLY the current
# activation's EMPTY placement widgets (tracked per-view in ``_placement_widgets``),
# NEVER a previously-completed measurement — so drawing a measurement on a 2nd pane
# no longer wipes the 1st. This is now the ONLY path (the old destructive branch
# that removed every widget on the non-completed views was retired).
def _slice_bound_annotations_enabled():
    """Slice-bound MPR annotations are ON by default (each measurement shows
    only on the reslice position where it was drawn). Escape hatch:
    ``AIPACS_MPR_SLICE_ANNOTATIONS=0`` restores the legacy always-visible
    behaviour."""
    return os.environ.get("AIPACS_MPR_SLICE_ANNOTATIONS", "").strip().lower() not in (
        "0", "false", "off",
    )


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
        # App-wide measurement green — matches RulerInteractorStyle /
        # AngleInteractorStyle (self.color = (0, 0.9, 0)) so MPR measurements
        # look the same as the 2D viewers.
        self.tool_color = (0.0, 0.9, 0.0)
        
        # Initialize tool storage for each view
        for view_name in ['axial', 'sagittal', 'coronal']:
            self.active_tools[view_name] = {
                'ruler': [],
                'angle': [],
                'caption': [],
                'arrow': []
            }

        # Two-click arrow tool state (2026-06-06): per-view interactor
        # observer tags + the pending first (tail) point per view.
        self._arrow_observers = {}
        self._arrow_pending_tail = {}

        # Live arrow rubber-band preview (2026-06-28, FAST-like): while a tail is
        # anchored, a transient leader actor follows the cursor. Per-view mouse-move
        # observer tag, the transient preview actor, and the last display position
        # (a 2px move throttle that keeps the preview smooth on large volumes).
        self._arrow_move_observers = {}
        self._arrow_preview_actor = {}
        self._arrow_preview_last_xy = {}

        # Single-use tool auto-exit (2026-06-09): ruler/angle/arrow are
        # one-shot — after ONE completed measurement the tool returns the
        # mouse to the MPR default (stack/WL/zoom), exactly like the 2D
        # viewer's RulerInteractorStyle.auto_deactivate_tool(). `on_auto_exit`
        # is the toolbar callback (set via _mpr_layout.set_tool_auto_exit_
        # callback) that drops the tool highlight + restores tool_selected.
        self.on_auto_exit = None
        self._placement_clicks = {}      # {(view, tool): count}
        self._auto_exit_in_progress = False

        # Current-activation EMPTY placement widgets, per view (2026-06-28). Lets
        # the single-use auto-exit drop ONLY the unplaced widgets it created this
        # activation on the OTHER views — never a previously-completed measurement.
        self._placement_widgets = {}     # {view_name: widget for the current activation}

        # Slice-bound annotations (2026-06-09): a measurement is visible ONLY
        # at the reslice position (through-plane coordinate) where it was
        # drawn — like the 2D viewer's per-slice widgets — instead of being
        # projected onto every slice. `_annotation_visible_cache` keeps the
        # last-applied visibility per annotation so the per-frame refresh only
        # toggles when it actually changes (cheap + flicker-free).
        self._slice_bound_enabled = _slice_bound_annotations_enabled()
        self._annotation_visible_cache = {}   # id(item) -> bool

        logger.info("MPR Measurement Tools initialized")

    # ── Slice-bound annotation visibility (2026-06-09) ──────────────────
    def _annotation_look_coord(self, tool_type, item, look_axis):
        """Return the through-plane (look-axis) WORLD coordinate of an
        annotation — i.e. the reslice plane it was drawn on. None if it can't
        be resolved (then the annotation is left visible)."""
        try:
            if tool_type == 'arrow':
                p1 = item.get('p1') if isinstance(item, dict) else None
                return float(p1[look_axis]) if p1 is not None else None
            rep = item.GetRepresentation()
            p = [0.0, 0.0, 0.0]
            if tool_type == 'ruler':
                rep.GetPoint1WorldPosition(p)
            elif tool_type == 'angle':
                if hasattr(rep, 'GetCenterWorldPosition'):
                    rep.GetCenterWorldPosition(p)
                else:
                    rep.GetPoint1WorldPosition(p)
            elif tool_type == 'caption':
                if hasattr(rep, 'GetAnchorPosition'):
                    rep.GetAnchorPosition(p)
                else:
                    return None
            else:
                return None
            return float(p[look_axis])
        except Exception:
            return None

    def _apply_annotation_visibility(self, item, tool_type, visible):
        """Toggle an annotation's visibility; returns True if it CHANGED.
        VTK widgets use On()/Off() (couples visibility + interactivity, so a
        hidden annotation can't be grabbed); the raw arrow actor uses
        SetVisibility."""
        key = id(item)
        if self._annotation_visible_cache.get(key) == visible:
            return False
        self._annotation_visible_cache[key] = visible
        try:
            if tool_type == 'arrow':
                actor = item.get('actor') if isinstance(item, dict) else None
                if actor is not None:
                    actor.SetVisibility(1 if visible else 0)
            else:
                if visible:
                    item.On()
                else:
                    item.Off()
        except Exception:
            pass
        return True

    def refresh_slice_visibility(self, view_name=None):
        """Show only the annotations whose reslice plane matches each pane's
        current through-plane position; hide the rest. Called from the MPR
        reslice path (scroll / crosshair move) — cheap + change-only, never
        destroys annotations (scroll away and back restores them)."""
        if not self._slice_bound_enabled:
            return
        views = [view_name] if view_name else ['axial', 'sagittal', 'coronal']
        for vn in views:
            if vn not in self.active_tools:
                continue
            try:
                look_axis = int(self.mpr_viewer._view_axes(vn)[0])
                cur = float(self.mpr_viewer.current_position[look_axis])
                sp = abs(float(self.mpr_viewer.spacing[look_axis]))
                tol = max(sp * 0.5, 0.01)
            except Exception:
                continue
            dirty = False
            for tool_type in ('ruler', 'angle', 'caption', 'arrow'):
                for item in list(self.active_tools[vn].get(tool_type, [])):
                    pos = self._annotation_look_coord(tool_type, item, look_axis)
                    if pos is None:
                        continue  # can't bind → leave as-is (visible)
                    visible = abs(cur - pos) <= tol
                    if self._apply_annotation_visibility(item, tool_type, visible):
                        dirty = True
            if dirty:
                try:
                    self.mpr_viewer._request_render(vn)
                except Exception:
                    pass

    # ── Single-use tool auto-exit (2026-06-09) ──────────────────────────
    def _register_placement_autoexit(self, widget, view_name, tool_name, threshold):
        """Observe a placement widget's PlacePointEvent and auto-exit the tool
        once `threshold` points are placed (ruler=2, angle=3) — mirrors the 2D
        viewer's per-tool auto-deactivate so MPR never stays stuck in a tool."""
        self._placement_clicks[(view_name, tool_name)] = 0

        def _on_place(obj, event, vn=view_name, tn=tool_name, th=threshold):
            try:
                key = (vn, tn)
                self._placement_clicks[key] = self._placement_clicks.get(key, 0) + 1
                if self._placement_clicks[key] >= th:
                    self._fire_single_use_auto_exit(vn, tn)
            except Exception as exc:
                logger.error(f"placement auto-exit failed on {vn}/{tn}: {exc}")

        try:
            widget.AddObserver(vtk.vtkCommand.PlacePointEvent, _on_place)
        except Exception as exc:
            logger.error(f"could not register placement auto-exit: {exc}")

    def _fire_single_use_auto_exit(self, completed_view, tool_name):
        """Defer the actual teardown to the next event-loop tick so we never
        mutate widgets inside their own VTK placement callback."""
        if self._auto_exit_in_progress:
            return
        self._auto_exit_in_progress = True
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                0, lambda: self._do_single_use_auto_exit(completed_view, tool_name)
            )
        except Exception:
            # No Qt loop (headless) — run inline as a fallback.
            self._do_single_use_auto_exit(completed_view, tool_name)

    def _do_single_use_auto_exit(self, completed_view, tool_name):
        try:
            # Remove the EMPTY placement widgets on the OTHER views so a stray
            # click there can't start a second measurement (the reported
            # "multiple rulers"); keep the one the user just completed.
            if tool_name in ('ruler', 'angle'):
                # Drop ONLY this activation's unplaced placement widgets on the OTHER
                # views (tracked in _placement_widgets). This NEVER touches a
                # previously-completed measurement, so earlier annotations on those
                # panes survive — the "draw a 2nd measurement, the 1st disappears"
                # fix. The just-completed widget (completed_view) is a real
                # measurement and is kept.
                for vn in ('axial', 'sagittal', 'coronal'):
                    if vn == completed_view:
                        continue
                    w = self._placement_widgets.get(vn)
                    if w is None:
                        continue
                    try:
                        w.Off()
                    except Exception:
                        pass
                    try:
                        self.active_tools[vn][tool_name].remove(w)
                    except (ValueError, KeyError):
                        pass
                self._placement_widgets.clear()
            # Arrow: drop the click observers so no further arrows are placed.
            self._deactivate_arrow_placement()
            self._placement_clicks.clear()
            self.current_tool = None
            # Lock the slice binding for the just-completed measurement (it is
            # on the current reslice → stays visible here, hides when scrolled),
            # then force an IMMEDIATE paint of that pane. The batched
            # `_request_render` inside refresh can be coalesced/dropped during
            # the tool-completion + auto-exit + toolbar-restyle sequence, which
            # left a SECOND ruler created-but-not-painted (the reported "second
            # measurement doesn't show / looks like it's behind the image").
            try:
                self.refresh_slice_visibility(completed_view)
                # GUARANTEE the just-drawn measurement is shown: it was created
                # on the current reslice, so force its visibility True even if a
                # tiny reslice drift would fail the tolerance check at this
                # deferred moment (the slice-binding still hides it correctly on
                # the next scroll). This is what makes a SECOND/Nth measurement
                # reliably appear.
                items = self.active_tools.get(completed_view, {}).get(tool_name, [])
                if items:
                    self._apply_annotation_visibility(items[-1], tool_name, True)
                self.mpr_viewer._render_immediately(completed_view)
            except Exception:
                pass
            # Tell the toolbar to drop the tool highlight + restore the MPR
            # default mouse mode (stack / WL / zoom).
            cb = self.on_auto_exit
            if callable(cb):
                try:
                    cb()
                except Exception as exc:
                    logger.error(f"auto-exit toolbar callback failed: {exc}")
            logger.info(f"✓ MPR single-use tool '{tool_name}' auto-exited → default")
        finally:
            self._auto_exit_in_progress = False
    
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
        
        # IMPORTANT: Create distance widget representation FIRST.
        # Visuals mirror RulerInteractorStyle.set_widget_repr (2D viewers):
        # green, 1px line, no tick marks, "%-#6.3g mm" label, 24pt title.
        distance_rep = vtk.vtkDistanceRepresentation2D()
        distance_rep.GetAxis().GetProperty().SetColor(self.tool_color)
        distance_rep.GetAxis().GetProperty().SetLineWidth(1)
        distance_rep.GetAxis().SetTickLength(1)
        distance_rep.SetLabelFormat('%-#6.3g mm')
        axis = distance_rep.GetAxis()
        axis.UseFontSizeFromPropertyOn()
        ruler_tp = axis.GetTitleTextProperty()
        ruler_tp.SetFontSize(24)
        # Label readability (2026-06-06): measurement green + shadow instead
        # of the VTK default white (washes out over bright anatomy).
        ruler_tp.SetColor(*self.tool_color)
        ruler_tp.SetShadow(1)
        
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
        # Track THIS activation's placement widget so auto-exit can drop only the
        # unplaced ones on other views (never a completed measurement).
        self._placement_widgets[view_name] = distance_widget
        # Single-use: exit ruler mode after the 2-point measurement completes.
        self._register_placement_autoexit(distance_widget, view_name, 'ruler', 2)

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
        
        # IMPORTANT: Create angle widget representation FIRST.
        # Visuals mirror AngleInteractorStyle (2D viewers): green rays, arc
        # and point handles at default line width.
        angle_rep = vtk.vtkAngleRepresentation2D()
        angle_rep.GetRay1().GetProperty().SetColor(self.tool_color)
        angle_rep.GetRay2().GetProperty().SetColor(self.tool_color)
        try:
            angle_rep.GetArc().GetProperty().SetColor(self.tool_color)
            angle_rep.GetPoint1Representation().GetProperty().SetColor(self.tool_color)
        except Exception:
            pass
        # Label readability (2026-06-06): angle value (arc title) in
        # measurement green + shadow instead of default white.
        try:
            arc_tp = angle_rep.GetArc().GetTitleTextProperty()
            arc_tp.SetColor(*self.tool_color)
            arc_tp.SetShadow(1)
        except Exception:
            pass
        
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
        # Track THIS activation's placement widget (see ruler note above).
        self._placement_widgets[view_name] = angle_widget
        # Single-use: exit angle mode after the 3-point measurement completes.
        self._register_placement_autoexit(angle_widget, view_name, 'angle', 3)

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
    
    # ── Arrow tool (two-click, 2026-06-06) ──────────────────────────────
    # The toolbar ARROW used to route to the CAPTION tool here, which
    # instantly spawned a "Text" box with a default leader line in every
    # pane (the reported broken arrows). This is a real arrow matching the
    # 2D viewer's semantics: click 1 = tail, click 2 = head → filled-head
    # arrow drawn between the two points. SINGLE-USE (2026-06-09): after one
    # arrow the tool auto-exits to the MPR default mouse mode, like ruler/angle.

    def activate_arrow_tool(self, view_name='all'):
        """Activate two-click arrow placement on the given view(s)."""
        views = ['axial', 'sagittal', 'coronal'] if view_name == 'all' else [view_name]
        success = 0
        for vn in views:
            if self._activate_arrow_on_view(vn):
                success += 1
        if success:
            self.current_tool = 'arrow'
        logger.info(f"✓ Arrow tool activated on {success}/{len(views)} views")
        return success > 0

    def _activate_arrow_on_view(self, view_name):
        if view_name not in self.mpr_viewer.viewers:
            return False
        if view_name in self._arrow_observers:
            return True  # already armed

        interactor = self.mpr_viewer.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()

        def _on_click(obj, event, vn=view_name):
            try:
                self._handle_arrow_click(vn, obj)
            except Exception as exc:
                logger.error(f"arrow click failed on {vn}: {exc}")

        # Priority 0.6 > interactor style (0.0): consume presses while the
        # arrow tool is active so the crosshair never fights the placement
        # (same contract the vtk measurement widgets use at 0.5).
        tag = interactor.AddObserver("LeftButtonPressEvent", _on_click, 0.6)
        self._arrow_observers[view_name] = (interactor, tag)

        # Live rubber-band preview (FAST-like): a mouse-move observer updates a
        # transient arrow from the tail to the cursor between the two clicks. It
        # does NOT abort the move (the crosshair/hover is harmless without a
        # button press) and is a no-op until a tail is anchored.
        if _MPR_ANNOTATION_SMOOTH:
            def _on_move(obj, event, vn=view_name):
                try:
                    self._handle_arrow_move(vn)
                except Exception as exc:
                    logger.debug(f"arrow preview move failed on {vn}: {exc}")

            mtag = interactor.AddObserver("MouseMoveEvent", _on_move, 0.6)
            self._arrow_move_observers[view_name] = (interactor, mtag)
        return True

    def _display_to_world(self, renderer, x, y):
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToDisplay()
        coord.SetValue(float(x), float(y), 0.0)
        return tuple(coord.GetComputedWorldValue(renderer))

    def _handle_arrow_click(self, view_name, interactor_obj):
        interactor = self.mpr_viewer.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()
        click_x, click_y = interactor.GetEventPosition()
        renderer = self.mpr_viewer.viewers[view_name]['renderer']
        world = self._display_to_world(renderer, click_x, click_y)

        # Consume the press so the crosshair/stack interaction stays out of
        # the placement gesture. The abort flag lives on the vtkCommand, not
        # the interactor — fetch it via the stored observer tag and set it so
        # lower-priority observers (the interactor style at 0.0) are skipped
        # for THIS press. The crosshair style also self-guards on
        # current_tool=='arrow' (belt-and-suspenders, since GetCommand abort
        # support varies across VTK builds).
        try:
            entry = self._arrow_observers.get(view_name)
            if entry is not None:
                cmd = interactor_obj.GetCommand(entry[1])
                if cmd is not None:
                    cmd.SetAbortFlag(1)
        except Exception:
            pass

        tail = self._arrow_pending_tail.get(view_name)
        if tail is None:
            self._arrow_pending_tail[view_name] = world
            logger.debug(f"arrow tail anchored on {view_name} at {world}")
            return

        self._arrow_pending_tail[view_name] = None
        self._clear_arrow_preview(view_name)
        self._create_arrow_actor(view_name, tail, world)
        # Single-use: one arrow drawn → return to the MPR default mouse mode.
        self._fire_single_use_auto_exit(view_name, 'arrow')

    def _make_arrow_leader(self, p1_world, p2_world):
        """Build a filled-head leader (the arrow visual) between two WORLD points.

        Shared by the live preview and the final placed arrow so they look
        identical. Honors the saved Tools-Settings arrow style (capped body width)."""
        color = (0.0, 0.9, 0.0)
        width = 2.0
        try:
            from PacsClient.pacs.patient_tab.utils.tools_settings import get_arrow_style
            st = get_arrow_style()
            color = tuple(st.color)[:3]
            width = max(1.0, min(float(st.line_width), 2.0))
        except Exception:
            pass

        leader = vtk.vtkLeaderActor2D()
        leader.GetPositionCoordinate().SetCoordinateSystemToWorld()
        leader.GetPositionCoordinate().SetValue(*p1_world)
        leader.GetPosition2Coordinate().SetCoordinateSystemToWorld()
        leader.GetPosition2Coordinate().SetValue(*p2_world)
        leader.SetArrowStyleToFilled()
        leader.SetArrowPlacementToPoint2()
        # vtkLeaderActor2D sizes the head as a FRACTION of the leader (line) length,
        # so the old 0.06 length + default (~0.02) width drew a thin sliver behind
        # the body. Enlarge BOTH so the filled triangular head reads clearly and is
        # proportionate to the line. (ArrowLength = head length, ArrowWidth = base.)
        leader.SetArrowLength(0.15)
        leader.SetArrowWidth(0.12)
        leader.GetProperty().SetColor(*color)
        leader.GetProperty().SetLineWidth(width)
        return leader

    def _handle_arrow_move(self, view_name):
        """Live rubber-band: while the arrow tail is anchored, draw/update a preview
        arrow from the tail to the cursor (FAST-like). No-op until the first click.

        Smoothness: a 2px display-move threshold drops sub-pixel jitter so the pane
        only re-composites on real motion. The reslice output is cached (the slice is
        unchanged during placement), so each update is a cheap re-composite, not a
        re-reslice — keeping the preview smooth even on a large CBCT."""
        if not _MPR_ANNOTATION_SMOOTH or self.current_tool != 'arrow':
            return
        tail = self._arrow_pending_tail.get(view_name)
        if tail is None:
            return
        view = self.mpr_viewer.viewers.get(view_name)
        if not view:
            return
        interactor = view['widget'].GetRenderWindow().GetInteractor()
        x, y = interactor.GetEventPosition()
        last = self._arrow_preview_last_xy.get(view_name)
        if last is not None and abs(x - last[0]) < 2 and abs(y - last[1]) < 2:
            return  # throttle: ignore sub-2px jitter (keeps it smooth)
        self._arrow_preview_last_xy[view_name] = (x, y)
        renderer = view['renderer']
        head = self._display_to_world(renderer, x, y)
        preview = self._arrow_preview_actor.get(view_name)
        if preview is None:
            preview = self._make_arrow_leader(tail, head)
            renderer.AddActor2D(preview)
            self._arrow_preview_actor[view_name] = preview
        else:
            preview.GetPositionCoordinate().SetValue(*tail)
            preview.GetPosition2Coordinate().SetValue(*head)
        try:
            renderer.GetRenderWindow().Render()
        except Exception:
            pass

    def _clear_arrow_preview(self, view_name=None):
        """Remove the transient preview arrow(s) (the final placed arrow is kept)."""
        views = [view_name] if view_name else list(self._arrow_preview_actor.keys())
        for vn in views:
            preview = self._arrow_preview_actor.pop(vn, None)
            self._arrow_preview_last_xy.pop(vn, None)
            if preview is None:
                continue
            try:
                renderer = self.mpr_viewer.viewers[vn]['renderer']
                renderer.RemoveActor2D(preview)
            except Exception:
                pass

    def _create_arrow_actor(self, view_name, p1_world, p2_world):
        """Filled-head arrow between two WORLD points (camera-stable)."""
        renderer = self.mpr_viewer.viewers[view_name]['renderer']
        leader = self._make_arrow_leader(p1_world, p2_world)

        renderer.AddActor2D(leader)
        self.active_tools[view_name].setdefault('arrow', []).append({
            'actor': leader,
            'renderer': renderer,
            'p1': tuple(p1_world),
            'p2': tuple(p2_world),
        })
        # Instant final render (FAST-like) so the arrow appears the moment the 2nd
        # click lands; legacy path keeps the batched request.
        if _MPR_ANNOTATION_SMOOTH:
            try:
                self.mpr_viewer._render_immediately(view_name)
            except Exception:
                self.mpr_viewer._request_render(view_name)
        else:
            self.mpr_viewer._request_render(view_name)
        logger.info(f"✓ Arrow placed on {view_name}")

    def _deactivate_arrow_placement(self):
        """Remove click + preview-move observers, drop any live preview, and clear
        pending state (placed arrows stay)."""
        for view_name, (interactor, tag) in list(self._arrow_observers.items()):
            try:
                interactor.RemoveObserver(tag)
            except Exception:
                pass
        for view_name, (interactor, tag) in list(self._arrow_move_observers.items()):
            try:
                interactor.RemoveObserver(tag)
            except Exception:
                pass
        self._arrow_observers.clear()
        self._arrow_move_observers.clear()
        self._clear_arrow_preview()
        self._arrow_pending_tail.clear()

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

        # Arrow placement observers must not outlive the tool toggle.
        self._deactivate_arrow_placement()
        # Forget any tracked (unplaced) placement widgets from the last activation.
        self._placement_widgets.clear()

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
            tools = ['ruler', 'angle', 'caption', 'arrow']

        count = 0
        dirty_views = set()
        for vn in views:
            if vn not in self.active_tools:
                continue

            for tool in tools:
                if tool not in self.active_tools[vn]:
                    continue

                for widget in self.active_tools[vn][tool]:
                    try:
                        # Drop the slice-visibility cache entry for this item.
                        self._annotation_visible_cache.pop(id(widget), None)
                        if tool == 'arrow':
                            # Arrow entries are dicts holding a raw
                            # vtkLeaderActor2D, not a VTK widget — remove the
                            # actor from its renderer instead of .Off().
                            entry = widget
                            rend = entry.get('renderer')
                            actor = entry.get('actor')
                            if rend is not None and actor is not None:
                                rend.RemoveActor2D(actor)
                            dirty_views.add(vn)
                        else:
                            widget.Off()
                        count += 1
                    except Exception as e:
                        logger.error(f"Error removing widget: {e}")

                self.active_tools[vn][tool].clear()

        # Drop any in-flight arrow rubber-band preview too (edge case: clearing
        # while an arrow tail is anchored).
        self._clear_arrow_preview()

        # Raw actors don't trigger their own render — repaint the panes we
        # pulled arrows from.
        for vn in dirty_views:
            try:
                self.mpr_viewer._request_render(vn)
            except Exception:
                pass

        logger.info(f"✓ Cleared {count} measurements")
        return count

    def delete_measurement_at(self, view_name, display_pos, renderer, threshold=10):
        """
        Delete the closest measurement widget to a display position.
        Args:
            view_name: 'axial', 'sagittal', or 'coronal'
            display_pos: (x, y) tuple in display coordinates
            renderer: vtkRenderer for coordinate conversion
            threshold: max pixel distance to consider a hit
        Returns:
            True if a widget was removed, False otherwise
        """
        if view_name not in self.active_tools:
            return False

        if renderer is None:
            return False

        closest = None  # (tool_type, widget, distance)
        min_distance = float(threshold)

        for tool_type in ['ruler', 'angle', 'caption']:
            widgets = self.active_tools[view_name].get(tool_type, [])
            for widget in widgets:
                try:
                    distance = self._get_widget_distance(tool_type, widget, display_pos, renderer)
                except Exception:
                    distance = None
                if distance is None:
                    continue
                if distance <= min_distance:
                    min_distance = distance
                    closest = (tool_type, widget, distance)

        if not closest:
            return False

        tool_type, widget, _ = closest
        try:
            widget.Off()
        except Exception:
            pass

        try:
            self.active_tools[view_name][tool_type].remove(widget)
        except ValueError:
            pass

        logger.info(f"✓ Deleted {tool_type} measurement on {view_name}")
        return True

    def is_near_measurement(self, view_name, display_pos, renderer, threshold=12):
        """True when ``display_pos`` is within ``threshold`` px of any
        measurement annotation (line body, rays or caption anchor) on a view.

        Non-destructive twin of ``delete_measurement_at`` — used by the
        crosshair interactor style to YIELD: when the cursor is on an
        annotation, the style must not start a crosshair/stack/center drag,
        so the annotation widgets own the interaction (the reported
        "unstable drag" was the crosshair line-grab stealing body clicks).
        """
        if view_name not in self.active_tools or renderer is None:
            return False
        for tool_type in ['ruler', 'angle', 'caption']:
            for widget in self.active_tools[view_name].get(tool_type, []):
                try:
                    distance = self._get_widget_distance(
                        tool_type, widget, display_pos, renderer
                    )
                except Exception:
                    distance = None
                if distance is not None and distance <= float(threshold):
                    return True
        return False

    def _get_widget_distance(self, tool_type, widget, display_pos, renderer):
        if tool_type == 'ruler':
            rep = widget.GetRepresentation()
            p1 = [0, 0, 0]
            p2 = [0, 0, 0]
            rep.GetPoint1WorldPosition(p1)
            rep.GetPoint2WorldPosition(p2)
            d1 = self._world_to_display(renderer, p1)
            d2 = self._world_to_display(renderer, p2)
            return self._point_to_line_distance(display_pos, d1, d2)

        if tool_type == 'angle':
            rep = widget.GetRepresentation()
            p1 = [0, 0, 0]
            p2 = [0, 0, 0]
            p3 = [0, 0, 0]
            rep.GetPoint1WorldPosition(p1)
            rep.GetCenterWorldPosition(p2)
            rep.GetPoint2WorldPosition(p3)
            d1 = self._world_to_display(renderer, p1)
            d2 = self._world_to_display(renderer, p2)
            d3 = self._world_to_display(renderer, p3)
            dist1 = self._point_to_line_distance(display_pos, d1, d2)
            dist2 = self._point_to_line_distance(display_pos, d2, d3)
            return min(dist1, dist2)

        if tool_type == 'caption':
            rep = widget.GetRepresentation()
            anchor = [0, 0, 0]
            try:
                rep.GetAnchorPosition(anchor)
            except Exception:
                return None
            d1 = self._world_to_display(renderer, anchor)
            return self._point_to_point_distance(display_pos, d1)

        return None

    def _world_to_display(self, renderer, world_pos):
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
        coord.SetValue(world_pos[0], world_pos[1], world_pos[2])
        return coord.GetComputedDisplayValue(renderer)

    def _point_to_line_distance(self, point, line_start, line_end):
        import math
        dx = line_end[0] - line_start[0]
        dy = line_end[1] - line_start[1]
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return math.sqrt((point[0] - line_start[0]) ** 2 + (point[1] - line_start[1]) ** 2)
        t = ((point[0] - line_start[0]) * dx + (point[1] - line_start[1]) * dy) / length_sq
        t = max(0.0, min(1.0, t))
        closest_x = line_start[0] + t * dx
        closest_y = line_start[1] + t * dy
        return math.sqrt((point[0] - closest_x) ** 2 + (point[1] - closest_y) ** 2)

    def _point_to_point_distance(self, p1, p2):
        import math
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)
    
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

