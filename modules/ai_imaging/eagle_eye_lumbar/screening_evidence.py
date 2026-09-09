"""Build a source-grounded atlas for neutral lumbar abnormality screening.

The atlas is rendered from immutable DICOM pixels in the analysis worker.  It
does not drive the viewer, press Sync, or depend on UI state.  Every tile has a
session-local identity and a private transform back to patient LPS geometry so
the screening model can propose cross-plane observations without becoming the
authority for registration.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from modules.ai_imaging.evidence_core import (
    DicomSlice,
    DicomSliceStack,
    EvidenceBudget,
    SeriesVolume,
    fit_grayscale,
    horizontal_patient_orientation,
    horizontal_patient_orientation_for_slice,
    intensity_window,
    intensity_window_slices,
    inspect_image_quality,
)

from .evidence_bundle import MODE_FOCUSED_V4_CORRELATED
from .focus_evidence import (
    FocusedEvidenceError,
    SAGITTAL_OVERVIEW_ROI_MM,
    _assert_source_signal,
    _atomic_image,
    _atomic_json,
    _axial_roi,
    _captured_axial_sequence,
    _display,
    _display_dicom_slice,
    _load_required_sources,
    _sagittal_roi,
)
from .llm_package import AnalysisPackage, PackagedImage


SCREENING_MODE = "focused-v4-correlated-screening"
MANIFEST_SCHEMA_VERSION = "1.6.0"
MANIFEST_NAME = "screening_manifest.json"
COORDINATE_SPACE = "tile_content_0_1000"
SAGITTAL_TILE_SIZE = (320, 555)
AXIAL_TILE_SIZE = (256, 256)
SAGITTAL_TILES_PER_PAGE = 8
AXIAL_TILES_PER_PAGE = 20
SAGITTAL_PAGE_COLUMNS = 6
AXIAL_PAGE_COLUMNS = 5
DEFAULT_SCREENING_BUDGET = EvidenceBudget()
PAGE_HEADER = 42
CELL_LABEL = 28
GROUP_HEADER = 26
GROUP_GAP = 32
_HIGH_SEQUENCE_CONFIDENCE = frozenset({"high"})
_GROUP_COLORS = ("#7dd3fc", "#c4b5fd", "#86efac", "#fca5a5", "#fcd34d", "#f0abfc")


class ScreeningEvidenceError(RuntimeError):
    """The DICOM screening atlas could not be composed safely."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code or "screening_evidence_failed")


def _frame_groups(
    volumes: Dict[str, SeriesVolume], axial_stack: DicomSliceStack
) -> Dict[str, str]:
    """Replace private FrameOfReference UIDs with local equality groups."""
    values: Dict[str, str] = {}
    groups: Dict[str, str] = {}
    sources: Iterable[tuple[str, str]] = [
        (role, str(volume.frame_of_reference_uid or ""))
        for role, volume in volumes.items()
    ]
    if axial_stack.slices:
        sources = [*sources, ("axial_t2", str(axial_stack.slices[0].frame_of_reference_uid or ""))]
    for role, uid in sources:
        if uid:
            groups.setdefault(uid, f"frame-{len(groups) + 1}")
            values[role] = groups[uid]
        else:
            values[role] = f"unverified-{role}"
    return values


