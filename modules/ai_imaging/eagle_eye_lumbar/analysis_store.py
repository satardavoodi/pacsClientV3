"""The LLM analysis of a captured session: its state, request and result.

Addressed by DIRECTORY, not by the `EagleEyeCaptureSession` object. By the time
an analysis runs the capture object has usually been written and dropped, and a
retry or a re-open happens long after it is gone - so anything that needed the
live object could not reopen a result, which is the whole point of §13/§14.

ONE AUTHORITY FOR THE STATE
---------------------------
``llm_result.json`` holds the state. It is deliberately NOT mirrored into
``session.json``: two files claiming to know whether an analysis finished is two
files that can disagree, and the wrong one is always the one someone reads.

STALE "ANALYZING"
-----------------
A crash (or a close) during a request leaves ``analyzing`` on disk with nothing
left to finish it. A state that can never be left is a state that blocks retry
forever, so the record carries the pid and the start time, and a reader in a
different process - or after `STALE_AFTER_S` - is told the run is stale and
offered a retry instead.

Pure python: no Qt, no network.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .constants import (
    EAGLE_EYE_VERSION,
    LLM_REQUEST_JSON,
    LLM_RESULT_JSON,
    LLM_RESULT_TXT,
)

logger = logging.getLogger(__name__)

STATE_NOT_ANALYZED = "not_analyzed"
STATE_ANALYZING = "analyzing"
STATE_COMPLETE = "complete"
STATE_FAILED = "failed"

STATE_LABELS = {
    STATE_NOT_ANALYZED: "Not analyzed",
    STATE_ANALYZING: "Analyzing",
    STATE_COMPLETE: "Analysis complete",
    STATE_FAILED: "Analysis failed",
}

# A request carrying tens of high-detail screenshots is slow, but not this slow.
STALE_AFTER_S = 1800.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_seconds(stamp: str) -> Optional[float]:
    try:
        started = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started).total_seconds()


def _write_json(path: Path, document: Dict[str, Any]) -> None:
    """Temp file then replace, so a crash mid-write leaves the old state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False, default=str)
    os.replace(str(tmp), str(path))


class AnalysisRecord:
    """What is known about one session's analysis, read from disk."""

    __slots__ = ("state", "stale", "text", "error", "document", "path")

    def __init__(self, state: str, path: Path, stale: bool = False,
                 text: str = "", error: str = "",
                 document: Optional[Dict[str, Any]] = None):
        self.state = state
        self.path = Path(path)
        self.stale = bool(stale)
        self.text = str(text or "")
        self.error = str(error or "")
        self.document = dict(document or {})

    @property
    def label(self) -> str:
        if self.stale:
            return "Analysis interrupted"
        return STATE_LABELS.get(self.state, self.state)

    @property
    def has_result(self) -> bool:
        return self.state == STATE_COMPLETE and bool(self.text.strip())

    @property
    def can_retry(self) -> bool:
        """A failed or interrupted run retries; a finished one re-analyses."""
        return self.state == STATE_FAILED or self.stale

    @property
    def in_flight(self) -> bool:
        return self.state == STATE_ANALYZING and not self.stale

    @property
    def model(self) -> str:
        """The run-level summary. `stage_models` is the per-pass truth."""
        return str(self.document.get("model") or "")

    @property
    def stage_models(self):
        """One model per stage, in order. Empty for records written before
        per-stage models existed - fall back to `model` there."""
        return [str(m or "") for m in (self.document.get("stage_models") or [])]

    @property
    def pipeline_id(self) -> str:
        return str(self.document.get("pipeline_id") or "")

    @property
    def prompt_version(self) -> str:
        """The analysis version. Prefers the pipeline's; falls back to the
        single-prompt key so a record written by v1.x still reads."""
        return str(self.document.get("pipeline_version")
                   or self.document.get("prompt_version") or "")

    @property
    def stage_count(self) -> int:
        return int(self.document.get("stage_count") or 0)

    @property
    def completed_at(self) -> str:
        return str(self.document.get("completed_at") or "")


