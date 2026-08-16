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

**Default OFF since IMP-4 (2026-08-16).** Opt in with
``AIPACS_BROWSER_PREWARM=1``. A cold GUI-thread construct was measured at
**72.1 s** live (see ``should_prewarm`` for the full timeline and reasoning);
every scheduling guard below worked correctly and still could not prevent it,
because the construct's cost is unbounded and it must run on the GUI thread.
Everything documented below therefore describes how the warm behaves WHEN
EXPLICITLY ENABLED.
Tunables (ms): ``AIPACS_BROWSER_PREWARM_DELAY_MS`` (initial delay, default
20000), ``AIPACS_BROWSER_PREWARM_IDLE_MS`` (required idle gap, default 5000),
``AIPACS_BROWSER_PREWARM_MAX_WAIT_MS`` (give-up cap, default 600000),
``AIPACS_BROWSER_PREWARM_POLL_MS`` (recheck interval, default 2000),
``AIPACS_BROWSER_PREWARM_UNTOUCHED_MS`` (no-input-at-all grace before warming
anyway, default 120000; 0 = legacy pre-input warm allowed).
``AIPACS_BROWSER_PREWARM_IDLE_ONLY=0`` restores the legacy fixed-delay warm.
``AIPACS_BROWSER_PREWARM_FILE_WARM=0`` disables the off-thread file pre-read.
``AIPACS_BROWSER_PREWARM_RECENCY_VETO=0`` disables the construct-time
input-recency re-check (IMP-3, 2026-08-07: the idle verdict went stale during
kick()'s background phase and the ~19 s Chromium construct collided with a
patient double-click; the idle gap must hold AT construct time).

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

# IMP-5 (2026-08-16): the .pak/.dat set above is only 152.1 MB of a 358 MB
# WebEngine payload. Audited on the reporting workstation, the 277.4 MB NOT
# being pre-read is almost entirely ONE file:
#     202.3 MB  Qt6WebEngineCore.dll      <-- the engine itself
#      10.2 MB  Qt6Core.dll
#       9.5 MB  Qt6Gui.dll
#       6.6 MB  Qt6Widgets.dll   (+ Quick/Qml/…)
# `kick()` already IMPORTS QtWebEngineCore off-thread, which memory-maps that
# DLL — but mapping is lazy: its pages are faulted in only as the global init
# executes them, i.e. ON THE GUI THREAD, from cold disk, past two real-time AV
# engines. Sequentially pre-reading the DLLs on the daemon thread pulls them
# into the OS page cache and pays the AV verdict off-thread, exactly as the
# .pak pre-read already does. Names are matched conservatively so this never
# walks the whole of site-packages.
_WARM_DLL_HINTS = (
    "qt6webenginecore", "qt6core", "qt6gui", "qt6widgets",
    "qt6network", "qt6quick", "qt6qml", "qt6positioning",
)
_WARM_FILE_BUDGET_BYTES = 600 * 1024 * 1024   # hard cap; full payload is ~430 MB


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
                elif path.suffix.lower() == ".dll" and path.stem.lower() in _WARM_DLL_HINTS:
                    # IMP-5: the engine DLLs — 277 MB the warm used to miss.
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
    """True when an idle pre-warm should run this session.

    IMP-4 (2026-08-16) — the pre-warm is now OPT-IN (default OFF).

    Live evidence, pid 218252, with every earlier guard working as designed:
        11:05:47  idle 12692 ms >= 5000 ms after first interaction -> warming now
        11:06:04  file warm read 152.1 MB in 4358 ms (off-thread)
        11:07:16  Chromium engine warmed (construct+setUrl 72122 ms on GUI thread)
    -> a **72.1 second** frozen clinical workstation.

    The scheduling guards (OPT-22 idle gate, IMP-1 modal veto, IMP-3
    construct-time input-recency re-check) all did the right thing: the user
    had genuinely been idle for 12.7 s, so the construct was allowed. The
    lesson from four live incidents (~17 s 2026-07-23, 19 s 2026-08-07,
    39.7 s 2026-08-05, 72 s today) is that WHEN the construct runs was never
    the real problem — its COST is unbounded and cannot be capped, because Qt
    requires QWebEngineView construction on the GUI thread and that call is
    atomic. No idle window is long enough to be safe when a cold boot can take
    72 s, and the user can always resume work inside it.

    The trade is therefore settled the other way: pay the Chromium boot when
    the user actually OPENS the Web Browser (an explicit action, where a wait
    is expected and attributable) instead of risking a minutes-long freeze
    mid-reporting for a feature that may not be used at all this session.

    Opt in with AIPACS_BROWSER_PREWARM=1 on machines where the boot is cheap
    (it was 219-227 ms warm on 2026-08-07); the adaptive marker is still
    honoured on top, so opting in only warms sessions after the browser has
    been used at least once. AIPACS_BROWSER_PREWARM=0 (or unset) = off.
    """
    if (os.environ.get("AIPACS_BROWSER_PREWARM", "0") or "0").strip() != "1":
        return False
    try:
        return _marker_path().exists()
    except Exception:
        return False


