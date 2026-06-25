# -*- coding: utf-8 -*-
"""DentalVolume — single source of truth for the bound CBCT volume + geometry.

Wraps the SHARED ``vtk_image_data`` already built by the FAST viewer /
``PyDicomLazyVolume`` (the very handle the 2D viewer, standard MPR, and the simple
Dental Curve MPR all consume). It does **not** build, copy, or recompute a volume
or its geometry — it only READS dimensions / spacing / origin / direction off the
shared image data, exactly as the existing viewport-sync code already does
(``_pw_sync.py`` reads ``viewer.vtk_image_data.GetDimensions()/GetSpacing()``).

It operates on a *duck-typed* image-data object (anything exposing
``GetDimensions`` / ``GetSpacing`` / ``GetOrigin`` / ``GetFieldData``), so it needs
no VTK import and is unit-testable headless with a tiny fake.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

# Row-major 4x4 identity, used when the shared volume carries no DirectionMatrix.
_IDENTITY_4 = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]


class DentalVolume:
    """Read-only geometry handle over the shared ``vtk_image_data``."""

    def __init__(self, image_data: Any, modality: str = "", series_uid: Optional[str] = None):
        # NOTE: this is a *reference* to the shared volume, not a copy. The dental
        # workspace only reads geometry here (Milestone 1); it must never mutate
        # the shared image data.
        self._img = image_data
        self.modality = (modality or "").upper()
        self.series_uid = series_uid

    @property
    def image_data(self) -> Any:
        return self._img

    def is_valid(self) -> bool:
        try:
            return all(int(x) > 0 for x in self.dimensions)
        except Exception:
            return False

    @property
    def dimensions(self) -> Tuple[int, int, int]:
        d = self._img.GetDimensions()
        return (int(d[0]), int(d[1]), int(d[2]))

    @property
    def spacing(self) -> Tuple[float, float, float]:
        s = self._img.GetSpacing()
        return (float(s[0]), float(s[1]), float(s[2]))

    @property
    def origin(self) -> Tuple[float, float, float]:
        o = self._img.GetOrigin()
        return (float(o[0]), float(o[1]), float(o[2]))

    @property
    def direction_matrix(self) -> List[float]:
        """Row-major 4x4 direction read from the shared ``DirectionMatrix``
        field-data array (the SAME array ``PyDicomLazyVolume`` attaches from the
        DICOM Image Orientation Patient). Identity if absent — never recomputed
        here, to keep ONE geometry source."""
        try:
            fd = self._img.GetFieldData()
            arr = fd.GetArray("DirectionMatrix") if fd is not None else None
            if arr is not None and arr.GetNumberOfTuples() >= 16:
                return [float(arr.GetValue(i)) for i in range(16)]
        except Exception:
            pass
        return list(_IDENTITY_4)

    def slice_count(self) -> int:
        return self.dimensions[2]

    def summary(self) -> str:
        if not self.is_valid():
            return "no valid volume"
        dx, dy, dz = self.dimensions
        sx, sy, sz = self.spacing
        mod = self.modality or "—"
        return f"{mod} · {dx}×{dy}×{dz} vox · {sx:.3f}×{sy:.3f}×{sz:.3f} mm"
