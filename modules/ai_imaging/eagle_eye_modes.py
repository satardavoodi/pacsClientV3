"""The single authority for "which Eagle Eye mode is this study?".

``normalize_eagle_eye_mode`` was copy-pasted into three files (the AI main
window, the imaging tab and the AI patient widget override). Three copies of a
mapping that must agree is exactly how a mode ends up half-supported, so the
mapping now lives here and those three delegate to it. Their published
behaviour for MG and DX is unchanged, byte for byte.

Import-light on purpose: no Qt, no pydicom, no VTK. It is imported at module
scope by widgets that are themselves imported during startup.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

MODE_MAMMOGRAPHY = "mammography"
MODE_BONE_AGE = "bone_age"
MODE_LUMBAR_MRI = "lumbar_mri"

KNOWN_MODES = (MODE_MAMMOGRAPHY, MODE_BONE_AGE, MODE_LUMBAR_MRI)

_ALIASES = {
    MODE_MAMMOGRAPHY: ("mg", "mammo", "mammography", "breast"),
    MODE_BONE_AGE: ("dx", "bone", "bone_age", "bone-age", "boneage"),
    MODE_LUMBAR_MRI: (
        "lumbar", "lumbar_mri", "lumbar-mri", "lumbarmri",
        "lumbar_spine", "spine_mri", "ls_spine", "lspine",
    ),
}

# Words that mean "lumbar spine" in a study/series description. Matched against
# a normalised blob, so "L-SPINE", "L SPINE" and "LSPINE" all land here.
_LUMBAR_HINTS = (
    "lumbar", "lumbosacral", "l spine", "lspine", "ls spine", "lsspine",
    "l s spine", "lumb",
)

# Words that mean the MR is of some OTHER region. A study description reading
# "MRI CERVICAL SPINE" must not open the lumbar layout just because "spine"
# appears - so an explicit non-lumbar region wins over a weak lumbar hint.
_NON_LUMBAR_HINTS = (
    "cervical", "c spine", "cspine", "thoracic", "t spine", "tspine",
    "dorsal", "brain", "head", "knee", "shoulder", "hip", "ankle", "wrist",
    "elbow", "abdomen", "pelvis", "prostate", "liver", "breast", "cardiac",
    "sacroiliac", "si joint", "foot", "hand", "orbit", "neck",
)


# ---------------------------------------------------------------------------
# BodyPartExamined — the reliable signal, handled separately from free text
# ---------------------------------------------------------------------------
# Learned the hard way (2026-08-26): a real Siemens lumbar study carried
# SeriesDescription 't2_tse_sag' / 't1_tse_sag' / 't2_tse_tra_msma', an EMPTY
# StudyDescription in the local DB and NULL series body parts. The ONLY thing
# that said "lumbar" anywhere was BodyPartExamined = 'LSPINE'. Free text alone
# is not a gate; the DICOM body-part code is.
#
# Matching is on a squashed form (non-alphanumerics removed, uppercased), so
# 'L_SPINE', 'L SPINE' and 'LSPINE' are one token.

# The body-part -> region table lives in eagle_eye_lumbar.protocols, which is
# the ONE place that knows what a DICOM body-part code means. This module only
# asks it the narrower question "is that region lumbar?", so the two can never
# disagree about, say, whether CTSPINE is cervical.

VERDICT_LUMBAR = "lumbar"
VERDICT_OTHER = "other"
VERDICT_UNKNOWN = "unknown"


def _squash(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower()).upper()


def _body_part_tokens(values: Iterable[Any]) -> list:
    """Split body-part fields into individual codes.

    The local `studies.body_part` column accumulates every series' body part as
    a comma-joined string ('HEAD, BRAIN', 'ABDOMEN, ABDOMENPELVIS'), so one
    field can carry several codes.
    """
    tokens = []
    for value in values or ():
        for part in re.split(r"[,;/\\|]+", str(value or "")):
            squashed = _squash(part)
            if squashed:
                tokens.append(squashed)
    return tokens


def body_part_verdict(values: Iterable[Any]) -> str:
    """``lumbar`` / ``other`` / ``unknown`` from BodyPartExamined codes alone.

    A lumbar code anywhere wins — a spine protocol legitimately reports both
    'LSPINE' and a neighbouring level. Only when nothing is lumbar does a
    recognised other-region code produce a rejection.
    """
    from modules.ai_imaging.eagle_eye_lumbar.protocols import (
        REGION_LUMBAR, region_for_body_part,
    )
    regions = [region_for_body_part(token) for token in _body_part_tokens(values)]
    regions = [r for r in regions if r]
    if REGION_LUMBAR in regions:
        return VERDICT_LUMBAR
    if regions:
        return VERDICT_OTHER
    return VERDICT_UNKNOWN


def lumbar_verdict(body_parts: Optional[Iterable[Any]] = None,
                   texts: Optional[Iterable[Any]] = None) -> tuple:
    """Overall verdict plus a human-readable reason, for logging and dialogs.

    Order of authority: the DICOM body-part code first (it is a coded field),
    descriptive free text only as a fallback. Returns
    ``(verdict, reason)`` where verdict is lumbar / other / unknown.
    """
    tokens = _body_part_tokens(body_parts or ())
    verdict = body_part_verdict(body_parts or ())
    if verdict == VERDICT_LUMBAR:
        return VERDICT_LUMBAR, f"BodyPartExamined says {'/'.join(sorted(set(tokens)))}"
    if verdict == VERDICT_OTHER:
        return VERDICT_OTHER, f"BodyPartExamined says {'/'.join(sorted(set(tokens)))}"

    if looks_like_lumbar(*(texts or ())):
        return VERDICT_LUMBAR, "study/series descriptions name the lumbar spine"

    blob = " ".join(_normalise(t) for t in (texts or ()) if t)
    for hint in _NON_LUMBAR_HINTS:
        if hint in blob:
            return VERDICT_OTHER, f"descriptions name another region ('{hint}')"

    return VERDICT_UNKNOWN, "no body part and no description names a region"


def _normalise(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(part) for part in value)
    text = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
    return re.sub(r"\s+", " ", text).strip()


def normalize_eagle_eye_mode(mode: Any) -> Optional[str]:
    """Canonical mode name for any accepted spelling, else None."""
    value = str(mode or "").strip().lower()
    if not value:
        return None
    for canonical, aliases in _ALIASES.items():
        if value in aliases or value == canonical:
            return canonical
    return None


def looks_like_lumbar(*texts: Any) -> bool:
    """True when the given descriptive text names the lumbar spine.

    Explicit non-lumbar regions veto: a cervical or thoracic MR is not opened
    in the lumbar layout, even though both are spine studies.
    """
    blob = " ".join(_normalise(text) for text in texts if text)
    if not blob:
        return False
    if any(hint in blob for hint in _NON_LUMBAR_HINTS) and not any(
        hint in blob for hint in ("lumbar", "lumbosacral")
    ):
        return False
    return any(hint in blob for hint in _LUMBAR_HINTS)


def resolve_eagle_eye_mode(modality: Any, texts: Optional[Iterable[Any]] = None) -> Optional[str]:
    """Pick the Eagle Eye mode for a study from its modality and descriptions.

    MG and DX keep their existing unconditional mapping. MR only resolves to the
    lumbar mode when the descriptions actually say lumbar - an unrecognised MR
    returns None and the caller keeps its previous behaviour rather than opening
    a layout built for a different body part.
    """
    value = str(modality or "").strip().upper()
    if value == "MG":
        return MODE_MAMMOGRAPHY
    if value == "DX":
        return MODE_BONE_AGE
    if value == "MR" and looks_like_lumbar(*(texts or ())):
        return MODE_LUMBAR_MRI
    return None
