"""DICOM overlay-plane (group 60xx) extraction for the FAST viewer.

Some derived/secondary-capture images carry their visible content as a 1-bit
DICOM *overlay plane* (Graphics type) rather than in PixelData. Patient 46382
series 100/101 are a clear case: the last two slices are Siemens "CSA BLACK
IMAGE" secondary captures whose PixelData is all-zero, while the mean-curve
chart / diagram lives in overlay group ``(6000,3000)`` (type ``G``). A viewer
that renders only PixelData shows a blank black slice; rendering the overlay
reveals the chart.

This module returns a combined HxW uint8 (0/1) overlay mask for an image, or
``None`` when there is no overlay (the overwhelmingly common case — one cheap
tag probe). The caller composites it onto the display bitmap in a highlight
colour. Standard DICOM overlays are 1-bit monochrome graphics, so the result is
a single colour, not a full-colour image.

Env-gated by ``AIPACS_DICOM_OVERLAY`` (default on); colour via
``AIPACS_DICOM_OVERLAY_COLOR`` as "R,G,B" (default bright green).
"""
from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)


def _flag(name: str, default: str = "1") -> bool:
    return str(os.environ.get(name, default)).strip().lower() not in ("0", "false", "no", "off")


_OVERLAY_ENABLED = _flag("AIPACS_DICOM_OVERLAY")

# Repeating overlay groups: 6000, 6002, ... 601E.
_OVERLAY_GROUPS = tuple(range(0x6000, 0x6020, 2))


def overlay_enabled() -> bool:
    return _OVERLAY_ENABLED


def overlay_color() -> tuple:
    raw = os.environ.get("AIPACS_DICOM_OVERLAY_COLOR", "")
    try:
        parts = [int(x) for x in raw.split(",")]
        if len(parts) == 3 and all(0 <= p <= 255 for p in parts):
            return (parts[0], parts[1], parts[2])
    except Exception:
        pass
    return (0, 255, 0)  # bright green — visible on black SC frames


def has_overlay(ds) -> bool:
    try:
        return any((g, 0x3000) in ds and (g, 0x0010) in ds for g in _OVERLAY_GROUPS)
    except Exception:
        return False


def _fit(ov: np.ndarray, rows: int, cols: int, ds, group: int) -> np.ndarray:
    """Place a (possibly smaller / origin-offset) overlay into a rows x cols mask."""
    ov = np.asarray(ov)
    if ov.ndim == 3:                      # multi-frame overlay -> first frame
        ov = ov[0]
    ov = (ov != 0).astype(np.uint8)
    if ov.shape == (rows, cols):
        return ov
    out = np.zeros((rows, cols), np.uint8)
    # Overlay Origin (60xx,0050) is 1-based [row, col]; default top-left.
    r0 = c0 = 0
    try:
        origin = ds[(group, 0x0050)].value
        if origin is not None and len(origin) == 2:
            r0 = max(0, int(origin[0]) - 1)
            c0 = max(0, int(origin[1]) - 1)
    except Exception:
        pass
    h = min(ov.shape[0], rows - r0)
    w = min(ov.shape[1], cols - c0)
    if h > 0 and w > 0:
        out[r0:r0 + h, c0:c0 + w] = ov[:h, :w]
    return out


def extract_overlay_mask(ds, rows: int, cols: int):
    """Return a combined HxW uint8 (0/1) overlay mask, or None if no overlay."""
    if not _OVERLAY_ENABLED:
        return None
    try:
        if not has_overlay(ds):
            return None
        from pydicom.overlays.numpy_handler import get_overlay_array
        combined = None
        for g in _OVERLAY_GROUPS:
            if (g, 0x3000) not in ds or (g, 0x0010) not in ds:
                continue
            try:
                ov = get_overlay_array(ds, g)
            except Exception as exc:
                logger.warning("[DICOM_OVERLAY] group 0x%04x decode failed: %s", g, exc)
                continue
            mask = _fit(ov, int(rows), int(cols), ds, g)
            combined = mask if combined is None else np.maximum(combined, mask)
        if combined is not None and int(combined.sum()) == 0:
            return None
        return combined
    except Exception as exc:                # pragma: no cover - never crash decode
        logger.warning("[DICOM_OVERLAY] overlay extraction error: %s", exc)
        return None
