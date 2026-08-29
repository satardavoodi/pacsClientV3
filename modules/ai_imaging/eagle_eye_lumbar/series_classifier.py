"""Automatic Sagittal-T2 / Sagittal-T1 / Axial-T2 selection for lumbar MRI.

The reader must not have to point at the three series by hand, but a wrong
silent pick is worse than no pick: a T1 shown as T2 would poison every frame of
the capture session and, later, the analysis built on it. So this module

  * gates hard on things that CANNOT be traded off - modality, acquisition
    plane (from ImageOrientationPatient, never from a description), localizer
    or derived series, an implausibly short stack;
  * scores what remains, preferring the acquisition parameters (EchoTime,
    RepetitionTime, ScanningSequence) over free-text, because
    "SAG T2" in a description is a convention and TE = 100 ms is a fact;
  * reports a confidence band, the reasons behind the pick, and every runner-up
    with its own score, so an uncertain slot is visible rather than silent.

Pure python: no Qt, no pydicom, no VTK. Callers hand it plain dicts (see
``series_probe`` for the workstation-side adapter), which is what makes the
whole selection layer testable without a GUI or a real study.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .constants import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    SLOT_AX_T2,
    SLOT_ORDER,
    SLOT_REQUIRED_PLANE,
    SLOT_SAG_T1,
    SLOT_SAG_T2,
    UNCERTAIN_BANDS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text vocabularies
# ---------------------------------------------------------------------------
# Matched against a normalised blob of SeriesDescription + ProtocolName +
# SequenceName + ImageType. Word-boundary matching keeps "T1" out of "T1RHO"
# and stops "loc" firing inside "block".

_T2_TOKENS = ("t2", "t2w", "t2tse", "t2fse", "tse t2", "frfse", "haste", "ssfse", "drive")
_T1_TOKENS = ("t1", "t1w", "t1tse", "t1fse", "t1se", "flair t1", "mprage", "tfe t1")
_STIR_TOKENS = ("stir", "tirm", "short tau", "shorttau")
_PD_TOKENS = ("pd", "pdw", "proton")
_FATSAT_TOKENS = ("fs", "fatsat", "fat sat", "fatsuppressed", "spir", "spair", "spectral", "dixon")
_CONTRAST_TOKENS = ("gd", "gado", "post", "postcontrast", "contrast", "ce", "c+", "+c")
_LUMBAR_TOKENS = ("lumbar", "lspine", "l spine", "l-spine", "ls", "lssp", "lumbosacral", "lumb")

# Series that must never occupy a slot, whatever else they score.
_REJECT_TOKENS = (
    "localizer", "localiser", "scout", "survey", "loc", "plan", "ref",
    "dwi", "diffusion", "adc", "trace", "eadc",
    "myelo", "mrm", "mip", "mpr", "reformat", "reformatted",
    "phase", "fieldmap", "field map", "b0", "shim", "calibration",
    "screen save", "screensave", "dose", "report", "key images",
)

_DERIVED_IMAGE_TYPES = ("DERIVED", "SECONDARY", "LOCALIZER", "PROJECTION IMAGE")


def _normalise(text: Any) -> str:
    """Lowercase, collapse separators - '  SAG_T2-TSE ' -> 'sag t2 tse'."""
    if text is None:
        return ""
    if isinstance(text, (list, tuple)):
        text = " ".join(str(part) for part in text)
    out = str(text).lower()
    out = re.sub(r"[^a-z0-9+]+", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def _has_token(blob: str, token: str) -> bool:
    """Whole-token match against a normalised blob."""
    if not blob or not token:
        return False
    token = _normalise(token)
    if not token:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", blob) is not None


def _any_token(blob: str, tokens: Iterable[str]) -> Optional[str]:
    for token in tokens:
        if _has_token(blob, token):
            return token
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------

class SeriesCandidate:
    """One study series, described well enough to be scored.

    Everything is optional except ``index`` - a study whose headers are thin
    still gets classified, just with lower confidence and text-only reasons.
    """

    __slots__ = (
        "index", "series_uid", "series_number", "series_description", "protocol_name",
        "sequence_name", "image_type", "modality", "body_part", "plane", "slice_count",
        "echo_time", "repetition_time", "inversion_time", "scanning_sequence",
        "sequence_variant", "instances", "thumbnail_index", "series_path",
        "study_description", "_blob",
    )

    def __init__(
        self,
        index: int,
        series_uid: str = "",
        series_number: Any = "",
        series_description: str = "",
        protocol_name: str = "",
        sequence_name: str = "",
        image_type: Any = None,
        modality: str = "",
        body_part: str = "",
        plane: str = "",
        slice_count: int = 0,
        echo_time: Any = None,
        repetition_time: Any = None,
        inversion_time: Any = None,
        scanning_sequence: Any = "",
        sequence_variant: Any = "",
        instances: Optional[Sequence[Dict[str, Any]]] = None,
        thumbnail_index: int = -1,
        series_path: str = "",
        study_description: str = "",
    ):
        self.index = int(index)
        self.thumbnail_index = int(thumbnail_index)
        self.series_path = str(series_path or "")
        self.study_description = str(study_description or "")
        self.series_uid = str(series_uid or "")
        self.series_number = series_number
        self.series_description = str(series_description or "")
        self.protocol_name = str(protocol_name or "")
        self.sequence_name = str(sequence_name or "")
        self.image_type = image_type
        self.modality = str(modality or "").upper()
        self.body_part = str(body_part or "")
        self.plane = str(plane or "")
        self.slice_count = int(slice_count or 0)
        self.echo_time = _as_float(echo_time)
        self.repetition_time = _as_float(repetition_time)
        self.inversion_time = _as_float(inversion_time)
        self.scanning_sequence = scanning_sequence
        self.sequence_variant = sequence_variant
        self.instances = list(instances or ())
        self._blob = _normalise(
            " ".join([
                self.series_description, self.protocol_name, self.sequence_name,
                _normalise(self.image_type), _normalise(self.scanning_sequence),
                _normalise(self.sequence_variant), self.body_part,
            ])
        )

    @property
    def text(self) -> str:
        """Normalised search blob over every descriptive header."""
        return self._blob

    @property
    def label(self) -> str:
        return self.series_description or self.protocol_name or f"Series {self.series_number}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "thumbnail_index": self.thumbnail_index,
            "series_uid": self.series_uid,
            "series_number": self.series_number,
            "series_description": self.series_description,
            "protocol_name": self.protocol_name,
            "modality": self.modality,
            "plane": self.plane,
            "slice_count": self.slice_count,
            "echo_time": self.echo_time,
            "repetition_time": self.repetition_time,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SeriesCandidate":
        return cls(**data)


# ---------------------------------------------------------------------------
# Weighting evidence
# ---------------------------------------------------------------------------

WEIGHTING_T1 = "t1"
WEIGHTING_T2 = "t2"
WEIGHTING_PD = "pd"
WEIGHTING_STIR = "stir"
WEIGHTING_UNKNOWN = "unknown"

# Spin-echo boundaries. Deliberately conservative: the bands are wide enough to
# cover 1.5T and 3T lumbar protocols from every vendor, and anything landing
# between them is called unknown rather than forced into a class.
_TE_T2_MIN_MS = 70.0
_TE_T1_MAX_MS = 30.0
_TR_T1_MAX_MS = 900.0
_TR_T2_MIN_MS = 1800.0


def weighting_from_timings(candidate: SeriesCandidate) -> Optional[str]:
    """Weighting implied by TE/TR alone, or None when they do not decide it."""
    te, tr = candidate.echo_time, candidate.repetition_time
    if te is None:
        return None
    if candidate.inversion_time is not None and 80.0 <= candidate.inversion_time <= 250.0:
        return WEIGHTING_STIR
    if te >= _TE_T2_MIN_MS:
        return WEIGHTING_T2
    if te <= _TE_T1_MAX_MS:
        if tr is not None and tr >= _TR_T2_MIN_MS:
            return WEIGHTING_PD          # short TE + long TR = proton density
        if tr is None or tr <= _TR_T1_MAX_MS:
            return WEIGHTING_T1
    return None


def weighting_from_text(candidate: SeriesCandidate) -> Optional[str]:
    """Weighting implied by the descriptive headers, or None."""
    blob = candidate.text
    if _any_token(blob, _STIR_TOKENS):
        return WEIGHTING_STIR
    has_t2 = _any_token(blob, _T2_TOKENS)
    has_t1 = _any_token(blob, _T1_TOKENS)
    if has_t2 and not has_t1:
        return WEIGHTING_T2
    if has_t1 and not has_t2:
        return WEIGHTING_T1
    if _any_token(blob, _PD_TOKENS) and not (has_t1 or has_t2):
        return WEIGHTING_PD
    return None


def resolve_weighting(candidate: SeriesCandidate) -> Dict[str, Any]:
    """Combine timing and text evidence into one weighting verdict.

    Timings win when the two disagree - a mislabelled protocol is common, a
    misreported EchoTime is not - but the disagreement is recorded so the
    reason string can show it.
    """
    by_time = weighting_from_timings(candidate)
    by_text = weighting_from_text(candidate)

    if by_time and by_text and by_time != by_text:
        return {
            "weighting": by_time,
            "source": "timings_over_text",
            "conflict": True,
            "by_time": by_time,
            "by_text": by_text,
        }
    weighting = by_time or by_text or WEIGHTING_UNKNOWN
    source = "timings" if by_time else ("text" if by_text else "none")
    return {
        "weighting": weighting,
        "source": source,
        "conflict": False,
        "by_time": by_time,
        "by_text": by_text,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

_MIN_SLICES = 3


def _slot_spec(slot, protocol=None):
    """The ProtocolSlot describing ``slot``.

    ``slot`` may be a ProtocolSlot already, or a slot key resolved against
    ``protocol`` (default: the lumbar protocol). Plane, weighting and plausible
    stack size all come from the protocol definition rather than from tables in
    here, so a new protocol needs no edit to the classifier.
    """
    if hasattr(slot, "plane") and hasattr(slot, "weighting"):
        return slot
    from .protocols import LUMBAR_MRI
    spec = (protocol or LUMBAR_MRI).slot(str(slot))
    if spec is None:
        raise KeyError(f"unknown slot {slot!r} for protocol "
                       f"{(protocol or LUMBAR_MRI).id}")
    return spec


class SlotScore:
    """One candidate's fitness for one slot."""

    __slots__ = ("candidate", "slot", "score", "rejected", "reasons", "weighting")

    def __init__(self, candidate: SeriesCandidate, slot: str):
        self.candidate = candidate
        self.slot = slot
        self.score = 0.0
        self.rejected: Optional[str] = None
        self.reasons: List[str] = []
        self.weighting: Dict[str, Any] = {}

    def as_dict(self) -> Dict[str, Any]:
        data = self.candidate.as_dict()
        data.update({
            "score": round(self.score, 1),
            "rejected": self.rejected,
            "reasons": list(self.reasons),
            "weighting": self.weighting.get("weighting", WEIGHTING_UNKNOWN),
        })
        return data


