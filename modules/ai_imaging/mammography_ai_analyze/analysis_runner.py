"""Off-GUI-thread runner for bounded mammography evidence analysis."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Set

from PySide6.QtCore import QObject, Signal

from modules.ai_imaging.eagle_eye_lumbar import llm_backend

from . import package_builder
from .source_snapshot import MammographySourceHint

logger = logging.getLogger(__name__)


class _MammographyModelStage:
    name = "mammography"
    model_default = "gpt-5.6-luna"
    model_feature = "eagle_eye"


_MODEL_STAGE = _MammographyModelStage()
_LIVE_RUNS: Set["MammographyAnalysisRunner"] = set()


def live_run_count() -> int:
    return len(_LIVE_RUNS)


class MammographyAnalysisRunner(QObject):
    """Run one study package and request without blocking the Qt GUI thread."""

    started = Signal()
    progress = Signal(str, str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        study_uid: str,
        attachments_root: Path | str,
        detection_csv_path: Path | str | None = None,
        classification_csv_path: Path | str | None = None,
        local_source_hints: tuple[MammographySourceHint, ...] = (),
        parent=None,
    ):
        super().__init__(parent)
        self._study_uid = str(study_uid or "").strip()
        self._attachments_root = Path(attachments_root)
        self._detection_csv_path = Path(detection_csv_path) if detection_csv_path else None
        self._classification_csv_path = (
            Path(classification_csv_path) if classification_csv_path else None
        )
        self._local_source_hints = tuple(local_source_hints)
        self._worker = None
        self._detached = False

    @property
    def running(self) -> bool:
        return self._worker is not None

    def start(self) -> bool:
        if self.running:
            return False
        if not self._study_uid:
            self._fail_before_start("The mammography study identity is unavailable.")
            return False
        try:
            from modules.EchoMind.viewer_chat.ai_chat_api import ApiWorker
        except Exception as exc:
            self._fail_before_start(f"The EchoMind AI worker is unavailable: {exc}")
            return False

        backend = llm_backend.resolve_backend()
        model = llm_backend.resolve_model(backend, _MODEL_STAGE)

        def work() -> dict[str, Any]:
            detection = self._detection_csv_path
            classification = self._classification_csv_path
            if detection is None:
                detection, classification = package_builder.resolve_active_csv_paths(
                    self._study_uid, self._attachments_root
                )
            self.progress.emit("preparing", "Preparing mammography evidence")
            try:
                package = package_builder.build_package(
                    study_uid=self._study_uid,
                    detection_csv_path=detection,
                    classification_csv_path=classification,
                    local_source_hints=self._local_source_hints,
                )
            except package_builder.PackageError as exc:
                return {"error": str(exc)}
            with package:
                self.progress.emit("analyzing", "Reviewing mammography evidence")
                return _send_request(package, backend=backend, model=model)

        worker = ApiWorker(work, parent=self)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_thread_finished)
        self._worker = worker
        _LIVE_RUNS.add(self)
        self.started.emit()
        worker.start()
        logger.info("[MAMMOGRAPHY-AI] request started backend=%s model=%s", backend, model)
        return True

    def detach(self) -> None:
        """Disconnect UI delivery while retaining the worker until it finishes."""
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
        logger.info("[MAMMOGRAPHY-AI] request detached")

    def _fail_before_start(self, message: str) -> None:
        logger.warning("[MAMMOGRAPHY-AI] request could not start")
        self.failed.emit(str(message))

    def _on_done(self, result: Any) -> None:
        if self._detached:
            return
        if isinstance(result, dict) and result.get("error"):
            self.failed.emit(str(result["error"]))
            return
        content = result.get("content") if isinstance(result, dict) else result
        text = str(content or "").strip()
        if text:
            self.finished.emit(text)
        else:
            self.failed.emit("The model returned an empty response.")

    def _on_worker_failed(self, message: str) -> None:
        if not self._detached:
            self.failed.emit(str(message))

    def _on_thread_finished(self) -> None:
        self._worker = None
        _LIVE_RUNS.discard(self)


def _backend_module(backend: str):
    if backend == "openai":
        from modules.EchoMind.viewer_chat import openai_parallel_backend as module
    else:
        from modules.EchoMind.viewer_chat import openai_reporter as module
    if not hasattr(module, "EagleEyeImageAnalysis"):
        raise RuntimeError("The selected EchoMind backend cannot analyze image evidence.")
    return module


def _send_request(
    package: package_builder.MammographyPackage,
    *,
    backend: str,
    model: str,
) -> dict[str, Any]:
    if backend == "company":
        denied = llm_backend.company_entitlement_error()
        if denied:
            return {"error": denied}
    module = _backend_module(backend)
    result = module.EagleEyeImageAnalysis(
        system_prompt=package.system_prompt,
        header=package.header,
        items=package.images,
        model=model,
        max_tokens=6000,
        temperature=0.0,
    )
    if isinstance(result, dict):
        return result
    return {"content": str(result or "")}