def result_path(session_dir) -> Path:
    return Path(session_dir) / LLM_RESULT_TXT


def request_path(session_dir) -> Path:
    return Path(session_dir) / LLM_REQUEST_JSON


def read_record(session_dir) -> AnalysisRecord:
    """Current analysis state for a session directory. Never raises."""
    root = Path(session_dir)
    doc_path = root / LLM_RESULT_JSON
    try:
        with doc_path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except FileNotFoundError:
        return AnalysisRecord(STATE_NOT_ANALYZED, root)
    except (OSError, ValueError) as exc:
        logger.warning("[EAGLE-EYE-LLM] unreadable %s: %s", doc_path, exc)
        return AnalysisRecord(STATE_NOT_ANALYZED, root)

    state = str(document.get("state") or STATE_NOT_ANALYZED)

    text = ""
    if state == STATE_COMPLETE:
        try:
            text = (root / LLM_RESULT_TXT).read_text(encoding="utf-8")
        except (OSError, ValueError):
            # The pointer says complete but the text is gone. Reporting
            # "complete" and then showing an empty window is the worst of the
            # options; treat it as a failure that can be retried.
            return AnalysisRecord(
                STATE_FAILED, root, error="the saved result text is missing",
                document=document)

    stale = False
    if state == STATE_ANALYZING:
        age = _age_seconds(document.get("started_at") or "")
        owner = document.get("pid")
        stale = (owner != os.getpid()) or (age is not None and age > STALE_AFTER_S)

    return AnalysisRecord(state, root, stale=stale, text=text,
                          error=str(document.get("error") or ""),
                          document=document)


def write_request(session_dir, document: Dict[str, Any]) -> Path:
    """Record exactly what is about to be sent, before sending it."""
    path = request_path(session_dir)
    _write_json(path, document)
    return path


# ── per-stage artifacts ──────────────────────────────────────────────────────
# Every pass is kept in full. Comparing a one-pass run with a two-pass one, or
# measuring whether verification actually improved anything, is only possible
# if BOTH passes survive - the screening list, the verification audit, and what
# each was asked. Named by position so a third stage needs no new vocabulary.

def stage_request_path(session_dir, number: int) -> Path:
    return Path(session_dir) / f"llm_stage{int(number)}_request.json"


def stage_response_path(session_dir, number: int) -> Path:
    return Path(session_dir) / f"llm_stage{int(number)}_response.txt"


def stage_structured_path(session_dir, number: int) -> Path:
    return Path(session_dir) / f"llm_stage{int(number)}_structured.json"


def write_stage_request(session_dir, number: int, stage,
                        document: Dict[str, Any]) -> Path:
    path = stage_request_path(session_dir, number)
    _write_json(path, document)
    return path