def _rejection_reason(candidate: SeriesCandidate, spec) -> Optional[str]:
    """Hard gates. A rejected candidate can never fill this slot."""
    if candidate.modality and candidate.modality != "MR":
        return f"modality is {candidate.modality}, not MR"

    required_plane = spec.plane
    if candidate.plane != required_plane:
        return f"acquisition plane is {candidate.plane or 'unknown'}, not {required_plane}"

    if candidate.slice_count and candidate.slice_count < _MIN_SLICES:
        return f"only {candidate.slice_count} slice(s)"

    token = _any_token(candidate.text, _REJECT_TOKENS)
    if token:
        return f"looks like a non-diagnostic series ('{token}')"

    image_type = _normalise(candidate.image_type).upper()
    for marker in _DERIVED_IMAGE_TYPES:
        if _has_token(image_type.lower(), marker.lower()):
            return f"ImageType is {marker}"

    return None


def score_candidate(candidate: SeriesCandidate, slot, protocol=None) -> SlotScore:
    """Score one candidate for one slot. Never raises."""
    spec = _slot_spec(slot, protocol)
    result = SlotScore(candidate, spec.key)
    result.rejected = _rejection_reason(candidate, spec)
    if result.rejected:
        return result

    wanted = spec.weighting
    evidence = resolve_weighting(candidate)
    result.weighting = evidence
    weighting = evidence["weighting"]

    # --- weighting match: the dominant term -------------------------------
    if weighting == wanted:
        gain = 55.0 if evidence["source"].startswith("timings") else 40.0
        result.score += gain
        result.reasons.append(
            f"{wanted.upper()} weighting from {evidence['source']}"
            + (f" (description says {evidence['by_text']})" if evidence["conflict"] else "")
        )
    elif weighting == WEIGHTING_UNKNOWN:
        result.reasons.append("weighting could not be determined from headers")
    else:
        result.score -= 45.0
        result.reasons.append(f"weighting reads as {weighting.upper()}, not {wanted.upper()}")

    # --- plane already gated, but an explicit description agreeing helps ---
    plane_words = {"sagittal": ("sag",), "axial": ("ax", "tra"), "coronal": ("cor",)}
    if _any_token(candidate.text, plane_words.get(spec.plane, ()) + (spec.plane,)):
        result.score += 6.0
        result.reasons.append(f"description agrees with the {spec.plane} geometry")

    # --- lumbar body part --------------------------------------------------
    if _any_token(candidate.text, _LUMBAR_TOKENS):
        result.score += 8.0
        result.reasons.append("named as a lumbar / L-spine series")

    # --- penalties: still usable, but a plain series is preferred ---------
    fat = _any_token(candidate.text, _FATSAT_TOKENS)
    if fat:
        result.score -= 12.0
        result.reasons.append(f"fat-suppressed ('{fat}') - a plain sequence is preferred")
    contrast = _any_token(candidate.text, _CONTRAST_TOKENS)
    if contrast:
        result.score -= 18.0
        result.reasons.append(f"looks post-contrast ('{contrast}')")

    # --- stack size plausibility ------------------------------------------
    band = spec.plausible_slices
    if band and candidate.slice_count:
        low, high = band
        if low <= candidate.slice_count <= high:
            result.score += 10.0
            result.reasons.append(f"{candidate.slice_count} slices is typical for this plane")
        else:
            result.score -= 6.0
            result.reasons.append(f"{candidate.slice_count} slices is atypical for this plane")

    # --- geometry present at all ------------------------------------------
    if candidate.instances:
        first = candidate.instances[0] or {}
        if first.get("image_position_patient") and first.get("image_orientation_patient"):
            result.score += 6.0
        else:
            result.score -= 20.0
            result.reasons.append("instances carry no IPP/IOP - cannot be synchronised")

    result.score = max(0.0, min(100.0, result.score))
    return result


