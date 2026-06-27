"""Adaptive QtWebEngine pre-warm for fast Web Browser opens (2026-06-27).

The first time a ``QWebEngineView`` is constructed the entire Chromium engine
boots **synchronously on the GUI thread** (big DLL load + global V8/ICU/GPU
init + ``QtWebEngineProcess`` spawn). That cold boot is the ~20 s "browser
opens slowly" delay. Qt widgets are GUI-thread-only, so the construction
itself cannot move off the GUI thread — but we CAN:

* pay the heavy **DLL load** on a daemon thread (pure ``import`` — thread-safe,
  touches no Qt object), and
* pay the **engine construction** during **idle**, once, instead of on the
  user's click.

**Adaptive policy (default).** Pre-warm only in sessions *after* the user has
opened the Web Browser at least once (a marker file in the browser state
dir). A workstation that never uses the browser never loads Chromium; one
that does gets near-instant opens from the next session on.

Everything here is best-effort and fully guarded: a pre-warm failure must
NEVER affect app/home startup or the clinical UI. This module imports only
stdlib + ``PySide6.QtCore`` at top level (NOT QtWebEngine), so importing it
is cheap.

Kill switch: ``AIPACS_BROWSER_PREWARM=0``.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_MARKER_NAME = ".browser_used"

_scheduled = False   # one pre-warm per process
_warm_view = None    # keep the throwaway view alive during the warm window
_warm_ctl = None     # keep the controller (and its signal connection) alive


def _state_dir() -> Path:
    try:
        from PacsClient.utils.data_paths import BROWSER_STATE_DIR
        d = Path(BROWSER_STATE_DIR)
    except Exception:
        d = Path.home() / ".aipacs_web_browser"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _marker_path() -> Path:
    return _state_dir() / _MARKER_NAME


def mark_browser_used() -> None:
    """Record that the user has opened the Web Browser at least once.

    Best-effort — a failure here must never disturb opening the browser.
    """
    try:
        _marker_path().write_text("1", encoding="utf-8")
    except Exception:
        logger.debug("browser prewarm: could not write used-marker", exc_info=True)


def should_prewarm() -> bool:
    """True when an idle pre-warm should run this session (adaptive policy)."""
    if os.environ.get("AIPACS_BROWSER_PREWARM", "1") == "0":
        return False
    try:
        return _marker_path().exists()
    except Exception:
        return False


def schedule_prewarm(delay_ms: int = 4000) -> bool:
    """Schedule a one-time, idle, background QtWebEngine pre-warm.

    Returns True when a pre-warm was scheduled. No-op (returns False) when
    disabled, the browser has never been used, already scheduled this
    process, or Qt is unavailable. The calling thread NEVER imports
    QtWebEngine — the DLL load runs on a daemon thread and only the final
    ``QWebEngineView`` construction (which must be GUI-thread) is posted back
    to the GUI thread, deferred ``delay_ms`` so it never competes with the
    login/home paint.
    """
    global _scheduled, _warm_ctl
    if _scheduled:
        return False
    if not should_prewarm():
        return False
    try:
        from PySide6.QtCore import QObject, QTimer, Signal
    except Exception:
        return False
    _scheduled = True

    class _PrewarmController(QObject):
        construct = Signal()

        def __init__(self) -> None:
            super().__init__()
            # Worker-thread emit → queued delivery onto the GUI thread
            # (the connection target lives on the GUI thread).
            self.construct.connect(self._on_construct)

        def kick(self) -> None:
            def _bg_import() -> None:
                try:
                    import PySide6.QtWebEngineCore  # noqa: F401 (DLL load off GUI thread)
                    import PySide6.QtWebEngineWidgets  # noqa: F401
                except Exception:
                    logger.debug("browser prewarm: QtWebEngine import failed",
                                 exc_info=True)
                    return
                try:
                    self.construct.emit()  # hop to the GUI thread
                except Exception:
                    logger.debug("browser prewarm: emit failed", exc_info=True)

            threading.Thread(target=_bg_import, name="browser-prewarm-import",
                             daemon=True).start()

        def _on_construct(self) -> None:
            _construct_warm_view()

    _warm_ctl = _PrewarmController()
    QTimer.singleShot(max(0, int(delay_ms)), _warm_ctl.kick)
    logger.info("browser prewarm: scheduled (delay=%dms)", int(delay_ms))
    return True


def _construct_warm_view() -> None:
    """Construct a hidden ``QWebEngineView`` once to amortize Chromium's global
    init on the GUI thread. The global engine stays warm for the process after
    the throwaway view is released, so the user's first real browser open is
    fast. Never shown — no window appears.
    """
    global _warm_view
    if _warm_view is not None:
        return
    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception:
        logger.debug("browser prewarm: widgets import failed", exc_info=True)
        return
    try:
        view = QWebEngineView()           # offscreen, never shown
        view.setUrl(QUrl("about:blank"))
        _warm_view = view
        logger.info("browser prewarm: Chromium engine warmed")
    except Exception:
        logger.debug("browser prewarm: view construction failed", exc_info=True)
        return

    def _release() -> None:
        global _warm_view
        try:
            if _warm_view is not None:
                _warm_view.deleteLater()
        except Exception:
            pass
        _warm_view = None

    # Hold briefly so Chromium finishes booting, then drop the render process
    # (the global engine stays initialized for the rest of the process).
    try:
        QTimer.singleShot(2500, _release)
    except Exception:
        _release()


__all__ = ["mark_browser_used", "should_prewarm", "schedule_prewarm"]
