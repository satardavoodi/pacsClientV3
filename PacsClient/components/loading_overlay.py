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
import os
import contextlib
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt, QEvent, QRect, QTimer, QRectF, QPropertyAnimation, QEasingCurve,
)
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
    QProgressBar,
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
    # Fallback: use _project_root
    try:
        from _project_root import PROJECT_ROOT
        p = PROJECT_ROOT / "Qss" / "images" / "aiLogo.png"
        if p.exists():
            return p
    except Exception:
        pass
    return Path("Qss/images/aiLogo.png")  # last-resort relative


_LOGO_PATH: Path = _resolve_logo_path()


def _window_transparent_for_input_flag():
    """Best-effort access to Qt's top-level input-transparent window flag."""
    with contextlib.suppress(Exception):
        return Qt.WindowType.WindowTransparentForInput
    with contextlib.suppress(Exception):
        return Qt.WindowTransparentForInput
    return None


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
    ROTATION_STEP_DEGREES = 1.2
    FRAME_INTERVAL_MS = 30

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
        self._timer.start(self.FRAME_INTERVAL_MS)

    def _tick(self):
        self._angle = (self._angle + self.ROTATION_STEP_DEGREES) % 360.0
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
def _anchor_has_native_render_window(anchor) -> bool:
    """True when the anchor hosts a NATIVE OS render surface (VTK / OpenGL) that a
    Qt child overlay cannot paint over.

    The FAST (pydicom / QPainter) viewport — the default — is pure Qt and returns
    False, so its loading overlay can be a normal CHILD widget (clipped to the
    viewport, correctly layered, never floating above other apps). Only a real
    VTK/Advanced viewport needs the legacy top-level always-on-top window. Any
    failure → False (prefer the child overlay; it is the common case)."""
    try:
        if anchor is None:
            return False
        candidates = [anchor]
        try:
            candidates += list(anchor.findChildren(QWidget))
        except Exception:
            pass
        for w in candidates:
            try:
                _cn = type(w).__name__
                if ("VTK" in _cn or "vtk" in _cn or "GLWidget" in _cn
                        or "OpenGL" in _cn):
                    return True
                # VTK/OpenGL surfaces paint on a native window handle.
                if w.testAttribute(Qt.WA_PaintOnScreen):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


