"""Stable viewer / series request identity — the keystone of the unified viewer pipeline.

S0 of ``docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md``. This module
is **pure stdlib** (no Qt / VTK / pydicom / numpy) and, in S0, is **introduced UNUSED** so the
contract can be locked and unit-tested before any production call site moves (zero runtime
risk). It works identically for the FAST (pydicom) and Advanced (VTK) backends because it
carries no backend state — only identity.

Why this exists
---------------
Today the viewer keys a series two fragile ways, and the seams between them are the root of a
whole family of recurring bugs:

* **viewer request token = grid index** (``viewer_id = viewer_index``). The grid index is
  reused across patient/layout switches, so a stale Patient-A worker can pass an
  ``_is_request_current`` check against a Patient-B viewer in the same cell (architecture
  review hazard **A1**). Isolation currently rests on 4 *content* guards, not the keys.
* **series key = bare ``series_number``**. For a multi-study patient the same number exists in
  several studies, so the download manager (bare number) and the multi-study UI (offset/
  display key) disagree — the seam behind 47084 / 46970 / 46713.

A :class:`ViewerHandle` is a **per-viewport stable UUID** (one per viewer cell, stable across
the series switches that happen *in that cell*, regenerated when the cell is rebound to a new
patient/layout). A :class:`SeriesRequest` binds the globally-unique series identity
``(patient_id, study_uid, series_uid)`` plus its UI ``display_key`` to a ``ViewerHandle``, so a
download / decode / display request is unambiguous across patients, studies, and layout
changes. Isolation becomes **structural** (compare identities, not grid indices), which is what
lets later stages retire the content guards.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Optional


def _norm(value) -> str:
    """Normalize an identifier to a stripped string ("" for None)."""
    if value is None:
        return ""
    return str(value).strip()


@dataclass(frozen=True)
class ViewerHandle:
    """A stable identity for one viewer cell (viewport).

    Identity is the ``uuid`` alone. ``slot_hint`` records the grid index the handle currently
    occupies for **diagnostics only** — it never participates in equality/hash, so moving a
    viewport between grid slots does not change its identity (the A1 fix).
    """

    uuid: str = field(default_factory=lambda: uuid.uuid4().hex)
    slot_hint: Optional[int] = field(default=None, compare=False)

    @classmethod
    def new(cls, slot_hint: Optional[int] = None) -> "ViewerHandle":
        return cls(uuid=uuid.uuid4().hex, slot_hint=slot_hint)

    def with_slot(self, slot_hint: Optional[int]) -> "ViewerHandle":
        """Return the SAME identity with an updated diagnostic slot hint."""
        return replace(self, slot_hint=slot_hint)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"VH:{self.uuid[:8]}" + (f"@{self.slot_hint}" if self.slot_hint is not None else "")


@dataclass(frozen=True)
class SeriesRequest:
    """An unambiguous request to download / decode / display one series in one viewport.

    ``(patient_id, study_uid, series_uid)`` is the globally-unique, patient-scoped series
    identity used for state keying and isolation. ``display_key`` is the multi-study UI
    offset/display key (equals the bare number for single-study) used only for UI projection.
    ``viewer_handle`` ties the request to a specific viewport.
    """

    patient_id: str
    study_uid: str
    series_uid: str
    display_key: str
    viewer_handle: ViewerHandle
    intent: str = "display"  # display | preview | prefetch

    # -- construction ------------------------------------------------------ #
    @classmethod
    def create(
        cls,
        *,
        patient_id,
        study_uid,
        series_uid,
        display_key=None,
        viewer_handle: Optional[ViewerHandle] = None,
        intent: str = "display",
    ) -> "SeriesRequest":
        """Build a normalized request. ``display_key`` defaults to ``series_uid`` when not
        supplied (callers should pass the offset/display key for multi-study)."""
        dk = _norm(display_key) or _norm(series_uid)
        return cls(
            patient_id=_norm(patient_id),
            study_uid=_norm(study_uid),
            series_uid=_norm(series_uid),
            display_key=dk,
            viewer_handle=viewer_handle or ViewerHandle.new(),
            intent=(intent or "display").strip() or "display",
        )

    # -- keys -------------------------------------------------------------- #
    @property
    def identity_key(self) -> tuple:
        """Patient-scoped series identity — the cross-patient-safe key. Includes
        ``patient_id`` so a foreign study can never masquerade as this patient's series."""
        return (self.patient_id, self.study_uid, self.series_uid)

    @property
    def series_scope_key(self) -> tuple:
        """``(study_uid, series_uid)`` — globally-unique series key for disk/state/cache
        (patient-blind, because disk folders are keyed by ``study_uid``)."""
        return (self.study_uid, self.series_uid)

    # -- predicates -------------------------------------------------------- #
    def is_valid(self) -> bool:
        """A request is usable only when fully identified."""
        return bool(self.patient_id and self.study_uid and self.series_uid and self.display_key
                    and self.viewer_handle and self.viewer_handle.uuid)

    def is_same_series(self, other: "SeriesRequest") -> bool:
        return isinstance(other, SeriesRequest) and self.series_scope_key == other.series_scope_key

    def is_same_target(self, other: "SeriesRequest") -> bool:
        """Same series AND same viewport — the precise 'this exact request' test that replaces
        the grid-index ``_is_request_current`` comparison."""
        return (self.is_same_series(other)
                and isinstance(other, SeriesRequest)
                and self.viewer_handle == other.viewer_handle)

    def belongs_to_patient(self, patient_id) -> bool:
        """Structural isolation check — never admit a series for the wrong patient."""
        return self.patient_id == _norm(patient_id) and bool(self.patient_id)

    def for_handle(self, viewer_handle: ViewerHandle) -> "SeriesRequest":
        return replace(self, viewer_handle=viewer_handle)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (f"SeriesRequest(pid={self.patient_id} study=…{self.study_uid[-8:]} "
                f"series_uid=…{self.series_uid[-8:]} key={self.display_key} "
                f"{self.viewer_handle} intent={self.intent})")
