"""Shared pure series identifier helpers and multi-study UI projection.

These helpers intentionally stay small and conservative. They centralize the
common logic for resolving a caller-provided series identifier into the
canonical series-number string used by FAST viewer components, while allowing
callers to layer on their own local fallbacks. Multi-study key/path construction
lives here so controllers consume one projection instead of reimplementing it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, NamedTuple


@dataclass(frozen=True)
class SeriesActionIdentity:
    """Pre-viewport intent, not a SeriesRef or a transferable viewer handle.

    Home's display/storage hints are retained losslessly, but only the two UIDs
    may resolve an action in another owner. No patient pixels or Qt state travel.
    """

    study_uid: str
    series_uid: str
    series_number: str
    display_key: str
    folder_key: str
    series_path: str

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, Any]) -> SeriesActionIdentity | None:
        study_uid = str(metadata.get("study_uid") or "").strip()
        series_uid = get_series_uid(metadata)
        if not study_uid or not series_uid:
            return None
        original = metadata.get("_orig_series_number")
        if original is None or original == "":
            original = metadata.get("series_number", "")
        return cls(
            study_uid, series_uid, str(original),
            str(metadata.get("display_key") or ""),
            str(metadata.get("folder_key") or ""),
            str(metadata.get("series_path") or ""),
        )

    def resolve_display_key(
        self, entries: Mapping[str, Mapping[str, Any]], *, primary_study_uid: str = ""
    ) -> str | None:
        """Find exactly one destination-owned key; never fall back to Home's key.

        Missing entry study UID follows the existing primary-bucket rule. Foreign
        series must carry their own study UID. Ambiguous/missing identities fail closed.
        """
        if not self.study_uid or not self.series_uid:
            return None
        found = None
        for key, entry in entries.items():
            if not isinstance(entry, Mapping):
                continue
            study_uid = str(entry.get("study_uid") or primary_study_uid or "").strip()
            if study_uid != self.study_uid or get_series_uid(entry) != self.series_uid:
                continue
            key = str(key)
            if found is not None or not (key.isascii() and key.isdecimal()):
                return None
            found = key
        return found


class MultiStudySeriesProjection(NamedTuple):
    """Fresh owner-local UI maps; input metadata and prior slots stay untouched.

    These mutable projections belong to one patient tab. Cross-domain consumers
    continue to resolve immutable SeriesRef values from the resulting entries.
    """

    slot_order: list[str]
    series_info: dict[str, dict[str, Any]]
    uid_to_key: dict[str, str]
    viewer_groups: list[tuple[str, int, list[tuple[str, dict[str, Any]]]]]


def build_multistudy_series_projection(
    studies_index: Mapping[str, Iterable[Mapping[str, Any]]],
    primary_study_uid: str,
    previous_slot_order: list[str] | None = None,
    source_root: str | PurePath | None = None,
    *,
    series_sort_key: Callable[[Mapping[str, Any]], Any],
) -> MultiStudySeriesProjection:
    """Project already-normalized series into the existing multi-study keys.

    This is the shared implementation formerly embedded in the patient widget.
    Ingestion still owns missing-number normalization; the canonical display-key
    allocator still owns same-study collisions. This step only assigns stable
    study slots and stamps copied entries with their own identity/path. Labels
    never identify a series, and no network, disk, database or Qt work occurs.

    The caller retains the single-study gate and presentation ordering policy.
    A panel must not reuse these keys in a different tab without resolving its
    study/series UID there: slot order is owned by that tab's lifetime.
    """
    primary = str(primary_study_uid or "")
    slot_order = list(previous_slot_order) if isinstance(previous_slot_order, list) else []
    try:
        if primary and primary in studies_index:
            if primary in slot_order:
                slot_order.remove(primary)
            slot_order.insert(0, primary)
        for study_uid in sorted(uid for uid in studies_index if uid != primary):
            if study_uid not in slot_order:
                slot_order.append(study_uid)
        slot_order = [uid for uid in slot_order if uid in studies_index]
    except Exception:
        slot_order = ([primary] if primary in studies_index else []) + sorted(
            uid for uid in studies_index if uid != primary
        )

    root = PurePath(source_root) if source_root is not None else None
    series_info = {}
    uid_to_key = {}
    viewer_groups = []
    for slot, study_uid in enumerate(slot_order):
        offset = slot * 1_000_000
        group = []
        for series in sorted(studies_index.get(study_uid, []) or [], key=series_sort_key):
            original = series.get("_orig_series_number") or get_series_number(series)
            try:
                local_key = int(str(series.get("display_key") or original).strip())
            except (TypeError, ValueError):
                continue
            key = str(local_key + offset)
            entry = dict(series)
            entry["series_number"] = key
            entry["display_key"] = key
            entry["_orig_series_number"] = str(original)
            entry["_study_slot"] = slot
            entry["study_uid"] = study_uid
            if root is not None and not entry.get("series_path"):
                folder_key = str(entry.get("folder_key") or original)
                entry["series_path"] = str(root / study_uid / folder_key)
            series_info[key] = entry
            series_uid = get_series_uid(series)
            if series_uid:
                uid_to_key[series_uid] = key
            group.append((key, entry))
        if group:
            viewer_groups.append((study_uid, slot, group))
    return MultiStudySeriesProjection(slot_order, series_info, uid_to_key, viewer_groups)


def get_series_number(series_info: Mapping[str, Any] | None) -> str:
    """Return the normalized series-number string from a series-info mapping."""
    if not isinstance(series_info, Mapping):
        return ""
    value = series_info.get("series_number", "")
    return str(value or "").strip()


def get_series_uid(series_info: Mapping[str, Any] | None) -> str:
    """Return the best available series UID from a series-info mapping."""
    if not isinstance(series_info, Mapping):
        return ""
    value = series_info.get("series_uid") or series_info.get("series_instance_uid") or ""
    return str(value or "").strip()


def resolve_series_identifier(
    series_identifier: Any,
    *,
    known_series_numbers: Iterable[Any] | None = None,
    uid_to_number_map: Mapping[str, Any] | None = None,
    series_info_map: Mapping[Any, Mapping[str, Any]] | None = None,
) -> str:
    """Resolve a series identifier to the canonical series-number string.

    Resolution order is deliberately conservative and mirrors the existing FAST
    behavior used by thumbnails and DM progress wiring:

    1. Exact match against known series-number keys.
    2. Numeric identifier shortcut.
    3. Direct lookup in UID→series-number mapping.
    4. Scan of series-info mappings using series UID fields.
    5. Fallback to the original identifier string.
    """
    series_key = str(series_identifier or "").strip()
    if not series_key:
        return ""

    if known_series_numbers is not None:
        try:
            known_keys = {str(value) for value in known_series_numbers}
        except Exception:
            known_keys = set()
        if series_key in known_keys:
            return series_key

    if series_key.isdigit():
        return series_key

    if uid_to_number_map:
        try:
            mapped = uid_to_number_map.get(series_key)
        except Exception:
            mapped = None
        if mapped is not None and str(mapped).strip():
            return str(mapped).strip()

    if series_info_map:
        try:
            items = series_info_map.items()
        except Exception:
            items = ()
        for series_number, info in items:
            if get_series_uid(info) == series_key:
                return str(series_number).strip()

    return series_key
