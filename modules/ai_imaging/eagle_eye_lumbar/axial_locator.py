"""DICOM plane locators in spare evidence cells, never lesion annotations.

The clean diagnostic tiles are not modified. All coordinates are derived from
source geometry, not screening boxes, level names, or an assumed midline.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from modules.ai_imaging.evidence_core import DicomSlice, EvidenceError, SeriesVolume


POLICY = "dicom-axial-plane-locator-v1"


def plane_segment(
    volume: SeriesVolume, slice_index: int, axial: DicomSlice,
    crop_box: Sequence[int],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Intersect two finite image planes; return sagittal source pixel centers.

    DICOM PS3.3 C.7.6.2: columns follow the first IOP triplet with column
    spacing; rows follow the second triplet with row spacing. Image Position
    is the first pixel center, not its edge. Differing FoRs need registration,
    which this helper deliberately does not infer.
    """
    if (not volume.frame_of_reference_uid
            or volume.frame_of_reference_uid != axial.frame_of_reference_uid):
        raise EvidenceError("frame_of_reference_unverified")
    if not volume.source_geometry_verified:
        raise EvidenceError("source_geometry_unverified")
    direction = np.asarray(volume.direction, dtype=float).reshape(3, 3)
    spacing = np.asarray(volume.spacing, dtype=float)
    row, column = np.asarray(axial.orientation_lps, dtype=float).reshape(2, 3)
    geometry = np.r_[direction.ravel(), spacing, volume.origin, axial.position_lps,
                     row, column, axial.pixel_spacing]
    if (not np.isfinite(geometry).all() or np.any(spacing <= 0)
            or not np.allclose(direction.T @ direction, np.eye(3), atol=1e-3)
            or not np.allclose([row @ row, column @ column, row @ column],
                               [1, 1, 0], atol=1e-3)):
        raise EvidenceError("invalid_plane_geometry")
    if not 0 <= slice_index < volume.depth:
        raise EvidenceError("invalid_source_slice")
    left, top, right, bottom = crop_box
    if not (0 <= left < right <= volume.width and 0 <= top < bottom <= volume.height):
        raise EvidenceError("invalid_locator_crop")
    normal = np.cross(row, column)
    base = np.asarray(volume.continuous_index_to_patient((0, 0, slice_index)))
    u, v = direction[:, 0] * spacing[0], direction[:, 1] * spacing[1]
    a, b = float(normal @ u), float(normal @ v)
    c = float(normal @ (base - np.asarray(axial.position_lps)))
    if np.hypot(a / spacing[0], b / spacing[1]) < 1e-4:
        raise EvidenceError("parallel_image_planes")
    points = []
    if abs(b) > 1e-9:
        for x in (left, right - 1):
            y = -(a * x + c) / b
            if top - 1e-7 <= y <= bottom - 1 + 1e-7:
                points.append(np.array([x, np.clip(y, top, bottom - 1)]))
    if abs(a) > 1e-9:
        for y in (top, bottom - 1):
            x = -(b * y + c) / a
            if left - 1e-7 <= x <= right - 1 + 1e-7:
                points.append(np.array([np.clip(x, left, right - 1), y]))
    if len(points) < 2:
        raise EvidenceError("plane_outside_locator_crop")
    start, end = max(((p, q) for p in points for q in points),
                     key=lambda pair: np.linalg.norm(pair[1] - pair[0]))
    # Also clip to the actual axial FOV, not an infinite extension of that plane.
    axial_coordinates = []
    for point in (start, end):
        delta = base + u * point[0] + v * point[1] - np.asarray(axial.position_lps)
        axial_coordinates.append(np.array([
            delta @ row / axial.pixel_spacing[1],
            delta @ column / axial.pixel_spacing[0],
        ]))
    lo, hi = 0.0, 1.0
    for axis, bound in enumerate((axial.width - 1, axial.height - 1)):
        first = float(axial_coordinates[0][axis])
        change = float(axial_coordinates[1][axis] - first)
        if abs(change) < 1e-9:
            if not -1e-7 <= first <= bound + 1e-7:
                raise EvidenceError("plane_outside_axial_fov")
        else:
            t0, t1 = sorted((-first / change, (bound - first) / change))
            lo, hi = max(lo, t0), min(hi, t1)
    if hi <= lo or np.linalg.norm(end - start) < 1e-6:
        raise EvidenceError("plane_outside_axial_fov")
    delta = end - start
    return tuple(map(tuple, (start + lo * delta, start + hi * delta)))


