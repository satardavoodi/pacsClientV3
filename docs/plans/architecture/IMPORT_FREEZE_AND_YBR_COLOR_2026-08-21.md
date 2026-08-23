# Import freeze + colour-corrupted ultrasound — 2026-08-21

Two unrelated defects reported together against patient **SHUSHLEBIN DMITRY
(PatientID 13996506)**, study `1.2.410.114480.3.2.503247.20260707080007251.1`
(ALPINION E-CUBE i7, Breast US, 1 series, 45 instances, imported
2026-08-21 13:49:30).

| | Symptom | Root cause | Status |
|---|---|---|---|
| **A** | Long UI freeze during import; worse the more local studies exist | Patient-list streamer resolving each row's on-disk path on the GUI thread | Fixed |
| **B** | Image renders as coloured static; other viewers (Myrian) show it fine | pydicom mis-expands mislabelled `YBR_FULL_422` data **and** the viewer never converts YBR→RGB | Fixed |

---

## A. Import freeze — 13.0 s of blocking disk I/O on the GUI thread

### Evidence

`user_data/logs/app.log`, window 2026-08-21 13:45–14:10, main-thread probe
(`aipacs.main_thread_probe._f11_sampler`): **137 `[MAIN_THREAD_STALL_TRACE]`
samples**. The `gap_ms` field climbs monotonically 2 913 → 3 920 → 4 926 →
5 934 → 6 941 → 7 950 → 8 970 → 9 977 → 11 017 → 12 024 → **13 031 ms** between
13:50:03 and 13:50:16 — one uninterrupted 13-second block.

Innermost frame, ranked:

| samples | Σ gap (ms) | frame |
|--------:|-----------:|-------|
| 73 | 168 375 | `pathlib/_local.py :: stat` |
| 31 | 81 271 | `pathlib/_local.py :: iterdir` |
| 10 | 17 443 | `main.py :: notify` |

**104 of 137 samples (76 %) were inside a blocking filesystem call.** Every one
of them was reached through the same stack:

```
patient_table_widget.py:4684  _progressive_render_next
  -> :4706 <lambda>  -> :4717 _progressive_background_step     (122/137 traces)
    -> home_search_service.py:498  render_one                  (104/137 traces)
      -> home_search_service.py:102/127/132  _resolve_renderable_study_path
        -> Path.exists() -> os.stat()          |  utils.py:1658 has_subfolders -> Path.iterdir()
```

### Why it happened

OPT-50 (2026-08-03) had already moved that path resolution off the GUI thread:
the first `_PATHS_HEAD = 60` rows are resolved before first paint, the rest on a
worker future, and `render_one` keeps an **inline fallback** for "a row the
worker has not reached yet". The comment in the source asserted the worker
"comfortably outruns the 40-rows-per-50 ms streamer… the race is harmless by
construction".

Measured on this machine, warm: `_resolve_renderable_study_path` costs
**0.16–0.22 ms/row → 4 500–6 000 rows/s** against the streamer's 800 rows/s. So
in steady state the assertion holds. It does **not** hold during an import: the
worker and the streamer share one disk, which is simultaneously being written by
the importer and re-scanned by on-access AV as the new `.dcm` files land. The
13 s batch rendered 40 rows, i.e. **~325 ms per row** — three orders of
magnitude slower than warm. Once the streamer overtakes the worker, *every*
remaining row pays that cost on the GUI thread; with 2 333 studies in the local
DB (736 study folders on disk) there are thousands of such rows. That is exactly
the reported "the more local studies, the worse the freeze".

### Fix

`PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py`

* `load_progressive(..., ready=None)` — the caller may supply
  `ready(item) -> bool`, "this row can be rendered without touching the disk".
* `_progressive_render_next` gained two guards:
  * **back-pressure** — a row that is not `ready` **ends the batch** (the cursor
    stops on it). The idle timer re-arms, so the stream simply follows the
    worker instead of racing it. No disk I/O ever runs on the GUI thread.
  * **per-batch wall-clock budget** (`_PROGRESSIVE_BUDGET_MS = 30`) — even
    fully-resolved rows build cell widgets, and 40 of those can outlast a frame.
    The batch stops at the budget and resumes on the next tick.
* **Forward-progress escape hatch**: if the stream is continuously deferred for
  `_PROGRESSIVE_DEFER_FORCE_MS` (4 000 ms) — e.g. the resolver future died — it
  force-renders exactly **one** row per batch (paying the inline resolve) so the
  list can never stall permanently.