def _idle_only() -> bool:
    return (os.environ.get("AIPACS_BROWSER_PREWARM_IDLE_ONLY", "1") or "1").strip() != "0"


# ── IMP-1 (2026-08-05): busy-app veto ───────────────────────────────────────
# The OPT-22 idle gate counts only discrete input (click/key/wheel), so a user
# WAITING on a modal — import scan/copy progress, the import preview dialog, a
# message box — looks "idle". Live 2026-08-05: the warm fired at 20:36:17
# mid-import (clicks inside the NATIVE folder picker never reach the Qt event
# filter), `_warm_webengine_files` then read 152 MB against the import copy's
# I/O, and `_construct_warm_view` landed on the GUI thread at 20:36:23 —
# one contiguous 39.7 s MAIN_THREAD_STALL over the whole copy (import
# duration 40.9 s for 66 MB ≈ 1.6 MB/s from the same contention).
# Veto = a modal/popup widget is open. Checked (a) in the idle poll, so the
# warm never KICKS while a dialog is up, and (b) right before the GUI-thread
# construct, so a construct queued earlier DEFERS until the modal closes
# (bounded; gives up after _CONSTRUCT_DEFER_MAX_MS).
# Kill switch: AIPACS_BROWSER_PREWARM_BUSY_VETO=0 restores OPT-22 behaviour.
_CONSTRUCT_DEFER_POLL_MS = 2000
_CONSTRUCT_DEFER_MAX_MS = 600000.0


def _busy_veto_enabled() -> bool:
    return (os.environ.get("AIPACS_BROWSER_PREWARM_BUSY_VETO", "1") or "1").strip() != "0"


def _recency_veto_enabled() -> bool:
    """IMP-3 kill switch: construct-time input-recency re-check (default on)."""
    return (os.environ.get("AIPACS_BROWSER_PREWARM_RECENCY_VETO", "1") or "1").strip() != "0"


