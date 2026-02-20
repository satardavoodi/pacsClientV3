"""
AI Pacs Loading Overlay
=======================
A reusable, branded full-screen loading overlay for the AI-PACS application.

Usage:
    from PacsClient.components.loading_overlay import AiPacsLoadingOverlay

    # Show
    overlay = AiPacsLoadingOverlay.show_overlay(
        parent_window,
        title="AI Pacs Image Analysis",
        status="Loading module...",
        subtitle="Preparing Advanced MPR and AI segmentation engine",
    )

    # Later — hide
    AiPacsLoadingOverlay.hide_overlay(overlay)

The overlay is modal (blocks mouse interaction with widgets behind it),
displays the AI Pacs logo with an animated spinner ring around it,
and includes animated status text.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QRect, QTimer, QRectF
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QPixmap,
    QConicalGradient,
    QFont,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
#  Resolve the logo path once at import time
# ---------------------------------------------------------------------------
def _resolve_logo_path() -> Path:
    """Return the absolute path to aiLogo.png, works in dev and PyInstaller."""
    try:
        from PacsClient.utils.config import IMAGES_LOGIN_PATH
        p = Path(IMAGES_LOGIN_PATH) / "aiLogo.png"
        if p.exists():
            return p
    except Exception:
        pass
    # Fallback: walk up from this file
    candidates = [
        Path(__file__).resolve().parents[2] / "Qss" / "images" / "aiLogo.png",
        Path(__file__).resolve().parents[3] / "Qss" / "images" / "aiLogo.png",
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path("Qss/images/aiLogo.png")  # last-resort relative


_LOGO_PATH: Path = _resolve_logo_path()


# ═══════════════════════════════════════════════════════════════════════════
#  Logo + spinner widget  (paints the logo in the center with rotating arcs)
# ═══════════════════════════════════════════════════════════════════════════
class _LogoSpinner(QWidget):
    """Custom QWidget that paints the AI Pacs logo with a rotating
    gradient ring around it."""

    OUTER_RADIUS = 68       # outer ring radius
    INNER_RADIUS = 54       # inner ring radius (gap between ring & logo)
    LOGO_SIZE = 80          # logo is drawn at 80×80 inside the ring
    WIDGET_SIZE = 160       # total widget dimensions

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(self.WIDGET_SIZE, self.WIDGET_SIZE)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")

        # Load the logo pixmap once
        self._logo: QPixmap | None = None
        if _LOGO_PATH.exists():
            px = QPixmap(str(_LOGO_PATH))
            if not px.isNull():
                self._logo = px.scaled(
                    self.LOGO_SIZE, self.LOGO_SIZE,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )

        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(20)  # ~50 fps

    def _tick(self):
        self._angle = (self._angle + 2.5) % 360.0
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2

        # ── 1.  Faint track circle ──────────────────────────────────
        track = QPen(QColor(60, 75, 100, 50))
        track.setWidth(4)
        p.setPen(track)
        r_track = QRect(
            int(cx - self.OUTER_RADIUS), int(cy - self.OUTER_RADIUS),
            self.OUTER_RADIUS * 2, self.OUTER_RADIUS * 2,
        )
        p.drawEllipse(r_track)

        # ── 2.  Gradient arc (rotating) ─────────────────────────────
        p.save()
        p.translate(cx, cy)
        p.rotate(self._angle)

        # Conical gradient for a smooth tail-off effect
        grad = QConicalGradient(0, 0, 0)
        grad.setColorAt(0.00, QColor(59, 130, 246, 255))   # #3b82f6 full
        grad.setColorAt(0.35, QColor(96, 165, 250, 200))   # #60a5fa
        grad.setColorAt(0.70, QColor(34, 211, 238, 120))   # #22d3ee
        grad.setColorAt(1.00, QColor(59, 130, 246, 0))     # fade to zero

        pen_arc = QPen()
        pen_arc.setBrush(grad)
        pen_arc.setWidth(5)
        pen_arc.setCapStyle(Qt.RoundCap)
        p.setPen(pen_arc)

        arc_rect = QRect(-self.OUTER_RADIUS, -self.OUTER_RADIUS,
                         self.OUTER_RADIUS * 2, self.OUTER_RADIUS * 2)
        p.drawArc(arc_rect, 0, 270 * 16)  # 270° arc with tail
        p.restore()

        # ── 3.  Second thinner ring (counter-rotate) ────────────────
        p.save()
        p.translate(cx, cy)
        p.rotate(-self._angle * 1.4)

        pen2 = QPen(QColor(124, 58, 237, 140))  # #7c3aed purple
        pen2.setWidth(2)
        pen2.setCapStyle(Qt.RoundCap)
        p.setPen(pen2)
        r2 = self.INNER_RADIUS + 4
        arc2 = QRect(-r2, -r2, r2 * 2, r2 * 2)
        p.drawArc(arc2, 0, 100 * 16)
        p.restore()

        # ── 4.  Pulsing glow behind logo ───────────────────────────
        # Subtle radial glow that breathes with the angle
        pulse = 0.5 + 0.5 * math.sin(math.radians(self._angle * 2))
        glow_alpha = int(20 + 30 * pulse)
        glow_r = int(self.LOGO_SIZE / 2 + 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(59, 130, 246, glow_alpha))
        p.drawEllipse(QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2))

        # ── 5.  Logo ────────────────────────────────────────────────
        if self._logo and not self._logo.isNull():
            lx = int(cx - self._logo.width() / 2)
            ly = int(cy - self._logo.height() / 2)
            p.drawPixmap(lx, ly, self._logo)

        p.end()


# ═══════════════════════════════════════════════════════════════════════════
#  AiPacsLoadingOverlay  (public API)
# ═══════════════════════════════════════════════════════════════════════════
class AiPacsLoadingOverlay(QWidget):
    """Full-window loading overlay with the AI Pacs logo, animated spinner,
    and status text.  Designed to be created once and shown/hidden.

    Class Methods
    -------------
    show_overlay(parent, ...)  →  AiPacsLoadingOverlay
    hide_overlay(overlay)
    """

    def __init__(
        self,
        parent: QWidget,
        title: str = "AI Pacs Image Analysis",
        status: str = "Please wait",
        subtitle: str = "",
    ):
        super().__init__(parent)
        self.setObjectName("AiPacsLoadingOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        # Cover the entire parent
        self.setGeometry(parent.rect())

        # Semi-transparent dark backdrop
        self.setStyleSheet(
            "QWidget#AiPacsLoadingOverlay { background: rgba(10, 14, 20, 210); }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignCenter)

        # ── Card ─────────────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("AiPacsLoaderCard")
        card.setFixedSize(440, 400)
        card.setStyleSheet("""
            QFrame#AiPacsLoaderCard {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1e293b, stop:1 #0f172a);
                border: 1px solid #334155;
                border-radius: 20px;
            }
        """)

        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(30, 28, 30, 28)
        card_lay.setSpacing(10)
        card_lay.setAlignment(Qt.AlignCenter)

        # Title
        lbl_title = QLabel(title)
        lbl_title.setObjectName("AiPacsLoaderTitle")
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet("""
            QLabel#AiPacsLoaderTitle {
                font-size: 20px; font-weight: 700;
                color: #60a5fa;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                background: transparent; border: none;
                letter-spacing: 0.6px;
            }
        """)
        card_lay.addWidget(lbl_title)
        card_lay.addSpacing(8)

        # Logo + spinner
        spinner = _LogoSpinner(card)
        card_lay.addWidget(spinner, alignment=Qt.AlignCenter)

        card_lay.addSpacing(8)

        # Status text with animated dots
        self._dots_n = 0
        self._status_base = status
        self._lbl_status = QLabel(status)
        self._lbl_status.setObjectName("AiPacsLoaderStatus")
        self._lbl_status.setAlignment(Qt.AlignCenter)
        self._lbl_status.setStyleSheet("""
            QLabel#AiPacsLoaderStatus {
                font-size: 14px; color: #cbd5e1;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                background: transparent; border: none;
            }
        """)
        card_lay.addWidget(self._lbl_status)

        # Subtitle
        if subtitle:
            lbl_sub = QLabel(subtitle)
            lbl_sub.setObjectName("AiPacsLoaderSub")
            lbl_sub.setAlignment(Qt.AlignCenter)
            lbl_sub.setWordWrap(True)
            lbl_sub.setStyleSheet("""
                QLabel#AiPacsLoaderSub {
                    font-size: 11px; color: #64748b;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                    background: transparent; border: none;
                }
            """)
            card_lay.addWidget(lbl_sub)

        outer.addWidget(card, alignment=Qt.AlignCenter)

        # ── Dots animation timer ─────────────────────────────────────
        self._dots_timer = QTimer(self)
        self._dots_timer.timeout.connect(self._tick_dots)
        self._dots_timer.start(420)

    # ── helpers ──────────────────────────────────────────────────────
    def _tick_dots(self):
        self._dots_n = (self._dots_n + 1) % 4
        self._lbl_status.setText(self._status_base + "." * self._dots_n)

    def set_status(self, text: str):
        """Update the main status text (the dots animation adjusts)."""
        self._status_base = text
        self._lbl_status.setText(text)

    # ── class-level show / hide API ──────────────────────────────────
    @classmethod
    def show_overlay(
        cls,
        parent: QWidget,
        title: str = "AI Pacs Image Analysis",
        status: str = "Please wait",
        subtitle: str = "",
    ) -> "AiPacsLoadingOverlay":
        """Create, paint, and return the overlay (already visible).

        Call ``AiPacsLoadingOverlay.hide_overlay(ref)`` when done.
        """
        overlay = cls(parent, title=title, status=status, subtitle=subtitle)
        overlay.raise_()
        overlay.show()
        # Force the event loop to paint the overlay immediately
        QApplication.processEvents()
        QApplication.processEvents()
        return overlay

    @staticmethod
    def hide_overlay(overlay: Optional["AiPacsLoadingOverlay"]):
        """Safely hide and schedule deletion of *overlay*."""
        if overlay is not None:
            overlay.hide()
            overlay.deleteLater()
