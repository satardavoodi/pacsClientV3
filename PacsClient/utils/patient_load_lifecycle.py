"""Canonical patient-load lifecycle — the single deterministic loading authority.

Foundation of the reliability refactor described in
``docs/reports/PATIENT_LOADING_PIPELINE_RELIABILITY_REVIEW_2026-07-02.md``.

WHY THIS EXISTS
---------------
The historic load path defines "done" by *notification arrival* while mutable
shared state (a monotonic ``_thumbnail_fetch_token``, a single primary
``study_uid`` on the DM bridge, a viewport's ``_awaiting_series_number``) still
happens to match. When any notification is dropped — the user clicked again, a
token moved, a secondary (previous-exam) study's key did not match, an asyncio
task was cancelled, or the GUI thread froze — the finished work is *discarded,
not reconciled*, and nothing re-drives the study to completion. That is the
single defect behind all three reported symptoms (blank/partial thumbnails,
previous-exam "grows only after a second drag", and the machine-dependent
80/20).

This module supplies the missing owner: an **identity-keyed model** plus a
**single pure reconcile authority** that defines "done" by *state convergence
against disk*, not by a signal arriving. A dropped event costs latency, never
correctness — the next event or convergence sweep recomputes the same answer.

WHAT IT ADDS vs. WHAT IT REUSES
-------------------------------
It does NOT re-implement completeness / grow / never-downgrade logic. Those
already live in the project's pure authorities and are *composed* here:
  * ``series_completeness.SeriesCompletenessSnapshot`` — count truth table.
  * ``series_display_state.decide_display_action`` — the viewport grow/skip/await
    decision, including the never-downgrade guard (the "99 -> 8" reset fix).
This module adds the layer those do not have: per-(patient, study, series)
STAGE ownership, identity that makes a previous-exam series first-class, and
"park, never discard" so a late result for the *currently selected* study is
always applied.

CLINICAL SAFETY — read before extending
---------------------------------------
Pure stdlib only (+ the two sibling authorities). **No Qt / VTK / numpy /
pydicom, no I/O, no widget access.** It resolves *which stage a series is in and
what to do next* from counts the caller collects; it NEVER touches pixels,
geometry (IPP/IOP spacing), slice ordering, orientation, VTK render windows, or
MPR reslice. The caller performs the side effect (fetch / download / decode /
grow) and remains responsible for collecting the counts it feeds in. Keeping
this module pure is what lets it be unit-tested in isolation and prevents it
from disturbing the clinically-protected render path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

from PacsClient.utils.series_display_state import (
    DisplayAction,
    build_series_display_state,
    decide_display_action,
)

# Reuse the ONE intent vocabulary already defined by the study-set authority so
# the whole pipeline speaks a single language (no forked enum).
from PacsClient.utils.patient_study_set import Intent


# ---------------------------------------------------------------------------
# Stages & actions (the closed vocabulary of the lifecycle)
# ---------------------------------------------------------------------------
class LoadStage(str, Enum):
    """The deterministic states a series (and, aggregated, a study) moves through.

    Progression is monotonic toward a terminal state; a series never silently
    regresses (``DISPLAYED_COMPLETE`` and ``FAILED`` are sticky).
    """

    #: Identity minted from a click; nothing resolved yet.
    SELECTED = "selected"
    #: The study's series set is known (from disk cache or server).
    SERIES_KNOWN = "series_known"
    #: The series set has been rendered to the sidebar (preview terminal).
    THUMBS_READY = "thumbs_ready"
    #: OPEN intent: images are being fetched; nothing shown for this series yet.
    SERIES_LOADING = "series_loading"
    #: The first instance is decoded and shown; more are still expected.
    FIRST_IMAGE = "first_image"
    #: The viewport shows the full on-disk set and the series is complete. Terminal.
    DISPLAYED_COMPLETE = "displayed_complete"
    #: An authoritative failure. Terminal, but the user sees an explicit state.
    FAILED = "failed"


class LoadAction(str, Enum):
    """The single next thing a caller should do for a series. Output of reconcile."""

    #: Nothing to do (complete, or a skip-downgrade, or preview with thumbs shown).
    NONE = "none"
    #: The study has no series set yet — resolve it (cache-first, then server).
    RESOLVE_SERIES = "resolve_series"
    #: Series set known but sidebar not yet rendered — render thumbnails.
    RENDER_THUMBS = "render_thumbs"
    #: OPEN intent and nothing on disk — start/prioritize the download.
    START_DOWNLOAD = "start_download"
    #: Disk holds more instances than the viewport shows — load/grow the viewport
    #: up to the on-disk set (first image, or an in-place grow). Maps to the
    #: ``decide_display_action`` GROW/REBUILD/REFRESH family.
    LOAD_OR_GROW = "load_or_grow"
    #: Viewport matches disk but the series is not fully downloaded — keep the
    #: current volume and wait for more disk (never rebuild smaller).
    WAIT = "wait"


# The DisplayActions that mean "bring the viewport up to the on-disk set".
_GROW_ACTIONS = frozenset(
    {
        DisplayAction.GROW_IN_PLACE,
        DisplayAction.REFRESH_AND_REBUILD,
        DisplayAction.REBUILD,
    }
)


def _is_open_intent(intent: str) -> bool:
    """OPEN / refresh intents load a viewport; everything else is preview-only."""
    return intent in (Intent.OPEN_VIEWER, Intent.REFRESH_OPEN_VIEWER)


# ---------------------------------------------------------------------------
# Identity (collision-free key that makes a previous-exam series first-class)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CanonicalSeriesId:
    """The immutable, collision-free identity of one series.

    ``series_uid`` is globally unique, so it — not the (colliding) series number
    — is the primary match key. ``study_uid`` + ``orig_series_number`` locate the
    on-disk folder (``SOURCE_PATH/<study_uid>/<orig_series_number>``). A secondary
    (previous-exam) study carries its OWN ``study_uid`` here, which is precisely
    why it stops being a "sibling" special case and becomes first-class.
    """

    study_uid: str
    orig_series_number: str
    series_uid: str = ""

    def key(self) -> str:
        # series_uid when present (unique), else the study-scoped number.
        if self.series_uid:
            return f"uid:{self.series_uid}"
        return f"num:{self.study_uid}/{self.orig_series_number}"


# ---------------------------------------------------------------------------
# Records (the live, identity-keyed model — the single source of truth)
# ---------------------------------------------------------------------------
@dataclass
class SeriesLoadRecord:
    """Live load facts for one series. Counts are fed by the caller; monotonic
    guards here enforce the never-downgrade / sticky-terminal invariants."""

    canonical: CanonicalSeriesId
    display_key: str = ""
    #: SERVER-declared instance count (image_count). 0 == unknown. Never the disk
    #: fallback — a disk-derived expected would make on_disk == expected trivially
    #: true and defeat completeness (the poisoned-count class of bugs).
    expected: int = 0
    #: Authoritative "what exists" — from the canonical on-disk folder.
    on_disk: int = 0
    #: A ``*.part`` write is in flight (the folder is still growing).
    has_part: bool = False
    #: Frames handed to the viewport (viewer_visible_count).
    decoded: int = 0
    stage: LoadStage = LoadStage.SELECTED
    failure_cause: str = ""
    # settle tracking for the expected-unknown case (mirror of _disk_series_settled)
    _stable_disk_ticks: int = 0
    _last_seen_disk: int = -1

    # -- monotonic mutators (the only way counts change) --------------------
    def note_expected(self, value: int) -> None:
        try:
            v = max(0, int(value or 0))
        except Exception:
            return
        # expected only ever resolves upward to the true server count.
        if v > self.expected:
            self.expected = v

    def note_disk(self, on_disk: int, has_part: bool = False) -> None:
        try:
            v = max(0, int(on_disk or 0))
        except Exception:
            return
        self.has_part = bool(has_part)
        # Track stability for the expected-unknown completion path: the same
        # nonzero count seen twice in a row with no .part == settled.
        if v == self._last_seen_disk and v > 0 and not has_part:
            self._stable_disk_ticks += 1
        else:
            self._stable_disk_ticks = 0
        self._last_seen_disk = v
        # on_disk is authoritative and may legitimately grow; it should not drop
        # below a previously observed complete count within one identity.
        if v >= self.on_disk:
            self.on_disk = v

    def note_decoded(self, value: int) -> None:
        try:
            v = max(0, int(value or 0))
        except Exception:
            return
        if v > self.decoded:  # viewer slice count never regresses within a series
            self.decoded = v

    def fail(self, cause: str) -> None:
        if self.stage != LoadStage.DISPLAYED_COMPLETE:
            self.failure_cause = str(cause or "unknown")
            self.stage = LoadStage.FAILED

    @property
    def settled(self) -> bool:
        """True when the on-disk folder has stopped changing (expected unknown)."""
        return self._stable_disk_ticks >= 1 and self.on_disk > 0 and not self.has_part

    @property
    def disk_complete(self) -> bool:
        if self.expected > 0:
            return self.on_disk >= self.expected
        return self.settled


@dataclass
class StudyLoadRecord:
    """Live load facts for one study (a set of series under one study_uid)."""

    patient_id: str
    study_uid: str
    intent: str = Intent.PREVIEW_ONLY
    series_known: bool = False
    thumbs_rendered: bool = False
    series: Dict[str, SeriesLoadRecord] = field(default_factory=dict)
    stage: LoadStage = LoadStage.SELECTED


# ---------------------------------------------------------------------------
# The single reconcile authority (pure — the §6.4 decide-once function)
# ---------------------------------------------------------------------------
def reconcile_series(rec: SeriesLoadRecord, intent: str) -> LoadAction:
    """Decide the ONE next action for a series. Pure; no I/O, no mutation.

    The viewport grow / skip-downgrade / await decision is delegated verbatim to
    ``decide_display_action`` so the never-downgrade guarantee lives in exactly
    one place. This function only adds the stage semantics around it.
    """
    if rec.stage == LoadStage.FAILED:
        return LoadAction.NONE

    # Preview intent never loads a viewport — thumbnails are the terminal.
    if not _is_open_intent(intent):
        return LoadAction.NONE

    # Nothing on disk yet: the only useful action is to (keep) downloading.
    if rec.on_disk == 0:
        return LoadAction.START_DOWNLOAD

    # Delegate the count-level decision to the shared authority.
    state = build_series_display_state(
        rec.canonical.key(),
        server_count=rec.expected,
        disk_count=rec.on_disk,
        canonical_metadata_count=rec.on_disk,
        viewer_visible_count=rec.decoded,
        expected_count=rec.expected,
        has_lazy_loader=True,  # FAST/Advanced expose a lazy grow; caller may refine
    )
    action = decide_display_action(state)

    if action in _GROW_ACTIONS:
        # Viewer is behind disk (includes the 0 -> first-image case).
        return LoadAction.LOAD_OR_GROW
    if action == DisplayAction.AWAIT_DOWNLOAD:
        return LoadAction.WAIT
    if action == DisplayAction.SKIP_DOWNGRADE:
        return LoadAction.NONE
    # NOOP: viewer shows the full known set. Complete when disk-complete, else wait
    # for more instances to arrive on disk.
    if rec.disk_complete:
        return LoadAction.NONE
    return LoadAction.WAIT


def derive_series_stage(rec: SeriesLoadRecord, intent: str) -> LoadStage:
    """Pure: the stage a series is in, given its current counts. Sticky terminals
    are honored by the caller (``PatientLoadModel``) which never downgrades."""
    if rec.stage == LoadStage.FAILED:
        return LoadStage.FAILED

    if not _is_open_intent(intent):
        # Preview: the series is "known"; the study-level THUMBS_READY is set once
        # the sidebar renders (tracked on the study record).
        return LoadStage.SERIES_KNOWN

    if rec.decoded <= 0:
        return LoadStage.SERIES_LOADING

    # Something is shown. Complete only when the viewer has caught disk AND the
    # series is disk-complete (expected met, or settled when expected unknown).
    if rec.decoded >= rec.on_disk and rec.disk_complete:
        return LoadStage.DISPLAYED_COMPLETE
    return LoadStage.FIRST_IMAGE


def derive_study_stage(study: StudyLoadRecord) -> LoadStage:
    """Pure: aggregate a study's stage from its series and preview/open intent."""
    if not study.series_known:
        return LoadStage.SELECTED
    if not _is_open_intent(study.intent):
        return LoadStage.THUMBS_READY if study.thumbs_rendered else LoadStage.SERIES_KNOWN

    stages = [s.stage for s in study.series.values()]
    if not stages:
        return LoadStage.SERIES_KNOWN
    if all(st == LoadStage.DISPLAYED_COMPLETE for st in stages):
        return LoadStage.DISPLAYED_COMPLETE
    if all(st in (LoadStage.DISPLAYED_COMPLETE, LoadStage.FAILED) for st in stages):
        # Every series terminal, at least one failed.
        return LoadStage.FAILED if any(st == LoadStage.FAILED for st in stages) else LoadStage.DISPLAYED_COMPLETE
    if any(st in (LoadStage.FIRST_IMAGE, LoadStage.DISPLAYED_COMPLETE) for st in stages):
        return LoadStage.FIRST_IMAGE
    return LoadStage.SERIES_LOADING


