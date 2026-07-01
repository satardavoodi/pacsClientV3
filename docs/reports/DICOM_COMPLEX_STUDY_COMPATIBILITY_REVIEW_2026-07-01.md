# DICOM Compatibility Review — Multi-frame / Cine / Time-based Studies

**Date:** 2026-07-01 **Scope:** Enhanced/multi-frame MR, X-Ray Angiography (XA/XRF),
Ultrasound / echocardiography (incl. color Doppler, B-mode), Ophthalmic photography.
**Goal:** these studies must not fail during grouping, loading, opening, playback, or
display; the viewer must correctly detect SOP Class, modality, NumberOfFrames,
PhotometricInterpretation, transfer syntax, frame timing, and display behavior.

This is the as-built record + staged plan. It grounds each category in the DICOM
standard, states what the FAST viewer already does, what was implemented in this pass,
and what is deliberately deferred (with rationale).

---

## 0. What was changed — as-built manifest (2026-07-01)

**Status:** implemented + unit-tested in the offscreen lane (19 viewer tests green: pure
resolver + player behavioral, real synthetic multi-frame DICOM, wiring pins). Every change is
flag-gated default-on and byte-identical for single-frame series (the whole current store).
NEEDS live source-build verification with a real cine/enhanced series (none exist in the store
yet) — see §6. Requires an app **restart** to take effect.

### New files
- `modules/viewer/fast/cine_metadata.py` — pure (Qt-free) frame-rate resolver. `resolve_frame_rate`
  (DICOM precedence RecommendedDisplayFrameRate → CineRate → 1000/FrameTime → mean(FrameTimeVector)
  → default, clamped 1–60 fps), `playback_fps`, `is_cine`, `clamp_fps`.
- `modules/viewer/fast/cine_player.py` — pure `CinePlayer` state machine (play / pause / stop /
  toggle / advance / step / loop / set_fps / set_count / sync_index / interval_ms). No Qt, no pixels.
- `tests/code/viewer/test_fast_multiframe.py` — multi-frame expansion + header `num_frames` capture
  (real synthetic multi-frame DICOM).
- `tests/code/viewer/test_cine_playback.py` — frame-rate resolver, `CinePlayer` behavior, SOP+timing
  capture, container-wiring source-pins.
- `docs/reports/DICOM_COMPLEX_STUDY_COMPATIBILITY_REVIEW_2026-07-01.md` — this document.

### Modified files
- `modules/viewer/fast/dicom_header_scan.py` — `DicomHeaderEntry` gains `num_frames`,
  `sop_class_uid`, `frame_time_ms`, `cine_rate`, `recommended_display_frame_rate`; `entry_from_dataset`
  captures them (free during the existing `stop_before_pixels` read); `_safe_number_of_frames` helper.
- `modules/viewer/fast/lightweight_2d_pipeline.py` — `SliceMeta` gains `frame_index`, `num_frames`,
  `frame_rate`. `open_series` → `_expand_multiframe_slices` (one `SliceMeta` per frame of a
  `NumberOfFrames>1` file). `_decode_slice` selects `arr[frame_index]` (was `arr[0]`).
  `_decode_cache_key` appends `::f{frame_index}` (per-frame L2 cache). `_sort_slices` orders by
  `frame_index`. New getters `is_cine_series()` + `cine_frame_rate()`. Flag `AIPACS_FAST_MULTIFRAME`.
- `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py` — additive cine engine:
  `_cine_player` + `_cine_timer` members; `toggle_cine` / `start_cine` / `stop_cine` / `_cine_tick` /
  `is_cine_series` / `_cine_frame_rate` methods; a `keyPressEvent` where **Space** toggles playback
  for a cine series and every other key passes through unchanged; timer stopped in `cleanup()`.
  Flag `AIPACS_FAST_CINE`.
- `CLAUDE.md` — guard notes under the FAST multi-frame / cine section.

### Flags
| Flag | Default | Effect |
|---|---|---|
| `AIPACS_FAST_MULTIFRAME` | on | expand `NumberOfFrames>1` into N navigable slices; `=0` = legacy frame-0 only |
| `AIPACS_FAST_CINE` | on | cine playback engine + Space toggle; `=0` = no playback |

