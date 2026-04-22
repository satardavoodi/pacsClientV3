"""Shared helpers for FAST series fact resolution.

These helpers centralize how FAST paths answer questions like:

- what is the canonical series identifier?
- what is the best expected image count currently known?

The goal is not to perform heavy I/O or own widget state. Instead, callers pass
already-available maps/lists (server series info, thumbnail metadata, metadata
flat cache) and optionally a lightweight disk-count callback when they want a
bounded on-disk fallback.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from PacsClient.utils.series_completeness import build_series_completeness_snapshot
from PacsClient.utils.series_identity import resolve_series_identifier


_EXPLICIT_COUNT_KEYS = (
    "image_count",
    "number_of_instances",
    "instances_count",
    "expected_instances",
    "total_instances",
)


def _normalize_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _extract_explicit_count(mapping: Mapping[str, Any] | None) -> int:
    if not isinstance(mapping, Mapping):
        return 0
    for key in _EXPLICIT_COUNT_KEYS:
        value = mapping.get(key)
        count = _normalize_count(value)
        if count > 0:
            return count
    return 0


def _extract_preview_total(metadata: Mapping[str, Any] | None) -> int:
    if not isinstance(metadata, Mapping):
        return 0
    if not bool(metadata.get("preview_only", False)):
        return 0
    return _normalize_count(metadata.get("preview_total_instances", 0))


def _extract_metadata_instance_count(metadata: Mapping[str, Any] | None) -> int:
    if not isinstance(metadata, Mapping):
        return 0
    instances = metadata.get("instances") or []
    if isinstance(instances, Sequence) and not isinstance(instances, (str, bytes)):
        return _normalize_count(len(instances))
    return 0


def _find_thumbnail_metadata(
    series_key: str,
    *,
    thumbnail_items: Sequence[Any] | None,
    series_number_to_index: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    items = thumbnail_items or []
    if series_number_to_index:
        try:
            idx = series_number_to_index.get(series_key)
        except Exception:
            idx = None
        try:
            if idx is not None and 0 <= int(idx) < len(items):
                item = items[int(idx)]
                metadata = item.get("metadata") if isinstance(item, Mapping) else None
                if isinstance(metadata, Mapping):
                    return metadata
        except Exception:
            pass

    for item in items:
        if not isinstance(item, Mapping):
            continue
        metadata = item.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            continue
        series_info = metadata.get("series") or {}
        if str(series_info.get("series_number", "") or "").strip() == series_key:
            return metadata
    return None


@dataclass(frozen=True)
class SeriesExpectedCountResolution:
    requested_identifier: str
    series_identifier: str
    expected_count: int = 0
    source: str = ""

    def to_completeness_snapshot(
        self,
        *,
        metadata_count: Any = 0,
        disk_count: Any = 0,
        viewer_visible_count: Any = 0,
    ):
        """Build a completeness snapshot using the resolved expected count."""
        return build_series_completeness_snapshot(
            self.series_identifier,
            expected_count=self.expected_count,
            metadata_count=metadata_count,
            disk_count=disk_count,
            viewer_visible_count=viewer_visible_count,
        )


def resolve_series_expected_count(
    series_identifier: Any,
    *,
    uid_to_number_map: Mapping[str, Any] | None = None,
    series_info_map: Mapping[Any, Mapping[str, Any]] | None = None,
    metadata_flat_map: Mapping[str, Mapping[str, Any]] | None = None,
    thumbnail_items: Sequence[Any] | None = None,
    series_number_to_index: Mapping[str, Any] | None = None,
    disk_count_getter: Callable[[str], Any] | None = None,
) -> SeriesExpectedCountResolution:
    """Resolve the best currently-known expected count for a series.

    Resolution order is conservative and optimized for active FAST runtime use:

    1. Canonicalize identifier to series-number form.
    2. Preview-total from metadata-flat cache.
    3. Explicit server/series-info count.
    4. Preview-total from thumbnail metadata.
    5. Explicit thumbnail/metadata series count.
    6. Metadata-flat instance count.
    7. Thumbnail metadata instance count.
    8. Optional lightweight disk-count fallback.
    """
    requested_key = str(series_identifier or "").strip()
    series_key = resolve_series_identifier(
        requested_key,
        uid_to_number_map=uid_to_number_map,
        series_info_map=series_info_map,
    )

    flat_meta = None
    if metadata_flat_map:
        try:
            flat_meta = metadata_flat_map.get(series_key)
        except Exception:
            flat_meta = None

    thumb_meta = _find_thumbnail_metadata(
        series_key,
        thumbnail_items=thumbnail_items,
        series_number_to_index=series_number_to_index,
    )

    preview_total = _extract_preview_total(flat_meta)
    if preview_total > 0:
        return SeriesExpectedCountResolution(
            requested_identifier=requested_key,
            series_identifier=series_key,
            expected_count=preview_total,
            source="metadata_flat.preview_total_instances",
        )

    explicit_server_count = 0
    if series_info_map:
        try:
            explicit_server_count = _extract_explicit_count(series_info_map.get(series_key))
        except Exception:
            explicit_server_count = 0
    if explicit_server_count > 0:
        return SeriesExpectedCountResolution(
            requested_identifier=requested_key,
            series_identifier=series_key,
            expected_count=explicit_server_count,
            source="series_info.image_count",
        )

    preview_total = _extract_preview_total(thumb_meta)
    if preview_total > 0:
        return SeriesExpectedCountResolution(
            requested_identifier=requested_key,
            series_identifier=series_key,
            expected_count=preview_total,
            source="thumbnail.preview_total_instances",
        )

    explicit_thumb_count = _extract_explicit_count(
        (thumb_meta or {}).get("series") if isinstance(thumb_meta, Mapping) else None
    )
    if explicit_thumb_count > 0:
        return SeriesExpectedCountResolution(
            requested_identifier=requested_key,
            series_identifier=series_key,
            expected_count=explicit_thumb_count,
            source="thumbnail.series.image_count",
        )

    metadata_count = _extract_metadata_instance_count(flat_meta)
    if metadata_count > 0:
        return SeriesExpectedCountResolution(
            requested_identifier=requested_key,
            series_identifier=series_key,
            expected_count=metadata_count,
            source="metadata_flat.instances",
        )

    metadata_count = _extract_metadata_instance_count(thumb_meta)
    if metadata_count > 0:
        return SeriesExpectedCountResolution(
            requested_identifier=requested_key,
            series_identifier=series_key,
            expected_count=metadata_count,
            source="thumbnail.instances",
        )

    if disk_count_getter is not None:
        disk_count = _normalize_count(disk_count_getter(series_key))
        if disk_count > 0:
            return SeriesExpectedCountResolution(
                requested_identifier=requested_key,
                series_identifier=series_key,
                expected_count=disk_count,
                source="disk_count_fallback",
            )

    return SeriesExpectedCountResolution(
        requested_identifier=requested_key,
        series_identifier=series_key,
        expected_count=0,
        source="unknown",
    )