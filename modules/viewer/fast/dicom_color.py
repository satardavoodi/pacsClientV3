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

# ── 2026-08-21: multi-sample (SamplesPerPixel >= 3) colour correctness ────────
# Two independent defects, both reproduced on the ALPINION E-CUBE i7 breast US
# study 1.2.410.114480.3.2.503247.20260707080007251.1 (45 instances):
#
#   1. 39 of its 45 instances declare PhotometricInterpretation YBR_FULL_422 but
#      ship FULL, non-subsampled pixel data (len(PixelData) == R*C*3, not
#      R*C*2). pydicom 2.4.5 warns about this and then applies the 4:2:2 -> 4:4:4
#      resample ANYWAY (numpy_handler.get_pixeldata), reading with stride 4 from
#      a period-3 interleave after truncating the buffer to 2/3. Every output
#      sample becomes a rotating mix of Y/Cb/Cr from neighbouring pixels ->
#      coloured static. MEASURED row-to-row correlation: -0.36 (noise) vs 0.93
#      once the bogus expansion is skipped.
#
#   2. Even with correct geometry the FAST pipeline painted the raw samples as
#      RGB (`samples_per_pixel >= 3` branch), so a YBR frame rendered with a
#      heavy cyan cast (Cb/Cr ~128 landing in the G/B channels).
#
# `normalize_ybr_subsampling` fixes (1) BEFORE pixel data is touched;
# `ybr_samples_to_rgb` fixes (2) AFTER decode. Both are no-ops for grayscale and
# for true RGB, and both are individually kill-switchable.
_YBR422_FIX = _flag("AIPACS_DICOM_YBR422_FIX")
_YBR_TO_RGB = _flag("AIPACS_DICOM_YBR_TO_RGB")


def color_enabled() -> bool:
    return _COLOR_ENABLED


def ybr422_fix_enabled() -> bool:
    return _YBR422_FIX


def ybr_to_rgb_enabled() -> bool:
    return _YBR_TO_RGB


def _uncompressed(ds) -> bool:
    """True when the dataset's transfer syntax stores native (unencapsulated) pixels."""
    try:
        from pydicom.uid import UID
        ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
        if ts is None:
            return True                      # no file meta -> raw little endian
        return not UID(str(ts)).is_compressed
    except Exception:
        return False


def normalize_ybr_subsampling(ds) -> bool:
    """Repair a dataset that claims YBR_FULL_422 but carries full-rate samples.

    Must be called BEFORE ``ds.pixel_array``: pydicom caches the decoded array,
    and it is the decode itself that mis-resamples.  Mutates ``ds`` in memory
    only (nothing is written back to the file).  Returns True when the
    photometric interpretation was corrected.

    Deliberately narrow — every one of these must hold, so a genuinely
    subsampled 4:2:2 image is never touched:
      * colour handling and the fix are enabled
      * the transfer syntax is uncompressed (for encapsulated data the codec
        owns subsampling, not the tag)
      * PhotometricInterpretation is exactly YBR_FULL_422
      * SamplesPerPixel == 3 and BitsAllocated == 8
      * len(PixelData) covers the FULL R*C*3*frames, i.e. nothing was subsampled
    """
    if not (_COLOR_ENABLED and _YBR422_FIX):
        return False
    try:
        if str(getattr(ds, "PhotometricInterpretation", "") or "").upper().strip() \
                != "YBR_FULL_422":
            return False
        if int(getattr(ds, "SamplesPerPixel", 1) or 1) != 3:
            return False
        if int(getattr(ds, "BitsAllocated", 8) or 8) != 8:
            return False
        if not _uncompressed(ds):
            return False
        if "PixelData" not in ds:
            return False
        rows = int(getattr(ds, "Rows", 0) or 0)
        cols = int(getattr(ds, "Columns", 0) or 0)
        if rows <= 0 or cols <= 0:
            return False
        try:
            frames = max(1, int(getattr(ds, "NumberOfFrames", 1) or 1))
        except Exception:
            frames = 1
        raw = ds["PixelData"].value
        if not isinstance(raw, (bytes, bytearray)):
            return False
        if len(raw) < rows * cols * 3 * frames:
            return False                     # genuinely subsampled -> leave alone
        ds.PhotometricInterpretation = "YBR_FULL"
        logger.info(
            "[DICOM_COLOR] YBR_FULL_422 mislabel corrected -> YBR_FULL "
            "(%dx%d frames=%d pixel_bytes=%d)", rows, cols, frames, len(raw),
        )
        return True
    except Exception as exc:                  # pragma: no cover - never break decode
        logger.debug("[DICOM_COLOR] ybr422 normalize skipped: %s", exc)
        return False


def ybr_samples_to_rgb(ds, arr):
    """Convert a decoded multi-sample YBR frame to RGB; pass anything else through.

    Call AFTER ``ds.pixel_array``.  pydicom rewrites
    ``ds.PhotometricInterpretation`` to ``RGB`` when a decoding handler already
    performed the colour conversion (the Pillow/GDCM JPEG paths do), so reading
    the tag *after* the decode is what tells us whether a conversion is still
    owed — that keeps compressed colour images from being converted twice.
    """
    if not (_COLOR_ENABLED and _YBR_TO_RGB):
        return arr
    try:
        a = np.asarray(arr)
        if a.ndim < 3 or a.shape[-1] != 3:
            return arr
        photometric = str(getattr(ds, "PhotometricInterpretation", "") or "").upper().strip()
        if "YBR" not in photometric:
            return arr
        from pydicom.pixel_data_handlers.util import convert_color_space
        out = convert_color_space(a, photometric, "RGB")
        return np.ascontiguousarray(np.clip(out, 0, 255).astype(np.uint8))
    except Exception as exc:                  # pragma: no cover - never break decode
        logger.warning("[DICOM_COLOR] YBR->RGB convert failed: %s; "
                       "rendering raw samples", exc)
        return arr


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
