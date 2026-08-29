"""Build privacy-bounded MRI evidence around a radiologist-marked ROI.

The source DICOM pixels never leave this module. Every selected stack is
represented by complete overview contact sheets plus high-detail context/zoom
images for the projected ROI slice and five adjacent slices in each direction.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from modules.ai_imaging.eagle_eye_lumbar.llm_package import (
    AnalysisPackage,
    PackagedImage,
)
from modules.ai_imaging.eagle_eye_lumbar.series_classifier import SeriesCandidate

from .models import LegionConsultRequest
from .prompts import LEGION_ANALYSIS_PIPELINE
from .series_selection import series_key


EVIDENCE_MANIFEST = "evidence_manifest.json"
TILES_PER_PAGE = 20
TILE_SIZE = (256, 256)
MIN_PROJECTED_ROI_SIZE = 12


class EvidenceError(RuntimeError):
    """The selected DICOM evidence cannot be prepared safely."""


@dataclass(frozen=True)
class SeriesVolume:
    """One decoded 3D scalar volume with SimpleITK-compatible geometry."""

    pixels: np.ndarray
    origin: tuple[float, float, float]
    spacing: tuple[float, float, float]
    direction: tuple[float, ...]
    plane: str = "unknown"
    inverted: bool = False

    def __post_init__(self) -> None:
        pixels = np.asarray(self.pixels)
        if pixels.ndim != 3:
            raise ValueError("Legion Consult requires a 3D scalar image volume.")
        if not all(int(size) > 0 for size in pixels.shape):
            raise ValueError("Legion Consult received an empty 3D volume.")
        if len(self.origin) != 3 or len(self.spacing) != 3 or len(self.direction) != 9:
            raise ValueError("The volume geometry is incomplete.")
        if any(float(value) <= 0 for value in self.spacing):
            raise ValueError("The volume spacing must be positive.")

    @property
    def depth(self) -> int:
        return int(self.pixels.shape[0])

    @property
    def height(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def width(self) -> int:
        return int(self.pixels.shape[2])

    def patient_to_continuous_index(
        self, point: Sequence[float]
    ) -> tuple[float, float, float]:
        """Map patient LPS millimetres to continuous x/y/z voxel indices."""
        if len(point) < 3:
            raise ValueError("A patient-space point requires three coordinates.")
        direction = np.asarray(self.direction, dtype=np.float64).reshape(3, 3)
        delta = np.asarray(point[:3], dtype=np.float64) - np.asarray(
            self.origin, dtype=np.float64
        )
        try:
            axis_distance = np.linalg.solve(direction, delta)
        except np.linalg.LinAlgError as exc:
            raise EvidenceError("The DICOM orientation matrix is singular.") from exc
        index = axis_distance / np.asarray(self.spacing, dtype=np.float64)
        return tuple(float(value) for value in index)


@dataclass(frozen=True)
class ROIProjection:
    """Projected attention rectangle for one stack."""

    center_slice: int
    bounds: tuple[int, int, int, int]
    continuous_points: tuple[tuple[float, float, float], ...]


def focus_slice_indices(center: int, depth: int, padding: int = 5) -> tuple[int, ...]:
    """Return a clipped inclusive slice window around the projected center."""
    if depth <= 0:
        return ()
    center = min(max(int(center), 0), int(depth) - 1)
    padding = max(int(padding), 0)
    return tuple(range(max(0, center - padding), min(depth, center + padding + 1)))


def overview_page_indices(
    depth: int, tiles_per_page: int = TILES_PER_PAGE
) -> tuple[tuple[int, ...], ...]:
    """Partition a stack so every slice appears once in an overview page."""
    if depth <= 0:
        return ()
    if tiles_per_page <= 0:
        raise ValueError("tiles_per_page must be positive")
    indices = tuple(range(int(depth)))
    return tuple(
        indices[start : start + int(tiles_per_page)]
        for start in range(0, len(indices), int(tiles_per_page))
    )


def _expanded_axis_bounds(low: float, high: float, limit: int) -> tuple[int, int]:
    center = (float(low) + float(high)) / 2.0
    half = max(abs(float(high) - float(low)) / 2.0, MIN_PROJECTED_ROI_SIZE / 2.0)
    first = max(0, int(math.floor(center - half)))
    last = min(int(limit), int(math.ceil(center + half)))
    if last <= first:
        first = min(max(int(round(center)), 0), max(int(limit) - 1, 0))
        last = min(int(limit), first + 1)
    return first, last


def project_patient_roi(
    volume: SeriesVolume,
    patient_lps_corners: Sequence[Sequence[float]],
) -> ROIProjection:
    """Project the four patient-space ROI corners into one selected series."""
    if len(patient_lps_corners) != 4:
        raise EvidenceError("The attention ROI must contain four patient-space corners.")
    points = tuple(
        volume.patient_to_continuous_index(point) for point in patient_lps_corners
    )
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    center_slice = min(
        max(int(round(sum(zs) / len(zs))), 0),
        volume.depth - 1,
    )
    x0, x1 = _expanded_axis_bounds(min(xs), max(xs), volume.width)
    y0, y1 = _expanded_axis_bounds(min(ys), max(ys), volume.height)
    return ROIProjection(
        center_slice=center_slice,
        bounds=(x0, y0, x1, y1),
        continuous_points=points,
    )


def _dicom_files(candidate: SeriesCandidate) -> list[str]:
    directory = Path(candidate.series_path)
    if not directory.is_dir():
        raise EvidenceError("A selected MRI series is no longer available locally.")
    try:
        import SimpleITK as sitk

        filenames = list(
            sitk.ImageSeriesReader.GetGDCMSeriesFileNames(
                str(directory), str(candidate.series_uid or "")
            )
        )
        if not filenames:
            filenames = list(sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(directory)))
    except Exception as exc:
        raise EvidenceError("The selected MRI series headers could not be indexed.") from exc
    if not filenames:
        raise EvidenceError("A selected MRI series contains no readable DICOM images.")
    return filenames


def _reject_burned_annotations(first_file: str) -> bool:
    """Fail closed when the DICOM explicitly declares burned-in annotation."""
    try:
        import pydicom

        dataset = pydicom.dcmread(
            first_file,
            stop_before_pixels=True,
            specific_tags=["BurnedInAnnotation", "PhotometricInterpretation"],
        )
    except Exception as exc:
        raise EvidenceError("The selected MRI privacy metadata could not be read.") from exc
    value = str(getattr(dataset, "BurnedInAnnotation", "") or "").strip().upper()
    if value == "YES":
        raise EvidenceError(
            "A selected series declares burned-in annotations and cannot be sent safely."
        )
    return str(getattr(dataset, "PhotometricInterpretation", "") or "").upper() == (
        "MONOCHROME1"
    )


def load_series_volume(candidate: SeriesCandidate) -> SeriesVolume:
    """Decode one selected DICOM series without constructing Qt or VTK objects."""
    filenames = _dicom_files(candidate)
    inverted = _reject_burned_annotations(filenames[0])
    try:
        import SimpleITK as sitk

        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(filenames)
        image = reader.Execute()
        pixels = sitk.GetArrayFromImage(image)
        if int(image.GetDimension()) != 3:
            raise EvidenceError("A selected MRI series is not a 3D image stack.")
        return SeriesVolume(
            pixels=np.asarray(pixels),
            origin=tuple(float(value) for value in image.GetOrigin()),
            spacing=tuple(float(value) for value in image.GetSpacing()),
            direction=tuple(float(value) for value in image.GetDirection()),
            plane=str(candidate.plane or "unknown"),
            inverted=inverted,
        )
    except EvidenceError:
        raise
    except Exception as exc:
        raise EvidenceError("A selected MRI series could not be decoded.") from exc


def _intensity_window(volume: SeriesVolume) -> tuple[float, float]:
    """Estimate a robust window from a bounded sample of the volume."""
    values = np.asarray(volume.pixels)
    flat = values.reshape(-1)
    stride = max(1, int(math.ceil(flat.size / 1_000_000)))
    sample = np.asarray(flat[::stride], dtype=np.float32)
    finite = sample[np.isfinite(sample)]
    if finite.size == 0:
        raise EvidenceError("A selected MRI series contains no finite pixel values.")
    low, high = np.percentile(finite, (1.0, 99.0))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(np.min(finite))
        high = float(np.max(finite))
    return float(low), float(high)


def _display_slice(
    pixels: np.ndarray, low: float, high: float, inverted: bool
) -> np.ndarray:
    values = np.asarray(pixels, dtype=np.float32)
    if high <= low:
        scaled = np.zeros(values.shape, dtype=np.uint8)
    else:
        scaled = np.clip((values - low) * (255.0 / (high - low)), 0, 255).astype(
            np.uint8
        )
    return 255 - scaled if inverted else scaled


def _fit_grayscale(array: np.ndarray, size: tuple[int, int]) -> Image.Image:
    image = Image.fromarray(array, mode="L")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "black")
    canvas.paste(image.convert("RGB"), ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def _safe_role(request: LegionConsultRequest, key: str, ordinal: int) -> str:
    labels = []
    if key == request.selection.source_series_key:
        labels.append("source")
    if key == request.selection.t1_series_key:
        labels.append("T1")
    if key == request.selection.t2_series_key:
        labels.append("T2")
    return "+".join(labels) if labels else f"optional-{ordinal}"


def _draw_overview(
    volume: SeriesVolume,
    low: float,
    high: float,
    indices: Sequence[int],
    projection: ROIProjection,
    role: str,
    plane: str,
) -> Image.Image:
    columns = 5
    rows = int(math.ceil(len(indices) / columns))
    header_height = 34
    page = Image.new("RGB", (columns * TILE_SIZE[0], header_height + rows * TILE_SIZE[1]), "black")
    draw = ImageDraw.Draw(page)
    font = ImageFont.load_default()
    draw.text((8, 8), f"{role} | {plane} | complete stack overview", fill="white", font=font)
    focus = set(focus_slice_indices(projection.center_slice, volume.depth, 5))
    for position, index in enumerate(indices):
        x = (position % columns) * TILE_SIZE[0]
        y = header_height + (position // columns) * TILE_SIZE[1]
        display_slice = _display_slice(
            volume.pixels[index], low, high, volume.inverted
        )
        tile = _fit_grayscale(display_slice, TILE_SIZE)
        page.paste(tile, (x, y))
        draw.rectangle(
            (x + 1, y + 1, x + TILE_SIZE[0] - 2, y + TILE_SIZE[1] - 2),
            outline="#ef4444" if index in focus else "#334155",
            width=3 if index in focus else 1,
        )
        draw.text((x + 7, y + 6), f"slice {index + 1}/{volume.depth}", fill="white", font=font)
    return page


def _draw_focus(
    display_slice: np.ndarray,
    projection: ROIProjection,
    slice_index: int,
    depth: int,
    role: str,
    plane: str,
) -> Image.Image:
    x0, y0, x1, y1 = projection.bounds
    context = _fit_grayscale(display_slice, (512, 512))
    scale = min(512 / display_slice.shape[1], 512 / display_slice.shape[0])
    offset_x = (512 - display_slice.shape[1] * scale) / 2.0
    offset_y = (512 - display_slice.shape[0] * scale) / 2.0
    context_draw = ImageDraw.Draw(context)
    context_draw.rectangle(
        (
            int(offset_x + x0 * scale),
            int(offset_y + y0 * scale),
            int(offset_x + x1 * scale),
            int(offset_y + y1 * scale),
        ),
        outline="#ef4444",
        width=3,
    )

    margin_x = max((x1 - x0), 8)
    margin_y = max((y1 - y0), 8)
    crop_bounds = (
        max(0, x0 - margin_x),
        max(0, y0 - margin_y),
        min(display_slice.shape[1], x1 + margin_x),
        min(display_slice.shape[0], y1 + margin_y),
    )
    crop = display_slice[crop_bounds[1] : crop_bounds[3], crop_bounds[0] : crop_bounds[2]]
    zoom = _fit_grayscale(crop, (512, 512))
    page = Image.new("RGB", (1024, 548), "black")
    page.paste(context, (0, 36))
    page.paste(zoom, (512, 36))
    draw = ImageDraw.Draw(page)
    draw.text(
        (8, 10),
        f"{role} | {plane} | slice {slice_index + 1}/{depth} | context + ROI zoom",
        fill="white",
        font=ImageFont.load_default(),
    )
    return page


def _atomic_json(path: Path, document: dict) -> None:
    temporary = path.with_name(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _candidate_map(candidates: Iterable[SeriesCandidate]) -> dict[str, SeriesCandidate]:
    return {series_key(candidate): candidate for candidate in candidates}


def build_evidence_package(
    request: LegionConsultRequest,
    candidates: Sequence[SeriesCandidate],
    session_dir: str | Path,
) -> AnalysisPackage:
    """Render selected MRI evidence and return the two-stage analysis package."""
    root = Path(session_dir)
    root.mkdir(parents=True, exist_ok=True)
    evidence_dir = root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    by_key = _candidate_map(candidates)
    entries: list[dict] = []
    packaged: list[PackagedImage] = []
    series_summaries: list[dict] = []

    for ordinal, key in enumerate(request.selection.selected_series_keys, start=1):
        candidate = by_key.get(key)
        if candidate is None:
            raise EvidenceError("A selected MRI series could not be matched for analysis.")
        volume = load_series_volume(candidate)
        low, high = _intensity_window(volume)
        projection = project_patient_roi(
            volume, request.attention_anchor.patient_lps_corners
        )
        role = _safe_role(request, key, ordinal)
        plane = str(volume.plane or "unknown")
        focus_indices = focus_slice_indices(
            projection.center_slice, volume.depth, request.slice_padding
        )
        overview_pages = overview_page_indices(volume.depth)
        series_summaries.append(
            {
                "role": role,
                "plane": plane,
                "slice_count": volume.depth,
                "projected_center_slice": projection.center_slice,
                "focus_slice_count": len(focus_indices),
                "overview_page_count": len(overview_pages),
            }
        )

        for page_number, indices in enumerate(overview_pages, start=1):
            filename = f"series_{ordinal:02d}_overview_{page_number:02d}.png"
            path = evidence_dir / filename
            _draw_overview(
                volume, low, high, indices, projection, role, plane
            ).save(path, "PNG", optimize=True)
            caption = (
                f"Series {ordinal} ({role}, {plane}) complete-stack overview page "
                f"{page_number}/{len(overview_pages)}; contains slices "
                f"{indices[0] + 1}-{indices[-1] + 1} of {volume.depth}. "
                "Red borders mark the projected ROI-centered context range."
            )
            entry = {
                "file": f"evidence/{filename}",
                "caption": caption,
                "session": f"series-{ordinal}-overview",
                "index": page_number,
                "kind": "complete_stack_overview",
            }
            entries.append(entry)
            packaged.append(PackagedImage(path, caption, entry["session"], page_number))

        for focus_number, index in enumerate(focus_indices, start=1):
            filename = f"series_{ordinal:02d}_focus_{focus_number:02d}.png"
            path = evidence_dir / filename
            display_slice = _display_slice(
                volume.pixels[index], low, high, volume.inverted
            )
            _draw_focus(
                display_slice, projection, index, volume.depth, role, plane
            ).save(path, "PNG", optimize=True)
            caption = (
                f"Series {ordinal} ({role}, {plane}) lesion-focused slice "
                f"{index + 1}/{volume.depth}; left panel is full anatomical context "
                "with projected ROI box, right panel is an enlarged ROI neighborhood."
            )
            entry = {
                "file": f"evidence/{filename}",
                "caption": caption,
                "session": f"series-{ordinal}-focus",
                "index": focus_number,
                "kind": "roi_context_and_zoom",
            }
            entries.append(entry)
            packaged.append(PackagedImage(path, caption, entry["session"], focus_number))

    if not packaged:
        raise EvidenceError("No MRI evidence images were generated.")

    manifest = {
        "schema_version": 1,
        "session_id": request.session_id,
        "protocol_id": LEGION_ANALYSIS_PIPELINE.id,
        "coverage": (
            "Every selected stack is represented in full by overview contact sheets; "
            "the projected ROI is also represented at full context and zoom for the "
            "center slice plus up to five slices on each side."
        ),
        "series": series_summaries,
        "images": entries,
    }
    _atomic_json(root / EVIDENCE_MANIFEST, manifest)
    return _package_from_document(root, request.selection.study_uid, manifest)


def _package_from_document(root: Path, study_uid: str, manifest: dict) -> AnalysisPackage:
    images: list[PackagedImage] = []
    for entry in manifest.get("images") or ():
        path = root / str(entry.get("file") or "")
        if not path.is_file():
            raise EvidenceError("A persisted Legion Consult evidence image is missing.")
        images.append(
            PackagedImage(
                path=path,
                caption=str(entry.get("caption") or ""),
                session=str(entry.get("session") or "evidence"),
                index=int(entry.get("index") or 0),
            )
        )
    if not images:
        raise EvidenceError("The Legion Consult evidence manifest contains no images.")
    series_lines = [
        f"  Series {number}: role={item.get('role')}, plane={item.get('plane')}, "
        f"complete stack={item.get('slice_count')} slices, "
        f"ROI center slice={int(item.get('projected_center_slice') or 0) + 1}, "
        f"focused slices={item.get('focus_slice_count')}"
        for number, item in enumerate(manifest.get("series") or (), start=1)
    ]
    header = "\n".join(
        [
            "LEGION CONSULT MRI EVIDENCE PACKAGE",
            "  patient: PID 0",
            "  The radiologist-drawn ROI is an attention hint, not a segmentation or diagnosis.",
            "  Complete-stack overview pages and projected ROI-focused images follow.",
            "  Correlate all images across planes and sequences as one target.",
            *series_lines,
            f"  Total derived evidence images: {len(images)}",
        ]
    )
    return AnalysisPackage(
        session_dir=root,
        session_id=str(manifest.get("session_id") or root.name),
        protocol_id=LEGION_ANALYSIS_PIPELINE.id,
        analysis=LEGION_ANALYSIS_PIPELINE,
        header=header,
        images=images,
        study_instance_uid=study_uid,
    )


def load_evidence_package(
    session_dir: str | Path, *, study_uid: str = ""
) -> AnalysisPackage:
    """Rebuild a retry package from persisted derived images only."""
    root = Path(session_dir)
    try:
        manifest = json.loads((root / EVIDENCE_MANIFEST).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvidenceError("The Legion Consult evidence package has not been prepared.") from exc
    except (OSError, ValueError) as exc:
        raise EvidenceError("The Legion Consult evidence manifest is unreadable.") from exc
    return _package_from_document(root, study_uid, manifest)
