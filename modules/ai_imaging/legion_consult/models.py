"""Immutable Legion Consult request models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence
from uuid import uuid4


Point2D = tuple[float, float]
Point3D = tuple[float, float, float]


@dataclass(frozen=True)
class SeriesSelectionPlan:
    """Validated series assignments for one configured consultation."""

    study_uid: str
    source_series_key: str
    t1_series_key: str
    t2_series_key: str
    selected_series_keys: tuple[str, ...]
    select_all: bool
    estimated_image_count: int
    series_manifest: tuple[dict, ...]

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AttentionAnchor:
    """A rectangular attention hint in source-image and patient LPS space."""

    source_series_key: str
    source_slice_index: int
    image_corners: tuple[Point2D, Point2D, Point2D, Point2D]
    patient_lps_corners: tuple[Point3D, Point3D, Point3D, Point3D]

    @classmethod
    def from_rectangle(
        cls,
        *,
        source_series_key: str,
        source_slice_index: int,
        diagonal_points: Sequence[Point2D],
        image_to_patient: Callable[[float, float, int], Sequence[float]],
    ) -> "AttentionAnchor":
        if len(diagonal_points) != 2:
            raise ValueError("A rectangle requires exactly two diagonal points.")
        first, second = diagonal_points
        min_x, max_x = sorted((float(first[0]), float(second[0])))
        min_y, max_y = sorted((float(first[1]), float(second[1])))
        if min_x == max_x or min_y == max_y:
            raise ValueError("The attention rectangle must have a non-zero area.")

        image_corners = (
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
        )
        patient_corners = []
        for x, y in image_corners:
            mapped = image_to_patient(x, y, int(source_slice_index))
            if mapped is None or len(mapped) < 3:
                raise ValueError("The ROI could not be mapped to patient coordinates.")
            patient_corners.append((float(mapped[0]), float(mapped[1]), float(mapped[2])))

        return cls(
            source_series_key=str(source_series_key),
            source_slice_index=int(source_slice_index),
            image_corners=image_corners,
            patient_lps_corners=tuple(patient_corners),
        )

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LegionConsultRequest:
    """A local, configured request that has not been sent to an AI provider."""

    schema_version: int
    session_id: str
    created_at_utc: str
    status: str
    remote_send_status: str
    slice_padding: int
    selection: SeriesSelectionPlan
    attention_anchor: AttentionAnchor

    @classmethod
    def create(
        cls,
        *,
        plan: SeriesSelectionPlan,
        anchor: AttentionAnchor,
    ) -> "LegionConsultRequest":
        if anchor.source_series_key != plan.source_series_key:
            raise ValueError("The ROI source does not match the selected source series.")
        now = datetime.now(timezone.utc)
        session_id = f"{now:%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:8]}"
        return cls(
            schema_version=1,
            session_id=session_id,
            created_at_utc=now.isoformat(),
            status="configured",
            remote_send_status="not_sent",
            slice_padding=5,
            selection=plan,
            attention_anchor=anchor,
        )

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "created_at_utc": self.created_at_utc,
            "status": self.status,
            "remote_send_status": self.remote_send_status,
            "slice_padding": self.slice_padding,
            "selection": self.selection.as_dict(),
            "attention_anchor": self.attention_anchor.as_dict(),
        }
