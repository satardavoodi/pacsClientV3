"""Build a PNG-only multimodal request package from DX wrist DICOM files."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .analysis_prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_WRIST_HINTS = (
    "wrist", "hand", "carpal", "scaphoid", "distal radius", "distal ulna",
)
_DICOM_SUFFIXES = {".dcm", ".dicom"}


class PackageError(RuntimeError):
    """The selected study is not a readable DX wrist study."""


@dataclass(frozen=True)
class DXWristImage:
    path: Path
    caption: str
    mime: str = "image/png"


@dataclass(frozen=True)
class DXWristPackage:
    study_uid: str
    output_dir: Path
    images: list[DXWristImage]
    system_prompt: str = SYSTEM_PROMPT

    @property
    def header(self) -> str:
        return (
            "DX wrist radiograph analysis. Review all supplied views together. "
            "Return bone age estimate, reasoning, and pathological findings."
        )


def _is_wrist_dataset(dataset: Any) -> bool:
    values = (
        getattr(dataset, "BodyPartExamined", ""),
        getattr(dataset, "StudyDescription", ""),
        getattr(dataset, "SeriesDescription", ""),
        getattr(dataset, "ProtocolName", ""),
    )
    text = " ".join(str(value or "").lower() for value in values)
    return any(hint in text for hint in _WRIST_HINTS)


def _candidate_files(source_dir: Path) -> list[Path]:
    files = []
    for path in sorted(source_dir.rglob("*")):
        if path.is_file() and (path.suffix.lower() in _DICOM_SUFFIXES or not path.suffix):
            files.append(path)
    return files


def _dicom_to_png(source: Path, destination: Path) -> None:
    import numpy as np
    import pydicom
    from PIL import Image

    dataset = pydicom.dcmread(str(source), force=True)
    array = np.asarray(dataset.pixel_array)
    if array.ndim > 2:
        array = array[0]
    array = array.astype(np.float32, copy=False)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        raise PackageError(f"No usable pixels in {source.name}")
    low, high = np.percentile(finite, [1.0, 99.0])
    if high <= low:
        low, high = float(finite.min()), float(finite.max())
    if high <= low:
        normalized = np.zeros(array.shape, dtype=np.uint8)
    else:
        normalized = np.clip((array - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)
    if str(getattr(dataset, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
        normalized = 255 - normalized
    Image.fromarray(normalized, mode="L").save(str(destination), "PNG")


def build_package(study_uid: str, source_dir: str | Path, output_dir: str | Path | None = None) -> DXWristPackage:
    """Validate a DX wrist study and create isolated PNG request files."""
    import pydicom

    source = Path(source_dir)
    if not source.is_dir():
        raise PackageError("The DX wrist source folder is unavailable.")
    candidates = _candidate_files(source)
    if not candidates:
        raise PackageError("No DICOM images were found for the DX wrist study.")

    selected: list[tuple[Path, Any]] = []
    for path in candidates:
        try:
            dataset = pydicom.dcmread(str(path), stop_before_pixels=False, force=True)
            modality = str(getattr(dataset, "Modality", "") or "").upper()
            if modality in {"DX", "CR"} and _is_wrist_dataset(dataset):
                selected.append((path, dataset))
        except Exception:
            continue
    if not selected:
        raise PackageError("The selected study does not contain a readable DX wrist image.")

    target = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="dx_wrist_ai_"))
    target.mkdir(parents=True, exist_ok=True)
    images: list[DXWristImage] = []
    for index, (source_path, dataset) in enumerate(selected, start=1):
        png_path = target / f"wrist_{index:03d}.png"
        _dicom_to_png(source_path, png_path)
        view = str(getattr(dataset, "ViewPosition", "") or "unknown")
        images.append(DXWristImage(png_path, f"DX wrist view {index}: {view}"))
    return DXWristPackage(str(study_uid or ""), target, images)
