# Portable fix guide — DICOM overlay-plane graphics & embedded colour not rendering

**Audience:** an engineering agent porting this fix to a **Cornerstone3D / OHIF** web
workstation, a **dwv** web viewer, and the **server-side thumbnail** generator.
**Origin:** root-caused and fixed in the AI-PACS desktop workstation (Python/PySide6),
2026-06-17, patient 46630. This document is implementation-agnostic; the desktop fix is
included only as a worked reference.

---

## 0. TL;DR

Some device-derived MR/CT frames put their *visible content outside the Pixel Data*:

1. **Overlay planes** — group `(60xx,3000)` 1-bit bitmaps (ROI annotations, mean-curve
   charts, measurement tables). The Pixel Data may be a normal image **or entirely
   black**; the graphics live only in the overlay plane.
2. **Embedded palette colour on a "monochrome" image** — `PhotometricInterpretation =
   MONOCHROME2`, `SamplesPerPixel = 1`, but the file also ships a Red/Green/Blue
   **Palette Colour LUT** (parametric maps: TTP, perfusion, wash-in/wash-out).

A viewer that renders **only Pixel Data with grayscale window/level** shows these as a
**black frame** (overlay-only / black secondary capture) or a **missing annotation**
(overlay over a real image) or a **grayscale map** (palette ignored). The files are
valid; the bug is in the decode/render path.

**The fix:** in *every* code path that turns a DICOM instance into displayed pixels,
(a) extract group-`60xx` overlay planes and composite them onto the frame in a highlight
colour, and (b) apply an embedded palette LUT / proper colour conversion before window/
level. Leave the ordinary grayscale path untouched.

---

## 1. Clinical symptom

Breast MRI (Siemens dynaVIEWS), a derived "result" series of ~5 images per series:

| Slice | Looks like | Bug in our viewer |
|------|------------|-------------------|
| 1–3  | Breast image; slice 3 has a coloured **ROI annotation** (Min/Max, Area, Mean/SD) | Image shows, **annotation missing** |
| 4–5  | **Enhancement curve / mean-curve chart** (axes, curve, result table) | Shows **solid black** |

A reference DICOM workstation renders all of it correctly → the files are fine; our
rendering pipeline dropped the overlay/colour content.

---

## 2. What is actually in the files (the real cause)

### 2.1 Reference data — patient 46630, series 100–105 (all six identical in structure)

Probed with `pydicom` on the actual downloaded files:

| Slice | SOP Class | ImageType | Photometric | Pixel Data | Overlay `(6000,3000)` |
|-------|-----------|-----------|-------------|-----------|------------------------|
| 1 | MR Image Storage `1.2.840.10008.5.1.4.1.1.4` | `DERIVED\SECONDARY\…\CSA RESAMPLED` | MONOCHROME2, 416×396 | real image (nonzero) | type **G**, 20592 B = 416·396/8 |
| 2 | MR Image Storage | same | MONOCHROME2, 416×396 | real image | type G, 20592 B |
| 3 | MR Image Storage | same | MONOCHROME2, 416×396 | real image | type G, 20592 B → **ROI annotation** |
| 4 | Secondary Capture `1.2.840.10008.5.1.4.1.1.7` | `DERIVED\SECONDARY\OTHER\CSA BLACK IMAGE` (DerivationDescription `MeanCurve`) | MONOCHROME2, 512×512 | **ALL ZERO** | type G, 32768 B = 512·512/8 → **chart** |
| 5 | Secondary Capture | same | MONOCHROME2, 512×512 | **ALL ZERO** | type G, 32768 B → **chart** |

- Transfer Syntax: Explicit VR Little Endian (uncompressed) — no JPEG/JPEG2000/RLE here.
- `WindowCenter/Width`: 226/532 (image slices), **100/100** (black chart slices).
- No `RescaleSlope/Intercept`, no Modality/VOI LUT sequence, no ICC profile.
- `BurnedInAnnotation` absent. The graphics are **not** burned into Pixel Data — they are
  in the overlay plane. (The vendor also ships a private `(0029,xx10) MEDCOM OOG` vector
  blob — proprietary, ignore it; the **standard** overlay plane carries the same chart.)

