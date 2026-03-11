"""
session_log.py
--------------
Lightweight session tracker for EchoMind Secretary requests.

Each call to orchestrator.handle() gets one SessionLog object:
  - session_id: unique UUID per handle() call
  - thread_id : ID of the calling thread
  - started_at: ISO timestamp
  - entries   : ordered list of log dicts (step tracing)
  - closed_at : ISO timestamp when the session ends

On close(), the session is flushed as a single JSON line to:
    <LOG_DIR>/<YYYY-MM-DD>.jsonl

where LOG_DIR defaults to  data/echomind_logs/  (relative to workspace root).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Any

# ── Log directory ──────────────────────────────────────────────────────────────
try:
    from PacsClient.utils.data_paths import ECHOMIND_LOGS_DIR
    _LOG_DIR = ECHOMIND_LOGS_DIR
except Exception:
    _LOG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "echomind_logs"


class SessionLog:
    """
    Tracks one EchoMind Secretary request from start to finish.

    Usage::

        session = SessionLog(user_text="show today's patients")
        session.add("plan", {"action": "list_patients", ...})
        session.add("result", {"ok": True, ...})
        session.close(result)          # writes to log file
    """

    def __init__(self, user_text: str, session_id: str | None = None):
        self.session_id: str = session_id or f"echomind-{uuid.uuid4().hex[:12]}"
        self.thread_id: int = threading.get_ident()
        self.started_at: str = datetime.now().isoformat(timespec="seconds")
        self.user_text: str = user_text
        self.entries: list[dict[str, Any]] = []
        self._closed = False

    # ------------------------------------------------------------------
    # Entry helpers

    def add(self, key: str, value: Any) -> None:
        """Append a named entry to the log timeline."""
        self.entries.append({
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "key": key,
            "value": value,
        })

    def add_plan(self, plan: dict[str, Any]) -> None:
        self.add("plan", plan)

    def add_result(self, result: dict[str, Any]) -> None:
        self.add("result", result)

    def add_error(self, error: str, attempt: int | None = None) -> None:
        self.add("error", {"message": error, "attempt": attempt})

    def add_repair(self, repaired_plan: dict[str, Any], attempt: int) -> None:
        self.add("repair", {"attempt": attempt, "plan": repaired_plan})

    # ------------------------------------------------------------------
    # Persistence

    def close(self, result: dict[str, Any] | None = None) -> None:
        """Finalize the session and append a JSON-Lines record to today's log file."""
        if self._closed:
            return
        self._closed = True
        closed_at = datetime.now().isoformat(timespec="seconds")
        if result is not None:
            self.add_result(result)

        record = {
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "started_at": self.started_at,
            "closed_at": closed_at,
            "user_text": self.user_text,
            "entries": self.entries,
            "ok": bool(result.get("ok")) if isinstance(result, dict) else None,
            "action": result.get("action") if isinstance(result, dict) else None,
        }

        try:
            log_dir = Path(_LOG_DIR)
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"{date.today().isoformat()}.jsonl"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            # Never let logging fail the pipeline
            sys.stderr.write(
                f"[EchoMind | Session ] WARNING — could not write session log: {exc}\n"
            )
            sys.stderr.flush()

    def __repr__(self) -> str:
        return (
            f"<SessionLog id={self.session_id!r} "
            f"user={self.user_text[:40]!r} entries={len(self.entries)}>"
        )
