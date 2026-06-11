"""Qt-free grouping/filter logic for the Education ▸ Consultation sections (ADR-0007).

* **My Consultations dashboard:** merge Drive engine rows + aipacs_web registry
  rows into the five clinical status buckets (Pending / Awaiting response /
  Awaiting review / Answered / Closed). Dedupe of external registry rows
  against their Drive twins is preserved via
  :func:`assign_core.registry_rows_to_display`. The frozen internal Drive
  statuses are READ here only — never written, never persisted as labels.
* **Consultant Directory:** pure substring / type / availability filtering.
* **Storage:** tolerant quota/usage summary helpers shared by the Storage
  section and the account-popup storage line.

All pure Python so it is unit-testable headless; the Qt widgets in
``consultation_page.py`` / ``sections_*.py`` only compose these pieces.
"""

from __future__ import annotations

from . import assign_core

# ── status buckets (dashboard) ─────────────────────────────────────────────────
BUCKET_PENDING = "pending"
BUCKET_AWAITING_RESPONSE = "awaiting_response"
BUCKET_AWAITING_REVIEW = "awaiting_review"
BUCKET_ANSWERED = "answered"
BUCKET_CLOSED = "closed"

BUCKET_ORDER = [
    BUCKET_PENDING,
    BUCKET_AWAITING_RESPONSE,
    BUCKET_AWAITING_REVIEW,
    BUCKET_ANSWERED,
    BUCKET_CLOSED,
]

BUCKET_LABELS = {
    BUCKET_PENDING: "Pending",
    BUCKET_AWAITING_RESPONSE: "Awaiting response",
    BUCKET_AWAITING_REVIEW: "Awaiting review",
    BUCKET_ANSWERED: "Answered",
    BUCKET_CLOSED: "Closed",
}

# Drive engine statuses (frozen vocabulary, state_machine.py) → bucket per
# direction. ``conflict`` surfaces in the direction's "awaiting" bucket so it
# stays visible instead of hiding among Pending.
_DRIVE_BUCKETS = {
    "outgoing": {
        "pending": BUCKET_PENDING,
        "uploaded": BUCKET_AWAITING_RESPONSE,
        "downloaded": BUCKET_AWAITING_RESPONSE,
        "reviewed": BUCKET_AWAITING_RESPONSE,
        "answered": BUCKET_ANSWERED,
        "closed": BUCKET_CLOSED,
        "conflict": BUCKET_AWAITING_RESPONSE,
    },
    "incoming": {
        "pending": BUCKET_PENDING,
        "uploaded": BUCKET_AWAITING_REVIEW,
        "downloaded": BUCKET_AWAITING_REVIEW,
        "reviewed": BUCKET_AWAITING_REVIEW,
        "answered": BUCKET_ANSWERED,
        "closed": BUCKET_CLOSED,
        "conflict": BUCKET_AWAITING_REVIEW,
    },
}

# Registry statuses (Laravel vocabulary, ADR-0006) → bucket per box.
# An inbox "pending" is a request not yet accepted → Pending; once accepted it
# is "received … accepted, not answered" → Awaiting review (the ADR-0007 text).
_REGISTRY_BUCKETS = {
    "sent": {
        "pending": BUCKET_AWAITING_RESPONSE,
        "accepted": BUCKET_AWAITING_RESPONSE,
        "answered": BUCKET_ANSWERED,
        "declined": BUCKET_CLOSED,
        "closed": BUCKET_CLOSED,
    },
    "inbox": {
        "pending": BUCKET_PENDING,
        "accepted": BUCKET_AWAITING_REVIEW,
        "answered": BUCKET_ANSWERED,
        "declined": BUCKET_CLOSED,
        "closed": BUCKET_CLOSED,
    },
}


def bucket_for_drive(status: str, direction: str) -> str:
    """Bucket id for a Drive engine row (direction = incoming|outgoing)."""
    table = _DRIVE_BUCKETS.get(direction) or _DRIVE_BUCKETS["outgoing"]
    return table.get(str(status or "pending").strip().lower(), BUCKET_PENDING)


def bucket_for_registry(status: str, box: str) -> str:
    """Bucket id for an aipacs_web registry row (box = inbox|sent)."""
    table = _REGISTRY_BUCKETS.get(box) or _REGISTRY_BUCKETS["sent"]
    return table.get(str(status or "pending").strip().lower(), BUCKET_PENDING)


def drive_row_actionable(row: dict, direction: str) -> bool:
    """True when the Requests view offers an action for this Drive row."""
    r = row or {}
    status = str(r.get("status") or "").strip().lower()
    if direction == "incoming":
        if status == "uploaded" and r.get("remote_folder_id"):
            return True  # Download & review
        return status in ("downloaded", "reviewed") and bool(r.get("local_path"))
    return status == "answered"  # Mark closed