def write_stage_response(session_dir, number: int, stage, text: str,
                         structured: Optional[Dict[str, Any]] = None,
                         usage: Optional[Dict[str, Any]] = None) -> Path:
    """The raw answer, and its structured block when it parsed.

    `structured` is None when the model's JSON did not parse. That is recorded
    as an explicit `parsed: false` rather than an absent file, so a later
    evaluation can tell "the model produced nothing structured" apart from
    "nobody looked".

    `usage` is recorded so `parsed: false` can be told apart from its most
    likely CAUSE. On session 20260826T202150Z stage 1's JSON was cut off
    mid-string at 3996 completion tokens against a 4000 ceiling: not a model
    that cannot emit JSON, a model that ran out of room. Those two need
    completely different fixes, and without the numbers beside the flag they
    look identical.
    """
    root = Path(session_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = stage_response_path(root, number)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(str(text or ""), encoding="utf-8")
    os.replace(str(tmp), str(path))

    ceiling = int(getattr(stage, "max_output_tokens", 0) or 0)
    produced = int((usage or {}).get("completion_tokens") or 0)
    _write_json(stage_structured_path(root, number), {
        "stage_number": int(number),
        "stage": getattr(stage, "name", ""),
        "prompt_id": getattr(stage, "id", ""),
        "prompt_version": getattr(stage, "version", ""),
        "model": str((usage or {}).get("model") or ""),
        "parsed": structured is not None,
        "completion_tokens": produced,
        "max_output_tokens": ceiling,
        # Providers do not agree on how to report a length stop, and some omit
        # it entirely, so infer it from what we DO get back on every backend.
        # The margin is deliberate: a model that stops one or two tokens short
        # of its ceiling did not choose to stop there.
        "truncated": bool(ceiling and produced and produced >= ceiling - 8),
        "data": structured,
    })
    return path


def mark_analyzing(session_dir, analysis, model: str = "", backend: str = "",
                   image_count: int = 0, models=None) -> Dict[str, Any]:
    """Claim the session for a run in flight. Returns the written document.

    ``model`` is the run-level summary; ``models`` is one entry per stage, in
    order. The passes may run on DIFFERENT models (a stage can be A/B-tested on
    its own), and a single string cannot describe that without lying about one
    of them - so the per-stage list is what a later comparison should read.
    """
    document = {
        "eagle_eye_version": EAGLE_EYE_VERSION,
        "state": STATE_ANALYZING,
        "started_at": _utc_now_iso(),
        "completed_at": None,
        "pid": os.getpid(),
        "model": str(model or ""),
        "stage_models": [str(m or "") for m in (models or [])],
        "backend": str(backend or ""),
        "image_count": int(image_count or 0),
        "error": "",
    }
    if analysis is not None:
        document.update(analysis.as_dict())
    _write_json(Path(session_dir) / LLM_RESULT_JSON, document)
    return document


def mark_complete(session_dir, text: str, started: Optional[Dict[str, Any]] = None,
                  usage: Optional[Dict[str, Any]] = None) -> AnalysisRecord:
    """Save the model's answer and flip the state.

    The TEXT is written first: a reader that sees ``complete`` must always find
    something to show, so the pointer is the last thing to change.
    """
    root = Path(session_dir)
    root.mkdir(parents=True, exist_ok=True)
    body = str(text or "")

    tmp = root / (LLM_RESULT_TXT + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(str(tmp), str(root / LLM_RESULT_TXT))

    document = dict(started or {})
    document.update({
        "eagle_eye_version": EAGLE_EYE_VERSION,
        "state": STATE_COMPLETE,
        "completed_at": _utc_now_iso(),
        "error": "",
        "result_file": LLM_RESULT_TXT,
        "result_characters": len(body),
        "usage": dict(usage or {}),
    })
    _write_json(root / LLM_RESULT_JSON, document)
    logger.info("[EAGLE-EYE-LLM] analysis complete for %s (%d chars)",
                root.name, len(body))
    return AnalysisRecord(STATE_COMPLETE, root, text=body, document=document)


def mark_failed(session_dir, error: str,
                started: Optional[Dict[str, Any]] = None) -> AnalysisRecord:
    """Record the failure WITHOUT touching the captures.

    Capture succeeded and the request did not; nothing about the images is in
    doubt, so a retry must never mean recapturing the study.
    """
    root = Path(session_dir)
    document = dict(started or {})
    document.update({
        "eagle_eye_version": EAGLE_EYE_VERSION,
        "state": STATE_FAILED,
        "completed_at": _utc_now_iso(),
        "error": str(error or "unknown error"),
    })
    _write_json(root / LLM_RESULT_JSON, document)
    logger.warning("[EAGLE-EYE-LLM] analysis failed for %s: %s", root.name, error)
    return AnalysisRecord(STATE_FAILED, root, error=str(error or ""), document=document)
