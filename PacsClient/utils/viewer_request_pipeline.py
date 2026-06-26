"""``ensure_series_displayed`` chokepoint — the unified entry point for showing a series.

S3 of ``docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md``. **Pure stdlib**
(composes the S0 spine: ``SeriesRequest`` identity + the ``decide_display_action`` authority).
Introduced **UNUSED** in S3a so the contract is locked + unit-tested before any production entry
point is routed through it (S3b → zero runtime risk now).

Why this exists
---------------
Today four entry points each re-answer "what should this viewport do with this series?" on their
own — the drop (``change_series_on_viewer``), the live grow (``on_series_images_progress``), the
download completion, and the disk-ready resume — keyed by bare ``series_number`` + a grid-index
token, patched by ``_PROGRESSIVE_UID_BIND`` and a scatter of count-truth gates. The result is the
fragmentation the architecture review flagged (multi-study key collisions, the livelock, the
"groups late / must re-drag" bug).

The chokepoint funnels all four through ONE function that owns: the display **decision** (reusing
``decide_display_action`` — never a second copy), the canonical-metadata sync, the settled state,
and **request-scoped** cancellation (by the stable ``SeriesRequest`` identity, so a concurrent drop
on another patient/viewport can't be confused for this one). This module is the **decision core**;
S3b wires the side-effecting execution + cancellation around it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from PacsClient.utils.viewer_identity import SeriesRequest
from PacsClient.utils.series_display_state import (
    DisplayAction,
    build_series_display_state,
    decide_display_action,
)


class LoadIntent(str, Enum):
    DISPLAY = "display"    # user dropped/selected — show it now
    PREVIEW = "preview"    # quick preview only (first image)
    PREFETCH = "prefetch"  # warm the cache; no viewport change


# Actions that require the caller to actually load/grow/rebuild (vs. leave the viewport as-is).
_WORK_ACTIONS = frozenset({
    DisplayAction.GROW_IN_PLACE,
    DisplayAction.REFRESH_AND_REBUILD,
    DisplayAction.REBUILD,
    DisplayAction.AWAIT_DOWNLOAD,
})


@dataclass(frozen=True)
class DisplayPlan:
    """The decision the chokepoint reaches for one ``SeriesRequest`` — carries the stable identity
    so the executor (S3b) applies it to the RIGHT viewport/series and can cancel it if a newer
    request for the same viewport supersedes it."""

    request: SeriesRequest
    action: DisplayAction
    target_count: int
    intent: LoadIntent
    reason: str

    @property
    def needs_work(self) -> bool:
        """True when the viewport must load/grow/rebuild/await (vs. leave it alone)."""
        return self.action in _WORK_ACTIONS

    @property
    def is_noop(self) -> bool:
        """NOOP or SKIP_DOWNGRADE — the viewport already shows at least the target; never shrink."""
        return self.action in (DisplayAction.NOOP, DisplayAction.SKIP_DOWNGRADE)

    def supersedes(self, other: "DisplayPlan") -> bool:
        """A plan supersedes a prior one when it targets the SAME viewport (same ViewerHandle) but a
        DIFFERENT series — the request-scoped cancellation signal that replaces the grid-index
        token race."""
        if not isinstance(other, DisplayPlan):
            return False
        return (self.request.viewer_handle == other.request.viewer_handle
                and not self.request.is_same_series(other.request))


def plan_series_display(
    request: SeriesRequest,
    *,
    viewer_visible_count: Any = 0,
    disk_count: Any = 0,
    server_count: Any = 0,
    expected_count: Any = 0,
    canonical_metadata_count: Any = 0,
    has_lazy_loader: bool = False,
    backend_mismatch: bool = False,
    rebuild_needed: bool = False,
    force_reload: bool = False,
    intent: LoadIntent = LoadIntent.DISPLAY,
) -> DisplayPlan:
    """Pure: decide what a viewport must DO to display ``request``'s series, given the current
    counts + backend. Composes the stable identity (``SeriesRequest``) with the single
    ``SeriesDisplayState`` decision authority (no second copy of the rules). **No side effects** —
    the caller (S3b) executes the returned :class:`DisplayPlan`. Works for FAST and Advanced (the
    backend only affects ``has_lazy_loader`` / ``backend_mismatch``)."""
    state = build_series_display_state(
        request.display_key or request.series_uid,
        server_count=server_count,
        disk_count=disk_count,
        canonical_metadata_count=canonical_metadata_count,
        viewer_visible_count=viewer_visible_count,
        expected_count=expected_count,
        has_lazy_loader=has_lazy_loader,
        backend_mismatch=backend_mismatch,
        rebuild_needed=rebuild_needed,
        force_reload=force_reload,
    )
    action = decide_display_action(state)
    try:
        intent = intent if isinstance(intent, LoadIntent) else LoadIntent(str(intent))
    except Exception:
        intent = LoadIntent.DISPLAY
    return DisplayPlan(
        request=request,
        action=action,
        target_count=int(state.target),
        intent=intent,
        reason="%s target=%d visible=%d disk=%d expected=%d" % (
            action.name, int(state.target), int(viewer_visible_count or 0),
            int(disk_count or 0), int(expected_count or 0),
        ),
    )
