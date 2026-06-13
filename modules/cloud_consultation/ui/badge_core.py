"""Qt-free count logic for the account-pill notification badge (workflow v2).

The badge on the top-right user pill shows::

    pending received consultations (registry inbox, status requested/accepted)
    + unread HIGH/CRITICAL notifications

Pure Python so it is unit-testable headless; the Qt rendering/worker lives in
``account_hook.py``. Never raises — malformed rows are simply skipped.
"""

from __future__ import annotations

# Registry inbox statuses that count as "waiting for me" (the Laravel registry
# vocabulary is pending → accepted/declined → answered → closed; "requested"
# kept for tolerance with older backend builds).
PENDING_RECEIVED_STATUSES = {"pending", "requested", "accepted"}

# Notification priority tiers that surface on the pill (2026-06-11 tier table).
BADGE_PRIORITIES = {"high", "critical"}


def count_pending_received(rows, notifications=None) -> int:
    """The pill-badge count. ``rows`` = registry INBOX rows; ``notifications``
    = inbox notification rows (each may carry ``status`` and ``priority``).

    * a registry row counts when its ``status`` is in
      :data:`PENDING_RECEIVED_STATUSES`;
    * a notification counts when it is unread AND its ``priority`` is in
      :data:`BADGE_PRIORITIES`.
    """
    count = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue  # malformed row — skipped, never raises
        status = str(row.get("status") or "pending").strip().lower()
        if status in PENDING_RECEIVED_STATUSES:
            count += 1
    for n in notifications or []:
        if not isinstance(n, dict):
            continue  # malformed row — skipped, never raises
        unread = str(n.get("status") or "unread").strip().lower() == "unread"
        priority = str(n.get("priority") or "").strip().lower()
        if unread and priority in BADGE_PRIORITIES:
            count += 1
    return count


def badge_text(count: int, cap: int = 9) -> str:
    """Compact badge caption: ``""`` for zero, ``"9+"`` above the cap."""
    try:
        n = int(count)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return f"{cap}+" if n > cap else str(n)
