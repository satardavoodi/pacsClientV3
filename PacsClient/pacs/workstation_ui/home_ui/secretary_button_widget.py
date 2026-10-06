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
    QLineEdit,
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
from modules.EchoMind.secretary_bridge import create_secretary_orchestrator
from modules.EchoMind.api_manager import APIKeyManager, Manage
from modules.EchoMind.viewer_chat.ai_chat_api import ApiWorker

# ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ 2026-07-31: detach-don't-wait, the same contract the EchoMind chat uses ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
# `SecretaryButtonWidget` had NO teardown at all ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ no closeEvent, no cleanup, no
# deleteLater ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ and created one `ApiWorker(parent=self)` QThread per voice
# command. Closing the app while an STT upload was in flight (the upload budget
# is 360 s, so this is ordinary, not a corner case) let Qt destroy a RUNNING
# QThread: `QThread: Destroyed while thread is still running` -> qFatal ->
# abort(), with no traceback and no Python frame. app.log simply stops
# mid-line.
#
# The rule: never `wait()` (that re-creates the freeze the worker exists to
# avoid) and never let Python GC a running QThread (that aborts the process).
# Disconnect it, unparent it, park it here, and release it when it finishes.
_ORPHANED_SECRETARY_WORKERS: list = []

# ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ 2026-07-31: Phase 2/3 planning off the GUI thread ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
# `AIPACS_ECHOMIND_SECRETARY_ASYNC=0` restores the fully-synchronous pipeline
# (planning AND execution inline in the STT callback, i.e. the legacy freeze).
_ENV_SECRETARY_ASYNC = "AIPACS_ECHOMIND_SECRETARY_ASYNC"


def _secretary_async_enabled() -> bool:
    raw = os.environ.get(_ENV_SECRETARY_ASYNC)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _release_orphan_secretary_worker(worker) -> None:
    try:
        _ORPHANED_SECRETARY_WORKERS.remove(worker)
    except ValueError:
        pass
    try:
        worker.deleteLater()
    except Exception:
        pass
from modules.EchoMind.secretary.stt.router import SttRouter
from modules.EchoMind.settings_store import (
    get_secretary_stt_route,
    get_stt_settings,
    load_settings,
    get_echomind_api_key,
)


# ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ 2026-08-10: one transport retry for the Secretary STT upload ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
# Agent mode had NO retry of any kind, while the chat gained `_retry_once` on
# 2026-08-09. A timeout, a dropped connection or an HTTP 5xx is usually transient
# and costs the physician an entire re-dictation here. Only those are resent: a
# recording the server answered and found silent ("No speech recognized.") is a
# quality event ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ resending it buys a duplicate failure and a wasted upload of
# patient dictation.
_STT_TRANSPORT_MARKERS = (
    "server error",          # requests' raise_for_status wording for every 5xx
    "timeout",
    "timed out",
    "connection",            # ConnectionError / HTTPConnectionPool / aborted
    "max retries",
    "remote end closed",
    "reset by peer",
    "broken pipe",
    "bad gateway",
    "service unavailable",
    "temporarily unavailable",
)


def _stt_failure_is_transport(stt_resp: dict) -> bool:
    """Did the STT request fail to COMPLETE (vs. complete and hear nothing)?

    Mirrors the split the chat makes in `ai_chat_pages._transcribe_now`: the
    worker's `err()` path is "transport", while `accepted=False` / an empty
    transcript is "quality". Anything unrecognised counts as NOT transport, so
    the default stays "do not resend the patient's dictation".
    """
    try:
        if stt_resp.get("ok"):
            return False
        err = str(stt_resp.get("error") or "").strip().lower()
    except Exception:                        # pragma: no cover - defensive
        return False
    if not err:
        return False
    # Quality / caller-side outcomes a resend cannot change.
    if "no speech" in err or "no files" in err or "no valid audio" in err:
        return False
    return any(marker in err for marker in _STT_TRANSPORT_MARKERS)