> The same study's series 21 (`…_WO`) and 22 (`…_TTP`) are the **embedded-palette** case:
> MONOCHROME2 + a 4096-entry RGB Palette Colour LUT — colour maps that a grayscale-only
> viewer renders as gray. Your other PACS/web viewer will hit this too; §6 covers it.

### 2.2 The three mechanisms to handle

1. **Overlay plane `(60xx,3000)`** — DICOM PS3.3 C.9. 1 bit/pixel bitmap. Up to 16 planes
   in repeating groups `6000, 6002, … 601E`. Per group:
   - `(60xx,0010)` Overlay Rows, `(60xx,0011)` Overlay Columns
   - `(60xx,0040)` Overlay Type (`G` graphics, `R` ROI)
   - `(60xx,0050)` Overlay Origin `[row, col]` — **1-based**, may offset the bitmap
   - `(60xx,0100)` Bits Allocated = 1, `(60xx,0102)` Bit Position = 0
   - `(60xx,0015)` Number of Frames in Overlay (multi-frame overlays → use frame 0)
   - `(60xx,3000)` Overlay Data — **bit-packed, LSB-first within each byte** (PS3.5)
2. **Embedded palette colour on monochrome** — `SamplesPerPixel = 1`,
   `PhotometricInterpretation = MONOCHROME1/2`, **and** Red Palette Colour LUT Descriptor
   `(0028,1101)` + Data `(0028,1201)` present (also `1102/1202` green, `1103/1203` blue).
   Apply the LUT to get RGB. (Plain `PHOTOMETRIC = PALETTE COLOR` is the standard variant
   of the same thing.)
3. **Black secondary capture** — Pixel Data all-zero; the only content is the overlay
   plane. Detection is generic: *all-zero (or near-zero) pixels + an overlay present* →
   render the overlay. Don't special-case vendor `ImageType` strings.

---

## 3. Why a viewer shows black / missing

A typical fast 2D render path is: `decode Pixel Data → apply window/level → grayscale
buffer → display`. That path:

- **never reads group 60xx**, so overlay annotations/charts are invisible;
- on an all-zero SC frame, produces a uniformly black buffer;
- treats `SamplesPerPixel == 1` as grayscale, so an **embedded palette LUT is ignored**
  and a colour map renders gray;
- window/level on a colour buffer (if colour were naively forced) would destroy the
  colour.

None of these is a decoder bug — the decoder is correct. The content simply isn't in the
place the renderer looks.

---

## 4. The transferable root-cause lesson (read this even if you skim the rest)

In our desktop app the overlay/colour fix already existed — **but it was wired into the
wrong render path.** There were two decode backends; the fix lived in the one the live
GUI did **not** use for these series. Result: the code was present, committed, and
unit-tested, yet the screen stayed black.

**Lesson for your port:**

- A workstation usually has **more than one place** that rasterises a DICOM frame:
  the main 2D viewport, the **thumbnail generator**, the stack/cine prefetcher, a print/
  export path, MPR/3D, and sometimes a "fast" vs "full" renderer. Cornerstone/OHIF and
  dwv each have their own image-loader + render layers, **and your server renders
  thumbnails separately.**
- Adding overlay/colour support to one path does **not** fix the others. **Inventory
  every path that produces displayed/exported pixels and apply the fix (or a shared
  helper) to each**, then verify each on screen — not just in a unit test.
- Verify on the *actual rendered output* (pixel check / screenshot), because a passing
  unit test on a helper proves the helper, not the path that reaches the user.

---

## 5. Diagnostic methodology (reproduce on any file, any stack)

### 5.1 Server / Python probe (authoritative)