def _series_contract(
    package: AnalysisPackage, volumes: Dict[str, SeriesVolume]
) -> tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    """Assign neutral series identities and expose semantics only when reliable."""
    roles = [role for role in ("sagittal_t2", "sagittal_t1") if role in volumes]
    roles.sort(key=lambda role: (
        str(package.source_series.get(role, {}).get("series_number") or ""),
        str(package.source_series.get(role, {}).get("series_uid") or ""),
        role,
    ))
    by_role: Dict[str, str] = {}
    contract: Dict[str, Dict[str, Any]] = {}
    for index, role in enumerate(roles):
        series_id = f"sagittal-series-{chr(ord('a') + index)}"
        by_role[role] = series_id
        source = package.source_series.get(role, {})
        confidence = str(source.get("confidence") or "unknown").strip().casefold()
        assigned_by = str(source.get("assigned_by") or "unknown").strip().casefold()
        reliable = assigned_by == "user" or confidence in _HIGH_SEQUENCE_CONFIDENCE
        contract[series_id] = {
            "display_name": f"Sagittal Series {chr(ord('A') + index)}",
            "plane": "sagittal",
            "semantic_label": role if reliable else None,
            "semantic_confidence": "high" if assigned_by == "user" else confidence,
            "semantic_source": "user" if assigned_by == "user" else "workstation_classifier",
        }

    axial_id = "axial-series-a"
    by_role["axial_t2"] = axial_id
    source = package.source_series.get("axial_t2", {})
    confidence = str(source.get("confidence") or "unknown").strip().casefold()
    assigned_by = str(source.get("assigned_by") or "unknown").strip().casefold()
    reliable = assigned_by == "user" or confidence in _HIGH_SEQUENCE_CONFIDENCE
    contract[axial_id] = {
        "display_name": "Axial Series A",
        "plane": "axial",
        "semantic_label": "axial_t2" if reliable else None,
        "semantic_confidence": "high" if assigned_by == "user" else confidence,
        "semantic_source": "user" if assigned_by == "user" else "workstation_classifier",
    }
    return by_role, contract


def _axial_group_contract(measured_slabs: Sequence[Sequence[Any]]) -> list[Dict[str, Any]]:
    """Convert measured slice clusters into neutral, non-anatomical identities."""
    groups = []
    for index, bounds in enumerate(measured_slabs or (), start=1):
        try:
            first, last = int(bounds[0]), int(bounds[1])
        except (IndexError, TypeError, ValueError):
            continue
        if first <= 0 or last < first:
            continue
        groups.append({
            "group_id": f"axial-group-{index:02d}",
            "display_name": f"Axial Group {index}",
            "axial_frames": [first, last],
            "member_capture_frames": list(range(first, last + 1)),
            "member_count": last - first + 1,
            "meaning": "geometry_only_unlabelled_anatomical_group",
        })
    return groups


