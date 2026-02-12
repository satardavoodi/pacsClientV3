"""Datamodels for the printing module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class FilmSize:
    """Physical film size in inches."""

    name: str
    width_in: float
    height_in: float


@dataclass(frozen=True)
class FilmLayout:
    """Layout grid and spacing for a film sheet."""

    rows: int
    cols: int
    margin_in: float = 0.25
    gutter_in: float = 0.05


@dataclass(frozen=True)
class ViewportState:
    """Viewport adjustments for an image."""

    window_width: Optional[float] = None
    window_level: Optional[float] = None
    zoom: float = 1.0
    pan: Tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class ImageSelection:
    """Selection range for images within a series."""

    series_uid: str
    image_indices: List[int]
    viewport: ViewportState = field(default_factory=ViewportState)


@dataclass(frozen=True)
class SeriesSelection:
    """Selection for one or more series contributing to a film."""

    study_uid: str
    series_uids: List[str]
    image_selections: List[ImageSelection]


@dataclass(frozen=True)
class PrinterConfig:
    """Printer configuration for OS or DICOM printers."""

    name: str
    printer_type: str  # "os" or "dicom"
    settings: Dict[str, str] = field(default_factory=dict)


@dataclass
class PrintJob:
    """A complete print job description."""

    patient_id: str
    patient_name: str
    study_uid: str
    film_size: FilmSize
    layout: FilmLayout
    series_selection: SeriesSelection
    printer: PrinterConfig
    metadata: Dict[str, str] = field(default_factory=dict)