def _confidence_band(score: float, margin: float) -> str:
    if score <= 0.0:
        return CONFIDENCE_NONE
    if score >= 70.0 and margin >= 15.0:
        return CONFIDENCE_HIGH
    if score >= 50.0 and margin >= 5.0:
        return CONFIDENCE_MEDIUM
    if score >= 25.0:
        return CONFIDENCE_LOW
    return CONFIDENCE_NONE


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

class SlotSelection:
    """What was chosen for one slot, why, and what else was in the running."""

    __slots__ = ("slot", "chosen", "score", "margin", "confidence", "reasons",
                 "alternatives", "rejected", "manual", "ranked")

    def __init__(self, slot: str):
        self.slot = slot
        self.chosen: Optional[SeriesCandidate] = None
        self.score = 0.0
        self.margin = 0.0
        self.confidence = CONFIDENCE_NONE
        self.reasons: List[str] = []
        self.alternatives: List[Dict[str, Any]] = []
        self.rejected: List[Dict[str, Any]] = []
        self.manual = False
        # Every candidate that passed the hard gates for this slot, best first.
        # This is what the manual-selection dialog offers: the gates removed
        # series that CANNOT be right (wrong plane, localizer, wrong modality),
        # so offering them back would invite the exact mistake the gates exist
        # to prevent.
        self.ranked: List["SlotScore"] = []

    @property
    def resolved(self) -> bool:
        return self.chosen is not None

    @property
    def uncertain(self) -> bool:
        return (not self.resolved) or self.confidence in UNCERTAIN_BANDS

    def as_dict(self) -> Dict[str, Any]:
        return {
            "slot": self.slot,
            "resolved": self.resolved,
            "uncertain": self.uncertain,
            "assigned_by": "user" if self.manual else "automatic",
            "confidence": self.confidence,
            "score": round(self.score, 1),
            "margin_over_runner_up": round(self.margin, 1),
            "reasons": list(self.reasons),
            "selected": self.chosen.as_dict() if self.chosen else None,
            "alternatives": list(self.alternatives),
            "rejected": list(self.rejected),
        }


