"""Compose compact, geometry-aligned focused-v2 evidence for verification."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from modules.ai_imaging.evidence_core import (
    DicomSlice,
    DicomSliceStack,
    EvidenceBudget,
    EvidenceError,
    SeriesVolume,
    display_slice,
    fit_grayscale,
    focus_slice_indices,
    horizontal_patient_orientation,
    horizontal_patient_orientation_for_slice,
    inspect_image_quality,
    intensity_window,
    intensity_window_slices,
    load_dicom_slice_stack,
    load_series_volume,
)

from .evidence_bundle import (
    MODE_FOCUSED_V2,
    MODE_FOCUSED_V3,
    MODE_FOCUSED_V3_PARASAGITTAL,
    MODE_FOCUSED_V4_CORRELATED,
    MODE_FOCUSED_V5_LEVEL_CARDS,
)
from .evidence_request import (
    ADDITIONAL_FINDINGS_LEVEL,
    EvidenceFocus,
    EvidencePlan,
    build_evidence_plan,
)
from .llm_package import AnalysisPackage, PackagedImage
from .series_classifier import SeriesCandidate
from .axial_locator import draw_locator, plane_segment
from .atomic_pipeline import STRUCTURE_CARD_PROFILES, structures_for_group


MANIFEST_NAME = "evidence_manifest.json"
MANIFEST_SCHEMA_VERSION = "1.3.0"
AXIAL_WINDOW_POLICY = "same-slab-backfill-v1"
TILE_SIZE = (256, 256)
HEADER_HEIGHT = 40
DEFAULT_BUDGET = EvidenceBudget()
CAPTURE_MATCH_TOLERANCE_MM = 2.0
SAME_PLANE_DOT_TOLERANCE = 0.999

# --- V3 geometry ------------------------------------------------------------
#
# V2 letterboxes the WHOLE acquired field into a 256 px tile: a 200 mm lumbar
# axial lands at 0.78 mm/px and a 300 mm sagittal at 1.17, so the 1-3 mm
# base-versus-dome difference that separates a bulge from a protrusion is one
# to three pixels. V3 changes nothing about which slices are chosen - only how
# many pixels each one is allowed to keep. Every tile is first cropped to a
# physical box around the spine, so the same 256 or 384 px is spent on ~100 mm
# instead of ~200-300 mm.
#
# The boxes are deliberately generous. Centring is geometric, not segmented
# (see _axial_roi), so a box that is merely close still contains the canal;
# the crop actually used is recorded per tile in the manifest.
FOCUS_TILE_SIZE_V3 = (384, 384)
LEVEL_CARD_SAGITTAL_TILE_SIZE = (320, 224)
LEVEL_CARD_AXIAL_TILE_SIZE = FOCUS_TILE_SIZE_V3
# The sagittal overview keeps the whole lumbar column, so its crop is tall and
# narrow; a square tile would let the height set the scale and give the crop
# back almost nothing. This is the one non-square tile in the pipeline.
SAGITTAL_OVERVIEW_TILE_V3 = (288, 512)
AXIAL_ROI_MM = (96.0, 104.0)          # (left-right, anterior-posterior)
AXIAL_ROI_POSTERIOR_BIAS = 0.06       # fraction of image height, toward P
SAGITTAL_FOCUS_ROI_MM = (100.0, 100.0)   # (anterior-posterior, superior-inferior)
SAGITTAL_LEVEL_CARD_ROI_MM = (100.0, 60.0)
SAGITTAL_OVERVIEW_ROI_MM = (150.0, 260.0)
MIN_ROI_PIXELS = 48
# Sampling targets for a bounded experiment, not anatomical zone thresholds.
PARASAGITTAL_TARGET_OFFSETS_MM = (-15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0)
PARASAGITTAL_POLICY = "bilateral-lps-supplement-v1"
LEVEL_CARD_MAX_FOCUSES = 8
LEVEL_CARD_TEMPLATE_VERSION = "2.0.0"
LEVEL_CARD_MANIFEST_VERSION = "3.1.0"
LEVEL_CARD_SAGITTAL_SAMPLING_POLICY = "anatomical-midline-spaced-v1"
LEVEL_CARD_SAGITTAL_SOURCE_OFFSETS = (-4, -2, 0, 2, 4)
LEVEL_CARD_MIDLINE_TOLERANCE_SLICES = 2
LEVEL_CARD_SEQUENCE_BORDERS = {
    "sagittal_t2": "cyan",
    "sagittal_t1": "amber",
    "axial_t2": "violet",
    "diagnostic_meaning": False,
}


class FocusedEvidenceError(RuntimeError):
    """Focused evidence failed safely and verification must use layout evidence."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code or "focused_v2_failed")


def _candidate_from_source(role: str, source: Dict[str, Any]) -> SeriesCandidate:
    allowed = {
        key: source.get(key)
        for key in (
            "index",
            "series_uid",
            "series_number",
            "series_description",
            "protocol_name",
            "modality",
            "plane",
            "slice_count",
            "echo_time",
            "repetition_time",
            "series_path",
        )
    }
    allowed["index"] = int(allowed.get("index") or 0)
    path = Path(str(allowed.get("series_path") or ""))
    if not path.is_dir():
        raise FocusedEvidenceError(
            "source_series_missing",
            f"The local DICOM source for {role} is unavailable.",
        )
    if not str(allowed.get("series_uid") or "").strip():
        raise FocusedEvidenceError(
            "source_identity_missing",
            f"The local DICOM source for {role} has no series identity.",
        )
    allowed["series_path"] = str(path)
    return SeriesCandidate.from_dict(allowed)


def _load_required_sources(
    package: AnalysisPackage,
) -> tuple[Dict[str, SeriesVolume], DicomSliceStack]:
    required = ("sagittal_t2", "axial_t2")
    missing = [role for role in required if role not in package.source_series]
    if missing:
        raise FocusedEvidenceError(
            "source_provenance_unavailable",
            "The session predates local DICOM evidence provenance.",
        )
    volumes: Dict[str, SeriesVolume] = {}
    try:
        volumes["sagittal_t2"] = load_series_volume(
            _candidate_from_source("sagittal_t2", package.source_series["sagittal_t2"])
        )
        axial_stack = load_dicom_slice_stack(
            _candidate_from_source("axial_t2", package.source_series["axial_t2"])
        )
    except FocusedEvidenceError:
        raise
    except EvidenceError as exc:
        raise FocusedEvidenceError("dicom_decode_failed", str(exc)) from exc
    source = package.source_series.get("sagittal_t1")
    if source:
        try:
            volumes["sagittal_t1"] = load_series_volume(
                _candidate_from_source("sagittal_t1", source)
            )
        except (FocusedEvidenceError, EvidenceError):
            # Sagittal T1 enriches marrow/foraminal context but is not required
            # to preserve the focused T2 verification path.
            pass
    return volumes, axial_stack


def _sample_indices(depth: int, limit: int) -> tuple[int, ...]:
    if depth <= 0 or limit <= 0:
        return ()
    count = min(int(depth), int(limit))
    return tuple(dict.fromkeys(int(round(value)) for value in np.linspace(0, depth - 1, count)))


def _assert_source_signal(arrays: Iterable[np.ndarray]) -> None:
    samples = []
    for array in arrays:
        flat = np.asarray(array, dtype=np.uint8).reshape(-1)
        stride = max(1, int(np.ceil(flat.size / 100_000)))
        samples.append(flat[::stride])
    if not samples:
        raise FocusedEvidenceError("empty_render", "No source pixels were selected.")
    combined = np.concatenate(samples)
    p01, p99 = np.percentile(combined, (1.0, 99.0))
    if np.unique(combined).size < 8 or float(p99) - float(p01) < 4.0:
        raise FocusedEvidenceError(
            "uniform_render",
            "The selected DICOM render is empty or effectively uniform.",
        )


def _display(volume: SeriesVolume, index: int, window: tuple[float, float]) -> np.ndarray:
    return display_slice(volume.pixels[int(index)], window[0], window[1], volume.inverted)


def _display_dicom_slice(
    image_slice: DicomSlice, window: tuple[float, float]
) -> np.ndarray:
    return display_slice(
        image_slice.pixels,
        window[0],
        window[1],
        image_slice.inverted,
    )


@dataclass(frozen=True)
class _RenderProfile:
    """How much of each slice survives into the model-facing sheet."""

    mode: str
    focus_tile: tuple[int, int]
    axial_overview_tile: tuple[int, int]
    sagittal_overview_tile: tuple[int, int]
    crop_to_spine: bool

    @classmethod
    def for_mode(cls, mode: str) -> "_RenderProfile":
        normalized = str(mode or "").strip().lower()
        if normalized in {
            MODE_FOCUSED_V3,
            MODE_FOCUSED_V4_CORRELATED,
            MODE_FOCUSED_V5_LEVEL_CARDS,
        }:
            return cls(
                normalized, FOCUS_TILE_SIZE_V3, TILE_SIZE,
                SAGITTAL_OVERVIEW_TILE_V3, True,
            )
        return cls(MODE_FOCUSED_V2, TILE_SIZE, TILE_SIZE, TILE_SIZE, False)


def _clamped_box(
    width: int, height: int, center_x: float, center_y: float,
    box_width: float, box_height: float,
) -> tuple[int, int, int, int]:
    """A pixel box of the requested size, centred where asked, inside the image."""
    # The image itself is the last word: a minimum wider than the slice would
    # push the box outside it.
    box_w = min(int(width), max(MIN_ROI_PIXELS, min(int(round(box_width)), int(width))))
    box_h = min(int(height), max(MIN_ROI_PIXELS, min(int(round(box_height)), int(height))))
    left = max(0, min(int(round(center_x - box_w / 2.0)), int(width) - box_w))
    top = max(0, min(int(round(center_y - box_h / 2.0)), int(height) - box_h))
    return left, top, left + box_w, top + box_h


def _axial_roi(
    array: np.ndarray, image_slice: DicomSlice
) -> tuple[np.ndarray, tuple[int, int, int, int], tuple[float, float]]:
    """Crop one axial slice to a physical box around the spinal canal.

    The centre is geometric, not segmented. Lumbar axials are prescribed about
    the spine, so the canal sits near the mid-column and slightly posterior to
    the mid-row; the direction cosines say which way posterior is, so the bias
    is applied in patient space rather than by assuming an array orientation.
    The box is deliberately generous - a merely-close centre still contains the
    disc, the canal, both lateral recesses and the facets - and the crop that
    was actually used is recorded per tile in the manifest, so a bad centre is
    visible rather than silent.
    """
    height, width = array.shape[:2]
    row_mm, column_mm = (float(value) for value in image_slice.pixel_spacing)
    column_axis = np.asarray(image_slice.orientation_lps[3:], dtype=np.float64)
    posterior_sign = 1.0 if float(column_axis[1]) >= 0.0 else -1.0
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0 + posterior_sign * AXIAL_ROI_POSTERIOR_BIAS * height
    box = _clamped_box(
        width, height, center_x, center_y,
        AXIAL_ROI_MM[0] / column_mm, AXIAL_ROI_MM[1] / row_mm,
    )
    return array[box[1]:box[3], box[0]:box[2]], box, (column_mm, row_mm)


def _sagittal_roi(
    array: np.ndarray, volume: SeriesVolume,
    continuous_index: Optional[Sequence[float]], roi_mm: tuple[float, float],
) -> tuple[np.ndarray, tuple[int, int, int, int], tuple[float, float]]:
    """Crop one sagittal slice to a physical box, centred on a projected point."""
    height, width = array.shape[:2]
    x_mm = float(volume.spacing[0])
    y_mm = float(volume.spacing[1])
    if continuous_index is not None:
        center_x = float(continuous_index[0])
        center_y = float(continuous_index[1])
    else:
        center_x = (width - 1) / 2.0
        center_y = (height - 1) / 2.0
    box = _clamped_box(
        width, height, center_x, center_y, roi_mm[0] / x_mm, roi_mm[1] / y_mm
    )
    return array[box[1]:box[3], box[0]:box[2]], box, (x_mm, y_mm)


def _effective_mm_per_pixel(
    box: tuple[int, int, int, int], spacing_xy: tuple[float, float],
    tile: tuple[int, int],
) -> tuple[float, float]:
    """What one tile pixel is worth once the crop is letterboxed into the tile.

    ``fit_grayscale`` scales down but never up, so a crop smaller than the tile
    keeps its native sampling and a larger one is reduced by the fitted ratio.
    """
    box_w = max(1, box[2] - box[0])
    box_h = max(1, box[3] - box[1])
    scale = min(1.0, float(tile[0]) / box_w, float(tile[1]) / box_h)
    return (
        round(spacing_xy[0] / scale, 4),
        round(spacing_xy[1] / scale, 4),
    )


def _axial_tile(
    item: "_CapturedAxialSlice",
    window: tuple[float, float],
    profile: "_RenderProfile",
    tile: tuple[int, int],
    label: str,
    sampling: Optional[Dict[str, Any]],
    bucket: str,
) -> tuple[np.ndarray, str]:
    """One axial tile, cropped to the spine when the profile asks for it."""
    array = _display_dicom_slice(item.source, window)
    if not profile.crop_to_spine:
        return (array, label)
    cropped, box, spacing = _axial_roi(array, item.source)
    if sampling is not None:
        sampling.setdefault(bucket, []).append({
            "capture_frame": item.capture_frame,
            "crop_box": list(box),
            "mm_per_pixel": list(_effective_mm_per_pixel(box, spacing, tile)),
        })
    return (cropped, label)


