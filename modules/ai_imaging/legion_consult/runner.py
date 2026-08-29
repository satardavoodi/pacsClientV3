"""Run Legion Consult evidence preparation and two-stage analysis off Qt GUI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, Signal

from modules.ai_imaging.eagle_eye_lumbar import analysis_store, llm_backend
from modules.ai_imaging.eagle_eye_lumbar.series_classifier import SeriesCandidate

from .evidence import (
    EVIDENCE_MANIFEST,
    EvidenceError,
    build_evidence_package,
    load_evidence_package,
)
from .models import LegionConsultRequest
from .session_store import update_request_state


logger = logging.getLogger(__name__)
_LIVE_RUNS: set["LegionAnalysisRunner"] = set()


def live_run_count() -> int:
    return len(_LIVE_RUNS)


class LegionAnalysisRunner(QObject):
    """Single-shot background preparation and analysis for one saved request."""

    started = Signal()
    stage = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        session_dir: str | Path,
        request: LegionConsultRequest,
        candidates: Sequence[SeriesCandidate] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.session_dir = Path(session_dir)
        self.request = request
        self.candidates = tuple(candidates)
        self._worker = None
        self._detached = False
        self._send_started = False

    @property
    def running(self) -> bool:
        return self._worker is not None

    def start(self) -> bool:
        if self.running:
            return False
        try:
            from modules.EchoMind.viewer_chat.ai_chat_api import ApiWorker
        except Exception:
            self._fail_before_start("The EchoMind AI worker is unavailable.")
            return False

        def report(number, total, name) -> None:
            if not self._detached:
                self.stage.emit(int(number), int(total), str(name))

        def work():
            logger.info(
                "[LEGION-CONSULT] event=evidence_prepare_started session=%s",
                self.request.session_id,
            )
            if (self.session_dir / EVIDENCE_MANIFEST).is_file():
                package = load_evidence_package(
                    self.session_dir,
                    study_uid=self.request.selection.study_uid,
                )
            else:
                if not self.candidates:
                    raise EvidenceError(
                        "The selected source series are unavailable for evidence preparation."
                    )
                package = build_evidence_package(
                    self.request, self.candidates, self.session_dir
                )
            backend = llm_backend.resolve_backend()
            stage_models = llm_backend.resolve_stage_models(package.analysis, backend)
            model_summary = llm_backend.summarize_models(stage_models)
            started_doc = analysis_store.mark_analyzing(
                self.session_dir,
                package.analysis,
                model=model_summary,
                models=stage_models,
                backend=backend,
                image_count=package.image_count,
            )
            logger.info(
                "[LEGION-CONSULT] event=analysis_started session=%s images=%d stages=%d",
                self.request.session_id,
                package.image_count,
                len(package.analysis.stages),
            )
            update_request_state(
                self.session_dir / "request.json",
                status="analyzing",
                remote_send_status="pending",
            )
            self._send_started = True
            return llm_backend.run_analysis(
                self.session_dir,
                backend=backend,
                started=started_doc,
                package=package,
                progress=report,
                prepare_evidence=False,
            )

        worker = ApiWorker(work, parent=self)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_thread_finished)
        self._worker = worker
        _LIVE_RUNS.add(self)
        self.started.emit()
        worker.start()
        return True

    def detach(self) -> None:
        self._detached = True
        worker = self._worker
        if worker is None:
            return
        for name in ("done", "failed"):
            try:
                getattr(worker, name).disconnect()
            except (RuntimeError, TypeError):
                pass
        try:
            worker.setParent(None)
        except RuntimeError:
            pass
        logger.info(
            "[LEGION-CONSULT] event=analysis_detached session=%s",
            self.request.session_id,
        )

    def _fail_before_start(self, message: str) -> None:
        try:
            analysis_store.mark_failed(self.session_dir, message)
        except Exception:
            pass
        self.failed.emit(message)

    def _on_done(self, record) -> None:
        if self._detached:
            return
        if getattr(record, "state", None) == analysis_store.STATE_COMPLETE:
            self._update_request_state("complete", "sent")
            logger.info(
                "[LEGION-CONSULT] event=analysis_completed session=%s",
                self.request.session_id,
            )
            self.finished.emit(record)
        else:
            self._update_request_state("failed", "not_confirmed")
            self.failed.emit(getattr(record, "error", "") or "Analysis failed.")

    def _on_worker_failed(self, message: str) -> None:
        if self._detached:
            return
        safe_message = str(message or "Legion Consult analysis failed.")
        self._update_request_state(
            "failed", "not_confirmed" if self._send_started else "not_sent"
        )
        try:
            analysis_store.mark_failed(self.session_dir, safe_message)
        except Exception:
            pass
        logger.warning(
            "[LEGION-CONSULT] event=analysis_failed session=%s",
            self.request.session_id,
        )
        self.failed.emit(safe_message)

    def _update_request_state(self, status: str, remote_send_status: str) -> None:
        try:
            update_request_state(
                self.session_dir / "request.json",
                status=status,
                remote_send_status=remote_send_status,
            )
        except Exception as exc:
            logger.warning(
                "[LEGION-CONSULT] event=request_state_update_failed session=%s error=%s",
                self.request.session_id,
                exc.__class__.__name__,
            )

    def _on_thread_finished(self) -> None:
        self._worker = None
        _LIVE_RUNS.discard(self)