class LumbarSelection:
    """Every slot of a protocol, resolved together."""

    def __init__(self, protocol=None):
        if protocol is None:
            from .protocols import LUMBAR_MRI
            protocol = LUMBAR_MRI
        self.protocol = protocol
        self.slot_order: List[str] = list(protocol.slot_keys)
        self.slots: Dict[str, SlotSelection] = {
            key: SlotSelection(key) for key in self.slot_order
        }

    def __getitem__(self, slot: str) -> SlotSelection:
        return self.slots[slot]

    @property
    def resolved(self) -> bool:
        return all(sel.resolved for sel in self.slots.values())

    @property
    def uncertain_slots(self) -> List[str]:
        return [slot for slot in self.slot_order if self.slots[slot].uncertain]

    @property
    def unresolved_slots(self) -> List[str]:
        return [slot for slot in self.slot_order if not self.slots[slot].resolved]

    def candidate_for(self, slot: str) -> Optional[SeriesCandidate]:
        return self.slots[slot].chosen

    def assign_manually(self, slot: str, candidate: SeriesCandidate) -> None:
        """Record a slot the USER picked.

        Confidence becomes ``high`` because a human looked at the images - that
        is a stronger signal than any header heuristic - and the manual origin
        is kept in the reasons so the manifest shows how the slot was filled.
        """
        sel = self.slots[slot]
        sel.chosen = candidate
        sel.confidence = CONFIDENCE_HIGH
        sel.manual = True
        sel.reasons = [f"chosen by the user: {candidate.label}"]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "protocol_id": getattr(self.protocol, "id", None),
            "resolved": self.resolved,
            "uncertain_slots": self.uncertain_slots,
            "slots": {slot: self.slots[slot].as_dict() for slot in self.slot_order},
        }


