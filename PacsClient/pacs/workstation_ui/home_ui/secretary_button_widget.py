import math
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer, QRectF, Signal, QSize, QEvent
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QInputDialog,
    QMessageBox,
    QLineEdit,
)

from PacsClient.utils import IMAGES_LOGIN_PATH
from PacsClient.pacs.patient_tab.viewers.secretary_bridge import create_secretary_orchestrator
from EchoMind.api_manager import APIKeyManager, Manage
from EchoMind.ai_chat_api import ApiWorker
from EchoMind.secretary.stt.router import SttRouter
from EchoMind.settings_store import get_secretary_stt_route, load_settings, get_echomind_api_key


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

        # Error-state animation (slower red pulse)
        self._error_mode: bool = False
        self._error_frames: list = []
        self._error_frame_index: int = 0
        self._error_timer = QTimer(self)
        self._error_timer.setInterval(90)
        self._error_timer.timeout.connect(self._advance_error_frame)

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
            # Clear error mode so a fresh activation shows listening colours
            self._error_mode = False
            self._error_timer.stop()
            self._frame_timer.start()
        else:
            self._frame_timer.stop()
            self._frame_index = 0
            if self._error_mode:
                self._error_timer.start()
        self.update()

    def _advance_frame(self):
        if not self._active or not self._active_frames:
            return
        self._frame_index = (self._frame_index + 1) % len(self._active_frames)
        self.update()
        parent = self.parentWidget()
        if parent is not None:
            parent.update()

    def set_error(self, error: bool) -> None:
        """Switch the orb into error visual mode (red slow-pulse) or back to idle."""
        error = bool(error)
        if self._error_mode == error:
            return
        self._error_mode = error
        if error and not self._active:
            self._error_frame_index = 0
            self._error_timer.start()
        else:
            self._error_timer.stop()
            self._error_frame_index = 0
        self.update()

    def _advance_error_frame(self):
        if not self._error_mode or self._active:
            return
        self._error_frame_index = (self._error_frame_index + 1) % max(1, len(self._error_frames))
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
        self._inactive_frame = self._render_frame(side, active=False, phase=0.0, error=False)

        frame_count = 72
        self._active_frames = [
            self._render_frame(
                side,
                active=True,
                phase=(2.0 * math.pi * idx) / float(frame_count),
                error=False,
            )
            for idx in range(frame_count)
        ]
        self._frame_index = 0

        # Error state: 48 frames ≈ 4.3 s slow red pulse
        error_frame_count = 48
        self._error_frames = [
            self._render_frame(
                side,
                active=False,
                phase=(2.0 * math.pi * idx) / float(error_frame_count),
                error=True,
            )
            for idx in range(error_frame_count)
        ]
        self._error_frame_index = 0

    def _secretary_icon(self, size, active, error=False):
        if error:
            color = "#a05548"
        else:
            color = "#dcf8ff" if active else "#7f91a8"
        for icon_name in ("fa5s.user-tie", "fa5s.robot", "fa5s.microphone"):
            try:
                return qta.icon(icon_name, color=color).pixmap(size, size)
            except Exception:
                continue
        fallback = QPixmap(size, size)
        fallback.fill(Qt.transparent)
        return fallback

    def _draw_base_orb(self, painter, orb_rect, active, error=False):
        circle = QPainterPath()
        circle.addEllipse(orb_rect)

        painter.save()
        painter.setClipPath(circle)

        texture_size = int(orb_rect.width())
        texture = self._build_texture(texture_size)
        if not texture.isNull():
            painter.setOpacity(0.92 if active else (0.28 if error else 0.34))
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
        if error:
            light.setColorAt(0.0,  QColor(255, 72, 52, 58))
            light.setColorAt(0.45, QColor(200, 38, 28, 22))
            light.setColorAt(1.0,  QColor(255, 255, 255, 0))
        else:
            light.setColorAt(0.0, QColor(255, 255, 255, 84 if active else 36))
            light.setColorAt(0.45, QColor(121, 218, 255, 48 if active else 12))
            light.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(orb_rect, light)

        depth = QRadialGradient(
            orb_rect.center().x(),
            orb_rect.center().y() + orb_rect.height() * 0.36,
            orb_rect.width() * 0.75,
        )
        if error:
            depth.setColorAt(0.0, QColor(14, 6, 6, 0))
            depth.setColorAt(1.0, QColor(14, 6, 6, 148))
        else:
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

    def _render_frame(self, side, active, phase, error=False):
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
        self._draw_base_orb(painter, static_orb_rect, active, error=error)

        if error:
            border = QPen(QColor(218, 65, 48, 162), 1.85)
        else:
            border = QPen(QColor(101, 226, 255, 156 if active else 106), 1.85)
        painter.setPen(border)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(pulse_orb_rect.adjusted(2.0, 2.0, -2.0, -2.0))

        if active:
            pulse_ring = QPen(QColor(116, 234, 255, int(16 + (28 * beat_strength))), 1.25)
            painter.setPen(pulse_ring)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(pulse_orb_rect.adjusted(-5.0, -5.0, 5.0, 5.0))
        elif error:
            err_beat = self._heartbeat_strength(phase * 0.55)  # slower than normal
            pulse_ring = QPen(QColor(228, 58, 40, int(18 + (32 * err_beat))), 1.25)
            painter.setPen(pulse_ring)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(pulse_orb_rect.adjusted(-5.0, -5.0, 5.0, 5.0))

        icon_size = int(static_orb_rect.width() * 0.28)
        icon = self._secretary_icon(icon_size, active, error=error)
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
        elif self._error_mode and self._error_frames:
            frame = self._error_frames[self._error_frame_index % len(self._error_frames)]
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
        cursor.movePosition(QTextCursor.End)
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


