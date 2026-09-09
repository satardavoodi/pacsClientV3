"""Immutable local-source hints copied from the mammography viewer catalogue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_LOCAL_SOURCE_HINTS = 512


@dataclass(frozen=True)
class MammographySourceHint:
    """Private local identity used to rebind a stale result path on a worker."""

    path: str
    series_uid: str = ""
    sop_instance_uid: str = ""
    instance_number: int | None = None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def snapshot_mammography_source_hints(patient_widget: Any) -> tuple[MammographySourceHint, ...]:
    """Copy MG instance identity without filesystem work or live Qt/VTK objects."""

    hints = []
    seen = set()
    for entry in getattr(patient_widget, "lst_thumbnails_data", ()) or ():
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("metadata") or {}
        series = metadata.get("series") or {}
        modality = str(series.get("modality") or "").upper().strip()
        if modality and modality != "MG":
            continue
        series_uid = str(series.get("series_uid") or "").strip()
        for instance in metadata.get("instances") or ():
            if not isinstance(instance, dict):
                continue
            path = str(instance.get("instance_path") or "").strip()
            if not path:
                continue
            sop_uid = str(
                instance.get("sop_instance_uid")
                or instance.get("sop_uid")
                or instance.get("SOPInstanceUID")
                or ""
            ).strip()
            identity = (path, series_uid, sop_uid)
            if identity in seen:
                continue
            seen.add(identity)
            hints.append(
                MammographySourceHint(
                    path=path,
                    series_uid=series_uid,
                    sop_instance_uid=sop_uid,
                    instance_number=_optional_int(
                        instance.get("instance_number")
                        if instance.get("instance_number") is not None
                        else instance.get("InstanceNumber")
                    ),
                )
            )
            if len(hints) > MAX_LOCAL_SOURCE_HINTS:
                return tuple(hints)
    return tuple(hints)
