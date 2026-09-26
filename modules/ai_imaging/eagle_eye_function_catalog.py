"""Available functions exposed by the Eagle Eye launcher."""

from __future__ import annotations

from dataclasses import dataclass


FUNCTION_NATIVE_ANALYSIS = "native_analysis"
FUNCTION_LEGION_CONSULT = "legion_consult"
FUNCTION_BRAIN_LESIONS = "brain_lesions"
FUNCTION_ALIGNMENT = "alignment_view"
FUNCTION_TOTAL_SPINE = "total_spine_alignment"


@dataclass(frozen=True)
class EagleEyeFunctionOption:
    """One function shown in the Eagle Eye function picker."""

    key: str
    label: str
    enabled: bool = True
    reason: str = ""


_NATIVE_LABELS = {
    "MG": "Mammography Pathology Analysis",
    "DX": "Bone Age AI",
    "MR": "Lumbar Pathology Analysis",
}


def function_options_for_modality(modality: str, mode: str | None = None) -> tuple[EagleEyeFunctionOption, ...]:
    """Return native analysis plus Legion Consult for an Eagle Eye modality."""
    normalized = str(modality or "").strip().upper()
    if mode == "brain_mri":
        return (
            EagleEyeFunctionOption(FUNCTION_NATIVE_ANALYSIS, "Whole Brain Segmentation | T1 MPRAGE"),
            EagleEyeFunctionOption(FUNCTION_BRAIN_LESIONS, "White-matter Lesions | 2D or 3D FLAIR + T1",
                                   reason="Select acquisition type in the analysis window. Requires its server model package and image review."),
        )
    native_label = _NATIVE_LABELS.get(normalized, "Eagle Eye Analysis")
    legion_enabled = normalized == "MR"
    return (
        EagleEyeFunctionOption(FUNCTION_NATIVE_ANALYSIS, native_label,
                               enabled=normalized in {"MG", "DX", "MR"},
                               reason="" if normalized in {"MG", "DX", "MR"}
                               else "No analysis is available for this image type."),
        *((EagleEyeFunctionOption(FUNCTION_ALIGNMENT, "Alignment View | Hip-Knee-Ankle",
                                  reason="Local AI landmarks, editable measurements and bilateral report."),)
          if normalized in {"DX", "CR"} else ()),
        *((EagleEyeFunctionOption(FUNCTION_TOTAL_SPINE, "Total Spine Alignment | Coronal + Lateral",
                                  reason="Coronal landmark proposals, manual sagittal measurements and reviewed reports."),)
          if normalized in {"DX", "CR"} else ()),
        EagleEyeFunctionOption(
            FUNCTION_LEGION_CONSULT,
            "Legion Consult",
            enabled=legion_enabled,
            reason=(
                ""
                if legion_enabled
                else "Legion Consult is currently available for MRI studies only."
            ),
        ),
    )