# ──────────────────────────────────────────────────────────────────────────────
# SecretaryConfirmDialog
# Dark-themed modal popup for actions that require explicit user confirmation:
#   • Download patient / batch download
#   • Delete patient / study / any stored item
#   • Structural server changes (send report, modify stored data)
# All other commands (search, open, navigate, view) are executed immediately
# without showing this dialog.
# ──────────────────────────────────────────────────────────────────────────────
class SecretaryConfirmDialog(QDialog):
    """EchoMind-styled Yes/No confirmation dialog for critical Secretary actions."""

    # action → (window title, qtawesome icon, English confirmation sentence)
    _ACTION_MAP: dict = {
        "download_patient":    ("Download Patient",    "fa5s.download",          "I want to download this patient's data."),
        "select_and_download": ("Batch Download",      "fa5s.download",          "I want to download the selected patients."),
        "open_patient":        ("Open Patient",        "fa5s.folder-open",       "I want to open this patient's study."),
        "delete_patient":      ("Delete Patient",      "fa5s.trash-alt",         "I want to delete this patient."),
        "delete_study":        ("Delete Study",        "fa5s.trash-alt",         "I want to delete this study."),
        "delete_item":         ("Delete Item",         "fa5s.trash-alt",         "I want to delete this item."),
        "send_report":         ("Send Report",         "fa5s.paper-plane",       "I want to send this report to the server."),
        "modify_data":         ("Modify Server Data",  "fa5s.edit",              "I want to apply changes to the stored data."),
        "create_record":       ("Create Record",       "fa5s.plus-circle",       "I want to create a new record on the server."),
    }
    _DEFAULT = ("Confirm Action", "fa5s.exclamation-triangle", "Are you sure you want to proceed?")

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        action = str(result.get("action") or "")
        title, icon_name, message = self._ACTION_MAP.get(action, self._DEFAULT)
        data = result.get("data") or {}
        detail = self._build_detail(action, data, result.get("message", ""))

        self.setModal(True)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumWidth(400)

        # ── Root: semi-transparent overlay ────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        overlay = QFrame(self)
        overlay.setStyleSheet("QFrame { background: rgba(4, 8, 14, 172); }")
        root.addWidget(overlay)

        ol = QVBoxLayout(overlay)
        ol.setContentsMargins(22, 22, 22, 22)
        ol.setSpacing(0)

        # ── Main panel ────────────────────────────────────────────────────────
        panel = QFrame(overlay)
        panel.setStyleSheet(
            "QFrame {"
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "  stop:0 #0c1826, stop:0.6 #091420, stop:1 #06101a);"
            "border: 1px solid #1e4a72;"
            "border-radius: 14px;"
            "}"
        )
        ol.addWidget(panel)

        pl = QVBoxLayout(panel)
        pl.setContentsMargins(26, 20, 26, 20)
        pl.setSpacing(12)

        # ── Header row: action icon + branding label ───────────────────────────
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        try:
            action_icon_lbl = QLabel()
            pix = qta.icon(icon_name, color="#4ab0e8").pixmap(26, 26)
            action_icon_lbl.setPixmap(pix)
            action_icon_lbl.setFixedSize(26, 26)
            header_row.addWidget(action_icon_lbl, 0)
        except Exception:
            pass

        brand = QLabel("EchoMind Secretary")
        brand.setStyleSheet(
            "QLabel {"
            "color: #3a8ec8; font-size: 10px;"
            "font-family: 'Roboto', sans-serif; font-weight: 600;"
            "background: transparent;"
            "}"
        )
        header_row.addWidget(brand, 1)
        pl.addLayout(header_row)

        # ── Thin divider ──────────────────────────────────────────────────────
        sep = QFrame(panel)
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { background: #1b3a56; border: none; max-height: 1px; }")
        pl.addWidget(sep)

        # ── Action title ──────────────────────────────────────────────────────
        title_lbl = QLabel(title)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(
            "QLabel {"
            "color: #d5eeff; font-size: 15px;"
            "font-family: 'Roboto', sans-serif; font-weight: 700;"
            "background: transparent; padding-top: 2px;"
            "}"
        )
        pl.addWidget(title_lbl)

        # ── English confirmation sentence ─────────────────────────────────────
        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(
            "QLabel {"
            "color: #9ac4e0; font-size: 13px;"
            "font-family: 'Roboto', sans-serif;"
            "background: transparent;"
            "}"
        )
        pl.addWidget(msg_lbl)

        # ── Detail card (patient name/ID or count) ────────────────────────────
        if detail:
            detail_lbl = QLabel(detail)
            detail_lbl.setWordWrap(True)
            detail_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            detail_lbl.setStyleSheet(
                "QLabel {"
                "color: #6898b8; font-size: 11px;"
                "font-family: 'Consolas', 'Roboto Mono', monospace;"
                "background: rgba(10, 22, 36, 0.75);"
                "border: 1px solid #1a3550;"
                "border-radius: 7px;"
                "padding: 7px 12px;"
                "}"
            )
            pl.addWidget(detail_lbl)

        # ── Spacer ────────────────────────────────────────────────────────────
        pl.addSpacing(4)

        # ── Button row ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch(1)

        self._no_btn = QPushButton("No, Cancel")
        self._no_btn.setCursor(Qt.PointingHandCursor)
        self._no_btn.setFixedHeight(34)
        self._no_btn.setMinimumWidth(114)
        self._no_btn.setStyleSheet(
            "QPushButton {"
            "background: rgba(14, 26, 42, 0.92);"
            "color: #7098b0; border: 1px solid #2a4a68;"
            "border-radius: 8px; font-size: 12px;"
            "font-family: 'Roboto', sans-serif; font-weight: 600; padding: 0 18px;"
            "}"
            "QPushButton:hover {"
            "background: rgba(22, 38, 58, 0.96); color: #99c0da; border-color: #3e6a8a;"
            "}"
            "QPushButton:pressed { background: rgba(8, 16, 28, 1.0); }"
        )
        self._no_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._no_btn)

        self._yes_btn = QPushButton("Yes, Proceed")
        self._yes_btn.setCursor(Qt.PointingHandCursor)
        self._yes_btn.setFixedHeight(34)
        self._yes_btn.setMinimumWidth(122)
        self._yes_btn.setDefault(True)
        self._yes_btn.setStyleSheet(
            "QPushButton {"
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "  stop:0 #1a6aa8, stop:1 #134e80);"
            "color: #d8f0ff; border: 1px solid #2e80c0;"
            "border-radius: 8px; font-size: 12px;"
            "font-family: 'Roboto', sans-serif; font-weight: 700; padding: 0 18px;"
            "}"
            "QPushButton:hover {"
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "  stop:0 #2280c8, stop:1 #1a5e98);"
            "border-color: #40a0e0;"
            "}"
            "QPushButton:pressed { background: #0e3e68; }"
        )
        self._yes_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._yes_btn)

        pl.addLayout(btn_row)

    @staticmethod
    def _build_detail(action: str, data: dict, fallback_msg: str) -> str:
        """Compose a human-readable detail line from result data."""
        if isinstance(data, dict):
            candidate = data.get("candidate")
            if isinstance(candidate, dict):
                pid  = str(candidate.get("patient_id")   or "").strip()
                name = str(candidate.get("patient_name") or "").strip()
                if name and pid:
                    return f"Patient: {name}  ({pid})"
                if name or pid:
                    return f"Patient: {name or pid}"
            count = data.get("selected_count") or data.get("downloaded_count")
            if count:
                scol = str(data.get("sort_column") or "")
                sord = str(data.get("sort_order")  or "")
                suffix = f"  —  sorted by {scol} {sord}" if scol else ""
                return f"{count} patient(s) will be affected{suffix}"
        if fallback_msg:
            clean = " ".join(str(fallback_msg).split())
            return clean[:180] + ("…" if len(clean) > 180 else "")
        return ""


