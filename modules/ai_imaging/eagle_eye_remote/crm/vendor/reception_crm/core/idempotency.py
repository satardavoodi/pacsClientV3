"""Write de-duplication.

    Agents retry. Networks time out mid-write. Neither may create two
    receptions.   (docs/security-model.md §5)

Rules, exactly:
  * a replayed key with the SAME payload returns the ORIGINAL result and does
    not call the CRM again;
  * a replayed key with a DIFFERENT payload is a hard error, not a new write —
    it means the client is confused, and guessing which one it meant is the one
    thing we must not do;
  * records live 24 hours.

Backed by a JSON file under ``<data_root>/data/idempotency.json`` so a gateway
restart cannot resurrect a duplicate admission.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from .errors import ReceptionCoreError

TTL_SECONDS = 24 * 60 * 60


class IdempotencyConflictError(ReceptionCoreError):
    code = "IDEMPOTENCY_CONFLICT"


class IdempotencyStore:
    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "data" / "idempotency.json"
        self._lock = threading.Lock()

    def lookup(self, key: str, payload_hash: str) -> dict[str, Any] | None:
        if not key:
            return None
        with self._lock:
            records = self._load()
            record = records.get(key)
            if not record:
                return None
            if record.get("payload_hash") != payload_hash:
                raise IdempotencyConflictError(
                    "This request id was already used with a different payload."
                )
            return record.get("result")

    def remember(self, key: str, payload_hash: str, result: dict[str, Any]) -> None:
        if not key:
            return
        with self._lock:
            records = self._load()
            records[key] = {
                "payload_hash": payload_hash,
                "result": result,
                "stored_at": time.time(),
            }
            self._save(records)

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        cutoff = time.time() - TTL_SECONDS
        return {k: v for k, v in raw.items() if isinstance(v, dict) and float(v.get("stored_at", 0)) >= cutoff}

    def _save(self, records: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(self._path)
