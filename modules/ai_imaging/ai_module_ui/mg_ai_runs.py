"""
MG AI run registry — append a run to `mg_ai_manifest.json` WITHOUT activating it.

WHY THIS EXISTS
────────────────────────────────────────────────────────────────────────────────
The existing writer (`ai_chat_interactorstyle._save_mg_manifest`) appends a run to
`available[]` AND repoints `active` at it. That is right for a user-initiated
analysis — they asked for it, they want to see it.

It is WRONG for the 3D Cursor's automatic second pass. Repointing `active` would
swap every box in every viewport out from under a radiologist who is midway
through picking landmarks. The second-pass result must be:

    • preserved on disk                     (it already is — filenames are unique)
    • selectable from the AI Results dropdown  (needs an `available[]` entry)
    • NOT displayed as the active run unless the user chooses it

Hence: append-only, `active` untouched by default.

Manifest shape (unchanged, back-compatible):

    {
      "available": [ {"detection": ..., "classification": ..., "threshold": 0.45,
                      "run_id": ..., "created_at": ..., "source": ...}, ... ],
      "active":    {"detection": ..., "classification": ...}
    }

`run_id`, `created_at` and `source` are NEW keys. They are safe to add: the reader
`PacsClient.utils.utils.load_mg_ai_runs` splats each entry with `**run`, so unknown
keys pass through untouched, and every existing consumer keys off
`detection`/`classification`/`threshold` only. Older manifests without these keys
keep working — every read is a `.get()`.

This closes a real gap: today a "run" has NO identity beyond its filename, and two
runs at the same threshold collide into "Threshold 0.45" and "Threshold 0.45_2"
with no semantics. The spec requires "each analysis run receives a unique result
identifier"; `run_id` is that identifier.

Purity: stdlib only. No Qt, no VTK.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

MANIFEST_FILENAME = "mg_ai_manifest.json"


def manifest_path(study_uid: str, attachments_path: str) -> str:
    return os.path.join(str(attachments_path), str(study_uid), MANIFEST_FILENAME)


def _load(path: str) -> Dict[str, Any]:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                data.setdefault("available", [])
                data.setdefault("active", {})
                return data
    except Exception:
        pass
    return {"available": [], "active": {}}


def _atomic_write(path: str, doc: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def append_run(
    study_uid: str,
    attachments_path: str,
    detection_csv: str,
    classification_csv: Optional[str] = None,
    threshold: Optional[float] = None,
    *,
    run_id: Optional[str] = None,
    source: str = "second_pass",
    set_active: bool = False,
) -> Optional[str]:
    """
    Register an analysis run in the manifest.

    Args:
        set_active: default False. Pass True ONLY when the user explicitly asked
                    for this run to be shown. The automatic second pass must never
                    set it — see the module docstring.

    Returns the run_id, or None on failure. Never raises: a manifest write failure
    must not break an analysis whose CSV is already safely on disk.
    """
    try:
        path = manifest_path(study_uid, attachments_path)
        doc = _load(path)

        rid = run_id or new_run_id()
        det = str(detection_csv)
        cls = str(classification_csv) if classification_csv else None

        # De-dupe on the (detection, classification) pair — the identity the rest
        # of the codebase already uses.
        for entry in doc["available"]:
            if entry.get("detection") == det and entry.get("classification") == cls:
                entry.setdefault("run_id", rid)
                entry.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
                entry.setdefault("source", source)
                if set_active:
                    doc["active"] = {"detection": det, "classification": cls}
                _atomic_write(path, doc)
                return entry.get("run_id")

        doc["available"].append({
            "detection": det,
            "classification": cls,
            "threshold": float(threshold) if threshold is not None else None,
            "run_id": rid,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": source,
        })

        if set_active:
            doc["active"] = {"detection": det, "classification": cls}

        _atomic_write(path, doc)
        return rid
    except Exception as exc:  # noqa: BLE001
        print(f"[3D-Cursor][RUNS] manifest append failed (non-fatal): {exc}")
        return None


def find_run_by_threshold(
    study_uid: str,
    attachments_path: str,
    threshold: float,
    *,
    tolerance: float = 0.001,
) -> Optional[Dict[str, Any]]:
    """
    Most recent run at (approximately) `threshold`, or None.

    Lets the two-stage workflow REUSE an existing lower-threshold run instead of
    burning a fresh backend call every time the 3D Cursor is opened on the same
    study. Re-running the same analysis repeatedly is slow, costs the AI server,
    and produces `_2`, `_3`, `_4`... clutter in the dropdown for no clinical gain.
    """
    try:
        doc = _load(manifest_path(study_uid, attachments_path))
        matches = [
            r for r in doc.get("available", [])
            if r.get("threshold") is not None
            and abs(float(r["threshold"]) - float(threshold)) <= tolerance
            and r.get("detection")
            and os.path.isfile(str(r["detection"]))
        ]
        if not matches:
            return None
        # Prefer the newest by created_at when present; fall back to list order.
        matches.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return matches[0]
    except Exception:
        return None
