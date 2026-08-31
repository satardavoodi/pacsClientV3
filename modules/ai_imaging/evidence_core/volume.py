"""Geometry-preserving DICOM volume loading and grayscale rendering helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image


MIN_PROJECTED_ROI_SIZE = 12
MAX_DICOM_EVIDENCE_SLICES = 1024


class EvidenceError(RuntimeError):
    """Selected DICOM evidence cannot be prepared safely."""


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
            raise ValueError("Evidence preparation requires a 3D scalar image volume.")
        if not all(int(size) > 0 for size in pixels.shape):
            raise ValueError("Evidence preparation received an empty 3D volume.")
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

    def continuous_index_to_patient(
        self, index: Sequence[float]
    ) -> tuple[float, float, float]:
        """Map continuous x/y/z voxel indices to patient LPS millimetres."""
        if len(index) < 3:
            raise ValueError("A volume index requires three coordinates.")
        direction = np.asarray(self.direction, dtype=np.float64).reshape(3, 3)
        axis_distance = np.asarray(index[:3], dtype=np.float64) * np.asarray(
            self.spacing, dtype=np.float64
        )
        point = np.asarray(self.origin, dtype=np.float64) + direction @ axis_distance
        return tuple(float(value) for value in point)


@dataclass(frozen=True)
class DicomSlice:
    """One decoded DICOM slice with its own patient-space geometry."""

    pixels: np.ndarray
    position_lps: tuple[float, float, float]
    orientation_lps: tuple[float, float, float, float, float, float]
    pixel_spacing: tuple[float, float]
    source_ordinal: int
    inverted: bool = False

    def __post_init__(self) -> None:
        pixels = np.asarray(self.pixels)
        if pixels.ndim != 2 or not all(int(size) > 0 for size in pixels.shape):
            raise ValueError("DICOM evidence requires a non-empty 2D scalar slice.")
        if len(self.position_lps) != 3 or len(self.orientation_lps) != 6:
            raise ValueError("The DICOM slice patient geometry is incomplete.")
        if len(self.pixel_spacing) != 2 or any(
            float(value) <= 0 for value in self.pixel_spacing
        ):
            raise ValueError("The DICOM slice pixel spacing is invalid.")
        geometry = (*self.position_lps, *self.orientation_lps, *self.pixel_spacing)
        if not all(math.isfinite(float(value)) for value in geometry):
            raise ValueError("The DICOM slice patient geometry is non-finite.")
        if int(self.source_ordinal) <= 0:
            raise ValueError("The DICOM source ordinal must be positive.")

        row = np.asarray(self.orientation_lps[:3], dtype=np.float64)
        column = np.asarray(self.orientation_lps[3:], dtype=np.float64)
        if (
            np.linalg.norm(row) < 0.5
            or np.linalg.norm(column) < 0.5
            or abs(float(np.dot(row, column))) > 0.05
        ):
            raise ValueError("The DICOM slice orientation vectors are invalid.")

    @property
    def height(self) -> int:
        return int(np.asarray(self.pixels).shape[0])

    @property
    def width(self) -> int:
        return int(np.asarray(self.pixels).shape[1])

    @property
    def center_lps(self) -> tuple[float, float, float]:
        """Return the physical center of this slice, not its top-left DICOM origin."""
        row = np.asarray(self.orientation_lps[:3], dtype=np.float64)
        column = np.asarray(self.orientation_lps[3:], dtype=np.float64)
        row /= np.linalg.norm(row)
        column /= np.linalg.norm(column)
        row_spacing, column_spacing = (float(value) for value in self.pixel_spacing)
        point = (
            np.asarray(self.position_lps, dtype=np.float64)
            + row * column_spacing * ((self.width - 1) / 2.0)
            + column * row_spacing * ((self.height - 1) / 2.0)
        )
        return tuple(float(value) for value in point)


@dataclass(frozen=True)
class DicomSliceStack:
    """A bounded set of independently oriented DICOM slices."""

    slices: tuple[DicomSlice, ...]
    plane: str = "unknown"

    def __post_init__(self) -> None:
        if not self.slices:
            raise ValueError("DICOM evidence received an empty slice stack.")
        if len(self.slices) > MAX_DICOM_EVIDENCE_SLICES:
            raise ValueError("The DICOM evidence slice count exceeds the safety limit.")
        ordinals = [int(item.source_ordinal) for item in self.slices]
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("The DICOM evidence source ordinals are not unique.")

    @property
    def depth(self) -> int:
        return len(self.slices)


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


def horizontal_patient_orientation(
    volume: SeriesVolume, minimum_axis_alignment: float = 0.75
) -> tuple[str, str] | None:
    """Return patient labels for the displayed left and right image edges."""
    direction = np.asarray(volume.direction, dtype=np.float64).reshape(3, 3)
    rightward = direction[:, 0]
    axis = int(np.argmax(np.abs(rightward)))
    if abs(float(rightward[axis])) < float(minimum_axis_alignment):
        return None
    positive = ("L", "P", "S")[axis]
    negative = ("R", "A", "I")[axis]
    right_label = positive if rightward[axis] > 0 else negative
    left_label = negative if rightward[axis] > 0 else positive
    return left_label, right_label


def horizontal_patient_orientation_for_slice(
    image_slice: DicomSlice, minimum_axis_alignment: float = 0.75
) -> tuple[str, str] | None:
    """Return patient labels for the horizontal edges of one DICOM slice."""
    rightward = np.asarray(image_slice.orientation_lps[:3], dtype=np.float64)
    axis = int(np.argmax(np.abs(rightward)))
    if abs(float(rightward[axis])) < float(minimum_axis_alignment):
        return None
    positive = ("L", "P", "S")[axis]
    negative = ("R", "A", "I")[axis]
    right_label = positive if rightward[axis] > 0 else negative
    left_label = negative if rightward[axis] > 0 else positive
    return left_label, right_label


def overview_page_indices(
    depth: int, tiles_per_page: int = 20
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
    """Project four patient-space ROI corners into one selected series."""
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


def _dicom_files(candidate: Any) -> list[str]:
    directory = Path(str(getattr(candidate, "series_path", "") or ""))
    if not directory.is_dir():
        raise EvidenceError("A selected MRI series is no longer available locally.")
    try:
        import SimpleITK as sitk

        series_uid = str(getattr(candidate, "series_uid", "") or "")
        filenames = list(
            sitk.ImageSeriesReader.GetGDCMSeriesFileNames(
                str(directory), series_uid
            )
        )
        if not filenames and not series_uid:
            filenames = list(sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(directory)))
    except Exception as exc:
        raise EvidenceError("The selected MRI series headers could not be indexed.") from exc
    if not filenames:
        raise EvidenceError("A selected MRI series contains no readable DICOM images.")
    return filenames


def _reject_burned_annotations(first_file: str) -> bool:
    """Fail closed when DICOM explicitly declares burned-in annotation."""
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


def _read_slice_header(filename: str) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float, float, float, float],
    tuple[float, float],
    bool,
]:
    try:
        import pydicom

        dataset = pydicom.dcmread(
            filename,
            stop_before_pixels=True,
            specific_tags=[
                "BurnedInAnnotation",
                "ImageOrientationPatient",
                "ImagePositionPatient",
                "PhotometricInterpretation",
                "PixelSpacing",
            ],
        )
        if str(getattr(dataset, "BurnedInAnnotation", "") or "").strip().upper() == "YES":
            raise EvidenceError(
                "A selected series declares burned-in annotations and cannot be sent safely."
            )
        position = tuple(float(value) for value in dataset.ImagePositionPatient)
        orientation = tuple(float(value) for value in dataset.ImageOrientationPatient)
        spacing = tuple(float(value) for value in dataset.PixelSpacing)
        inverted = (
            str(getattr(dataset, "PhotometricInterpretation", "") or "").upper()
            == "MONOCHROME1"
        )
    except EvidenceError:
        raise
    except Exception as exc:
        raise EvidenceError("A selected MRI slice has incomplete DICOM geometry.") from exc
    if len(position) != 3 or len(orientation) != 6 or len(spacing) != 2:
        raise EvidenceError("A selected MRI slice has incomplete DICOM geometry.")
    return position, orientation, spacing, inverted


def _decode_single_slice(filename: str) -> np.ndarray:
    try:
        import SimpleITK as sitk

        image = sitk.ReadImage(filename)
        pixels = np.asarray(sitk.GetArrayFromImage(image))
    except Exception as exc:
        raise EvidenceError("A selected MRI slice could not be decoded.") from exc
    while pixels.ndim > 2 and pixels.shape[0] == 1:
        pixels = pixels[0]
    if pixels.ndim != 2:
        raise EvidenceError("Focused evidence requires single-frame scalar DICOM slices.")
    return pixels


def load_dicom_slice_stack(candidate: Any) -> DicomSliceStack:
    """Decode a series without collapsing independently angled slabs into one affine."""
    filenames = _dicom_files(candidate)
    if len(filenames) > MAX_DICOM_EVIDENCE_SLICES:
        raise EvidenceError("The selected MRI series exceeds the evidence slice limit.")
    slices = []
    for ordinal, filename in enumerate(filenames, start=1):
        position, orientation, spacing, inverted = _read_slice_header(filename)
        try:
            slices.append(
                DicomSlice(
                    pixels=_decode_single_slice(filename),
                    position_lps=position,
                    orientation_lps=orientation,
                    pixel_spacing=spacing,
                    source_ordinal=ordinal,
                    inverted=inverted,
                )
            )
        except ValueError as exc:
            raise EvidenceError("A selected MRI slice has invalid DICOM geometry.") from exc
    return DicomSliceStack(
        slices=tuple(slices),
        plane=str(getattr(candidate, "plane", "") or "unknown"),
    )


def load_series_volume(candidate: Any) -> SeriesVolume:
    """Decode one selected DICOM series without constructing Qt or VTK objects."""
    filenames = _dicom_files(candidate)
    inverted = _reject_burned_annotations(filenames[0])
    try:
        import SimpleITK as sitk

        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(filenames)
        image = reader.Execute()
        if int(image.GetDimension()) != 3:
            raise EvidenceError("A selected MRI series is not a 3D image stack.")
        return SeriesVolume(
            pixels=np.asarray(sitk.GetArrayFromImage(image)),
            origin=tuple(float(value) for value in image.GetOrigin()),
            spacing=tuple(float(value) for value in image.GetSpacing()),
            direction=tuple(float(value) for value in image.GetDirection()),
            plane=str(getattr(candidate, "plane", "") or "unknown"),
            inverted=inverted,
        )
    except EvidenceError:
        raise
    except Exception as exc:
        raise EvidenceError("A selected MRI series could not be decoded.") from exc


def intensity_window(volume: SeriesVolume) -> tuple[float, float]:
    """Estimate a robust window from a bounded sample of the volume."""
    flat = np.asarray(volume.pixels).reshape(-1)
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


def intensity_window_slices(slices: Iterable[DicomSlice]) -> tuple[float, float]:
    """Estimate one stable display window across independently oriented slices."""
    arrays = [np.asarray(item.pixels) for item in slices]
    if not arrays:
        raise EvidenceError("A selected MRI series contains no slices to window.")
    total = sum(int(array.size) for array in arrays)
    stride = max(1, int(math.ceil(total / 1_000_000)))
    samples = [np.asarray(array.reshape(-1)[::stride], dtype=np.float32) for array in arrays]
    finite = np.concatenate([sample[np.isfinite(sample)] for sample in samples])
    if finite.size == 0:
        raise EvidenceError("A selected MRI series contains no finite pixel values.")
    low, high = np.percentile(finite, (1.0, 99.0))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(np.min(finite))
        high = float(np.max(finite))
    return float(low), float(high)


def display_slice(
    pixels: np.ndarray, low: float, high: float, inverted: bool
) -> np.ndarray:
    """Apply a fixed volume window to one slice and return 8-bit grayscale."""
    values = np.asarray(pixels, dtype=np.float32)
    if high <= low:
        scaled = np.zeros(values.shape, dtype=np.uint8)
    else:
        scaled = np.clip((values - low) * (255.0 / (high - low)), 0, 255).astype(
            np.uint8
        )
    return 255 - scaled if inverted else scaled


def fit_grayscale(array: np.ndarray, size: tuple[int, int]) -> Image.Image:
    """Letterbox grayscale pixels without ever upscaling the source image."""
    image = Image.fromarray(np.asarray(array, dtype=np.uint8), mode="L")
    target = (min(int(size[0]), image.width), min(int(size[1]), image.height))
    image.thumbnail(target, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "black")
    canvas.paste(
        image.convert("RGB"),
        ((size[0] - image.width) // 2, (size[1] - image.height) // 2),
    )
    return canvas