### Not changed (already worked / deliberately deferred)
Decode, photometric (MONO/RGB/YBR_FULL_422/PALETTE), compressed transfer syntaxes
(JPEG/JPEG2000/RLE), and per-slice failure resilience were already correct and were left as-is.
Deferred with rationale: enhanced-MR volumetric per-frame geometry, US region calibration, JPEG-LS
codec, XA polarity, and the visible toolbar Play button (§5).

---

## 1. DICOM rules per category (grounded)

**Multi-frame pixel data.** A single DICOM object can hold N frames in one PixelData
element (cine loop, temporal, or 3D/4D). NumberOfFrames (0028,0008) gives N; the frames
are stored consecutively. Frame-order and per-frame attributes are conveyed either by the
classic frame pointers or, for Enhanced objects, by functional-group sequences.
(DICOM PS3.3; dicomstandard.org/concepts.)

**Enhanced MR Image (A.36).** Uses SharedFunctionalGroupsSequence (attributes constant
across frames) + PerFrameFunctionalGroupsSequence (one item per frame). Per-frame geometry
lives in PlanePositionSequence (ImagePositionPatient) / PlaneOrientationSequence; per-frame
timing in FrameContentSequence; per-frame rescale in PixelValueTransformationSequence. The
i-th per-frame item pertains to frame i. (dicom.nema.org sect_A.36; innolitics enhanced-mr-image.)

**X-Ray Angiography (A.14 / XA).** Cine runs are stored as multi-frame, usually MONOCHROME2.
Playback timing from CineRate (0018,0040) or FrameTime (0018,1063). May carry
PixelIntensityRelationship + PixelIntensityRelationshipSign (LOG / inverted) affecting
display polarity. (dicom.nema.org XA IOD.)

**Ultrasound Multi-frame (A.7).** Purpose-built multi-frame IOD. PhotometricInterpretation is
often RGB, YBR_FULL, YBR_FULL_422 (JPEG-lossy color), or PALETTE COLOR; FrameTime for cine
speed; SequenceOfUltrasoundRegions (0018,6011) carries per-region spatial calibration (physical
delta X/Y) and UltrasoundColorDataPresent flags Doppler/flow overlays. YBR_FULL_422 subsamples
Cb/Cr horizontally (2 Y : 1 Cb : 1 Cr) and must be converted to RGB for display.
(dicom.nema.org sect_A.7; innolitics us-image 00280004.)

**Ophthalmic Photography (A.41).** OP SOP classes; single-frame, multi-frame, or cine sequence;
typically RGB. Parse + display like other RGB (multi-)frame objects. (dicom.nema.org sect_A.41.)

---

## 2. Current-state gap matrix (FAST viewer, audited 2026-07-01)

| Dimension | Status before this pass | Notes / file |
|---|---|---|
| MONOCHROME1 / MONOCHROME2 | ✅ handled | `_decode_slice` polarity + storage-bounds invert |
| RGB / YBR_FULL / YBR_FULL_422 | ✅ handled | `dicom_color.py` → pydicom `convert_color_space` |
| PALETTE COLOR / embedded palette | ✅ handled | `apply_color_lut` (gated `AIPACS_DICOM_PALETTE_ON_MONO`) |
| PlanarConfiguration | ✅ implicit via pydicom | RGB de-planarized by pydicom |
| Compressed TS: JPEG baseline / JPEG2000 / RLE | ✅ handled | pylibjpeg + -libjpeg + -openjpeg + -rle in requirements |
| JPEG-LS (.80/.81) | ⚠️ no handler declared | pylibjpeg-libjpeg lacks LS; see §5 |
| Multi-frame (N frames in 1 file) | ❌→✅ FIXED | showed frame 0 only; now expands to N slices |
| NumberOfFrames detection | ❌→✅ FIXED | captured in header scan |
| SOP Class detection | ❌→✅ FIXED | now captured (`sop_class_uid`) |
| Frame timing (CineRate/FrameTime/RecDisplayRate) | ❌→✅ FIXED | captured + resolved to fps |
| Cine playback (play/pause/loop) | ❌→✅ ADDED | additive engine, Space toggle |
| Failure resilience (bad frame → black, no abort) | ✅ robust | per-slice guarded; header scan skips bad files |
| Enhanced-MR per-frame geometry (volumetric) | ❌ deferred | PerFrameFunctionalGroups not read; see §5 |
| US region calibration (measurements) | ❌ deferred | SequenceOfUltrasoundRegions not read; see §5 |