def _sagittal_group_contract(
    volumes: Dict[str, SeriesVolume],
    series_by_role: Dict[str, str],
) -> tuple[list[Dict[str, Any]], Dict[tuple[str, int], str]]:
    """Create three neutral lateral-to-central geometry regions across series.

    The outer three source planes are retained as separate lateral regions when
    coverage permits; all intervening planes form the central region. A shared,
    sign-canonicalized DICOM slice axis establishes patient-space order across
    series even when their source acquisition orders are reversed. No
    right/left anatomical label is assigned at this geometry-only stage.
    """
    memberships: Dict[tuple[str, int], str] = {}
    reference_axis: np.ndarray | None = None
    for role in ("sagittal_t2", "sagittal_t1"):
        volume = volumes.get(role)
        if volume is None:
            continue
        try:
            direction = np.asarray(volume.direction, dtype=np.float64).reshape(3, 3)
            candidate = direction[:, 2]
            candidate = candidate / np.linalg.norm(candidate)
        except (TypeError, ValueError) as exc:
            raise ScreeningEvidenceError(
                "sagittal_geometry_grouping_failed",
                "A sagittal series has invalid patient-space geometry.",
            ) from exc
        if not np.isfinite(candidate).all():
            raise ScreeningEvidenceError(
                "sagittal_geometry_grouping_failed",
                "A sagittal series has an invalid slice-normal axis.",
            )
        dominant = int(np.argmax(np.abs(candidate)))
        reference_axis = candidate if candidate[dominant] >= 0 else -candidate
        break
    if reference_axis is None:
        raise ScreeningEvidenceError(
            "sagittal_geometry_grouping_failed",
            "No sagittal series is available for geometry grouping.",
        )
    groups = [
        {
            "group_id": f"sagittal-group-{index:02d}",
            "display_name": f"Sagittal Group {index}",
            "spatial_order": index,
            "ordering_basis": "shared_canonical_dicom_slice_axis_projection_ascending",
            "meaning": "geometry_only_unlabelled_sagittal_region",
            "series_members": {},
        }
        for index in range(1, 4)
    ]
    for role in ("sagittal_t2", "sagittal_t1"):
        volume = volumes.get(role)
        series_id = series_by_role.get(role)
        if volume is None or not series_id:
            continue
        if volume.depth < 3:
            raise ScreeningEvidenceError(
                "sagittal_geometry_grouping_failed",
                "A sagittal series needs at least three spatially distinct slices.",
            )
        try:
            direction = np.asarray(volume.direction, dtype=np.float64).reshape(3, 3)
            origin = np.asarray(volume.origin, dtype=np.float64)
            step = direction[:, 2] * float(volume.spacing[2])
            local_axis = step / np.linalg.norm(step)
            if abs(float(np.dot(local_axis, reference_axis))) < 0.95:
                raise ValueError("incompatible sagittal slice axes")
            coordinates = {
                index: float(np.dot(origin + step * index, reference_axis))
                for index in range(volume.depth)
            }
        except (TypeError, ValueError) as exc:
            raise ScreeningEvidenceError(
                "sagittal_geometry_grouping_failed",
                "A sagittal series has invalid patient-space geometry.",
            ) from exc
        if not all(math.isfinite(value) for value in coordinates.values()):
            raise ScreeningEvidenceError(
                "sagittal_geometry_grouping_failed",
                "A sagittal series has non-finite patient-space positions.",
            )
        ordered = sorted(coordinates, key=coordinates.__getitem__)
        if len({round(coordinates[index], 4) for index in ordered}) != len(ordered):
            raise ScreeningEvidenceError(
                "sagittal_geometry_grouping_failed",
                "A sagittal series has repeated patient-space positions.",
            )
        outer = min(3, max(1, (len(ordered) - 1) // 2))
        partitions = (ordered[:outer], ordered[outer:-outer], ordered[-outer:])
        if any(not partition for partition in partitions):
            raise ScreeningEvidenceError(
                "sagittal_geometry_grouping_failed",
                "A sagittal series cannot form two lateral and one central group.",
            )
        for group, indices in zip(groups, partitions):
            group_id = str(group["group_id"])
            for index in indices:
                memberships[(role, index)] = group_id
            values = [coordinates[index] for index in indices]
            group["series_members"][series_id] = {
                "source_slices": [index + 1 for index in indices],
                "member_count": len(indices),
                "slice_normal_range_mm": [round(min(values), 4), round(max(values), 4)],
                "geometry_verified": bool(volume.source_geometry_verified),
            }
    if not all(group["series_members"] for group in groups):
        raise ScreeningEvidenceError(
            "sagittal_geometry_grouping_failed",
            "Sagittal geometry groups have incomplete source membership.",
        )
    return groups, memberships


def _group_for_frame(groups: Sequence[Dict[str, Any]], frame: int | None) -> str | None:
    if frame is None:
        return None
    for group in groups:
        first, last = group["axial_frames"]
        if first <= frame <= last:
            return str(group["group_id"])
    return None


def _tile_record(
    *,
    role: str,
    slice_index: int,
    crop_box: Sequence[int],
    frame_group: str,
    volume: SeriesVolume | None = None,
    image_slice: DicomSlice | None = None,
    capture_frame: int | None = None,
    sampling: Dict[str, Any] | None = None,
    series_id: str | None = None,
    public_role: str | None = None,
    geometry_group_id: str | None = None,
) -> Dict[str, Any]:
    public_series = str(series_id or role)
    record: Dict[str, Any] = {
        "tile_id": f"{public_series}:{slice_index + 1:04d}",
        "role": str(public_role or public_series),
        "series_id": public_series,
        "source_role": role,
        "source_slice": slice_index + 1,
        "capture_frame": int(capture_frame) if capture_frame is not None else None,
        "source_crop_box": [int(value) for value in crop_box],
        "frame_group": frame_group,
        "sampling": dict(sampling or {}),
    }
    if geometry_group_id:
        record["geometry_group_id"] = geometry_group_id
    if volume is not None:
        record["mapping"] = {
            "kind": "volume",
            "origin": [float(value) for value in volume.origin],
            "spacing": [float(value) for value in volume.spacing],
            "direction": [float(value) for value in volume.direction],
            "slice_index": int(slice_index),
        }
    elif image_slice is not None:
        record["mapping"] = {
            "kind": "dicom_slice",
            "position_lps": [float(value) for value in image_slice.position_lps],
            "orientation_lps": [float(value) for value in image_slice.orientation_lps],
            "pixel_spacing": [float(value) for value in image_slice.pixel_spacing],
        }
    return record


def _fitted_content_size(
    crop_box: Sequence[int], tile_size: tuple[int, int]
) -> list[int]:
    """Return the diagnostic-content size after no-upscale letterboxing."""
    width = max(1, int(crop_box[2]) - int(crop_box[0]))
    height = max(1, int(crop_box[3]) - int(crop_box[1]))
    scale = min(1.0, float(tile_size[0]) / width, float(tile_size[1]) / height)
    return [
        max(1, int(round(width * scale))),
        max(1, int(round(height * scale))),
    ]


def _sampling_record(
    crop_box: Sequence[int],
    spacing_xy: tuple[float, float],
    tile_size: tuple[int, int],
) -> Dict[str, Any]:
    box = tuple(int(value) for value in crop_box)
    content_size = _fitted_content_size(box, tile_size)
    source_size = [max(1, box[2] - box[0]), max(1, box[3] - box[1])]
    return {
        "source_spacing_mm": [round(float(value), 6) for value in spacing_xy],
        "effective_mm_per_pixel": [
            round(float(spacing_xy[index]) * source_size[index] / content_size[index], 4)
            for index in (0, 1)
        ],
        "fitted_content_size": content_size,
        "tile_size": list(tile_size),
    }


def _render_page(
    title: str,
    tiles: Sequence[tuple[np.ndarray, Dict[str, Any], tuple[str, str] | None]],
    destination: Path,
    *,
    tile_size: tuple[int, int],
    page_columns: int,
    group_labels: Dict[str, str] | None = None,
) -> list[Dict[str, Any]]:
    grouped: Dict[str, list] = {}
    for tile in tiles:
        group_id = str(tile[1].get("geometry_group_id") or "ungrouped")
        grouped.setdefault(group_id, []).append(tile)
    columns = min(
        page_columns,
        max(1, max((len(items) for items in grouped.values()), default=1)),
    )
    cell_width = tile_size[0]
    cell_height = tile_size[1] + CELL_LABEL
    group_rows = {
        group_id: int(math.ceil(len(items) / columns))
        for group_id, items in grouped.items()
    }
    content_height = sum(
        GROUP_HEADER + group_rows[group_id] * cell_height
        for group_id in grouped
    )
    content_height += GROUP_GAP * max(0, len(grouped) - 1)
    canvas = Image.new(
        "RGB", (columns * cell_width, PAGE_HEADER + content_height), "black"
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((8, 13), title, fill="white", font=font)
    blocks = []
    group_top = PAGE_HEADER
    for group_id, items in grouped.items():
        try:
            group_index = max(0, int(group_id.rsplit("-", 1)[-1]) - 1)
        except ValueError:
            group_index = 0
        outline = _GROUP_COLORS[group_index % len(_GROUP_COLORS)] if group_id else "#64748b"
        label = (group_labels or {}).get(group_id, group_id)
        draw.text(
            (8, group_top + 6),
            f"{label} | SPATIALLY SEPARATE GEOMETRY BLOCK",
            fill="white",
            font=font,
        )
        tile_top = group_top + GROUP_HEADER
        for index, (array, record, orientation) in enumerate(items):
            column = index % columns
            row = index // columns
            left = column * cell_width
            top = tile_top + row * cell_height
            canvas.paste(fit_grayscale(array, tile_size), (left, top))
            record["page_box"] = [
                left,
                top,
                left + tile_size[0],
                top + tile_size[1],
            ]
            record["layout_group_id"] = group_id
            draw.rectangle(
                (left + 1, top + 1, left + tile_size[0] - 2, top + tile_size[1] - 2),
                outline=outline,
                width=3 if group_id else 1,
            )
            draw.text((left + 6, top + 6), record["tile_id"], fill="#22d3ee", font=font)
            draw.text(
                (left + 6, top + 20),
                label,
                fill=outline,
                font=font,
            )
            if orientation:
                draw.text((left + 7, top + tile_size[1] // 2), orientation[0], fill="#fbbf24", font=font)
                draw.text((left + tile_size[0] - 16, top + tile_size[1] // 2), orientation[1], fill="#fbbf24", font=font)
            source_label = (
                f"AX frame {record['capture_frame']}"
                if record.get("capture_frame") is not None
                else f"source slice {record['source_slice']}"
            )
            draw.text((left + 6, top + tile_size[1] + 8), source_label, fill="#cbd5e1", font=font)
        block_bottom = tile_top + group_rows[group_id] * cell_height
        blocks.append({
            "geometry_group_id": group_id,
            "display_label": label,
            "primary_grouping_signal": "physical_spacing",
            "box": [0, group_top, canvas.width, block_bottom],
            "tile_ids": [record["tile_id"] for _array, record, _orientation in items],
        })
        group_top = block_bottom + GROUP_GAP
    _atomic_image(canvas, destination)
    return blocks


def _grouped_page_indices(
    tiles: Sequence[tuple[np.ndarray, Dict[str, Any], tuple[str, str] | None]],
    maximum_tiles: int,
) -> list[list[int]]:
    """Paginate only at geometry-group boundaries; never split a group for color."""
    grouped: Dict[str, list[int]] = {}
    for index, (_array, record, _orientation) in enumerate(tiles):
        group_id = str(record.get("geometry_group_id") or "ungrouped")
        grouped.setdefault(group_id, []).append(index)
    pages: list[list[int]] = []
    current: list[int] = []
    for indices in grouped.values():
        if current and len(current) + len(indices) > maximum_tiles:
            pages.append(current)
            current = []
        current.extend(indices)
    if current:
        pages.append(current)
    return pages


def _sagittal_tiles(
    role: str,
    volume: SeriesVolume,
    frame_group: str,
    series_id: str,
    public_role: str,
    group_memberships: Dict[tuple[str, int], str],
) -> list[tuple[np.ndarray, Dict[str, Any], tuple[str, str] | None]]:
    window = intensity_window(volume)
    result = []
    for index in range(volume.depth):
        array = _display(volume, index, window)
        cropped, box, spacing = _sagittal_roi(
            array, volume, None, SAGITTAL_OVERVIEW_ROI_MM
        )
        record = _tile_record(
            role=role,
            slice_index=index,
            crop_box=box,
            frame_group=frame_group,
            volume=volume,
            sampling=_sampling_record(box, spacing, SAGITTAL_TILE_SIZE),
            series_id=series_id,
            public_role=public_role,
            geometry_group_id=group_memberships.get((role, index)),
        )
        result.append((cropped, record, horizontal_patient_orientation(volume)))
    return result


def _axial_tiles(
    package: AnalysisPackage,
    stack: DicomSliceStack,
    frame_group: str,
    series_id: str,
    public_role: str,
    geometry_groups: Sequence[Dict[str, Any]],
) -> list[tuple[np.ndarray, Dict[str, Any], tuple[str, str] | None]]:
    sequence = _captured_axial_sequence(package, stack)
    window = intensity_window_slices(stack.slices)
    result = []
    for item in sequence:
        orientation = horizontal_patient_orientation_for_slice(item.source)
        if orientation != ("R", "L"):
            raise FocusedEvidenceError(
                "axial_canonical_orientation_unverified",
                "Axial evidence must have verified canonical radiological orientation (R at viewer left, L at viewer right).",
            )
        array = _display_dicom_slice(item.source, window)
        cropped, box, spacing = _axial_roi(array, item.source)
        source_index = int(item.source.source_ordinal) - 1
        record = _tile_record(
            role="axial_t2",
            slice_index=source_index,
            crop_box=box,
            frame_group=frame_group,
            image_slice=item.source,
            capture_frame=item.capture_frame,
            sampling=_sampling_record(box, spacing, AXIAL_TILE_SIZE),
            series_id=series_id,
            public_role=public_role,
            geometry_group_id=_group_for_frame(geometry_groups, item.capture_frame),
        )
        result.append(
            (cropped, record, orientation)
        )
    return result


def prepare_screening_package(package: AnalysisPackage) -> AnalysisPackage:
    """Return a bounded DICOM atlas for the first-pass Gemini branch."""
    try:
        volumes, axial_stack = _load_required_sources(package)
        groups = _frame_groups(volumes, axial_stack)
        series_by_role, series_contract = _series_contract(package, volumes)
        sagittal_groups, sagittal_group_memberships = _sagittal_group_contract(
            volumes, series_by_role
        )
        geometry_groups = _axial_group_contract(
            package.evidence_audit.get("measured_slabs", ())
        )
        role_tiles: list[tuple[str, str, str, list]] = []
        for role in ("sagittal_t2", "sagittal_t1"):
            volume = volumes.get(role)
            if volume is not None:
                series_id = series_by_role[role]
                contract = series_contract[series_id]
                public_role = str(contract.get("semantic_label") or series_id)
                role_tiles.append((
                    role,
                    series_id,
                    contract["display_name"],
                    _sagittal_tiles(
                        role,
                        volume,
                        groups[role],
                        series_id,
                        public_role,
                        sagittal_group_memberships,
                    ),
                ))
        axial_id = series_by_role["axial_t2"]
        axial_contract = series_contract[axial_id]
        role_tiles.append((
            "axial_t2",
            axial_id,
            axial_contract["display_name"],
            _axial_tiles(
                package,
                axial_stack,
                groups["axial_t2"],
                axial_id,
                str(axial_contract.get("semantic_label") or axial_id),
                geometry_groups,
            ),
        ))
        _assert_source_signal(
            array
            for _role, _series_id, _display, tiles in role_tiles
            for array, _record, _orientation in tiles
        )
    except ScreeningEvidenceError:
        raise
    except FocusedEvidenceError as exc:
        raise ScreeningEvidenceError(exc.code, str(exc)) from exc
    except Exception as exc:
        raise ScreeningEvidenceError("screening_atlas_composition_failed", str(exc)) from exc

    output_dir = package.session_dir / ".evidence" / MODE_FOCUSED_V4_CORRELATED / "screening"
    pages = []
    images = []
    image_index = 0
    group_labels = {
        str(group["group_id"]): str(group["display_name"])
        for group in (*sagittal_groups, *geometry_groups)
    }
    for role, series_id, display_name, tiles in role_tiles:
        sagittal = role.startswith("sagittal_")
        tile_size = SAGITTAL_TILE_SIZE if sagittal else AXIAL_TILE_SIZE
        tiles_per_page = (
            SAGITTAL_TILES_PER_PAGE if sagittal else AXIAL_TILES_PER_PAGE
        )
        page_columns = SAGITTAL_PAGE_COLUMNS if sagittal else AXIAL_PAGE_COLUMNS
        for page_number, indices in enumerate(
            _grouped_page_indices(tiles, tiles_per_page), start=1
        ):
            image_index += 1
            selected = [tiles[index] for index in indices]
            path = output_dir / f"{series_id}_page_{page_number:02d}.png"
            try:
                group_blocks = _render_page(
                    f"CORRELATED ANATOMY | {display_name} | page {page_number}",
                    selected,
                    path,
                    tile_size=tile_size,
                    page_columns=page_columns,
                    group_labels=group_labels,
                )
            except (OSError, ValueError) as exc:
                raise ScreeningEvidenceError(
                    "screening_atlas_render_failed", str(exc)
                ) from exc
            public_tiles = []
            for _array, record, _orientation in selected:
                record["image_index"] = image_index
                public_tiles.append(record)
            pages.append(
                {
                    "image_index": image_index,
                    "role": str(series_contract[series_id].get("semantic_label") or series_id),
                    "series_id": series_id,
                    "page": page_number,
                    "tile_size": list(tile_size),
                    "page_columns": min(page_columns, max(1, len(selected))),
                    "page_header": PAGE_HEADER,
                    "cell_label": CELL_LABEL,
                    "layout_kind": "geometry-group-blocks-v1",
                    "group_gap_px": GROUP_GAP,
                    "group_blocks": group_blocks,
                    "tiles": public_tiles,
                }
            )
            ids = ", ".join(record["tile_id"] for _array, record, _orientation in selected)
            images.append(
                PackagedImage(
                    path,
                    f"Source-grounded {display_name} anatomy atlas page {page_number}; tile IDs: {ids}.",
                    f"screening-{series_id}",
                    image_index,
                    evidence_mode=SCREENING_MODE,
                )
            )

    try:
        qualities = [inspect_image_quality(item.path) for item in images]
    except (OSError, ValueError) as exc:
        raise ScreeningEvidenceError(
            "screening_atlas_quality_failed", str(exc)
        ) from exc
    usage = DEFAULT_SCREENING_BUDGET.measure(
        qualities, (item.path for item in images)
    )
    try:
        DEFAULT_SCREENING_BUDGET.validate(usage, 0)
    except ValueError as exc:
        raise ScreeningEvidenceError(
            "screening_atlas_budget_exceeded", str(exc)
        ) from exc

    sampling_summary: Dict[str, Any] = {}
    for role, series_id, _display, _tiles in role_tiles:
        role_pages = [page for page in pages if page["series_id"] == series_id]
        role_records = [tile for page in role_pages for tile in page["tiles"]]
        samples = [tile["sampling"]["effective_mm_per_pixel"] for tile in role_records]
        sampling_summary[series_id] = {
            "tile_size": list(role_pages[0]["tile_size"]),
            "tiles_per_page": (
                SAGITTAL_TILES_PER_PAGE
                if role.startswith("sagittal_")
                else AXIAL_TILES_PER_PAGE
            ),
            "pagination_policy": "geometry_group_boundary",
            "primary_grouping_signal": "physical_spacing",
            "page_count": len(role_pages),
            "tile_count": len(role_records),
            "effective_mm_per_pixel": {
                "minimum": [min(values[index] for values in samples) for index in (0, 1)],
                "maximum": [max(values[index] for values in samples) for index in (0, 1)],
            },
        }

    capacity_notes = []
    if usage.image_count >= DEFAULT_SCREENING_BUDGET.max_images:
        capacity_notes.append("image_capacity_reached")
    if usage.pixel_count >= DEFAULT_SCREENING_BUDGET.max_pixels * 0.9:
        capacity_notes.append("pixel_headroom_below_ten_percent")
    if usage.byte_count >= DEFAULT_SCREENING_BUDGET.max_bytes * 0.9:
        capacity_notes.append("byte_headroom_below_ten_percent")

    audit = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "evidence_mode": SCREENING_MODE,
        "coordinate_space": COORDINATE_SPACE,
        "pages": pages,
        "measured_slabs": package.evidence_audit.get("measured_slabs", []),
        "series_contract": series_contract,
        "geometry_groups": {
            "sagittal": sagittal_groups,
            "axial": geometry_groups,
        },
        "screening_sampling": sampling_summary,
        "budget": {
            "image_count": usage.image_count,
            "pixel_count": usage.pixel_count,
            "byte_count": usage.byte_count,
            "max_images": DEFAULT_SCREENING_BUDGET.max_images,
            "max_pixels": DEFAULT_SCREENING_BUDGET.max_pixels,
            "max_bytes": DEFAULT_SCREENING_BUDGET.max_bytes,
        },
        "capacity_notes": capacity_notes,
        "warnings": [],
    }
    try:
        _atomic_json(output_dir / MANIFEST_NAME, audit)
    except OSError as exc:
        raise ScreeningEvidenceError(
            "screening_atlas_manifest_failed", str(exc)
        ) from exc
    base_header = "\n".join(
        line for line in package.header.splitlines()
        if "images follow, in capture order" not in line
    )
    series_lines = []
    for series_id, record in series_contract.items():
        hint = record.get("semantic_label")
        hint_text = (
            f"; high-confidence semantic label={hint}"
            if hint else "; semantic label unresolved - determine from images and metadata"
        )
        series_lines.append(
            f"    {record['display_name']} [{series_id}]: plane={record['plane']}{hint_text}"
        )
    group_lines = [
            f"    {group['display_name']} [{group['group_id']}]: geometry-only "
            "sagittal region; anatomical role unresolved"
            for group in sagittal_groups
    ] + [
        f"    {group['display_name']} [{group['group_id']}]: axial frames "
        f"{group['axial_frames'][0]}-{group['axial_frames'][1]}; anatomical level unresolved"
        for group in geometry_groups
    ]
    header = (
        f"{base_header}\n"
        "  GEOMETRY-FIRST ANATOMY ATLAS. The workstation groups spatially related "
        "images but does not guess unresolved sequence or lumbar-level semantics.\n"
        + "\n".join(series_lines)
        + ("\n" + "\n".join(group_lines) if group_lines else "")
        + "\n  Each cyan "
        "tile ID identifies one immutable DICOM slice. Report a location as image + "
        "tile_id + box_2d. box_2d is [ymin,xmin,ymax,xmax] normalized 0..1000 "
        "relative to the grayscale diagnostic CONTENT inside that tile, excluding "
        "black letterbox padding, borders and labels. Link observations in different "
        "roles under one finding only when they plausibly represent the same abnormal "
        "focus; deterministic patient-space geometry will verify the proposed link. "
        "Do not diagnose or grade the focus."
    )
    return AnalysisPackage(
        package.session_dir,
        package.session_id,
        package.protocol_id,
        package.analysis,
        header,
        images,
        study_instance_uid=package.study_instance_uid,
        source_series=package.source_series,
        evidence_audit=audit,
    )


def tile_inventory(package: AnalysisPackage) -> Dict[tuple[int, str], Dict[str, Any]]:
    """Return the unambiguous local transform inventory for an atlas package."""
    inventory: Dict[tuple[int, str], Dict[str, Any]] = {}
    for page in package.evidence_audit.get("pages", []):
        if not isinstance(page, dict):
            continue
        image_index = page.get("image_index")
        if type(image_index) is not int:
            continue
        for tile in page.get("tiles", []):
            if not isinstance(tile, dict) or not isinstance(tile.get("tile_id"), str):
                continue
            key = (image_index, tile["tile_id"])
            inventory[key] = tile if key not in inventory else None
    return inventory


def tile_box_center_lps(tile: Dict[str, Any], box: Sequence[float]) -> tuple[float, float, float]:
    """Resolve one tile-content box centre to patient LPS millimetres."""
    crop = tile["source_crop_box"]
    y = float(crop[1]) + ((float(box[0]) + float(box[2])) / 2000.0) * (float(crop[3]) - float(crop[1]))
    x = float(crop[0]) + ((float(box[1]) + float(box[3])) / 2000.0) * (float(crop[2]) - float(crop[0]))
    mapping = tile["mapping"]
    if mapping["kind"] == "volume":
        direction = np.asarray(mapping["direction"], dtype=np.float64).reshape(3, 3)
        axis_distance = np.asarray(
            (x * mapping["spacing"][0], y * mapping["spacing"][1], mapping["slice_index"] * mapping["spacing"][2]),
            dtype=np.float64,
        )
        point = np.asarray(mapping["origin"], dtype=np.float64) + direction @ axis_distance
    elif mapping["kind"] == "dicom_slice":
        row = np.asarray(mapping["orientation_lps"][:3], dtype=np.float64)
        column = np.asarray(mapping["orientation_lps"][3:], dtype=np.float64)
        row /= np.linalg.norm(row)
        column /= np.linalg.norm(column)
        point = (
            np.asarray(mapping["position_lps"], dtype=np.float64)
            + row * float(mapping["pixel_spacing"][1]) * x
            + column * float(mapping["pixel_spacing"][0]) * y
        )
    else:
        raise ValueError("Unknown screening tile mapping kind.")
    result = tuple(float(value) for value in point)
    if not all(math.isfinite(value) for value in result):
        raise ValueError("Screening tile geometry produced a non-finite point.")
    return result
