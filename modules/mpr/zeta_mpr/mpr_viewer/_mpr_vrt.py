"""
MPR VRT (Volume Rendering) Mixin — 3D preset menu, appearance interaction.

Extracted from standard_mpr_viewer.py (Phase 5A refactoring).
"""
import logging

from PySide6.QtCore import Qt, QPoint

logger = logging.getLogger(__name__)


class _MprVrtMixin:
    """VRT preset menu, appearance delta, and all VRT mouse event handlers."""

    def _show_vrt_preset_menu(self, widget, pos):
        """Show a polished right-click preset menu for the 3D viewport.

        Presets are grouped by category with section headers, styled to
        match the application's dark theme (``_variables.scss`` palette).
        """
        try:
            view_name = self._vtk_widget_to_view.get(widget)
            if view_name != '3d':
                return

            self.stop_auto_rotation()

            from PySide6.QtWidgets import (
                QMenu, QWidgetAction, QWidget, QVBoxLayout, QHBoxLayout,
                QLabel, QScrollArea, QFrame, QPushButton, QGraphicsDropShadowEffect,
            )
            from PySide6.QtGui import QFont, QColor

            # ── Collect presets grouped by category ──────────────────────
            preset_names = self.preset_manager.get_all_preset_names()
            if not preset_names:
                return

            # Map of category enum → display label & icon
            _CAT_META = {
                'CT Bone':         ('🦴', 'CT Bone'),
                'CT Soft Tissue':  ('🫀', 'CT Soft Tissue'),
                'CT Lung':         ('🫁', 'CT Lung'),
                'CT Vessel':       ('🩸', 'CT Vessel'),
                'CT Cardiac':      ('❤️', 'CT Cardiac'),
                'CT Contrast':     ('💉', 'CT Contrast'),
                'MRI Brain':       ('🧠', 'MRI Brain'),
                'MRI Angiography': ('🔬', 'MRI Angiography'),
                'Technique':       ('⚙️', 'Rendering Technique'),
            }

            from collections import OrderedDict
            grouped: OrderedDict[str, list] = OrderedDict()
            for name in preset_names:
                info = self.preset_manager.get_preset_info(name) if hasattr(self.preset_manager, 'get_preset_info') else None
                cat_val = info.get('category', 'Other') if isinstance(info, dict) else 'Other'
                grouped.setdefault(cat_val, []).append(name)

            # ── Build the floating panel ─────────────────────────────────
            menu = QMenu(self)
            menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            menu.setAttribute(Qt.WA_TranslucentBackground, True)
            menu.setStyleSheet("QMenu { background: transparent; border: none; padding: 0; margin: 0; }")

            # Container widget
            container = QWidget()
            container.setObjectName("vrtPresetPanel")
            container.setStyleSheet("""
                #vrtPresetPanel {
                    background: #1a1e21;
                    border: 1px solid #2d3235;
                    border-radius: 10px;
                }
            """)
            shadow = QGraphicsDropShadowEffect(container)
            shadow.setBlurRadius(24)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(0, 0, 0, 160))
            container.setGraphicsEffect(shadow)

            root_layout = QVBoxLayout(container)
            root_layout.setContentsMargins(10, 10, 10, 10)
            root_layout.setSpacing(0)

            # ── Title bar ────────────────────────────────────────────────
            title = QLabel("  3D Volume Presets")
            title.setStyleSheet("""
                QLabel {
                    color: #fefefe;
                    font-size: 13px;
                    font-weight: 600;
                    padding: 6px 4px 8px 4px;
                    background: transparent;
                }
            """)
            root_layout.addWidget(title)

            # Thin separator
            sep = QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet("background: #2d3235;")
            root_layout.addWidget(sep)

            # ── Scrollable preset area ───────────────────────────────────
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setStyleSheet("""
                QScrollArea {
                    background: transparent;
                    border: none;
                }
                QScrollBar:vertical {
                    background: #14181a;
                    width: 6px;
                    border-radius: 3px;
                    margin: 2px 0;
                }
                QScrollBar::handle:vertical {
                    background: #3a3f44;
                    border-radius: 3px;
                    min-height: 24px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #525a60;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0;
                }
            """)

            inner = QWidget()
            inner.setStyleSheet("background: transparent;")
            inner_layout = QVBoxLayout(inner)
            inner_layout.setContentsMargins(2, 6, 2, 4)
            inner_layout.setSpacing(2)

            # ── Category sections ────────────────────────────────────────
            _ITEM_STYLE = """
                QPushButton {{
                    text-align: left;
                    padding: 7px 14px 7px 28px;
                    border: none;
                    border-radius: 6px;
                    font-size: 12px;
                    color: {fg};
                    background: {bg};
                    font-weight: {weight};
                }}
                QPushButton:hover {{
                    background: #2a2f33;
                    color: #fefefe;
                }}
                QPushButton:pressed {{
                    background: #fba43b;
                    color: #0f1214;
                }}
            """

            for cat_val, names in grouped.items():
                icon, label = _CAT_META.get(cat_val, ('📁', cat_val))
                # Section header
                header = QLabel(f"  {icon}  {label}")
                header.setStyleSheet("""
                    QLabel {
                        color: #989898;
                        font-size: 11px;
                        font-weight: 600;
                        padding: 8px 4px 3px 6px;
                        background: transparent;
                        letter-spacing: 0.5px;
                    }
                """)
                inner_layout.addWidget(header)

                for preset_name in names:
                    is_active = (preset_name == getattr(self, 'current_3d_preset', None))
                    btn = QPushButton(preset_name)
                    btn.setCursor(Qt.PointingHandCursor)
                    fg = "#fba43b" if is_active else "#CBCBCB"
                    bg = "#21272a" if is_active else "transparent"
                    weight = "600" if is_active else "400"
                    btn.setStyleSheet(_ITEM_STYLE.format(fg=fg, bg=bg, weight=weight))
                    btn.setFixedHeight(32)
                    btn.clicked.connect(
                        lambda checked=False, n=preset_name: (self._apply_vrt_preset(n), menu.close())
                    )
                    inner_layout.addWidget(btn)

            inner_layout.addStretch()
            scroll.setWidget(inner)

            # Size the scroll area
            max_h = min(self.height() - 40, 480)
            scroll.setFixedWidth(240)
            scroll.setMaximumHeight(max_h)
            root_layout.addWidget(scroll)

            # ── Embed in QMenu ───────────────────────────────────────────
            action = QWidgetAction(menu)
            action.setDefaultWidget(container)
            menu.addAction(action)

            global_pos = widget.mapToGlobal(pos)
            menu.exec(global_pos)
        except Exception as e:
            logger.error(f"Error showing VRT preset menu: {e}", exc_info=True)

    def _show_vrt_preset_menu_from_interactor(self, widget):
        """Show VRT preset menu from VTK right-click event."""
        try:
            interactor = widget.GetRenderWindow().GetInteractor()
            x, y = interactor.GetEventPosition()
            # VTK display coords origin is bottom-left; Qt is top-left
            qt_pos = QPoint(int(x), int(widget.height() - y))
            self._show_vrt_preset_menu(widget, qt_pos)
        except Exception as e:
            logger.error(f"Error handling VRT right-click: {e}", exc_info=True)

    def _apply_vrt_preset(self, preset_name):
        """Apply a volume rendering preset to the 3D view."""
        if '3d' not in self.viewers:
            return

        volume_property = self.viewers['3d']['property']
        self._apply_volume_preset(volume_property, preset_name)
        self.current_3d_preset = preset_name

        if hasattr(self, 'vol_combo'):
            try:
                self.vol_combo.setCurrentText(preset_name)
            except Exception:
                pass

        renderer = self.viewers['3d']['renderer']
        renderer.GetRenderWindow().Render()
        self._reset_vrt_rmb_state()

    def _reset_vrt_rmb_state(self):
        state = self._vrt_mouse_state
        state['rmb_down'] = False
        state['rmb_dragging'] = False
        state['rmb_start_pos'] = None
        state['opacity_points'] = None
        state['lighting'] = None
        if not state.get('lmb_down') and not state.get('mmb_down'):
            state['last_pos'] = None
        try:
            if '3d' in self.viewers:
                style = self.viewers['3d'].get('style')
                if style and hasattr(style, 'reset_interaction_state'):
                    style.reset_interaction_state()
        except Exception:
            pass

    def _capture_vrt_baseline(self):
        if '3d' not in self.viewers:
            return
        volume_property = self.viewers['3d']['property']
        opacity = volume_property.GetScalarOpacity()
        points = []
        size = opacity.GetSize()
        for i in range(size):
            vals = [0.0, 0.0, 0.0, 0.0]
            opacity.GetNodeValue(i, vals)
            points.append(tuple(vals))
        self._vrt_mouse_state['opacity_points'] = points
        self._vrt_mouse_state['lighting'] = (
            volume_property.GetAmbient(),
            volume_property.GetDiffuse(),
            volume_property.GetSpecular()
        )

    def _apply_vrt_appearance_delta(self, dx, dy):
        if '3d' not in self.viewers:
            return
        state = self._vrt_mouse_state
        if not state.get('opacity_points'):
            self._capture_vrt_baseline()

        points = state.get('opacity_points') or []
        if not points:
            return

        volume_property = self.viewers['3d']['property']
        opacity = volume_property.GetScalarOpacity()
        opacity.RemoveAllPoints()

        scale = max(0.1, min(3.0, 1.0 + dx * 0.005))
        for x, y, mid, sharp in points:
            new_y = max(0.0, min(1.0, y * scale))
            opacity.AddPoint(x, new_y, mid, sharp)

        ambient, diffuse, specular = state.get('lighting', (0.2, 0.7, 0.3))
        delta = -dy * 0.002
        volume_property.SetAmbient(max(0.0, min(1.0, ambient + delta)))
        volume_property.SetDiffuse(max(0.0, min(1.0, diffuse + delta)))
        volume_property.SetSpecular(max(0.0, min(1.0, specular + delta)))

        renderer = self.viewers['3d']['renderer']
        renderer.GetRenderWindow().Render()

    # ── VRT mouse event handlers (called from eventFilter / interactor) ──

    def _on_vrt_left_press(self, widget):
        if '3d' not in self.viewers:
            return
        state = self._vrt_mouse_state
        interactor = widget.GetRenderWindow().GetInteractor()
        style = self.viewers['3d'].get('style')

        state['lmb_down'] = True
        if state['rmb_down']:
            if style and not state['pan_active']:
                style.OnLeftButtonUp()
                style.OnMiddleButtonDown()
                state['pan_active'] = True
            interactor.AbortFlagOn()
            return

        if style:
            style.OnLeftButtonDown()

    def _on_vrt_left_release(self, widget):
        if '3d' not in self.viewers:
            return
        state = self._vrt_mouse_state
        interactor = widget.GetRenderWindow().GetInteractor()
        style = self.viewers['3d'].get('style')

        state['lmb_down'] = False
        if state['pan_active']:
            if style:
                style.OnMiddleButtonUp()
            state['pan_active'] = False
            if state['rmb_down'] and style:
                state['rmb_start_pos'] = interactor.GetEventPosition()
                state['last_pos'] = state['rmb_start_pos']
                state['rmb_dragging'] = False
                self._capture_vrt_baseline()
            return

        if style:
            style.OnLeftButtonUp()

    def _on_vrt_right_press(self, widget):
        if '3d' not in self.viewers:
            return
        state = self._vrt_mouse_state
        interactor = widget.GetRenderWindow().GetInteractor()
        style = self.viewers['3d'].get('style')

        state['rmb_down'] = True
        state['rmb_dragging'] = False
        pos = interactor.GetEventPosition()
        state['rmb_start_pos'] = pos
        state['last_pos'] = pos
        self._capture_vrt_baseline()

        if state['lmb_down'] and style and not state['pan_active']:
            style.OnLeftButtonUp()
            style.OnMiddleButtonDown()
            state['pan_active'] = True
        interactor.AbortFlagOn()

    def _on_vrt_right_release(self, widget):
        if '3d' not in self.viewers:
            return
        state = self._vrt_mouse_state
        interactor = widget.GetRenderWindow().GetInteractor()
        style = self.viewers['3d'].get('style')

        if state['pan_active']:
            if style:
                style.OnMiddleButtonUp()
            state['pan_active'] = False
            if state['lmb_down'] and style:
                style.OnLeftButtonDown()

        rmb_dragging = state.get('rmb_dragging', False)
        state['rmb_down'] = False
        state['rmb_dragging'] = False
        state['rmb_start_pos'] = None
        state['opacity_points'] = None
        state['lighting'] = None

        if not rmb_dragging:
            self._show_vrt_preset_menu_from_interactor(widget)

        interactor.AbortFlagOn()

    def _on_vrt_middle_press(self, widget):
        if '3d' not in self.viewers:
            return
        state = self._vrt_mouse_state
        interactor = widget.GetRenderWindow().GetInteractor()
        state['mmb_down'] = True
        state['last_pos'] = interactor.GetEventPosition()
        interactor.AbortFlagOn()

    def _on_vrt_middle_release(self, widget):
        if '3d' not in self.viewers:
            return
        state = self._vrt_mouse_state
        interactor = widget.GetRenderWindow().GetInteractor()
        state['mmb_down'] = False
        if not state.get('lmb_down') and not state.get('rmb_down'):
            state['last_pos'] = None
        interactor.AbortFlagOn()

    def _on_vrt_mouse_move(self, widget):
        if '3d' not in self.viewers:
            return
        state = self._vrt_mouse_state
        interactor = widget.GetRenderWindow().GetInteractor()
        style = self.viewers['3d'].get('style')
        pos = interactor.GetEventPosition()

        if state['pan_active']:
            if style:
                style.OnMouseMove()
            return

        if state['mmb_down']:
            if state['last_pos'] is None:
                state['last_pos'] = pos
                return
            dy = pos[1] - state['last_pos'][1]
            camera = self.viewers['3d']['renderer'].GetActiveCamera()
            zoom_factor = 1.0
            zoom_sensitivity = 0.005
            if dy > 0:
                zoom_factor = 1 / (1 + abs(dy) * zoom_sensitivity)
            elif dy < 0:
                zoom_factor = 1 + abs(dy) * zoom_sensitivity
            camera.Dolly(zoom_factor)
            self.viewers['3d']['renderer'].ResetCameraClippingRange()
            self.viewers['3d']['renderer'].GetRenderWindow().Render()
            state['last_pos'] = pos
            return

        if state['rmb_down'] and not state['pan_active']:
            if state['rmb_start_pos'] is None:
                state['rmb_start_pos'] = pos
                state['last_pos'] = pos
                return
            dx = pos[0] - state['rmb_start_pos'][0]
            dy = pos[1] - state['rmb_start_pos'][1]
            if not state['rmb_dragging']:
                if abs(dx) >= 4 or abs(dy) >= 4:
                    state['rmb_dragging'] = True
            if state['rmb_dragging']:
                self._apply_vrt_appearance_delta(dx, dy)
            return

        if state['lmb_down'] and style:
            style.OnMouseMove()