The decode/photometric/transfer-syntax layers were already solid with graceful
per-slice failure — a study never aborts loading because one frame can't decode.

---

## 3. Implemented in this pass (all flag-gated, default-on, single-frame byte-identical)

### 3.1 Multi-frame expansion (viewer shows all N frames)
`modules/viewer/fast/lightweight_2d_pipeline.py` + `dicom_header_scan.py`
(flag `AIPACS_FAST_MULTIFRAME`). A `NumberOfFrames>1` file is expanded into N `SliceMeta`
(same path, distinct `frame_index`); `_decode_slice` selects `arr[frame_index]` (not `arr[0]`);
`_decode_cache_key` appends `::f{k}` so frames don't collide in the L2 cache; `_sort_slices`
keeps frame order. The slider/wheel already range over `slice_count`, so the N frames are
navigable with zero extra wiring. Single-frame series never enter the expansion (byte-identical).

### 3.2 SOP class + cine frame-timing detection
`dicom_header_scan.py` now captures, for free during the existing header read:
`sop_class_uid`, `frame_time_ms` (FrameTime), `cine_rate` (CineRate),
`recommended_display_frame_rate` (RecommendedDisplayFrameRate).
`modules/viewer/fast/cine_metadata.py` (pure) resolves a playback fps by the DICOM precedence
RecommendedDisplayFrameRate → CineRate → 1000/FrameTime → mean(FrameTimeVector) → default,
clamped to [1, 60] fps. The pipeline exposes `is_cine_series()` + `cine_frame_rate()`.

### 3.3 Cine playback engine
`modules/viewer/fast/cine_player.py` (pure `CinePlayer` state machine: play/pause/loop/step/
advance/interval_ms) + an additive engine on `QtFastContainer`
(`vtk_widget/qt_fast_container.py`, flag `AIPACS_FAST_CINE`): a `QTimer` advances frames at the
resolved fps; **Spacebar** toggles play/pause for a cine series; the timer is stopped in
`cleanup()`. Purely additive — new members/methods + a `keyPressEvent` that passes every
non-cine key straight through, so ordinary single-frame series and all existing key behavior
are unchanged. `toggle_cine()` is public so a toolbar Play button can call it (staged, §5).

### 3.4 Tests
`tests/code/viewer/test_fast_multiframe.py` (real synthetic multi-frame DICOM: header captures
N, `arr[k]` selects frame k, + wiring pins) and `tests/code/viewer/test_cine_playback.py`
(pure frame-rate resolver precedence/clamp, `CinePlayer` state-machine behavior, header SOP+timing
capture, container-wiring source-pins). Green in the offscreen lane.

---

## 4. Robustness — "must not fail at any stage"

- **Grouping / enumeration:** a 1-file/N-frame series is counted by frames for display but by
  files on disk for the download/grow logic — the two are tracked separately, so multi-frame
  never mis-drives the grow/disk-count path (disk = 1 file, viewer = N frames; the never-downgrade
  guard keeps N).
- **Loading / opening:** an undecodable frame renders black and is skipped; the series still opens.
  A corrupt file is skipped by the header scan. No single frame aborts the study.
- **Display:** photometric + VOI-LUT + palette paths already cover the common color/mono cases;
  an unknown photometric silently falls back to grayscale W/L rather than raising.
- **Playback:** the cine engine is inert unless the series is a genuine multi-frame cine and the
  user toggles it; the timer is torn down on cleanup/close; every callback is exception-guarded.

---

## 5. Deferred (with rationale) — staged, each flag-gated + live-verified when data exists

