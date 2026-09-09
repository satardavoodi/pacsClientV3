"""Eagle Eye lumbar-spine MRI capture and analysis feature package.

The package owns the complete feature lifecycle while the general imaging tab
only supplies widgets, displays status, and delegates start/result/teardown
actions to the workflow coordinator.

Package layout
--------------
``constants``          slot names, capture-order vocabulary, pipeline version.
``geometry``           pure-DICOM plane / ordering / nearest-slice math (no Qt).
``series_classifier``  scores study series into SAG-T2 / SAG-T1 / AX-T2 slots.
``series_probe``       builds classifier candidates from a loaded PatientWidget.
``session_store``      on-disk session + JSON manifests.
``capture_controller`` Qt-side, timer-driven sweep over the 3x1 Eagle Eye layout.
``evidence_bundle``    canonical V5 level-card selection and rollback policy.
``evidence_request``   bounded model-attention normalization and focus planning.
``screening_evidence`` source-grounded DICOM screening atlas construction.
``anatomy_cards``     anatomy-only mapping validation and Gate 1-to-2 cards.
``screening_attention``canonical diagnosis-free attention handoff.
``focus_evidence``     worker-side lesion-centred verification evidence.
``clinical_context``   bounded clinical-document attachment package.
``llm_runner``         off-thread bridge to the shared EchoMind/GapGPT transport.
``workflow_coordinator`` capture, analysis, result, retry, and teardown lifecycle.
``result_panel``       reusable non-modal analysis result window.

Pure protocol, geometry, grading, and storage modules remain headless-testable.
Qt dependencies stay in the capture controller, workflow coordinator, and
result panel; transport details remain behind the existing EchoMind bridge.
"""

from .constants import (
    EAGLE_EYE_LUMBAR_VERSION,
    SLOT_SAG_T2,
    SLOT_SAG_T1,
    SLOT_AX_T2,
    SLOT_ORDER,
    PLANE_AXIAL,
    PLANE_SAGITTAL,
    PLANE_CORONAL,
    PLANE_OBLIQUE,
    PLANE_UNKNOWN,
)

__all__ = [
    "EAGLE_EYE_LUMBAR_VERSION",
    "SLOT_SAG_T2",
    "SLOT_SAG_T1",
    "SLOT_AX_T2",
    "SLOT_ORDER",
    "PLANE_AXIAL",
    "PLANE_SAGITTAL",
    "PLANE_CORONAL",
    "PLANE_OBLIQUE",
    "PLANE_UNKNOWN",
]
