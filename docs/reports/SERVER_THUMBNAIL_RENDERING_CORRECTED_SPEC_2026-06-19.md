# Server-side thumbnail rendering — corrected spec (2026-06-19)

**For:** the server-side AI agent that implemented the previous guide
(`DICOM_OVERLAY_AND_COLOR_RENDERING_PORTABLE_FIX.md`).
**Why:** after that guide was applied, server thumbnails regressed — grayscale CT/MR
thumbnails became **over-white / washed-out**, and some color/derived thumbnails look
wrong. This document pinpoints the cause and gives the corrected, authoritative
rendering rules. **The workstation must not (and does not) correct thumbnails locally —
the server must send ready-to-display images that match the viewer.**

Ground truth = the AI-PACS desktop viewer's decode path
(`modules/viewer/fast/lightweight_2d_pipeline.py`), which renders these same series
correctly. The server thumbnail must reproduce that output.

---

## 1. Root cause of the regression (read this first)

The previous guide is **correct about color and overlays**. The regression is in its
**grayscale fallback** — §8.3's `render_display_rgb` "grayscale window/level (your
existing logic)" branch:

```python
# PREVIOUS (WRONG) grayscale branch — §8.3
lo = (wc or 128) - (ww or 256) / 2.0
g8 = np.clip((arr.astype(np.float32) - lo) / max(ww or 256, 1) * 255, 0, 255).astype(np.uint8)
```

It applies window/level to **raw stored pixels** and is missing four things the viewer
does. Any one of them whitens/wrongs a grayscale thumbnail:

1. **No RescaleSlope/RescaleIntercept.** CT WindowCenter/Width are in **Hounsfield units**,
   but stored pixels are unsigned (e.g. 0–4095) with `RescaleIntercept = -1024`. Window
   must be applied to `pixel*slope + intercept`, not to the raw pixel.
2. **No VOI LUT / VOI LUT Function.** A present `VOILUTSequence`, or a `SIGMOID` /
   `LINEAR_EXACT` `VOILUTFunction`, is ignored — wrong mapping.
3. **No multi-valued WindowCenter/Width handling.** `WindowCenter` is often a list
   (e.g. `[40, -600]`); `wc or 128` then carries a list into arithmetic → wrong/garbage.
   And when WC/WW are absent the code defaults to 128/256 instead of deriving from data.
4. **No MONOCHROME1 inversion.** MONOCHROME1 (min = white) renders inverted.

### Worked example — exactly why CT goes white (measured)

Real series (study …86503): **lung-window CT, WindowCenter = -600, WindowWidth = 1200**,
stored pixels unsigned 0–4095, `RescaleIntercept = -1024` (slope 1).

- Correct: `HU = pixel - 1024` (range −1024..3071); window −600±600 ⇒ map [−1200, 0] HU
  to 0–255 → a normal lung image.
- Previous code (no rescale): `lo = -600 - 600 = -1200`; every stored pixel ≥ 0, so
  `(pixel + 1200)/1200*255 ≥ 255` for **all** pixels → **clipped to 255 → solid white.**

This is why the lung/CT thumbnails are pure white while the **viewer shows them
correctly** (the viewer applies rescale). It is a thumbnail-pipeline-vs-viewer-pipeline
mismatch, server-side. Soft-tissue series (e.g. WC 40/WW 350) happened to look only
"bright/washed-out" rather than fully white, for the same reason.

---

## 2. The authoritative render order (mirror the viewer EXACTLY)

Per slice, produce a ready-to-display RGB (or grayscale) image with this order. **Color
is decided first; window/level is applied to grayscale ONLY.**