1. **Enhanced-MR / volumetric per-frame geometry** (PerFrameFunctionalGroupsSequence →
   per-frame ImagePositionPatient / orientation / rescale). Today all frames of a multi-frame
   file share the first frame's geometry — CORRECT for a temporal cine (US/XA/echo, frames at one
   position), but WRONG for a spatially-varying enhanced MR/CT volume (would mis-stack in 3D /
   mis-measure). Safe fallback today: it displays as a scrollable stack (no crash). The volumetric
   case feeds MPR/3D — a separate geometry task in the lazy-volume path
   (`pydicom_2d_backend.py:456`, `decode_service.py:194` also do `arr[0]`). Needs an enhanced-MR
   sample to validate.
2. **US region calibration** (SequenceOfUltrasoundRegions) for physically-correct measurements on
   ultrasound. Not read today → US measurements use pixel spacing / are uncalibrated. Additive
   metadata read; needs a US sample with regions to validate.
3. **JPEG-LS transfer syntax** (.80/.81). No handler declared. Add `pillow`/gdcm or a JPEG-LS
   plugin, or detect + surface an explicit "unsupported codec" state instead of a black frame.
4. **XA display polarity** (PixelIntensityRelationship LOG / sign) — some angiography needs an
   intensity inversion for conventional display. Modality-aware branch; needs an XA sample.
5. **Toolbar Play/pause + speed control + frame indicator.** The cine engine + `toggle_cine()` are
   in place; a visible toolbar button (and an on-viewport play affordance) is the remaining UI hop,
   staged because the toolbar is a protected surface and there is no multi-frame series in the
   current store to validate against. Spacebar already toggles playback for a focused cine cell.
6. **Cine speed / direction UI** (fps slider, bounce mode) — `CinePlayer` already supports fps and
   could support bounce; expose in the toolbar with #5.

---

## 6. Live-verification checklist (run when a cine/enhanced series is available)

1. Open a multi-frame US/XA/echo series → the viewport shows all N frames (slider ranges 0..N-1),
   not a single image.
2. Press **Space** on the focused cine cell → it plays as a loop at ~the DICOM frame rate; Space
   again pauses. Scroll/slider still steps frames.
3. Color-Doppler US → color frames render (RGB/YBR path), not grayscale-mangled.
4. Confirm ordinary single-frame CT/MR/US series are unchanged (no play control appears; navigation
   identical). Kill switches: `AIPACS_FAST_MULTIFRAME=0`, `AIPACS_FAST_CINE=0`.
5. Check `app.log` for `lw2d-pipeline multiframe-expand files=1 -> slices=N` and
   `[FAST-CINE] play frames=N fps=…`.

---

## 7. Flags summary

| Flag | Default | Effect |
|---|---|---|
| `AIPACS_FAST_MULTIFRAME` | on | expand NumberOfFrames>1 into N slices; `=0` = legacy frame-0 only |
| `AIPACS_FAST_CINE` | on | enable the cine playback engine + Space toggle; `=0` = no playback |

Both only ever activate for a genuine multi-frame file, so the entire current (single-frame)
dataset is byte-identical.

---

## 8. Related fix — previous-exam / multi-study series display + correct grow (2026-07-01)

This is the fix that actually resolved the patient the multi-frame work started from (46281
series 1 "shows one image"). It turned out **not** to be multi-frame — it was a previous-exam
(secondary-study) ultrasound series that displayed only 1 of its N images and never grew. The
same class hit 48476 (series 203 / offset keys 1000001, 3000202) and earlier 48273 / 48296 /
48101 / 48567. Deeper architecture record: `docs/plans/architecture/MULTISTUDY_SERIES_IDENTITY_AND_GROUPING_REVIEW_2026-06-30.md`.

### The symptom
On a patient with a **Previous Exam** (a prior study under a different Patient ID / Study UID,
merged into the open viewer), dragging one of the previous exam's series showed only its first
image — e.g. `[GROW-DISPLAYED] series=1000001 displayed=1 disk=6` in `viewer_diagnostics.log`,
where 6 images were already on disk but the viewport stayed at 1. Live evidence: the series was
opened **mid-download** (first image primed → `open_series slices=1`), the rest arrived, but the
viewport never grew.

