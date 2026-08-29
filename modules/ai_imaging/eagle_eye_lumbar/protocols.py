"""Eagle Eye protocol definitions - what each body-region workflow requires.

A protocol says three things: which body region it covers, which series slots it
needs, and how those slots are laid out on screen. Everything downstream reads
them from here rather than knowing "lumbar means three panes" in its own code,
so adding Cervical Spine MRI later is a new entry in ``PROTOCOLS`` plus a sweep,
not an edit spread across the classifier, the layout and the dialogs.

This module is also the ONE place that maps a DICOM ``BodyPartExamined`` code to
an anatomical region; ``eagle_eye_modes`` delegates to it. That table used to
exist only as a lumbar-vs-everything-else pair of sets, which could not answer
"then WHICH region is it?" - the question the protocol picker has to answer when
detection is uncertain.

Pure python: no Qt, no pydicom.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .analysis_prompt import LUMBAR_PATHOLOGY
from .constants import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    PLANE_AXIAL,
    PLANE_CORONAL,
    PLANE_SAGITTAL,
    SLOT_AX_T2,
    SLOT_LABELS,
    SLOT_ORDER,
    SLOT_SAG_T1,
    SLOT_SAG_T2,
)

WEIGHTING_T1 = "t1"
WEIGHTING_T2 = "t2"


class ProtocolSlot:
    """One viewport of a protocol and the series it must be filled with."""

    __slots__ = ("key", "label", "position", "plane", "weighting",
                 "min_slices", "max_slices")

    def __init__(self, key: str, label: str, position: int, plane: str,
                 weighting: str, min_slices: int = 0, max_slices: int = 0):
        self.key = key
        self.label = label
        self.position = int(position)     # 1-based viewport index, left to right
        self.plane = plane                # required acquisition plane (from IOP)
        self.weighting = weighting        # required contrast weighting
        self.min_slices = int(min_slices)  # plausible stack size, 0 = no opinion
        self.max_slices = int(max_slices)

    @property
    def plausible_slices(self) -> Optional[Tuple[int, int]]:
        if self.min_slices and self.max_slices:
            return (self.min_slices, self.max_slices)
        return None

    def as_dict(self) -> Dict[str, object]:
        return {
            "key": self.key, "label": self.label, "position": self.position,
            "plane": self.plane, "weighting": self.weighting,
            "plausible_slices": list(self.plausible_slices or ()),
        }


class CaptureSession:
    """One screenshot sweep of a protocol, described as data.

    The controller runs whatever sessions a protocol declares, in order, and
    knows nothing about "sagittal" or "axial" beyond what it reads here. Adding
    Brain MRI means adding sessions to a protocol, not adding branches to the
    sweep.

    Roles, not viewports. ``primary``/``synced``/``reference`` name SERIES ROLES
    (``constants.SLOT_*``); the protocol's slots map those onto positions.

    - ``primary``    the series that drives the sweep, one frame per slice
    - ``synced``     series that follow it to the corresponding anatomy each
                     frame (Lock Sync moves them; geometry verifies them)
    - ``reference``  series that provide cross-reference. ``park_reference``
                     decides whether they hold one slice for the whole sweep
                     (so only the reference line moves) or follow the primary.
    - ``hide_reference_lines_on`` the viewports that must be captured CLEAN.
                     Defaults to primary + synced — the panes actually being
                     evaluated — because a line drawn across the anatomy under
                     assessment degrades the very image the sweep exists to
                     produce. An explicit tuple overrides the default.
    """

    __slots__ = ("name", "label", "primary", "synced", "reference", "plane",
                 "park_reference", "_hide_reference_lines_on",
                 "directory", "file_prefix", "session_type")

    def __init__(self, name: str, primary: str, plane: str,
                 label: str = "", synced: Sequence[str] = (),
                 reference: Sequence[str] = (), park_reference: bool = False,
                 hide_reference_lines_on: Optional[Sequence[str]] = None,
                 directory: str = "", file_prefix: str = "",
                 session_type: str = ""):
        self.name = str(name)
        self.label = label or self.name.replace("_", " ").title()
        self.primary = str(primary)
        self.plane = str(plane)
        self.synced = tuple(synced)
        self.reference = tuple(reference)
        self.park_reference = bool(park_reference)
        self._hide_reference_lines_on = (
            None if hide_reference_lines_on is None else tuple(hide_reference_lines_on)
        )
        self.directory = directory or self.name.title()
        self.file_prefix = file_prefix or self.name
        self.session_type = session_type or self.name

    @property
    def evaluation_roles(self) -> Tuple[str, ...]:
        """The panes this sweep exists to produce images OF."""
        return (self.primary,) + self.synced

    @property
    def hide_reference_lines_on(self) -> Tuple[str, ...]:
        """Roles whose viewport must carry NO reference line during this sweep."""
        if self._hide_reference_lines_on is not None:
            return self._hide_reference_lines_on
        return self.evaluation_roles

    @property
    def roles(self) -> Tuple[str, ...]:
        return self.evaluation_roles + self.reference

    def as_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "label": self.label,
            "primary": self.primary,
            "synced": list(self.synced),
            "reference": list(self.reference),
            "plane": self.plane,
            "park_reference": self.park_reference,
            "hide_reference_lines_on": list(self.hide_reference_lines_on),
            "directory": self.directory,
        }


class Protocol:
    """A body-region workflow: required slots, layout, and capture sessions."""

    __slots__ = ("id", "name", "modality", "regions", "slots", "layout",
                 "capture", "sessions", "analysis")

    def __init__(self, id: str, name: str, modality: str, regions: Sequence[str],
                 slots: Sequence[ProtocolSlot] = (), layout: Tuple[int, int] = (1, 1),
                 capture: bool = False, sessions: Sequence[CaptureSession] = (),
                 analysis=None):
        self.id = id
        self.name = name
        self.modality = modality
        self.regions = tuple(regions)
        self.slots = tuple(slots)
        self.layout = tuple(layout)
        # False = the protocol is offered in the picker so the user can see it
        # is coming, but no capture pipeline exists for it yet. Better than
        # hiding it and better than letting it fail halfway through a sweep.
        self.capture = bool(capture)
        self.sessions = tuple(sessions)
        # The `analysis_prompt.AnalysisPrompt` this protocol's captures are read
        # with, or None for a protocol that captures but is not analysed yet.
        # The prompt is protocol DATA for the same reason the sweeps are: the
        # packaging and request code must stay free of body-part knowledge.
        self.analysis = analysis

    @property
    def implemented(self) -> bool:
        """Capturable: slots to fill AND at least one sweep to run over them."""
        return self.capture and bool(self.slots) and bool(self.sessions)

    @property
    def analysable(self) -> bool:
        """Capturable AND carries a prompt to read the captures with.

        Separate from ``implemented`` on purpose: a protocol whose sweeps work
        is still useful without an LLM prompt, and offering analysis it cannot
        perform would fail after the whole study had already been captured.
        """
        return self.implemented and self.analysis is not None

    @property
    def sync_groups(self) -> Tuple[Tuple[str, ...], ...]:
        """Role groups that move together, derived from the sessions.

        Derived rather than declared so it cannot contradict the sweeps that
        actually do the moving: for lumbar this is (sagittal_t2, sagittal_t1),
        because the sagittal sweep drives T2 with T1 synced to it.
        """
        groups = []
        for session in self.sessions:
            if session.synced:
                groups.append((session.primary,) + session.synced)
        return tuple(groups)

    def session(self, name: str) -> Optional[CaptureSession]:
        for item in self.sessions:
            if item.name == name:
                return item
        return None

    @property
    def slot_keys(self) -> Tuple[str, ...]:
        return tuple(slot.key for slot in self.slots)

    def slot(self, key: str) -> Optional[ProtocolSlot]:
        for item in self.slots:
            if item.key == key:
                return item
        return None

    def as_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "modality": self.modality,
            "regions": list(self.regions),
            "layout": {"rows": self.layout[0], "columns": self.layout[1]},
            "slots": [slot.as_dict() for slot in self.slots],
            "sessions": [session.as_dict() for session in self.sessions],
            "sync_groups": [list(group) for group in self.sync_groups],
            "implemented": self.implemented,
            "analysable": self.analysable,
            "analysis": (self.analysis.as_dict() if self.analysis is not None else None),
        }


# ---------------------------------------------------------------------------
# Regions
# ---------------------------------------------------------------------------

REGION_LUMBAR = "lumbar_spine"
REGION_CERVICAL = "cervical_spine"
REGION_THORACIC = "thoracic_spine"
REGION_KNEE = "knee"
REGION_SHOULDER = "shoulder"
REGION_BRAIN = "brain"
REGION_OTHER = "other"

# BodyPartExamined -> region. Keys are "squashed": non-alphanumerics removed and
# uppercased, so 'L_SPINE', 'L SPINE' and 'LSPINE' are one key.
_BODY_PART_REGION: Dict[str, str] = {}


def _register(region: str, *codes: str) -> None:
    for code in codes:
        _BODY_PART_REGION[code] = region


_register(REGION_LUMBAR, "LSPINE", "LSSPINE", "LUMBAR", "LUMBARSPINE",
          "LUMBOSACRAL", "LUMBOSACRALSPINE", "SPINELUMBAR", "LUMBARSACRAL", "LLSPINE")
_register(REGION_CERVICAL, "CSPINE", "CERVICAL", "CERVICALSPINE", "CTSPINE", "NECKSPINE")
_register(REGION_THORACIC, "TSPINE", "THORACIC", "THORACICSPINE", "DORSAL", "DORSALSPINE")
_register(REGION_KNEE, "KNEE", "PATELLA")
_register(REGION_SHOULDER, "SHOULDER", "ACJOINT")
_register(REGION_BRAIN, "BRAIN", "HEAD", "SKULL", "PITUITARY", "IAC")
_register(REGION_OTHER,
          "NECK", "ORBIT", "FACE", "SINUS", "TMJ",
          "HIP", "ANKLE", "WRIST", "ELBOW", "FOOT", "HAND",
          "FEMUR", "TIBIA", "HUMERUS", "EXTREMITY", "UPPEREXTREMITY", "LOWEREXTREMITY",
          "ABDOMEN", "ABDOMENPELVIS", "PELVIS", "PROSTATE", "LIVER", "KIDNEY",
          "BREAST", "HEART", "CHEST", "THORAX", "LUNG", "SACROILIAC", "SIJOINT")


def region_for_body_part(code: str) -> Optional[str]:
    """Region for one squashed BodyPartExamined code, or None if unrecognised."""
    return _BODY_PART_REGION.get(str(code or "").strip().upper())


def known_body_part_codes() -> Tuple[str, ...]:
    return tuple(sorted(_BODY_PART_REGION))


# ---------------------------------------------------------------------------
# The protocol registry
# ---------------------------------------------------------------------------

LUMBAR_MRI = Protocol(
    id="lumbar_mri",
    name="Lumbar Spine MRI",
    modality="MR",
    regions=(REGION_LUMBAR,),
    layout=(1, 3),
    capture=True,
    analysis=LUMBAR_PATHOLOGY,
    slots=(
        ProtocolSlot(SLOT_SAG_T2, SLOT_LABELS[SLOT_SAG_T2], 1,
                     PLANE_SAGITTAL, WEIGHTING_T2, 8, 30),
        ProtocolSlot(SLOT_SAG_T1, SLOT_LABELS[SLOT_SAG_T1], 2,
                     PLANE_SAGITTAL, WEIGHTING_T1, 8, 30),
        ProtocolSlot(SLOT_AX_T2, SLOT_LABELS[SLOT_AX_T2], 3,
                     PLANE_AXIAL, WEIGHTING_T2, 9, 60),
    ),
    sessions=(
        # Sagittal sweep: the sagittal images are what is being read, so both
        # sagittal panes are captured CLEAN and the axial pane keeps its line as
        # the spatial reference.
        CaptureSession(
            name="sagittal", label="Sagittal sweep",
            primary=SLOT_SAG_T2, synced=(SLOT_SAG_T1,), reference=(SLOT_AX_T2,),
            plane=PLANE_SAGITTAL, park_reference=False,
            directory="Sagittal", file_prefix="sagittal",
            session_type="lumbar_sagittal",
        ),
        # Axial sweep: the axial image is what is being read, so it is captured
        # clean; both sagittal panes hold their mid-line slice and keep their
        # reference lines, which is what shows the level of the current axial.
        CaptureSession(
            name="axial", label="Axial sweep",
            primary=SLOT_AX_T2, synced=(), reference=(SLOT_SAG_T2, SLOT_SAG_T1),
            plane=PLANE_AXIAL, park_reference=True,
            directory="Axial", file_prefix="axial",
            session_type="lumbar_axial",
        ),
    ),
)

# Declared but not yet built. They appear in the protocol picker so the list
# reads as a roadmap rather than a dead end, and the caller reports "not
# available in this version" instead of failing part-way through a sweep.
_PLANNED = (
    Protocol("cervical_mri", "Cervical Spine MRI", "MR", (REGION_CERVICAL,)),
    Protocol("thoracic_mri", "Thoracic Spine MRI", "MR", (REGION_THORACIC,)),
    Protocol("knee_mri", "Knee MRI", "MR", (REGION_KNEE,)),
    Protocol("shoulder_mri", "Shoulder MRI", "MR", (REGION_SHOULDER,)),
    Protocol("brain_mri", "Brain MRI", "MR", (REGION_BRAIN,)),
)

PROTOCOLS: Tuple[Protocol, ...] = (LUMBAR_MRI,) + _PLANNED

_BY_REGION: Dict[str, Protocol] = {}
for _protocol in PROTOCOLS:
    for _region in _protocol.regions:
        _BY_REGION.setdefault(_region, _protocol)


def get_protocol(protocol_id: str) -> Optional[Protocol]:
    for protocol in PROTOCOLS:
        if protocol.id == protocol_id:
            return protocol
    return None


def protocol_for_region(region: str) -> Optional[Protocol]:
    return _BY_REGION.get(str(region or ""))


def implemented_protocols() -> Tuple[Protocol, ...]:
    return tuple(p for p in PROTOCOLS if p.implemented)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# Free-text region hints, used ONLY when BodyPartExamined says nothing. The
# coded field is the authority; a description is a guess someone typed.
_TEXT_REGION_HINTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (REGION_LUMBAR, ("lumbar", "lumbosacral", "l spine", "lspine", "ls spine", "lsspine")),
    (REGION_CERVICAL, ("cervical", "c spine", "cspine")),
    (REGION_THORACIC, ("thoracic", "t spine", "tspine", "dorsal")),
    (REGION_KNEE, ("knee", "patella")),
    (REGION_SHOULDER, ("shoulder", "rotator cuff")),
    (REGION_BRAIN, ("brain", "cranial", "pituitary")),
)


class ProtocolDetection:
    """What the study looks like, how sure we are, and why."""

    __slots__ = ("protocol", "region", "confidence", "reason")

    def __init__(self, protocol: Optional[Protocol], region: Optional[str],
                 confidence: str, reason: str):
        self.protocol = protocol
        self.region = region
        self.confidence = confidence
        self.reason = reason

    @property
    def certain(self) -> bool:
        """True only when the run may proceed WITHOUT asking the user.

        Requires high confidence AND a protocol that can actually be captured -
        recognising a knee MRI perfectly is still not a reason to start a sweep
        no pipeline exists for.
        """
        return (
            self.confidence == CONFIDENCE_HIGH
            and self.protocol is not None
            and self.protocol.implemented
        )

    def as_dict(self) -> Dict[str, object]:
        return {
            "protocol_id": self.protocol.id if self.protocol else None,
            "protocol_name": self.protocol.name if self.protocol else None,
            "region": self.region,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _squash(value: object) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower()).upper()


def _split_codes(values: Sequence[object]) -> List[str]:
    import re
    codes: List[str] = []
    for value in values or ():
        for part in re.split(r"[,;/\\|]+", str(value or "")):
            squashed = _squash(part)
            if squashed:
                codes.append(squashed)
    return codes


def detect_protocol(body_parts: Sequence[object] = (),
                    texts: Sequence[object] = (),
                    modality: str = "MR") -> ProtocolDetection:
    """Work out which protocol a study needs, and say how sure that is.

    High confidence => the caller proceeds automatically. Anything less => the
    caller must ask, because a wrong protocol silently loads the wrong three
    series and every screenshot after that is wrong too.
    """
    import re

    codes = _split_codes(body_parts)
    regions = [region_for_body_part(code) for code in codes]
    regions = [r for r in regions if r]

    # A coded body part is the strongest signal there is. If several are present
    # (a spine study can report two levels) any one with a capture pipeline wins,
    # so an L-spine series inside a longer spine study still routes correctly.
    for region in regions:
        protocol = protocol_for_region(region)
        if protocol is not None and protocol.implemented:
            return ProtocolDetection(
                protocol, region, CONFIDENCE_HIGH,
                f"BodyPartExamined says {'/'.join(sorted(set(codes)))}",
            )
    if regions:
        region = regions[0]
        return ProtocolDetection(
            protocol_for_region(region), region, CONFIDENCE_HIGH,
            f"BodyPartExamined says {'/'.join(sorted(set(codes)))}",
        )

    blob = re.sub(r"\s+", " ", re.sub(
        r"[^a-z0-9]+", " ", " ".join(str(t or "") for t in (texts or ())).lower()
    )).strip()

    matched = [region for region, hints in _TEXT_REGION_HINTS
               if any(hint in blob for hint in hints)]
    if len(matched) == 1:
        region = matched[0]
        return ProtocolDetection(
            protocol_for_region(region), region, CONFIDENCE_MEDIUM,
            "study/series descriptions name the region",
        )
    if len(matched) > 1:
        return ProtocolDetection(
            None, None, CONFIDENCE_LOW,
            "descriptions name more than one region (" + ", ".join(matched) + ")",
        )
    if codes:
        return ProtocolDetection(
            None, None, CONFIDENCE_LOW,
            f"BodyPartExamined ({'/'.join(sorted(set(codes)))}) is not a region Eagle Eye knows",
        )
    return ProtocolDetection(
        None, None, CONFIDENCE_NONE,
        "the study records no body part and no description names a region",
    )
