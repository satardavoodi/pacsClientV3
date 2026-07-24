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

**Idle gating (OPT-22, 2026-07-08; hardened 2026-07-23).** The GUI-thread engine
construction blocks the main thread for the full cold-boot duration (**up to
~21 s** on some machines). The original schedule fired it a fixed ``delay_ms``
(4 s) after the home panel built — which is NOT idle: the user is loading/
searching the patient list then, so the block landed as a startup freeze
(`interaction_active=False` 21 s stall, live 2026-07-07). The construction now
waits for a **genuine idle gap** — no discrete user input (click / key / wheel)
for ``idle_ms`` — after a longer initial delay, rechecking on a poll timer, and
**gives up** (skips the warm this session, never forcing a freeze) if the user
stays continuously busy past ``max_wait_ms``. When it finally warms, the user is
not interacting, so the block is unnoticed; the next real browser open is still
fast. Legacy fixed-delay behaviour is preserved under
``AIPACS_BROWSER_PREWARM_IDLE_ONLY=0``.

**First-interaction requirement (2026-07-23, click-lag root cause).** "Idle" was
measured only as *absence of input since the watch started* — but right after
startup the user has not interacted YET, so the pre-input quiet moment (waiting
for the home page to paint) satisfied the 5 s gap and the ~17 s Chromium boot
landed exactly as the user began clicking patients (live 13:51 session,
2026-07-23: gap_ms=17031 inside ``_construct_warm_view``/``view.setUrl``,
queued patient clicks processed only after the boot). The idle gap now
qualifies ONLY AFTER the first discrete input has been seen — idle means "a
pause BETWEEN interactions", never "the user hasn't started yet". A user who
truly walked away (no input at all) is covered by the ``untouched_ms`` grace
(default 120 s): after that long with zero input the warm runs anyway.

Everything here is best-effort and fully guarded: a pre-warm failure must
NEVER affect app/home startup or the clinical UI. This module imports only
stdlib + ``PySide6.QtCore`` at top level (NOT QtWebEngine, NOT QtWidgets), so
importing it is cheap.

Kill switch: ``AIPACS_BROWSER_PREWARM=0``.
Tunables (ms): ``AIPACS_BROWSER_PREWARM_DELAY_MS`` (initial delay, default
20000), ``AIPACS_BROWSER_PREWARM_IDLE_MS`` (required idle gap, default 5000),
``AIPACS_BROWSER_PREWARM_MAX_WAIT_MS`` (give-up cap, default 600000),
``AIPACS_BROWSER_PREWARM_POLL_MS`` (recheck interval, default 2000),
``AIPACS_BROWSER_PREWARM_UNTOUCHED_MS`` (no-input-at-all grace before warming
anyway, default 120000; 0 = legacy pre-input warm allowed).
``AIPACS_BROWSER_PREWARM_IDLE_ONLY=0`` restores the legacy fixed-delay warm.
``AIPACS_BROWSER_PREWARM_FILE_WARM=0`` disables the off-thread file pre-read.

**Cold-boot economics (measured 2026-07-23, tools/dev/bench_webengine_boot.py).**
On the reporting workstation a WARM Chromium boot is ~1.0 s total (construct+
setUrl ~0.6 s) and NO flag set (--disable-gpu / slim / no-sandbox) changes it
beyond noise — flags are NOT the lever. The 11–17 s live freezes are the COLD
first-boot-of-the-day: ~200 MB of WebEngine DLLs/resources read from disk while
the AV scans them and Proxifier hooks the QtWebEngineProcess spawn
(cold bench: construct 1.1 s, full ready 14.7 s). Hence ``_warm_webengine_files``
pre-reads those files on the DAEMON thread before the GUI-thread construction,
so the disk+AV cost is paid off-thread and the GUI block stays near the warm
~0.6 s. The warm view is also held until ``loadFinished`` (failsafe 60 s) — the
old fixed 2.5 s release destroyed the view BEFORE a cold boot finished, wasting
part of the warm.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_MARKER_NAME = ".browser_used"

