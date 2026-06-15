"""Standards-based DICOM colour decoding for the FAST viewer.

Converts any DICOM colour representation into an 8-bit RGB array suitable for
``QImage.Format_RGB888``. Returns ``None`` for genuine monochrome so the caller
keeps the grayscale window/level path completely unchanged.

Handled photometric interpretations (DICOM PS3.3 C.7.6.3):
  * ``RGB``                         -> passthrough (pydicom already de-planarises)
  * ``YBR_FULL`` / ``YBR_FULL_422`` -> ``convert_color_space`` -> RGB
  * ``PALETTE COLOR``               -> ``apply_color_lut`` -> RGB
  * ``MONOCHROME1/2`` that ALSO carries an embedded Red/Green/Blue Palette Colour
    LUT (Siemens perfusion / parametric maps such as TTP / time-to-peak; the
    scanner ships the exact pseudo-colour LUT) -> ``apply_color_lut`` -> RGB

16-bit colour and 16-bit palette LUT entries are scaled to 8-bit.

Discovered for patient 46382 (series 21 ``WO`` / 22 ``TTP``): MONOCHROME2 maps
that embed a 4096-entry 16-bit Palette Colour LUT — reference viewers apply it
to show a colour map; AI-PACS previously ignored it and showed grayscale.

Safety: a plain grayscale CT/MR (no RGB/YBR/PALETTE, no embedded palette) hits
only two tag look-ups here and returns ``None`` — the hot mono path is unchanged.
Everything is env-gated so colour can be disabled on a problem build.
"""
from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)


def _flag(name: str, default: str = "1") -> bool:
    return str(os.environ.get(name, default)).strip().lower() not in ("0", "false", "no", "off")


# Master gate (all colour handling) and a finer gate for the embedded-palette-on
# -monochrome behaviour (the only case that changes how an otherwise-grayscale
# image looks). Both default ON.
_COLOR_ENABLED = _flag("AIPACS_DICOM_COLOR")
_PALETTE_ON_MONO = _flag("AIPACS_DICOM_PALETTE_ON_MONO")

_RED_PALETTE_DESC = 0x00281101   # Red Palette Colour LUT Descriptor
_RED_PALETTE_DATA = 0x00281201   # Red Palette Colour LUT Data


def color_enabled() -> bool:
    return _COLOR_ENABLED


def has_embedded_palette(ds) -> bool:
    """True when a (MONOCHROME) dataset carries an explicit RGB Palette Colour LUT."""
    try:
        return (_RED_PALETTE_DATA in ds) and (_RED_PALETTE_DESC in ds)
    except Exception:
        return False


def _to_uint8_rgb(rgb) -> np.ndarray:
    """Coerce any colour array to a contiguous HxWx3 uint8 RGB image."""
    a = np.asarray(rgb)
    if a.ndim == 4:                      # multi-frame colour -> first frame
        a = a[0]
    if a.ndim == 2:                      # single channel -> replicate
        a = np.repeat(a[..., None], 3, axis=2)
    if a.shape[-1] > 3:                  # drop alpha / extra samples
        a = a[..., :3]
    if a.dtype == np.uint8:
        out = a
    elif np.issubdtype(a.dtype, np.integer) and int(a.max(initial=0)) > 255:
        # 16-bit colour / 16-bit palette entries: take the high byte (standard).
        out = (a.astype(np.uint32) >> 8).astype(np.uint8)
    else:
        mx = float(np.nanmax(a)) if a.size else 0.0
        if mx <= 255.0:
            out = np.clip(a, 0, 255).astype(np.uint8)
        else:                            # float colour -> scale by max (keeps ratios)
            out = (a.astype(np.float32) * (255.0 / mx)).clip(0, 255).astype(np.uint8)
    return np.ascontiguousarray(out, dtype=np.uint8)


def decode_color_for_display(ds, arr):
    """Return an HxWx3 uint8 RGB image for a colour DICOM, else ``None`` (mono).

    ``ds``  : the pydicom Dataset (for photometric + palette LUT tags)
    ``arr`` : the already-decoded ``ds.pixel_array`` (passed in to avoid re-decode)
    """
    if not _COLOR_ENABLED:
        return None
    try:
        photometric = str(getattr(ds, "PhotometricInterpretation", "") or "").upper().strip()
        samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)
        a = np.asarray(arr)

        # ── multi-sample colour: RGB / YBR_FULL / YBR_FULL_422 ───────────────
        if samples >= 3 or (a.ndim >= 3 and a.shape[-1] == 3):
            if a.ndim == 4:
                a = a[0]
            if "YBR" in photometric:
                try:
                    from pydicom.pixel_data_handlers.util import convert_color_space
                    a = convert_color_space(a, photometric, "RGB")
                except Exception as exc:      # pragma: no cover - defensive
                    logger.warning("[DICOM_COLOR] YBR->RGB convert failed (%s): %s; "
                                   "rendering raw samples", photometric, exc)
            return _to_uint8_rgb(a)

        # ── palette colour: PALETTE COLOR photometric, or an embedded LUT on a
        #    monochrome parametric map (Siemens TTP/perfusion) ────────────────
        if photometric.startswith("PALETTE") or (_PALETTE_ON_MONO and has_embedded_palette(ds)):
            try:
                from pydicom.pixel_data_handlers.util import apply_color_lut
                rgb = apply_color_lut(a, ds)
                return _to_uint8_rgb(rgb)
            except Exception as exc:
                logger.warning("[DICOM_COLOR] palette LUT apply failed (photometric=%s): "
                               "%s; falling back to grayscale", photometric, exc)
                return None
    except Exception as exc:                  # pragma: no cover - never crash decode
        logger.warning("[DICOM_COLOR] colour decode error: %s; falling back to grayscale", exc)
        return None
    return None
