"""
Two-Stage 3D Cursor — session data model and persistence.

Records the full provenance of one correspondence attempt, so that a result shown
on screen can always be traced back to the exact inputs that produced it:

    source lesion + source view + original run/threshold
        -> predicted region (method, distance, bands)
            -> second-pass run/threshold
                -> candidates
                    -> selected candidate + score

This matters for two reasons beyond tidiness:

  1. CLINICAL AUDIT. If a radiologist acts on a highlighted correspondence, we must
     be able to say which model run, which threshold and which landmarks produced
     it. "The AI said so" is not a record.

  2. GROUND TRUTH. Every confirmed session is a labelled CC/MLO correspondence
     pair — precisely the data that does not exist publicly (CL-Net's authors had
     to hand-label DDSM). Persisting sessions turns normal clinical use into the
     validation set we need to calibrate the band widths and the Stage-2 weights.
     Nothing else in the plan unblocks without it.

Purity: stdlib only (json, dataclasses, uuid, datetime). No Qt, VTK, numpy.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


SESSION_FILENAME = "mg_3dcursor_sessions.json"
SCHEMA_VERSION = 1


@dataclass
class SessionLesion:
    """A lesion box with everything needed to re-derive its geometry later."""
    box_px: List[float]
    score: float = 0.5
    classification: Optional[str] = None
    finding_uid: Optional[str] = None
    center_px: Optional[Tuple[float, float]] = None


@dataclass
class SessionRegion:
    """The Stage-1 prediction, in a form that survives a round trip to disk."""
    method: str                       # 'ss' | 'ab'
    distance_mm: float
    distance_kind: str                # 'axial' | 'radial'
    inner_band_mm: float
    outer_band_mm: float
    nominal_point_px: Optional[Tuple[float, float]] = None
    ok: bool = True
    message: str = ""


@dataclass
class SessionCandidate:
    box_px: List[float]
    score: float
    total: float
    rank: int
    deviation_mm: float
    in_inner_band: bool
    in_outer_band: bool
    classification: Optional[str] = None
    components: Dict[str, float] = field(default_factory=dict)


@dataclass
class TwoStageSession:
    """One complete two-stage correspondence attempt."""
    session_id: str
    study_uid: str
    laterality: str

    # ── Stage 0: the source lesion, and where it came from ──
    source_view: str                              # 'CC' | 'MLO'
    target_view: str                              # 'CC' | 'MLO'
    source_lesion: SessionLesion
    original_run_detection_csv: Optional[str] = None
    original_threshold: Optional[float] = None

    # ── Landmarks (so the region is reproducible) ──
    source_nipple_px: Optional[Tuple[float, float]] = None
    target_nipple_px: Optional[Tuple[float, float]] = None
    pectoral_angle_deg: Optional[float] = None
    # PNL cross-view depth-normalisation diagnostic (legacy horizontal depth,
    # perpendicular depth, normalised depth, both nipple→pectoral PNLs, and the
    # correction ratio). None when GM/PNL was not applicable. Recorded whether or
    # not the normaliser was applied, so a study can be re-analysed offline.
    pnl: Optional[Dict[str, Any]] = None

    # ── Stage 1: the predicted region ──
    region: Optional[SessionRegion] = None

    # ── Stage 2: the lower-threshold rerun ──
    second_pass_run_id: Optional[str] = None
    second_pass_detection_csv: Optional[str] = None
    second_pass_threshold: Optional[float] = None
    second_pass_status: str = "not_started"   # not_started|running|done|failed|skipped
    second_pass_error: Optional[str] = None

    # ── Stage 2: candidates and outcome ──
    candidates: List[SessionCandidate] = field(default_factory=list)
    match_status: str = "pending"             # match|ambiguous|no_match|pending
    selected_candidate: Optional[SessionCandidate] = None
    match_score: Optional[float] = None
    match_margin: Optional[float] = None
    message: str = ""

    # ── Human adjudication (the ground-truth signal) ──
    # Set only when the radiologist explicitly confirms/rejects. `None` = not
    # reviewed. NEVER infer this from the fact that a match was displayed.
    human_confirmed: Optional[bool] = None
    human_confirmed_box_px: Optional[List[float]] = None

    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Persistence ─────────────────────────────────────────────────────────────

def sessions_path(study_uid: str, attachments_path: str) -> str:
    return os.path.join(str(attachments_path), str(study_uid), SESSION_FILENAME)


def load_sessions(study_uid: str, attachments_path: str) -> List[Dict[str, Any]]:
    """Return the raw session dicts for a study. Never raises."""
    path = sessions_path(study_uid, attachments_path)
    try:
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        sessions = data.get("sessions", [])
        return sessions if isinstance(sessions, list) else []
    except Exception:
        return []


def save_session(
    session: TwoStageSession,
    attachments_path: str,
) -> Optional[str]:
    """
    Append (or replace-by-id) a session. Atomic write; never raises.

    Returns the file path on success, None on failure. A persistence failure must
    never break the clinical workflow — the result is already on screen; losing the
    audit record is bad but not dangerous, and raising here would be.
    """
    try:
        path = sessions_path(session.study_uid, attachments_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        existing = load_sessions(session.study_uid, attachments_path)
        payload = session.to_dict()
        replaced = False
        for i, s in enumerate(existing):
            if s.get("session_id") == session.session_id:
                existing[i] = payload
                replaced = True
                break
        if not replaced:
            existing.append(payload)

        doc = {"schema_version": SCHEMA_VERSION, "sessions": existing}

        directory = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        return path
    except Exception as exc:  # noqa: BLE001 — persistence must never be fatal
        print(f"[3D-Cursor][SESSION] save failed (non-fatal): {exc}")
        return None


# ─── Builders ────────────────────────────────────────────────────────────────

def session_from_result(
    *,
    study_uid: str,
    laterality: str,
    source_view: str,
    target_view: str,
    source_lesion,                 # geometry.LesionLocation
    region,                        # search_region.SearchRegion | None
    match_result,                  # candidate_matching.MatchResult | None
    original_threshold: Optional[float] = None,
    original_run_detection_csv: Optional[str] = None,
    second_pass_threshold: Optional[float] = None,
    second_pass_detection_csv: Optional[str] = None,
    second_pass_run_id: Optional[str] = None,
    second_pass_status: str = "not_started",
    second_pass_error: Optional[str] = None,
    source_nipple_px: Optional[Tuple[float, float]] = None,
    target_nipple_px: Optional[Tuple[float, float]] = None,
    pectoral_angle_deg: Optional[float] = None,
    pnl: Optional[Dict[str, Any]] = None,
    source_classification: Optional[str] = None,
) -> TwoStageSession:
    """Assemble a persistable session from the live Stage-1/Stage-2 objects."""
    src = SessionLesion(
        box_px=[float(v) for v in source_lesion.to_pixel_box()],
        score=float(getattr(source_lesion, "score", 0.5)),
        classification=source_classification,
        center_px=tuple(source_lesion.center_px),
    )

    sess_region = None
    if region is not None:
        sess_region = SessionRegion(
            method=region.method,
            distance_mm=round(float(region.distance_mm), 3),
            distance_kind=region.distance_kind,
            inner_band_mm=float(region.inner_band_mm),
            outer_band_mm=float(region.outer_band_mm),
            nominal_point_px=region.nominal_point_px,
            ok=bool(region.ok),
            message=region.message,
        )

    cands: List[SessionCandidate] = []
    selected: Optional[SessionCandidate] = None
    status = "pending"
    score: Optional[float] = None
    margin: Optional[float] = None
    message = ""

    if match_result is not None:
        status = match_result.status
        margin = match_result.margin
        message = match_result.message
        for s in match_result.ranked:
            cands.append(SessionCandidate(
                box_px=[float(v) for v in s.candidate.box_px],
                score=float(s.candidate.score),
                total=float(s.total),
                rank=int(s.rank),
                deviation_mm=float(s.deviation_mm),
                in_inner_band=bool(s.in_inner_band),
                in_outer_band=bool(s.in_outer_band),
                classification=s.candidate.classification,
                components=dict(s.components),
            ))
        if match_result.best is not None:
            b = match_result.best
            selected = SessionCandidate(
                box_px=[float(v) for v in b.candidate.box_px],
                score=float(b.candidate.score),
                total=float(b.total),
                rank=int(b.rank),
                deviation_mm=float(b.deviation_mm),
                in_inner_band=bool(b.in_inner_band),
                in_outer_band=bool(b.in_outer_band),
                classification=b.candidate.classification,
                components=dict(b.components),
            )
            score = float(b.total)

    return TwoStageSession(
        session_id=TwoStageSession.new_id(),
        study_uid=str(study_uid),
        laterality=str(laterality),
        source_view=str(source_view),
        target_view=str(target_view),
        source_lesion=src,
        original_run_detection_csv=original_run_detection_csv,
        original_threshold=original_threshold,
        source_nipple_px=source_nipple_px,
        target_nipple_px=target_nipple_px,
        pectoral_angle_deg=pectoral_angle_deg,
        pnl=pnl,
        region=sess_region,
        second_pass_run_id=second_pass_run_id,
        second_pass_detection_csv=second_pass_detection_csv,
        second_pass_threshold=second_pass_threshold,
        second_pass_status=second_pass_status,
        second_pass_error=second_pass_error,
        candidates=cands,
        match_status=status,
        selected_candidate=selected,
        match_score=score,
        match_margin=margin,
        message=message,
    )