```python
import numpy as np, pydicom
ds = pydicom.dcmread(path, force=True)
arr = ds.pixel_array
print("photometric", ds.get("PhotometricInterpretation"),
      "samples", ds.get("SamplesPerPixel"),
      "pixels nonzero", int(np.count_nonzero(arr)), "/", arr.size)
# overlay planes
for g in range(0x6000, 0x6020, 2):
    if (g, 0x3000) in ds and (g, 0x0010) in ds:
        from pydicom.overlays.numpy_handler import get_overlay_array
        ov = get_overlay_array(ds, g)
        print(f"overlay {hex(g)} type", ds.get((g,0x0040)),
              "lit", int(np.asarray(ov).sum()), "origin", ds.get((g,0x0050)))
# embedded palette on monochrome
print("embedded palette:", (0x00281201 in ds) and (0x00281101 in ds))
```

Decisive signals: `pixels nonzero == 0` **and** an overlay with `lit > 0` → black-SC +
overlay chart. Real image **and** an overlay with `lit > 0` → annotation-over-image.
`embedded palette: True` on `MONOCHROME*` → colour map ignored as gray.

### 5.2 Browser / JS probe (dcmjs or dicom-parser)

```js
// dataSet = dicomParser.parseDicom(byteArray)
const spp  = dataSet.uint16('x00280002');         // SamplesPerPixel
const photo= dataSet.string('x00280004');         // PhotometricInterpretation
const hasOverlay = !!dataSet.elements['x60003000'] && !!dataSet.elements['x60000010'];
const hasPalette = !!dataSet.elements['x00281201'] && !!dataSet.elements['x00281101'];
// pixel all-zero check: read PixelData per BitsAllocated and test max === 0
```

If `hasOverlay` is true and the frame is black/real-image, the overlay isn't being drawn.
If `hasPalette` and `photo` starts with `MONOCHROME`, colour is being dropped.

---

## 6. The fix algorithm (vendor-neutral)

Run this **per slice**, inside each render/thumbnail path, **without** changing the
ordinary grayscale path:

```
function renderFrame(ds, pixels):
    # 1. COLOUR first (returns an RGB image or null)
    rgb = decodeColor(ds, pixels)          # see 6a
    if rgb == null:
        gray8 = windowLevelToUint8(pixels, ww, wc)   # unchanged grayscale path
        base  = gray8                                  # 1-channel
    else:
        base  = rgb                                    # 3-channel, DO NOT window/level it

    # 2. OVERLAY planes on top (returns a 0/1 mask or null)
    mask = extractOverlayMask(ds, rows, cols)          # see 6b
    if mask != null:
        base = toRGB(base)                             # promote gray→RGB only if needed
        paint(base, mask, HIGHLIGHT_COLOR)             # e.g. magenta or green

    display(base)
```

### 6a. `decodeColor(ds, pixels)` → RGB or null

- `PhotometricInterpretation` in `RGB` → use as-is (de-planarise if
  `PlanarConfiguration == 1`).
- `YBR_FULL` / `YBR_FULL_422` → convert YBR→RGB.
- `PALETTE COLOR`, **or** (`MONOCHROME*` **and** Red Palette LUT Descriptor+Data present)
  → apply the RGB Palette LUT:
  - LUT descriptor `(0028,1101)` = `[numEntries, firstMapped, bitsPerEntry]`
    (`numEntries == 0` means 65536).
  - `index = clamp(pixelValue - firstMapped, 0, numEntries-1)`.
  - `R = redLUT[index]`, etc. If `bitsPerEntry == 16`, take the **high byte** (`>> 8`).
- else → return **null** (genuine monochrome; caller keeps grayscale window/level).
- 16-bit colour → scale to 8-bit. **Never** apply grayscale window/level to a colour
  buffer.

### 6b. `extractOverlayMask(ds, rows, cols)` → 0/1 mask or null

