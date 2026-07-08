from dataclasses import dataclass


@dataclass(frozen=True)
class MGFieldSpec:
    name: str
    label: str
    source: str
    required: bool = False
    automatic: bool = False
    editable: bool = True


DETECTION_FIELD_SPECS = {
    "dicom_full_path": MGFieldSpec("dicom_full_path", "DICOM Path", "detection", required=True, editable=False),
    "box": MGFieldSpec("box", "Box Coordinates", "detection", required=True, automatic=True, editable=False),
    "scores": MGFieldSpec("scores", "AI Confidence", "detection", editable=False),
    "coord_space": MGFieldSpec("coord_space", "Coordinate Space", "detection", automatic=True, editable=False),
    "geometry_version": MGFieldSpec("geometry_version", "Geometry Version", "detection", automatic=True, editable=False),
    "coord_system": MGFieldSpec("coord_system", "Coordinate System", "detection", automatic=True, editable=False),
    "new_box": MGFieldSpec("new_box", "Human Added Box", "detection", required=True, automatic=True, editable=False),
    "removed": MGFieldSpec("removed", "Rejected AI Box", "detection", automatic=True, editable=False),
}

CLASSIFICATION_FIELD_SPECS = {
    "dicom_full_path": MGFieldSpec("dicom_full_path", "DICOM Path", "classification", required=True, editable=False),
    "xmin": MGFieldSpec("xmin", "X Min", "classification", required=True, automatic=True, editable=False),
    "ymin": MGFieldSpec("ymin", "Y Min", "classification", required=True, automatic=True, editable=False),
    "xmax": MGFieldSpec("xmax", "X Max", "classification", required=True, automatic=True, editable=False),
    "ymax": MGFieldSpec("ymax", "Y Max", "classification", required=True, automatic=True, editable=False),
    "labels_pred": MGFieldSpec("labels_pred", "Finding Label", "classification", required=True),
}

OPTIONAL_REVIEW_FIELD_SPECS = {
    "laterality": MGFieldSpec("laterality", "Laterality", "review"),
    "view": MGFieldSpec("view", "View", "review"),
    "lesion_type": MGFieldSpec("lesion_type", "Lesion Type", "review"),
    "location": MGFieldSpec("location", "Location", "review"),
    "quadrant": MGFieldSpec("quadrant", "Quadrant", "review"),
    "clock_position": MGFieldSpec("clock_position", "Clock Position", "review"),
    "depth": MGFieldSpec("depth", "Depth", "review"),
    "birads_category": MGFieldSpec("birads_category", "BI-RADS", "review"),
    "confidence": MGFieldSpec("confidence", "Human Confidence", "review"),
}


def infer_mg_csv_contract(detection_columns=None, classification_columns=None):
    detection_columns = set(detection_columns or [])
    classification_columns = set(classification_columns or [])

    mandatory = []
    automatic = []
    optional = []

    for name, spec in DETECTION_FIELD_SPECS.items():
        if name in detection_columns or spec.required:
            if spec.required:
                mandatory.append(spec)
            elif spec.automatic:
                automatic.append(spec)
            else:
                optional.append(spec)

    for name, spec in CLASSIFICATION_FIELD_SPECS.items():
        if name in classification_columns or (classification_columns and spec.required):
            if spec.required:
                mandatory.append(spec)
            elif spec.automatic:
                automatic.append(spec)
            else:
                optional.append(spec)

    for spec in OPTIONAL_REVIEW_FIELD_SPECS.values():
        optional.append(spec)

    return {
        "mandatory": _dedupe_specs(mandatory),
        "automatic": _dedupe_specs(automatic),
        "optional": _dedupe_specs(optional),
    }


def _dedupe_specs(specs):
    seen = set()
    result = []
    for spec in specs:
        key = (spec.source, spec.name)
        if key in seen:
            continue
        seen.add(key)
        result.append(spec)
    return result


def normalize_mg_action(action):
    value = str(action or "").strip().lower()
    if value in ("confirm", "confirmed"):
        return "confirmed"
    if value in ("reject", "rejected", "remove", "removed"):
        return "rejected"
    if value in ("correct", "corrected", "edit", "edited", "update"):
        return "corrected"
    if value in ("new", "new_finding", "human_added"):
        return "new_human_finding"
    return "pending"