* A batch that renders nothing no longer rebuilds the "Showing X of Y" label
  (that would repaint at the timer's 20 Hz for no visible change).

`PacsClient/pacs/workstation_ui/home_ui/home_search_service.py`

* `_row_paths_ready(patient)` — one dict membership test, no I/O; passed to
  `load_progressive(ready=…)` only on the off-thread branch.
* **Positive-only path memo** (`_PATH_MEMO`, TTL 300 s, cap 8 000) inside
  `_resolve_renderable_study_path`, so repeated searches stop re-`stat`-ing the
  same folders. **Negatives are deliberately never cached**: the failure mode of
  caching a positive is a row that lingers for at most the TTL after its folder
  is deleted; the failure mode of caching a negative would be a freshly imported
  study that refuses to appear. `clear_path_memo()` is exported for tests and
  bulk deletes.

### Kill switches

| Variable | Default | Effect when `0` |
|---|---|---|
| `AIPACS_LIST_STREAM_BACKPRESSURE` | on | streamer ignores `ready`; pre-fix inline resolve |
| `AIPACS_LIST_STREAM_BUDGET_MS` | `30` | `0` disables the per-batch time cut |
| `AIPACS_LIST_PATH_MEMO` | on | every resolve re-hits the disk |
| `AIPACS_LIST_PATHS_OFFTHREAD` | on | (pre-existing) no worker resolution and no `ready` predicate |

### Guards

`tests/code/ui_services/test_list_stream_backpressure.py` — 17 tests.
**15 of 17 fail against the HEAD sources** (verified by
`tools/analysis/oneoff/verify_backpressure_guard_fails_prefix_2026_08_21.py`,
which swaps in `git show HEAD:` copies and restores them); the 2 that pass are
the pins on unchanged legacy behaviour.

---

## B. Colour-corrupted ultrasound — two stacked defects

### Header of the failing study

```
TransferSyntaxUID          1.2.840.10008.1.2.1   Explicit VR Little Endian (UNCOMPRESSED)
Modality / Manufacturer    US / ALPINION E-CUBE i7
SamplesPerPixel            3        PlanarConfiguration 0
Rows x Columns             768 x 1024
BitsAllocated/Stored/High  8 / 8 / 7     PixelRepresentation 0
WindowCenter / Width       127 / 255
LossyImageCompression      01  (ISO_10918_1) — JPEG once, transcoded to native on the way in
PhotometricInterpretation  YBR_FULL_422  (39 instances) | YBR_FULL (5) | …
len(PixelData)             2 359 296  ==  768 * 1024 * 3      <- FULL rate, NOT subsampled
```

No Modality LUT, no VOI LUT sequence, no Palette Colour LUT, no ICC profile,
single frame. So of the whole property list the only two that matter here are
**PhotometricInterpretation** and the **actual PixelData length**.

### Defect B-1 — pydicom expands 4:2:2 data that was never subsampled

`pydicom 2.4.5 numpy_handler.get_pixeldata()`:

1. `expected_len` = `R*C*3 // 3 * 2` = 1 572 864 (the 4:2:2 assumption).
2. actual = 2 359 296 > expected → emits *"…is a third larger than expected…
   You may need to change the Photometric Interpretation"* — **and continues**.
3. `arr = np.frombuffer(pixel_data[:expected_len], …)` → **truncates the frame
   to two thirds**.
4. Then unconditionally resamples 4:2:2 → 4:4:4 with stride 4 over a period-3
   interleave:
   `out[::6]=arr[::4]`, `out[3::6]=arr[1::4]`, `out[1::6]=out[4::6]=arr[2::4]`,
   `out[2::6]=out[5::6]=arr[3::4]`.

Every output sample becomes a rotating mix of Y/Cb/Cr from *different* pixels.

### Defect B-2 — the viewer never converted YBR to RGB

`lightweight_2d_pipeline._render_frame_uncached` and `_decode_slice`, and
`decode_service._decode_worker`, all took a `samples_per_pixel >= 3` branch that
returned the raw samples straight to `QImage.Format_RGB888`.
`dicom_color.decode_color_for_display` — which *does* know how to convert — was
gated behind `samples_per_pixel < 3` in `_ensure_extras`, so it never ran for a
true colour image.

### Measured: row-to-row correlation of instance 22

A real anatomical frame correlates strongly between adjacent rows; scrambled
samples do not.

| interpretation | correlation | verdict |
|---|---:|---|
| A — `pixel_array` painted as RGB (**what AI-PACS did**) | **−0.355** | noise |
| B — `pixel_array` + YBR→RGB (fixing only B-2) | −0.376 | **still noise** |
| C — raw reshape, no 422 expansion, no convert | 0.930 | image, heavy cyan cast |
| D — raw reshape + YBR→RGB (**the fix**) | 0.931 | correct |

Fixing only the obvious defect (B-2) would have changed nothing visible. Both
corrections are required, in this order.

### Fix

`modules/viewer/fast/dicom_color.py` — two new Qt-free helpers:

* `normalize_ybr_subsampling(ds)` — must run **before** `ds.pixel_array` (pydicom
  caches the mis-decoded array). Rewrites `PhotometricInterpretation` to
  `YBR_FULL` **only** when every one of these holds: colour handling enabled,
  transfer syntax **uncompressed**, photometric exactly `YBR_FULL_422`,
  `SamplesPerPixel == 3`, `BitsAllocated == 8`, and
  `len(PixelData) >= Rows*Columns*3*frames`. A genuinely subsampled 4:2:2 image
  fails the last test and is left alone.
* `ybr_samples_to_rgb(ds, arr)` — runs **after** the decode and converts only if
  the tag *still* says YBR. pydicom rewrites the tag to `RGB` when a codec
  (Pillow/GDCM JPEG) already did the conversion, so reading it post-decode is
  what prevents a compressed colour image from being converted twice.

Wired into both decode paths:

* `modules/viewer/fast/decode_service.py::_decode_worker` (subprocess pool)
* `modules/viewer/fast/lightweight_2d_pipeline.py::_decode_slice` (in-process)

The disk pixel cache is unaffected — it already refuses non-2-D arrays on both
`put` and read, so no colour frame is cached and none can be poisoned.

### Verification

Through the **real** `_decode_worker`, over all 45 instances:

| | instances with correlation > 0.5 | median correlation |
|---|---:|---:|
| kill switches off (pre-fix behaviour) | 5 / 45 | −0.326 |
| fix on | **45 / 45** | **0.934** |

**Regression sweep** — one instance from each of **220 local series**, decoded
twice (fix off / fix on) and compared byte-for-byte:
**219 identical, 1 changed** — and that one is an instance of the failing study
itself. No other study in the 2 333-study local database is affected.

### Kill switches

| Variable | Default | Effect when `0` |
|---|---|---|
| `AIPACS_DICOM_YBR422_FIX` | on | no `YBR_FULL_422` mislabel correction |
| `AIPACS_DICOM_YBR_TO_RGB` | on | multi-sample YBR painted raw, as before |
| `AIPACS_DICOM_COLOR` | on | master switch — disables both of the above |

### Guards

`tests/code/viewer/test_ybr_color_decode.py` — 23 tests.
**19 of 23 fail against the HEAD sources** (verified by
`tools/analysis/oneoff/verify_ybr_guard_fails_prefix_2026_08_21.py`); the 4 that
pass pin behaviour that is correct either way.

---

## Diagnostics produced (all read-only, `tools/analysis/oneoff/`)

| script | what it answers |
|---|---|
| `locate_patient_13996506_2026_08_21.py` | PatientID → patient_pk → study → series → on-disk path |
| `dicom_probe_13996506_2026_08_21.py` | every photometric / pixel-layout tag the report asked about |
| `ybr_repro_13996506_2026_08_21.py` | photometric distribution across all 45 instances |
| `ybr422_truth_2026_08_21.py` | the four candidate interpretations, with correlation + PNGs |
| `ybr422_montage_2026_08_21.py` | the side-by-side A/B/C/D montage |
| `verify_ybr_fix_2026_08_21.py` | all 45 instances through the real decoder, fix on vs off |
| `ybr_fix_regression_sweep_2026_08_21.py` | 220-series byte-identical sweep |
| `import_stall_2026_08_21.py` | ranks the sampled stall frames in the import window |
| `measure_path_resolve_2026_08_21.py` | per-row resolve cost vs streamer demand |
| `prove_progressive_test_prefails_2026_08_21.py` | shows 4 stale guards already failed at HEAD |
| `verify_ybr_guard_fails_prefix_2026_08_21.py` | new colour guards vs HEAD sources |
| `verify_backpressure_guard_fails_prefix_2026_08_21.py` | new streamer guards vs HEAD sources |

## Known-unfixed / follow-ups

1. **Not yet observed live.** Both fixes are verified offline and by test. The
   running app (pid 397556) still carries the old code — a restart is needed to
   see the corrected ultrasound and a clean import.
2. **Thumbnails.** Checked, and *not* as bad as expected: the series thumbnail
   (`user_data/patients/thumbnails/<uid>/0.png`) is instance 0, which is the
   Secondary Capture (`1.2.840.10008.5.1.4.1.1.7`) of the scanner's patient-entry
   form and carries `YBR_FULL` — not the mislabelled `YBR_FULL_422` — so it is
   structurally intact, only colour-shifted (measured mean per-channel error 13.7
   against the correct rendering). It was generated by the pre-fix decoder and is
   **not** regenerated by this change; it will stay slightly off until rebuilt.
   Worth noting separately that this series' first instance is a form screenshot,
   so its thumbnail is that form rather than an ultrasound image — that is the
   data, not a defect.
3. **Other decode consumers** (`modules/printing/render/dicom_renderer.py`,
   `modules/cd_burner/portable_viewer/render.py`,
   `modules/viewer/backends/pydicom_2d_backend.py`) have their own
   `pixel_array` calls and were **not** touched. `cd_burner` already calls
   `convert_color_space`; the other two were not audited.
4. **Compressed YBR** (JPEG-encapsulated ultrasound) is untouched by B-1 by
   design and relies on `ybr_samples_to_rgb`'s post-decode tag check. No such
   study exists in the local DB, so this path is reasoned about, not measured.
5. **Four pre-existing failures** in
   `tests/code/system/test_local_search_progressive.py` are stale pins from a
   June batch-size change (`_PROGRESSIVE_INITIAL_BATCH` is 20, the tests assert
   100/40) and a constant rename (`_LOCAL_SEARCH_BATCH` →
   `_LOCAL_PROGRESSIVE_MIN`). Proved to fail at HEAD; left alone as unrelated.
6. Two further pre-existing failures — `test_login_carries_the_user_identity_ids`
   and `test_status_flags_are_stashed_on_the_widget_to_avoid_recompute` — remain
   from earlier sessions.