```
render(ds):
    arr = decoded Pixel Data (decompress JPEG/JP2/RLE first if needed)

    # (A) COLOR PATH — return RGB, NEVER window/level it
    rgb = decode_color(ds, arr)            # RGB / YBR→RGB / PALETTE / embedded-palette-on-mono
    if rgb is not None:
        base = to_uint8_rgb(rgb)           # 16-bit color → high byte (>>8)
    else:
        # (B) GRAYSCALE PATH — the part that was wrong; do ALL of these in order:
        a = arr as float32
        a = a * RescaleSlope + RescaleIntercept          # 1) modality rescale (HU for CT)
        if VOILUTSequence present:                       # 2) VOI
            g8 = apply_voi_lut_sequence(a, ds) -> 0..255
        else:
            wc, ww = select_window(ds, a)                # 3) first of multi-valued; data-derived default
            g8 = window_to_uint8(a, wc, ww, VOILUTFunction)   # LINEAR (default) / LINEAR_EXACT / SIGMOID
        if PhotometricInterpretation == MONOCHROME1:     # 4) invert
            g8 = 255 - g8
        base = gray_to_rgb(g8)             # or keep 1-channel; promote to RGB only if an overlay is composited

    # (C) OVERLAY PLANES (60xx) — unchanged from the previous guide (it was correct)
    mask = extract_overlay_mask(ds)        # 1-bit, LSB-first, 1-based origin, OR-combine
    if mask is not None and mask.any():
        base = to_rgb(base); paint(base, mask, HIGHLIGHT_COLOR)

    return base                            # ready-to-display PNG/JPEG
```

**Viewer references (the rules above are taken from these):**
- Rescale + MONOCHROME1: `lightweight_2d_pipeline._get_pixel_array` (`arr*slope+intercept`,
  `should_invert_for_display(photometric, PresentationLUTShape)`).
- Window + VOI function: `_window_level_to_uint8_with_voi_function` (LINEAR / LINEAR_EXACT /
  SIGMOID).
- Color + overlay: `dicom_color.decode_color_for_display`, `dicom_overlay.extract_overlay_mask`
  (the previous guide §6 is faithful to these — keep it).

---

## 3. Corrected server Python (drop-in replacement for §8.3)