# ---------------------------------------------------------------------------
# Cutover policy — Seam A: what to do with a token-stale thumbnail result
# ---------------------------------------------------------------------------
def resolve_stale_thumbnail_action(
    token_matches: bool,
    is_active_selection: bool,
    cutover_enabled: bool,
) -> str:
    """Decide what to do with a returned right-panel thumbnail fetch whose request
    token no longer matches (a newer selection bumped ``_thumbnail_fetch_token``).

    LEGACY (``cutover_enabled=False``) always discards on a token mismatch. That
    also drops a result for a study the user has clicked BACK to (A -> B -> A):
    the token was bumped by B, but the fetch is for A and A is active again — the
    exact "only the first thumbnail / blank sidebar until reopen" loss (Problem #1).

    CUTOVER (``cutover_enabled=True``) renders a token-stale result IFF it is still
    for the currently-active selection. Cross-patient safety is UNCHANGED: the
    caller still re-checks ``_is_active_patient_selection`` immediately before
    ``display_thumbnails`` (the legacy final guard), so a result for a
    non-active patient can never be shown. This only stops discarding a result
    that legacy would itself have been willing to display had the token not moved.

    Returns ``'render'`` or ``'discard'``. Pure; no side effects.
    """
    if token_matches:
        return "render"
    if cutover_enabled and is_active_selection:
        return "render"
    return "discard"