_scheduled = False   # one pre-warm per process
_warm_view = None    # keep the throwaway view alive during the warm window
_warm_ctl = None     # keep the controller (and its signal connection) alive


def _now_ms() -> float:
    return time.monotonic() * 1000.0


# ── Off-thread file warm (2026-07-23, measured cold-boot fix) ──────────────
# Files the engine reads during its GUI-thread init that a plain `import` does
# NOT touch: the render-process executable, ICU data, resource .pak bundles and
# the V8 snapshot. Pre-reading them on the daemon thread pulls them into the OS
# file cache AND lets the antivirus scan them off-thread, so the GUI-thread
# construction hits warm cache (~0.6 s) instead of paying the ~15 s cold cost.
_WARM_FILE_NAMES = ("QtWebEngineProcess.exe", "icudtl.dat", "v8_context_snapshot.bin")
_WARM_FILE_SUFFIXES = (".pak",)
_WARM_FILE_BUDGET_BYTES = 600 * 1024 * 1024   # hard cap; typical total is ~350 MB


def _file_warm_enabled() -> bool:
    return (os.environ.get("AIPACS_BROWSER_PREWARM_FILE_WARM", "1") or "1").strip() != "0"


def _webengine_aux_files(root: Path | None = None) -> list[Path]:
    """The WebEngine auxiliary files worth pre-reading, under the PySide6 dir
    (or ``root`` override for tests). Best-effort; returns [] on any error."""
    out: list[Path] = []
    try:
        if root is None:
            import PySide6
            root = Path(PySide6.__file__).resolve().parent
        for path in root.rglob("*"):
            try:
                if not path.is_file():
                    continue
                if path.name in _WARM_FILE_NAMES or path.suffix.lower() in _WARM_FILE_SUFFIXES:
                    out.append(path)
            except OSError:
                continue
    except Exception:
        return []
    return out


