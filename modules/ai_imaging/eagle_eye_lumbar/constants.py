"""Vocabulary shared by every Eagle Eye lumbar module.

Kept in one place so the classifier, the session manifest and the capture
controller can never drift on a slot name or a direction string - the manifest
is the contract the (future) LLM stage will read.
"""

# Bumped whenever the capture layout, manifest schema or ordering rule changes.
# Written into every session.json so a later reader knows exactly which
# pipeline produced the images.
#   1.0.0  lumbar-only pipeline, pass-specific manifest keys
#   1.1.0  protocol-driven capture sessions; manifest frames are keyed by SERIES
#          ROLE ("panes") instead of by lumbar-specific field names
#   1.2.0  each frame records normalized image-viewport bounds and source PNG
#          dimensions so worker-side evidence derivatives never guess geometry
EAGLE_EYE_VERSION = "1.2.0"
# Historical name. Kept so nothing importing it breaks; new code uses
# EAGLE_EYE_VERSION, because the pipeline is no longer lumbar-only.
EAGLE_EYE_LUMBAR_VERSION = EAGLE_EYE_VERSION

# ---------------------------------------------------------------------------
# SERIES ROLES.
#
# A role is the semantic identity of a series inside a protocol - "the sagittal
# T2", not "viewport 1". Protocols map roles onto viewport positions; nothing
# downstream should ever say `if lumbar: viewport1 = ...`. These strings are the
# keys used by the classifier, the selection, the manifest and the capture
# sessions, so they are the one vocabulary that must not drift.
# ---------------------------------------------------------------------------
SLOT_SAG_T2 = "sagittal_t2"
SLOT_SAG_T1 = "sagittal_t1"
SLOT_AX_T2 = "axial_t2"

# Declared for protocols not yet built (brain being the first planned user), so
# that adding one is a configuration change rather than a vocabulary change.
SLOT_AX_T1 = "axial_t1"
SLOT_AX_FLAIR = "axial_flair"
SLOT_SAG_T1_POST = "sagittal_t1_post"
SLOT_COR_T2 = "coronal_t2"

# The LUMBAR viewport order, left to right. Generic code must use
# ``protocol.slot_keys`` (or ``selection.slot_order``) instead - this exists for
# the lumbar defaults in the layout override and for backwards compatibility.
SLOT_ORDER = (SLOT_SAG_T2, SLOT_SAG_T1, SLOT_AX_T2)

# Human labels painted on the viewport group boxes.
SLOT_LABELS = {
    SLOT_SAG_T2: "Sagittal T2",
    SLOT_SAG_T1: "Sagittal T1",
    SLOT_AX_T2: "Axial T2",
    SLOT_AX_T1: "Axial T1",
    SLOT_AX_FLAIR: "Axial FLAIR",
    SLOT_SAG_T1_POST: "Sagittal T1 +C",
    SLOT_COR_T2: "Coronal T2",
}

# ---------------------------------------------------------------------------
# Acquisition planes (from ImageOrientationPatient, never from a description).
# ---------------------------------------------------------------------------
PLANE_AXIAL = "axial"
PLANE_SAGITTAL = "sagittal"
PLANE_CORONAL = "coronal"
PLANE_OBLIQUE = "oblique"
PLANE_UNKNOWN = "unknown"

# The plane each slot requires. A candidate in the wrong plane is never a
# fallback for a slot - a coronal T2 must not silently become "Sagittal T2".
SLOT_REQUIRED_PLANE = {
    SLOT_SAG_T2: PLANE_SAGITTAL,
    SLOT_SAG_T1: PLANE_SAGITTAL,
    SLOT_AX_T2: PLANE_AXIAL,
    SLOT_AX_T1: PLANE_AXIAL,
    SLOT_AX_FLAIR: PLANE_AXIAL,
    SLOT_SAG_T1_POST: PLANE_SAGITTAL,
    SLOT_COR_T2: PLANE_CORONAL,
}

# ---------------------------------------------------------------------------
# Capture ordering - stored explicitly in every manifest (spec 14).
# ---------------------------------------------------------------------------
ORDER_RIGHT_TO_LEFT = "right_to_left"
ORDER_LEFT_TO_RIGHT = "left_to_right"
ORDER_SUPERIOR_TO_INFERIOR = "superior_to_inferior"
ORDER_INFERIOR_TO_SUPERIOR = "inferior_to_superior"
ORDER_UNKNOWN = "unknown"

# Preferred sweep direction per plane. Sagittal sweeps patient-right to
# patient-left and axial sweeps head to feet - the way a radiologist reads a
# lumbar study - but the direction that was ACTUALLY used is always recorded,
# because a series whose geometry cannot be resolved falls back to stack order.
PREFERRED_ORDER = {
    PLANE_SAGITTAL: ORDER_RIGHT_TO_LEFT,
    PLANE_AXIAL: ORDER_SUPERIOR_TO_INFERIOR,
}

# ---------------------------------------------------------------------------
# Session layout on disk.
# ---------------------------------------------------------------------------
SESSION_TYPE_SAGITTAL = "lumbar_sagittal"
SESSION_TYPE_AXIAL = "lumbar_axial"

SAGITTAL_DIR = "Sagittal"
AXIAL_DIR = "Axial"
SESSION_JSON = "session.json"
MANIFEST_JSON = "manifest.json"

SAGITTAL_PREFIX = "sagittal"
AXIAL_PREFIX = "axial"

# The LLM analysis of a captured session lives beside the captures, so a stored
# result can never be separated from the images and prompt that produced it.
LLM_REQUEST_JSON = "llm_request.json"
LLM_RESULT_TXT = "llm_result.txt"
LLM_RESULT_JSON = "llm_result.json"

# ---------------------------------------------------------------------------
# Detection confidence bands (see series_classifier).
# ---------------------------------------------------------------------------
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_NONE = "none"

# A slot resolved below this band is reported as uncertain: the pipeline still
# records the best candidate and every alternative, but the session is flagged
# so the selection can be reviewed rather than trusted silently (spec 16).
UNCERTAIN_BANDS = (CONFIDENCE_LOW, CONFIDENCE_NONE)