### Why a previous exam is special (display keys)
A previous-exam series is keyed in the viewer by an **offset display key**
`study_slot * 1_000_000 + original_series_number` (e.g. `2000602`) so it can coexist with the
current study's same-numbered series. Its files live under its OWN study folder
`SOURCE_PATH/<its_study_uid>/<original_series_number>/`, resolved collision-free via
`_resolve_canonical_series_identity(display_key) → (study_uid, orig_series, series_uid)`.

### Root causes (two reinforcing bugs)
1. **Wrong on-disk count for offset keys.** `_count_series_files_on_disk(series_number)`
   (`_vc_cache.py`) joined the tab's **primary** study path with the bare number. For a
   previous-exam offset key like `2000602` that folder does not exist under the primary study →
   it returned **0**. Every one of the ~13 callers (the same-series no-op grow check, progressive
   grow, load-completion, the backend probe) then believed the series had nothing on disk, so the
   shared decision authority (`decide_display_action`) had nothing to grow and skipped the rebuild.
2. **The grow rebuild was swallowed.** The Stage-A1 watchdog grow
   (`_vc_progressive.py::_maybe_grow_displayed_to_disk`) rebuilt via
   `change_series_on_viewer(display_key, force_reload=False)`, but the same-series no-op
   (`_vc_switch.py`: viewport already shows this key) fired and — compounded by bug 1's disk 0 —
   never rebuilt. The log showed 4 grow attempts with `displayed` never moving.

### Fixes (flag-gated, default-on, single/primary series byte-identical)
- **Canonical disk count at the source** (`AIPACS_DISK_COUNT_CANONICAL`): when the bare
  primary-path join misses AND the key is an offset key (`>= 1_000_000`),
  `_count_series_files_on_disk` resolves canonical identity and counts the series' OWN folder
  `SOURCE_PATH/<study_uid>/<orig_series>`. Strictly additive — ordinary / primary / single-study
  numbers (`< 1_000_000`) never reach the fallback. This one source-level fix makes the whole
  pipeline (same-series no-op, progressive grow, completion) see the true count for a previous-exam
  series, so it grows on every path — not one per-call-site patch.
- **A1 rebuild uses `force_reload=True`**: A1 is the canonical-identity authority that already
  counted the true disk folder and confirmed the folder is SETTLED (stable `.dcm`, no in-flight
  `.part`), so it tells `change_series` to execute the rebuild it decided on, bypassing the
  same-series no-op. SAFE (no re-download): it only fires on a finished folder, so there is no load
  miss to trigger a re-fetch — it re-reads the complete DICOM files into the viewport.

### How a previous exam now displays + grows
- **Display:** the "Previous Exam" button lists prior studies (server-linked by National ID /
  reception); selecting one merges it into the open viewer via the `sanctioned_uids` allow-list
  (so cross-patient isolation is preserved — a foreign study is never auto-merged). Each exam keeps
  its OWN `study_uid` + `patient_id`; disk stays `SOURCE_PATH/<study_uid>/...`.
- **Grow:** dragging a previous-exam series downloads it (metadata-first, images on drag); while it
  downloads or right after, the viewport now grows from its partial stack to the full on-disk count
  because the disk count is correct (canonical) and the A1 watchdog rebuild is no longer swallowed.
- **Isolation preserved:** the enumerated / merged studies are re-validated against the server's
  own `patient_id` at every persist/display sink; the fix only ADDS correct grow behavior keyed on
  canonical identity, it never re-attributes a series across patients/studies.

### Tests + status
`tests/code/viewer/test_disk_count_canonical_offset_key.py`,
`tests/code/viewer/test_grow_displayed_to_disk.py` (pins `force_reload=True`), plus the existing
`test_canonical_disk_complete.py` / `test_resume_settle_requires_awaited_series.py` /
`test_multistudy_per_series_study_pk.py` — green in the offscreen lane.

