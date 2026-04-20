from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import pydicom


_DICOM_SUFFIXES = {".dcm", ".dicom", ""}


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        if isinstance(value, (list, tuple)):
            if not value:
                return default
            value = value[0]
        return float(value)
    except Exception:
        return default


def _as_float_tuple(value: Any, n: int, default: Sequence[float]) -> tuple[float, ...]:
    try:
        if value is None:
            return tuple(float(x) for x in default[:n])
        seq = list(value)
        if len(seq) < n:
            return tuple(float(x) for x in default[:n])
        return tuple(float(seq[i]) for i in range(n))
    except Exception:
        return tuple(float(x) for x in default[:n])


@dataclass(frozen=True)
class DicomHeaderEntry:
    path: str
    rows: int
    cols: int
    pixel_spacing: tuple[float, float]
    iop: tuple[float, float, float, float, float, float]
    ipp: tuple[float, float, float]
    slice_thickness: Optional[float]
    spacing_between_slices: Optional[float]
    photometric: str
    bits_allocated: int
    pixel_representation: int
    samples_per_pixel: int
    window_width: Optional[float]
    window_center: Optional[float]
    slope: float
    intercept: float
    instance_number: Optional[int]
    is_rgb: bool


def entry_from_dataset(path: str, ds: pydicom.Dataset) -> DicomHeaderEntry:
    iop = _as_float_tuple(getattr(ds, "ImageOrientationPatient", None), 6, (1, 0, 0, 0, 1, 0))
    ipp = _as_float_tuple(getattr(ds, "ImagePositionPatient", None), 3, (0, 0, 0))
    ps = _as_float_tuple(getattr(ds, "PixelSpacing", None), 2, (1, 1))
    spp = int(getattr(ds, "SamplesPerPixel", 1) or 1)
    return DicomHeaderEntry(
        path=str(path),
        rows=int(getattr(ds, "Rows", 0) or 0),
        cols=int(getattr(ds, "Columns", 0) or 0),
        pixel_spacing=(float(ps[0]), float(ps[1])),
        iop=(float(iop[0]), float(iop[1]), float(iop[2]), float(iop[3]), float(iop[4]), float(iop[5])),
        ipp=(float(ipp[0]), float(ipp[1]), float(ipp[2])),
        slice_thickness=_safe_float(getattr(ds, "SliceThickness", None)),
        spacing_between_slices=_safe_float(getattr(ds, "SpacingBetweenSlices", None)),
        photometric=str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")),
        bits_allocated=int(getattr(ds, "BitsAllocated", 16) or 16),
        pixel_representation=int(getattr(ds, "PixelRepresentation", 1) or 1),
        samples_per_pixel=spp,
        window_width=_safe_float(getattr(ds, "WindowWidth", None)),
        window_center=_safe_float(getattr(ds, "WindowCenter", None)),
        slope=_safe_float(getattr(ds, "RescaleSlope", None), 1.0) or 1.0,
        intercept=_safe_float(getattr(ds, "RescaleIntercept", None), 0.0) or 0.0,
        instance_number=(
            int(getattr(ds, "InstanceNumber"))
            if getattr(ds, "InstanceNumber", None) is not None
            else None
        ),
        is_rgb=(spp >= 3),
    )


def scan_series_header_entries(
    series_path: str | Path,
    *,
    existing_paths: Optional[Iterable[str]] = None,
) -> list[DicomHeaderEntry]:
    series_dir = Path(series_path)
    if not series_dir.is_dir():
        return []

    existing = {str(p) for p in (existing_paths or ())}
    files = [
        p for p in series_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in _DICOM_SUFFIXES
        and str(p) not in existing
    ]

    out: list[DicomHeaderEntry] = []
    for path in sorted(files):
        try:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
            out.append(entry_from_dataset(str(path), ds))
        except Exception:
            continue
    return out