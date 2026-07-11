"""
Network reachability monitor (OPT-04 / DM resume — 2026-07-08)

Lightweight, OPT-IN, off-GUI-thread reachability probe used to auto-resume
download studies that were parked in FAILED because a multi-minute internet
outage drained their retry budget. See
``docs/reports/DOWNLOAD_MANAGER_RESUME_RETRY_RELIABILITY_AUDIT_2026-07-08.md``.

Design invariants (must not be broken):
- **Pure stdlib** (``socket``/``threading`` only) — no Qt, no PySide6 — so it is
  fully unit-testable headless and cannot touch the imaging / render domains.
- **Passive**: it NEVER downloads, mutates queue state, or calls into the DM. It
  only records offline→online EDGES; the GUI thread polls
  :meth:`consume_online_edge` and decides what to do. No cross-thread Qt calls,
  no signals — this is what keeps the wiring safe.
- **Default OFF**. The DM widget constructs it only when ``AIPACS_DM_NET_MONITOR=1``.
- Startup state is ``None`` (unknown); an edge fires only on a real
  ``offline (False) → online (True)`` transition, so a healthy first probe never
  spuriously re-arms the queue.
"""

import logging
import socket
import threading

logger = logging.getLogger(__name__)


def probe_reachable(host, port, timeout=3.0) -> bool:
    """Return True iff a TCP connection to ``(host, port)`` opens within
    ``timeout`` seconds. Pure, side-effect-free, never raises."""
    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout)):
            return True
    except Exception:
        return False


class NetworkReachabilityMonitor:
    """Background TCP-reachability poller that reports offline→online edges.

    The monitor thread only touches plain flags under a lock; the consumer
    (GUI thread) calls :meth:`consume_online_edge`. There is deliberately no Qt
    object here so the cross-thread hand-off is a lock, not a queued signal.
    """

    def __init__(self, host, port, interval_s=15.0, timeout_s=3.0, probe=None):
        self._host = host
        self._port = port
        self._interval_s = float(interval_s)
        self._timeout_s = float(timeout_s)
        self._probe = probe or probe_reachable
        self._lock = threading.Lock()
        self._online = None  # None = unknown (startup); True/False afterwards
        self._pending_online_edge = False
        self._thread = None
        self._stop = threading.Event()

    # ── observation / edge detection ─────────────────────────────────────
    def _record(self, reachable) -> bool:
        """Fold one observation into the state. Returns True iff this is an
        offline→online edge (which also latches ``_pending_online_edge``)."""
        with self._lock:
            was = self._online
            self._online = bool(reachable)
            # Fire only on a genuine offline(False)→online(True) transition.
            # Startup (was is None) never fires an edge.
            if reachable and was is False:
                self._pending_online_edge = True
                return True
            return False

    def consume_online_edge(self) -> bool:
        """Thread-safe: return True once per offline→online edge, then clear it."""
        with self._lock:
            edge = self._pending_online_edge
            self._pending_online_edge = False
            return edge

    def is_online(self):
        with self._lock:
            return self._online

    # ── lifecycle ────────────────────────────────────────────────────────
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                reachable = self._probe(self._host, self._port, self._timeout_s)
                if self._record(reachable):
                    logger.info(
                        "[DM-NET] offline->online edge (host=%s port=%s)",
                        self._host, self._port,
                    )
            except Exception:
                logger.exception("[DM-NET] probe loop error (non-fatal)")
            # Interruptible sleep — stop() wakes it immediately.
            self._stop.wait(self._interval_s)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="dm-net-monitor",
        )
        self._thread.start()
        logger.info(
            "[DM-NET] reachability monitor started (host=%s port=%s interval=%.0fs)",
            self._host, self._port, self._interval_s,
        )

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            try:
                t.join(timeout=1.0)
            except Exception:
                pass
        self._thread = None