# Lazy orb-frame build (2026-06-18 perceived-latency work). The orb pre-renders
# 72 active + 48 error animation frames; doing that synchronously on the first
# home-page paint blocked the GUI thread ~3.5 s every launch. With this on, only
# the inactive + first frame are built up front and the rest stream in on an idle
# timer (the orb is inactive at startup, so the active/error frames aren't needed
# yet). Kill switch: AIPACS_ORB_LAZY_FRAMES=0 restores the synchronous build.
_ORB_LAZY_FRAMES = (os.getenv("AIPACS_ORB_LAZY_FRAMES", "1") or "1").strip() != "0"


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
        self._icon_pixmap_cache = {}  # key=(size, color) ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ QPixmap; avoids 121 qta calls per rebuild

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

        # Lazy frame-build state (see _ORB_LAZY_FRAMES). The chunked builder fills
        # the remaining active/error frames a few per tick after first paint.
        self._lazy_build_side = -1
        self._lazy_active_done = 0
        self._lazy_error_done = 0
        self._lazy_frame_timer = QTimer(self)
        self._lazy_frame_timer.setInterval(15)
        self._lazy_frame_timer.timeout.connect(self._build_more_frames)

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
        # NOTE (2026-04-30): the original implementation called QColor(img.pixel(x, y))
        # in a Python double loop over every (step) pixel of an Echo-Mind PNG. F11
        # main-thread sampler captured a single 22.2 s startup stall in this method
        # on a fresh launch (pid 39244, 2026-04-30). Vectorized via numpy on the
        # QImage byte buffer; observed runtime drops from seconds to a few ms.
        if pixmap.isNull():
            return 0.62, 0.50

        img = pixmap.toImage().convertToFormat(QImage.Format_RGB32)
        width = img.width()
        height = img.height()
        if width <= 1 or height <= 1:
            return 0.62, 0.50

        try:
            bytes_per_line = img.bytesPerLine()
            ptr = img.constBits()
            # PySide6 returns a memoryview-like; bytes() copy is cheap relative
            # to the previous Python pixel loop and avoids lifetime issues.
            buf = bytes(ptr)[: bytes_per_line * height]
            arr = np.frombuffer(buf, dtype=np.uint8).reshape((height, bytes_per_line))
            arr = arr[:, : width * 4].reshape((height, width, 4))
            # Format_RGB32 on little-endian Windows lays out as BGRA bytes.
            b_full = arr[..., 0].astype(np.int16)
            g_full = arr[..., 1].astype(np.int16)
            r_full = arr[..., 2].astype(np.int16)
        except Exception:
            # On any unexpected layout/conversion failure, fall back to the
            # documented neutral default so the orb still renders correctly.
            return 0.62, 0.50

        step = max(1, min(width, height) // 380)
        right_start = int(width * 0.24)
        if right_start >= width:
            return 0.62, 0.50

        rs = r_full[::step, right_start::step]
        gs = g_full[::step, right_start::step]
        bs = b_full[::step, right_start::step]

        cyan_like = (bs > 92) & (gs > 76) & (bs > (rs + 14)) & (gs > (rs + 8))
        bright_white = (rs > 208) & (gs > 208) & (bs > 208)
        mask = cyan_like | bright_white

        luminance = 0.2126 * rs + 0.7152 * gs + 0.0722 * bs
        cyan_bias = np.maximum(0.0, (bs - rs) * 1.2) + np.maximum(0.0, (gs - rs) * 0.9)
        weight = luminance * 0.35 + cyan_bias
        weight = np.where(mask & (weight > 0.0), weight, 0.0)

        # Project subsampled columns back into the full-width column-weight vector.
        col_sum = weight.sum(axis=0)
        col_weights = np.zeros(width, dtype=np.float64)
        sampled_xs = right_start + np.arange(col_sum.shape[0]) * step
        valid = sampled_xs < width
        col_weights[sampled_xs[valid]] = col_sum[valid]
        total_weight = float(col_weights.sum())
        if total_weight <= 0.0:
            return 0.62, 0.50

        window = max(96, int(width * 0.30))
        if window >= width:
            window = max(32, width - 1)

        # Sliding-window sum via cumulative-sum; equivalent to the original
        # incremental running sum over col_weights.
        csum = np.concatenate(([0.0], np.cumsum(col_weights)))
        win_sums = csum[window:width] - csum[: width - window]
        if win_sums.size == 0:
            return 0.62, 0.50
        best_start = int(np.argmax(win_sums))

        band_start = best_start
        band_end = min(width, best_start + window)
        band = col_weights[band_start:band_end]
        band_weight = float(band.sum())
        if band_weight <= 0.0:
            return 0.62, 0.50
        weighted_x = float((band * np.arange(band_start, band_end)).sum())

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

    _ACTIVE_FRAME_COUNT = 72
    _ERROR_FRAME_COUNT = 48  # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ°ط·آ«أ¢â‚¬آ  4.3 s slow red pulse

    def _rebuild_frames(self):
        side = max(160, min(self.width(), self.height()))
        if side == self._cached_side:
            return

        self._cached_side = side
        self._inactive_frame = self._render_frame(side, active=False, phase=0.0, error=False)
        self._frame_index = 0
        self._error_frame_index = 0
        frame_count = self._ACTIVE_FRAME_COUNT
        error_frame_count = self._ERROR_FRAME_COUNT

        if not _ORB_LAZY_FRAMES:
            # Legacy: build every frame synchronously (ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ°ط·آ«أ¢â‚¬آ 3.5 s on first paint).
            self._active_frames = [
                self._render_frame(
                    side, active=True,
                    phase=(2.0 * math.pi * idx) / float(frame_count), error=False,
                )
                for idx in range(frame_count)
            ]
            self._error_frames = [
                self._render_frame(
                    side, active=False,
                    phase=(2.0 * math.pi * idx) / float(error_frame_count), error=True,
                )
                for idx in range(error_frame_count)
            ]
            return

        # Lazy: build the inactive (above) + first active + first error frame now so
        # the animation can start immediately, then stream the rest in chunks (see
        # _build_more_frames). paintEvent / _advance_frame use len(_active_frames),
        # so a growing list animates smoothly (briefly fewer frames, then full).
        self._active_frames = [self._render_frame(side, active=True, phase=0.0, error=False)]
        self._error_frames = [self._render_frame(side, active=False, phase=0.0, error=True)]
        self._lazy_build_side = side
        self._lazy_active_done = 1
        self._lazy_error_done = 1
        self._lazy_frame_timer.start()

    def _build_more_frames(self):
        """Idle-time chunked builder for the remaining active/error frames.

        Runs only under _ORB_LAZY_FRAMES. QPixmap/QPainter are main-thread only, so
        this builds a few frames per tick on the GUI thread ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ no single tick blocks.
        Stops when both sets are complete or the widget size changed (a new
        _rebuild_frames will restart it for the new size).
        """
        side = self._lazy_build_side
        if side != self._cached_side:
            self._lazy_frame_timer.stop()
            return
        frame_count = self._ACTIVE_FRAME_COUNT
        error_frame_count = self._ERROR_FRAME_COUNT
        chunk = 8
        built = 0
        try:
            while self._lazy_active_done < frame_count and built < chunk:
                idx = self._lazy_active_done
                self._active_frames.append(
                    self._render_frame(
                        side, active=True,
                        phase=(2.0 * math.pi * idx) / float(frame_count), error=False,
                    )
                )
                self._lazy_active_done += 1
                built += 1
            while self._lazy_error_done < error_frame_count and built < chunk:
                idx = self._lazy_error_done
                self._error_frames.append(
                    self._render_frame(
                        side, active=False,
                        phase=(2.0 * math.pi * idx) / float(error_frame_count), error=True,
                    )
                )
                self._lazy_error_done += 1
                built += 1
        except Exception:
            self._lazy_frame_timer.stop()
            return
        if (self._lazy_active_done >= frame_count
                and self._lazy_error_done >= error_frame_count):
            self._lazy_frame_timer.stop()

    def _secretary_icon(self, size, active, error=False):
        """Return a QPixmap for the secretary icon.  Cached by (size, color) to prevent
        qta.icon().pixmap() being called 121 times per _rebuild_frames() (was 36-40 s stall)."""
        if error:
            color = "#a05548"
        else:
            color = "#dcf8ff" if active else "#7f91a8"
        cache_key = (size, color)
        cached = self._icon_pixmap_cache.get(cache_key)
        if cached is not None:
            return cached
        result = None
        for icon_name in ("fa5s.user-tie", "fa5s.robot", "fa5s.microphone"):
            try:
                result = qta.icon(icon_name, color=color).pixmap(size, size)
                break
            except Exception:
                continue
        if result is None:
            result = QPixmap(size, size)
            result.fill(Qt.transparent)
        self._icon_pixmap_cache[cache_key] = result
        return result

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

        if getattr(self, "_compact_avatar", False):
            from .secretary_compact_ui import paint_compact_orb
            paint_compact_orb(self, painter)
            painter.end()
            return
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
            "font-size: 16px;"
            "font-family: 'Segoe UI', sans-serif;"
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
            width = min(720, host.width())
            height = min(480, host.height())
            self.setGeometry(top_left.x() + (host.width()-width)//2,
                             top_left.y() + (host.height()-height)//2, width, height)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


# ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
# SecretaryConfirmDialog
# Dark-themed modal popup for actions that require explicit user confirmation:
#   ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ¢ط¢آ¢ Download patient / batch download
#   ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ¢ط¢آ¢ Delete patient / study / any stored item
#   ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ¢ط¢آ¢ Structural server changes (send report, modify stored data)
# All other commands (search, open, navigate, view) are executed immediately
# without showing this dialog.
# ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
class SecretaryConfirmDialog(QDialog):
    """EchoMind-styled Yes/No confirmation dialog for critical Secretary actions."""

    # action ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ (window title, qtawesome icon, English confirmation sentence)
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

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Root: semi-transparent overlay ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        overlay = QFrame(self)
        overlay.setObjectName("secretaryConfirmOuter")
        overlay.setStyleSheet("QFrame#secretaryConfirmOuter { background: transparent; border: none; }")
        root.addWidget(overlay)

        ol = QVBoxLayout(overlay)
        ol.setContentsMargins(22, 22, 22, 22)
        ol.setSpacing(0)

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Main panel ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
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

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Header row: action icon + branding label ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
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

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Thin divider ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
        sep = QFrame(panel)
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { background: #1b3a56; border: none; max-height: 1px; }")
        pl.addWidget(sep)

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Action title ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
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

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ English confirmation sentence ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
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

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Detail card (patient name/ID or count) ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
        if detail:
            detail_lbl = QLabel(detail)
            detail_lbl.setWordWrap(True)
            detail_lbl.setTextFormat(Qt.PlainText)
            detail_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            detail_lbl.setStyleSheet(
                "QLabel {"
                "color: #6898b8; font-size: 11px;"
                "font-family: 'Segoe UI', sans-serif;"
                "background: rgba(10, 22, 36, 0.75);"
                "border: 1px solid #1a3550;"
                "border-radius: 7px;"
                "padding: 7px 12px;"
                "}"
            )
            pl.addWidget(detail_lbl)

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Spacer ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
        pl.addSpacing(4)

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Button row ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch(1)

        self._no_btn = QPushButton("No, Cancel")
        self._no_btn.setCursor(Qt.PointingHandCursor)
        self._no_btn.setMinimumHeight(34)  # Archetype 5: floor, can grow with font/DPI
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
        self._yes_btn.setMinimumHeight(34)  # Archetype 5: floor, can grow with font/DPI
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
        """Use verified structured details; never truncate a raw planner message."""
        if isinstance(data, dict):
            candidate = data.get("candidate")
            if isinstance(candidate, dict):
                pid = str(candidate.get("patient_id") or "").strip()
                name = str(candidate.get("patient_name") or "").strip()
                if name or pid:
                    return f"Patient: {name} ({pid})" if name and pid else f"Patient: {name or pid}"
            count = data.get("selected_count") or data.get("downloaded_count")
            if count:
                return f"{count} studies will be affected."
        from .secretary_result_text import format_result
        return format_result({'ok':False, 'action':action, 'data':data,
                              'error_code':'CONFIRM_REQUIRED'})


class SecretaryButtonWidget(QWidget):
    def _watch_help_ticket(self, dialog):
        previous = getattr(self, '_observed_support_dialog', None)
        if previous is dialog and getattr(dialog,'_secretary_observer',None) is self:
            return False
        if previous is not None:
            try:
                previous.deliveryChanged.disconnect(self._on_help_ticket_update)
            except (RuntimeError, TypeError):
                pass
        self._observed_support_dialog = dialog
        other = getattr(dialog,'_secretary_observer',None)
        if other is not None and other is not self:
            try:
                dialog.deliveryChanged.disconnect(other._on_help_ticket_update)
            except (RuntimeError, TypeError):
                pass
        dialog._secretary_observer = self
        dialog.deliveryChanged.connect(self._on_help_ticket_update)
        if dialog.public_result.get('state') in ('pending', 'received', 'running'):
            self._on_help_ticket_update(dict(dialog.public_result))
            return True
        return False

    def _on_help_ticket_update(self, result):
        from PacsClient.utils.support_ticket_feedback import ticket_feedback
        stage, text = ticket_feedback(result)
        if not getattr(self, '_secretary_busy', False):
            self._set_thinking_status(stage)
        if result.get('completed_chunks') is not None:
            return  # The status/form carries progress; do not flood the conversation.
        self.append_output(text)

    listeningToggled = Signal(bool)

    def _open_support_issue(self):
        from PacsClient.pacs.workstation_ui.home_ui.home_panel.widget import get_home_widget
        from .support_issue_dialog import open_support_issue_form
        home = get_home_widget()
        if home is None or self._rec_running or self._secretary_busy:
            return
        try:
            open_support_issue_form(home)
        except ValueError:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, 'Support issue', 'Sign in to the PACS workstation before reporting an issue.')

    def _prepare_help_ticket(self, transcript, recording=None):
        self._set_thinking_status("Working: Preparing Help Ticket")
        self.mode_selector.setEnabled(False)
        def work():
            from modules.EchoMind.secretary.remote_planner import request
            return request('plan', transcript, interaction_mode='help_ticket', question_context={'support_ticket_intents':1})
        def done(response):
            ticket = response['ticket']
            self._open_help_ticket(ticket['description'], recording, ticket['category'], ticket.get('operation','prepare'))
        def failed(message):
            self._post_log("system", message)
            self._set_thinking_status("Failed")
            self._finish_secretary_cycle()
        self._run_worker(work, done, failed)

    def _open_help_ticket(self, transcript, recording=None, category='other', operation='prepare'):
        """Reuse the reviewed website issue flow without AI planning or auto-send."""
        from PacsClient.pacs.workstation_ui.home_ui.home_panel.widget import get_home_widget
        from .support_issue_dialog import open_support_issue_form
        try:
            home = get_home_widget()
            if home is None:
                raise ValueError("Open the main workstation before reporting an issue.")
            existing = getattr(home, '_support_issue_dialog', None)
            if operation == 'prepare' and existing is not None and existing.public_result.get('state') in ('received','not_found'):
                existing.close()
            if existing is not None and existing.isVisible():
                dialog = existing
                existing.raise_()
                existing.activateWindow()
                message = "An issue draft is already open. Review it before creating another ticket."
            else:
                bus = getattr(home, 'command_bus', None)
                if bus is not None:
                    prepared = bus.execute({'action':'prepare_help_ticket', 'entities':{'description':transcript if operation=='prepare' else ''}})
                    if not prepared.ok:
                        raise ValueError(prepared.message or 'Help Ticket preparation is unavailable.')
                    dialog = getattr(home, '_support_issue_dialog', None)
                else:
                    dialog = open_support_issue_form(home, transcript if operation=='prepare' else '')
                if dialog is not None:
                    dialog.category.setCurrentIndex(dialog.category.findData(category))
                    if recording and operation == 'prepare':
                        dialog._ticket_recordings.append(recording)
                message = "Looking for your previous Help Ticket and its delivery receipt." if operation != 'prepare' else "Help ticket draft ready. Review the report and click Send issue to submit it to AI-PACS support."
            feedback_shown = False
            if dialog is not None:
                dialog._requested_ticket_operation = operation
                feedback_shown = self._watch_help_ticket(dialog)
            stage = 'Confirmation required'
            if operation != 'prepare' and dialog is not None:
                result = dialog.public_result
                if result.get('state') in ('received','not_found','pending'):
                    from PacsClient.utils.support_ticket_feedback import ticket_feedback
                    stage, message = ticket_feedback(result)
                elif getattr(dialog,'_operation',None) is not None:
                    stage = 'Working: Checking Help Ticket'
            if not feedback_shown:
                self.append_output(message)
            self._set_thinking_status(stage)
        except ValueError as exc:
            self._post_log("system", str(exc))
            self._set_thinking_status("Failed")
        except Exception:
            self._post_log("system", "Could not open the help ticket form. Please try again from the main workstation.")
            self._set_thinking_status("Failed")
        finally:
            self._finish_secretary_cycle()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("secretaryButtonWidget")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Archetype 5: minimum height floor lowered from 396 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 240. On a
        # 1024-tall monitor (Monitor B in the test plan) the previous 396 px
        # floor combined with the Patient Search section above forced the
        # left sidebar to overflow; with 240 px the panel still fits the
        # orb comfortably at its 90-px minimum diameter, and scrolling
        # picks up the rest if the user wants the orb larger.
        # See docs/conventions/RESPONSIVE_UI_CONVENTION.md.
        self.setMinimumHeight(240)
        self._log_box_height = 28
        self._log_popup = None
        self._response_panel = None
        self._log_lines = []
        self._stage_lines = []
        self._thinking_stage = "Ready"
        self._rec_running = False
        self._rec_thread = None
        self._rec_stream = None       # live PortAudio stream, for deterministic stop
        # True from the moment a voice command is accepted until its result is
        # rendered. The old guard only checked the STT worker, so once THAT had
        # finished a second command could start on top of an in-flight
        # execution ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ and `home_widget_adapter.search` pumps `processEvents`
        # for up to 45 s, which is exactly what delivers the orb click that
        # starts it.
        self._secretary_busy = False
        self._workers: list = []      # live ApiWorkers, for deterministic teardown
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

        self.report_issue_button = QToolButton(self)
        self.report_issue_button.setText('Report an issue')
        self.report_issue_button.setToolTip('Review and send an AI-PACS support issue')
        self.report_issue_button.clicked.connect(self._open_support_issue)
        main_layout.addWidget(self.report_issue_button, 0, Qt.AlignHCenter)

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
            "font-family: 'Segoe UI', sans-serif;"
            "}"
        )
        main_layout.addWidget(self.log_box, 0, Qt.AlignHCenter)

        command_row = QHBoxLayout()
        self.command_input = QLineEdit(self)
        self.command_input.setObjectName("secretaryCommandInput")
        self.command_input.setAccessibleName("Secretary command")
        self.command_input.setPlaceholderText("Type a command...")
        self.command_input.setMaxLength(20000)
        self.command_input.setStyleSheet("QLineEdit { font-size: 14px; padding: 6px; }")
        self.command_send = QPushButton("Send", self)
        self.command_send.setAccessibleName("Send Secretary command")
        self.command_send.clicked.connect(self._send_typed_command)
        self.command_input.returnPressed.connect(self._send_typed_command)
        command_row.addWidget(self.command_input, 1)
        command_row.addWidget(self.command_send)
        main_layout.addLayout(command_row)

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Memory status row: counter label + "New" button ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
        _mem_row = QHBoxLayout()
        _mem_row.setSpacing(4)
        _mem_row.setContentsMargins(2, 0, 2, 0)

        self.memory_label = QLabel("Memory #1 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ Cycle 0/10")
        self.memory_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.memory_label.setStyleSheet(
            "QLabel {"
            "color: #5a8fa0;"
            "font-size: 10px;"
            "font-family: 'Segoe UI', sans-serif;"
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
        from .secretary_compact_ui import configure_compact_secretary
        configure_compact_secretary(self)
        self._set_thinking_status("Ready")

    def _set_log_box_text(self, text: str) -> None:
        try:
            self.log_box.setPlainText(text or "")
        except Exception:
            pass

    def _refresh_log_box(self) -> None:
        if getattr(self, "_compact_companion", False) and hasattr(self, "_status_hint"):
            from .secretary_compact_ui import update_companion_status
            update_companion_status(self, self._thinking_stage or "Ready")
        else:
            self._set_log_box_text(self._thinking_stage or "Ready")

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        panel_rect = QRectF(self.rect())
        state  = getattr(self, "_ui_state", "idle")
        fade   = getattr(self, "_fade_t",   1.0)

        # === Panel background ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ subtle per-state tint ========================
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

        # === Listening ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ two-layer bright blue glow =========================
        if state == "listening":
            phase = self.orb_button.get_phase()
            beat  = max(0.0, min(1.0, (0.5 - 0.5 * math.cos(phase)) ** 1.25))
            f     = fade  # 0 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 1 as state fades in

            # Outer atmospheric glow (large, soft)
            r_out = max(panel_rect.width() * 1.05, panel_rect.height() * 0.90)
            g_out = QRadialGradient(halo_cx, halo_cy, r_out)
            g_out.setColorAt(0.00, QColor( 92, 228, 255, int((62 + 32 * beat) * f)))
            g_out.setColorAt(0.38, QColor( 58, 178, 238, int((24 + 14 * beat) * f)))
            g_out.setColorAt(0.72, QColor( 26, 110, 168, int(( 7 +  5 * beat) * f)))
            g_out.setColorAt(1.00, QColor(  0,   0,   0, 0))
            painter.setBrush(g_out)
            painter.drawEllipse(QRectF(halo_cx - r_out, halo_cy - r_out, r_out * 2, r_out * 2))

            # Inner core glow (tight ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ makes center feel strongly illuminated)
            r_in = max(panel_rect.width() * 0.50, orb_geo.height() * 1.02)
            g_in = QRadialGradient(halo_cx, halo_cy, r_in)
            g_in.setColorAt(0.00, QColor(148, 255, 255, int((112 + 58 * beat) * f)))
            g_in.setColorAt(0.30, QColor( 92, 220, 255, int(( 62 + 34 * beat) * f)))
            g_in.setColorAt(0.65, QColor( 50, 162, 222, int(( 22 + 14 * beat) * f)))
            g_in.setColorAt(1.00, QColor(  0,   0,   0, 0))
            painter.setBrush(g_in)
            painter.drawEllipse(QRectF(halo_cx - r_in, halo_cy - r_in, r_in * 2, r_in * 2))

        # === Error ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ slow red radial glow ====================================
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

        # Adaptive orb sizing for the EchoMind Secretary panel.
        # History:
        #   - Original: hard floor of 90 px and 80% of available space ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ on
        #     narrow sidebars (ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ°ط·آ¢ط¢آ¤ 240 px on Monitor B) the orb dominated the
        #     column.
        #   - W6 follow-up #6: floor 60 px, scale 0.78, ceiling 340 px so
        #     the orb keeps shrinking under pressure.
        #   - 2026-05-26 user request #1: 10% larger overall. Scale 0.78 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢
        #     0.86, ceiling 340 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 374, floor 60 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 66.
        #   - 2026-05-26 user request #2: 20% larger, less black margin.
        #     Scale 0.86 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 0.96, ceiling 374 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 449, floor 66 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ 80, buffer
        #     +26 ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ +14.
        #   - 2026-05-26 user request #3 (final): 10% smaller again to
        #     dial in the sweet spot before testing. All three knobs
        #     multiplied by 0.9 (rounded to integer pixels). Net effect
        #     versus original W6-follow-up #6: about 10-12 % larger orb
        #     with tighter margins, but ~10 % smaller than the previous
        #     "+20 %" pass.
        # The widget still uses setFixedSize on the orb specifically ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ the
        # orb MUST be a perfect circle (radial symmetry), which is the
        # convention's documented leaf case for setFixedSize. Click/hover
        # behaviour is driven by orb_button's own signals ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ unchanged.
        # See docs/conventions/RESPONSIVE_UI_CONVENTION.md ط·آ·ط¢آ¢ط·آ¢ط¢آ§"When you cannot
        # avoid setFixed*".
        if getattr(self, "_compact_companion", False):
            # Keep room for status text while consuming the available height.
            diameter = max(76, min(180, self.width() - 136, self.height() - 118))
            self.orb_button.setFixedSize(diameter, diameter)
            return
        avail_w = max(72, self.width() - 8)
        avail_h = max(72, self.height() - (self._log_box_height + 18))
        diameter = min(404, avail_w, avail_h)
        diameter = max(72, int(diameter * 0.86))
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

    # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Visual state machine ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬

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
        self._fade_t = min(1.0, self._fade_t + 0.055)  # ~18 steps ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ°ط·آ«أ¢â‚¬آ  290 ms
        self.update()
        if self._fade_t >= 1.0:
            self._fade_timer.stop()

    # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Memory helpers ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬

    def _on_new_memory(self) -> None:
        """Create a new memory file when the user clicks the 'New' button."""
        if self._secretary_busy or self.orb_button._active:
            self._post_log("system", "Finish the current command before starting a new conversation.")
            return
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
            self.memory_label.setText(f"Memory #{num} - Cycle {cyc}/10")
        except Exception:
            pass

    # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Confirmation dialog ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬

    def _show_secretary_confirm_dialog(self, result: dict) -> bool:
        """Show the EchoMind confirmation popup. Returns True if user clicked Yes.

        F12 fix (2026-06-09): when this widget is hosted inside the global
        ``SecretaryPopup`` (a frameless, always-on-top ``Qt.Tool`` window), a
        modal dialog parented to that popup is rendered *behind* the always-on-
        top popup ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ so the user's "Yes" never cleanly resolves to Accepted and
        the confirmed action silently cancels (the reported "asks for
        confirmation, then nothing happens"). Parenting the dialog to the real
        main window AND giving it WindowStaysOnTopHint makes the F12 flow
        behave exactly like the Main-Page orb (whose ``self.window()`` is
        already the main window). Harmless for the orb."""
        try:
            # Resolve the REAL top-level main window, not self.window() (which
            # is the always-on-top popup when hosted by F12).
            host = None
            try:
                from PacsClient.pacs.workstation_ui.home_ui.home_panel.widget import get_home_widget
                hw = get_home_widget()
                if hw is not None:
                    host = hw.window()
            except Exception:
                host = None
            if host is None:
                host = self.window()

            dlg = SecretaryConfirmDialog(result, parent=host)
            # Sit above the always-on-top F12 popup so the Yes/No buttons are
            # actually visible and clickable.
            try:
                dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            except Exception:
                pass
            dlg.adjustSize()
            # Centre the dialog over the host window
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

    # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ F12 global-popup: surface home-data results (2026-06-09) ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
    # Actions whose result lives on the Home page. When the assistant runs
    # from the global F12 popup (over the viewer/another module), bring the
    # Home page forward after one of these succeeds so the user actually sees
    # the outcome (download manager, search/patient list). Viewer/read actions
    # are intentionally excluded so reviewing isn't interrupted.
    _HOME_RESULT_ACTIONS = {
        "list_patients", "download_patient", "select_and_download",
        "sort_patients", "set_source_mode", "import_dicom", "select_patient",
    }

    def _maybe_surface_home_result(self, result: dict) -> None:
        """Bring the main window's Home page forward for a successful
        home-data command ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ ONLY when hosted in the global F12 popup. No-op
        for the Main-Page orb (already on Home) and for non-home actions.
        Best-effort; never raises into the result path."""
        try:
            if not getattr(self, "_in_global_popup", False):
                return
            if not (result or {}).get("ok"):
                return
            if str((result or {}).get("action") or "") not in self._HOME_RESULT_ACTIONS:
                return
            from PacsClient.pacs.workstation_ui.home_ui.home_panel.widget import get_home_widget
            hw = get_home_widget()
            if hw is None:
                return
            main_win = hw.window()
            if main_win is None:
                return
            show_home = getattr(main_win, "_show_home_page", None)
            if callable(show_home):
                show_home()
            try:
                main_win.raise_()
                main_win.activateWindow()
            except Exception:
                pass
        except Exception:
            pass

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
        from .secretary_response_panel import SecretaryResponsePanel
        if self._response_panel is None:
            self._response_panel = SecretaryResponsePanel(self.window())
            self._response_panel.detailsRequested.connect(self._toggle_log_popup)
            self._response_panel.commandSubmitted.connect(self.submit_text_command)
        self._response_panel.set_muted(getattr(self, "_reply_muted", False))
        self._response_panel.set_response(text)
        self._response_panel.open_response()
        self.append_log("assistant", text)
        self._append_stage_line(self._format_stage_line("Result", text))

    def _on_active_changed(self, active):
        if active:
            if self._response_panel is not None:
                self._response_panel.stop()
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
        # 2026-07-31 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ the two-argument `QTimer.singleShot(0, fn)` creates the
        # timer on the CALLING thread. The recorder is a plain
        # `threading.Thread` with no Qt event loop, so a timer created there
        # never fires and the log line was silently dropped. The three-argument
        # form takes a context QObject and delivers into THAT object's thread,
        # which is the GUI thread. Same call from the GUI thread is unchanged.
        try:
            QTimer.singleShot(0, self, lambda: self.append_log(role, text))
        except TypeError:                    # very old PySide6
            QTimer.singleShot(0, lambda: self.append_log(role, text))

    def _call_on_gui(self, fn) -> None:
        """Run `fn` on the GUI thread. Safe to call from any thread."""
        try:
            QTimer.singleShot(0, self, fn)
        except TypeError:                    # very old PySide6
            QTimer.singleShot(0, fn)

    def _send_transcript_to_gapgpt(self, transcript: str) -> None:
        text = (transcript or "").strip()
        if not text:
            return

        if not self._ensure_echomind_login():
            self._post_log("system", "GapGPT blocked: EchoMind key is not validated.")
            return

        def work():
            # LLM call goes through modules.EchoMind.llm_client ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ key comes from Settings ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬ط¢آ ط£آ¢أ¢â€ڑآ¬أ¢â€‍آ¢ EchoMind
            try:
                from modules.EchoMind.llm_client import gapgpt_chat, LLMError
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
        # 2026-07-31 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ track it so `cleanup()` can detach it, and free the
        # QObject when it ends (one per command accumulated for the whole
        # session otherwise, each pinning its closure).
        self._workers.append(worker)
        worker.finished.connect(lambda w=worker: self._retire_worker(w))
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
        from .secretary_result_text import format_result
        return format_result(result)

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
        try:
            from modules.EchoMind.llm_client import get_active_backend_display_name, is_active_backend_configured
            from modules.EchoMind.settings_store import get_llm_backend
        except Exception:
            get_llm_backend = None
            is_active_backend_configured = None
            get_active_backend_display_name = None

        if callable(get_llm_backend) and get_llm_backend() == "openai":
            if callable(is_active_backend_configured) and is_active_backend_configured():
                self._post_log(
                    "system",
                    f"EchoMind login OK: {get_active_backend_display_name() if callable(get_active_backend_display_name) else 'OpenAI'}",
                )
                return True
            QMessageBox.information(
                self,
                "EchoMind",
                "No OpenAI key is saved. Open Settings -> EchoMind -> OpenAI and configure it.",
            )
            return False

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
                (error or "Invalid key.") + " Update it in Settings -> modules.EchoMind.",
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
                ) as stream:
                    # 2026-07-31 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ keep a handle. The stream used to live only
                    # inside this `with`, so nothing could stop it
                    # deterministically: cancel_recording only flipped a flag
                    # and joined for 1.5 s, and if PortAudio did not return in
                    # time the stream was still live, with a bound method
                    # pointing at a widget Qt was about to free. This is the
                    # pre-fix shape of the crash the EchoMind composer's
                    # `cleanup()` was written for.
                    self._rec_stream = stream
                    while self._rec_running:
                        sd.sleep(100)
            except Exception as exc:
                self._rec_running = False
                self._post_log("system", f"Recording error: {exc}")
                # 2026-07-31 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ this ran ON THE AUDIO THREAD. `_set_active_silent`
                # calls blockSignals/setChecked and `orb_button._apply_state`,
                # which starts and stops QTimers and calls update() ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ widget
                # mutation from a non-GUI thread, i.e. undefined behaviour and
                # an intermittent access violation on Windows. Reached whenever
                # the mic is held by another app, unplugged, or the device index
                # went stale after a dock change.
                self._call_on_gui(lambda: self._set_active_silent(False))
            finally:
                self._rec_stream = None

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

    def _abort_audio_stream(self) -> None:
        """Stop PortAudio deterministically. Never raises."""
        stream = getattr(self, "_rec_stream", None)
        self._rec_stream = None
        if stream is None:
            return
        for call in ("abort", "close"):
            try:
                getattr(stream, call)(ignore_errors=True)
            except TypeError:
                try:
                    getattr(stream, call)()
                except Exception:
                    pass
            except Exception:
                pass

    def cancel_recording(self) -> bool:
        """Stop an in-flight recording WITHOUT processing it.

        Used by the F12 popup's X button (2026-06-06): closing the popup
        mid-listen must discard the capture instead of sending it to STT.
        Safe to call at any time from the GUI thread; returns True when a
        recording was actually cancelled. Never raises.
        """
        if not getattr(self, "_rec_running", False):
            return False
        self._rec_running = False
        thread = getattr(self, "_rec_thread", None)
        if thread is not None:
            try:
                thread.join(timeout=1.5)
            except Exception:
                pass
            self._rec_thread = None
        # 2026-07-31 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ the join has no fallback: if PortAudio does not return
        # within 1.5 s the stream is still live. Stop it explicitly.
        self._abort_audio_stream()
        self._rec_frames = []
        self._rec_started_at = None
        try:
            self._set_thinking_status("Ready")
        except Exception:
            pass
        try:
            self._post_log("system", "Recording cancelled.")
        except Exception:
            pass
        try:
            self._set_active_silent(False)
        except Exception:
            pass
        return True

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

        if (self._worker is not None and self._worker.isRunning()) or self._secretary_busy:
            self._set_thinking_status("Ready")
            self._post_log("system", "Secretary is still processing the previous request.")
            return
        # Covers the WHOLE pipeline (STT -> plan -> execute -> render), not just
        # the STT worker. See `_secretary_busy` in __init__ for why.
        self._secretary_busy = True

        self._set_thinking_status("Phase 1: Transcribing")
        self._post_log("system", "Phase 1: Sending voice to GPT for transcription...")

        retain_ticket_audio = self.mode_selector.currentData() == "help_ticket"
        def work():
            import datetime as _dt
            import sys as _sys
            def _elog(msg: str) -> None:
                try:
                    _sys.stderr.write(msg + "\n")
                    _sys.stderr.flush()
                except Exception:
                    pass
            _elog(f"[EchoMind | Phase 1] {_dt.datetime.now():%H:%M:%S} ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ STT started: sending audio to transcription service")
            try:
                stt_settings = load_settings() or {}
                # 2026-08-10 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ pass the CONFIGURED upload budget. The router took
                # no `timeout`, so NativeIrannobatProvider's own default reached
                # `_post_audio`, and a truthy `timeout` wins there over
                # `cfg["timeout_seconds"]`: Settings ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“ط·آ¢ط¢آ¸ EchoMind ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ“ط·آ¢ط¢آ¸ Voice to Text was
                # inert for agent mode while the chat honoured it.
                try:
                    stt_timeout = int(get_stt_settings().get("timeout_seconds") or 0) or None
                except Exception:
                    stt_timeout = None
                stt_req = {
                    "route": get_secretary_stt_route(),
                    # DELIBERATELY False, and deliberately NOT wired to the
                    # `secretary_stt_fallback` setting. The router's fallback is
                    # Google Web Speech, and that setting defaults to True ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ wiring
                    # it would ship raw patient dictation to Google's free,
                    # unauthenticated endpoint on the most common failure mode (an
                    # empty transcript). Do not connect them without a PHI review.
                    "fallback": False,
                    # DIVERGENCE from the chat, left as-is on purpose: chat starts
                    # at "clear" and auto-retries once in "noisy"; agent mode opens
                    # in "noisy". That moves the server's acceptance threshold for
                    # dictation, so changing it is a clinical behaviour change and
                    # needs the owner's sign-off.
                    "quality_mode": "noisy",
                    "timeout": stt_timeout,
                }
                stt_resp = self._stt_router.transcribe_files(
                    paths=[tmp],
                    route=stt_req["route"],
                    fallback=stt_req["fallback"],
                    quality_mode=stt_req["quality_mode"],
                    timeout=stt_req["timeout"],
                )
                # ONE plain resend, transport failures only ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ the agent-mode
                # counterpart of the chat's `_retry_once("transport")`. Identical
                # request (same file, same quality_mode); never fired for "no
                # speech"/quality. It stays on this worker thread ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ `_post_log`
                # already marshals itself to the GUI thread.
                if _stt_failure_is_transport(stt_resp):
                    self._post_log("system", "STT transport failure ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ retrying once...")
                    _elog(f"[EchoMind | Phase 1] {_dt.datetime.now():%H:%M:%S} ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ STT transport failure, retrying once")
                    stt_resp = self._stt_router.transcribe_files(
                        paths=[tmp],
                        route=stt_req["route"],
                        fallback=stt_req["fallback"],
                        quality_mode=stt_req["quality_mode"],
                        timeout=stt_req["timeout"],
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
                ticket_recording = None
                if retain_ticket_audio:
                    with open(tmp, "rb") as recording:
                        ticket_recording = recording.read(24 * 1024 * 1024 + 1)
                    if len(ticket_recording) > 24 * 1024 * 1024:
                        raise ValueError("Help Ticket recording exceeds the local package limit")
                return {
                    "ok": True,
                    "transcript": transcript,
                    "ticket_recording": ticket_recording,
                    "stt_req": stt_req,
                    "stt_resp": stt_resp,
                    "stt_settings": stt_settings,
                }
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass

        def done(resp):
            self._secretary_transcript_ready(resp)

        def failed(msg: str):
            if getattr(self, "_ui_state", "idle") != "error":
                self.set_ui_state("idle")
            self._set_thinking_status("Failed")
            self._post_log("system", f"Secretary failed: {msg}")
            self._finish_secretary_cycle()

        self._worker = ApiWorker(work, parent=self)
        self._worker.done.connect(done)
        self._worker.failed.connect(failed)
        self._workers.append(self._worker)
        self._worker.finished.connect(lambda w=self._worker: self._retire_worker(w))
        self._worker.start()


    # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Secretary pipeline helpers (2026-07-31) ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
    def _send_typed_command(self):
        if self.submit_text_command(self.command_input.text()):
            self.command_input.clear()

    def submit_text_command(self, text):
        """Typed input shares the post-transcription planning/execution path."""
        from modules.EchoMind.secretary.credential_guard import contains_api_credential, LOCAL_ENTRY_MESSAGE
        text = str(text or "").strip()
        if not text or len(text) > 20000 or self._rec_running or self._secretary_busy:
            return False
        if contains_api_credential(text):
            self._post_log("system", LOCAL_ENTRY_MESSAGE)
            return False
        self._secretary_busy = True
        self._secretary_transcript_ready({"ok": True, "transcript": text,
            "stt_req": {"route": "typed"}, "stt_resp": {"ok": True, "route_used": "typed"}})
        return True

    def _secretary_transcript_ready(self, resp):
        if not resp.get("ok"):
            stt_req = resp.get("stt_req") or {}
            stt_resp = resp.get("stt_resp") or {}
            self._set_thinking_status("Failed")
            self._post_log("system", f"STT request: {stt_req}")
            # 2026-08-10 ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ this used to print the provider dict verbatim. For
            # AI-PACS Servers 1/2 that dict is the server's merged RAW body: it
            # carries the transcript (patient dictation) and the resolved
            # endpoint, so one failed dictation put PHI *and* a server address
            # on screen. Same spirit as `voice_transcription._delegate`: report
            # the LENGTH, never the content, and never the raw dict.
            self._post_log(
                "system",
                "STT result: route={} used={} ok={} chars={} error={}".format(
                    stt_req.get("route") or "-",
                    stt_resp.get("route_used") or "-",
                    bool(stt_resp.get("ok")),
                    len(str(stt_resp.get("transcript") or "")),
                    stt_resp.get("error") or "-",
                ),
            )
            self._post_log("system", f"Secretary failed: {resp.get('error')}")
            self._finish_secretary_cycle()
            return
        transcript = (resp.get("transcript") or "").strip()
        from modules.EchoMind.secretary.credential_guard import contains_api_credential, LOCAL_ENTRY_MESSAGE
        if contains_api_credential(transcript):
            self._post_log('system', LOCAL_ENTRY_MESSAGE)
            self._finish_secretary_cycle()
            return
        if self.mode_selector.currentData() == "help_ticket":
            self._prepare_help_ticket(transcript, resp.get("ticket_recording"))
            return
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
        _elog(f"[EchoMind | Phase 1] {_dt.datetime.now():%H:%M:%S} ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ STT complete")
        _elog(f"  input_chars : {len(transcript)}")
        self._post_log("system", f"Phase 1 complete ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ transcript: {transcript!r}")
        if transcript:
            self.append_input(transcript)
        if not self._ensure_secretary_runtime():
            self._finish_secretary_cycle()
            return
        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Phase 2/3 now run OFF the GUI thread (2026-07-31) ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
        # `done` is delivered on the GUI thread ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ the modal confirm dialog
        # below only works because it is. Running `orchestrator.handle()`
        # here meant Phase-1 routing (20 s) + Phase-2 planning (30 s) +
        # repair (2 x 25 s) blocked the event loop: 60-95 s of frozen
        # workstation on a degraded link, and the staged "Phase 2 / Phase 3"
        # labels below could not repaint until it was all over, so they
        # arrived at once, after the fact.
        #
        # Only PLANNING moves. Execution reaches adapters that legitimately
        # touch widgets, so it stays on this thread ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ moving it would turn a
        # freeze into an access violation.
        self._set_thinking_status("Phase 2: Module Routing")
        self._post_log("system", "Phase 2: Sending transcript + module catalog to GPT.")
        _elog(f"[EchoMind | Phase 2] {_dt.datetime.now():%H:%M:%S} ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ sending transcript + catalog to GPT for module routing")
        stt_settings = resp.get("stt_settings") or {}
        requested_route = str(stt_req.get("route") or "native")
        used_route = str(stt_resp.get("route_used") or requested_route)
        # `progress_cb` is invoked from the PLANNING thread. The two-argument
        # `QTimer.singleShot(0, fn)` creates the timer on the calling thread,
        # which has no Qt event loop, so the stage label would never update ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’
        # `_call_on_gui` passes a context object and delivers into ours.
        def _progress(stage: str) -> None:
            self._call_on_gui(lambda s=stage: self._set_thinking_status(s))
        self.mode_selector.setEnabled(False)
        question_context = {}
        if self.mode_selector.currentData() == "ask":
            bus = self._secretary_orchestrator.executor._resolve_bus()
            from PacsClient.utils.secretary_question_context import capture_question_context
            question_context = capture_question_context(bus)
        if self.mode_selector.currentData() == "guide":
            bus = self._secretary_orchestrator.executor._resolve_bus()
            from PacsClient.utils.secretary_question_context import capture_guide_context
            question_context = capture_guide_context(bus)
        payload = {
            "text": transcript,
            "language": "auto",
            "session_id": self._secretary_session_id + ":" + self.mode_selector.currentData(),
            "source_scope": "active_tab",
            "interaction_mode": self.mode_selector.currentData(),
            "question_context": question_context,
            "stt_route": requested_route,
            "stt_route_used": used_route,
            "stt_fallback": bool(stt_settings.get("secretary_stt_fallback", True)),
            "progress_cb": _progress,
        }
        ui_capture=None
        panel=getattr(self,'_response_panel',None)
        include_screen=getattr(panel,'include_screen',None)
        if include_screen is not None and include_screen.isChecked():
            bus=self._secretary_orchestrator.executor._resolve_bus()
            observation=bus.registry.adapter('ui_observation') if bus is not None else None
            if observation is None:
                self._post_log('system','Screen context is unavailable for this application window.')
                self._finish_secretary_cycle()
                return
            try:
                from PacsClient.utils.secretary_ui_observation import capture
                ui_capture=capture(observation.root_getter())
                question_context=dict(question_context,ui_controls=ui_capture[0])
                payload['question_context']=question_context
            except (RuntimeError,ValueError):
                self._post_log('system','Open the intended page before including screen context.')
                self._finish_secretary_cycle()
                return
        if not _secretary_async_enabled() and ui_capture is None:
            self._secretary_execute_and_render(payload)
            return
        def plan_work():
            # PURE NETWORK ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ must not touch a single Qt object.
            worker_payload = payload
            if payload['interaction_mode'] == 'ask':
                from PacsClient.utils.secretary_question_context import collect_question_evidence, collect_settings_report
                from PacsClient.utils.data_paths import LOGS_DIR
                evidence = collect_question_evidence(question_context, LOGS_DIR)
                evidence['settings_report'] = collect_settings_report()
                worker_payload = dict(payload, question_context=evidence)
            if ui_capture is not None:
                from PacsClient.utils.secretary_ui_observation import encode
                worker_payload=dict(worker_payload,ui_image=encode(*ui_capture))
            return {"plan": self._secretary_orchestrator.preplan(worker_payload)}
        def plan_done(res: dict):
            # Re-check metadata-only Guide context as well as image context.
            if payload['interaction_mode'] == 'guide' and ui_capture is None:
                metadata = question_context.get('ui_controls', {})
                if metadata.get('context_digest'):
                    current_bus = self._secretary_orchestrator.executor._resolve_bus()
                    current_observation = current_bus.registry.adapter('ui_observation') if current_bus else None
                    if current_observation is None or not current_observation.is_current(metadata):
                        self._post_log('system', 'The page changed while preparing guidance. Ask again for the current page.')
                        self._finish_secretary_cycle()
                        return
            # Back on the GUI thread. `False` means planning ran and found
            # nothing, so `handle()` will not re-run the LLM here.
            if ui_capture is not None and not observation.is_current(ui_capture[0]):
                self._post_log('system','Screen context changed while planning. Capture the current page and retry.')
                self._finish_secretary_cycle()
                return
            payload["_preplanned"] = (res or {}).get("plan") or False
            self._secretary_execute_and_render(payload)
        def plan_failed(msg: str):
            self._set_thinking_status("Failed")
            self._post_log("system", f"Secretary planning failed: {msg}")
            self._finish_secretary_cycle()
        self._run_worker(plan_work, plan_done, plan_failed)

    def _run_worker(self, work, on_done, on_failed=None):
        """Run `work` on an ApiWorker and deliver the result to the GUI thread.

        Registers the worker so `cleanup()` can detach it on teardown, and frees
        the QObject when it ends. `work` MUST NOT touch a single Qt object.
        """
        worker = ApiWorker(work, parent=self)
        worker.done.connect(on_done)
        if on_failed is not None:
            worker.failed.connect(on_failed)
        self._workers.append(worker)
        worker.finished.connect(lambda w=worker: self._retire_worker(w))
        worker.start()
        return worker

    def _finish_secretary_cycle(self) -> None:
        """Release the pipeline lock. Safe to call more than once."""
        self._secretary_busy = False
        self.mode_selector.setEnabled(True)

    def _schedule_execution_repair(self, payload: dict, result: dict) -> None:
        """Keep server repair off Qt; resume local execution with fresh permission."""
        from modules.EchoMind.secretary.execution_repair import repair_plan_after_execution_failure
        failure = dict(result)
        request = failure.pop('_execution_repair')
        attempt = request['attempt']
        from copy import deepcopy
        runtime_capabilities = deepcopy(getattr(
            self._secretary_orchestrator, '_last_runtime_capabilities', None))
        self._set_thinking_status('Eagle Eye Server: Repairing action')

        def work():
            return {'plan': repair_plan_after_execution_failure(
                user_text=payload.get('text') or '', language=payload.get('language') or 'auto',
                failed_plan=request['failed_plan'], execution_result=failure,
                attempt=attempt, max_attempts=self._secretary_orchestrator._MAX_EXECUTION_RETRIES,
                runtime_capabilities=runtime_capabilities)}

        def done(response):
            plan = (response or {}).get('plan')
            if plan:
                self._secretary_execute_and_render(dict(payload, _preplanned=plan,
                                                        _execution_attempt=attempt + 1))
            else:
                self._secretary_execute_and_render(payload, completed_result=failure)

        def failed(message):
            self._post_log('system', 'Secretary server repair could not complete.')
            self._secretary_execute_and_render(payload, completed_result=failure)

        self._run_worker(work, done, failed)

    def _secretary_execute_and_render(self, payload: dict, *, completed_result=None) -> None:
        """Schedule execution on the existing qasync GUI loop without blocking it."""
        import asyncio
        task = asyncio.create_task(self._secretary_execute_and_render_async(
            payload, completed_result=completed_result))
        tasks = getattr(self, "_execution_tasks", None)
        if tasks is None:
            tasks = self._execution_tasks = set()
        tasks.add(task)
        def finished(done):
            tasks.discard(done)
            if not done.cancelled():
                error = done.exception()
                if error is not None:
                    self._post_log("system", "Secretary execution stopped unexpectedly.")
                    self._finish_secretary_cycle()
        task.add_done_callback(finished)

    async def _secretary_execute_and_render_async(self, payload: dict, *, completed_result=None) -> None:
        self._set_thinking_status("Executing")
        """Execute the plan and render the result. **GUI thread only.**

        Everything here is deliberately on this thread: the executor reaches
        adapters that legitimately touch widgets, and the confirmation dialog is
        modal. When `payload["_preplanned"]` is set, the LLM work has already
        happened on a worker, so `handle()` goes straight to execution instead
        of re-running routing and planning here.
        """
        import datetime as _dt2
        import sys as _sys2

        def _elog2(msg: str) -> None:
            try:
                _sys2.stderr.write(msg + "\n")
                _sys2.stderr.flush()
            except Exception:
                pass

        try:
            if completed_result is None:
                payload = dict(payload, _defer_execution_repair=True)
                result = await self._secretary_orchestrator.handle_async(payload)
            else:
                result = completed_result
            if (result or {}).get('_execution_repair'):
                self._schedule_execution_repair(payload, result)
                return
        except Exception as exc:
            self._set_thinking_status("Failed")
            self._post_log("system", f"Secretary engine error: {exc}")
            self._finish_secretary_cycle()
            return

        # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ Popup confirmation dialog ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
        # Triggered for: download, delete, structural server changes. All other
        # actions execute directly and never reach CONFIRM_REQUIRED.
        if (result or {}).get("error_code") == "CONFIRM_REQUIRED":
            self._set_thinking_status("Awaiting Confirmation")
            self._post_log("system", "Confirmation required ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ showing dialog.")
            confirmed = self._show_secretary_confirm_dialog(result or {})
            answer_text = "yes" if confirmed else "no"
            try:
                # Resolves a pending choice from session state ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ no LLM call, so
                # this one does not need to go back through a worker.
                from .secretary_result_text import confirmation_request
                result = await self._secretary_orchestrator.handle_async(
                    confirmation_request(payload, confirmed))
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
                f"User {'confirmed' if confirmed else 'cancelled'} ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ "
                f"result: {'OK' if (result or {}).get('ok') else (result or {}).get('error_code', 'error')}",
            )

        _elog2(f"[EchoMind | Result ] {_dt2.datetime.now():%H:%M:%S} ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ pipeline complete")
        _elog2(f"  ok         : {(result or {}).get('ok')}")
        _elog2(f"  action     : {(result or {}).get('action')}")
        _elog2(f"  message    : {str((result or {}).get('message') or '')[:120]}")
        data = (result or {}).get("data")
        if isinstance(data, list):
            _elog2(f"  data rows  : {len(data)}")
        elif isinstance(data, dict):
            _elog2(f"  data keys  : {list(data.keys())}")

        try:
            self.append_output(self._format_secretary_result_text(result or {}))
            self._maybe_surface_home_result(result or {})
        finally:
            self._set_thinking_status("Done" if (result or {}).get("ok") else "Failed")
            self.set_ui_state("idle")
            self._finish_secretary_cycle()
            QTimer.singleShot(50, self._refresh_memory_label)
            if (result or {}).get("error_code") == "NEEDS_CLARIFICATION":
                from .secretary_clarification_dialog import question_from_result
                question = question_from_result(result or {})
                self._set_thinking_status("Awaiting answer")
                if question:
                    QTimer.singleShot(0, lambda: self._ask_secretary_clarification(payload, question))

    # ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ deterministic teardown (2026-07-31) ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط·آ£ط¢آ¢ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ط£آ¢أ¢â‚¬ع‘ط¢آ¬
    def _ask_secretary_clarification(self, payload, clarification):
        from .secretary_clarification_dialog import SecretaryClarificationDialog, clarification_reply
        try:
            dlg = SecretaryClarificationDialog(clarification, self.window())
            if dlg.exec() != QDialog.Accepted:
                self._set_thinking_status("Cancelled")
                return
            reply = clarification_reply(payload, clarification, dlg.answer)
        except ValueError:
            self._set_thinking_status("Failed")
            return
        self._secretary_busy = True
        self.mode_selector.setEnabled(False)
        self._set_thinking_status("Eagle Eye Server: Planning")
        def done(response):
            reply["_preplanned"] = response.get("plan") or False
            self._secretary_execute_and_render(reply)
        def failed(message):
            self.append_output(message)
            self._set_thinking_status("Failed")
            self._finish_secretary_cycle()
        self._run_worker(lambda: {"plan": self._secretary_orchestrator.preplan(reply)}, done, failed)

    def _retire_worker(self, worker) -> None:
        # Drop the request handle before Qt deletes the finished worker.
        if self._worker is worker:
            self._worker = None
        try:
            self._workers.remove(worker)
        except (ValueError, AttributeError):
            pass
        try:
            worker.deleteLater()
        except Exception:
            pass

    def cleanup(self) -> None:
        """Stop every native and threaded resource BEFORE Qt frees this widget.

        Mirrors `OneChatPage.cleanup` in the EchoMind chat, which exists because
        destroying a parent while a child ApiWorker QThread is still running
        aborts the process with no traceback. This class had no teardown at all.

        Never `wait()` ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ that would freeze the GUI for the remaining read
        timeout, which is the whole thing the worker exists to avoid.
        """
        panel = getattr(self, "_response_panel", None)
        if panel is not None:
            panel.close()
        for task in tuple(getattr(self, "_execution_tasks", ())):
            task.cancel()
        try:
            self._rec_running = False
        except Exception:
            pass
        try:
            self._abort_audio_stream()
        except Exception:
            pass
        thread = getattr(self, "_rec_thread", None)
        if thread is not None:
            try:
                thread.join(timeout=1.0)
            except Exception:
                pass
            self._rec_thread = None

        for worker in list(getattr(self, "_workers", []) or []):
            try:
                if not worker.isRunning():
                    continue
            except Exception:
                continue
            for sig in ("done", "failed", "finished"):
                try:
                    getattr(worker, sig).disconnect()
                except Exception:
                    pass
            try:
                worker.setParent(None)
                _ORPHANED_SECRETARY_WORKERS.append(worker)
                worker.finished.connect(
                    lambda _w=worker: _release_orphan_secretary_worker(_w)
                )
            except Exception:
                pass
        try:
            self._workers = []
        except Exception:
            pass
        self._worker = None

        # Any straggler the list missed (a worker created by a future code path
        # that forgets to register) ط·آ£ط¢آ¢ط£آ¢أ¢â‚¬ع‘ط¢آ¬ط£آ¢أ¢â€ڑآ¬أ¢â‚¬إ’ same contract.
        try:
            from PySide6.QtCore import QThread
            for child in self.findChildren(QThread):
                try:
                    if not child.isRunning():
                        continue
                    child.setParent(None)
                    _ORPHANED_SECRETARY_WORKERS.append(child)
                    child.finished.connect(
                        lambda _w=child: _release_orphan_secretary_worker(_w)
                    )
                except Exception:
                    pass
        except Exception:
            pass

        try:
            self._fade_timer.stop()
        except Exception:
            pass

    def closeEvent(self, event):
        if self._response_panel is not None:
            self._response_panel.close()
        try:
            self.cleanup()
        except Exception:
            pass
        super().closeEvent(event)
