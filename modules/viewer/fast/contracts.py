from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple

from PySide6.QtGui import QImage


@dataclass(frozen=True)
class FrameData:
    image: QImage
    width: int
    height: int
    photometric: str
    dtype: str
    window_applied: bool


@dataclass(frozen=True)
class GeometryData:
    image_position_patient: Tuple[float, float, float]
    image_orientation_patient: Tuple[float, float, float, float, float, float]
    pixel_spacing: Tuple[float, float]
    slice_thickness: Optional[float]
    spacing_between_slices: Optional[float]
    rows: int
    cols: int


class IViewer2DBackend(Protocol):
    def open_series(self, series_path: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        ...

    def close_series(self) -> None:
        ...

    @property
    def capabilities(self) -> Dict[str, Any]:
        ...

    def get_slice_count(self) -> int:
        ...

    def get_frame(self, slice_index: int) -> FrameData:
        ...

    def get_geometry(self, slice_index: int) -> GeometryData:
        ...

    def image_xy_to_patient_xyz(self, x: float, y: float, slice_index: int) -> Tuple[float, float, float]:
        ...

    def patient_xyz_to_image_xy(self, xyz: Tuple[float, float, float], slice_index: int) -> Tuple[float, float]:
        ...

    def set_window_level(self, window: Optional[float], level: Optional[float]) -> None:
        ...

    def set_slice_index(self, index: int) -> None:
        ...

    def get_window_level(self) -> Tuple[Optional[float], Optional[float]]:
        ...

    def get_file_paths(self) -> List[str]:
        ...

