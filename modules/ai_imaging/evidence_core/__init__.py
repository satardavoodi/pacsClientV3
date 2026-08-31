"""Shared, headless DICOM evidence primitives for AI imaging workflows."""

from .budget import EvidenceBudget, EvidenceUsage
from .quality import EvidenceQuality, inspect_image_quality
from .volume import (
    DicomSlice,
    DicomSliceStack,
    EvidenceError,
    ROIProjection,
    SeriesVolume,
    display_slice,
    fit_grayscale,
    focus_slice_indices,
    horizontal_patient_orientation,
    horizontal_patient_orientation_for_slice,
    intensity_window,
    intensity_window_slices,
    load_dicom_slice_stack,
    load_series_volume,
    overview_page_indices,
    project_patient_roi,
)

__all__ = (
    "EvidenceBudget",
    "DicomSlice",
    "DicomSliceStack",
    "EvidenceError",
    "EvidenceQuality",
    "EvidenceUsage",
    "ROIProjection",
    "SeriesVolume",
    "display_slice",
    "fit_grayscale",
    "focus_slice_indices",
    "horizontal_patient_orientation",
    "horizontal_patient_orientation_for_slice",
    "inspect_image_quality",
    "intensity_window",
    "intensity_window_slices",
    "load_dicom_slice_stack",
    "load_series_volume",
    "overview_page_indices",
    "project_patient_roi",
)
