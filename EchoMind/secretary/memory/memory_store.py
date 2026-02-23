"""
memory_store.py
---------------
EchoMind Secretary — file-based conversation memory.

Storage
-------
- Text files written to  attachment/EchoMindMemory/
- A lightweight ``echomind_memory_files`` table in the shared ``dicom.db``
  tracks (memory_number, filename, filepath, created_at, cycle_count).

Each file holds at most MAX_CYCLES_PER_FILE cycles (default 10).
When the limit is reached a new file is automatically created and the
previous file is deleted from disk (the DB row is preserved for reference).

Each cycle records
------------------
- User request text
- Modules selected  (Phase 1 routing result)
- Document reference (derived from module names)
- GPT JSON command   (Phase 3 action plan)
- Execution result   (ok flag, action, message)
- Patient list       (id, name, modality, body_part, date, time, images_count)

Usage
-----
    store = EchoMindMemoryStore()
    store.start_cycle("Show CT patients from today")
    store.record_modules(["homepage"])
    store.record_doc_ref("homepage.md")
    store.record_gpt_command({"action": "list_patients", ...})
    store.record_execution_result({"ok": True, ...}, patient_rows)
    store.close_cycle()

    context = store.get_context_for_llm()   # inject into Phase 3 LLM prompt
    num, cyc = store.get_current_info()     # (memory_number, cycle_count) for UI
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_CYCLES_PER_FILE: int = 10

# ── File-write lock (module-level — shared across all instances) ───────────────
_file_lock = threading.Lock()

# ── Determine memory folder ────────────────────────────────────────────────────
try:
    from PacsClient.utils.config import BASE_PATH as _BASE
    _MEMORY_DIR: Path = Path(_BASE) / "attachment" / "EchoMindMemory"
except Exception:
    _MEMORY_DIR = Path(__file__).resolve().parents[4] / "attachment" / "EchoMindMemory"

# Same relative DB path used by the rest of the application
_DB_PATH = "dicom.db"


# ── Low-level DB helpers ───────────────────────────────────────────────────────

def _db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(
        _DB_PATH,
        timeout=30.0,
        check_same_thread=False,
        isolation_level="DEFERRED",
    )
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def _create_table() -> None:
    """Create the echomind_memory_files table if it does not yet exist."""
    try:
        with _db_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS echomind_memory_files (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_number  INTEGER NOT NULL,
                    filename       TEXT    NOT NULL,
                    filepath       TEXT    NOT NULL,
                    created_at     TEXT    NOT NULL,
                    cycle_count    INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.commit()
    except Exception:
        pass  # DB might not exist yet — fail silently


# ── Text-formatting helpers ────────────────────────────────────────────────────

def _fmt_patient_list(patients: list[dict[str, Any]]) -> str:
    if not patients:
        return "(none)"
    lines: list[str] = []
    for i, p in enumerate(patients, 1):
        images = p.get("images_count") or p.get("images") or ""
        lines.append(
            f"  {i}. ID:{p.get('patient_id', '')} "
            f"| Name:{p.get('patient_name', '')} "
            f"| Modality:{p.get('modality', '')} "
            f"| Body:{p.get('body_part', '')} "
            f"| Date:{p.get('date', '')} "
            f"| Time:{p.get('time', '')} "
            f"| Images:{images}"
        )
    return "\n".join(lines)


def _make_filename(memory_number: int) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"Memory_{memory_number:03d}_{ts}.txt"


# ── Main class ─────────────────────────────────────────────────────────────────

class EchoMindMemoryStore:
    """
    File-based conversation memory for EchoMind Secretary.

    One instance per ``SecretaryOrchestrator`` is recommended; the memory
    counter starts at 1 each time the software is opened (it continues from
    the highest DB number already stored, so numbering is globally unique).

    Thread-safe for file writes via an internal module-level lock.
    """

    def __init__(self) -> None:
        try:
            _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        _create_table()

        self._memory_number: int = self._next_memory_number()
        self._cycle_count: int = 0
        self._filepath: Path = _MEMORY_DIR / _make_filename(self._memory_number)
        self._db_row_id: int | None = None
        self._register_file()

        # Working dict for the cycle currently being collected
        self._current: dict[str, Any] = {}

    # ── DB helpers ─────────────────────────────────────────────────────────────

    def _next_memory_number(self) -> int:
        try:
            with _db_conn() as conn:
                row = conn.execute(
                    "SELECT COALESCE(MAX(memory_number), 0) FROM echomind_memory_files"
                ).fetchone()
                return (row[0] if row else 0) + 1
        except Exception:
            return 1

    def _register_file(self) -> None:
        try:
            with _db_conn() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO echomind_memory_files
                        (memory_number, filename, filepath, created_at, cycle_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        self._memory_number,
                        self._filepath.name,
                        str(self._filepath),
                        datetime.now().isoformat(timespec="seconds"),
                        0,
                    ),
                )
                conn.commit()
                self._db_row_id = cur.lastrowid
        except Exception:
            self._db_row_id = None

    def _update_cycle_count_in_db(self) -> None:
        if self._db_row_id is None:
            return
        try:
            with _db_conn() as conn:
                conn.execute(
                    "UPDATE echomind_memory_files SET cycle_count = ? WHERE id = ?",
                    (self._cycle_count, self._db_row_id),
                )
                conn.commit()
        except Exception:
            pass

    # ── Cycle lifecycle ─────────────────────────────────────────────────────────

    def start_cycle(self, user_text: str) -> None:
        """
        Begin collecting data for a new cycle.

        If the current file already contains MAX_CYCLES_PER_FILE cycles this
        call transparently creates a new memory file first.
        """
        if self._cycle_count >= MAX_CYCLES_PER_FILE:
            self.new_memory()

        self._current = {
            "cycle_number": self._cycle_count + 1,   # provisional — confirmed on close
            "user_text": user_text,
            "modules": [],
            "doc_ref": "",
            "gpt_command": {},
            "execution_result": {},
            "patient_list": [],
        }

    def record_modules(self, modules: list[str]) -> None:
        """Store the Phase 1 routing result (list of module names)."""
        self._current["modules"] = list(modules or [])
        # Derive doc references from module names (e.g. "homepage" → "homepage.md")
        docs = ", ".join(f"{m}.md" for m in (modules or []))
        self._current["doc_ref"] = docs

    def record_doc_ref(self, doc_name: str) -> None:
        """Override the document reference string explicitly."""
        self._current["doc_ref"] = doc_name or ""

    def record_gpt_command(self, plan: dict[str, Any] | None) -> None:
        """Store the action plan produced by the Phase 3 LLM call."""
        self._current["gpt_command"] = dict(plan) if plan else {}

    def record_execution_result(
        self,
        result: dict[str, Any],
        patient_list: list[dict[str, Any]] | None = None,
    ) -> None:
        """Store the executor output and the resulting patient list."""
        self._current["execution_result"] = {
            "ok": result.get("ok"),
            "action": result.get("action"),
            "message": result.get("message"),
        }
        self._current["patient_list"] = list(patient_list or [])

    def close_cycle(self) -> None:
        """
        Finalise the current cycle — append the formatted block to the .txt
        file and increment the cycle counter in the DB.

        Idempotent: calling close_cycle() when no cycle was started is a no-op.
        """
        if not self._current:
            return

        self._cycle_count += 1
        self._current["cycle_number"] = self._cycle_count
        try:
            self._write_cycle_to_file(self._current)
        except Exception:
            pass
        self._update_cycle_count_in_db()
        self._current = {}

    # ── New memory file ─────────────────────────────────────────────────────────

    def new_memory(self) -> None:
        """
        Create a fresh memory file (triggered by the "New" button or by
        the automatic cycle-limit rollover).

        The previous txt file is deleted from disk; its DB row is retained.
        """
        # Delete old file from disk
        try:
            if self._filepath.exists():
                self._filepath.unlink()
        except Exception:
            pass

        self._memory_number += 1
        self._cycle_count = 0
        self._filepath = _MEMORY_DIR / _make_filename(self._memory_number)
        self._current = {}
        self._register_file()

    # ── LLM context injection ───────────────────────────────────────────────────

    def get_context_for_llm(self, max_cycles: int = 5) -> str:
        """
        Return the last ``max_cycles`` cycles from the current memory file
        formatted as an ``=== CONVERSATION MEMORY ===`` block suitable for
        injecting into the Phase 3 LLM prompt.

        Returns an empty string when there is nothing to report.
        """
        try:
            if not self._filepath.exists():
                return ""
            text = self._filepath.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                return ""

            # Split on "--- Cycle" delimiter and take the most-recent cycles
            raw_blocks = [b.strip() for b in text.split("--- Cycle") if b.strip()]
            if not raw_blocks:
                return ""

            recent = raw_blocks[-max_cycles:]
            content = "\n\n".join(f"--- Cycle {b}" for b in recent)

            return (
                f"=== CONVERSATION MEMORY ===\n"
                f"Memory #{self._memory_number} | Cycles recorded: {self._cycle_count}\n"
                f"\n"
                f"HOW TO READ THIS MEMORY (critical):\n"
                f"  [User Request]      = the spoken command in that cycle\n"
                f"  [GPT Command]       = the action plan you (or a prior call) produced\n"
                f"  [Execution Result]  = ok:True means the action completed successfully\n"
                f"  [Patient List]      = rows returned by the executor; FORMAT:\n"
                f"                        N. ID:<id> | Name:<name> | Modality:<code> | Body:<part> | Date:... | Images:...\n"
                f"                        patient_code for follow-up commands = the numeric ID after 'ID:'\n"
                f"\n"
                f"RESOLUTION RULES:\n"
                f"  1. Scan [Patient List] of the MOST RECENT cycle where ok:True.\n"
                f"  2. Match the user's reference (modality / body_part / name / index) to a row.\n"
                f"  3. Extract the numeric value after 'ID:' — that is the patient_code.\n"
                f"  4. Never use body-part name or modality code as patient_code.\n"
                f"  5. Single match → needs_confirmation=false; multiple matches → needs_confirmation=true.\n"
                f"\n"
                f"{content}\n"
                f"=== END MEMORY ==="
            )
        except Exception:
            return ""

    # ── Status info ─────────────────────────────────────────────────────────────

    def get_current_info(self) -> tuple[int, int]:
        """Return ``(memory_number, cycle_count)`` for the UI status label."""
        return self._memory_number, self._cycle_count

    # ── Private file writer ─────────────────────────────────────────────────────

    def _write_cycle_to_file(self, cycle: dict[str, Any]) -> None:
        n = cycle.get("cycle_number", "?")

        # GPT command JSON
        gpt_cmd_text: str
        try:
            gpt_cmd_text = json.dumps(
                cycle.get("gpt_command") or {}, ensure_ascii=False, indent=2
            )
        except Exception:
            gpt_cmd_text = str(cycle.get("gpt_command") or "")

        # Execution result summary
        res = cycle.get("execution_result") or {}
        res_text = (
            f"ok: {res.get('ok')} | "
            f"action: {res.get('action')} | "
            f"{res.get('message') or ''}"
        )

        patient_text = _fmt_patient_list(cycle.get("patient_list") or [])

        block = (
            f"--- Cycle {n} ---\n"
            f"[User Request]  ← what was spoken\n"
            f"{cycle.get('user_text', '')}\n\n"
            f"[Modules]  ← Phase 1 routing result\n"
            f"{', '.join(cycle.get('modules') or [])}\n\n"
            f"[Document Reference]  ← module catalog docs used\n"
            f"{cycle.get('doc_ref', '')}\n\n"
            f"[GPT Command]  ← action plan sent to Orchestrator\n"
            f"{gpt_cmd_text}\n\n"
            f"[Execution Result]  ← ok:True=success ok:False=failed-or-pending\n"
            f"{res_text}\n\n"
            f"[Patient List]  ← rows returned; use ID: value as patient_code in follow-up commands\n"
            f"{patient_text}\n"
            f"---END---\n\n"
        )

        with _file_lock:
            with open(self._filepath, "a", encoding="utf-8") as fh:
                fh.write(block)
