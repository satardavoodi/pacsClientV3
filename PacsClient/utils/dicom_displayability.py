"""Low-cost local DICOM pixel-payload classification.

The patient image viewer must not treat SR, presentation-state, or other
metadata-only DICOM objects as one-slice image series.  These helpers inspect
only the pixel element headers and defer the pixel value itself, so callers can
classify local series without decoding or loading large cine payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydicom.filereader import read_partial
from pydicom.tag import Tag


PIXEL_DATA_TAGS = (
    Tag(0x7FE0, 0x0010),  # Pixel Data
    Tag(0x7FE0, 0x0008),  # Float Pixel Data
    Tag(0x7FE0, 0x0009),  # Double Float Pixel Data
)


@dataclass(frozen=True)
class SeriesPixelInventory:
    """Displayability summary for one local series directory."""

    instance_count: int = 0
    pixel_instance_count: int = 0
    frame_count: int = 0

    @property
    def has_pixel_data(self) -> bool:
        return self.pixel_instance_count > 0

    @property
    def display_image_count(self) -> int:
        """Number of viewport frames represented by the series."""
        return self.frame_count or self.pixel_instance_count


def _dicom_file_pixel_facts(file_path: str | Path) -> tuple[bool, int]:
    """Return pixel-element presence and NumberOfFrames without pixel decode."""

    found_pixel_data = False

    def _stop_at_pixel_data(tag, _vr, _length) -> bool:
        nonlocal found_pixel_data
        if tag in PIXEL_DATA_TAGS:
            found_pixel_data = True
            return True
        return False

    try:
        with Path(file_path).open("rb") as stream:
            dataset = read_partial(stream, stop_when=_stop_at_pixel_data, force=True)
    except Exception:
        return False, 0
    if not found_pixel_data:
        return False, 0
    try:
        frames = max(1, int(getattr(dataset, "NumberOfFrames", 1) or 1))
    except (TypeError, ValueError):
        frames = 1
    return True, frames


def dicom_file_has_pixel_data(file_path: str | Path) -> bool:
    """Inspect pixel-element presence without reading the pixel value."""
    return _dicom_file_pixel_facts(file_path)[0]


def inspect_series_pixel_inventory(series_path: str | Path) -> SeriesPixelInventory:
    """Count DICOM objects and pixel-bearing objects in a local series folder."""

    root = Path(str(series_path or ""))
    if not root.is_dir():
        return SeriesPixelInventory()

    files = sorted(path for path in root.glob("*.dcm") if path.is_file())
    pixel_instance_count = 0
    frame_count = 0
    for path in files:
        has_pixel_data, frames = _dicom_file_pixel_facts(path)
        if has_pixel_data:
            pixel_instance_count += 1
            frame_count += frames
    return SeriesPixelInventory(
        instance_count=len(files),
        pixel_instance_count=pixel_instance_count,
        frame_count=frame_count,
    )