@dataclass(frozen=True)
class _CapturedAxialSlice:
    capture_frame: int
    capture_position_lps: tuple[float, float, float]
    source: DicomSlice


def _capture_position(item: PackagedImage) -> tuple[float, float, float]:
    pane = ((item.capture or {}).get("panes") or {}).get("axial_t2") or {}
    position = pane.get("position")
    try:
        point = tuple(float(value) for value in position[:3])
    except (TypeError, ValueError):
        point = ()
    if len(point) != 3 or not all(np.isfinite(value) for value in point):
        raise FocusedEvidenceError(
            "focus_geometry_unavailable",
            "An axial capture frame has no usable DICOM position.",
        )
    return point


def _captured_axial_sequence(
    package: AnalysisPackage, stack: DicomSliceStack
) -> tuple[_CapturedAxialSlice, ...]:
    captures = sorted(
        (item for item in package.images if item.session == "axial"),
        key=lambda item: int(item.index),
    )
    if not captures:
        raise FocusedEvidenceError(
            "focus_geometry_unavailable",
            "The verification package contains no axial capture frames.",
        )
    capture_frames = [int(item.index) for item in captures]
    if capture_frames != list(range(1, len(capture_frames) + 1)):
        raise FocusedEvidenceError(
            "capture_frame_identity_invalid",
            "The axial capture frame sequence is not contiguous and one-based.",
        )

    available = list(stack.slices)
    mapped = []
    seen_frames = set()
    for capture in captures:
        frame = int(capture.index)
        if frame <= 0 or frame in seen_frames:
            raise FocusedEvidenceError(
                "capture_frame_identity_invalid",
                "The axial capture frame numbering is invalid.",
            )
        point = np.asarray(_capture_position(capture), dtype=np.float64)
        candidates = [
            (
                float(
                    np.linalg.norm(
                        point - np.asarray(item.position_lps, dtype=np.float64)
                    )
                ),
                ordinal,
                item,
            )
            for ordinal, item in enumerate(available)
        ]
        if not candidates:
            raise FocusedEvidenceError(
                "capture_source_identity_mismatch",
                "The captured axial stack has more frames than the source series.",
            )
        distance, source_index, source = min(candidates, key=lambda pair: pair[0])
        if distance > CAPTURE_MATCH_TOLERANCE_MM:
            raise FocusedEvidenceError(
                "capture_source_geometry_mismatch",
                "An axial capture frame cannot be matched to its source DICOM slice.",
            )
        available.pop(source_index)
        seen_frames.add(frame)
        mapped.append(
            _CapturedAxialSlice(
                capture_frame=frame,
                capture_position_lps=tuple(float(value) for value in point),
                source=source,
            )
        )
    return tuple(mapped)


def _same_acquisition_plane(first: DicomSlice, second: DicomSlice) -> bool:
    first_row = np.asarray(first.orientation_lps[:3], dtype=np.float64)
    first_column = np.asarray(first.orientation_lps[3:], dtype=np.float64)
    second_row = np.asarray(second.orientation_lps[:3], dtype=np.float64)
    second_column = np.asarray(second.orientation_lps[3:], dtype=np.float64)
    first_row /= np.linalg.norm(first_row)
    first_column /= np.linalg.norm(first_column)
    second_row /= np.linalg.norm(second_row)
    second_column /= np.linalg.norm(second_column)
    return (
        float(np.dot(first_row, second_row)) >= SAME_PLANE_DOT_TOLERANCE
        and float(np.dot(first_column, second_column)) >= SAME_PLANE_DOT_TOLERANCE
    )


def _same_slab_neighbors(
    sequence: Sequence[_CapturedAxialSlice], center_index: int, padding: int = 2,
    *, selection_metadata: Optional[Dict[str, Any]] = None,
) -> tuple[_CapturedAxialSlice, ...]:
    """Fill a bounded axial window without crossing the anchor's slab."""
    if not sequence:
        return ()
    gaps = [
        float(
            np.linalg.norm(
                np.asarray(sequence[index].capture_position_lps)
                - np.asarray(sequence[index - 1].capture_position_lps)
            )
        )
        for index in range(1, len(sequence))
    ]
    typical_gap = float(np.median(gaps)) if gaps else float("inf")
    maximum_gap = typical_gap * 1.5

    first = int(center_index)
    last = int(center_index)
    while first > 0:
        gap = float(
            np.linalg.norm(
                np.asarray(sequence[first].capture_position_lps)
                - np.asarray(sequence[first - 1].capture_position_lps)
            )
        )
        if gap > maximum_gap or not _same_acquisition_plane(
            sequence[first].source, sequence[first - 1].source
        ):
            break
        first -= 1
    while last + 1 < len(sequence):
        gap = float(
            np.linalg.norm(
                np.asarray(sequence[last + 1].capture_position_lps)
                - np.asarray(sequence[last].capture_position_lps)
            )
        )
        if gap > maximum_gap or not _same_acquisition_plane(
            sequence[last].source, sequence[last + 1].source
        ):
            break
        last += 1

    slab = sequence[first : last + 1]
    local_center = int(center_index) - first
    padding = max(int(padding), 0)
    requested_count = 2 * padding + 1
    count = min(len(slab), requested_count)
    # Shift only the window when an edge clips it. The original anchor still
    # determines sagittal projection; no neighboring acquisition slab is used.
    start = min(max(local_center - padding, 0), len(slab) - count)
    selected = tuple(slab[start : start + count])
    if selection_metadata is not None:
        clipped_count = min(len(slab), local_center + padding + 1) - max(
            0, local_center - padding
        )
        selection_metadata.update({
            "policy": AXIAL_WINDOW_POLICY,
            "anchor_capture_frame": sequence[center_index].capture_frame,
            "available_slab_depth": len(slab),
            "slab_capture_frame_range": [slab[0].capture_frame, slab[-1].capture_frame],
            "requested_slice_count": requested_count,
            "expected_slice_count": count,
            "selected_slice_count": len(selected),
            "boundary_adjusted": len(selected) > clipped_count,
        })
    return selected


def _draw_sheet(
    rows: Sequence[
        tuple[str, Sequence[tuple[np.ndarray, str]], Optional[tuple[str, str]]]
    ],
    title: str,
    tile_size: tuple[int, int] = TILE_SIZE,
    prominent_labels: bool = False,
) -> Image.Image:
    columns = max((len(tiles) for _label, tiles, _orientation in rows), default=1)
    row_height = tile_size[1] + 24
    canvas = Image.new(
        "RGB",
        (columns * tile_size[0], HEADER_HEIGHT + len(rows) * row_height),
        "black",
    )
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=18 if prominent_labels else 10)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((8, 12), title, fill="white", font=font)
    for row_number, (row_label, tiles, orientation) in enumerate(rows):
        top = HEADER_HEIGHT + row_number * row_height
        has_tile_footers = any(len(tile) >= 3 and bool(tile[2]) for tile in tiles)
        for column, tile_record in enumerate(tiles):
            array, label = tile_record[:2]
            footer = tile_record[2] if len(tile_record) >= 3 else ""
            edge_markers = tile_record[3] if len(tile_record) >= 4 else ()
            left = column * tile_size[0]
            tile = fit_grayscale(array, tile_size)
            canvas.paste(tile, (left, top))
            draw.rectangle(
                (left + 1, top + 1, left + tile_size[0] - 2, top + tile_size[1] - 2),
                outline="#475569",
                width=1,
            )
            draw.text((left + 6, top + 6), label, fill="white", font=font)
            if orientation is not None:
                left_label, right_label = orientation
                middle = top + tile_size[1] // 2
                draw.text((left + 7, middle), left_label, fill="#fbbf24", font=font)
                draw.text(
                    (left + tile_size[0] - 16, middle),
                    right_label,
                    fill="#fbbf24",
                    font=font,
                )
            if edge_markers:
                scale = min(tile_size[0] / max(array.shape[1], 1),
                            tile_size[1] / max(array.shape[0], 1))
                content_width = array.shape[1] * scale
                content_height = array.shape[0] * scale
                offset_x = left + (tile_size[0] - content_width) / 2
                offset_y = top + (tile_size[1] - content_height) / 2
                for x_fraction, y_fraction in edge_markers:
                    x = offset_x + x_fraction * content_width
                    y = offset_y + y_fraction * content_height
                    dx = 10 if x_fraction <= 0.5 else -10
                    dy = 10 if y_fraction <= 0.5 else -10
                    draw.line((x, y, x + dx, y + dy), fill="#22d3ee", width=2)
            if footer:
                draw.text(
                    (left + 6, top + tile_size[1] + 5),
                    footer,
                    fill="#fbbf24",
                    font=font,
                )
        if not has_tile_footers:
            draw.text((6, top + tile_size[1] + 6), row_label, fill="#cbd5e1", font=font)
    return canvas


def _draw_structure_card_sheet(
    sagittal_groups: Sequence[tuple[str, Sequence[tuple[str, tuple]], Optional[tuple[str, str]]]],
    axial_tiles: Sequence[tuple],
    title: str,
    axial_orientation: Optional[tuple[str, str]],
) -> Image.Image:
    """Render only the planes required for one anatomical decision."""
    if not sagittal_groups or not axial_tiles:
        raise FocusedEvidenceError(
            "structure_card_layout_incomplete",
            "A structure card requires sagittal evidence and at least one axial tile.",
        )
    row_count = max(len(items) for _label, items, _orientation in sagittal_groups)
    if row_count not in {1, 2}:
        raise FocusedEvidenceError(
            "structure_card_layout_incomplete",
            "A structure card supports one or two matched sagittal sequences.",
        )

    sagittal_width, sagittal_height = LEVEL_CARD_SAGITTAL_TILE_SIZE
    axial_width, axial_height = LEVEL_CARD_AXIAL_TILE_SIZE
    header_height = 56
    group_header_height = 32
    footer_height = 24
    row_gap = 4
    section_gap = 14
    axial_header_height = 32
    sagittal_bottom = (
        header_height + group_header_height
        + row_count * (sagittal_height + footer_height)
        + (row_count - 1) * row_gap
    )
    axial_top = sagittal_bottom + section_gap + axial_header_height
    height = axial_top + axial_height + footer_height + 8
    width = max(
        len(sagittal_groups) * sagittal_width,
        len(axial_tiles) * axial_width,
        720,
    )
    canvas = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.load_default(size=18)
        label_font = ImageFont.load_default(size=16)
        metadata_font = ImageFont.load_default(size=12)
    except TypeError:
        title_font = ImageFont.load_default()
        label_font = title_font
        metadata_font = title_font
    border_colors = {
        "sagittal_t2": "#22d3ee",
        "sagittal_t1": "#f59e0b",
        "axial_t2": "#a78bfa",
    }

    def draw_tile(
        tile_record: tuple,
        left: int,
        top: int,
        tile_size: tuple[int, int],
        orientation: Optional[tuple[str, str]],
        border_color: str,
    ) -> None:
        array, label = tile_record[:2]
        footer = tile_record[2] if len(tile_record) >= 3 else ""
        edge_markers = tile_record[3] if len(tile_record) >= 4 else ()
        tile = fit_grayscale(array, tile_size)
        canvas.paste(tile, (left, top))
        draw.rectangle(
            (left + 2, top + 2, left + tile_size[0] - 3, top + tile_size[1] - 3),
            outline=border_color,
            width=3,
        )
        draw.text((left + 7, top + 7), label, fill="white", font=label_font)
        if orientation is not None:
            left_label, right_label = orientation
            middle = top + tile_size[1] // 2
            draw.text((left + 8, middle), left_label, fill="#f8fafc", font=label_font)
            draw.text(
                (left + tile_size[0] - 20, middle), right_label,
                fill="#f8fafc", font=label_font,
            )
        if edge_markers:
            scale = min(
                tile_size[0] / max(array.shape[1], 1),
                tile_size[1] / max(array.shape[0], 1),
            )
            content_width = array.shape[1] * scale
            content_height = array.shape[0] * scale
            offset_x = left + (tile_size[0] - content_width) / 2
            offset_y = top + (tile_size[1] - content_height) / 2
            for x_fraction, y_fraction in edge_markers:
                x = offset_x + x_fraction * content_width
                y = offset_y + y_fraction * content_height
                dx = 10 if x_fraction <= 0.5 else -10
                dy = 10 if y_fraction <= 0.5 else -10
                draw.line((x, y, x + dx, y + dy), fill="#22d3ee", width=2)
        if footer:
            draw.text(
                (left + 7, top + tile_size[1] + 5), footer,
                fill="#fbbf24", font=metadata_font,
            )

    draw.text((8, 7), title, fill="white", font=title_font)
    draw.text(
        (8, 33),
        "BORDERS: T2 CYAN | T1 AMBER | AX T2 VIOLET - SEQUENCE IDENTITY ONLY",
        fill="#cbd5e1",
        font=metadata_font,
    )
    sagittal_left = (width - len(sagittal_groups) * sagittal_width) // 2
    for column, (group_label, items, orientation) in enumerate(sagittal_groups):
        left = sagittal_left + column * sagittal_width
        draw.rectangle(
            (left + 2, header_height + 2, left + sagittal_width - 3, sagittal_bottom - 2),
            outline="#64748b",
            width=2,
        )
        draw.text(
            (left + 7, header_height + 8), group_label,
            fill="#e2e8f0", font=metadata_font,
        )
        for row, (role, tile_record) in enumerate(items):
            top = header_height + group_header_height + row * (
                sagittal_height + footer_height + row_gap
            )
            draw_tile(
                tile_record, left, top, LEVEL_CARD_SAGITTAL_TILE_SIZE,
                orientation, border_colors[role],
            )

    divider_y = sagittal_bottom + section_gap // 2
    draw.line((0, divider_y, width, divider_y), fill="#94a3b8", width=3)
    draw.text(
        (8, sagittal_bottom + section_gap + 8),
        "AXIAL T2 STRUCTURE SEQUENCE | READ LEFT TO RIGHT",
        fill="#e2e8f0", font=metadata_font,
    )
    axial_left = (width - len(axial_tiles) * axial_width) // 2
    for column, tile_record in enumerate(axial_tiles):
        draw_tile(
            tile_record, axial_left + column * axial_width, axial_top,
            LEVEL_CARD_AXIAL_TILE_SIZE, axial_orientation,
            border_colors["axial_t2"],
        )
    return canvas


