"""Download subprocess pre-warm pool (Phase 1) — OFF by default.

Removes the ~2.3 s Windows ``spawn`` bootstrap (process creation + interpreter
boot) from the user-visible download-start path by keeping ONE idle, already-
booted download subprocess ready. When a download starts, the job is handed to
the warm spare instead of spawning fresh; the next spare is then warmed in the
background.

Safety:
  * Entirely gated by env ``AIPACS_DM_PREWARM`` (OFF unless 1/true/yes). When
    OFF, every method is a no-op and the download path is byte-for-byte the
    original spawn-per-download behaviour.
  * Never raises into the caller — any failure returns None so the caller falls
    back to the normal spawn.
  * The idle spare opens NO database/socket (those open only once it receives a
    job inside ``_run_download_in_process``), so an idle spare costs only a
    booted interpreter — keeping the "don't starve the app" resource-harmony
    rule. At most one spare is kept.
  * The spare is daemon=True, so it dies with the parent (no orphan on exit).
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def prewarm_enabled() -> bool:
    """True only when AIPACS_DM_PREWARM is explicitly enabled."""
    return os.getenv("AIPACS_DM_PREWARM", "0").strip().lower() in ("1", "true", "yes")


class DownloadPrewarmPool:
    """Maintains at most one pre-warmed idle download subprocess."""

    def __init__(self) -> None:
        self._spare: Optional[Dict[str, Any]] = None
        try:
            self._ctx = mp.get_context("spawn")
        except Exception:
            self._ctx = mp  # fallback; only used when enabled

    def ensure_warm(self) -> None:
        """Spawn an idle spare if enabled and none is alive (no-op otherwise)."""
        if not prewarm_enabled():
            return
        spare = self._spare
        try:
            if spare is not None and spare["process"].is_alive():
                return  # a spare is already booting or ready — never double-spawn
        except Exception:
            pass
        self._spare = None
        try:
            from .download_process_entry import _prewarmed_download_worker_main
            task_q = self._ctx.Queue(maxsize=1)
            result_q = self._ctx.Queue(maxsize=1000)
            cancel_evt = self._ctx.Event()
            ready_evt = self._ctx.Event()
            proc = self._ctx.Process(
                target=_prewarmed_download_worker_main,
                args=(task_q, result_q, cancel_evt, os.getcwd(), ready_evt),
                name="DL-prewarm",
                daemon=True,
            )
            proc.start()
            self._spare = {
                "process": proc, "task_q": task_q, "result_q": result_q,
                "cancel_evt": cancel_evt, "ready_evt": ready_evt,
            }
            logger.info("🔥 [PREWARM] spawned idle download subprocess pid=%s",
                        proc.pid, extra={"component": "ipc"})
        except Exception:
            logger.exception("[PREWARM] failed to spawn idle spare")
            self._spare = None

    def acquire(self, task: Any, config_dict: dict) -> Optional[Tuple[Any, Any, Any]]:
        """Hand the job to a ready warm spare and return its
        ``(process, result_queue, cancel_event)``; return None to signal the
        caller should spawn normally. Always best-effort + non-raising.
        """
        if not prewarm_enabled():
            return None
        spare = self._spare
        ready = False
        try:
            ready = (spare is not None
                     and spare["process"].is_alive()
                     and spare["ready_evt"].is_set())
        except Exception:
            ready = False
        if not ready:
            # No warm spare ready yet — bootstrap one for the NEXT download and
            # let this one spawn normally.
            try:
                self.ensure_warm()
            except Exception:
                pass
            return None
        try:
            spare["task_q"].put((task, config_dict))
        except Exception:
            logger.exception("[PREWARM] failed to hand job to spare; falling back")
            return None
        self._spare = None
        result = (spare["process"], spare["result_q"], spare["cancel_evt"])
        try:
            self.ensure_warm()  # warm the next spare in the background
        except Exception:
            pass
        return result

    def shutdown(self) -> None:
        """Unblock + terminate the idle spare (best-effort). daemon=True already
        covers process exit, so this is a clean-shutdown nicety."""
        spare = self._spare
        self._spare = None
        if spare is None:
            return
        try:
            from .download_process_entry import _PREWARM_SHUTDOWN
            spare["task_q"].put(_PREWARM_SHUTDOWN)
        except Exception:
            pass
        try:
            if spare["process"].is_alive():
                spare["process"].terminate()
        except Exception:
            pass


_pool_singleton: Optional[DownloadPrewarmPool] = None


def get_download_prewarm_pool() -> DownloadPrewarmPool:
    global _pool_singleton
    if _pool_singleton is None:
        _pool_singleton = DownloadPrewarmPool()
    return _pool_singleton
