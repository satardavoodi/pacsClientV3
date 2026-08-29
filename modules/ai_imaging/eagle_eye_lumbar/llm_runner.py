"""Run one Eagle Eye analysis off the GUI thread.

Thin on purpose. Everything that decides anything lives in `llm_backend`; this
file exists only to get that work off the GUI thread and deliver the answer
back on it, so the workstation stays usable for the minutes a 40-image request
can take.

WHY ApiWorker AND NOT A NEW THREAD CLASS
----------------------------------------
`EchoMind.viewer_chat.ai_chat_api.ApiWorker` is the workstation's existing
"run this callable, emit the result" QThread, already used by every EchoMind AI
call. Reusing it means Eagle Eye inherits the error masking (`failed` never
leaks an endpoint) and the teardown behaviour the chat pages already rely on.

THE STRONG REFERENCE IS NOT OPTIONAL
------------------------------------
OPT-51: a running QThread with no live reference is destroyed mid-run and Qt
aborts the PROCESS with "QThread: Destroyed while thread is still running" - no
traceback, the log simply stops. `_LIVE_RUNS` holds every in-flight run until
it finishes. `detach()` is the close-while-in-flight path: disconnect so the
answer can never reach a dead widget, keep the reference so the thread may
finish and free itself.

Note the asymmetry with `analysis_store`: the STATE is already on disk before
the worker starts, so even a hard kill leaves a session that reopens as
interrupted-and-retryable rather than as though nothing ever happened.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Set

from PySide6.QtCore import QObject, Signal

from . import analysis_store, llm_backend, llm_package

logger = logging.getLogger(__name__)

# Every in-flight run. Module level, so a closing tab cannot collect one.
_LIVE_RUNS: Set["EagleEyeAnalysisRunner"] = set()


def live_run_count() -> int:
    """In-flight analyses. Used by guards and by teardown logging."""
    return len(_LIVE_RUNS)


class EagleEyeAnalysisRunner(QObject):
    """One analysis of one captured session.

    Single-shot: construct, ``start()``, take ``finished`` or ``failed``.
    Re-analysing means a new runner, so a stale worker can never write over a
    newer result.
    """

    started = Signal()
    # (stage number, stage total, stage name) - emitted FROM the worker thread.
    # Qt queues a cross-thread signal, so the slot still runs on the GUI thread;
    # this is the only safe way to report progress out of `run_analysis`.
    stage = Signal(int, int, str)
    finished = Signal(object)   # analysis_store.AnalysisRecord
    failed = Signal(str)

    def __init__(self, session_dir, protocol=None, parent=None):
        super().__init__(parent)
        self.session_dir = Path(session_dir)
        self.protocol = protocol
        self._worker = None
        self._detached = False

    # -- lifecycle ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._worker is not None

    def start(self) -> bool:
        """Begin the request. Returns False if it could not even be started."""
        if self.running:
            return False

        try:
            from modules.EchoMind.viewer_chat.ai_chat_api import ApiWorker
        except Exception as exc:
            self._fail_before_start(f"the EchoMind AI worker is unavailable: {exc}")
            return False

        # Claim the session on the GUI thread, BEFORE the worker exists, so the
        # UI can flip to "analyzing" immediately and a crash in the next
        # millisecond still leaves a state on disk.
        try:
            package = llm_package.build_package(
                self.session_dir, protocol=self.protocol)
        except Exception as exc:
            self._fail_before_start(str(exc))
            return False

        backend = llm_backend.resolve_backend()
        # PER STAGE, through the shared authority, and NEVER passed to
        # `run_analysis` as `model=`.
        #
        # This claim step used to resolve ONE model and hand it down as
        # `model=`, which `run_analysis` correctly reads as "the caller named a
        # model" and applies to every pass. The effect was silent: the stage
        # defaults became dead code in the only real caller, and a run that was
        # supposed to screen on one model and verify on another did both on the
        # first one (session 20260826T191537Z). Resolve here only for what this
        # thread has to write, and let the loop resolve for itself.
        stage_models = llm_backend.resolve_stage_models(package.analysis, backend)
        model_summary = llm_backend.summarize_models(stage_models)
        started_doc = analysis_store.mark_analyzing(
            self.session_dir, package.analysis,
            model=model_summary, models=stage_models,
            backend=backend, image_count=package.image_count)

        def report(number, total_stages, name):
            if not self._detached:
                self.stage.emit(int(number), int(total_stages), str(name))

        def work():
            # Hand the worker the package built above - it is plain paths and
            # strings, no Qt - so the manifests are read once per run, not twice.
            return llm_backend.run_analysis(
                self.session_dir, protocol=self.protocol,
                backend=backend, started=started_doc,
                package=package, progress=report)

        worker = ApiWorker(work, parent=self)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_thread_finished)

        self._worker = worker
        _LIVE_RUNS.add(self)
        self.started.emit()
        worker.start()
        logger.info("[EAGLE-EYE-LLM] run started for %s (%d images, %s/%s)",
                    self.session_dir.name, package.image_count, backend,
                    model_summary)
        return True

    def detach(self) -> None:
        """Close-while-in-flight: let the request die unheard, not mid-thread.

        The worker keeps running (an HTTP request cannot be interrupted) but
        its result is disconnected, so it can never reach a widget that is
        being destroyed. The reference stays until the thread finishes.
        """
        self._detached = True
        worker = self._worker
        if worker is None:
            return
        for name in ("done", "failed"):
            try:
                getattr(worker, name).disconnect()
            except Exception:
                pass
        try:
            worker.setParent(None)
        except Exception:
            pass
        logger.info("[EAGLE-EYE-LLM] run detached for %s", self.session_dir.name)

    # -- worker callbacks (GUI thread) -------------------------------------

    def _fail_before_start(self, message: str) -> None:
        """No worker was ever created, so the state must still be recorded."""
        logger.warning("[EAGLE-EYE-LLM] cannot start for %s: %s",
                       self.session_dir.name, message)
        try:
            analysis_store.mark_failed(self.session_dir, message)
        except Exception:
            pass
        self.failed.emit(message)

    def _on_done(self, record) -> None:
        # `run_analysis` returns a stored record for BOTH outcomes, so a failed
        # request arrives here rather than on `failed` - which only fires when
        # the worker itself raised.
        if self._detached:
            return
        state = getattr(record, "state", None)
        if state == analysis_store.STATE_COMPLETE:
            self.finished.emit(record)
        else:
            self.failed.emit(getattr(record, "error", "") or "analysis failed")

    def _on_worker_failed(self, message: str) -> None:
        if self._detached:
            return
        try:
            analysis_store.mark_failed(self.session_dir, message)
        except Exception:
            pass
        self.failed.emit(message)

    def _on_thread_finished(self) -> None:
        self._worker = None
        _LIVE_RUNS.discard(self)