# ---------------------------------------------------------------------------
# Transition record (Stage-0 instrumentation — pure; the wiring layer logs it)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Transition:
    """One stage change, emitted for the structured ``[LIFECYCLE]`` log so the
    invariant 'every SELECTED reaches DISPLAYED_COMPLETE' is measurable live."""

    patient_id: str
    study_uid: str
    series_key: str  # "" for a study-level transition
    frm: LoadStage
    to: LoadStage
    reason: str = ""


def format_transition(t: Transition) -> str:
    """Pure formatter for the structured log line. The wiring layer calls
    ``logger.info(format_transition(t))`` so this module imports no logging/Qt."""
    scope = f"study={t.study_uid[-16:]}" + (f" series={t.series_key}" if t.series_key else "")
    return (
        f"[LIFECYCLE] patient={t.patient_id} {scope} "
        f"{t.frm.value}->{t.to.value}" + (f" reason={t.reason}" if t.reason else "")
    )


# ---------------------------------------------------------------------------
# The model container (identity-keyed; park-never-discard; convergence owner)
# ---------------------------------------------------------------------------
class PatientLoadModel:
    """Single source of truth for one patient's in-flight loads.

    Every event updates the identity-keyed record it belongs to — even for a
    study that is not the currently displayed one — so a late/slow result is
    PARKED, never discarded (the fix for the thumbnail-discard defect). The UI
    is a pure projection: ``render(model)``; a missed event cannot corrupt it.

    The class holds NO Qt/timer/thread state; the wiring layer drives it from Qt
    callbacks and a single convergence sweep, and reads back actions + transitions.
    """

    #: Memory bounds so a long, default-ON clinical session cannot grow without
    #: limit. ``transitions`` is a rolling telemetry log; studies are evicted only
    #: when TERMINAL (never an in-flight study), preserving park-never-discard.
    _MAX_TRANSITIONS = 5000
    _TRANSITIONS_TRIM_TO = 4000
    _MAX_STUDIES = 1000
    _STUDIES_KEEP = 800

    def __init__(self, on_transition: Optional[Callable[[Transition], None]] = None):
        self._studies: Dict[str, StudyLoadRecord] = {}
        self._on_transition = on_transition
        self.transitions: List[Transition] = []

    # -- identity helpers ---------------------------------------------------
    @staticmethod
    def _skey(study_uid: str) -> str:
        return str(study_uid or "").strip()

    def study(self, study_uid: str) -> Optional[StudyLoadRecord]:
        return self._studies.get(self._skey(study_uid))

    def _push_transition(self, t: "Transition") -> None:
        """Append to the rolling (bounded) telemetry log and notify the callback."""
        self.transitions.append(t)
        if len(self.transitions) > self._MAX_TRANSITIONS:
            del self.transitions[: len(self.transitions) - self._TRANSITIONS_TRIM_TO]
        if self._on_transition is not None:
            try:
                self._on_transition(t)
            except Exception:
                pass  # instrumentation must never break the pipeline

    def _evict_terminal_studies(self) -> None:
        """Bound the study map. Evict only TERMINAL studies (thumbs-ready preview,
        displayed-complete, or failed), oldest first — never an in-flight study, so
        the park-never-discard invariant for active work is preserved."""
        if len(self._studies) <= self._MAX_STUDIES:
            return
        terminal = (LoadStage.THUMBS_READY, LoadStage.DISPLAYED_COMPLETE, LoadStage.FAILED)
        for key in list(self._studies.keys()):
            if len(self._studies) <= self._STUDIES_KEEP:
                break
            if self._studies[key].stage in terminal:
                del self._studies[key]

    def _emit(self, study: StudyLoadRecord, before: LoadStage, series_key: str, reason: str) -> None:
        after = study.stage
        if after == before:
            return
        t = Transition(study.patient_id, study.study_uid, series_key, before, after, reason)
        self._push_transition(t)

    def _refresh_study_stage(self, study: StudyLoadRecord, series_key: str, reason: str) -> None:
        before = study.stage
        new = derive_study_stage(study)
        # Never downgrade a study out of a terminal state on a benign re-eval.
        if before in (LoadStage.DISPLAYED_COMPLETE,) and new != LoadStage.DISPLAYED_COMPLETE:
            return
        study.stage = new
        self._emit(study, before, series_key, reason)

    # -- events (each updates identity-keyed state, then reconciles) ---------
    def on_selection(self, patient_id: str, study_uid: str, intent: str) -> StudyLoadRecord:
        """A patient/study was selected. Idempotent: re-selecting the same study
        does not reset progress (the fix for 'reopen re-fetches everything')."""
        key = self._skey(study_uid)
        study = self._studies.get(key)
        if study is None:
            study = StudyLoadRecord(patient_id=str(patient_id or ""), study_uid=key, intent=intent)
            self._studies[key] = study
            self._evict_terminal_studies()  # bound memory for long default-ON sessions
        else:
            # Upgrade intent (preview -> open) without discarding known state.
            if _is_open_intent(intent):
                study.intent = intent
        self._refresh_study_stage(study, "", "selection")
        return study

    def on_series_set(self, study_uid: str, series: List[CanonicalSeriesId],
                      *, expected: Optional[Dict[str, int]] = None) -> None:
        """The study's series set is resolved. Merges (never truncates) so a
        previous-exam series added later is additive, and re-resolution is a no-op."""
        study = self.study(study_uid)
        if study is None:
            return
        expected = expected or {}
        for cid in series:
            rk = cid.key()
            rec = study.series.get(rk)
            if rec is None:
                rec = SeriesLoadRecord(canonical=cid)
                study.series[rk] = rec
            if rk in expected:
                rec.note_expected(expected[rk])
        study.series_known = True
        self._refresh_study_stage(study, "", "series_set")

    def mark_thumbs_rendered(self, study_uid: str) -> None:
        study = self.study(study_uid)
        if study is None:
            return
        study.thumbs_rendered = True
        self._refresh_study_stage(study, "", "thumbs_rendered")

    def _series(self, study_uid: str, cid: CanonicalSeriesId) -> Optional[SeriesLoadRecord]:
        study = self.study(study_uid)
        if study is None:
            return None
        rk = cid.key()
        rec = study.series.get(rk)
        if rec is None:
            rec = SeriesLoadRecord(canonical=cid)
            study.series[rk] = rec
        return rec

    def on_disk_change(self, study_uid: str, cid: CanonicalSeriesId,
                       on_disk: int, *, has_part: bool = False,
                       expected: Optional[int] = None) -> LoadAction:
        """Authoritative disk update for a series. Returns the reconciled action.
        This is the event that makes completion converge WITHOUT any progress
        signal — the fix for the previous-exam 'grows only on second drag'."""
        rec = self._series(study_uid, cid)
        study = self.study(study_uid)
        if rec is None or study is None:
            return LoadAction.NONE
        if expected is not None:
            rec.note_expected(expected)
        rec.note_disk(on_disk, has_part=has_part)
        return self._advance_series(study, rec, "disk_change")

    def on_decoded(self, study_uid: str, cid: CanonicalSeriesId, decoded: int) -> LoadAction:
        """The viewport now shows ``decoded`` frames of this series."""
        rec = self._series(study_uid, cid)
        study = self.study(study_uid)
        if rec is None or study is None:
            return LoadAction.NONE
        rec.note_decoded(decoded)
        return self._advance_series(study, rec, "decoded")

    def on_failure(self, study_uid: str, cid: CanonicalSeriesId, cause: str) -> LoadAction:
        rec = self._series(study_uid, cid)
        study = self.study(study_uid)
        if rec is None or study is None:
            return LoadAction.NONE
        rec.fail(cause)
        self._refresh_study_stage(study, rec.canonical.key(), f"failed:{cause}")
        return LoadAction.NONE

    def _advance_series(self, study: StudyLoadRecord, rec: SeriesLoadRecord, reason: str) -> LoadAction:
        """Recompute a series' sticky stage + return its reconciled action."""
        before = rec.stage
        new = derive_series_stage(rec, study.intent)
        # Sticky terminals: never downgrade a completed/failed series.
        if before == LoadStage.DISPLAYED_COMPLETE:
            new = LoadStage.DISPLAYED_COMPLETE
        elif before == LoadStage.FAILED:
            new = LoadStage.FAILED
        if new != before:
            rec.stage = new
            # a per-series transition is worth logging for the invariant proof
            t = Transition(study.patient_id, study.study_uid, rec.canonical.key(), before, new, reason)
            self._push_transition(t)
        self._refresh_study_stage(study, rec.canonical.key(), reason)
        return reconcile_series(rec, study.intent)

    # -- convergence sweep (replaces the GUI-thread polling watchdog) --------
    def non_terminal_series(self) -> List[Tuple[str, CanonicalSeriesId]]:
        """Every series not yet in a terminal stage — the set the convergence
        sweep must keep re-driving. Empty == everything converged (sweep stops)."""
        out: List[Tuple[str, CanonicalSeriesId]] = []
        for study in self._studies.values():
            if not _is_open_intent(study.intent):
                continue
            for rec in study.series.values():
                if rec.stage not in (LoadStage.DISPLAYED_COMPLETE, LoadStage.FAILED):
                    out.append((study.study_uid, rec.canonical))
        return out

    def is_settled(self) -> bool:
        """True when no OPEN study has a non-terminal series left — the invariant
        the validation harness asserts (§8): every SELECTED-open study converged."""
        return not self.non_terminal_series()

    def pending_action(self, study_uid: str, cid: CanonicalSeriesId, intent: Optional[str] = None) -> LoadAction:
        """Reconcile a single series on demand (used by the convergence sweep)."""
        study = self.study(study_uid)
        if study is None:
            return LoadAction.NONE
        rec = study.series.get(cid.key())
        if rec is None:
            return LoadAction.NONE
        return reconcile_series(rec, intent or study.intent)
