"""
Stage 2a — the BACKGROUND lower-threshold re-analysis.

Fires an MG analysis at (original_threshold - 0.05) the moment the 3D Cursor is
activated, so it runs *while* the radiologist is placing landmarks. By the time
they finish the three picks, the extra detections are usually already back.

WHY A SEPARATE LAUNCHER (and not `AIChatInteractorStyle.start_mg_process`)
────────────────────────────────────────────────────────────────────────────────
`start_mg_process` cannot be reused for this, for three independent reasons:

  1. It shows an APPLICATION-MODAL overlay
     (`ai_chat_interactorstyle.py:834`, `setWindowModality(ApplicationModal)`).
     That freezes the entire app for the duration of the run — including the
     guided picker the user is supposed to be interacting with. It is the single
     line that makes the requested workflow impossible.

  2. It opens a threshold dialog and a Re-run/Open/Cancel pre-flight prompt.
     The second pass is automatic; it must not ask the user anything.

  3. It holds the worker on the transient interactor style, which is replaced on
     every Eagle Eye trigger — orphaning a running QThread.

So this controller launches `MamoWorker` directly, silently, and holds the
reference on a LONG-LIVED owner (the ImagingToolsTab). `start_mg_process` is left
completely untouched: the normal, user-initiated analysis path is byte-identical.

REUSE BEFORE RERUN
────────────────────────────────────────────────────────────────────────────────
If a run at the target threshold already exists on disk for this study, we use it
instead of calling the backend again. Re-running costs ~minutes of AI server time,
and produces `_2`, `_3`, `_4`... duplicates in the AI Results dropdown for zero
clinical gain.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from .. import mg_ai_runs
from .threshold_policy import (  # noqa: F401  (re-exported for callers)
    MIN_THRESHOLD,
    THRESHOLD_STEP,
    second_pass_threshold,
    threshold_ladder,
)

# Diagnostics go through the LOGGER, not print().
#
# Live finding (2026-07-14): every `[3D-Cursor]` print() in this feature was
# invisible in `user_data/logs/app.log` — prints go to stdout, which in a
# VS Code source run lands in the terminal and is lost afterwards. Debugging the
# first real failure therefore required reading the CSVs by hand. Modules that use
# `logging.getLogger(__name__)` (e.g. TrainingUI) DO reach app.log. Use the logger.
logger = logging.getLogger(__name__)


# Master kill switch. `=0` disables the second pass entirely — the 3D Cursor then
# falls back to Stage-1-only (geometry region, no AI candidates), which is exactly
# the legacy behaviour plus a better region.
ENABLED = os.getenv("AIPACS_CURSOR3D_SECOND_PASS", "1").strip().lower() not in ("0", "false", "no", "off")


class SecondPassController(QObject):
    """
    Launches (or reuses) a lower-threshold MG analysis in the background.

    Signals:
        started(float)                     — threshold the pass is running at
        reused(str, float)                 — detection_csv, threshold (no backend call)
        finished(str, str, float)          — detection_csv, classification_csv, threshold
        failed(str)                        — human-readable error
    """

    started = Signal(float)
    reused = Signal(str, float)
    finished = Signal(str, str, float)
    failed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._worker = None            # strong ref — do NOT let this be GC'd
        self._threshold: Optional[float] = None
        self._run_id: Optional[str] = None
        self._study_uid: Optional[str] = None
        self._attachments_path: Optional[str] = None

    # ── introspection ────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @property
    def threshold(self) -> Optional[float]:
        return self._threshold

    @property
    def run_id(self) -> Optional[str]:
        return self._run_id

    # ── launch ───────────────────────────────────────────────────────────────

    def start(
        self,
        *,
        study_uid: str,
        attachments_path: str,
        original_threshold: float,
        threshold: Optional[float] = None,
        breast_url: Optional[str] = None,
        allow_reuse: bool = True,
    ) -> bool:
        """
        Begin a second pass. Returns True if a pass is now in flight OR an existing
        run was reused; False if the second pass is unavailable.

        Args:
            threshold: run at THIS threshold instead of `original − 0.05`. Used by
                the escalation ladder to step deeper when the first rung finds
                nothing inside the predicted region.

        NEVER raises and NEVER blocks — it is called on the GUI thread from the
        3D Cursor button handler, immediately before the guided picker opens.
        """
        if not ENABLED:
            return False

        if self.is_running:
            # A pass is already in flight for this session — don't stack them.
            return True

        target = (
            round(float(threshold), 2) if threshold is not None
            else second_pass_threshold(original_threshold)
        )
        self._study_uid = str(study_uid)
        self._attachments_path = str(attachments_path)
        self._threshold = target

        # 1) Reuse an existing run at this threshold, if we have one.
        if allow_reuse:
            existing = mg_ai_runs.find_run_by_threshold(
                self._study_uid, self._attachments_path, target
            )
            if existing:
                det = str(existing.get("detection") or "")
                self._run_id = existing.get("run_id")
                logger.info(f"[3D-Cursor][2ND-PASS] reusing existing run at {target:.2f}: {det}")
                self.reused.emit(det, target)
                return True

        # 2) Otherwise, call the backend — off-thread, no modal overlay.
        if not breast_url:
            try:
                from PacsClient.utils.utils import get_server_url
                breast_url = get_server_url("breast")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[3D-Cursor][2ND-PASS] cannot resolve AI server: {exc}")
                return False

        if not breast_url:
            logger.warning(
                "[3D-Cursor][2ND-PASS] AI (breast) server URL not configured — skipping second pass"
            )
            return False

        try:
            from modules.viewer.interactor_styles.ai_chat_interactorstyle import MamoWorker
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[3D-Cursor][2ND-PASS] MamoWorker unavailable: {exc}")
            return False

        try:
            worker = MamoWorker(
                study_uid=self._study_uid,
                breast_url=breast_url,
                det_eval_thr=target,
            )
            worker.finished.connect(self._on_worker_finished)
            worker.error.connect(self._on_worker_error)
            self._worker = worker
            logger.info(
                f"[3D-Cursor][2ND-PASS] launching background analysis at threshold {target:.2f}"
            )
            self.started.emit(target)
            worker.start()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[3D-Cursor][2ND-PASS] launch failed: {exc}")
            self._worker = None
            return False

    def cancel(self) -> None:
        """Best-effort cancel. The worker checks `canceled` between phases."""
        if self._worker is not None:
            try:
                self._worker.canceled = True
            except Exception:
                pass

    # ── worker callbacks (GUI thread, via queued signal) ─────────────────────

    def _on_worker_finished(self, out: dict) -> None:
        det = str((out or {}).get("csv") or "")
        cls = str((out or {}).get("csv_classification") or "")

        if not det or not os.path.isfile(det):
            self.failed.emit("Lower-threshold analysis returned no detection CSV.")
            self._worker = None
            return

        # Register the run so it is selectable from the AI Results dropdown —
        # but do NOT make it active: that would swap the boxes out from under the
        # user mid-workflow.
        self._run_id = mg_ai_runs.append_run(
            self._study_uid,
            self._attachments_path,
            detection_csv=det,
            classification_csv=cls or None,
            threshold=self._threshold,
            source="cursor3d_second_pass",
            set_active=False,
        )

        logger.info(
            f"[3D-Cursor][2ND-PASS] done threshold={self._threshold:.2f} "
            f"run_id={self._run_id} csv={os.path.basename(det)}"
        )
        self.finished.emit(det, cls, float(self._threshold or 0.0))
        self._worker = None

    def _on_worker_error(self, message: str) -> None:
        # MamoWorker now reads the response BODY before raising (it used to call
        # resp.raise_for_status(), which discarded it and surfaced a bare
        # "Bad Gateway"), so `message` should name the real cause.
        logger.error(f"[3D-Cursor][2ND-PASS] failed: {message}")
        self.failed.emit(str(message))
        self._worker = None