def classify_for_protocol(
    protocol,
    candidates: Sequence[SeriesCandidate],
    max_alternatives: int = 3,
) -> LumbarSelection:
    """Resolve every slot a protocol requires from a study's series.

    Slot order matters and comes from the protocol: for lumbar, the two sagittal
    slots compete for the same pool, so Sagittal T2 (the anchor of the whole
    session - it drives the sweep and the T1 follows it) is assigned first and
    Sagittal T1 picks from what is left. A series is never assigned twice.
    """
    selection = LumbarSelection(protocol)
    taken: set = set()

    for slot in selection.slot_order:
        spec = protocol.slot(slot)
        sel = selection.slots[slot]
        scored: List[SlotScore] = []
        for candidate in candidates or ():
            result = score_candidate(candidate, spec, protocol)
            if result.rejected:
                sel.rejected.append({
                    "index": candidate.index,
                    "series_number": candidate.series_number,
                    "series_description": candidate.series_description,
                    "reason": result.rejected,
                })
                continue
            if candidate.index in taken:
                sel.rejected.append({
                    "index": candidate.index,
                    "series_number": candidate.series_number,
                    "series_description": candidate.series_description,
                    "reason": "already assigned to an earlier slot",
                })
                continue
            scored.append(result)

        if not scored:
            sel.confidence = CONFIDENCE_NONE
            sel.reasons.append("no series in this study passed the gates for this slot")
            continue

        scored.sort(key=lambda r: r.score, reverse=True)
        best = scored[0]
        runner_up = scored[1].score if len(scored) > 1 else 0.0
        margin = best.score - runner_up

        sel.ranked = list(scored)
        sel.alternatives = [r.as_dict() for r in scored[1:1 + max_alternatives]]
        sel.score = best.score
        sel.margin = margin
        sel.confidence = _confidence_band(best.score, margin)
        sel.reasons = list(best.reasons)

        if sel.confidence == CONFIDENCE_NONE:
            sel.reasons.append("best candidate scored too low to be trusted; slot left unresolved")
            continue

        sel.chosen = best.candidate
        taken.add(best.candidate.index)

    return selection


def classify_lumbar_series(
    candidates: Sequence[SeriesCandidate],
    max_alternatives: int = 3,
) -> LumbarSelection:
    """Lumbar-protocol shorthand for :func:`classify_for_protocol`."""
    from .protocols import LUMBAR_MRI
    return classify_for_protocol(LUMBAR_MRI, candidates, max_alternatives)