### Live verification — patient 48695 (2026-07-01) ✅ CONFIRMED
Fresh run logs (`viewer_diagnostics.log` / `download_diagnostics.log`, pid 81164) confirm both fixes
work on real data:
- **Previous exam loads from its own study.** The previous exam (Siemens study `…1107…019`) was keyed
  by the offset display key `1000010` and read from its OWN folder `…/019/10/` (dims 184×256, distinct
  from the primary 512×512) — canonical identity routed it correctly; no cross-patient-skip warnings.
- **Every series grew to its full on-disk count, with `displayed` CLIMBING between attempts** (the
  signature that `force_reload=True` now actually rebuilds instead of being swallowed): primary 302
  29→41→100→147, 303 8→40→147, 175651321 1→36; **previous-exam 1000010 50→144, 2000203 20→70→135**.
- **No series hit the 4-attempt cap still behind** — each settled in 1–3 attempts.
- **Previous-exam download KPIs clean:** series 12→144, 100→144, 101→30, 102→176, 103→140, every one
  `on_disk == expected`, zero retries, TTFI ~60 ms, TTFC 0.6–3.4 s.
- **Zero** `ViewportLoadFailed` / false "slow connection" / "Response too large" / re-download /
  cross-patient-leak markers.

| Flag | Default | Effect |
|---|---|---|
| ~~`AIPACS_DISK_COUNT_CANONICAL`~~ | **COLLAPSED** | canonical on-disk count for offset keys is now UNCONDITIONAL (flag removed after the 48695 live verification — the legacy "return wrong 0" had no valid use) |
| `AIPACS_GROW_DISPLAYED_TO_DISK` | on | watchdog grows a displayed-behind-disk viewport (A1); `=0` = off. Kept as a kill switch for the larger watchdog behavior (next collapse candidate) |

### Smooth grow — anti-hiccup (2026-07-01, `AIPACS_GROW_SMOOTH_APPEND` default on)
User feedback after 48695: as new images downloaded and the series grew, the slice count and
scroll bar **jumped/hiccuped** — the app felt "shocked" by the sudden import. Cause: A1 grew the
viewport with a full `change_series_on_viewer(force_reload=True)` **rebuild** — it invalidated the
decoded-volume cache, re-decoded from disk, and reset the view, so the count and slider snapped in
big discrete jumps (e.g. 29→100→147) with a flicker each time. Fix: A1 now GROWS THE SAME WAY the
native progressive download does — the additive append `vtk_w.image_viewer.grow(force_flush=True)`
(→ `Lightweight2DPipeline.refresh_file_list`, which reads headers for only the NEW files on a
background thread, **preserves the existing SliceMeta + cached pixels**, and keeps the current
slice/view) followed by `_update_vtk_slice_range(...)` to advance the slider count in place. No
re-decode, no flicker, no position reset — the stack simply extends. The full `force_reload` rebuild
remains the FALLBACK for a non-FAST/Advanced viewport (which has no `bridge.grow`) or when the
append doesn't advance. Guard: `test_grow_displayed_to_disk.py` (smooth-append + fallback pins).
NEEDS live source-build verify (grow should now feel continuous, not shocked).

### Post-verification polish (2026-07-01)
After the 48695 confirmation, two safe clean-ups landed:
- **Flag collapse (unify directive):** `AIPACS_DISK_COUNT_CANONICAL` was removed — the canonical
  on-disk count for offset display keys is now the single unconditional path in
  `_count_series_files_on_disk` (`_vc_cache.py`). Ordinary/primary/single-study numbers
  (`< 1_000_000`) still never reach it, so they stay byte-identical.
- **Bounded A1 bookkeeping:** `_maybe_grow_displayed_to_disk` (`_vc_progressive.py`) kept two
  per-`(series, disk-count)` dicts (`_grow_disk_counts`, `_grow_disk_attempts`) that were never
  cleared → a slow per-session leak. They now self-clear past 512 entries; clearing is safe (a
  settled series is never revisited, and at worst a re-grow re-establishes its prev / retries only
  while still behind). A1's dedicated fresh `.dcm`+`.part` scandir is kept intentionally (it needs an
  atomic snapshot for the settle decision that the 1 s TTL-cached shared counter cannot provide).
