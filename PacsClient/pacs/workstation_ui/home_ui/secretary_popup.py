"""SecretaryPopup — global F12 overlay for the EchoMind Secretary (2026-06-06).

Hosts its OWN ``SecretaryButtonWidget`` instance (the same class as the orb
under the home-page patient search) inside a frameless, always-on-top,
NON-MODAL tool window, so the assistant is reachable from any module/page
without touching the home-page widget or stealing input from the app below.

Behavior contract:
* F12 anywhere → ``SecretaryPopup.toggle_for(main_window)`` (registered in
  ``shortcut_manager``). First press creates the singleton lazily; later
  presses toggle visibility.
* Non-blocking: ``Qt.Tool`` window — the user keeps interacting with the
  app underneath (no modality, no input grab).
* X button (or any close) cancels an in-flight recording SAFELY via the
  widget's ``cancel_recording()`` (capture discarded, never sent to STT),
  then hides — the instance is reused, so session/memory state survives.
* The home-page secretary widget is untouched: this is a separate instance
  with its own orchestrator session.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget,
)


def _default_inner_factory() -> QWidget:
    # Imported lazily — secretary_button_widget pulls in audio deps
    # (sounddevice/soundfile) that must not load at app start for F12's sake.
    from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import (
        SecretaryButtonWidget,
    )
    return SecretaryButtonWidget()


class SecretaryPopup(QWidget):
    """Frameless, draggable, always-on-top host for the Secretary widget."""

    _instance: Optional["SecretaryPopup"] = None

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        inner_factory: Optional[Callable[[], QWidget]] = None,
    ) -> None:
        super().__init__(parent)
        # Tool window: floats above the app, has no taskbar entry, and —
        # critically — is NOT modal and does NOT grab input (unlike Qt.Popup),
        # so the UI underneath stays fully interactive.
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setWindowTitle("EchoMind Secretary")
        self._drag_offset: Optional[QPoint] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)

        # ── title bar: brand + X ────────────────────────────────────────
        self._title_bar = QWidget(self)
        bar = QHBoxLayout(self._title_bar)
        bar.setContentsMargins(4, 0, 0, 0)
        bar.setSpacing(6)
        self._title_lbl = QLabel("EchoMind Secretary", self._title_bar)
        self.close_btn = QToolButton(self._title_bar)
        self.close_btn.setObjectName("secretaryPopupClose")
        self.close_btn.setText("✕")
        self.close_btn.setToolTip("Close (cancels listening if active)")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setFixedSize(26, 26)
        self.close_btn.clicked.connect(self.request_close)
        bar.addWidget(self._title_lbl)
        bar.addStretch(1)
        bar.addWidget(self.close_btn)
        root.addWidget(self._title_bar)

        # ── the secretary widget itself (own instance) ──────────────────
        self.inner = (inner_factory or _default_inner_factory)()
        root.addWidget(self.inner, 1)

        self.setMinimumWidth(330)
        self._apply_style()

    # ── styling (V2 tokens with safe fallback) ──────────────────────────
    def _apply_style(self) -> None:
        panel, border, text, muted, accent = (
            "#111927", "#2d3748", "#f8fafc", "#93a4b7", "#3182ce")
        try:
            from PacsClient.utils.theme_manager import get_theme_manager
            t = get_theme_manager().current_theme()
            panel = t.get("card_bg", panel)
            border = t.get("border", border)
            text = t.get("text_primary", text)
            muted = t.get("text_muted", muted)
            accent = t.get("accent", accent)
        except Exception:
            pass
        self.setStyleSheet(
            "SecretaryPopup { background: " + panel + "; border: 1px solid "
            + border + "; border-radius: 12px; }\n"
            "QLabel { color: " + muted + "; font-size: 11px; font-weight: 700;"
            " letter-spacing: 0.5px; font-family: 'Roboto', sans-serif;"
            " background: transparent; border: none; }\n"
            "QToolButton#secretaryPopupClose { color: " + text + ";"
            " background: transparent; border: 1px solid transparent;"
            " border-radius: 8px; font-size: 13px; }\n"
            "QToolButton#secretaryPopupClose:hover { border: 1px solid "
            + accent + "; background: rgba(49, 130, 206, 0.16); }\n"
        )

    # ── close semantics ─────────────────────────────────────────────────
    def _cancel_active_work(self) -> None:
        """Safely stop anything the inner widget is doing. Never raises."""
        try:
            cancel = getattr(self.inner, "cancel_recording", None)
            if callable(cancel):
                cancel()
        except Exception:
            pass

    def request_close(self) -> None:
        """X button / programmatic close: cancel then hide (instance reused)."""
        self._cancel_active_work()
        self.hide()

    def closeEvent(self, event):  # noqa: N802 — Qt override
        # Covers OS-level closes (Alt+F4 on the tool window): same safety.
        self._cancel_active_work()
        event.ignore()
        self.hide()

    # ── frameless drag (title bar) ──────────────────────────────────────
    def mousePressEvent(self, event):  # noqa: N802
        if (event.button() == Qt.LeftButton
                and event.position().y() <= self._title_bar.height() + 10):
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    # ── singleton toggle (the F12 entry point) ──────────────────────────
    @classmethod
    def toggle_for(
        cls,
        main_window: Optional[QWidget],
        inner_factory: Optional[Callable[[], QWidget]] = None,
    ) -> "SecretaryPopup":
        """Create-once / show / hide. Never raises into the shortcut path."""
        inst = cls._instance
        if inst is None:
            inst = cls(parent=main_window, inner_factory=inner_factory)
            cls._instance = inst
        if inst.isVisible():
            inst.request_close()
            return inst
        inst._position_over(main_window)
        inst.show()
        inst.raise_()
        try:
            inst.activateWindow()
        except Exception:
            pass
        return inst

    def _position_over(self, main_window: Optional[QWidget]) -> None:
        """Lower-left of the main window (mirrors the home-page placement),
        clamped to the available screen. Keeps a user-dragged position on
        re-open within the same session."""
        if getattr(self, "_user_positioned", False):
            return
        try:
            self.adjustSize()
            if main_window is not None and main_window.isVisible():
                geo = main_window.geometry()
                x = geo.x() + 24
                y = geo.y() + geo.height() - self.height() - 48
            else:
                screen = self.screen() or None
                avail = screen.availableGeometry() if screen else None
                if avail is None:
                    return
                x = avail.x() + 24
                y = avail.y() + avail.height() - self.height() - 48
            self.move(max(0, x), max(0, y))
        except Exception:
            pass

    def moveEvent(self, event):  # noqa: N802
        # After the user drags it somewhere, respect that position next time.
        if self._drag_offset is not None:
            self._user_positioned = True
        super().moveEvent(event)


__all__ = ["SecretaryPopup"]