def _app_is_busy() -> bool:
    """True while a modal dialog / popup is open. GUI-thread callers only."""
    if not _busy_veto_enabled():
        return False
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return False
        return (app.activeModalWidget() is not None
                or app.activePopupWidget() is not None)
    except Exception:
        return False


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
            # IMP-1: construct-deferral deadline (0 = not yet deferring).
            self._construct_deadline_ms = 0.0

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
            # IMP-1: never run the Chromium construct while a modal is open —
            # live 2026-08-05 it landed mid-import-copy and blocked the GUI
            # thread for 39.7 s. Defer in short steps until the modal closes;
            # give up (skip this session's warm) past the deadline.
            # IMP-3 (2026-08-07): ALSO require the idle gap to still hold AT
            # CONSTRUCT TIME. The idle verdict is taken in _check_idle, but
            # kick()'s background phase (DLL import + file warm) runs for
            # seconds before this handler fires — live 21:28 the user
            # double-clicked patient 53516 inside that window and the
            # construct landed with the click already queued behind it:
            # one 19.0 s MAIN_THREAD_STALL, the open processed only after.
            # The input filter now stays installed through kick(), so a
            # fresh click defers the construct instead of freezing behind it.
            busy = _app_is_busy()
            recent = (not busy and _recency_veto_enabled() and self._seen_input
                      and (_now_ms() - self._last_input_ms) < self._idle_ms)
            if busy or recent:
                now = _now_ms()
                if self._construct_deadline_ms <= 0:
                    self._construct_deadline_ms = now + _CONSTRUCT_DEFER_MAX_MS
                if now < self._construct_deadline_ms:
                    try:
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(_CONSTRUCT_DEFER_POLL_MS,
                                          self._on_construct)
                        logger.debug("browser prewarm: %s -> construct deferred",
                                     "app busy (modal open)" if busy
                                     else "recent user input")
                        return
                    except Exception:
                        logger.debug("browser prewarm: defer failed; "
                                     "constructing now", exc_info=True)
                else:
                    logger.info("browser prewarm: app busy past construct "
                                "deadline -> skipping warm view this session")
                    self._remove_input_filter()
                    return
            self._remove_input_filter()
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
                # IMP-1: an open modal (import scan/copy progress, preview
                # dialog, message box) means the user is mid-workflow even
                # with zero clicks — count it as activity so the warm never
                # kicks under a modal. max_wait still bounds the watch.
                if _app_is_busy():
                    self._last_input_ms = now
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
                elif (self._untouched_ms > 0 and waited >= self._untouched_ms
                      and not _app_is_busy()):
                    # IMP-1: the away-branch keys on `waited` (not idle_for),
                    # so it must ALSO respect the busy veto — a zero-input
                    # auto-import (CD media startup path) would otherwise
                    # trip "user away" mid-copy.
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
            # IMP-3: when warming, KEEP the input filter installed — kick()'s
            # background phase takes seconds and _on_construct re-checks input
            # recency at construct time. The filter is removed there (on
            # construct or on skip). The give-up path removes it now.
            if not warm:
                self._remove_input_filter()
            if warm:
                self.kick()

        def _remove_input_filter(self) -> None:
            try:
                if self._filter is not None:
                    self._filter.removeEventFilter(self)
                    self._filter = None
            except Exception:
                pass

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
    """Trigger Chromium's one-time global init, the cheapest way available.

    IMP-5 (2026-08-16) — this no longer constructs a throwaway
    ``QWebEngineView``; it just touches ``QWebEngineProfile.defaultProfile()``,
    which is what actually forces the global engine init. (The function keeps
    its name because ``_on_construct`` and the prewarm tests address it.)

    Measured on the reporting workstation, warm, 2 runs each — "warm block" is
    the GUI-thread stall, "user open" is what the user then waits for when they
    really open the browser:

        no warm at all           block    0 ms   ->  user open  971 ms
        throwaway view (old)     block  991/889  ->  user open  156/115 ms
        defaultProfile() (new)   block  772/662  ->  user open  173/123 ms

    Identical benefit to the user, for **~24 % less GUI-thread block** (717 vs
    940 ms mean), because the old path additionally paid ``setUrl()`` + a full
    ``about:blank`` page load. It also stops creating a render process that was
    then held alive for up to 60 s purely to be thrown away.

    A phase breakdown of the boot confirms where the cost really is — the view
    itself was never the expensive part:

        import QtWebEngineCore      46 ms   (already off-thread in kick())
        QApplication()              45 ms
        defaultProfile()           918 ms   <-- the global init, GUI-thread only
        QWebEngineView()             0 ms
        setUrl() + loadFinished    554 ms   <-- pure waste for a warm

    Chromium flags are NOT a lever here (measured: --disable-gpu 661 ms,
    --no-sandbox 665 ms, --no-sandbox --disable-gpu 635 ms, --in-process-gpu
    696 ms vs 662-918 ms default — all within noise).
    """
    global _warm_view
    if _warm_view is not None:
        return
    try:
        from PySide6.QtWebEngineCore import QWebEngineProfile
    except Exception:
        logger.debug("browser prewarm: QtWebEngine import failed", exc_info=True)
        return
    try:
        start = _now_ms()
        # Touching the default profile boots the global engine (V8/ICU/network/
        # GPU). Qt owns this object for the process lifetime — nothing to hold,
        # nothing to release, no render process created.
        profile = QWebEngineProfile.defaultProfile()
        _warm_view = profile if profile is not None else True   # "warmed" latch
        logger.info("browser prewarm: Chromium engine warmed "
                    "(defaultProfile %.0f ms on GUI thread)",
                    _now_ms() - start)
    except Exception:
        logger.debug("browser prewarm: engine warm failed", exc_info=True)
        return


__all__ = ["mark_browser_used", "should_prewarm", "schedule_prewarm"]
# OPT-22 idle-gated prewarm shipped 2026-07-08 (see docs regression report).