def group_consultations(
    drive_incoming: list[dict],
    drive_outgoing: list[dict],
    registry_inbox: list[dict] | None = None,
    registry_sent: list[dict] | None = None,
) -> dict[str, list[dict]]:
    """The My Consultations dashboard model: bucket id → annotated rows.

    Rows are copies annotated with ``_source`` (drive|registry), ``_direction``
    (incoming|outgoing), ``_bucket`` and ``_actionable``. External registry
    rows that mirror an already-listed Drive row are dropped (same dedupe as
    the Requests merge); Drive rows are never modified.
    """
    buckets: dict[str, list[dict]] = {b: [] for b in BUCKET_ORDER}
    for direction, rows in (("incoming", drive_incoming), ("outgoing", drive_outgoing)):
        for raw in rows or []:
            row = dict(raw or {})
            row["_source"] = "drive"
            row["_direction"] = direction
            row["_bucket"] = bucket_for_drive(row.get("status"), direction)
            row["_actionable"] = drive_row_actionable(row, direction)
            buckets[row["_bucket"]].append(row)
    for box, drive_rows, rows in (
        ("inbox", drive_incoming, registry_inbox),
        ("sent", drive_outgoing, registry_sent),
    ):
        merged = assign_core.registry_rows_to_display(
            list(rows or []), list(drive_rows or [])
        )
        for row in merged:
            row = dict(row)
            row["_source"] = "registry"
            row["_direction"] = "incoming" if box == "inbox" else "outgoing"
            row["_bucket"] = bucket_for_registry(row.get("status"), box)
            row["_actionable"] = bool(assign_core.registry_actions(row, box))
            buckets[row["_bucket"]].append(row)
    return buckets


# ── consultant directory filtering ─────────────────────────────────────────────
AVAILABILITY_VALUES = ("available", "busy", "away")


def consultant_specialties(consultants: list[dict]) -> list[str]:
    """Distinct, sorted specialty values for the Directory's specialty combo."""
    seen: dict[str, str] = {}
    for c in consultants or []:
        value = str((c or {}).get("specialty")
                    or (c or {}).get("speciality") or "").strip()
        if value and value.lower() not in seen:
            seen[value.lower()] = value
    return sorted(seen.values(), key=str.lower)


def filter_consultants(
    consultants: list[dict],
    query: str = "",
    kind: str = "all",
    availability: str = "all",
    specialty: str = "all",
) -> list[dict]:
    """Client-side directory filter: substring + type + availability + specialty.

    * ``query`` matches case-insensitively against name / specialty /
      expertise (and the legacy spelling variants assign_core tolerates);
    * ``kind`` is ``all`` / ``internal`` / ``external``;
    * ``availability`` is ``all`` or an exact (case-insensitive) value;
    * ``specialty`` is ``all`` or an exact (case-insensitive) specialty.
    """
    q = str(query or "").strip().lower()
    want_kind = str(kind or "all").strip().lower()
    want_avail = str(availability or "all").strip().lower()
    want_spec = str(specialty or "all").strip().lower()
    out: list[dict] = []
    for c in consultants or []:
        c = c or {}
        if want_kind in (assign_core.INTERNAL, assign_core.EXTERNAL):
            if assign_core.consultant_kind(c) != want_kind:
                continue
        if want_avail and want_avail != "all":
            if str(c.get("availability") or "").strip().lower() != want_avail:
                continue
        if want_spec and want_spec != "all":
            spec = str(c.get("specialty") or c.get("speciality") or "")
            if spec.strip().lower() != want_spec:
                continue
        if q:
            hay = " ".join(
                str(c.get(k) or "")
                for k in ("name", "full_name", "specialty", "speciality",
                          "expertise", "consultation_interests")
            ).lower()
            if q not in hay:
                continue
        out.append(c)
    return out


# ── storage summary helpers (Storage section + account popup line) ─────────────
STORAGE_WARN_FRACTION = 0.8
STORAGE_ALERT_FRACTION = 0.95

# Client-side TTL: a section/popup reuses its last fetched storage payload on
# re-entry within this window (ADR-0007 D / popup throttle ≥60 s).
STORAGE_CACHE_TTL_SEC = 300.0


def storage_cache_fresh(loaded_at_monotonic, now_monotonic=None,
                        ttl: float = STORAGE_CACHE_TTL_SEC) -> bool:
    """True when a cached storage result fetched at ``loaded_at_monotonic``
    (a ``time.monotonic()`` stamp) is still fresh. ``None`` → never fresh."""
    if loaded_at_monotonic is None:
        return False
    if now_monotonic is None:
        import time

        now_monotonic = time.monotonic()
    try:
        return (float(now_monotonic) - float(loaded_at_monotonic)) < float(ttl)
    except (TypeError, ValueError):
        return False


def storage_summary(storage: dict | None) -> dict:
    """Tolerant quota/usage numbers from a ``/me/storage`` payload.

    Returns ``{"quota": int|None, "used": int|None, "fraction": float|None,
    "warn": bool, "alert": bool}``. ``warn`` trips at ≥80 % used, ``alert``
    at ≥95 % (ADR-0007 hub styling). Missing/zero quota yields
    ``fraction=None`` and never warns (the quota gate fails open — ADR-0005)."""
    d = storage or {}
    quota = _first_int(d, ("quota_bytes", "quota", "total_bytes", "limit_bytes"))
    used = _first_int(d, ("used_bytes", "usage_bytes", "used", "usage"))
    fraction = None
    if quota and quota > 0 and used is not None:
        fraction = used / float(quota)
    return {
        "quota": quota,
        "used": used,
        "fraction": fraction,
        "warn": bool(fraction is not None and fraction >= STORAGE_WARN_FRACTION),
        "alert": bool(fraction is not None and fraction >= STORAGE_ALERT_FRACTION),
    }


def _first_int(d: dict, keys) -> int | None:
    for key in keys:
        value = d.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
        try:
            if value is not None and str(value).strip():
                return int(float(str(value)))
        except (TypeError, ValueError):
            continue
    return None


def format_bytes(n) -> str:
    """Human-readable size; ``—`` for unknown."""
    try:
        size = float(n)
    except (TypeError, ValueError):
        return "—"
    if size < 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return "—"