- For each group `g` in `6000..601E` step 2 with `(g,3000)` and `(g,0010)` present:
  - Unpack `(g,3000)` Overlay Data as **1 bit/pixel, LSB-first**:
    `bit(i) = (bytes[i >> 3] >> (i & 7)) & 1` for `i in 0 .. rows*cols-1`
    (use `(g,0010)`/`(g,0011)` for the overlay's own rows/cols; multi-frame → frame 0).
  - Place into the image grid at origin `(g,0050)` `[row,col]` **(1-based → subtract 1)**;
    default top-left.
  - OR-combine planes.
- If the combined mask is empty → return null.
- Standard overlays are 1-bit monochrome → render in a single **highlight colour**
  (no per-pixel colour). Pick one; magenta `255,0,255` matches many Siemens reference
  viewers, green `0,255,0` is high-contrast on black. Make it configurable.

### Safety invariants (keep these — they prevent regressions)

- A plain grayscale CT/MR (no overlay, no palette) must hit only a couple of tag look-ups
  and fall through to the **unchanged** grayscale path (same bytes as before).
- Gate the whole thing behind a flag so it can be disabled on a problem build.
- Don't change geometry, slice ordering, spacing, or MPR/3D behaviour — this is a 2D
  raster concern only.
- Overlay extraction/colour must be **exception-safe**: on any failure, fall back to the
  grayscale frame rather than crashing the decode.

---

## 7. Reference implementation (AI-PACS desktop — working)

Three small modules, reused by every render path:

- `dicom_overlay.extract_overlay_mask(ds, rows, cols)` → `HxW` 0/1 mask or `None`
  (groups `60xx`, LSB-first unpack, 1-based origin placement, OR-combine).
- `dicom_color.decode_color_for_display(ds, arr)` → `HxWx3` uint8 RGB or `None`
  (RGB / YBR→RGB / PALETTE / embedded-palette-on-mono; 16-bit→8-bit high byte).
- The render path: colour → RGB frame; else grayscale window/level; then if a mask is
  present, composite it in the highlight colour onto an RGB copy. No-overlay grayscale
  stays a 1-channel buffer.

The bug was that this logic lived in one backend (`pydicom_2d_backend`) while the live
viewport used another (`lightweight_2d_pipeline`); the fix was to call the **same**
helpers from the active path's frame builder, gated by `AIPACS_FAST_DICOM_EXTRAS`
(default on), with the grayscale hot path untouched. (See §4 — this is the lesson to
carry over.)

Validation that the fix is correct on the real files (so your port has a target): the
extracted masks are exactly **717** lit px (slice-3 annotation), **5546** and **11197**
(the two charts); rendered output matches the reference viewer.

---

## 8. Porting guide

### 8.1 Cornerstone3D / OHIF

**Status of built-in support:** DICOM overlay planes (group 60xx, PS3.3 C.9) are **not**
rendered out of the box — this has been an open request for years
(cornerstoneTools #751, #780; overlay-coordinate bug #902). `cornerstoneWADOImageLoader`
(now **deprecated** in favour of Cornerstone3D / `@cornerstonejs/dicom-image-loader`)
added a metadata provider for group-6000 tags but does **not** composite the overlay into
the displayed image. So you must do it explicitly. Concretely:

1. **Get the overlay + palette metadata.** Parse with `dcmjs`
   (`DicomMessage.readFile` → `DicomMetaDictionary.naturalizeDataset`) or `dicom-parser`.
   Read `OverlayRows/Columns/Type/Origin/Data` for each `60xx` group, and the Palette LUT
   tags. Cornerstone's metadata providers can serve these per `imageId` — register a
   provider that returns an `overlayPlaneModule` (Cornerstone has an
   `overlayPlaneModule` metadata type) and a palette/LUT module.
2. **Colour:** make sure the image loader produces an **RGB** image for PALETTE COLOR /
   embedded-palette / YBR. The standard loaders handle `PALETTE COLOR` and `RGB`/`YBR`,
   but the **embedded-palette-on-MONOCHROME** case (samplesPerPixel 1 + palette LUT) is
   the one they treat as grayscale — detect it in a custom loader/decoder step and apply
   the LUT (§6a) so `image.color === true` with the RGB pixel data. Do **not** let
   VOI/window-level run on colour pixels.
3. **Overlay rendering:** Cornerstone3D renders to WebGL; you cannot just memcpy onto the
   canvas. Two viable approaches:
   - **Annotation/SVG layer:** unpack the 1-bit mask (§6b) and draw it as an overlay in
     the viewport's SVG annotation layer (or a custom `Enabled Element` annotation). This
     is the cleanest for ROI annotations/charts and keeps it above the image with correct
     zoom/pan (Cornerstone applies the viewport transform to the SVG layer).
   - **Bake into the image:** in a custom image loader, after building the pixel array,
     composite the overlay (§6b) into the RGB pixel data so the frame is RGB with the
     graphics painted in. Simplest correctness; loses the ability to toggle the overlay.
   For a **black SC frame**, baking is fine (there's nothing to lose); for an annotation
   over a diagnostic image, prefer the SVG layer so the underlying pixels stay pristine.
4. **Origin/coordinates:** honour `OverlayOrigin` (1-based) — the historical Cornerstone
   overlay tool had an off-by-one/coordinate bug (#902). Map overlay pixel `(r,c)` to
   image pixel `(r-1+originRow-1, c-1+originCol-1)` and then through the viewport
   transform.
5. **OHIF:** implement the above as (a) a metadata provider + custom image-loader decode
   step for colour, and (b) a small **customization / viewport overlay** module (or a
   CornerstoneTools/CS3D annotation) that reads the overlay-plane metadata for the
   displayed `imageId` and draws the mask. Gate it behind a config flag.

> Minimal JS to unpack the overlay mask (LSB-first) once you have the bytes:
> ```js
> function unpackOverlay(bytes, rows, cols) {            // bytes: Uint8Array of (60xx,3000)
>   const n = rows * cols, mask = new Uint8Array(n);
>   for (let i = 0; i < n; i++) mask[i] = (bytes[i >> 3] >> (i & 7)) & 1;
>   return mask;                                          // row-major, image grid
> }
> ```

### 8.2 dwv (DICOM Web Viewer)

dwv parses the full dataset (so the `60xx` elements and palette LUT are available via
`dicomElements`/the parsed tags) and renders to layered `<canvas>` elements (image layer +
draw layer). Approach:

1. **Colour:** dwv's image decoder handles `PALETTE COLOR` and RGB/YBR via the photometric
   interpretation. For **embedded-palette-on-MONOCHROME**, dwv will treat it as
   MONOCHROME → detect the palette LUT tags after parsing and either (a) rewrite the
   in-memory photometric handling to apply the LUT, or (b) post-process the decoded frame
   to RGB using the LUT (§6a) before it's drawn.
2. **Overlay plane:** read `x60003000` (and `x60000010/0011/0040/0050`) from the parsed
   elements, unpack the 1-bit data (§6b / the JS snippet above), and **draw the mask onto
   the draw layer** (or a dedicated overlay canvas) in the highlight colour, applying
   dwv's current zoom/translation so it tracks the image. dwv already composes a separate
   info/draw layer over the image layer (see dwv #483 on rendering the info layer) — add
   the overlay there. For black-SC chart frames, the image layer is black and the overlay
   layer carries the chart.
3. Honour `OverlayOrigin` (1-based) for placement; OR-combine multiple `60xx` groups.
4. Gate behind a flag; leave dwv's normal grayscale/colour rendering unchanged when no
   overlay/palette is present.

### 8.3 Server-side thumbnails (important — separate path)

Thumbnails are usually rendered server-side to PNG/JPEG, independent of the web viewer.
If the server renders only Pixel Data + grayscale W/L, the **chart-slice thumbnail is
black** and an **annotation thumbnail loses its annotation** — same bug, different code.
If your server uses Python/pydicom, reuse the exact §6 algorithm:

```python
import numpy as np, pydicom
from pydicom.overlays.numpy_handler import get_overlay_array
from pydicom.pixel_data_handlers.util import apply_color_lut, convert_color_space

def render_display_rgb(ds, ww=None, wc=None, highlight=(255, 0, 255)):
    arr = ds.pixel_array
    photo = str(getattr(ds, "PhotometricInterpretation", "") or "").upper()
    samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)
    # --- colour ---
    rgb = None
    if samples >= 3 or (arr.ndim == 3 and arr.shape[-1] == 3):
        rgb = convert_color_space(arr, photo, "RGB") if "YBR" in photo else arr
    elif photo.startswith("PALETTE") or ((0x00281201 in ds) and (0x00281101 in ds)):
        rgb = apply_color_lut(arr, ds)
    if rgb is not None:
        rgb = (rgb >> 8).astype(np.uint8) if rgb.max() > 255 else rgb.astype(np.uint8)
        base = np.ascontiguousarray(rgb)
    else:
        # grayscale window/level (your existing logic)
        lo = (wc or 128) - (ww or 256) / 2.0
        g8 = np.clip((arr.astype(np.float32) - lo) / max(ww or 256, 1) * 255, 0, 255).astype(np.uint8)
        base = np.repeat(g8[..., None], 3, axis=2)
    # --- overlay planes ---
    rows, cols = int(ds.Rows), int(ds.Columns)
    mask = None
    for g in range(0x6000, 0x6020, 2):
        if (g, 0x3000) in ds and (g, 0x0010) in ds:
            try:
                ov = (np.asarray(get_overlay_array(ds, g)) != 0).astype(np.uint8)
            except Exception:
                continue
            m = np.zeros((rows, cols), np.uint8)
            r0, c0 = 0, 0
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
    return base  # HxWx3 uint8 → PNG
```

Also fix **which slice is chosen** as the series thumbnail: if the generator picks the
last instance and that's a black SC frame, the thumbnail is black even before overlays —
pick a representative image slice, or render the overlay so the chart shows.

---

## 9. Validation & acceptance checklist

Per target (web viewport, thumbnails, and any export/print path), on patient-46630-class
data:

- [ ] Series opens; all 5 slices load.
- [ ] First 3 slices show the breast image; **slice 3 shows its ROI annotation**.
- [ ] Last 2 slices are **not black** — the mean-curve chart/axes/table is visible.
- [ ] Output matches the reference viewer (content identical; highlight colour may differ).
- [ ] **Embedded-palette series (e.g. TTP/WO maps) render in colour**, not gray.
- [ ] **Thumbnails** for the chart slices are not black; annotation thumbnails show it.
- [ ] **No regression:** ordinary grayscale MR/CT renders exactly as before (same W/L,
      same look) and pays ~no extra cost.
- [ ] Works after drag-and-drop / re-open / scroll through all slices (every render path).
- [ ] Multi-frame, multi-series, and multi-patient still correct (no cross-contamination).
- [ ] Verify on the **actual rendered pixels** (screenshot or pixel sample), not only a
      helper unit test.

Quick automated check (any stack): count highlight-colour pixels in the rendered frame —
for 46630 series 104 expect ≈717 (slice 3), ≈5546 (slice 4), ≈11197 (slice 5); 0 for a
normal grayscale slice.

---

## 10. Pitfalls & gotchas

- **Bit order:** overlay data is packed **LSB-first** within each byte (PS3.5). Unpack
  with `(byte >> (i & 7)) & 1`, not MSB-first. (numpy: `np.packbits/unpackbits(...,
  bitorder='little')`.)
- **Origin is 1-based** `[row, col]` `(60xx,0050)`; subtract 1. Overlay rows/cols can
  differ from the image (place into the image grid, clip to bounds).
- **Don't window/level colour.** Route colour to an RGB path; W/L only applies to
  monochrome.
- **Embedded palette on MONOCHROME is the sneaky one:** `SamplesPerPixel == 1`, so a
  samples-based "is this colour?" test misses it. Check for the palette LUT *tags*.
- **16-bit palette / 16-bit colour:** take the high byte (`>> 8`) to get 8-bit RGB.
- **Black SC detection is generic:** all-zero pixels + overlay present → render overlay.
  Don't gate on vendor `ImageType`/`DerivationDescription` strings (brittle across
  vendors); use them only as a hint if you must.
- **Keep the grayscale hot path byte-identical** and gate the feature; this is what makes
  the change safe to ship in a clinical viewer.
- **Multiple render paths** (viewport, thumbnail, prefetch, print, MPR) — fix/verify each
  (§4). A passing helper test ≠ a fixed screen.
- **Private vendor vector graphics** (e.g. Siemens `MEDCOM OOG`, `0029,xx10`) are
  proprietary — ignore them; the **standard** `60xx` overlay carries the same content.
- **Compressed transfer syntaxes:** 46630 is uncompressed, but in general decode
  JPEG/JPEG2000/RLE Pixel Data first; overlay data is uncompressed regardless.

---

## 11. Appendix — tag & standard reference

**Overlay plane (repeat for groups `6000, 6002, … 601E`):**

| Tag | Name | Notes |
|-----|------|-------|
| `(60xx,0010)` | Overlay Rows | overlay bitmap height |
| `(60xx,0011)` | Overlay Columns | overlay bitmap width |
| `(60xx,0015)` | Number of Frames in Overlay | multi-frame → use frame 0 |
| `(60xx,0040)` | Overlay Type | `G` graphics, `R` ROI |
| `(60xx,0050)` | Overlay Origin | `[row,col]`, **1-based** |
| `(60xx,0100)` | Overlay Bits Allocated | 1 |
| `(60xx,0102)` | Overlay Bit Position | 0 |
| `(60xx,3000)` | Overlay Data | 1bpp, **LSB-first** packed |

**Palette colour LUT:** Descriptors `(0028,1101/1102/1103)`, Data
`(0028,1201/1202/1203)` (R/G/B). Descriptor = `[numEntries, firstMapped, bitsPerEntry]`.

**Colour / photometric:** `(0028,0002)` SamplesPerPixel, `(0028,0004)`
PhotometricInterpretation (`MONOCHROME1/2`, `PALETTE COLOR`, `RGB`, `YBR_FULL`,
`YBR_FULL_422`), `(0028,0006)` PlanarConfiguration.

**DICOM standard:** PS3.3 §C.9 (Overlays), §C.7.6.3 (Image Pixel / photometric &
palette), PS3.5 (overlay/pixel data encoding).

**Useful references:**
- DICOM PS3.3 C.9 Overlays — https://dicom.nema.org/dicom/2013/output/chtml/part03/sect_C.9.html
- Overlay Data attribute (Innolitics browser) — https://dicom.innolitics.com/ciods/cr-image/overlay-plane/60xx3000
- Cornerstone overlay support requests — https://github.com/cornerstonejs/cornerstoneTools/issues/751 , https://github.com/cornerstonejs/cornerstoneTools/issues/780 , https://github.com/cornerstonejs/cornerstoneTools/issues/902
- Cornerstone3D — https://www.cornerstonejs.org/
- dwv — https://github.com/ivmartel/dwv

---

*Origin: AI-PACS desktop fix, 2026-06-17 (patient 46630). Desktop as-built record:
`docs/reports/OVERLAY_RENDER_46630_2026-06-17.md`; related embedded-palette case:
`docs/reports/COLOR_DICOM_46382_2026-06-14.md`.*