def draw_locator(
    canvas: Image.Image, volume: SeriesVolume, source_slice: int,
    crop_box: Sequence[int], clean_crop: np.ndarray,
    axial_planes: Sequence[tuple[int, DicomSlice]], anchor_frame: int,
    cell_origin: tuple[int, int], tile_size: tuple[int, int],
) -> dict:
    """Fill only a spare cell; fail closed without touching diagnostic pixels."""
    audit = {"policy": POLICY, "status": "unavailable", "reason": None,
             "source_slice": source_slice, "anchor_capture_frame": anchor_frame,
             "coordinate_space": "source_pixel_centers_zero_based_xy",
             "anatomical_numbering_verified": False, "lesion_correspondence_verified": False}
    if not axial_planes:
        audit["reason"] = "axial_planes_missing"
        return audit
    if (not volume.frame_of_reference_uid or any(
            plane.frame_of_reference_uid != volume.frame_of_reference_uid
            for _, plane in axial_planes)):
        audit["reason"] = "frame_of_reference_unverified"
        return audit
    if not volume.source_geometry_verified:
        audit["reason"] = "source_geometry_unverified"
        return audit
    # Keep every selected frame in the audit; a missing intersection is not a
    # reason to fabricate or silently substitute the adjacent plane.
    segments, omitted = [], []
    for frame, plane in axial_planes[:5]:
        try:
            segment = plane_segment(volume, source_slice - 1, plane, crop_box)
        except (EvidenceError, ValueError) as exc:
            omitted.append({"capture_frame": frame,
                            "reason": str(exc) if isinstance(exc, EvidenceError)
                            else "invalid_plane_geometry"})
            continue
        segments.append({"capture_frame": frame,
                         "source_segment_xy": [list(point) for point in segment]})
    audit["omitted_planes"] = omitted
    if not segments:
        audit["reason"] = "no_visible_plane_intersections"
        return audit
    left, top, right, bottom = crop_box
    image = Image.fromarray(np.asarray(clean_crop, dtype=np.uint8))
    image.thumbnail((min(tile_size[0], image.width), min(tile_size[1], image.height)),
                    Image.Resampling.LANCZOS)
    offset = ((tile_size[0] - image.width) // 2, (tile_size[1] - image.height) // 2)
    tile = Image.new("RGB", tile_size, "black")
    tile.paste(image.convert("RGB"), offset)
    draw = ImageDraw.Draw(tile)
    for item in segments:
        coords = [((x - left + 0.5) * image.width / (right - left) - 0.5 + offset[0],
                   (y - top + 0.5) * image.height / (bottom - top) - 0.5 + offset[1])
                  for x, y in item["source_segment_xy"]]
        item["locator_segment_xy"] = [list(point) for point in coords]
        anchor = item["capture_frame"] == anchor_frame
        draw.line(coords, fill="#22d3ee" if anchor else "#eab308", width=1)
        x, y = coords[0]
        draw.text((max(3, min(x + 3, tile_size[0] - 55)),
                   max(36, min(y - 12, tile_size[1] - 18))),
                  f"AX {item['capture_frame']}", fill="#22d3ee" if anchor else "#eab308")
    draw.rectangle((1, 1, tile_size[0] - 2, tile_size[1] - 2), outline="#22d3ee")
    draw.rectangle((2, 2, tile_size[0] - 3, 33), fill="black")
    draw.text((6, 5), f"LOCATOR ONLY | T2 SAG {source_slice} | AX {anchor_frame} cyan",
              fill="#22d3ee", font=ImageFont.load_default())
    draw.text((6, 19), "Acquisition planes, NOT lesion outlines", fill="white")
    canvas.paste(tile, cell_origin)
    audit.update(status="partial" if omitted else "included", reason=None,
                 frame_of_reference_status="shared", planes=segments,
                 cell_origin_xy=list(cell_origin), tile_size=list(tile_size))
    return audit
