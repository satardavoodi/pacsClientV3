"""Explicit routes into the shared Advanced Analysis runtime."""

WORKFLOW_MODULES = {
    "vascular": "AIPacsVascular",
    "bronchoscopy": "AIPacsBronchoscopy",
}


def validate_workflow(value):
    if value is None or value == "":
        return None
    if value not in WORKFLOW_MODULES:
        raise ValueError("Unknown Advanced Analysis workflow")
    return value
