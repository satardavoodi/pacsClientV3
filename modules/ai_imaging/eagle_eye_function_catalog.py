"""Available functions exposed by the Eagle Eye launcher."""

from __future__ import annotations

from dataclasses import dataclass


FUNCTION_NATIVE_ANALYSIS = "native_analysis"
FUNCTION_LEGION_CONSULT = "legion_consult"


@dataclass(frozen=True)
class EagleEyeFunctionOption:
    """One function shown in the Eagle Eye function picker."""

    key: str
    label: str
    enabled: bool = True
    reason: str = ""


_NATIVE_LABELS = {
    "MG": "Mammography Analysis",
    "DX": "Bone Age Analysis",
    "MR": "Lumbar MRI Analysis",
}


def function_options_for_modality(modality: str) -> tuple[EagleEyeFunctionOption, ...]:
    """Return native analysis plus Legion Consult for an Eagle Eye modality."""
    normalized = str(modality or "").strip().upper()
    native_label = _NATIVE_LABELS.get(normalized, "Eagle Eye Analysis")
    legion_enabled = normalized == "MR"
    return (
        EagleEyeFunctionOption(FUNCTION_NATIVE_ANALYSIS, native_label),
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
