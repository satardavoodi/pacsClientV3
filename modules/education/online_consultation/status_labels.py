"""Clinical lifecycle labels for consultation statuses.

The engine keeps its fine-grained internal statuses (``pending → uploaded →
downloaded → reviewed → answered → closed`` + ``conflict``) — those drive the state
machine and MUST NOT change. The clinic-facing UI shows the simpler lifecycle the
workflow was specified with: **Pending / Sent / Received / Answered / Closed**.

Mapping is direction-aware: the same internal ``uploaded`` row is "Sent" for the
originator (outgoing) and "Received" (a new consultation request) for the assignee
(incoming).
"""

from __future__ import annotations

CONSULTATION_TAG = "Online Consultation"

# internal status -> (outgoing label, incoming label)
_DISPLAY: dict[str, tuple[str, str]] = {
    "pending":    ("Pending",  "Pending"),
    "uploaded":   ("Sent",     "Received"),
    "downloaded": ("Sent",     "Received"),
    "reviewed":   ("Sent",     "Received"),
    "answered":   ("Answered", "Answered"),
    "closed":     ("Closed",   "Closed"),
    "conflict":   ("Conflict", "Conflict"),
}

# display label -> chip colour (works on the dark V2 surfaces)
_COLOR: dict[str, str] = {
    "Pending":  "#94a3b8",
    "Sent":     "#fbbf24",
    "Received": "#60a5fa",
    "Answered": "#34d399",
    "Closed":   "#64748b",
    "Conflict": "#f87171",
}


def display_status(internal_status: str, direction: str = "outgoing") -> str:
    """Map an internal engine status to the clinical lifecycle label."""
    pair = _DISPLAY.get(str(internal_status or "pending").lower())
    if pair is None:
        return str(internal_status or "Pending").capitalize()
    return pair[1] if direction == "incoming" else pair[0]


def status_color(label_or_status: str, direction: str = "outgoing") -> str:
    """Colour for a chip; accepts either a display label or an internal status."""
    label = label_or_status if label_or_status in _COLOR else display_status(
        label_or_status, direction
    )
    return _COLOR.get(label, "#94a3b8")