def _atomic_image(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{uuid4().hex}.tmp.png")
    try:
        image.save(temporary, "PNG", optimize=True)
        os.replace(temporary, path)
    finally:
        image.close()
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, document: Dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _crop_around_point(
    array: np.ndarray,
    continuous_index: tuple[float, float, float],
) -> np.ndarray:
    height, width = array.shape[:2]
    center_x = min(max(float(continuous_index[0]), 0.0), width - 1.0)
    center_y = min(max(float(continuous_index[1]), 0.0), height - 1.0)
    crop_width = min(width, max(64, int(round(width * 0.72))))
    crop_height = min(height, max(96, int(round(height * 0.58))))
    left = min(max(int(round(center_x - crop_width / 2)), 0), width - crop_width)
    top = min(max(int(round(center_y - crop_height / 2)), 0), height - crop_height)
    return array[top : top + crop_height, left : left + crop_width]


def _overview_images(
    volumes: Dict[str, SeriesVolume],
    axial_sequence: Sequence[_CapturedAxialSlice],
    windows: Dict[str, tuple[float, float]],
    output_dir: Path,
    profile: _RenderProfile,
    sampling: Optional[Dict[str, Any]] = None,
) -> list[tuple[Path, str, str]]:
    sagittal_t2 = volumes["sagittal_t2"]
    sagittal_t1 = volumes.get("sagittal_t1")
    sagittal_tile_size = profile.sagittal_overview_tile
    axial_tile_size = profile.axial_overview_tile

    def _sagittal_tile(volume: SeriesVolume, index: int, role: str, label: str):
        array = _display(volume, index, windows[role])
        if not profile.crop_to_spine:
            return (array, label)
        cropped, box, spacing = _sagittal_roi(
            array, volume, None, SAGITTAL_OVERVIEW_ROI_MM
        )
        if sampling is not None:
            sampling.setdefault("sagittal_overview", []).append({
                "role": role, "slice": index + 1, "crop_box": list(box),
                "mm_per_pixel": list(
                    _effective_mm_per_pixel(box, spacing, sagittal_tile_size)
                ),
            })
        return (cropped, label)

    sagittal_indices = focus_slice_indices(sagittal_t2.depth // 2, sagittal_t2.depth, 2)
    sagittal_rows = []
    t2_tiles = [
        _sagittal_tile(
            sagittal_t2, index, "sagittal_t2", f"T2 {index + 1}/{sagittal_t2.depth}"
        )
        for index in sagittal_indices
    ]
    sagittal_rows.append(
        (
            "Five contiguous near-midline sagittal T2 slices",
            t2_tiles,
            horizontal_patient_orientation(sagittal_t2),
        )
    )
    if sagittal_t1 is not None:
        t1_indices = focus_slice_indices(sagittal_t1.depth // 2, sagittal_t1.depth, 2)
        t1_tiles = [
            _sagittal_tile(
                sagittal_t1, index, "sagittal_t1",
                f"T1 {index + 1}/{sagittal_t1.depth}",
            )
            for index in t1_indices
        ]
        sagittal_rows.append(
            (
                "Five contiguous near-midline sagittal T1 slices",
                t1_tiles,
                horizontal_patient_orientation(sagittal_t1),
            )
        )
    _assert_source_signal(
        array
        for _label, tiles, _orientation in sagittal_rows
        for array, _name in tiles
    )
    label = profile.mode.replace("focused-v", "V").upper()
    sagittal_path = output_dir / "sagittal_overview.png"
    _atomic_image(
        _draw_sheet(
            sagittal_rows, f"FOCUSED {label} | sagittal overview", sagittal_tile_size
        ),
        sagittal_path,
    )

    axial_indices = _sample_indices(len(axial_sequence), 25)
    sampled_axial = [axial_sequence[index] for index in axial_indices]
    axial_total = len(axial_sequence)
    axial_tiles = [
        _axial_tile(item, windows["axial_t2"], profile, axial_tile_size,
                    f"AX frame {item.capture_frame}/{axial_total}",
                    sampling, "axial_overview")
        for item in sampled_axial
    ]
    _assert_source_signal(array for array, _name in axial_tiles)
    axial_rows = [
        (
            "Superior-to-inferior original axial capture frames",
            axial_tiles[start : start + 5],
            horizontal_patient_orientation_for_slice(
                sampled_axial[start].source
            ),
        )
        for start in range(0, len(axial_tiles), 5)
    ]
    axial_path = output_dir / "axial_overview.png"
    _atomic_image(
        _draw_sheet(
            axial_rows, f"FOCUSED {label} | axial complete-stack overview",
            axial_tile_size,
        ),
        axial_path,
    )
    return [
        (
            sagittal_path,
            f"Focused {label} sagittal overview: five contiguous near-midline T2 "
            "slices and, when available, matched near-midline T1 context.",
            "sagittal-overview",
        ),
        (
            axial_path,
            f"Focused {label} axial overview: capture frames "
            f"{axial_sequence[0].capture_frame}-{axial_sequence[-1].capture_frame}; "
            f"{len(axial_indices)} superior-to-inferior ordered samples labeled "
            "with the original axial capture frame numbers.",
            "axial-overview",
        ),
    ]


_CARD_SAGITTAL_SLOTS = (
    ("right_foraminal_plane", "RIGHT FORAMINAL SAMPLE"),
    ("right_paracentral_plane", "RIGHT PARACENTRAL SAMPLE"),
    ("midline_plane", "MIDLINE SAMPLE"),
    ("left_paracentral_plane", "LEFT PARACENTRAL SAMPLE"),
    ("left_foraminal_plane", "LEFT FORAMINAL SAMPLE"),
)
_CARD_AXIAL_SLOTS = (
    ("disc_level_plane", "DISC-LEVEL PLANE"),
    ("max_abnormality_plane", "MAX-ABNORMALITY PLANE"),
    ("caudal_extent_plane", "CAUDAL-EXTENT PLANE"),
)


def _focus_center_index(
    axial_sequence: Sequence[_CapturedAxialSlice],
    matching_indices: Sequence[int],
    patient_point: Optional[Sequence[float]],
) -> int:
    if patient_point is None:
        return matching_indices[len(matching_indices) // 2]
    point = np.asarray(patient_point, dtype=np.float64)

    def plane_distance(index: int) -> float:
        image_slice = axial_sequence[index].source
        row = np.asarray(image_slice.orientation_lps[:3], dtype=np.float64)
        column = np.asarray(image_slice.orientation_lps[3:], dtype=np.float64)
        normal = np.cross(row, column)
        magnitude = np.linalg.norm(normal)
        if magnitude == 0.0:
            return float("inf")
        normal /= magnitude
        return abs(float(np.dot(point - np.asarray(image_slice.position_lps), normal)))

    return min(matching_indices, key=plane_distance)


def _fallback_sagittal_indices(
    volume: SeriesVolume,
    patient_point: Sequence[float],
    *,
    midline_index: int | None = None,
) -> tuple[int, int, int, int, int]:
    """Choose spaced foraminal-to-foraminal planes around stack midline.

    The patient point supplies the craniocaudal crop anchor, but its lateral
    coordinate may be a lesion location and must not redefine anatomical
    midline. A bounded Gemini midline proposal may refine the stack centre.
    """
    del patient_point
    if volume.depth < len(LEVEL_CARD_SAGITTAL_SOURCE_OFFSETS) * 2 - 1:
        raise FocusedEvidenceError(
            "level_card_sagittal_coverage_incomplete",
            "Nine source planes are required to preserve one intervening slice "
            "between midline, paracentral and foraminal samples.",
        )

    acquisition_center = int(round((volume.depth - 1) / 2.0))
    center = acquisition_center
    if (
        type(midline_index) is int
        and 0 <= midline_index < volume.depth
        and abs(midline_index - acquisition_center)
        <= LEVEL_CARD_MIDLINE_TOLERANCE_SLICES
    ):
        center = midline_index
    minimum_center = -LEVEL_CARD_SAGITTAL_SOURCE_OFFSETS[0]
    maximum_center = volume.depth - 1 - LEVEL_CARD_SAGITTAL_SOURCE_OFFSETS[-1]
    center = min(max(center, minimum_center), maximum_center)
    available = [
        center + offset for offset in LEVEL_CARD_SAGITTAL_SOURCE_OFFSETS
    ]

    center_xy = ((volume.width - 1) / 2.0, (volume.height - 1) / 2.0)
    patient_x = {
        index: float(volume.continuous_index_to_patient((*center_xy, index))[0])
        for index in available
    }
    return tuple(sorted(available, key=patient_x.__getitem__))


def _validated_sagittal_proposal_indices(
    volume: SeriesVolume,
    requested: Dict[str, Any],
    role: str,
) -> tuple[int, int, int, int, int] | None:
    """Accept anatomy-selected planes only when their spacing is credible."""
    proposals = [
        requested.get(f"{role}.{suffix}") for suffix, _label in _CARD_SAGITTAL_SLOTS
    ]
    if any(item is None for item in proposals):
        return None
    indices = tuple(item.source_slice - 1 for item in proposals)
    if (
        any(index < 0 or index >= volume.depth for index in indices)
        or len(set(indices)) != len(indices)
    ):
        return None
    steps = [right - left for left, right in zip(indices, indices[1:])]
    if not (all(step > 0 for step in steps) or all(step < 0 for step in steps)):
        return None
    distances = [abs(step) for step in steps]
    if not (
        1 <= distances[0] <= 3
        and 2 <= distances[1] <= 3
        and 2 <= distances[2] <= 3
        and 1 <= distances[3] <= 3
    ):
        return None
    acquisition_center = int(round((volume.depth - 1) / 2.0))
    if (
        abs(indices[2] - acquisition_center)
        > LEVEL_CARD_MIDLINE_TOLERANCE_SLICES
    ):
        return None

    center_xy = ((volume.width - 1) / 2.0, (volume.height - 1) / 2.0)
    patient_x = [
        float(volume.continuous_index_to_patient((*center_xy, index))[0])
        for index in indices
    ]
    if max(patient_x) - min(patient_x) > 0.1 and not all(
        left + 0.1 < right for left, right in zip(patient_x, patient_x[1:])
    ):
        return None
    return indices


def _score_footer(score: int | None, reference: str = "") -> str:
    if score is None:
        score_text = "ABN EVIDENCE NR"
    else:
        score_text = f"ABN EVIDENCE {score}/3 {'*' * score}"
    return f"{score_text} | {reference}" if reference else score_text


def _structure_metadata(focus: EvidenceFocus) -> list[dict]:
    return [
        {
            "attention_id": item.attention_id,
            "structure": item.structure,
            "assessment": item.assessment,
            "vertebra": item.vertebra,
            "endplate_surface": item.endplate_surface,
            "confidence": item.confidence,
            "abnormality_magnitude": item.visual_salience,
            "slice_persistence": item.slice_persistence,
        }
        for item in focus.structure_attention
    ]


def _structure_checklist(
    focus: EvidenceFocus, structure_group: str = "",
) -> dict[str, str]:
    raised = {item.structure for item in focus.structure_attention}
    scoped = list(structures_for_group(structure_group) or tuple(sorted(raised)))
    return {
        structure: (
            "abnormal_screening_attention"
            if structure in raised else "not_raised_by_screening"
        )
        for structure in scoped
    }


def _required_companion_assessments(structure_group: str) -> list[dict[str, str]]:
    """Atomic cards do not add diagnostic companion tasks to screening rows."""
    del structure_group
    return []


def _public_card_slots(slots: Sequence[dict]) -> list[dict]:
    """Remove local geometric coordinates from the compact model handoff."""
    result = []
    for slot in slots:
        locator = slot.get("reference_locator")
        locator = locator if isinstance(locator, dict) else {}
        result.append({
            "slot": slot.get("slot"),
            "role": slot.get("role"),
            "source_slice": slot.get("source_slice"),
            "capture_frame": slot.get("capture_frame"),
            "selection": slot.get("selection"),
            "abnormality_conspicuity": slot.get("abnormality_conspicuity"),
            "attention_ids": list(slot.get("attention_ids") or ()),
            "geometry_group_id": slot.get("geometry_group_id") or None,
            "parent_group_id": slot.get("parent_group_id") or None,
            "parent_group_members": list(slot.get("parent_group_members") or ()),
            "reference_locator": {
                "status": locator.get("status", "unavailable"),
                "reference_axial_frame": locator.get("reference_axial_frame"),
                "diagnostic_interior_line_drawn": bool(
                    locator.get("diagnostic_interior_line_drawn", False)
                ),
            },
        })
    return result


def _diagnostic_group_integrity(
    slots: Sequence[dict], *, require_contract: bool = False,
) -> dict[str, Any]:
    """Validate focused selections as subsets of immutable parent groups."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    missing_contract = False
    for slot in slots:
        role = str(slot.get("role") or "")
        geometry_group_id = str(slot.get("geometry_group_id") or "")
        parent_group_id = str(slot.get("parent_group_id") or geometry_group_id)
        original = tuple(int(value) for value in slot.get("parent_group_members") or ())
        if not geometry_group_id:
            if require_contract:
                raise FocusedEvidenceError(
                    "geometry_group_integrity_error",
                    "A diagnostic slot is missing its authoritative geometry-group identity.",
                )
            missing_contract = True
        elif parent_group_id != geometry_group_id:
            raise FocusedEvidenceError(
                "geometry_group_integrity_error",
                "A diagnostic slot changed its parent geometry-group identity.",
            )
        member = (
            slot.get("capture_frame") if role == "axial_t2"
            else slot.get("source_slice")
        )
        if type(member) is not int or member < 1:
            raise FocusedEvidenceError(
                "geometry_group_integrity_error",
                "A diagnostic slot has no valid parent-group member identity.",
            )
        if not original:
            missing_contract = True
            original = (member,)
        if member not in original:
            raise FocusedEvidenceError(
                "geometry_group_integrity_error",
                f"Selected member {member} is outside immutable group {parent_group_id}.",
            )
        key = (parent_group_id or f"legacy-unavailable:{role}:{member}", role)
        record = grouped.setdefault(key, {
            "group_id": parent_group_id or None,
            "series_role": role,
            "member_kind": (
                "capture_frame" if role == "axial_t2" else "source_slice"
            ),
            "original_members": list(original),
            "selected_members": [],
        })
        if record["original_members"] != list(original):
            raise FocusedEvidenceError(
                "geometry_group_integrity_error",
                f"Conflicting parent membership was supplied for {parent_group_id}.",
            )
        if member not in record["selected_members"]:
            record["selected_members"].append(member)
    rows = []
    for record in grouped.values():
        record["selection_kind"] = (
            "complete_group"
            if record["selected_members"] == record["original_members"]
            else "focused_subset"
        )
        record["status"] = "intact"
        rows.append(record)
    return {
        "version": "1.0.0",
        "status": "legacy_unavailable" if missing_contract else "validated",
        "groups": rows,
    }


def _group_contract_rows(group_integrity: Optional[Dict[str, Any]]) -> list[dict]:
    if not isinstance(group_integrity, dict):
        return []
    rows = group_integrity.get("groups")
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _group_contract_for_member(
    rows: Sequence[dict], role: str, member: int,
) -> Optional[dict]:
    matches = [
        row for row in rows
        if str(row.get("series_role") or "") == role
        and member in row.get("original_members", ())
    ]
    if len(matches) > 1:
        raise FocusedEvidenceError(
            "geometry_group_integrity_error",
            f"Member {member} belongs to multiple immutable {role} groups.",
        )
    return matches[0] if matches else None


def _axial_contract_for_level(
    rows: Sequence[dict], level: str,
) -> Optional[dict]:
    matches = [
        row for row in rows
        if str(row.get("series_role") or "") == "axial_t2"
        and str(row.get("mapped_level") or "") == level
    ]
    if len(matches) > 1:
        raise FocusedEvidenceError(
            "geometry_group_integrity_error",
            f"Multiple immutable axial groups are mapped to {level}.",
        )
    return matches[0] if matches else None


def _sagittal_contract_indices(
    rows: Sequence[dict], role: str, depth: int,
) -> Optional[tuple[int, int, int, int, int]]:
    by_anatomy = {
        str(row.get("anatomical_role") or ""): [
            int(value) for value in row.get("original_members") or ()
        ]
        for row in rows
        if str(row.get("series_role") or "") == role
    }
    right = by_anatomy.get("right_lateral", [])
    central = by_anatomy.get("central", [])
    left = by_anatomy.get("left_lateral", [])
    if not right or len(central) < 3 or not left:
        return None
    selected = (
        right[len(right) // 2],
        central[0],
        central[len(central) // 2],
        central[-1],
        left[len(left) // 2],
    )
    indices = tuple(value - 1 for value in selected)
    if len(set(indices)) != 5 or any(index < 0 or index >= depth for index in indices):
        raise FocusedEvidenceError(
            "geometry_group_integrity_error",
            f"Immutable {role} groups cannot supply five distinct anatomy planes.",
        )
    return indices


def _edge_locator(
    volume: SeriesVolume,
    source_index: int,
    crop_box: Sequence[int],
    axial: _CapturedAxialSlice,
) -> tuple[tuple[tuple[float, float], ...], dict]:
    """Return edge-only reference ticks; diagnostic interior pixels stay clean."""
    audit = {
        "policy": "dicom-edge-ticks-v1",
        "status": "unavailable",
        "reference_axial_frame": axial.capture_frame,
        "source_slice": source_index + 1,
    }
    try:
        segment = plane_segment(volume, source_index, axial.source, crop_box)
    except (EvidenceError, ValueError) as exc:
        audit["reason"] = str(exc)
        return (), audit
    left, top, right, bottom = crop_box
    width = max(right - left, 1)
    height = max(bottom - top, 1)
    markers = tuple(
        (
            min(max((x - left) / width, 0.0), 1.0),
            min(max((y - top) / height, 0.0), 1.0),
        )
        for x, y in segment
    )
    audit.update(
        status="included",
        reason=None,
        marker_coordinate_space="crop_fraction_xy",
        markers=[list(point) for point in markers],
        diagnostic_interior_line_drawn=False,
    )
    return markers, audit


def _distinct_axial_fallback(
    ordered_axial: Sequence[_CapturedAxialSlice],
    anchor_item: _CapturedAxialSlice,
    keyed: Sequence[_CapturedAxialSlice],
) -> tuple[_CapturedAxialSlice, _CapturedAxialSlice, _CapturedAxialSlice]:
    """Return three distinct same-slab context planes whenever depth permits."""
    if len(ordered_axial) < 3:
        padded = list(ordered_axial)
        while len(padded) < 3:
            padded.append(padded[-1])
        return tuple(padded[:3])
    abnormal = keyed[0] if keyed else anchor_item
    abnormal_position = ordered_axial.index(abnormal)
    start = min(max(abnormal_position - 1, 0), len(ordered_axial) - 3)
    context = list(ordered_axial[start:start + 3])
    # Keep the visible order cranial-to-caudal. With no complete Gemini slot
    # contract these are context samples, not fabricated role verification.
    return context[0], context[1], context[2]


def _level_card_image(
    volumes: Dict[str, SeriesVolume],
    axial_sequence: Sequence[_CapturedAxialSlice],
    windows: Dict[str, tuple[float, float]],
    focus: EvidenceFocus,
    frame_range: tuple[int, int],
    output_dir: Path,
    profile: _RenderProfile,
    group_integrity: Optional[Dict[str, Any]] = None,
) -> tuple[Path, str, dict]:
    """Render one bounded anatomy-specific card from geometry-validated sources."""
    structure_group = (
        focus.card_kind.partition(":")[2]
        if focus.card_kind.startswith("structure:") else "other"
    )
    card_profile = STRUCTURE_CARD_PROFILES.get(
        structure_group, STRUCTURE_CARD_PROFILES["other"]
    )
    first_frame, last_frame = frame_range
    matching_indices = [
        index for index, item in enumerate(axial_sequence)
        if first_frame <= item.capture_frame <= last_frame
    ]
    if not matching_indices:
        raise FocusedEvidenceError(
            "focus_geometry_unavailable",
            "The requested level card has no matching axial capture frame.",
        )
    center_index = _focus_center_index(
        axial_sequence, matching_indices, focus.geometry_anchor_lps
    )
    center = axial_sequence[center_index]
    patient_point = focus.geometry_anchor_lps or center.source.center_lps
    requested = {slot.slot: slot for slot in focus.card_slots}
    group_contract_rows = _group_contract_rows(group_integrity)
    sagittal_tile_size = LEVEL_CARD_SAGITTAL_TILE_SIZE
    axial_tile_size = LEVEL_CARD_AXIAL_TILE_SIZE
    sampling: Dict[str, Any] = {"sagittal": [], "axial": []}
    card_slots = []
    sagittal_t2_indices: list[int] = []

    def sagittal_row(role: str):
        volume = volumes.get(role)
        if volume is None:
            raise FocusedEvidenceError(
                "level_card_sequence_unavailable",
                f"The fixed level card requires {role}.",
            )
        accepted_proposals = (
            _validated_sagittal_proposal_indices(volume, requested, role)
            if role == "sagittal_t2" else None
        )
        midline_proposal = requested.get(f"{role}.midline_plane")
        proposed_midline_index = (
            midline_proposal.source_slice - 1
            if midline_proposal is not None else None
        )
        fallback = (
            _sagittal_contract_indices(group_contract_rows, role, volume.depth)
            or _fallback_sagittal_indices(
                volume,
                patient_point,
                midline_index=proposed_midline_index,
            )
        )
        projection = volume.patient_to_continuous_index(patient_point)
        tiles = []
        for position, (suffix, _visible_label) in enumerate(_CARD_SAGITTAL_SLOTS):
            slot_name = f"{role}.{suffix}"
            proposal = requested.get(slot_name)
            proposed_index = proposal.source_slice - 1 if proposal is not None else -1
            if role == "sagittal_t2" and accepted_proposals is not None:
                source_index = accepted_proposals[position]
                selection = "gemini_proposal_spacing_confirmed"
            elif role == "sagittal_t1" and len(sagittal_t2_indices) == 5:
                t2_volume = volumes["sagittal_t2"]
                t2_projection = t2_volume.patient_to_continuous_index(patient_point)
                paired_point = t2_volume.continuous_index_to_patient((
                    float(t2_projection[0]),
                    float(t2_projection[1]),
                    sagittal_t2_indices[position],
                ))
                paired_projection = volume.patient_to_continuous_index(paired_point)
                source_index = min(
                    max(int(round(paired_projection[2])), 0), volume.depth - 1
                )
                selection = (
                    "gemini_proposal_geometry_confirmed"
                    if proposed_index == source_index
                    else "local_geometry_t1_t2_sync"
                )
            else:
                source_index = fallback[position]
                selection = (
                    "local_spaced_from_gemini_midline"
                    if proposed_midline_index == fallback[2]
                    else "local_anatomical_midline_spacing_fallback"
                )
            if role == "sagittal_t2":
                sagittal_t2_indices.append(source_index)
            parent_contract = _group_contract_for_member(
                group_contract_rows, role, source_index + 1
            )
            parent_group_id = (
                str(parent_contract.get("group_id") or "")
                if parent_contract is not None
                else proposal.parent_group_id if proposal is not None
                else ""
            )
            parent_group_members = (
                list(parent_contract.get("original_members") or ())
                if parent_contract is not None
                else list(proposal.parent_group_members) if proposal is not None
                else []
            )
            proposed_group_id = (
                proposal.geometry_group_id if proposal is not None else ""
            )
            if proposed_group_id and parent_group_id and proposed_group_id != parent_group_id:
                raise FocusedEvidenceError(
                    "geometry_group_integrity_error",
                    f"{slot_name} member {source_index + 1} moved from "
                    f"{parent_group_id} to {proposed_group_id}.",
                )
            array = _display(volume, source_index, windows[role])
            crop, box, spacing = _sagittal_roi(
                array, volume, projection, SAGITTAL_LEVEL_CARD_ROI_MM
            )
            markers, locator = _edge_locator(
                volume, source_index, box, reference_axial
            )
            sampling["sagittal"].append({
                "slot": slot_name,
                "role": role,
                "source_slice": source_index + 1,
                "crop_box": list(box),
                "mm_per_pixel": list(
                    _effective_mm_per_pixel(box, spacing, sagittal_tile_size)
                ),
                "selection": selection,
                "geometry_group_id": (
                    parent_group_id or proposed_group_id or None
                ),
            })
            score = (
                proposal.abnormality_conspicuity
                if proposal is not None and proposed_index == source_index else None
            )
            attention_ids = (
                list(proposal.attention_ids)
                if proposal is not None and proposed_index == source_index else []
            )
            card_slots.append({
                "slot": slot_name,
                "role": role,
                "source_slice": source_index + 1,
                "capture_frame": None,
                "selection": selection,
                "abnormality_conspicuity": score,
                "attention_ids": attention_ids,
                "geometry_group_id": (
                    parent_group_id or proposed_group_id
                ),
                "parent_group_id": parent_group_id or proposed_group_id,
                "parent_group_members": parent_group_members,
                "reference_locator": locator,
            })
            sequence = "T2" if role == "sagittal_t2" else "T1"
            tiles.append((
                crop,
                (
                    f"{sequence} | {parent_group_id or proposed_group_id} | "
                    f"VOL {source_index + 1}/{volume.depth}"
                    if parent_group_id or proposed_group_id
                    else f"{sequence} | VOL {source_index + 1}/{volume.depth}"
                ),
                _score_footer(score, f"REF AX {reference_axial.capture_frame}"),
                markers,
            ))
        return tiles

    axial_by_frame = {
        axial_sequence[index].capture_frame: axial_sequence[index]
        for index in matching_indices
    }
    ordered_axial = [axial_sequence[index] for index in matching_indices]
    anchor_item = axial_sequence[center_index]
    keyed = [
        axial_by_frame[frame]
        for frame in focus.key_axial_frames
        if frame in axial_by_frame
    ]
    axial_fallback = _distinct_axial_fallback(ordered_axial, anchor_item, keyed)
    proposed_axials = []
    for suffix, _visible_label in _CARD_AXIAL_SLOTS:
        proposal = requested.get(f"axial_t2.{suffix}")
        proposed_axials.append(
            axial_by_frame.get(proposal.capture_frame)
            if proposal is not None and proposal.capture_frame is not None else None
        )
    use_proposed_axials = (
        all(item is not None for item in proposed_axials)
        and len({item.capture_frame for item in proposed_axials}) == 3
    )
    axial_tiles = []
    axial_group_id = next(
        (
            item.geometry_group_id
            for item in requested.values()
            if item.role == "axial_t2" and item.geometry_group_id
        ),
        "",
    )
    axial_contract = _axial_contract_for_level(group_contract_rows, focus.level)
    if axial_contract is not None:
        contract_group_id = str(axial_contract.get("group_id") or "")
        contract_members = [
            int(value) for value in axial_contract.get("original_members") or ()
        ]
        if contract_members != list(range(first_frame, last_frame + 1)):
            raise FocusedEvidenceError(
                "geometry_group_integrity_error",
                f"{focus.level} parent group does not match its authoritative frame range.",
            )
        if axial_group_id and axial_group_id != contract_group_id:
            raise FocusedEvidenceError(
                "geometry_group_integrity_error",
                f"{focus.level} diagnostic slots changed axial parent group.",
            )
        axial_group_id = contract_group_id
    axial_parent_group_id = next(
        (
            item.parent_group_id
            for item in requested.values()
            if item.role == "axial_t2" and item.parent_group_id
        ),
        str(axial_contract.get("group_id") or "") if axial_contract else axial_group_id,
    )
    axial_parent_members = next(
        (
            list(item.parent_group_members)
            for item in requested.values()
            if item.role == "axial_t2" and item.parent_group_members
        ),
        (
            list(axial_contract.get("original_members") or ())
            if axial_contract else list(range(first_frame, last_frame + 1))
        ),
    )
    for position, (suffix, visible_label) in enumerate(_CARD_AXIAL_SLOTS):
        slot_name = f"axial_t2.{suffix}"
        proposal = requested.get(slot_name)
        if use_proposed_axials:
            selected = proposed_axials[position]
            selection = "gemini_proposal_same_slab_confirmed"
            score = proposal.abnormality_conspicuity
            attention_ids = list(proposal.attention_ids)
        else:
            selected = axial_fallback[position]
            selection = "local_same_slab_context_fallback"
            score = None
            attention_ids = []
        axial_tiles.append(_axial_tile(
            selected,
            windows["axial_t2"],
            profile,
            axial_tile_size,
            (
                f"AX T2 | {axial_group_id} | {visible_label} | "
                f"frame {selected.capture_frame}/{len(axial_sequence)}"
                if axial_group_id
                else f"AX T2 | {visible_label} | frame {selected.capture_frame}/{len(axial_sequence)}"
            ),
            sampling,
            "axial",
        ) + (_score_footer(score), ()))
        sampling["axial"][-1]["slot"] = slot_name
        sampling["axial"][-1]["selection"] = selection
        sampling["axial"][-1]["geometry_group_id"] = axial_group_id or None
        card_slots.append({
            "slot": slot_name,
            "role": "axial_t2",
            "source_slice": selected.source.source_ordinal,
            "capture_frame": selected.capture_frame,
            "selection": selection,
            "abnormality_conspicuity": score,
            "attention_ids": attention_ids,
            "geometry_group_id": axial_group_id,
            "parent_group_id": axial_parent_group_id,
            "parent_group_members": axial_parent_members,
            "reference_locator": {
                "policy": "dicom-edge-ticks-v1",
                "status": "orientation_only",
                "diagnostic_interior_line_drawn": False,
            },
        })

    reference_axial = (
        proposed_axials[0] if use_proposed_axials else axial_fallback[0]
    )

    sagittal_tiles_by_role = {
        role: sagittal_row(role) for role in card_profile.sagittal_sequences
    }
    # The caption and manifest follow the intended comparison order: complete
    # each same-plane T2/T1 pair before moving to the next patient-space plane.
    slot_records = {item["slot"]: item for item in card_slots}
    ordered_slot_names = [
        *(
            name
            for suffix in card_profile.sagittal_planes
            for name in (
                f"{role}.{suffix}" for role in card_profile.sagittal_sequences
            )
        ),
        *(f"axial_t2.{suffix}" for suffix in card_profile.axial_planes),
    ]
    card_slots = [slot_records[name] for name in ordered_slot_names]
    allowed_slot_names = set(ordered_slot_names)
    sampling["sagittal"] = [
        row for row in sampling["sagittal"] if row.get("slot") in allowed_slot_names
    ]
    sampling["axial"] = [
        row for row in sampling["axial"] if row.get("slot") in allowed_slot_names
    ]
    _assert_source_signal(
        [
            *(
                sagittal_tiles_by_role[role][
                    next(
                        index for index, (candidate, _label) in enumerate(_CARD_SAGITTAL_SLOTS)
                        if candidate == suffix
                    )
                ][0]
                for suffix in card_profile.sagittal_planes
                for role in card_profile.sagittal_sequences
            ),
            *(
                axial_tiles[
                    next(
                        index for index, (candidate, _label) in enumerate(_CARD_AXIAL_SLOTS)
                        if candidate == suffix
                    )
                ][0]
                for suffix in card_profile.axial_planes
            ),
        ]
    )
    attention_label = ", ".join(focus.attention_ids) or "no-attention-id"
    path = output_dir / f"{focus.focus_id}_{focus.level.replace('-', '_')}.png"
    title = (
        f"ATOMIC {structure_group.upper()} CARD | {focus.focus_id} | "
        f"SUBJECT {focus.level}"
    )
    sagittal_labels = dict(_CARD_SAGITTAL_SLOTS)
    sagittal_groups = []
    for suffix in card_profile.sagittal_planes:
        index = next(
            index for index, (candidate, _label) in enumerate(_CARD_SAGITTAL_SLOTS)
            if candidate == suffix
        )
        items = [
            (role, sagittal_tiles_by_role[role][index])
            for role in card_profile.sagittal_sequences
        ]
        orientation = horizontal_patient_orientation(
            volumes[card_profile.sagittal_sequences[0]]
        )
        sagittal_groups.append((sagittal_labels[suffix].upper(), items, orientation))
    selected_axial_tiles = [
        axial_tiles[
            next(
                index for index, (candidate, _label) in enumerate(_CARD_AXIAL_SLOTS)
                if candidate == suffix
            )
        ]
        for suffix in card_profile.axial_planes
    ]
    _atomic_image(
        _draw_structure_card_sheet(
            sagittal_groups,
            selected_axial_tiles,
            title,
            horizontal_patient_orientation_for_slice(center.source),
        ),
        path,
    )
    axial_frames = list(dict.fromkeys(
        item["capture_frame"] for item in card_slots if item["role"] == "axial_t2"
    ))
    visual_groups = [
        *(
            {
                "group_id": f"sagittal-pair-{suffix.removesuffix('_plane').replace('_', '-')}",
                "column": column,
                "patient_plane": suffix,
                "same_patient_plane": True,
                "reading_order": "top_to_bottom",
                "slots": [
                    f"{role}.{suffix}" for role in card_profile.sagittal_sequences
                ],
            }
            for column, suffix in enumerate(card_profile.sagittal_planes, start=1)
        ),
        {
            "group_id": "axial-level-sequence",
            "column": None,
            "patient_plane": "level_bound_axial_slab",
            "same_patient_plane": False,
            "reading_order": "left_to_right",
            "slots": [f"axial_t2.{suffix}" for suffix in card_profile.axial_planes],
        },
    ]
    group_integrity = _diagnostic_group_integrity(
        card_slots, require_contract=bool(group_contract_rows),
    )
    card_metadata = {
        "schema_version": "1.0.0",
        "card_id": focus.focus_id,
        "card_kind": "lumbar_structure",
        "template_id": card_profile.template_id,
        "structure_group": structure_group,
        "subject_level": focus.level,
        "attention_ids": list(focus.attention_ids),
        "structures": _structure_metadata(focus),
        "structure_checklist": _structure_checklist(focus, structure_group),
        "slots": _public_card_slots(card_slots),
        "geometry_group_ids": {
            "sagittal": list(dict.fromkeys(
                item["geometry_group_id"]
                for item in card_slots
                if str(item.get("role") or "").startswith("sagittal_")
                and item.get("geometry_group_id")
            )),
            "axial": list(dict.fromkeys(
                item["geometry_group_id"]
                for item in card_slots
                if item.get("role") == "axial_t2" and item.get("geometry_group_id")
            )),
        },
        "group_integrity": group_integrity,
        "layout": {
            "kind": "atomic-structure-card-v1",
            "sagittal_sampling_policy": LEVEL_CARD_SAGITTAL_SAMPLING_POLICY,
            "visual_reading_order": ordered_slot_names,
            "visual_groups": visual_groups,
            "tile_sizes": {
                "sagittal": list(sagittal_tile_size),
                "axial": list(axial_tile_size),
            },
            "sequence_border_legend": LEVEL_CARD_SEQUENCE_BORDERS,
        },
        "tile_score_name": "abnormality_conspicuity",
        "tile_score_scale": {"0": "not_visible", "1": "subtle", "2": "definite", "3": "marked"},
        "tile_scores_are_diagnostic_severity": False,
    }
    caption = (
        f"ATOMIC DIAGNOSTIC CARD: {structure_group}; {focus.focus_id}; attention IDs "
        f"{attention_label}; SUBJECT LEVEL {focus.level}; source slab AX frames "
        f"{first_frame}-{last_frame}. Only the printed {structure_group} question is "
        "under review. Read each shown sagittal patient-space plane with its matched "
        "sequence partner when present, then read the selected axial sequence left to right. "
        "VOL is the source-volume index and is not a DICOM InstanceNumber. "
        "Colored borders encode sequence identity only and never diagnosis "
        "or severity. The sagittal column labels describe sampling planes, not "
        "the side or diagnosis of a finding. Axial central/subarticular/foraminal/"
        "extraforaminal zones are evaluated within each axial tile; discal/pedicular/"
        "infrapedicular position is a separate craniocaudal classification. "
        "Tile ABN EVIDENCE scores are Gemini conspicuity routing hints, not disease "
        "severity or a diagnosis. The immediately preceding model text block carries "
        "the authoritative CARD_METADATA_JSON payload for this image."
    )
    return path, caption, {
        "focus_id": focus.focus_id,
        "level": focus.level,
        "family": focus.family,
        "confidence": focus.confidence,
        "visual_salience": focus.visual_salience,
        "within_study_priority": focus.within_study_priority,
        "slice_persistence": focus.slice_persistence,
        "attention_sources": list(focus.sources),
        "attention_ids": list(focus.attention_ids),
        "correspondence_status": focus.correspondence_status or "legacy_unverified",
        "anchor_source": (
            "screening_geometry" if focus.geometry_anchor_lps is not None
            else "axial_slice_geometric_center"
        ),
        "axial_horizontal_orientation": list(
            horizontal_patient_orientation_for_slice(center.source) or ()
        ),
        "screening_frame_range": list(frame_range),
        "axial_window": {
            "policy": "fixed-card-slot-v1",
            "anchor_capture_frame": anchor_item.capture_frame,
        },
        "axial_capture_frames": axial_frames,
        "axial_source_ordinals": [
            item["source_slice"] for item in card_slots if item["role"] == "axial_t2"
        ],
        "sagittal_t2_source_slices": [
            item["source_slice"] for item in card_slots if item["role"] == "sagittal_t2"
        ],
        "sagittal_t1_source_slices": [
            item["source_slice"] for item in card_slots if item["role"] == "sagittal_t1"
        ],
        "card_kind": "atomic_structure_card",
        "structure_group": structure_group,
        "card_template_version": LEVEL_CARD_TEMPLATE_VERSION,
        "sagittal_sampling_policy": LEVEL_CARD_SAGITTAL_SAMPLING_POLICY,
        "card_slots": card_slots,
        "card_metadata": card_metadata,
        "group_integrity": group_integrity,
        "layout_kind": "atomic-structure-card-v1",
        "visual_reading_order": ordered_slot_names,
        "visual_groups": visual_groups,
        "sequence_border_legend": LEVEL_CARD_SEQUENCE_BORDERS,
        "tile_size": list(axial_tile_size),
        "tile_sizes": {
            "sagittal": list(sagittal_tile_size),
            "axial": list(axial_tile_size),
        },
        "sampling": sampling,
    }


def _additional_findings_card_image(
    volumes: Dict[str, SeriesVolume],
    axial_sequence: Sequence[_CapturedAxialSlice],
    windows: Dict[str, tuple[float, float]],
    focus: EvidenceFocus,
    output_dir: Path,
    profile: _RenderProfile,
) -> tuple[Path, str, dict]:
    """Render one bounded card for abnormal foci outside named disc intervals."""
    tile_size = profile.focus_tile
    axial_by_frame = {item.capture_frame: item for item in axial_sequence}
    slots_by_role = {
        role: [slot for slot in focus.card_slots if slot.role == role][:3]
        for role in ("sagittal_t2", "sagittal_t1", "axial_t2")
    }
    rendered_slots = []
    rows = []
    for role, row_label in (
        ("sagittal_t2", "SAGITTAL T2 ADDITIONAL FINDINGS"),
        ("sagittal_t1", "SAGITTAL T1 ADDITIONAL FINDINGS"),
        ("axial_t2", "AXIAL T2 ADDITIONAL FINDINGS"),
    ):
        tiles = []
        for slot in slots_by_role[role]:
            if role == "axial_t2":
                item = axial_by_frame.get(slot.capture_frame)
                if item is None:
                    continue
                tile_record = _axial_tile(
                    item, windows["axial_t2"], profile, tile_size,
                    f"AX T2 | {slot.attention_ids[0] if slot.attention_ids else slot.slot} | "
                    f"frame {item.capture_frame}/{len(axial_sequence)}",
                    None, "additional",
                )
                source_slice = item.source.source_ordinal
                capture_frame = item.capture_frame
                orientation = horizontal_patient_orientation_for_slice(item.source)
            else:
                volume = volumes.get(role)
                if volume is None or not 1 <= slot.source_slice <= volume.depth:
                    continue
                source_index = slot.source_slice - 1
                array = _display(volume, source_index, windows[role])
                projection = (
                    volume.patient_to_continuous_index(focus.geometry_anchor_lps)
                    if focus.geometry_anchor_lps is not None else None
                )
                crop, _box, _spacing = _sagittal_roi(
                    array, volume, projection, SAGITTAL_OVERVIEW_ROI_MM
                )
                sequence = "T2" if role == "sagittal_t2" else "T1"
                tile_record = (
                    crop,
                    f"{sequence} SAG | "
                    f"{slot.attention_ids[0] if slot.attention_ids else slot.slot} | "
                    f"slice {slot.source_slice}/{volume.depth}",
                )
                source_slice = slot.source_slice
                capture_frame = None
                orientation = horizontal_patient_orientation(volume)
            footer = _score_footer(slot.abnormality_conspicuity)
            tiles.append(tile_record + (footer, ()))
            rendered_slots.append({
                "slot": slot.slot,
                "role": role,
                "source_slice": source_slice,
                "capture_frame": capture_frame,
                "selection": slot.selection,
                "abnormality_conspicuity": slot.abnormality_conspicuity,
                "attention_ids": list(slot.attention_ids),
                "reference_locator": {
                    "policy": "dicom-edge-ticks-v1",
                    "status": "not_available_for_additional_card",
                    "diagnostic_interior_line_drawn": False,
                },
            })
        if tiles:
            rows.append((row_label, tiles, orientation))
    if not rows:
        raise FocusedEvidenceError(
            "additional_card_source_unavailable",
            "The additional finding has no renderable source location.",
        )
    attention_label = ", ".join(focus.attention_ids) or "no-attention-id"
    title = f"ADDITIONAL FINDINGS CARD | {focus.focus_id} | {attention_label}"
    path = output_dir / f"{focus.focus_id}_additional_findings.png"
    card_metadata = {
        "schema_version": "1.0.0",
        "card_id": focus.focus_id,
        "card_kind": "additional_findings",
        "subject_level": None,
        "attention_ids": list(focus.attention_ids),
        "structures": _structure_metadata(focus),
        "structure_checklist": _structure_checklist(focus),
        "slots": _public_card_slots(rendered_slots),
        "tile_score_name": "abnormality_conspicuity",
        "tile_score_scale": {"0": "not_visible", "1": "subtle", "2": "definite", "3": "marked"},
        "tile_scores_are_diagnostic_severity": False,
    }
    _atomic_image(_draw_sheet(rows, title, tile_size, prominent_labels=True), path)
    caption = (
        "ADDITIONAL FINDINGS CARD: abnormal screening attention outside a resolved "
        "lumbar disc interval. Do not force a disc level; classify only the bound "
        "anatomical focus and state localization uncertainty. Tile ABN EVIDENCE "
        "scores are routing hints, not disease severity. The immediately preceding "
        "model text block carries the authoritative CARD_METADATA_JSON payload for "
        "this image."
    )
    return path, caption, {
        "focus_id": focus.focus_id,
        "level": ADDITIONAL_FINDINGS_LEVEL,
        "family": focus.family,
        "confidence": focus.confidence,
        "visual_salience": focus.visual_salience,
        "within_study_priority": focus.within_study_priority,
        "slice_persistence": focus.slice_persistence,
        "attention_sources": list(focus.sources),
        "attention_ids": list(focus.attention_ids),
        "correspondence_status": focus.correspondence_status or "legacy_unverified",
        "card_kind": "additional_findings_card",
        "card_template_version": LEVEL_CARD_TEMPLATE_VERSION,
        "card_slots": rendered_slots,
        "card_metadata": card_metadata,
        "axial_capture_frames": list(dict.fromkeys(
            item["capture_frame"] for item in rendered_slots
            if item["capture_frame"] is not None
        )),
        "sampling": {},
        "tile_size": list(tile_size),
    }


def _focus_image(
    volumes: Dict[str, SeriesVolume],
    axial_sequence: Sequence[_CapturedAxialSlice],
    windows: Dict[str, tuple[float, float]],
    focus: EvidenceFocus,
    frame_range: tuple[int, int],
    output_dir: Path,
    profile: _RenderProfile,
    group_integrity: Optional[Dict[str, Any]] = None,
) -> tuple[Path, str, dict]:
    level_card = profile.mode == MODE_FOCUSED_V5_LEVEL_CARDS
    if level_card:
        if focus.card_kind == "additional_findings":
            return _additional_findings_card_image(
                volumes, axial_sequence, windows, focus, output_dir, profile
            )
        return _level_card_image(
            volumes, axial_sequence, windows, focus, frame_range, output_dir, profile,
            group_integrity,
        )
    sagittal = volumes["sagittal_t2"]
    sagittal_t1 = volumes.get("sagittal_t1")
    first_frame, last_frame = frame_range
    matching_indices = [
        index
        for index, item in enumerate(axial_sequence)
        if first_frame <= item.capture_frame <= last_frame
    ]
    if not matching_indices:
        raise FocusedEvidenceError(
            "focus_geometry_unavailable",
            "The requested focus has no matching axial capture frame.",
        )
    patient_point = focus.geometry_anchor_lps
    if patient_point is not None:
        point = np.asarray(patient_point, dtype=np.float64)

        def plane_distance(index: int) -> float:
            image_slice = axial_sequence[index].source
            row = np.asarray(image_slice.orientation_lps[:3], dtype=np.float64)
            column = np.asarray(image_slice.orientation_lps[3:], dtype=np.float64)
            normal = np.cross(row, column)
            normal /= np.linalg.norm(normal)
            return abs(float(np.dot(point - np.asarray(image_slice.position_lps), normal)))

        center_index = min(matching_indices, key=plane_distance)
    else:
        center_index = matching_indices[len(matching_indices) // 2]
    center = axial_sequence[center_index]
    axial_window: Dict[str, Any] = {}
    axial_items = _same_slab_neighbors(
        axial_sequence, center_index, 2, selection_metadata=axial_window
    )
    if level_card:
        # A card is an isolated diagnostic unit. Never let a neighboring slab
        # enter it merely because two prescriptions have similar orientation
        # and spacing, and keep the sequence compact enough to read as one task.
        axial_items = [
            item for item in axial_items
            if first_frame <= item.capture_frame <= last_frame
        ]
        if len(axial_items) > 4:
            axial_items = sorted(
                sorted(
                    axial_items,
                    key=lambda item: abs(item.capture_frame - center.capture_frame),
                )[:4],
                key=lambda item: item.capture_frame,
            )
    if not axial_items:
        raise FocusedEvidenceError(
            "focus_geometry_unavailable",
            "The requested focus has no geometry-consistent axial neighbors.",
        )
    patient_point = patient_point or center.source.center_lps
    sagittal_window = windows["sagittal_t2"]
    axial_total = len(axial_sequence)
    tile = profile.focus_tile
    sampling: Dict[str, Any] = {}
    axial_tiles = [
        _axial_tile(item, windows["axial_t2"], profile, tile,
                    (
                        f"{focus.level} | AX T2 | frame {item.capture_frame}/{axial_total}"
                        if level_card else f"AX frame {item.capture_frame}/{axial_total}"
                    ),
                    sampling, "axial")
        for item in axial_items
    ]

    def _sag_crop(array, volume, projection, role, slice_number):
        if not profile.crop_to_spine:
            return _crop_around_point(array, projection)
        roi_mm = SAGITTAL_LEVEL_CARD_ROI_MM if level_card else SAGITTAL_FOCUS_ROI_MM
        cropped, box, spacing = _sagittal_roi(
            array, volume, projection, roi_mm
        )
        sampling.setdefault("sagittal", []).append({
            "role": role, "slice": slice_number, "crop_box": list(box),
            "mm_per_pixel": list(_effective_mm_per_pixel(box, spacing, tile)),
        })
        return cropped

    sagittal_projection = sagittal.patient_to_continuous_index(patient_point)
    sagittal_center = min(
        max(int(round(sagittal_projection[2])), 0), sagittal.depth - 1
    )
    sagittal_indices = (
        (sagittal_center,)
        if level_card
        else focus_slice_indices(sagittal_center, sagittal.depth, 1)
    )
    sagittal_tiles = []
    for index in sagittal_indices:
        array = _display(sagittal, index, sagittal_window)
        sagittal_tiles.append(
            (
                _sag_crop(array, sagittal, sagittal_projection,
                          "sagittal_t2", index + 1),
                (
                    f"{focus.level} | SAG T2 | slice {index + 1}/{sagittal.depth}"
                    if level_card else f"T2 SAG {index + 1}/{sagittal.depth}"
                ),
            )
        )
    sagittal_t1_indices = []
    if sagittal_t1 is not None:
        t1_projection = sagittal_t1.patient_to_continuous_index(patient_point)
        t1_index = min(
            max(int(round(t1_projection[2])), 0), sagittal_t1.depth - 1
        )
        t1_array = _display(sagittal_t1, t1_index, windows["sagittal_t1"])
        sagittal_t1_indices.append(t1_index + 1)
        sagittal_tiles.append(
            (
                _sag_crop(t1_array, sagittal_t1, t1_projection,
                          "sagittal_t1", t1_index + 1),
                (
                    f"{focus.level} | SAG T1 | slice {t1_index + 1}/{sagittal_t1.depth}"
                    if level_card else f"T1 SAG {t1_index + 1}/{sagittal_t1.depth}"
                ),
            )
        )

    if level_card:
        rows = [
            (
                f"SUBJECT LEVEL {focus.level}: one targeted sagittal T2 and matched T1",
                sagittal_tiles,
                horizontal_patient_orientation(sagittal),
            ),
            (
                f"SUBJECT LEVEL {focus.level}: contiguous axial T2 from this slab only",
                axial_tiles,
                horizontal_patient_orientation_for_slice(center.source),
            ),
        ]
    else:
        rows = [
            (
                "Up to five contiguous axial T2 slices within one acquisition slab",
                axial_tiles,
                horizontal_patient_orientation_for_slice(center.source),
            ),
            (
                "Same-level sagittal context projected in patient coordinates",
                sagittal_tiles,
                horizontal_patient_orientation(sagittal),
            ),
        ]
    _assert_source_signal(
        array for _label, tiles, _orientation in rows for array, _name in tiles
    )
    label = profile.mode.replace("focused-v", "V").upper()
    path = output_dir / f"{focus.focus_id}_{focus.level.replace('-', '_')}.png"
    attention_label = ", ".join(focus.attention_ids) or "no-attention-id"
    title = (
        f"DIAGNOSTIC LEVEL CARD | {focus.focus_id} | {attention_label} | "
        f"SUBJECT {focus.level}"
        if level_card else f"FOCUSED {label} | {focus.level} | {focus.family}"
    )
    _atomic_image(
        _draw_sheet(rows, title, tile, prominent_labels=level_card),
        path,
    )
    capture_frames = [item.capture_frame for item in axial_items]
    capture_label = (
        f"{capture_frames[0]}-{capture_frames[-1]}"
        if len(capture_frames) > 1
        else str(capture_frames[0])
    )
    if level_card:
        caption = (
            f"DIAGNOSTIC LEVEL CARD {focus.focus_id}; attention IDs {attention_label}; "
            f"SUBJECT LEVEL {focus.level}; source slab AX frames {first_frame}-{last_frame}; "
            f"displayed AX frames {capture_label}. This single card is the complete "
            "model-facing evidence unit for these attention IDs: one targeted sagittal "
            "T2, one geometrically matched sagittal T1 when available, and up to four "
            "contiguous axial T2 slices. Do not borrow anatomy, morphology, or frame "
            "evidence from another card."
        )
    else:
        caption = (
            f"Focused {label} level fusion for {focus.level} ({focus.family}): "
            f"adjacent axial T2 capture frames {capture_label} "
            "with geometry-projected sagittal T2 context and optional sagittal T1. "
            "Read adjacent slices as one continuous local sequence, not as independent images."
        )
    manifest = {
        "focus_id": focus.focus_id,
        "level": focus.level,
        "family": focus.family,
        "confidence": focus.confidence,
        "visual_salience": focus.visual_salience,
        "within_study_priority": focus.within_study_priority,
        "slice_persistence": focus.slice_persistence,
        "attention_sources": list(focus.sources),
        "attention_ids": list(focus.attention_ids),
        "correspondence_status": focus.correspondence_status or "legacy_unverified",
        "anchor_source": (
            "screening_geometry" if focus.geometry_anchor_lps is not None
            else "axial_slice_geometric_center"
        ),
        "axial_horizontal_orientation": list(
            horizontal_patient_orientation_for_slice(center.source) or ()
        ),
        "screening_frame_range": list(frame_range),
        "axial_window": axial_window,
        "axial_capture_frames": capture_frames,
        "axial_source_ordinals": [
            item.source.source_ordinal for item in axial_items
        ],
        "sagittal_t2_source_slices": [index + 1 for index in sagittal_indices],
        "sagittal_t1_source_slices": sagittal_t1_indices,
        "card_kind": "self_contained_level_card" if level_card else None,
        "tile_size": list(tile),
        "sampling": sampling,
    }
    return path, caption, manifest


def _parasagittal_samples(
    volume: SeriesVolume, patient_point: Sequence[float],
) -> tuple[list[dict], dict]:
    """Select both sides of a geometric reference, independent of model labels."""
    direction = np.asarray(volume.direction, dtype=np.float64).reshape(3, 3)
    if not np.all(np.isfinite(direction)) or abs(direction[0, 2]) < 0.85:
        raise EvidenceError("Parasagittal sampling requires a sagittal patient-space axis.")
    anchor = volume.patient_to_continuous_index(patient_point)
    if not all(np.isfinite(anchor)):
        raise EvidenceError("The sagittal reference is non-finite.")
    reference_index = int(round(anchor[2]))
    if not (0 <= reference_index < volume.depth and 0 <= anchor[0] < volume.width
            and 0 <= anchor[1] < volume.height):
        raise EvidenceError("The sagittal reference lies outside the source volume.")
    reference_point = np.asarray(volume.continuous_index_to_patient(
        (anchor[0], anchor[1], reference_index)
    ))
    selected: Dict[int, dict] = {}
    unavailable = []
    # Give the unchanged reference priority if coarse spacing merges targets.
    for offset in sorted(PARASAGITTAL_TARGET_OFFSETS_MM, key=abs):
        point = reference_point + np.asarray((offset, 0.0, 0.0))
        target = volume.patient_to_continuous_index(point)
        index = int(round(target[2]))
        if not (0 <= index < volume.depth and 0 <= target[0] < volume.width
                and 0 <= target[1] < volume.height):
            unavailable.append(offset)
            continue
        if index in selected:
            selected[index]["target_offsets_mm"].append(offset)
            continue
        projection = (target[0], target[1], float(index))
        actual_point = volume.continuous_index_to_patient(projection)
        selected[index] = {
            "source_slice": index + 1,
            "projection": projection,
            "offset_mm": round(actual_point[0] - reference_point[0], 4),
            "target_offsets_mm": [offset],
            "reference": index == reference_index,
        }
    samples = sorted(selected.values(), key=lambda item: item["offset_mm"])
    offsets = [item["offset_mm"] for item in samples]
    return samples, {
        "policy": PARASAGITTAL_POLICY,
        "reference_source_slice": reference_index + 1,
        "reference_kind": "axial_geometric_center_projection_not_verified_anatomical_midline",
        "target_offsets_mm": list(PARASAGITTAL_TARGET_OFFSETS_MM),
        "unavailable_target_offsets_mm": sorted(unavailable),
        "bilateral_coverage": any(x < -0.1 for x in offsets) and any(x > 0.1 for x in offsets),
        "source_slice_numbering": "one_based_decoded_volume_index_not_dicom_instance_number",
        "ordered_patient_direction": "right_to_left",
    }


def _parasagittal_image(
    volume: SeriesVolume, patient_point: Sequence[float], window: tuple[float, float],
    focus: dict, output_dir: Path,
    axial_planes: Sequence[tuple[int, DicomSlice]] = (),
) -> tuple[Path, str, dict]:
    samples, selection = _parasagittal_samples(volume, patient_point)
    tile_size = FOCUS_TILE_SIZE_V3
    tiles = []
    sampling = []
    reference_crop = None
    for sample in samples:
        array = _display(volume, sample["source_slice"] - 1, window)
        crop, box, spacing = _sagittal_roi(
            array, volume, sample["projection"], SAGITTAL_FOCUS_ROI_MM
        )
        offset = sample["offset_mm"]
        location = "REF" if sample["reference"] else f"{'R' if offset < 0 else 'L'} {abs(offset):.1f} mm"
        tiles.append((crop, f"T2 SAG {sample['source_slice']}/{volume.depth} | {location}"))
        if sample["reference"]:
            reference_crop = (crop, box, sample["source_slice"])
        sampling.append({
            "source_slice": sample["source_slice"], "offset_mm": offset,
            "target_offsets_mm": sample["target_offsets_mm"], "reference": sample["reference"],
            "crop_box": list(box),
            "mm_per_pixel": list(_effective_mm_per_pixel(box, spacing, tile_size)),
        })
    # Remove only surplus letterboxing. The new cell height is never smaller
    # than the previously displayed anatomy; width and source sampling stay put.
    heights = [min(array.shape[0], int(round(array.shape[0] * min(
        1.0, tile_size[0] / array.shape[1], tile_size[1] / array.shape[0]
    )))) for array, _ in tiles]
    tile_size = (tile_size[0], min(tile_size[1], max(256, max(heights) + 48)))
    _assert_source_signal(array for array, _ in tiles)
    rows = [
        ("Sagittal T2 samples, right to left; spacing may be nonuniform", tiles[i:i + 4],
         horizontal_patient_orientation(volume))
        for i in range(0, len(tiles), 4)
    ]
    path = output_dir / f"{focus['focus_id']}_parasagittal.png"
    canvas = _draw_sheet(rows, f"SAGITTAL SUPPLEMENT | {focus['level']}", tile_size)
    columns = max(len(row[1]) for row in rows)
    locator = {"policy": "dicom-axial-plane-locator-v1", "status": "unavailable",
               "reason": "no_spare_locator_cell"}
    # Seven clean samples occupy seven of eight existing cells. Use only the
    # spare cell: do not add pixels, shrink anatomy or overdraw diagnostic tiles.
    if reference_crop is not None and len(tiles) < len(rows) * columns:
        clean_crop, box, source_slice = reference_crop
        row, column = divmod(len(tiles), columns)
        locator = draw_locator(
            canvas, volume, source_slice, box, clean_crop, axial_planes,
            focus["axial_window"]["anchor_capture_frame"],
            (column * tile_size[0], HEADER_HEIGHT + row * (tile_size[1] + 24)),
            tile_size,
        )
    _atomic_image(canvas, path)
    caption = (
        f"Bilateral sagittal T2 supplement for {focus['level']}, paired with {focus['focus_id']}. "
        "Read tiles row-wise from patient right to left using displayed offsets; samples may "
        "be noncontiguous. REF is the unchanged geometric reference, not a verified anatomical "
        "midline. T2 SAG labels are source-volume slice numbers, not axial capture frames."
        " The crop can contain adjacent levels; its title does not label every visible disc."
    )
    if locator["status"] in {"included", "partial"}:
        caption += (
            " The LOCATOR ONLY cell repeats the clean REF image with DICOM axial-plane "
            "intersections labelled by AX capture frame; cyan is the selected anchor. "
            "Use it to link planes, then judge morphology on the clean tiles. Lines are "
            "acquisition planes, not lesion outlines, verified disc labels or proof of "
            "same-lesion correspondence. Do not transfer a neighboring disc's morphology "
            "to the focus title."
        )
    else:
        caption += " Axial-plane locator unavailable; cross-plane identity requires review."
    return path, caption, {
        "focus_id": focus["focus_id"], "level": focus["level"],
        "anchor_capture_frame": focus["axial_window"]["anchor_capture_frame"],
        "selection": selection, "sampling": sampling, "tile_count": len(tiles),
        "tile_size": list(tile_size), "render_policy": "compact-vertical-padding-v1",
        "axial_locator": locator,
        "file": path.name,
    }


def prepare_verification_package(
    package: AnalysisPackage,
    screening_text: str,
    screening_structured: Optional[Dict[str, Any]],
    context_structured: Optional[Dict[str, Any]],
    *,
    budget: EvidenceBudget = DEFAULT_BUDGET,
    mode: str = MODE_FOCUSED_V2,
) -> AnalysisPackage:
    """Build a compact package after both parallel attention branches finish.

    V2 and V3 choose the same slices by the same geometry; V3 spends more of
    each tile on the spine. V4 adds correlated parasagittal supplements. V5
    replaces the multi-image verification package with one self-contained card
    per resolved level so a diagnostic task cannot borrow an adjacent slab.
    """
    requested_mode = str(mode).strip().lower()
    if requested_mode == MODE_FOCUSED_V5_LEVEL_CARDS and budget == DEFAULT_BUDGET:
        budget = replace(budget, max_focuses=LEVEL_CARD_MAX_FOCUSES)
    add_supplements = requested_mode in {
        MODE_FOCUSED_V3_PARASAGITTAL, MODE_FOCUSED_V4_CORRELATED,
    }
    profile_mode = (
        MODE_FOCUSED_V3
        if requested_mode == MODE_FOCUSED_V3_PARASAGITTAL
        else requested_mode
    )
    profile = _RenderProfile.for_mode(profile_mode)
    output_mode = requested_mode if add_supplements else profile.mode
    plan: EvidencePlan = build_evidence_plan(
        screening_text,
        screening_structured,
        context_structured,
        max_focuses=budget.max_focuses,
    )
    try:
        volumes, axial_stack = _load_required_sources(package)
        axial_sequence = _captured_axial_sequence(package, axial_stack)
        windows = {
            role: intensity_window(volume) for role, volume in volumes.items()
        }
        windows["axial_t2"] = intensity_window_slices(axial_stack.slices)
        output_dir = package.session_dir / ".evidence" / output_mode
        overview_sampling: Dict[str, Any] = {}
        warnings = list(plan.warnings)
        level_cards = output_mode == MODE_FOCUSED_V5_LEVEL_CARDS
        rendered = (
            []
            if level_cards
            else _overview_images(
                volumes, axial_sequence, windows, output_dir, profile,
                overview_sampling,
            )
        )
        overview_image_count = len(rendered)
        focus_manifest = []
        for focus in plan.focuses:
            level_range = plan.level_frames.get(focus.level)
            candidate_ranges = (
                [(0, 0)]
                if level_cards and focus.card_kind == "additional_findings"
                else
                [level_range]
                if level_cards and level_range is not None
                else [
                    *((frame, frame) for frame in focus.key_axial_frames),
                    *([level_range] if level_range is not None else []),
                ]
            )
            if not candidate_ranges:
                warnings.append(f"level_map_missing:{focus.level}")
                continue
            rendered_focus = None
            last_error = None
            for frame_range in candidate_ranges:
                try:
                    rendered_focus = _focus_image(
                        volumes,
                        axial_sequence,
                        windows,
                        focus,
                        frame_range,
                        output_dir,
                        profile,
                        plan.group_integrity,
                    )
                    break
                except FocusedEvidenceError as exc:
                    last_error = exc
                except (EvidenceError, ValueError) as exc:
                    last_error = FocusedEvidenceError(
                        "focus_geometry_failed", str(exc)
                    )
            if rendered_focus is None:
                code = last_error.code if last_error is not None else "focus_render_failed"
                detail = str(last_error or "Focused evidence rendering failed.")
                warnings.append(f"{code}:{focus.level}:{detail}")
                continue
            path, caption, manifest = rendered_focus
            rendered.append((path, caption, focus.focus_id))
            focus_manifest.append(manifest)

        if level_cards and not focus_manifest:
            warnings.append("level_card_no_focus_overview_fallback")
            rendered = _overview_images(
                volumes, axial_sequence, windows, output_dir, profile,
                overview_sampling,
            )
            overview_image_count = len(rendered)

        card_payloads: Dict[int, Dict[str, Any]] = {}
        if level_cards and focus_manifest:
            for image_index, ((path, _caption, _session), focus) in enumerate(
                zip(rendered, focus_manifest),
                start=1,
            ):
                card_payloads[image_index] = {
                    "schema_version": "1.0.0",
                    "image_index": image_index,
                    "image_file": path.name,
                    "card_metadata": focus["card_metadata"],
                }

        packaged = [
            PackagedImage(
                path=path,
                caption=caption,
                session=session,
                index=index,
                evidence_mode=output_mode,
                card_payload=card_payloads.get(index),
            )
            for index, (path, caption, session) in enumerate(rendered, start=1)
        ]
        qualities = [inspect_image_quality(item.path) for item in packaged]
        usage = budget.measure(qualities, (item.path for item in packaged))
        budget.validate(usage, len(focus_manifest))
        if card_payloads:
            for image_index, focus in enumerate(focus_manifest, start=1):
                card_json_path = packaged[image_index - 1].path.with_suffix(
                    ".card.json"
                )
                _atomic_json(card_json_path, card_payloads[image_index])
                focus["card_json_file"] = card_json_path.name
        supplement_manifest = []
        if add_supplements:
            plan_by_id = {item.focus_id: item for item in plan.focuses}
            for focus in focus_manifest:
                record = {"focus_id": focus["focus_id"], "level": focus["level"]}
                supplement_manifest.append(record)
                if len(packaged) >= budget.max_images:
                    record["status"] = "budget_excluded"
                    warnings.append(f"parasagittal_budget_excluded:{focus['focus_id']}")
                    continue
                center = next(item for item in axial_sequence if item.capture_frame ==
                              focus["axial_window"]["anchor_capture_frame"])
                planned_focus = plan_by_id.get(focus["focus_id"])
                patient_point = (
                    planned_focus.geometry_anchor_lps
                    if planned_focus is not None and planned_focus.geometry_anchor_lps is not None
                    else center.source.center_lps
                )
                try:
                    path, caption, detail = _parasagittal_image(
                        volumes["sagittal_t2"], patient_point,
                        windows["sagittal_t2"], focus, output_dir,
                        [(item.capture_frame, item.source) for item in axial_sequence
                         if item.capture_frame in focus["axial_capture_frames"]],
                    )
                    record.update(detail)
                    quality = inspect_image_quality(path)
                except (EvidenceError, FocusedEvidenceError, OSError, ValueError):
                    record["status"] = "unavailable"
                    warnings.append(f"parasagittal_unavailable:{focus['focus_id']}")
                    continue
                trial_usage = budget.measure(
                    [*qualities, quality], [*(item.path for item in packaged), path]
                )
                try:
                    budget.validate(trial_usage, len(focus_manifest))
                except ValueError:
                    record["status"] = "budget_excluded"
                    warnings.append(f"parasagittal_budget_excluded:{focus['focus_id']}")
                    continue
                packaged.append(PackagedImage(
                    path, caption, f"{focus['focus_id']}-parasagittal", len(packaged) + 1,
                    evidence_mode=output_mode,
                ))
                qualities.append(quality)
                usage = trial_usage
                record["status"] = "included"
                locator_status = record["axial_locator"]["status"]
                if locator_status != "included":
                    warnings.append(f"axial_locator_{locator_status}:{focus['focus_id']}")
                if (record["selection"]["unavailable_target_offsets_mm"]
                        or not record["selection"]["bilateral_coverage"]):
                    warnings.append(f"parasagittal_partial_coverage:{focus['focus_id']}")
    except FocusedEvidenceError:
        raise
    except (EvidenceError, OSError, ValueError) as exc:
        raise FocusedEvidenceError(
            f"{profile.mode.replace('-', '_')}_composition_failed", str(exc)
        ) from exc

    manifest_document = {
        "schema_version": (
            LEVEL_CARD_MANIFEST_VERSION if output_mode == MODE_FOCUSED_V5_LEVEL_CARDS
            else "1.7.0" if output_mode == MODE_FOCUSED_V4_CORRELATED
            else "1.6.0" if add_supplements else MANIFEST_SCHEMA_VERSION
        ),
        "plan_schema_version": plan.schema_version,
        "evidence_mode": output_mode,
        "render_profile": {
            "focus_tile": list(profile.focus_tile),
            "axial_overview_tile": list(profile.axial_overview_tile),
            "sagittal_overview_tile": list(profile.sagittal_overview_tile),
            "crop_to_spine": profile.crop_to_spine,
            "axial_roi_mm": list(AXIAL_ROI_MM) if profile.crop_to_spine else None,
            "sagittal_focus_roi_mm": (
                list(
                    SAGITTAL_LEVEL_CARD_ROI_MM
                    if output_mode == MODE_FOCUSED_V5_LEVEL_CARDS
                    else SAGITTAL_FOCUS_ROI_MM
                ) if profile.crop_to_spine else None
            ),
            "sagittal_overview_roi_mm": (
                list(SAGITTAL_OVERVIEW_ROI_MM) if profile.crop_to_spine else None
            ),
        },
        "overview_sampling": overview_sampling,
        "overview_image_count": overview_image_count,
        "focus_image_count": len(focus_manifest),
        "focuses": focus_manifest,
        "measured_slabs": package.evidence_audit.get("measured_slabs", []),
        "warnings": list(dict.fromkeys(warnings)),
        "budget": {
            "image_count": usage.image_count,
            "pixel_count": usage.pixel_count,
            "byte_count": usage.byte_count,
            "max_images": budget.max_images,
            "max_focuses": budget.max_focuses,
            "max_pixels": budget.max_pixels,
            "max_bytes": budget.max_bytes,
        },
    }
    if output_mode == MODE_FOCUSED_V5_LEVEL_CARDS:
        manifest_document["card_bindings"] = [
            {
                "image_index": index,
                "focus_id": focus["focus_id"],
                "attention_ids": focus["attention_ids"],
                "subject_level": (
                    None if focus["level"] == ADDITIONAL_FINDINGS_LEVEL
                    else focus["level"]
                ),
                "allowed_axial_frames": focus["axial_capture_frames"],
                "card_kind": focus["card_kind"],
                "structure_group": focus.get("structure_group", "other"),
                "group_integrity": focus.get("group_integrity", {}),
                "card_metadata": focus["card_metadata"],
                "card_json_file": focus["card_json_file"],
            }
            for index, focus in enumerate(focus_manifest, start=1)
        ]
    if add_supplements:
        manifest_document["parasagittal_supplements"] = supplement_manifest
        capacity_notes = []
        if usage.image_count >= budget.max_images:
            capacity_notes.append("image_capacity_reached")
        if usage.pixel_count >= budget.max_pixels * 0.9:
            capacity_notes.append("pixel_headroom_below_ten_percent")
        if usage.byte_count >= budget.max_bytes * 0.9:
            capacity_notes.append("byte_headroom_below_ten_percent")
        manifest_document["capacity_notes"] = capacity_notes
    _atomic_json(output_dir / MANIFEST_NAME, manifest_document)
    base_header = "\n".join(
        line
        for line in package.header.splitlines()
        if "images follow, in capture order" not in line
    )
    mode_label = profile.mode.replace("focused-v", "V").upper()
    crop_note = (
        "  Each tile is cropped to a fixed physical box around the spine before "
        "it is scaled, so the pixels are spent on the disc, canal, recesses and "
        "facets rather than on the whole acquired field. The crop is geometric, "
        "not segmented: judge what you can see and say a structure is not "
        "assessable if the box excludes it.\n"
        if profile.crop_to_spine else ""
    )
    if output_mode == MODE_FOCUSED_V5_LEVEL_CARDS and focus_manifest:
        binding_lines = []
        for index, focus in enumerate(focus_manifest, start=1):
            attention_label = ",".join(focus["attention_ids"]) or "no-attention-id"
            frames = ",".join(str(frame) for frame in focus["axial_capture_frames"])
            subject = (
                "ADDITIONAL FINDINGS"
                if focus["level"] == ADDITIONAL_FINDINGS_LEVEL
                else f"SUBJECT LEVEL {focus['level']}"
            )
            binding_lines.append(
                f"  IMAGE {index} = {focus['focus_id']} = {attention_label} = "
                f"{subject} = STRUCTURE {focus.get('structure_group', 'other')} = "
                f"ALLOWED AX FRAMES {frames or 'none'}"
            )
        header = (
            f"{base_header}\n{crop_note}"
            "  EVIDENCE MODE: FOCUSED V5 ATOMIC STRUCTURE CARDS. Each model-facing "
            "image is one self-contained diagnostic task for exactly one abnormal "
            "screening structure group at one level. The card includes only the "
            "sagittal sequences, patient-space planes and axial samples required for "
            "that anatomical decision. Sagittal T1/T2 images sharing a patient-space "
            "plane remain vertically paired. "
            "VOL labels are source-volume indices, not DICOM InstanceNumbers; the "
            "two orders may run in opposite directions. "
            "Read the printed sagittal groups first, then the selected axial sequence "
            "left to right. Cyan, amber and violet borders encode sequence identity only, never "
            "diagnostic meaning, abnormality, laterality or severity. Gemini proposes source tiles "
            "and the local orchestrator validates role, identity and same-slab membership "
            "before filling a slot. T1 planes are synchronized to T2 through patient "
            "geometry. A local geometric fallback is labelled in the audit. "
            "There are no whole-stack or sagittal overview images "
            "in a positive-focus request. Use only the card bound to an attention ID; "
            "never use another card to classify, localize, grade, or justify that focus. "
            "A card may show a small amount of neighboring anatomy for context, but only "
            "the explicitly printed SUBJECT LEVEL is under review. AX labels are original "
            "capture frame numbers. Slot names describe sampling positions, not a finding's "
            "side, diagnosis or severity. An ADDITIONAL FINDINGS card is used only for "
            "abnormal attention that cannot be assigned safely to a named disc interval; "
            "never force it into a level. Every image is preceded by exactly one "
            "CARD_METADATA_JSON payload with "
            "structure attention, tile provenance and per-tile conspicuity. The score is "
            "an attention-routing hint and is never diagnostic severity. Cyan edge ticks "
            "are DICOM plane references; no full locator line crosses diagnostic anatomy.\n"
            "  AUTHORITATIVE CARD BINDINGS:\n"
            + "\n".join(binding_lines)
            + f"\n  {len(packaged)} model-facing level card(s) follow."
        )
    else:
        header = (
            f"{base_header}\n"
            f"{crop_note}"
            f"  EVIDENCE MODE: FOCUSED {mode_label}. The verification package contains a bounded "
            "sagittal overview, an ordered axial whole-stack overview, and one geometry-"
            "aligned level-fusion sheet for each resolved attention focus. Each focus "
            "sheet contains up to five contiguous neighboring slices from one acquisition "
            "slab; interpret them as a local sequence. Edge orientation labels are derived "
            "from DICOM direction cosines. Focus selection came from screening/context, "
            "but all diagnostic labels remain hypotheses to adjudicate. AX labels are "
            "original axial capture frame numbers used by the measured slab structure and "
            "final LEVEL MAP; raw DICOM source ordinals and composite-image indexes are "
            "never report frame numbers. "
            f"{len(packaged)} model-facing composite images follow."
        )
    if add_supplements:
        header += (
            "\n  Additional sagittal supplements, when budget and geometry permit, follow "
            "the unchanged base images. Their captions identify the paired focus and "
            "patient-space sample offsets; do not assume every source slice is shown."
            " A sagittal crop can contain adjacent levels. Its title is an attention "
            "label, not anatomical numbering of every visible disc. Where available, "
            "the spare LOCATOR ONLY cell shows DICOM intersections with the paired AX "
            "capture frames; use clean tiles for diagnosis. If the lesion-to-plane link "
            "is uncertain, record the uncertainty instead of borrowing a neighboring "
            "disc's appearance or renaming a level to fit the title."
        )
    if output_mode == MODE_FOCUSED_V4_CORRELATED:
        header += (
            "\n  CORRELATED FOCUS CONTRACT: screening locations were resolved through "
            "DICOM patient geometry. Focus crops are centred on the resolved abnormality "
            "anchor when available, not on the geometric centre of the axial slice. "
            "This confirms spatial correspondence only. Re-derive anatomy, level, side, "
            "normality and diagnosis independently from the supplied images."
        )
    if warnings:
        header += ("\n  EVIDENCE COVERAGE LIMITATIONS: " + "; ".join(dict.fromkeys(warnings))
                   + ". Missing focused evidence is not a normal finding.")
    return AnalysisPackage(
        session_dir=package.session_dir,
        session_id=package.session_id,
        protocol_id=package.protocol_id,
        analysis=package.analysis,
        header=header,
        images=packaged,
        study_instance_uid=package.study_instance_uid,
        source_series=package.source_series,
        evidence_audit=manifest_document,
    )
