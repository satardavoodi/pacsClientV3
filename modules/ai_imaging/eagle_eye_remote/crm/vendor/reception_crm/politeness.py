"""Yield to the software that was here first.

The agent shares a machine with the reception/paraclinic system, MongoDB and
the PACS server. It is a companion, and a companion that competes for the CPU
on equal terms is not one -- during a busy clinic morning the thing that must
stay responsive is patient registration, not a chat answer.

Windows gives us exactly the lever for this: a process priority class. At
BELOW_NORMAL the scheduler hands the agent CPU only when the reception stack is
not asking for it. On an idle machine nothing changes and the agent runs at full
speed; under contention it steps back. There is no configuration and no tuning
here on purpose -- "be lower priority than the clinical software" is not a
preference.

This is deliberately best-effort: if the priority cannot be set, the agent still
starts. A companion service that refuses to run because it could not lower its
own priority would be a worse outcome than one running at normal priority.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import contextmanager

LOG = logging.getLogger("reception_crm.politeness")

#: Set to "false" to leave the priority alone. Exists for the one case that
#: could justify it -- a dedicated machine where the agent IS the workload --
#: and for diagnosing whether priority is behind a slow answer.
ENV_YIELD = "RECEPTION_YIELD_CPU"


def wanted() -> bool:
    return (os.getenv(ENV_YIELD) or "").strip().lower() not in ("0", "false", "no", "off")


def yield_cpu_to_clinical_software() -> str:
    """Drop this process to below-normal priority. Returns what happened."""
    if not wanted():
        return "left at default (%s=false)" % ENV_YIELD
    if not sys.platform.startswith("win"):
        try:
            os.nice(5)  # type: ignore[attr-defined]
            return "nice +5"
        except Exception as exc:  # noqa: BLE001
            return "unchanged (%s)" % type(exc).__name__

    try:
        import ctypes
        from ctypes import wintypes

        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        kernel32 = ctypes.windll.kernel32

        # The argtypes/restype declarations are not ceremony, they are the fix.
        # ctypes defaults a function's return type to `c_int` (32-bit), so on
        # 64-bit Python `GetCurrentProcess()` -- whose real return is the
        # pseudo-handle (HANDLE)-1 -- came back as a truncated 32-bit -1 and was
        # then widened to 0x00000000FFFFFFFF when passed back in. That is not a
        # valid handle, so SetPriorityClass returned 0 and the agent quietly kept
        # running at normal priority. The first deployment of this file did
        # exactly that; it was caught only because the outcome is logged.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]

        handle = kernel32.GetCurrentProcess()
        if kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS):
            return "BELOW_NORMAL_PRIORITY_CLASS"
        return "unchanged (SetPriorityClass failed, GetLastError=%d)" % ctypes.get_last_error()
    except Exception as exc:  # noqa: BLE001 - never block startup over this
        return "unchanged (%s: %s)" % (type(exc).__name__, exc)


def apply() -> None:
    """Called once at service start. Logs the outcome and never raises."""
    outcome = yield_cpu_to_clinical_software()
    LOG.info("cpu priority: %s", outcome)


# --------------------------------------------------------------------------- #
# Yielding on the reception API, not only on the CPU
# --------------------------------------------------------------------------- #
#: How many reception API calls this agent may have in flight at once.
#:
#: CPU priority is the right lever for CPU and does nothing for this. A
#: below-normal process can still open twenty simultaneous connections to
#: `server-interface`, and those queue in ITS thread pool at ITS priority --
#: which is the reception desk's priority.
#:
#: It used to be bounded by accident: one question meant one API call. The
#: gathering loop broke that accident. Analysis may now fetch up to eight
#: sources, and each phone that asks at the same time multiplies it again.
#:
#: Four is chosen to be lower than any plausible reception concurrency, so that
#: even saturated the agent is a minority of the traffic. Measured cost of the
#: cap: nothing. Reception reports answer in 7-835 ms, so four at a time is far
#: more throughput than the loop can consume between LLM rounds.
ENV_MAX_INFLIGHT = "RECEPTION_MAX_INFLIGHT"
DEFAULT_MAX_INFLIGHT = 4

#: Longest an agent call will wait for a slot before giving up on politeness
#: and proceeding. A queue that grows without bound turns a busy moment into a
#: pile of stuck threads; going ahead is better than hanging, and it is logged.
ACQUIRE_TIMEOUT_SECONDS = 20.0


def _max_inflight() -> int:
    raw = (os.getenv(ENV_MAX_INFLIGHT) or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_INFLIGHT
    except ValueError:
        value = DEFAULT_MAX_INFLIGHT
    return max(1, min(32, value))


class _ReceptionGate:
    """Bounds how much of the reception API this agent occupies at once."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._semaphore: threading.Semaphore | None = None
        self._limit = 0
        self.waited = 0
        self.forced = 0

    def _ensure(self) -> threading.Semaphore:
        # Built on first use rather than at import: the limit comes from the
        # environment, and `apply_to_environment()` publishes the configuration
        # after this module is imported.
        with self._lock:
            if self._semaphore is None:
                self._limit = _max_inflight()
                self._semaphore = threading.BoundedSemaphore(self._limit)
                LOG.info("reception API concurrency limited to %d in-flight call(s)", self._limit)
            return self._semaphore

    @contextmanager
    def slot(self):
        semaphore = self._ensure()
        acquired = semaphore.acquire(timeout=ACQUIRE_TIMEOUT_SECONDS)
        if not acquired:
            # Never a reason to fail a clinician's question. Proceeding beyond
            # the cap is a worse day for the reception API than staying under
            # it, and a much better one than a hung request.
            self.forced += 1
            LOG.warning(
                "reception API gate full for %.0fs; proceeding over the limit of %d",
                ACQUIRE_TIMEOUT_SECONDS, self._limit,
            )
            yield
            return
        self.waited += 1
        try:
            yield
        finally:
            try:
                semaphore.release()
            except ValueError:  # pragma: no cover - only if released twice
                LOG.warning("reception API gate released more times than acquired")

    def status(self) -> dict[str, int]:
        return {"limit": self._limit or _max_inflight(), "forced_past_limit": self.forced}


#: One gate for the whole process. Module-level on purpose: the resource being
#: protected is the reception system, and it does not care which of our objects
#: is calling it.
reception_gate = _ReceptionGate()
