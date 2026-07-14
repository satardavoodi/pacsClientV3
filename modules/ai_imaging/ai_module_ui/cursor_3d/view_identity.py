"""
3D Cursor — ONE resolver for "which view is this viewer showing?" (R/L + CC/MLO).

WHY
---
The pickers used to read ONLY `image_viewer.metadata['series']['laterality' /
'view_position']`. On real mammography studies those keys are frequently EMPTY
(the acquisition puts the view in the DICOM header / series description, not in
our series metadata), so:

    • the legacy dialog said  "Please click the Nipple point in viewer **View**"
      (the `_get_view_info` fallback string), and
    • the guided flow could not identify CC vs MLO and fell back to the legacy flow.

Meanwhile `imaging_tab._extract_view_data_from_widget` — the code that feeds the
CORRELATOR — already had a DICOM-header fallback, which is why the correlation
itself worked. This module makes that resolution shared and complete:

    1. series metadata            (laterality / view_position, several key spellings)
    2. DICOM header of instance 0 (ImageLaterality | Laterality, ViewPosition)
    3. free text                  (series description / name, e.g. "R CC", "L-MLO")

Result is cached on the widget (`_cursor3d_view_identity`) so a click never pays a
dcmread. `parse_view_from_text` is pure and unit-tested.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple

# Mammography view positions we can act on. CC and MLO are the two the 3D Cursor
# correlates; the rest are recognised so we can say "unsupported view" instead of
# silently mislabelling them.
_KNOWN_VIEWS = ("CC", "MLO", "ML", "LM", "XCCL", "XCCM", "FB", "SIO", "LMO")


def parse_view_from_text(text: str) -> Tuple[str, str]:
    """Parse a laterality + view position out of free text (pure).

    "R-CC" / "R CC" / "RCC" / "Right CC" / "L_MLO" / "MLO L" → ('R','CC') etc.
    Returns ('', '') when nothing can be read.
    """
    if not text:
        return "", ""
    t = str(text).upper()

    view = ""
    for v in sorted(_KNOWN_VIEWS, key=len, reverse=True):  # XCCL before CC
        if re.search(rf"(?<![A-Z]){v}(?![A-Z])", t):
            view = v
            break
    if not view:
        # glued forms: RCC / LMLO
        m = re.search(r"(?<![A-Z])([RL])(CC|MLO)(?![A-Z])", t)
        if m:
            return m.group(1), m.group(2)
        return "", ""

    lat = ""
    if re.search(r"\bRIGHT\b", t) or re.search(r"(?<![A-Z])R(?![A-Z])", t):
        lat = "R"
    if re.search(r"\bLEFT\b", t) or re.search(r"(?<![A-Z])L(?![A-Z])", t):
        # if both matched, prefer an explicit word
        if not lat or re.search(r"\bLEFT\b", t):
            lat = "L"
    if not lat:
        m = re.search(r"(?<![A-Z])([RL])(?:[-_ ]?)(?:%s)" % "|".join(_KNOWN_VIEWS), t)
        if m:
            lat = m.group(1)
    return lat, view


def _from_metadata(vtk_widget) -> Tuple[str, str]:
    try:
        iv = getattr(vtk_widget, 'image_viewer', None)
        if iv is None:
            return "", ""
        meta = getattr(iv, 'metadata', {}) or {}
        series = meta.get('series', {}) or {}

        lat = ""
        for key in ('laterality', 'image_laterality', 'ImageLaterality', 'Laterality'):
            val = series.get(key) or meta.get(key)
            if val:
                lat = str(val).upper().strip()
                break

        vp = ""
        for key in ('view_position', 'ViewPosition', 'view'):
            val = series.get(key) or meta.get(key)
            if val:
                vp = str(val).upper().strip()
                break

        if lat and vp:
            return lat[:1], vp

        # description / name often carries "R CC"
        for key in ('series_description', 'description', 'series_name', 'name'):
            txt = series.get(key)
            if txt:
                t_lat, t_vp = parse_view_from_text(str(txt))
                lat = lat or t_lat
                vp = vp or t_vp
                if lat and vp:
                    break
        return (lat[:1] if lat else ""), vp
    except Exception:
        return "", ""


def _dicom_path(vtk_widget) -> str:
    try:
        iv = getattr(vtk_widget, 'image_viewer', None)
        meta = (getattr(iv, 'metadata', {}) or {}) if iv else {}
        instances = meta.get('instances', []) or []
        if instances and isinstance(instances[0], dict):
            return str(instances[0].get('instance_path', '') or '')
    except Exception:
        pass
    return ""


def _from_dicom(vtk_widget) -> Tuple[str, str]:
    """Same fallback `imaging_tab._extract_view_data_from_widget` already uses."""
    path = _dicom_path(vtk_widget)
    if not path or not os.path.isfile(path):
        return "", ""
    try:
        import pydicom
        ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        lat = getattr(ds, 'ImageLaterality', None) or getattr(ds, 'Laterality', None) or ''
        vp = getattr(ds, 'ViewPosition', None) or ''
        lat = str(lat).upper().strip()
        vp = str(vp).upper().strip()
        if not (lat and vp):
            # some vendors only fill the description
            txt = f"{getattr(ds, 'SeriesDescription', '') or ''} {getattr(ds, 'ProtocolName', '') or ''}"
            t_lat, t_vp = parse_view_from_text(txt)
            lat = lat or t_lat
            vp = vp or t_vp
        return (lat[:1] if lat else ""), vp
    except Exception as e:
        print(f"[3D-Cursor][VIEW-ID] DICOM read failed: {e}")
        return "", ""


def resolve_view_identity(vtk_widget, *, use_cache: bool = True) -> Tuple[str, str]:
    """Return (laterality, view_position) for a viewer, e.g. ('R', 'MLO').

    Empty strings when it genuinely cannot be determined — callers must NOT guess.
    """
    if vtk_widget is None:
        return "", ""

    if use_cache:
        cached = getattr(vtk_widget, '_cursor3d_view_identity', None)
        if isinstance(cached, tuple) and len(cached) == 2 and cached[0] and cached[1]:
            return cached

    lat, vp = _from_metadata(vtk_widget)
    if not (lat and vp):
        d_lat, d_vp = _from_dicom(vtk_widget)
        lat = lat or d_lat
        vp = vp or d_vp

    result = (lat, vp)
    try:
        vtk_widget._cursor3d_view_identity = result
    except Exception:
        pass

    print(f"[3D-Cursor][VIEW-ID] viewer resolved as laterality={lat or '?'} view={vp or '?'}")
    return result


def view_label(vtk_widget, fallback: str = "View") -> str:
    """Display label such as 'R-CC' (or the fallback when unknown)."""
    lat, vp = resolve_view_identity(vtk_widget)
    if lat and vp:
        return f"{lat}-{vp}"
    if vp:
        return vp
    return fallback
