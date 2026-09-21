"""Visible, input-guarded browser opening without changing synchronous callers.

No WebEngine import at module scope. The cold engine still runs on GUI; this
notice explains that wait, it does not make the atomic native startup responsive.
"""

from __future__ import annotations

import logging
import time
import weakref

from PySide6.QtCore import QEvent, QTimer, Qt, Slot
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QProgressBar, QVBoxLayout
from shiboken6 import isValid

logger = logging.getLogger(__name__)
_NOTICE_ATTR = "_web_browser_launch_notice"


class _BrowserLaunchNotice(QFrame):
    """Temporary shell-header status strip and application-local input gate.

    A new top-level dialog cannot reliably paint before its first expose event.
    A child of the existing shell can repaint synchronously without dispatching
    unrelated queued work. Keep it over the Qt header, not native VTK viewports.
    """

    _INPUT_EVENTS = frozenset({
        QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseMove,
        QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.Shortcut,
        QEvent.Type.ShortcutOverride, QEvent.Type.Wheel, QEvent.Type.ContextMenu,
        QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd,
        QEvent.Type.TabletPress, QEvent.Type.TabletMove, QEvent.Type.TabletRelease,
        QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop,
    })

    def __init__(self, owner):
        super().__init__(owner.window())
        self._owner_ref = weakref.ref(owner)
        self._active = True
        self.result = None
        self.setObjectName("browserLaunchNotice")
        self.setAccessibleName("Web Browser initialization status")
        self.setStyleSheet(
            "QFrame#browserLaunchNotice { background: #172b43; border: 1px solid #529fe5; }"
            "QFrame#browserLaunchNotice QLabel { color: #ffffff; background: transparent; border: none; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(4)
        self._status = QLabel("Opening Web Browser - Please wait", self)
        font = self._status.font()
        font.setBold(True)
        self._status.setFont(font)
        layout.addWidget(self._status)
        detail = QLabel(
            "Initializing the browser engine. Other controls are temporarily locked.\n"
            "First use may take longer; the indicator may pause during initialization.", self)
        detail.setWordWrap(True)
        layout.addWidget(detail)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)  # Unknown duration, never fabricated percent.
        self._progress.setTextVisible(False)
        self._progress.setMaximumHeight(8)
        layout.addWidget(self._progress)
        self._release_timer = QTimer(self)
        self._release_timer.setSingleShot(True)
        self._release_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._release_timer.timeout.connect(self.release)
        self._sync_geometry()

    def _sync_geometry(self):
        anchor = self.parentWidget()
        self.setGeometry(0, 0, anchor.width(), min(anchor.height(), self.sizeHint().height()))

    def present(self):
        QApplication.instance().installEventFilter(self)
        self.show()
        self.raise_()
        self.repaint()  # Paint only. Never processEvents()/exec() in a constructor path.

    def eventFilter(self, obj, event):
        if not self._active:
            return False
        kind = event.type()
        if kind in self._INPUT_EVENTS:
            event.accept()
            return True
        if obj is self.parentWidget():
            if kind == QEvent.Type.Close:
                event.ignore()  # Cannot cancel an atomic native constructor safely.
                return True
            if kind == QEvent.Type.Resize:
                self._sync_geometry()
                self.raise_()
        return False

    def finish(self, result):
        self.result = result
        self._status.setText("Web Browser ready" if result is not None else "Web Browser could not be opened")
        self._progress.hide()
        # Return to the normal event loop with the gate still installed, so
        # queued clicks/keys from the blocked interval are discarded, not replayed.
        # This is a short input-drain grace, not a sleep or startup timeout.
        self._release_timer.start(150)

    @Slot()
    def release(self):
        if not self._active:
            return
        self._active = False
        self._release_timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        owner = self._owner_ref()
        if owner is not None and isValid(owner) and getattr(owner, _NOTICE_ATTR, None) is self:
            setattr(owner, _NOTICE_ATTR, None)
        self.hide()
        self.deleteLater()


def open_browser_tab(owner, tab_widget, custom_tab_manager):
    """Same Widget-or-None contract for Home, OAuth and CommandBus callers."""
    from PacsClient.pacs.workstation_ui.home_ui.home_module_tabs import (
        activate_or_create_module_tab, find_existing_module_tab,
    )

    previous = getattr(owner, _NOTICE_ATTR, None)
    if previous is not None and isValid(previous) and previous._active:
        return previous.result  # No recursive construction or second notice.

    def activate(factory):
        return activate_or_create_module_tab(
            tab_widget, custom_tab_manager, tab_flag_key="is_web_browser_tab",
            widget_factory=factory, add_tab_method_name="add_web_browser_tab",
            fallback_label="Web Browser",
        )

    existing = find_existing_module_tab(tab_widget, custom_tab_manager, "is_web_browser_tab")
    if existing is not None:
        return activate(lambda: None)  # Existing-tab activation cannot invoke the factory.

    notice = _BrowserLaunchNotice(owner)
    setattr(owner, _NOTICE_ATTR, notice)
    result = None
    started = time.monotonic()
    try:
        notice.present()
        logger.info("[WEB_BROWSER_LAUNCH] phase=opening")
        import_started = time.monotonic()
        from modules.web_browser import WebBrowserWidget
        imported = time.monotonic()
        result = activate(WebBrowserWidget)
        constructed = time.monotonic()
        logger.info(
            "[WEB_BROWSER_LAUNCH] phase=ready import_ms=%.2f construct_ms=%.2f total_ms=%.2f",
            (imported - import_started) * 1000, (constructed - imported) * 1000,
            (constructed - started) * 1000,
        )
        # Marker is preserved; prewarm remains explicitly opt-in, never enabled here.
        try:
            from modules.web_browser.prewarm import mark_browser_used
            mark_browser_used()
        except Exception:
            logger.debug("browser-used marker could not be recorded", exc_info=True)
        return result
    finally:
        if isValid(notice):
            notice.finish(result)
