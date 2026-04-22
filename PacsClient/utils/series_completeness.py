"""Shared helpers for FAST series completeness decisions.

These helpers are intentionally read-only and low-level. They do not perform
any I/O or reach into widget state directly; callers remain responsible for
collecting counts from server metadata, disk, or viewers. The helper only
normalizes those counts into consistent completeness predicates so FAST paths
stop re-deriving slightly different truth tables in multiple places.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _normalize_count(value: Any) -> int:
    """Convert a count-like value to a non-negative integer."""
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


@dataclass(frozen=True)
class SeriesCompletenessSnapshot:
    """Normalized series completeness facts from already-known counts."""

    series_identifier: str
    expected_count: int = 0
    metadata_count: int = 0
    disk_count: int = 0
    viewer_visible_count: int = 0

    @property
    def has_expected_count(self) -> bool:
        return self.expected_count > 0

    @property
    def max_known_count(self) -> int:
        return max(self.metadata_count, self.disk_count, self.viewer_visible_count)

    @property
    def has_any_local_data(self) -> bool:
        return max(self.metadata_count, self.disk_count) > 0

    @property
    def metadata_behind_disk(self) -> bool:
        return self.disk_count > self.metadata_count

    @property
    def viewer_behind_disk(self) -> bool:
        return self.disk_count > self.viewer_visible_count

    @property
    def is_incomplete(self) -> bool:
        if not self.has_expected_count:
            return False
        return self.max_known_count < self.expected_count

    @property
    def is_disk_complete(self) -> bool:
        if self.has_expected_count:
            return self.disk_count >= self.expected_count
        return self.disk_count > 0

    @property
    def is_viewer_complete(self) -> bool:
        if self.has_expected_count:
            return self.viewer_visible_count >= self.expected_count
        return self.viewer_visible_count > 0


def build_series_completeness_snapshot(
    series_identifier: Any,
    *,
    expected_count: Any = 0,
    metadata_count: Any = 0,
    disk_count: Any = 0,
    viewer_visible_count: Any = 0,
) -> SeriesCompletenessSnapshot:
    """Create a normalized completeness snapshot from already-collected counts."""
    return SeriesCompletenessSnapshot(
        series_identifier=str(series_identifier or "").strip(),
        expected_count=_normalize_count(expected_count),
        metadata_count=_normalize_count(metadata_count),
        disk_count=_normalize_count(disk_count),
        viewer_visible_count=_normalize_count(viewer_visible_count),
    )