```python
import numpy as np, pydicom
from pydicom.pixel_data_handlers.util import (
    apply_color_lut, convert_color_space, apply_modality_lut, apply_voi_lut,
)
from pydicom.overlays.numpy_handler import get_overlay_array


def _select_window(ds, a):
    """First value of a (possibly multi-valued) WindowCenter/Width; sensible
    data-derived default when absent. WC/WW are in the SAME units as `a`
    (i.e. AFTER modality rescale)."""
    wc = getattr(ds, "WindowCenter", None)
    ww = getattr(ds, "WindowWidth", None)
    if isinstance(wc, (list, tuple, pydicom.multival.MultiValue)):
        wc = wc[0]
    if isinstance(ww, (list, tuple, pydicom.multival.MultiValue)):
        ww = ww[0]
    try:
        wc = float(wc); ww = float(ww)
        if ww > 0:
            return wc, ww
    except (TypeError, ValueError):
        pass
    lo, hi = float(np.min(a)), float(np.max(a))          # fall back to actual data range
    return (lo + hi) / 2.0, max(hi - lo, 1.0)


def _window_linear_uint8(a, wc, ww, voi_fn="LINEAR"):
    """DICOM linear window → uint8 (matches the viewer's window_to_uint8 / VOI fn)."""
    fn = (voi_fn or "LINEAR").strip().upper()
    a = a.astype(np.float32, copy=False)
    if fn == "SIGMOID":
        z = np.clip(-4.0 * (a - wc) / max(ww, 1e-6), -60, 60)
        return (255.0 / (1.0 + np.exp(z))).astype(np.uint8)
    lo = wc - ww / 2.0                                    # LINEAR / LINEAR_EXACT
    return np.clip((a - lo) / max(ww, 1.0) * 255.0, 0, 255).astype(np.uint8)


def render_display_rgb(ds, highlight=(255, 0, 255)):
    arr = ds.pixel_array
    photo = str(getattr(ds, "PhotometricInterpretation", "") or "").upper()
    samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)

    # ---- (A) COLOR: return RGB, never window/level it ----
    rgb = None
    if samples >= 3 or (arr.ndim == 3 and arr.shape[-1] == 3):
        rgb = convert_color_space(arr, photo, "RGB") if "YBR" in photo else arr
    elif photo.startswith("PALETTE") or ((0x00281201 in ds) and (0x00281101 in ds)):
        rgb = apply_color_lut(arr, ds)                   # PALETTE or embedded-palette-on-mono
    if rgb is not None:
        rgb = (rgb >> 8).astype(np.uint8) if int(rgb.max()) > 255 else rgb.astype(np.uint8)
        base = np.ascontiguousarray(rgb)
    else:
        # ---- (B) GRAYSCALE: rescale → VOI/WC-WW → MONOCHROME1 invert (THE FIX) ----
        if "VOILUTSequence" in ds:
            # pydicom apply_voi_lut applies the VOI LUT (assumes modality LUT already applied)
            a = apply_modality_lut(arr, ds).astype(np.float32, copy=False)
            v = apply_voi_lut(a, ds, index=0).astype(np.float32, copy=False)
            lo, hi = float(np.min(v)), float(np.max(v))
            g8 = np.clip((v - lo) / max(hi - lo, 1.0) * 255.0, 0, 255).astype(np.uint8)
        else:
            a = apply_modality_lut(arr, ds).astype(np.float32, copy=False)   # rescale slope/intercept
            wc, ww = _select_window(ds, a)
            voi_fn = str(getattr(ds, "VOILUTFunction", "LINEAR") or "LINEAR")
            g8 = _window_linear_uint8(a, wc, ww, voi_fn)
        if photo == "MONOCHROME1":
            g8 = 255 - g8
        base = np.repeat(g8[..., None], 3, axis=2)

    # ---- (C) OVERLAY planes (unchanged — the previous guide was correct here) ----
    rows, cols = int(ds.Rows), int(ds.Columns)
    mask = None
    for g in range(0x6000, 0x6020, 2):
        if (g, 0x3000) in ds and (g, 0x0010) in ds:
            try:
                ov = (np.asarray(get_overlay_array(ds, g)) != 0).astype(np.uint8)
            except Exception:
                continue
            m = np.zeros((rows, cols), np.uint8)
            r0 = c0 = 0
            if (g, 0x0050) in ds:
                o = ds[(g, 0x0050)].value
                if o and len(o) == 2:
                    r0, c0 = max(0, int(o[0]) - 1), max(0, int(o[1]) - 1)
            h, w = min(ov.shape[0], rows - r0), min(ov.shape[1], cols - c0)
            if h > 0 and w > 0:
                m[r0:r0+h, c0:c0+w] = ov[:h, :w]
            mask = m if mask is None else np.maximum(mask, m)
    if mask is not None and mask.any():
        base = np.ascontiguousarray(base).copy()
        base[mask.astype(bool)] = np.asarray(highlight, np.uint8)
    return base  # HxWx3 uint8 → encode PNG/JPEG and send
```

Key differences vs the previous §8.3 (these are the regression fixes):
- **`apply_modality_lut` before windowing** (rescale slope/intercept) — fixes the white CT.
- **VOI LUT Sequence honored**; `VOILUTFunction` (SIGMOID/LINEAR_EXACT) honored.
- **Multi-valued WC/WW** → first value; **data-derived default** when absent (never 128/256
  blindly).
- **MONOCHROME1 inversion.**
- Color/overlay logic kept (it was right). `apply_color_lut` handles both `PALETTE COLOR`
  and embedded-palette-on-MONOCHROME; YBR→RGB via `convert_color_space`; color is **never**
  windowed.

---

## 4. Representative-slice selection (also from the previous guide §8.3 — keep)

Don't pick the last instance as the series thumbnail: on these studies the last
instance is often an all-zero secondary-capture / chart frame. Pick a **middle image
slice** of the series (or, for an overlay-only black SC frame, render the overlay so the
chart shows). A black/white thumbnail caused by slice choice is separate from the
windowing bug above — fix both.

---

## 5. Before / after (measured)

Measured on the real downloaded DICOM (the previous §8.3 grayscale formula vs the
corrected one in §3), pixel stats of the rendered 8-bit thumbnail:

| Series | WC / WW (intercept) | Before — regressed (§8.3) | After — corrected (§3) |
|---|---|---|---|
| CT **lung** 201/203 | −600 / 1200 (−1024) | **mean 255, std 0, white 100%** → solid white | mean ~123, std ~87, white ~18% → real lung CT |
| CT soft-tissue 202 | 50 / 350 (−1024) | mean 202, std 60, white 50% → washed-out | mean ~22, std ~50, black ~77% → correct |
| CT bone / abdomen presets | bone/abdomen WC/WW | over-white if multi-valued/raw | correct, per the chosen window |
| MR grayscale | per-tag | washed if rescale/VOI skipped | correct |
| Color / perfusion / palette maps | n/a (color) | OK only if not force-windowed | correct color (no W/L on color) |
| Mean-curve chart / ROI overlay (SC) | n/a | black / missing | overlay composited (chart visible) |

The lung rows are the decisive proof: identical input, the regressed formula yields a
**perfectly uniform white** frame (std 0) while the corrected formula yields a normal
image (std ~87) — because the corrected path applies `RescaleIntercept = -1024` before
the HU window. (Reproduced 2026-06-19 on study …86503 and …86505.)

Automated check (any stack): a correctly windowed grayscale CT thumbnail must **not** be
near-uniform — assert `std(pixels) > a small epsilon` and `mean` not pinned at 0 or 255.
For 46630 overlay series, highlight-pixel counts ≈ 717 / 5546 / 11197 (from the guide §9).

---

## 6. Validation checklist (server thumbnails vs viewer)

For each, the **server thumbnail must visually equal the viewer's decoded frame**:

- [ ] CT abdomen window — not white; soft-tissue contrast visible.
- [ ] CT lung window (WC −600 / WW 1200) — **not white**; lung detail visible.
- [ ] CT bone window — correct, not over-white.
- [ ] Standard MR grayscale — correct W/L, not washed out.
- [ ] Multi-valued WindowCenter/Width — uses the first value (or the documented default),
      not garbage.
- [ ] VOI LUT Sequence / SIGMOID VOILUTFunction present — honored.
- [ ] MONOCHROME1 series — not inverted.
- [ ] Color MR / perfusion / palette maps — render in color, **never** grayscale-windowed.
- [ ] Embedded-palette-on-MONOCHROME (TTP/WO) — colored, not gray.
- [ ] Device graph / chart / annotation (overlay 60xx, black SC) — overlay composited,
      not black/white.
- [ ] Secondary-capture / DICOMized doc — representative slice, not all-zero frame.
- [ ] **No regression:** a plain grayscale CT/MR with simple WC/WW looks the same as a
      correctly-rendered frame, and identical to the viewer.
- [ ] Pixel/stat check: no thumbnail is near-uniform white/black unless the source frame
      genuinely is.

---

## 7. Workstation side — confirmed, no local correction

The workstation receives the server PNG/JPEG and displays it **as-is** (decode base64 →
cache → `make_pixmap_from_bytes` → show); it applies **no** window/level, rescale, VOI, or
color transform to thumbnails, by design. So once the server produces correct thumbnails
per §2–§3, the workstation shows them correctly with **zero** local changes — which is the
required behavior. (We did not and will not add local thumbnail correction.)

The single rule to remember: **the server thumbnail must run the same decode order the
viewer runs — modality rescale → VOI/window (with VOI function) → MONOCHROME1 invert for
grayscale; RGB/YBR/PALETTE/embedded-palette for color (no windowing); 60xx overlay
composite on top.** The previous guide had color + overlay right; it only needed the full
grayscale chain restored.

---

*Origin: AI-PACS workstation investigation 2026-06-19. Viewer ground truth:
`modules/viewer/fast/lightweight_2d_pipeline.py`. Prior server guide:
`DICOM_OVERLAY_AND_COLOR_RENDERING_PORTABLE_FIX.md`. Workstation thumbnail-source
investigation: `docs/reports/DOWNLOAD_MODE_SERIES_THUMBNAIL_INVESTIGATION_2026-06-19.md`.*
