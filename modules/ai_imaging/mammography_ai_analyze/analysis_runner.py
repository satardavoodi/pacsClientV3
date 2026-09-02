"""Run one Mammography Intelligent AI Analyze off the GUI thread.

Reuses the existing EchoMind infrastructure:
- ``ApiWorker`` from ``modules.EchoMind.viewer_chat.ai_chat_api``
- ``EagleEyeImageAnalysis`` from ``openai_reporter`` (company/GapGPT) or
  ``openai_parallel_backend`` (OpenAI-direct)

The architecture mirrors ``eagle_eye_lumbar.llm_runner``: a thin QObject
bridge that gets the work off the GUI thread and delivers the result back
on it, so the workstation stays usable during a multi-image API request.

THE STRONG REFERENCE IS NOT OPTIONAL
--------------------------------------
OPT-51: a running QThread with no live reference is destroyed mid-run and Qt
aborts the PROCESS. ``_LIVE_RUNS`` holds every in-flight run until it
finishes.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import QObject, Signal

from . import package_builder

logger = logging.getLogger(__name__)
ANALYSIS_MODEL = "gpt-5.6-luna"

# Every in-flight run. Module level, so a closing tab cannot collect one.
_LIVE_RUNS: Set["MammographyAnalysisRunner"] = set()


def live_run_count() -> int:
    """In-flight analyses."""
    return len(_LIVE_RUNS)


class MammographyAnalysisRunner(QObject):
    """One analysis of one mammography study.

    Single-shot: construct, ``start()``, take ``finished`` or ``failed``.
    Re-analysing means a new runner, so a stale worker can never write over
    a newer result.
    """

    started = Signal()
    # (stage_name, progress_message)
    progress = Signal(str, str)
    finished = Signal(str)  # the pathological findings text
    failed = Signal(str)

    def __init__(self, study_uid: str = "", csv_path: str = "",
                 package: package_builder.MammographyPackage = None,
                 parent=None):
        super().__init__(parent)
        self._study_uid = study_uid
        self._csv_path = csv_path
        self._package = package  # optional: pre-built package
        self._worker = None
        self._detached = False

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
            self._fail_before_start(
                f"the EchoMind AI worker is unavailable: {exc}"
            )
            return False

        study_uid = self._study_uid
        csv_path = self._csv_path

        # Resolve backend and model (same path as Eagle Eye Lumbar)
        try:
            from modules.ai_imaging.eagle_eye_lumbar.llm_backend import (
                resolve_backend,
                resolve_model,
            )

            backend = resolve_backend()
            resolve_model(backend)
            model = ANALYSIS_MODEL
        except Exception as exc:
            logger.warning(
                "[AI_ANALYZE] backend/model resolution failed (%s); "
                "using defaults",
                exc,
            )
            backend = "company"
            model = ANALYSIS_MODEL

        logger.info(
            "[AI_ANALYZE] Starting async work: model=%s, backend=%s, "
            "study=%s, csv=%s",
            model, backend, study_uid, csv_path or "none",
        )

        def work() -> Dict[str, Any]:
            # Heavy I/O runs HERE in the worker thread, NOT on GUI thread
            try:
                package = package_builder.build_package(
                    study_uid=study_uid,
                    csv_path=csv_path,
                )
                logger.info(
                    "[AI_ANALYZE] Package built: %d images, %d annotations",
                    package.image_count, package.total_annotations,
                )
            except Exception as exc:
                logger.error("[AI_ANALYZE][ERROR] Package build failed: %s", exc)
                return {"error": f"Failed to prepare images: {exc}"}
            return _send_request(package, backend, model)

        worker = ApiWorker(work, parent=self)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_thread_finished)

        self._worker = worker
        _LIVE_RUNS.add(self)
        self.started.emit()
        self.progress.emit("analyzing", "Request started")
        worker.start()

        logger.info(
            "[AI_ANALYZE] Request started: %d images, model=%s",
            package.image_count,
            model,
        )
        return True

    def detach(self) -> None:
        """Close-while-in-flight: let the request die unheard, not mid-thread."""
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
        logger.info("[AI_ANALYZE] Run detached")

    # -- worker callbacks (GUI thread) -------------------------------------

    def _fail_before_start(self, message: str) -> None:
        logger.error("[AI_ANALYZE][ERROR] Cannot start: %s", message)
        self.failed.emit(message)

    def _on_done(self, result: Any) -> None:
        if self._detached:
            return
        if isinstance(result, dict) and result.get("error"):
            self.failed.emit(result["error"])
        elif isinstance(result, dict) and result.get("content"):
            self.finished.emit(result["content"])
        elif isinstance(result, str) and result.strip():
            self.finished.emit(result)
        else:
            self.failed.emit("The model returned an empty response.")

    def _on_worker_failed(self, message: str) -> None:
        if self._detached:
            return
        logger.error("[AI_ANALYZE][ERROR] Worker failed: %s", message)
        self.failed.emit(message)

    def _on_thread_finished(self) -> None:
        self._worker = None
        _LIVE_RUNS.discard(self)


def _company_entitlement_error() -> str:
    """Check company entitlement. Returns '' when OK, else the denial reason.

    Mirrors ``eagle_eye_lumbar.llm_backend.company_entitlement_error``:
    calls the ONE authority (``company_entitled``) which self-heals a session
    where the key is saved in settings but not yet validated in memory.
    """
    try:
        from modules.EchoMind.entitlement import ENTITLEMENT_DENIED, company_entitled
    except Exception as exc:
        return f"the EchoMind entitlement check is unavailable: {exc}"
    try:
        if not company_entitled():
            return ENTITLEMENT_DENIED
        # Keep the credential consumed by EagleEyeImageAnalysis in sync with
        # the entitlement check when another EchoMind surface initialized the
        # manager during startup.
        from modules.EchoMind.api_manager import Manage

        Manage.instance().ensure_detected()
        return ""
    except Exception as exc:
        return f"the EchoMind company credential is unavailable: {exc}"


def _send_request(
    package: package_builder.MammographyPackage,
    backend: str,
    model: str,
) -> Dict[str, Any]:
    """The actual API call, run inside the ApiWorker thread.

    Follows the exact same pattern as ``llm_backend._dispatch``:
    build the user content, call ``EagleEyeImageAnalysis``.
    """
    logger.info("[AI_ANALYZE] Request started")

    try:
        # ── Entitlement BEFORE the first request (same as llm_backend.run_analysis) ──
        # company_entitled() calls the ONE authority that checks the in-memory
        # manager AND falls back to re-validating the saved key from settings.
        # This self-heals a session where the user has not opened EchoMind yet.
        if backend == "company":
            denied = _company_entitlement_error()
            if denied:
                logger.warning("[AI_ANALYZE] refused before sending: %s", denied)
                return {"error": denied}

        # Build the user content: [header, caption, image, caption, image, ...]
        user_content = _build_user_content(package)
        logger.info("[AI_ANALYZE] User content built: %d parts", len(user_content))

        # Get the backend module (same pattern as llm_backend._dispatch)
        module = _backend_module(backend)

        logger.info("[AI_ANALYZE] Sending to %s via %s", model, backend)
        start_time = time.time()

        result = module.EagleEyeImageAnalysis(
            system_prompt=package.system_prompt,
            header=package.header,
            items=package.images,
            model=model,
            max_tokens=6000,
            temperature=0.2,
        )

        elapsed = time.time() - start_time
        logger.info("[AI_ANALYZE] Response received in %.1fs", elapsed)

        # Extract content
        content = ""
        if isinstance(result, dict):
            content = str(result.get("content") or "").strip()
        elif isinstance(result, str):
            content = result.strip()

        if not content:
            logger.warning("[AI_ANALYZE] Empty response from model")
            return {"error": "The model returned an empty response."}

        # Log usage (non-sensitive)
        usage = {}
        if isinstance(result, dict):
            usage = result.get("usage") or {}
        logger.info(
            "[AI_ANALYZE] Response parsed: %d chars, tokens: prompt=%s, "
            "completion=%s",
            len(content),
            usage.get("prompt_tokens", "?"),
            usage.get("completion_tokens", "?"),
        )

        return {"content": content, "usage": usage}

    except Exception as exc:
        error_msg = str(exc).strip() or exc.__class__.__name__
        logger.error(
            "[AI_ANALYZE][ERROR] Request failed: %s (%s)",
            error_msg,
            exc.__class__.__name__,
        )
        return {"error": f"AI analysis failed: {error_msg}"}


def _build_user_content(
    package: package_builder.MammographyPackage,
) -> list:
    """Build the multimodal user content list for the API request.

    Follows the same pattern as ``openai_reporter.build_eagle_eye_user_content``:
    header text, then for each image: caption text + base64 image.
    If CSV data exists, it is appended as a text block.
    """
    import base64

    content: list = []

    # Header text
    if package.header:
        content.append({"type": "text", "text": package.header})

    # Images with captions
    for img in package.images:
        if img.caption:
            content.append({"type": "text", "text": img.caption})
        try:
            with open(img.path, "rb") as handle:
                encoded = base64.b64encode(handle.read()).decode("utf-8")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img.mime};base64,{encoded}",
                        "detail": "high",
                    },
                }
            )
        except Exception as exc:
            logger.warning(
                "[AI_ANALYZE] Failed to encode image %s: %s", img.path, exc
            )
            content.append(
                {"type": "text", "text": f"[Image could not be loaded: {img.path.name}]"}
            )

    # CSV data as text block
    if package.has_csv:
        csv_data = package.csv_data
        csv_header = (
            "\n\nSTRUCTURED AI DETECTION RESULTS (CSV):\n"
            f"Columns: {', '.join(csv_data.columns)}\n"
            f"Rows: {csv_data.row_count}\n\n"
            f"{csv_data.content}"
        )
        content.append({"type": "text", "text": csv_header})

    return content


def _backend_module(backend: str):
    """Get the backend module (company or openai)."""
    if backend == "openai":
        from modules.EchoMind.viewer_chat import openai_parallel_backend as module
    else:
        from modules.EchoMind.viewer_chat import openai_reporter as module

    if not hasattr(module, "EagleEyeImageAnalysis"):
        raise RuntimeError(
            f"the {backend} EchoMind backend has no Eagle Eye image analysis"
        )
    return module
