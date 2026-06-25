# -*- coding: utf-8 -*-
"""Data-source contract for the Dental Imaging module.

The module receives the *currently active* series from the Patient Viewer as a
``DentalSeriesContext`` — a lightweight, pure-stdlib handle (no Qt / no VTK) into
the SAME safe series/MPR infrastructure the rest of the app already uses: the
``series_path`` DICOM directory + identifiers + window/level that the Advanced
MPR and Stitching launchers already pass today.

It is intentionally a *handle*, not a volume. Later milestones turn ``dicom_dir``
into a volume via the shared
``modules/viewer/fast/pydicom_lazy_volume.py::PyDicomLazyVolume`` and the
standard-MPR geometry contract. This module must NEVER build its own volume or
geometry system (see README.md → "Shared core, do not duplicate").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class DentalSeriesContext:
    """Everything the workspace needs to (later) load the active series.

    All fields optional so a workspace can open even with nothing selected
    (it then shows an empty shell rather than failing).
    """

    dicom_dir: Optional[str] = None        # series_path — the on-disk DICOM dir
    series_uid: Optional[str] = None
    series_number: Optional[Any] = None
    window_width: Optional[float] = None
    window_level: Optional[float] = None
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    study_uid: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def is_loadable(self) -> bool:
        """True when there is a DICOM directory the module can load from."""
        return bool(self.dicom_dir)

    def summary(self) -> str:
        """One-line human summary for the workspace header/status."""
        sn = self.series_number if self.series_number is not None else "?"
        who = self.patient_name or self.patient_id or "—"
        return f"{who} · Series {sn} · UID {self.series_uid or '—'}"
