# -*- coding: utf-8 -*-
"""Bind the active Patient-Viewer series to a ``DentalVolume`` — by REUSE.

The active viewer already holds the shared volume at
``selected_widget.image_viewer.vtk_image_data`` (built by the FAST pipeline /
``PyDicomLazyVolume`` and consumed by the 2D viewer + standard MPR + the simple
Dental Curve MPR). Milestone 1 **reuses that exact handle** — it does not rebuild
a volume or fork a pipeline, which is the whole point of the unified-MPR direction.

A future step may add a ``PyDicomLazyVolume.from_series(study_path, metadata)``
fallback to bind a *non-active* series (e.g. one the user picked but isn't viewing);
that is intentionally out of scope here to keep Milestone 1 minimal and safe.

Duck-typed (no Qt/VTK import) so it stays import-light and headless-testable.
"""
from __future__ import annotations

from typing import Any, Optional

from .volume import DentalVolume


def get_active_image_data(patient_widget: Any) -> Any:
    """Return the active viewer's shared ``vtk_image_data``, or ``None``."""
    sw = getattr(patient_widget, "selected_widget", None)
    iv = getattr(sw, "image_viewer", None) if sw is not None else None
    if iv is None:
        return None
    return getattr(iv, "vtk_image_data", None)


def _active_modality(patient_widget: Any) -> str:
    sw = getattr(patient_widget, "selected_widget", None)
    iv = getattr(sw, "image_viewer", None) if sw is not None else None
    md = getattr(iv, "metadata", None) if iv is not None else None
    try:
        return str((md or {}).get("series", {}).get("modality", "") or "")
    except Exception:
        return ""


def materialize_lazy_volume(lazy: Any, *, max_slices: int = 8192) -> int:
    """Force a ``PyDicomLazyVolume`` to FULLY DECODE its slices synchronously.

    ``PyDicomLazyVolume.from_series`` (the non-active-series bind path) returns a
    LAZY volume — a zero-filled memmap whose slices the viewer decodes on demand.
    The dental previews / reconstruction read the volume IMMEDIATELY, so without
    this the middle Axial slice is blank and the volume is ~all zeros ("the series
    is not imported correctly"). We decode every slice via the blocking decoder,
    then refresh the VTK scalars so the now-complete memmap is what renders.

    Duck-typed + fully guarded (no Qt/VTK import): returns the number of slices
    decoded (0 if the object isn't a lazy volume / lacks the API). Never raises.
    The active-viewer reuse path is unaffected — that volume is already decoded.
    """
    if lazy is None:
        return 0
    decode = getattr(lazy, "_load_slice_blocking", None)
    if not callable(decode):
        return 0
    try:
        count = int(getattr(lazy, "slice_count", 0) or 0)
    except Exception:
        count = 0
    count = min(count, int(max_slices))
    loaded = 0
    for i in range(count):
        try:
            if decode(i, emit_signal=False):
                loaded += 1
        except Exception:
            break
    refresh = getattr(lazy, "mark_vtk_modified", None)
    if callable(refresh):
        try:
            refresh()
        except Exception:
            pass
    return loaded


def bind_active_viewer_volume(patient_widget: Any, series_uid: Optional[str] = None) -> Optional[DentalVolume]:
    """Wrap the active viewer's shared volume as a ``DentalVolume`` (reuse, no copy).

    Returns ``None`` when there is no active viewer / no built volume, or when the
    volume is not valid — the workspace then shows an empty shell rather than
    failing.
    """
    img = get_active_image_data(patient_widget)
    if img is None:
        return None
    dvol = DentalVolume(img, modality=_active_modality(patient_widget), series_uid=series_uid)
    return dvol if dvol.is_valid() else None
