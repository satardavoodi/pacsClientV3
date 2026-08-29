"""Study -> protocol -> series, asking only where the answer is not certain.

This is the whole pre-flight in one place: by the time it returns, either every
required viewport has a validated series behind it, or nothing opens at all. The
layout is never built from a partial mapping, because a sweep started against a
half-filled layout produces a session that LOOKS complete and is wrong.

The rule at every step is the same: automatic when confident, interactive when
not, and never a silent guess.

    studies ── one?  ──────────────────────────► use it
            └─ several? ────────────────────────► ask
    protocol ── high confidence + implemented? ─► use it
             └─ anything less ─────────────────► ask
    series  ── every slot confident? ──────────► use them
            └─ some uncertain? ───────────────► ask ONLY about those
    validate ── all slots filled, no duplicates ► open
             └─ otherwise ────────────────────► refuse, explaining which slot

Prompts are injected rather than imported, so the whole state machine is
exercised headlessly with fakes; the Qt dialogs live in ``selection_dialogs``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from .constants import CONFIDENCE_HIGH
from .protocols import Protocol, ProtocolDetection, PROTOCOLS, detect_protocol
from .series_classifier import LumbarSelection, SeriesCandidate, classify_for_protocol
from .study_catalog import StudyCandidate, collect_studies, needs_study_prompt

logger = logging.getLogger(__name__)


class ResolveContext:
    """Where the resolver gets its facts. Injected so tests need no widget."""

    def __init__(self,
                 studies: Callable[[], List[StudyCandidate]],
                 probe: Callable[[StudyCandidate], List[SeriesCandidate]]):
        self.studies = studies
        self.probe = probe

    @classmethod
    def for_widget(cls, patient_widget: Any) -> "ResolveContext":
        from .series_probe import probe_study_series

        def _studies() -> List[StudyCandidate]:
            return collect_studies(patient_widget)

        def _probe(study: StudyCandidate) -> List[SeriesCandidate]:
            return probe_study_series(study.path)

        return cls(_studies, _probe)


class Prompts:
    """Everything the resolver may need to ask. Override what you need.

    The defaults decline rather than guess: a caller that supplies no UI gets
    "could not resolve", never a study or protocol picked on its behalf.
    """

    def choose_study(self, studies: Sequence[StudyCandidate],
                     reason: str) -> Optional[StudyCandidate]:
        return None

    def choose_protocol(self, protocols: Sequence[Protocol],
                        detection: ProtocolDetection) -> Optional[Protocol]:
        return None

    def choose_series(self, protocol: Protocol, slot_key: str,
                      options: Sequence[SeriesCandidate],
                      suggestion: Optional[SeriesCandidate],
                      reason: str) -> Optional[SeriesCandidate]:
        return None

    def report(self, title: str, message: str) -> None:
        logger.info("eagle_eye: %s - %s", title, message)


class Resolution:
    """A fully validated Eagle Eye run request."""

    __slots__ = ("study", "protocol", "detection", "selection", "candidates")

    def __init__(self, study: StudyCandidate, protocol: Protocol,
                 detection: ProtocolDetection, selection: LumbarSelection,
                 candidates: Sequence[SeriesCandidate]):
        self.study = study
        self.protocol = protocol
        self.detection = detection
        self.selection = selection
        self.candidates = list(candidates)

    def assignment(self, slot_key: str) -> Optional[SeriesCandidate]:
        return self.selection.candidate_for(slot_key)

    def slot_series(self) -> Dict[str, Dict[str, Any]]:
        """Slot -> a series identity that survives the move to a new tab.

        Deliberately NOT the thumbnail index: the Eagle Eye tab builds its own
        widget with its own thumbnail list, so an index resolved here means
        nothing there. SeriesInstanceUID is the durable key, with series number
        as the fallback for studies whose UIDs did not survive an import.
        """
        out: Dict[str, Dict[str, Any]] = {}
        for slot_key in self.protocol.slot_keys:
            candidate = self.assignment(slot_key)
            if candidate is None:
                continue
            out[slot_key] = {
                "series_uid": candidate.series_uid,
                "series_number": str(candidate.series_number),
                "series_description": candidate.series_description,
                "assigned_by": "user" if self.selection[slot_key].manual else "automatic",
                "confidence": self.selection[slot_key].confidence,
            }
        return out

    def as_dict(self) -> Dict[str, Any]:
        return {
            "study": self.study.as_dict(),
            "protocol": self.protocol.as_dict(),
            "protocol_detection": self.detection.as_dict(),
            "slot_series": self.slot_series(),
            "series_selection": self.selection.as_dict(),
        }


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

def _slot_options(selection: LumbarSelection, slot_key: str,
                  candidates: Sequence[SeriesCandidate]) -> List[SeriesCandidate]:
    """What the manual picker may offer for one slot.

    Only series that passed the slot's hard gates. Offering the rejected ones
    back would let a coronal series or a localizer be assigned by hand - exactly
    what the gates exist to prevent - so a slot with no viable candidate is
    reported as impossible rather than opened up to anything.
    """
    ranked = getattr(selection[slot_key], "ranked", None) or []
    if ranked:
        return [item.candidate for item in ranked]
    return []


def _region_label(region: Optional[str]) -> str:
    """'cervical_spine' -> 'Cervical Spine'; None -> 'different-region'."""
    if not region or region == "other":
        return "different-region"
    return str(region).replace("_", " ").title()


def _validate(protocol: Protocol, selection: LumbarSelection) -> Optional[str]:
    """Why this mapping must not open a layout, or None when it is sound."""
    missing = [protocol.slot(k).label for k in protocol.slot_keys
               if selection.candidate_for(k) is None]
    if missing:
        return "no series is assigned to " + ", ".join(missing)

    seen: Dict[Any, str] = {}
    for slot_key in protocol.slot_keys:
        candidate = selection.candidate_for(slot_key)
        key = candidate.series_uid or f"#{candidate.series_number}"
        label = protocol.slot(slot_key).label
        if key in seen:
            return (f"{label} and {seen[key]} are both set to the same series "
                    f"({candidate.label})")
        seen[key] = label
    return None


def resolve(context: ResolveContext, prompts: Optional[Prompts] = None) -> Optional[Resolution]:
    """Run the pre-flight. Returns None when the run must not start."""
    prompts = prompts or Prompts()

    # -- 1. which study -----------------------------------------------------
    try:
        studies = list(context.studies() or [])
    except Exception as exc:
        logger.error("eagle_eye: could not list studies: %s", exc, exc_info=True)
        prompts.report("Eagle Eye", f"Could not list this patient's studies: {exc}")
        return None

    if not studies:
        prompts.report("Eagle Eye", "No study is loaded for this patient.")
        return None

    if needs_study_prompt(studies):
        study = prompts.choose_study(
            studies, f"{len(studies)} studies are loaded for this patient.")
        if study is None:
            return None
    else:
        study = studies[0]

    # -- 2. what is in it ---------------------------------------------------
    try:
        candidates = list(context.probe(study) or [])
    except Exception as exc:
        logger.error("eagle_eye: could not read %s: %s", study.study_uid, exc, exc_info=True)
        prompts.report("Eagle Eye", f"Could not read the series of this study: {exc}")
        return None

    if not candidates:
        prompts.report(
            "Eagle Eye",
            f"No readable DICOM series were found for {study.label}.")
        return None

    # -- 3. which protocol --------------------------------------------------
    body_parts = [c.body_part for c in candidates if c.body_part]
    texts: List[str] = [study.description]
    for candidate in candidates:
        texts.extend([candidate.series_description, candidate.protocol_name,
                      candidate.study_description])

    detection = detect_protocol(body_parts, texts)
    logger.info("eagle_eye: protocol detection -> %s (%s): %s",
                detection.protocol.id if detection.protocol else None,
                detection.confidence, detection.reason)

    available = ", ".join(p.name for p in PROTOCOLS if p.implemented)

    if detection.certain:
        protocol = detection.protocol
    elif detection.confidence == CONFIDENCE_HIGH:
        # The region is KNOWN, it is simply not one Eagle Eye can capture yet.
        # Offering a protocol picker here would be dishonest and dangerous: it
        # invites picking "Lumbar Spine MRI" on a brain study, where the
        # classifier could well find a sagittal T2, a sagittal T1 and an axial
        # T2 and fill the layout with anatomy the protocol was never meant for.
        # Uncertainty is a reason to ask; lack of support is not.
        known = detection.protocol.name if detection.protocol else _region_label(detection.region)
        prompts.report(
            "Eagle Eye",
            f"This looks like a {known} study ({detection.reason}), which Eagle Eye "
            f"cannot analyse yet.\n\nSupported today: {available}.")
        return None
    else:
        protocol = prompts.choose_protocol(PROTOCOLS, detection)
        if protocol is None:
            return None

    if not protocol.implemented:
        prompts.report(
            "Eagle Eye",
            f"{protocol.name} is not available in this version yet.\n\n"
            f"Supported today: {available}.")
        return None

    # -- 4. which series fills each slot ------------------------------------
    selection = classify_for_protocol(protocol, candidates)
    for slot_key in protocol.slot_keys:
        slot = selection[slot_key]
        label = protocol.slot(slot_key).label
        logger.info("eagle_eye: %s -> %s (score=%.1f, %s)", label,
                    slot.chosen.label if slot.chosen else "UNRESOLVED",
                    slot.score, slot.confidence)

    # -- 5. ask about the uncertain slots ONLY ------------------------------
    for slot_key in protocol.slot_keys:
        slot = selection[slot_key]
        if not slot.uncertain:
            continue

        options = _slot_options(selection, slot_key, candidates)
        spec = protocol.slot(slot_key)
        if not options:
            prompts.report(
                "Eagle Eye",
                f"This study has no series that could be {spec.label}.\n\n"
                f"A {spec.plane} {spec.weighting.upper()} series is required.")
            return None

        reason = (f"Eagle Eye could not confidently identify {spec.label}."
                  if slot.chosen is not None
                  else f"Eagle Eye could not identify {spec.label}.")
        picked = prompts.choose_series(protocol, slot_key, options, slot.chosen, reason)
        if picked is None:
            return None
        selection.assign_manually(slot_key, picked)

    # -- 6. validate before anything opens ----------------------------------
    problem = _validate(protocol, selection)
    if problem:
        prompts.report(
            "Eagle Eye",
            f"The {protocol.name} layout was not opened because {problem}.")
        return None

    return Resolution(study, protocol, detection, selection, candidates)
