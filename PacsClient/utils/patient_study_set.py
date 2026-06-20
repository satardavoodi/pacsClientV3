"""Canonical patient -> study -> series data contract for AI-PACS workflows.

Foundation (Phase 1) of the "one unified pipeline" effort:
  - docs/reports/UNIFIED_PATIENT_STUDY_PIPELINE_REVIEW_2026-06-17.md
  - docs/reports/UNIFIED_PIPELINE_EVALUATION_2026-06-17.md

This module provides:
  1. The immutable data contract every workflow will eventually consume
     (PatientStudySetRequest / SeriesDescriptor / StudyDescriptor / PatientStudySet).
  2. `merge_study_uids(...)` — the SINGLE pure authority for "which studies belong
     to this patient?", consolidating the union + dedup + selected-first ordering
     + cross-patient owner filtering that is currently duplicated across
     `_resolve_patient_study_uids`, `_reconcile_patient_studies_on_click`,
     `_resync_patient_studies_from_server`, `on_plus_button_clicked`, etc.

CLINICAL SAFETY — read before extending:
  This layer resolves *which* studies/series exist and their METADATA only. It must
  NEVER touch pixel data, geometry (IPP/IOP-derived spacing), slice ordering,
  orientation, VTK render windows, or MPR reslice. All of that lives DOWNSTREAM of
  the viewer metadata sink ``set_server_series_info`` and is out of scope for the
  study-set pipeline. Do NOT import Qt / VTK / numpy / pydicom here — keep this
  module pure (stdlib only) so it stays unit-testable in isolation and reusable
  across Home UI, Download Manager, and the viewer bridge.

This module is now LIVE: it is imported by the home-panel resolver
(`_resolve_patient_study_uids` owner-filter via merge_study_uids), the open-viewer
back-fill, and the resync / reconcile download-enqueue sites (all flag-gated).
Remaining callers not yet migrated to the service: the resolver's study-source
gather, the single-click / async per-modality enumeration, the plus-button path,
and manual download. Keep this module pure (stdlib only) so it stays the shared
authority and is unit-testable in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional


class Intent:
    """Action intents (string-typed for cheap logging/serialization). The unified
    path is one resolution contract; side effects depend on the intent."""

    PREVIEW_ONLY = "preview_only"
    OPEN_VIEWER = "open_viewer"
    REFRESH_OPEN_VIEWER = "refresh_open_viewer"
    MANUAL_REFRESH = "manual_refresh"
    MANUAL_DOWNLOAD = "manual_download"
    LOCAL_RESTORE = "local_restore"
    OFFLINE_CLOUD_PREVIEW = "offline_cloud_preview"
    IMPORT_CD = "import_cd"


class Freshness:
    """How fresh the resolved set is — drives the fast-first-paint optimization."""

    LOCAL_FAST = "local_fast"
    CACHED_SERVER = "cached_server"
    FRESH_PATIENT_ROW = "fresh_patient_row"
    FRESH_STUDY_SERIES = "fresh_study_series"
    FORCED_FRESH = "forced_fresh"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PatientStudySetRequest:
    """Input to PatientStudySetService.resolve()."""

    patient_id: str
    patient_name: str = ""
    selected_study_uid: str = ""
    source_mode: str = ""
    intent: str = Intent.PREVIEW_ONLY
    force_refresh: bool = False
    allow_remote: bool = True


@dataclass(frozen=True)
class SeriesDescriptor:
    """One series, identified by its OWN study_uid + series_uid. ``series_number``
    is study-local only and must never be treated as globally unique.

    ``folder_key`` is the canonical on-disk folder name for this series within its
    study — normally ``series_number``, but when two distinct ``series_uid`` share a
    ``series_number`` in one study the non-largest get a stable disambiguated key
    (``"<num>__<uid8>"``) so neither is overwritten. It is the single identity the
    downloader (disk write) and the viewer sink (load) must agree on; compute it via
    ``resolve_series_folder_key`` so there is exactly one rule. Empty = bare number."""

    study_uid: str
    series_uid: str = ""
    series_number: str = ""
    modality: str = ""
    description: str = ""
    image_count: int = 0
    thumbnail_path: str = ""
    is_document: bool = False
    folder_key: str = ""


@dataclass(frozen=True)
class StudyDescriptor:
    """One study under a patient, keyed by StudyInstanceUID (the disk/DB identity)."""

    study_uid: str
    patient_id: str = ""
    patient_name: str = ""
    modality: str = ""
    study_date: str = ""
    description: str = ""
    series: tuple[SeriesDescriptor, ...] = ()
    owner_verified: bool = False
    local_status: str = "unknown"
    server_status: str = "unknown"
    missing_series_numbers: tuple[str, ...] = ()
    partial_series_numbers: tuple[str, ...] = ()
    content_version: Optional[int] = None


@dataclass(frozen=True)
class PatientStudySet:
    """The canonical, immutable result every workflow consumes."""

    patient_id: str
    patient_name: str
    selected_study_uid: str
    studies: tuple[StudyDescriptor, ...] = ()
    source_mode: str = ""
    freshness: str = Freshness.UNKNOWN
    warnings: tuple[str, ...] = ()

    @property
    def study_uids(self) -> tuple[str, ...]:
        return tuple(s.study_uid for s in self.studies)

    @property
    def is_multistudy(self) -> bool:
        return len(self.studies) > 1

    def study(self, study_uid: str) -> Optional[StudyDescriptor]:
        target = _clean(study_uid)
        for s in self.studies:
            if s.study_uid == target:
                return s
        return None


def _clean(value) -> str:
    return str(value or "").strip()


def merge_study_uids(
    sources: Iterable[Iterable[str]],
    selected_study_uid: str = "",
    *,
    owner_of: Optional[Callable[[str], Optional[str]]] = None,
    patient_id: str = "",
    sanctioned_uids: Optional[Iterable[str]] = None,
) -> tuple[list[str], list[str]]:
    """Canonical union of a patient's study UIDs from all discovery sources.

    This is the single authority that today is duplicated across
    ``_resolve_patient_study_uids`` (union + selected-first + fallbacks) and the
    cross-patient guards in the open / reconcile / grouped-thumbnail paths.

    Args:
        sources: iterable of iterables of study_uid strings, in priority order
            (e.g. table-row primary, row['study_uids'], row['studies'],
            latest_study_uid, DB studies, cached map, per-modality enumeration).
            First-seen order is preserved across sources; duplicates and empty/
            whitespace values are dropped.
        selected_study_uid: the clicked/selected study. Always kept and placed
            FIRST, regardless of owner (the user explicitly chose it).
        owner_of: optional callable ``study_uid -> owner patient_id`` (or None when
            the owner is unknown, e.g. a fresh server study not yet in the local DB).
            A study whose owner is POSITIVELY a DIFFERENT patient_id is dropped
            (cross-patient clinical isolation). Unknown owner (None/"") is KEPT so
            normal fresh-server opens never break. Exceptions from the callable are
            treated as "unknown owner" (kept) and never propagate.
        patient_id: the target patient. Owner filtering is applied only when BOTH
            ``owner_of`` and ``patient_id`` are provided.
        sanctioned_uids: optional allow-list of study_uids that must be KEPT even
            when their owner is positively a different patient_id. This is the
            cross-identity escape hatch for the "Previous Exams" feature: studies
            the server linked to the SAME real person (by National ID / reception
            history) and that the user EXPLICITLY selected. Default empty => the
            owner filter behaves byte-identically (nothing is sanctioned, so no
            foreign study is ever silently admitted). Never auto-populate this
            from caller/current context — only from server-verified previous-exam
            identity (see ``previous_exams.sanctioned_study_uids``).

    Returns:
        ``(ordered_uids, dropped_foreign)``:
            ordered_uids: list[str], unique, selected-first, then first-seen order,
                with positively-foreign studies removed.
            dropped_foreign: list[str], studies dropped because their owner is a
                different patient_id (for logging/telemetry).
    """
    pid = _clean(patient_id)
    selected = _clean(selected_study_uid)

    ordered: list[str] = []
    seen: set[str] = set()

    def _add(uid) -> None:
        u = _clean(uid)
        if u and u not in seen:
            seen.add(u)
            ordered.append(u)

    if selected:
        _add(selected)
    for source in (sources or []):
        for uid in (source or []):
            _add(uid)

    # Owner filtering is optional; without a resolver or a target pid we cannot
    # prove any study foreign, so return the unfiltered union.
    if not (owner_of and pid):
        return ordered, []

    sanctioned = {_clean(u) for u in (sanctioned_uids or []) if _clean(u)}

    kept: list[str] = []
    dropped: list[str] = []
    for uid in ordered:
        if uid == selected:
            # The explicitly-selected study is always kept (the user chose it).
            kept.append(uid)
            continue
        if uid in sanctioned:
            # Server-verified previous exam of the SAME real person, explicitly
            # selected by the user — admitted despite a different owner. Each such
            # study still preserves its own study_uid / patient_id downstream.
            kept.append(uid)
            continue
        try:
            owner = _clean(owner_of(uid))
        except Exception:
            owner = ""  # unknown -> keep (never block on a flaky lookup)
        if owner and owner != pid:
            dropped.append(uid)  # positively foreign -> drop (clinical isolation)
        else:
            kept.append(uid)     # owner matches OR unknown -> keep
    return kept, dropped


def diff_study_uids(previous, current) -> list[str]:
    """Study UIDs present in ``current`` but not ``previous`` (order-preserved,
    cleaned, deduped).

    Used by the Phase-2 shadow study-set-growth detector to quantify the
    open-vs-late divergence (the 46630 class: the double-click OPEN path resolves
    a smaller set than a later reconcile discovers) without changing behavior.
    """
    prev = {_clean(u) for u in (previous or []) if _clean(u)}
    out: list[str] = []
    seen: set[str] = set()
    for u in (current or []):
        c = _clean(u)
        if c and c not in prev and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def resolve_study_uids(
    *,
    table_uids=None,
    rightpanel_uids=None,
    cache_uids=None,
    selected_study_uid="",
    owner_of: Optional[Callable[[str], Optional[str]]] = None,
    patient_id: str = "",
    sanctioned_uids: Optional[Iterable[str]] = None,
) -> tuple[list[str], list[str]]:
    """Conditional-fallback gather + canonical owner-filter — the resolution logic
    of the home-panel ``_resolve_patient_study_uids``, extracted as a pure function
    so every workflow shares ONE authority.

    The right-panel and cache fallbacks are consulted ONLY when the table source
    yields <= 1 study (this preserves the legacy behavior exactly: stale fallbacks
    must not widen a row that already resolved multiple studies). The selected
    study is placed first and always kept; positively-foreign studies are dropped.

    Returns ``(ordered_uids, dropped_foreign)``.
    """
    raw: list[str] = []
    seen: set[str] = set()

    def _add(lst) -> None:
        for u in (lst or []):
            c = _clean(u)
            if c and c not in seen:
                seen.add(c)
                raw.append(c)

    _add(table_uids)
    if len(raw) <= 1:
        _add(rightpanel_uids)
    if len(raw) <= 1:
        _add(cache_uids)
    return merge_study_uids(
        [raw], selected_study_uid, owner_of=owner_of, patient_id=patient_id,
        sanctioned_uids=sanctioned_uids)


def build_download_payload(study_uid, patient_id, patient_name, study_info) -> dict:
    """Canonical Download Manager ``add_downloads`` payload for ONE study, built
    from server study-info.

    Centralizes the dict shape that was duplicated across the open back-fill,
    resync, and reconcile enqueue sites (the ``DownloadPlan`` seed of the unified
    pipeline). Callers pass the full server ``series`` list; the DM resume scan
    downloads only the series missing on disk, so this stays "missing-only" without
    the payload itself filtering. Pure; tolerant of partial dicts.
    """
    info = study_info or {}
    series = info.get('series') or []
    try:
        images = sum(int((s or {}).get('image_count', 0) or 0) for s in series)
    except Exception:
        images = 0
    return {
        'patient_id': _clean(patient_id),
        'patient_name': patient_name,
        'study_uid': _clean(study_uid),
        'study_date': info.get('study_date', ''),
        'modality': info.get('modality', ''),
        # The DM queue reads 'study_description' (modules/.../_dm_queue.py); keep
        # 'description' too for any consumer that reads that key. Both carry the
        # same value so study description is never lost in DM state/UI.
        'description': info.get('study_description', ''),
        'study_description': info.get('study_description', ''),
        'series_count': info.get('count_of_series', len(series)),
        'images_count': images,
        'series': series,
    }


def resolve_series_folder_key(series_number, series_uid, study_series) -> str:
    """Canonical on-disk folder name for ONE series within its study — the single
    series→disk identity the downloader (disk write) and the viewer sink (load) must
    agree on.

    Bare ``str(series_number)`` when the number is unique within the study (the common
    case, byte-identical to the legacy ``{study_uid}/{series_number}/`` layout); a stable
    disambiguated ``"<num>__<uid8>"`` for the non-largest of a same-number collision so
    neither series is overwritten (two distinct SeriesInstanceUIDs can legitimately share
    one series_number — see ``SeriesDescriptor.folder_key``).

    ``study_series`` is an iterable of ``(series_number, series_uid, image_count)`` for
    ALL series in the study. The RULE lives in one pure, plugin-mirrored impl,
    ``modules.download_manager.core.series_folder.resolve_series_folder_name`` — that is
    where the frozen download subprocess reaches it (the download payload ships
    ``modules.download_manager``, not ``PacsClient``). This accessor is the shared
    authority's facade for PacsClient-side callers (the viewer metadata sink). One impl,
    one rule. Falls back to the bare number on any error so it can never break a caller.
    """
    try:
        from modules.download_manager.core.series_folder import (
            resolve_series_folder_name,
        )
        return resolve_series_folder_name(series_number, series_uid, study_series)
    except Exception:
        return str(series_number)


class PatientStudySetService:
    """Facade — the single named API for patient study-set resolution and download
    planning that workflows should migrate to. Thin by design: the logic lives in
    the module-level functions; this groups them so callers depend on one service
    surface instead of re-implementing union / owner-filter / payload logic.
    Stateless and pure (no Qt/VTK)."""

    merge_study_uids = staticmethod(merge_study_uids)
    diff_study_uids = staticmethod(diff_study_uids)
    resolve_study_uids = staticmethod(resolve_study_uids)
    build_download_payload = staticmethod(build_download_payload)
    resolve_series_folder_key = staticmethod(resolve_series_folder_key)
