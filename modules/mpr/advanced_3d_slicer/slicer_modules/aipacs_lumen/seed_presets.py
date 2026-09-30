"""Workflow seed classes, independent of Qt and Slicer imports."""
ROLE_TAG = "AIPacsLumen.SeedRole"


def seed_role(segment):
    import vtk
    value = vtk.mutable("")
    return str(value) if segment.GetTag(ROLE_TAG, value) else ""

# role, name, color, enabled initially, placement guidance
PRESETS = {
    "bronchoscopy": (
        ("lumen", "Airway lumen", (0.2, 0.8, 1.0), True,
         "Paint inside the trachea and the bronchi you want to follow, on several slices. Avoid the airway wall."),
        ("parenchyma", "Lung parenchyma", (0.5, 0.85, 0.3), True,
         "Paint lung tissue outside the bronchi in both lungs, including areas near likely leaks. Do not paint inside airways."),
        ("background", "Soft tissue / background", (0.95, 0.65, 0.3), True,
         "Paint surrounding non-airway tissue, such as mediastinum and chest wall, on several slices."),
        ("external_air", "External air (optional)", (0.65, 0.5, 0.9), False,
         "Enable if the volume includes outside air that competes with the airway. Paint outside the body, not in lung or airway."),
    ),
    "vascular": (
        ("lumen", "Vessel lumen", (0.95, 0.25, 0.25), True,
         "Paint inside the target vessel on several slices along its course. Avoid wall, plaque and nearby vessels."),
        ("background", "Surrounding tissue / background", (0.95, 0.7, 0.3), True,
         "Paint non-target tissue around the vessel on several slices and near potential leaks."),
        ("other_vessels", "Other vessels (optional)", (0.3, 0.55, 0.95), False,
         "Enable when neighboring vessels must be excluded. Paint inside those vessels, not the target vessel."),
        ("bone", "Bone / calcification (optional)", (0.85, 0.85, 0.65), False,
         "Enable when visible bone or calcification competes with the lumen. Paint only structures to exclude; do not label vessel lumen."),
    ),
}


def ensure_seed_segments(segmentation, mode):
    """Idempotently add missing classes; preserve existing names, paint and colors.

    Adopt an untagged legacy target by exact name only. Never guess that an
    arbitrary first segment represents the lumen.
    """
    result, created = {}, set()
    for role, name, color, enabled, hint in PRESETS[mode]:
        identifier = None
        for index in range(segmentation.GetNumberOfSegments()):
            candidate = segmentation.GetNthSegmentID(index)
            segment = segmentation.GetSegment(candidate)
            if seed_role(segment) == mode + ":" + role:
                identifier = candidate
                break
        if identifier is None and role == "lumen":
            for index in range(segmentation.GetNumberOfSegments()):
                candidate = segmentation.GetNthSegmentID(index)
                segment = segmentation.GetSegment(candidate)
                if segment.GetName() == name and not seed_role(segment):
                    identifier = candidate
                    break
        if identifier is None:
            identifier = segmentation.AddEmptySegment("", name, color)
            created.add(role)
        segmentation.GetSegment(identifier).SetTag(ROLE_TAG, mode + ":" + role)
        result[role] = identifier
    return result, created


def lumen_segment_id(segmentation, mode):
    for index in range(segmentation.GetNumberOfSegments()):
        identifier = segmentation.GetNthSegmentID(index)
        if seed_role(segmentation.GetSegment(identifier)) == mode + ":lumen":
            return identifier
    raise ValueError("The target lumen segment is missing. Restore the seed classes first.")
