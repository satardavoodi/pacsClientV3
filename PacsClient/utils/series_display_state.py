"""Pure, shared decision authority for FAST series-display actions.

This is the single source of truth for the question every series load / switch /
progressive-grow / completion / resume entry point keeps re-answering on its own:

    "given what the SERVER, DISK, CANONICAL METADATA and the VIEWER each currently
     know about a series, what should this entry point DO — nothing, grow it,
     refresh+rebuild it, or leave it alone because shrinking it would be wrong?"

Today that decision is re-derived in 13+ places from 4 disagreeing count sources
(see docs/reports/SERIES_DISPLAY_PIPELINE_UNIFIED_METHOD_EVALUATION_2026-06-24.md).
Routing them through ONE pure function is the §7 unification step: one authority,
one truth table, no forked variants.

Design rules (kept identical to patient_study_set.py / series_completeness.py):
- **Pure stdlib only** (+ series_completeness). No Qt / VTK / pydicom / numpy, no
  I/O, no widget access — so it stays unit-testable in isolation and cannot
  disturb the clinically-protected render path.
- It only DECIDES. The caller still performs the operation (grow / refresh /
  rebuild) and remains responsible for collecting the counts it feeds in.
- The expected/target count is taken as ``max(resolved_expected, server_count)``
  so a transient-low disk read can never make a partial series look complete, and
  the **never-downgrade** rule guarantees a viewer is never rebuilt below the slice
  count it already shows (the 47793/47842 "99 → 8" reset).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from PacsClient.utils.series_completeness import (
    SeriesCompletenessSnapshot,
    build_series_completeness_snapshot,
)


class DisplayAction(str, Enum):
    """The closed set of things an entry point may do to a series' viewport."""

    #: Viewer already shows the full known set — do nothing.
    NOOP = "noop"
    #: Disk grew beyond the viewer AND a lazy loader can extend it cheaply.
    GROW_IN_PLACE = "grow_in_place"
    #: Disk grew but there is no lazy loader (e.g. a preview / offline-cloud
    #: volume): the canonical metadata may be a stale stub, so refresh it to disk
    #: FIRST, then rebuild from the full instance list.
    REFRESH_AND_REBUILD = "refresh_and_rebuild"
    #: Backend mismatch or an explicit force-reload — rebuild from the full set.
    REBUILD = "rebuild"
    #: The viewer already shows MORE slices than the best on-disk/expected target
    #: would provide; a reload here would SHRINK it. Keep what is shown.
    SKIP_DOWNGRADE = "skip_downgrade"
    #: Viewer matches disk but the series is not fully downloaded yet — keep the
    #: current volume and let the download/grow path catch it up (never rebuild to
    #: a smaller on-disk count).
    AWAIT_DOWNLOAD = "await_download"


@dataclass(frozen=True)
class SeriesDisplayState:
    """Normalized, read-only display facts for one (viewer, series)."""

    series_identifier: str
    snapshot: SeriesCompletenessSnapshot
    has_lazy_loader: bool = False
    backend_mismatch: bool = False
    rebuild_needed: bool = False
    force_reload: bool = False

    # convenience accessors (read-through to the completeness snapshot)
    @property
    def viewer_visible(self) -> int:
        return self.snapshot.viewer_visible_count

    @property
    def disk(self) -> int:
        return self.snapshot.disk_count

    @property
    def canonical(self) -> int:
        return self.snapshot.metadata_count

    @property
    def expected(self) -> int:
        return self.snapshot.expected_count

    @property
    def target(self) -> int:
        """The best known *should-show* count (never trusts a single source)."""
        return max(self.snapshot.disk_count, self.snapshot.expected_count)


def build_series_display_state(
    series_identifier: Any,
    *,
    server_count: Any = 0,
    disk_count: Any = 0,
    canonical_metadata_count: Any = 0,
    viewer_visible_count: Any = 0,
    expected_count: Any = 0,
    has_lazy_loader: bool = False,
    backend_mismatch: bool = False,
    rebuild_needed: bool = False,
    force_reload: bool = False,
) -> SeriesDisplayState:
    """Assemble a :class:`SeriesDisplayState` from already-collected counts.

    ``expected`` is consolidated as ``max(resolved_expected, server_count)`` — the
    authoritative target that is immune to a transient-low disk read.
    """
    def _i(v: Any) -> int:
        try:
            return max(0, int(v or 0))
        except Exception:
            return 0

    expected = max(_i(expected_count), _i(server_count))
    snapshot = build_series_completeness_snapshot(
        series_identifier,
        expected_count=expected,
        metadata_count=canonical_metadata_count,
        disk_count=disk_count,
        viewer_visible_count=viewer_visible_count,
    )
    return SeriesDisplayState(
        series_identifier=str(series_identifier or "").strip(),
        snapshot=snapshot,
        has_lazy_loader=bool(has_lazy_loader),
        backend_mismatch=bool(backend_mismatch),
        rebuild_needed=bool(rebuild_needed),
        force_reload=bool(force_reload),
    )


def decide_display_action(state: SeriesDisplayState) -> DisplayAction:
    """The ONE decide-once function every entry point should consult.

    Precedence (most specific first):

    1. **REBUILD** — a backend mismatch / explicit rebuild must rebuild from the
       full set regardless of counts.
    2. **SKIP_DOWNGRADE** — never rebuild a viewer below the slice count it already
       shows (unless an explicit force-reload asked for it). This is the structural
       guard against the resume-watchdog "99 → 8" reset.
    3. **GROW_IN_PLACE / REFRESH_AND_REBUILD** — disk has grown beyond the viewer:
       extend in place if a lazy loader exists, else refresh the canonical metadata
       to disk and rebuild.
    4. **AWAIT_DOWNLOAD** — viewer matches disk but the series is still incomplete
       vs the expected count: keep the current volume.
    5. **NOOP** — the viewer shows the full known set.
    """
    snap = state.snapshot

    # 1. Explicit rebuild always wins.
    if state.backend_mismatch or state.rebuild_needed:
        return DisplayAction.REBUILD

    # 2. Never downgrade. A reload from a staler/smaller source must not shrink a
    #    viewer that already shows more than the best known target. An explicit
    #    force_reload (genuine user re-drop) is allowed to override.
    if (
        not state.force_reload
        and state.target > 0
        and state.viewer_visible > state.target
    ):
        return DisplayAction.SKIP_DOWNGRADE

    # 3. Disk grew beyond what the viewer shows — bring the viewer up.
    if snap.viewer_behind_disk:
        if state.has_lazy_loader:
            return DisplayAction.GROW_IN_PLACE
        return DisplayAction.REFRESH_AND_REBUILD

    # 4. Viewer == disk, but the series isn't fully downloaded yet. Rebuilding now
    #    would only re-show the same (or fewer) slices — keep the current volume.
    if snap.is_incomplete:
        return DisplayAction.AWAIT_DOWNLOAD

    # 5. Nothing to do.
    return DisplayAction.NOOP
