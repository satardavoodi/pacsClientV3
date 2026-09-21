"""In-memory integrity checks for the Advanced decoded-volume execution domain."""


def is_advanced_metadata(metadata):
    if not isinstance(metadata, dict):
        return False
    series = metadata.get("series") or {}
    backend = str(series.get("viewer_backend", "")).strip().lower()
    if backend:
        return backend == "vtk_simpleitk"
    return bool(metadata.get("series_geometry_index") or metadata.get("_series_geometry_index_obj"))


def advanced_payload_matches_frames(image, metadata):
    """Validate Advanced frame coverage; leave other backends' lazy semantics alone.

    Metadata can contain one record per decoded frame or one per multiframe SOP.
    No disk/DB reads, pixel copies, header inference or ordering mutations occur.
    Preview completeness is a separate admission decision by the full-cache owner.
    """
    if not is_advanced_metadata(metadata):
        return True
    try:
        frames = metadata.get('_advanced_presentation_frames')
        if frames is not None:
            instances = metadata.get('instances') or []
            if (metadata.get('spatial_geometry_available') is not False
                    or not isinstance(frames, tuple) or not frames
                    or image is not frames[0] or len(frames) != len(instances)):
                return False
            return all(
                frame.GetDimensions() == (int(inst['columns']), int(inst['rows']), 1)
                and frame.GetNumberOfScalarComponents() == (3 if inst.get('is_rgb') else 1)
                and frame.GetPointData().GetScalars() is not None
                for frame, inst in zip(frames, instances)
            )
        depth = int(image.GetDimensions()[2])
        instances = metadata.get("instances") or []
        if depth <= 0 or not instances:
            return False
        if len(instances) == depth:
            return True
        if len(instances) > depth:
            return False
        return sum(max(1, int(item.get("number_of_frames", 1) or 1))
                   for item in instances) == depth
    except (AttributeError, TypeError, ValueError, IndexError, KeyError, OverflowError):
        return False