class SecretaryButtonWidget(QWidget):
    listeningToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("secretaryButtonWidget")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(396)
        self._log_box_height = 28
        self._log_popup = None
        self._log_lines = []
        self._stage_lines = []
        self._thinking_stage = "Ready"
        self._rec_running = False
        self._rec_thread = None
        self._rec_frames = []
        self._rec_fs = 44100
        self._rec_started_at = None
        self._last_audio_path = None
        self._stt_router = SttRouter()
        self._worker = None
        self._secretary_orchestrator = None
        self._secretary_session_id = f"secretary-home-{uuid.uuid4().hex[:10]}"

        # Visual state machine: "idle" | "listening" | "error"
        self._ui_state: str = "idle"
        self._prev_ui_state: str = "idle"
        self._fade_t: float = 1.0
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(16)
        self._fade_timer.timeout.connect(self._advance_fade)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 4, 2, 4)
        main_layout.setSpacing(6)

        self.orb_button = SecretaryOrbButton(self)
        self.orb_button.activeChanged.connect(self._on_active_changed)
        main_layout.addWidget(self.orb_button, 1, Qt.AlignHCenter)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("")
        self.log_box.document().setMaximumBlockCount(90)
        self.log_box.setFixedHeight(self._log_box_height)
        self.log_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.log_box.setFrameStyle(QFrame.NoFrame)
        self.log_box.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log_box.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log_box.setStyleSheet(
            "QPlainTextEdit {"
            "background: transparent;"
            "border: none;"
            "padding: 0px;"
            "color: #cce9ff;"
            "font-size: 12px;"
            "font-family: 'Consolas', 'Roboto Mono', monospace;"
            "}"
        )
        main_layout.addWidget(self.log_box, 0, Qt.AlignHCenter)

        # ── Memory status row: counter label + "New" button ───────────────────
        _mem_row = QHBoxLayout()
        _mem_row.setSpacing(4)
        _mem_row.setContentsMargins(2, 0, 2, 0)

        self.memory_label = QLabel("Memory #1 — Cycle 0/10")
        self.memory_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.memory_label.setStyleSheet(
            "QLabel {"
            "color: #5a8fa0;"
            "font-size: 10px;"
            "font-family: 'Consolas', 'Roboto Mono', monospace;"
            "background: transparent;"
            "}"
        )
        _mem_row.addWidget(self.memory_label, 1)

        self.memory_new_btn = QToolButton(self)
        self.memory_new_btn.setText("New")
        self.memory_new_btn.setToolTip("Start a new conversation memory file")
        self.memory_new_btn.setCursor(Qt.PointingHandCursor)
        self.memory_new_btn.setAutoRaise(True)
        self.memory_new_btn.setFixedHeight(18)
        self.memory_new_btn.setStyleSheet(
            "QToolButton {"
            "color: #5a8fa0;"
            "font-size: 10px;"
            "background: rgba(14, 26, 38, 0.70);"
            "border: 1px solid #2a4a5a;"
            "border-radius: 4px;"
            "padding: 0px 5px;"
            "}"
            "QToolButton:hover {"
            "color: #9accde;"
            "border-color: #4a8aa8;"
            "background: rgba(22, 40, 56, 0.90);"
            "}"
        )
        self.memory_new_btn.clicked.connect(self._on_new_memory)
        _mem_row.addWidget(self.memory_new_btn, 0)

        main_layout.addLayout(_mem_row)

        self.log_expand_icon = QToolButton(self)
        self.log_expand_icon.setCursor(Qt.PointingHandCursor)
        self.log_expand_icon.setAutoRaise(True)
        self.log_expand_icon.setToolTip("Details")
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
        self.log_expand_icon.setVisible(True)

        self.log_box.viewport().installEventFilter(self)
        self._set_thinking_status("Ready")

    def _set_log_box_text(self, text: str) -> None:
        try:
            self.log_box.setPlainText(text or "")
        except Exception:
            pass

    def _refresh_log_box(self) -> None:
        if self._stage_lines:
            text = self._stage_lines[-1]
        else:
            text = (self._thinking_stage or "Ready").strip() or "Ready"
        self._set_log_box_text(text)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        panel_rect = QRectF(self.rect())
        state  = getattr(self, "_ui_state", "idle")
        fade   = getattr(self, "_fade_t",   1.0)

        # === Panel background — subtle per-state tint ========================
        pg = QLinearGradient(panel_rect.topLeft(), panel_rect.bottomLeft())
        if state == "error":
            pg.setColorAt(0.0,  QColor(20,  8, 10, 215))
            pg.setColorAt(0.35, QColor(15,  6,  8, 230))
            pg.setColorAt(1.0,  QColor(10,  4,  5, 242))
        elif state == "listening":
            pg.setColorAt(0.0,  QColor( 8, 19, 36, 215))
            pg.setColorAt(0.35, QColor( 6, 15, 28, 230))
            pg.setColorAt(1.0,  QColor( 3, 10, 20, 242))
        else:  # idle
            pg.setColorAt(0.0,  QColor( 8, 14, 22, 215))
            pg.setColorAt(0.35, QColor( 7, 12, 19, 228))
            pg.setColorAt(1.0,  QColor( 5, 10, 16, 240))
        painter.fillRect(panel_rect, pg)

        if not hasattr(self, "orb_button"):
            painter.end()
            return

        orb_geo = self.orb_button.geometry()
        halo_cx = orb_geo.center().x()
        halo_cy = orb_geo.center().y() + orb_geo.height() * 0.04
        painter.setPen(Qt.NoPen)

        # === Listening — two-layer bright blue glow =========================
        if state == "listening":
            phase = self.orb_button.get_phase()
            beat  = max(0.0, min(1.0, (0.5 - 0.5 * math.cos(phase)) ** 1.25))
            f     = fade  # 0 → 1 as state fades in

            # Outer atmospheric glow (large, soft)
            r_out = max(panel_rect.width() * 1.05, panel_rect.height() * 0.90)
            g_out = QRadialGradient(halo_cx, halo_cy, r_out)
            g_out.setColorAt(0.00, QColor( 92, 228, 255, int((62 + 32 * beat) * f)))
            g_out.setColorAt(0.38, QColor( 58, 178, 238, int((24 + 14 * beat) * f)))
            g_out.setColorAt(0.72, QColor( 26, 110, 168, int(( 7 +  5 * beat) * f)))
            g_out.setColorAt(1.00, QColor(  0,   0,   0, 0))
            painter.setBrush(g_out)
            painter.drawEllipse(QRectF(halo_cx - r_out, halo_cy - r_out, r_out * 2, r_out * 2))

            # Inner core glow (tight — makes center feel strongly illuminated)
            r_in = max(panel_rect.width() * 0.50, orb_geo.height() * 1.02)
            g_in = QRadialGradient(halo_cx, halo_cy, r_in)
            g_in.setColorAt(0.00, QColor(148, 255, 255, int((112 + 58 * beat) * f)))
            g_in.setColorAt(0.30, QColor( 92, 220, 255, int(( 62 + 34 * beat) * f)))
            g_in.setColorAt(0.65, QColor( 50, 162, 222, int(( 22 + 14 * beat) * f)))
            g_in.setColorAt(1.00, QColor(  0,   0,   0, 0))
            painter.setBrush(g_in)
            painter.drawEllipse(QRectF(halo_cx - r_in, halo_cy - r_in, r_in * 2, r_in * 2))

        # === Error — slow red radial glow ====================================
        elif state == "error":
            n_err   = len(self.orb_button._error_frames) if self.orb_button._error_frames else 48
            idx_e   = self.orb_button._error_frame_index
            e_phase = (2.0 * math.pi * idx_e) / max(1, n_err)
            beat_e  = max(0.0, min(1.0, (0.5 - 0.5 * math.cos(e_phase * 0.65)) ** 1.2))

            r_err = max(panel_rect.width() * 0.88, panel_rect.height() * 0.76)
            g_err = QRadialGradient(halo_cx, halo_cy, r_err)
            g_err.setColorAt(0.00, QColor(255, 66, 46, int((60 + 44 * beat_e) * fade)))
            g_err.setColorAt(0.38, QColor(200, 35, 24, int((20 + 16 * beat_e) * fade)))
            g_err.setColorAt(0.75, QColor(128, 16, 10, int(( 6 +  5 * beat_e) * fade)))
            g_err.setColorAt(1.00, QColor(  0,  0,  0, 0))
            painter.setBrush(g_err)
            painter.drawEllipse(QRectF(halo_cx - r_err, halo_cy - r_err, r_err * 2, r_err * 2))

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

    def eventFilter(self, obj, event):
        if obj is getattr(self, "log_box", None).viewport() and event.type() == QEvent.MouseButtonPress:
            self._toggle_log_popup()
            return True
        return super().eventFilter(obj, event)

    def _set_thinking_status(self, stage: str) -> None:
        stage = (stage or "").strip()
        self._thinking_stage = stage or "Ready"
        self._refresh_log_box()

    # ── Visual state machine ──────────────────────────────────────────────────

    def set_ui_state(self, state: str) -> None:
        """Transition the panel to 'idle', 'listening', or 'error' with a fade."""
        if state == getattr(self, "_ui_state", "idle"):
            return
        self._prev_ui_state = getattr(self, "_ui_state", "idle")
        self._ui_state = state
        self._fade_t = 0.0
        # Sync orb error-mode so its border/ring change too
        if hasattr(self, "orb_button"):
            self.orb_button.set_error(state == "error")
        self._fade_timer.start()
        self.update()

    def _advance_fade(self) -> None:
        self._fade_t = min(1.0, self._fade_t + 0.055)  # ~18 steps ≈ 290 ms
        self.update()
        if self._fade_t >= 1.0:
            self._fade_timer.stop()

    # ── Memory helpers ────────────────────────────────────────────────────────

    def _on_new_memory(self) -> None:
        """Create a new memory file when the user clicks the 'New' button."""
        try:
            # Ensure the orchestrator is alive so we can reach its memory store
            if not self._ensure_secretary_runtime():
                return
            mem = getattr(self._secretary_orchestrator, "memory_store", None)
            if mem is not None:
                mem.new_memory()
                self._refresh_memory_label()
        except Exception:
            pass

    def _refresh_memory_label(self) -> None:
        """Read the current (memory_number, cycle_count) and update the label."""
        try:
            mem = getattr(getattr(self, "_secretary_orchestrator", None), "memory_store", None)
            if mem is None:
                return
            num, cyc = mem.get_current_info()
            self.memory_label.setText(f"Memory #{num} — Cycle {cyc}/10")
        except Exception:
            pass

    # ── Confirmation dialog ───────────────────────────────────────────────────

    def _show_secretary_confirm_dialog(self, result: dict) -> bool:
        """Show the EchoMind confirmation popup. Returns True if user clicked Yes."""
        try:
            dlg = SecretaryConfirmDialog(result, parent=self.window())
            dlg.adjustSize()
            # Centre the dialog over the host window
            host = self.window()
            if host is not None:
                geo = host.geometry()
                hint = dlg.sizeHint()
                dlg.move(
                    geo.x() + max(0, (geo.width()  - hint.width())  // 2),
                    geo.y() + max(0, (geo.height() - hint.height()) // 2),
                )
            return dlg.exec() == QDialog.Accepted
        except Exception:
            return False

    def append_log(self, role, text):
        ts = datetime.now().strftime("%H:%M:%S")
        role_map = {
            "user": "Input",
            "assistant": "Output",
            "system": "System",
        }
        role_label = role_map.get(str(role).lower(), str(role).title())
        self._log_lines.append(f"[{ts}] {role_label}: {text}")
        self._sync_popup_log_text()

    def append_input(self, text):
        self.append_log("user", text)
        self._append_stage_line(self._format_stage_line("Transcript", text))

    def append_output(self, text):
        self.append_log("assistant", text)
        self._append_stage_line(self._format_stage_line("Result", text))

    def _on_active_changed(self, active):
        if active:
            self._stage_lines = []
            
            # Check microphone availability first
            if not self._check_microphone_available():
                self._set_active_silent(False)
                QTimer.singleShot(0, lambda: self.set_ui_state("error"))
                return
            
            if not self._ensure_echomind_login():
                self._set_active_silent(False)
                QTimer.singleShot(0, lambda: self.set_ui_state("error"))
                return
            self.set_ui_state("listening")
            self._set_thinking_status("Listening")
            self.append_log("system", "Secretary is live and listening for a command.")
            self._start_recording()
        else:
            # Only drop back to idle if the previous action was not an error
            if getattr(self, "_ui_state", "idle") != "error":
                self.set_ui_state("idle")
            self._set_thinking_status("Transcribing")
            self.append_log("system", "Secretary listening stopped.")
            self._stop_recording_and_process()
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
            self._log_popup.set_log_text("\n".join(self._log_lines))

    def _toggle_log_popup(self):
        if self._log_popup is not None and self._log_popup.isVisible():
            self._log_popup.close()
            return

        if self._log_popup is None:
            self._log_popup = SecretaryLogPopup(self.window())
            self._log_popup.closed.connect(self._on_log_popup_closed)
        self._log_popup.close_btn.setIcon(self._safe_icon(("fa5s.compress", "fa5s.compress-alt", "fa5s.times"), "#d5e8fb"))
        self._log_popup.set_log_text("\n".join(self._log_lines))
        self._log_popup.open_over(self.window())

    def _on_log_popup_closed(self):
        if self._log_popup is not None:
            self._log_popup.hide()

    def _format_stage_line(self, label: str, text: str, max_len: int = 220) -> str:
        clean = " ".join(str(text or "").split()).strip()
        if max_len > 0 and len(clean) > max_len:
            clean = clean[: max_len - 3].rstrip() + "..."
        if label:
            return f"{label}: {clean}" if clean else f"{label}:"
        return clean

    def _append_stage_line(self, text: str) -> None:
        line = (text or "").strip()
        if not line:
            return
        self._stage_lines.append(line)
        self._refresh_log_box()

    def _set_active_silent(self, active: bool) -> None:
        try:
            self.orb_button.blockSignals(True)
            self.orb_button.setChecked(bool(active))
        finally:
            try:
                self.orb_button.blockSignals(False)
            except Exception:
                pass
        try:
            self.orb_button._apply_state(bool(active))
        except Exception:
            pass

    def _post_log(self, role: str, text: str) -> None:
        QTimer.singleShot(0, lambda: self.append_log(role, text))

    def _send_transcript_to_gapgpt(self, transcript: str) -> None:
        text = (transcript or "").strip()
        if not text:
            return

        if not self._ensure_echomind_login():
            self._post_log("system", "GapGPT blocked: EchoMind key is not validated.")
            return

        def work():
            # LLM call goes through EchoMind.llm_client — key comes from Settings → EchoMind
            try:
                from EchoMind.llm_client import gapgpt_chat, LLMError
                content = gapgpt_chat(
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful medical assistant. Respond to the transcript concisely.",
                        },
                        {"role": "user", "content": text},
                    ],
                    model="gpt-4.1-mini",
                    timeout=60,
                )
                return {"ok": True, "content": content}
            except LLMError as exc:
                return {"ok": False, "error": str(exc)}
            except Exception as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        def done(resp: dict):
            if not isinstance(resp, dict):
                self._post_log("system", "GapGPT failed: Invalid response payload.")
                return
            if not resp.get("ok"):
                self._post_log("system", f"GapGPT failed: {resp.get('error')}")
                return
            content = (resp.get("content") or "").strip()
            if content:
                self.append_output(f"GapGPT: {content}")

        def failed(msg: str):
            self._post_log("system", f"GapGPT failed: {msg}")

        worker = ApiWorker(work, parent=self)
        worker.done.connect(done)
        worker.failed.connect(failed)
        worker.start()

    def _ensure_secretary_runtime(self) -> bool:
        if self._secretary_orchestrator is not None:
            return True
        try:
            self._secretary_orchestrator = create_secretary_orchestrator()
        except Exception:
            self._secretary_orchestrator = None
        if self._secretary_orchestrator is None:
            self._post_log("system", "Secretary engine is unavailable.")
            self._set_thinking_status("Ready")
            return False
        return True

    def _format_secretary_result_text(self, result: dict) -> str:
        action = str(result.get("action") or "secretary")
        msg = str(result.get("message") or "").strip()

        # Chitchat / greeting replies — show as a clean conversational message.
        if action == "chitchat":
            return msg or "Secretary: ..."

        ok = "OK" if result.get("ok") else "Action Required"
        lines = [f"Secretary [{action}] ({ok}): {msg}"]

        data = result.get("data")
        if isinstance(data, list):
            for idx, row in enumerate(data[:30], start=1):
                if not isinstance(row, dict):
                    continue
                pid = str(row.get("patient_id") or "").strip()
                name = str(row.get("patient_name") or "").strip()
                date = str(row.get("date") or "").strip()
                modality = str(row.get("modality") or "").strip()
                suid = str(row.get("study_uid") or "").strip()
                lines.append(f"{idx}. {pid} - {name} | {date} | {modality} | {suid}")
        elif isinstance(data, dict):
            candidate = data.get("candidate") if isinstance(data.get("candidate"), dict) else data
            if isinstance(candidate, dict):
                pid = str(candidate.get("patient_id") or "").strip()
                name = str(candidate.get("patient_name") or "").strip()
                suid = str(candidate.get("study_uid") or "").strip()
                lines.append(f"Selected: {pid} - {name} | {suid}")

        return "\n".join([line for line in lines if line])

    def _check_microphone_available(self) -> bool:
        """
        Check if a microphone is available and active.
        Returns True if microphone is available, False otherwise.
        Shows an error message to the user if microphone is not available.
        """
        try:
            # Get list of input devices
            devices = sd.query_devices()
            if not devices:
                QMessageBox.warning(
                    self,
                    "Microphone Not Found",
                    "No audio input devices detected. Please connect a microphone and try again.",
                )
                self._post_log("system", "Error: No audio input devices found.")
                return False
            
            # Check if default input device is available
            try:
                default_input = sd.query_devices(kind='input')
                if default_input is None:
                    QMessageBox.warning(
                        self,
                        "Microphone Not Available",
                        "No default input device is configured. Please check your audio settings.",
                    )
                    self._post_log("system", "Error: No default input device configured.")
                    return False
                
                # Check if the device has input channels
                max_input_channels = default_input.get('max_input_channels', 0)
                if max_input_channels <= 0:
                    QMessageBox.warning(
                        self,
                        "Microphone Inactive",
                        "The default input device has no active input channels. Please enable your microphone.",
                    )
                    self._post_log("system", "Error: Default input device has no active channels.")
                    return False
                
                self._post_log("system", f"Microphone check OK: {default_input.get('name', 'Unknown device')}")
                return True
                
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Microphone Error",
                    f"Unable to access the microphone. Please check your audio settings.\n\nError: {str(e)}",
                )
                self._post_log("system", f"Error: Failed to query input device: {e}")
                return False
                
        except Exception as e:
            QMessageBox.critical(
                self,
                "Audio System Error",
                f"Failed to check audio devices. Please verify your audio drivers are installed.\n\nError: {str(e)}",
            )
            self._post_log("system", f"Error: Failed to check audio devices: {e}")
            return False

    def _ensure_echomind_login(self) -> bool:
        mgr = APIKeyManager.instance()
        if mgr.is_validated():
            return True

        key = (get_echomind_api_key() or "").strip()
        if not key:
            QMessageBox.information(
                self,
                "EchoMind",
                "No EchoMind key saved. Open Settings -> EchoMind to configure it.",
            )
            return False

        success, center, error = mgr.validate_key(key)
        if not success:
            QMessageBox.critical(
                self,
                "EchoMind Authentication",
                (error or "Invalid key.") + " Update it in Settings -> EchoMind.",
            )
            return False

        try:
            Manage.instance().detect_center(key)
        except Exception:
            pass
        self._post_log("system", f"EchoMind login OK: {center or 'Unknown'}")
        return True

    def _start_recording(self) -> None:
        if self._rec_running:
            return
        self._rec_running = True
        self._rec_started_at = time.time()
        self._rec_frames = []
        self._set_thinking_status("Listening")
        self._post_log("system", "Listening started.")

        def worker():
            try:
                with sd.InputStream(
                    samplerate=self._rec_fs,
                    channels=1,
                    dtype="int16",
                    callback=self._rec_callback,
                ):
                    while self._rec_running:
                        sd.sleep(100)
            except Exception as exc:
                self._rec_running = False
                self._post_log("system", f"Recording error: {exc}")
                self._set_active_silent(False)

        self._rec_thread = threading.Thread(target=worker, daemon=True)
        self._rec_thread.start()

    def _rec_callback(self, indata, frames, time_info, status):
        del frames, time_info, status
        if not self._rec_running:
            return
        try:
            self._rec_frames.append(indata.copy())
        except Exception:
            pass

    def _stop_recording_and_process(self) -> None:
        if not self._rec_running:
            return
        self._rec_running = False
        started_at = self._rec_started_at
        self._rec_started_at = None
        if self._rec_thread is not None:
            try:
                self._rec_thread.join(timeout=1.5)
            except Exception:
                pass
            self._rec_thread = None

        if not self._rec_frames:
            self._set_thinking_status("Ready")
            self._post_log("system", "No audio captured.")
            return

        tmp = os.path.join(tempfile.gettempdir(), f"secretary_{int(time.time())}.wav")
        try:
            audio = np.concatenate(self._rec_frames, axis=0)
            peak = 0
            try:
                peak = int(np.max(np.abs(audio))) if audio.size else 0
            except Exception:
                peak = 0
            if peak < 300:
                self._set_thinking_status("Ready")
                self._post_log("system", "Audio too quiet or muted. Check microphone input.")
                return
            sf.write(tmp, audio, self._rec_fs)
            self._last_audio_path = tmp
            duration_s = float(len(audio)) / float(self._rec_fs or 1)
            if started_at is not None:
                elapsed = max(0.0, time.time() - started_at)
                self._post_log("system", f"Listening stopped. Duration: {elapsed:.2f}s")
            self._post_log("system", f"Audio captured: {duration_s:.2f}s @ {self._rec_fs}Hz")
        except Exception as exc:
            self._set_thinking_status("Ready")
            self._post_log("system", f"Audio save failed: {exc}")
            return

        if self._worker is not None and self._worker.isRunning():
            self._set_thinking_status("Ready")
            self._post_log("system", "Secretary is still processing the previous request.")
            return

        self._set_thinking_status("Phase 1: Transcribing")
        self._post_log("system", "Phase 1: Sending voice to GPT for transcription...")

        def work():
            import datetime as _dt
            import sys as _sys
            def _elog(msg: str) -> None:
                try:
                    _sys.stderr.write(msg + "\n")
                    _sys.stderr.flush()
                except Exception:
                    pass
            _elog(f"[EchoMind | Phase 1] {_dt.datetime.now():%H:%M:%S} — STT started: sending audio to transcription service")
            try:
                stt_settings = load_settings() or {}
                stt_req = {
                    "route": get_secretary_stt_route(),
                    "fallback": False,
                    "quality_mode": "noisy",
                }
                stt_resp = self._stt_router.transcribe_files(
                    paths=[tmp],
                    route=stt_req["route"],
                    fallback=stt_req["fallback"],
                    quality_mode=stt_req["quality_mode"],
                )
                transcript = (stt_resp.get("transcript") or "").strip()
                if not transcript:
                    return {
                        "ok": False,
                        "error": stt_resp.get("error") or "No speech recognized.",
                        "stt_req": stt_req,
                        "stt_resp": stt_resp,
                        "stt_settings": stt_settings,
                    }
                return {
                    "ok": True,
                    "transcript": transcript,
                    "stt_req": stt_req,
                    "stt_resp": stt_resp,
                    "stt_settings": stt_settings,
                }
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass

        def done(resp: dict):
            if not resp.get("ok"):
                stt_req = resp.get("stt_req") or {}
                stt_resp = resp.get("stt_resp") or {}
                self._set_thinking_status("Ready")
                self._post_log("system", f"STT request: {stt_req}")
                self._post_log("system", f"STT response: {stt_resp}")
                self._post_log("system", f"Secretary failed: {resp.get('error')}")
                return
            transcript = (resp.get("transcript") or "").strip()
            stt_req = resp.get("stt_req") or {}
            stt_resp = resp.get("stt_resp") or {}
            import datetime as _dt
            import sys as _sys
            def _elog(msg: str) -> None:
                try:
                    _sys.stderr.write(msg + "\n")
                    _sys.stderr.flush()
                except Exception:
                    pass
            _elog(f"[EchoMind | Phase 1] {_dt.datetime.now():%H:%M:%S} — STT complete")
            _elog(f"  transcript : {transcript!r}")
            self._post_log("system", f"Phase 1 complete — transcript: {transcript!r}")
            if transcript:
                self.append_input(transcript)

            if not self._ensure_secretary_runtime():
                return

            # Phase 2: the orchestrator will route the text to a module (LLM call).
            self._set_thinking_status("Phase 2: Module Routing")
            self._post_log("system", "Phase 2: Sending transcript + module catalog to GPT.")
            _elog(f"[EchoMind | Phase 2] {_dt.datetime.now():%H:%M:%S} — sending transcript + catalog to GPT for module routing")

            stt_settings = resp.get("stt_settings") or {}
            requested_route = str(stt_req.get("route") or "native")
            used_route = str(stt_resp.get("route_used") or requested_route)

            # progress_cb is invoked from the worker thread — use singleShot to
            # update the Qt label safely from the main thread.
            def _progress(stage: str) -> None:
                QTimer.singleShot(0, lambda s=stage: self._set_thinking_status(s))

            payload = {
                "text": transcript,
                "language": "auto",
                "session_id": self._secretary_session_id,
                "source_scope": "active_tab",
                "stt_route": requested_route,
                "stt_route_used": used_route,
                "stt_fallback": bool(stt_settings.get("secretary_stt_fallback", True)),
                "progress_cb": _progress,
            }
            try:
                result = self._secretary_orchestrator.handle(payload)  # type: ignore[union-attr]
            except Exception as exc:
                self._set_thinking_status("Ready")
                self._post_log("system", f"Secretary engine error: {exc}")
                return

            # ── Popup confirmation dialog ─────────────────────────────────────
            # Triggered for: download, delete, structural server changes.
            # All other actions (search, open, navigate, view) execute directly
            # and will never reach CONFIRM_REQUIRED so the dialog is never shown.
            if (result or {}).get("error_code") == "CONFIRM_REQUIRED":
                self._set_thinking_status("Awaiting Confirmation")
                self._post_log("system", "Confirmation required — showing dialog.")
                confirmed = self._show_secretary_confirm_dialog(result or {})
                answer_text = "yes" if confirmed else "no"
                try:
                    result = self._secretary_orchestrator.handle({  # type: ignore[union-attr]
                        "text": answer_text,
                        "session_id": self._secretary_session_id,
                    })
                except Exception as _conf_exc:
                    result = {
                        "ok": False,
                        "action": (result or {}).get("action", "unknown"),
                        "message": f"Confirmation dispatch failed: {_conf_exc}",
                        "data": None,
                        "error_code": "INTERNAL",
                    }
                self._post_log(
                    "system",
                    f"User {'confirmed' if confirmed else 'cancelled'} — "
                    f"result: {'OK' if (result or {}).get('ok') else (result or {}).get('error_code', 'error')}",
                )

            import datetime as _dt2
            import sys as _sys2
            def _elog2(msg: str) -> None:
                try:
                    _sys2.stderr.write(msg + "\n")
                    _sys2.stderr.flush()
                except Exception:
                    pass
            _elog2(f"[EchoMind | Result ] {_dt2.datetime.now():%H:%M:%S} — pipeline complete")
            _elog2(f"  ok         : {(result or {}).get('ok')}")
            _elog2(f"  action     : {(result or {}).get('action')}")
            _elog2(f"  message    : {str((result or {}).get('message') or '')[:120]}")
            data = (result or {}).get("data")
            if isinstance(data, list):
                _elog2(f"  data rows  : {len(data)}")
            elif isinstance(data, dict):
                _elog2(f"  data keys  : {list(data.keys())}")
            self.append_output(self._format_secretary_result_text(result or {}))
            self._set_thinking_status("Ready")
            self.set_ui_state("idle")
            # Update memory label with new cycle count
            QTimer.singleShot(50, self._refresh_memory_label)

        def failed(msg: str):
            if getattr(self, "_ui_state", "idle") != "error":
                self.set_ui_state("idle")
            self._set_thinking_status("Ready")
            self._post_log("system", f"Secretary failed: {msg}")

        self._worker = ApiWorker(work, parent=self)
        self._worker.done.connect(done)
        self._worker.failed.connect(failed)
        self._worker.start()
