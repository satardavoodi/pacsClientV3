import math
from datetime import datetime
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer, QRectF, Signal, QSize
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from PacsClient.utils import IMAGES_LOGIN_PATH


class SecretaryOrbButton(QToolButton):
    activeChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("EchoMind Secretary microphone trigger")
        self.setAutoRaise(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            "QToolButton { background: transparent; border: none; }"
            "QToolButton:pressed { background: transparent; border: none; }"
        )

        self._active = False
        self._frame_index = 0
        self._cached_side = -1
        self._inactive_frame = QPixmap()
        self._active_frames = []
        self._texture = self._load_texture()
        self._texture_focus = self._detect_texture_focus(self._texture)
        self._texture_cache = {}

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(70)
        self._frame_timer.timeout.connect(self._advance_frame)

        self.toggled.connect(self._on_toggled)

    def sizeHint(self):
        return QSize(248, 248)

    def minimumSizeHint(self):
        return QSize(180, 180)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return max(180, width)

    def set_active(self, active):
        active = bool(active)
        if self.isChecked() != active:
            self.setChecked(active)
            return
        self._apply_state(active)

    def is_active(self):
        return self._active

    def get_phase(self):
        total_frames = len(self._active_frames) if self._active_frames else 72
        if total_frames <= 0:
            return 0.0
        return (2.0 * math.pi * self._frame_index) / float(total_frames)

    def _on_toggled(self, checked):
        self._apply_state(bool(checked))
        self.activeChanged.emit(self._active)

    def _apply_state(self, active):
        self._active = active
        if active:
            self._frame_timer.start()
        else:
            self._frame_timer.stop()
            self._frame_index = 0
        self.update()

    def _advance_frame(self):
        if not self._active or not self._active_frames:
            return
        self._frame_index = (self._frame_index + 1) % len(self._active_frames)
        self.update()
        parent = self.parentWidget()
        if parent is not None:
            parent.update()

    def _load_texture(self):
        texture_path = Path(IMAGES_LOGIN_PATH) / "Echo-Mind2.png"
        pixmap = QPixmap(str(texture_path))
        if pixmap.isNull():
            return QPixmap()
        return pixmap

    def _detect_texture_focus(self, pixmap):
        if pixmap.isNull():
            return 0.62, 0.50

        img = pixmap.toImage().convertToFormat(QImage.Format_RGB32)
        width = img.width()
        height = img.height()
        if width <= 1 or height <= 1:
            return 0.62, 0.50

        step = max(1, min(width, height) // 380)
        right_start = int(width * 0.24)
        col_weights = [0.0] * width
        total_weight = 0.0

        for y in range(0, height, step):
            for x in range(right_start, width, step):
                c = QColor(img.pixel(x, y))
                r = c.red()
                g = c.green()
                b = c.blue()

                cyan_like = (b > 92 and g > 76 and b > (r + 14) and g > (r + 8))
                bright_white = (r > 208 and g > 208 and b > 208)
                if not (cyan_like or bright_white):
                    continue

                luminance = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
                cyan_bias = max(0.0, (b - r) * 1.2) + max(0.0, (g - r) * 0.9)
                weight = max(0.0, (luminance * 0.35) + cyan_bias)
                if weight <= 0.0:
                    continue

                col_weights[x] += weight
                total_weight += weight

        if total_weight <= 0.0:
            return 0.62, 0.50

        window = max(96, int(width * 0.30))
        if window >= width:
            window = max(32, width - 1)

        current_sum = sum(col_weights[:window])
        best_sum = current_sum
        best_start = 0
        for start in range(1, width - window):
            current_sum += col_weights[start + window - 1] - col_weights[start - 1]
            if current_sum > best_sum:
                best_sum = current_sum
                best_start = start

        band_start = best_start
        band_end = min(width, best_start + window)
        band_weight = 0.0
        weighted_x = 0.0
        for x in range(band_start, band_end):
            w = col_weights[x]
            band_weight += w
            weighted_x += x * w

        if band_weight <= 0.0:
            return 0.62, 0.50

        center_x = weighted_x / band_weight
        x_ratio = max(0.0, min(1.0, center_x / float(width)))
        return x_ratio, 0.50

    def _build_texture(self, side):
        if self._texture.isNull():
            return QPixmap()

        cached = self._texture_cache.get(side)
        if cached is not None and not cached.isNull():
            return cached

        src = self._texture
        src_w = src.width()
        src_h = src.height()
        base_crop = float(min(src_w, src_h))

        focus_x, _ = self._texture_focus
        center_x = max(0.0, min(float(src_w), float(src_w) * focus_x))

        # Keep the visual center of "EchoMind" text centered on the orb as much as possible.
        max_crop_for_focus = max(1.0, 2.0 * min(center_x, float(src_w) - center_x))
        crop = min(base_crop * 0.985, max_crop_for_focus)

        x0 = center_x - (crop * 0.5)
        y0 = ((float(src_h) - crop) * 0.5) + (crop * 0.10)
        max_x = max(0.0, float(src_w) - crop)
        max_y = max(0.0, float(src_h) - crop)
        x0 = max(0.0, min(max_x, x0))
        y0 = max(0.0, min(max_y, y0))

        crop_i = max(1, int(round(crop)))
        x0_i = int(round(x0))
        y0_i = int(round(y0))
        square = src.copy(x0_i, y0_i, crop_i, crop_i)
        scaled = square.scaled(side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self._texture_cache[side] = scaled
        return scaled

    def _rebuild_frames(self):
        side = max(160, min(self.width(), self.height()))
        if side == self._cached_side:
            return

        self._cached_side = side
        self._inactive_frame = self._render_frame(side, active=False, phase=0.0)

        frame_count = 72
        self._active_frames = [
            self._render_frame(
                side,
                active=True,
                phase=(2.0 * math.pi * idx) / float(frame_count),
            )
            for idx in range(frame_count)
        ]
        self._frame_index = 0

    def _secretary_icon(self, size, active):
        color = "#dcf8ff" if active else "#7f91a8"
        for icon_name in ("fa5s.user-tie", "fa5s.robot", "fa5s.microphone"):
            try:
                return qta.icon(icon_name, color=color).pixmap(size, size)
            except Exception:
                continue
        fallback = QPixmap(size, size)
        fallback.fill(Qt.transparent)
        return fallback

    def _draw_base_orb(self, painter, orb_rect, active):
        circle = QPainterPath()
        circle.addEllipse(orb_rect)

        painter.save()
        painter.setClipPath(circle)

        texture_size = int(orb_rect.width())
        texture = self._build_texture(texture_size)
        if not texture.isNull():
            painter.setOpacity(0.92 if active else 0.34)
            painter.drawPixmap(orb_rect.toRect(), texture)
            painter.setOpacity(1.0)
        else:
            fallback = QLinearGradient(orb_rect.topLeft(), orb_rect.bottomRight())
            fallback.setColorAt(0.0, QColor("#1f3347"))
            fallback.setColorAt(1.0, QColor("#0f1419"))
            painter.fillRect(orb_rect, fallback)

        light = QRadialGradient(
            orb_rect.left() + orb_rect.width() * 0.33,
            orb_rect.top() + orb_rect.height() * 0.26,
            orb_rect.width() * 0.78,
        )
        light.setColorAt(0.0, QColor(255, 255, 255, 84 if active else 36))
        light.setColorAt(0.45, QColor(121, 218, 255, 48 if active else 12))
        light.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(orb_rect, light)

        depth = QRadialGradient(
            orb_rect.center().x(),
            orb_rect.center().y() + orb_rect.height() * 0.36,
            orb_rect.width() * 0.75,
        )
        depth.setColorAt(0.0, QColor(11, 16, 22, 0))
        depth.setColorAt(1.0, QColor(11, 16, 22, 128 if active else 168))
        painter.fillRect(orb_rect, depth)

        # Remove source text artifacts from the original banner and keep mascot focus.
        text_mask = QLinearGradient(orb_rect.topLeft(), orb_rect.bottomLeft())
        text_mask.setColorAt(0.00, QColor(8, 13, 20, 0))
        text_mask.setColorAt(0.52, QColor(8, 13, 20, 0))
        text_mask.setColorAt(0.70, QColor(8, 13, 20, 110 if active else 128))
        text_mask.setColorAt(1.00, QColor(8, 13, 20, 204 if active else 218))
        painter.fillRect(orb_rect, text_mask)

        painter.restore()

    def _heartbeat_strength(self, phase):
        # Slow breathing-like pulse synced with wave cycle.
        beat = 0.5 - (0.5 * math.cos(phase))
        return max(0.0, min(1.0, beat ** 1.25))

    def _render_frame(self, side, active, phase):
        pixmap = QPixmap(side, side)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        main_rect = QRectF(2.0, 2.0, side - 4.0, side - 4.0)
        static_orb_rect = main_rect.adjusted(14.0, 14.0, -14.0, -14.0)
        beat_strength = self._heartbeat_strength(phase) if active else 0.0
        pulse_scale = 1.0 + (0.014 * beat_strength)
        pulse_orb_w = static_orb_rect.width() * pulse_scale
        pulse_orb_h = static_orb_rect.height() * pulse_scale
        pulse_orb_rect = QRectF(
            static_orb_rect.center().x() - (pulse_orb_w * 0.5),
            static_orb_rect.center().y() - (pulse_orb_h * 0.5),
            pulse_orb_w,
            pulse_orb_h,
        )
        center = static_orb_rect.center()

        # Keep banner/background fully static inside the circle.
        self._draw_base_orb(painter, static_orb_rect, active)

        border = QPen(QColor(101, 226, 255, 156 if active else 106), 1.85)
        painter.setPen(border)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(pulse_orb_rect.adjusted(2.0, 2.0, -2.0, -2.0))

        if active:
            pulse_ring = QPen(QColor(116, 234, 255, int(16 + (28 * beat_strength))), 1.25)
            painter.setPen(pulse_ring)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(pulse_orb_rect.adjusted(-5.0, -5.0, 5.0, 5.0))

        icon_size = int(static_orb_rect.width() * 0.28)
        icon = self._secretary_icon(icon_size, active)
        icon_x = int(center.x() - (icon_size * 0.5))
        icon_y = int(center.y() - (icon_size * 0.5))
        painter.drawPixmap(icon_x, icon_y, icon)

        painter.end()
        return pixmap

    def paintEvent(self, event):
        del event
        self._rebuild_frames()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        side = min(self.width(), self.height())
        x0 = int((self.width() - side) / 2.0)
        y0 = int((self.height() - side) / 2.0)
        target = QRectF(x0, y0, side, side)

        if self._active and self._active_frames:
            frame = self._active_frames[self._frame_index]
        else:
            frame = self._inactive_frame
        if not frame.isNull():
            painter.drawPixmap(target.toRect(), frame)

        painter.end()


class SecretaryLogPopup(QDialog):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.overlay = QFrame(self)
        self.overlay.setStyleSheet("QFrame { background: rgba(7, 12, 18, 178); }")
        root.addWidget(self.overlay)

        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(76, 58, 76, 58)
        overlay_layout.setSpacing(0)

        panel = QFrame(self.overlay)
        panel.setStyleSheet(
            "QFrame {"
            "background: #0b1219;"
            "border: 1px solid #2a4563;"
            "border-radius: 12px;"
            "}"
        )
        overlay_layout.addWidget(panel, 1)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(4)

        title = QLabel("Secretary Conversation")
        title.setStyleSheet(
            "QLabel {"
            "color: #d5e8fb;"
            "font-size: 12px;"
            "font-family: 'Roboto', sans-serif;"
            "font-weight: 700;"
            "}"
        )
        header.addWidget(title)
        header.addStretch(1)

        self.close_btn = QToolButton(panel)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setAutoRaise(True)
        self.close_btn.setIcon(qta.icon("fa5s.times", color="#d5e8fb"))
        self.close_btn.setToolTip("Close popup")
        self.close_btn.setStyleSheet(
            "QToolButton {"
            "background: rgba(32, 52, 73, 0.75);"
            "border: 1px solid #3e6288;"
            "border-radius: 9px;"
            "padding: 3px;"
            "}"
            "QToolButton:hover {"
            "background: rgba(45, 69, 94, 0.90);"
            "}"
        )
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.clicked.connect(self.close)
        header.addWidget(self.close_btn)
        panel_layout.addLayout(header)

        self.log_view = QPlainTextEdit(panel)
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "QPlainTextEdit {"
            "background: rgba(8, 13, 19, 0.96);"
            "border: 1px solid #314b67;"
            "border-radius: 8px;"
            "padding: 8px;"
            "color: #cae8ff;"
            "font-size: 12px;"
            "font-family: 'Consolas', 'Roboto Mono', monospace;"
            "}"
        )
        panel_layout.addWidget(self.log_view, 1)

    def set_log_text(self, text):
        self.log_view.setPlainText(text or "")
        cursor = self.log_view.textCursor()
        cursor.movePosition(cursor.End)
        self.log_view.setTextCursor(cursor)

    def open_over(self, parent_widget):
        host = parent_widget if parent_widget is not None else self.parentWidget()
        if host is not None:
            top_left = host.mapToGlobal(host.rect().topLeft())
            self.setGeometry(top_left.x(), top_left.y(), host.width(), host.height())
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class SecretaryButtonWidget(QWidget):
    listeningToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("secretaryButtonWidget")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(396)
        self._log_box_height = 126
        self._log_popup = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 4, 2, 4)
        main_layout.setSpacing(6)

        self.orb_button = SecretaryOrbButton(self)
        self.orb_button.activeChanged.connect(self._on_active_changed)
        main_layout.addWidget(self.orb_button, 1, Qt.AlignHCenter)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Secretary log: input / output")
        self.log_box.document().setMaximumBlockCount(90)
        self.log_box.setFixedHeight(self._log_box_height)
        self.log_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.log_box.setStyleSheet(
            "QPlainTextEdit {"
            "background: rgba(8, 13, 19, 0.92);"
            "border: 1px solid #2f455d;"
            "border-radius: 8px;"
            "padding: 6px;"
            "padding-top: 8px;"
            "padding-right: 30px;"
            "color: #cce9ff;"
            "font-size: 11px;"
            "font-family: 'Consolas', 'Roboto Mono', monospace;"
            "}"
            "QScrollBar:vertical {"
            "background: transparent;"
            "width: 8px;"
            "margin: 2px;"
            "}"
            "QScrollBar::handle:vertical {"
            "background: #3f5972;"
            "border-radius: 4px;"
            "min-height: 20px;"
            "}"
        )
        main_layout.addWidget(self.log_box)

        self.log_expand_icon = QToolButton(self)
        self.log_expand_icon.setCursor(Qt.PointingHandCursor)
        self.log_expand_icon.setAutoRaise(True)
        self.log_expand_icon.setToolTip("Open log popup")
        self.log_expand_icon.setIcon(self._safe_icon(("fa5s.expand", "fa5s.external-link-alt", "fa5s.search-plus"), "#b5dbff"))
        self.log_expand_icon.setStyleSheet(
            "QToolButton {"
            "background: rgba(24, 40, 56, 0.80);"
            "border: 1px solid #3d607f;"
            "border-radius: 9px;"
            "padding: 2px;"
            "}"
            "QToolButton:hover {"
            "background: rgba(36, 58, 80, 0.94);"
            "border-color: #5c8ec0;"
            "}"
        )
        self.log_expand_icon.setFixedSize(20, 20)
        self.log_expand_icon.clicked.connect(self._toggle_log_popup)
        self.log_expand_icon.raise_()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        panel_rect = QRectF(self.rect())
        panel_grad = QLinearGradient(panel_rect.topLeft(), panel_rect.bottomLeft())
        panel_grad.setColorAt(0.0, QColor(8, 15, 24, 210))
        panel_grad.setColorAt(0.35, QColor(7, 14, 22, 228))
        panel_grad.setColorAt(1.0, QColor(5, 11, 18, 238))
        painter.fillRect(panel_rect, panel_grad)

        if hasattr(self, "orb_button"):
            orb_geo = self.orb_button.geometry()
            halo_center_x = orb_geo.center().x()
            halo_center_y = orb_geo.center().y() + (orb_geo.height() * 0.04)
            if self.orb_button.is_active():
                phase = self.orb_button.get_phase()
                beat = 0.5 - (0.5 * math.cos(phase))
                beat = max(0.0, min(1.0, beat ** 1.25))

                halo_radius = max(panel_rect.width() * 0.95, panel_rect.height() * 0.82)
                halo = QRadialGradient(halo_center_x, halo_center_y, halo_radius)
                halo.setColorAt(0.00, QColor(88, 219, 255, int(72 + (38 * beat))))
                halo.setColorAt(0.40, QColor(63, 178, 232, int(30 + (18 * beat))))
                halo.setColorAt(0.82, QColor(30, 114, 165, int(8 + (6 * beat))))
                halo.setColorAt(1.00, QColor(10, 18, 27, 0))
                painter.setPen(Qt.NoPen)
                painter.setBrush(halo)
                painter.drawEllipse(
                    QRectF(
                        halo_center_x - halo_radius,
                        halo_center_y - halo_radius,
                        halo_radius * 2.0,
                        halo_radius * 2.0,
                    )
                )

        painter.end()

    def _draw_sidebar_waves(self, painter, center_x, center_y, phase, beat_strength, panel_rect, orb_size):
        wave_base = QColor(112, 232, 255)
        orbit_count = 5
        point_count = 240
        # Anchor waves tightly to the circle, then loosen spacing as they move outward.
        core_radius = max(orb_size * 0.54, panel_rect.width() * 0.19)
        inner_gap = max(orb_size * 0.055, 10.0)
        gap_growth = max(orb_size * 0.022, 3.0)
        base_rotation = phase * 0.12

        radius_cursor = core_radius + inner_gap
        for orbit_idx in range(orbit_count):
            if orbit_idx > 0:
                radius_cursor += inner_gap + ((orbit_idx - 1) * gap_growth)

            # Outward propagation lag: inner rings lead, outer rings follow.
            propagation_phase = phase - (orbit_idx * 0.48)
            drive = 0.5 - (0.5 * math.cos(propagation_phase))
            drive = drive ** 1.35

            orbit_radius = radius_cursor + (drive * (3.2 + (orbit_idx * 1.1))) + (beat_strength * (2.0 + (orbit_idx * 0.8)))
            amplitude = (2.6 + (orbit_idx * 1.0)) * (0.75 + (0.45 * drive))
            rotation = base_rotation + (orbit_idx * 0.16)
            alpha_base = 22 + (orbit_idx * 5)
            alpha_anim = 0.72 + (0.28 * (0.5 + (0.5 * math.sin((propagation_phase * 0.9) + (orbit_idx * 0.25)))))
            pen_alpha = int((alpha_base + (12 * drive) + (10 * beat_strength)) * alpha_anim)
            pen_width = 1.00 + (0.56 * (orbit_idx / 4.0))

            path = QPainterPath()
            for point_idx in range(point_count + 1):
                t = (2.0 * math.pi * point_idx) / float(point_count)
                angle = t + rotation
                wave_1 = math.sin((t * 5.0) - (propagation_phase * 0.95))
                wave_2 = math.sin((t * 8.0) + (propagation_phase * 0.55) + (orbit_idx * 0.4))
                radius = orbit_radius + (wave_1 * amplitude) + (wave_2 * amplitude * 0.22)
                x = center_x + (math.cos(angle) * radius)
                y = center_y + (math.sin(angle) * radius)
                if point_idx == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            path.closeSubpath()

            pen = QPen(QColor(wave_base.red(), wave_base.green(), wave_base.blue(), pen_alpha), pen_width)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "log_expand_icon") and hasattr(self, "log_box"):
            icon_x = self.log_box.x() + self.log_box.width() - self.log_expand_icon.width() - 8
            icon_y = self.log_box.y() + 8
            self.log_expand_icon.move(icon_x, icon_y)
            self.log_expand_icon.raise_()

        max_by_width = max(90, self.width() - 8)
        max_by_height = max(90, self.height() - (self._log_box_height + 26))
        diameter = min(340, max_by_width, max_by_height)
        diameter = max(90, int(diameter * 0.80))
        self.orb_button.setFixedSize(diameter, diameter)

    def set_active(self, active):
        self.orb_button.set_active(active)

    def is_active(self):
        return self.orb_button.is_active()

    def append_log(self, role, text):
        ts = datetime.now().strftime("%H:%M:%S")
        role_map = {
            "user": "Input",
            "assistant": "Output",
            "system": "System",
        }
        role_label = role_map.get(str(role).lower(), str(role).title())
        self.log_box.appendPlainText(f"[{ts}] {role_label}: {text}")
        self._sync_popup_log_text()

    def append_input(self, text):
        self.append_log("user", text)

    def append_output(self, text):
        self.append_log("assistant", text)

    def _on_active_changed(self, active):
        if active:
            self.append_log("system", "Secretary is live and listening for a command.")
        else:
            self.append_log("system", "Secretary listening stopped.")
        self.update()
        self.listeningToggled.emit(active)

    def _safe_icon(self, names, color):
        for name in names:
            try:
                return qta.icon(name, color=color)
            except Exception:
                continue
        return qta.icon("fa5s.square", color=color)

    def _sync_popup_log_text(self):
        if self._log_popup is not None and self._log_popup.isVisible():
            self._log_popup.set_log_text(self.log_box.toPlainText())

    def _toggle_log_popup(self):
        if self._log_popup is not None and self._log_popup.isVisible():
            self._log_popup.close()
            return

        if self._log_popup is None:
            self._log_popup = SecretaryLogPopup(self.window())
            self._log_popup.closed.connect(self._on_log_popup_closed)
        self._log_popup.close_btn.setIcon(self._safe_icon(("fa5s.compress", "fa5s.compress-alt", "fa5s.times"), "#d5e8fb"))
        self._log_popup.set_log_text(self.log_box.toPlainText())
        self._log_popup.open_over(self.window())

    def _on_log_popup_closed(self):
        if self._log_popup is not None:
            self._log_popup.hide()