def _warm_webengine_files(root: Path | None = None) -> int:
    """Sequentially read (and discard) the WebEngine auxiliary files to warm the
    OS file cache + AV verdict cache OFF the GUI thread. Returns bytes read.
    Bounded by ``_WARM_FILE_BUDGET_BYTES``; never raises."""
    if not _file_warm_enabled():
        return 0
    total = 0
    start = _now_ms()
    try:
        for path in _webengine_aux_files(root):
            if total >= _WARM_FILE_BUDGET_BYTES:
                break
            try:
                with open(path, "rb") as fh:
                    while total < _WARM_FILE_BUDGET_BYTES:
                        chunk = fh.read(4 * 1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
            except OSError:
                continue
        logger.info("browser prewarm: file warm read %.1f MB in %.0f ms (off-thread)",
                    total / 1e6, _now_ms() - start)
    except Exception:
        logger.debug("browser prewarm: file warm failed", exc_info=True)
    return total


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except Exception:
        return default


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


def _idle_only() -> bool:
    return (os.environ.get("AIPACS_BROWSER_PREWARM_IDLE_ONLY", "1") or "1").strip() != "0"


def schedule_prewarm(delay_ms: int | None = None) -> bool:
    """Schedule a one-time, idle, background QtWebEngine pre-warm.

    Returns True when a pre-warm was scheduled. No-op (returns False) when
    disabled, the browser has never been used, already scheduled this
    process, or Qt is unavailable. The calling thread NEVER imports
    QtWebEngine — the DLL load runs on a daemon thread and only the final
    ``QWebEngineView`` construction (which must be GUI-thread) is posted back
    to the GUI thread, gated on a genuine idle gap so it never competes with
    the login / home paint / patient-list load / active use.
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
            self._filter = None
            self._poll_timer = None
            self._last_input_ms = 0.0
            self._start_ms = 0.0
            self._idle_ms = 5000.0
            self._max_wait_ms = 600000.0
            # 2026-07-23 click-lag fix: idle qualifies only BETWEEN interactions.
            self._seen_input = False
            self._untouched_ms = 120000.0

        # ── heavy work: DLL load off-thread, construction on GUI thread ──
        def kick(self) -> None:
            def _bg_import() -> None:
                try:
                    import PySide6.QtWebEngineCore  # noqa: F401 (DLL load off GUI thread)
                    import PySide6.QtWebEngineWidgets  # noqa: F401
                except Exception:
                    logger.debug("browser prewarm: QtWebEngine import failed",
                                 exc_info=True)
                    return
                # Pre-read the engine's auxiliary files (render-process exe, ICU,
                # .pak resources, V8 snapshot) while still OFF the GUI thread —
                # measured 2026-07-23: this is where the ~15 s COLD boot lives
                # (disk read + AV scan), not in any Chromium flag.
                try:
                    _warm_webengine_files()
                except Exception:
                    logger.debug("browser prewarm: file warm failed", exc_info=True)
                try:
                    self.construct.emit()  # hop to the GUI thread
                except Exception:
                    logger.debug("browser prewarm: emit failed", exc_info=True)

            threading.Thread(target=_bg_import, name="browser-prewarm-import",
                             daemon=True).start()

        def _on_construct(self) -> None:
            _construct_warm_view()

        # ── idle gating (OPT-22) ─────────────────────────────────────────
        def start_idle_watch(self, delay_ms: int, idle_ms: int,
                             max_wait_ms: int, poll_ms: int,
                             untouched_ms: int = 120000) -> None:
            """Install a minimal input tracker and warm only on a real idle gap."""
            self._idle_ms = float(max(0, idle_ms))
            self._max_wait_ms = float(max(0, max_wait_ms))
            self._untouched_ms = float(max(0, untouched_ms))
            self._poll_ms = int(max(250, poll_ms))
            self._start_ms = _now_ms()
            self._last_input_ms = self._start_ms
            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                if app is not None:
                    app.installEventFilter(self)
                    self._filter = app
            except Exception:
                logger.debug("browser prewarm: idle filter install failed", exc_info=True)
            # First check after the initial delay; then poll until idle or give up.
            QTimer.singleShot(max(0, int(delay_ms)), self._check_idle)

        def _check_idle(self) -> None:
            try:
                now = _now_ms()
                idle_for = now - self._last_input_ms
                waited = now - self._start_ms
                # A quiet stretch counts as idle ONLY once the user has actually
                # interacted — the pre-first-input silence right after startup is
                # the moment the user is ABOUT to start working, and warming there
                # froze their first patient clicks for the whole Chromium boot
                # (~17 s live, 2026-07-23). untouched_ms (0 = disabled → legacy
                # behaviour) is the walked-away fallback: with zero input for that
                # long, the user is genuinely absent and warming is safe.
                if self._seen_input:
                    if idle_for >= self._idle_ms:
                        logger.info(
                            "browser prewarm: idle %.0fms >= %.0fms after first "
                            "interaction -> warming now", idle_for, self._idle_ms)
                        self._finish_watch(warm=True)
                        return
                elif self._untouched_ms <= 0 and idle_for >= self._idle_ms:
                    # Legacy pre-input warm explicitly re-enabled (untouched_ms=0).
                    logger.info("browser prewarm: idle %.0fms >= %.0fms (pre-input "
                                "legacy mode) -> warming now", idle_for, self._idle_ms)
                    self._finish_watch(warm=True)
                    return
                elif self._untouched_ms > 0 and waited >= self._untouched_ms:
                    logger.info(
                        "browser prewarm: no input at all for %.0fms (grace %.0fms) "
                        "-> user away, warming now", waited, self._untouched_ms)
                    self._finish_watch(warm=True)
                    return
                if waited >= self._max_wait_ms:
                    logger.info("browser prewarm: user busy for %.0fms (cap %.0fms) -> "
                                "skipping prewarm this session", waited, self._max_wait_ms)
                    self._finish_watch(warm=False)
                    return
                # Re-check shortly.
                self._poll_timer = QTimer()
                self._poll_timer.setSingleShot(True)
                self._poll_timer.timeout.connect(self._check_idle)
                self._poll_timer.start(self._poll_ms)
            except Exception:
                logger.debug("browser prewarm: idle check failed", exc_info=True)
                # On any error, fall back to warming so the feature still works.
                self._finish_watch(warm=True)

        def _finish_watch(self, warm: bool) -> None:
            try:
                if self._poll_timer is not None:
                    self._poll_timer.stop()
                    self._poll_timer = None
            except Exception:
                pass
            try:
                if self._filter is not None:
                    self._filter.removeEventFilter(self)
                    self._filter = None
            except Exception:
                pass
            if warm:
                self.kick()

        def eventFilter(self, obj, event):  # noqa: N802 (Qt signature)
            # Record only DISCRETE user actions (click / key / wheel). Mouse-move
            # is intentionally ignored: a user reading a study (no clicks) is
            # effectively idle and a good moment to warm. Never consume the event.
            try:
                from PySide6.QtCore import QEvent
                et = event.type()
                if et in (
                    QEvent.Type.MouseButtonPress,
                    QEvent.Type.MouseButtonRelease,
                    QEvent.Type.MouseButtonDblClick,
                    QEvent.Type.KeyPress,
                    QEvent.Type.Wheel,
                    QEvent.Type.TouchBegin,
                ):
                    self._last_input_ms = _now_ms()
                    self._seen_input = True
            except Exception:
                pass
            return False

    _warm_ctl = _PrewarmController()

    if _idle_only():
        delay = _env_int("AIPACS_BROWSER_PREWARM_DELAY_MS",
                         20000 if delay_ms is None else int(delay_ms))
        idle = _env_int("AIPACS_BROWSER_PREWARM_IDLE_MS", 5000)
        max_wait = _env_int("AIPACS_BROWSER_PREWARM_MAX_WAIT_MS", 600000)
        poll = _env_int("AIPACS_BROWSER_PREWARM_POLL_MS", 2000)
        untouched = _env_int("AIPACS_BROWSER_PREWARM_UNTOUCHED_MS", 120000)
        _warm_ctl.start_idle_watch(delay, idle, max_wait, poll, untouched)
        logger.info("browser prewarm: idle-gated (initial delay=%dms, idle_gap=%dms, "
                    "cap=%dms, untouched_grace=%dms, first-interaction required)",
                    delay, idle, max_wait, untouched)
    else:
        # Legacy fixed-delay warm (byte-identical to the pre-OPT-22 behaviour).
        legacy_delay = 4000 if delay_ms is None else int(delay_ms)
        QTimer.singleShot(max(0, legacy_delay), _warm_ctl.kick)
        logger.info("browser prewarm: scheduled (delay=%dms)", legacy_delay)
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

    # Hold the throwaway view until the engine has ACTUALLY finished booting
    # (loadFinished), then drop the render process — the global engine stays
    # initialized for the rest of the process. The old fixed 2.5 s release
    # destroyed the view mid-boot on a COLD start (measured ~15 s to ready,
    # 2026-07-23), wasting part of the warm. 60 s failsafe so the view can
    # never linger if loadFinished is lost.
    released = {"done": False}

    def _release_once(*_a) -> None:
        if released["done"]:
            return
        released["done"] = True
        try:
            QTimer.singleShot(1500, _release)  # small settle after ready
        except Exception:
            _release()

    try:
        view.loadFinished.connect(_release_once)
        QTimer.singleShot(60000, _release_once)  # failsafe
    except Exception:
        try:
            QTimer.singleShot(2500, _release)
        except Exception:
            _release()


__all__ = ["mark_browser_used", "should_prewarm", "schedule_prewarm"]
# OPT-22 idle-gated prewarm shipped 2026-07-08 (see docs regression report).
