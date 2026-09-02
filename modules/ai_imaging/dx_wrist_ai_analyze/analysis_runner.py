"""Run DX wrist PNG analysis through the configured multimodal API."""

from __future__ import annotations

import logging
from typing import Any, Set

from PySide6.QtCore import QObject, Signal

from . import package_builder

logger = logging.getLogger(__name__)
ANALYSIS_MODEL = "gpt-5.6-luna"
_LIVE_RUNS: Set["DXWristAnalysisRunner"] = set()


class DXWristAnalysisRunner(QObject):
    """Single-shot worker for one DX wrist intelligent analysis."""

    started = Signal()
    progress = Signal(str, str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, study_uid: str, source_dir: str, output_dir: str, parent=None):
        super().__init__(parent)
        self.study_uid = study_uid
        self.source_dir = source_dir
        self.output_dir = output_dir
        self._worker = None
        self._detached = False

    @property
    def running(self) -> bool:
        return self._worker is not None

    def start(self) -> bool:
        if self.running:
            return False
        try:
            from modules.EchoMind.viewer_chat.ai_chat_api import ApiWorker
            from modules.ai_imaging.eagle_eye_lumbar.llm_backend import resolve_backend, resolve_model
        except Exception as exc:
            self.failed.emit(f"The AI worker is unavailable: {exc}")
            return False

        backend = resolve_backend()
        resolve_model(backend)
        model = ANALYSIS_MODEL

        def work() -> dict[str, Any]:
            try:
                package = package_builder.build_package(
                    self.study_uid, self.source_dir, self.output_dir
                )
                if backend == "company":
                    from modules.EchoMind.entitlement import company_entitled
                    from modules.EchoMind.api_manager import Manage

                    if not company_entitled():
                        return {"error": "The AI-PACS company key is not authorized."}
                    Manage.instance().ensure_detected()
                module = self._backend_module(backend)
                result = module.EagleEyeImageAnalysis(
                    system_prompt=package.system_prompt,
                    header=package.header,
                    items=package.images,
                    model=model,
                    max_tokens=3000,
                    temperature=0.1,
                )
                content = result.get("content", "") if isinstance(result, dict) else str(result)
                return {"content": str(content or "").strip()}
            except Exception as exc:
                logger.error("[DX_WRIST_AI][ERROR] analysis failed: %s", exc)
                return {"error": str(exc)}

        worker = ApiWorker(work, parent=self)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        _LIVE_RUNS.add(self)
        self.started.emit()
        self.progress.emit("analyzing", "Preparing DX wrist images")
        worker.start()
        return True

    @staticmethod
    def _backend_module(backend: str):
        if backend == "openai":
            from modules.EchoMind.viewer_chat import openai_parallel_backend as module
        else:
            from modules.EchoMind.viewer_chat import openai_reporter as module
        return module

    def detach(self) -> None:
        self._detached = True
        if self._worker is not None:
            for signal_name in ("done", "failed"):
                try:
                    getattr(self._worker, signal_name).disconnect()
                except Exception:
                    pass
            try:
                self._worker.setParent(None)
            except Exception:
                pass

    def _on_done(self, result: Any) -> None:
        if self._detached:
            return
        if isinstance(result, dict) and result.get("error"):
            self.failed.emit(str(result["error"]))
        elif isinstance(result, dict) and result.get("content"):
            self.finished.emit(str(result["content"]))
        else:
            self.failed.emit("The model returned an empty response.")

    def _on_failed(self, message: str) -> None:
        if not self._detached:
            self.failed.emit(str(message))

    def _on_finished(self) -> None:
        self._worker = None
        _LIVE_RUNS.discard(self)
