"""Compose compact, geometry-aligned focused-v2 evidence for verification."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
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

from .evidence_bundle import MODE_FOCUSED_V2, MODE_FOCUSED_V3, MODE_FOCUSED_V3_PARASAGITTAL
from .evidence_request import EvidenceFocus, EvidencePlan, build_evidence_plan
from .llm_package import AnalysisPackage, PackagedImage
from .series_classifier import SeriesCandidate


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
# The sagittal overview keeps the whole lumbar column, so its crop is tall and
# narrow; a square tile would let the height set the scale and give the crop
# back almost nothing. This is the one non-square tile in the pipeline.
SAGITTAL_OVERVIEW_TILE_V3 = (288, 512)
AXIAL_ROI_MM = (96.0, 104.0)          # (left-right, anterior-posterior)
AXIAL_ROI_POSTERIOR_BIAS = 0.06       # fraction of image height, toward P
SAGITTAL_FOCUS_ROI_MM = (100.0, 100.0)   # (anterior-posterior, superior-inferior)
SAGITTAL_OVERVIEW_ROI_MM = (150.0, 260.0)
MIN_ROI_PIXELS = 48
# Sampling targets for a bounded experiment, not anatomical zone thresholds.
PARASAGITTAL_TARGET_OFFSETS_MM = (-15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0)
PARASAGITTAL_POLICY = "bilateral-lps-supplement-v1"


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
        if str(mode or "").strip().lower() == MODE_FOCUSED_V3:
            return cls(
                MODE_FOCUSED_V3, FOCUS_TILE_SIZE_V3, TILE_SIZE,
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
) -> Image.Image:
    columns = max((len(tiles) for _label, tiles, _orientation in rows), default=1)
    row_height = tile_size[1] + 24
    canvas = Image.new(
        "RGB",
        (columns * tile_size[0], HEADER_HEIGHT + len(rows) * row_height),
        "black",
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((8, 12), title, fill="white", font=font)
    for row_number, (row_label, tiles, orientation) in enumerate(rows):
        top = HEADER_HEIGHT + row_number * row_height
        for column, (array, label) in enumerate(tiles):
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
        draw.text((6, top + tile_size[1] + 6), row_label, fill="#cbd5e1", font=font)
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


def _focus_image(
    volumes: Dict[str, SeriesVolume],
    axial_sequence: Sequence[_CapturedAxialSlice],
    windows: Dict[str, tuple[float, float]],
    focus: EvidenceFocus,
    frame_range: tuple[int, int],
    output_dir: Path,
    profile: _RenderProfile,
) -> tuple[Path, str, dict]:
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
    center_index = matching_indices[len(matching_indices) // 2]
    center = axial_sequence[center_index]
    axial_window: Dict[str, Any] = {}
    axial_items = _same_slab_neighbors(
        axial_sequence, center_index, 2, selection_metadata=axial_window
    )
    if not axial_items:
        raise FocusedEvidenceError(
            "focus_geometry_unavailable",
            "The requested focus has no geometry-consistent axial neighbors.",
        )
    patient_point = center.source.center_lps
    sagittal_window = windows["sagittal_t2"]
    axial_total = len(axial_sequence)
    tile = profile.focus_tile
    sampling: Dict[str, Any] = {}
    axial_tiles = [
        _axial_tile(item, windows["axial_t2"], profile, tile,
                    f"AX frame {item.capture_frame}/{axial_total}",
                    sampling, "axial")
        for item in axial_items
    ]

    def _sag_crop(array, volume, projection, role, slice_number):
        if not profile.crop_to_spine:
            return _crop_around_point(array, projection)
        cropped, box, spacing = _sagittal_roi(
            array, volume, projection, SAGITTAL_FOCUS_ROI_MM
        )
        sampling.setdefault("sagittal", []).append({
            "role": role, "slice": slice_number, "crop_box": list(box),
            "mm_per_pixel": list(_effective_mm_per_pixel(box, spacing, tile)),
        })
        return cropped

    sagittal_projection = sagittal.patient_to_continuous_index(patient_point)
    sagittal_indices = focus_slice_indices(
        int(round(sagittal_projection[2])), sagittal.depth, 1
    )
    sagittal_tiles = []
    for index in sagittal_indices:
        array = _display(sagittal, index, sagittal_window)
        sagittal_tiles.append(
            (
                _sag_crop(array, sagittal, sagittal_projection,
                          "sagittal_t2", index + 1),
                f"T2 SAG {index + 1}/{sagittal.depth}",
            )
        )
    if sagittal_t1 is not None:
        t1_projection = sagittal_t1.patient_to_continuous_index(patient_point)
        t1_index = min(
            max(int(round(t1_projection[2])), 0), sagittal_t1.depth - 1
        )
        t1_array = _display(sagittal_t1, t1_index, windows["sagittal_t1"])
        sagittal_tiles.append(
            (
                _sag_crop(t1_array, sagittal_t1, t1_projection,
                          "sagittal_t1", t1_index + 1),
                f"T1 SAG {t1_index + 1}/{sagittal_t1.depth}",
            )
        )

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
    _atomic_image(
        _draw_sheet(
            rows, f"FOCUSED {label} | {focus.level} | {focus.family}", tile
        ),
        path,
    )
    capture_frames = [item.capture_frame for item in axial_items]
    capture_label = (
        f"{capture_frames[0]}-{capture_frames[-1]}"
        if len(capture_frames) > 1
        else str(capture_frames[0])
    )
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
        "attention_sources": list(focus.sources),
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
) -> tuple[Path, str, dict]:
    samples, selection = _parasagittal_samples(volume, patient_point)
    tile_size = FOCUS_TILE_SIZE_V3
    tiles = []
    sampling = []
    for sample in samples:
        array = _display(volume, sample["source_slice"] - 1, window)
        crop, box, spacing = _sagittal_roi(
            array, volume, sample["projection"], SAGITTAL_FOCUS_ROI_MM
        )
        offset = sample["offset_mm"]
        location = "REF" if sample["reference"] else f"{'R' if offset < 0 else 'L'} {abs(offset):.1f} mm"
        tiles.append((crop, f"T2 SAG {sample['source_slice']}/{volume.depth} | {location}"))
        sampling.append({
            "source_slice": sample["source_slice"], "offset_mm": offset,
            "target_offsets_mm": sample["target_offsets_mm"], "reference": sample["reference"],
            "crop_box": list(box),
            "mm_per_pixel": list(_effective_mm_per_pixel(box, spacing, tile_size)),
        })
    _assert_source_signal(array for array, _ in tiles)
    rows = [
        ("Sagittal T2 samples, right to left; spacing may be nonuniform", tiles[i:i + 4],
         horizontal_patient_orientation(volume))
        for i in range(0, len(tiles), 4)
    ]
    path = output_dir / f"{focus['focus_id']}_parasagittal.png"
    _atomic_image(_draw_sheet(rows, f"SAGITTAL SUPPLEMENT | {focus['level']}", tile_size), path)
    caption = (
        f"Bilateral sagittal T2 supplement for {focus['level']}, paired with {focus['focus_id']}. "
        "Read tiles row-wise from patient right to left using displayed offsets; samples may "
        "be noncontiguous. REF is the unchanged geometric reference, not a verified anatomical "
        "midline. T2 SAG labels are source-volume slice numbers, not axial capture frames."
    )
    return path, caption, {
        "focus_id": focus["focus_id"], "level": focus["level"],
        "anchor_capture_frame": focus["axial_window"]["anchor_capture_frame"],
        "selection": selection, "sampling": sampling, "tile_count": len(tiles),
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
    each tile on the spine. The opt-in parasagittal mode appends bounded
    bilateral supplements only after the unchanged V3 package is complete.
    """
    add_supplements = str(mode).strip().lower() == MODE_FOCUSED_V3_PARASAGITTAL
    profile = _RenderProfile.for_mode(MODE_FOCUSED_V3 if add_supplements else mode)
    output_mode = MODE_FOCUSED_V3_PARASAGITTAL if add_supplements else profile.mode
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
        rendered = _overview_images(
            volumes, axial_sequence, windows, output_dir, profile,
            overview_sampling,
        )
        focus_manifest = []
        warnings = list(plan.warnings)
        for focus in plan.focuses:
            level_range = plan.level_frames.get(focus.level)
            candidate_ranges = [
                *((frame, frame) for frame in focus.key_axial_frames),
                *([level_range] if level_range is not None else []),
            ]
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
                warnings.append(f"{code}:{focus.level}")
                continue
            path, caption, manifest = rendered_focus
            rendered.append((path, caption, focus.focus_id))
            focus_manifest.append(manifest)

        packaged = [
            PackagedImage(
                path=path,
                caption=caption,
                session=session,
                index=index,
                evidence_mode=output_mode,
            )
            for index, (path, caption, session) in enumerate(rendered, start=1)
        ]
        qualities = [inspect_image_quality(item.path) for item in packaged]
        usage = budget.measure(qualities, (item.path for item in packaged))
        budget.validate(usage, len(focus_manifest))
        supplement_manifest = []
        if add_supplements:
            for focus in focus_manifest:
                record = {"focus_id": focus["focus_id"], "level": focus["level"]}
                supplement_manifest.append(record)
                if len(packaged) >= budget.max_images:
                    record["status"] = "budget_excluded"
                    warnings.append(f"parasagittal_budget_excluded:{focus['focus_id']}")
                    continue
                center = next(item for item in axial_sequence if item.capture_frame ==
                              focus["axial_window"]["anchor_capture_frame"])
                try:
                    path, caption, detail = _parasagittal_image(
                        volumes["sagittal_t2"], center.source.center_lps,
                        windows["sagittal_t2"], focus, output_dir,
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
        "schema_version": "1.4.0" if add_supplements else MANIFEST_SCHEMA_VERSION,
        "plan_schema_version": plan.schema_version,
        "evidence_mode": output_mode,
        "render_profile": {
            "focus_tile": list(profile.focus_tile),
            "axial_overview_tile": list(profile.axial_overview_tile),
            "sagittal_overview_tile": list(profile.sagittal_overview_tile),
            "crop_to_spine": profile.crop_to_spine,
            "axial_roi_mm": list(AXIAL_ROI_MM) if profile.crop_to_spine else None,
            "sagittal_focus_roi_mm": (
                list(SAGITTAL_FOCUS_ROI_MM) if profile.crop_to_spine else None
            ),
            "sagittal_overview_roi_mm": (
                list(SAGITTAL_OVERVIEW_ROI_MM) if profile.crop_to_spine else None
            ),
        },
        "overview_sampling": overview_sampling,
        "overview_image_count": 2,
        "focus_image_count": len(focus_manifest),
        "focuses": focus_manifest,
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
    if add_supplements:
        manifest_document["parasagittal_supplements"] = supplement_manifest
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
    header = (
        f"{base_header}\n"
        f"{crop_note}"
        f"  EVIDENCE MODE: FOCUSED {mode_label}. The verification package contains a bounded "
        "sagittal overview, an ordered axial whole-stack overview, and one geometry-"
        "aligned level-fusion sheet for each resolved attention focus. Each focus "
        "sheet contains up to five contiguous neighboring slices from one acquisition "
        "slab; interpret them as a local sequence. Edge orientation labels are derived "
        "from DICOM direction "
        "cosines. Focus selection came from screening/context, but all diagnostic "
        "labels remain hypotheses to adjudicate. AX labels are original axial "
        "capture frame numbers used by the measured slab structure and final "
        "LEVEL MAP; raw DICOM source ordinals and composite-image indexes are "
        "never report frame numbers. "
        f"{len(packaged)} model-facing composite images follow."
    )
    if add_supplements:
        header += (
            "\n  Additional sagittal supplements, when budget and geometry permit, follow "
            "the unchanged base images. Their captions identify the paired focus and "
            "patient-space sample offsets; do not assume every source slice is shown."
        )
    return AnalysisPackage(
        session_dir=package.session_dir,
        session_id=package.session_id,
        protocol_id=package.protocol_id,
        analysis=package.analysis,
        header=header,
        images=packaged,
        study_instance_uid=package.study_instance_uid,
        source_series=package.source_series,
    )