class AiPacsLoadingOverlay(QWidget):
    """Loading overlay. In FAST mode it is a **child of the target viewport** (so it
    is clipped, correctly layered above the image/metadata/annotations, and never
    floats above other apps). Only when the anchor hosts a native VTK/OpenGL surface
    does it fall back to a **top-level frameless always-on-top window** to paint
    above that native surface.

    Regular child-widget overlays are always painted *behind* VTK render
    windows because VTK uses native OS window handles.  Making the overlay
    a top-level ``Qt.Tool`` window with ``WindowStaysOnTopHint`` is the
    only reliable way to appear above them.

    The overlay tracks its *anchor widget* (the widget it was shown over)
    and repositions itself whenever the anchor moves or resizes.

    Class Methods
    -------------
    show_overlay(parent, ...)  →  AiPacsLoadingOverlay
    hide_overlay(overlay)
    """

    def __init__(
        self,
        anchor: QWidget,
        title: str = "AI Pacs Image Analysis",
        status: str = "Please wait",
        subtitle: str = "",
        minimal: bool = False,
        pass_through: bool = False,
        child_mode: Optional[bool] = None,
    ):
        # ── Layering fix (2026-06-24) ─────────────────────────────────────────
        # Be a CHILD of the viewport when possible. The overlay used to be a
        # top-level Qt.Tool + WindowStaysOnTopHint window — the only way to paint
        # above a NATIVE VTK/OpenGL render window — but that made it a separate OS
        # window: it floated above OTHER apps (Chrome) and was never a real layer
        # in the viewport stack (so the gif / black box / metadata / image /
        # annotations layered wrongly). In FAST mode (the default — NO native VTK
        # window) the viewport is pure Qt, so the overlay is just a CHILD widget of
        # the anchor: clipped to it, raised above its content, hidden/destroyed
        # with it. Fall back to the legacy top-level window ONLY when the anchor
        # actually hosts a native render surface. Kill switch (force legacy
        # top-level): AIPACS_OVERLAY_CHILD_MODE=0.
        if child_mode is None:
            _child_enabled = (os.getenv("AIPACS_OVERLAY_CHILD_MODE", "1") or "1").strip() != "0"
            child_mode = bool(_child_enabled) and not _anchor_has_native_render_window(anchor)
        self._child_mode = bool(child_mode)

        if self._child_mode:
            # Child overlay — a real layer inside the viewport.
            super().__init__(anchor)
        else:
            # Legacy top-level frameless tool window — floats above VTK surfaces.
            super().__init__(
                None,
                Qt.Tool
                | Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint,
            )
            self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setObjectName("AiPacsLoadingOverlay")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._minimal = bool(minimal)
        self._pass_through = bool(pass_through)

        if self._pass_through:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            if not self._child_mode:
                _transparent_input_flag = _window_transparent_for_input_flag()
                if _transparent_input_flag is not None:
                    self.setWindowFlag(_transparent_input_flag, True)

        # Keep a reference to the widget we're covering
        self._anchor = anchor

        # Cover the anchor (local rect as a child; global coords as a top-level).
        self._sync_geometry()

        # Watch the anchor (and its top window) for move / resize
        anchor.installEventFilter(self)
        top = anchor.window()
        if top and top is not anchor:
            top.installEventFilter(self)

        # ── Overlay scoping (2026-06-24, Issue 1) ─────────────────────────────
        # This overlay is a TOP-LEVEL Qt.Tool + WindowStaysOnTopHint window — the
        # only reliable way to paint above native VTK/OpenGL viewports. Left
        # unscoped, that also made it float above OTHER applications (e.g. Chrome)
        # and linger after a patient-tab switch. Scope it to the app + anchor:
        # hide whenever the APPLICATION loses focus to another app (so it never
        # covers another program), and whenever the anchor viewport hides (tab
        # switch / dispose); restore when focus + anchor return and loading is
        # still intended. ``_intended_visible`` is the loading state the show/hide
        # API drives. Intra-app window/tab changes do NOT fire
        # applicationStateChanged, so this never self-hides on activateWindow().
        # Kill switch: AIPACS_OVERLAY_SCOPED=0.
        self._intended_visible = True
        # A CHILD overlay is already clipped to the viewport, so it can never float
        # above another app or linger on a tab switch — no app-state scoping needed.
        # Only the top-level (VTK) fallback needs it.
        self._scoped = (not self._child_mode) and (
            os.getenv("AIPACS_OVERLAY_SCOPED", "1") or "1"
        ).strip() != "0"
        if self._scoped:
            try:
                _app = QApplication.instance()
                if _app is not None:
                    _app.applicationStateChanged.connect(self._on_app_state_changed)
            except Exception:
                pass

        # Semi-transparent dark backdrop (painted via paintEvent for
        # true translucent background on a top-level window)
        self._bg_color = QColor(10, 14, 20, 210)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignCenter)

        if self._minimal:
            spinner = _LogoSpinner(self)
            outer.addWidget(spinner, alignment=Qt.AlignCenter)
            self._dots_n = 0
            self._status_base = status or ""
            # Minimal overlay grows an optional, compact "download card" used by the
            # drag-drop loading state: an identity line, a status line, a thin
            # progress bar, and a detail line (speed/ETA/elapsed). Every element
            # stays empty/hidden until set_loading_details()/set_status() populates
            # it, so the plain waiting spinner looks exactly as before when idle.
            # (No dots timer in minimal mode — a live count reads better.)
            outer.addSpacing(10)

            # Identity line (e.g. "MR · Series 4 · T2 FLAIR") — bold, on top.
            self._lbl_title = QLabel("", self)
            self._lbl_title.setObjectName("AiPacsLoaderIdentityMinimal")
            self._lbl_title.setAlignment(Qt.AlignCenter)
            self._lbl_title.setStyleSheet("""
                QLabel#AiPacsLoaderIdentityMinimal {
                    font-size: 14px; font-weight: 700; color: #f1f5f9;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                    background: transparent; border: none; letter-spacing: 0.3px;
                }
            """)
            self._lbl_title.setVisible(False)
            outer.addWidget(self._lbl_title, alignment=Qt.AlignCenter)

            # Status line ("Downloading 12 of 25 · 48%", "Reconnecting…", etc.).
            self._lbl_status = QLabel(self._status_base, self)
            self._lbl_status.setObjectName("AiPacsLoaderStatusMinimal")
            self._lbl_status.setAlignment(Qt.AlignCenter)
            self._lbl_status.setStyleSheet("""
                QLabel#AiPacsLoaderStatusMinimal {
                    font-size: 13px; font-weight: 600; color: #e2e8f0;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                    background: transparent; border: none; letter-spacing: 0.3px;
                }
            """)
            self._lbl_status.setVisible(bool(self._status_base))
            outer.addSpacing(4)
            outer.addWidget(self._lbl_status, alignment=Qt.AlignCenter)

            # Thin determinate progress bar (hidden until a fraction is set, so
            # indeterminate states like "Connecting…" show no bar).
            self._progress_bar = QProgressBar(self)
            self._progress_bar.setObjectName("AiPacsLoaderBarMinimal")
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setTextVisible(False)
            self._progress_bar.setFixedSize(220, 6)
            self._progress_bar.setStyleSheet("""
                QProgressBar#AiPacsLoaderBarMinimal {
                    background: rgba(148,163,184,0.25); border: none;
                    border-radius: 3px;
                }
                QProgressBar#AiPacsLoaderBarMinimal::chunk {
                    background: #3b82f6; border-radius: 3px;
                }
            """)
            self._progress_bar.setVisible(False)
            outer.addSpacing(6)
            outer.addWidget(self._progress_bar, alignment=Qt.AlignCenter)

            # Detail line (speed · ETA · elapsed) — smaller, quieter.
            self._lbl_detail = QLabel("", self)
            self._lbl_detail.setObjectName("AiPacsLoaderDetailMinimal")
            self._lbl_detail.setAlignment(Qt.AlignCenter)
            self._lbl_detail.setStyleSheet("""
                QLabel#AiPacsLoaderDetailMinimal {
                    font-size: 11px; color: #94a3b8;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                    background: transparent; border: none;
                }
            """)
            self._lbl_detail.setVisible(False)
            outer.addSpacing(4)
            outer.addWidget(self._lbl_detail, alignment=Qt.AlignCenter)
            return

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

    # ── geometry sync ────────────────────────────────────────────────
    def _sync_geometry(self):
        """Reposition/resize to cover the anchor widget exactly."""
        a = self._anchor
        if a is None or not a.isVisible():
            return
        if getattr(self, "_child_mode", False):
            # Child of the anchor: cover its full client rect in LOCAL coords and
            # stay raised above the anchor's image / metadata / annotation layers.
            self.setGeometry(0, 0, a.width(), a.height())
            try:
                self.raise_()
            except Exception:
                pass
            return
        global_pos = a.mapToGlobal(a.rect().topLeft())
        self.setGeometry(global_pos.x(), global_pos.y(), a.width(), a.height())

    # ── paint the translucent backdrop ───────────────────────────────
    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self._bg_color)
        p.end()

    # ── resize / move tracking via event filter ──────────────────────
    def eventFilter(self, obj, event):
        """Follow anchor widget moves/resizes; scope visibility to the anchor so
        the overlay is dropped on a patient-tab switch / viewport dispose
        (2026-06-24, Issue 1)."""
        etype = event.type()
        if etype in (QEvent.Resize, QEvent.Move):
            self._sync_geometry()
        elif getattr(self, "_scoped", False) and obj is self._anchor:
            if etype == QEvent.Hide:
                # Anchor viewport hidden (tab switch / dispose) → don't linger.
                try:
                    self.hide()
                except Exception:
                    pass
            elif etype == QEvent.Show and getattr(self, "_intended_visible", True):
                try:
                    self._sync_geometry()
                    self.show()
                    self.raise_()
                except Exception:
                    pass
        return super().eventFilter(obj, event)

    def _on_app_state_changed(self, state):
        """Hide while another APPLICATION is in front (a top-level always-on-top
        overlay must never float above other apps), restore when AI-PACS regains
        focus and loading is still intended (2026-06-24, Issue 1)."""
        if not getattr(self, "_scoped", False):
            return
        try:
            if state != Qt.ApplicationActive:
                self.hide()
            elif getattr(self, "_intended_visible", True) \
                    and self._anchor is not None and self._anchor.isVisible():
                self._sync_geometry()
                self.show()
                self.raise_()
        except Exception:
            pass

    # ── helpers ──────────────────────────────────────────────────────
    def _tick_dots(self):
        self._dots_n = (self._dots_n + 1) % 4
        if self._lbl_status is not None:
            self._lbl_status.setText(self._status_base + "." * self._dots_n)

    def set_status(self, text: str):
        """Update the main status text (the dots animation adjusts)."""
        self._status_base = text
        if self._lbl_status is not None:
            self._lbl_status.setText(text)
            if self._minimal:
                # Minimal overlay only reveals its status line when it has text,
                # so the plain waiting spinner is visually unchanged when idle.
                try:
                    self._lbl_status.setVisible(bool(text))
                except Exception:
                    pass

    def set_loading_details(self, *, title=None, status=None, detail=None, fraction=None):
        """Update the rich download-loading fields on the minimal overlay.

        All keyword-only and independent: pass only what changed. ``title`` is the
        series-identity line, ``status`` the main line (progress text / connection
        state), ``detail`` the small speed/ETA/elapsed line, and ``fraction`` a
        0..1 progress value (``None`` hides the bar for indeterminate states like
        "Connecting…"). Each element is shown only when it has content, so the plain
        spinner is unchanged when nothing is set. Best-effort: never raises.
        """
        try:
            if status is not None:
                self.set_status(status)
            lbl_title = getattr(self, "_lbl_title", None)
            if title is not None and lbl_title is not None:
                lbl_title.setText(str(title))
                lbl_title.setVisible(bool(title))
            lbl_detail = getattr(self, "_lbl_detail", None)
            if detail is not None and lbl_detail is not None:
                lbl_detail.setText(str(detail))
                lbl_detail.setVisible(bool(detail))
            bar = getattr(self, "_progress_bar", None)
            if bar is not None:
                if fraction is None:
                    bar.setVisible(False)
                else:
                    try:
                        pct = max(0, min(100, int(round(float(fraction) * 100))))
                    except Exception:
                        pct = 0
                    bar.setValue(pct)
                    bar.setVisible(True)
        except Exception:
            pass

    # ── class-level show / hide API ──────────────────────────────────
    @classmethod
    def show_overlay(
        cls,
        parent: QWidget,
        title: str = "AI Pacs Image Analysis",
        status: str = "Please wait",
        subtitle: str = "",
        minimal: bool = False,
        pass_through: bool = False,
    ) -> "AiPacsLoadingOverlay":
        """Create, paint, and return the overlay (already visible).

        *parent* is the widget the overlay should cover (e.g. the center
        viewer area).  The overlay is a top-level window that floats above
        native VTK/OpenGL surfaces.

        Call ``AiPacsLoadingOverlay.hide_overlay(ref)`` when done.
        """
        overlay = cls(
            parent,
            title=title,
            status=status,
            subtitle=subtitle,
            minimal=minimal,
            pass_through=pass_through,
        )
        overlay.show()
        overlay.raise_()
        if not pass_through:
            overlay.activateWindow()
        # Force the event loop to paint the overlay immediately
        QApplication.processEvents()
        QApplication.processEvents()
        return overlay

    @staticmethod
    def hide_overlay(
        overlay: Optional["AiPacsLoadingOverlay"],
        fade_ms: int = 500,
        delay_ms: int = 0,
    ):
        """Fade-out then hide and delete *overlay*.

        Args:
            overlay:  The overlay instance (or None — safe to pass).
            fade_ms:  Duration of the opacity fade-out (default 500 ms).
            delay_ms: Extra delay *before* starting the fade (default 0).
        """
        if overlay is None:
            return

        # Mark the loading state as ended so the app-state / anchor scoping
        # (Issue 1) does not re-show the overlay during/after the fade-out.
        try:
            overlay._intended_visible = False
        except Exception:
            pass

        def _start_fade():
            # Production-crash guard (other-PC frozen build, 2026-06-05
            # evaluation): 1× native access violation HERE — the overlay's
            # C++ object was already destroyed (series-switch teardown raced
            # the fade), so QPropertyAnimation(overlay,…)/windowOpacity()
            # dereferenced a deleted QWidget. Check liveness first; a dying
            # overlay must never take the whole process down.
            try:
                import shiboken6
                if not shiboken6.isValid(overlay):
                    return
            except ImportError:
                pass
            try:
                # Animate windowOpacity from 1.0 → 0.0
                anim = QPropertyAnimation(overlay, b"windowOpacity")
                anim.setDuration(fade_ms)
                anim.setStartValue(overlay.windowOpacity())
                anim.setEndValue(0.0)
                anim.setEasingCurve(QEasingCurve.InOutQuad)
                # Once the animation finishes, actually remove the overlay
                anim.finished.connect(lambda: _cleanup(overlay))
                # Store a reference so it isn't garbage-collected mid-animation
                overlay._fade_anim = anim
                anim.start()
            except RuntimeError:
                # Qt wrapper died between the liveness check and use —
                # nothing left to fade; best-effort cleanup only.
                _cleanup(overlay)

        def _cleanup(ov):
            try:
                ov.hide()
                ov.deleteLater()
            except Exception:
                pass

        if delay_ms > 0:
            QTimer.singleShot(delay_ms, _start_fade)
        else:
            _start_fade()
